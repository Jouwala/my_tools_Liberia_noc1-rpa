#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
realtime_proxy.py -- VMAX "CXO Dashboard" (ZTE RDK / Awade) configured proxy
Derived from the website-data-snapshot skill template.

AUTH (reverse-engineered from cxo_dashboard.html + portal bundles):
  - Public key: GET  /rdk/service/app/portal/server/loginAuthenticate
                -> JSON {"key":..,"iv":..,"publicKey":"MII..."}
  - Encrypt password with JSEncrypt PKCS#1 v1.5 (NOT OAEP) -> base64
  - Login:  POST /web/res/web-common/login   (application/x-www-form-urlencoded)
            body: username=<u>&password=<enc>&isEncypted=true
            -> {"result":1,"home":"/web/iui/framework/default.html",...}
  - Session cookie: JSESSIONID (auto-managed by cookiejar)
  - CSRF "forgerydefense": read from cookie if present, sent as a header.
  - Data APIs (same-origin, need JSESSIONID):
      /rdk/service/app/insight/realtimeguarantee/ds_dashboard_Overseas/server/
        {Summary,Service,healthView,network}/<endpoint>
"""
import atexit
import base64
import json
import os
import re
import ssl
import threading
import time
import urllib.parse

import http.cookiejar as cookiejar
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, HTTPRedirectHandler, HTTPCookieProcessor, HTTPSHandler
from urllib.error import URLError, HTTPError

# ---- editable config -------------------------------------------------------
PORT = 8790
TARGET_HOST = "https://10.123.255.12:26180"


def _load_cred(key, default_user, default_secret, env_user, env_secret):
    """从 backend.services.credential_store 读取凭据，取不到时回落到内置默认值。

    优先级由 credential_store.get_credential 决定：环境变量 > credentials 表 > 代码默认值。
    """
    import sys
    from pathlib import Path

    here = Path(__file__).resolve()
    for cand in (here.parent, *here.parents):
        svc = cand / "backend" / "services"
        if svc.exists():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            try:
                from backend.services.credential_store import get_credential

                u, s = get_credential(key, default_user, default_secret, env_user, env_secret)
                return u, s
            except Exception as e:  # pragma: no cover
                sys.stderr.write(f"[cred] store load failed for {key}, using default: {e}\n")
            break
    return (
        os.environ.get(env_user, default_user),
        os.environ.get(env_secret, default_secret),
    )
# ---------------------------------------------------------------------------


# ⚠ default_secret 传空串（2026-10-04）：原先这里写的是 vmax_cxo 组的口令明文，
# 既入库（AGENTS.md 四.2），也是 credential_store 的重复副本，无法轮换。
# 现在凭据只从「环境变量 VMAX_CXO_PASS > 凭据库 vmax_cxo 组」取，
# 两处都空时会拿到空口令并让登录**明确失败**，而不是静默用错值。
USER, PASS = _load_cred("vmax_cxo", "ZeeshanM", "", "VMAX_CXO_USER", "VMAX_CXO_PASS")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, "vmax_session.json")

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

CJ = cookiejar.CookieJar()
CSRF = ""
_OPENER = None
_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# 登录节流 / 失败退避（2026-10-04「eFlow 用户数风暴」事故的治本项）
# 事故：上游持续 403 时，ensure_login() 被每个请求触发 → 每次登录都在上游
# 新建一个永不释放的会话 → 会话数暴涨、上游开始拒绝登录 → 更凶的重试。
# 三道闸门见 ensure_login() 的 docstring。均可用环境变量覆盖，便于应急调参。
# ---------------------------------------------------------------------------
def _env_float(name, default):
    """读环境变量为 float；非法值回退默认，避免现场手滑写错导致起不来。"""
    try:
        v = float(os.environ.get(name, "").strip())
        return v if v >= 0 else default
    except (TypeError, ValueError):
        return default


_LOGIN_MIN_INTERVAL = _env_float("PROXY_LOGIN_MIN_INTERVAL", 30.0)   # 成功冷却
_LOGIN_BACKOFF = _env_float("PROXY_LOGIN_BACKOFF", 30.0)             # 退避基数
_LOGIN_BACKOFF_MAX = _env_float("PROXY_LOGIN_BACKOFF_MAX", 600.0)    # 退避上限

# ---------------------------------------------------------------------------
# 上游超时（2026-10-10 分档）。旧版只有 fetch() 里一个硬编码 30s，而两个调用方
# 的客户端超时都比它长（cxo_dashboard_cache 的 _REQ_TIMEOUT=(10,60)、
# vmax_cxo_daily_cache 的 (10,90)）—— 代理先超时就会把"上游还在算"变成
# "代理报错"，调用方再重试，等于给已经很慢的上游加倍流量。
# 分档取值刻意保持**小于**对应调用方的读超时，让超时在离上游近的那一侧发生：
#   普通看板接口 45s < 60s；history 批量明细 75s < 90s。
# 注意：这里的超时**不再触发重新登录**，见 _proxy() 与 _probe_session()。
# ---------------------------------------------------------------------------
_UPSTREAM_TIMEOUT = _env_float("VMAX_PROXY_TIMEOUT", 45.0)
_UPSTREAM_TIMEOUT_HEAVY = _env_float("VMAX_PROXY_TIMEOUT_HEAVY", 75.0)
_HEAVY_PATH_HINTS = ("/query/v2/history",)

_LOGIN_LAST_OK = 0.0
_LOGIN_LAST_FAIL = 0.0
_LOGIN_FAIL_COUNT = 0
# ---------------------------------------------------------------------------


def load_session():
    """从 vmax_session.json 恢复 CookieJar 与 forgerydefense。"""
    global CSRF
    if not os.path.exists(SESSION_FILE):
        return False
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        CJ.clear()
        for c in data.get("cookies", []):
            CJ.set_cookie(
                cookiejar.Cookie(
                    version=0,
                    name=c.get("name"),
                    value=c.get("value"),
                    port=None,
                    port_specified=False,
                    domain=c.get("domain") or "",
                    domain_specified=bool(c.get("domain")),
                    domain_initial_dot=str(c.get("domain") or "").startswith("."),
                    path=c.get("path") or "/",
                    path_specified=True,
                    secure=bool(c.get("secure")),
                    expires=None,
                    discard=True,
                    comment=None,
                    comment_url=None,
                    rest={},
                    rfc2109=False,
                )
            )
        CSRF = data.get("csrf", "") or ""
        return len(list(CJ)) > 0
    except Exception:
        return False


def save_session():
    """把当前 CookieJar 与 forgerydefense 落盘，供下次复用。"""
    cookies = [
        {
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
            "secure": c.secure,
        }
        for c in CJ
    ]
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump({"cookies": cookies, "csrf": CSRF}, f, ensure_ascii=False, indent=2)


def build_opener():
    """构造全局 opener（忽略自签证书 + CookieJar + 不自动跟随重定向）。"""
    global _OPENER
    _OPENER = urllib.request.build_opener(
        HTTPRedirectHandler(), HTTPCookieProcessor(CJ), HTTPSHandler(context=_SSL)
    )
    return _OPENER


def vmax_login():
    """用户名 + JSEncrypt(PKCS#1 v1.5) 加密密码登录。"""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        print("[login] missing dependency: pip install cryptography")
        return False

    sess = _OPENER
    base = TARGET_HOST
    ua = "Mozilla/5.0"

    try:
        r = sess.open(
            Request(
                base + "/rdk/service/app/portal/server/loginAuthenticate",
                headers={"User-Agent": ua, "Accept": "*/*", "Referer": base + "/rdk/app/portal/web/"},
            ),
            timeout=20,
        )
        cfg = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        print("[login] loginAuthenticate failed:", e)
        return False

    try:
        pub_pem = "-----BEGIN PUBLIC KEY-----\n" + cfg["publicKey"] + "\n-----END PUBLIC KEY-----\n"
        pub = serialization.load_pem_public_key(pub_pem.encode())
        enc = base64.b64encode(
            pub.encrypt(PASS.encode("utf-8"), padding.PKCS1v15())
        ).decode()
    except Exception as e:
        print("[login] loginAuthenticate failed:", e)
        return False

    body = urllib.parse.urlencode(
        {"username": USER, "password": enc, "isEncypted": "true"}
    ).encode()

    try:
        req = Request(
            base + "/web/res/web-common/login",
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": ua,
            },
        )
        resp = sess.open(req, timeout=20)
    except HTTPError as e:
        print("[login] login HTTP error:", e.code)
        return False
    except Exception as e:
        print("[login] login error:", e)
        return False

    try:
        j = json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception as e:
        print("[login] login error:", e)
        return False

    if j.get("result") != 1:
        print("[login] FAILED (portal rejected): ", j)
        return False

    global CSRF
    # ⚠ eFlow 的 cookie 名带**端口后缀**（如 `forgerydefense-26180`），
    #   原实现用精确相等匹配裸名，**永远取不到 csrf**，导致后续请求缺 CSRF 头
    #   而被上游拒绝、进而反复重登。2026-10-04 与 realtime_proxy.py 同源缺陷
    #   一起修正：改用前缀匹配，兼容裸名与带后缀名。
    for c in CJ:
        if c.name.lower() == "forgerydefense" \
                or c.name.lower().startswith("forgerydefense-"):
            CSRF = c.value
            break

    print(
        "[login] ok as ",
        USER,
        " (JSESSIONID present=",
        "yes" if len(list(CJ)) else "no",
        ", forgerydefense=",
        "yes" if CSRF else "no",
        ")",
    )
    _activate_dashboard()
    return True


def _activate_dashboard():
    """Run the dashboard's onInit (dbCommonConfig.js). The portal activates the
    Service/Summary ECMA modules only after this call; without it, POSTs such as
    Service/getIndicatorData return 500 'ECMA script format error' even with a
    valid JSESSIONID. Harmless to call on an already-activated session."""
    url = (
        TARGET_HOST
        + "/rdk/service/app/insight/realtimeguarantee/ds_dashboard_Overseas/server/utils/dbCommonConfig.js"
    )
    try:
        _OPENER.open(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20)
        print("[activate] dashboard context loaded", flush=True)
        return True
    except Exception as e:
        print("[activate] note:", e, flush=True)
        return None


def vmax_logout():
    """Free the user's connection on shutdown (portal caps concurrent sessions)."""
    try:
        _OPENER.open(
            Request(
                TARGET_HOST + "/rdk/service/app/portal/server/logout",
                headers={"User-Agent": "Mozilla/5.0"},
            ),
            timeout=10,
        )
        print("[logout] session released", flush=True)
        return True
    except Exception as e:
        print("[logout] note:", e, flush=True)
        return None


def _probe_session():
    """探活上游会话，返回**三态**：True=会话可用 / False=会话确实失效 / None=无从判断。

    The portal's getUserName returns 200 even for a DEAD JSESSIONID, so probing
    it gives a false "session valid" and the proxy then keeps serving 404s for
    every dashboard API call. Instead probe a real dashboard endpoint: a 200
    means the session is live, an explicit HTTP rejection means re-login.

    ⚠ 2026-10-10 由二态改三态。旧版结尾是 `except Exception: return False`，
    于是「上游慢/网络抖动」和「会话已失效」被压成同一件事：判成失效就会调
    `vmax_login()` **新建一个会话**，而本门户是按用户限并发（见 main() 里
    max connections 那句 WARN）的单会话口径 —— 越慢越重登、越重登越挤掉正在
    跑的会话，是正反馈。实测 2026-10-04~09 每天 358~626 次 re-login，触发原因
    全是 `The read operation timed out`，即绝大多数重登是被"慢"误判出来的。

    现在只有明确的 HTTP 拒答（401/403/404/407）才判 False；超时、TLS、拒连、
    上游 5xx 一律返回 None，由调用方保留现有会话不重登。
    """
    url = (
        TARGET_HOST
        + "/rdk/service/app/insight/realtimeguarantee/ds_dashboard_Overseas/server/Service/getIndicatorData"
    )
    body = json.dumps(
        {
            "province_id": "",
            "city_id": "",
            "area_id": "",
            "tabId": 0,
            "infoId": 391,
            "view_id": 2,
        }
    ).encode("utf-8")
    try:
        req = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="POST",
        )
        r = _OPENER.open(req, timeout=_UPSTREAM_TIMEOUT)
        code = r.getcode()
    except HTTPError as e:
        code = e.code
    except Exception:
        # 网络层拿不到状态码 —— 不能据此否定手上的会话
        return None
    if code == 200:
        return True
    if code in (401, 403, 404, 407):
        return False
    return None


def ensure_login(force=False):
    """持锁确保会话可用：先复用磁盘会话，探活失败则重新登录。

    ⚠ 带**节流 / 失败退避**（2026-10-04「eFlow 用户数风暴」事故的治本项）。
    本函数由 `fetch` 处理器在收到 401/403/407 时调用，而每个代理请求都是独立
    触发的。若上游持续拒绝，会形成「403 → 重登 → 又 403 → 又重登」的正反馈，
    每次登录都在上游**新建一个永不释放的会话**，把上游会话数顶爆。

    三道闸门与 tools/realtime_proxy.py 一致：
      1. 成功冷却 `_LOGIN_MIN_INTERVAL`：冷却期内即使被拒也不重登；
      2. 失败退避 `_LOGIN_BACKOFF`：失败后指数增长窗口内一律不再尝试；
      3. `_LOCK` 串行化，并发触发最多换 1 次真实登录。

    Args:
        force: True 时跳过节流（仅用于进程启动时的首次登录）。
    """
    global _LOGIN_LAST_OK, _LOGIN_LAST_FAIL, _LOGIN_FAIL_COUNT
    with _LOCK:
        now = time.time()

        # 闸门 2：失败退避中 —— 不触网，直接返回"不可用"
        if _LOGIN_FAIL_COUNT > 0 and not force:
            wait = min(
                _LOGIN_BACKOFF * (2 ** (_LOGIN_FAIL_COUNT - 1)),
                _LOGIN_BACKOFF_MAX,
            )
            elapsed = now - _LOGIN_LAST_FAIL
            if elapsed < wait:
                print(
                    f"[auth] backoff: skip login "
                    f"(failed {_LOGIN_FAIL_COUNT}x, {wait - elapsed:.0f}s left)",
                    flush=True,
                )
                return False

        # 闸门 1：成功冷却期内 —— 直接复用，不重登
        if _LOGIN_LAST_OK and not force \
                and (now - _LOGIN_LAST_OK) < _LOGIN_MIN_INTERVAL:
            print(
                f"[auth] throttle: reuse session "
                f"({now - _LOGIN_LAST_OK:.0f}s < {_LOGIN_MIN_INTERVAL}s)",
                flush=True,
            )
            return bool(len(CJ))  # 有 Cookie 即认为可复用

        if load_session():
            probe = _probe_session()
            if probe is True:
                _activate_dashboard()
                _LOGIN_LAST_OK = time.time()
                _LOGIN_FAIL_COUNT = 0
                return True
            if probe is None:
                # 上游慢/不可达，但手上的会话**没有被否定** —— 保留会话、不重登，
                # 让这一次请求按正常路径去撞上游（成功就用，超时就让调用方超时）。
                # 在这里重登的代价是：单会话门户会把可能正在跑的另一个会话挤掉，
                # 把一次"慢"放大成一片 502。见 _probe_session() 的三态说明。
                print(
                    "[auth] probe unknown (upstream slow/unreachable?) "
                    "-- keep current session, no re-login",
                    flush=True,
                )
                return bool(len(CJ))
            # probe is False：明确的 401/403/404/407，会话确实失效，继续重新登录

        if vmax_login():
            save_session()
            _LOGIN_LAST_OK = time.time()
            _LOGIN_FAIL_COUNT = 0
            return True

        # 登录失败：记一次失败并进入退避
        _LOGIN_FAIL_COUNT += 1
        _LOGIN_LAST_FAIL = time.time()
        print(f"[auth] login failed ({_LOGIN_FAIL_COUNT}x) -- entering backoff", flush=True)
        return False


def fetch(target_url, method="GET", body=None):
    """向 TARGET_HOST 发请求，带上 CSRF 头；返回 (status, resp)。

    超时按端点分档（见 _UPSTREAM_TIMEOUT / _UPSTREAM_TIMEOUT_HEAVY 处的注释）：
    history 批量明细给宽，其余看板接口保持比调用方更短，避免代理先超时引发
    调用方重试、把流量翻倍压到已经很慢的上游。
    """
    timeout = _UPSTREAM_TIMEOUT
    if any(h in target_url for h in _HEAVY_PATH_HINTS):
        timeout = _UPSTREAM_TIMEOUT_HEAVY
    req = Request(
        target_url,
        data=body.encode("utf-8") if isinstance(body, str) else body,
        method=method.upper(),
    )
    req.add_header("Origin", TARGET_HOST)
    req.add_header("Referer", TARGET_HOST + "/")
    if CSRF:
        req.add_header("forgerydefense", CSRF)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    resp = _OPENER.open(req, timeout=timeout)
    return resp.getcode(), resp


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/health"):
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            # ⚠ 判据不能用 `bool(CSRF)`：本门户（10.123.255.12:26180）实测
            #   **只签发 JSESSIONID，从不签发 forgerydefense**，所以 CSRF 恒为空，
            #   原判据会让登录成功后 auth 仍永久显示 false，误导排障
            #   （2026-10-04 实测：vmax_login() 返回 True、fetch 可用，但 auth=false）。
            #   改为「有会话 Cookie 且有 CSRF 头则算带 CSRF；仅凭 Cookie 也算已鉴权」。
            ok = len(list(CJ)) > 0
            self.wfile.write(
                json.dumps(
                    {
                        "status": "ok",
                        "proxy": "ready",
                        "auth": ok,
                        "csrf": bool(CSRF),
                        "user": USER,
                    }
                ).encode()
            )
            return
        if self.path.startswith("/proxy"):
            return self._proxy()
        self.send_response(404)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path.startswith("/proxy"):
            return self._proxy()
        self.send_response(404)
        self.end_headers()

    def _proxy(self):
        qs = urllib.parse.urlparse(self.path).query
        args = urllib.parse.parse_qs(qs)
        target = (args.get("url") or [""])[0]
        if not target.startswith(TARGET_HOST):
            self.send_response(400)
            self._cors()
            self.end_headers()
            self.wfile.write(b"only TARGET_HOST is allowed")
            return

        method = (args.get("method") or [self.command])[0].upper()
        body = (args.get("body") or [""])[0]
        ln = int(self.headers.get("Content-Length") or 0)
        if ln:
            body = self.rfile.read(ln).decode("utf-8", "ignore")

        # status/payload 必须**先绑定**：下面的 except 分支（网络异常）拿不到
        # HTTP 状态码，而循环末尾与失败分支都要用它们。2026-10-04 修复
        # UnboundLocalError（之前 except Exception 路径从未给 status 赋值，
        # 一旦上游不可达就抛 UnboundLocalError，把 502 变成 500 堆栈）。
        status = 0
        payload = b""

        for _ in range(2):
            try:
                status, resp = fetch(target, method, body if method == "POST" else None)
                payload = resp.read()
                if status == 200:
                    self.send_response(200)
                    self._cors()
                    ct = resp.headers.get("Content-Type") or "application/json"
                    self.send_header("Content-Type", ct)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    # 调用方（浏览器/后端）常在上游变慢时先断开，写完才发现连接
                    # 已没 —— 那是**客户端**的超时，不是代理故障。旧版让它冒到
                    # socketserver.handle_error，每次打一整页 ConnectionAbortedError
                    # 堆栈（今天 12:11 那份日志 5 次），把真故障埋在噪音里。
                    try:
                        self.wfile.write(payload)
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                        print("[proxy] client aborted before write, upstream was 200", flush=True)
                    return
                session_rejected = status in (401, 407, 403)
            except HTTPError as e:
                status = e.code
                payload = e.read()
                session_rejected = status in (401, 407, 403)
            except Exception as e:
                # 网络层异常（读超时/TLS/拒连）**不是**会话失效，绝不触发重登。
                # 旧版在这里置 session_rejected=True → 每一次上游读超时都会变成
                # 一次真实登录，而本门户按用户限并发，重登会把正在跑的会话挤掉
                # （2026-10-10 复盘：10-04~09 每天 358~626 次 re-login 全部由
                # read timeout 引发，是"越慢越重登、越重登越坏"的正反馈）。
                # 现在直接回 504 让调用方按自己的超时处置；调用方要么已有
                # last-known-good 兜底，要么下一轮重取（本代理的会话状态没被动过）。
                print("[proxy] upstream network error, NO re-login:", e, flush=True)
                self.send_response(504)
                self._cors()
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            if session_rejected:
                print("[proxy] session rejected (", status, "), re-login", flush=True)
                if ensure_login():
                    continue
                self.send_response(502)
                self._cors()
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", "0")
                self.end_headers()
                self.wfile.write(b"login failed (portal connection limit?)")
                return
            break

        print("[proxy] upstream ", status, " for ", target[:160], " -> ", len(payload), flush=True)
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # 同上：调用方先撤，不代表上游返回有问题，status 已经打印过了
            pass

    def log_message(self, *a):
        pass


def main():
    import atexit

    _OPENER_INIT = build_opener()
    # force=True：进程启动时的首次登录是**有意为之**的，不应被节流拦下
    ok = ensure_login(force=True)
    if ok:
        save_session()
        atexit.register(vmax_logout)
    else:
        print(
            "[proxy] WARN: login failed -- the dashboard will get 502/empty data. "
            "Usually this is the portal's per-user concurrent-session cap "
            "('max connections for the user is reached'). Free a slot by logging "
            "the account out of other sessions, then restart.",
            flush=True,
        )
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(
        "[proxy] listening on http://127.0.0.1:",
        PORT,
        "  target=",
        TARGET_HOST,
        "  auth=",
        ok,
        flush=True,
    )
    srv.serve_forever()


if __name__ == "__main__":
    main()

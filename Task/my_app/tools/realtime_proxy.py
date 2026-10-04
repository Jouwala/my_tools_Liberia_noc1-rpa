#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
realtime_proxy.py — 本地实时代理（v4）
目标：
  - 保留原有“用户名 + RSA 加密密码”的 FMS 登录方式
  - 自动从当前 API URL 生成 OAuth2 redirect_uri
  - 同时支持 alarmstatistics-service / eflow-configcenter 等多个业务 API
  - 会话失效自动重新登录并重试
  - 正确保留 OAuth 登录过程中的 Cookie
  - API 请求遇到 302/401/403/406/407 时按鉴权失效处理
  - 支持 GET / POST
  - 自动追加 csrftoken
  - CORS
  - 仅允许 TARGET_HOST，避免开放代理
  - 更详细的日志，便于定位上游问题

用法：
  python realtime_proxy_v4.py

页面：
  fetch('http://127.0.0.1:8787/proxy?url=' + encodeURIComponent(API_URL))

说明：
  登录方式未改变：
    1. authorize 获取 loginParameters
    2. publickey 获取 RSA 公钥
    3. RSA-OAEP(SHA-256) 加密密码
    4. POST /api/oauth2/v1/login_rsa
    5. 保存 Cookie + forgerydefense
"""
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
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPCookieProcessor, HTTPSHandler
from urllib.error import URLError, HTTPError

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key

# ---- editable config -------------------------------------------------------
PORT = 8787
TARGET_HOST = "https://10.100.20.8:28001"


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


USER, PASS = _load_cred("fms_portal", "admin", "Brysj*8*", "FMS_PORTAL_USER", "FMS_PORTAL_PASS")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, "fms_session.json")

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

_LOCK = threading.RLock()
_SESSION = {"cookie": "", "csrf": ""}

# 共享会话**结构性**不可用标记（import/路径问题）。会话失效不算，见 _try_adopt_shared()
_SHARED_BROKEN = False

# ---------------------------------------------------------------------------
# 登录节流 / 失败退避（2026-10-04「eFlow 用户数风暴」事故的治本项）
#
# 背景：本代理每个上游 403 都会触发一次 refresh_session()，而上游每次登录都会
# 新建一个**永不释放**的服务端会话。会话文件缺失 + 登录被拒时形成正反馈：
#   403 → 登录 → csrf 取不到 → 会话没更新 → 又 403 → …（实测 3822 次/天）
# 因此登录必须被节流，且失败后必须退避，否则 my_app 的重试会打死上游。
#
# 三个常量都可用环境变量覆盖，便于现场应急调参而不改代码。
# ---------------------------------------------------------------------------

def _env_float(name, default):
    """读环境变量为 float；非法值回退默认，避免现场手滑写错导致起不来。"""
    try:
        v = float(os.environ.get(name, "").strip())
        return v if v >= 0 else default
    except (TypeError, ValueError):
        return default


# 成功登录后的冷却期（秒）：期间即使收到 403 也只复用现有会话，不再登录。
# 默认 30s —— 足以吸收前端并发刷新，又不至于让真失效的会话卡太久。
_LOGIN_MIN_INTERVAL = _env_float("PROXY_LOGIN_MIN_INTERVAL", 30.0)

# 失败退避基数（秒）：第 1 次失败等 1×，第 2 次 2×，第 3 次 4× …… 指数增长。
_LOGIN_BACKOFF = _env_float("PROXY_LOGIN_BACKOFF", 30.0)

# 退避上限（秒）：防止退避窗口无限增长导致永远不再尝试。
_LOGIN_BACKOFF_MAX = _env_float("PROXY_LOGIN_BACKOFF_MAX", 600.0)

# 运行时状态（受 _LOCK 保护）
_LOGIN_LAST_OK = 0.0        # 上次**成功**登录的时刻（0 = 从未成功）
_LOGIN_LAST_FAIL = 0.0      # 上次**失败**登录的时刻
_LOGIN_FAIL_COUNT = 0       # 连续失败次数（成功后清零）
# ---------------------------------------------------------------------------


class NoRedirectHandler(HTTPRedirectHandler):
    """API 请求不自动跟随 301/302/303/307/308，方便正确识别鉴权跳转。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_COOKIE_JAR = cookiejar.CookieJar()
_OPENER = build_opener(
    NoRedirectHandler(),
    HTTPCookieProcessor(_COOKIE_JAR),
    HTTPSHandler(context=_SSL),
)


def load_session():
    """从 fms_session.json 读取 cookie / csrf。

    ⚠ 本文件是**本代理私有**的会话快照，与 `auth_manager` 的
    `backend/services/auth_cache/<host>_<port>.json` **是两份独立的存储**。
    因此 `AUTH_TOKEN_TTL` 对本文件**不生效** —— 这是 2026-10-04
    「TTL 配了 1440 分钟却仍在频繁登录」的原因之一。

    真正的共享靠 `adopt_shared_session()`：它优先去读 auth_manager 的缓存，
    让本代理与所有 worker 共用同一个 token（用户最初的要求就是这个）。
    """
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            _SESSION["cookie"] = obj.get("cookie", "") or ""
            _SESSION["csrf"] = obj.get("csrf", "") or ""
            print(
                "[proxy] session loaded: cookie=",
                "yes" if _SESSION["cookie"] else "no",
                ", csrf=",
                "yes" if _SESSION["csrf"] else "no",
            )
    except Exception as e:
        print("[proxy] no valid session file: ", e)
    return _SESSION["cookie"], _SESSION["csrf"]


def adopt_shared_session():
    """优先复用 `auth_manager` 的**跨进程共享** eFlow 会话。

    这是「eFlow 登录要用已经获取的 token，不要每个任务申请一次」这条要求的落地：
    worker（sp_online_sync 等）与其它进程都通过 auth_manager 读写同一份
    `auth_cache`，本代理接入它之后，**全项目只有一个 token 来源**，
    避免"代理自己登录一份、worker 又登录一份"地把上游会话数顶上去。

    返回 True 表示成功拿到共享会话并已写入本进程；False 表示拿不到
    （缓存不存在/已过期/模块不可用），调用方应回退到自己的登录流程。

    ⚠ **必须验证会话真的可用，不能只信 TTL**（2026-10-04 踩坑）：
    `auth_manager` 只按 `expires_in` 判过期，而 eFlow 可能**提前**作废会话
    （实测：缓存里 created_at 才 10 分钟、TTL 86400，但请求返回
     401 {"hasLogged":true,"source":"smagent",...}）。
    早期版本直接采纳这个"看着有效其实已死"的会话，导致 `refresh_session()`
    把死会话又还给调用方 → 重试仍 401 → 502，**比不接共享还糟**。
    因此这里**先探活**：拿一个轻量 API 验一次，通过才采纳。

    注意：**失败不抛异常**。代理必须能独立启动 —— 若 auth_manager 不可用，
    本代理仍应能靠 `load_session()` + `do_login()` 自给自足。
    """
    try:
        import sys as _sys
        from pathlib import Path as _Path

        here = _Path(__file__).resolve()
        for cand in (here.parent, *here.parents):
            if (cand / "backend" / "services" / "auth_manager.py").exists():
                if str(cand) not in _sys.path:
                    _sys.path.insert(0, str(cand))
                break
        else:
            return False

        from backend.services.auth_manager import get_auth

        # 从 TARGET_HOST 解析出 host/port，**不另建一份常量**（避免两个真相源）。
        _p = urllib.parse.urlsplit(TARGET_HOST)
        _host, _port = _p.hostname, (_p.port or 443)

        # force_refresh=False（默认）：**只读缓存**，缓存有效就绝不触网登录。
        # 这正是关键 —— 代理启动不该触发一次真实登录。
        auth = get_auth(_host, _port, USER, PASS)
        cookie = auth.get("cookie", "")
        csrf = auth.get("forgery_token", "")
        if not cookie:
            return False

        # ★ 关键一步：拿一个**轻量只读** API 验证会话是否真的还活着。
        # 为什么不能省：`get_auth()` 只按 TTL 判过期，eFlow 却可能提前作废。
        # 不验证就采纳 = 把一个死会话当成"刷新成功"还给调用方，
        # 调用方重试仍 401，最终 502（这正是本函数早期版本的 bug）。
        if not _probe_session_alive(cookie, csrf):
            print("[proxy] shared session is stale (probe failed); will self-login")
            return False

        _SESSION["cookie"] = cookie
        _SESSION["csrf"] = csrf
        save_session(cookie, csrf)  # 同步到本代理私有快照，便于离线诊断
        print(
            "[proxy] shared session adopted from auth_manager: "
            f"cookie=yes, csrf={'yes' if csrf else 'no'}, "
            f"from_cache={auth.get('from_cache')}, probe=ok"
        )
        return True
    except Exception as e:
        print(f"[proxy] shared session unavailable ({type(e).__name__}: {e}); will self-login")
        return False


# 探活用的轻量 API（只读、不产生副作用、上游返回小）。
# 选 getConfigCenterSiteTypeList 而不是看板 API：后者可能很慢，探活不该拖慢启动。
_PROBE_PATH = ("/api/alarmstatistics-service/v1/levelregion/"
               "getConfigCenterSiteTypeList?sitetype=ALL")


def _probe_session_alive(cookie, csrf):
    """用一次轻量请求判断会话是否真的可用。返回 True=可用。

    判据是**响应状态码 200**，而不是响应体内容 —— 我们要回答的只是
    "这个会话还能不能取数"，业务内容对探活无关。
    """
    if not cookie:
        return False
    try:
        url = normalize_target_url(TARGET_HOST + _PROBE_PATH)
    except Exception:
        return False

    hdrs = {"Cookie": cookie, "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": TARGET_HOST + "/uportal/framework/default.html"}
    if csrf:
        hdrs["forgerydefense"] = csrf
    try:
        req = Request(url, headers=hdrs, method="GET")
        with _OPENER.open(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except HTTPError as e:
        # 401/403 = 会话确实失效，这是探活要抓的主要情况
        if e.code in (401, 403):
            return False
        # 其它 4xx/5xx 不能断定会话有问题（可能是探活 API 本身变了），
        # 保守起见当作"不可用"，让调用方走自己的登录流程（更安全）。
        return False
    except Exception as e:
        # 打印真实原因：静默 return False 会让"探活恒失败"无法定位
        # （2026-10-04 踩过 —— 探活恒 False 导致共享会话从未被采纳）。
        print(f"[proxy] probe failed: {type(e).__name__}: {e}")
        return False


def _try_adopt_shared():
    """轻量包装 `adopt_shared_session()`，供热路径调用（带失败缓存）。

    ⚠ 只缓存**"模块不可用"**这种真失败，**不缓存"会话暂时失效"**。
    早期版本把"探活失败"也记成不可用，于是**一次失效就永久关闭共享**，
    之后每次都自己登录 —— 反而加剧了登录风暴。会话失效是**可恢复的正常状态**
    （下次别的进程登录后缓存就新了），必须允许重试。
    """
    global _SHARED_BROKEN
    if _SHARED_BROKEN:
        return False
    try:
        return adopt_shared_session()
    except Exception as e:
        # 只有 import/路径这类"结构性"错误才永久关闭；会话问题上面已返回 False
        print(f"[proxy] shared session disabled for this run ({type(e).__name__}: {e})")
        _SHARED_BROKEN = True
        return False


def save_session(cookie, csrf):
    """原子写盘：先写 .tmp 再 os.replace，避免半截 JSON。"""
    tmp = SESSION_FILE + ".tmp"
    data = {"cookie": cookie or "", "csrf": csrf or ""}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SESSION_FILE)


def normalize_target_url(url):
    """
    校验并规范目标 URL。
    只允许 TARGET_HOST 下的 HTTPS API。
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("only HTTPS target is allowed")
    if not parsed.netloc or TARGET_HOST.split("//", 1)[-1] not in parsed.netloc:
        raise ValueError("url must target " + TARGET_HOST)
    if not parsed.path.startswith("/api/"):
        raise ValueError("only /api/ URLs are allowed")
    return url


def get_redirect_uri(api_url):
    """
    OAuth2 redirect_uri 使用当前 API 的 path + query。
    例如：
      /api/eflow-configcenter/v1/.../rule/list
    """
    p = urllib.parse.urlsplit(api_url)
    redirect_uri = p.path or "/"
    if p.query:
        redirect_uri += "?" + p.query
    return redirect_uri


def build_authorize_url(api_url):
    """构造 /api/oauth2/v1/authorize?... 登录入口 URL。"""
    redirect_uri = get_redirect_uri(api_url)
    params = urllib.parse.urlencode(
        {
            "scope": "user.login",
            "response_type": "code",
            "redirect_uri": redirect_uri,
        }
    )
    return TARGET_HOST + "/api/oauth2/v1/authorize?" + params


def _request(url, data=None, headers=None, method="GET", timeout=25, follow_redirects=False):
    """统一请求入口；默认不跟随重定向（便于识别鉴权跳转）。"""
    req = Request(url, data=data, headers=headers or {}, method=method)
    opener = _OPENER
    if follow_redirects:
        opener = build_opener(
            HTTPCookieProcessor(_COOKIE_JAR), HTTPSHandler(context=_SSL)
        )
    return opener.open(req, timeout=timeout)


def _read_response(resp):
    """读取响应体并推断 Content-Type。"""
    body = resp.read()
    ctype = resp.headers.get("Content-Type", "application/json")
    return body, ctype


def _extract_login_parameters(text):
    """
    兼容：
      loginParameters = "xxx"
      loginParameters="xxx"
      var loginParameters = "xxx"
    """
    patterns = [
        r'loginParameters\s*=\s*"([^"]+)"',
        r"loginParameters\s*=\s*'([^']+)'",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    return ""


def _build_public_key(pub):
    """把裸 base64 的 RSA 公钥补成 PEM 并加载（每 64 字符折行）。"""
    pem_body = re.sub(r"\s+", "", pub)
    pem = (
        "-----BEGIN PUBLIC KEY-----\n"
        + "\n".join(pem_body[i : i + 64] for i in range(0, len(pem_body), 64))
        + "\n-----END PUBLIC KEY-----"
    )
    return load_pem_public_key(pem.encode())


def _cookie_header_from_jar():
    """把 CookieJar 拼成 Cookie 请求头。"""
    cookies = []
    for c in _COOKIE_JAR:
        cookies.append(c.name + "=" + c.value)
    return "; ".join(cookies)


def do_login(api_url):
    """
    保留原有用户名 + RSA 加密密码登录方式。

    与 v3 的主要区别：
      - redirect_uri 根据当前 API 动态生成
      - 登录过程使用 CookieJar，避免 authorize 设置的 Cookie 丢失
      - 不依赖 urllib 自动跟随 302
    """
    redirect_uri = get_redirect_uri(api_url)
    auth_url = build_authorize_url(api_url)
    print("[auth] login start")
    print("[auth] redirect_uri=", redirect_uri)

    _COOKIE_JAR.clear()
    common_headers = {"User-Agent": _UA, "Accept": "*/*"}

    # 1) authorize：期望 302 跳登录页，从 login page 里取 loginParameters
    try:
        r = _request(auth_url, headers=common_headers, method="GET", timeout=20, follow_redirects=False)
        raw = r.read()
        status = r.status
        location = r.headers.get("Location", "")
    except HTTPError as e:
        raw = e.read()
        status = e.code
        location = e.headers.get("Location", "")
    except Exception as e:
        raise RuntimeError("authorize failed: " + str(e))

    if status not in (200, 301, 302, 303, 307, 308):
        raise RuntimeError("authorize HTTP " + str(status) + ": " + location)

    text = raw.decode("utf-8", "ignore")
    login_parameters = _extract_login_parameters(text)
    loc = location or ""

    if not login_parameters and loc:
        if not loc.startswith("http"):
            loc = urllib.parse.urljoin(TARGET_HOST, loc)
        print("[auth] authorize redirect -> login page")
        login_text = ""
        try:
            lr = _request(loc, headers=common_headers, method="GET", timeout=20, follow_redirects=False)
            login_text = lr.read().decode("utf-8", "ignore")
        except HTTPError as e:
            login_text = e.read().decode("utf-8", "ignore")
            print("login page HTTP ", e.code)
        except Exception as e:
            print("login page HTTP ", e)

        login_parameters = _extract_login_parameters(login_text)

    if not login_parameters:
        raise RuntimeError(
            "loginParameters not found; authorize HTTP=" + str(status) + ", location=" + loc
        )
    print("[auth] loginParameters len=", len(login_parameters))

    # 2) publickey：拿 RSA 公钥
    try:
        pr = _request(
            TARGET_HOST + "/api/oauth2/v1/login/publickey",
            headers=common_headers,
            method="GET",
            timeout=20,
            follow_redirects=False,
        )
        praw = pr.read()
        if pr.status != 200:
            print("publickey HTTP ", pr.status)
    except HTTPError as e:
        raise RuntimeError("publickey HTTP " + str(e.code))

    try:
        pj = json.loads(praw.decode("utf-8", "ignore"))
        pub = pj["rsaPublicKey"]
    except Exception as e:
        raise RuntimeError("invalid publickey response: " + str(e))
    if not pub:
        raise RuntimeError("rsaPublicKey missing")
    print("[auth] publickey len=", len(pub))

    # 3) RSA-OAEP(SHA-256) 加密密码 + 4) login_rsa
    key = _build_public_key(pub)
    enc_pwd = base64.b64encode(
        key.encrypt(
            PASS.encode(),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
    ).decode()

    body = json.dumps(
        {"username": USER, "password": enc_pwd, "parameters": login_parameters},
        ensure_ascii=False,
    ).encode()

    login_headers = {
        "User-Agent": _UA,
        "Accept": "*/*",
        "language-option": "en_US",
        "Content-Type": "application/json; charset=utf-8",
        "Origin": TARGET_HOST,
        "Referer": TARGET_HOST + "/",
    }

    try:
        lr2 = _request(
            TARGET_HOST + "/api/oauth2/v1/login_rsa",
            data=body,
            headers=login_headers,
            method="POST",
            timeout=25,
            follow_redirects=False,
        )
        raw2 = lr2.read()
        status2 = lr2.status
        set_cookie = lr2.headers.get("Set-Cookie", "") or ""
    except HTTPError as e:
        raw2 = e.read()
        status2 = e.code
        set_cookie = e.headers.get("Set-Cookie", "") or ""

    # 取 csrf（forgerydefense）。
    # ⚠ eFlow 的 cookie 名带**端口后缀**，实测为 `forgerydefense-28001`，
    #   而不是裸 `forgerydefense`。原实现用 `c.name == "forgerydefense"` 精确匹配，
    #   因此**永远取不到 csrf** → do_login() 恒定返回 ("", "") → 会话永不生效
    #   → 每个请求 403 → 再次登录。这是 2026-10-04「eFlow 用户数风暴」的
    #   真正触发缺陷（与下面 result 判据是同一段逻辑上的两个独立错误）。
    #   改用前缀匹配，兼容裸名与带后缀名。
    csrf = ""
    for c in _COOKIE_JAR:
        if c.name == "forgerydefense" or c.name.startswith("forgerydefense-"):
            csrf = c.value
            break
    if not csrf and set_cookie:
        for part in set_cookie.split(","):
            for seg in part.split(";"):
                seg = seg.strip()
                if seg.lower().startswith("forgerydefense"):
                    csrf = seg.split("=", 1)[1]
                    if csrf == "deleted":
                        csrf = ""

    if status2 and status2 >= 300:
        print("login_rsa HTTP ", status2)

    cookie = _cookie_header_from_jar()

    # ------------------------------------------------------------------
    # 登录成功判据（2026-10-04 修正）
    #
    # 原判据是「响应体含 "result":"1"」，但**这版 eFlow 的 login_rsa 恒返回
    # "result":"0"**，同时正常签发 Z-AUTH-CODE / forgerydefense / x-dexmesh-user。
    # 实测：全部历史日志里 "result":"1" 出现 **0 次**，"result":"0" 出现 2422 次；
    # 而同一时刻 backend.services.auth_manager（只认 Z-AUTH-CODE）登录**成功**。
    # 也就是说登录一直是成功的，是这里判错了 —— 会话因此永不生效，每个请求
    # 都 403 并再次触发登录，这正是 2026-10-04「eFlow 用户数风暴」的核心缺陷。
    #
    # 新判据与 auth_manager 对齐：**拿到会话凭据即为成功**。
    # 顺序上先信凭据（cookie + csrf），因为那是后续请求真正要用的东西；
    # 没有任何凭据时才回落到 result 标记，用于给出可诊断的失败信息。
    # ------------------------------------------------------------------
    txt = raw2.decode("utf-8", "ignore")
    body_says_ok = ('"result":"1"' in txt or '"result": 1' in txt)
    body_says_fail = ('"result":"0"' in txt or '"result": 0' in txt)

    if cookie and csrf:
        # 会话凭据齐全 = 成功。若响应体带 result:0，仅记一行说明，不算失败。
        if body_says_fail:
            print(
                "[auth] note: resp has result:0 but session issued "
                "(Z-AUTH-CODE + csrf ok) -- treating as SUCCESS"
            )
        return cookie, csrf

    if body_says_ok:
        # 上游说成功但没给全凭据：仍按失败处理，否则后续请求必然 403
        print(
            "login failed: result:1 but incomplete session: cookie=",
            "yes" if cookie else "no",
            ", csrf=",
            "yes" if csrf else "no",
        )
        return "", ""

    print(
        "login failed: cookie=",
        "yes" if cookie else "no",
        ", csrf=",
        "yes" if csrf else "no",
        ", body=",
        txt[:300],
    )
    return "", ""


def ensure_session(api_url):
    """首次调用时确保有会话；已有则直接复用。"""
    with _LOCK:
        cookie = _SESSION.get("cookie")
        csrf = _SESSION.get("csrf")
        if cookie:
            return cookie, csrf
        cookie, csrf = do_login(api_url)
        if cookie:
            _SESSION["cookie"] = cookie
            _SESSION["csrf"] = csrf
            save_session(cookie, csrf)
        return cookie, csrf


def refresh_session(api_url):
    """会话失效后重登并落盘（带**节流 + 失败退避**）。

    为什么必须节流（2026-10-04 事故复盘）
    ------------------------------------
    本函数由 `Handler._proxy` 在收到 401/403/406/407 时调用，而每个代理请求
    都是独立触发的。会话文件缺失或登录被上游拒绝时，会形成正反馈死循环：

        请求 403 → refresh_session() 登录 → csrf 取不到 → 会话没更新
          → 下一个请求又 403 → 又登录 → …… （实测达 3822 次/天、几秒一次）

    上游（eFlow）每次登录都会**新建一个服务端会话且从不释放**，于是 my_app
    自己的重试把 eFlow 的会话数顶爆 —— 这正是 2026-10-04 的"用户数风暴"。

    三道闸门（缺一不可）：
      1. **成功冷却** `_LOGIN_MIN_INTERVAL`：距上次成功登录不足该秒数就直接复用
         现有会话，不再登录。用于吸收"前端并发刷新"这种正常但密集的触发。
      2. **失败退避** `_LOGIN_BACKOFF`：登录失败后，在指数增长的窗口内
         （失败次数越多等得越久，上限 `_LOGIN_BACKOFF_MAX`）**一律不再尝试登录**，
         直接让调用方走失败分支。这切断正反馈，避免把上游打死。
      3. **并发合并**：`_LOCK` 保证同一时刻只有一个登录在飞；配合 1/2，
         并发的 N 个 403 最多只换 1 次真实登录。

    返回 (cookie, csrf)。**被节流或退避拦下时返回 ("", "")**，明确告诉调用方
    "本次没有刷新成功" —— 调用方据此走失败分支（502），而不是拿着同一个失效
    会话重试。这一点很关键：调用方判定成功的条件是 `[0]` 非空，若这里回填现有
    cookie，调用方会误以为刷新成功并 continue，白白多打一次上游（又是一次 403）。
    """
    global _LOGIN_LAST_OK, _LOGIN_LAST_FAIL, _LOGIN_FAIL_COUNT
    with _LOCK:
        now = time.time()

        # 闸门 2：失败退避中，直接放弃（不触网）
        if _LOGIN_FAIL_COUNT > 0:
            wait = min(
                _LOGIN_BACKOFF * (2 ** (_LOGIN_FAIL_COUNT - 1)),
                _LOGIN_BACKOFF_MAX,
            )
            elapsed = now - _LOGIN_LAST_FAIL
            if elapsed < wait:
                print(
                    f"[auth] backoff: skip login "
                    f"(failed {_LOGIN_FAIL_COUNT}x, {wait - elapsed:.0f}s left)"
                )
                return "", ""

        # 闸门 1：成功冷却期内，复用现有会话（不触网）
        if _LOGIN_LAST_OK and (now - _LOGIN_LAST_OK) < _LOGIN_MIN_INTERVAL:
            print(
                f"[auth] throttle: reuse session "
                f"({now - _LOGIN_LAST_OK:.0f}s < {_LOGIN_MIN_INTERVAL}s)"
            )
            # 返回空 = 告诉调用方"本次没有真正刷新"。若这里返回现有 cookie，
            # 调用方会以为刷新成功并 continue 重试同一个失效会话，
            # 白白多打一次上游（每次重试都是一次 403）。
            return "", ""

        # 闸门 0：**先尝试复用共享会话**（auth_manager 缓存），完全不触网。
        #
        # 为什么放在最前面：403 可能只是因为**本代理手里的会话旧了**，而别的
        # 进程（worker）刚登录过、缓存是新鲜的。此时直接复用即可，**无需登录**
        # —— 这正是"不要每个任务申请一次 token"的落地。只有共享缓存也拿不到
        # 可用会话时，才退回到自己登录。
        #
        # 放在退避/冷却判断**之后**是有意的：若刚经历失败退避，说明上游可能
        # 正在拒绝，此时连共享缓存也不该抢先复用（保持退避语义），交由调用方
        # 走失败分支。
        if _try_adopt_shared():
            print("[auth] reused shared session from auth_manager (no login needed)")
            return _SESSION["cookie"], _SESSION["csrf"]

        cookie, csrf = do_login(api_url)

        if cookie and csrf:
            _SESSION["cookie"] = cookie
            _SESSION["csrf"] = csrf
            save_session(cookie, csrf)
            _LOGIN_LAST_OK = time.time()
            _LOGIN_FAIL_COUNT = 0
            print("[proxy] session refreshed csrf=", (csrf[:16] + "…") if csrf else "no")
        else:
            # 登录失败：记一次失败，进入退避；**不**落盘半截会话
            _LOGIN_FAIL_COUNT += 1
            _LOGIN_LAST_FAIL = time.time()
            print(
                f"[auth] login failed ({_LOGIN_FAIL_COUNT}x) -- entering backoff"
            )
        return cookie, csrf


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, data=b"", ctype="application/json; charset=utf-8", extra_headers=None):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        if ctype:
            self.send_header("Content-Type", ctype)
        for k, v in (extra_headers or {}).items():
            self.send_header(str(k), str(v))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _proxy(self):
        query = urllib.parse.urlsplit(self.path).query
        q = urllib.parse.parse_qs(query, keep_blank_values=True)

        url = (q.get("url") or [""])[0]
        if not url:
            return self._json({"error": "missing 'url' param"}, 400)

        try:
            url = normalize_target_url(url)
        except ValueError as e:
            return self._json({"error": str(e)}, 403)

        method = (q.get("method") or [self.command or "GET"])[0].upper()
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            return self._json({"error": "unsupported method: " + method}, 405)

        body = (q.get("body") or [""])[0]
        client_cookie = (q.get("cookie") or [""])[0]

        def build_headers():
            headers = {
                "Accept": "application/json, text/plain, */*",
                "Origin": TARGET_HOST,
                "Referer": TARGET_HOST + "/",
                "User-Agent": _UA,
            }
            ck = client_cookie or _SESSION.get("cookie") or ""
            if ck:
                headers["Cookie"] = ck
            if method in ("POST", "PUT", "PATCH"):
                headers["Content-Type"] = "application/json; charset=utf-8"
            return headers

        data = body.encode("utf-8") if body else None

        redirect_uri = get_redirect_uri(url)
        for attempt in (1, 2):
            csrf = _SESSION.get("csrf") or ""
            if csrf:
                sep = "&" if urllib.parse.urlsplit(url).query else "?"
                u = url + sep + "csrftoken=" + urllib.parse.quote(csrf, safe="")
            else:
                u = url

            print("[proxy] ", method, " ", url, " (attempt=", attempt, ", redirect_uri=", redirect_uri, ")")

            try:
                r = _request(
                    u,
                    data=data,
                    headers=build_headers(),
                    method=method,
                    timeout=25,
                    follow_redirects=False,
                )
                raw = r.read()
                ctype = r.headers.get("Content-Type", "application/json")
                location = r.headers.get("Location", "")
                status = r.status

                if 200 <= status < 300:
                    return self._send(status, raw, ctype)

                if status in (301, 302, 303, 307, 308):
                    if "/api/oauth2/v1/authorize" in (location or ""):
                        print("[proxy] auth redirect detected: ", location)
                        if attempt == 1 and refresh_session(url)[0]:
                            continue
                        return self._json(
                            {
                                "error": "re-login failed",
                                "detail": "upstream redirect",
                                "upstream_status": status,
                                "location": location,
                            },
                            502,
                        )
                    return self._send(status, raw, ctype)

                return self._json(
                    {
                        "error": "upstream redirect",
                        "upstream_status": status,
                        "location": location,
                        "body": raw.decode("utf-8", "ignore")[:1000],
                    },
                    502,
                )

            except HTTPError as e:
                err_body = e.read()
                status = e.code
                location = e.headers.get("Location", "") if e.headers else ""

                if status in (401, 403, 406, 407):
                    print("[proxy] auth error ", status, ", refreshing session...")
                    if attempt == 1 and refresh_session(url)[0]:
                        continue
                    return self._json(
                        {
                            "error": "upstream error",
                            "detail": err_body.decode("utf-8", "ignore")[:2000],
                            "upstream_status": status,
                            "upstream_body": err_body.decode("utf-8", "ignore")[:2000],
                        },
                        502,
                    )

                return self._json(
                    {
                        "error": "upstream error",
                        "upstream_status": status,
                        "upstream_body": err_body.decode("utf-8", "ignore")[:2000],
                    },
                    502,
                )

            except HTTPError as e:  # pragma: no cover - 保底分支
                print("[proxy] HTTPError ", e.code, ": ", e)
                return self._json(
                    {
                        "error": "upstream error",
                        "upstream_status": e.code,
                        "upstream_body": "",
                        "location": "",
                    },
                    500,
                )

            except URLError as e:
                reason = getattr(e, "reason", e)
                print("[proxy] upstream unreachable: ", reason)
                return self._json({"error": "upstream unreachable", "detail": str(reason)}, 502)

            except Exception as e:
                print("[proxy] internal error: ", type(e).__name__, e)
                return self._json({"error": "proxy internal error"}, 500)

        return self._json({"error": "proxy retry exhausted"}, 502)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in ("/", "/health"):
            return self._json(
                {
                    "status": "ok",
                    "proxy": "ready",
                    "target": TARGET_HOST,
                    "auth": bool(_SESSION.get("cookie")),
                    "user": USER,
                }
            )
        if path == "/proxy":
            return self._proxy()
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/proxy":
            return self._proxy()
        return self._json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        print("[http] ", self.address_string(), " - ", fmt % args)


def main():
    load_session()
    # 启动时优先接入 auth_manager 的**跨进程共享会话**：worker 等进程若已有
    # 可用 token，本代理直接复用，**不再自己登录一份**。这是"全项目一个 token
    # 来源"的关键 —— 否则代理与 worker 各登录一份，上游会话数翻倍。
    adopted = adopt_shared_session()
    if not adopted:
        print("[proxy] no shared session at startup; will self-login if needed")
    try:
        cookie, _csrf = ensure_session(
            TARGET_HOST + "/api/alarmstatistics-service/v1/levelregion/getsitelocations"
        )
    except Exception as e:
        cookie = ""
        print("[proxy] startup login failed: ", e)
        print("[proxy] proxy will retry login when an API requires auth")

    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("实时代理已启动: http://127.0.0.1:", PORT, " (目标 ", TARGET_HOST, ", 用户 ", USER, ")")
    print("共享会话: ", "已接入 auth_manager 缓存" if adopted else "未接入（独立登录）")
    print("自动登录: 用户名 + RSA 加密密码方式（未改变）")
    print("动态 redirect_uri: 已启用")
    print("多业务 API: 已启用")
    print("自动重登: 已启用")
    print("登录节流: 已启用")
    print("日志: 已启用")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("已停止")


if __name__ == "__main__":
    main()

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
    """从 fms_session.json 读取 cookie / csrf。"""
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

    csrf = ""
    for c in _COOKIE_JAR:
        if c.name == "forgerydefense":
            csrf = c.value
    if not csrf and set_cookie:
        for part in set_cookie.split(","):
            for seg in part.split(";"):
                seg = seg.strip()
                if seg.lower().startswith("forgerydefense="):
                    csrf = seg.split("=", 1)[1]
                    if csrf == "deleted":
                        csrf = ""

    if status2 and status2 >= 300:
        print("login_rsa HTTP ", status2)

    cookie = _cookie_header_from_jar()
    result_ok = (
        '"result":"1"' in raw2.decode("utf-8", "ignore")
        or '"result": 1' in raw2.decode("utf-8", "ignore")
    )
    if not result_ok:
        txt = raw2.decode("utf-8", "ignore")
        if '"result":"0"' in txt or '"result": 0' in txt:
            print(
                "login failed: cookie=",
                "yes" if cookie else "no",
                ", csrf=",
                "yes" if csrf else "no",
                ", body=",
                txt[:300],
            )
            return "", ""
        if cookie and csrf:
            print(
                "[auth] warning: login response has no explicit result 0/1; "
                "accepting because cookie + csrf are present"
            )
        else:
            print(
                "login failed: cookie=",
                "yes" if cookie else "no",
                ", csrf=",
                "yes" if csrf else "no",
                ", body=",
                txt[:300],
            )
            return "", ""

    print(
        "[auth] login success: cookie=",
        "yes" if cookie else "no",
        ", csrf=",
        (csrf[:16] + "…") if csrf else "no",
    )
    return cookie, csrf


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
    """会话失效后重登并落盘。"""
    with _LOCK:
        cookie, csrf = do_login(api_url)
        if cookie:
            _SESSION["cookie"] = cookie
            _SESSION["csrf"] = csrf
            save_session(cookie, csrf)
            print("[proxy] session refreshed csrf=", (csrf[:16] + "…") if csrf else "no")
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
    print("自动登录: 用户名 + RSA 加密密码方式（未改变）")
    print("动态 redirect_uri: 已启用")
    print("多业务 API: 已启用")
    print("自动重登: 已启用")
    print("日志: 已启用")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("已停止")


if __name__ == "__main__":
    main()

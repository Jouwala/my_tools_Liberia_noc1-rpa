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


USER, PASS = _load_cred("vmax_cxo", "ZeeshanM", "Zte@1a2b3c", "VMAX_CXO_USER", "VMAX_CXO_PASS")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, "vmax_session.json")

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

CJ = cookiejar.CookieJar()
CSRF = ""
_OPENER = None
_LOCK = threading.Lock()


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
    for c in CJ:
        if c.name.lower() == "forgerydefense":
            CSRF = c.value

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
    """Return True only if the dashboard ECMA modules accept the session.

    The portal's getUserName returns 200 even for a DEAD JSESSIONID, so probing
    it gives a false "session valid" and the proxy then keeps serving 404s for
    every dashboard API call. Instead probe a real dashboard endpoint: a 200
    means the session is live, anything else means re-login.
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
        r = _OPENER.open(req, timeout=20)
        return r.getcode() == 200
    except HTTPError as e:
        return e.code == 200
    except Exception:
        return False


def ensure_login():
    """持锁确保会话可用：先复用磁盘会话，探活失败则重新登录。"""
    with _LOCK:
        if load_session() and _probe_session():
            _activate_dashboard()
            return True
        if vmax_login():
            save_session()
            return True
        return False


def fetch(target_url, method="GET", body=None):
    """向 TARGET_HOST 发请求，带上 CSRF 头；返回 (status, resp, payload)。"""
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
    resp = _OPENER.open(req, timeout=30)
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
            ok = bool(CSRF) and len(list(CJ)) > 0
            self.wfile.write(
                json.dumps(
                    {"status": "ok", "proxy": "ready", "auth": ok, "user": USER}
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
                    self.wfile.write(payload)
                    return
                session_rejected = status in (401, 407, 403)
            except HTTPError as e:
                status = e.code
                payload = e.read()
                session_rejected = status in (401, 407, 403)
            except Exception as e:
                print("[proxy] network error, re-login:", e)
                session_rejected = True
                payload = b""

            if session_rejected:
                print("[proxy] session rejected (", status, "), re-login", flush=True)
                if ensure_login():
                    continue
                self.send_response(502)
                self._cors()
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
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


def main():
    import atexit

    _OPENER_INIT = build_opener()
    ok = ensure_login()
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

"""临时诊断：复刻 eFlow「直接鉴权 + CDP 种 cookie」流程，逐步打印诊断信息。

用法：
  python TMP/t_cdp_eflow.py <out.png> [httponly]
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import websockets  # noqa: E402

from backend.services import portal_login_service as svc  # noqa: E402

OUT_PNG = sys.argv[1] if len(sys.argv) > 1 else "TMP/cdp_eflow.png"
HTTP_ONLY = (len(sys.argv) > 2 and sys.argv[2].lower() == "httponly")
BROWSER = svc.get_default_browser_exe()
PROFILE = os.path.abspath(f"TMP/_cdp_eflow_{uuid.uuid4().hex[:8]}")


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


async def main():
    spec = svc.PORTALS["eflow"]
    host, port = svc.resolve_endpoint(spec)
    login_url = svc.build_login_url(spec)
    home_url = f"https://{host}:{port}{spec['redirect']}"
    log("browser:", BROWSER)
    log("login_url:", login_url)
    log("home_url:", home_url)

    cookie_str, forgery = svc._eflow_direct_auth(spec)
    log("auth ok, forgery:", forgery[:16], "...")

    os.makedirs(PROFILE, exist_ok=True)
    proc = subprocess.Popen(
        [BROWSER, f"--user-data-dir={PROFILE}", "--remote-debugging-port=0",
         "--start-maximized", "--no-first-run", "--no-default-browser-check", login_url],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    dport = None
    devtools = os.path.join(PROFILE, "DevToolsActivePort")
    for _ in range(60):
        if os.path.exists(devtools):
            try:
                with open(devtools, encoding="utf-8") as f:
                    dport = int(f.readline().strip())
                break
            except Exception:
                pass
        time.sleep(0.1)
    if not dport:
        raise SystemExit("no devtools port")
    log("devtools port:", dport)

    with urllib.request.urlopen(f"http://127.0.0.1:{dport}/json", timeout=5) as r:
        targets = json.loads(r.read().decode("utf-8"))
    tgt = next((t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None)
    ws_url = tgt["webSocketDebuggerUrl"]
    log("target url:", tgt.get("url"))

    mid = [0]

    async with websockets.connect(ws_url, max_size=None) as ws:
        async def send(method, params=None, wait=True):
            mid[0] += 1
            i = mid[0]
            payload = {"id": i, "method": method}
            if params is not None:
                payload["params"] = params
            await ws.send(json.dumps(payload))
            if not wait:
                return None
            while True:
                data = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                if data.get("id") == i:
                    return data

        async def js(expr):
            r = await send("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                                "awaitPromise": True})
            res = (r or {}).get("result", {})
            if res.get("exceptionDetails"):
                return {"__exc__": str(res["exceptionDetails"])[:200]}
            return res.get("result", {}).get("value")

        await send("Network.enable", wait=False)
        await send("Runtime.enable", wait=False)
        await send("Page.enable", wait=False)
        await send("Security.setIgnoreCertificateErrors", {"ignore": True}, wait=False)

        # --- 1) 等页面真正落到 eFlow 源（而不是 about:blank / 中间重定向） ---
        for i in range(40):
            info = await js("(() => ({href: location.href, rs: document.readyState, "
                            "origin: location.origin}))()")
            log("  wait page:", info)
            if isinstance(info, dict) and host in str(info.get("href", "")):
                break
            await asyncio.sleep(0.5)

        # --- 2) 种 cookie ---
        n = 0
        for ck in svc._split_cookies(cookie_str):
            r = await send("Network.setCookie", {
                "name": ck["name"], "value": ck["value"], "domain": host, "path": "/",
                "httpOnly": HTTP_ONLY, "secure": True})
            ok = (r or {}).get("result", {}).get("success")
            log("  setCookie", ck["name"], "->", ok)
            if ok is not False:
                n += 1
        log("cookies set:", n, "httpOnly:", HTTP_ONLY)

        # --- 3) 写 csrftoken（在正确的源上） ---
        expr = ("(() => { try { localStorage.setItem('csrftoken', JSON.stringify(%s));"
                " return localStorage.getItem('csrftoken'); } catch (e) { return 'ERR:' + e; } })()"
                % json.dumps(forgery))
        log("  csrftoken write ->", await js(expr))
        log("  document.cookie ->", str(await js("document.cookie"))[:300])

        # --- 4) 导航到主页 ---
        await send("Page.navigate", {"url": home_url}, wait=False)
        for i in range(30):
            await asyncio.sleep(1)
            href = await js("location.href")
            if i in (2, 5, 9, 14, 20, 28):
                txt = await js("(document.body?document.body.innerText:'').slice(0,300)")
                lsc = await js("localStorage.getItem('csrftoken')")
                log(f"  t={i}s href={href}")
                log(f"        text={str(txt)[:200]!r}")
                log(f"        ls.csrftoken={str(lsc)[:60]}")

        final_href = await js("location.href")
        final_text = await js("(document.body?document.body.innerText:'').slice(0,1200)")
        log("FINAL href:", final_href)
        log("FINAL text:", repr(str(final_text)[:800]))
        log("FINAL cookie:", str(await js("document.cookie"))[:400])

        shot = await send("Page.captureScreenshot", {"format": "png"})
        data = ((shot or {}).get("result", {}) or {}).get("data")
        if data:
            with open(os.path.abspath(OUT_PNG), "wb") as f:
                f.write(base64.b64decode(data))
            log("screenshot ->", os.path.abspath(OUT_PNG))
        else:
            log("screenshot FAILED")

    log("browser pid", proc.pid, "kept open for inspection")


asyncio.run(main())

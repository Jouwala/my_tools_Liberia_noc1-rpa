"""反代链路完整验证：反代登录 + 抓主页加载期间的失败请求。

用法：python TMP/t_proxy_login2.py <out.png>
"""
import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid

for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(k, None)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import websockets  # noqa: E402
from backend.services.portal_login_service import get_default_browser_exe  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "TMP/proxy_login2.png"
LOGIN_URL = ("http://localhost/api/oauth2/v1/authorize?scope=user.login"
             "&response_type=code&redirect_uri=/uportal/framework/default.html")
PROFILE = os.path.abspath(f"TMP/_proxy2_eflow_{uuid.uuid4().hex[:8]}")


async def main():
    os.makedirs(PROFILE, exist_ok=True)
    exe = get_default_browser_exe()
    proc = subprocess.Popen([exe, f"--user-data-dir={PROFILE}", "--remote-debugging-port=0",
                             "--start-maximized", "--no-first-run", "--no-default-browser-check",
                             LOGIN_URL],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    devtools = os.path.join(PROFILE, "DevToolsActivePort")
    port = None
    for _ in range(60):
        if os.path.exists(devtools):
            with open(devtools, encoding="utf-8") as f:
                port = int(f.readline().strip())
            break
        time.sleep(0.1)
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as r:
        targets = json.loads(r.read().decode("utf-8"))
    tgt = next(t for t in targets if t.get("type") == "page")

    async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=None) as ws:
        mid = 0
        pending = {}

        async def send(method, params=None, wait=True):
            nonlocal mid
            mid += 1
            m = {"id": mid, "method": method}
            if params:
                m["params"] = params
            await ws.send(json.dumps(m))
            if not wait:
                return None
            while True:
                d = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                if d.get("id") == mid:
                    return d

        async def js(expr):
            d = await send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            res = d.get("result") or {}
            if res.get("exceptionDetails"):
                return "EXC"
            return (res.get("result") or {}).get("value")

        await send("Network.enable", wait=False)
        await send("Runtime.enable", wait=False)
        await send("Page.enable", wait=False)
        await send("Security.enable", wait=False)
        await send("Security.setIgnoreCertificateErrors", {"ignore": True}, wait=False)

        bad, total = [], 0
        done = False
        deadline = time.time() + 70
        while time.time() < deadline and not done:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
            except asyncio.TimeoutError:
                href = await js("location.href")
                if href and "default.html" in str(href):
                    # 主页已到，再等 8s 收数据请求
                    t2 = time.time() + 8
                    while time.time() < t2:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=2)
                        except asyncio.TimeoutError:
                            continue
                        d = json.loads(raw)
                        if d.get("method") == "Network.responseReceived":
                            rr = d["params"]["response"]
                            total += 1
                            if int(rr.get("status") or 0) >= 400:
                                bad.append((rr["status"], rr.get("url", "")))
                    done = True
                continue
            d = json.loads(raw)
            if d.get("method") == "Network.responseReceived":
                rr = d["params"]["response"]
                total += 1
                pending[d["params"]["requestId"]] = rr.get("url", "")
                if int(rr.get("status") or 0) >= 400:
                    bad.append((rr["status"], rr.get("url", "")))
            elif d.get("method") == "Network.loadingFailed":
                bad.append(("FAIL", pending.get(d["params"].get("requestId"), "?")
                            + " " + str(d["params"].get("errorText"))))

        print("总响应:", total)
        print("失败请求:", len(bad))
        seen = set()
        for s, u in bad:
            k = (s, u[:110])
            if k in seen:
                continue
            seen.add(k)
            print(f"  {s}  {u[:160]}")
        print("href:", await js("location.href"))
        txt = str(await js("(document.body?document.body.innerText:'').slice(0,250)") or "")
        print("text:", txt.replace("\n", " | ")[:250])
        shot = await send("Page.captureScreenshot", {"format": "png"})
        data = ((shot.get("result") or {}) or {}).get("data")
        if data:
            with open(os.path.abspath(OUT), "wb") as f:
                f.write(base64.b64decode(data))
            print("screenshot ->", os.path.abspath(OUT))
    try:
        proc.kill()
    except Exception:
        pass


asyncio.run(main())

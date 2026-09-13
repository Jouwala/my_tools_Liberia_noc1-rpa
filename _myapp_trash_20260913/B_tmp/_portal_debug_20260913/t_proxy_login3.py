"""反代登录后，观察 eFlow 主页的告警数据是否会加载出来（决定客户端模式是否可用）。

用法：python TMP/t_proxy_login3.py
"""
import asyncio
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

LOGIN_URL = ("http://localhost/api/oauth2/v1/authorize?scope=user.login"
             "&response_type=code&redirect_uri=/uportal/framework/default.html")
PROFILE = os.path.abspath(f"TMP/_proxy3_eflow_{uuid.uuid4().hex[:8]}")


async def main():
    os.makedirs(PROFILE, exist_ok=True)
    proc = subprocess.Popen([get_default_browser_exe(), f"--user-data-dir={PROFILE}",
                             "--remote-debugging-port=0", "--start-maximized", "--no-first-run",
                             "--no-default-browser-check", LOGIN_URL],
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
    bad = []
    pending = {}

    async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=None) as ws:
        mid = 0

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

        async def drain(seconds):
            end = time.time() + seconds
            while time.time() < end:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1)
                except asyncio.TimeoutError:
                    continue
                d = json.loads(raw)
                if d.get("method") == "Network.responseReceived":
                    rr = d["params"]["response"]
                    pending[d["params"]["requestId"]] = rr.get("url", "")
                    if int(rr.get("status") or 0) >= 400:
                        bad.append((rr["status"], rr.get("url", "")))
                elif d.get("method") == "Network.loadingFailed":
                    bad.append(("FAIL", pending.get(d["params"].get("requestId"), "?")
                                + " " + str(d["params"].get("errorText"))))

        # 等主页出现
        for i in range(30):
            await drain(2)
            href = str(await js("location.href") or "")
            if "default.html" in href:
                print(f"主页已到（{i*2+2}s）: {href}")
                break
        for i in range(15):
            await drain(3)
            txt = str(await js("(document.body?document.body.innerText:'').slice(0,400)") or "")
            line = [ln for ln in txt.split("\n") if "Alarms" in ln or "/" in ln][:6]
            print(f"  t={(i+1)*3}s :: {line}")
        print("失败请求:", len(bad))
        for s, u in bad[:20]:
            print(f"  {s} {u[:150]}")
    try:
        proc.kill()
    except Exception:
        pass


asyncio.run(main())

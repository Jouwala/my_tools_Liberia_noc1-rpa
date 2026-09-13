"""验证「客户端模式走 nginx 反代 + 注入填表」这条链路对 eFlow 是否真的能登录。

做法：起一个干净的 Chrome，直接打开反代后的登录入口
  http://localhost/api/oauth2/v1/authorize?scope=user.login&response_type=code&redirect_uri=/uportal/framework/default.html
然后观察：注入脚本是否填了账号密码、是否自动提交、最终是否进主页。
用法：python TMP/t_proxy_login.py <out.png>
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

OUT = sys.argv[1] if len(sys.argv) > 1 else "TMP/proxy_login.png"
LOGIN_URL = ("http://localhost/api/oauth2/v1/authorize?scope=user.login"
             "&response_type=code&redirect_uri=/uportal/framework/default.html")
PROFILE = os.path.abspath(f"TMP/_proxy_eflow_{uuid.uuid4().hex[:8]}")


async def main():
    os.makedirs(PROFILE, exist_ok=True)
    exe = get_default_browser_exe()
    print("browser:", exe)
    print("login_url:", LOGIN_URL)
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
    print("devtools port:", port)
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as r:
        targets = json.loads(r.read().decode("utf-8"))
    tgt = next(t for t in targets if t.get("type") == "page")

    async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=None) as ws:
        mid = 0

        async def send(method, params=None):
            nonlocal mid
            mid += 1
            m = {"id": mid, "method": method}
            if params:
                m["params"] = params
            await ws.send(json.dumps(m))
            while True:
                d = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                if d.get("id") == mid:
                    return d

        async def js(expr):
            d = await send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            res = d.get("result") or {}
            if res.get("exceptionDetails"):
                return "EXC:" + str(res["exceptionDetails"])[:100]
            return (res.get("result") or {}).get("value")

        await send("Security.enable")
        await send("Security.setIgnoreCertificateErrors", {"ignore": True})
        await send("Runtime.enable")
        await send("Page.enable")

        probe = ("(() => { const u=document.querySelector('#inputUserName')||"
                 "document.querySelector('input[name=username]');"
                 " const p=document.querySelector('#inputCiphercode')||"
                 "document.querySelector('input[type=password]');"
                 " return JSON.stringify({href: location.href,"
                 " u: u ? String(u.value) : null, pLen: p ? String(p.value).length : null,"
                 " inject: !!document.querySelector('script[src*=inject.js]'),"
                 " txt: (document.body?document.body.innerText:'').slice(0,120)}); })()")

        for i in range(14):
            await asyncio.sleep(2)
            print(f"  t={(i+1)*2}s :: {await js(probe)}")

        print("FINAL href:", await js("location.href"))
        print("FINAL text:", str(await js("(document.body?document.body.innerText:'').slice(0,300)"))[:300])
        print("cookie(JS可见):", str(await js("document.cookie"))[:200])
        shot = await send("Page.captureScreenshot", {"format": "png"})
        data = ((shot.get("result") or {}) or {}).get("data")
        if data:
            with open(os.path.abspath(OUT), "wb") as f:
                f.write(base64.b64decode(data))
            print("screenshot ->", os.path.abspath(OUT))
    print("chrome pid:", proc.pid)


asyncio.run(main())

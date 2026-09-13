"""A/B 对比：localStorage.csrftoken 存「带引号的 JSON 串」vs「裸 token」对 eFlow 首屏的影响。

对已在运行的 eFlow 调试窗口做：设置 csrftoken -> 整页重载主页 -> 读文案 + 截图。
用法：python TMP/t_ab_csrftoken.py <cdp_port> <quoted|raw> <out.png>
"""
import asyncio
import base64
import json
import os
import sys
import urllib.request

for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(k, None)

PORT = int(sys.argv[1])
MODE = sys.argv[2]
OUT = sys.argv[3]


async def main():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=5) as r:
        targets = json.loads(r.read().decode("utf-8"))
    tgt = next(t for t in targets if t.get("type") == "page")
    import websockets
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
                d = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
                if d.get("id") == mid:
                    return d

        async def js(expr):
            d = await send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            res = d.get("result") or {}
            if res.get("exceptionDetails"):
                return f"EXC:{str(res['exceptionDetails'])[:120]}"
            return (res.get("result") or {}).get("value")

        await send("Page.enable")
        await send("Security.enable")
        await send("Security.setIgnoreCertificateErrors", {"ignore": True})
        tok = await js("localStorage.getItem('csrftoken')")
        tok = str(tok).strip('"')
        print("token:", tok[:24], "...")
        if MODE == "quoted":
            expr = "localStorage.setItem('csrftoken', JSON.stringify(%s)); localStorage.getItem('csrftoken')" % json.dumps(tok)
        else:
            expr = "localStorage.setItem('csrftoken', %s); localStorage.getItem('csrftoken')" % json.dumps(tok)
        print("stored as:", repr(await js(expr)))

        await send("Page.navigate", {"url": "https://10.100.20.8:28001/uportal/framework/default.html"})
        for i in range(12):
            await asyncio.sleep(2)
            txt = str(await js("(document.body?document.body.innerText:'').slice(0,400)") or "")
            if i in (1, 3, 5, 11):
                print(f"  t={(i+1)*2}s len={len(txt)} :: {txt[:120]!r}")
        txt = str(await js("(document.body?document.body.innerText:'').slice(0,3000)") or "")
        print("MODE", MODE, "final len:", len(txt))
        print("final text:", txt[:400].replace("\n", " | "))
        shot = await send("Page.captureScreenshot", {"format": "png"})
        data = ((shot.get("result") or {}) or {}).get("data")
        if data:
            with open(os.path.abspath(OUT), "wb") as f:
                f.write(base64.b64decode(data))
            print("screenshot ->", os.path.abspath(OUT))


asyncio.run(main())

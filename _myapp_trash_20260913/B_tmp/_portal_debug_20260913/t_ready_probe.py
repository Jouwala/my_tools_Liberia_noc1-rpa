"""对已打开的 eFlow 浏览器（诊断脚本留下的窗口）验证 PORTAL_READY_JS 判定是否可靠。"""
import asyncio
import glob
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import websockets  # noqa: E402
from backend.services.portal_login_service import PORTAL_READY_JS, _SESSION_ERR_RE  # noqa: E402

cands = sorted(glob.glob(os.path.abspath("TMP/_cdp_eflow_*/DevToolsActivePort")))
print("profiles:", cands)
port = None
for c in cands:
    with open(c, encoding="utf-8") as f:
        p = int(f.readline().strip())
    port = p
    break
if not port:
    raise SystemExit("no DevToolsActivePort found")
print("devtools port:", port)


async def main():
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as r:
        targets = json.loads(r.read().decode("utf-8"))
    tgt = next(t for t in targets if t.get("type") == "page")
    async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=None) as ws:
        mid = 0

        async def js(expr):
            nonlocal mid
            mid += 1
            await ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate",
                                      "params": {"expression": expr, "returnByValue": True}}))
            while True:
                d = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
                if d.get("id") == mid:
                    res = (d.get("result") or {})
                    if res.get("exceptionDetails"):
                        return f"EXC: {str(res['exceptionDetails'])[:150]}"
                    return (res.get("result") or {}).get("value")

        print("url:", await js("location.href"))
        print("ready_js ->", await js(PORTAL_READY_JS))
        txt = await js("(document.body?document.body.innerText:'').slice(0,200)")
        print("text:", repr(str(txt))[:220])
        print("session_err_re ->", bool(_SESSION_ERR_RE.search(str(txt))))


asyncio.run(main())

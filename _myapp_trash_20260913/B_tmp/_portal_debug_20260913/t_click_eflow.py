"""端到端验证「用户真实点击」：打开门户登录页 -> 真实鼠标点击 eFlow 的登录按钮
-> 检查是否触发了服务器端直接鉴权、卡片状态、以及弹出的 eFlow 窗口是否已登录。

用法：python TMP/t_click_eflow.py <page.png> <eflow.png>
"""
import asyncio
import base64
import glob
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

PAGE_PNG = sys.argv[1] if len(sys.argv) > 1 else "TMP/click_page.png"
EF_PNG = sys.argv[2] if len(sys.argv) > 2 else "TMP/click_eflow.png"
URL = "http://localhost/myapp/?page=portalLogin"
PROFILE = os.path.abspath(f"TMP/_click_ui_{uuid.uuid4().hex[:8]}")


async def cdp(ws_url):
    return await websockets.connect(ws_url, max_size=None)


async def main():
    os.makedirs(PROFILE, exist_ok=True)
    proc = subprocess.Popen([get_default_browser_exe(), f"--user-data-dir={PROFILE}",
                             "--remote-debugging-port=0", "--start-maximized", "--no-first-run",
                             "--no-default-browser-check", URL],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    devtools = os.path.join(PROFILE, "DevToolsActivePort")
    port = None
    for _ in range(80):
        if os.path.exists(devtools):
            with open(devtools, encoding="utf-8") as f:
                port = int(f.readline().strip())
            break
        time.sleep(0.1)
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as r:
        targets = json.loads(r.read().decode("utf-8"))
    tgt = next(t for t in targets if t.get("type") == "page")

    ws = await cdp(tgt["webSocketDebuggerUrl"])
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
            return "EXC:" + str(res["exceptionDetails"])[:150]
        return (res.get("result") or {}).get("value")

    await send("Runtime.enable", wait=False)
    await send("Page.enable", wait=False)

    # 1) 等门户卡片渲染出来
    rect = None
    for i in range(40):
        await asyncio.sleep(1)
        rect = await js("""(() => {
          const cards = Array.from(document.querySelectorAll('.ant-card'));
          const card = cards.find(c => (c.innerText||'').includes('eFlow'));
          if (!card) return null;
          const btns = Array.from(card.querySelectorAll('button'));
          const b = btns.find(x => /登录|Login/i.test(x.innerText||''));
          if (!b) return null;
          const r = b.getBoundingClientRect();
          return {x: r.left + r.width/2, y: r.top + r.height/2,
                  label: (b.innerText||'').trim(), card: (card.innerText||'').slice(0,60)};
        })()""")
        if isinstance(rect, dict) and rect.get("x"):
            print(f"找到按钮({i+1}s): {rect}")
            break
        rect = None
    if not rect:
        print("没找到 eFlow 卡片的登录按钮，页面文本：")
        print(str(await js("(document.body?document.body.innerText:'').slice(0,600)")))
        raise SystemExit(1)

    # 2) 真实鼠标点击（Input.dispatchMouseEvent 才算用户手势）
    x, y = rect["x"], rect["y"]
    await send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none"})
    await send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y,
                                            "button": "left", "clickCount": 1})
    await send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y,
                                            "button": "left", "clickCount": 1})
    print("已点击 Login 按钮")

    # 3) 观察卡片状态变化
    for i in range(14):
        await asyncio.sleep(3)
        st = await js("""(() => {
          const cards = Array.from(document.querySelectorAll('.ant-card'));
          const card = cards.find(c => (c.innerText||'').includes('eFlow'));
          return card ? (card.innerText||'').replace(/\\n/g,' | ').slice(0,220) : null;
        })()""")
        print(f"  t={(i+1)*3}s 卡片: {st}")
    shot = await send("Page.captureScreenshot", {"format": "png"})
    data = ((shot.get("result") or {}) or {}).get("data")
    if data:
        with open(os.path.abspath(PAGE_PNG), "wb") as f:
            f.write(base64.b64decode(data))
        print("页面截图 ->", os.path.abspath(PAGE_PNG))
    await ws.close()

    # 4) 检查服务器端弹出的 eFlow 窗口
    time.sleep(2)
    cands = sorted(glob.glob(os.path.abspath("data/portal_profiles/_tmp_eflow_*/DevToolsActivePort")),
                   key=os.path.getmtime)
    if not cands:
        print("没有发现 eFlow 服务器端窗口的调试端口")
        return
    with open(cands[-1], encoding="utf-8") as f:
        eport = int(f.readline().strip())
    with urllib.request.urlopen(f"http://127.0.0.1:{eport}/json", timeout=5) as r:
        et = json.loads(r.read().decode("utf-8"))
    etgt = next((t for t in et if t.get("type") == "page"), None)
    print("eFlow 窗口 target:", etgt.get("url"))
    ws2 = await websockets.connect(etgt["webSocketDebuggerUrl"], max_size=None)
    mid2 = 0

    async def send2(method, params=None):
        nonlocal mid2
        mid2 += 1
        m = {"id": mid2, "method": method}
        if params:
            m["params"] = params
        await ws2.send(json.dumps(m))
        while True:
            d = json.loads(await asyncio.wait_for(ws2.recv(), timeout=30))
            if d.get("id") == mid2:
                return d

    await send2("Page.enable")
    print("eFlow href:", await js2(send2, "location.href"))
    txt = await js2(send2, "(document.body?document.body.innerText:'').slice(0,260)")
    print("eFlow 文案:", str(txt).replace("\n", " | ")[:260])
    s2 = await send2("Page.captureScreenshot", {"format": "png"})
    d2 = ((s2.get("result") or {}) or {}).get("data")
    if d2:
        with open(os.path.abspath(EF_PNG), "wb") as f:
            f.write(base64.b64decode(d2))
        print("eFlow 截图 ->", os.path.abspath(EF_PNG))


async def js2(send_fn, expr):
    d = await send_fn("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    res = d.get("result") or {}
    if res.get("exceptionDetails"):
        return "EXC"
    return (res.get("result") or {}).get("value")


asyncio.run(main())

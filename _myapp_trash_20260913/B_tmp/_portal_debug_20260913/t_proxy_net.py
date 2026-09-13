"""连到刚才那个「反代登录成功」的浏览器，抓它加载主页时的失败请求。

目的：判断走 nginx 反代的 eFlow 主页是不是「登录成功但接口全挂」（告警数 0/0）。
用法：python TMP/t_proxy_net.py <cdp_port>
"""
import asyncio
import glob
import json
import os
import sys
import urllib.request

for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(k, None)

port = int(sys.argv[1])


async def main():
    import websockets
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as r:
        targets = json.loads(r.read().decode("utf-8"))
    tgt = next(t for t in targets if t.get("type") == "page")
    print("target:", tgt.get("url"))
    reqs = {}
    bad = []
    async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=None) as ws:
        mid = 0

        async def send(method, params=None):
            nonlocal mid
            mid += 1
            m = {"id": mid, "method": method}
            if params:
                m["params"] = params
            await ws.send(json.dumps(m))
            return m["id"]

        await send("Network.enable")
        await send("Runtime.enable")
        await send("Page.enable")
        await send("Page.reload", {"ignoreCache": True})
        deadline = asyncio.get_event_loop().time() + 40
        while asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                break
            d = json.loads(raw)
            m = d.get("method")
            p = d.get("params") or {}
            if m == "Network.responseReceived":
                rr = p.get("response") or {}
                url = rr.get("url", "")
                reqs[p.get("requestId")] = url
                if int(rr.get("status") or 0) >= 400:
                    bad.append((rr.get("status"), url))
            elif m == "Network.loadingFailed":
                bad.append(("FAILED", reqs.get(p.get("requestId"), "?") + " " + str(p.get("errorText"))))
        print("请求总数:", len(reqs), " 失败:", len(bad))
        for s, u in bad[:40]:
            print(f"  {s}  {u[:150]}")


asyncio.run(main())

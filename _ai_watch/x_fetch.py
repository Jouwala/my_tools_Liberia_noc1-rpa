# -*- coding: utf-8 -*-
"""X(Twitter) 首页时间线抓取器。

用本机已安装的 Chrome（无需下载 Chromium），持久化 profile 到
x_profile/，首次需人工登录一次，之后复用登录态。

用法：
  python x_fetch.py login    # 打开浏览器等待人工登录，登录成功后回车/超时自动保存
  python x_fetch.py fetch    # 抓取首页时间线，输出 _raw_tweets.json
"""
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(BASE, "x_profile")
OUT = os.path.join(BASE, "_raw_tweets.json")
CDP = os.path.join(BASE, ".cdp_port.txt")

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]


def _context(p):
    """优先复用已开着的 Chrome（CDP），否则新开持久化上下文。"""
    if os.path.exists(CDP):
        port = open(CDP).read().strip()
        try:
            b = p.chromium.connect_over_cdp("http://127.0.0.1:%s" % port)
            ctx = b.contexts[0] if b.contexts else b.new_context()
            return b, ctx, True
        except Exception:
            pass
    b = p.chromium.launch_persistent_context(
        PROFILE,
        channel="chrome",
        headless=False,
        args=LAUNCH_ARGS,
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
    )
    return b, b, False


def is_logged_in(ctx):
    pg = ctx.pages[0] if ctx.pages else ctx.new_page()
    pg.goto("https://x.com/home", wait_until="domcontentloaded")
    pg.wait_for_timeout(5000)
    # 登录态判断：账号切换按钮存在 = 已登录
    return pg.locator('[data-testid="SideNav_AccountSwitcher_Button"]').count() > 0


def cmd_login():
    with sync_playwright() as p:
        b, ctx, _ = _context(p)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto("https://x.com/home", wait_until="domcontentloaded")
        print("浏览器已打开。请在窗口中完成登录（扫码或账号密码）。", flush=True)
        for i in range(60):
            pg.wait_for_timeout(10000)
            try:
                if pg.locator('[data-testid="SideNav_AccountSwitcher_Button"]').count() > 0:
                    print("检测到登录成功。", flush=True)
                    break
            except Exception:
                pass
            if i % 6 == 5:
                print("...仍在等待登录 (%d/60)" % (i + 1), flush=True)
        pg.wait_for_timeout(3000)
        try:
            b.close()
        except Exception:
            pass
    print("profile 已保存到", PROFILE, flush=True)


ART = "article[data-testid='tweet']"


def harvest(pg):
    out = []
    for a in pg.locator(ART).all():
        try:
            t = a.inner_text(timeout=2000)
        except Exception:
            continue
        if not t.strip():
            continue
        # 结构化字段
        handle = ""
        m = re.search(r"@([A-Za-z0-9_]{2,15})", t)
        if m:
            handle = "@" + m.group(1)
        # 名字/handle/·时间 三行以内取前两段
        head = t.split("\n")[:3]
        try:
            url = a.locator('a[href*="/status/"]').first.get_attribute("href")
            url = "https://x.com" + url if url and url.startswith("/") else url
        except Exception:
            url = ""
        # 正文 = 去掉头部几行后剩下的
        body_lines = t.split("\n")
        body = "\n".join(body_lines[2:]) if len(body_lines) > 2 else t
        # 互动数
        metrics = {}
        for name, pat in (("like", r"([\d,.]+[KkMm]?)\s*$"),):
            pass
        for m2 in a.locator('[data-testid="reply"] , [data-testid="retweet"] , [data-testid="like"] , [data-testid="bookmark"]').all():
            pass
        nums = re.findall(r"\n([\d.,]+[KkMm]?)\s*$", "\n" + t)
        if nums:
            metrics["raw_counts"] = nums
        out.append({
            "handle": handle,
            "head": " | ".join(head),
            "text": t,
            "body": body,
            "url": url,
            "metrics": metrics,
        })
    return out


def scroll_capture(pg, rounds=25):
    seen = {}
    for i in range(rounds):
        try:
            pg.mouse.wheel(0, 4000)
            pg.wait_for_timeout(2500)
        except Exception:
            break
        for t in harvest(pg):
            k = t["url"] or (t["handle"] + "|" + t["text"][:80])
            if k not in seen:
                seen[k] = t
        sys.stderr.write("round %d  total=%d\n" % (i + 1, len(seen)))
    return list(seen.values())


def cmd_fetch():
    with sync_playwright() as p:
        b, ctx, _ = _context(p)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto("https://x.com/home", wait_until="domcontentloaded")
        pg.wait_for_timeout(6000)
        if pg.locator('[data-testid="SideNav_AccountSwitcher_Button"]').count() == 0:
            print("NOT_LOGGED_IN")
            return
        tweets = scroll_capture(pg)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(tweets, f, ensure_ascii=False, indent=1)
        print("saved", len(tweets), "->", OUT, flush=True)
        try:
            b.close()
        except Exception:
            pass


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    (cmd_login if cmd == "login" else cmd_fetch)()
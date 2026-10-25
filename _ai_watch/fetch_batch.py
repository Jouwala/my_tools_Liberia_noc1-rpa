# -*- coding: utf-8 -*-
"""批量抓取 X 账号公开时间线（免登录 r.jina.ai 通道）。

策略：
  1. jina 的 markdown 模式对部分账号会返回「降级」渲染（无 status 链接 /
     无时间戳 / 无互动量），对另一些账号正常。
  2. HTML 模式（x-respond-with: html）始终返回完整 DOM，因此统一走
     HTML 模式，再用 html2md.py 转成 parse.py 期望的 markdown 行格式。

先删除同名旧文件保证新鲜度（周报逻辑，非首次构建的 skip-if-exists）。
遇到 429 限流时指数退避重试。
"""
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "raw")
HTML_DIR = os.path.join(RAW, "html")

ACCOUNTS = [
    # 核心厂商
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "GoogleAI", "MetaAI",
    "mistralai", "QwenLM", "huggingface", "GitHubAI", "Replicate",
    "GroqAI", "nvidia", "AIatMeta", "claudeai",
    # 研究者 / 开发者
    "karpathy", "simonw", "swyx", "sama", "JeffDean", "gdb",
    "AravSrinivas", "cohere", "vercel",
    # 补充信源
    "ollama", "perplexity_ai", "moonshotai", "z-ai", "MiniMaxAI",
]

# 噪声账号：内容为搬运 / 骚扰 / 与 AI 弱相关，抓了也剔
NOISE = {"DeepSeekAI", "TogetherAI", "ylecun"}


def valid_html(path):
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            txt = fh.read()
    except OSError:
        return False
    return len(txt) > 4000 and "<article" in txt


def fetch(acct):
    os.makedirs(HTML_DIR, exist_ok=True)
    out = os.path.join(HTML_DIR, "%s.html" % acct)
    md_out = os.path.join(RAW, "%s.md" % acct)
    for p in (out, md_out):
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    url = "https://r.jina.ai/https://x.com/%s" % acct
    last = "?"
    for attempt in range(5):
        try:
            r = subprocess.run(
                ["curl", "-s", "-m", "120", "-H", "x-respond-with: html",
                 url, "-o", out, "-w", "%{http_code}"],
                capture_output=True, text=True, timeout=150,
            )
            last = (r.stdout or "").strip()
        except Exception as e:  # noqa: BLE001
            last = "ERR:%s" % str(e)[:60]
        if valid_html(out):
            # 转成 jina 同构 markdown
            sys.path.insert(0, BASE)
            import html2md
            html = open(out, encoding="utf-8", errors="ignore").read()
            md = html2md.html_to_markdown(html, acct)
            if md.count("*   ") >= 1:
                with open(md_out, "w", encoding="utf-8") as fh:
                    fh.write(md)
                return acct, last, "OK %d tweets" % md.count("*   ")
            last = "CONV-EMPTY"
        if last == "429":
            time.sleep(15 * (attempt + 1))
        else:
            time.sleep(5)
    if os.path.exists(out):
        try:
            os.remove(out)
        except OSError:
            pass
    return acct, last, "FAILED"


def main():
    os.makedirs(RAW, exist_ok=True)
    accounts = [a for a in ACCOUNTS if a not in NOISE]
    results = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        for res in ex.map(fetch, accounts):
            results.append(res)
            print("%-20s %-5s %s" % res, flush=True)
    ok = [r for r in results if r[2].startswith("OK")]
    print("\n=== %d/%d accounts fetched ===" % (len(ok), len(accounts)))
    if ok:
        print("成功:", ", ".join(r[0] for r in ok))


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""把 tweets.json 加工成报告用的 tweets_final.json。

做三件事：
  1. 剔除噪声账号（内容搬运 / 骚扰 / 与 AI 弱相关）。
  2. 用推文 ID 的 snowflake 时间戳补全绝对日期（parse.py 的 `when` 只能
     拿到 "19h" 这类相对值或空）。
  3. 去重、按热度排序。

parse.py 不改动，本脚本在其产物之上做后处理。
"""
import datetime
import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "tweets.json")
OUT = os.path.join(BASE, "tweets_final.json")

# 噪声账号：DeepSeekAI 内容是搬运他人推文、TogetherAI 抓到骚扰内容、
# ylecun 是政治吐槽。抓取阶段已跳过，这里再兜一层。
NOISE_ACCOUNTS = {"DeepSeekAI", "TogetherAI", "ylecun"}

SNOWFLAKE_EPOCH = 1288834974657  # X/Twitter ID 时间戳基准（毫秒）
STATUS_RE = re.compile(r"/status/(\d{15,})")

# 展示名（HTML 转 markdown 时抽到的第一个非 handle 文本）
DISPLAY = {
    "AIatMeta": "AI at Meta",
    "Alibaba_Qwen": "Qwen",
    "AnthropicAI": "Anthropic",
    "AravSrinivas": "Aravind Srinivas",
    "GitHub": "GitHub",
    "GoogleAI": "Google AI",
    "GoogleDeepMind": "Google DeepMind",
    "GroqAI": "Groq",
    "JeffDean": "Jeff Dean",
    "MiniMax_AI": "MiniMax",
    "OpenAI": "OpenAI",
    "Replicate": "Replicate",
    "claudeai": "Claude",
    "cohere": "Cohere",
    "gdb": "Greg Brockman",
    "huggingface": "Hugging Face",
    "karpathy": "Andrej Karpathy",
    "mistralai": "Mistral AI",
    "moonshotai": "Moonshot AI",
    "nvidia": "NVIDIA",
    "ollama": "Ollama",
    "perplexity_ai": "Perplexity",
    "sama": "Sam Altman",
    "simonw": "Simon Willison",
    "swyx": "swyx",
    "vercel": "Vercel",
}


def tweet_date(url):
    """从 snowflake ID 解出绝对日期（UTC）。"""
    m = STATUS_RE.search(url or "")
    if not m:
        return ""
    ms = (int(m.group(1)) >> 22) + SNOWFLAKE_EPOCH
    dt = datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)
    return dt.strftime("%Y-%m-%d")


def main():
    with open(SRC, encoding="utf-8") as fh:
        tweets = json.load(fh)

    seen = set()
    out = []
    dropped = []
    for t in tweets:
        acct = t.get("account", "")
        if acct in NOISE_ACCOUNTS:
            dropped.append((acct, "噪声账号"))
            continue
        url = t.get("url", "")
        if not url or url in seen:
            dropped.append((acct, "重复/无链接"))
            continue
        seen.add(url)

        t = dict(t)
        t["account"] = acct
        t["name"] = DISPLAY.get(acct, acct)
        date = tweet_date(url)
        t["date"] = date
        # `when` 保留原相对值，补一个绝对日期字段
        t["when"] = date or t.get("when", "")
        t["text"] = re.sub(r"\s+", " ", t.get("text", "")).strip()
        out.append(t)

    out.sort(key=lambda x: -(x["metrics"]["likes"] + x["metrics"]["views"] * 0.01))

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    print("tweets_final: %d 条（剔除 %d）" % (len(out), len(dropped)))
    for a, r in dropped:
        print("  剔除 %s: %s" % (a, r))
    accs = sorted(set(t["account"] for t in out))
    print("账号数 %d: %s" % (len(accs), ", ".join(accs)))


if __name__ == "__main__":
    main()

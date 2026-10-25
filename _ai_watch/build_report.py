# -*- coding: utf-8 -*-
"""把 report_template.html 的占位符替换为真实数据，产出周报。

占位符：
  __DATA__        tweets_final.json 全文
  __ACC_COUNT__   账号数
  __TWEET_COUNT__ 推文数
  __DATE_CN__     报告日期（中文）
  __STATS__       统计卡
  __ACC_BTNS__    账号筛选按钮（按实际账号数生成）
"""
import datetime
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(BASE, "report_template.html")
DATA = os.path.join(BASE, "tweets_final.json")

ACC_LABEL = {
    "AIatMeta": "Meta AI",
    "Alibaba_Qwen": "通义千问",
    "AnthropicAI": "Anthropic",
    "AravSrinivas": "Perplexity",
    "GitHub": "GitHub",
    "GoogleAI": "Google AI",
    "GoogleDeepMind": "DeepMind",
    "JeffDean": "Jeff Dean",
    "Kimi_Moonshot": "Kimi",
    "MiniMax_AI": "MiniMax",
    "OpenAI": "OpenAI",
    "Replicate": "Replicate",
    "claudeai": "Claude",
    "cohere": "Cohere",
    "gdb": "Brockman",
    "huggingface": "HF",
    "karpathy": "karpathy",
    "mistralai": "Mistral",
    "nvidia": "NVIDIA",
    "ollama": "Ollama",
    "perplexity_ai": "Perplexity",
    "sama": "sama",
    "simonw": "simonw",
    "swyx": "swyx",
    "vercel": "Vercel",
}


def main():
    with open(TPL, encoding="utf-8") as fh:
        tpl = fh.read()
    with open(DATA, encoding="utf-8") as fh:
        tweets = json.load(fh)

    accounts = sorted({t["account"] for t in tweets})
    today = datetime.date.today()
    date_cn = "%d 年 %d 月 %d 日" % (today.year, today.month, today.day)

    # 统计卡（按模板实际卡片数动态统计，避免与正文脱节）
    import re
    model_cards = len(re.findall(r'data-cat="model"', tpl))
    free_cards = len(re.findall(r'data-cat="free"', tpl))
    skill_rows = len(re.findall(r"<td><b>", tpl))
    stats = [
        (len(accounts), "个信源账号"),
        (len(tweets), "条一手推文"),
        (model_cards, "个新发布模型"),
        (free_cards, "项免费与开源资源"),
    ]
    stats_html = "\n".join(
        '  <div class="stat"><div class="n">%s</div><div class="l">%s</div></div>' % s
        for s in stats
    )

    # 账号筛选按钮
    btns = "\n".join(
        '    <button class="fbtn" data-f="%s">%s</button>' % (a, ACC_LABEL.get(a, a))
        for a in accounts
    )

    out = tpl
    out = out.replace("__DATA__", json.dumps(tweets, ensure_ascii=False, separators=(",", ":")))
    out = out.replace("__ACC_COUNT__", str(len(accounts)))
    out = out.replace("__TWEET_COUNT__", str(len(tweets)))
    out = out.replace("__DATE_CN__", date_cn)
    out = out.replace("__STATS__", stats_html)
    out = out.replace("__ACC_BTNS__", btns)

    assert "__" not in out.replace("__proto__", ""), "仍有未替换的占位符"

    path = os.path.join(BASE, "AI动态观测周报_%s.html" % today.strftime("%Y%m%d"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out)
    print("生成: %s" % path)
    print("账号 %d 个，推文 %d 条，大小 %.1f KB" % (
        len(accounts), len(tweets), os.path.getsize(path) / 1024))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""把 raw/*.md 里的推文清洗成结构化 JSON，供报告生成使用。

jina.ai 返回的 markdown 中，一条推文的形态大致为：
  *   [![](头像)](url)  [@acct](url)  [时间](url)   正文… [Video 3](url)00:00   [451](compose) 663 8.7K 1M
互动量在行尾，可能是 [N](link) 也可能是裸数字，且常被拆成多行。
"""
import glob
import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, "raw")
OUT = os.path.join(BASE, "tweets.json")

IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINKTXT = re.compile(r"\[([^\]]*)\]\([^)]*\)")
STATUS_RE = re.compile(r"/status/(\d{15,})")
NUM = r"[\d][\d.,]*[KkMm]?"

BOILER_PREFIX = (
    "Log in", "Sign up", "Terms", "Privacy", "Cookies", "Accessibility",
    "See what", "Continue with", "Scan to get", "## Log in",
)

STOP_TAIL = re.compile(
    r"\s*(\[\s*(" + NUM + r")\s*\]\([^)]*compose/post[^)]*\)|(?:^|\s)(" + NUM + r"))\s*$"
)


def parse_count(s):
    if not s:
        return 0
    s = s.replace(",", "").strip().rstrip(".")
    mult = 1
    if s and s[-1] in "KkMm":
        mult = 1000 if s[-1] in "Kk" else 1_000_000
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def clean(s):
    s = IMG.sub(" ", s)
    s = LINKTXT.sub(r"\1", s)
    s = re.sub(r"\[Video[^\]]*\]\([^)]*\)[^ ]*", " ", s)
    s = re.sub(r"\[(GIF|Image \d+[^\]]*)\]", " ", s)
    s = s.replace("Show more", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def extract_metrics(text):
    """从一行末尾向前吞掉最多 4 个数字，返回 (正文, [回复,转发,点赞,浏览])。"""
    counts = []
    rest = text.rstrip()
    for _ in range(4):
        m = STOP_TAIL.search(rest)
        if not m:
            break
        val = m.group(2) or m.group(3)
        if val is None:
            break
        counts.append(parse_count(val))
        rest = rest[: m.start()]
    counts.reverse()  # 回到 时间顺序
    while len(counts) < 4:
        counts.insert(0, 0)
    return rest, counts[-4:]


def main():
    tweets = []
    for f in sorted(glob.glob(os.path.join(RAW, "*.md"))):
        account = os.path.splitext(os.path.basename(f))[0]
        text = open(f, encoding="utf-8").read()
        text = text.split("## Log in or sign up")[0]
        chunks = re.split(r"\n\*\s+", text)
        for ch in chunks[1:]:
            lines = ch.split("\n")
            head = lines[0]
            if "twimg.com/profile_images" not in head:
                continue
            extra = []
            for ln in lines[1:]:
                if "twimg.com/profile_images" in ln:
                    break
                extra.append(ln)
            raw_line = " ".join([head] + extra)
            body, counts = extract_metrics(raw_line)
            m = STATUS_RE.search(head)
            tm = re.search(r"\[([^\]]*(?:Oct|Sep|Nov|\d+[hm]))\]\(", head)
            # 正文 = 抬头（昵称 @handle 时间）之后的部分
            anchor = re.search(r"\]\([^)]*/status/\d+\)\s*|\]\([^)]*/status/[^)]+\)\s*", head)
            if anchor:
                body = body[anchor.end():] if anchor.end() <= len(body) else body
            else:
                ah = re.search(r"\[([^\]]*(?:Oct|Sep|Nov|\d+[hm]))\]\([^)]*\)\s*", body)
                if ah:
                    body = body[ah.end():]
            body = clean(body)
            if len(body) < 25:
                continue
            if any(body.startswith(b) for b in BOILER_PREFIX):
                continue
            m = STATUS_RE.search(head)
            tm = re.search(r"\[([^\]]*(?:Oct|Sep|Nov|\d+[hm]))\]\(", head)
            tweets.append({
                "account": account,
                "when": tm.group(1) if tm else "",
                "url": "https://x.com/%s/status/%s" % (account, m.group(1)) if m else "",
                "metrics": {"replies": counts[0], "reposts": counts[1],
                            "likes": counts[2], "views": counts[3]},
                "text": body,
            })
    tweets.sort(key=lambda t: -(t["metrics"]["likes"] + t["metrics"]["views"] * 0.01))
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(tweets, fh, ensure_ascii=False, indent=1)
    ok = sum(1 for t in tweets if t["metrics"]["likes"] > 0)
    print("tweets: %d (有互动量 %d) -> %s" % (len(tweets), ok, OUT))


if __name__ == "__main__":
    main()
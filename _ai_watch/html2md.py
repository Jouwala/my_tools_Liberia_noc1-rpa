# -*- coding: utf-8 -*-
"""把 r.jina.ai 的 HTML 渲染结果转成与 jina markdown 模式同构的文本。

背景：jina 的 markdown 模式对部分账号返回「降级」渲染（缺 status 链接、
时间戳与互动量），而 HTML 模式（x-respond-with: html）始终返回完整 DOM。
本模块用嵌套感知的解析器切分 <article>，还原出 parse.py 期望的 markdown
行格式，从而让清洗逻辑（parse.py）保持不变。

期望输出（每条推文一个 `*   ` 块，行尾是 4 个互动量 token）：
*   [](https://x.com/<acct>/status/<id>)[![Image 3: @<acct>](<avatar>)](https://x.com/<acct>)  [<Name>](https://x.com/<acct>) [@<acct>](https://x.com/<acct>) [<when>](https://x.com/<acct>/status/<id>)   <正文>   [reply](https://x.com/compose/post?in_reply_to=<id>) repost like views
"""
import html as htmllib
import re
from html.parser import HTMLParser

STATUS_PATH_RE = re.compile(r"^/([A-Za-z0-9_]+)/status/(\d{15,})")
AVATAR_RE = re.compile(r'<img[^>]*src="(https://pbs\.twimg\.com/profile_images/[^"]+)"')
AVATAR_ANY_RE = re.compile(r'profile_images/[^"\s]+?_normal\.jpg')
ENGAGE_ARIA = {
    "reply": "Reply",
    "repost": "Repost",
    "like": "Like",
    "views": "View count",
}
ENGAGE_DATA_RE = re.compile(r'data-engagement-action="([^"]+)"')
COUNT_RE = re.compile(r'x-animated-count-visual"[^>]*>([^<]*)<')
# 正文容器：text-primary + whitespace-pre-wrap
# （页头昵称块是 font-bold，handle 块是 flex，均不匹配）
TEXT_BODY_RE = re.compile(
    r'<div class="max-w-full text-body[^"]*text-primary[^"]*whitespace-pre-wrap[^"]*"[^>]*>',
    re.S,
)


class ArticleSplitter(HTMLParser):
    """按 <article> 嵌套关系切出顶层 article 的 HTML 片段。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.cur = None
        self.articles = []

    def handle_starttag(self, tag, attrs):
        if tag == "article":
            if self.depth == 0:
                self.cur = ["<article>"]
            self.depth += 1
            if self.cur is not None:
                self.cur.append("</article>" if False else "")
        elif self.cur is not None:
            self.cur.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag == "article":
            self.depth -= 1
            if self.depth == 0 and self.cur is not None:
                self.articles.append("".join(self.cur))
                self.cur = None
            elif self.cur is not None:
                self.cur.append("</article>")
        elif self.cur is not None:
            self.cur.append("</%s>" % tag)

    def handle_data(self, data):
        if self.cur is not None:
            self.cur.append(data)

    def handle_startendtag(self, tag, attrs):
        if self.cur is not None:
            self.cur.append(self.get_starttag_text())


def split_articles(html):
    p = ArticleSplitter()
    p.feed(html)
    p.close()
    return p.articles


def _strip_tags(s):
    return re.sub(r"<[^>]+>", "", s)


def _unescape(s):
    return htmllib.unescape(s)


def _clean_text(s):
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>", "\n", s)
    s = _strip_tags(s)
    s = _unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def _parse_count(raw):
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return None
    mult = 1
    if raw[-1] in "Kk":
        mult, raw = 1000, raw[:-1]
    elif raw[-1] in "Mm":
        mult, raw = 1000000, raw[:-1]
    try:
        return int(float(raw) * mult)
    except ValueError:
        return None


def _fmt(n):
    if not n:
        return "0"
    if n >= 1000000:
        return "%.1fM" % (n / 1000000)
    if n >= 1000:
        return "%.1fK" % (n / 1000)
    return str(n)


def _text_bodies(article):
    """取出所有正文容器（主推文在前，引用推文在后）。"""
    out = []
    for m in TEXT_BODY_RE.finditer(article):
        # 从容器起点开始做 div 深度配平，找到其闭合位置
        i = m.end()
        depth = 1
        tag_re = re.compile(r"<(/?)div\b[^>]*>", re.I)
        while depth > 0 and i < len(article):
            mm = tag_re.search(article, i)
            if not mm:
                break
            depth += -1 if mm.group(1) else 1
            if depth == 0:
                i = mm.end()
                break
            i = mm.end()
        out.append(article[m.end(): i])
    return out


def _links(article):
    out = []
    for m in re.finditer(r'<a\b([^>]*)>(.*?)</a>', article, re.S):
        href = re.search(r'href="([^"]*)"', m.group(1))
        txt = re.sub(r"<[^>]+>", "", m.group(2))
        out.append((href.group(1) if href else "",
                    re.sub(r"\s+", " ", _unescape(txt)).strip()))
    return out


def _metrics(article):
    """reply / repost / like / views。

    X 的渲染有两种：带 data-engagement-action 的新版，以及仅靠
    aria-label 的旧版，两种都覆盖。
    """
    found = {}

    for m in ENGAGE_DATA_RE.finditer(article):
        action = m.group(1)
        key = {"retweet": "repost"}.get(action, action)
        if key in found:
            continue
        seg = article[m.start(): m.start() + 2500]
        c = COUNT_RE.search(seg)
        if c:
            v = _parse_count(c.group(1))
            if v is not None:
                found[key] = v

    for key, aria in ENGAGE_ARIA.items():
        if key in found:
            continue
        i = article.find('aria-label="%s"' % aria)
        if i < 0:
            continue
        seg = article[i: i + 2500]
        c = COUNT_RE.search(seg)
        if c:
            v = _parse_count(c.group(1))
            if v is not None:
                found[key] = v

    return (found.get("reply"), found.get("repost"),
            found.get("like"), found.get("views"))


def html_to_markdown(html, acct):
    """把一个账号的 HTML 渲染转成 jina 同构 markdown 文本。"""
    blocks = []
    for art in split_articles(html):
        links = _links(art)

        # 找到主推文的 status id（正文之前出现的第一个）
        sid, when = None, ""
        for href, txt in links:
            m = STATUS_PATH_RE.match(href)
            if not m:
                continue
            if sid is None:
                sid = m.group(2)
                if txt:
                    when = txt
        if not sid:
            continue

        bodies = _text_bodies(art)
        if not bodies:
            continue
        body = _clean_text(bodies[0])
        if not body:
            continue
        quoted = _clean_text(bodies[1]) if len(bodies) > 1 else ""

        av = AVATAR_RE.search(art)
        if not av:
            m2 = AVATAR_ANY_RE.search(art)
            avatar = ("https://pbs.twimg.com/profile_images/" + m2.group(0)
                      if m2 else "")
        else:
            avatar = av.group(1)

        name = ""
        for href, txt in links:
            if not txt or txt.startswith("@") or len(txt) > 40:
                continue
            if re.fullmatch(r"[A-Za-z0-9_\-.· ]{2,40}", txt) and "status" not in href:
                name = txt
                break
        if not name:
            name = acct

        replies, reposts, likes, views = _metrics(art)

        url = "https://x.com/%s/status/%s" % (acct, sid)
        # 头部顺序很关键：parse.py 用 `](/status/<id>)` 作为正文锚点，
        # 首个匹配必须是日期锚点，这样切出来的正文才不含昵称/handle 前缀。
        head = ""
        if avatar:
            head += "[![Image 3: @%s](%s)](https://x.com/%s)" % (acct, avatar, acct)
        head += "  [%s](https://x.com/%s)" % (name, acct)
        head += " [@%s](https://x.com/%s)" % (acct, acct)
        head += " [%s](%s)" % (when, url)

        text = body.replace("\n", " ")
        if quoted:
            text += " " + quoted.replace("\n", " ")

        tail = "[%s](https://x.com/compose/post?in_reply_to=%s) %s %s %s" % (
            _fmt(replies), sid, _fmt(reposts), _fmt(likes), _fmt(views),
        )
        blocks.append("*   %s   %s   %s" % (head, text, tail))
    return "\n\n".join(blocks)


def main():
    import os
    import sys

    src, dst = sys.argv[1], sys.argv[2]
    acct = os.path.splitext(os.path.basename(src))[0]
    html = open(src, encoding="utf-8", errors="ignore").read()
    md = html_to_markdown(html, acct)
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(md)
    print("%s -> %d blocks" % (acct, md.count("*   ")))


if __name__ == "__main__":
    main()

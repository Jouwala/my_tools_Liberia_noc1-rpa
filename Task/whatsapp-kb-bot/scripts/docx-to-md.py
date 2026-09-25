#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""docx → markdown 转换（纯标准库，不依赖 python-docx）。

用法：
    python scripts/docx-to-md.py 输入.docx 输出.md

这个脚本为 **RAG 检索**服务，不是通用格式转换器。三个刻意的取舍：

1. **保留标题层级**。分块器按 Markdown 标题强制断块（见 rag.js 的 chunkText）。
   标题一丢，整节内容会粘成一大块，语义被稀释，检索精度直接掉。

2. **整段丢弃目录**（`toc 1/2/3` 样式）。目录条目是正文标题的副本，
   不丢的话同一批文字在索引里出现两份，白白挤占 topK。

3. **图片只留 `[图]` 占位**。检索是纯文本的，图片内容进不了向量；
   但保留占位能提示"此处原本有图"，避免截图前后的说明文字被割裂成互不相干的碎片。

表格转成 Markdown 表格 —— 规则 / 字段类信息大量以表格承载，丢了损失很大。
"""
from __future__ import annotations

import html
import re
import sys
import zipfile

# 段落样式 → Markdown 标题级别
HEADING = {
    '2': 1, '3': 2, '4': 3, '5': 4, '6': 5, '7': 6, '8': 6, '9': 6,
    '59': 1, '61': 2, '62': 3,   # 附录标题 1/2/3
}
# 丢弃：toc 1/2/3（目录条目）+ TOC 标题1
DROP = {'13', '14', '15', '48'}
# 列表
LIST = {'52', '55'}              # NumberList1 / BulletList1
# 提示块
NOTE = {'63'}                    # 注意标题

_RE_PARA = re.compile(r'<w:p\b[^>]*>.*?</w:p>|<w:p\b[^>]*/>', re.S)
_RE_TBL = re.compile(r'<w:tbl>.*?</w:tbl>', re.S)
_RE_TR = re.compile(r'<w:tr\b[^>]*>.*?</w:tr>', re.S)
_RE_TC = re.compile(r'<w:tc>.*?</w:tc>', re.S)
_RE_TXT = re.compile(r'<w:t[^>]*>([^<]*)</w:t>')


def para_style(p: str) -> str:
    m = re.search(r'<w:pStyle w:val="([^"]+)"', p)
    return m.group(1) if m else ''


def para_text(p: str) -> str:
    """拼接段落内的文本节点。制表符与软换行都归一为空格。

    必须做实体解码：Word 把 `&` 存成 `&amp;`，不解码的话标题会变成
    `Trouble Ticket&amp;&amp;Work Ticket` 这种，既难读又会让字面检索失配。
    """
    s = re.sub(r'<w:tab\s*/>', ' ', p)
    s = re.sub(r'<w:br\s*/>', ' ', s)
    return html.unescape(''.join(_RE_TXT.findall(s)))


def has_image(p: str) -> bool:
    return '<w:drawing>' in p or '<w:pict>' in p


def _clean(t: str) -> str:
    return re.sub(r'\s+', ' ', t).strip()


def cell_text(tc: str) -> str:
    parts = [_clean(para_text(p)) for p in _RE_PARA.findall(tc)]
    t = ' '.join(x for x in parts if x)
    return t.replace('|', '\\|')


def table_md(tbl: str) -> list[str]:
    """把 <w:tbl> 转成 Markdown 表格。首行视为表头。"""
    rows: list[list[str]] = []
    for tr in _RE_TR.findall(tbl):
        cells = [cell_text(tc) for tc in _RE_TC.findall(tr)]
        if cells:
            rows.append(cells)
    if not rows:
        return []
    width = max(len(r) for r in rows)
    out: list[str] = []
    for i, r in enumerate(rows):
        r = r + [''] * (width - len(r))
        out.append('| ' + ' | '.join(r) + ' |')
        if i == 0:
            out.append('|' + '---|' * width)
    return out


def convert(path: str) -> str:
    z = zipfile.ZipFile(path)
    xml = z.read('word/document.xml').decode('utf-8', 'ignore')
    m = re.search(r'<w:body>(.*)</w:body>', xml, re.S)
    body = m.group(1) if m else xml

    # 按文档顺序遍历顶层元素：表格 或 段落
    tokens = re.findall(r'<w:tbl>.*?</w:tbl>|<w:p\b[^>]*>.*?</w:p>|<w:p\b[^>]*/>', body, re.S)

    lines: list[str] = []
    stats = {'heading': 0, 'para': 0, 'list': 0, 'img': 0, 'tbl': 0, 'dropped': 0}

    for tok in tokens:
        if tok.startswith('<w:tbl>'):
            lines.append('')
            lines.extend(table_md(tok))
            lines.append('')
            stats['tbl'] += 1
            continue

        style = para_style(tok)
        text = _clean(para_text(tok))
        img = has_image(tok)

        if style in DROP:
            stats['dropped'] += 1
            continue

        if not text and not img:
            lines.append('')
            continue

        if img:
            stats['img'] += 1
            text = (text + ' [图]').strip()

        lvl = HEADING.get(style)
        if lvl:
            stats['heading'] += 1
            lines.append('')
            lines.append('#' * lvl + ' ' + text)
            lines.append('')
        elif style in NOTE:
            lines.append(f'**注意**：{text}')
        elif style in LIST:
            stats['list'] += 1
            lines.append('- ' + text)
        else:
            stats['para'] += 1
            lines.append(text)

    # 压缩连续空行
    out: list[str] = []
    for ln in lines:
        if ln.strip() == '' and out and out[-1].strip() == '':
            continue
        out.append(ln.rstrip())

    text = '\n'.join(out).strip() + '\n'
    print(
        f'  标题 {stats["heading"]}｜正文 {stats["para"]}｜列表 {stats["list"]}｜'
        f'表格 {stats["tbl"]}｜图片占位 {stats["img"]}｜丢弃目录 {stats["dropped"]}',
        file=sys.stderr,
    )
    return text


def main() -> int:
    if len(sys.argv) < 3:
        print('用法：python docx-to-md.py 输入.docx 输出.md', file=sys.stderr)
        return 2
    src, dst = sys.argv[1], sys.argv[2]
    try:
        md = convert(src)
    except Exception as e:
        print(f'转换失败：{e}', file=sys.stderr)
        return 1
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f'  ✓ {dst}（{len(md)} 字符）', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())

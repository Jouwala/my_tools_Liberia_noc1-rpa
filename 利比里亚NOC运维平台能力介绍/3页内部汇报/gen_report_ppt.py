# -*- coding: utf-8 -*-
"""
生成「OLR MS 运维工具平台」3 页中文内部汇报 PPTX。
页面：P1 运维痛点 / P2 逻辑架构 / P3 主要功能。
视觉沿用同目录 DESIGN.md 的 ZTE 蓝商务风（浅底 + #0072BC 主色）。
数字取自代码实值（App.tsx VALID_PAGES=59、task_registry TASK_SPECS=72），非手册旧值。
运行结束打印总耗时（秒）。
"""
import sys, time, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_t0 = time.time()

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

# ---------- 调色板（DESIGN.md §2）----------
PRIMARY = RGBColor(0x00, 0x72, 0xBC)
DEEP    = RGBColor(0x0F, 0x2C, 0x4D)
ACCENT  = RGBColor(0xFF, 0x92, 0x2B)
LIGHT   = RGBColor(0xF2, 0xF6, 0xFA)
BODY    = RGBColor(0x1A, 0x2B, 0x3D)
SEC     = RGBColor(0x64, 0x74, 0x8B)
FOOT    = RGBColor(0x94, 0xA3, 0xB8)
HAIR    = RGBColor(0xE2, 0xE8, 0xE0)
HAIR    = RGBColor(0xE2, 0xE8, 0xF0)
WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
FONT    = "微软雅黑"

EMU_IN = 914400
PAGE_W, PAGE_H = 13.333, 7.5

prs = Presentation()
prs.slide_width  = Emu(int(PAGE_W * EMU_IN))
prs.slide_height = Emu(int(PAGE_H * EMU_IN))
BLANK = prs.slide_layouts[6]


def _set_ea(run, name=FONT):
    """同时设置西文与中文（East Asian）字体，避免中文回退成宋体。"""
    run.font.name = name
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", name)


def add_text(slide, x, y, w, h, runs, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP, line_spacing=1.0, space_after=0, wrap=True):
    """runs: list of paragraphs; each paragraph = list of (text, size, bold, color)."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    for i, para in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line_spacing
        if space_after:
            p.space_after = Pt(space_after)
        for (txt, size, bold, color) in para:
            r = p.add_run()
            r.text = txt
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = color
            _set_ea(r)
    return tb


def _units(text):
    """估算文本宽度单位：CJK 全角=1.0，其余=0.55。"""
    return sum(1.0 if ord(c) > 0x2E80 else 0.55 for c in text)


def chip_width(text, size_pt, pad=0.30):
    """按字宽估算 chip 宽度（英寸），保证单行不换行。"""
    return pad + _units(text) * (size_pt / 72.0)


def add_box(slide, x, y, w, h, fill=None, line=None, line_w=0.75,
            shape=MSO_SHAPE.RECTANGLE, shadow=False):
    sp = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid(); sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line; sp.line.width = Pt(line_w)
    sp.shadow.inherit = False
    if not shadow:
        # 关闭默认阴影
        spPr = sp._element.spPr
        el = spPr.makeelement(qn('a:effectLst'), {})
        spPr.append(el)
    sp.text_frame.word_wrap = True
    return sp


def box_text(sp, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE,
             line_spacing=1.0, ml=0.12, mt=0.06):
    tf = sp.text_frame
    tf.vertical_anchor = anchor
    tf.margin_left = Inches(ml); tf.margin_right = Inches(ml)
    tf.margin_top = Inches(mt);  tf.margin_bottom = Inches(mt)
    for i, para in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line_spacing
        for (txt, size, bold, color) in para:
            r = p.add_run(); r.text = txt
            r.font.size = Pt(size); r.font.bold = bold
            r.font.color.rgb = color
            _set_ea(r)


def header(slide, title, subtitle=None):
    add_box(slide, 0.667, 0.36, 0.055, 0.44, fill=PRIMARY)
    add_text(slide, 0.82, 0.30, 11.6, 0.6,
             [[(title, 25, True, DEEP)]], anchor=MSO_ANCHOR.MIDDLE)
    if subtitle:
        add_text(slide, 0.84, 0.90, 11.6, 0.34,
                 [[(subtitle, 11.5, False, SEC)]])


def footer(slide, idx, total=3):
    add_box(slide, 0.667, 6.92, 12.0, 0.012, fill=HAIR)
    add_text(slide, 0.667, 7.0, 8.0, 0.3,
             [[("OLR MS 运维工具平台 · 内部汇报", 10, False, FOOT)]])
    add_text(slide, 10.667, 7.0, 2.0, 0.3,
             [[("%02d / %02d" % (idx, total), 10, False, FOOT)]], align=PP_ALIGN.RIGHT)


# ================= P1 · 运维痛点 =================
s = prs.slides.add_slide(BLANK)
header(s, "一、平台基于哪些运维痛点设计",
       "面向 NOC/SOC「每天要看板、要发报表、报表不能漏、告警不能延误」的值班场景，逐条对着痛点长出来")

pains = [
    ("数据分散在多个上游系统",
     "eFlow、各制式网管(UME/CNN/iPRAN/MW)、CN EMS、FineBI、邮箱、FTP 各自为政，手工汇总耗时、口径不一。",
     "72 个定时任务统一采集→清洗→落库，形成单一数据底座。"),
    ("报表 / 看板人工制作，易漏发",
     "每日 Excel 报表与邮件投递靠人做，一忙就漏、一发就错。",
     "自动生成报表 + 定时邮件/微信投递；失败自动重试、漏跑自动补投。"),
    ("看板入口分散，值班来回切系统",
     "FineBI 决策平台与自研系统两套入口，找一张看板要点好几层。",
     "统一门户聚合 55+ 页面直链 + FineBI 报表分类，一个入口全达。"),
    ("知识锁在文档与规则里",
     "告警码释义、TT 定级、派单规则、iMind-eFlow 操作指南，答一个问题要翻半天文档。",
     "WhatsApp 群内 @ 问答，带出处引用，答不出明确说「库里没有」不编造。"),
    ("实时告警通知不可靠",
     "旧方案靠 Chrome 扩展驱动 WhatsApp Web，需浏览器常开、手动重扫，DOM 猜测致重复告警。",
     "独立 headless 推送守护，UME 服务器告警每分钟推送 + 服务端回执。"),
    ("进程 / 任务需人盯，易崩易卡",
     "采集任务漏跑、后端或 worker 崩溃会中断正在看板取数的人。",
     "worker 分组 + 双看门狗心跳自愈，单实例锁防双写。"),
]

cw, ch, gap = 3.86, 2.42, 0.21
x0, y0 = 0.667, 1.36
for i, (t, pain, sol) in enumerate(pains):
    cx = x0 + (i % 3) * (cw + gap)
    cy = y0 + (i // 3) * (ch + gap)
    card = add_box(s, cx, cy, cw, ch, fill=LIGHT)
    # 序号徽章
    badge = add_box(s, cx + 0.18, cy + 0.18, 0.42, 0.42, fill=PRIMARY, shape=MSO_SHAPE.OVAL)
    box_text(badge, [[("%d" % (i + 1), 15, True, WHITE)]], align=PP_ALIGN.CENTER)
    # 痛点标题
    add_text(s, cx + 0.72, cy + 0.20, cw - 0.9, 0.6,
             [[(t, 13.5, True, DEEP)]], anchor=MSO_ANCHOR.MIDDLE, line_spacing=0.95)
    # 痛点描述
    add_text(s, cx + 0.20, cy + 0.80, cw - 0.4, 0.95,
             [[(pain, 10.5, False, SEC)]], line_spacing=1.05)
    # 分隔线
    add_box(s, cx + 0.20, cy + 1.72, cw - 0.4, 0.012, fill=HAIR)
    # 解法
    add_text(s, cx + 0.20, cy + 1.80, cw - 0.4, 0.56,
             [[("解法  ", 10.5, True, ACCENT), (sol, 10.5, False, BODY)]], line_spacing=1.05)
footer(s, 1)


# ================= P2 · 逻辑架构 =================
s = prs.slides.add_slide(BLANK)
header(s, "二、平台设计与实现的逻辑架构",
       "「一个入口 + 一个数据核心 + 一个交互层」三层结构，本机 nginx:80 统一反代缝合")

# 左侧 nginx 竖脊
spine = add_box(s, 0.667, 1.42, 1.35, 5.06, fill=DEEP)
box_text(spine, [
    [("nginx", 15, True, WHITE)],
    [(":80", 13, True, PRIMARY)],
    [("", 6, False, WHITE)],
    [("统一入口", 11, False, WHITE)],
    [("反向代理", 11, False, WHITE)],
    [("静态资源", 11, False, WHITE)],
    [("缝合三系统", 10.5, False, RGBColor(0xB8,0xC7,0xD9))],
], align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.15)

bands = [
    ("入口层", "统一门户 (Portal)",
     "React 19 + Vite + Tailwind v4，聚合 FineBI 决策报表 + my_app 全部看板；顶部 TaskSyncWidget 每 60s 拉 /api/tasks 展示任务状态，离线自动降级静态快照。",
     ["看板聚合", "三视图", "深浅双模", "中英 i18n", "移动端二维码"]),
    ("数据核心", "my_app (Data Insight)",
     "vite:7090 → FastAPI:7038 → PostgreSQL(主)/SQLite(快照)。分层 routers(HTTP)→services(60+业务模块)→models(ORM)。72 定时任务写 task_queue，worker 分组串行消费。",
     ["41→72 定时任务", "worker×8 组", "双看门狗自愈", "失败重试/漏跑补投", "单实例锁"]),
    ("交互层", "WhatsApp 机器人",
     "Node.js + Baileys 群客户端 → 工具路由：规则层优先(单号/日期/级别) + LLM 兜底(站点名等开集)。bge-m3 向量 + 词级 BM25 混合检索，未命中即拒答。",
     ["本地 Ollama", "混合检索", "带出处引用", "数字只由脚本渲染"]),
]
by, bh, bgap = 1.42, 1.58, 0.16
bx, bw = 2.18, 10.48
for i, (tag, name, desc, chips) in enumerate(bands):
    y = by + i * (bh + bgap)
    # 层名标签
    lab = add_box(s, bx, y, 2.15, bh, fill=(PRIMARY if i != 1 else DEEP))
    box_text(lab, [[(tag, 14, True, WHITE)], [(name, 10.5, False, RGBColor(0xD7,0xE6,0xF5))]],
             align=PP_ALIGN.CENTER, line_spacing=1.1)
    # 描述框（整块浅色背景；描述在上部居中，chips 收在面板内底部）
    add_box(s, bx + 2.25, y, bw - 2.25, bh, fill=LIGHT)
    add_text(s, bx + 2.25 + 0.16, y + 0.10, bw - 2.25 - 0.32, bh - 0.62,
             [[(desc, 10.8, False, BODY)]], anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.12)
    # 技术 chips（按字宽估算，保证单行）
    chip_x = bx + 2.25 + 0.16
    chip_y = y + bh - 0.46
    for c in chips:
        cwid = chip_width(c, 8.6)
        ch_sp = add_box(s, chip_x, chip_y, cwid, 0.30, fill=WHITE, line=PRIMARY, line_w=0.75,
                        shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        box_text(ch_sp, [[(c, 8.6, False, PRIMARY)]], align=PP_ALIGN.CENTER, ml=0.02)
        chip_x += cwid + 0.12
    # 层间箭头
    if i < 2:
        ar = add_box(s, bx + 0.9, y + bh - 0.02, 0.34, bgap + 0.04, fill=ACCENT,
                     shape=MSO_SHAPE.DOWN_ARROW)
footer(s, 2)


# ================= P3 · 主要功能 =================
s = prs.slides.add_slide(BLANK)
header(s, "三、平台主要实现的功能",
       "三大子系统能力清单（页面数 / 任务数为代码实值，截至 2026-10-18）")

cols = [
    ("my_app 数据平台", PRIMARY, "59 页面路由 · 72 定时任务", [
        "数据采集同步：eFlow / 各制式 UME / CN EMS / MW 微波 / FW 防火墙 / FineBI / 邮箱 / 备件",
        "看板与下钻：TT&WO、告警、NUR、MS SLA、GIS、丢包、电池、CXO、CN KPI 5min、CR/PM 分析",
        "GIS 人员图层：位置 / WO / 路线 / 悬停告警连线",
        "站点可用率 2G/3G/4G（走本地 PG，远端 HTTP 回退）",
        "通用表浏览 + 字段画像 + Excel/CSV 导入导出",
        "自动 Excel 报表 + 邮件 / 微信 / OpenClaw 通知",
    ]),
    ("统一门户", DEEP, "聚合入口 · 40+ 看板直链", [
        "看板聚合：my_app 真实页面直链 + FineBI 报表分类",
        "实时任务调度 Widget（/api/tasks，离线降级快照）",
        "三视图：卡片网格 / 高密清单 / 业务分类矩阵",
        "环境切换：一键替换全部看板链接 IP / 域名",
        "深浅双模 + 中英文国际化（持久化）",
        "收藏置顶、访问热度排序、JSON 备份、移动端二维码",
    ]),
    ("WhatsApp 机器人", PRIMARY, "群内交互 · 本地 RAG", [
        "知识库问答，带「来源：」出处引用 + 阈值拒答",
        "TT/WO 工单定级分析（命中规则 + 逐条件依据）",
        "工单统计：今天几张 P1 / 昨天未关单 / 站点 X",
        "告警码释义、压缩规则、级别规则表查询（不走 LLM）",
        "站点实时告警状态查询",
        "P1 / UME 服务器告警推送（每分钟，含图片/文档/回执）",
    ]),
]
cw, gap = 3.86, 0.21
x0, y0, head_h = 0.667, 1.36, 0.92
list_h = 3.72
for i, (name, color, stat, feats) in enumerate(cols):
    cx = x0 + i * (cw + gap)
    hd = add_box(s, cx, y0, cw, head_h, fill=color)
    box_text(hd, [[(name, 15, True, WHITE)], [(stat, 10, False, RGBColor(0xD7,0xE6,0xF5))]],
             align=PP_ALIGN.CENTER, line_spacing=1.15)
    lb = add_box(s, cx, y0 + head_h, cw, list_h, fill=LIGHT)
    paras = []
    for f in feats:
        paras.append([("▪ ", 10, True, ACCENT), (f, 10, False, BODY)])
    box_text(lb, paras, anchor=MSO_ANCHOR.TOP, line_spacing=1.14, mt=0.14, ml=0.16)
    # 段落间距
    tf = lb.text_frame
    for p in tf.paragraphs:
        p.space_after = Pt(6)

# 底部 KPI 条
ky = y0 + head_h + list_h + 0.18
kpi = add_box(s, x0, ky, cw * 3 + gap * 2, 0.62, fill=DEEP)
stats = [("3", "大子系统"), ("1", "统一入口"), ("59", "功能页面路由"), ("72", "登记定时任务"), ("8", "worker 分组")]
seg = (cw * 3 + gap * 2) / len(stats)
kpi_runs = []
for i, (num, lab) in enumerate(stats):
    kpi_runs.append([(num, 20, True, ACCENT), ("  " + lab, 11, False, WHITE)])
    if i < len(stats) - 1:
        kpi_runs.append([("   |   ", 14, False, PRIMARY)])
box_text(kpi, [ [r for pair in kpi_runs for r in pair] ], align=PP_ALIGN.CENTER)
footer(s, 3)


# ---------- 保存（占用则加 _序号）----------
out_dir = os.path.dirname(os.path.abspath(__file__))
base = "运维工具平台_3页内部汇报"
path = os.path.join(out_dir, base + ".pptx")
n = 1
while True:
    try:
        prs.save(path)
        break
    except PermissionError:
        path = os.path.join(out_dir, "%s_%d.pptx" % (base, n)); n += 1
        if n > 20:
            raise

print("已生成：", path)
print("总耗时(秒)：%.2f" % (time.time() - _t0))

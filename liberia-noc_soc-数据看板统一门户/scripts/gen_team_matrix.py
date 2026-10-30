#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
gen_team_matrix.py —— 由《新看板设计.xlsx》生成团队门户的可见性矩阵
================================================================================
用途
----
`v3/team_portal/` 下的五个团队门户（/v3/fo_portal/、/v3/bo_portal/、
/v3/flm_portal/、/v3/smc_portal/、/v3/cxo_portal/）每个页面只显示该团队在
《新看板设计.xlsx》里打勾（√）的那几行内容。

本脚本是那份 Excel 与门户之间的**唯一转换入口**：
Excel 是业务需求的真相源，本脚本把它翻译成 `assets/team-matrix.js`
（window.OLBR_TEAM_MATRIX），门户运行时只读那一份。

为什么要有这一层（而不是把 √ 直接写进 JS）
--------------------------------------
Excel 里有一列一列的勾，人工誊抄进代码必然出错，而且 Excel 改��后没人知道
代码也要改。本脚本保证两者**可重复地**对上：改 Excel → 重跑本脚本 → 提交
生成的 team-matrix.js，diff 一眼能看出需求变了哪几格。

映射表（Excel 的 Detail 列 → 门户内部键）在本文件里，是**唯一需要人工维护**
的地方；每一行都注明了它对应门户里的哪个组件。

用法
----
    python scripts/gen_team_matrix.py                # 写 v3/team_portal/assets/team-matrix.js
    python scripts/gen_team_matrix.py --check        # 只比对，不写（CI 用）
    python scripts/gen_team_matrix.py --xlsx <路径>  # 指定 Excel（默认桌面那份）

依赖：openpyxl
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_PATH = os.path.join(ROOT, "v3", "team_portal", "assets", "team-matrix.js")
DEFAULT_XLSX = os.path.join(os.path.expanduser("~"), "Desktop", "新看板设计.xlsx")

# --------------------------------------------------------------------------
# 团队列：Excel 表头 → 门户团队 id
# --------------------------------------------------------------------------
TEAMS = [
    ("ZTE FO Team", "fo"),
    ("ZTE BO Team", "bo"),
    ("ZTE FLM Team", "flm"),
    ("Orange SMC", "smc"),
    ("Orange CXO", "cxo"),
]

# --------------------------------------------------------------------------
# Excel 的 Detail 文案 → (域键, 子键)
#
# 域键与门户代码里的取用点一一对应：
#   qc       → #band   Daily Operation 六个实时指标卡
#   kpi      → #kpi    Network Status 指标带
#   bf       → #kpi    Network Benchmark 基准行
#   view     → #views6 Domain Dashboard 六个视图列
#   map      → #l0Map  GIS MAP 三个地图页签
#   qa       → #qaSlot Knowledge Q&A 两个页签 + 右下角问答助手
#   report   → #emailSlot Auto Report 邮件附件清单
#   oss      → #ossSlot OSS Portal Login 卡片
#   complaint→ #complaint 客户投诉查询
#   escalation→#esc     升级机制
#   feedback → #fbSlot  用户反馈
# --------------------------------------------------------------------------
DETAIL_MAP = {
    # --- 1 Daily Operation -------------------------------------------------
    "Alarm": ("qc", "alarm"),
    "TT": ("qc", "tt"),
    "WO": ("qc", "wo"),
    "CR": ("qc", "cr"),
    "PMT": ("qc", "pmt"),
    # ⚠️ "SPMS" 不在这里：它在第 1 域是指标、第 4 域是看板，靠 DETAIL_BY_DOMAIN 消歧。
    # --- 2 Network Status --------------------------------------------------
    # Excel 写的是「CXO View（ User/Traffic/Throughput)」，即总流量/活跃用户/视频速率。
    # ⚠️ 这里的键必须写成**归一化之后**的样子（半角括号 + 原来的空格）：
    #    norm() 会把全角括号换成半角，若这里写全角就永远匹配不上。
    "CXO View( User/Traffic/Throughput)": ("kpi", "rich"),
    "Availability(2G/3G/4G)": ("kpi", "avail"),
    # --- 3 Network Benchmark -----------------------------------------------
    "Speedtest": ("bf", "speed"),
    "Meta": ("bf", "meta"),
    # --- 4 Domain Dashboard → 见 DETAIL_BY_DOMAIN（这一域全部需要按域名消歧）---
    # --- 5 GIS MAP ---------------------------------------------------------
    "Alarm MAP": ("map", "gis"),
    "Person MAP": ("map", "person"),
    "MW MAP": ("map", "mwRealTime"),
    # --- 6 Knowledge Q&A ---------------------------------------------------
    "TT/Alarm Analysis": ("qa", "eflow"),
    "Knowledge O&A": ("qa", "rag"),
    "Quick Q&A": ("qa", "assistant"),
    # --- 7 Auto-report -----------------------------------------------------
    # 右值是 /api/email-reports/latest 里的 source_id。
    "Liberia Site-Down 8H Report Email": ("report", "liberia_8h"),
    "Liberia Site-Down 1H Report Email": ("report", "liberia_1h"),
    "Battery KPI Email": ("report", "battery"),
    "TTs and MTTR Report Generate": ("report", "tt_mttr"),
    "Packet Loss Daily Report Email": ("report", "packet_loss"),
    "SpareParts Report Email": ("report", "sp_spareparts"),
    "Comsumables Report Email": ("report", "sp_consumables"),
    "RAN UME Daily Report": ("report", "ran_availability"),
    "MS WOs SLA Daily Report Email": ("report", "ms_wo_sla"),
    "MS Contract KPIs Daily Report Email": ("report", "ms_contract"),
    # --- 8 OSS Portal Login ------------------------------------------------
    # 右值是 team-scope.js 里的 OSS 槽位名（一个槽位可对应多条目录条目，
    # 例如 NMSCCN 同时覆盖「ZTE UME NMS」与「CCN UME NMS」两条）。
    "Portal Login (NMS Portal One-click Login)": ("oss", "portalLogin"),
    "ZTE UME NMSCCN": ("oss", "nmsccn"),
    "UME NMSiPRAN": ("oss", "ipran"),
    "UME NMSMW": ("oss", "mw"),
    "UME NMSFW UMC (Firewall)": ("oss", "fwumc"),
    "VMAX CXO Dashboard": ("oss", "vmaxcxo"),
    "UME iMonitor Screen": ("oss", "imonitor"),
    "eFlow Alarm System": ("oss", "eflow"),
    "RAIS Permission Platform": ("oss", "rais"),
    "DC Server": ("oss", "dcserver"),
    # --- 9~11 无 Detail 文本的域 -------------------------------------------
    "": None,  # 占位，实际由 DOMAIN_ROWS 处理
}

# 「Domain」列上、Detail 为空的三个域（Excel 第 44~46 行）。
# Excel 里它们只有 Domain 没有 Detail，用域名直接匹配。
DOMAIN_ONLY_MAP = {
    "Customer complaint": ("complaint", "vmax"),
    "Escalation Matrix": ("escalation", "esc"),
    "User Feedback": ("feedback", "fb"),
}

# --------------------------------------------------------------------------
# 需要按 Domain 消歧的 Detail 文案
# --------------------------------------------------------------------------
# 为什么必须消歧：Excel 里有两处 Detail 叫 "SPMS" ——
#   · 第 1 域「Daily Operation」里的 SPMS = 备件出入库（未结单量）→ QC 指标卡
#   · 第 4 域「Domain Dashboard」里的 SPMS = 备件管理看板 → 视图列
# 同一个词在两个域指两件不同的事，只看 Detail 无法区分，故按 (Domain, Detail) 查表。
#
# 右值的 **view** 是门户目录里的分组 id（v3/olbrportal 的 V6_GROUPS / catalog.groups）。
# Excel 的叫法与分组 id 不一一对应：PD View 对应目录里的 'MS View'，
# SPMS 对应 'SP View'（备件管理），这里显式翻译，不靠字符串猜测。
DETAIL_BY_DOMAIN = {
    ("Daily Operation", "SPMS"): ("qc", "spms"),
    ("Domain Dashboard", "CXO"): ("view", "CXO View"),
    ("Domain Dashboard", "PD"): ("view", "MS View"),
    ("Domain Dashboard", "BO"): ("view", "BO View"),
    ("Domain Dashboard", "FO"): ("view", "FO View"),
    ("Domain Dashboard", "FLM"): ("view", "FLM View"),
    ("Domain Dashboard", "SPMS"): ("view", "SP View"),
}


def norm(s) -> str:
    """去空白 + 全角括号归一，让 Detail 文案的匹配不被排版细节卡住。"""
    s = str(s or "").strip()
    return s.replace("（", "(").replace("）", ")").replace("　", " ")


def read_matrix(xlsx_path: str):
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError:
        sys.exit("需要 openpyxl：pip install openpyxl")

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["Sheet1"] if "Sheet1" in wb.sheetnames else wb.worksheets[0]

    header = [norm(ws.cell(1, c).value) for c in range(1, ws.max_column + 1)]
    col_of = {}
    for label, tid in TEAMS:
        for i, h in enumerate(header):
            if h == label:
                col_of[tid] = i + 1
                break
        else:
            sys.exit("Excel 表头里找不到团队列：%s" % label)

    # 矩阵结构：{域键: {子键: [有勾的团队 id, ...]}}
    matrix: dict[str, dict[str, list[str]]] = {}

    def mark(domain: str, sub: str, team: str):
        matrix.setdefault(domain, {}).setdefault(sub, [])
        if team not in matrix[domain][sub]:
            matrix[domain][sub].append(team)

    current_domain = ""
    for r in range(2, ws.max_row + 1):
        domain_cell = norm(ws.cell(r, 2).value)
        detail_cell = norm(ws.cell(r, 3).value)
        if domain_cell:
            current_domain = domain_cell

        # 优先用 Detail 精确匹配；没有 Detail 时退回按 Domain 匹配。
        key = None
        if detail_cell:
            # ① 需要消歧的（Domain, Detail）优先 —— 它比裸 Detail 更具体。
            key = DETAIL_BY_DOMAIN.get((current_domain, detail_cell))
            # ② 裸 Detail 匹配（不依赖 Domain 的那些）。
            if not key:
                key = DETAIL_MAP.get(detail_cell)
        elif current_domain in DOMAIN_ONLY_MAP:
            key = DOMAIN_ONLY_MAP[current_domain]

        if not key:
            continue
        d, sub = key
        for tid, col in col_of.items():
            if norm(ws.cell(r, col).value) == "√":
                mark(d, sub, tid)

    return matrix


def _resolve_by_domain(domain: str, detail: str) -> tuple[str, str] | None:
    """兼容旧调用点：新逻辑已并入 read_matrix 的 DETAIL_BY_DOMAIN 查表。"""
    return DETAIL_BY_DOMAIN.get((domain, detail))


def render_js(matrix: dict) -> str:
    """生成 team-matrix.js。"""
    payload = json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True)
    body = io.StringIO()
    body.write("/* ============================================================================\n")
    body.write("   team-matrix.js —— 团队门户可见性矩阵（**生成文件，勿手改**）\n")
    body.write("   ----------------------------------------------------------------------------\n")
    body.write("   由 scripts/gen_team_matrix.py 从《新看板设计.xlsx》生成。\n")
    body.write("   改需求请改 Excel 后重跑该脚本，不要直接编辑本文件 ——\n")
    body.write("   手改会在下次重跑时被静默覆盖。\n")
    body.write("\n")
    body.write("   结构：{ 域键: { 子键: [有勾的团队 id, ...] } }\n")
    body.write("   域键与门户组件的对应关系见 gen_team_matrix.py 里的 DETAIL_MAP 注释。\n")
    body.write("   ========================================================================== */\n")
    body.write("(function () {\n")
    body.write("  'use strict';\n")
    body.write("  window.OLBR_TEAM_MATRIX = ")
    body.write(payload)
    body.write(";\n")
    body.write("})();\n")
    return body.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default=DEFAULT_XLSX)
    ap.add_argument("--check", action="store_true", help="只比对现有文件，不写入")
    args = ap.parse_args()

    if not os.path.exists(args.xlsx):
        sys.exit("找不到 Excel：%s" % args.xlsx)

    matrix = read_matrix(args.xlsx)
    js = render_js(matrix)

    if args.check:
        if not os.path.exists(OUT_PATH):
            print("team-matrix.js 不存在，需要生成")
            return 1
        with open(OUT_PATH, "r", encoding="utf-8") as f:
            if f.read() != js:
                print("team-matrix.js 与 Excel 不一致，请重跑 gen_team_matrix.py")
                return 1
        print("team-matrix.js 与 Excel 一致")
        return 0

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(js)
    print("已写入 %s" % OUT_PATH)
    for domain, subs in matrix.items():
        for sub, teams in subs.items():
            print("  %-10s %-18s %s" % (domain, sub, ",".join(teams)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

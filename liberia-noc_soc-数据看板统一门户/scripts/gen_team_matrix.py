#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
gen_team_matrix.py —— 由**仓库内的唯一真相源**生成团队门户的可见性矩阵
================================================================================
真相源
------
`v3/team_portal/scope-map.json` 是**唯一**需要人工维护的文件：
它把「Excel 里那一行」翻译成「门户里的哪个组件」，并保存当前生效的勾选矩阵。

    scope-map.json
      ├─ domains[].items[].excel  → Excel 的 Detail 文案（匹配用）
      ├─ domains[].items[].key    → 门户内部标识（矩阵与渲染点都用它）
      ├─ domains[].items[].urlPatterns → OSS 槽位 → 目录条目的匹配依据
      └─ matrix                   → 当前生效的勾选矩阵

本脚本从它生成 `v3/team_portal/assets/team-matrix.js`（window.OLBR_TEAM_MATRIX），
门户运行时只读那一份。**生成物勿手改** —— 手改会在下次重跑时被静默覆盖。

Excel 的角色
------------
Excel（各团队看板内容清单）只是 `scope-map.json` 里 `matrix` 段的**编辑器**：
用 `--import-excel` 从 Excel 把勾选状态导回 `matrix` 段，然后提交 JSON。
这样做的好处：
  · 仓库里有可 diff、可评审、可复现的真相源（不再依赖某人桌面上的一份 xlsx）；
  · Excel 里新增一行内容时，脚本会**报孤儿行**（见下），逼人把它登记进 scope-map.json。

孤儿行检测（2026-10-30 加）
--------------------------
此前 Excel 里新增一行内容、而映射表没跟上时，脚本**静默跳过**那一行 ——
门户看上去就是「那一项没显示」，没人知道是需求没配还是代码漏了。
现在：Excel 里出现 `scope-map.json` 未登记的 Detail 文案 → 打印**行号 + 文案**
并以非零退出码结束。`--check` 与 `--import-excel` 都会跑这项检测。

用法
----
    python scripts/gen_team_matrix.py                 # 生成 assets/team-matrix.js
    python scripts/gen_team_matrix.py --check         # 只比对，不写盘（CI 用）
    python scripts/gen_team_matrix.py --import-excel   # 从 Excel 导入勾选状态到 scope-map.json
    python scripts/gen_team_matrix.py --import-excel --xlsx <路径>
    python scripts/gen_team_matrix.py --check-excel    # 只跑孤儿行检测

依赖：openpyxl（仅 --import-excel / --check-excel 需要）
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
# 钩子（.git/hooks/pre-commit -> check-team-scope.mjs）与 CI 里 stdout 是管道，
# Windows 下 Python 默认按 cp1252 编码，打印中文/✓ 会抛 UnicodeEncodeError 让
# 校验误判失败（校验本身是通过的）。见 .qoder/rules/shell_safe.md 第 2 条。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_PATH = os.path.join(ROOT, "v3", "team_portal", "assets", "team-matrix.js")
SCOPE_MAP_JS_PATH = os.path.join(ROOT, "v3", "team_portal", "assets", "team-scope-map.js")
SCOPE_MAP_PATH = os.path.join(ROOT, "v3", "team_portal", "scope-map.json")
DEFAULT_XLSX = os.path.join(os.path.expanduser("~"), "Desktop", "新看板设计.xlsx")


# --------------------------------------------------------------------------
# 真相源读取
# --------------------------------------------------------------------------
def load_scope_map(path: str = SCOPE_MAP_PATH) -> dict:
    if not os.path.exists(path):
        sys.exit("找不到真相源文件：%s" % path)
    with io.open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for field in ("teams", "domains", "matrix"):
        if field not in data:
            sys.exit("scope-map.json 缺字段：%s" % field)
    return data


def all_domains(scope: dict) -> list:
    """domains + extra_domains。

    extra_domains 里的域不在 Excel 里（辅助入口 / 归档区这类结构性区块），
    但它们同样受矩阵控制，故对账与生成时必须与 domains 同等对待 ——
    漏掉的话，那两个区块会悄悄地对所有团队显示。
    """
    return list(scope.get("domains", [])) + list(scope.get("extra_domains", []) or [])


def team_ids(scope: dict) -> list[str]:
    return [t["id"] for t in scope["teams"]]


# --------------------------------------------------------------------------
# Excel 解析
# --------------------------------------------------------------------------
def norm(s) -> str:
    """去空白 + 全角括号归一，让 Detail 文案的匹配不被排版细节卡住。"""
    s = str(s or "").strip()
    return s.replace("（", "(").replace("）", ")").replace("　", " ")


def build_excel_lookup(scope: dict) -> dict:
    """从 scope-map.json 构造 Excel 文案 → (域键, 子键) 的查表。

    ⚠️ 为什么必须按 (Domain, Detail) 查表：Excel 里有两处 Detail 叫 "SPMS" ——
      · 第 1 域「Daily Operation」里的 SPMS = 备件出入库（未结单量）→ QC 指标卡
      · 第 4 域「Domain Dashboard」里的 SPMS = 备件管理看板 → 视图列
    同一个词在两个域指两件不同的事，只看 Detail 无法区分。
    """
    lookup: dict[tuple[str, str], tuple[str, str]] = {}
    for dom in all_domains(scope):
        for item in dom["items"]:
            detail = norm(item.get("excel") or "")
            if not detail:
                continue
            lookup[(norm(dom["excelDomain"]), detail)] = (dom["key"], item["key"])
    return lookup


def read_excel_matrix(scope: dict, xlsx_path: str) -> tuple[dict, list[tuple[int, str, str]]]:
    """读 Excel 的勾选状态。

    返回 (matrix, orphans)：
      · matrix —— {域键: {子键: [有勾的团队 id]}}
      · orphans —— [(行号, Domain, Detail)]，scope-map.json 未登记的行
    """
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError:
        sys.exit("需要 openpyxl：pip install openpyxl")

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["Sheet1"] if "Sheet1" in wb.sheetnames else wb.worksheets[0]

    header = [norm(ws.cell(1, c).value) for c in range(1, ws.max_column + 1)]
    col_of: dict[str, int] = {}
    for team in scope["teams"]:
        label = norm(team["excelColumn"])
        if label not in header:
            sys.exit("Excel 表头里找不到团队列：%s" % team["excelColumn"])
        col_of[team["id"]] = header.index(label) + 1

    lookup = build_excel_lookup(scope)
    # 「只有 Domain 没有 Detail」的域（scope-map.json 里 domainOnly=true）
    domain_only = {
        norm(d["excelDomain"]): (d["key"], d["items"][0]["key"])
        for d in all_domains(scope)
        if d.get("domainOnly")
    }

    matrix: dict[str, dict[str, list[str]]] = {}
    orphans: list[tuple[int, str, str]] = []

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

        key = None
        if detail_cell:
            # ① (Domain, Detail) 精确匹配 —— 比裸 Detail 更具体
            key = lookup.get((current_domain, detail_cell))
            if not key:
                orphans.append((r, current_domain, detail_cell))
                continue
        elif current_domain in domain_only:
            key = domain_only[current_domain]
        else:
            # 既没有 Detail、Domain 也没登记 → 这一行没法映射
            if current_domain:
                orphans.append((r, current_domain, ""))
            continue

        d, sub = key
        for tid, col in col_of.items():
            if norm(ws.cell(r, col).value) == "√":
                mark(d, sub, tid)

    return matrix, orphans


# --------------------------------------------------------------------------
# 孤儿行检测
# --------------------------------------------------------------------------
def report_orphans(orphans: list[tuple[int, str, str]], xlsx_path: str) -> int:
    if not orphans:
        print("✓ 孤儿行检测通过：Excel 里的每一行都已登记进 scope-map.json。")
        return 0
    print("✗ 发现 %d 行 Excel 内容未登记进 scope-map.json：" % len(orphans), file=sys.stderr)
    for row, domain, detail in orphans:
        label = detail or "（无 Detail，按 Domain 匹配）"
        print("    第 %d 行 · Domain=%r · Detail=%r" % (row, domain, label), file=sys.stderr)
    print(
        "\n处理办法：\n"
        "  ① 在 v3/team_portal/scope-map.json 的对应 domain 里补一个 item\n"
        "     （key = 门户内部标识，excel = Excel 那一行的 Detail 文案）\n"
        "  ② 若这一行**不该**出现在门户上，直接从 Excel 里删掉\n"
        "  ③ 然后重跑：python scripts/gen_team_matrix.py --import-excel",
        file=sys.stderr,
    )
    print("Excel：%s" % xlsx_path, file=sys.stderr)
    return 1


# --------------------------------------------------------------------------
# 矩阵规范化与校验
# --------------------------------------------------------------------------
def normalize_matrix(scope: dict, matrix: dict) -> dict:
    """把矩阵规范化成「域键 → 子键 → 团队列表」，并剔除未知项。

    未知项的处理：
      · 团队 id 不在 teams 白名单里 → 剔除（脏数据不该把内容放给不存在的团队）
      · 域键/子键不在 scope-map.json 里 → 剔除
    剔除后的矩阵**只包含已登记的项**，这正是「缺项 = 不显示」的语义基础。
    """
    known_domains = {d["key"]: d for d in all_domains(scope)}
    valid_teams = set(team_ids(scope))
    out: dict[str, dict[str, list[str]]] = {}
    for dom_key, subs in matrix.items():
        if dom_key not in known_domains:
            continue
        valid_subs = {i["key"] for i in known_domains[dom_key]["items"]}
        for sub, teams in subs.items():
            if sub not in valid_subs:
                continue
            kept = [t for t in teams if t in valid_teams]
            if kept:
                out.setdefault(dom_key, {})[sub] = kept
    return out


def validate_matrix(scope: dict, matrix: dict) -> list[str]:
    """返回问题清单（空 = 通过）。"""
    problems: list[str] = []
    known_domains = {d["key"]: d for d in all_domains(scope)}
    valid_teams = set(team_ids(scope))
    for dom_key, subs in matrix.items():
        if dom_key not in known_domains:
            problems.append("矩阵里出现未登记的域：%s" % dom_key)
            continue
        valid_subs = {i["key"] for i in known_domains[dom_key]["items"]}
        for sub, teams in subs.items():
            if sub not in valid_subs:
                problems.append("域 %s 里出现未登记的项：%s" % (dom_key, sub))
            for t in teams:
                if t not in valid_teams:
                    problems.append("域 %s / 项 %s 里出现未知团队：%s" % (dom_key, sub, t))
    return problems


# --------------------------------------------------------------------------
# 生成物渲染
# --------------------------------------------------------------------------
def render_js(scope: dict, matrix: dict) -> str:
    """生成 team-matrix.js（矩阵）与 team-scope-map.js（作用域映射）。

    两个生成物**同源**（都来自 scope-map.json），刻意放两个文件：
      · team-matrix.js    —— 纯数据（勾了哪些），体积小、被 olbr.js 与 team-scope.js 读
      · team-scope-map.js —— 纯映射（OSS 槽位 → 目录 url 片段），只有 team-scope.js 读
    分开的好处：矩阵变了不必重传映射，映射变了不必重传矩阵；
    且两者都**不含代码**，被手改的风险面比「一个文件里混着代码与数据」小得多。
    """
    payload = json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True)
    body = io.StringIO()
    body.write("/* ============================================================================\n")
    body.write("   team-matrix.js —— 团队门户可见性矩阵（**生成文件，勿手改**）\n")
    body.write("   ----------------------------------------------------------------------------\n")
    body.write("   由 scripts/gen_team_matrix.py 从 v3/team_portal/scope-map.json 生成。\n")
    body.write("   改需求请改 scope-map.json（或改 Excel 后跑 --import-excel），\n")
    body.write("   不要直接编辑本文件 —— 手改会在下次重跑时被静默覆盖。\n")
    body.write("\n")
    body.write("   结构：{ 域键: { 子键: [有勾的团队 id, ...] } }\n")
    body.write("   域键与门户组件的对应关系见 scope-map.json。\n")
    body.write("   ========================================================================== */\n")
    body.write("(function () {\n")
    body.write("  'use strict';\n")
    body.write("  window.OLBR_TEAM_MATRIX = ")
    body.write(payload)
    body.write(";\n")
    body.write("})();\n")
    return body.getvalue()


def render_scope_map_js(scope: dict) -> str:
    """生成 team-scope-map.js：域 → 子键 → { urlPatterns }。

    ⚠️ 只有 OSS 域需要 urlPatterns（槽位 → 门户目录条目的匹配依据）。
    其它域的 items 没有 urlPatterns —— 它们靠 key 直接对应门户组件。
    """
    out: dict[str, dict[str, dict]] = {}
    for dom in all_domains(scope):
        items: dict[str, dict] = {}
        for item in dom["items"]:
            entry: dict = {}
            pats = item.get("urlPatterns")
            if pats:
                entry["urlPatterns"] = list(pats)
            items[item["key"]] = entry
        out[dom["key"]] = items

    payload = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)
    body = io.StringIO()
    body.write("/* ============================================================================\n")
    body.write("   team-scope-map.js —— 团队门户的**作用域映射**（**生成文件，勿手改**）\n")
    body.write("   ----------------------------------------------------------------------------\n")
    body.write("   由 scripts/gen_team_matrix.py 从 v3/team_portal/scope-map.json 生成。\n")
    body.write("   与 team-matrix.js 同源 —— 一个说「勾了哪些」，一个说「怎么对应到门户组件」。\n")
    body.write("\n")
    body.write("   结构：{ 域键: { 子键: { urlPatterns?: [...] } } }\n")
    body.write("   urlPatterns 只在 OSS 域出现：它是「槽位 → 门户目录条目」的匹配依据\n")
    body.write("   （用 url 片段而非标题 —— 标题在目录里可编辑，模糊匹配会突然失效）。\n")
    body.write("   ========================================================================== */\n")
    body.write("(function () {\n")
    body.write("  'use strict';\n")
    body.write("  window.OLBR_SCOPE_MAP = ")
    body.write(payload)
    body.write(";\n")
    body.write("})();\n")
    return body.getvalue()


def write_scope_map(scope: dict, matrix: dict, path: str = SCOPE_MAP_PATH) -> None:
    """把矩阵写回 scope-map.json（保留其它段落的排版与注释键）。

    ⚠️ 用 json 重新序列化会丢掉原文件的缩进风格差异，故这里读原文做**文本替换**：
    只替换 "matrix" 那一段，其余字节不动 —— 注释键（_comment*）必须原样保留。
    """
    with io.open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    data = json.loads(raw)
    old = json.dumps(data["matrix"], ensure_ascii=False, indent=2)
    new = json.dumps(matrix, ensure_ascii=False, indent=2)
    if old not in raw:
        # 缩进不同时退化为「整体重写」（仍然只改 matrix 的值）
        data["matrix"] = matrix
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(raw.replace(old, new, 1))


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default=DEFAULT_XLSX, help="Excel 路径（默认桌面那份）")
    ap.add_argument("--check", action="store_true", help="只比对现有生成物，不写盘（CI 用）")
    ap.add_argument("--import-excel", action="store_true", help="从 Excel 导入勾选状态到 scope-map.json")
    ap.add_argument("--check-excel", action="store_true", help="只跑孤儿行检测，不写盘")
    args = ap.parse_args()

    scope = load_scope_map()

    # —— Excel 相关分支 ——
    if args.import_excel or args.check_excel:
        if not os.path.exists(args.xlsx):
            sys.exit("找不到 Excel：%s" % args.xlsx)
        matrix, orphans = read_excel_matrix(scope, args.xlsx)
        rc = report_orphans(orphans, args.xlsx)
        if rc != 0:
            return rc
        if args.check_excel:
            return 0
        matrix = normalize_matrix(scope, matrix)
        problems = validate_matrix(scope, matrix)
        if problems:
            print("✗ 导入的矩阵有问题：", file=sys.stderr)
            for p in problems:
                print("    " + p, file=sys.stderr)
            return 1
        write_scope_map(scope, matrix)
        print("✓ 已把 Excel 的勾选状态导入 %s" % SCOPE_MAP_PATH)
        print("  （请 git diff 复核后提交；下游还需重跑本脚本生成 team-matrix.js）")
        return 0

    # —— 常规生成 / 比对 ——
    raw_matrix = scope["matrix"]
    problems = validate_matrix(scope, raw_matrix)
    if problems:
        print("✗ scope-map.json 的 matrix 段有问题：", file=sys.stderr)
        for p in problems:
            print("    " + p, file=sys.stderr)
        return 1

    matrix = normalize_matrix(scope, raw_matrix)
    js = render_js(scope, matrix)
    scope_map_js = render_scope_map_js(scope)

    if args.check:
        ok = True
        for path, content, label in (
            (OUT_PATH, js, "team-matrix.js"),
            (SCOPE_MAP_JS_PATH, scope_map_js, "team-scope-map.js"),
        ):
            if not os.path.exists(path):
                print("%s 不存在，需要生成" % label, file=sys.stderr)
                ok = False
                continue
            with io.open(path, "r", encoding="utf-8") as f:
                if f.read() != content:
                    print(
                        "%s 与 scope-map.json 不一致，请重跑 gen_team_matrix.py" % label,
                        file=sys.stderr,
                    )
                    ok = False
        if not ok:
            return 1
        print("✓ team-matrix.js 与 team-scope-map.js 均与 scope-map.json 一致")
        return 0

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with io.open(OUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(js)
    with io.open(SCOPE_MAP_JS_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(scope_map_js)
    print("✓ 已写入 %s" % OUT_PATH)
    print("✓ 已写入 %s" % SCOPE_MAP_JS_PATH)
    for domain, subs in matrix.items():
        for sub, teams in subs.items():
            print("  %-11s %-18s %s" % (domain, sub, ",".join(teams)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

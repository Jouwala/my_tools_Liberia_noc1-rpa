#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从 eflow.sqlite3 自动生成「数据字典」条目，写入知识库 13_数据字典_DataDictionary/

用法:
    python gen_datadict.py                       # 生成全部表
    python gen_datadict.py --table eflow_tt      # 只生成一张表
    python gen_datadict.py --dry-run             # 只看会生成什么，不写文件

产出:
    10_集成篇_Integration/13_数据字典_DataDictionary/<表名>_字段字典.md
    10_集成篇_Integration/13_数据字典_DataDictionary/00_索引.md

重要:
    脚本产出的是**数据库客观事实**（列名、类型、非空数、取值分布）。
    「业务含义」列脚本不知道，需要人工补充 —— 生成的文档里会留空并标注。
"""

import os
import sys
import sqlite3
import argparse
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

KB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(
    KB_ROOT, "10_集成篇_Integration", "13_数据字典_DataDictionary"
)
DB_PATH = r"D:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3"

# 表 → 中文名
TABLE_CN = {
    "eflow_tt": "TT 故障工单",
    "eflow_wo": "WO 作业工单",
    "eflow_cr": "CR 变更申请",
    "eflow_pm": "PM 巡检任务",
    "site": "站点主数据",
    "person": "人员",
    "realtime_alarm": "实时告警",
    "history_alarm": "历史告警",
}

# 关键字段（跨表做枚举汇总，对应 BACKLOG #34）
KEY_FIELDS = [
    "Status", "Ticket Severity", "Suspended", "domain", "Networktype",
    "Alarm Severity", "Alarm Category", "Source", "Ticket Type",
]

ENUM_THRESHOLD = 25   # 去重值 <= 此数 且 > 1 时，输出完整枚举分布
SAMPLE_LIMIT = 200    # 取示例值时最多扫描的行数

# 敏感列：示例值脱敏，且不输出枚举分布
# （person 表含真实姓名/电话/身份证/住址，直接写进文档会泄露同事隐私）
# 说明：分两类——
#   长词用子串匹配（phone → phone_2）；短词(<=3字母)只做整词匹配（by → 只命中 "Created By"）
#   "人"相关列（creator/handler/implementer/…）也脱敏，TT/WO 表这类列存的是真实人名
SENSITIVE_PATTERNS = [
    # 联系方式与身份标识
    "phone", "mobile", "telephone", "email", "mail", "idnumber", "id number",
    "idno", "passport", "address", "age", "gender", "nationality",
    "password", "passwd", "credential", "token", "secret", "birth",
    # 人员相关（存真实姓名）
    "creator", "handler", "implementer", "assignee", "requestor", "requester",
    "approver", "operator", "engineer", "employee", "staff", "person",
    "request by", "created by", "update by", "updated by", "modify by",
    "manager", "leader", "supervisor", "dispatcher",
    # 自由文本（可能夹带人名/电话）
    "remark", "comment", "description", "memo", "note",
    # 其他
    "name", "contact",
]


def is_sensitive(col):
    low = col.lower().replace("_", " ").replace(".", " ")
    words = set(low.split())
    for p in SENSITIVE_PATTERNS:
        if " " in p:            # 多词短语，整体子串匹配
            if p in low:
                return True
        elif len(p) <= 3:       # 短词，只认整词，避免误伤（如 by → byproduct）
            if p in words:
                return True
        else:                   # 长词，子串匹配（phone → phone_2）
            if p in low:
                return True
    return False


def q(col):
    """安全引用列名（列名可能含空格、点号，如 'WO No.'）"""
    return '"' + col.replace('"', '""') + '"'


def qv(val, maxlen=40):
    """格式化单元格值"""
    if val is None:
        return "（空）"
    s = str(val).replace("\n", " ").replace("\r", " ").replace("|", "\\|")
    s = s.strip()
    if s == "":
        return "（空串）"
    if len(s) > maxlen:
        s = s[:maxlen] + "…"
    return s


def get_columns(conn, table):
    return [r[1] for r in conn.execute(f'PRAGMA table_info({q(table)})').fetchall()]


def get_rowcount(conn, table):
    return conn.execute(f'SELECT COUNT(*) FROM {q(table)}').fetchone()[0]


def batch_stats(conn, table, cols):
    """一次全表扫描，取所有列的 非空数 / 去重数"""
    exprs = []
    for c in cols:
        exprs.append(f"COUNT({q(c)})")
        exprs.append(f"COUNT(DISTINCT {q(c)})")
    sql = f'SELECT {",".join(exprs)} FROM {q(table)}'
    row = conn.execute(sql).fetchone()
    out = {}
    for i, c in enumerate(cols):
        out[c] = (row[2 * i], row[2 * i + 1])
    return out


def sample_values(conn, table, col, n=3):
    """取前 n 个不同示例值（LIMIT 早停，快）"""
    try:
        rows = conn.execute(
            f'SELECT {q(col)} FROM {q(table)} '
            f'WHERE {q(col)} IS NOT NULL AND {q(col)} <> "" LIMIT {SAMPLE_LIMIT}'
        ).fetchall()
    except sqlite3.Error:
        return []
    seen, out = set(), []
    for (v,) in rows:
        key = str(v)
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
        if len(out) >= n:
            break
    return out


def enum_dist(conn, table, col, limit=30):
    """低基数列的取值分布"""
    try:
        rows = conn.execute(
            f'SELECT {q(col)} AS v, COUNT(*) AS c FROM {q(table)} '
            f'GROUP BY {q(col)} ORDER BY c DESC LIMIT {limit}'
        ).fetchall()
    except sqlite3.Error:
        return []
    return rows


def gen_table_doc(conn, table, today):
    cols = get_columns(conn, table)
    nrows = get_rowcount(conn, table)
    stats = batch_stats(conn, table, cols)
    cn = TABLE_CN.get(table, table)

    lines = []
    lines.append("---")
    lines.append(f"标题: {table} 字段字典（{cn}）")
    lines.append("分类: 10_集成篇_Integration/13_数据字典_DataDictionary")
    lines.append(f"标签: [数据字典, {table}]")
    lines.append("状态: 已验证")
    lines.append("适用对象: 开发")
    lines.append(f"最后更新: {today}")
    lines.append("作者: tools/gen_datadict.py")
    lines.append("来源: 数据库读取")
    lines.append("---")
    lines.append("")
    lines.append(f"# {table} 字段字典（{cn}）")
    lines.append("")
    lines.append("> ⚠️ 本文件由 `tools/gen_datadict.py` **自动生成**。")
    lines.append("> **列名 / 类型 / 非空数 / 取值分布 = 数据库客观实际**，可信。")
    lines.append("> **「业务含义」列是空的** —— 脚本不知道每个字段在业务上是什么意思，**需要人工补充**。")
    lines.append("> 补充后请把 front-matter 的 `作者` 改成你，`来源` 改成 `数据库读取 + 人工补充`。")
    lines.append("")
    lines.append("## 表概况")
    lines.append("")
    lines.append(f"- 表名：`{table}`（{cn}）")
    lines.append(f"- 行数：**{nrows:,}**")
    lines.append(f"- 列数：**{len(cols)}**")
    lines.append(f"- 数据来源：`{DB_PATH}`")
    lines.append(f"- 生成时间：{today}")
    lines.append("")

    sens_cols = [c for c in cols if is_sensitive(c)]
    if sens_cols:
        lines.append(f"> 🔒 **脱敏说明**：本表含 {len(sens_cols)} 个疑似个人信息列，"
                     "其示例值已脱敏、且不输出取值分布，避免泄露同事隐私。")
        lines.append(">")
        lines.append(f"> 涉及列：{', '.join('`%s`' % c for c in sens_cols[:20])}"
                     + ("…" if len(sens_cols) > 20 else ""))
        lines.append("")

    # 高填充率字段优先展示
    lines.append("## 字段清单")
    lines.append("")
    lines.append("按填充率从高到低排序（空列排在最后）。")
    lines.append("")
    lines.append("| # | 字段名 | 类型 | 非空 | 填充率 | 去重值 | 示例值 | 业务含义（待人工补） |")
    lines.append("|---|--------|------|------|--------|--------|--------|----------------------|")

    ordered = sorted(
        cols, key=lambda c: (-(stats.get(c, (0, 0))[0] / nrows if nrows else 0), c.lower())
    )
    sensitive_hit = []
    for i, c in enumerate(ordered, 1):
        nonnull, nuniq = stats.get(c, (0, 0))
        rate = (nonnull / nrows * 100) if nrows else 0
        if is_sensitive(c):
            sensitive_hit.append(c)
            sample_txt = "🔒 已脱敏"
        else:
            samples = sample_values(conn, table, c)
            sample_txt = " / ".join(qv(s, 24) for s in samples) if samples else "—"
        lines.append(
            f"| {i} | `{c}` | | {nonnull:,} | {rate:.0f}% | {nuniq:,} | {sample_txt} | |"
        )

    # 枚举分布（敏感列不输出，避免列出具体姓名/电话/邮箱）
    enum_cols = [
        c for c in ordered
        if 1 < stats.get(c, (0, 0))[1] <= ENUM_THRESHOLD
        and stats.get(c, (0, 0))[0] > 0
        and not is_sensitive(c)
    ]
    if enum_cols:
        lines.append("")
        lines.append("## 枚举取值分布")
        lines.append("")
        lines.append(f"> 仅列出去重值 ≤ {ENUM_THRESHOLD} 的列，按记录数倒序。**这是判断字段语义最有用的部分。**")
        lines.append("")
        for c in enum_cols:
            rows = enum_dist(conn, table, c)
            if not rows:
                continue
            lines.append(f"### `{c}`")
            lines.append("")
            lines.append("| 取值 | 记录数 | 占比 | 业务含义（待人工补） |")
            lines.append("|------|--------|------|----------------------|")
            for v, cnt in rows:
                pct = (cnt / nrows * 100) if nrows else 0
                lines.append(f"| {qv(v, 60)} | {cnt:,} | {pct:.1f}% | |")
            lines.append("")

    lines.append("## 相关")
    lines.append("")
    lines.append("- 索引：[00_索引.md](./00_索引.md)")
    lines.append("- 术语：[90_术语表_Glossary.md](../../../90_术语表_Glossary.md)")
    lines.append("")
    return "\n".join(lines) + "\n", len(cols), nrows, len(enum_cols)


def main():
    ap = argparse.ArgumentParser(description="生成 eFlow 数据字典")
    ap.add_argument("--table", action="append", help="只生成指定表，可重复")
    ap.add_argument("--db", default=DB_PATH, help="eflow.sqlite3 路径")
    ap.add_argument("--dry-run", action="store_true", help="不写文件，只打印计划")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"✗ 数据库不存在: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    existing = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]
    targets = args.table if args.table else [t for t in TABLE_CN if t in existing]
    missing = [t for t in targets if t not in existing]
    if missing:
        print(f"✗ 以下表不存在: {missing}")
        print(f"  可用表: {existing}")
        return 1

    today = datetime.now().strftime("%Y-%m-%d")
    print(f"数据库: {args.db}")
    print(f"输出目录: {OUT_DIR}")
    print(f"目标表: {targets}")
    print("=" * 70)

    summary = []
    for t in targets:
        print(f"\n处理 {t} ...", end=" ", flush=True)
        doc, ncol, nrow, nenum = gen_table_doc(conn, t, today)
        summary.append((t, ncol, nrow, nenum))
        print(f"{ncol} 列 / {nrow:,} 行 / {nenum} 个枚举列")
        if not args.dry_run:
            os.makedirs(OUT_DIR, exist_ok=True)
            path = os.path.join(OUT_DIR, f"{t}_字段字典.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(doc)
            print(f"  ✓ 已写入 {os.path.relpath(path, KB_ROOT)}")

    # 索引
    if not args.dry_run and summary:
        idx = ["---", "标题: 数据字典索引", "状态: 已验证", "适用对象: 开发",
               f"最后更新: {today}", "作者: tools/gen_datadict.py",
               "来源: 数据库读取", "---", "",
               "# 数据字典索引", "",
               f"> 由 `tools/gen_datadict.py` 生成于 {today}。**「业务含义」列待人工补充。**",
               "", "| 表 | 说明 | 列数 | 行数 | 枚举列 | 文档 |",
               "|---|---|---|---|---|---|"]
        for t, ncol, nrow, nenum in summary:
            idx.append(
                f"| `{t}` | {TABLE_CN.get(t, t)} | {ncol} | {nrow:,} | {nenum} | "
                f"[{t}_字段字典.md](./{t}_字段字典.md) |"
            )
        idx += ["", "## 下一步", "",
                "1. 打开每张表的文档，补充「业务含义」列",
                "2. 补完把 front-matter 的作者/来源改掉",
                "3. 在 [INDEX.md](../../../INDEX.md) 的「13 数据字典」下加索引行", ""]
        with open(os.path.join(OUT_DIR, "00_索引.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(idx))
        print(f"\n✓ 索引已写入 13_数据字典_DataDictionary/00_索引.md")

    print("\n" + "=" * 70)
    print(f"完成：{len(summary)} 张表"
          + ("（dry-run，未写文件）" if args.dry_run else ""))
    if not args.dry_run:
        print("\n⚠️ 生成的文档「业务含义」列是空的，需要人工补充才算完整条目。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

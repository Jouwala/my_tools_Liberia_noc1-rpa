# -*- coding: utf-8 -*-
"""
规则缺口体检 (Rule Coverage Audit)
====================================
比对 eflow_tt 里**实际出现**的 alarm_code 与三套规则的覆盖情况：

  1. 推单规则  eflow_push_rules.xlsx  (触发步骤=FOAccept 的那批才是真正推单决策)
  2. 定级规则  eflow_TT_rules.xlsx    (状态=ACTIVE)
  3. 压缩规则  eflow_alarm_rules.xlsx (状态=ENABLED；siteAlarmCode 等参数里的码)

输出三件事：
  - 哪些实际告警码没被任一规则覆盖（= 会落兜底 / 靠人抢）
  - 重点核查 2114322696（项目里反复问到的告警码）
  - 缺口清单落 TMP/rule_coverage_audit_<时间戳>.xlsx（.gitignore 已覆盖，不入库）

与 `eflow_rules_matcher`（每天 04:20 的定时任务 `eflow_tt_rules_check`）的区别：
matcher 是**事中判定**——单条 TT 跑过来立刻判「该什么级别」；本工具是**事前体检**——
站在规则设计者的角度看「我的规则够不够用」。两者口径不重叠，是互补关系。

数据源
------
按 `MY_APP_DB_MODE` 自动跟随项目主库（见 `backend/database.py:27` 熔断开关）：
  - pg 模式：DATABASE_URL + schema 推断
  - sqlite 模式：db/app.db 本地文件
  - 不再独立读 .env 的 DATABASE_URL（避免与主进程对不上导致误诊）。

用法
----
从 my_app 项目根执行（必须有 backend/.env 或环境变量 MY_APP_DB_MODE）：

    cd d:\\01_RPA\\Task\\my_app
    python backend/services/eflow_rules/audit_rule_coverage.py

输出落 `backend/services/eflow_rules/TMP/rule_coverage_audit_<时间戳>.xlsx`，
该目录已被 .gitignore 覆盖（`Task\\my_app\\.gitignore` 的 `/TMP/` 与根规则的 `TMP/`）。
"""
from __future__ import annotations

import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

# Windows cp1252 默认编码会爆 UnicodeEncodeError（emoji/全角字符）；
# 同目录 eflow_rules_matcher.py:24 也走这行，覆盖 UTF-8。
sys.stdout.reconfigure(encoding="utf-8")

# ------------------------------------------------------------------ #
# 路径与配置
# ------------------------------------------------------------------ #
HERE = Path(__file__).resolve().parent

# 子进程从 my_app 根跑本脚本时 sys.path 不含 cwd，backend.* 找不到；
# 同目录 eflow_Push_Rule_Collector.py:28-29 已用同样手法。
_PROJECT_ROOT = HERE.parent.parent.parent  # eflow_rules/ → services/ → backend/ → my_app/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 同目录的规则表；先尝试本目录，回退 backend/services/eflow_rules（兼容从项目根运行的写法）
CANDIDATE_DIRS = [
    HERE,
    HERE / "backend" / "services" / "eflow_rules",
    HERE.parent / "backend" / "services" / "eflow_rules",
]
RULES_DIR = next(
    (d for d in CANDIDATE_DIRS if (d / "eflow_TT_rules.xlsx").is_file()),
    HERE,
)

TT_RULES_XLSX = RULES_DIR / "eflow_TT_rules.xlsx"
PUSH_RULES_XLSX = RULES_DIR / "eflow_push_rules.xlsx"
ALARM_RULES_XLSX = RULES_DIR / "eflow_alarm_rules.xlsx"

# 报告/导出落 TMP（已忽略，不会污染版本库）
TMP_DIR = HERE / "TMP"
TMP_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------ #
# alarm_code 提取
# ------------------------------------------------------------------ #
# 定级规则的「条件」列形如：
#   AND | eflow_ticket_ticket_wo.alarmCode in '9970, 9980' (string)
#   OR  | eflow_ticket_ticket_wo.alarmCode = '9995' (string)
# 推单规则由 eflow_Push_Rule_Collector._fmt_rows 生成，连接词后**没有** `|`：
#   AND eflow_ticket_ticket_wo.alarmCode in '9920, 9925' (string)
# 因此用宽松正则同时兼容。
_ALARM_IN_RE = re.compile(r"alarmCode\s+(?:in|not\s+in)\s+'([^']*)'", re.IGNORECASE)
_ALARM_EQ_RE = re.compile(r"alarmCode\s*(?:=|!=|<>)\s*'([^']*)'", re.IGNORECASE)


def _norm_code(v) -> str:
    """告警码归一化：去 .0 后缀、去首尾空白、去引号。"""
    s = str(v).strip().strip("'\"")
    if s.endswith(".0"):
        s = s[:-2]
    return s


def extract_alarm_codes(cond_text) -> set[str]:
    """从条件文本抓 alarmCode 的所有字面量取值（归一化）。"""
    if cond_text is None or (isinstance(cond_text, float) and pd.isna(cond_text)):
        return set()
    s = str(cond_text)
    out: set[str] = set()
    for m in _ALARM_IN_RE.finditer(s):
        for v in m.group(1).split(","):
            v = v.strip()
            if v:
                out.add(_norm_code(v))
    for m in _ALARM_EQ_RE.finditer(s):
        v = m.group(1).strip()
        if v:
            out.add(_norm_code(v))
    return out


# ------------------------------------------------------------------ #
# 读规则
# ------------------------------------------------------------------ #
def collect_rule_codes() -> dict:
    """返回 {'push': set, 'severity': set, 'compress': set, '_counts': {...}}。"""
    codes = {"push": set(), "severity": set(), "compress": set()}
    detail = {"push": {}, "severity": {}, "compress": {}}
    counts: dict = {}

    # 推单：只看 FOAccept（真正决定推 WO/分流）；其余步骤只展示不计入覆盖
    if PUSH_RULES_XLSX.is_file():
        df = pd.read_excel(PUSH_RULES_XLSX, sheet_name="Push_Rules")
        sub = df[df["触发步骤"].astype(str).str.strip() == "FOAccept"]
        for _, r in sub.iterrows():
            for c in extract_alarm_codes(r.get("条件")):
                codes["push"].add(c)
                detail["push"].setdefault(c, []).append(str(r.get("ID")))
        counts["push_total"] = int(len(sub))

    # 定级：全部 ACTIVE
    if TT_RULES_XLSX.is_file():
        df = pd.read_excel(TT_RULES_XLSX, sheet_name="TT_Rules")
        if "状态" in df.columns:
            df = df[df["状态"].astype(str).str.upper() == "ACTIVE"]
        for _, r in df.iterrows():
            for c in extract_alarm_codes(r.get("条件")):
                codes["severity"].add(c)
                detail["severity"].setdefault(c, []).append(str(r.get("ID")))
        counts["severity_total"] = int(len(df))

    # 压缩：OUTAGE 关联规则的 siteAlarmCode / *AlarmList / alarmcodeList 参数
    if ALARM_RULES_XLSX.is_file():
        df = pd.read_excel(ALARM_RULES_XLSX, sheet_name="Alarm_Rules")
        for _, r in df.iterrows():
            if str(r.get("状态")).upper() != "ENABLED":
                continue
            params = str(r.get("参数"))
            for m in re.finditer(
                r"(?:AlarmCode|AlarmList|alarmcode|alarmcodeList)\s*\)?\s*=\s*([0-9][0-9, ]*)",
                params,
                re.IGNORECASE,
            ):
                for v in m.group(1).split(","):
                    v = v.strip()
                    if v:
                        nv = _norm_code(v)
                        codes["compress"].add(nv)
                        detail["compress"].setdefault(nv, []).append(str(r.get("规则ID")))
        if "状态" in df.columns:
            counts["compress_total"] = int((df["状态"].astype(str).str.upper() == "ENABLED").sum())

    return {"codes": codes, "detail": detail, "counts": counts}


# ------------------------------------------------------------------ #
# 读 eflow_tt 实际告警码（双模：pg / sqlite，遵循 MY_APP_DB_MODE）
# ------------------------------------------------------------------ #
def load_actual_codes() -> tuple[Counter, int]:
    """返回 (告警码 → 出现次数 Counter, 总工单数)。"""
    from backend.database import get_raw_connection

    sql = (
        "SELECT alarm_code, count(*) AS n FROM eflow_tt "
        "WHERE alarm_code IS NOT NULL AND alarm_code <> '' "
        "GROUP BY alarm_code ORDER BY n DESC"
    )
    with get_raw_connection() as conn:
        cur = conn.execute(sql)
        rows = cur.fetchall()

    cnt: Counter = Counter()
    total = 0
    for row in rows:
        # 双模都支持 row['col'] 字符串索引（sqlite3.Row / _PsycopgRow）
        code = row["alarm_code"]
        n = int(row["n"])
        cnt[_norm_code(code)] += n
        total += n
    return cnt, total


# ------------------------------------------------------------------ #
# 主流程
# ------------------------------------------------------------------ #
def _audit_one(name: str, rule_set: set, actual: Counter, total_tt: int) -> int:
    """单环节缺口分析：打印 + 返回未覆盖工单数。"""
    missing = [(code, n) for code, n in actual.items() if code not in rule_set]
    missing.sort(key=lambda x: -x[1])
    miss_tt = sum(n for _, n in missing)
    print(f"\n###### {name} 缺口 ######")
    print(
        f"  覆盖 {len(actual) - len(missing)}/{len(actual)} 个码 | "
        f"未覆盖 {len(missing)} 个码，涉及 {miss_tt} 条工单 "
        f"({miss_tt / total_tt * 100:.1f}%)"
        if total_tt else
        f"  覆盖 {len(actual) - len(missing)}/{len(actual)} 个码 | 未覆盖 {len(missing)} 个码"
    )
    if missing:
        print(f"  {'alarm_code':>14} {'工单数':>7}")
        for code, n in missing[:40]:
            print(f"  {code:>14} {n:>7}")
        if len(missing) > 40:
            print(f"  ... 其余 {len(missing) - 40} 个码省略")
    return miss_tt


def main() -> int:
    from backend.database import DB_MODE  # 触发 .env 加载 + DB_MODE 解析

    print("=" * 78)
    print("规则缺口体检 (Rule Coverage Audit)")
    print(f"规则目录: {RULES_DIR}")
    print(f"DB 模式:  {DB_MODE}")
    print("=" * 78)

    rc = collect_rule_codes()
    codes = rc["codes"]
    detail = rc["detail"]
    cnt = rc["counts"]

    print("\n规则覆盖的 alarm_code 数量：")
    print(f"  推单(FOAccept) 规则 {cnt.get('push_total', '?')} 条 → 覆盖 {len(codes['push'])} 个码")
    print(f"  定级           规则 {cnt.get('severity_total', '?')} 条 → 覆盖 {len(codes['severity'])} 个码")
    print(f"  压缩(OUTAGE)   规则 {cnt.get('compress_total', '?')} 条 → 覆盖 {len(codes['compress'])} 个码")

    actual, total_tt = load_actual_codes()
    print(f"\neflow_tt 实际：{total_tt} 条工单，{len(actual)} 个不同 alarm_code")

    print("\n" + "=" * 78)
    print("缺口分析（按实际出现次数降序，只列出现 ≥1 次的码）")
    print("=" * 78)
    _audit_one("推单规则 (FOAccept)", codes["push"], actual, total_tt)
    _audit_one("定级规则", codes["severity"], actual, total_tt)
    _audit_one("压缩规则 (OUTAGE)", codes["compress"], actual, total_tt)

    # 重点核查：项目里反复问到的告警码
    print("\n" + "=" * 78)
    print("重点核查：2114322696")
    print("=" * 78)
    for env, key in [("推单", "push"), ("定级", "severity"), ("压缩", "compress")]:
        hit = "2114322696" in codes[key]
        rules = detail[key].get("2114322696", [])
        n = actual.get("2114322696", 0)
        print(
            f"  {env}规则: {'✅ 覆盖' if hit else '❌ 未覆盖'}"
            + (f"  (规则: {rules})" if hit else "")
            + f"  | 实际工单 {n} 条"
        )

    # 导出缺口清单（落 TMP，不入库）
    out = []
    for code, n in actual.most_common():
        out.append({
            "alarm_code": code,
            "tt_count": n,
            "in_push": code in codes["push"],
            "in_severity": code in codes["severity"],
            "in_compress": code in codes["compress"],
        })
    outdf = pd.DataFrame(out)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    outp = TMP_DIR / f"rule_coverage_audit_{stamp}.xlsx"
    try:
        outdf.to_excel(outp, index=False)
        print(f"\n✓ 缺口清单已导出：{outp}")
    except Exception as e:  # noqa: BLE001
        print(f"\n!! 导出失败（可能 TMP 不可写）：{e}")

    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

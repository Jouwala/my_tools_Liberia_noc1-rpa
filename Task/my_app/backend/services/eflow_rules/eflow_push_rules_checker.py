# -*- coding: utf-8 -*-
"""eflow_push_rules_checker.py - eFlow 推单规则（TT Push Order Rule）批量评估
================================================================================

要解决的问题
------------
eFlow 应用了新的派单规则后，「这批单会怎么派」与「改了之后会变什么」无法一眼看出。
本模块把**同一套推单规则**批量套到最新一批 eflow_tt 上，逐单给出：

  · 规则判定结果 —— FOAccept 阶段命中的推单规则、目标处理人、推送路径；
  · 实际派单结果 —— 该单真实的 wo_no 与 FO Accept 环节的处理人 / 处理组；
  · **一致性差异** —— 规则说该派给 A，实际派给了 B（或规则说该建 WO，实际没有 WO）。

再配合**每周留存一份快照**，就能回答「规则改前 / 改后，逐单判定变了什么」。

模块划分（AGENTS.md 三.2：单文件不超过 500 行）
------------------------------------------------
| 文件 | 职责 |
| --- | --- |
| 本文件 `eflow_push_rules_checker.py` | 编排：取样本 → 加载规则 → 求值 → 分类 → 导出/摘要 |
| `eflow_push_rule_eval.py` | 规则求值（条件解析 / 匹配 / 未知字段范围） |
| `eflow_push_dispatch.py` | 实际派单解析 + 「规则 vs 实际」一致性分类 |
| `eflow_push_rule_history.py` | 规则的「历史建 WO 率」统计 |
| `eflow_push_snapshots.py` | 周快照与两次运行对比 |

口径（不产生第二套判定）
------------------------
| 内容 | 来源 |
| --- | --- |
| 推单规则表 | `eflow_push_rules.xlsx` 的 `Push_Rules` 工作表（`eflow_Push_Rule_Collector` 落盘） |
| 规则条件解析 / 求值 | `eflow_push_rule_eval`（内部复用 `tt_rule_evidence` + `eflow_rules_matcher`） |
| 站点属性 | `eflow_rules_matcher.load_site_attrs`（同级别规则检查，按 site_id 关联） |
| 样本 | 与 `eflow_tt_rules_check` 同一口径：created_time 最新的 N 条（默认 1000，且只取有 alarm_code 的） |

四类单（页面上各占一张卡，互斥且求和等于总数）
----------------------------------------------
  correct     规则判定与实际派单一致
  mismatch    规则判定与实际**不同**（该建 WO 却没建 / 建了却推给了别的组 / 不该建 WO 却建了）
  undecidable 命中了引用本地取不到字段的规则 —— 不算命中、也不算未命中
  unmatched   没有任何 FOAccept 推单规则适用于本单（规则真空）
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_RULES_DIR = Path(__file__).resolve().parent
PUSH_RULES_XLSX = _RULES_DIR / "eflow_push_rules.xlsx"
OUTPUT_XLSX = _RULES_DIR / "eflow_push_rules_check.xlsx"
SUMMARY_JSON = _RULES_DIR / "eflow_push_rules_check_latest.json"


# ------------------------------------------------------------------ #
# 小工具
# ------------------------------------------------------------------ #

def _s(v: Any) -> str:
    """pandas / numpy 标量 → 干净字符串（NaN / None / NaT → 空串）。"""
    if v is None:
        return ""
    try:
        import pandas as pd
        if v is pd.NaT:
            return ""
        if isinstance(v, float) and pd.isna(v):
            return ""
    except Exception:  # noqa: BLE001
        pass
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def _norm_code(v: Any) -> str:
    """告警码归一：去掉 pandas 读出来的 `.0` 尾巴（与 build_value_frame 一致）。"""
    s = _s(v)
    return s[:-2] if s.endswith(".0") else s


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(path))


# ------------------------------------------------------------------ #
# 样本
# ------------------------------------------------------------------ #

def load_sample(limit: int = 1000) -> "Any":
    """取最新 N 条 eflow_tt（与 eflow_rules_matcher.get_eflow_tt_data 同口径）。

    为什么不复用它的函数：那个函数走**裸 sqlite3.connect**（离线脚本专用，
    见 eflow_rules_matcher.py:38-43 的说明）。本模块会跑在 FastAPI/worker 进程里，
    必须走 database.get_raw_connection 才能同时支持 pg / sqlite 两种 DB_MODE。

    口径必须与级别规则检查保持一致（同一批样本、同一条 WHERE），
    否则两个页签的「总 TT」会不一样，使用者会当成 bug：
      · 只取 alarm_code 非空的单（规则都按告警码/属性匹配）
      · ORDER BY created_time DESC
    """
    import pandas as pd
    from backend.database import get_raw_connection

    limit = max(1, min(int(limit or 1000), 10000))
    # 列名与 eflow_rules_matcher.get_eflow_tt_data 对齐（多取 4 列供派单解析用）
    sql = (
        "SELECT wo_no, tt_no, ticket_no, title, "
        "       alarm_code, alarm_category, alarm_subcategory, alarm_type, "
        "       alarm_severity, ticket_severity, "
        "       site_id, site_name, ne_name, domain, status, ticket_type, "
        "       project_name, template_name, "
        "       vip_site, hub_site, site_type, site_class, "
        "       down_site_count, site_information, alarm_description, "
        "       created_time, alarm_occur_time, alarm_clear_time, "
        "       current_handler, fo_accept_detail, fo_process_detail, create_detail, "
        "       bo_accept_detail, bo_process_detail, third_accept_detail, "
        "       third_process_detail, confirm_detail, closed_detail, "
        "       process_description "
        "FROM eflow_tt "
        "WHERE alarm_code IS NOT NULL AND alarm_code != '' "
        "ORDER BY created_time DESC "
        "LIMIT ?"
    )
    with get_raw_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, (limit,))
        names = [d[0] for d in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ #
# 主流程
# ------------------------------------------------------------------ #

_ROW_COLUMNS = (
    ("tt_no", "tt_no"), ("wo_no", "wo_no"),
    ("ticket_no", "ticket_no"), ("title", "title"),
    ("alarm_code", "alarm_code"), ("alarm_name", "alarm_name"),
    ("site_id", "site_id"), ("site_name", "site_name"), ("ne_name", "ne_name"),
    ("domain", "domain"), ("site_type", "site_type"), ("vip_site", "vip_site"),
    ("down_site_count", "down_site_count"), ("ticket_severity", "ticket_severity"),
    ("created_time", "created_time"),
    ("alarm_occur_time", "alarm_occur_time"), ("alarm_clear_time", "alarm_clear_time"),
)


def check_all(limit: int = 1000) -> Dict[str, Any]:
    """跑一轮完整评估：样本 + 规则判定 + 实际派单 + 分类 + 导出 + 快照。"""
    from backend.services.eflow_rules import eflow_push_dispatch as D
    from backend.services.eflow_rules import eflow_push_rule_eval as EV
    from backend.services.eflow_rules import eflow_push_rule_history as H
    from backend.services.eflow_rules import eflow_push_snapshots as S
    from backend.services.eflow_rules import eflow_rules_matcher as M

    t0 = time.perf_counter()

    raw_rules = [EV.prepare_rule(rec) for rec in EV.load_push_rules(PUSH_RULES_XLSX)]
    rules = [r for r in raw_rules if r]
    if not rules:
        raise RuntimeError("推单规则表中没有可用的 ACTIVE ttPushOrderRule")

    tt_df = load_sample(limit=limit)
    if tt_df.empty:
        raise RuntimeError("eflow_tt 中没有可检查的样本（alarm_code 非空的单为空）")

    attrs = M.load_site_attrs(tt_df["site_id"]) if "site_id" in tt_df.columns else {}
    vf = M.build_value_frame(tt_df, attrs=attrs)
    records = tt_df.to_dict("records")
    ev = EV.evaluate_rules(rules, vf, records, attrs=attrs)

    rows: List[Dict[str, Any]] = []
    for i, rec in enumerate(records):
        actual = D.parse_actual_dispatch(rec)
        hit = ev["hits"][i]
        undec = bool(ev["undecidable"].iloc[i])
        cat, kind = D.classify(hit, actual, undec)
        row: Dict[str, Any] = {}
        for src, dst in _ROW_COLUMNS:
            row[dst] = _s(rec.get(src))
        row["alarm_code"] = _norm_code(rec.get("alarm_code"))
        row["alarm_name"] = _s(rec.get("alarm_description")) or row["alarm_name"]
        # 实际派单
        row["has_wo"] = actual["has_wo"]
        row["dispatch_person"] = actual["dispatch_person"]
        row["dispatch_group"] = actual["dispatch_group"]
        row["fo_operator"] = actual["operator"]
        row["robot_handled"] = actual["robot_handled"]
        row["dispatch_parsed"] = actual["parsed"]
        # 规则判定
        row["rule_id"] = _s((hit or {}).get("rule_id"))
        row["rule_name"] = _s((hit or {}).get("rule_name"))
        row["rule_priority"] = (hit or {}).get("priority")
        row["rule_builds_wo"] = bool((hit or {}).get("built_wo"))
        row["target_handler"] = _s((hit or {}).get("target_handler"))
        row["push_path"] = _s((hit or {}).get("push_path"))
        row["auto_operator"] = _s((hit or {}).get("auto_operator"))
        row["evidence"] = _s((hit or {}).get("evidence"))
        # 分类
        row["category"] = cat
        row["diff_kind"] = kind
        rows.append(row)

    elapsed = time.perf_counter() - t0
    files = _export(rows, ev["per_rule"])

    # 规则历史生效情况：让「历来如此」与「这次改坏的」在页面上能区分开
    per_rule = H.rule_history(ev["per_rule"], attrs)
    summary = _summarize(rows, per_rule, rules, limit, elapsed, files)
    S.write_snapshot(summary, rows)
    _atomic_write_json(SUMMARY_JSON, summary)
    return summary


# ------------------------------------------------------------------ #
# 导出 & 摘要
# ------------------------------------------------------------------ #

def _export(rows: List[Dict[str, Any]], per_rule: List[Dict[str, Any]]) -> Dict[str, Any]:
    """导出逐单明细 Excel（两个 Sheet：All_TT_Records + Rule_Hits）。"""
    import pandas as pd

    try:
        df_all = pd.DataFrame(rows)
        df_rule = pd.DataFrame(per_rule)
        target = OUTPUT_XLSX
        try:
            with pd.ExcelWriter(target, engine="openpyxl") as w:
                df_all.to_excel(w, sheet_name="All_TT_Records", index=False)
                df_rule.to_excel(w, sheet_name="Rule_Hits", index=False)
        except PermissionError:
            target = OUTPUT_XLSX.with_name(OUTPUT_XLSX.stem + "_new.xlsx")
            with pd.ExcelWriter(target, engine="openpyxl") as w:
                df_all.to_excel(w, sheet_name="All_TT_Records", index=False)
                df_rule.to_excel(w, sheet_name="Rule_Hits", index=False)
        return {"xlsx": str(target), "xlsx_name": target.name}
    except Exception as e:  # noqa: BLE001
        logger.warning("推单检查表导出失败：%s", e)
        return {"xlsx": "", "xlsx_name": ""}


def _summarize(rows: List[Dict[str, Any]], per_rule: List[Dict[str, Any]],
               rules: List[Dict[str, Any]], limit: int, elapsed: float,
               files: Dict[str, Any]) -> Dict[str, Any]:
    from backend.services.eflow_rules import eflow_push_dispatch as D

    total = len(rows)
    counts = {c: 0 for c in D.CATEGORIES}
    diff = {k: 0 for k in D.DIFF_KINDS}
    for r in rows:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
        if r["diff_kind"]:
            diff[r["diff_kind"]] = diff.get(r["diff_kind"], 0) + 1

    actual_wo = sum(1 for r in rows if r["has_wo"])
    rule_wo = sum(1 for r in rows if r["rule_builds_wo"])
    unparsed = sum(1 for r in rows if not r["dispatch_parsed"])

    grp: Dict[str, int] = {}
    for r in rows:
        g = r["dispatch_group"] or "—"
        grp[g] = grp.get(g, 0) + 1

    missing_fields: Dict[str, List[str]] = {}
    for pr in per_rule:
        for f in pr.get("unknown_fields") or []:
            missing_fields.setdefault(f, []).append(_s(pr.get("rule_id")))

    try:
        rules_mtime = PUSH_RULES_XLSX.stat().st_mtime
    except OSError:
        rules_mtime = None

    return {
        "success": True,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "generated_ts": time.time(),
        "limit": limit,
        "total": total,
        "counts": counts,
        # 恒等式：四类互斥求和 = 总数（页面会核对，不自洽就显式告警）
        "consistent": sum(counts.values()) == total,
        "diff": diff,
        "actual_wo": actual_wo,
        "actual_no_wo": total - actual_wo,
        "rule_wo": rule_wo,
        "dispatch_unparsed": unparsed,
        "group_dist": [{"group": g, "count": n}
                       for g, n in sorted(grp.items(), key=lambda kv: -kv[1])],
        "rule_breakdown": per_rule,
        "rules_count": len(rules),
        "rules_mtime": rules_mtime,
        "missing_fields": {k: sorted(v) for k, v in missing_fields.items()},
        "elapsed_seconds": round(elapsed, 2),
        "files": files,
    }


# ------------------------------------------------------------------ #
# 对外再导出（保持调用方只 import 本模块）
# ------------------------------------------------------------------ #

from backend.services.eflow_rules.eflow_push_snapshots import (  # noqa: E402
    compare_snapshots, list_snapshots, load_snapshot,
)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(check_all(limit=1000), ensure_ascii=False, indent=2)[:4000])

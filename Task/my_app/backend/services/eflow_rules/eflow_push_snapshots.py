# -*- coding: utf-8 -*-
"""eflow_push_snapshots.py - 推单规则检查的周快照与跨次对比
==========================================================

从 `eflow_push_rules_checker.py` 拆出（原文件超过 AGENTS.md 三.2 的 500 行约定）。

为什么需要快照：规则改了以后「派单会怎么变」只有在**两次运行之间**才看得出来。
单次运行只能回答「当下规则 vs 实际派单」，回答不了「相对改之前变了什么」。

存什么：摘要 + 逐单「minimal 行」（只留对比需要的字段，单份约 1-2 MB）。
对比靠 `tt_no` 对齐 —— 聚合数字做不到这一点。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_RULES_DIR = Path(__file__).resolve().parent
SNAPSHOT_DIR = _RULES_DIR / "push_rules_snapshots"
# 只保留最近 N 份；页面「两次运行对比」不会需要更早的
SNAPSHOT_KEEP = 10

# 快照里逐单保留的字段（对比用；不要加展示列，否则文件会迅速膨胀）
_SLIM_KEYS = (
    "tt_no", "alarm_code", "rule_id", "rule_name", "rule_builds_wo",
    "target_handler", "has_wo", "dispatch_group", "category", "diff_kind",
)


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(path))


def write_snapshot(summary: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
    """落一份周快照：摘要 + 逐单 minimal 行。失败只记日志，不影响主流程。"""
    try:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(summary["generated_ts"]))
        slim = [{k: r.get(k) for k in _SLIM_KEYS} for r in rows]
        payload = {
            "id": stamp,
            "generated_at": summary["generated_at"],
            "generated_ts": summary["generated_ts"],
            "total": summary["total"],
            "counts": summary["counts"],
            "rules_mtime": summary.get("rules_mtime"),
            "rules_count": summary["rules_count"],
            "rule_breakdown": summary["rule_breakdown"],
            "rows": slim,
        }
        _atomic_write_json(SNAPSHOT_DIR / f"{stamp}.json", payload)
        _prune()
    except Exception as e:  # noqa: BLE001
        logger.warning("推单检查快照写入失败：%s", e)


def _prune() -> None:
    try:
        files = sorted(SNAPSHOT_DIR.glob("*.json"))
        for old in files[:-SNAPSHOT_KEEP]:
            try:
                old.unlink()
            except OSError:
                pass
    except OSError:
        pass


def list_snapshots() -> List[Dict[str, Any]]:
    """列出可用快照（新的在前），供页面「两次运行对比」选择。"""
    out: List[Dict[str, Any]] = []
    if not SNAPSHOT_DIR.is_dir():
        return out
    for f in sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        out.append({
            "id": d.get("id") or f.stem,
            "generated_at": d.get("generated_at"),
            "total": d.get("total"),
            "counts": d.get("counts") or {},
            "rules_count": d.get("rules_count"),
            "rule_breakdown": d.get("rule_breakdown") or [],
        })
    return out


def load_snapshot(sid: str) -> Dict[str, Any]:
    """按 id 读快照。id 只允许 `[0-9A-Za-z_-]`（防止路径穿越）。"""
    sid = re.sub(r"[^0-9A-Za-z_\-]", "", str(sid or "").strip())
    if not sid:
        raise ValueError("快照 id 为空")
    f = SNAPSHOT_DIR / f"{sid}.json"
    if not f.is_file():
        raise FileNotFoundError(f"快照不存在：{sid}")
    return json.loads(f.read_text(encoding="utf-8"))


def compare_snapshots(from_id: str, to_id: str) -> Dict[str, Any]:
    """按 tt_no 对齐两次快照，给出逐单变化与逐规则命中数变化。

    两次快照的样本窗口可能不同（新单进来了 / 老单滑出 LIMIT 窗口），
    所以返回里显式分出：
      · changed   —— 两次都出现且判定结果变了
      · only_to   —— 只在 to 里（新增样本）
      · only_from —— 只在 from 里（滑出窗口）
    页面上把它们分开列，避免「新增 100 张单」被误读成「100 张单判错了」。
    """
    a = load_snapshot(from_id)
    b = load_snapshot(to_id)
    am = {r["tt_no"]: r for r in a.get("rows", [])}
    bm = {r["tt_no"]: r for r in b.get("rows", [])}

    def _sig(r: Dict[str, Any]) -> Tuple:
        return (r.get("rule_id"), bool(r.get("rule_builds_wo")),
                r.get("has_wo"), r.get("dispatch_group"), r.get("category"))

    changed: List[Dict[str, Any]] = []
    for tt, br in bm.items():
        ar = am.get(tt)
        if not ar or _sig(ar) == _sig(br):
            continue
        changed.append({
            "tt_no": tt,
            "alarm_code": br.get("alarm_code"),
            "from_rule_id": ar.get("rule_id") or "",
            "to_rule_id": br.get("rule_id") or "",
            "from_rule_name": ar.get("rule_name") or "",
            "to_rule_name": br.get("rule_name") or "",
            "from_builds_wo": ar.get("rule_builds_wo"),
            "to_builds_wo": br.get("rule_builds_wo"),
            "from_has_wo": ar.get("has_wo"),
            "to_has_wo": br.get("has_wo"),
            "from_group": ar.get("dispatch_group") or "",
            "to_group": br.get("dispatch_group") or "",
            "from_category": ar.get("category") or "",
            "to_category": br.get("category") or "",
        })

    # 逐规则命中数变化（以规则 ID 为键；规则被删除/新增也会出现）
    def _rb(snap: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {str(x.get("rule_id") or ""): x for x in snap.get("rule_breakdown") or []}

    ra, rb = _rb(a), _rb(b)
    rule_delta: List[Dict[str, Any]] = []
    for rid in sorted(set(ra) | set(rb), key=lambda x: (len(x), x)):
        x, y = ra.get(rid), rb.get(rid)
        m_from = (x or {}).get("matched", 0) or 0
        m_to = (y or {}).get("matched", 0) or 0
        if x is None or y is None or m_from != m_to:
            src = y or x or {}
            rule_delta.append({
                "rule_id": rid,
                "rule_name": str(src.get("rule_name") or ""),
                "status": "added" if x is None else ("removed" if y is None else "changed"),
                "matched_from": None if x is None else m_from,
                "matched_to": None if y is None else m_to,
            })

    ca = a.get("counts") or {}
    cb = b.get("counts") or {}
    # 四类固定键：前端按固定顺序展示，缺键补 0 而不是 undefined
    counts = {c: {"from": ca.get(c, 0), "to": cb.get(c, 0),
                  "delta": cb.get(c, 0) - ca.get(c, 0)}
              for c in ("correct", "mismatch", "undecidable", "unmatched")}
    return {
        "from": {"id": a.get("id"), "generated_at": a.get("generated_at"),
                 "rules_mtime": a.get("rules_mtime"), "rules_count": a.get("rules_count")},
        "to": {"id": b.get("id"), "generated_at": b.get("generated_at"),
               "rules_mtime": b.get("rules_mtime"), "rules_count": b.get("rules_count")},
        "rules_changed": a.get("rules_mtime") != b.get("rules_mtime"),
        "counts": counts,
        "changed_total": len(changed),
        "changed": changed[:500],
        "only_to": len(set(bm) - set(am)),
        "only_from": len(set(am) - set(bm)),
        "rule_delta": rule_delta,
    }

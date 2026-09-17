# -*- coding: utf-8 -*-
"""VMAX CXO 天粒度看板 API —— 只读透传日值归档，并排成「周一~周日 × 本周/前一周/前两周」网格。

与现有 /api/vmax-cxo-dashboard/*、/api/cxo-dashboard/* 完全独立：
本路由只读 data/vmax_cxo_daily/daily.json（由新任务 vmax_cxo_daily_sync 写入），
不读也不写 data/cxo_dashboard/*，现有看板不受任何影响。

背景约束（实测，见 backend/services/vmax_cxo_daily_cache.py 头注释）：
    - VMAX 无原生天粒度（Granularity 枚举只到 1hour）-> 日值由小时明细本地聚合
    - 小时明细仅保留约 8 天 -> 网格中早于保留地板的日期永久不可回补，前端留灰空格
"""
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.services.vmax_cxo_daily_cache import (DAILY_FILE, KPI_SPECS, RETENTION_DAYS,
                                                   build_tab_tree)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vmax-cxo-daily", tags=["vmax-cxo-daily"])

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_WEEK_LABELS = [("this", "This Week"), ("prev1", "Last Week"), ("prev2", "Week Before Last")]


def _load_store() -> Optional[Dict[str, Any]]:
    try:
        with open(DAILY_FILE, "r", encoding="utf-8") as stream:
            store = json.load(stream)
        return store if isinstance(store, dict) else None
    except FileNotFoundError:
        return None
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("[vmax-cxo-daily] 日存读取失败: %s", exc)
        return None


def _day_entry(days: Dict[str, Any], iso: str, today: date) -> Dict[str, Any]:
    """单日：主口径取值 + 状态 + 缺失原因（前端据此画灰空格 + tooltip）。"""
    per_kpi = days.get(iso) or {}
    values: Dict[str, Any] = {}
    hours: Dict[str, Any] = {}
    for kpi_id, spec in KPI_SPECS.items():
        rec = per_kpi.get(kpi_id)
        if not isinstance(rec, dict):
            continue
        val = rec.get(spec["agg"])
        if val is not None:
            values[kpi_id] = val
        hours[kpi_id] = rec.get("n")
    complete = bool(per_kpi) and all((per_kpi.get(k) or {}).get("complete") for k in per_kpi)

    if values and complete:
        state = "ok"
    elif values and (per_kpi.get(next(iter(per_kpi))) or {}).get("in_progress"):
        state = "partial"
    elif values:
        state = "incomplete"          # 有数但小时点不全（上游当时缺分区）
    elif iso > today.isoformat():
        state = "future"
    else:
        state = "missing"

    reason = None
    if state == "future":
        reason = "该日期尚未到来"
    elif state == "missing":
        reason = ("超出 VMAX 小时明细保留期（约 %d 天），本地日存也未采集到该日 -> 永久不可回补"
                  % RETENTION_DAYS)
    elif state == "incomplete":
        reason = "当日部分小时缺分区（上游当时无数据），非本系统问题"
    return {"date": iso, "dow": _DOW[date.fromisoformat(iso).weekday()], "state": state,
            "values": values, "hours": hours, "reason": reason}


@router.get("/grid")
def get_grid(anchor: str = ""):
    """返回 3 条周曲线 × 7 天网格。anchor 可为任意日期（默认今天），用于回看历史三周。"""
    store = _load_store()
    if not store:
        return JSONResponse({"status": "ok", "source": "empty", "updated_at": None,
                             "weeks": [], "kpis": [], "coverage": {}},
                            headers={"Cache-Control": "no-store"})
    try:
        today = (datetime.strptime(anchor, "%Y-%m-%d").date() if anchor else date.today())
    except ValueError:
        return JSONResponse({"status": "error", "error": "anchor 需为 YYYY-MM-DD"}, status_code=400)

    days = store.get("days") if isinstance(store.get("days"), dict) else {}
    this_monday = today - timedelta(days=today.weekday())
    weeks = []
    for key, label in _WEEK_LABELS:
        monday = this_monday - timedelta(days=7 * int(key[4:]) if key != "this" else 0)
        week_days = [_day_entry(days, (monday + timedelta(days=i)).isoformat(), today) for i in range(7)]
        weeks.append({"key": key, "label": label, "monday": monday.isoformat(), "days": week_days})

    stored = sorted(days)
    # 分组元数据：按 KPI_SPECS 声明顺序聚合（summary -> network），供前端分节渲染
    order, by_group = [], {}
    for kpi_id, spec in KPI_SPECS.items():
        g = spec.get("group", "summary")
        if g not in by_group:
            by_group[g] = []
            order.append(g)
        by_group[g].append(kpi_id)
    body = {
        "status": "ok",
        "source": "cache",
        "updated_at": store.get("updated_at"),
        "granularity": store.get("granularity", "1hour"),
        "retention_days": store.get("retention_days", RETENTION_DAYS),
        "today": today.isoformat(),
        "coverage": {"oldest": stored[0] if stored else None,
                     "newest": stored[-1] if stored else None,
                     "stored_days": len(stored)},
        "groups": [{"key": g, "kpis": by_group[g]} for g in order],
        # 页签树（与参考看板 vmaxCxoDashboard 的 Network/Service 页签结构一致）：
        # 顶层 summary/network/service，后两者带子页签，每个页签给出其 kpi id 列表。
        "tabs": build_tab_tree(),
        "kpis": [{"id": kpi_id, "title": spec["title"], "unit": spec["unit"],
                  "agg": spec["agg"], "digits": spec["digits"],
                  "group": spec.get("group", "summary"), "note": spec.get("note", "")}
                 for kpi_id, spec in KPI_SPECS.items()],
        "weeks": weeks,
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.get("/days")
def get_days(limit: int = 60):
    """日存明细（表格/排查用）：按日期倒序，带每个 KPI 的 sum/avg/max 全口径。"""
    store = _load_store()
    if not store:
        return JSONResponse({"status": "ok", "source": "empty", "days": []},
                            headers={"Cache-Control": "no-store"})
    days = store.get("days") if isinstance(store.get("days"), dict) else {}
    cut = max(1, min(int(limit or 60), 400))
    ordered = sorted(days, reverse=True)[:cut]
    out: List[Dict[str, Any]] = [
        dict({"date": iso, "dow": _DOW[date.fromisoformat(iso).weekday()]},
             **{kpi_id: (days[iso].get(kpi_id) or {}) for kpi_id in KPI_SPECS})
        for iso in ordered]
    return JSONResponse({"status": "ok", "source": "cache", "updated_at": store.get("updated_at"),
                         "count": len(out), "days": out}, headers={"Cache-Control": "no-store"})


@router.get("/status")
def get_status():
    """轻量健康检查：日存是否存在、覆盖到哪天。"""
    store = _load_store()
    if not store:
        return {"status": "ok", "cache_exists": False, "updated_at": None, "stored_days": 0}
    days = sorted(store.get("days") or {})
    return {"status": "ok", "cache_exists": True, "updated_at": store.get("updated_at"),
            "stored_days": len(days), "oldest": days[0] if days else None,
            "newest": days[-1] if days else None, "granularity": store.get("granularity")}

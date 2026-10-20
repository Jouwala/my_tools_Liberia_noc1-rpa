# -*- coding: utf-8 -*-
"""VMAX 90 天经营看板 API（?page=vmaxCxoDashboard_90Days）—— CEO 视角的只读接口。

数据源：`data/olib_soc_report/olib_soc_report.sqlite3` 的 `daily_kpi` 表
（由任务 olib_soc_kpi_daily_sync 每日增量、olib_soc_vmax_report 每月全量写入）。

本路由**只读**（sqlite `query_only=ON`），不改动任何现有看板的数据与接口：
    /api/vmax-cxo-dashboard/*  原版 15 分钟大屏
    /api/vmax-cxo-daily/*      天粒度（周一~周日三条周曲线）
    /api/olib-soc-dashboard/*  本路由（90 天日/周趋势 + 昨日卡片 + 极值）

一个接口给全量载荷（90 天 × 9 指标 ≈ 1000 个数字，几十 KB），前端切换日/周粒度不再请求。
"""
import logging
from datetime import date, timedelta

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.services.olib_soc_report import olib_soc_kpi_store as kpi

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/olib-soc-dashboard", tags=["olib-soc-dashboard"])

_NO_STORE = {"Cache-Control": "no-store"}


@router.get("/overview")
def get_overview(days: int = 90):
    """看板主载荷：卡片（最新日 + 90 天最大/平均/最低 + 周/月同比）+ 日/周趋势 + 明细表。"""
    try:
        body = kpi.build_overview(days=days)
    except Exception as exc:                                             # noqa: BLE001
        logger.exception("[olib-soc-dashboard] 载荷构建失败")
        return JSONResponse({"status": "error", "error": "%s: %s" % (type(exc).__name__, exc)},
                            status_code=500, headers=_NO_STORE)
    return JSONResponse(body, headers=_NO_STORE)


@router.get("/app-offload")
def get_app_offload(days: int = 90, as_of: str = "", top: int = 40):
    """分业务「本地 / 海外」服务器流量下钻（看板点「缓存占比」卡片时调一次）。

    * `as_of` 指定看哪一天（默认库里最新一天）；只认 YYYY-MM-DD，非法值直接 400，
      不静默回退 —— 静默回退会让用户以为看的是自己点的那天。
    * 返回「最新一天」与「窗口累计」两套行 + 各自的合计；表格合计等于当日全量，
      能与 traffic 卡片对账（明细全量落库，未按流量阈值截断）。
    """
    if as_of:
        try:
            date.fromisoformat(as_of)
        except ValueError:
            return JSONResponse({"status": "error", "error": "as_of 需为真实存在的 YYYY-MM-DD 日期"},
                                status_code=400, headers=_NO_STORE)
    try:
        body = kpi.build_app_offload(days=days, as_of=as_of or None, top=top)
    except Exception as exc:                                             # noqa: BLE001
        logger.exception("[olib-soc-dashboard] 分业务分流载荷构建失败")
        return JSONResponse({"status": "error", "error": "%s: %s" % (type(exc).__name__, exc)},
                            status_code=500, headers=_NO_STORE)
    return JSONResponse(body, headers=_NO_STORE)


@router.get("/status")
def get_status():
    """轻量健康检查：KPI 库覆盖到哪天、覆盖多少天、最近一次写入时间。

    覆盖统计按 90 天窗口（= 看板窗口）算，而不是只看最近几天，
    这样「库里有几天数据」能直接对上页面上的 `stored/expected`。
    """
    body = kpi.build_overview(days=90)
    coverage = body.get("coverage") or {}
    return JSONResponse({
        "status": body.get("status"),
        "db": str(kpi.KPI_DB_PATH),
        "db_exists": kpi.KPI_DB_PATH.exists(),
        "newest": coverage.get("newest"),
        "oldest": coverage.get("oldest"),
        "stored_days": coverage.get("stored_days", 0),
        "expected_days": coverage.get("expected_days", 90),
        "missing_days": len(coverage.get("missing_days") or []),
        # 行在但关键指标为 NULL 的天（该指标卡片会「少一天」）——与整行缺失分开计数，
        # 便于巡检一眼看出「库里天数够、但有列是空的」。
        "incomplete_days": len(coverage.get("incomplete_days") or []),
        "updated_at": body.get("updated_at"),
        "as_of": body.get("as_of"),
        "today": date.today().isoformat(),
        "metrics": [m["id"] for m in kpi.METRICS],
        "primary": kpi.PRIMARY_IDS,
    }, headers=_NO_STORE)


@router.get("/days")
def get_days(days: int = 90):
    """完整日值序列（排查/导出用）：一天一行，原始口径（TB / 用户数 / 百分比）。"""
    days = max(1, min(int(days or 90), 400))
    end = date.today() - timedelta(days=1)                               # 当天仍在累积
    begin = end - timedelta(days=days - 1)
    rows = kpi.fetch_range(begin.isoformat(), end.isoformat())
    return JSONResponse({"status": "ok", "begin": begin.isoformat(), "end": end.isoformat(),
                         "count": len(rows), "days": rows}, headers=_NO_STORE)

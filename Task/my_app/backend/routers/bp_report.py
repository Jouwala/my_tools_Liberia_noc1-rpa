# -*- coding: utf-8 -*-
"""BP Report（Bad Performance 小区报告）API。

数据来源与口径见 backend/services/bp_caliber.py、
backend/services/bp_report_import.py（Excel 一次性导入）、
backend/services/bp_report_sync.py（从 RAN_UME 更新）。

口径（umlaut 定义）：
    Daily:   Average DL Active User Number > 2.5
             AND [FDD]DL IP Throughput(Mbps) < 3
             AND [FDD]DL PRB Utilization Rate > 80%
    Weekly:  一周内 4/7 天为 BP
    Monthly: 一个月内 3/4 个完整周为 BP

GET /api/bp-report/overview
    ?start=YYYY-MM-DD&end=YYYY-MM-DD&granularity=day|week|month
    -> {meta, granularity, range, summary, trend:[...]}

GET /api/bp-report/regional（分区维度，对应 Excel 的 Regional - Daily）
    ?start&end&region
    -> {meta, range, regions:[...], series:[...]}

GET /api/bp-report/layer（分层维度，对应 Excel 的 Frequency layer - Daily）
    ?start&end&region&layer
    -> {meta, range, layers:[...], series:[...]}

GET /api/bp-report/cells（**下钻**：概览里每个数字都能落到这里）
    ?day=YYYY-MM-DD | ?start&end
    &region&layer&scope=bp|nonbp|undecidable|all&limit
    -> {meta, scope, filters, total, bp, nonbp, undecidable, rows:[...]}
    其中 `scope=bp` 的行数 == 概览的 summary.bp_cells（同一 WHERE，见 service 模块说明）。

GET /api/bp-report/meta（口径说明、脏值统计、同步状态与对账差异）
    -> {caliber, active_user, counts, regions, layers, dirty, reconcile, notes}

⚠️ 本页**口径不完整**：`Average DL Active User Number` 在 RAN_UME 侧未采集，
   因此每日 BP 判定实际只覆盖两个条件。`/overview` 与 `/meta` 的
   `active_user.available=false` 是给前端的常驻告警依据，**不要隐藏**。
"""
import logging
import re

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from backend.api_i18n import translate_ui_fields

from backend.services import bp_report_service as svc

logger = logging.getLogger("bp_report")

router = APIRouter(prefix="/api/bp-report", tags=["bp-report"])

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _day(v: str) -> str:
    """日期/周期参数归一化。

    ⚠️ 2026-09-29 修复：本函数原先把「不符合 `YYYY-MM-DD` 的值」**静默清成空串**，
    而空串在 `_range_sql_day()` 里会让谓词退化成 `1=1` —— 于是：
      · 前端按**周**下钻传 `2023-W48`（概览自己输出的 period 标签）→ 被清空 → 返回**全表**前 N 行；
      · 传错参数（如 `garbage`）→ 同样被清空 → 同样返回全表。
    两者都表现为「明细有 20000 行、truncated=true」，看起来像"数据很多"，
    极易被当成正常结果，实际与用户点的那一期毫无关系。

    现在：合法周期标签原样透传（由 `bp_caliber.period_to_day_range()` 还原成区间），
    非法值交给 service 抛错，由本路由返回明确的 warning，**不再静默放宽查询**。
    """
    v = (v or "").strip()
    if not v:
        return ""
    # 单日、ISO 周（YYYY-Www）、整月（YYYY-MM）都放行，具体还原在 service 里做
    if _DAY_RE.match(v) or re.fullmatch(r"\d{4}-W\d{2}", v) or re.fullmatch(r"\d{4}-\d{2}", v):
        return v
    raise ValueError(f"无法识别的日期/周期参数：{v!r}（需 YYYY-MM-DD / YYYY-Www / YYYY-MM）")


def _fail(msg: str):
    """库不存在等硬错误：返回 200 + 空结构 + warnings，让页面能显示原因而不是白屏。"""
    return JSONResponse(status_code=200, content={
        "meta": {"warnings": [msg], "generated_at": "", "elapsed_seconds": 0,
                 "active_user": {"available": False, "reason": msg},
                 "caliber": {}, "truncated": False},
        "granularity": "day", "range": {"start": "", "end": ""},
        "summary": {"periods": 0, "bp_cells": 0, "total_cells": 0,
                    "traffic_tb": None, "avg_ratio": None, "dict_cells": 0},
        "trend": [], "warnings": [msg],
    })


@router.get("/overview")
def overview(
    request: Request,
    start: str = Query("", description="开始日期 YYYY-MM-DD（日粒度）或 YYYY-Www / YYYY-MM"),
    end: str = Query("", description="结束日期"),
    granularity: str = Query("day", description="粒度：day / week / month"),
):
    """总体趋势与合计（对应 Excel 的 Overall - Daily / Weekly / Monthly）。"""
    try:
        return translate_ui_fields(svc.load_overview(start, end, granularity), request)
    except FileNotFoundError as e:
        logger.warning("[bp-report/overview] %s", e)
        return _fail(str(e))
    except Exception as e:
        logger.exception("[bp-report/overview] 失败: %s", e)
        return _fail(f"load_failed: {e}")


@router.get("/regional")
def regional(
    request: Request,
    start: str = Query("", description="开始日期 YYYY-MM-DD"),
    end: str = Query("", description="结束日期 YYYY-MM-DD"),
    region: str = Query("", description="分区（留空=全部分区）"),
):
    """分区维度（Cluster1~6 / Rural / ERA / Unknown）。"""
    try:
        return translate_ui_fields(svc.load_regional(start, end, region), request)
    except FileNotFoundError as e:
        return _fail(str(e))
    except Exception as e:
        logger.exception("[bp-report/regional] 失败: %s", e)
        return _fail(f"load_failed: {e}")


@router.get("/layer")
def layer(
    request: Request,
    start: str = Query("", description="开始日期 YYYY-MM-DD"),
    end: str = Query("", description="结束日期 YYYY-MM-DD"),
    region: str = Query("", description="分区过滤（留空=全部）"),
    layer_name: str = Query("", alias="layer", description="频层过滤（留空=全部）"),
):
    """频层维度（L800 / L1800 20M / L1800 15M / L1800 10M / L2600 / Unknown）。"""
    try:
        return translate_ui_fields(svc.load_layer(start, end, region, layer_name), request)
    except FileNotFoundError as e:
        return _fail(str(e))
    except Exception as e:
        logger.exception("[bp-report/layer] 失败: %s", e)
        return _fail(f"load_failed: {e}")


@router.get("/cells")
def cells(
    request: Request,
    day: str = Query("", description="单日 YYYY-MM-DD（下钻单日时用）"),
    start: str = Query("", description="开始日期 YYYY-MM-DD"),
    end: str = Query("", description="结束日期 YYYY-MM-DD"),
    region: str = Query("", description="分区过滤"),
    layer: str = Query("", description="频层过滤"),
    scope: str = Query("all", description="范围：bp / nonbp / undecidable / all"),
    limit: int = Query(svc.MAX_DETAIL_ROWS, ge=1, le=svc.MAX_DETAIL_ROWS,
                       description="取样上限（默认即上限，截断时 meta.truncated=true）"),
):
    """小区明细下钻。

    **一致性契约**：`scope=bp` 的行数 == `/overview` 的 `trend[].detail_cells`
    （同一组谓词，已逐期验证）。注意它**不等于** `trend[].bp_cells` ——
    后者取自 Excel「Overall」汇总表，与「BP Cells List」明细本身就是两个口径
    （差额见 `trend[].detail_diff`），界面必须两者并排展示而不是假装相等。

    `day` / `start` / `end` 除 `YYYY-MM-DD` 外，也接受概览输出的周期标签
    `YYYY-Www` / `YYYY-MM`（前端按周/月下钻时直接传 period），由
    `bp_caliber.period_to_day_range()` 还原成日期区间。

    版本标记（用于确认线上 7038 是否已加载本版本代码）：BPR_META_V2
    """
    try:
        return translate_ui_fields(svc.load_cells(day=_day(day), start=_day(start), end=_day(end),
                                             region=region, layer=layer, scope=scope, limit=limit),
                                 request)
    except ValueError as e:
        # 参数非法：明确报错，**绝不**退化成"无过滤全表"（那正是 2026-09-29 的事故）
        logger.warning("[bp-report/cells] 参数被拒: %s", e)
        return JSONResponse(status_code=200, content={
            "meta": {"warnings": [str(e)], "generated_at": "", "elapsed_seconds": 0,
                     "truncated": False, "limit": limit},
            "scope": scope, "filters": {"day": day, "start": start, "end": end,
                                        "region": region, "layer": layer},
            "total": 0, "bp": 0, "nonbp": 0, "undecidable": 0, "rows": [],
        })
    except FileNotFoundError as e:
        return _fail(str(e))
    except Exception as e:
        logger.exception("[bp-report/cells] 失败: %s", e)
        return _fail(f"load_failed: {e}")


@router.get("/meta")
def meta(request: Request):
    """口径说明、脏值统计、同步状态与对账差异。"""
    try:
        return translate_ui_fields(svc.load_meta(), request)
    except FileNotFoundError as e:
        return {"caliber": {}, "active_user": {"available": False, "reason": str(e)},
                "counts": {}, "regions": [], "layers": [], "dirty": {},
                "reconcile": {}, "notes": [], "warnings": [str(e)], "errors": []}
    except Exception as e:
        logger.exception("[bp-report/meta] 失败: %s", e)
        return {"caliber": {}, "active_user": {"available": False, "reason": str(e)},
                "counts": {}, "regions": [], "layers": [], "dirty": {},
                "reconcile": {}, "notes": [], "warnings": [f"load_failed: {e}"],
                "errors": []}

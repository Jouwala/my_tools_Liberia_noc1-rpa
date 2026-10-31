# -*- coding: utf-8 -*-
"""
vmax_diagnosis.py（router）—— 投诉诊断聚合接口
=============================================================================
GET /api/vmax-diagnosis?msisdn=&start=&end=

一次返回四个源（1300 / 1100 / 32 / 1301）的**原始行**，前端在其上做
四维评分、投诉类型判据、证据时间线与结论（见 frontend/src/pages/vmaxDiagnosisRules.ts）。

## 为什么把评分放前端

方案 §4.2 要求「切换投诉类型不重新取数」——秒切。
若评分在后端，每切一次页签就要多打一次上游（1300 三页 12s，
且上游限并发），体验和上游压力都不允许。
所以本接口**只做取数与归一**，不做判断 —— 判断逻辑集中在一处（前端纯函数），
避免「后端算一套、前端又算一套」的口径漂移。

## 为什么保留 /api/vmax-flow-xdr

`vmaxFlowFromXdr` 的分类聚合（按应用 / 按业务大类）仍由 `/api/vmax-flow-xdr`
提供 —— 前端「业务流量」页签复用它，避免同一份 1300 数据在两次请求里
被算出两套「总流量」。本接口返回的 1300 原始行是给诊断与时间线用的。

P0'-1（2026-11-01，单账号约束）：诊断顺手把「业务流量」页签要的
`flow` 聚合一起算好（复用刚取到的 1300/1301 行，不再打上游），
前端优先用 `flow` 直接渲染；`/api/vmax-flow-xdr` 仅作回退保留
（诊断失败、或旧前端直调时才走第二遍取数）。

只读透传：不落库、不缓存。鉴权走 main.py 的统一门户会话中间件。
"""
import logging
import re
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.routers.vmax_xdr_common import (
    humanize_login as _humanize_login,
    mask_msisdn as _mask_msisdn,
    parse_bound as _parse_bound,
)
from backend.services.vmax_cca.vmax_cca_client import (
    VmaxCcaError, VmaxCcaNotConfigured, VmaxCcaUnavailable, normalize_msisdn,
)
from backend.services.vmax_cca.vmax_diagnosis import VmaxDiagnosis
from backend.services.vmax_cca.vmax_flow_from_xdr import VmaxFlowFromXdr
from backend.services.vmax_cca.vmax_xdr_client import get_xdr_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vmax-diagnosis", tags=["vmax-diagnosis"])

# 诊断要看四个源，最短保留期由 RAN(32) 决定 —— 24 小时。
# 超过这个窗口，32 一定空，结论里的「无线质量」会永远是「无数据可判」，
# 所以在入口就拦住，而不是让用户对着一堆空卡片猜。
MAX_WINDOW_HOURS = 24
DEFAULT_WINDOW_HOURS = 3


@router.get("")
def get_diagnosis(
    msisdn: str = Query(..., min_length=5, max_length=24),
    start: Optional[str] = Query(None, description="窗口起点 YYYY-MM-DD[ HH:MM]，缺省 3 小时前"),
    end: Optional[str] = Query(None, description="窗口终点 YYYY-MM-DD[ HH:MM]，缺省现在"),
):
    """号码 + 时间窗 -> 四个源的原始话单 + IMSI 映射。

    返回 `{window, imsi, sources: [{key,label,ok,rows,error,truncated}]}`。

    **单源失败不整页失败**：某源超时/报错时该源 `ok=false` + `error` 文案，
    其余源照常返回，前端按可用的源计算结论并在页面标注「部分数据源未返回」。
    这是排障场景的硬要求 —— 一个源挂了导致整页白屏，用户就什么也看不到。
    """
    normalized = normalize_msisdn(msisdn)
    if not re.fullmatch(r"\d{5,20}", normalized):
        raise HTTPException(status_code=422,
                            detail="号码格式不正确：请输入 231 开头的完整数字号码")

    end_dt = _parse_bound(end, end_of=True)
    start_dt = (_parse_bound(start, end_of=False) if start
                else end_dt - timedelta(hours=DEFAULT_WINDOW_HOURS))
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt
    if end_dt - start_dt > timedelta(hours=MAX_WINDOW_HOURS):
        raise HTTPException(
            status_code=422,
            detail="时间窗跨度不能超过 %d 小时（无线侧话单只保留 %d 小时）"
                   % (MAX_WINDOW_HOURS, MAX_WINDOW_HOURS))

    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        diag = VmaxDiagnosis(get_xdr_client())
        payload = diag.fetch_all(
            normalized, start_dt.strftime(fmt), end_dt.strftime(fmt))
        # P0'-1：诊断顺手算好流量聚合（复用 1300/1301 行，不再打上游）。
        # 失败不影响诊断主体：flow 置空，前端回退到 /api/vmax-flow-xdr。
        try:
            rows_1300 = next(
                (s.get("rows") or [] for s in payload.get("sources", [])
                 if s.get("key") == "1300"), [])
            rows_1301 = next(
                (s.get("rows") or [] for s in payload.get("sources", [])
                 if s.get("key") == "1301"), [])
            flow = VmaxFlowFromXdr(diag.xdr).aggregate_from_rows(rows_1300, rows_1301)
            payload["flow"] = flow
            payload["flow_reused"] = flow is not None
        except Exception as exc:                                      # noqa: BLE001
            logger.warning("[vmax_diagnosis] 流量复用聚合失败（前端将回退单查）: %s", exc)
            payload["flow"] = None
            payload["flow_reused"] = False
    except VmaxCcaNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VmaxCcaUnavailable as exc:
        logger.warning("[vmax_diagnosis] 查询 %s 上游不可用: %s",
                       _mask_msisdn(normalized), exc)
        raise HTTPException(
            status_code=502,
            detail="诊断查询服务暂不可用: %s" % _humanize_login(str(exc))) from exc
    except VmaxCcaError as exc:
        logger.warning("[vmax_diagnosis] 查询 %s 异常: %s",
                       _mask_msisdn(normalized), exc)
        raise HTTPException(status_code=502,
                            detail="诊断查询失败: %s" % exc) from exc
    except Exception as exc:                                          # noqa: BLE001
        logger.exception("[vmax_diagnosis] 查询 %s 内部异常", _mask_msisdn(normalized))
        raise HTTPException(status_code=500,
                            detail="诊断查询内部错误: %s" % type(exc).__name__) from exc

    payload["msisdn"] = normalized
    payload["window"] = {"start": start_dt.strftime(fmt), "end": end_dt.strftime(fmt)}
    return payload

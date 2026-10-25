# -*- coding: utf-8 -*-
"""
vmax_cca_query.py - VMAX CCA 用户信息查询 API
==============================================
按号码查询 VMAX CCA 投诉系统的用户信息（IMSI/MSISDN 映射）与终端信息，
对接实现见 backend/services/vmax_cca/（协议复刻记录在其 README.md）。

- GET /api/vmax-cca-query?msisdn=777123456

只读透传查询，不做任何落库；号码在日志中掩码，不打印上游响应原文（含用户数据）。
鉴权走 main.py 的统一门户会话中间件（/api/* 全量要求登录），无需额外挂 require_protected。
"""
import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.services.vmax_cca.vmax_cca_client import (
    VmaxCcaError, VmaxCcaNotConfigured, VmaxCcaUnavailable, get_client,
    normalize_msisdn,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vmax-cca-query", tags=["vmax-cca-query"])


def _mask_msisdn(msisdn: str) -> str:
    """日志里只留号码头尾，中间打码。"""
    if len(msisdn) <= 6:
        return "*" * len(msisdn)
    return msisdn[:4] + "*" * (len(msisdn) - 6) + msisdn[-2:]


@router.get("")
def query_user_info(
    msisdn: str = Query(..., min_length=5, max_length=24),
    start: Optional[str] = Query(
        None, description="窗口起点 YYYY-MM-DD[ HH:MM:SS]，缺省今天 00:00:00"),
    end: Optional[str] = Query(
        None, description="窗口终点 YYYY-MM-DD[ HH:MM:SS]，缺省起点当天 23:59:00"),
):
    """输入号码 + 时间窗，返回用户信息（含 IMSI）、终端信息、窗口内流量与驻留小区。

    found=False 表示 VMAX 查无此号（业务正常，返回 200，由前端展示空态）。
    flow / cells 为 None 表示该窗口无数据（DPI / usertrack 无记录），同样是业务正常。
    """
    normalized = normalize_msisdn(msisdn)
    if not re.fullmatch(r"\d{5,20}", normalized):
        raise HTTPException(status_code=422, detail="号码格式不正确：请输入 231 开头的完整数字号码")
    try:
        result = get_client().query(normalized, start, end)
    except VmaxCcaNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VmaxCcaUnavailable as exc:
        logger.warning("[vmax_cca] 查询 %s 上游不可用: %s", _mask_msisdn(normalized), exc)
        raise HTTPException(status_code=502, detail="VMAX 查询服务暂不可用: %s" % exc) from exc
    except VmaxCcaError as exc:
        # normalize_window 的跨度超限也走这里（VmaxCcaError），给 422 更贴切
        if "时间窗" in str(exc):
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        logger.warning("[vmax_cca] 查询 %s 失败: %s", _mask_msisdn(normalized), exc)
        raise HTTPException(status_code=502, detail="VMAX 查询失败: %s" % exc) from exc
    except Exception as exc:                                         # noqa: BLE001
        logger.exception("[vmax_cca] 查询 %s 异常", _mask_msisdn(normalized))
        raise HTTPException(status_code=500, detail="VMAX 查询内部错误: %s" % type(exc).__name__) from exc
    return result

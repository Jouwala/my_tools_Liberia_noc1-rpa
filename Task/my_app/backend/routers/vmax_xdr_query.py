# -*- coding: utf-8 -*-
"""
vmax_xdr_query.py - Talon XDR 信令详单查询 API
==============================================
按号码 + 时间窗查询 Talon XDR 信令详单（合并表），服务前端的「VMAX 信令详单」页。
协议复刻与踩坑记录见 backend/services/vmax_cca/vmax_xdr_client.py 头注释。

- GET /api/vmax-xdr-query?msisdn=&service_type=1100&start=&end=&page=&page_size=

只读透传：不落库、不缓存（信令数据量大且属用户隐私）。
鉴权走 main.py 的统一门户会话中间件（/api/* 全量要求登录），无需额外挂载。
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.services.vmax_cca.vmax_cca_client import (
    VmaxCcaError, VmaxCcaNotConfigured, VmaxCcaUnavailable, normalize_msisdn,
)
from backend.services.vmax_cca.vmax_xdr_client import (
    XDR_SERVICES, VmaxXdrError, VmaxXdrUnsupported, get_xdr_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vmax-xdr-query", tags=["vmax-xdr-query"])

# 窗口跨度上限：信令详单一天可达万级记录，再大既慢又无意义
MAX_WINDOW_HOURS = 72


def _mask_msisdn(msisdn: str) -> str:
    """日志里只留号码头尾，中间打码（与 vmax_cca_query 同一口径）。"""
    if len(msisdn) <= 6:
        return "*" * len(msisdn)
    return msisdn[:4] + "*" * (len(msisdn) - 6) + msisdn[-2:]


def _parse_bound(raw: Optional[str], end_of: bool) -> datetime:
    """解析 "YYYY-MM-DD" / "YYYY-MM-DD HH:MM[:SS]"，日粒度补全天边界。"""
    if not raw:
        return datetime.now().replace(minute=59 if end_of else 0,
                                      second=59 if end_of else 0, microsecond=0)
    text = str(raw).strip().replace("T", " ")
    day_only = len(text) <= 10
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text[:16], "%Y-%m-%d %H:%M")
        except ValueError as exc:
            raise HTTPException(status_code=422,
                                detail="时间格式不正确：请用 YYYY-MM-DD 或 YYYY-MM-DD HH:MM") from exc
    if day_only:
        dt = dt.replace(hour=23 if end_of else 0, minute=59 if end_of else 0,
                        second=59 if end_of else 0)
    return dt


@router.get("/services")
def list_services():
    """可查询的 serviceType 清单（前端下拉直接用，避免中英文案两处维护）。"""
    return {"services": XDR_SERVICES}


@router.get("")
def query_xdr(
    msisdn: str = Query(..., min_length=5, max_length=24),
    service_type: str = Query("1100", description="serviceType，见 /api/vmax-xdr-query/services"),
    start: Optional[str] = Query(None, description="窗口起点 YYYY-MM-DD[ HH:MM]，缺省 24 小时前"),
    end: Optional[str] = Query(None, description="窗口终点 YYYY-MM-DD[ HH:MM]，缺省现在"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    """按号码查合并 XDR 信令详单。

    返回 field/header（列定义）与 rows（按列头绑好的字段名 -> 值），前端直接渲染表格。
    records 为总记录数，用于分页；records=0 是业务正常（该号码窗口内无该类型信令）。
    """
    normalized = normalize_msisdn(msisdn)
    if not re.fullmatch(r"\d{5,20}", normalized):
        raise HTTPException(status_code=422,
                            detail="号码格式不正确：请输入 231 开头的完整数字号码")

    end_dt = _parse_bound(end, end_of=True)
    start_dt = _parse_bound(start, end_of=False) if start else end_dt - timedelta(hours=24)
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt
    if end_dt - start_dt > timedelta(hours=MAX_WINDOW_HOURS):
        raise HTTPException(status_code=422,
                            detail="时间窗跨度不能超过 %d 小时" % MAX_WINDOW_HOURS)

    # 上游要求毫秒边界（与 CCA 的秒级窗口不同，见 vmax_xdr_client 头注释）
    fmt = "%Y-%m-%d %H:%M:%S.000"
    try:
        result = get_xdr_client().query(
            normalized, service_type, start_dt.strftime(fmt), end_dt.strftime(fmt),
            page=page, page_size=page_size)
    except VmaxXdrUnsupported as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except VmaxCcaNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VmaxCcaUnavailable as exc:
        logger.warning("[vmax_xdr] 查询 %s 上游不可用: %s", _mask_msisdn(normalized), exc)
        raise HTTPException(status_code=502, detail="XDR 查询服务暂不可用: %s" % exc) from exc
    except VmaxXdrError as exc:
        logger.warning("[vmax_xdr] 查询 %s 失败: %s", _mask_msisdn(normalized), exc)
        raise HTTPException(status_code=502, detail="XDR 查询失败: %s" % exc) from exc
    except VmaxCcaError as exc:
        logger.warning("[vmax_xdr] 查询 %s 异常: %s", _mask_msisdn(normalized), exc)
        raise HTTPException(status_code=502, detail="XDR 查询失败: %s" % exc) from exc
    except Exception as exc:                                          # noqa: BLE001
        logger.exception("[vmax_xdr] 查询 %s 内部异常", _mask_msisdn(normalized))
        raise HTTPException(status_code=500,
                            detail="XDR 查询内部错误: %s" % type(exc).__name__) from exc
    return result

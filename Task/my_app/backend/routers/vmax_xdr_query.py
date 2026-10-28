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
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.routers.vmax_xdr_common import (
    humanize_login as _humanize_login,
    humanize_upstream as _humanize_upstream,
    mask_msisdn as _mask_msisdn,
    parse_bound as _parse_bound,
)
from backend.services.vmax_cca.vmax_cca_client import (
    VmaxCcaError, VmaxCcaNotConfigured, VmaxCcaUnavailable, normalize_msisdn,
)
from backend.services.vmax_cca.vmax_xdr_client import (
    XDR_SERVICES, VmaxXdrError, VmaxXdrUnsupported, get_xdr_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vmax-xdr-query", tags=["vmax-xdr-query"])

# 窗口跨度上限（小时）统一由 XDR_SERVICES 每项的 retention_hours 决定：
# 不同 serviceType 在上游的保留时长不同，用同一个上限会让用户查到「不存在」
# 的时间段并收到看不懂的上游错误码。见 services/vmax_cca/vmax_xdr_client.py。
# 时间解析 / 号码脱敏 / 错误码翻译与「XDR Records」路由共用一份，见 vmax_xdr_common。


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

    spec = next((s for s in XDR_SERVICES if s["id"] == service_type), None)
    if spec is None:
        raise HTTPException(
            status_code=422,
            detail="serviceType %s 暂未接入；当前支持 %s"
                   % (service_type, ", ".join(s["id"] for s in XDR_SERVICES)))
    # 窗口上限跟着该类型的保留时长走（32 只留 ~24h，1100 等留 72h）
    max_hours = int(spec.get("retention_hours") or 72)
    default_hours = min(24, max_hours)

    end_dt = _parse_bound(end, end_of=True)
    start_dt = (_parse_bound(start, end_of=False) if start
                else end_dt - timedelta(hours=default_hours))
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt
    if end_dt - start_dt > timedelta(hours=max_hours):
        raise HTTPException(
            status_code=422,
            detail="%s 的时间窗跨度不能超过 %d 小时（上游只保留最近 %d 小时的数据）"
                   % (spec.get("name_zh") or spec["name"], max_hours, max_hours))

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
        raise HTTPException(status_code=502,
                            detail="XDR 查询服务暂不可用: %s" % _humanize_login(str(exc))) from exc
    except VmaxXdrError as exc:
        logger.warning("[vmax_xdr] 查询 %s 失败: %s", _mask_msisdn(normalized), exc)
        detail = _humanize_upstream(str(exc))
        # 上游原始文案仍留在日志里（带 operation code），便于排障；
        # 但不再把 3100100xxx 这种码直接甩给界面。
        if detail == str(exc):
            raise HTTPException(status_code=502, detail="XDR 查询失败: %s" % exc) from exc
        raise HTTPException(status_code=422, detail=detail) from exc
    except VmaxCcaError as exc:
        logger.warning("[vmax_xdr] 查询 %s 异常: %s", _mask_msisdn(normalized), exc)
        raise HTTPException(status_code=502, detail="XDR 查询失败: %s" % exc) from exc
    except Exception as exc:                                          # noqa: BLE001
        logger.exception("[vmax_xdr] 查询 %s 内部异常", _mask_msisdn(normalized))
        raise HTTPException(status_code=500,
                            detail="XDR 查询内部错误: %s" % type(exc).__name__) from exc
    return result

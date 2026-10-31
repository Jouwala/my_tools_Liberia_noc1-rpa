# -*- coding: utf-8 -*-
"""
vmax_flow_xdr.py - 按分类流量（由 XDR 用户面数据算出）
=====================================================
「VMAX 用户查询」页「流量信息」卡的**数据来源**。

## 为什么是独立路由

页面上那张「流量信息」卡有两级页签（数据|语音 + 流量|视频|网页|游戏|OTT语音|
OTT视频|TCP指标|控制面）。原先数据取自 CCA 的 `query_flow`（DPI 应用识别），
但**实测绝大多数用户查不到**（`total_flux="--"`、`app_flux="[]"`）——
CCA 网页同样为空。这是采集侧的问题，换查询参数解决不了。

于是改用 Talon XDR 的**用户面话单**（`fact_5gsa_psup_flow` 等）自己算：
每条话单带 service / 应用名 / 上下行流量与包数 / TCP 时延与重传，
足以还原出同构的分类结果。详见 services/vmax_cca/vmax_flow_from_xdr.py。

## 接口

- GET /api/vmax-flow-xdr?msisdn=&start=&end=

只读透传：不落库、不缓存（信令数据量大且属用户隐私）。
鉴权走 main.py 的统一门户会话中间件（/api/* 全量要求登录）。
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
from backend.services.vmax_cca.vmax_flow_from_xdr import VmaxFlowFromXdr
from backend.services.vmax_cca.vmax_xdr_client import (
    VmaxXdrError, VmaxXdrUnsupported, get_xdr_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vmax-flow-xdr", tags=["vmax-flow-xdr"])

# 上游用户面数据的保留时长与 XDR 其它类型一致（72h）。
MAX_WINDOW_HOURS = 72
# 缺省窗口：最近 3 小时（与页面顶部的默认时间窗同口径）
DEFAULT_WINDOW_HOURS = 3


@router.get("")
def query_flow_by_xdr(
    msisdn: str = Query(..., min_length=5, max_length=24),
    start: Optional[str] = Query(None, description="窗口起点 YYYY-MM-DD[ HH:MM]，缺省 3 小时前"),
    end: Optional[str] = Query(None, description="窗口终点 YYYY-MM-DD[ HH:MM]，缺省现在"),
):
    """号码 + 时间窗 -> 按分类流量（页签结构见 vmax_flow_from_xdr.py）。

    返回 {total_flux, total_flux_kb, apps, categories, source, records}：
      - categories：与页面二级页签一一对应，每项 {key, apps, kpis, total_flux}；
      - apps：全量应用列表（按流量降序，带占比）；
      - source：恒为 "xdr_user_plane"，前端据此标注数据来源。

    该号码窗口内无用户面记录时返回 `{"found": false, "categories": []}`
    （HTTP 200，业务正常）—— 用户没有上网记录是常态，不是故障。
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
            detail="时间窗跨度不能超过 %d 小时（上游只保留最近 %d 小时的用户面数据）"
                   % (MAX_WINDOW_HOURS, MAX_WINDOW_HOURS))

    # 上游要秒级窗口（这里用 CCA 的格式；vmax_flow_from_xdr 内部会转成
    # Talon 的毫秒边界并把 end 往后挪 1 分钟，避开上游的坏分区边界）
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        result = VmaxFlowFromXdr(get_xdr_client()).query(
            normalized, start_dt.strftime(fmt), end_dt.strftime(fmt))
    except VmaxXdrUnsupported as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except VmaxCcaNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VmaxCcaUnavailable as exc:
        logger.warning("[vmax_flow_xdr] 查询 %s 上游不可用: %s", _mask_msisdn(normalized), exc)
        raise HTTPException(
            status_code=502,
            detail="用户面流量查询服务暂不可用: %s" % _humanize_login(str(exc))) from exc
    except VmaxXdrError as exc:
        logger.warning("[vmax_flow_xdr] 查询 %s 失败: %s", _mask_msisdn(normalized), exc)
        detail = _humanize_upstream(str(exc))
        if detail == str(exc):
            raise HTTPException(status_code=502, detail="用户面流量查询失败: %s" % exc) from exc
        raise HTTPException(status_code=422, detail=detail) from exc
    except VmaxCcaError as exc:
        logger.warning("[vmax_flow_xdr] 查询 %s 异常: %s", _mask_msisdn(normalized), exc)
        raise HTTPException(status_code=502, detail="用户面流量查询失败: %s" % exc) from exc
    except Exception as exc:                                          # noqa: BLE001
        logger.exception("[vmax_flow_xdr] 查询 %s 内部异常", _mask_msisdn(normalized))
        raise HTTPException(status_code=500,
                            detail="用户面流量查询内部错误: %s" % type(exc).__name__) from exc

    if result is None:
        return {
            "found": False,
            "msisdn": normalized,
            "window": {"starttime": start_dt.strftime(fmt), "endtime": end_dt.strftime(fmt)},
            "total_flux": "—",
            "apps": [],
            "categories": [],
            "source": "xdr_user_plane",
            "records": 0,
        }
    result["found"] = True
    result["msisdn"] = normalized
    result["window"] = {"starttime": start_dt.strftime(fmt), "endtime": end_dt.strftime(fmt)}
    return result

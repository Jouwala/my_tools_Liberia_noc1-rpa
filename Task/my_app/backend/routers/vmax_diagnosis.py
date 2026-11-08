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
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.routers.vmax_xdr_common import (
    humanize_login as _humanize_login,
    mask_msisdn as _mask_msisdn,
    parse_bound as _parse_bound,
)
from backend.services.vmax_cca.vmax_cca_client import (
    VmaxCcaError, VmaxCcaNotConfigured, VmaxCcaUnavailable, normalize_msisdn,
)
from backend.services.vmax_cca.vmax_diagnosis import (
    DONE_EVENT, SOURCE_EVENT, VmaxDiagnosis,
)
from backend.services.vmax_cca.vmax_flow_from_xdr import VmaxFlowFromXdr
from backend.services.vmax_cca.vmax_xdr_client import get_xdr_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vmax-diagnosis", tags=["vmax-diagnosis"])

# 诊断要看四个源，最短保留期由 RAN(32) 决定 —— 24 小时。
# 超过这个窗口，32 一定空，结论里的「无线质量」会永远是「无数据可判」，
# 所以在入口就拦住，而不是让用户对着一堆空卡片猜。
MAX_WINDOW_HOURS = 24
DEFAULT_WINDOW_HOURS = 3

FMT_SEC = "%Y-%m-%d %H:%M:%S"


def _resolve_window(msisdn: str, start: Optional[str],
                    end: Optional[str]) -> Tuple[str, datetime, datetime]:
    """号码归一 + 时间窗解析（`GET` 与 `/stream` **共用一份**校验）。

    两个端点各写一套校验迟早会漂移（一个放宽、一个没放宽），
    所以窗口上限、号码格式、start>end 互换这些都收在这一个函数里。
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
    return normalized, start_dt, end_dt


def _flow_of(diag: VmaxDiagnosis,
             rows_1300: List[Dict[str, Any]],
             rows_1301: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], bool]:
    """把已取到的 1300/1301 行聚合成「业务流量」（P0'-1，复用不重取）。

    失败不影响诊断主体：返回 (None, False)，前端回退到 `/api/vmax-flow-xdr`。
    """
    try:
        flow = VmaxFlowFromXdr(diag.xdr).aggregate_from_rows(rows_1300, rows_1301)
        return flow, flow is not None
    except Exception as exc:                                      # noqa: BLE001
        logger.warning("[vmax_diagnosis] 流量复用聚合失败（前端将回退单查）: %s", exc)
        return None, False


def _sse_frame(event: str, data: Any) -> str:
    """SSE 单帧。`data:` 必须是单行（json.dumps 默认不换行），否则会被拆成多帧。"""
    return "event: %s\ndata: %s\n\n" % (
        event, json.dumps(data, ensure_ascii=False, default=str))


def _iter_stream_frames(diag: VmaxDiagnosis, normalized: str,
                        start: str, end: str) -> Iterator[str]:
    """逐帧产出 SSE 文本（2026-11-07 P3-1）。

    帧序：
      source × 4   —— 与 `fetch_all()` 里 sources 的单项同形（每源跑完就推）
      flow         —— 拿到 1300 + 1301 后立即推（业务流量页签不必等 32）
      done         —— {msisdn, window, imsi[, flow, flow_reused]}

    前端解析约定（`frontend/src/pages/useVmaxDiagnosis.ts`）：
      收到 source → 追加到 sources 并增量渲染；收到 flow → 填业务流量；
      收到 done   → 标记取数完成（**结论只在这之后才算**，避免半份数据
      先给出「没问题」的错误结论）；收到 error 或流中断 → 回退老接口。
    """
    rows_by_key: Dict[str, List[Dict[str, Any]]] = {}
    flow_sent = False
    for event, data in diag.iter_sources(normalized, start, end):
        if event == SOURCE_EVENT:
            key = data.get("key") or "?"
            rows_by_key[key] = data.get("rows") or []
            yield _sse_frame(SOURCE_EVENT, data)
            # 1300（12s）与 1301（1s）都到齐即可算流量，比等 32 早
            if not flow_sent and "1300" in rows_by_key and "1301" in rows_by_key:
                flow, reused = _flow_of(diag, rows_by_key["1300"], rows_by_key["1301"])
                yield _sse_frame("flow", {"flow": flow, "flow_reused": reused})
                flow_sent = True
        elif event == DONE_EVENT:
            meta: Dict[str, Any] = {
                "msisdn": normalized,
                "window": data.get("window") or {"start": start, "end": end},
                "imsi": data.get("imsi") or "",
            }
            if not flow_sent:   # 1300/1301 全失败也要给前端一个明确的 flow 结论
                flow, reused = _flow_of(diag, rows_by_key.get("1300") or [],
                                        rows_by_key.get("1301") or [])
                meta["flow"] = flow
                meta["flow_reused"] = reused
            yield _sse_frame(DONE_EVENT, meta)


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

    P3-1 起另有 `GET /stream`（SSE 渐进返回）；本接口保留为非流式路径与
    前端的失败回退目标，两者取数口径共用 `VmaxDiagnosis.iter_sources()`。
    """
    normalized, start_dt, end_dt = _resolve_window(msisdn, start, end)
    try:
        diag = VmaxDiagnosis(get_xdr_client())
        payload = diag.fetch_all(
            normalized, start_dt.strftime(FMT_SEC), end_dt.strftime(FMT_SEC))
        # P0'-1：诊断顺手算好流量聚合（复用 1300/1301 行，不再打上游）。
        rows_1300 = next(
            (s.get("rows") or [] for s in payload.get("sources", [])
             if s.get("key") == "1300"), [])
        rows_1301 = next(
            (s.get("rows") or [] for s in payload.get("sources", [])
             if s.get("key") == "1301"), [])
        flow, reused = _flow_of(diag, rows_1300, rows_1301)
        payload["flow"] = flow
        payload["flow_reused"] = reused
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
    payload["window"] = {"start": start_dt.strftime(FMT_SEC),
                         "end": end_dt.strftime(FMT_SEC)}
    return payload


@router.get("/stream")
def stream_diagnosis(
    msisdn: str = Query(..., min_length=5, max_length=24),
    start: Optional[str] = Query(None, description="窗口起点 YYYY-MM-DD[ HH:MM]，缺省 3 小时前"),
    end: Optional[str] = Query(None, description="窗口终点 YYYY-MM-DD[ HH:MM]，缺省现在"),
):
    """SSE 版诊断：每跑完一个源推一帧（2026-11-07 P3-1，按源渐进渲染）。

    为什么值得单开一个端点：四个源串行 ≈21s（见 vmax_diagnosis 模块头），
    其中 1300 约 12s。老接口要等 21s 才给任何内容，用户全程白屏；本端点
    1300 一到前端就能渲染分析，32 到了再补无线侧。

    **不改变原有契约**：`GET /api/vmax-diagnosis` 原样保留，前端在流失败
    （非 200 / 无 done 帧 / 网络中断）时回退到它 —— 最坏情况与今天完全一致。

    鉴权走 main.py 的统一门户会话中间件（与其它 /api 一致，需要 Cookie）。
    `X-Accel-Buffering: no` 让 nginx 不缓冲本响应（本仓库既有 SSE 端点
    `routers/incident_overview.py` 同款），**不需要改 nginx 配置**。
    """
    normalized, start_dt, end_dt = _resolve_window(msisdn, start, end)
    try:
        # 客户端在返回响应**之前**建好：配置缺失/上游不可用能给出正常的
        # 503/502，前端据此直接展示错误（流一旦开始就只能发 error 帧）。
        diag = VmaxDiagnosis(get_xdr_client())
    except VmaxCcaNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VmaxCcaUnavailable as exc:
        raise HTTPException(
            status_code=502,
            detail="诊断查询服务暂不可用: %s" % _humanize_login(str(exc))) from exc
    except VmaxCcaError as exc:
        raise HTTPException(status_code=502,
                            detail="诊断查询失败: %s" % exc) from exc

    frames = _iter_stream_frames(
        diag, normalized, start_dt.strftime(FMT_SEC), end_dt.strftime(FMT_SEC))
    return StreamingResponse(
        frames,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

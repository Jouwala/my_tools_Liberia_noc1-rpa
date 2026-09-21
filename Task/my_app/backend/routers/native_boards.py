# -*- coding: utf-8 -*-
"""原生看板 API（my-finebi 全部看板 → my_app 原生页）。

一套端点驱动 17 个看板，slug 见 native_catalog.CATALOG。

GET /api/native-boards
    -> {boards:[{slug,page,title,category,tags,widgets}]}
    前端用它渲染菜单 / 校验路由。

GET /api/native-boards/{slug}
    ?start=YYYY-MM-DD&end=YYYY-MM-DD   时间窗口（可选，须成对出现）
    ?force=1                           跳过缓存立即回源（前端「刷新」按钮）
    -> {meta:{...}, title, widgets:[{id,title,chart,pivot,pct,columns,rows,error,
                                    date_field,windowed}]}
    meta.window_supported 指示该页能否按日期过滤（不能时前端禁用时间控件）。
    meta.cached / stale / cache_age_s / cache_source 说明本次数据的缓存命中情况。

GET /api/native-boards/{slug}/export
    同上参数；返回 xlsx（每组件一个 sheet + 说明 sheet）。

GET /api/native-boards/{slug}/health
    远端连通性探测。

GET /api/native-boards/_cache/stats
    缓存概览（内存条数 / 磁盘条目 / TTL / 正在后台刷新的键）。

POST /api/native-boards/_cache/prewarm
    手动触发后台预热（幂等：全部命中时不做任何事）。

缓存策略（详见 dashboard_service 顶部说明）
    源数据天粒度更新，故 TTL 默认 6 小时（NATIVE_BOARD_CACHE_TTL 可调）。
    内存 LRU + 磁盘 JSON 双层：看门狗重启后磁盘缓存仍在，依然秒开。
    过期不阻塞：先返回旧数据，同时后台回源（stale-while-revalidate）。
"""
import logging
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from backend.services import dashboard_service as svc

logger = logging.getLogger("native_board")

router = APIRouter(prefix="/api/native-boards", tags=["native-boards"])


@router.get("")
def list_boards():
    """全部原生看板清单（轻量，不含 SQL）。"""
    return {"boards": svc.list_boards()}


# 注意：这两条必须放在 /{slug} 之前，否则 "_cache" 会被当成 slug
@router.get("/_cache/stats")
def cache_stats():
    """缓存概览：内存/磁盘条目、TTL、正在后台刷新的键。"""
    return svc.cache_stats()


@router.post("/_cache/prewarm")
def cache_prewarm():
    """手动触发后台预热（幂等）。"""
    return svc.prewarm()


@router.get("/{slug}")
def board_data(
    slug: str,
    start: str = Query("", description="开始日期 YYYY-MM-DD"),
    end: str = Query("", description="结束日期 YYYY-MM-DD"),
    force: int = Query(0, description="1=跳过缓存强制刷新"),
):
    """整页数据：内存/磁盘缓存 → 冷取数（可选时间窗口）。"""
    try:
        s, e = svc.validate_window(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return svc.get_board_data(slug, s, e, force=bool(force))
    except svc.BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{slug}/export")
def board_export(
    slug: str,
    start: str = Query("", description="开始日期 YYYY-MM-DD"),
    end: str = Query("", description="结束日期 YYYY-MM-DD"),
):
    """导出整页数据为 Excel（每组件一个 sheet + 说明 sheet）。"""
    try:
        s, e = svc.validate_window(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        data = svc.get_board_data(slug, s, e, force=True)
    except svc.BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        blob = svc.build_excel(data)
    except ImportError as exc:  # openpyxl 缺失
        raise HTTPException(
            status_code=500, detail=f"缺少 openpyxl，无法导出 Excel: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("导出 Excel 失败 slug=%s", slug)
        raise HTTPException(status_code=500, detail=f"导出失败: {exc}") from exc

    title = (data.get("title") or slug).replace(" ", "_")
    win = f"_{s}_{e}" if s else ""
    # RFC 5987：中文文件名走 filename*，ASCII 兜底
    fname_ascii = f"{slug}{win}_{date.today().isoformat()}.xlsx"
    fname_utf8 = quote(f"{title}{win}_{date.today().isoformat()}.xlsx")
    return Response(
        content=blob,
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"),
        headers={
            "Content-Disposition":
                f"attachment; filename=\"{fname_ascii}\"; "
                f"filename*=UTF-8''{fname_utf8}",
            "Content-Length": str(len(blob)),
            "Cache-Control": "no-store",
        },
    )


@router.get("/{slug}/health")
def board_health(slug: str):
    """远端只读 API 连通性探测。"""
    return svc.health(slug)

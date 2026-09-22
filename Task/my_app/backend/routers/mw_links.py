# -*- coding: utf-8 -*-
"""MW Links（KML 叠加图层）数据库化 API

GET  /api/mw-links/status    : kml_mw_links 当前状态（行数/站点/链路/导入时间）
GET  /api/mw-links/geojson   : 从数据库生成 GeoJSON（页面直接消费，替代静态文件）
POST /api/mw-links/import    : 上传 KML 更新 kml_mw_links（只写这一张表）
POST /api/mw-links/rebuild   : 由 kml_mw_links 重建 GeoJSON 静态回退副本

安全约束：本路由只操作 kml_mw_links 一张表，表名不接受任何外部参数，
因此不会影响 master_site_db / mw_ume_bw_* 等其他看板依赖的表。
"""
import logging
import os
import re
import uuid
import time
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from backend.database import DB_PATH
from backend.services.mw_ume import mw_links_store as store

logger = logging.getLogger("mw_links_router")
router = APIRouter(prefix="/api/mw-links", tags=["mw-links"])

UPLOAD_DIR = DB_PATH.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


@router.get("/status")
def status():
    """当前 kml_mw_links 状态。"""
    return store.table_status()


@router.get("/geojson")
def geojson():
    """从数据库生成 GeoJSON 供 MW 页面叠加图层消费。

    页面侧采用「先试本接口、失败回退静态 geojson」的双保险策略，
    因此这里在无数据时返回 404，让页面走回退分支而不是拿到空图层。
    """
    fc = store.build_geojson()
    if fc is None:
        raise HTTPException(status_code=404, detail="kml_mw_links 暂无数据，请先导入 KML")
    return JSONResponse(
        content=fc,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.post("/import")
async def import_kml(file: UploadFile = File(...)):
    """上传 KML 文件更新 kml_mw_links（整表替换，自动备份旧表）。"""
    raw_name = file.filename or "upload.kml"
    if not raw_name.lower().endswith(".kml"):
        raise HTTPException(status_code=400, detail="仅支持 .kml 文件")

    # 防御路径穿越
    base = re.sub(r'[\/\\]', '_', raw_name).split('\x00')[0]
    base = re.sub(r'[^\w.\-]', '_', base) or "upload.kml"
    safe_name = f"{uuid.uuid4().hex[:8]}_{base}"
    path = (UPLOAD_DIR / safe_name).resolve()
    if not str(path).startswith(str(UPLOAD_DIR.resolve()) + os.sep):
        raise HTTPException(status_code=400, detail="非法文件名")

    start = time.time()
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    with open(path, "wb") as f:
        f.write(content)

    try:
        stats = store.import_kml(str(path))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("[MW-LINKS] 导入失败")
        raise HTTPException(status_code=500, detail=f"导入失败: {e}")
    finally:
        try:
            os.remove(path)
        except Exception:
            pass

    # 导入后同步刷新静态回退副本
    try:
        store.export_geojson_files()
    except Exception as e:
        logger.warning("[MW-LINKS] 静态副本刷新失败（不影响页面走接口）: %s", e)

    st = store.table_status()
    logger.info("[MW-LINKS] 导入完成: %s", st)
    return {
        "ok": True,
        "filename": raw_name,
        "table": store.TABLE_NAME,
        "sites": stats["sites"],
        "links": stats["links"],
        "skipped": stats["skipped"],
        "rows": stats["total"],
        "elapsed_seconds": round(time.time() - start, 2),
        "status": st,
    }


@router.post("/rebuild")
def rebuild():
    """由 kml_mw_links 重建 GeoJSON（同时写静态回退副本）。"""
    st = store.table_status()
    if not st["exists"] or st["rows"] == 0:
        raise HTTPException(status_code=400, detail="kml_mw_links 暂无数据")
    res = store.export_geojson_files()
    if res is None:
        raise HTTPException(status_code=500, detail="GeoJSON 生成失败")
    return {"ok": True, "features": res["features"], "written": res["written"], "status": st}

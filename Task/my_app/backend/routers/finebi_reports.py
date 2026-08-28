"""FineBI 报表文件 API —— 列出/下载 FineBI 调度输出的最新 Excel（Task Report Files → FINEBI report 页签）

数据源：backend.services.finebi_report_sync 每小时从 FTP 192.168.100.19
/webroot/WEB-INF/schedule 各子文件夹同步最新一份 Excel 到本地 data/finebi_reports/<文件夹>/。
本模块只读本地目录，不触 FTP；下载接口限定在该目录内且仅放行 Excel 文件。
"""
import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["finebi_reports"])

_BASE = Path(__file__).resolve().parent.parent.parent
_FINEBI_DIR = _BASE / "data" / "finebi_reports"
_EXCEL_EXTS = (".xlsx", ".xls")


def _is_excel(name: str) -> bool:
    return name.lower().endswith(_EXCEL_EXTS) and not name.startswith("~$")


@router.get("/api/finebi-reports/latest")
def finebi_reports_latest():
    """每个 FineBI 文件夹最新一份 Excel（同步任务已保证每文件夹只留最新）。"""
    reports = []
    if _FINEBI_DIR.is_dir():
        for folder_dir in sorted(_FINEBI_DIR.iterdir(), key=lambda p: p.name.lower()):
            if not folder_dir.is_dir():
                continue
            files = [f for f in folder_dir.iterdir() if f.is_file() and _is_excel(f.name)]
            files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            if not files:
                continue
            f = files[0]
            reports.append({
                "folder": folder_dir.name,
                "name": f.name,
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
            })
    return {"reports": reports}


@router.get("/api/finebi-reports/download/{folder}/{filename:path}")
def finebi_reports_download(folder: str, filename: str):
    """下载指定 FineBI 报表：仅放行 data/finebi_reports/<folder>/ 内的 Excel 文件。"""
    if any(ch in filename for ch in ("/", "\\")) or filename.startswith("..") or folder.startswith(".."):
        raise HTTPException(status_code=400, detail="非法文件名")
    if not _is_excel(filename):
        raise HTTPException(status_code=403, detail="仅允许下载 Excel 文件")
    fpath = (_FINEBI_DIR / folder / filename).resolve()
    folder_dir = (_FINEBI_DIR / folder).resolve()
    if not fpath.is_file() or folder_dir not in fpath.parents:
        raise HTTPException(status_code=404, detail="文件不存在")
    quoted = quote(filename)
    return FileResponse(
        fpath,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )

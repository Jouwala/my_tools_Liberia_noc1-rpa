"""NUR 排除名单（TT_Exclude）上传接口。

=========================== 为什么独立成路由 ===========================

1. `tables.py` 已是 600+ 行的存量超限文件，按 AGENTS.md 三.2「改到它们时
   不得继续无度膨胀」，新功能独立成模块；
2. 语义上与 `tables.py` 的通用导入**不同**：通用导入用上传文件名当表名、
   用户自定；本接口表名**固定为 `tt_exclude`**，且多两道护栏。

=========================== 为什么表名必须固定 ===========================

`nur_calc` 读的是一个固定表名 `tt_exclude`。若沿用通用的「文件名即表名」，
用户传 `TT_Exclude.xlsx` 会建出 `tt_exclude_xlsx`，NUR 读不到 —— 表现为
「传了文件但数字没变」，极难排查。固定表名同时收紧了安全面：不能让用户
借这个入口覆盖任意表。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from backend.services import tt_exclude as tx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tables", tags=["tt-exclude"])


@router.post("/import-exclude")
async def import_exclude_list(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
    uploaded_by: str = Form(""),
):
    """上传 NUR 排除名单（TT_Exclude）—— 全量替换 `tt_exclude` 表。

    三个护栏（沿用 docs/upload-sheet-to-table-feasibility.md:195-200 的约定）：
      1. **禁止空导入** —— 空名单 = 没有任何单被排除，NUR 口径会静默变化；
      2. **格式校验** —— 票号须形如 TT202608090116，拦住「传错文件」；
      3. **dry_run** —— 先看「将替换 N 行 → 新 M 行、新增/移除各多少」再落库。

    上传人：系统当前**没有多用户体系**（见 helpContent.ts:950「No multi-user
    system」），故记录**客户端 IP**（经 nginx 反代由 --proxy-headers 还原为
    真实来源，见 backend/security.py:10-11），而不是伪造一个用户名 ——
    假的审计数据比没有审计数据更危险。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件")
    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx, .xls, .csv 文件")

    operator = (uploaded_by or "").strip() or \
        f"ip:{request.client.host if request.client else 'unknown'}"

    content = await file.read()
    try:
        tickets, rep = tx.parse_tickets(content, file.filename)
        result = tx.replace_all(tickets, source_file=file.filename,
                                uploaded_by=operator, dry_run=dry_run)
    except tx.ExcludeImportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("[TT-EXCLUDE] 导入失败")
        raise HTTPException(status_code=500, detail=f"导入失败: {e}")

    return {"ok": True, "filename": file.filename, "parse": rep,
            "change": result, "dry_run": dry_run, "operator": operator}


@router.get("/exclude-meta")
def get_exclude_meta():
    """当前排除名单的元信息（条数 / 内容时间 / 上传人 / 来源文件）。

    页面用它显示当前名单状态。注意展示的是 **_import_time（内容时间）**
    而非接口拉取时间 —— 后者会让人误以为名单很新（2026-10-05 真实踩坑：
    标签显示 16:47 很新，内容却全是 8 月初的）。
    """
    meta = tx.fetch_meta()
    tickets = tx.fetch_tickets()
    meta["tickets"] = sorted(tickets) if tickets else []
    return meta

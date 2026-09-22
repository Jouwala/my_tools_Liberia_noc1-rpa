"""文件上传 API"""
import logging
import os
import re
import uuid
import json
import time
import pandas as pd
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Depends

from backend.database import get_raw_connection, DB_PATH
from backend.dialect_helpers import write_df, ensure_table_indexes
from backend.services.profiler import DataProfiler
from backend.security import require_protected

router = APIRouter(prefix="/api/upload", tags=["upload"])

UPLOAD_DIR = DB_PATH.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


def clean_column_name(col: str) -> str:
    if not isinstance(col, str):
        col = str(col)
    col = col.strip()
    col = re.sub(r'[^\w\s]', '_', col)
    col = re.sub(r'\s+', '_', col)
    col = re.sub(r'_+', '_', col)
    col = col.strip('_').lower()
    if col and col[0].isdigit():
        col = f'col_{col}'
    return col or 'unnamed'


@router.post("", dependencies=[Depends(require_protected)])
async def upload_excel(file: UploadFile = File(...)):
    """上传Excel文件，自动建表入库，返回字段识别和质量问题"""
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx, .xls, .csv 文件")

    start_time = time.time()

    # 保存文件（防御路径穿越：剥离文件名中的目录分隔符/空字符，强制落在 UPLOAD_DIR 内）
    raw_name = file.filename or "upload.xlsx"
    _base = re.sub(r'[\/\\]', '_', raw_name).split('\x00')[0]
    _base = re.sub(r'[^\w.\-]', '_', _base) or "upload.xlsx"
    safe_name = f"{uuid.uuid4().hex[:8]}_{_base}"
    file_path = (UPLOAD_DIR / safe_name).resolve()
    if not str(file_path).startswith(str(UPLOAD_DIR.resolve()) + os.sep):
        raise HTTPException(status_code=400, detail="非法文件名")
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 读取Excel
    try:
        if file.filename.endswith('.csv'):
            xls_sheets = {"Sheet1": pd.read_csv(str(file_path))}
        else:
            xls = pd.ExcelFile(str(file_path), engine='openpyxl')
            xls_sheets = {s: pd.read_excel(xls, sheet_name=s) for s in xls.sheet_names}
            xls.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {str(e)}")

    with get_raw_connection(str(DB_PATH)) as conn:
        results = []

        for sheet_name, df in xls_sheets.items():
            if df.empty:
                continue

            # 清洗列名
            df.columns = [clean_column_name(c) for c in df.columns]

            # 处理重复列名
            seen = {}
            new_cols = []
            for c in df.columns:
                if c in seen:
                    seen[c] += 1
                    new_cols.append(f"{c}_{seen[c]}")
                else:
                    seen[c] = 0
                    new_cols.append(c)
            df.columns = new_cols

            # 删除全空列
            df = df.dropna(axis=1, how='all')

            # 生成表名：隔离在 upload_ 命名空间并加 uuid，避免覆盖系统表（如 master_site_db）
            table_name = f"upload_{uuid.uuid4().hex[:8]}_{clean_column_name(Path(raw_name).stem) or 'tbl'}"
            if len(xls_sheets) > 1:
                table_name = f"{table_name}_{clean_column_name(sheet_name)}"

            # 写入数据库
            write_df(df, table_name, if_exists="replace")

            # 建立索引（与 init_db / 表浏览器导入共用同一份约定）
            ensure_table_indexes(conn, table_name, df.columns)

            conn.commit()

            # 数据质量分析
            profile = DataProfiler.profile_table(df)
            conclusions = DataProfiler.generate_conclusions(profile)

            # 记录上传信息
            conn.execute("""
            INSERT INTO uploaded_files (filename, original_name, table_name, row_count, col_count, columns_info, quality_issues, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (safe_name, file.filename, table_name, len(df), len(df.columns),
                  json.dumps([{"name": c["name"], "type": c["dtype"], "type_category": c["type_category"]} for c in profile["columns"]], ensure_ascii=False),
                  json.dumps(profile["issues_summary"], ensure_ascii=False)))
            conn.commit()

            results.append({
                "sheet_name": sheet_name,
                "table_name": table_name,
                "row_count": len(df),
                "col_count": len(df.columns),
                "profile_summary": {
                    "quality_score": profile["quality_score"],
                    "issue_count": len(profile["issues_summary"]),
                    "issues": profile["issues_summary"][:10],
                },
                "conclusions": conclusions,
            })

        conn.close()
        elapsed = time.time() - start_time

        return {
            "filename": file.filename,
            "tables": results,
            "elapsed_seconds": round(elapsed, 2),
        }


@router.get("/history")
def get_upload_history():
    """获取上传历史"""
    with get_raw_connection() as conn:
        try:
            cursor = conn.execute("SELECT * FROM uploaded_files ORDER BY uploaded_at DESC LIMIT 50")
            columns = [desc[0] for desc in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return {"uploads": rows}
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_upload_history: exception swallowed", exc_info=True)
            return {"uploads": []}
        finally:
            conn.close()
"""数据表浏览 API"""
import io
import logging
import json
import re
import os
import time
import uuid
import sqlite3
from urllib.parse import quote
from fastapi import APIRouter, Query, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.database import get_raw_connection, list_tables, DB_PATH
from backend.dialect_helpers import table_columns, write_df, ensure_table_indexes
from backend.routers.upload import clean_column_name, UPLOAD_DIR
from backend.services.profiler import DataProfiler
import pandas as pd

router = APIRouter(prefix="/api/tables", tags=["tables"])
logger = logging.getLogger(__name__)

# ---------------- 列显示模板（持久化，跟随 DB_MODE 双模） ----------------
# 表名以 _ 开头：get_tables 列表接口会跳过下划线前缀表，Table Browser 不可见
TEMPLATE_TABLE = "_table_view_templates"


class ViewTemplateIn(BaseModel):
    table_name: str
    name: str
    columns: list


def _ensure_template_table(conn):
    """双模建表（sqlite/PG 语法一致），已存在则跳过。"""
    conn.execute(
        f'CREATE TABLE IF NOT EXISTS "{TEMPLATE_TABLE}" ('
        ' table_name TEXT NOT NULL,'
        ' name TEXT NOT NULL,'
        ' columns TEXT NOT NULL,'
        ' created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,'
        ' updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,'
        ' PRIMARY KEY (table_name, name))'
    )
    conn.commit()


@router.get("/view-templates")
def list_view_templates(table_name: str = Query(...)):
    """列出某表已保存的列显示模板"""
    with get_raw_connection() as conn:
        _ensure_template_table(conn)
        rows = conn.execute(
            f'SELECT table_name, name, columns, created_at, updated_at '
            f'FROM "{TEMPLATE_TABLE}" WHERE table_name = ? ORDER BY updated_at DESC',
            (table_name,)).fetchall()
        conn.close()
    result = []
    for r in rows:
        try:
            cols = json.loads(r[2])
            if not isinstance(cols, list):
                cols = []
        except Exception:
            cols = []
        result.append({
            "table_name": r[0], "name": r[1], "columns": cols,
            "created_at": str(r[3]), "updated_at": str(r[4]),
        })
    return {"templates": result}


@router.post("/view-templates")
def save_view_template(body: ViewTemplateIn):
    """保存列显示模板（同表同名覆盖）"""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="模板名称不能为空")
    if not body.columns:
        raise HTTPException(status_code=400, detail="列清单不能为空")
    cols = [str(c).strip() for c in body.columns if str(c).strip()][:200]
    if not cols:
        raise HTTPException(status_code=400, detail="列清单不能为空")
    with get_raw_connection() as conn:
        if body.table_name not in list_tables():
            conn.close()
            raise HTTPException(status_code=404, detail=f"表 {body.table_name} 不存在")
        _ensure_template_table(conn)
        # 双模 upsert（sqlite 3.24+ 与 PG 均支持 ON CONFLICT DO UPDATE）
        conn.execute(
            f'INSERT INTO "{TEMPLATE_TABLE}" (table_name, name, columns, updated_at) '
            'VALUES (?, ?, ?, CURRENT_TIMESTAMP) '
            'ON CONFLICT(table_name, name) DO UPDATE SET '
            'columns = excluded.columns, updated_at = CURRENT_TIMESTAMP',
            (body.table_name, name, json.dumps(cols, ensure_ascii=False)))
        conn.commit()
        conn.close()
    logging.getLogger(__name__).info(
        "[TEMPLATE] 保存列模板: %s / %s (%d 列)", body.table_name, name, len(cols))
    return {"ok": True, "name": name, "columns": cols}


@router.delete("/view-templates")
def delete_view_template(table_name: str = Query(...), name: str = Query(...)):
    """删除列显示模板"""
    with get_raw_connection() as conn:
        _ensure_template_table(conn)
        conn.execute(
            f'DELETE FROM "{TEMPLATE_TABLE}" WHERE table_name = ? AND name = ?',
            (table_name, name))
        conn.commit()
        conn.close()
    return {"ok": True}


def _column_metadata(conn, table_name):
    """返回 [{name, type, notnull, pk}]，双模兼容。

    sqlite 用表值函数 pragma_table_info（等价于 PRAGMA table_info，
    但不在 PG 分支出现 sqlite 方言字面量）；PG 用 information_schema.columns。
    """
    if isinstance(conn, sqlite3.Connection):
        rows = conn.execute(
            "SELECT name, type, notnull, pk FROM pragma_table_info(?)", (table_name,)
        ).fetchall()
        return [
            {"name": r[0], "type": r[1], "notnull": r[2], "pk": r[3]}
            for r in rows
        ]
    # 注意：多个 schema 可能都有同名表（如 app.eflow_tt 与 eflow.eflow_tt），
    # 若用 ANY(current_schemas(false)) 会把所有 schema 的列混合返回（如同时含
    # "Title" 与 "title"），生成的 WHERE "Title" LIKE ? 在 PG 上因大小写报
    # "字段 Title 不存在"。必须把列元数据限定到 search_path 中第一个包含该表的
    # schema —— 即 FROM "table" 实际解析到的那个 schema。
    rows = conn.execute(
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_name = ? "
        "  AND table_schema = ("
        "      SELECT table_schema FROM information_schema.tables "
        "      WHERE table_name = ? AND table_schema = ANY(current_schemas(false)) "
        "      ORDER BY array_position(current_schemas(false), table_schema) "
        "      LIMIT 1"
        "  ) "
        "ORDER BY ordinal_position", (table_name, table_name)
    ).fetchall()
    return [
        {"name": r[0], "type": r[1], "notnull": 1 if r[2] == "NO" else 0, "pk": 0}
        for r in rows
    ]


def _is_text_type(type_str):
    """判断列是否适合做 LIKE 文本搜索（双模）。"""
    t = (type_str or "").lower()
    return t in ("", "text") or "char" in t or "clob" in t

# 仅允许纯标识符作为列名/排序字段，杜绝 SQL 注入（原 sort_by/column 直接拼接到 SQL）
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(name: str) -> bool:
    return isinstance(name, str) and bool(_IDENT_RE.match(name))


def _build_search_clause(conn, table_name, search):
    """构建全文搜索 WHERE 子句与参数（分页/导出共用）。

    对表中所有列（含非 text 类型）执行 LIKE 模糊搜索：
    - text/varchar 等文本列：直接 "col" LIKE ?
    - bigint/integer/double precision/timestamp 等非文本列：
      用 CAST("col" AS TEXT) LIKE ? 转换后再匹配

    双模兼容：PG 与 SQLite 均支持 CAST(... AS TEXT)。
    上限 200 列防止极端宽表导致 OR 链过长。
    返回 (where_clause, params)。
    """
    if not search:
        return "", []
    col_info = _column_metadata(conn, table_name)
    if not col_info:
        return "", []

    MAX_COLS = 200
    conditions = []
    for c in col_info[:MAX_COLS]:
        name = c["name"]
        if _is_text_type(c["type"]):
            conditions.append(f'"{name}" LIKE ?')
        else:
            # 非文本类型列需 CAST 才能 LIKE（PG 严格，SQLite 也兼容）
            conditions.append(f'CAST("{name}" AS TEXT) LIKE ?')

    if not conditions:
        return "", []

    like_val = f"%{search}%"
    return " WHERE " + " OR ".join(conditions), [like_val] * len(conditions)


@router.get("")
def get_tables():
    """列出所有表和元信息"""
    with get_raw_connection() as conn:
        tables = list_tables()
        result = []

        for table_name in tables:
            if table_name.startswith('_'):
                continue
            try:
                row_count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
                col_info = _column_metadata(conn, table_name)
                columns = [{"name": c["name"], "type": c["type"], "notnull": c["notnull"], "pk": c["pk"]} for c in col_info]
                result.append({
                    "name": table_name,
                    "row_count": row_count,
                    "col_count": len(columns),
                    "columns": columns,
                })
            except Exception as e:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_tables: exception swallowed", exc_info=True)
                continue

        conn.close()
        return {"tables": result, "total": len(result)}


@router.get("/{table_name}/data")
def get_table_data(
    table_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: str = Query(None),
    sort_order: str = Query("asc"),
    search: str = Query(None),
):
    """分页读取表数据"""
    with get_raw_connection() as conn:

        # 验证表名存在
        tables = list_tables()
        if table_name not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")

        # 构建查询
        where_clause, params = _build_search_clause(conn, table_name, search)

        order_clause = ""
        if sort_by:
            if not _safe_ident(sort_by):
                conn.close()
                raise HTTPException(status_code=400, detail=f"非法排序列名: {sort_by}")
            direction = "ASC" if sort_order == "asc" else "DESC"
            order_clause = f' ORDER BY "{sort_by}" {direction}'

        offset = (page - 1) * page_size
        count_sql = f'SELECT COUNT(*) FROM "{table_name}"{where_clause}'
        total = conn.execute(count_sql, params).fetchone()[0]

        data_sql = f'SELECT * FROM "{table_name}"{where_clause}{order_clause} LIMIT {page_size} OFFSET {offset}'
        cursor = conn.execute(data_sql, params)
        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        conn.close()

        return {
            "data": rows,
            "columns": columns,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }


@router.get("/{table_name}/export")
def export_table_data(
    table_name: str,
    format: str = Query("xlsx"),
    search: str = Query(None),
    columns: str = Query(None),
    limit: int = Query(200000, ge=1, le=500000),
):
    """导出整表为文件（xlsx/csv），支持与分页浏览相同的 search 过滤。

    columns: 逗号分隔列名，仅导出所选列（缺省全部列）。
    服务端生成，大表不压前端内存；limit 默认 20 万行防内存溢出。
    """
    if format not in ("xlsx", "csv"):
        raise HTTPException(status_code=400, detail="format 必须为 xlsx 或 csv")
    with get_raw_connection() as conn:
        tables = list_tables()
        if table_name not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")
        # 选列导出：仅允许表中真实存在的标识符列名，杜绝 SQL 注入
        select_clause = "*"
        if columns:
            wanted = [c.strip() for c in columns.split(",") if c.strip()]
            bad = [c for c in wanted if not _safe_ident(c)]
            if bad:
                conn.close()
                raise HTTPException(status_code=400, detail=f"非法列名: {bad}")
            valid = {c["name"] for c in _column_metadata(conn, table_name)}
            sel = [c for c in wanted if c in valid]
            if not sel:
                conn.close()
                raise HTTPException(status_code=400, detail="所选列在表中均不存在")
            select_clause = ", ".join(f'"{c}"' for c in sel)
        where_clause, params = _build_search_clause(conn, table_name, search)
        # 向量化整表读取（与 profile 接口同款 read_sql_query，双模兼容）
        df = pd.read_sql_query(
            f'SELECT {select_clause} FROM "{table_name}"{where_clause} LIMIT {limit}',
            conn, params=params)
        conn.close()
    if df.empty:
        raise HTTPException(status_code=400, detail="表为空，无数据可导出")
    buf = io.BytesIO()
    if format == "xlsx":
        df.to_excel(buf, index=False, engine="openpyxl")
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"{table_name}.xlsx"
    else:
        # utf-8-sig 带 BOM，Excel 直接打开中文不乱码
        buf.write(df.to_csv(index=False).encode("utf-8-sig"))
        media_type = "text/csv"
        filename = f"{table_name}.csv"
    buf.seek(0)
    logging.getLogger(__name__).info(
        "[EXPORT] %s -> %s (%d 行)", table_name, format, len(df))
    return StreamingResponse(
        buf,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


# ---------------- 自定义导入：Excel/CSV → 用户命名的新表（写入当前数据库） ----------------
# 导入记账列：与 backend/scripts/init_db.py:113-115 完全同源（同名义列、同取值语义），
# 保证「表浏览器导入」与「系统初始化导入」产出的表结构一致，可互相替换。
IMPORT_META_COLS = ("_source_file", "_source_sheet", "_import_time")


def _attach_import_meta(df, source_file, source_sheet):
    """给待入库的 DataFrame 追加 3 个记账列（就地返回，不修改调用方对象）。

    - _source_file：原始上传文件名（非落盘的 uuid 临时名）
    - _source_sheet：来源工作表名（CSV 为 Sheet1）
    - _import_time：导入时刻 ISO 字符串

    列名以 ``_`` 开头：clean_column_name 会剥掉源表列名的前导下划线，
    因此这两个命名空间不会与用户表头冲突。
    """
    if any(c in df.columns for c in IMPORT_META_COLS):
        # 极端情况：源表头被清洗后恰好撞上记账列名，记账列让位（保留用户数据）
        df = df.drop(columns=[c for c in IMPORT_META_COLS if c in df.columns])
    df = df.copy()
    df["_source_file"] = source_file
    df["_source_sheet"] = source_sheet
    df["_import_time"] = pd.Timestamp.now().isoformat()
    return df


@router.post("/import")
async def import_excel_to_table(
    file: UploadFile = File(...),
    table_name: str = Form(...),
    overwrite: bool = Form(False),
    sheet: str = Form(""),
):
    """将 Excel/CSV 导入为一张（或多张）用户命名的新表，写入当前数据库。

    - table_name：目标表名，必须是合法标识符；拒绝以 _ 开头（内部表命名空间）与已存在表（除非 overwrite=True）。
    - sheet：可选。留空或 __all__ 表示全部 sheet；指定某个 sheet 名时只导入该 sheet，表名即 table_name。
    - 单 Sheet：直接用 table_name 建表；多 Sheet（未指定 sheet）：table_name_<sheet> 各建一张。
    - 列名自动清洗（clean_column_name），与 /api/upload 同源逻辑。
    """
    if not file.filename or not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx, .xls, .csv 文件")

    name = (table_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="表名不能为空")
    if name.startswith('_'):
        raise HTTPException(status_code=400, detail="表名不能以 _ 开头（_ 为内部表保留命名空间）")
    if not _safe_ident(name):
        raise HTTPException(
            status_code=400,
            detail=f"非法表名: {name}（只能含字母、数字、下划线，且以字母或下划线开头）",
        )

    # 防御路径穿越：文件名仅保留安全字符，强制落在 UPLOAD_DIR 内
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

    start_time = time.time()
    raw_sheet = sheet or ""
    want_sheet = raw_sheet.strip()
    if want_sheet.lower() in ("__all__", "all", "*"):
        want_sheet = ""
        raw_sheet = ""
    try:
        if raw_name.lower().endswith('.csv'):
            if want_sheet:
                raise HTTPException(status_code=400, detail="CSV 文件没有工作表，无需指定 sheet")
            xls_sheets = {"Sheet1": pd.read_csv(str(file_path))}
        else:
            xls = pd.ExcelFile(str(file_path), engine='openpyxl')
            all_sheets = list(xls.sheet_names)
            if want_sheet:
                # Excel 的 sheet 名允许首尾空格（如 "Master Site Database  "），
                # 前端传回的值可能被中间环节 strip 掉，故先精确匹配，再按去空格唯一匹配。
                if raw_sheet in all_sheets:
                    picked = [raw_sheet]
                else:
                    cands = [s for s in all_sheets if s.strip() == want_sheet]
                    if len(cands) == 1:
                        picked = cands
                    else:
                        hint = ", ".join(f'"{s}"' for s in all_sheets)
                        if not cands:
                            raise HTTPException(
                                status_code=400,
                                detail=f"工作表不存在: {want_sheet}（可用: {hint}）",
                            )
                        raise HTTPException(
                            status_code=400,
                            detail=f"工作表名不唯一（仅首尾空格不同）: {want_sheet}（可用: {hint}）",
                        )
            else:
                picked = all_sheets
            xls_sheets = {s: pd.read_excel(xls, sheet_name=s) for s in picked}
            xls.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {str(e)}")
    finally:
        try:
            os.remove(file_path)
        except Exception:
            pass

    sheet_names = list(xls_sheets.keys())

    # 目标表名：单 sheet 用原名；多 sheet 追加 _<clean(sheet)>
    if len(sheet_names) == 1:
        target_names = [name]
    else:
        seen = {}
        target_names = []
        for s in sheet_names:
            cand = f"{name}_{clean_column_name(s)}"
            if cand in seen:
                seen[cand] += 1
                cand = f"{cand}_{seen[cand]}"
            else:
                seen[cand] = 0
            target_names.append(cand)

    # 冲突检测（已存在且未勾选覆盖则 409）
    existing = set(list_tables())
    collide = [t for t in target_names if t in existing]
    if collide and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"表已存在: {', '.join(collide)}（勾选「覆盖已存在表」可替换）",
        )

    # 清洗各 sheet（列名标准化 + 去重列名 + 丢弃全空列）
    cleaned = []
    for tname, sheet_name in zip(target_names, sheet_names):
        df = xls_sheets[sheet_name]
        if df.empty:
            if len(xls_sheets) == 1:
                raise HTTPException(status_code=400, detail="文件内容为空，无可导入数据")
            continue
        df.columns = [clean_column_name(c) for c in df.columns]
        seen_c = {}
        new_cols = []
        for c in df.columns:
            if c in seen_c:
                seen_c[c] += 1
                new_cols.append(f"{c}_{seen_c[c]}")
            else:
                seen_c[c] = 0
                new_cols.append(c)
        df.columns = new_cols
        df = df.dropna(axis=1, how='all')
        cleaned.append((tname, sheet_name, df))

    created = []
    with get_raw_connection() as conn:
        for tname, sheet_name, df in cleaned:
            # 记账列：与 backend/scripts/init_db.py 的导入约定保持一致，
            # 任何来源的表都能追溯「哪个文件、哪个 sheet、什么时候导入的」。
            df = _attach_import_meta(df, raw_name, sheet_name)
            write_df(df, tname, if_exists="replace" if overwrite else "append")
            # 索引：与 init_db 初始化导入共用同一份约定（含 site_name / alarm_occur_time
            # 复合索引等），失败会记 warning 而非静默跳过。
            idx_names = ensure_table_indexes(conn, tname, df.columns, logger=logger)
            conn.commit()
            created.append({
                "table_name": tname,
                "sheet_name": sheet_name,
                "row_count": int(len(df)),
                "col_count": int(len(df.columns)),
                "indexes": idx_names,
            })
        conn.close()

    logging.getLogger(__name__).info(
        "[IMPORT] 自定义导入: %s -> %d 张表 (%s)", raw_name,
        len(created), ", ".join(c["table_name"] for c in created))
    return {
        "ok": True,
        "filename": raw_name,
        "tables": created,
        "elapsed_seconds": round(time.time() - start_time, 2),
    }


@router.get("/{table_name}/profile")
def get_table_profile(table_name: str):
    """字段画像（空值率、唯一值、分布、异常值）"""
    with get_raw_connection() as conn:
        tables = list_tables()

        if table_name not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")

        # 读取数据进行分析（限制最大行数以保证性能）
        df = pd.read_sql_query(f'SELECT * FROM "{table_name}" LIMIT 10000', conn)
        conn.close()

        if df.empty:
            raise HTTPException(status_code=400, detail="表为空，无法分析")

        profile = DataProfiler.profile_table(df)
        conclusions = DataProfiler.generate_conclusions(profile)

        return {
            "table_name": table_name,
            "profile": profile,
            "conclusions": conclusions,
        }


@router.get("/{table_name}/stats/{column}")
def get_column_stats(table_name: str, column: str):
    """单列详细统计"""
    with get_raw_connection() as conn:
        tables = list_tables()

        if table_name not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")

        if not _safe_ident(column):
            conn.close()
            raise HTTPException(status_code=400, detail=f"非法列名: {column}")

        df = pd.read_sql_query(f'SELECT "{column}" FROM "{table_name}" LIMIT 50000', conn)
        conn.close()

        series = df[column]
        stats = {
            "column": column,
            "total": len(series),
            "non_null": int(series.notna().sum()),
            "null_count": int(series.isna().sum()),
            "unique": int(series.nunique()),
        }

        if pd.api.types.is_numeric_dtype(series):
            stats.update({
                "mean": float(series.mean()) if series.notna().any() else None,
                "median": float(series.median()) if series.notna().any() else None,
                "std": float(series.std()) if series.notna().any() else None,
                "min": float(series.min()) if series.notna().any() else None,
                "max": float(series.max()) if series.notna().any() else None,
                "distribution": DataProfiler._get_distribution(series),
            })
        else:
            value_counts = series.value_counts().head(20)
            stats["value_counts"] = {str(k): int(v) for k, v in value_counts.items()}

        return stats


def _get_distribution(series: pd.Series) -> dict:
    """获取数值分布直方图数据"""
    import numpy as np
    clean = series.dropna()
    if len(clean) == 0:
        return {}
    counts, bins = np.histogram(clean, bins=20)
    return {
        "bins": [round(float(b), 2) for b in bins],
        "counts": [int(c) for c in counts],
    }

# 添加静态方法到DataProfiler
DataProfiler._get_distribution = staticmethod(_get_distribution)
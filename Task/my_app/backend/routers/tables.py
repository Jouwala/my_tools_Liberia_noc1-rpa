"""数据表浏览 API"""
import io
import logging
import json
import re
import sqlite3
from urllib.parse import quote
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.database import get_raw_connection, list_tables
from backend.dialect_helpers import table_columns
from backend.services.profiler import DataProfiler
import pandas as pd

router = APIRouter(prefix="/api/tables", tags=["tables"])

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
    rows = conn.execute(
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_name = ? AND table_schema = ANY(current_schemas(false)) "
        "ORDER BY ordinal_position", (table_name,)
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
    """构建全文搜索 WHERE 子句与参数（分页/导出共用）。返回 (where_clause, params)"""
    if not search:
        return "", []
    col_info = _column_metadata(conn, table_name)
    text_cols = [c["name"] for c in col_info if _is_text_type(c["type"])]
    if not text_cols:
        return "", []
    conditions = [f'"{c}" LIKE ?' for c in text_cols[:10]]
    return " WHERE " + " OR ".join(conditions), [f"%{search}%"] * min(len(text_cols), 10)


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
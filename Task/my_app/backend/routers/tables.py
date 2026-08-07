"""数据表浏览 API"""
import logging
import json
import re
import sqlite3
from fastapi import APIRouter, Query, HTTPException
from backend.database import get_raw_connection, list_tables
from backend.dialect_helpers import table_columns
from backend.services.profiler import DataProfiler
import pandas as pd

router = APIRouter(prefix="/api/tables", tags=["tables"])


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
        where_clause = ""
        text_cols = []
        if search:
            # 全文搜索：在所有文本列中搜索
            col_info = _column_metadata(conn, table_name)
            text_cols = [c["name"] for c in col_info if _is_text_type(c["type"])]
            if text_cols:
                conditions = [f'"{c}" LIKE ?' for c in text_cols[:10]]
                where_clause = " WHERE " + " OR ".join(conditions)

        order_clause = ""
        if sort_by:
            if not _safe_ident(sort_by):
                conn.close()
                raise HTTPException(status_code=400, detail=f"非法排序列名: {sort_by}")
            direction = "ASC" if sort_order == "asc" else "DESC"
            order_clause = f' ORDER BY "{sort_by}" {direction}'

        offset = (page - 1) * page_size
        count_sql = f'SELECT COUNT(*) FROM "{table_name}"{where_clause}'
        params = [f'%{search}%'] * min(len(text_cols), 10) if search else []

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
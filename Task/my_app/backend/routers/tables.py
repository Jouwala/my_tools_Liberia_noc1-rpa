"""数据表浏览 API"""
import json
import sqlite3
from fastapi import APIRouter, Query, HTTPException
from backend.database import get_raw_connection, list_tables
from backend.services.profiler import DataProfiler
import pandas as pd

router = APIRouter(prefix="/api/tables", tags=["tables"])


@router.get("")
def get_tables():
    """列出所有表和元信息"""
    conn = get_raw_connection()
    tables = list_tables()
    result = []

    for table_name in tables:
        if table_name.startswith('_'):
            continue
        try:
            row_count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            col_info = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            columns = [{"name": c[1], "type": c[2], "notnull": c[3], "pk": c[5]} for c in col_info]
            result.append({
                "name": table_name,
                "row_count": row_count,
                "col_count": len(columns),
                "columns": columns,
            })
        except Exception as e:
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
    conn = get_raw_connection()

    # 验证表名存在
    tables = list_tables()
    if table_name not in tables:
        conn.close()
        raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")

    # 构建查询
    where_clause = ""
    if search:
        # 全文搜索：在所有文本列中搜索
        col_info = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        text_cols = [c[1] for c in col_info if c[2].upper() in ('TEXT', 'VARCHAR', '')]
        if text_cols:
            conditions = [f'"{c}" LIKE ?' for c in text_cols[:10]]
            where_clause = " WHERE " + " OR ".join(conditions)

    order_clause = ""
    if sort_by:
        order_clause = f' ORDER BY "{sort_by}" {"ASC" if sort_order == "asc" else "DESC"}'

    offset = (page - 1) * page_size
    count_sql = f'SELECT COUNT(*) FROM "{table_name}"{where_clause}'
    params = [f'%{search}%'] * min(len([c for c in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall() if c[2].upper() in ('TEXT', 'VARCHAR', '')]), 10) if search else []

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
    conn = get_raw_connection()
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
    conn = get_raw_connection()
    tables = list_tables()

    if table_name not in tables:
        conn.close()
        raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")

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

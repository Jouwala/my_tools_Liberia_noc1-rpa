"""分析归档 API"""
import logging
import json
import sqlite3
from datetime import datetime
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from backend.database import get_raw_connection, DB_PATH
from backend.dialect_helpers import list_table_names
from backend.services.profiler import DataProfiler
import pandas as pd


def _rows_as_dicts(cursor):
    """cursor -> [dict, ...]（双模：sqlite Row / PG 元组均兼容）"""
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


def _row_as_dict(cursor):
    """单行 cursor -> dict 或 None（双模兼容）"""
    cols = [d[0] for d in cursor.description]
    r = cursor.fetchone()
    return dict(zip(cols, r)) if r is not None else None


router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class AnalysisCreate(BaseModel):
    name: str
    description: Optional[str] = None
    table_name: str
    chart_config: Optional[dict] = None
    conclusions: Optional[List[str]] = None


class AnalysisUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    chart_config: Optional[dict] = None
    conclusions: Optional[List[str]] = None


@router.post("")
def create_analysis(req: AnalysisCreate):
    """创建分析任务，自动生成图表配置和结论并归档"""
    with get_raw_connection(str(DB_PATH)) as conn:
        if isinstance(conn, sqlite3.Connection):
            conn.row_factory = sqlite3.Row

        # 检查表是否存在
        tables = list_table_names(conn)
        if req.table_name not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail=f"表 {req.table_name} 不存在")

        # 读取数据生成分析
        df = pd.read_sql_query(f'SELECT * FROM "{req.table_name}" LIMIT 10000', conn)

        profile = DataProfiler.profile_table(df)
        auto_conclusions = DataProfiler.generate_conclusions(profile)

        # 自动生成图表配置
        chart_config = _generate_chart_config(df, profile, req.table_name)

        # 合并用户结论和自动结论
        all_conclusions = (req.conclusions or []) + auto_conclusions

        # 快照数据：关键统计
        snapshot = {
            "profile_summary": {
                "total_rows": profile["total_rows"],
                "total_cols": profile["total_cols"],
                "quality_score": profile["quality_score"],
                "issue_count": len(profile["issues_summary"]),
            },
            "top_issues": profile["issues_summary"][:20],
            "column_types": {c["name"]: c["type_category"] for c in profile["columns"]},
        }

        cursor = conn.execute("""
        INSERT INTO analysis_archive (name, description, table_name, chart_config, conclusions, snapshot_data)
        VALUES (?, ?, ?, ?, ?, ?)
        RETURNING id
        """, (
            req.name,
            req.description,
            req.table_name,
            json.dumps(chart_config, ensure_ascii=False),
            json.dumps(all_conclusions, ensure_ascii=False),
            json.dumps(snapshot, ensure_ascii=False),
        ))
        conn.commit()
        analysis_id = cursor.fetchone()[0]
        conn.close()

        return {
            "id": analysis_id,
            "name": req.name,
            "table_name": req.table_name,
            "chart_config": chart_config,
            "conclusions": all_conclusions,
        }


@router.get("")
def list_analyses(
    search: str = Query(None),
    table_name: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """查询历史分析列表（归档检索）"""
    with get_raw_connection(str(DB_PATH)) as conn:
        if isinstance(conn, sqlite3.Connection):
            conn.row_factory = sqlite3.Row

        where_parts = []
        params = []

        if search:
            where_parts.append("(name LIKE ? OR description LIKE ? OR conclusions LIKE ?)")
            params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])

        if table_name:
            where_parts.append("table_name = ?")
            params.append(table_name)

        where_clause = " WHERE " + " AND ".join(where_parts) if where_parts else ""
        offset = (page - 1) * page_size

        total = conn.execute(f"SELECT COUNT(*) FROM analysis_archive{where_clause}", params).fetchone()[0]
        rows = _rows_as_dicts(conn.execute(
            f"SELECT id, name, description, table_name, created_at, updated_at FROM analysis_archive{where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [page_size, offset]
        ))

        conn.close()

        return {
            "analyses": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/{analysis_id}")
def get_analysis(analysis_id: int):
    """获取单个分析详情"""
    with get_raw_connection(str(DB_PATH)) as conn:
        if isinstance(conn, sqlite3.Connection):
            conn.row_factory = sqlite3.Row

        row = _row_as_dict(conn.execute("SELECT * FROM analysis_archive WHERE id = ?", (analysis_id,)))
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="分析记录不存在")

        result = row
        # 解析JSON字段
        for field in ['chart_config', 'conclusions', 'snapshot_data']:
            if result.get(field):
                try:
                    result[field] = json.loads(result[field])
                except Exception:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_analysis: exception swallowed", exc_info=True)
                    pass

        conn.close()
        return result


@router.delete("/{analysis_id}")
def delete_analysis(analysis_id: int):
    """删除分析记录"""
    with get_raw_connection(str(DB_PATH)) as conn:
        cursor = conn.execute("DELETE FROM analysis_archive WHERE id = ?", (analysis_id,))
        conn.commit()
        conn.close()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="分析记录不存在")

        return {"deleted": True, "id": analysis_id}


def _as_numeric_metric(s: pd.Series):
    """把一列转换为可用于聚合(.mean 等)的数值序列；无法安全数值化时返回 None。

    存量 500 的两类根因都在这里被拦下：
    - 布尔列：pandas 中 bool 属 numeric_dtype，但其 quantile/IQR 会抛
      TypeError: numpy boolean subtract，且"布尔求均值"语义可疑 → 直接排除。
    - 文本列：type_category 只是"名字像数值"（如 total_items / down_site_count /
      sla_deadline 实为 str），直接 .mean() 会抛 dtype 'str' does not support 'mean'。
      这里尝试 to_numeric，若可转换值占比不足 50%，视为真正文本列并返回 None。
    """
    if pd.api.types.is_bool_dtype(s):
        return None
    if pd.api.types.is_numeric_dtype(s):
        return s
    non_null = int(s.notna().sum())
    if non_null == 0:
        return None
    try:
        conv = pd.to_numeric(s, errors="coerce")
    except (TypeError, ValueError):
        return None
    if int(conv.notna().sum()) / non_null < 0.5:
        return None
    return conv


def _generate_chart_config(df: pd.DataFrame, profile: dict, table_name: str) -> dict:
    """根据数据特征自动生成图表配置"""
    charts = []
    columns = profile["columns"]

    # 找分类字段（适合做饼图/柱状图）
    cat_cols = [c for c in columns if c["type_category"] in ("分类", "文本-分类", "地理区域") and c["unique_count"] <= 30 and c["unique_count"] > 1]

    # 找数值字段候选（适合做柱状图/折线图）。
    # ⚠️ type_category 只是"名字像数值"的线索，实际 dtype 必须再校验，
    # 否则 str 列会带着 .mean() 直接 500（见 _as_numeric_metric）。
    num_candidates = [c for c in columns if "数值" in c.get("type_category", "") or c.get("type_category") in ("计数/数量", "时长/SLA")]

    # 找时间字段
    time_cols = [c for c in columns if c["type_category"] in ("时间", "日期时间")]

    # 1. 分类字段 -> 饼图
    for col in cat_cols[:3]:
        if col["name"] not in df.columns:
            continue
        try:
            value_counts = df[col["name"]].value_counts().head(10).to_dict()
            charts.append({
                "type": "pie",
                "title": f"{col['name']} 分布",
                "chart_key": "distribution",
                "column": col["name"],
                "data": [{"name": str(k), "value": int(v)} for k, v in value_counts.items()],
            })
        except Exception:
            logging.getLogger(__name__).warning(
                "[_generate_chart_config] pie 生成失败 table=%s col=%s", table_name, col["name"], exc_info=True)

    # 2. 分类字段 vs 数值字段 -> 柱状图（数值列先做 dtype 校验/转换，再聚合）
    # 按顺序挑出前 2 个"真正可数值化"的列，避免前两个候选恰好都不可用时白丢图表。
    metrics = []
    for c in num_candidates[:12]:
        if len(metrics) >= 2:
            break
        if c["name"] not in df.columns:
            continue
        metric_series = _as_numeric_metric(df[c["name"]])
        if metric_series is not None:
            metrics.append((c["name"], metric_series))

    if cat_cols and metrics:
        for cat_col in cat_cols[:2]:
            if cat_col["name"] not in df.columns:
                continue
            for metric_name, metric_series in metrics:
                try:
                    frame = pd.DataFrame({
                        "__cat": df[cat_col["name"]],
                        "__val": metric_series,
                    })
                    grouped = frame.groupby("__cat")["__val"].mean().dropna().head(15).to_dict()
                    if not grouped:
                        continue
                    charts.append({
                        "type": "bar",
                        "title": f"{cat_col['name']} vs {metric_name} (均值)",
                        "chart_key": "mean_comparison",
                        "x_column": cat_col["name"],
                        "y_column": metric_name,
                        "data": [{"name": str(k), "value": round(float(v), 2) if pd.notna(v) else 0} for k, v in grouped.items()],
                    })
                except Exception:
                    logging.getLogger(__name__).warning(
                        "[_generate_chart_config] bar 生成失败 table=%s: %s vs %s",
                        table_name, cat_col["name"], metric_name, exc_info=True)
                    continue

    # 3. 时间字段 -> 时间趋势
    for time_col in time_cols[:1]:
        if time_col["name"] in df.columns:
            try:
                df[time_col["name"]] = pd.to_datetime(df[time_col["name"]], errors='coerce')
                daily = df.groupby(df[time_col["name"]].dt.date).size()
                if len(daily) > 1:
                    charts.append({
                        "type": "line",
                        "title": f"{time_col['name']} 趋势",
                        "chart_key": "trend",
                        "x_column": time_col["name"],
                        "data": [{"date": str(k), "count": int(v)} for k, v in daily.tail(60).items()],
                    })
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _generate_chart_config: exception swallowed", exc_info=True)
                pass

    # 4. 质量分数雷达图
    radar_data = []
    for col in columns[:10]:
        score = 100 - col.get("null_rate", 0) - min(col.get("issue_count", 0) * 10, 50)
        radar_data.append({"name": col["name"][:15], "score": max(score, 0)})
    if radar_data:
        charts.append({
            "type": "radar",
            "title": "字段质量雷达",
            "chart_key": "quality_radar",
            "data": radar_data,
        })
    # 5. SLA热力图 - 如果有 sla_status 和分类字段
    sla_col = next((c for c in columns if 'sla' in c['name'].lower()), None)
    if sla_col and cat_cols:
        for cat_col in cat_cols[:2]:
            if cat_col['name'] in df.columns and sla_col['name'] in df.columns:
                try:
                    ct = pd.crosstab(df[cat_col['name']], df[sla_col['name']])
                    ct = ct.head(15)
                    heatmap_data = []
                    y_cats = list(ct.index)
                    x_cats = list(ct.columns)
                    for yi, yv in enumerate(y_cats):
                        for xi, xv in enumerate(x_cats):
                            val = int(ct.iloc[yi, xi]) if pd.notna(ct.iloc[yi, xi]) else 0
                            heatmap_data.append([xi, yi, val])
                    charts.append({
                        "type": "heatmap",
                        "title": f"{cat_col['name']} vs {sla_col['name']} (SLA达成)",
                        "chart_key": "sla_heatmap",
                        "x_column": sla_col['name'],
                        "y_column": cat_col['name'],
                        "x_labels": [str(x) for x in x_cats],
                        "y_labels": [str(y) for y in y_cats],
                        "data": heatmap_data,
                    })
                except Exception:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] _generate_chart_config: exception swallowed", exc_info=True)
                    pass

    # 6. 状态vs分类 热力图
    status_col = next((c for c in columns if c['name'] == 'status' or c['type_category'] == '分类'), None)
    if status_col and len(cat_cols) > 1:
        region_col = next((c for c in cat_cols if 'region' in c['name'].lower()), cat_cols[0] if cat_cols else None)
        if region_col and region_col['name'] != status_col['name']:
            if region_col['name'] in df.columns and status_col['name'] in df.columns:
                try:
                    ct2 = pd.crosstab(df[region_col['name']], df[status_col['name']])
                    ct2 = ct2.head(15)
                    hm2 = []
                    y2 = list(ct2.index)
                    x2 = list(ct2.columns)
                    for yi, yv in enumerate(y2):
                        for xi, xv in enumerate(x2):
                            val = int(ct2.iloc[yi, xi]) if pd.notna(ct2.iloc[yi, xi]) else 0
                            hm2.append([xi, yi, val])
                    charts.append({
                        "type": "heatmap",
                        "title": f"{region_col['name']} vs {status_col['name']}",
                        "chart_key": "status_heatmap",
                        "x_column": status_col['name'],
                        "y_column": region_col['name'],
                        "x_labels": [str(x) for x in x2],
                        "y_labels": [str(y) for y in y2],
                        "data": hm2,
                    })
                except Exception:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] _generate_chart_config: exception swallowed", exc_info=True)
                    pass

    return {
        "table_name": table_name,
        "charts": charts,
        "generated_at": datetime.now().isoformat(),
    }
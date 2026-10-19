# -*- coding: utf-8 -*-
"""CN KPI 5 分钟看板数据服务（?page=cn_kpi_5mins）

=========================== 数据源 ===========================

`cnn_kpi_sync_5mins` 任务（每 15 分钟）写入的 `5mins_*` 表，位于远端
db_ps_cs_cn.sqlite3。读取走远端只读 SQL API（`cn_kpi_service.query_remote`），
与 `cn_kpi` 看板同一套通道。

=========================== Day0 / Day1 拆分 ===========================

图要把「今天」与「昨天」两条曲线叠画。拆分**在 SQL 里完成**，输出三列
    [HH:MM, 'Day0' | 'Day1', 值]
前端 `CnKpi5mins.tsx` 复用 `pivot` 机制（按第 2 列透视成多序列），不需要任何
新的拆分逻辑。

日切基准：`substr("End Time", 1, 10)`
    · "Day0" = 今天；"Day1" = 昨天。
    · 用 End Time 而不是 Begin Time：5 分钟窗口是 [00:00, 00:05)，用 End Time
      与 `cn_kpi` 看板既有的 `substr("End Time",1,10)` 口径保持一致。

x 轴：`substr("End Time", 12, 5)` → "00:05"。两条序列共用同一 HH:MM 轴，
所以 00:05 的今天值会与 00:05 的昨天值对齐，这正是叠画对比想要的。

=========================== 上游无 5 分钟数据的 3 个模板 ===========================

xGW_LICENSE / xGW_CPU_USAGE / 3G_FDD_DATA_TRAFFIC 上游恒无 5 分钟数据
（见 `cnn_ume_kpi_5mins_service.py` 文件头实测），因此它们对应的 5mins_ 表
**根本不存在**。组件查询会失败 → 本服务把它标记为 `empty: true` 并给出
**业务原因**（而不是抛错让整页红掉），前端显示空态卡片。

=========================== 缓存 ===========================

整页结果 TTL 30s。任务每 15 分钟才写一次，30s 已能挡住翻页/重刷的重复查询，
又不会让刚跑完的任务结果被缓存挡太久。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from backend.services.cn_kpi_service import REMOTE_DB, query_remote

logger = logging.getLogger("cn_kpi_5mins")

# 结果 TTL（秒）：任务 15 分钟写一次，30s 足够吸收翻页/连点刷新
CACHE_TTL = 30

# 并发上限：远端 db_writer_api 单机服务，8 个组件并发已够
MAX_WORKERS = 6

# 上游无数据的表 → 展示给用户的原因（前端据此显示「无数据」而非「查询失败」）
#
# 2026-10-19 起清空：xGW License / xGW CPU / 3G FDD 三个原模板虽无 5 分钟档，
# 但上游同日补建了 15 分钟档模板，`cnn_ume_kpi_5mins_service.FIFTEEN_MIN_TEMPLATES`
# 已切换到那 3 个新模板并正常产出数据。故本表暂时没有「已知无数据」的组件。
# 保留该机制：将来上游再调整档位、导致某表确实为空时，在此登记原因即可，
# 无需改前端（`_fetch_widget` 会直接返回业务空态，且不去远端打一次注定失败的查询）。
UNAVAILABLE_TABLES: Dict[str, str] = {}


# ----------------------------------------------------------------------
# SQL 片段复用
# ----------------------------------------------------------------------
# Day0/Day1 标签：外层比较当前日期。
# 用 SQLite 的 date('now') 让「今天」随时间自然滚动，无需前端传日期。
_DAY_LABEL = (
    "CASE WHEN substr(\"End Time\",1,10) = date('now') THEN 'Day0' "
    "WHEN substr(\"End Time\",1,10) = date('now','-1 day') THEN 'Day1' END"
)
# x 轴：HH:MM
_TIME_KEY = "substr(\"End Time\",12,5)"
# 时间窗口：近 2 天（今天 + 昨天）。用 End Time 过滤，与标签口径一致。
_WINDOW = "\"End Time\" >= date('now','-1 day') AND \"End Time\" < date('now','+1 day')"


def _agg_sql(table: str, value_expr: str, series_name: str,
             extra_where: str = "") -> str:
    """生成一个「按 HH:MM 聚合 + 打 Day0/Day1 标签」的 3 列 SQL。

    value_expr：对指标列的聚合表达式（如 SUM("x") 或 ROUND(SUM("x")/1e6,2)）
    extra_where：附加过滤（如 RG 编号）
    """
    where = _WINDOW + (f" AND {extra_where}" if extra_where else "")
    return (
        f'SELECT {_TIME_KEY} AS t, {_DAY_LABEL} AS day, '
        f'{value_expr} AS "{series_name}" '
        f'FROM "{table}" WHERE {where} '
        f"GROUP BY t, day ORDER BY t"
    )


# ----------------------------------------------------------------------
# 组件清单（8 个，与 cnn_kpi_sync_5mins 的 8 个模板一一对应）
# ----------------------------------------------------------------------
# chart 统一用 line + pivot=True（三列 [HH:MM, Day0/Day1, 值]）。
# pct=True 的组件纵轴格式化为百分比。
WIDGETS: List[Dict[str, Any]] = [
    {
        "id": "vlr",
        "title": "VLR Subscribers",
        "table": "5mins_VLR_SUBSCRIBERS_TEMPLATE_OSS_UME",
        "sql": _agg_sql("5mins_VLR_SUBSCRIBERS_TEMPLATE_OSS_UME",
                        'SUM("Number of Subscribers in VLR")', "VLR Subscribers"),
    },
    {
        "id": "voice",
        "title": "Voice Traffic(Erl)",
        "table": "5mins_VOICE_TRAFFIC_TEMPLATE_OSS_UME",
        "sql": _agg_sql("5mins_VOICE_TRAFFIC_TEMPLATE_OSS_UME",
                        'ROUND(SUM("Seized Traffic(Erl)"),2)', "Voice Traffic(Erl)"),
    },
    {
        "id": "data_sub",
        "title": "Data Subscribers",
        "table": "5mins_DATA_SUBSCRIBERS_TEMPLATE_OSS_UME",
        "sql": _agg_sql(
            "5mins_DATA_SUBSCRIBERS_TEMPLATE_OSS_UME",
            "ROUND(SUM(COALESCE(\"Mean number of attached subscribers(GSM)\",0)"
            "+COALESCE(\"Mean number of attached subscribers(UMTS)\",0)"
            "+COALESCE(\"Mean Number of EPS Attach subscribers\",0)),0)",
            "Data Subscribers"),
    },
    {
        "id": "4g_traffic",
        "title": "4G FDD Traffic(GB)",
        "table": "5mins_4G_FDD_DATA_TRAFFIC_TEMPLATE_OSS_UME",
        # 字节 → GB：/1e9（与 CN KPI 看板的 GB 口径一致）
        "sql": _agg_sql(
            "5mins_4G_FDD_DATA_TRAFFIC_TEMPLATE_OSS_UME",
            'ROUND(SUM("Byte of downlink data packets received via SGi interface per APN(Byte)")/1000000000.0,3)',
            "4G FDD Traffic(GB)"),
    },
    {
        "id": "rg30",
        "title": "RG-30 (GB)",
        "table": "5mins_FREE_RATING_GROUP_TEMPLATE_OSS_update_UME",
        "sql": _agg_sql(
            "5mins_FREE_RATING_GROUP_TEMPLATE_OSS_update_UME",
            'ROUND(SUM("Bytes of flows of downlink packets based RG(Byte)")/1000000000.0,3)',
            "RG-30(GB)", extra_where="\"Measurement Object\" = '30'"),
    },
    {
        "id": "rg12",
        "title": "RG-12 (GB)",
        "table": "5mins_FREE_RATING_GROUP_TEMPLATE_OSS_update_UME",
        "sql": _agg_sql(
            "5mins_FREE_RATING_GROUP_TEMPLATE_OSS_update_UME",
            'ROUND(SUM("Bytes of flows of downlink packets based RG(Byte)")/1000000000.0,3)',
            "RG-12(GB)", extra_where="\"Measurement Object\" = '12'"),
    },
    {
        "id": "rg11",
        "title": "RG-11 (GB)",
        "table": "5mins_FREE_RATING_GROUP_TEMPLATE_OSS_update_UME",
        "sql": _agg_sql(
            "5mins_FREE_RATING_GROUP_TEMPLATE_OSS_update_UME",
            'ROUND(SUM("Bytes of flows of downlink packets based RG(Byte)")/1000000000.0,3)',
            "RG-11(GB)", extra_where="\"Measurement Object\" = '11'"),
    },
    {
        "id": "rg6",
        "title": "RG-6 (GB)",
        "table": "5mins_FREE_RATING_GROUP_TEMPLATE_OSS_update_UME",
        "sql": _agg_sql(
            "5mins_FREE_RATING_GROUP_TEMPLATE_OSS_update_UME",
            'ROUND(SUM("Bytes of flows of downlink packets based RG(Byte)")/1000000000.0,3)',
            "RG-6(GB)", extra_where="\"Measurement Object\" = '6'"),
    },
    # ------------------------------------------------------------------
    # 以下 3 个在 2026-10-19 前是空态卡（原模板无 5 分钟档）。上游同一天补建了
    # 15 分钟档模板，采集侧已切到新模板（`FIFTEEN_MIN_TEMPLATES`），这里改为正常取数。
    # ⚠ 它们的粒度是 15 分钟而非 5 分钟，行数约为其他组件的 1/3，属正常。
    # ------------------------------------------------------------------
    {
        "id": "xgw_license",
        "title": "xGW License Occupancy(%)",
        "table": "5mins_xGW_LICENSE_OCCUPANCY_TEMPLATE_OSS_UME",
        # 与 CN KPI 看板口径一致：取 Throughput Usage(%) 作为 License 占用率
        "sql": _agg_sql(
            "5mins_xGW_LICENSE_OCCUPANCY_TEMPLATE_OSS_UME",
            'ROUND(AVG("Throughput Usage(%)"),2)', "License Occupancy(%)"),
        "pct": True,
    },
    {
        "id": "xgw_cpu",
        "title": "xGW CPU Usage(%)",
        "table": "5mins_xGW_CPU_USAGE_TEMPLATE_OSS_UME_UME",
        # 与 CN KPI 看板一致：峰值 vCPU 使用率
        "sql": _agg_sql(
            "5mins_xGW_CPU_USAGE_TEMPLATE_OSS_UME_UME",
            'ROUND(AVG("Peak usage ratio of UP\'s vCPU(%)"),2)', "xGW CPU Usage(%)"),
        "pct": True,
    },
    {
        "id": "3g_traffic",
        "title": "3G FDD Traffic(GB)",
        "table": "5mins_3G_FDD_DATA_TRAFFIC_TEMPLATE_OSS_UME",
        # 字节 → GB
        # ⚠ 列名是 "Bytes"（复数）。3G 与 4G 的列名**不同**：4G 是 "Byte of ... SGi"（单数），
        # 3G 是 "Bytes of ... Gi"（复数）。写成单数时 SQLite 不报错，而是把双引号标识符
        # 当字符串字面量，SUM 恒等于 0 —— 2026-10-19 实测踩过（页面 3G 全 0）。
        "sql": _agg_sql(
            "5mins_3G_FDD_DATA_TRAFFIC_TEMPLATE_OSS_UME",
            'ROUND(SUM("Bytes of downlink data packets received via Gi interface per APN(Byte)")/1000000000.0,3)',
            "3G FDD Traffic(GB)"),
    },
]


# ----------------------------------------------------------------------
# 列名守卫（2026-10-19 新增）
# ----------------------------------------------------------------------
# 为什么需要：SQLite 对双引号包起来的**不存在的列名**不报错，而是把它当字符串
# 字面量。于是 `SUM("Byte of ...")`（真实列名是 "Bytes of ..."）会恒等于 0，
# 页面显示一条贴地的 0 曲线，**没有任何报错**。3G FDD 就是这么翻车的：
# 4G 的列名是 "Byte of ... SGi"（单数），3G 是 "Bytes of ... Gi"（复数），
# 抄的时候漏了一个 s。
#
# 本守卫在整页取数时顺带校验：每个 widget 的 SQL 里出现的双引号标识符，必须是
# 该表真实存在的列（或 SQL 里的别名）。不一致就在组件上标 error，而不是让用户
# 对着一张「看起来正常、其实全是 0」的图猜。
_QUOTED_IDENT_RE = re.compile(r'"([^"]+)"')


def _known_columns(table: str) -> Optional[set]:
    """取远端表的真实列名；取不到返回 None（守卫静默跳过，不影响正常出图）。"""
    try:
        res = query_remote(f'SELECT * FROM "{table}" LIMIT 0', db=REMOTE_DB, limit=1)
    except Exception:  # noqa: BLE001 — 表不存在/服务不可达都不该拖垮整页
        return None
    if not res.get("success", True):
        return None
    return set(res.get("columns") or [])


def _verify_columns(w: Dict[str, Any]) -> str:
    """返回错误说明；空串表示列名都对得上。

    只校验「会出现在 SELECT 列表中、且属于源表」的标识符：表名本身、SQL 别名
    （AS 后面的名字）、以及 day/t 这类输出列不在校验范围。
    """
    table = w.get("table") or ""
    sql = w.get("sql") or ""
    if not table or not sql:
        return ""
    cols = _known_columns(table)
    if cols is None:
        return ""
    # SQL 里出现的别名（AS "xxx"）不是源表列，排除掉
    aliases = set(re.findall(r'\bAS\s+"([^"]+)"', sql, flags=re.IGNORECASE))
    missing = [
        name for name in _QUOTED_IDENT_RE.findall(sql)
        if name != table and name not in aliases and name not in cols
    ]
    if missing:
        return (f'列名不存在于表 {table}：{missing}。'
                f'SQLite 会把未知双引号标识符当字符串字面量，导致结果恒为 0（不会报错）。'
                f'现有列：{sorted(cols)}')
    return ""


def _fetch_widget(w: Dict[str, Any]) -> Dict[str, Any]:
    """取单个组件；空表/无数据都算「空态」，不算失败。"""
    out: Dict[str, Any] = {
        "id": w["id"],
        "title": w["title"],
        "chart": "line",
        "pivot": True,      # 三列 [HH:MM, Day0/Day1, 值]
        "pct": bool(w.get("pct")),   # 百分比组件（纵轴格式化为 %）
        "sql": w["sql"],
        "columns": ["Time", "Day", w["title"]],
        "rows": [],
        "error": "",
        "empty": False,
        "empty_reason": "",
    }
    # 已知上游无 5 分钟数据：直接给业务原因，不去远端打一次注定失败的表
    reason = UNAVAILABLE_TABLES.get(w["table"])
    if reason:
        out["empty"] = True
        out["empty_reason"] = reason
        return out
    if not w.get("sql"):
        # 兜底：没有 SQL 的组件（理论上都已被 UNAVAILABLE_TABLES 覆盖）
        out["empty"] = True
        out["empty_reason"] = "该组件暂无可用查询。"
        return out

    # 列名守卫：先确认 SQL 引用的标识符都是真实列，避免「不报错但恒为 0」
    col_err = _verify_columns(w)
    if col_err:
        out["error"] = col_err
        logger.error("CN KPI 5mins 组件 %s 列名校验失败：%s", w["id"], col_err)
        return out

    try:
        res = query_remote(w["sql"], db=REMOTE_DB, limit=5000)
    except Exception as e:  # noqa: BLE001 — 表不存在也算空态
        msg = str(e)
        if "no such table" in msg.lower():
            out["empty"] = True
            out["empty_reason"] = "该 5 分钟数据表尚未生成（任务未跑过或上游无此粒度数据）。"
        else:
            out["error"] = msg
        logger.warning("CN KPI 5mins 组件 %s 取数失败：%s", w["id"], msg)
        return out

    if not res.get("success", True):
        out["error"] = res.get("error") or "远端返回 success=false"
        return out

    out["columns"] = list(res.get("columns") or out["columns"])
    out["rows"] = [list(r) for r in (res.get("rows") or [])]
    if not out["rows"]:
        out["empty"] = True
        out["empty_reason"] = "当前窗口（今天 + 昨天）内暂无 5 分钟数据。"
    return out


# ----------------------------------------------------------------------
# 缓存
# ----------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {}


def get_overview(force: bool = False) -> Dict[str, Any]:
    """整页数据：8 个组件并发取数 + TTL 缓存。"""
    now = time.time()
    if not force:
        with _cache_lock:
            hit = _cache.get("all")
            if hit is not None and (now - hit["at"]) < CACHE_TTL:
                data = hit["data"]
                data["meta"] = {**data["meta"], "cached": True}
                return data

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        widgets = list(pool.map(_fetch_widget, WIDGETS))

    failed = sum(1 for w in widgets if w["error"])
    empty = sum(1 for w in widgets if w["empty"])
    data = {
        "meta": {
            "db": REMOTE_DB,
            "count": len(widgets),
            "failed": failed,
            "empty": empty,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
            "cached": False,
        },
        "title": "CCN_KPI_5mins",
        "widgets": widgets,
    }
    with _cache_lock:
        _cache["all"] = {"at": time.time(), "data": data}
    return data


def health() -> Dict[str, Any]:
    """远端连通性探测。"""
    try:
        res = query_remote("SELECT 1 AS ok", limit=1)
        return {"ok": True, "db": REMOTE_DB, "elapsed_ms": res.get("elapsed_ms")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "db": REMOTE_DB, "error": str(e)}

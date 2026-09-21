# -*- coding: utf-8 -*-
"""CN KPI 看板数据服务（原 my-finebi「CN KPI」看板原生重建）。

=========================== 数据源与统计口径 ===========================

数据源
    远端只读 SQL API（backend/config/remote_host.py → 默认 http://192.168.100.19:8765）
    逻辑库 db_ps_cs_cn.sqlite3（FineBI 连接名 db_ps_cs_cn，PS/CS CN KPI）

    **不再依赖 my-finebi 进程**：my-finebi 门户/后端停掉不影响本页；
    只要求远端 8765 只读 API 可达（.19 开机且 db_writer_api 在跑）。

来源与口径
    18 个组件的 SQL 与图表类型，逐条解析自 FineBI 原看板（公开链接 iYiQ）的
    数据集定义，与原版 1:1 对齐（见 my-finebi 的 backend/seed_cnkpi.json）。
    - 折线类：GROUP BY substr("End Time",1,10)，默认近 31 天
    - pivot 类：SQL 返回 [时间, NE, 值] 三列，前端按 NE 透视成多序列
    - 单位换算与原版一致（Byte→GB 除以 1000/1000，与 FineBI 相同）

只读保障
    远端 /api/query 在连接层强制 PRAGMA query_only=ON；本服务只发 SELECT。
    本地再做一次语句形状守卫（必须 SELECT/WITH 开头、禁止分号），双保险。

时间范围
    默认近 31 天（与原版 FineBI 一致）。页面可传 start / end（YYYY-MM-DD）
    自定义区间 —— 由 _apply_range() 把 SQL 里的 {{LO}} / {{HI}} 占位符替换为
    **经过严格正则校验的字面量**（只允许 YYYY-MM-DD），绝不拼接任意用户输入。

缓存
    整页 18 个组件并发取数，结果按「时间区间」维度 TTL（默认 60s）缓存，
    避免每次刷新都打 18 次远端；单组件失败只标记该组件，不拖垮整页。
======================================================================
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from backend.config.remote_host import get_api_base_url

logger = logging.getLogger("cn_kpi")

# 远端逻辑库名（FineBI 连接名 db_ps_cs_cn → 远端 E:\01_RPA\LBR_Tools\KPI\db_ps_cs_cn.sqlite3）
REMOTE_DB = "db_ps_cs_cn.sqlite3"

# 取数超时（秒）：单组件远端查询；整页并发受此上限约束
QUERY_TIMEOUT = 60

# 整页结果 TTL（秒）——看板数据是日粒度，60s 足够新
CACHE_TTL = 60

# 并发上限：远端 db_writer_api 是单机服务，避免一次性打太多连接
MAX_WORKERS = 6

# 显式禁用代理：内网地址绝不能被 HTTP_PROXY 劫持（沿用 query_engine 的做法）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 只读语句守卫（本地一道，远端另有一道）
_GUARD_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


# ----------------------------------------------------------------------
# 组件清单：SQL 与展示元数据，逐条对齐 FineBI 原看板（公开链接 iYiQ）
# ----------------------------------------------------------------------
# title   : 组件标题（与原版一致）
# chart   : line / kpi / text
# pivot   : True 表示 SQL 返回三列 [时间, 系列名, 值]，需按第 2 列透视
# pct     : True 表示纵轴为百分比（两位小数）
#
# SQL 里的 {{LO}} / {{HI}} 是时间区间占位符（默认近 31 天），
# 由 _apply_range() 依据请求参数替换；无占位符的 SQL 不受区间影响。
#
# 顺序与 seed_cnkpi.json 的 widgets 顺序保持一致，便于日后比对。
WIDGETS: List[Dict[str, Any]] = [
    {
        "id": "kpi_time",
        "title": "TIme",
        "chart": "kpi",
        "sql": (
            'SELECT MAX(substr("End Time",1,10)) AS "Date" '
            'FROM "VLR_SUBSCRIBERS_TEMPLATE_OSS_EMS"'
        ),
    },
    {
        "id": "c1",
        "title": "VLR Subscribers",
        "chart": "line",
        "sql": (
            'SELECT substr("End Time",1,10) AS t, '
            'SUM("Number of Subscribers in VLR") AS "VLR Subscribers" FROM (\n'
            'SELECT "End Time", "Number of Subscribers in VLR" '
            'FROM "VLR_SUBSCRIBERS_TEMPLATE_OSS_EMS" '
            'UNION ALL SELECT "End Time", "Number of Subscribers in VLR" '
            'FROM "VLR_SUBSCRIBERS_TEMPLATE_OSS_UME"\n'
            ")  GROUP BY substr(\"End Time\",1,10) "
            "HAVING t >= {{LO}} AND t < {{HI}} ORDER BY t"
        ),
    },
    {
        "id": "c4",
        "title": "Voice Traffic(Erl)",
        "chart": "line",
        "sql": (
            'SELECT substr("End Time",1,10) AS t, '
            'SUM(v) AS "Voice Traffic(Erl)" FROM (\n'
            'SELECT "End Time", "Seized Traffic(Erl)" AS v '
            'FROM "VOICE_TRAFFIC_TEMPLATE_OSS_UME" '
            'UNION ALL SELECT "End Time", "Seized Traffic(Erl)" AS v '
            'FROM "VOICE_TRAFFIC_TEMPLATE_OSS_EMS"\n'
            ")  GROUP BY substr(\"End Time\",1,10) "
            "HAVING t >= {{LO}} AND t < {{HI}} ORDER BY t"
        ),
    },
    {
        "id": "c12",
        "title": "USSD SUCCESS RATIO",
        "chart": "line",
        "pct": True,
        "sql": (
            'SELECT substr("End Time",1,10) AS t, '
            'ROUND(AVG(v),2) AS "USSD SUCCESS RATIO" FROM (\n'
            'SELECT "End Time", "USSD SUCCESS RATIO" AS v '
            'FROM "USSD_RATIO_TEMPLATE_OSS_EMS"\n'
            ")  GROUP BY substr(\"End Time\",1,10) "
            "HAVING t >= {{LO}} AND t < {{HI}} ORDER BY t"
        ),
    },
    {
        "id": "c13",
        "title": "Successful ratio of location update(%)",
        "chart": "line",
        "pct": True,
        "sql": (
            'SELECT substr("End Time",1,10) AS t, '
            'ROUND(AVG(v),2) AS "Location Update(%)" FROM (\n'
            'SELECT "End Time", "Successful ratio of location update(%)" AS v '
            'FROM "LOCATION_UPDATE_TEMPLATE_OSS_EMS"\n'
            ")  GROUP BY substr(\"End Time\",1,10) "
            "HAVING t >= {{LO}} AND t < {{HI}} ORDER BY t"
        ),
    },
    {
        "id": "c3",
        "title": "Data Subscribers",
        "chart": "line",
        "sql": (
            'SELECT substr("End Time",1,10) AS t, SUM(gsm) AS "GSM", '
            'SUM(umts) AS "UMTS", SUM(eps) AS "EPS", '
            'SUM(gsm+umts+eps) AS "Total" FROM (\n'
            'SELECT "End Time", "Mean number of attached subscribers(GSM)" AS gsm, '
            '"Mean number of attached subscribers(UMTS)" AS umts, '
            '"Mean Number of EPS Attach subscribers" AS eps '
            'FROM "DATA_SUBSCRIBERS_TEMPLATE_OSS_UME"\n'
            ")  GROUP BY substr(\"End Time\",1,10) "
            "HAVING t >= {{LO}} AND t < {{HI}} ORDER BY t"
        ),
    },
    {
        "id": "c5",
        "title": "FDD Traffic(GB)",
        "chart": "line",
        "sql": (
            'SELECT substr("End Time",1,10) AS t, '
            'ROUND(SUM(b)/1000.0/1000.0, 2) AS "FDD Traffic(GB)" FROM (\n'
            'SELECT "End Time", "Byte of downlink data packets received via SGI '
            'interface per APN(Byte)" AS b FROM "4G_FDD_DATA_TRAFFIC_TEMPLATE_OSS_UME"\n'
            ")  GROUP BY substr(\"End Time\",1,10) "
            "HAVING t >= {{LO}} AND t < {{HI}} ORDER BY t"
        ),
    },
    {
        "id": "c6",
        "title": "TDD Traffic(GB)",
        "chart": "line",
        "sql": (
            'SELECT substr("End Time",1,10) AS t, '
            'ROUND(SUM(b)/1000.0/1000.0, 2) AS "TDD Traffic(GB)" FROM (\n'
            'SELECT "End Time", "Byte of downlink data packets received via SGI '
            'interface per APN(Byte)" AS b FROM "TDD_DATA_TRAFFIC_TEMPLATE_OSS_EMS"\n'
            ")  GROUP BY substr(\"End Time\",1,10) "
            "HAVING t >= {{LO}} AND t < {{HI}} ORDER BY t"
        ),
    },
    {
        "id": "rg30",
        "title": "RG-30",
        "chart": "line",
        "sql": (
            'SELECT substr("Begin Time",1,10) AS t, '
            'ROUND(SUM(b)/1000.0/1000.0, 2) AS "RG-30(GB)" FROM (\n'
            'SELECT "Begin Time", "Bytes of flows of downlink packets based RG(Byte)" '
            'AS b, "Measurement Object" AS mo '
            'FROM "FREE_RATING_GROUP_TEMPLATE_OSS_update_UME"\n'
            ") WHERE mo = '30' GROUP BY substr(\"Begin Time\",1,10) "
            "HAVING t >= {{LO}} AND t < {{HI}} ORDER BY t"
        ),
    },
    {
        "id": "rg12",
        "title": "RG-12",
        "chart": "line",
        "sql": (
            'SELECT substr("Begin Time",1,10) AS t, '
            'ROUND(SUM(b)/1000.0/1000.0, 2) AS "RG-12(GB)" FROM (\n'
            'SELECT "Begin Time", "Bytes of flows of downlink packets based RG(Byte)" '
            'AS b, "Measurement Object" AS mo '
            'FROM "FREE_RATING_GROUP_TEMPLATE_OSS_update_UME"\n'
            ") WHERE mo = '12' GROUP BY substr(\"Begin Time\",1,10) "
            "HAVING t >= {{LO}} AND t < {{HI}} ORDER BY t"
        ),
    },
    {
        "id": "rg11",
        "title": "RG-11",
        "chart": "line",
        "sql": (
            'SELECT substr("Begin Time",1,10) AS t, '
            'ROUND(SUM(b)/1000.0/1000.0, 2) AS "RG-11(GB)" FROM (\n'
            'SELECT "Begin Time", "Bytes of flows of downlink packets based RG(Byte)" '
            'AS b, "Measurement Object" AS mo '
            'FROM "FREE_RATING_GROUP_TEMPLATE_OSS_update_UME"\n'
            ") WHERE mo = '11' GROUP BY substr(\"Begin Time\",1,10) "
            "HAVING t >= {{LO}} AND t < {{HI}} ORDER BY t"
        ),
    },
    {
        "id": "rg6",
        "title": "RG-6",
        "chart": "line",
        "sql": (
            'SELECT substr("Begin Time",1,10) AS t, '
            'ROUND(SUM(b)/1000.0/1000.0, 2) AS "RG-6(GB)" FROM (\n'
            'SELECT "Begin Time", "Bytes of flows of downlink packets based RG(Byte)" '
            'AS b, "Measurement Object" AS mo '
            'FROM "FREE_RATING_GROUP_TEMPLATE_OSS_update_UME"\n'
            ") WHERE mo = '6' GROUP BY substr(\"Begin Time\",1,10) "
            "HAVING t >= {{LO}} AND t < {{HI}} ORDER BY t"
        ),
    },
    {
        "id": "c11",
        "title": "USPP Utilization(%)",
        "chart": "line",
        "pct": True,
        "sql": (
            'SELECT substr("End Time",1,10) AS t, '
            'ROUND(MAX(v),2) AS "License Occupancy(%)" FROM (\n'
            'SELECT "End Time", "License Occupancy Rates(%)" AS v '
            'FROM "LICENSE_OCCUPANCY_TEMPLATE_OSS_EMS"\n'
            ")  GROUP BY substr(\"End Time\",1,10) "
            "HAVING t >= {{LO}} AND t < {{HI}} ORDER BY t"
        ),
    },
    {
        "id": "c2",
        "title": "MSC Utilization(%)",
        "chart": "line",
        "pct": True,
        "sql": (
            'SELECT substr(e."End Time",1,10) AS t, '
            'ROUND(MAX(e."Number of Subscribers in VLR")/3000000.0*100, 2) AS "EMS", '
            'ROUND(MAX(u."Number of Subscribers in VLR")/4000000.0*100, 2) AS "UME" '
            'FROM "VLR_SUBSCRIBERS_TEMPLATE_OSS_EMS" e '
            'LEFT JOIN "VLR_SUBSCRIBERS_TEMPLATE_OSS_UME" u '
            'ON substr(u."End Time",1,10) = substr(e."End Time",1,10) '
            'GROUP BY substr(e."End Time",1,10) '
            "HAVING t >= {{LO}} AND t < {{HI}} ORDER BY t"
        ),
    },
    {
        "id": "c7",
        "title": "Data Throughput(Mbps)",
        "chart": "line",
        "pivot": True,
        "sql": (
            'SELECT substr("End Time",1,13) || \':00\' AS t, NE, '
            '"Number of Throughput(Mbps) Used" AS v '
            'FROM "xGW_LICENSE_OCCUPANCY_TEMPLATE_OSS_UME" '
            'WHERE "End Time" >= {{LO}} AND "End Time" < {{HI}} ORDER BY t'
        ),
    },
    {
        "id": "c8",
        "title": "xGW Throughput Utilization(%)",
        "chart": "line",
        "pivot": True,
        "pct": True,
        "sql": (
            'SELECT substr("End Time",1,13) || \':00\' AS t, NE, '
            '"Throughput Usage(%)" AS v '
            'FROM "xGW_LICENSE_OCCUPANCY_TEMPLATE_OSS_UME" '
            'WHERE "End Time" >= {{LO}} AND "End Time" < {{HI}} ORDER BY t'
        ),
    },
    {
        "id": "c10",
        "title": "xGW Session Utilization(%)",
        "chart": "line",
        "pivot": True,
        "pct": True,
        "sql": (
            'SELECT substr("End Time",1,13) || \':00\' AS t, NE, '
            '"PFCP Sessions Usage(%)" AS v '
            'FROM "xGW_LICENSE_OCCUPANCY_TEMPLATE_OSS_UME" '
            'WHERE "End Time" >= {{LO}} AND "End Time" < {{HI}} ORDER BY t'
        ),
    },
    {
        "id": "c9",
        "title": "xGW CPU Utilization(%)",
        "chart": "line",
        "pivot": True,
        "pct": True,
        "sql": (
            'SELECT substr("End Time",1,10) AS t, NE, '
            '"Peak usage ratio of UP\'s vCPU(%)" AS v '
            'FROM "xGW_CPU_USAGE_TEMPLATE_OSS_UME_UME" '
            'WHERE "End Time" >= {{LO}} AND "End Time" < {{HI}} ORDER BY t'
        ),
    },
]

# 标题栏（原版 text 组件的 HTML）。
# 注意：原版含指向 FineBI（http://192.168.100.19/webroot/decision/link/iYiQ）的外链，
# 本页已不依赖 FineBI，故去掉超链接，仅保留标题文本与样式。
TITLE_HTML = (
    '<div style="width:100%;display:flex;flex-direction:column">'
    '<div><p style="text-align:center;margin:0">'
    '<span style="font-size:30px;color:#ffffff">❯❯❯ '
    "CCN_Daily_KPI"
    ' ❮❮❮</span></p></div></div>'
)


# ----------------------------------------------------------------------
# 只读守卫与远端查询
# ----------------------------------------------------------------------
def _guard(sql: str) -> str:
    """本地只读守卫：必须 SELECT/WITH 开头、禁止分号（单语句）。"""
    s = (sql or "").strip()
    if not s:
        raise ValueError("SQL 不能为空")
    if ";" in s:
        raise ValueError("仅允许单条语句（不允许分号多语句）")
    if not _GUARD_RE.match(s):
        raise ValueError("仅允许 SELECT / WITH 只读查询")
    return s


# 日期字面量严格校验：只接受 YYYY-MM-DD，杜绝任何注入可能
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# SQL 里的时间区间占位符（原 SQL 的 date('now','-31 day') / datetime('now','-31 day')
# 已全部改为这两个占位符，由 _apply_range() 按请求区间替换）
_LO_TOKEN = "{{LO}}"
_HI_TOKEN = "{{HI}}"

# 默认区间：近 31 天（与原版 FineBI 口径一致）
_DEFAULT_LO = "date('now','-31 day')"
_DEFAULT_HI = "date('now','+1 day')"


def _validate_date(v: Optional[str], field: str) -> Optional[str]:
    """校验 YYYY-MM-DD；空值返回 None。非法即抛错（不静默忽略）。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if not _DATE_RE.match(s):
        raise ValueError(f"{field} 格式必须是 YYYY-MM-DD，收到：{v!r}")
    return s


def _apply_range(sql: str, start: Optional[str], end: Optional[str]) -> str:
    """把 SQL 里的 {{LO}} / {{HI}} 占位符替换为已校验的日期字面量。

    - 无占位符的 SQL（如 KPI 单值）原样返回，不受区间影响。
    - start/end 均为 None 时回退默认近 31 天（与原版 FineBI 一致）。
    - 替换值经 _validate_date 严格校验（仅 YYYY-MM-DD），不含引号/分号，
      故不存在注入面；时间列形如 'YYYY-MM-DDTHH:MM:SS' 文本，
      按 substr(...,1,10) 生成的 'YYYY-MM-DD' 做字典序比较即为日期比较。
    """
    if _LO_TOKEN not in sql and _HI_TOKEN not in sql:
        return sql
    lo = _validate_date(start, "start")
    hi = _validate_date(end, "end")
    lo_sql = f"'{lo}'" if lo else _DEFAULT_LO
    hi_sql = f"'{hi}'" if hi else _DEFAULT_HI
    return sql.replace(_LO_TOKEN, lo_sql).replace(_HI_TOKEN, hi_sql)


def query_remote(sql: str, db: str = REMOTE_DB, limit: int = 5000) -> Dict[str, Any]:
    """调用远端只读 SQL API 执行一条 SELECT。

    返回远端原始结构：{success, columns, rows, count, truncated, elapsed_ms}
    """
    sql = _guard(sql)
    url = f"{get_api_base_url()}/api/query"
    payload = json.dumps({"db": db, "sql": sql, "limit": limit},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _OPENER.open(req, timeout=QUERY_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise RuntimeError(f"远端数据源返回 HTTP {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"无法连接远端数据源 {url}：{getattr(e, 'reason', e)}"
        ) from e


def _fetch_widget(w: Dict[str, Any], start: Optional[str] = None,
                  end: Optional[str] = None) -> Dict[str, Any]:
    """取单个组件的数据；失败只标记该组件，不影响整页。"""
    out: Dict[str, Any] = {
        "id": w["id"],
        "title": w["title"],
        "chart": w["chart"],
        "pivot": bool(w.get("pivot")),
        "pct": bool(w.get("pct")),
        "sql": "",
        "columns": [],
        "rows": [],
        "error": "",
    }
    if w["chart"] == "text":
        return out
    try:
        sql = _apply_range(w["sql"], start, end)
        out["sql"] = sql
        res = query_remote(sql)
        if not res.get("success", True):
            raise RuntimeError(res.get("error") or "远端返回 success=false")
        out["columns"] = list(res.get("columns") or [])
        out["rows"] = [list(r) for r in (res.get("rows") or [])]
    except Exception as e:  # noqa: BLE001 — 单组件失败不应中断整页
        logger.warning("CN KPI 组件 %s(%s) 取数失败: %s", w["id"], w["title"], e)
        out["error"] = str(e)
    return out


# ----------------------------------------------------------------------
# 缓存（按时间区间分行）
# ----------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {}


def get_overview(
    force: bool = False,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict[str, Any]:
    """整页数据：18 个组件并发取数 + TTL 缓存（按时间区间分行）。

    start / end：YYYY-MM-DD；留空表示近 31 天（与原版 FineBI 一致）。
    返回 {meta:{db,host,count,failed,elapsed_ms,cached,start,end},
          title, title_html, widgets:[...]}
    """
    # 先校验区间（非法直接抛错 → 路由转 400，不进入取数）
    start_v = _validate_date(start, "start")
    end_v = _validate_date(end, "end")
    if start_v and end_v and start_v > end_v:
        raise ValueError(f"开始日期不能晚于结束日期：{start_v} > {end_v}")

    key = f"{start_v or ''}~{end_v or ''}"
    now = time.time()
    if not force:
        with _cache_lock:
            hit = _cache.get(key)
            if hit is not None and (now - hit["at"]) < CACHE_TTL:
                data = hit["data"]
                data["meta"] = {**data["meta"], "cached": True}
                return data

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        widgets = list(pool.map(lambda w: _fetch_widget(w, start_v, end_v), WIDGETS))

    failed = sum(1 for w in widgets if w["error"])
    data = {
        "meta": {
            "db": REMOTE_DB,
            "host": get_api_base_url(),
            "count": len(widgets),
            "failed": failed,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
            "cached": False,
            "start": start_v,
            "end": end_v,
        },
        "title": "CCN_Daily_KPI",
        "title_html": TITLE_HTML,
        "widgets": widgets,
    }
    with _cache_lock:
        _cache[key] = {"at": time.time(), "data": data}
    return data


def health() -> Dict[str, Any]:
    """远端连通性探测（供页面诊断提示用）。"""
    try:
        res = query_remote("SELECT 1 AS ok", limit=1)
        return {"ok": True, "host": get_api_base_url(), "db": REMOTE_DB,
                "elapsed_ms": res.get("elapsed_ms")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "host": get_api_base_url(), "db": REMOTE_DB, "error": str(e)}

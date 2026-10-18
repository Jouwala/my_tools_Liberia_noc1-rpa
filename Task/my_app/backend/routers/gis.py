"""GIS地理信息 API - Voronoi分区版

P2#8 重构（2026-08-03）：
- 几何计算（Voronoi/边界裁剪/平滑）下沉至 gis_geometry.py；
- 4 个高圈复杂度函数（get_sites/get_realtime_sites/get_region_boundaries 等）
  拆分为单一职责的 SQL 构建 / 统计采集 / 行组装助手函数。
"""
import logging
import re
import threading
import time as _time
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Query, HTTPException
from backend.database import get_raw_connection, DB_PATH, DB_MODE
from backend.dialect_helpers import list_table_names, table_columns
from backend.routers.gis_geometry import compute_region_boundaries, load_county_boundaries

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gis", tags=["gis"])

# ========== 自适应GIS数据库结构检测 ==========
# 结构探测带 TTL（2026-09-29 修复）：原实现是进程级永久缓存，
# 一旦在表存在时建立，之后 has_realtime_alarm 恒为 True —— 即使该表被
# 定时任务整表重建（eflow_active_alarm 每 30 分钟一次）短暂消失，
# 缓存也不会更新，兜底判断失效。加 TTL 后结构变化最多在 _SCHEMA_TTL 秒内可见。
_gis_schema_cache = None
_gis_schema_cache_ts = 0.0
_SCHEMA_TTL = 300  # 秒；与同文件 _META_TTL 同量级，避免每次请求都探测


def _detect_gis_schema(force: bool = False) -> dict:
    """检测数据库结构，兼容 my_app 和 MTN_Comsal（带 TTL 缓存）。

    force=True 时跳过缓存强制重新探测（供需要最新结构的调用方使用）。
    """
    global _gis_schema_cache, _gis_schema_cache_ts
    now = _time.time()
    if (not force) and _gis_schema_cache and (now - _gis_schema_cache_ts) < _SCHEMA_TTL:
        return _gis_schema_cache

    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))

        # 站点表
        site_table = "master_site_db" if "master_site_db" in tables else "site_db" if "site_db" in tables else None

        site_cols = set()
        if site_table:
            site_cols = set(table_columns(conn, site_table))

        # 字段映射
        province_col = "province_county" if "province_county" in site_cols else "province" if "province" in site_cols else None
        vip_col = "vip_site" if "vip_site" in site_cols else "vipsite" if "vipsite" in site_cols else None
        hub_col = "hub_site" if "hub_site" in site_cols else "hubsite" if "hubsite" in site_cols else None

        # TT表关联字段
        tt_cols = set()
        if "eflow_tt" in tables:
            tt_cols = set(table_columns(conn, "eflow_tt"))
        tt_site_key = "site_id" if "site_id" in tt_cols else "site_name" if "site_name" in tt_cols else None

        # WO表
        has_wo = "eflow_wo" in tables
        # topology表
        has_topology = "topology" in tables
        # 告警表
        has_realtime_alarm = "realtime_alarm" in tables
        has_history_alarm = "history_alarm" in tables

        conn.close()

        _gis_schema_cache = {
            "site_table": site_table, "site_cols": site_cols,
            "province_col": province_col, "vip_col": vip_col, "hub_col": hub_col,
            "tt_site_key": tt_site_key, "has_wo": has_wo, "has_topology": has_topology,
            "tt_cols": tt_cols,
            "has_realtime_alarm": has_realtime_alarm, "has_history_alarm": has_history_alarm,
        }
        _gis_schema_cache_ts = now
        return _gis_schema_cache


# GIS 筛选列配置：(param_name, db_column, label)
_GIS_FILTER_COLS = [
    ("trm_type", "trm_type", "TRM Type"),
    ("site_type", "site_type", "Site Type"),
    ("hubsite", "hub_site", "Hub Site"),
    ("vip_site", "vip_site", "VIP Site"),
    # 现场维护与区域职责
    ("supervisor", "supervisor", "Supervisor"),
    # 注意：GIS 站点表(master_site_db)的 FME 列名是 fme_name（人名，如 "Mark D. Paye"）。
    # 早前误用了 updated_fme_name_new —— 那是 eFlow 侧(eflow_site)的维护班组编码
    # （如 "FE_FE_112;FE_FE_115"），在站点表里并不存在，导致该筛选项恒为空。
    ("fme_name", "fme_name", "FME Name"),
    ("province_county", "province_county", "Province/County"),
    ("network_type", "network_type", "Network Type"),
    ("power_sources", "power_sources", "Power Sources"),
    ("site_caregory", "site_caregory", "Site Category"),
    # 说明：原配置里的 "area" 与 "site_information" 两列在 master_site_db 中并不存在，
    # 属于历史遗留的失效配置（前端因此永远渲染不出这两个下拉框），已移除。
    # 若后续站点表补上这两列，按 (参数名, 列名, 标签) 三元组加回即可，无需改动其它逻辑。
]

# 下钻 TT 列表候选列（按存在性动态选择）
_TT_DETAIL_COLS = [
    "title", "ticket_no", "wo_no", "site_id", "site_name", "site_class",
    "status", "creator", "owner", "ticket_severity", "sla_time", "sla_status",
    "region_id", "region_level1", "created_time", "alarm_occur_time",
    "alarm_clear_time", "root_cause", "sub_root_cause",
    "root_cause_description", "sla_remain_time", "fo_process_detail", "domain",
]

# WO 列表固定列
_WO_SELECT_COLS = (
    "wo_no, tt_no, title, status, creator, created_time, "
    "alarm_occur_time, alarm_clear_time, source, "
    "rc_main_category, rc_sub_category, ticket_severity"
)


def _parse_ts_ms(v):
    """将 servertime / alarmraisedtime 等字段统一解析为毫秒时间戳；无法解析返回 None"""
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            x = float(v)
        else:
            s = str(v).strip()
            if s == "" or s.lower() == "none":
                return None
            x = float(s)
        if x <= 0:
            return None
        # 秒级(<1e11) 与 毫秒级 兼容
        if x < 1e11:
            x = x * 1000
        return x
    except (ValueError, TypeError):
        logger.warning("[SILENT-EXCEPT] _parse_ts_ms: exception swallowed", exc_info=True)
        return None


def _parse_delay_sec(v):
    """将 assign_delay ('900s' / '14400s' / 纯秒数) 解析为秒；无法解析返回 None"""
    if v is None:
        return None
    s = str(v).strip().lower()
    if s == "" or s == "none":
        return None
    if s.endswith("s"):
        s = s[:-1]
    try:
        val = float(s)
    except ValueError:
        logger.warning("[SILENT-EXCEPT] _parse_delay_sec: exception swallowed", exc_info=True)
        return None
    return val if val >= 0 else None


# ========== 性能优化：静态元数据缓存 + 索引自愈 ==========
_meta_cache: dict = {}       # {"ts": epoch, "regions": [...], "filter_options": {...}}
_META_TTL = 300              # 秒；region / 筛选下拉项属于近似静态数据
_indexes_ensured = False


def _ensure_perf_indexes(conn):
    """确保关联查询所需索引存在（eflow_tt.tt_no 缺失会导致全表扫描）"""
    global _indexes_ensured
    if _indexes_ensured:
        return
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_eflow_tt_tt_no ON eflow_tt(tt_no)")
        conn.commit()
    except Exception:
        logger.warning("[SILENT-EXCEPT] _ensure_perf_indexes: exception swallowed", exc_info=True)
        pass
    _indexes_ensured = True


def _norm_site_category(value) -> str:
    """站点等级（site_caregory）归一化 → ERA / COOL / NORMAL / 其它原值。

    为什么要归一化：库里该列存在书写不一致的脏值 —— 实测 `master_site_db` 里
    `REGULAR（NORMAL)` / `REGULAR(COOL.I）` 这类带全角括号与制式后缀的写法
    与 `NORMAL` / `COOL` 混用。不归一化就会出现「NORMAL 与 REGULAR（NORMAL) 各算一档」，
    统计数字看着像少算，其实是同一档被劈成两半。

    ⚠️ 归一化口径必须与 `backend/services/eflow_rules/eflow_rules_matcher.py:135-152`
    的 `_SITE_TYPE_MAP` / `_norm_site_type` **保持一致**（去空格 + 去括号内制式后缀 + 大写）。
    那里是 TT 派单规则的站点类型真相源，两处口径不一致会导致「GIS 统计的 NORMAL 站数」
    与「TT 规则命中的 NORMAL 站数」对不上。改一处必须改另一处。
    """
    if value is None:
        return ""
    s = str(value).strip()
    if s == "":
        return ""
    # 去掉括号**内容**，但保留括号本身（如 "REGULAR(COOL.I)" → "REGULAR()"）。
    # ⚠️ 刻意不用 `\(.*?\)`：它要求左右括号同型配对，遇到库里实际存在的**混用**写法
    #    "REGULAR(COOL.I）"（半角左 + 全角右）会匹配失败或跨越边界误删 ——
    #    实测 `\(.*?[)）]` 把 "REGULAR(COOL.I）)" 吃成 "REGULAR)"，
    #    而 `[（(].*?[)）]` 又把 "REGULAR（COOL.I）" 整段吃掉导致后缀丢失。
    # 去掉内容后括号成对，下一步连括号一起去掉，兼容任意左右混用。
    s = re.sub(r"[（(][^（()）]*[)）]", "()", s)
    s = s.replace("(", "").replace(")", "").replace("（", "").replace("）", "")
    key = s.upper().replace(" ", "").replace("_", "")
    if key in ("REGULAR", "NORMAL"):
        return "NORMAL"
    if key == "COOL":
        return "COOL"
    if key == "ERA":
        return "ERA"
    return key


def _site_type_stats(conn, st, site_cols) -> list:
    """站点等级（ERA / COOL / NORMAL）站点数统计，供页面「Total Sites」旁显示。

    口径：**全量站点表**，不加任何 WHERE —— 与 `{t('gis.totalSites')}`（= `/gis/sites`
    的 `sites.length`，827）同源。刻意**不**复用 `/gis/sites` 的「经纬度非空且非 0」条件：
    两者若混用，三个分类之和与站点总数对不上，看起来就像统计算错了。
    实测 `master_site_db` 的 827 站经纬度全部有效，故当前两种口径结果相同。
    """
    col = "site_caregory" if "site_caregory" in site_cols else None
    if not col:
        return []
    counts: dict = {}
    for (raw,) in conn.execute(
        f"SELECT {col} FROM {st} WHERE {col} IS NOT NULL AND {col} != ''"
    ).fetchall():
        k = _norm_site_category(raw)
        if k:
            counts[k] = counts.get(k, 0) + 1
    # ERA / COOL / NORMAL 固定顺序在前（用户要求的三个口径），其余脏值按数量追加，
    # 保证「新出现一个没见过的等级」时页面能自动暴露出来，而不是被静默吞掉。
    order = ["ERA", "COOL", "NORMAL"]
    stats = [{"name": k, "count": counts[k]} for k in order if k in counts]
    stats += [
        {"name": k, "count": v}
        for k, v in sorted(counts.items(), key=lambda x: -x[1]) if k not in order
    ]
    return stats


def _get_site_meta(conn, st, site_cols):
    """获取 regions + filter_options + site_type_stats（带 TTL 缓存，避免每次请求跑 10 条 DISTINCT）"""
    now = _time.time()
    if _meta_cache and (now - _meta_cache.get("ts", 0)) < _META_TTL:
        return _meta_cache["regions"], _meta_cache["filter_options"], _meta_cache["site_type_stats"]
    regions = [r[0] for r in conn.execute(
        f"SELECT DISTINCT region FROM {st} WHERE region IS NOT NULL AND region != '' ORDER BY region"
    ).fetchall()]
    filter_options = {}
    for param_name, db_col, _ in _GIS_FILTER_COLS:
        if db_col in site_cols:
            vals = [r[0] for r in conn.execute(
                f"SELECT DISTINCT {db_col} FROM {st} WHERE {db_col} IS NOT NULL AND {db_col} != '' ORDER BY {db_col}"
            ).fetchall()]
            # ⚠️ site_caregory 必须**归一化**后再当候选值（2026-09-28）。
            # 前端高级筛选走的是**客户端精确匹配**（`site[key] !== val`，见 GISMap.tsx
            # 的 filteredSites），所以候选值必须与站点上那个值逐字符相等才能筛出来。
            # 库里该列已知有 `REGULAR（NORMAL)` / `REGULAR(COOL.I）` 这类脏写法
            # （全角括号 + 制式后缀），若不归一化，用户会看到一串看着像重复的选项，
            # 且选了 `NORMAL` 筛不到写作 `REGULAR（NORMAL)` 的站 —— 数字对不上。
            # 归一化口径见 _norm_site_category，与 _site_type_stats 同源。
            # 顺带：归一化后只留 ERA/COOL/NORMAL 三档（用户要的就是这三个），
            # 排序也按这个固定顺序，而不是字母序 COOL/ERA/NORMAL。
            if param_name == "site_caregory":
                norm = {_norm_site_category(v) for v in vals}
                norm.discard("")
                order = ["ERA", "COOL", "NORMAL"]
                vals = [k for k in order if k in norm] + sorted(norm - set(order))
            filter_options[param_name] = vals
    site_type_stats = _site_type_stats(conn, st, site_cols)
    _meta_cache.update({
        "ts": now, "regions": regions,
        "filter_options": filter_options, "site_type_stats": site_type_stats,
    })
    return regions, filter_options, site_type_stats


# ========== SQL 构建 / 统计采集 / 行组装助手（P2#8 拆分） ==========

def _build_filter_where(S, filter_params, region, network_type):
    """动态筛选条件 → (where_parts, params)"""
    where_parts = []
    params = []
    for param_name, db_col, _ in _GIS_FILTER_COLS:
        val = filter_params.get(param_name)
        if val and db_col in S["site_cols"]:
            where_parts.append(f"{db_col} = ?")
            params.append(val)
    if region:
        where_parts.append("region = ?")
        params.append(region)
    if network_type and "network_type" in S["site_cols"]:
        where_parts.append("network_type = ?")
        params.append(network_type)
    return where_parts, params


def _build_site_select(S):
    """动态 SELECT 片段 → (filter_select_sql, filter_col_indices, prov_sel, vip_sel, hub_sel)"""
    prov_sel = S["province_col"] if S["province_col"] else "NULL"
    vip_sel = S["vip_col"] if S["vip_col"] else "NULL"
    hub_sel = S["hub_col"] if S["hub_col"] else "NULL"
    filter_select_parts = []
    filter_col_indices = {}  # param_name -> index in row
    base_cols = 10  # site_id, site_name, lat, lng, region, prov, network, site_type, vip, hub
    for param_name, db_col, _ in _GIS_FILTER_COLS:
        if db_col in S["site_cols"]:
            filter_select_parts.append(db_col)
            filter_col_indices[param_name] = base_cols + len(filter_select_parts) - 1
    filter_select_sql = ", " + ", ".join(filter_select_parts) if filter_select_parts else ""
    return filter_select_sql, filter_col_indices, prov_sel, vip_sel, hub_sel


def _his_alarm_ms_expr():
    """history_alarm.alarmraisedtime 是 TEXT 列（毫秒时间戳字符串）。
    SQLite 下 text/int 混合比较静默可用，PG 下 text >= bigint 直接报
    UndefinedFunction 导致整个 /gis/sites 500（时间窗口失效根因）。
    按方言输出数值化表达式（与 alarm_dashboard._bn 同款防护：
    非数字值 -> NULL，比较结果为 NULL 自然被排除）。"""
    if DB_MODE == "pg":
        return ('CASE WHEN alarmraisedtime IS NOT NULL AND alarmraisedtime ~ \'^[0-9]+$\' '
                "THEN alarmraisedtime::bigint ELSE NULL END")
    return "CAST(alarmraisedtime AS INTEGER)"


def _alarm_ms_expr(col="alarmraisedtime"):
    """history_alarm / realtime_alarm 的毫秒时间戳列 → 数值化表达式（带列名参数）。

    与 _his_alarm_ms_expr 同款方言防护，供按天聚合复用。
    """
    if DB_MODE == "pg":
        return (f"CASE WHEN {col} IS NOT NULL AND {col} ~ '^[0-9]+$' "
                f"THEN {col}::bigint ELSE NULL END")
    return f"CAST({col} AS INTEGER)"


def _parse_day(value, default=None):
    """校验 YYYY-MM-DD 日期字符串 → 规范化字符串；非法返回 default。

    日期会被内联进 SQL 片段（与 _time_window_clauses 既有风格一致），
    因此这里必须严格校验格式，杜绝任意字符串进入 SQL。
    """
    if not value:
        return default
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return default


def _resolve_window(time_start, time_end, days):
    """统一解析下钻窗口 → (start, end, end_exclusive)。

    规则：显式 time_start/time_end 优先（各自独立校验，非法则忽略）；
    只给 time_start 不给 time_end 时，end 取今天；
    都不给时按 days 从今天回溯（含当天，故为 days-1）。
    start/end 均为 'YYYY-MM-DD'，end_exclusive 为 end+1 天，便于用
    ``col >= start AND col < end_exclusive`` 做半开区间比较。
    """
    end = _parse_day(time_end)
    start = _parse_day(time_start)
    if not start:
        end = end or datetime.now().strftime("%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        start = (end_dt - timedelta(days=max(1, int(days)) - 1)).strftime("%Y-%m-%d")
    elif not end:
        end = datetime.now().strftime("%Y-%m-%d")
    end_excl = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    return start, end, end_excl


def _day_expr(col):
    """时间列 → 'YYYY-MM-DD' 表达式（sqlite substr / PG 取值截断）。

    列名均为代码内常量，不接受外部输入，无注入面。
    注意：eflow_tt.alarm_occur_time 在本项目里是 **text** 列（'YYYY-MM-DD HH:MM:SS'），
    PG 下 to_char(text, ...) 不存在（UndefinedFunction），故 PG 分支用
    substr(col::text, 1, 10) —— 对 text / timestamp 两种存储都安全。
    """
    if DB_MODE == "pg":
        return f"substr({col}::text, 1, 10)"
    return f"substr({col}, 1, 10)"


def _alarm_day_expr(col="alarmraisedtime"):
    """毫秒时间戳列 → 'YYYY-MM-DD'（epoch ms → 秒 → 日期）。

    先经 _alarm_ms_expr 数值化为 bigint，再转 timestamp。
    """
    ms = _alarm_ms_expr(col)
    if DB_MODE == "pg":
        return f"to_char(to_timestamp(({ms}) / 1000.0), 'YYYY-MM-DD')"
    return f"date(({ms}) / 1000, 'unixepoch')"


def _time_window_clauses(time_start, time_end):
    """构建时间窗口过滤片段 → (tt_where, wo_where, his_alarm_where)

    时间参数先经 _parse_day 校验（仅 YYYY-MM-DD），不接受任意字符串。
    """
    tt_where = ""
    wo_where = ""
    his_where = ""
    time_start = _parse_day(time_start)
    time_end = _parse_day(time_end)
    if time_start:
        tt_where += f" AND alarm_occur_time >= '{time_start}'"
        wo_where += f" AND alarm_occur_time >= '{time_start}'"
        his_where += f" AND {_his_alarm_ms_expr()} >= {int(datetime.strptime(time_start, '%Y-%m-%d').timestamp() * 1000)}"
    if time_end:
        end_dt = datetime.strptime(time_end, "%Y-%m-%d") + timedelta(days=1)
        end_str = end_dt.strftime("%Y-%m-%d")
        tt_where += f" AND alarm_occur_time < '{end_str}'"
        wo_where += f" AND alarm_occur_time < '{end_str}'"
        his_where += f" AND {_his_alarm_ms_expr()} < {int(end_dt.timestamp() * 1000)}"
    return tt_where, wo_where, his_where


def _run_stats_query(conn, sql, label):
    """执行一条统计查询，失败时降级为空列表并告警（不冒泡成 500）。

    2026-09-29 新增：/gis/sites 会把 tt / wo / 实时告警 / 历史告警四张表的
    统计串在一次请求里（get_sites），其中任一表被定时任务整表重建时短暂不可用，
    都会让整个地图页 500。GIS 地图是站点底图，缺一张统计表应当只让对应计数
    显示不全，而不是整页失败 —— 与同文件 _fetch_alarm_list（:615-623）
    「表不存在或查询失败时返回 []」保持一致的口径。

    返回 [] 时页面上的对应计数为 0/缺省，属已知降级行为（有 WARNING 日志可查）。
    """
    try:
        return conn.execute(sql).fetchall()
    except Exception:
        logger.warning(
            "[gis/sites] %s 统计不可用，降级为 0（站点地图照常返回）", label, exc_info=True
        )
        return []


def _collect_tt_stats(conn, S, tt_time_where):
    """预计算 TT 统计（自适应关联字段）→ {site_key: (total, open, closed)}"""
    tt_stats = {}
    if S["tt_site_key"]:
        tt_sql = f"""
            SELECT {S['tt_site_key']}, COUNT(*),
                   SUM(CASE WHEN status != 'Closed' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN status = 'Closed' THEN 1 ELSE 0 END)
            FROM eflow_tt WHERE 1=1 {tt_time_where}
            GROUP BY {S['tt_site_key']}
        """
        for sid, cnt, open_cnt, closed_cnt in _run_stats_query(conn, tt_sql, "eflow_tt"):
            tt_stats[str(sid)] = (cnt or 0, open_cnt or 0, closed_cnt or 0)
    return tt_stats


def _collect_wo_stats(conn, S, wo_time_where):
    """WO 统计 → {site_key: count}"""
    wo_stats = {}
    if S["has_wo"] and S["tt_site_key"]:
        wo_sql = f"SELECT {S['tt_site_key']}, COUNT(*) FROM eflow_wo WHERE 1=1 {wo_time_where} GROUP BY {S['tt_site_key']}"
        for sid, cnt in _run_stats_query(conn, wo_sql, "eflow_wo"):
            wo_stats[str(sid)] = cnt or 0
    return wo_stats


def _collect_rt_alarm_stats(conn, S):
    """实时告警统计（按site_id分组）→ {site_id: count}

    表缺失时降级为空字典，**不冒泡成 500**（2026-09-29 修复）。
    背景：realtime_alarm 由 eflow_active_alarm 任务每 30 分钟整表重建
    （task_registry.py:240）。历史实现是 DROP→CREATE + if_exists="replace"，
    存在「表不存在」的窗口，恰好落进去的 /gis/sites 请求就整体 500
    （实测 request_id=ca74c28a6471，栈顶本函数）。
    写端已改为影子表 + 原子改名消除空窗；此处再加一层读取端容错：
    GIS 地图是站点底图，不该因为告警表瞬时不可用而整页失败 ——
    与同文件 _fetch_alarm_list（:615-623）「表不存在或查询失败返回 []」一致。
    """
    rt_alarm_stats = {}
    if S["has_realtime_alarm"]:
        sql = ("SELECT site_id, COUNT(*) FROM realtime_alarm "
               "WHERE site_id IS NOT NULL GROUP BY site_id")
        for sid, cnt in _run_stats_query(conn, sql, "realtime_alarm"):
            rt_alarm_stats[str(sid)] = cnt or 0
    return rt_alarm_stats


def _collect_his_alarm_stats(conn, S, his_time_where):
    """历史告警统计（按site_id分组，受时间窗口限制）→ {site_id: count}

    与 _collect_rt_alarm_stats 同款读取端容错：表缺失时降级为空字典而非 500。
    history_alarm 由 eflow_history_alarm 任务每 3 小时整表重建
    （task_registry.py:247），同属会被重建的表。
    """
    his_alarm_stats = {}
    if S["has_history_alarm"]:
        sql = (f"SELECT site_id, COUNT(*) FROM history_alarm "
               f"WHERE site_id IS NOT NULL{his_time_where} GROUP BY site_id")
        for sid, cnt in _run_stats_query(conn, sql, "history_alarm"):
            his_alarm_stats[str(sid)] = cnt or 0
    return his_alarm_stats


def _fix_latlng(lat, lng):
    """自动修正明显交换的经纬度"""
    if lat < 0 and 0 < lng < 10:
        return lng, lat
    return lat, lng


def _base_site_dict(row):
    """标准 SELECT 行 → 站点基础字段字典"""
    lat = round(float(row[2]), 6) if row[2] else 0
    lng = round(float(row[3]), 6) if row[3] else 0
    lat, lng = _fix_latlng(lat, lng)
    return {
        "site_id": str(row[0] or ''),
        "site_name": str(row[1] or ''),
        "lat": lat,
        "lng": lng,
        "region": str(row[4] or ''),
        "province_county": str(row[5] or ''),
        "network_type": str(row[6] or ''),
        "site_type": str(row[7] or ''),
        "vip_site": str(row[8] or ''),
        "hub_site": str(row[9] or ''),
    }


def _attach_filter_cols(site_dict, row, filter_col_indices):
    """将动态筛选列值附加到站点字典"""
    for param_name, idx in filter_col_indices.items():
        val = str(row[idx] or '') if idx < len(row) else ''
        # site_caregory 归一化后再下发（2026-09-28）。理由见 _get_site_meta 里
        # filter_options 的注释：前端是**精确匹配**，候选值与站点值必须同一口径，
        # 否则库里写作 `REGULAR（NORMAL)` 的站选 NORMAL 时筛不出来，而它明明
        # 已经被算进 site_type_stats 的 NORMAL 里 —— 统计数与筛出的站数对不上。
        # 这里归一化后，站点值与候选值都出自 _norm_site_category，必然一致。
        if param_name == "site_caregory":
            val = _norm_site_category(val)
        site_dict[param_name] = val


def _has_tt(tid) -> bool:
    """该告警是否带 TT。

    ⚠️ 「空 TT」在本库里是**两种**表示，不是一个：
      · NULL（真 NULL）
      · 字面量字符串 'empty'（源数据里的占位符，与 oss_specific_problem 用的是同一套）
    实测 58 行里 NULL 18 行 + 'empty' 11 行。只判 `tid is not None` 会把那 11 行
    算成「有 TT」，指标直接虚高（实测 Unknown 一档会从 1/11 错报成 11/11）。
    故必须同时排除 NULL / 空串 / 'empty'。
    """
    if tid is None:
        return False
    s = str(tid).strip()
    return s != "" and s.lower() != "empty"


# 有效的 TT 优先级档位（eflow_tt.ticket_severity 的取值域，实测 P1~P4 四档）。
# 顺序即优先级次序：P1 最高。UI 按此顺序展示。
TT_PRIORITY_ORDER = ["P1", "P2", "P3", "P4"]
# 未知档的展示键（库里 ticket_severity 存在 NULL；实测 36 行为空）
TT_PRIORITY_UNKNOWN = "Unknown"

# 实时补漏结果的进程内短缓存：{tt_no: (优先级别, 命中时间)}。
#
# ⚠️ 为什么必须有它（2026-10-16 实测到的 bug）：
#   卡片端点（/realtime/sites）与下钻端点（/realtime/priority-alarms）各自调一次
#   `_resolve_tt_priorities`。实时接口偶发少回几单时，两次解析就会给出不同结果 ——
#   实测卡片显示 P3=15/Unknown=6，而下钻显示 P3=21/Unknown=0，用户点进去数字对不上。
#   （根因见下方 `_resolve_tt_priorities` 的实测记录：实时接口只覆盖最近修改的若干行，
#    偶发抖动会让某些单这次命中、下次不命中。）
#   加一层 TTL 缓存后，同一批单在一次页面会话内**只解析一次**，两次调用必然一致；
#   顺带也把「每点一次下钻就打一轮 eFlow 分页（~8s）」的开销省掉。
#   TTL 取 5 分钟：足够覆盖用户看卡片→点下钻→返回→再点 的操作窗口，
#   又不至于让优先级长时间不更新（真正的 freshness 由每小时同步兜底）。
_TT_PRIO_TTL_SEC = 300
_tt_prio_cache: dict = {"at": 0.0, "data": {}}
# 实时拉到的**整个 TT 行**缓存（{tt_no: 行 or None}），供「这个 TT 存不存在」判断用。
# 与 _tt_prio_cache 分开存：一个存优先级别、一个存整行，用途不同但同源同 TTL。
_tt_live_cache: dict = {"at": 0.0, "data": {}}


def _norm_priority(raw) -> str:
    """ticket_severity → 归一的档位键。

    · 大小写与空白都要归一（库里/实时接口可能给 'p1'、' P1 '）—— 规则匹配那几处
      也是 `.strip().upper()` 的同一口径（见 eflow_rules_matcher.py 的用法）。
    · 只认 P1~P4；其余（NULL / 空 / 其它值）一律归到 Unknown，**不猜**。
      这样 UI 上 Unknown 一档能如实反映「取不到优先级」，而不是被塞进某个具体档。
    """
    s = str(raw or "").strip().upper()
    return s if s in TT_PRIORITY_ORDER else TT_PRIORITY_UNKNOWN


def _resolve_tt_priorities(tt_nos, conn):
    """批量取 TT 优先级：**本地镜像优先，实时接口补漏**。

    返回 {tt_no(大写): ('P1'..'P4' | 'Unknown', source)}，source ∈ {'mirror','live'}。

    ---- 为什么是这个顺序（2026-10-16 实测依据）----
    请求方原意是「本地库一小时才更新一次，取不到，要走实时」。实测与之不符：
      · 本地 `eflow_tt.ticket_severity` **本来就有**优先级，告警关联的 27 个 TT 全命中；
      · 直接调实时接口 `fetch_tt_live_batch` 只回 21/27，且**这 21 个值与本地逐条相同**；
      · 少的 6 个是 7~8 月的老单（last_modified_time = 2026-08-11），掉出了实时接口
        「按最近修改倒序前 4000 行」的窗口。
    结论：对当前数据，**镜像比实时更完整**。故以镜像为主干，只用实时去补两类缺口：
      ① 本地根本没有这个单（新单，还没被每小时同步覆盖）；
      ② 本地有、但 `last_modified_time` **晚于**该行的 `_sync_time`（理论上不该发生，
         作为防御：一旦同步有延迟，这里能兜住）。
    这样既不丢老单，又能拿到新单 —— 是「实时」这一诉求的正确落点，而不是全量改走实时
    （那会实测弄丢 6/27）。

    ⚠️ 失败降级：实时接口不可达时**不抛**，返回镜像结果 + 缺口标 Unknown。
       不能因为外部系统抖动就让整张卡空白 —— 优先级只是锦上添花的信息。
    """
    tids = sorted({str(t).strip().upper() for t in (tt_nos or []) if _has_tt(t)})
    if not tids:
        return {}

    out: dict = {}
    ph = ",".join(["?"] * len(tids))
    mirror_stale: list = []
    try:
        rows = conn.execute(
            f"SELECT tt_no, COALESCE(ticket_severity, ''), last_modified_time, _sync_time "
            f"FROM eflow_tt WHERE tt_no IN ({ph})", tids
        ).fetchall()
    except Exception as e:
        # eflow_tt 不存在（极端环境）时不该让整卡失败，全部转实时兜底。
        # ⚠️ 但**必须记日志**：这个 except 曾把真实错误吞掉，导致镜像查询静默返回空、
        #    所有 TT 都退到实时接口，而实时接口看不到老单 —— 表现为卡片上有 6 条
        #    Unknown 而下钻里却是 P3（2026-10-16 实测踩过）。静默吞错在这里代价很高。
        logger.warning("TT 优先级镜像查询失败，全部转实时补漏：%s: %s", type(e).__name__, e)
        rows = []
    for tno, sev, lastmod, synced in rows:
        key = str(tno).strip().upper()
        out[key] = (_norm_priority(sev), "mirror")
        # 防御性：本地这行比同步水印还新 → 认为镜像可能过期，进补漏集合
        if lastmod and synced and str(lastmod) > str(synced):
            mirror_stale.append(key)

    missing = [t for t in tids if t not in out] + mirror_stale
    if missing:
        # 先看进程内缓存（见 _tt_prio_cache 的注释：保证卡片与下钻两次解析一致）
        import time as _time
        now = _time.time()
        cache = _tt_prio_cache["data"]
        if now - _tt_prio_cache["at"] > _TT_PRIO_TTL_SEC:
            cache = {}
            _tt_prio_cache["data"] = cache
            _tt_prio_cache["at"] = now

        # 只对「缓存里也没有」的单真去打实时接口
        need_net = [t for t in missing if t not in cache]
        if need_net:
            try:
                from backend.services.eflow_data_mapper import fetch_tt_live_batch
                live = fetch_tt_live_batch(need_net) or {}
            except Exception as e:  # noqa: BLE001 —— 外部系统故障不应打断页面
                logger.warning("TT 优先级实时补漏失败，回退镜像结果：%s", e)
                live = {}
            for t in need_net:
                row = live.get(t)
                sev = row.get("ticket_severity") if row else None
                # 未命中也缓存（负结果），否则每点一次下钻都要重扫一遍实时接口
                cache[t] = _norm_priority(sev) if sev else TT_PRIORITY_UNKNOWN

        for t in missing:
            if t in cache:
                out[t] = (cache[t], "live" if cache[t] != TT_PRIORITY_UNKNOWN else "none")
            elif t not in out:
                # 两边都没有 → 明确标未知，不臆测
                out[t] = (TT_PRIORITY_UNKNOWN, "none")

    # 兜底：理论上 missing 已覆盖，但保证调用方拿到的字典对每个 tid 都有值
    for t in tids:
        out.setdefault(t, (TT_PRIORITY_UNKNOWN, "none"))
    return out




def _oss_category(osp, title) -> str:
    """OSS 问题类别：优先 oss_specific_problem，为空时**回退 alarm_title**。

    ---- 为什么要回退（2026-10-16 用户反馈）----
    实测发现同一批「Fiber Break」告警在库里被拆成两个值：
      · 11 条 oss_specific_problem = 'empty'（源数据未填类别）→ 原本全归 Unknown
      ·  1 条 oss_specific_problem = 'Fiber Break'
    用户点开 Unknown 看到满屏 Fiber Break 的标题，质疑「为什么统计为 Unknown」。
    核对上游：`originalspecificproblem` 那个 JSON 里也是 `"value": "empty"`、
    `displayname` 为空 —— 确实没填类别，只有**标题**有值。
    故按用户要求用标题兜底，让这 11 条归到 Fiber Break 而非 Unknown。

    ⚠️ 「空」有三种表示，必须都覆盖（与 _has_tt 同一类坑）：
       NULL / 空串 / 字面量 'empty'。
    ⚠️ 标题也做 trim：库里有 `' 2G SITE DOWN'` 这类带前后空格的脏值，
       不 trim 会让同一类因一个首空格而分成两档。
       **大小写刻意不归一**：`2G site down` 与 `2G SITE DOWN` 在本库里都存在，
       但都带非空 osp，走不到这个分支；若在这里强行 upper()，反而会让正常类别的
       展示名（原本是原始标题）被改写，属于无必要的行为变更。
       若将来确实出现「osp 为空且标题仅大小写不同」的重复档，再引入大小写归并。
    """
    cat = str(osp or "").strip()
    if cat and cat.lower() != "empty":
        return cat
    fallback = str(title or "").strip()
    return fallback if fallback else "Unknown"


def _build_site_id_resolver(conn, site_table):
    """构建「脏 site_id → 真实 site_id」的解析器（2026-10-17）。

    ---- 为什么需要（用户实测：「Alarm Stats 与地图对不上」）----
    realtime_alarm 里有少量行的 `site_id` **不是站点 ID，而是站点名**，
    实测 3 个：'Botota'（真 ID 3448）、'6120HA_Compound_3_UPE129'、'Tokadeh'。
    它们 JOIN 不上主表，于是告警被算进卡片统计、却画不到地图上，导致：
        Alarm Stats 合计 48  ≠  地图告警数 44
    用户确认按**站点名回退匹配**：能按名字对上真站点的就归位，
    对不上的才丢弃（并计入 orphan_alarms）。

    返回 resolve(raw_sid) 函数：命中返回真实 site_id，否则返回 None。
    ⚠️ 只对「主表里没有的 site_id」调用本解析器（见调用处），
       正常 ID 走原路径，不引入额外开销。
    ⚠️ 名字匹配用 _norm_site_name（去非字母数字 + 小写），而不是精确等于：
       源数据里站点名有大小写/空格/标点差异（如 'Qcell LMTI (Marshall)'），
       精确匹配会大量漏掉。这也是本项目其它地方站点名比对的既有口径。
    """
    rows = conn.execute(
        f"SELECT CAST(site_id AS TEXT), site_name FROM {site_table}"
    ).fetchall()
    by_id = {str(r[0]) for r in rows}
    # 归一化名字 → 该名下的**全部** site_id（可能是多个）。
    by_name: dict = {}
    for r in rows:
        nm = _norm_site_name(r[1])
        if not nm:
            continue
        by_name.setdefault(nm, set()).add(str(r[0]))

    # ⚠️ 重名处理：**只在唯一命中时回退**，一对多一律不猜。
    #    实测主表里有 10 组「同名不同 ID」，例如
    #        Weala  -> 3043 / 4043
    #        Totota -> 3045 / 4045
    #    它们其实是**同一站点的两套编号**（3xxx / 4xxx），不是两个站；
    #    但仅凭名字无法判断源数据里的 'Weala' 到底指哪个 ID。
    #    "取第一个"会让告警随机落到其中一个上 —— 数字看似对上了、站点却是错的，
    #    比标成孤儿更危险。故一对多时返回 None（保持孤儿），宁缺毋滥。
    #    本次要修的 'Botota' 在表里唯一（3448），不受此限制。
    ambiguous = {nm for nm, ids in by_name.items() if len(ids) > 1}
    if ambiguous:
        logger.info(
            "按站点名回退：%d 个名字对应多个 site_id，不参与回退：%s",
            len(ambiguous), sorted(ambiguous)[:10],
        )

    def resolve(raw_sid):
        """返回真实 site_id；无法**唯一**解析时返回 None。"""
        s = str(raw_sid or "").strip()
        if s in by_id:
            return s
        nm = _norm_site_name(s)
        if not nm or nm in ambiguous:
            return None
        ids = by_name.get(nm)
        return next(iter(ids)) if ids and len(ids) == 1 else None

    return resolve


def _scan_realtime_alarms(conn, site_table=None):
    """单次扫描 realtime_alarm，一次性算出：每站告警数 / tt_id / 超时 / OSS 统计

    site_table：主站点表名。**传入时**会把「用站点名冒充 site_id」的脏行
      按站点名回退归位到真实站点（见 _build_site_id_resolver）；
      不传则保持原样（不影响历史调用方的行为）。

    返回 7 元组，末尾两项为本轮新增（2026-10-16，OSS 卡改口径 + 下钻）：
      · oss_alarms —— {类别: 该类别下的**告警明细行**列表}，供下钻列表直接消费。
        在**同一次扫描**里顺带收集，而不是下钻时再查一遍 —— 这样「卡片上的数字」
        与「下钻列出的行数」必然同源同口径（AGENTS.md 三.1b 的硬要求：下钻 WHERE
        必须与概览完全一致；同源是最强的保证）。
      · oss_tt_counts —— {类别: 带有效 TT 的告警数}，即 oss_counts 的分子。
    """
    rt_alarm_stats: dict = {}
    site_ttids: dict = {}
    overdue_map: dict = {}
    ontime_map: dict = {}
    oss_counts: dict = {}
    oss_sites: dict = {}
    oss_alarms: dict = {}
    oss_tt_counts: dict = {}
    now_ms = int(datetime.now().timestamp() * 1000)
    alarm_rows = conn.execute(
        """
    SELECT CAST(site_id AS TEXT), tt_id, servertime, assign_delay,
           COALESCE(oss_specific_problem, ''), alarm_title, alarmcode,
           site_name, region, province, alarmchangedtime, durationname
    FROM realtime_alarm
    WHERE site_id IS NOT NULL
        """
    ).fetchall()
    # 脏 site_id 的解析器（仅在传入主表名时启用）。延迟到真正需要时才构建 ——
    # 只在发现「主表里没有的 site_id」时才建，正常数据零开销。
    _resolver = None
    _resolver_ready = False
    for (sid, tid, st_raw, ad_raw, osp, title, code,
         site_name, region, county, changed, duration) in alarm_rows:
        sid = str(sid)
        # 若该 site_id 不是主表里的真站点，尝试按站点名回退归位。
        # （site_table 未传时不处理，保持既有行为。）
        if site_table and not _resolver_ready:
            _resolver = _build_site_id_resolver(conn, site_table)
            _resolver_ready = True
        if _resolver is not None:
            resolved = _resolver(sid)
            if resolved is not None:
                sid = resolved
            # resolved 为 None：确实对不上任何站点，保留原值 →
            # 后续按 _valid_sids 过滤时会自然排除，并计入 orphan_alarms。
        rt_alarm_stats[sid] = rt_alarm_stats.get(sid, 0) + 1
        with_tt = _has_tt(tid)
        if with_tt and str(tid).startswith("TT"):
            site_ttids.setdefault(sid, []).append(tid)
        st_ms = _parse_ts_ms(st_raw)
        ad_sec = _parse_delay_sec(ad_raw)
        overdue = st_ms is not None and ad_sec is not None and (now_ms - st_ms) / 1000.0 > ad_sec
        if overdue:
            overdue_map[sid] = overdue_map.get(sid, 0) + 1
        else:
            ontime_map[sid] = ontime_map.get(sid, 0) + 1
        # 类别：osp 优先，为空/'empty' 时回退到 alarm_title（见 _oss_category 的注释）
        key = _oss_category(osp, title)
        oss_counts[key] = oss_counts.get(key, 0) + 1
        oss_sites.setdefault(key, set()).add(sid)
        if with_tt:
            oss_tt_counts[key] = oss_tt_counts.get(key, 0) + 1
        # 下钻明细行。字段刻意与前端告警表格的既有列对齐（站点/站点名/区域/省县/
        # TT/告警时间/时长/是否超时），避免前端为一个新弹窗再造一套列定义。
        oss_alarms.setdefault(key, []).append({
            "site_id": sid,
            "site_name": str(site_name or ""),
            "region": str(region or ""),
            "province_county": str(county or ""),
            "tt_id": "" if not with_tt else str(tid),
            "alarm_title": str(title or ""),
            "alarmcode": str(code or ""),
            "servertime": st_ms,
            "duration": str(duration or ""),
            "overdue": bool(overdue),
        })
    return (rt_alarm_stats, site_ttids, overdue_map, ontime_map,
            oss_counts, oss_sites, oss_alarms, oss_tt_counts)


def _priority_breakdown(alarm_rows, tt_prio: dict):
    """按优先级统计一批告警行 → 有序 [{priority, count}] + 各档告警行（供下钻）。

    统计单位是**告警**（每行一个告警），不是 TT —— 与卡片上「带 TT 的告警数」
    同一单位，用户对照两张卡不会出现「两个数字对不上」。
    只有带 TT 的告警才参与（没 TT 就没有优先级，归 Unknown 会把「无 TT」与
    「有 TT 但取不到级别」混为一谈，所以这里**排除无 TT 的行**，由调用方说明分母）。
    """
    buckets: dict = {p: [] for p in TT_PRIORITY_ORDER}
    buckets[TT_PRIORITY_UNKNOWN] = []
    for row in alarm_rows:
        tid = str(row.get("tt_id") or "").strip().upper()
        if not tid:
            continue  # 无 TT 的告警不参与优先级统计
        prio, _src = tt_prio.get(tid, (TT_PRIORITY_UNKNOWN, "none"))
        buckets.setdefault(prio, []).append(row)
    ordered = TT_PRIORITY_ORDER + [TT_PRIORITY_UNKNOWN]
    return (
        [{"priority": p, "count": len(buckets.get(p, []))} for p in ordered],
        buckets,
    )


def _live_tt_details(tt_nos) -> dict:
    """实时 eFlow 里这些 TT 的 {tt_no: 归一化行}，带进程内 TTL 缓存（负结果也缓存）。

    与优先级那条链路**共用同一份缓存**（_tt_prio_live_cache），但这里缓存的是整个行
    而非仅 ticket_severity —— 因为地图侧还需要判断「这个 TT 到底存不存在」，
    而优先级只需要级别。缓存的是同一个数据源、同一批单，没必要打两次接口。
    """
    import time as _time
    now = _time.time()
    cache = _tt_live_cache["data"]
    if now - _tt_live_cache["at"] > _TT_PRIO_TTL_SEC:
        cache = {}
        _tt_live_cache["data"] = cache
        _tt_live_cache["at"] = now
    need = [t for t in (tt_nos or []) if t not in cache]
    if need:
        try:
            from backend.services.eflow_data_mapper import fetch_tt_live_batch
            live = fetch_tt_live_batch(need) or {}
        except Exception as e:  # noqa: BLE001 —— 外部系统故障不应打断页面
            logger.warning("TT 实时查询失败，回退本地镜像：%s: %s", type(e).__name__, e)
            live = {}
        for t in need:
            cache[t] = live.get(t)  # 未命中缓存 None，避免反复重扫
    return {t: cache.get(t) for t in (tt_nos or []) if cache.get(t)}


def _match_tt_wo(conn, site_ttids):
    """批量关联 TT / WO → (existing_tts, tt_to_wo, valid_wos)

    existing_tts = 「存在的 TT」集合，判据是**本地镜像 ∪ 实时补漏**。

    ---- 为什么必须加实时这一路（2026-10-16 实测）----
    原实现只看本地 eflow_tt（每小时 :22 同步）。实测有 3 个告警的 tt_id
    （TT202610160151/152/155）在镜像里查不到 —— 它们是刚建的新单，还没被本轮同步覆盖。
    但直接问实时 eFlow，3 个**全都存在**（P2/P3）。
    于是地图按镜像算 rt_tt_count=0，而 OSS 卡的 with_tt 按「tt_id 非空」算 1，
    两者对不上 —— 这正是用户反馈的「地图上统计的 TT 也要相同的办法」。
    加实时补漏后，地图、抽屉、卡片三处都认这 3 个单，口径统一。
    """
    all_tids = sorted({t for tids in site_ttids.values() for t in tids})
    tt_to_wo: dict = {}       # tt_no -> wo_no（存在于 eflow_tt 的才算命中）
    existing_tts: set = set()
    if all_tids:
        ph = ",".join("?" * len(all_tids))
        for tno, wno in conn.execute(
            f"SELECT tt_no, wo_no FROM eflow_tt WHERE tt_no IN ({ph})", all_tids
        ).fetchall():
            existing_tts.add(tno)
            if wno:
                tt_to_wo[tno] = wno
        # 镜像没命中的，去实时补一次；补到的也算「存在」
        missing = [t for t in all_tids if t not in existing_tts]
        if missing:
            existing_tts.update(_live_tt_details(missing).keys())
    valid_wos: set = set()
    all_wos = sorted(set(tt_to_wo.values()))
    if all_wos:
        wph = ",".join("?" * len(all_wos))
        valid_wos = {r[0] for r in conn.execute(
            f"SELECT wo_no FROM eflow_wo WHERE wo_no IN ({wph})", all_wos
        ).fetchall()}
    return existing_tts, tt_to_wo, valid_wos


def _site_id_match(site_id):
    """构建 site_id 匹配条件 → (clause, params)

    master_site_db.site_id 在 PG 下是 integer，而 eflow_tt/eflow_wo 是 text；
    直接 site_id = ? 会因 text = integer 抛 UndefinedFunction（下钻 500 根因）。
    统一 CAST(site_id AS TEXT) 比较，参数只传字符串，PG / SQLite 均兼容。
    """
    return "CAST(site_id AS TEXT) = ?", (str(site_id),)


def _fetch_site_detail(conn, st, site_id):
    """按 site_id / site_name 查站点行 → (col_names, site_row or None)"""
    col_names = table_columns(conn, st)
    site_match, site_params = _site_id_match(site_id)
    site_row = conn.execute(
        f'SELECT * FROM {st} WHERE {site_match}', site_params
    ).fetchone()
    if not site_row:
        # 尝试用 site_name 匹配
        site_row = conn.execute(
            f'SELECT * FROM {st} WHERE site_name = ?', (site_id,)
        ).fetchone()
    return col_names, site_row


def _tt_site_match(S, site_id, site_detail):
    """确定 TT 关联方式：优先 site_id，其次 site_name → (clause, params)"""
    if S["tt_site_key"] == "site_id":
        return _site_id_match(site_id)
    if S["tt_site_key"] == "site_name":
        return "site_name = ?", (site_detail.get("site_name", site_id),)
    return "", ()


def _tt_select_clause(S):
    """TT 列表动态选择存在的列"""
    tt_available_cols = [col for col in _TT_DETAIL_COLS if col in S["tt_cols"]]
    return ", ".join(tt_available_cols) if tt_available_cols else "*"


def _dict_rows(cursor):
    """cursor → [dict, ...]"""
    cols = [desc[0] for desc in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _alarm_match_params(site_id):
    """告警表 site_id 匹配 → (clause, params)

    与 _site_id_match 同款防护：PG 下 site_id 是 text 列，参数只传字符串，
    避免 text = integer 类型错误（下钻 500 根因）。
    """
    return "CAST(site_id AS TEXT) = ?", (str(site_id),)


def _fetch_alarm_list(conn, S, table_key, table_name, site_id, time_start=None, time_end_excl=None):
    """实时/历史告警列表查询（表不存在或查询失败时返回 []）

    time_start / time_end_excl 仅对带 alarmraisedtime（epoch ms）的历史告警生效；
    实时告警是当前快照，不做时间过滤。
    """
    if not S[table_key]:
        return []
    try:
        site_match, site_params = _alarm_match_params(site_id)
        win, win_params = "", []
        if table_name == "history_alarm" and (time_start or time_end_excl):
            ms_expr = _alarm_ms_expr("alarmraisedtime")
            if time_start:
                win += f" AND {ms_expr} >= ?"
                win_params.append(int(datetime.strptime(time_start, "%Y-%m-%d").timestamp() * 1000))
            if time_end_excl:
                win += f" AND {ms_expr} < ?"
                win_params.append(int(datetime.strptime(time_end_excl, "%Y-%m-%d").timestamp() * 1000))
        cursor = conn.execute(f"""
            SELECT *
            FROM {table_name}
            WHERE {site_match} {win}
            ORDER BY alarmraisedtime DESC
            LIMIT 100
        """, list(site_params) + win_params)
        return _dict_rows(cursor)
    except Exception:
        logger.warning("[SILENT-EXCEPT] _fetch_alarm_list: exception swallowed", exc_info=True)
        return []


def _fetch_wo_list_by_site(conn, S, site_match, site_params):
    """按站点条件查 WO 列表（表不存在或查询失败时返回 []）

    site_params 由调用方按「站点条件 + 时间窗口」顺序拼好传入。
    """
    if not S["has_wo"]:
        return []
    try:
        cursor = conn.execute(f"""
            SELECT {_WO_SELECT_COLS}
            FROM eflow_wo
            WHERE {site_match} AND alarm_occur_time >= ? AND alarm_occur_time < ?
            ORDER BY alarm_occur_time DESC
            LIMIT 50
        """, site_params)
        return _dict_rows(cursor)
    except Exception:
        logger.warning("[SILENT-EXCEPT] _fetch_wo_list_by_site: exception swallowed", exc_info=True)
        return []


def _sla_stats_from_tt_list(tt_list):
    """基于 TT 列表计算 SLA 统计"""
    return {
        "total_tt": len(tt_list),
        "closed_tt": sum(1 for t in tt_list if str(t.get("status")) == "Closed"),
        "sla_met": sum(1 for t in tt_list if str(t.get("sla_status")) in ("Pass", "Within SLA")),
        "sla_violated": sum(1 for t in tt_list if str(t.get("sla_status")) == "Failed"),
    }


@router.get("/sites")
def get_sites(
    region: str = Query(None),
    trm_type: str = Query(None),
    site_type: str = Query(None),
    hubsite: str = Query(None),
    vip_site: str = Query(None),
    supervisor: str = Query(None),
    fme_name: str = Query(None),
    province_county: str = Query(None),
    power_sources: str = Query(None),
    site_caregory: str = Query(None),
    network_type: str = Query(None),
    time_start: str = Query(None, description="时间窗口开始 YYYY-MM-DD"),
    time_end: str = Query(None, description="时间窗口结束 YYYY-MM-DD"),
):
    """获取站点GIS数据 - 含 TT/WO统计，支持时间窗口和多列筛选（自适应数据库结构）"""
    S = _detect_gis_schema()
    if not S["site_table"]:
        return {"sites": [], "total": 0, "regions": [], "filter_options": {}}

    with get_raw_connection() as conn:
        st = S["site_table"]

        where_parts = [
            "latitude IS NOT NULL",
            "longitude IS NOT NULL",
            "CAST(latitude AS REAL) != 0",
            "CAST(longitude AS REAL) != 0",
        ]
        filter_params = {
            "trm_type": trm_type, "site_type": site_type,
            "hubsite": hubsite, "vip_site": vip_site,
            "supervisor": supervisor, "fme_name": fme_name,
            "province_county": province_county, "power_sources": power_sources,
            "site_caregory": site_caregory,
        }
        extra_where, params = _build_filter_where(S, filter_params, region, network_type)
        where_parts.extend(extra_where)
        where_clause = " AND ".join(where_parts)

        tt_time_where, wo_time_where, his_time_where = _time_window_clauses(time_start, time_end)
        filter_select_sql, filter_col_indices, prov_sel, vip_sel, hub_sel = _build_site_select(S)

        sql = f"""
            SELECT
                site_id, site_name,
                CAST(latitude AS REAL) as lat,
                CAST(longitude AS REAL) as lng,
                region, {prov_sel}, network_type, site_type,
                {vip_sel}, {hub_sel}{filter_select_sql}
            FROM {st}
            WHERE {where_clause}
        """
        rows = conn.execute(sql, params).fetchall()

        # region 列表 + 筛选列唯一值 + 站点等级统计（带 TTL 缓存）
        regions, filter_options, site_type_stats = _get_site_meta(conn, st, S["site_cols"])

        tt_stats = _collect_tt_stats(conn, S, tt_time_where)
        wo_stats = _collect_wo_stats(conn, S, wo_time_where)
        rt_alarm_stats = _collect_rt_alarm_stats(conn, S)
        his_alarm_stats = _collect_his_alarm_stats(conn, S, his_time_where)

        conn.close()

        site_list = []
        for row in rows:
            site_dict = _base_site_dict(row)
            sid = site_dict["site_id"]
            # 尝试用 site_id 匹配 TT 统计，也尝试 site_name
            tt = tt_stats.get(sid, (0, 0, 0))
            if tt == (0, 0, 0) and row[1]:
                tt = tt_stats.get(str(row[1]), (0, 0, 0))
            site_dict.update({
                "tt_count": tt[0],
                "open_tt": tt[1],
                "closed_tt": tt[2],
                "wo_count": wo_stats.get(sid, 0),
                "rt_alarm_count": rt_alarm_stats.get(sid, 0),
                "his_alarm_count": his_alarm_stats.get(sid, 0),
            })
            _attach_filter_cols(site_dict, row, filter_col_indices)
            site_list.append(site_dict)

        return {
            "sites": site_list,
            "total": len(site_list),
            "regions": regions,
            "filter_options": filter_options,
            "site_type_stats": site_type_stats,
        }


# ========== 站点级分制式 KPI 序列（2G/3G/4G 页签） ==========
# 数据源：主库 ms_sla_*_SITE 三张站点级日表（2026-06-18 起，约 96 天）。
# 关联口径（实测）：
#   4G  用 site_id 直接命中 eNodeBId；
#   2G/3G 的 SITE ID / NodeB ID 是另一套编号（BSC/NodeB 域），
#        与主数据 site_id 不同源，必须回退到「站点名规范化匹配」才能命中。
# 站点名前缀差异（4G 的 'eNodeB Name' 缺行政前缀）由 norm_site_name 消解。
_RAT_KPI_SPEC = [
    # (RAT, 表名, ID 列, 名称列, 指标列清单)
    ("2G", "ms_sla_Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_SITE", "SITE ID", "SITE Name", [
        ("tch_service_rate", "TCH in service rate(%)", True),
        ("tch_congestion", "TCH in congestion rate(include handover)(%)", False),
        ("sdcch_congestion", "SDCCH in congestion rate(%)", False),
        ("tch_drop", "TCH in call drop rate(include handover)(%)", False),
        ("sdcch_drop", "SDCCH channel in call drop rate(%)", False),
        ("cssr", "OCI_2G_CSSR_CS(%)", True),
        ("ho_in", "Handover in success rate(%)", True),
        ("ho_out", "Handover out success rate(%)", True),
        ("traffic_erl", "TCH total traffic number(erl)", None),
        ("outage_min", "2G outage(min)", None),
    ]),
    ("3G", "ms_sla_Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE", "NodeB ID", "NodeB Name", [
        ("cell_validity", "Cell Validity Rate(%)", True),
        ("cs_setup", "U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO", True),
        ("rrc_setup", "Ratio of successful RRC connection establishment(%)", True),
        ("cs_rab_setup", "Ratio of successful CS RAB establishment(%)", True),
        ("ps_rab_setup", "Ratio of successful PS RAB establishment(%)", True),
        ("cs_drop", "Ratio of CS Call Drop(%)", False),
        ("ps_drop", "Ratio of PS Call Drop(%)", False),
        ("traffic_erl", "Cell Traffic Volume, CS(Erl)", None),
        ("ps_dl_gb", "U31_Cell DL Traffic Volume, PS(GB)_901411_2_UROP.RNC-MO", None),
        ("ps_ul_gb", "U31_Cell UL Traffic Volume, PS(GB)_901410_2_UROP.RNC-MO", None),
    ]),
    ("4G", "ms_sla_Hourly_KPI_RPA_SITE_MS_SLA_FDD1day_SITE", "eNodeBId", "eNodeB Name", [
        ("cell_availability", "[FDD]Cell Availability[SDR_ITBBU]", True),
        ("call_setup", "[FDD]Call Setup Success Rate[SDR_ITBBU]", True),
        ("rrc_setup", "[FDD]RRC Establishment Success Rate[SDR_ITBBU]", True),
        ("erab_setup", "[FDD]E-RAB Setup Success Rate[SDR_ITBBU]", True),
        ("erab_drop", "[FDD]E-RAB Drop Rate[SDR_ITBBU]", False),
        ("ho_success", "[FDD]Intra-RAT HO Success Rate[SDR_ITBBU]", True),
        ("dl_prb", "[FDD]DL PRB Utilization Rate[SDR_ITBBU]", False),
        ("ul_prb", "[FDD]UL PRB Utilization Rate[SDR_ITBBU]", False),
        ("dl_gb", "[FDD]DL Traffic Volume (GBytes)-new", None),
        ("ul_gb", "[FDD]UL Traffic Volume (GBytes)-new", None),
        ("dl_throughput", "[FDD]DL IP Throughput(Mbps)[SDR_ITBBU]", None),
        ("ul_throughput", "[FDD]UL IP Throughput(Mbps)[SDR_ITBBU]", None),
    ]),
]


def _norm_site_name(value):
    """站点名规范化：去空白 + 去非字母数字字符 + 转小写。

    实测 4G 的 eNodeB Name 为 'Qcell LMTI (Marshall)'，而 2G/3G 为
    'Qcell LMTI (Marshall)'-同形；但部分站点存在行政前缀差异，
    故统一剥离非字母数字字符后比较。
    """
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _resolve_kpi_table(conn, declared_name, available=None):
    """把逻辑表名解析为库中真实表名。

    后端同步链路在不同历史阶段写入的表名不一致：SQLite 里是带
    'ms_sla_' 前缀的全名，PG 里前缀被去掉（'Hourly_KPI_RPA_SITE_...'）。
    这里按「全名 → 去 ms_sla_ 前缀 → 后缀匹配」依次尝试，两种库都能命中。
    """
    names = available if available is not None else set(list_table_names(conn))
    if declared_name in names:
        return declared_name
    stripped = declared_name[len("ms_sla_"):] if declared_name.startswith("ms_sla_") else declared_name
    if stripped in names:
        return stripped
    tail = stripped[-48:]
    matches = sorted(n for n in names if n.endswith(tail))
    return matches[0] if matches else None


def _load_site_kpi_series(site_id, site_name, days=60):
    """按站点读取 2G/3G/4G 站点级日粒度 KPI 序列（图表用）。

    返回 {rat: {"matched_by":..., "site_name":..., "metrics":[...],
                "daily":[{day, <key>: value, ...}], "days": n}}。
    单制式失败不影响其它制式；无数据时该 RAT 返回空。
    """
    out = {}
    sid = str(site_id or "").strip()
    nm = _norm_site_name(site_name)
    if not sid and not nm:
        return out
    try:
        with get_raw_connection() as conn:
            available = set(list_table_names(conn))
            for rat, declared, id_col, name_col, metrics in _RAT_KPI_SPEC:
                out[rat] = _load_one_rat_series(
                    conn, available, rat, declared, id_col, name_col, metrics, sid, nm, days)
    except Exception as exc:
        logger.warning("[gis/kpi] series connection failed site=%s: %s", sid, exc)
        for rat, *_ in _RAT_KPI_SPEC:
            out.setdefault(rat, {"matched_by": None, "site_name": None,
                                 "metrics": [], "daily": [], "days": 0})
    return out


def _load_one_rat_series(conn, available, rat, declared, id_col, name_col, metrics,
                         sid, nm, days):
    """单个制式的站点级 KPI 序列。"""
    entry = {"matched_by": None, "site_name": None, "metrics": [], "daily": [], "days": 0}
    try:
        table = _resolve_kpi_table(conn, declared, available)
        if not table:
            entry["error"] = "表不存在"
            return entry
        cols = set(table_columns(conn, table))
        if id_col not in cols or name_col not in cols:
            entry["error"] = "关键列缺失"
            return entry
        avail = [(k, c, r) for (k, c, r) in metrics if c in cols]
        if not avail:
            entry["error"] = "指标列全缺失"
            return entry

        # 定位站点：4G 用 site_id 直接命中；2G/3G 的 ID 是另一套编号，回退名称匹配
        target_name, matched_by = None, None
        if sid:
            row = conn.execute(
                f'SELECT "{name_col}" FROM "{table}" '
                f'WHERE CAST("{id_col}" AS TEXT) = ? AND "Begin Time" IS NOT NULL '
                f'ORDER BY "Begin Time" DESC LIMIT 1', (sid,)).fetchone()
            if row and row[0]:
                target_name, matched_by = row[0], "site_id"
        if target_name is None and nm:
            cand = conn.execute(
                f'SELECT DISTINCT "{name_col}" FROM "{table}" '
                f'WHERE "{name_col}" IS NOT NULL').fetchall()
            hit = next((c[0] for c in cand if _norm_site_name(c[0]) == nm), None)
            if hit:
                target_name, matched_by = hit, "site_name"
        if target_name is None:
            entry["error"] = "该制式无本站点数据"
            return entry

        entry["matched_by"] = matched_by
        entry["site_name"] = str(target_name)
        entry["metrics"] = [{"key": k, "label": c, "is_rate": r} for k, c, r in avail]

        sel = ", ".join(f'"{c}"' for _, c, _ in avail)
        day_sql = _day_expr('"Begin Time"')
        rows = conn.execute(
            f'SELECT {day_sql} AS day, {sel} FROM "{table}" '
            f'WHERE "{name_col}" = ? AND "Begin Time" IS NOT NULL '
            f'ORDER BY "Begin Time" DESC LIMIT ?',
            (target_name, max(1, int(days)))).fetchall()

        daily = []
        for r in reversed(rows):
            day = str(r[0])[:10] if r[0] else None
            if not day:
                continue
            item = {"day": day}
            for idx, (k, _c, _r) in enumerate(avail, start=1):
                v = r[idx]
                try:
                    item[k] = None if v is None else float(v)
                except (TypeError, ValueError):
                    item[k] = None
            daily.append(item)
        entry["daily"] = daily
        entry["days"] = len(daily)
    except Exception as exc:
        logger.warning("[gis/kpi] series failed rat=%s site=%s: %s", rat, sid, exc)
        entry["error"] = str(exc)[:160]
    return entry


def _load_site_kpis(site_id: str, site_detail: dict, days: int = 60) -> dict:
    """补充站点下钻 KPI。各数据域独立容错，缺表/缺数据不影响原有下钻。

    days 控制「站点可用率」回溯窗口（默认 60 天，跨月回溯），
    以及分制式 KPI 序列的取数天数。
    """
    result = {"availability": [], "packet_loss": [], "microwave": [], "warnings": []}
    site_name = str(site_detail.get("site_name") or site_detail.get("Site_Name") or "").strip()
    sid = str(site_id or "").strip()

    # 站点可用率：跨月回溯最近 days 天（原实现只取当月，月初只剩 1~2 个点）。
    try:
        from backend.services import site_availability_service as avail_svc
        norm_name = getattr(avail_svc, "norm_name", lambda value: str(value or "").strip().lower())
        end_day = datetime.now().date()
        start_day = end_day - timedelta(days=max(1, days) - 1)
        months, cursor_day = [], end_day.replace(day=1)
        while cursor_day >= start_day.replace(day=1):
            months.append(cursor_day.strftime("%Y-%m"))
            cursor_day = (cursor_day - timedelta(days=1)).replace(day=1)
        lo, hi = start_day.strftime("%Y-%m-%d"), end_day.strftime("%Y-%m-%d")

        merged = {}  # (tech, day) -> value，跨月同 key 取后值
        for month in sorted(set(months)):
            try:
                overview = avail_svc.build_overview(month)
            except Exception as exc:
                logger.warning("[gis/kpi] availability month=%s failed site=%s: %s", month, sid, exc)
                continue
            row = next((r for r in overview.get("sites", [])
                        if str(r.get("site_id") or "").strip() == sid
                        or norm_name(r.get("site_name")) == norm_name(site_name)), None)
            if not row:
                continue
            for tech, values in (row.get("techs") or {}).items():
                daily = values.get("daily") if isinstance(values, dict) else None
                if isinstance(daily, dict):
                    for day, value in daily.items():
                        if lo <= str(day)[:10] <= hi:
                            merged[(tech, str(day)[:10])] = value
        if merged:
            result["availability"] = [
                {"tech": tech, "day": day, "availability": value}
                for (tech, day), value in sorted(merged.items(), key=lambda kv: (kv[0][1], kv[0][0]))
            ]
        else:
            result["warnings"].append(f"近 {days} 天暂无站点可用率数据")
    except Exception as exc:
        logger.warning("[gis/kpi] availability failed site=%s: %s", sid, exc)
        result["warnings"].append("站点可用率暂不可用")

    # 丢包：独立 lte_pl 库。优先按站点编码匹配 Managed Element 末尾编码，再按名称匹配。
    # 双模：PG 模式下数据在 lte_pl.packet_loss_data（线上实时写入，约 167 万行）；
    # 本地 data/packet_lost/lte_pl.sqlite3 是迁移前的冻结快照（停在 2026-08-07），
    # 因此 PG 模式绝不能回落到该文件，否则图表会静默展示一个多月前的旧数据。
    try:
        conditions, params = [], []
        if sid:
            conditions.append('"Managed Element" LIKE ?')
            params.append(f"%({sid})")
        if site_name:
            conditions.append('"Managed Element" LIKE ?')
            params.append(f"%{site_name}%")
        rows = []
        if conditions:
            where = " OR ".join(conditions)
            # 与 Packet Loss 看板/日报口径一致：当天未过完，不纳入统计，
            # 否则半个自然日会被画成一个「跌到 0」的假数据点。
            today_str = datetime.now().strftime("%Y-%m-%d")
            if DB_MODE == "pg":
                # ::text 兼容 timestamp / text 两种存储
                sql = (
                    'SELECT substr("Begin Time"::text, 1, 10) AS day, '
                    'MAX("Packet Loss Rate(%)") AS max_packet_loss, '
                    'AVG("Packet Loss Rate(%)") AS avg_packet_loss, '
                    'COUNT(*) AS samples '
                    'FROM lte_pl.packet_loss_data WHERE (' + where + ') '
                    'AND substr("Begin Time"::text, 1, 10) < ? '
                    'GROUP BY substr("Begin Time"::text, 1, 10) '
                    'ORDER BY day DESC LIMIT 31'
                )
                with get_raw_connection() as conn:
                    cur = conn.execute(sql, tuple(params) + (today_str,))
                    cols = [d[0] for d in cur.description]
                    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            else:
                pl_path = Path(r"d:\01_RPA\Task\my_app\data\packet_lost\lte_pl.sqlite3")
                if not pl_path.exists():
                    result["warnings"].append("丢包数据源不存在")
                else:
                    # 一律走 get_raw_connection（勿改回裸 sqlite3.connect）：
                    # 裸连接绕过占位符 ? → %s 翻译与 _ClosingConnection 语义，
                    # 一旦 MY_APP_DB_MODE=pg 就必然失败。此路径仅在 sqlite 模式可达，
                    # 但保持单一数据访问入口，避免将来放宽分支时静默坏图。
                    # 参照 packet_loss_service.py:411 的同库读法。
                    sql = (
                        'SELECT substr("Begin Time",1,10) AS day, '
                        'MAX("Packet Loss Rate(%)") AS max_packet_loss, '
                        'AVG("Packet Loss Rate(%)") AS avg_packet_loss, '
                        'COUNT(*) AS samples '
                        'FROM packet_loss_data WHERE (' + where + ') '
                        'AND substr("Begin Time",1,10) < ? '
                        'GROUP BY substr("Begin Time",1,10) ORDER BY day DESC LIMIT 31'
                    )
                    with get_raw_connection(str(pl_path), timeout=60) as conn:
                        rows = [dict(r) for r in conn.execute(sql, tuple(params) + (today_str,)).fetchall()]
        result["packet_loss"] = list(reversed(rows))
        # 数值化，避免驱动差异导致前端拿到字符串
        for it in result["packet_loss"]:
            for k in ("max_packet_loss", "avg_packet_loss"):
                try:
                    it[k] = None if it.get(k) is None else round(float(it[k]), 4)
                except (TypeError, ValueError):
                    it[k] = None
            try:
                it["samples"] = int(it.get("samples") or 0)
            except (TypeError, ValueError):
                it["samples"] = 0
    except Exception as exc:
        logger.warning("[gis/kpi] packet loss failed site=%s: %s", sid, exc)
        result["warnings"].append("站点丢包数据暂不可用")

    # 微波利用率：复用 MW UME 拓扑服务，按节点 site_id 过滤关联链路。
    try:
        from backend.services.mw_ume.mw_ume_topology import get_topology
        topology = get_topology(top_n=50)
        nodes = {str(n.get("id")): n for n in topology.get("nodes", [])}
        matched = {node_id for node_id, node in nodes.items()
                   if str(node.get("site_id") or "").strip() == sid
                   or str(node.get("site") or "").strip().lower() == site_name.lower()}
        for edge in topology.get("edges", []):
            source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
            if source in matched or target in matched:
                # history 为逐日聚合的 [{date, tx_util, rx_util, max_util}]，
                # 供下钻抽屉画「逐日利用率趋势」；原实现把它丢弃了。
                history = edge.get("history") or []
                result["microwave"].append({
                    "source": nodes.get(source, {}).get("site") or source,
                    "target": nodes.get(target, {}).get("site") or target,
                    "tx_utilization": edge.get("tx_util"),
                    "rx_utilization": edge.get("rx_util"),
                    "capacity_mbps": edge.get("capacity"),
                    "level": edge.get("status"),
                    "max_util": edge.get("max_util"),
                    "begin_time": edge.get("begin_time") or edge.get("bt")
                                  or (history[-1].get("date") if history else None),
                    "history": [
                        {"day": h.get("date"), "tx_util": h.get("tx_util"),
                         "rx_util": h.get("rx_util"), "max_util": h.get("max_util")}
                        for h in history if h.get("date")
                    ],
                })
    except Exception as exc:
        logger.warning("[gis/kpi] microwave failed site=%s: %s", sid, exc)
        result["warnings"].append("微波链路利用率暂不可用")

    result["kpi_series"] = _load_site_kpi_series(site_id, site_name)
    return result


# ========== 下钻图表聚合 ==========
# 下钻明细列表受 LIMIT 50/100 限制（最近 N 条），直接对明细做统计会得到
# 「最近 N 条」而非「站点全量」的分布，画出来的图会误导人。
# 这里在 SQL 层 GROUP BY，返回站点全量口径的聚合结果，专供图表使用。


def _parse_duration_sec(value):
    """eflow_tt.fault_duration_time 形如 '0d0h15m' / '1d2h30m' → 秒；无法解析返回 None。

    也兼容纯数字（部分来源直接写秒数）。供故障时长分桶统计使用。
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = re.match(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", s)
    if m and any(m.groups()):
        d, h, mi, sec = (int(x) if x else 0 for x in m.groups())
        return d * 86400 + h * 3600 + mi * 60 + sec
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _bucket_counts(rows, key_idx=0, count_idx=1, top_n=None):
    """(值, 计数) 行 → [{name, value}, ...]，按计数降序。

    空值 / 'None' / '' 统一归到 'Unknown'，保证各图口径一致。
    """
    out = []
    for r in rows:
        name = r[key_idx]
        name = "Unknown" if name is None or str(name).strip() in ("", "None") else str(name).strip()
        out.append({"name": name, "value": int(r[count_idx] or 0)})
    out.sort(key=lambda x: -x["value"])
    return out[:top_n] if top_n else out


def _tt_wo_analytics(conn, S, site_match, site_params, start=None, end=None):
    """TT / WO 全量聚合统计（图表专用，不受列表 LIMIT 限制）。

    start / end 为已校验的 'YYYY-MM-DD'；end 为闭区间末日（内部 +1 天转半开）。
    """
    result = {"tt": {}, "wo": {}, "warnings": []}
    tt_time = "alarm_occur_time" if "alarm_occur_time" in S["tt_cols"] else "created_time"
    wo_time = "alarm_occur_time"

    # 时间窗口片段（与 site_match 并列 AND）
    end_excl = None
    if end:
        end_excl = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    tt_win, tt_win_params = "", []
    if start:
        tt_win += f" AND {tt_time} >= ?"
        tt_win_params.append(start)
    if end_excl:
        tt_win += f" AND {tt_time} < ?"
        tt_win_params.append(end_excl)
    wo_win, wo_win_params = "", []
    if start:
        wo_win += f" AND {wo_time} >= ?"
        wo_win_params.append(start)
    if end_excl:
        wo_win += f" AND {wo_time} < ?"
        wo_win_params.append(end_excl)

    tt_params = list(site_params) + tt_win_params
    wo_params = list(site_params) + wo_win_params

    # ---- TT 汇总 ----
    try:
        row = conn.execute(f"""
            SELECT COUNT(*),
                   SUM(CASE WHEN status = 'Closed' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN sla_status IN ('Pass', 'Within SLA') THEN 1 ELSE 0 END),
                   SUM(CASE WHEN sla_status = 'Failed' THEN 1 ELSE 0 END),
                   MIN({tt_time}), MAX({tt_time})
            FROM eflow_tt WHERE {site_match} {tt_win}
        """, tt_params).fetchone()
        total = int(row[0] or 0)
        result["tt"]["total"] = total
        result["tt"]["closed"] = int(row[1] or 0)
        result["tt"]["open"] = total - int(row[1] or 0)
        result["tt"]["sla_met"] = int(row[2] or 0)
        result["tt"]["sla_violated"] = int(row[3] or 0)
        result["tt"]["first_time"] = row[4]
        result["tt"]["last_time"] = row[5]
        result["tt"]["sla_rate"] = round(result["tt"]["sla_met"] / total * 100, 2) if total else None
    except Exception:
        logger.warning("[SILENT-EXCEPT] _tt_wo_analytics tt summary", exc_info=True)
        result["warnings"].append("TT 汇总统计失败")
        result["tt"]["total"] = 0

    # ---- TT 分布（按日 / 状态 / 严重度 / SLA / 根因） ----
    try:
        result["tt"]["daily"] = [
            {"day": str(r[0])[:10], "total": int(r[1] or 0), "closed": int(r[2] or 0)}
            for r in conn.execute(f"""
                SELECT {_day_expr(tt_time)} AS day, COUNT(*),
                       SUM(CASE WHEN status = 'Closed' THEN 1 ELSE 0 END)
                FROM eflow_tt WHERE {site_match} AND {tt_time} IS NOT NULL {tt_win}
                GROUP BY {_day_expr(tt_time)} ORDER BY day
            """, tt_params).fetchall()
        ]
        for key, col in (("by_status", "status"), ("by_severity", "ticket_severity"),
                         ("by_sla", "sla_status"), ("by_root_cause", "root_cause")):
            result["tt"][key] = _bucket_counts(conn.execute(
                f"SELECT {col}, COUNT(*) FROM eflow_tt WHERE {site_match} {tt_win} "
                f"GROUP BY 1 ORDER BY 2 DESC",
                tt_params).fetchall(), top_n=10 if key == "by_root_cause" else None)
    except Exception:
        logger.warning("[SILENT-EXCEPT] _tt_wo_analytics tt distribute", exc_info=True)
        result["warnings"].append("TT 分布统计失败")

    # ---- TT 故障时长分桶（解析 '0d0h15m'，SQL 层做不了） ----
    try:
        rows = conn.execute(
            f"SELECT fault_duration_time FROM eflow_tt "
            f"WHERE {site_match} AND fault_duration_time IS NOT NULL AND fault_duration_time != '' "
            f"{tt_win}", tt_params).fetchall()
        buckets = [("≤15m", 0, 900), ("15-30m", 900, 1800), ("30-60m", 1800, 3600),
                   ("1-4h", 3600, 14400), ("4-12h", 14400, 43200), (">12h", 43200, None)]
        counts = {b[0]: 0 for b in buckets}
        parsed = 0
        for r in rows:
            sec = _parse_duration_sec(r[0])
            if sec is None:
                continue
            parsed += 1
            for label, lo, hi in buckets:
                if sec >= lo and (hi is None or sec < hi):
                    counts[label] += 1
                    break
        result["tt"]["duration_buckets"] = [{"name": b[0], "value": counts[b[0]]} for b in buckets]
        result["tt"]["duration_parsed"] = parsed
        result["tt"]["duration_total"] = len(rows)
    except Exception:
        logger.warning("[SILENT-EXCEPT] _tt_wo_analytics tt duration", exc_info=True)
        result["tt"]["duration_buckets"] = []

    # ---- WO 汇总 + 分布 ----
    if S["has_wo"]:
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM eflow_wo WHERE {site_match} {wo_win}", wo_params).fetchone()
            result["wo"]["total"] = int(row[0] or 0)
            for key, col in (("by_status", "status"), ("by_source", "source"),
                             ("by_root_cause", "rc_main_category"),
                             ("by_severity", "ticket_severity")):
                try:
                    result["wo"][key] = _bucket_counts(conn.execute(
                        f"SELECT {col}, COUNT(*) FROM eflow_wo WHERE {site_match} {wo_win} "
                        f"GROUP BY 1 ORDER BY 2 DESC", wo_params).fetchall(), top_n=10)
                except Exception:
                    result["wo"][key] = []
            try:
                result["wo"]["daily"] = [
                    {"day": str(r[0])[:10], "total": int(r[1] or 0)}
                    for r in conn.execute(f"""
                        SELECT {_day_expr(wo_time)} AS day, COUNT(*)
                        FROM eflow_wo WHERE {site_match} AND {wo_time} IS NOT NULL {wo_win}
                        GROUP BY {_day_expr(wo_time)} ORDER BY day
                    """, wo_params).fetchall()
                ]
            except Exception:
                result["wo"]["daily"] = []
        except Exception:
            logger.warning("[SILENT-EXCEPT] _tt_wo_analytics wo", exc_info=True)
            result["wo"]["total"] = 0
            result["warnings"].append("WO 统计失败")

    return result


def _alarm_analytics(conn, S, site_id, start=None, end=None):
    """历史告警全量按日聚合（实时告警行数极少，不做时间序列）。"""
    out = {"his": {}}
    if not S["has_history_alarm"]:
        return out
    try:
        site_match, site_params = _alarm_match_params(site_id)
        win, win_params = "", []
        ms_expr = _alarm_ms_expr("alarmraisedtime")
        if start:
            win += f" AND {ms_expr} >= ?"
            win_params.append(int(datetime.strptime(start, "%Y-%m-%d").timestamp() * 1000))
        if end:
            end_dt = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
            win += f" AND {ms_expr} < ?"
            win_params.append(int(end_dt.timestamp() * 1000))
        params = list(site_params) + win_params
        day_expr = _alarm_day_expr("alarmraisedtime")
        out["his"]["daily"] = [
            {"day": str(r[0])[:10], "total": int(r[1] or 0)}
            for r in conn.execute(f"""
                SELECT {day_expr} AS day, COUNT(*)
                FROM history_alarm WHERE {site_match} AND alarmraisedtime IS NOT NULL {win}
                GROUP BY {day_expr} ORDER BY day
            """, params).fetchall() if r[0]
        ]
        out["his"]["by_severity"] = _bucket_counts(conn.execute(
            f"SELECT perceivedseverityname, COUNT(*) FROM history_alarm "
            f"WHERE {site_match} {win} GROUP BY 1 ORDER BY 2 DESC", params).fetchall())
        out["his"]["by_title"] = _bucket_counts(conn.execute(
            f"SELECT alarm_title, COUNT(*) FROM history_alarm "
            f"WHERE {site_match} {win} GROUP BY 1 ORDER BY 2 DESC", params).fetchall(), top_n=10)
        row = conn.execute(
            f"SELECT COUNT(*) FROM history_alarm WHERE {site_match} {win}", params).fetchone()
        out["his"]["total"] = int(row[0] or 0)
    except Exception:
        logger.warning("[SILENT-EXCEPT] _alarm_analytics his", exc_info=True)
        out["his"] = {}
    return out



@router.get("/drilldown/{site_id}/analytics")
def get_site_drilldown_analytics(
    site_id: str,
    days: int = Query(60, ge=1, le=365, description="统计窗口天数，默认 60"),
    time_start: str = Query(None, description="起始日 YYYY-MM-DD，优先于 days"),
    time_end: str = Query(None, description="结束日 YYYY-MM-DD（含），优先于 days"),
):
    """站点下钻「图表用」全量聚合统计（TT/WO/历史告警）。

    与 /drilldown/{site_id} 的明细列表不同：这里在 SQL 层 GROUP BY，
    统计口径是站点全量，不受列表 LIMIT 50/100 截断影响。
    默认只统计最近 60 天（days=60），可用 time_start/time_end 覆盖。
    """
    S = _detect_gis_schema()
    if not S["site_table"]:
        raise HTTPException(status_code=404, detail="站点表不存在")

    # 与 /drilldown/{site_id} 同口径的窗口解析
    start, end, _ = _resolve_window(time_start, time_end, days)

    with get_raw_connection() as conn:
        col_names, site_row = _fetch_site_detail(conn, S["site_table"], site_id)
        if not site_row:
            conn.close()
            raise HTTPException(status_code=404, detail=f"站点 {site_id} 不存在")
        site_detail = dict(zip(col_names, site_row))
        site_match, site_params = _tt_site_match(S, site_id, site_detail)
        if not site_match:
            conn.close()
            return {"tt": {}, "wo": {}, "his": {}, "warnings": ["无法确定站点关联字段"]}
        data = _tt_wo_analytics(conn, S, site_match, site_params, start, end)
        data.update(_alarm_analytics(conn, S, site_id, start, end))
        conn.close()
        data["site_id"] = str(site_id)
        data["site_name"] = site_detail.get("site_name")
        data["range"] = {"start": start, "end": end, "days": days}
        return data


@router.get("/drilldown/{site_id}")
def get_site_drilldown(
    site_id: str,
    days: int = Query(60, ge=1, le=365, description="明细列表窗口天数，默认 60"),
    time_start: str = Query(None, description="起始日 YYYY-MM-DD，优先于 days"),
    time_end: str = Query(None, description="结束日 YYYY-MM-DD（含），优先于 days"),
):
    """站点下钻：基本信息 + 关联TT/WO列表 + SLA达成情况（自适应数据库结构）

    明细列表默认只取最近 60 天（days=60），避免长周期站点一次拉回上千行。
    上限由 LIMIT 50/100 保证，时间窗口进一步收敛范围。
    """
    S = _detect_gis_schema()
    if not S["site_table"]:
        raise HTTPException(status_code=404, detail="站点表不存在")

    # 与 /analytics 同口径的窗口解析
    win_start, win_end, win_end_excl = _resolve_window(time_start, time_end, days)

    with get_raw_connection() as conn:
        st = S["site_table"]

        col_names, site_row = _fetch_site_detail(conn, st, site_id)
        if not site_row:
            conn.close()
            raise HTTPException(status_code=404, detail=f"站点 {site_id} 不存在")
        site_detail = dict(zip(col_names, site_row))

        tt_site_match, tt_site_params = _tt_site_match(S, site_id, site_detail)
        # 明细时间窗口（? 占位，与 site_match 的 params 顺序拼接）
        tt_win_sql = " AND alarm_occur_time >= ? AND alarm_occur_time < ?"
        tt_win_params = [win_start, win_end_excl]

        # TT列表 - 动态选择存在的列
        tt_cursor = conn.execute(f"""
            SELECT {_tt_select_clause(S)}
            FROM eflow_tt
            WHERE {tt_site_match} {tt_win_sql}
            ORDER BY alarm_occur_time DESC
            LIMIT 50
        """, list(tt_site_params) + tt_win_params)
        tt_list = _dict_rows(tt_cursor)

        # WO列表（仅当表存在时）
        wo_list = _fetch_wo_list_by_site(conn, S, tt_site_match,
                                         list(tt_site_params) + tt_win_params)

        # SLA统计（与明细同窗口，口径一致）
        sla_cursor = conn.execute(f"""
            SELECT COUNT(*),
                   SUM(CASE WHEN status = 'Closed' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN sla_status IN ('Pass', 'Within SLA') THEN 1 ELSE 0 END),
                   SUM(CASE WHEN sla_status = 'Failed' THEN 1 ELSE 0 END)
            FROM eflow_tt WHERE {tt_site_match} {tt_win_sql}
        """, list(tt_site_params) + tt_win_params)
        sla_row = sla_cursor.fetchone()

        # 实时 / 历史告警列表
        rt_alarm_list = _fetch_alarm_list(conn, S, "has_realtime_alarm", "realtime_alarm", site_id)
        his_alarm_list = _fetch_alarm_list(conn, S, "has_history_alarm", "history_alarm", site_id,
                                           win_start, win_end_excl)

        conn.close()

        return {
            "site_info": site_detail,
            "tt_list": tt_list,
            "tt_count": len(tt_list),
            "wo_list": wo_list,
            "wo_count": len(wo_list),
            "rt_alarm_list": rt_alarm_list,
            "rt_alarm_count": len(rt_alarm_list),
            "his_alarm_list": his_alarm_list,
            "his_alarm_count": len(his_alarm_list),
            "sla_stats": {
                "total_tt": sla_row[0] or 0,
                "closed_tt": sla_row[1] or 0,
                "sla_met": sla_row[2] or 0,
                "sla_violated": sla_row[3] or 0,
            },
            "range": {"start": win_start, "end": win_end, "days": days},
            "kpis": _load_site_kpis(site_id, site_detail, days),
        }


@router.get("/realtime/sites")
def get_realtime_sites(
    region: str = Query(None),
    trm_type: str = Query(None),
    site_type: str = Query(None),
    hubsite: str = Query(None),
    vip_site: str = Query(None),
    supervisor: str = Query(None),
    fme_name: str = Query(None),
    province_county: str = Query(None),
    power_sources: str = Query(None),
    site_caregory: str = Query(None),
    network_type: str = Query(None),
):
    """RealTime Alarm Map 站点：仅含实时告警站点，TT/WO 关联实时告警 tt_id

    实时数据，不做时间窗口过滤（始终取 realtime_alarm 全量当前快照）。
    性能：realtime_alarm 单次扫描 + TT/WO 批量关联，避免 per-site N+1 查询。
    """
    S = _detect_gis_schema()
    if not S["site_table"]:
        return {"sites": [], "total": 0, "regions": [], "filter_options": {}}
    with get_raw_connection() as conn:
        _ensure_perf_indexes(conn)
        st = S["site_table"]

        # ===== 1) 单次扫描 realtime_alarm =====
        # 后两项（oss_alarms / oss_tt_counts）供 OSS 卡片新口径与下钻使用；
        # 本端点只用 oss_counts / oss_tt_counts 组装 summary，明细行不下发
        # （列表点击时才走 /realtime/oss-alarms，避免每次刷页面都多传几十条）。
        (rt_alarm_stats, site_ttids, overdue_map, ontime_map,
         oss_counts, oss_sites, _oss_alarms, oss_tt_counts) = (
            _scan_realtime_alarms(conn, S["site_table"]) if S["has_realtime_alarm"]
            else ({}, {}, {}, {}, {}, {}, {}, {})
        )

        if not rt_alarm_stats:
            regions, filter_options, site_type_stats = _get_site_meta(conn, st, S["site_cols"])
            conn.close()
            return {
                "sites": [], "total": 0, "regions": regions, "filter_options": filter_options,
                "site_type_stats": site_type_stats,
                "realtime_alarm_summary": {"oss_problem_stats": [], "overdue_sites": 0, "ontime_sites": 0},
            }

        # ===== 2) 批量关联 TT / WO =====
        existing_tts, tt_to_wo, valid_wos = _match_tt_wo(conn, site_ttids)

        # ===== 3) 仅查询「有实时告警」的站点，而不是全表 805 站 =====
        alarm_site_ids = list(rt_alarm_stats.keys())
        where_parts = [
            "latitude IS NOT NULL", "longitude IS NOT NULL",
            "CAST(latitude AS REAL) != 0", "CAST(longitude AS REAL) != 0",
            f"CAST(site_id AS TEXT) IN ({','.join('?' * len(alarm_site_ids))})",
        ]
        params: list = list(alarm_site_ids)
        filter_params = {
            "trm_type": trm_type, "site_type": site_type,
            "hubsite": hubsite, "vip_site": vip_site,
            "supervisor": supervisor, "fme_name": fme_name,
            "province_county": province_county, "power_sources": power_sources,
            "site_caregory": site_caregory,
        }
        extra_where, extra_params = _build_filter_where(S, filter_params, region, network_type)
        where_parts.extend(extra_where)
        params.extend(extra_params)
        where_clause = " AND ".join(where_parts)

        filter_select_sql, filter_col_indices, prov_sel, vip_sel, hub_sel = _build_site_select(S)

        rows = conn.execute(f"""
            SELECT site_id, site_name, CAST(latitude AS REAL) as lat, CAST(longitude AS REAL) as lng,
                   region, {prov_sel}, network_type, site_type, {vip_sel}, {hub_sel}{filter_select_sql}
            FROM {st} WHERE {where_clause}
        """, params).fetchall()

        regions, filter_options, site_type_stats = _get_site_meta(conn, st, S["site_cols"])

        # ===== 3b) 按 TT 优先级统计（2026-10-16 新增卡）=====
        # ⚠️ **必须在 conn.close() 之前**：`_resolve_tt_priorities` 要读 eflow_tt 镜像。
        #    它先落在下面（原来的位置在 close 之后），结果拿到 InterfaceError:
        #    connection already closed，被那个 except 静默吞掉 → 镜像这一路全废、
        #    所有 TT 退到实时接口 → 实时看不到的 6 个老单变成 Unknown，卡片与下钻对不上。
        #    任何需要 DB 的步骤都必须排在这一行之前。
        # 只统计**能 JOIN 上主站点表**的站点（与 site_list / 地图同源）。
        # `rows` 就是本次查询出的主表站点，故它的 site_id 集合即有效集合；
        # 这样在 conn.close() 之前就能拿到，不必等 site_list 组装完。
        _valid_sids = {str(r[0]) for r in rows}
        all_alarm_rows = [
            r for rs in _oss_alarms.values() for r in rs
            if str(r.get("site_id")) in _valid_sids
        ]
        tt_prio = _resolve_tt_priorities([r.get("tt_id") for r in all_alarm_rows], conn)

        conn.close()

        # ===== 4) 组装（纯内存，无 SQL） =====
        site_list = []
        for row in rows:
            base = _base_site_dict(row)
            sid = base["site_id"]
            rt_cnt = rt_alarm_stats.get(sid, 0)
            if rt_cnt == 0:
                continue
            tids = site_ttids.get(sid, [])
            rt_tt_count = sum(1 for t in tids if t in existing_tts)
            rt_wo_count = len({tt_to_wo[t] for t in tids if t in tt_to_wo and tt_to_wo[t] in valid_wos})
            base.update({
                "tt_count": rt_tt_count, "open_tt": 0, "closed_tt": 0,
                "wo_count": rt_wo_count, "rt_alarm_count": rt_cnt, "his_alarm_count": 0,
                "rt_tt_count": rt_tt_count, "rt_wo_count": rt_wo_count,
                "rt_alarm_overdue": overdue_map.get(sid, 0),
                "rt_alarm_ontime": ontime_map.get(sid, 0),
            })
            _attach_filter_cols(base, row, filter_col_indices)
            site_list.append(base)

        # ===== 把 OSS 统计**收窄到地图上真实存在的站点**（2026-10-17 修复）=====
        #
        # ---- 为什么必须收窄（用户实测：「Alarm Stats (48) 跟地图怎么都对不上」）----
        # oss_counts 是在 `_scan_realtime_alarms` 里按 realtime_alarm **全表**累加的，
        # 但 site_list 只包含能 JOIN 上主站点表（master_site_db）的行。
        # 实测 realtime_alarm 里有 3 个 site_id **不是真站点 ID**：
        #     'Botota'（其实是站点名，真 ID = 3448）
        #     '6120HA_Compound_3_UPE129' / 'Tokadeh'（主表里连名字都找不到）
        # 这 3 个"站点"挂着 4 条 Fiber Break 告警，于是：
        #     Alarm Stats 合计 48  ≠  地图站点告警数 44
        # 两个数各自都对，但它们描述的是**不同的集合** —— 这种"各自正确却互相矛盾"
        # 最难排查。现在统一口径：**两张卡只统计地图上画得出来的站点**，
        # 与 site_list 严格同源，合计必然对得上。
        # ⚠️ 被排除的孤儿告警不会被静默吞掉：数量记在 orphan_alarms 里下发，
        #    便于排查数据质量（见 realtime_alarm_summary）。
        # 复用上面算好的 _valid_sids（来自主表查询结果），不重新从 site_list 推导 ——
        # 只保留一个来源，不易漂移。
        #
        # 用 oss_alarms 的明细行按 _valid_sids 过滤 —— 计数类映射（oss_counts）没有
        # 站点信息，无法反推某条告警属于哪个站，故不采用逐个扣减的写法，
        # 而是从明细重新数一遍，避免三份字典之间出现口径漂移。
        scoped_alarms = {
            k: [r for r in rowlist if str(r.get("site_id")) in _valid_sids]
            for k, rowlist in _oss_alarms.items()
        }
        scoped_alarms = {k: v for k, v in scoped_alarms.items() if v}
        # 由「保留下来的明细行」重新计数，保证 count / with_tt / sites 三者同源，
        # 不再分别来自 oss_counts / oss_tt_counts / oss_sites 三个可能不同步的字典。
        scoped_counts: dict = {}
        scoped_tt: dict = {}
        scoped_sites: dict = {}
        for k, rows in scoped_alarms.items():
            scoped_counts[k] = len(rows)
            scoped_tt[k] = sum(1 for r in rows if str(r.get("tt_id") or "").strip())
            scoped_sites[k] = {str(r.get("site_id")) for r in rows}

        orphan_alarms = sum(len(v) for v in _oss_alarms.values()) - \
                        sum(len(v) for v in scoped_alarms.values())

        oss_problem_stats = [
            # count = 该类别告警数；with_tt = 其中带有效 TT 的告警数；
            # sites = 该类别涉及的**去重站点数**（同一站点可归入多个类别，
            #         故各类 sites 相加 > 站点总数，这是正常的、不是 bug）。
            {"oss_specific_problem": k, "count": v,
             "with_tt": scoped_tt.get(k, 0),
             "sites": len(scoped_sites.get(k, set()))}
            for k, v in sorted(scoped_counts.items(), key=lambda x: -x[1])
        ]
        overdue_sites = sum(1 for s in site_list if s["rt_alarm_overdue"] > 0)
        ontime_sites = sum(1 for s in site_list if s["rt_alarm_overdue"] == 0 and s["rt_alarm_count"] > 0)

        # 优先级分档：tt_prio 已在 conn.close() 之前解析好（见上方 3b），
        # 这里只做纯内存的分桶，不再碰 DB。
        prio_rows, _ = _priority_breakdown(all_alarm_rows, tt_prio)
        priority_stats = {
            "rows": prio_rows,
            # 分母 = 带 TT 的告警数（= 各档之和），供前端显示合计与占比
            "total": sum(x["count"] for x in prio_rows),
        }

        return {
            "sites": site_list,
            "total": len(site_list),
            "regions": regions,
            "filter_options": filter_options,
            "site_type_stats": site_type_stats,
            "realtime_alarm_summary": {
                "oss_problem_stats": oss_problem_stats,
                "priority_stats": priority_stats,
                "overdue_sites": overdue_sites,
                "ontime_sites": ontime_sites,
                # 未纳入统计的孤儿告警数（其 site_id 不在主站点表里，地图上画不出来）。
                # 显式下发而不是丢弃，便于排查数据质量问题。
                "orphan_alarms": orphan_alarms,
            },
        }


@router.get("/realtime/oss-alarms")
def get_realtime_oss_alarms(
    problem: str = Query(..., description="OSS 问题类别（与卡片上显示的字面量一致）"),
    limit: int = Query(500, ge=1, le=5000),
):
    """OSS 卡片下钻：返回某 OSS 问题类别下的**实时告警明细**。

    口径（与 /realtime/sites 的 oss_problem_stats **完全同源**）：
      复用同一个 `_scan_realtime_alarms()`，取它的 oss_alarms[problem]。
      这样「卡片上的 count」与「本端点返回的行数」必然相等 —— 不是靠两处
      WHERE 写得一样（那会随时间漂移），而是物理上同一次扫描的产物。
      下钻不重新拼 SQL 条件，也就不存在「概览用 = 下钻用 LIKE」这类不一致。

    ⚠️ problem 的匹配规则必须与卡片一致：类别由 `_oss_category(osp, title)` 产出 ——
       osp 优先、为空/'empty' 时回退 alarm_title、两者都空才是 'Unknown'。
       这里直接拿**归一后的 key** 比对，不重新查库、也不做 LIKE
       （做 LIKE 会把「空值回退到标题」这条规则拆掉，数字立刻对不上）。

    limit 语义：截断时在 meta.truncated 里显式暴露（AGENTS.md 三.1b：
    取样必须显著大于单页最大数据量，且截断不得静默）。
    """
    S = _detect_gis_schema()
    if not S["site_table"]:
        raise HTTPException(status_code=404, detail="站点表不存在")
    with get_raw_connection() as conn:
        _ensure_perf_indexes(conn)
        try:
            if S["has_realtime_alarm"]:
                scan = _scan_realtime_alarms(conn, S["site_table"])
                oss_alarms = scan[6]      # {类别: 告警明细行}
                oss_tt_counts = scan[7]   # {类别: 带有效 TT 的告警数}
            else:
                oss_alarms, oss_tt_counts = {}, {}
            rows = oss_alarms.get(problem, [])
            # ⚠️ 必须与 /realtime/sites 的卡片**同样收窄到主站点表里存在的站点**
            #    （2026-10-17）。否则卡片只算地图上的站点、下钻却多列出孤儿告警，
            #    用户点开后会看到行数比卡片数字大 —— 正是"对不上"的复现。
            # 一次性取全量 site_id 集合再过滤，避免逐行查库（N+1）。
            valid_sids = {
                str(r0[0]) for r0 in
                conn.execute(f"SELECT CAST(site_id AS TEXT) FROM {S['site_table']}").fetchall()
            }
            rows = [r for r in rows if str(r.get("site_id")) in valid_sids]
            # 优先级解析（镜像优先 + 实时补漏）必须在连接关闭前做 ——
            # 它要读 eflow_tt 镜像。故整体挪进 with 块内。
            tt_prio = _resolve_tt_priorities([r.get("tt_id") for r in rows], conn)
        finally:
            conn.close()

    # 把优先级附加到每行上，供下钻表格直接渲染
    for r in rows:
        tid = str(r.get("tt_id") or "").strip().upper()
        prio, src = tt_prio.get(tid, (TT_PRIORITY_UNKNOWN, "none"))
        r["priority"] = prio
        # 无 TT 的行没有「优先级」可言，单独标出，避免与「有 TT 但未知」混淆
        r["priority_source"] = ("no_tt" if not tid else src)

    total = len(rows)
    truncated = total > limit
    return {
        "problem": problem,
        "count": total,                              # 与卡片 count 同源
        "total": total,
        # ⚠️ 必须是 `oss_tt_counts.get(problem, 0)`，**不能**回退成 oss_counts。
        # oss_tt_counts 只在 with_tt 为真时建键，因此「一条 TT 都没有」的类别
        # 在该字典里是**缺席**（不是 0）。若写成 .get(problem, oss_counts[...])，
        # 缺席时会把**告警总数**当成带 TT 数返回 —— 实测 4G/3G cell down、Fiber Break
        # 三档会被错报成 1/1（真实是 0/1），卡片数字直接失真。
        "with_tt": oss_tt_counts.get(problem, 0),
        "truncated": truncated,
        "limit": limit,
        "data": rows[:limit],
    }


@router.get("/realtime/priority-alarms")
def get_realtime_priority_alarms(
    priority: str = Query(..., description="优先级档位：P1/P2/P3/P4/Unknown"),
    limit: int = Query(500, ge=1, le=5000),
):
    """优先级卡下钻：返回某优先级档位下的**实时告警明细**。

    与 /realtime/sites 的 priority_stats 同源：同样取本次扫描的全部告警行，
    同样调 `_resolve_tt_priorities`（镜像优先 + 实时补漏），所以本端点返回的
    行数恒等于卡片上该档的数字 —— 与 OSS 下钻同一套「同源」保证。

    ⚠️ 「无 TT 的告警」不参与优先级统计（没有 TT 就谈不上优先级），
       因此 4 档 + Unknown 之和 = 带 TT 的告警数，而不是告警总数。
       Unknown 只表示「有 TT 但两边都取不到级别」。
    """
    prio_want = _norm_priority(priority)
    S = _detect_gis_schema()
    if not S["site_table"]:
        raise HTTPException(status_code=404, detail="站点表不存在")
    with get_raw_connection() as conn:
        _ensure_perf_indexes(conn)
        try:
            if S["has_realtime_alarm"]:
                scan = _scan_realtime_alarms(conn, S["site_table"])
                all_rows = [r for rows in scan[6].values() for r in rows]
            else:
                all_rows = []
            # 与卡片同样收窄到主站点表里存在的站点（否则卡片与下钻行数不一致）。
            valid_sids = {
                str(r0[0]) for r0 in
                conn.execute(f"SELECT CAST(site_id AS TEXT) FROM {S['site_table']}").fetchall()
            }
            all_rows = [r for r in all_rows if str(r.get("site_id")) in valid_sids]
            tt_prio = _resolve_tt_priorities([r.get("tt_id") for r in all_rows], conn)
        finally:
            conn.close()

    _, buckets = _priority_breakdown(all_rows, tt_prio)
    rows = buckets.get(prio_want, [])
    for r in rows:
        tid = str(r.get("tt_id") or "").strip().upper()
        src = tt_prio.get(tid, (TT_PRIORITY_UNKNOWN, "none"))[1]
        r["priority"] = prio_want
        r["priority_source"] = src

    total = len(rows)
    return {
        "priority": prio_want,
        "count": total,
        "total": total,
        "truncated": total > limit,
        "limit": limit,
        "data": rows[:limit],
    }


@router.get("/realtime/drilldown/{site_id}")
def get_realtime_drilldown(site_id: str):
    """RealTime Alarm Map 下钻：实时告警 + 关联 tt_id 的 TT + 其 WO（无历史告警）"""
    S = _detect_gis_schema()
    if not S["site_table"]:
        raise HTTPException(status_code=404, detail="站点表不存在")
    with get_raw_connection() as conn:
        st = S["site_table"]

        col_names, site_row = _fetch_site_detail(conn, st, site_id)
        if not site_row:
            conn.close()
            raise HTTPException(status_code=404, detail=f"站点 {site_id} 不存在")
        site_detail = dict(zip(col_names, site_row))

        # 实时告警 tt_id 集合（本站点）
        tids = [r[0] for r in conn.execute(
            "SELECT DISTINCT tt_id FROM realtime_alarm WHERE CAST(site_id AS TEXT)=? AND tt_id IS NOT NULL AND tt_id != '' AND substr(tt_id, 1, 2) = 'TT'",
            (str(site_id),)
        ).fetchall()]

        # TT 列表（动态列）
        # ⚠️ 过滤列必须是 **tt_no**，不能是 ticket_no（2026-10-16 修正）。
        #    实测证据：eflow_tt 里 `tt_no` 是真正的 TT 号（38482/38482 全部以 'TT' 开头），
        #    而 `ticket_no` 存的其实是 **WO 号**（样例 'WO202609270010'，只有 14523/38482 有值，
        #    且**没有一行**以 'TT' 开头）。
        #    原写法 `WHERE ticket_no IN (TT…)` 因此**永远匹配不到**任何行 ——
        #    表现为「地图上该站点 rt_tt_count=1，点开下钻的故障单却是 0 条」，
        #    即用户反馈的「对不上」。
        #    地图侧（_match_tt_wo）用的就是 tt_no，改这里之后两侧口径才一致。
        tt_list = []
        if tids:
            # ⚠️ 这里**必须显式带上 tt_no**：`_tt_select_clause` 只选展示列，
            #    **不含 tt_no**（它的职责是抽屉表格的列）。而下面判断「哪些单镜像里没有」
            #    要靠 tt_no 比对 —— 少了它，每行 tt_no 都是 None，
            #    于是所有 tids 都被误判为 miss，实时补漏会为同一单再插一行，
            #    表现为抽屉里同一条 TT 出现两次、tt_count 比地图多 1
            #    （2026-10-16 实测：地图 1 条 / 抽屉 2 条）。
            ph = ",".join("?" * len(tids))
            tt_cursor = conn.execute(
                f"SELECT tt_no, {_tt_select_clause(S)} FROM eflow_tt WHERE tt_no IN ({ph}) "
                f"ORDER BY alarm_occur_time DESC LIMIT 50",
                tids
            )
            tt_list = _dict_rows(tt_cursor)
            # 镜像里缺的（新单还没被每小时同步覆盖）去实时补，补到的也算上 ——
            # 与地图侧 _match_tt_wo 同一判据，否则「地图 1 条 / 抽屉 0 条」会复现。
            got = {str(t.get('tt_no') or '').strip().upper() for t in tt_list}
            miss = [t for t in tids if str(t).strip().upper() not in got]
            if miss:
                for tno, row in _live_tt_details(miss).items():
                    if row:
                        row = dict(row)
                        row['tt_no'] = tno   # 实时行本就带 tt_no，这里保证键一定在
                        tt_list.append(row)

        # WO 列表（来自 TT 的 wo_no）
        wo_list = []
        wo_nos = [t.get("wo_no") for t in tt_list if t.get("wo_no")]
        if S["has_wo"] and wo_nos:
            wph = ",".join("?" * len(wo_nos))
            try:
                wo_cursor = conn.execute(f"""
                    SELECT {_WO_SELECT_COLS}
                    FROM eflow_wo WHERE wo_no IN ({wph}) ORDER BY alarm_occur_time DESC LIMIT 50
                """, wo_nos)
                wo_list = _dict_rows(wo_cursor)
            except Exception:
                logger.warning("[SILENT-EXCEPT] get_realtime_drilldown: exception swallowed", exc_info=True)
                pass

        # 实时告警列表
        rt_alarm_list = _fetch_alarm_list(conn, S, "has_realtime_alarm", "realtime_alarm", site_id)

        conn.close()
        return {
            "site_info": site_detail,
            "tt_list": tt_list, "tt_count": len(tt_list),
            "wo_list": wo_list, "wo_count": len(wo_list),
            "rt_alarm_list": rt_alarm_list, "rt_alarm_count": len(rt_alarm_list),
            "his_alarm_list": [], "his_alarm_count": 0,
            "sla_stats": _sla_stats_from_tt_list(tt_list),
            "kpis": _load_site_kpis(site_id, site_detail),
        }


@router.get("/regions/summary")
def get_region_summary():
    """按Region汇总（自适应数据库结构）"""
    S = _detect_gis_schema()
    if not S["site_table"]:
        return {"regions": []}
    with get_raw_connection() as conn:
        st = S["site_table"]
        vip_expr = f"SUM(CASE WHEN {S['vip_col']} = 'Yes' THEN 1 ELSE 0 END)" if S["vip_col"] else "0"
        cursor = conn.execute(f"""
            SELECT region, COUNT(*) as site_count,
                   {vip_expr} as vip_count
            FROM {st}
            WHERE region IS NOT NULL AND region != ''
            GROUP BY region ORDER BY site_count DESC
        """)
        result = _dict_rows(cursor)
        conn.close()
        return {"regions": result}


@router.get("/topology")
def get_topology(with_util: int = Query(0, description="1=叠加 mwRealTime 最新 15 分钟粒度链路利用率")):
    """获取 MW 微波链路连线数据（含经纬度）。

    ⚠ 数据源变更（2026-09-25，用户要求）：
      原实现读 `topology` 表（515 行，经 master_site_db 两次 JOIN 后剩 507 条），
      该表的 site_a_id/site_b_id 是**站点编号**，JOIN 不上就丢线。
      现改读 `kml_mw_links`（kind='link' 共 844 条），端点自带两端经纬度
      （lon/lat、lon2/lat2），**无需 JOIN**，因此覆盖更全、也不会因主数据缺行而静默丢线。

    兼容性：**响应结构保持不变**（仍返回 site_a_*/site_b_*/lat_a/lat_b/is_hub_link），
      便于前端平滑切换；仅新增 color 字段（kml 自带的 4 色）供前端按真实线色渲染。
      kml_mw_links 无 hop_count / hub 标记，故 hop_count 置 0、is_hub_link 置 False，
      前端图例随之改为按 color 分组（见 GISMap.tsx）。

    ⚠ 利用率叠加（2026-09-28 新增，with_util=1）：
      把 `?page=mwRealTime` 的最新 15 分钟粒度利用率贴到这些线上，让 GIS 页不必切页
      就能看出哪条微波链路吃紧。两套数据主键不同（KML 用站名、KPI 用 IP）且链路集合
      不重合，**实测只有约一半的线能匹配上**，故：
        - 匹配策略与「宁可少标绝不猜标」的理由见 services/gis_mw_overlay.py 模块头注释；
        - 匹配不上的线 util=None / level='no_kpi'，**保留原 KML 线色**，
          前端据此显示为「无 KPI 数据」而不是绿色（无数据 ≠ 正常）；
        - 额外返回 util_meta 统计，让「为什么只有一半线有颜色」在界面上可解释。
      默认 with_util=0 时行为与改动前**逐字节一致**，便于回滚与灰度。
    """
    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))
        if "kml_mw_links" not in tables:
            logger.warning("[gis] kml_mw_links 不存在，拓扑返回空")
            return {"links": [], "total": 0}
        try:
            rows = conn.execute("""
                SELECT name, a, b, lon, lat, lon2, lat2, color
                FROM kml_mw_links
                WHERE kind = 'link'
                  AND lon IS NOT NULL AND lat IS NOT NULL
                  AND lon2 IS NOT NULL AND lat2 IS NOT NULL
            """).fetchall()
        except Exception:
            logger.warning("[SILENT-EXCEPT] get_topology kml_mw_links: exception swallowed", exc_info=True)
            return {"links": [], "total": 0}
        conn.close()

    links = []
    for name, a, b, lon, lat, lon2, lat2, color in rows:
        try:
            lat_a, lng_a, lat_b, lng_b = float(lat), float(lon), float(lat2), float(lon2)
        except (TypeError, ValueError):
            continue
        # 坐标合法性校验（与 mw_links_store.build_geojson 同一套规则）
        if not (-90 <= lat_a <= 90 and -180 <= lng_a <= 180
                and -90 <= lat_b <= 90 and -180 <= lng_b <= 180):
            continue
        links.append({
            "site_a_id": a or "", "site_a_name": a or "",
            "site_b_id": b or "", "site_b_name": b or "",
            "hop_count": 0,            # kml_mw_links 无此字段
            "is_hub_link": False,      # kml 无 hub 标记，改由 color 区分（见前端图例）
            "lat_a": lat_a, "lng_a": lng_a,
            "lat_b": lat_b, "lng_b": lng_b,
            "name": name or "",
            "color": color or "#0a84ff",
        })

    # 利用率叠加（可选）：匹配不上的线上 util=None / level='no_kpi'，前端保留原线色。
    util_meta = None
    if with_util:
        try:
            from backend.services.mw_ume.mw_ume_topology import get_realtime_topology
            from backend.services.gis_mw_overlay import match_links
            rt = get_realtime_topology(top_n=10)
            links, util_meta = match_links(links, rt.get("nodes") or [], rt.get("edges") or [])
            util_meta["slot"] = (rt.get("meta") or {}).get("selected_date")
            util_meta["granularity"] = (rt.get("meta") or {}).get("granularity")
        except Exception:
            # 不吞异常：叠加失败必须留痕，但**不影响**地图出线（线路本身仍可用）
            logger.warning("[SILENT-EXCEPT] get_topology with_util: exception swallowed",
                           exc_info=True)

    return {"links": links, "total": len(links), "util_meta": util_meta}


_boundaries_cache: dict = {}   # {"ts": epoch, "data": {...}}
_BOUNDARIES_TTL = 1800         # Voronoi 计算约 1.3s，站点坐标近乎静态，缓存 30 分钟


@router.get("/region-boundaries")
def get_region_boundaries():
    """获取各Region的Voronoi分区边界（用于地图蒙层，自适应数据库结构）"""
    if _boundaries_cache and (_time.time() - _boundaries_cache.get("ts", 0)) < _BOUNDARIES_TTL:
        return _boundaries_cache["data"]
    S = _detect_gis_schema()
    if not S["site_table"]:
        return {"regions": []}
    with get_raw_connection() as conn:
        st = S["site_table"]

        # 1. 获取所有站点坐标 + region
        sites = conn.execute(f"""
            SELECT site_id, region,
                   CAST(latitude AS REAL) as lat,
                   CAST(longitude AS REAL) as lng
            FROM {st}
            WHERE region IS NOT NULL AND region != ''
              AND latitude IS NOT NULL AND longitude IS NOT NULL
              AND CAST(latitude AS REAL) != 0
              AND CAST(longitude AS REAL) != 0
        """).fetchall()
        conn.close()

    # 2. Voronoi 分区 + 边界裁剪 + 平滑（几何逻辑见 gis_geometry.py）
    payload = compute_region_boundaries(sites)
    if payload["regions"]:
        _boundaries_cache.update({"ts": _time.time(), "data": payload})
    return payload


# ========== 真实县（County）行政边界（2026-09-25 新增） ==========
# 与上面的 /region-boundaries 并存，二者语义不同，不要互相替代：
#   /region-boundaries   由 827 个站点坐标 Voronoi **推算**出的 3 个大区蒙层
#   /county-boundaries   用户提供的**真实** 15 个县行政边界（GeoJSON 静态资源）
# 前端用三选一开关（none / region / county）切换，见 GISMap.tsx。
_county_cache: dict = {}      # {"ts": epoch, "data": {...}}
_COUNTY_TTL = 3600            # 县界几何是静态文件，站点计数变化慢，缓存 1 小时


# ========== 站点告警处理建议（2026-10-16 新增）==========
# 来源：eFlow QA → /eflow-qa/tt-ume-suggestion（按 TT 查 AID → UME）。
# 本端点按**站点**聚合：复用 /eflow-qa/ume-alarm 内部的 lookup_alarm 链路
# （eFlow alarm_id → UME aid → 处理建议），仅省掉前端按告警循环点选的负担。
# 典型用法：站点下钻抽屉里把同站点的告警建议合并展示。

_ALARM_SUG_CACHE: Dict[str, Tuple[float, dict]] = {}
_ALARM_SUG_LOCK = threading.Lock()
_ALARM_SUG_TTL_HIT = 300   # 命中缓存 5 分钟
_ALARM_SUG_TTL_MISS = 60   # miss/空缓存 60 秒
_ALARM_SUG_MAX_ALARMS = 30 # 单站点最多取多少条告警去查 UME（防抽屉打开一次打 UME 上百次）


def _resolve_alarm_id_value(row: Dict[str, Any]) -> Optional[str]:
    """从告警行里挑出可喂给 lookup_alarm 的 ID（数字 Alarm ID）。

    优先级：
      1. `id`       —— 告警表物理主键（PG bigint / SQLite int），等同 eFlow alarm_id；
      2. `alarm_id` —— 旧版 eflow schema 的别名列（部分环境仍保留）；
      3. `aid`      —— UME 侧告警 ID（PG 下是 text，SQLite 下也常见），
                      lookup_alarm 的 _local_alarm_by_aid 同样会用它兜底。

    返回规范化后的纯数字串（去 .0 后缀），无法识别时返回 None。
    """
    for k in ("id", "alarm_id", "aid"):
        v = row.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s.endswith(".0") and s[:-2].isdigit():
            s = s[:-2]
        if s.isdigit():
            return s
    return None


def _alarm_sug_select_clause(conn) -> str:
    """按告警表的实际列挑出站点建议查询需要的列名（PG Title Case vs SQLite snake_case）。

    不存在则跳过：避免在 PG 上 `SELECT alarm_id` 报 UndefinedColumn。
    返回值是 SELECT 子串（不含 FROM）。
    """
    wanted = ("id", "alarm_id", "aid", "alarmraisedtime", "perceivedseverityname",
              "alarm_title", "alarm_title_en", "codename", "alarmcode", "tt_id")
    cur = conn.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'realtime_alarm'
    """)
    present = {r[0].lower() for r in cur.fetchall()}
    cols = [c for c in wanted if c.lower() in present]
    if not cols:
        # 兜底：至少要 id，否则没东西查
        cols = ["id"]
    return ", ".join(cols)


@router.get("/site-alarm-suggestions")
def get_site_alarm_suggestions(
    site_id: str = Query(..., min_length=1, max_length=64, description="站点ID"),
    days: int = Query(60, ge=1, le=180, description="历史告警回看天数"),
    limit: int = Query(20, ge=1, le=50, description="返回告警建议的最大条数"),
    with_history: int = Query(0, ge=0, le=1, description="1=同时拉 UME 历史告警；0=只取建议"),
):
    """站点下钻的告警处理建议（复用 eFlow QA 的 lookup_alarm 链路）。

    链路与 /api/eflow-qa/ume-alarm 完全同源：
      1. 查 realtime_alarm / history_alarm，按站点过滤、取可查的 alarm_id；
      2. 对每条 alarm_id 调 lookup_alarm：
           - 数字 ID 走「本地 id 列 → aid 列 → UME 历史」兜底；
           - UME 历史未命中再按 站点+时刻 关联（find_alarm_by_event）；
      3. 取 suggestion.default / suggestion.customer；
      4. 按站点缓存（hit 5min / miss 1min），避免反复打 UME。

    返回结构：
      {
        "site_id": "...",
        "items": [
          {
            "alarm_id": "<eFlow 数字 ID>",
            "alarm_title": "...",
            "severity": "...",
            "raised_time": "...",
            "source_table": "realtime_alarm" | "history_alarm",
            "ok": true,
            "suggestion": { "default": "...", "customer": "..." },
            "error": null,
            "elapsed_sec": 0.3,
          }, ...
        ],
        "elapsed_sec": 1.2,
        "warnings": [],
        "cached": false,
      }

    ⚠️ 一次最多 ALARM_SUG_MAX_ALARMS=30 条告警去查 UME，超出截断并写入 warnings，
       让前端显式提示用户缩窗口或换站点。
    """
    cache_key = f"{site_id}|{days}|{limit}|{with_history}"
    now = _time.time()
    with _ALARM_SUG_LOCK:
        ent = _ALARM_SUG_CACHE.get(cache_key)
        if ent and now - ent[0] < (_ALARM_SUG_TTL_HIT if (ent[1] or {}).get("items") else _ALARM_SUG_TTL_MISS):
            cached = dict(ent[1])
            cached["cached"] = True
            return cached

    S = _detect_gis_schema()
    if not S["site_table"]:
        raise HTTPException(status_code=404, detail="站点表不存在")

    t0 = _time.time()
    items: List[Dict[str, Any]] = []
    warnings: List[str] = []
    skipped_no_id = 0

    # ---- 1) 收集候选告警：实时优先、再叠加历史（按告警表 id 去重） ----
    candidates: List[Tuple[str, Dict[str, Any]]] = []  # (source_table, row)
    seen_ids: Set[str] = set()

    with get_raw_connection() as conn:
        # 自适应列名：PG schema 与 eflow SQLite 字段名不一致
        # （PG 无 alarm_id / alarm_title_en，SQLite 无 aid 等），见 _alarm_sug_select_clause
        rt_select = _alarm_sug_select_clause(conn) if S["has_realtime_alarm"] else ""
        his_select = rt_select  # 两表 schema 一致
        if S["has_realtime_alarm"]:
            try:
                site_match, site_params = _alarm_match_params(site_id)
                cur = conn.execute(f"""
                    SELECT {rt_select}
                    FROM realtime_alarm
                    WHERE {site_match}
                    ORDER BY alarmraisedtime DESC
                    LIMIT {_ALARM_SUG_MAX_ALARMS}
                """, site_params)
                for r in _dict_rows(cur):
                    aid_str = _resolve_alarm_id_value(r)
                    if not aid_str or aid_str in seen_ids:
                        if not aid_str:
                            skipped_no_id += 1
                        continue
                    seen_ids.add(aid_str)
                    candidates.append(("realtime_alarm", r))
            except Exception:
                logger.warning("[SILENT-EXCEPT] site-alarm-suggestions realtime 拉取失败",
                               exc_info=True)

        if S["has_history_alarm"] and len(candidates) < limit:
            try:
                site_match, site_params = _alarm_match_params(site_id)
                # 历史告警时间窗口跟随 days，与 /gis/drilldown 的范围一致
                ms_expr = _alarm_ms_expr("alarmraisedtime")
                win_start_ms = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
                cur = conn.execute(f"""
                    SELECT {his_select}
                    FROM history_alarm
                    WHERE {site_match} AND {ms_expr} >= ?
                    ORDER BY alarmraisedtime DESC
                    LIMIT {_ALARM_SUG_MAX_ALARMS}
                """, list(site_params) + [win_start_ms])
                for r in _dict_rows(cur):
                    aid_str = _resolve_alarm_id_value(r)
                    if not aid_str or aid_str in seen_ids:
                        if not aid_str:
                            skipped_no_id += 1
                        continue
                    seen_ids.add(aid_str)
                    candidates.append(("history_alarm", r))
            except Exception:
                logger.warning("[SILENT-EXCEPT] site-alarm-suggestions history 拉取失败",
                               exc_info=True)

        conn.close()

    if not candidates:
        out = {
            "site_id": site_id,
            "items": [],
            "elapsed_sec": round(_time.time() - t0, 2),
            "warnings": ["该站点在数据库中没有可解析 alarm_id 的告警记录"],
            "cached": False,
        }
        with _ALARM_SUG_LOCK:
            _ALARM_SUG_CACHE[cache_key] = (_time.time(), out)
        return out

    if len(candidates) > limit:
        warnings.append(f"站点告警过多，仅取最近 {limit} 条去 UME 查建议")
        candidates = candidates[:limit]

    if skipped_no_id:
        warnings.append(f"{skipped_no_id} 条告警无可解析的 alarm_id，已跳过")

    # ---- 2) 逐条调 lookup_alarm，复用 eFlow QA 的同款链路 ----
    try:
        from backend.services.ran_ume.ran_ume_alarm_service import lookup_alarm
    except ImportError:  # pragma: no cover
        lookup_alarm = None  # type: ignore

    for source_table, row in candidates:
        aid_str = _resolve_alarm_id_value(row) or ""
        item: Dict[str, Any] = {
            "alarm_id": aid_str,
            "alarm_title": row.get("alarm_title") or row.get("alarm_title_en") or row.get("codename"),
            "alarmcode": row.get("alarmcode"),
            "severity": row.get("perceivedseverityname"),
            "raised_time": row.get("alarmraisedtime"),
            "tt_id": row.get("tt_id"),
            "source_table": source_table,
            "ok": False,
            "suggestion": None,
            "suggestion_error": None,
            "error": None,
            "elapsed_sec": 0.0,
        }
        if not aid_str or lookup_alarm is None:
            item["error"] = "lookup_alarm 不可用或 alarm_id 为空"
            items.append(item)
            continue
        try:
            res = lookup_alarm(aid_str, days=days, limit=10,
                                with_history=bool(with_history))
            item["elapsed_sec"] = res.get("elapsed_sec", 0.0)
            item["mode"] = res.get("mode")
            item["ok"] = bool(res.get("ok"))
            if item["ok"]:
                # 取告警侧展示字段（与 /ume-alarm 同源）
                a = res.get("alarm") or {}
                if a.get("title_en") or a.get("title_zh") or a.get("code_name"):
                    item["alarm_title"] = a.get("title_en") or a.get("title_zh") or a.get("code_name") or item["alarm_title"]
                if a.get("alarmcode") is not None:
                    item["alarmcode"] = a.get("alarmcode")
                item["suggestion"] = res.get("suggestion")
                if res.get("suggestion_error"):
                    item["suggestion_error"] = res.get("suggestion_error")
            else:
                item["error"] = res.get("error") or "UME 未返回该告警"
        except Exception as e:  # noqa: BLE001
            item["error"] = f"{type(e).__name__}: {e}"
        items.append(item)

    out = {
        "site_id": site_id,
        "items": items,
        "elapsed_sec": round(_time.time() - t0, 2),
        "warnings": warnings,
        "cached": False,
    }
    with _ALARM_SUG_LOCK:
        _ALARM_SUG_CACHE[cache_key] = (_time.time(), out)
    return out


@router.get("/county-boundaries")
def get_county_boundaries():
    """获取利比里亚 15 个县的真实行政边界（含站点数与实时告警站点数）。

    site_count 的口径与 /gis/sites 保持一致（同样只统计经纬度有效的站点），
    否则界面上的县名旁数字与点击后的地图站点数会对不上（AGENTS.md 三-1b）。

    alarm_site_count（2026-09-25 新增，用户要求标签改显示告警数）：
      = 该县**有实时告警的站点个数**（COUNT(DISTINCT site_id)，不是告警条数）。
      口径同 /gis/realtime/sites：realtime_alarm JOIN master_site_db 且经纬度有效。
      站点表 JOIN 不上的告警（实测 4 个站，site_id 不在主表）不计入任何县 ——
      与实时告警页的站数口径一致，避免两处对不上。

    边界文件缺失时不抛 500 —— 边界属增强显示，不应让整个地图挂掉。
    """
    if _county_cache and (_time.time() - _county_cache.get("ts", 0)) < _COUNTY_TTL:
        return _county_cache["data"]

    counties = load_county_boundaries()

    # 站点计数：与 /gis/sites 完全相同的 WHERE 口径
    counts: dict = {}
    # 告警站点计数：与 /gis/realtime/sites 相同的 JOIN 口径（COUNT DISTINCT 站点）
    alarm_counts: dict = {}
    S = _detect_gis_schema()
    if counties and S["site_table"]:
        try:
            with get_raw_connection() as conn:
                rows = conn.execute(f"""
                    SELECT province_county, COUNT(*)
                    FROM {S["site_table"]}
                    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                      AND CAST(latitude AS REAL) != 0
                      AND CAST(longitude AS REAL) != 0
                      AND province_county IS NOT NULL AND province_county != ''
                    GROUP BY province_county
                """).fetchall()
                # 归一化 key：库里同时存在 'River Cess' / 'River cess' 两种写法
                for name, cnt in rows:
                    key = re.sub(r"\s+", " ", str(name or "").strip()).lower()
                    counts[key] = counts.get(key, 0) + int(cnt or 0)

                if S["has_realtime_alarm"]:
                    arows = conn.execute(f"""
                        SELECT s.province_county,
                               COUNT(DISTINCT CAST(a.site_id AS TEXT))
                        FROM realtime_alarm a
                        JOIN {S["site_table"]} s
                          ON CAST(a.site_id AS TEXT) = CAST(s.site_id AS TEXT)
                        WHERE s.latitude IS NOT NULL AND s.longitude IS NOT NULL
                          AND CAST(s.latitude AS REAL) != 0
                          AND CAST(s.longitude AS REAL) != 0
                          AND s.province_county IS NOT NULL
                          AND s.province_county != ''
                        GROUP BY s.province_county
                    """).fetchall()
                    for name, cnt in arows:
                        key = re.sub(r"\s+", " ", str(name or "").strip()).lower()
                        alarm_counts[key] = alarm_counts.get(key, 0) + int(cnt or 0)
                conn.close()
        except Exception:
            logger.warning("[SILENT-EXCEPT] get_county_boundaries site_count: exception swallowed", exc_info=True)

    for c in counties:
        key = re.sub(r"\s+", " ", c["db_name"]).lower()
        c["site_count"] = counts.get(key, 0)
        c["alarm_site_count"] = alarm_counts.get(key, 0)

    payload = {"counties": counties}
    if counties:
        _county_cache.update({"ts": _time.time(), "data": payload})
    return payload

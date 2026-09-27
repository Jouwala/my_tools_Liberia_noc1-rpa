"""GIS地理信息 API - Voronoi分区版

P2#8 重构（2026-08-03）：
- 几何计算（Voronoi/边界裁剪/平滑）下沉至 gis_geometry.py；
- 4 个高圈复杂度函数（get_sites/get_realtime_sites/get_region_boundaries 等）
  拆分为单一职责的 SQL 构建 / 统计采集 / 行组装助手函数。
"""
import logging
import re
import time as _time
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, HTTPException
from backend.database import get_raw_connection, DB_PATH, DB_MODE
from backend.dialect_helpers import list_table_names, table_columns
from backend.routers.gis_geometry import compute_region_boundaries, load_county_boundaries

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gis", tags=["gis"])

# ========== 自适应GIS数据库结构检测 ==========
_gis_schema_cache = None

def _detect_gis_schema() -> dict:
    """检测数据库结构，兼容 my_app 和 MTN_Comsal"""
    global _gis_schema_cache
    if _gis_schema_cache:
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


def _get_site_meta(conn, st, site_cols):
    """获取 regions + filter_options（带 TTL 缓存，避免每次请求跑 9 条 DISTINCT）"""
    now = _time.time()
    if _meta_cache and (now - _meta_cache.get("ts", 0)) < _META_TTL:
        return _meta_cache["regions"], _meta_cache["filter_options"]
    regions = [r[0] for r in conn.execute(
        f"SELECT DISTINCT region FROM {st} WHERE region IS NOT NULL AND region != '' ORDER BY region"
    ).fetchall()]
    filter_options = {}
    for param_name, db_col, _ in _GIS_FILTER_COLS:
        if db_col in site_cols:
            filter_options[param_name] = [r[0] for r in conn.execute(
                f"SELECT DISTINCT {db_col} FROM {st} WHERE {db_col} IS NOT NULL AND {db_col} != '' ORDER BY {db_col}"
            ).fetchall()]
    _meta_cache.update({"ts": now, "regions": regions, "filter_options": filter_options})
    return regions, filter_options


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
        for sid, cnt, open_cnt, closed_cnt in conn.execute(tt_sql).fetchall():
            tt_stats[str(sid)] = (cnt or 0, open_cnt or 0, closed_cnt or 0)
    return tt_stats


def _collect_wo_stats(conn, S, wo_time_where):
    """WO 统计 → {site_key: count}"""
    wo_stats = {}
    if S["has_wo"] and S["tt_site_key"]:
        wo_sql = f"SELECT {S['tt_site_key']}, COUNT(*) FROM eflow_wo WHERE 1=1 {wo_time_where} GROUP BY {S['tt_site_key']}"
        for sid, cnt in conn.execute(wo_sql).fetchall():
            wo_stats[str(sid)] = cnt or 0
    return wo_stats


def _collect_rt_alarm_stats(conn, S):
    """实时告警统计（按site_id分组）→ {site_id: count}"""
    rt_alarm_stats = {}
    if S["has_realtime_alarm"]:
        for sid, cnt in conn.execute(
            "SELECT site_id, COUNT(*) FROM realtime_alarm WHERE site_id IS NOT NULL GROUP BY site_id"
        ).fetchall():
            rt_alarm_stats[str(sid)] = cnt or 0
    return rt_alarm_stats


def _collect_his_alarm_stats(conn, S, his_time_where):
    """历史告警统计（按site_id分组，受时间窗口限制）→ {site_id: count}"""
    his_alarm_stats = {}
    if S["has_history_alarm"]:
        for sid, cnt in conn.execute(
            f"SELECT site_id, COUNT(*) FROM history_alarm WHERE site_id IS NOT NULL{his_time_where} GROUP BY site_id"
        ).fetchall():
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
        site_dict[param_name] = str(row[idx] or '') if idx < len(row) else ''


def _scan_realtime_alarms(conn):
    """单次扫描 realtime_alarm，一次性算出：每站告警数 / tt_id / 超时 / OSS 统计"""
    rt_alarm_stats: dict = {}
    site_ttids: dict = {}
    overdue_map: dict = {}
    ontime_map: dict = {}
    oss_counts: dict = {}
    oss_sites: dict = {}
    now_ms = int(datetime.now().timestamp() * 1000)
    alarm_rows = conn.execute(
        """
    SELECT CAST(site_id AS TEXT), tt_id, servertime, assign_delay,
           COALESCE(oss_specific_problem, '')
    FROM realtime_alarm
    WHERE site_id IS NOT NULL
        """
    ).fetchall()
    for sid, tid, st_raw, ad_raw, osp in alarm_rows:
        sid = str(sid)
        rt_alarm_stats[sid] = rt_alarm_stats.get(sid, 0) + 1
        if tid and str(tid).startswith("TT"):
            site_ttids.setdefault(sid, []).append(tid)
        st_ms = _parse_ts_ms(st_raw)
        ad_sec = _parse_delay_sec(ad_raw)
        if st_ms is not None and ad_sec is not None and (now_ms - st_ms) / 1000.0 > ad_sec:
            overdue_map[sid] = overdue_map.get(sid, 0) + 1
        else:
            ontime_map[sid] = ontime_map.get(sid, 0) + 1
        key = osp if osp and osp != "empty" else "Unknown"
        oss_counts[key] = oss_counts.get(key, 0) + 1
        oss_sites.setdefault(key, set()).add(sid)
    return rt_alarm_stats, site_ttids, overdue_map, ontime_map, oss_counts, oss_sites


def _match_tt_wo(conn, site_ttids):
    """批量关联 TT / WO（2 条查询代替 per-site 3 条）→ (existing_tts, tt_to_wo, valid_wos)"""
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

        # region 列表 + 筛选列唯一值（带 TTL 缓存）
        regions, filter_options = _get_site_meta(conn, st, S["site_cols"])

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
                    conn = sqlite3.connect(str(pl_path))
                    conn.row_factory = sqlite3.Row
                    sql = (
                        'SELECT substr("Begin Time",1,10) AS day, '
                        'MAX("Packet Loss Rate(%)") AS max_packet_loss, '
                        'AVG("Packet Loss Rate(%)") AS avg_packet_loss, '
                        'COUNT(*) AS samples '
                        'FROM packet_loss_data WHERE (' + where + ') '
                        'AND substr("Begin Time",1,10) < ? '
                        'GROUP BY substr("Begin Time",1,10) ORDER BY day DESC LIMIT 31'
                    )
                    rows = [dict(r) for r in conn.execute(sql, params + [today_str]).fetchall()]
                    conn.close()
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
        rt_alarm_stats, site_ttids, overdue_map, ontime_map, oss_counts, oss_sites = (
            _scan_realtime_alarms(conn) if S["has_realtime_alarm"]
            else ({}, {}, {}, {}, {}, {})
        )

        if not rt_alarm_stats:
            regions, filter_options = _get_site_meta(conn, st, S["site_cols"])
            conn.close()
            return {
                "sites": [], "total": 0, "regions": regions, "filter_options": filter_options,
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

        regions, filter_options = _get_site_meta(conn, st, S["site_cols"])
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

        oss_problem_stats = [
            {"oss_specific_problem": k, "count": v, "sites": len(oss_sites.get(k, set()))}
            for k, v in sorted(oss_counts.items(), key=lambda x: -x[1])
        ]
        overdue_sites = sum(1 for s in site_list if s["rt_alarm_overdue"] > 0)
        ontime_sites = sum(1 for s in site_list if s["rt_alarm_overdue"] == 0 and s["rt_alarm_count"] > 0)
        return {
            "sites": site_list,
            "total": len(site_list),
            "regions": regions,
            "filter_options": filter_options,
            "realtime_alarm_summary": {
                "oss_problem_stats": oss_problem_stats,
                "overdue_sites": overdue_sites,
                "ontime_sites": ontime_sites,
            },
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
        tt_list = []
        if tids:
            ph = ",".join("?" * len(tids))
            tt_cursor = conn.execute(
                f"SELECT {_tt_select_clause(S)} FROM eflow_tt WHERE ticket_no IN ({ph}) ORDER BY alarm_occur_time DESC LIMIT 50",
                tids
            )
            tt_list = _dict_rows(tt_cursor)

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
def get_topology():
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
    return {"links": links, "total": len(links)}


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

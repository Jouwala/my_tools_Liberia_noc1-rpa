"""GIS地理信息 API - Voronoi分区版

P2#8 重构（2026-08-03）：
- 几何计算（Voronoi/边界裁剪/平滑）下沉至 gis_geometry.py；
- 4 个高圈复杂度函数（get_sites/get_realtime_sites/get_region_boundaries 等）
  拆分为单一职责的 SQL 构建 / 统计采集 / 行组装助手函数。
"""
import logging
import time as _time
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, HTTPException
from backend.database import get_raw_connection, DB_PATH
from backend.dialect_helpers import list_table_names, table_columns
from backend.routers.gis_geometry import compute_region_boundaries

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
    ("area", "area", "Area"),
    ("hubsite", "hub_site", "Hub Site"),
    ("site_information", "site_information", "Site Information"),
    ("vip_site", "vip_site", "VIP Site"),
    ("supervisor", "supervisor", "Supervisor"),
    ("updated_fme_name_new", "updated_fme_name_new", "FME Name"),
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


def _time_window_clauses(time_start, time_end):
    """构建时间窗口过滤片段 → (tt_where, wo_where, his_alarm_where)"""
    tt_where = ""
    wo_where = ""
    his_where = ""
    if time_start:
        tt_where += f" AND alarm_occur_time >= '{time_start}'"
        wo_where += f" AND alarm_occur_time >= '{time_start}'"
        his_where += f" AND alarmraisedtime >= {int(datetime.strptime(time_start, '%Y-%m-%d').timestamp() * 1000)}"
    if time_end:
        end_dt = datetime.strptime(time_end, "%Y-%m-%d") + timedelta(days=1)
        end_str = end_dt.strftime("%Y-%m-%d")
        tt_where += f" AND alarm_occur_time < '{end_str}'"
        wo_where += f" AND alarm_occur_time < '{end_str}'"
        his_where += f" AND alarmraisedtime < {int(end_dt.timestamp() * 1000)}"
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
    """构建 site_id 匹配条件（兼容整数和字符串）→ (clause, params)"""
    try:
        site_id_int = int(site_id)
        return "(site_id = ? OR site_id = ?)", (site_id, site_id_int)
    except (ValueError, TypeError):
        logger.warning("[SILENT-EXCEPT] _site_id_match: exception swallowed", exc_info=True)
        return "site_id = ?", (site_id,)


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
    """告警表 site_id 匹配（兼容整数和字符串）→ (clause, params)"""
    if str(site_id).isdigit():
        return "(site_id = ? OR site_id = ?)", (str(site_id), int(site_id))
    return "site_id = ?", (str(site_id),)


def _fetch_alarm_list(conn, S, table_key, table_name, site_id):
    """实时/历史告警列表查询（表不存在或查询失败时返回 []）"""
    if not S[table_key]:
        return []
    try:
        site_match, site_params = _alarm_match_params(site_id)
        cursor = conn.execute(f"""
            SELECT *
            FROM {table_name}
            WHERE {site_match}
            ORDER BY alarmraisedtime DESC
            LIMIT 100
        """, site_params)
        return _dict_rows(cursor)
    except Exception:
        logger.warning("[SILENT-EXCEPT] _fetch_alarm_list: exception swallowed", exc_info=True)
        return []


def _fetch_wo_list_by_site(conn, S, site_match, site_params):
    """按站点条件查 WO 列表（表不存在或查询失败时返回 []）"""
    if not S["has_wo"]:
        return []
    try:
        cursor = conn.execute(f"""
            SELECT {_WO_SELECT_COLS}
            FROM eflow_wo
            WHERE {site_match}
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
    area: str = Query(None),
    hubsite: str = Query(None),
    site_information: str = Query(None),
    vip_site: str = Query(None),
    supervisor: str = Query(None),
    updated_fme_name_new: str = Query(None),
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
            "trm_type": trm_type, "site_type": site_type, "area": area,
            "hubsite": hubsite, "site_information": site_information,
            "vip_site": vip_site, "supervisor": supervisor,
            "updated_fme_name_new": updated_fme_name_new,
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


@router.get("/drilldown/{site_id}")
def get_site_drilldown(site_id: str):
    """站点下钻：基本信息 + 关联TT/WO列表 + SLA达成情况（自适应数据库结构）"""
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

        tt_site_match, tt_site_params = _tt_site_match(S, site_id, site_detail)

        # TT列表 - 动态选择存在的列
        tt_cursor = conn.execute(f"""
            SELECT {_tt_select_clause(S)}
            FROM eflow_tt
            WHERE {tt_site_match}
            ORDER BY alarm_occur_time DESC
            LIMIT 50
        """, tt_site_params)
        tt_list = _dict_rows(tt_cursor)

        # WO列表（仅当表存在时）
        wo_list = _fetch_wo_list_by_site(conn, S, tt_site_match, tt_site_params)

        # SLA统计
        sla_cursor = conn.execute(f"""
            SELECT COUNT(*),
                   SUM(CASE WHEN status = 'Closed' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN sla_status IN ('Pass', 'Within SLA') THEN 1 ELSE 0 END),
                   SUM(CASE WHEN sla_status = 'Failed' THEN 1 ELSE 0 END)
            FROM eflow_tt WHERE {tt_site_match}
        """, tt_site_params)
        sla_row = sla_cursor.fetchone()

        # 实时 / 历史告警列表
        rt_alarm_list = _fetch_alarm_list(conn, S, "has_realtime_alarm", "realtime_alarm", site_id)
        his_alarm_list = _fetch_alarm_list(conn, S, "has_history_alarm", "history_alarm", site_id)

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
        }


@router.get("/realtime/sites")
def get_realtime_sites(
    region: str = Query(None),
    trm_type: str = Query(None),
    site_type: str = Query(None),
    area: str = Query(None),
    hubsite: str = Query(None),
    site_information: str = Query(None),
    vip_site: str = Query(None),
    supervisor: str = Query(None),
    updated_fme_name_new: str = Query(None),
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
            "trm_type": trm_type, "site_type": site_type, "area": area,
            "hubsite": hubsite, "site_information": site_information,
            "vip_site": vip_site, "supervisor": supervisor,
            "updated_fme_name_new": updated_fme_name_new,
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
            "SELECT DISTINCT tt_id FROM realtime_alarm WHERE CAST(site_id AS TEXT)=? AND tt_id IS NOT NULL AND tt_id != '' AND tt_id LIKE 'TT%'",
            (str(site_id),)
        )]

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
    """获取站点拓扑连线数据（含经纬度，自适应数据库结构）"""
    S = _detect_gis_schema()
    if not S["has_topology"] or not S["site_table"]:
        return {"links": [], "total": 0}
    with get_raw_connection() as conn:
        st = S["site_table"]
        rows = conn.execute(f"""
            SELECT t.site_a_id, t.site_a_name, t.site_b_id, t.site_b_name,
                   t.hop_count, t.a_is_hub, t.b_is_hub,
                   a.latitude as lat_a, a.longitude as lng_a,
                   b.latitude as lat_b, b.longitude as lng_b
            FROM topology t
            LEFT JOIN {st} a ON CAST(t.site_a_id AS TEXT) = CAST(a.site_id AS TEXT)
            LEFT JOIN {st} b ON CAST(t.site_b_id AS TEXT) = CAST(b.site_id AS TEXT)
            WHERE a.latitude IS NOT NULL AND b.latitude IS NOT NULL
        """).fetchall()
        conn.close()
        links = []
        for r in rows:
            links.append({
                "site_a_id": r[0], "site_a_name": r[1],
                "site_b_id": r[2], "site_b_name": r[3],
                "hop_count": r[4], "is_hub_link": bool(r[5] and r[6]),
                "lat_a": r[7], "lng_a": r[8],
                "lat_b": r[9], "lng_b": r[10],
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

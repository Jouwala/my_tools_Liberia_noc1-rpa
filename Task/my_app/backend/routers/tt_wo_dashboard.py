"""TT&WO Dashboard API - 综合统计看板 (自适应版: 兼容 my_app 和 MTN_Comsal)"""
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from backend.database import get_raw_connection, DB_PATH
from backend.dialect_helpers import list_table_names, table_columns

router = APIRouter(prefix="/api/tt-wo-dashboard", tags=["tt-wo-dashboard"])

# ========== 自适应数据库结构检测 ==========
_schema_cache = None


def _detect_schema() -> dict:
    """检测数据库结构，缓存后复用。兼容 my_app 和 MTN_Comsal"""
    global _schema_cache
    if _schema_cache:
        return _schema_cache

    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))

        # 站点表
        if "master_site_db" in tables:
            site_table = "master_site_db"
        elif "site_db" in tables:
            site_table = "site_db"
        else:
            site_table = None

        # TT表字段检测
        tt_cols = set(table_columns(conn, "eflow_tt")) if "eflow_tt" in tables else set()

        # 严重性字段: alarm_severity 或 category
        has_alarm_severity = "alarm_severity" in tt_cols
        sev_field = "alarm_severity" if has_alarm_severity else "category" if "category" in tt_cols else None

        # 站点关联字段: site_id 或 site_name
        site_join_field = "site_id" if "site_id" in tt_cols else "site_name" if "site_name" in tt_cols else None

        # 创建者字段: creator 或 owner
        creator_field = "creator" if "creator" in tt_cols else "owner" if "owner" in tt_cols else None

        # WO表
        has_wo = "eflow_wo" in tables

        # 站点表字段检测
        site_cols = set()
        if site_table:
            site_cols = set(table_columns(conn, site_table))

        # 站点统计字段映射
        site_stat_fields = {}
        if "power_sources" in site_cols:
            site_stat_fields["power_sources"] = "power_sources"
        if "power_vendor" in site_cols:
            site_stat_fields["power_vendor"] = "power_vendor"
        if "vendor" in site_cols and "power_vendor" not in site_cols:
            site_stat_fields["vendor"] = "vendor"
        if "updated_fme_name_new" in site_cols:
            site_stat_fields["maintenance_team"] = "updated_fme_name_new"
        elif "site_maintainer" in site_cols:
            site_stat_fields["maintenance_team"] = "site_maintainer"
        if "site_class" in site_cols:
            site_stat_fields["site_class"] = "site_class"

        # 高级过滤候选列（参照 GISMap 的 FILTER_CONFIG）：只在库中真实存在时才暴露给
        # 前端，避免换库（my_app / MTN_Comsal）后下拉框里出现永远为空的筛选项。
        site_filter_fields = [c for c in (
            "region", "province_county", "network_type", "site_type", "vip_site",
            "trm_type", "supervisor", "fme_name", "power_sources", "power_vendor",
            "site_caregory",
        ) if c in site_cols]

        conn.close()

        _schema_cache = {
            "site_table": site_table,
            "site_join_field": site_join_field,
            "sev_field": sev_field,
            "has_alarm_severity": has_alarm_severity,
            "creator_field": creator_field,
            "has_wo": has_wo,
            "site_stat_fields": site_stat_fields,
            "site_filter_fields": site_filter_fields,
            "tt_cols": tt_cols,
            "site_cols": site_cols,
        }
        return _schema_cache


def _time_filter(prefix: str, time_start: str | None, time_end: str | None) -> tuple[str, list]:
    """构建时间过滤SQL片段"""
    parts, params = [], []
    f = f"{prefix}.alarm_occur_time"
    if time_start:
        parts.append(f"{f} >= ?")
        params.append(time_start)
    if time_end:
        end_dt = datetime.strptime(time_end, "%Y-%m-%d") + timedelta(days=1)
        parts.append(f"{f} < ?")
        params.append(end_dt.strftime("%Y-%m-%d"))
    return " AND ".join(parts), params


def _safe_str(val, default: str = "Unknown") -> str:
    if val is None or str(val).strip() == '' or str(val) == 'None':
        return default
    return str(val)


# Ticket Severity 中这些值表示「没有可用级别」，不能作为一个真实级别参与统计。
# 同时兼容数据库里已经存在的正确拼写与历史误拼写 ``unkonw``。
#
# 背景（2026-09-29 业务要求）：page=tt 的 Ticket Severity 卡不得统计与显示 Unknown。
# 注意与邻近的 ``_safe_str`` 区分 —— ``_safe_str`` 把 NULL/空串/'None' 归并为字面量
# 'Unknown'，因此「空值」与「真的写着 unknown」在本函数里被统一拦截。
_EXCLUDED_TICKET_SEVERITIES = frozenset({"unknown", "unkonw"})


def _is_excluded_ticket_severity(value) -> bool:
    """判断 Ticket Severity 是否为不可统计/展示的 Unknown 标记。"""
    return str(value or "").strip().casefold() in _EXCLUDED_TICKET_SEVERITIES


def _ticket_severity_key(value) -> str | None:
    """返回可用于 Ticket Severity 统计的键；Unknown 标记返回 None。"""
    severity = _safe_str(value).strip()
    return None if _is_excluded_ticket_severity(severity) else severity


def _stat_key(value, excluded: frozenset, join_empty: bool = False) -> str | None:
    """统计维度的通用取值归一：命中 ``excluded`` 返回 None（调用方跳过该行）。

    :param excluded: 需排除的取值集合（小写比较）。
    :param join_empty: True 时沿用 ``_safe_str`` 的语义，把 NULL/空串/'None'
        归并为字面量 ``'Unknown'`` 再判排除；False 时保持原值（仅用于需要
        区分「空」与「字面量 None」的维度）。

    2026-09-29：SLA 状态同样要求不统计/不显示 Unknown（此前 JOIN 不上关联 TT、
    或 TT 未算 SLA 的行会被 ``_safe_str`` 归并成 'Unknown' 单独成一类）。
    """
    normalized = _safe_str(value) if join_empty else _safe_str(value, "")
    if str(normalized).strip().casefold() in excluded:
        return None
    return normalized


# SLA 状态：Pass / Failed / Within SLA 之外的值（含 JOIN 不上 TT 的 Unknown）不计入统计。
# 与 Ticket Severity 同一套排除语义，避免两个维度口径不一致。
_EXCLUDED_SLA_STATUSES = frozenset({"unknown", "unkonw"})

# 已剔除 Unknown 的维度（概览统计与下钻必须同步，否则数字与行数对不上）。
_UNKNOWN_EXCLUDED_DIMENSIONS = frozenset({"ticket_severity", "sla_status"})



# ========== ZTE / 3rd 归属过滤 ==========
# 口径（业务确认）：wo_no 非空 = ZTE 自派单，wo_no 为空 = 3rd 第三方单。
# overview 与 drilldown 必须共用本函数，否则「看板上的数字」与「下钻的行数」
# 会对不上，用户会当成 bug（见 Task/my_app/AGENTS.md 第三节第 1b 条）。
OWNER_ZTE = "zte"
OWNER_THIRD = "3rd"

# TRIM 兼顾 NULL 与纯空格两种空值写法（实测库里两种都存在）
_OWNER_SQL = {
    OWNER_ZTE: "(t.wo_no IS NOT NULL AND TRIM(t.wo_no) <> '')",
    OWNER_THIRD: "(t.wo_no IS NULL OR TRIM(t.wo_no) = '')",
}


def _owner_where(owner: str | None, alias: str = "t") -> str:
    """ZTE / 3rd 归属过滤条件片段（不含 AND 前缀）；owner 为空时返回空串。"""
    cond = _OWNER_SQL.get((owner or "").strip().lower())
    if not cond:
        return ""
    return cond if alias == "t" else cond.replace("t.wo_no", f"{alias}.wo_no")


def _parse_adv(adv: str | None) -> dict:
    """解析高级过滤参数（JSON 对象字符串）。

    用 JSON 传是为了让「可选列集合」保持开放：新增一个站点维度过滤不需要改
    后端签名。解析失败按「无过滤」处理并记警告，不抛 500 —— 一个坏 URL 不该
    把整个看板打成错误页。
    """
    if not adv:
        return {}
    try:
        import json
        obj = json.loads(adv)
        if isinstance(obj, dict):
            return obj
    except Exception:
        logging.getLogger(__name__).warning(
            "[tt-wo-dashboard] adv 参数解析失败，已按无过滤处理", exc_info=True
        )
    return {}


def _advanced_site_filters(filters: dict | None, schema: dict) -> tuple[str, list]:
    """把 {站点列名: 精确值} 转成站点 JOIN 上的 AND 片段 + 参数。

    安全：列名**必须**命中 schema 白名单（白名单来自真实的表结构，不接受请求
    输入），值一律走 `?` 占位符精确匹配 —— 因此不存在拼接注入面。类型统一用
    `=`（与 region 过滤同构），不用 LIKE，保证概览与下钻的行数严格一致。

    返回 (" AND ms.col = ?", [v])；无有效条件时返回 ("", [])。
    """
    if not filters:
        return "", []
    allowed = set(schema.get("site_filter_fields") or [])
    parts, params = [], []
    for col, val in filters.items():
        if col not in allowed:
            continue
        if val is None or str(val).strip() == "":
            continue
        parts.append(f"ms.{col} = ?")
        params.append(str(val))
    if not parts:
        return "", []
    return " AND " + " AND ".join(parts), params


# MTTR 趋势支持的三种时间粒度（对应前端三个页签：日 / 周 / 月）。
# 顺序即前端页签顺序；overview 的聚合与 drilldown 的维度判定共用这一份常量，
# 避免「图上有日粒度、下钻不认识 day」这类两处不同步。
_MTTR_GRANULARITIES = ("day", "week", "month")


def _period_label(ts: str, gran: str) -> str:
    """按粒度给出时间桶标签。

    day   → ``YYYY-MM-DD``
    week  → ``YYYY-Www``（ISO 8601 周）
    month → ``YYYY-MM``

    三种粒度走同一个解析入口，保证「同一张单在不同粒度下落在同一个日期锚点上」——
    这是日/周/月三个页签能互相对照（周图上的点确实等于该周 7 个日点的并集）的前提。
    无法解析时返回空串，由调用方跳过该行（不猜一个桶塞进去）。
    """
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _period_label: exception swallowed", exc_info=True)
        return ""
    if gran == "day":
        return dt.strftime("%Y-%m-%d")
    if gran == "month":
        return dt.strftime("%Y-%m")
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _week_label(ts: str) -> str:
    """ISO 周标签。保留旧函数名（下钻 week 维度与既有多处调用在用），实现委托给
    :func:`_period_label`，避免周口径出现第二套算法。"""
    return _period_label(ts, "week")


def _mttr_series(bucket: dict, total_bucket: dict | None = None) -> dict:
    """把 ``{级别: {桶标签: [时长...]}}`` 转成前端要的
    ``{级别: [{period, mttr, count, total}]}``。

    三项的语义必须分清，否则前端柱/线会给出互相矛盾的故事：

    - ``total``：该桶该级别的**全部 TT 单数**（只要能定位到桶就计，不论能否算出
      MTTR）。这是前端柱状图画的量，等于「那个时段那个级别有多少单」。
    - ``count``：其中**真正计入 MTTR 均值**的单数（时长 0<dur<43200 的有效单）。
      与 ``total`` 的差额 = 缺关单时间或时长越界的单。
    - ``mttr``：``count`` 这批单的时长均值；``count`` 为 0 时是 ``None``（断线），
      **不是 0** —— 「算不出 MTTR」与「MTTR 为 0」是两回事。

    桶取两者的并集：只有总单数、没有有效时长的桶也要出点，这样柱状图不会
    凭空丢掉一个「有单但算不出时长」的时段（曲线在该点断开，量仍然可见）。

    某级别在某桶完全没有单才不出现该点；前端按 period 对齐后自然断线
    （connectNulls:false）。
    """
    total_bucket = total_bucket or {}
    out = {}
    for sv, by_period in bucket.items():
        tot_by_period = total_bucket.get(sv) or {}
        items = []
        for p in sorted(set(by_period.keys()) | set(tot_by_period.keys())):
            vals = by_period.get(p) or []
            items.append({
                "period": p,
                "mttr": round(sum(vals) / len(vals), 1) if vals else None,
                "count": len(vals),
                # 极端情况兜底：有效单存在但总单表缺该桶时，至少不小于样本数
                "total": max(tot_by_period.get(p, 0), len(vals)),
            })
        out[sv] = items
    return out


@router.get("/overview")
def tt_wo_dashboard_overview(
    time_start: str = Query(None),
    time_end: str = Query(None),
    region: str = Query(None),
    owner: str = Query(None, description="ZTE / 3rd；wo_no 非空=ZTE，否则=3rd"),
    adv: str = Query(None, description="高级过滤，JSON 对象 {站点列名: 精确值}"),
):
    """TT&WO Dashboard 综合数据（自适应数据库结构）"""
    S = _detect_schema()
    adv_filters = _parse_adv(adv)
    with get_raw_connection() as conn:

        tt_tf, tt_tp = _time_filter("t", time_start, time_end)
        wo_tf, wo_tp = _time_filter("w", time_start, time_end)

        # 区域过滤 JOIN（自适应站点表和关联字段）
        # 高级过滤复用同一个站点 JOIN（别名 ms），与 region 条件叠加。
        # 注意：只要 region 或 adv 任一非空就要 JOIN，否则高级过滤无处挂载。
        region_join = region_where = ""
        region_params = []
        if S["site_table"] and (region or adv_filters):
            sjf = S["site_join_field"]
            region_join = f"JOIN {S['site_table']} ms ON t.{sjf} = CAST(ms.{sjf} AS TEXT)"
            if region:
                region_where += " AND ms.region = ?"
                region_params.append(region)
            adv_where, adv_params = _advanced_site_filters(adv_filters, S)
            region_where += adv_where
            region_params += adv_params

        region_join_wo = region_where_wo = ""
        wo_adv_params: list = []
        if S["has_wo"] and S["site_table"] and (region or adv_filters):
            sjf = S["site_join_field"]
            region_join_wo = f"JOIN {S['site_table']} ms ON w.{sjf} = CAST(ms.{sjf} AS TEXT)"
            if region:
                region_where_wo += " AND ms.region = ?"
            adv_where_wo, wo_adv_params = _advanced_site_filters(adv_filters, S)
            region_where_wo += adv_where_wo

        # WO 侧参数顺序必须与 region_where_wo 的拼接顺序一致：区域在前、高级过滤在后
        wo_region_params = ([region] if region else []) + wo_adv_params

        # ZTE / 3rd 归属过滤（只作用于 TT，WO 表本身没有这个归属概念）
        owner_tt = _owner_where(owner, "t")
        owner_tt_sql = f" AND {owner_tt}" if owner_tt else ""

        tt_where = f"WHERE {tt_tf}{region_where}{owner_tt_sql}" if tt_tf else f"WHERE 1=1{region_where}{owner_tt_sql}"
        tt_params = tt_tp + region_params
        wo_where = f"WHERE {wo_tf}{region_where_wo}" if wo_tf else f"WHERE 1=1{region_where_wo}"
        wo_params = wo_tp + wo_region_params

        # ========== 1. TT 统计 ==========
        # 动态构建 SELECT 字段（自适应 sev_field 和 site_join_field）
        sev_select = f"t.{S['sev_field']}" if S["sev_field"] else "NULL"
        tt_rows = conn.execute(f"""
            SELECT {sev_select}, t.ticket_severity, t.sla_status, t.status, t.domain,
                   t.wo_no, t.alarm_occur_time, t.alarm_clear_time, t.{S['site_join_field']}
            FROM eflow_tt t {region_join} {tt_where}
        """, tt_params).fetchall()

        tt_total = len(tt_rows)
        wo_no_set = set()
        sev_stats = {}
        ticket_sev = {}
        sla_stats = {}
        status_stats = {}
        domain_stats = {}
        week_data = {}
        # 按 ticket_severity 分级的 MTTR 序列，三种粒度各一份：
        # {粒度: {级别: {桶标签: [时长...]}}}。
        # 口径与 week_data 完全一致（同一时间字段、同一 0<dur<43200 剔除），
        # 只是额外按 级别 × 粒度 分桶 —— 因此同一粒度下各条序列的人次之和
        # 等于该粒度全量的人次（级别为空的单除外）。
        period_data_by_sev: dict[str, dict[str, dict[str, list]]] = {
            g: {} for g in _MTTR_GRANULARITIES
        }
        # 各粒度的「级别 × 桶 → 总单数」，与能否算出 MTTR 无关（前端柱状图画的就是它）。
        # {粒度: {级别: {桶标签: 单数}}}
        total_by_sev: dict[str, dict[str, dict[str, int]]] = {
            g: {} for g in _MTTR_GRANULARITIES
        }
        site_id_set = set()

        for r in tt_rows:
            sev_val = _safe_str(r[0])
            sev_stats[sev_val] = sev_stats.get(sev_val, 0) + 1
            ticket_sev_val = _ticket_severity_key(r[1])
            if ticket_sev_val is not None:
                ticket_sev[ticket_sev_val] = ticket_sev.get(ticket_sev_val, 0) + 1
            sla_val = _stat_key(r[2], _EXCLUDED_SLA_STATUSES, join_empty=True)
            if sla_val is not None:
                sla_stats[sla_val] = sla_stats.get(sla_val, 0) + 1
            status_val = _safe_str(r[3], "")
            if status_val:
                status_stats[status_val] = status_stats.get(status_val, 0) + 1
            domain_stats[_safe_str(r[4])] = domain_stats.get(_safe_str(r[4]), 0) + 1
            if r[5]:
                wo_no_set.add(r[5])
            if r[6]:
                # 只要发生时间可解析，就先归属到 日/周/月 三个桶并计入「该级别总单数」，
                # **不论这单能否算出 MTTR**（缺关单时间、时长越界都算）。
                # 这样柱状图的「TT 单数」才等于该时段该级别的真实单量，
                # 不会漏掉「有单但算不出时长」的时段。
                ts_occ = str(r[6])
                # ticket_severity 为空/None 的单不进任何级别序列
                # （没有级别可归，硬塞进 P4 会伪造数据）
                sv = _ticket_severity_key(r[1]) or ""
                # 三种粒度的桶标签一次算好、本行复用，避免对同一行重复 strptime
                buckets = {}
                for gran in _MTTR_GRANULARITIES:
                    lbl = _period_label(ts_occ, gran)
                    if lbl:
                        buckets[gran] = lbl
                if buckets:
                    if sv:
                        for gran, lbl in buckets.items():
                            by_lbl = total_by_sev[gran].setdefault(sv, {})
                            by_lbl[lbl] = by_lbl.get(lbl, 0) + 1
                    # MTTR 均值只吃时长有效的单：0 < dur < 43200 分钟
                    if r[7]:
                        try:
                            t1 = datetime.strptime(ts_occ[:19], "%Y-%m-%d %H:%M:%S")
                            t2 = datetime.strptime(str(r[7])[:19], "%Y-%m-%d %H:%M:%S")
                            dur_min = (t2 - t1).total_seconds() / 60
                        except Exception:
                            logging.getLogger(__name__).warning("[SILENT-EXCEPT] tt_wo_dashboard_overview: exception swallowed", exc_info=True)
                            dur_min = None
                        if dur_min is not None and 0 < dur_min < 43200:
                            # 一次遍历同时落 日/周/月 三个桶（顺带维护 week_data 的全量口径），
                            # 不再对同一批行扫三遍
                            for gran, lbl in buckets.items():
                                if sv:
                                    period_data_by_sev[gran].setdefault(sv, {}).setdefault(lbl, []).append(dur_min)
                                if gran == "week":
                                    week_data.setdefault(lbl, []).append(dur_min)
            if r[8]:
                site_id_set.add(r[8])

        status_stats = dict(sorted(status_stats.items(), key=lambda x: x[1], reverse=True))
        domain_stats = dict(sorted(domain_stats.items(), key=lambda x: x[1], reverse=True))
        mttr_weekly = [
            {"week": w, "mttr": round(sum(week_data[w]) / len(week_data[w]), 1), "count": len(week_data[w])}
            for w in sorted(week_data.keys())
        ]
        # 日/周/月三份分级序列（前端页签各读一份）。
        # 每项含 total（该桶该级别总单数，柱状图）/ count（计入 MTTR 的样本数）/ mttr。
        mttr_series = {
            g: _mttr_series(period_data_by_sev[g], total_by_sev[g]) for g in _MTTR_GRANULARITIES
        }
        # 兼容字段：由同一个 week 桶改名派生，保证不会与 mttr_series["week"] 分叉
        mttr_weekly_by_severity = {
            sv: [
                {"week": it["period"], "mttr": it["mttr"], "count": it["count"], "total": it["total"]}
                for it in items
            ]
            for sv, items in mttr_series["week"].items()
        }

        # ========== 2. WO 统计（表不存在时返回空）==========
        wo_total = 0
        rc_main, rc_sub, wo_source_stats, wo_status_stats = {}, {}, {}, {}
        if S["has_wo"]:
            wo_rows = conn.execute(f"""
                SELECT w.rc_main_category, w.rc_sub_category, w.source, w.status
                FROM eflow_wo w {region_join_wo} {wo_where}
            """, wo_params).fetchall()
            wo_total = len(wo_rows)
            for r in wo_rows:
                mc = _safe_str(r[0])
                rc_main[mc] = rc_main.get(mc, 0) + 1
                sc = _safe_str(r[1])
                rc_sub[sc] = rc_sub.get(sc, 0) + 1
                src = _safe_str(r[2])
                wo_source_stats[src] = wo_source_stats.get(src, 0) + 1
                st = _safe_str(r[3], "")
                if st:
                    wo_status_stats[st] = wo_status_stats.get(st, 0) + 1
        else:
            # 无 eflow_wo 表时，从 eflow_tt 获取 root_cause
            rc_rows = conn.execute(f"""
                SELECT t.root_cause, t.sub_root_cause
                FROM eflow_tt t {region_join} {tt_where}
            """, tt_params).fetchall()
            for r in rc_rows:
                mc = _safe_str(r[0])
                rc_main[mc] = rc_main.get(mc, 0) + 1
                sc = _safe_str(r[1])
                rc_sub[sc] = rc_sub.get(sc, 0) + 1
        wo_source_stats = dict(sorted(wo_source_stats.items(), key=lambda x: x[1], reverse=True))
        wo_status_stats = dict(sorted(wo_status_stats.items(), key=lambda x: x[1], reverse=True))

        # ========== 3. 站点信息统计（自适应字段）==========
        site_stats = {}
        if site_id_set and S["site_table"]:
            placeholders = ",".join("?" * len(site_id_set))
            site_params = list(site_id_set)
            # 动态 SELECT 站点字段
            select_fields = ", ".join(S["site_stat_fields"].values())
            if select_fields:
                rows = conn.execute(f"""
                    SELECT {select_fields}
                    FROM {S['site_table']}
                    WHERE CAST({S['site_join_field']} AS TEXT) IN ({placeholders})
                """, site_params).fetchall()
                field_keys = list(S["site_stat_fields"].keys())
                for r in rows:
                    for i, key in enumerate(field_keys):
                        val = r[i]
                        if val and str(val).strip() and str(val) != 'None':
                            if key not in site_stats:
                                site_stats[key] = {}
                            site_stats[key][val] = site_stats[key].get(val, 0) + 1
                for key in site_stats:
                    site_stats[key] = dict(sorted(site_stats[key].items(), key=lambda x: x[1], reverse=True)[:15])

        # ========== 4. 汇总 ==========
        regions = []
        if S["site_table"]:
            regions = [r[0] for r in conn.execute(
                f"SELECT DISTINCT region FROM {S['site_table']} WHERE region IS NOT NULL AND region != '' ORDER BY region"
            ).fetchall()]

        # 高级过滤的可选值（与 GISMap 的 filter_options 同思路）：只对白名单列做
        # DISTINCT，每列最多 200 个候选。列名来自 schema 白名单而非请求输入。
        filter_options: dict[str, list] = {}
        if S["site_table"]:
            for col in S["site_filter_fields"]:
                try:
                    rows = conn.execute(
                        f"""SELECT DISTINCT {col} FROM {S['site_table']}
                            WHERE {col} IS NOT NULL AND {col} != '' AND {col} != 'None'
                            ORDER BY {col} LIMIT 200"""
                    ).fetchall()
                    vals = [str(r[0]) for r in rows]
                    if vals:
                        filter_options[col] = vals
                except Exception:
                    logging.getLogger(__name__).warning(
                        "[tt-wo-dashboard] 高级过滤候选列 %s 查询失败，已跳过", col, exc_info=True
                    )

        conn.close()

        # 返回统一的 tt_stats 结构（同时包含 alarm_severity 和 category）
        tt_stats = {
            "alarm_severity": sev_stats if S["has_alarm_severity"] else {},
            "category": sev_stats if not S["has_alarm_severity"] else {},
            "ticket_severity": ticket_sev,
            "sla_status": sla_stats,
            "status": status_stats,
        }

        return {
            "filters": {
                "regions": regions,
                "time_start": time_start,
                "time_end": time_end,
                "region": region,
                "owner": owner,
                "adv": adv_filters,
                # 高级过滤：filter_fields 的顺序即前端下拉的展示顺序
                "filter_fields": S["site_filter_fields"],
                "filter_options": filter_options,
            },
            "summary": {"tt_total": tt_total, "wo_total": wo_total, "wo_no_count": len(wo_no_set)},
            "tt_stats": tt_stats,
            "mttr_weekly": mttr_weekly,
            "mttr_weekly_by_severity": mttr_weekly_by_severity,
            # 日/周/月三份分级 MTTR 序列（前端三个页签各读一份）。
            # 与 mttr_weekly_by_severity 同源（后者是本字段 week 的改名视图）。
            "mttr_series": mttr_series,
            "mttr_granularities": list(_MTTR_GRANULARITIES),
            "domain_stats": domain_stats,
            "root_cause": {"main": rc_main, "sub": rc_sub},
            "wo_stats": {"source": wo_source_stats, "status": wo_status_stats},
            "site_stats": site_stats,
        }


# ========== 下钻查询 ==========

# 维度 → (表类型, SQL条件片段, 字段名)
def _get_dimension_map():
    """根据数据库结构动态构建维度映射"""
    S = _detect_schema()
    dim = {
        "ticket_severity": ("tt", "t.ticket_severity = ?", "ticket_severity"),
        "sla_status":      ("tt", "t.sla_status = ?",      "sla_status"),
        "status":          ("tt", "t.status = ?",           "status"),
        "domain":          ("tt", "t.domain = ?",           "domain"),
        "all_tt":          ("tt", None, None),
    }
    if S["sev_field"]:
        sev_dim = S["sev_field"]
        dim[sev_dim] = ("tt", f"t.{sev_dim} = ?", sev_dim)
    if S["has_wo"]:
        dim.update({
            "rc_main":   ("wo", "w.rc_main_category = ?", "rc_main_category"),
            "rc_sub":    ("wo", "w.rc_sub_category = ?",  "rc_sub_category"),
            "wo_source": ("wo", "w.source = ?",           "source"),
            "wo_status": ("wo", "w.status = ?",           "status"),
            "all_wo":    ("wo", None, None),
        })
    else:
        # 无eflow_wo时，root_cause从eflow_tt获取
        if "root_cause" in S["tt_cols"]:
            dim["rc_main"] = ("tt", "t.root_cause = ?", "root_cause")
        if "sub_root_cause" in S["tt_cols"]:
            dim["rc_sub"] = ("tt", "t.sub_root_cause = ?", "sub_root_cause")
    for key, col in S["site_stat_fields"].items():
        dim[key] = ("site", col, key)
    return dim


def _build_tt_fields():
    """动态构建 TT 明细字段"""
    S = _detect_schema()
    # 优先使用 eflow_tt.tt_no (真实 TT 单号)，而非 ticket_no (可能是 WO 回退值)
    tt_no_field = "t.tt_no" if "tt_no" in S["tt_cols"] else "t.ticket_no"
    fields = ["t.title", tt_no_field, "t.wo_no", f"t.{S['site_join_field']}", "t.status"]
    if S["creator_field"]:
        fields.append(f"t.{S['creator_field']}")
    fields += ["t.ticket_severity"]
    if S["sev_field"]:
        fields.append(f"t.{S['sev_field']}")
    fields += ["t.sla_status", "t.alarm_occur_time", "t.alarm_clear_time", "t.domain", "t.root_cause", "t.sub_root_cause"]
    return ", ".join(fields)


@router.get("/drilldown")
def tt_wo_drilldown(
    type: str = Query("tt"),
    time_start: str = Query(None),
    time_end: str = Query(None),
    region: str = Query(None),
    owner: str = Query(None, description="ZTE / 3rd；与 overview 同一口径"),
    adv: str = Query(None, description="高级过滤，JSON 对象 {站点列名: 精确值}；与 overview 同一口径"),
    dimension: str = Query("all_tt"),
    value: str = Query(None),
):
    """TT/WO 明细下钻查询（自适应数据库结构）

    过滤口径必须与 /overview 逐条一致（同一时间字段、同一站点 JOIN、同一 owner
    判定、同一高级过滤），否则下钻行数会与看板上的数字对不上。
    """
    S = _detect_schema()
    adv_filters = _parse_adv(adv)
    DIMENSION_MAP = _get_dimension_map()
    with get_raw_connection() as conn:

        tt_tf, tt_tp = _time_filter("t", time_start, time_end)
        wo_tf, wo_tp = _time_filter("w", time_start, time_end)

        sjf = S["site_join_field"]
        region_join_tt = region_where_tt = ""
        region_params_tt: list = []
        if S["site_table"] and (region or adv_filters):
            region_join_tt = f"JOIN {S['site_table']} ms ON t.{sjf} = CAST(ms.{sjf} AS TEXT)"
            if region:
                region_where_tt += " AND ms.region = ?"
                region_params_tt.append(region)
            adv_where_tt, adv_params_tt = _advanced_site_filters(adv_filters, S)
            region_where_tt += adv_where_tt
            region_params_tt += adv_params_tt

        region_join_wo = region_where_wo = ""
        region_params_wo: list = []
        if S["has_wo"] and S["site_table"] and (region or adv_filters):
            region_join_wo = f"JOIN {S['site_table']} ms ON w.{sjf} = CAST(ms.{sjf} AS TEXT)"
            if region:
                region_where_wo += " AND ms.region = ?"
                region_params_wo.append(region)
            adv_where_wo, adv_params_wo = _advanced_site_filters(adv_filters, S)
            region_where_wo += adv_where_wo
            region_params_wo += adv_params_wo

        # ZTE / 3rd 归属过滤：与 overview 共用同一函数，保证口径一致
        owner_tt = _owner_where(owner, "t")
        tt_where_owner = f" AND {owner_tt}" if owner_tt else ""

        dim_info = DIMENSION_MAP.get(dimension, ("tt", None, None))
        dim_type = dim_info[0]

        if dim_type == "wo" and not S["has_wo"]:
            conn.close()
            return {"title": f"WO - {dimension}", "count": 0, "data": []}

        TT_FIELDS = _build_tt_fields()

        # week 维度
        # 时间粒度维度（day / week / month）：与 MTTR 趋势的三个页签一一对应。
        # 必须与 overview 的桶口径同源（都走 _period_label），否则点日图上的点
        # 会下钻出与该点对不上的行数——这是「下钻 WHERE 必须与概览一致」的硬要求。
        if dimension in _MTTR_GRANULARITIES and value:
            tt_where = f"WHERE {tt_tf}{region_where_tt}{tt_where_owner}" if tt_tf else f"WHERE 1=1{region_where_tt}{tt_where_owner}"
            tt_params = tt_tp + region_params_tt
            rows = conn.execute(f"""
                SELECT {TT_FIELDS} FROM eflow_tt t {region_join_tt}
                {tt_where} AND t.alarm_occur_time IS NOT NULL
                ORDER BY t.alarm_occur_time DESC
            """, tt_params).fetchall()
            cols = [c.strip().split('.')[-1] for c in TT_FIELDS.split(",")]
            data = [
                dict(zip(cols, row)) for row in rows
                if _period_label(str(dict(zip(cols, row)).get("alarm_occur_time") or ""), dimension) == value
            ]
            conn.close()
            return {"title": f"TT - {dimension.title()}: {value}", "count": len(data), "data": data}

        # 站点维度
        if dim_type == "site" and value:
            site_field = dim_info[1]
            if S["site_table"]:
                site_ids = conn.execute(f"""
                    SELECT {sjf} FROM {S['site_table']}
                    WHERE {site_field} = ? AND {sjf} IS NOT NULL
                """, [value]).fetchall()
                id_list = [str(s[0]) for s in site_ids]
                if not id_list:
                    conn.close()
                    return {"title": f"TT - {dimension}: {value}", "count": 0, "data": []}
                placeholders = ",".join("?" * len(id_list))
                tt_where = f"WHERE {tt_tf}{region_where_tt}{tt_where_owner}" if tt_tf else f"WHERE 1=1{region_where_tt}{tt_where_owner}"
                rows = conn.execute(f"""
                    SELECT {TT_FIELDS} FROM eflow_tt t {region_join_tt}
                    {tt_where} AND t.{sjf} IN ({placeholders})
                    ORDER BY t.alarm_occur_time DESC
                """, tt_tp + region_params_tt + id_list).fetchall()
                cols = [c.strip().split('.')[-1] for c in TT_FIELDS.split(",")]
                data = [dict(zip(cols, row)) for row in rows]
                conn.close()
                return {"title": f"TT - {dimension}: {value}", "count": len(data), "data": data}

        # 通用 TT 维度
        if dim_type == "tt":
            tt_where = f"WHERE {tt_tf}{region_where_tt}{tt_where_owner}" if tt_tf else f"WHERE 1=1{region_where_tt}{tt_where_owner}"
            tt_params = tt_tp + region_params_tt
            dim_cond = dim_info[1]
            extra_params: list = []
            if dim_cond and value:
                field_name = dim_info[2]
                # 2026-09-29：ticket_severity / sla_status 的 Unknown 已从概览统计中剔除
                # （见 _EXCLUDED_TICKET_SEVERITIES / _EXCLUDED_SLA_STATUSES），下钻必须
                # 同步返回空集，否则「卡片上已经没有这张卡、却还能下钻出 N 行」
                # —— 违反「下钻 WHERE 必须与概览一致」的硬要求。
                if field_name in _UNKNOWN_EXCLUDED_DIMENSIONS and _is_excluded_ticket_severity(value):
                    conn.close()
                    return {"title": f"TT - {dimension}: {value}", "count": 0, "data": []}
                if value == "Unknown":
                    tt_where += f" AND (t.{field_name} IS NULL OR t.{field_name} = '' OR t.{field_name} = 'None')"
                else:
                    tt_where += f" AND {dim_cond}"
                    extra_params = [value]
            rows = conn.execute(f"""
                SELECT {TT_FIELDS} FROM eflow_tt t {region_join_tt}
                {tt_where} ORDER BY t.alarm_occur_time DESC
            """, tt_params + extra_params).fetchall()
            cols = [c.strip().split('.')[-1] for c in TT_FIELDS.split(",")]
            data = [dict(zip(cols, row)) for row in rows]
            conn.close()
            return {"title": f"TT - {dimension}{': ' + value if value else ''}", "count": len(data), "data": data}

        # WO 维度
        if dim_type == "wo" and S["has_wo"]:
            WO_FIELDS = "w.wo_no, w.tt_no, w.title, w.status, w.creator, w.created_time, w.alarm_occur_time, w.alarm_clear_time, w.source, w.rc_main_category, w.rc_sub_category, w.ticket_severity, w.alarm_severity"
            wo_where = f"WHERE {wo_tf}{region_where_wo}" if wo_tf else f"WHERE 1=1{region_where_wo}"
            wo_params = wo_tp + region_params_wo
            dim_cond = dim_info[1]
            extra_params = []
            if dim_cond and value:
                field_name = dim_info[2]
                # 与 TT 侧同规则：已剔除 Unknown 的维度不该再下钻出行
                if field_name in _UNKNOWN_EXCLUDED_DIMENSIONS and _is_excluded_ticket_severity(value):
                    conn.close()
                    return {"title": f"WO - {dimension}: {value}", "count": 0, "data": []}
                if value == "Unknown":
                    wo_where += f" AND (w.{field_name} IS NULL OR w.{field_name} = '' OR w.{field_name} = 'None')"
                else:
                    wo_where += f" AND {dim_cond}"
                    extra_params = [value]
            rows = conn.execute(f"""
                SELECT {WO_FIELDS} FROM eflow_wo w {region_join_wo}
                {wo_where} ORDER BY w.alarm_occur_time DESC
            """, wo_params + extra_params).fetchall()
            cols = [c.strip().split('.')[-1] for c in WO_FIELDS.split(",")]
            data = [dict(zip(cols, row)) for row in rows]
            conn.close()
            return {"title": f"WO - {dimension}{': ' + value if value else ''}", "count": len(data), "data": data}

        conn.close()
        return {"title": "Unknown", "count": 0, "data": []}


# ========== 根因一致性审计（Root Cause Audit）==========
# 背景：eflow_tt.root_cause / sub_root_cause / root_cause_description 为 NOC 人工填报，
# 存在系统性误填（详见复盘报告 §4）。本模块用告警链路（history_alarm）作为权威依据，
# 与人工填报做一致性比对，供 TT 详情页"系统判定根因 vs NOC 填写根因"对比展示。

# 告警码 → 系统语义（来自 history_alarm 实测权威映射，2026-09 校准）
ALARM_CODE_SEMANTICS = {
    "99933": {"name": "SITE DOWN DUE TO POWER OFF", "reason_type": "TRM"},
    "9995":  {"name": "MW LINK DOWN",               "reason_type": "TRM"},
    "9920":  {"name": "Complete site down (CSD)",   "reason_type": "TRM"},
    "9910":  {"name": "Partial site down (PSD)",    "reason_type": "TRM"},
    "9970":  {"name": "4G SITE DOWN",               "reason_type": "TRM"},
    "9980":  {"name": "2G SITE DOWN",               "reason_type": "TRM"},
    "9990":  {"name": "3G SITE DOWN",               "reason_type": "TRM"},
    "9981":  {"name": "2G CELL DOWN",               "reason_type": "OTHER"},
    "9991":  {"name": "3G CELL DOWN",               "reason_type": "OTHER"},
    "9971":  {"name": "4G CELL DOWN",               "reason_type": "OTHER"},
    "4758":  {"name": "Fiber Break",                "reason_type": None},
}

# 语义关键词：用于从 codename 推断真实故障域
_POWER_HINTS = ("POWER", "GENSET", "BATTERY", "FUEL", "ENERGY", "GRID", "MAINS", "COMMERCIAL")
_TRM_HINTS = ("MW LINK", "MICROWAVE", "FIBER", "LINK DOWN", "TRANSMISSION", "MW ")

# NOC 填报的根因归属（用于一致性判定）
_NOC_POWER_FAMILY = {"POWER"}

# 真实故障域 → 建议追溯方向
_SUGGESTED_ACTION = {
    "TRM": "建议追溯该站上联传输链路（MW 微波 / PTN / 光纤），核查是否为链路反复中断",
    "POWER": "建议核查站点供电（市电 / 油机 / 电池），确认是否为真实断电",
    "OTHER": "建议结合告警明细进一步定位（小区级 / 板件级）",
}


def _norm_alarm_id(val) -> str:
    """归一化 alarm_id：eflow_tt.alarm_id 可能存成 '1764213380772.0'（浮点串）"""
    if val is None:
        return ""
    s = str(val).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _infer_fault_domain(codename: str, reason_type: str, alarmcode: str) -> tuple[str, str]:
    """从告警链路推断真实故障域。

    返回 (fault_domain, basis)：basis 说明判定依据，便于前端展示可解释性。
    """
    cn = (codename or "").upper()

    # 1) codename 明确含供电语义 → POWER
    if any(h in cn for h in _POWER_HINTS):
        return "POWER", f"codename='{codename}' 含供电语义"

    # 2) codename 含传输语义 → TRM
    if any(h in cn for h in _TRM_HINTS):
        return "TRM", f"codename='{codename}' 含传输语义"

    # 3) 回落：用 reason_type 兜底
    if reason_type:
        return reason_type, f"reason_type='{reason_type}'"

    # 4) 再回落：查静态语义表
    sem = ALARM_CODE_SEMANTICS.get(_norm_alarm_id(alarmcode))
    if sem and sem.get("reason_type"):
        return sem["reason_type"], f"alarmcode={alarmcode} 静态语义表"
    if sem:
        return "UNKNOWN", f"alarmcode={alarmcode} 语义未知（{sem.get('name')}）"

    return "UNKNOWN", "无可用告警链路信息"


def _fetch_alarm_chain(conn, tt_no: str, alarm_id, site_id,
                       alarm_code=None, tt_reason_type=None) -> tuple[list, str]:
    """三级策略取告警链路，逐级降权，越靠前越可信。

    返回 (rows, linkage)：
    - exact                  : history_alarm.tt_id = tt_no（1 单对 1 告警，最强）
    - site_fallback          : 同站点且**告警码严格一致**
    - site_reason_fallback   : 同站点且 **reason_type 一致**（同一故障域，如 TRM）
    - site_fallback_unrelated: 同站点有告警但与本单不同域 → 属其它单子，丢弃
    - none                   : 无任何可用告警
    """
    cols = "alarmcode, codename, reason_type, alarm_source, restypename, alarmkey, site_name"

    # 一级：tt_id 精确
    try:
        rows = conn.execute(
            f"SELECT {cols} FROM history_alarm WHERE tt_id = ? LIMIT 20", (tt_no,)
        ).fetchall()
        if rows:
            return rows, "exact"
    except Exception:
        logging.getLogger(__name__).warning("[root-cause-audit] tt_id 精确关联失败", exc_info=True)

    # 二级：alarm_id（归一化后）
    nid = _norm_alarm_id(alarm_id)
    if nid:
        try:
            rows = conn.execute(
                f"SELECT {cols} FROM history_alarm WHERE CAST(id AS TEXT) = ? LIMIT 20", (nid,)
            ).fetchall()
            if rows:
                return rows, "exact"
        except Exception:
            logging.getLogger(__name__).warning("[root-cause-audit] alarm_id 关联失败", exc_info=True)

    # 三级：站点级降级 —— 按"故障域族"匹配（比严格码匹配更符合业务语义）
    # 实测：同站点断站类告警码（9970/9980/9990/9910/9920/9995/99933）的 reason_type
    # 全部为 TRM，属同一故障域族；严格码匹配会漏掉"本单码未入库但同族告警在库"的情况。
    if site_id is not None and str(site_id).strip() not in ("", "None"):
        try:
            rows = conn.execute(
                f"""SELECT {cols} FROM history_alarm WHERE CAST(site_id AS TEXT) = ?
                    ORDER BY alarmraisedtime DESC LIMIT 50""",
                (str(site_id),),
            ).fetchall()
            if rows:
                tt_code = _norm_alarm_id(alarm_code)
                # 1) 严格码匹配（最强）
                if tt_code:
                    matched = [r for r in rows
                               if _norm_alarm_id(dict(r).get("alarmcode")) == tt_code]
                    if matched:
                        return matched, "site_fallback"

                # 2) reason_type 匹配（同故障域，次强）
                # 实测依据：断站类码(9970/9980/9990/9910/9920/9995/99933)的 reason_type
                # 统一为 TRM，属同一故障域；本单码未入库但同域告警在库时仍可佐证。
                tt_reason = (tt_reason_type or "").strip().upper()
                if not tt_reason and tt_code:
                    sem = ALARM_CODE_SEMANTICS.get(tt_code)
                    tt_reason = ((sem or {}).get("reason_type") or "").strip().upper()
                if tt_reason:
                    same_reason = [r for r in rows
                                   if (dict(r).get("reason_type") or "").strip().upper() == tt_reason]
                    if same_reason:
                        return same_reason, "site_reason_fallback"

                # 同站点有告警但不同域 → 属其它单子，不可采纳
                return [], "site_fallback_unrelated"
        except Exception:
            logging.getLogger(__name__).warning("[root-cause-audit] site_id 降级关联失败", exc_info=True)

    return [], "none"


@router.get("/root-cause-audit/{tt_no}")
def tt_root_cause_audit(tt_no: str):
    """单张 TT 的「系统判定根因 vs NOC 填写根因」一致性审计。

    权威依据：history_alarm（告警链路）> eflow_tt.alarm_reason_type > NOC 人工填报。
    对应复盘报告 §6.4 最小可行版本。
    """
    S = _detect_schema()
    with get_raw_connection() as conn:
        row = conn.execute(
            """SELECT tt_no, site_id, site_name, alarm_code, alarm_id, ticket_severity,
                      alarm_severity, status, root_cause, sub_root_cause, root_cause_description,
                      alarm_reason_type, last_processer, last_processer_group,
                      last_modified_time, fo_process_detail, fo_accept_detail, create_detail
               FROM eflow_tt WHERE tt_no = ?""",
            (tt_no,),
        ).fetchone()

        if not row:
            conn.close()
            return {"tt_no": tt_no, "found": False, "message": "未找到该工单"}

        t = dict(row)
        alarm_rows, linkage = _fetch_alarm_chain(
            conn, tt_no, t.get("alarm_id"), t.get("site_id"),
            t.get("alarm_code"), t.get("alarm_reason_type"),
        )
        conn.close()

    # ---- NOC 人工填报层 ----
    filed_by = ""
    filed_at = ""
    detail = t.get("fo_process_detail") or ""
    if detail:
        import re
        m = re.search(r"Operator:([^(]+)\(([^)]*)\)", str(detail))
        if m:
            filed_by = f"{m.group(1).strip()}({m.group(2).strip()})"
        m2 = re.search(r"Operation Time:([0-9\-: ]+)", str(detail))
        if m2:
            filed_at = m2.group(1).strip()

    noc_filled = {
        "root_cause": t.get("root_cause"),
        "sub_root_cause": t.get("sub_root_cause"),
        "root_cause_description": t.get("root_cause_description"),
        "filed_by": filed_by or t.get("last_processer"),
        "filed_at": filed_at or t.get("last_modified_time"),
    }

    # ---- 系统判定层（取告警链路中语义最明确的一条）----
    system_judged = None
    if alarm_rows:
        # 优先选 codename 能推断出故障域的记录
        best, best_domain, best_basis = None, "UNKNOWN", ""
        for r in alarm_rows:
            d = dict(r)
            dom, basis = _infer_fault_domain(
                d.get("codename"), d.get("reason_type"), d.get("alarmcode")
            )
            if dom != "UNKNOWN":
                best, best_domain, best_basis = d, dom, basis
                break
            if best is None:
                best, best_domain, best_basis = d, dom, basis

        codes = [str(dict(r).get("alarmcode")) for r in alarm_rows]
        names = [str(dict(r).get("codename")) for r in alarm_rows]
        system_judged = {
            "fault_domain": best_domain,
            "basis": best_basis,
            "alarmcode": best.get("alarmcode") if best else None,
            "codename": best.get("codename") if best else None,
            "reason_type": best.get("reason_type") if best else None,
            "alarm_source": best.get("alarm_source") if best else None,
            "restypename": best.get("restypename") if best else None,
            "alarmkey": best.get("alarmkey") if best else None,
            "linkage": linkage,
            "alarm_count": len(alarm_rows),
            "distinct_codes": sorted(set(codes)),
            "distinct_names": sorted(set(names)),
            "history_match": f"站点历史 {len(alarm_rows)} 条告警，指纹 {sorted(set(names))[:3]}",
        }
    elif t.get("alarm_reason_type"):
        # 无告警链路时，退到 TT 表系统字段（confidence 会相应降级）
        system_judged = {
            "fault_domain": t.get("alarm_reason_type"),
            "basis": "eflow_tt.alarm_reason_type（系统字段，无告警链路佐证）",
            "alarmcode": t.get("alarm_code"),
            "codename": None,
            "reason_type": t.get("alarm_reason_type"),
            "linkage": linkage,
            "alarm_count": 0,
        }

    # ---- 一致性判定 ----
    consistency = None
    mismatch_type = ""
    confidence = "low"
    note = ""

    noc_rc = (t.get("root_cause") or "").strip().upper()
    if system_judged and noc_rc:
        sys_domain = system_judged["fault_domain"]
        if sys_domain in ("POWER", "TRM", "OTHER"):
            confidence = ("high" if linkage == "exact"
                          else "medium" if linkage in ("site_fallback", "site_reason_fallback")
                          else "low")

            if noc_rc in _NOC_POWER_FAMILY and sys_domain == "TRM":
                consistency = False
                mismatch_type = "POWER<-TRM"
                note = ("NOC 填报 POWER（供电类），但告警链路显示为传输类（TRM）故障；"
                        "该站告警指纹未含供电语义，疑似误填。")
            elif noc_rc in _NOC_POWER_FAMILY and sys_domain == "POWER":
                consistency = True
                note = "NOC 填报 POWER，告警链路同样指向供电类，一致。"
            elif noc_rc in ("MW", "FIBER", "RAN", "IP-DWDM NETWORK") and sys_domain == "TRM":
                consistency = True
                note = "NOC 填报传输类，与告警链路一致。"
            elif sys_domain == "POWER" and noc_rc not in _NOC_POWER_FAMILY:
                consistency = False
                mismatch_type = f"{noc_rc}<-POWER"
                note = "告警链路指向供电类，但 NOC 未填报 POWER。"
            else:
                consistency = None
                note = f"告警链路判定为 {sys_domain}，NOC 填报 {noc_rc}，规则未覆盖该组合，需人工复核。"
    elif not noc_rc:
        consistency = None
        note = "NOC 未填报根因（root_cause 为空），无法比对。"
    elif linkage == "site_fallback_unrelated":
        consistency = None
        note = ("该站 48h 窗口内有其它单子的告警，但告警码与本单不匹配，"
                "不能作为本单判据（告警可能已滚出窗口或本单告警未被采集）。")
    else:
        consistency = None
        note = "缺少可用告警链路，无法比对（告警可能已滚出 48h 窗口）。"

    return {
        "tt_no": tt_no,
        "found": True,
        "site": {"site_id": t.get("site_id"), "site_name": t.get("site_name")},
        "ticket": {
            "ticket_severity": t.get("ticket_severity"),
            "alarm_severity": t.get("alarm_severity"),
            "alarm_code": t.get("alarm_code"),
            "status": t.get("status"),
        },
        "noc_filled": noc_filled,
        "system_judged": system_judged,
        "consistency": consistency,
        "mismatch_type": mismatch_type,
        "confidence": confidence,
        "note": note,
        "suggested_action": _SUGGESTED_ACTION.get(
            (system_judged or {}).get("fault_domain"), "无建议"
        ),
    }


@router.get("/root-cause-audit-summary")
def tt_root_cause_audit_summary(
    limit: int = Query(50, ge=1, le=500),
    only_mismatch: bool = Query(True),
):
    """批量根因一致性审计摘要（供看板列表 / 月度报告使用）。

    扫描 root_cause 非空的近期 TT，逐条比对告警链路，返回不一致清单。
    注意：history_alarm 为 48h 滚动窗口，故只对窗口内有告警的单有效。
    """
    with get_raw_connection() as conn:
        rows = conn.execute(
            """SELECT tt_no, site_id, site_name, alarm_code, alarm_id, ticket_severity,
                      root_cause, sub_root_cause, alarm_reason_type, last_processer,
                      last_modified_time
               FROM eflow_tt
               WHERE root_cause IS NOT NULL AND root_cause <> ''
               ORDER BY last_modified_time DESC LIMIT ?""",
            (limit,),
        ).fetchall()

        items, checked, mismatch_cnt, no_alarm, unrelated = [], 0, 0, 0, 0
        for r in rows:
            t = dict(r)
            alarm_rows, linkage = _fetch_alarm_chain(
                conn, t["tt_no"], t.get("alarm_id"), t.get("site_id"),
                t.get("alarm_code"), t.get("alarm_reason_type"),
            )
            if not alarm_rows:
                if linkage == "site_fallback_unrelated":
                    unrelated += 1
                else:
                    no_alarm += 1
                continue

            checked += 1
            best, best_domain, best_basis = None, "UNKNOWN", ""
            for a in alarm_rows:
                d = dict(a)
                dom, basis = _infer_fault_domain(
                    d.get("codename"), d.get("reason_type"), d.get("alarmcode")
                )
                if best is None or (dom != "UNKNOWN" and best_domain == "UNKNOWN"):
                    best, best_domain, best_basis = d, dom, basis
                if dom != "UNKNOWN":
                    break

            noc_rc = (t.get("root_cause") or "").strip().upper()
            is_mismatch = noc_rc in _NOC_POWER_FAMILY and best_domain == "TRM"
            if is_mismatch:
                mismatch_cnt += 1
                items.append({
                    "tt_no": t["tt_no"],
                    "site_name": t.get("site_name"),
                    "site_id": t.get("site_id"),
                    "ticket_severity": t.get("ticket_severity"),
                    "noc_root_cause": t.get("root_cause"),
                    "noc_sub_root_cause": t.get("sub_root_cause"),
                    "system_codename": best.get("codename") if best else None,
                    "system_alarmcode": best.get("alarmcode") if best else None,
                    "system_reason_type": best.get("reason_type") if best else None,
                    "system_fault_domain": best_domain,
                    "basis": best_basis,
                    "linkage": linkage,
                    "last_processer": t.get("last_processer"),
                    "last_modified_time": t.get("last_modified_time"),
                    "mismatch_type": "POWER<-TRM",
                })

        conn.close()

    if only_mismatch:
        return {
            "scanned": len(rows),
            "checked": checked,
            "no_alarm_data": no_alarm,
            "site_unrelated_skipped": unrelated,
            "mismatch_count": mismatch_cnt,
            "mismatch_rate_pct": round(100.0 * mismatch_cnt / checked, 1) if checked else 0.0,
            "items": items,
        }

    return {
        "scanned": len(rows),
        "checked": checked,
        "no_alarm_data": no_alarm,
        "site_unrelated_skipped": unrelated,
        "mismatch_count": mismatch_cnt,
        "mismatch_rate_pct": round(100.0 * mismatch_cnt / checked, 1) if checked else 0.0,
        "items": items,
    }

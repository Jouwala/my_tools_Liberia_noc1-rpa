# -*- coding: utf-8 -*-
"""FME 站点可用率与工单看板数据服务。

=========================== 数据源与口径（务必与页面说明一致）===========================

站点主数据
    db/app.db -> master_site_db（805 站）
    使用字段：site_id, site_name, region, province_county, network_type,
              fme_name, supervisor, vip_site, site_type

可用率（站点级天粒度，四种制式各一份）
    G   (2G) : 远端 db.sqlite3 -> 2G_Main_Kpi_Site_Daily
               站点名 "SITE Name"
               指标列 "306004:TCH in service rate(%)"      （UME 原值，0~1 比率）
    U   (3G) : 远端 db.sqlite3 -> 3G_Main_Kpi_Site_Daily
               站点名 "NodeB Name"
               指标列 "300857:Cell Validity Rate(%)"        （UME 原值，0~1 比率）
    L   (4G) : 远端 db.sqlite3 -> 4G_Main_Kpi_Site_Daily
               站点名 "eNodeB Name"
               指标列 "1638004469345:[FDD]Cell Availability[SDR_ITBBU]"
                                                            （UME 原值，0~1 比率）
    Tdd (TDD): 本地 data/ran_kpi_avalability_1day.sqlite3
               -> Daily_KPI_RPA_CELL_AVAIL_TDD
               站点名 "eNodeB Name"
               指标：AVG(CAST("Cell Service Time(s)" AS REAL)) / 86400
               （远端站点级日表没有 TDD 可用性字段，故 Tdd 由小区服务时长折算；
                 一个站点一天有多个 TDD 小区，取算术平均）

    说明：G/U/L 直接使用 UME 官方站点级可用性字段，不做二次折算；仅 Tdd 为派生口径。

工单
    db/app.db -> eflow_tt（TT 单）
    归属时间：created_time 落在统计月内 [月首 00:00:00, 次月首 00:00:00)
    未闭环：status != 'Closed'（该表只有 Closed 是终态，其余均为各类 Waiting）
    关联站点：优先 site_id 字符串精确匹配，其次 site_name 规范化匹配
              （规范化 = 去首尾空白 + 连续空白折叠 + 转小写）

聚合口径
    日值     ：UME 站点级原值（Tdd 为小区均值）
    周均     ：该自然周（周一起算）内、落在本月的、有值日期的算术平均
    月均     ：本月内有值日期的算术平均
    未达标天 ：日值 < threshold 的天数（threshold 默认 0.9965 = 99.65%）
=====================================================================================
"""
from __future__ import annotations

import calendar
import json
import logging
import re
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.database import get_raw_connection
from backend.services.remote_db_reader import get_remote_reader

logger = logging.getLogger("site_availability")

REMOTE_DB = "db.sqlite3"
LOCAL_AVAIL_DB = Path(r"d:\01_RPA\Task\my_app\data\ran_kpi_avalability_1day.sqlite3")

TECHS = ["G", "U", "L", "Tdd"]

# tech -> (远端表名, 站点名列, 可用率列)
REMOTE_SPEC: Dict[str, Tuple[str, str, str]] = {
    "G": ("2G_Main_Kpi_Site_Daily", "SITE Name", "306004:TCH in service rate(%)"),
    "U": ("3G_Main_Kpi_Site_Daily", "NodeB Name", "300857:Cell Validity Rate(%)"),
    "L": ("4G_Main_Kpi_Site_Daily", "eNodeB Name",
          "1638004469345:[FDD]Cell Availability[SDR_ITBBU]"),
}

# 本地 TDD（小区级）
LOCAL_TDD_TABLE = "Daily_KPI_RPA_CELL_AVAIL_TDD"
LOCAL_TDD_SITE_COL = "eNodeB Name"
LOCAL_TDD_VALUE_COL = "Cell Service Time(s)"

DEFAULT_THRESHOLD = 0.9965  # 99.65%

# ============ 统一缓存（复用项目 cache 服务）============
try:
    from backend.services.cache import get_cache

    _cache = get_cache()
except Exception:  # pragma: no cover - 缓存服务不可用时退化为无缓存
    _cache = None

_CACHE_TTL = 300


def _cache_get(key: str):
    if _cache is None:
        return None
    try:
        return _cache.get(key)
    except Exception:
        return None


def _cache_set(key: str, value):
    if _cache is None:
        return value
    try:
        _cache.set(key, value, _CACHE_TTL)
    except Exception:
        pass
    return value


# ============ 工具 ============
def norm_name(s: Any) -> str:
    """站点名规范化：去首尾空白、折叠连续空白、转小写。用于跨源关联。"""
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _to_float(v: Any) -> Optional[float]:
    """把远端/本地的原始值转成 0~1 的比率；无法解析返回 None。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    # 极端异常值直接判无效，避免污染均值
    if f < 0:
        return None
    return f


def month_bounds(month: str) -> Tuple[str, str]:
    """'YYYY-MM' -> ('YYYY-MM-01 00:00:00', 'YYYY-MM-<末日> 00:00:00' 的次日首刻)。

    返回 (start_inclusive, end_exclusive_str_next_month_first_day)
    """
    y, m = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(y, m)[1]
    return f"{month}-01 00:00:00", f"{month}-{last:02d} 23:59:59"


def month_days(month: str) -> List[str]:
    """返回该月所有日期（YYYY-MM-DD）。"""
    y, m = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(y, m)[1]
    return [f"{month}-{d:02d}" for d in range(1, last + 1)]


def month_weeks(month: str) -> List[Dict[str, Any]]:
    """把当月按自然周（周一起算）切分，返回 [{key,label,days:[...]}]。

    首尾周会被裁剪到本月范围内（例如 9/1 是周二，则 W1 只有 9/1~9/6）。
    """
    days = month_days(month)
    buckets: List[Dict[str, Any]] = []
    cur_key: Optional[str] = None
    for d in days:
        dt = datetime.strptime(d, "%Y-%m-%d").date()
        iso = dt.isocalendar()
        key = f"{iso[0]}-W{iso[1]:02d}"
        if cur_key != key:
            buckets.append({"key": key, "days": [], "start": d, "end": d})
            cur_key = key
        buckets[-1]["days"].append(d)
        buckets[-1]["end"] = d
    out = []
    for i, b in enumerate(buckets, 1):
        out.append({
            "key": b["key"],
            "label": f"W{i}",
            "range": f"{b['start'][5:]}~{b['end'][5:]}",
            "days": b["days"],
        })
    return out


# ============ 数据加载 ============
def _load_remote_tech(tech: str, month: str) -> Dict[Tuple[str, str], float]:
    """从远端读某制式整月站点级可用率。返回 {(norm_site, 'YYYY-MM-DD'): ratio}。"""
    table, site_col, val_col = REMOTE_SPEC[tech]
    start, end = month_bounds(month)
    where = f"\"Begin Time\" >= '{start}' AND \"Begin Time\" <= '{end}'"
    reader = get_remote_reader()
    try:
        res = reader.read_table(
            db=REMOTE_DB, table=table, limit=400000,
            columns=["Begin Time", site_col, val_col],
            where=where,
        )
    except Exception as e:
        logger.warning("[site-avail] 远端读取失败 tech=%s month=%s: %s", tech, month, e)
        return {}
    if not res.get("success", True):
        logger.warning("[site-avail] 远端返回失败 tech=%s: %s", tech, str(res)[:200])
        return {}
    cols = res.get("columns") or []
    rows = res.get("rows") or []
    try:
        i_bt = cols.index("Begin Time")
        i_nm = cols.index(site_col)
        i_v = cols.index(val_col)
    except ValueError as e:
        logger.warning("[site-avail] 远端列缺失 tech=%s: %s", tech, e)
        return {}
    out: Dict[Tuple[str, str], float] = {}
    for r in rows:
        if not r or len(r) <= max(i_bt, i_nm, i_v):
            continue
        nm = norm_name(r[i_nm])
        bt = str(r[i_bt] or "")[:10]
        v = _to_float(r[i_v])
        if not nm or not bt or v is None:
            continue
        k = (nm, bt)
        # 同站点同天多行时取均值（UME 侧理论上唯一，此处仅防御）
        if k in out:
            out[k] = (out[k] + v) / 2.0
        else:
            out[k] = v
    return out


def _load_local_tdd(month: str) -> Dict[Tuple[str, str], float]:
    """从本地小区级 TDD 表聚合出站点级日可用率：AVG(Service Time)/86400。"""
    start, end = month_bounds(month)
    if not LOCAL_AVAIL_DB.is_file():
        logger.warning("[site-avail] 本地可用性库不存在: %s", LOCAL_AVAIL_DB)
        return {}
    sql = f'''
        SELECT "{LOCAL_TDD_SITE_COL}" AS nm,
               substr("Begin Time", 1, 10) AS d,
               AVG(CAST("{LOCAL_TDD_VALUE_COL}" AS REAL)) / 86400.0 AS v
        FROM "{LOCAL_TDD_TABLE}"
        WHERE "Begin Time" >= ? AND "Begin Time" <= ?
          AND "{LOCAL_TDD_SITE_COL}" IS NOT NULL
        GROUP BY 1, 2
    '''
    out: Dict[Tuple[str, str], float] = {}
    # 该库是独立的本地 sqlite 文件：PG 模式下 get_raw_connection 会把它解析成
    # PG schema（不存在），因此这里必须直连 sqlite，不走项目双模封装。
    try:
        conn = sqlite3.connect(
            "file:%s?mode=ro" % LOCAL_AVAIL_DB.as_posix(), uri=True, timeout=30)
        try:
            for r in conn.execute(sql, (start, end)).fetchall():
                nm = norm_name(r[0])
                d = str(r[1] or "")[:10]
                v = _to_float(r[2])
                if nm and d and v is not None:
                    out[(nm, d)] = v
        finally:
            conn.close()
    except Exception as e:
        logger.warning("[site-avail] 本地 TDD 聚合失败 month=%s: %s", month, e)
    return out


def load_month_availability(month: str) -> Dict[str, Dict[Tuple[str, str], float]]:
    """加载整月四制式可用率（带缓存）。返回 {tech: {(norm_site, day): ratio}}。"""
    ck = f"site_avail:data:{month}"
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    data: Dict[str, Dict[Tuple[str, str], float]] = {}
    for tech in ["G", "U", "L"]:
        data[tech] = _load_remote_tech(tech, month)
    data["Tdd"] = _load_local_tdd(month)
    logger.info(
        "[site-avail] month=%s loaded G=%d U=%d L=%d Tdd=%d",
        month, len(data["G"]), len(data["U"]), len(data["L"]), len(data["Tdd"]),
    )
    return _cache_set(ck, data)


def load_master_sites() -> List[Dict[str, Any]]:
    """读取站点主数据（带缓存）。"""
    ck = "site_avail:master"
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    sql = """
        SELECT site_id, site_name, region, province_county, network_type,
               fme_name, supervisor, vip_site, site_type
        FROM master_site_db
    """
    out: List[Dict[str, Any]] = []
    try:
        # 双模约定：sqlite 原生写法（? 占位 + fetchall），PG 由连接层适配
        with get_raw_connection(timeout=30) as conn:
            for r in conn.execute(sql).fetchall():
                out.append({
                    "site_id": r[0],
                    "site_name": r[1],
                    "region": r[2],
                    "province_county": r[3],
                    "network_type": r[4],
                    "fme_name": r[5],
                    "supervisor": r[6],
                    "vip_site": r[7],
                    "site_type": r[8],
                    "_k": norm_name(r[1]),
                    "_sid": str(r[0]).strip() if r[0] is not None else "",
                })
    except Exception as e:
        logger.warning("[site-avail] 读取 master_site_db 失败: %s", e)
    return _cache_set(ck, out)


TT_COLUMNS = [
    "tt_no", "title", "status", "created_time", "alarm_occur_time",
    "ticket_severity", "alarm_category", "current_handler", "sla_status",
    "site_name", "site_id", "site_outage", "fault_duration_time",
    "root_cause", "last_modified_time",
]


def _load_month_tt(month: str) -> List[Dict[str, Any]]:
    """读取整月 TT 单（带缓存）。"""
    ck = f"site_avail:tt:{month}"
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    start, end = month_bounds(month)
    cols = ", ".join(f'"{c}"' for c in TT_COLUMNS)
    sql = f"SELECT {cols} FROM eflow_tt WHERE created_time >= ? AND created_time <= ?"
    out: List[Dict[str, Any]] = []
    try:
        with get_raw_connection(timeout=30) as conn:
            for r in conn.execute(sql, (start, end)).fetchall():
                row = {c: r[i] for i, c in enumerate(TT_COLUMNS)}
                row["_k"] = norm_name(row.get("site_name"))
                row["_sid"] = str(row.get("site_id") or "").strip()
                row["_open"] = str(row.get("status") or "").strip().lower() != "closed"
                out.append(row)
    except Exception as e:
        logger.warning("[site-avail] 读取 eflow_tt 失败 month=%s: %s", month, e)
    logger.info("[site-avail] month=%s tt=%d", month, len(out))
    return _cache_set(ck, out)


# ============ 构建结果 ============
def _avg(vals: List[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def build_overview(month: str, supervisor: str = "", fme: str = "",
                   tech: str = "L", threshold: float = DEFAULT_THRESHOLD,
                   only_with_data: bool = False) -> Dict[str, Any]:
    """构建看板数据。

    tech 决定「时间维度展开哪个制式」；四制式的月均值始终返回，便于横向对比。
    """
    t0 = time.time()
    days = month_days(month)
    weeks = month_weeks(month)
    avail = load_month_availability(month)
    master = load_master_sites()
    tt_rows = _load_month_tt(month)

    # ---- 工单归属：每条 TT 只归给唯一一个站点 ----
    # 归属规则：先用 site_id 命中 master，未命中再用规范化 site_name 命中。
    # 一条 TT 只能算一次，避免「汇总工单数 > 实际 TT 条数」的重复计数。
    # 用索引字典避免 O(TT数 × 站点数) 的嵌套扫描。
    idx_by_sid: Dict[str, int] = {}
    idx_by_nm: Dict[str, int] = {}
    for idx, ms in enumerate(master):
        if ms["_sid"] and ms["_sid"] not in idx_by_sid:
            idx_by_sid[ms["_sid"]] = idx
        if ms["_k"] and ms["_k"] not in idx_by_nm:
            idx_by_nm[ms["_k"]] = idx

    tt_owner: Dict[int, List[Dict[str, Any]]] = {}
    unmatched = 0
    for r in tt_rows:
        owner_idx = idx_by_sid.get(r["_sid"]) if r["_sid"] else None
        if owner_idx is None and r["_k"]:
            owner_idx = idx_by_nm.get(r["_k"])
        if owner_idx is None:
            unmatched += 1
            continue
        tt_owner.setdefault(owner_idx, []).append(r)

    warnings: List[str] = []
    for tk in ("G", "U", "L"):
        if not avail.get(tk):
            warnings.append(f"{tk} 制式本月无远端站点级可用性数据")
    if not avail.get("Tdd"):
        warnings.append("Tdd 制式本月无本地小区级数据")

    # ---- 逐站点构建 ----
    sites: List[Dict[str, Any]] = []
    for idx, ms in enumerate(master):
        if supervisor and (ms.get("supervisor") or "") != supervisor:
            continue
        if fme and (ms.get("fme_name") or "") != fme:
            continue

        techs_out: Dict[str, Any] = {}
        for tk in TECHS:
            m = avail.get(tk) or {}
            daily = {d: m[(ms["_k"], d)] for d in days if (ms["_k"], d) in m}
            if not daily:
                techs_out[tk] = {"month_avg": None, "min": None, "days_below": 0,
                                 "days_with_data": 0, "daily": {}, "weekly": {}}
                continue
            vals = list(daily.values())
            min_day = min(daily, key=lambda d: daily[d])
            weekly = {}
            for w in weeks:
                wv = [daily[d] for d in w["days"] if d in daily]
                if wv:
                    weekly[w["key"]] = _avg(wv)
            techs_out[tk] = {
                "month_avg": _avg(vals),
                "min": daily[min_day],
                "min_day": min_day,
                "days_below": sum(1 for v in vals if v < threshold),
                "days_with_data": len(vals),
                "daily": daily,
                "weekly": weekly,
            }

        if only_with_data and not techs_out.get(tech, {}).get("daily"):
            continue

        # 工单：取本站点被归属到的 TT（已在上面完成唯一归属，不会重复计数）
        tt_list = tt_owner.get(idx, [])

        sites.append({
            "site_id": ms["site_id"],
            "site_name": ms["site_name"],
            "region": ms["region"],
            "province_county": ms["province_county"],
            "network_type": ms["network_type"],
            "fme_name": ms["fme_name"],
            "supervisor": ms["supervisor"],
            "vip_site": ms["vip_site"],
            "site_type": ms["site_type"],
            "techs": techs_out,
            "tickets": {
                "total": len(tt_list),
                "open": sum(1 for r in tt_list if r["_open"]),
                "closed": sum(1 for r in tt_list if not r["_open"]),
            },
        })

    # ---- 汇总 ----
    summary: Dict[str, Any] = {"site_count": len(sites), "by_tech": {}}
    for tk in TECHS:
        vals = [s["techs"][tk]["month_avg"] for s in sites
                if s["techs"][tk]["month_avg"] is not None]
        below = [s for s in sites
                 if s["techs"][tk]["month_avg"] is not None
                 and s["techs"][tk]["month_avg"] < threshold]
        summary["by_tech"][tk] = {
            "avg": _avg(vals),
            "sites_with_data": len(vals),
            "sites_below": len(below),
            "min": min(vals) if vals else None,
        }
    summary["ticket_total"] = sum(s["tickets"]["total"] for s in sites)
    summary["ticket_open"] = sum(s["tickets"]["open"] for s in sites)
    summary["ticket_closed"] = sum(s["tickets"]["closed"] for s in sites)

    return {
        "meta": {
            "month": month,
            "days": days,
            "weeks": [{"key": w["key"], "label": w["label"], "range": w["range"],
                       "days": w["days"]} for w in weeks],
            "tech": tech,
            "threshold": threshold,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_seconds": round(time.time() - t0, 2),
            "warnings": warnings,
            "tickets": {
                "in_month": len(tt_rows),
                "matched_to_site": len(tt_rows) - unmatched,
                "unmatched": unmatched,
            },
            "sources": {
                "G": {"source": "远端 db.sqlite3 / 2G_Main_Kpi_Site_Daily",
                      "field": "306004:TCH in service rate(%)", "derived": False},
                "U": {"source": "远端 db.sqlite3 / 3G_Main_Kpi_Site_Daily",
                      "field": "300857:Cell Validity Rate(%)", "derived": False},
                "L": {"source": "远端 db.sqlite3 / 4G_Main_Kpi_Site_Daily",
                      "field": "1638004469345:[FDD]Cell Availability[SDR_ITBBU]",
                      "derived": False},
                "Tdd": {"source": "本地 ran_kpi_avalability_1day.sqlite3 / "
                                  "Daily_KPI_RPA_CELL_AVAIL_TDD",
                        "field": "AVG(Cell Service Time(s))/86400", "derived": True},
            },
        },
        "summary": summary,
        "sites": sites,
    }


def get_filters() -> Dict[str, Any]:
    """筛选器选项：supervisor / fme / 可选月份。"""
    ck = "site_avail:filters"
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    masters = load_master_sites()
    sups = sorted({(m.get("supervisor") or "").strip() for m in masters
                   if (m.get("supervisor") or "").strip()})
    fmes = sorted({(m.get("fme_name") or "").strip() for m in masters
                   if (m.get("fme_name") or "").strip()})
    today = date.today()
    months = []
    for i in range(11, -1, -1):
        y = today.year
        mo = today.month - i
        while mo <= 0:
            mo += 12
            y -= 1
        months.append(f"{y}-{mo:02d}")
    out = {"supervisors": sups, "fmes": fmes, "months": months,
           "site_count": len(masters)}
    return _cache_set(ck, out)


def get_site_tickets(month: str, site_id: str = "", site_name: str = "") -> Dict[str, Any]:
    """某站点整月 TT 明细（按 created_time 倒序）。"""
    rows = _load_month_tt(month)
    kid = str(site_id or "").strip()
    knm = norm_name(site_name)
    out = []
    for r in rows:
        if kid and r["_sid"] == kid:
            out.append(r)
        elif knm and r["_k"] == knm:
            out.append(r)
    out.sort(key=lambda r: str(r.get("created_time") or ""), reverse=True)
    clean = []
    for r in out:
        d = {c: r.get(c) for c in TT_COLUMNS}
        d["open"] = r["_open"]
        clean.append(d)
    return {"month": month, "site_id": site_id, "site_name": site_name,
            "total": len(clean),
            "open": sum(1 for r in clean if r["open"]),
            "rows": clean}

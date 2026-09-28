# -*- coding: utf-8 -*-
"""MS SLA 看板 API（MS Contract KPIs / MS WOs SLA 数据看板）

数据源: data/ms_sla/ms_sla_dashboard.sqlite3（由 backend/services/ms_sla_dashboard.py
在 ms_sla_full 报表流程中全量写入；NUR/SLA/WO 已改为 nur_calc 实时计算，见下）。

GET /api/ms-sla-dashboard/overview : 一次返回 NUR / SLA / Network KPI / Per-Site /
                                     WO SLA（日/周/月三级）+ 数据新鲜度 meta。

NUR/SLA/Network KPI/Per-Site 返回「指标为行、期间为列」的表结构（与 NurDashboard 的
NurRow[] 对齐，便于前端表格与趋势图复用）；WO 返回明细行数组。

数据口径（2026-08 起）：
- NUR / SLA / WO 以 nur_calc 实时计算为准（数据库 TT + 小区口径，支持下钻
  GET /api/nur/detail，与 NUR Dashboard 完全一致），不再读取旧 Excel 快照；
- Per-Site 的 PS_NUR_2G/PS_NUR_3G 行替换为 nur_calc 实时计算的
  「站点 NUR(<350/100000) 达标占比」，其余 PS_* 与 Network KPI 仍为快照库数值；
- start/end 查询参数可限制实时计算的期间范围（前端 Time Range 默认随粒度档位变化）。
- 粒度：`daily` / `weekly` / `monthly`（2026-09-28 起 weekly 加入；周口径为 ISO 周
  「YYYY-Wnn」，与 nur_calc.GRANULARITIES / NurDashboard 完全一致，因此两页同粒度
  数字必然相同）。Network / Per-Site 来自看板快照库，快照只有日/月两级，weekly
  返回空表（前端只有「全量 page=ms_sla」会渲染这两块，直链页 ms_sla_only 不渲染）。
设计参考 alarm_dashboard.py / packet_loss_dashboard.py：TTL 内存缓存 + 双模读取。
"""
import time
import logging
from pathlib import Path

from fastapi import APIRouter
from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names

logger = logging.getLogger("ms_sla_dashboard")

router = APIRouter(prefix="/api/ms-sla-dashboard", tags=["ms-sla-dashboard"])

DASH_DB_PATH = Path(r"d:\01_RPA\Task\my_app\data\ms_sla\ms_sla_dashboard.sqlite3")

# 看板支持的粒度（顺序即前端页签顺序）。NUR/SLA/WO 由 nur_calc 实时计算，三级齐全；
# Network / Per-Site 来自快照库 ms_sla_kpi，只有 daily/monthly 两个 dataset，weekly 留空。
GRANULARITIES = ("daily", "weekly", "monthly")

# 标量指标 dataset -> 返回字段名（metric 行 × period 列的透视表）。
# 注意：NUR/SLA 不再走 ms_sla_kpi 快照（nur_daily/nur_monthly/sla_daily/sla_monthly），
# 改由 nur_calc 实时计算，见 _load_live_nur_sla()。保留映射仅作跳过标记，避免误读旧快照。
SCALAR_DATASETS = {
    "nur_daily": "nur",
    "nur_monthly": "nur",
    "sla_daily": "sla",
    "sla_monthly": "sla",
    "network_daily": "network",
    "network_monthly": "network",
    "persite_daily": "persite",
    "persite_monthly": "persite",
}

# nur_calc 实时结果的 metric 名 -> MS SLA 看板前端 KPI List 语义名（与旧快照列名一致）
NUR_METRIC_MAP = {
    "Global_NUR": "NUR_NETWORK",
    "2G_NUR": "NUR_2G",
    "3G_NUR": "NUR_3G",
    "4G_NUR": "NUR_4G",
}

# nur_calc 实时 SLA 的 metric（P1~P4/Total）-> KPI List 语义名（TTR/TTR_P1..P4）
SLA_METRIC_MAP = {
    "Total": "TTR",
    "P1": "TTR_P1",
    "P2": "TTR_P2",
    "P3": "TTR_P3",
    "P4": "TTR_P4",
}

# Per-Site 的 NUR 行：PS_NUR_2G/PS_NUR_3G 改为 nur_calc 实时计算的
# 「站点 NUR(<350/100000) 达标占比」：达标站数 / 该制式有小区站点总数
# （如 100 站中 1 站 NUR>350，则指标=99%）。值：tech 名 -> nur_calc.persite_nur 键。
PERSITE_NUR_SRC = {
    "PS_NUR_2G": "2G",
    "PS_NUR_3G": "3G",
}

# ========== 统一缓存（LRU + TTL + 前缀失效） ==========
from backend.services.cache import get_cache

_cache = get_cache()
_CACHE_TTL = 60


def _cache_get(key: str):
    return _cache.get(key)


def _cache_set(key: str, value):
    _cache.set(key, value, _CACHE_TTL)
    return value


def _invalidate_sla():
    """数据更新时清除 SLA 相关缓存。"""
    _cache.invalidate("overview|")
    _cache.invalidate("nur|")
    _cache.invalidate("sla|")


def _rows_as_dicts(cursor):
    """cursor -> [dict, ...]（双模：sqlite Row / PG 元组均兼容）"""
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


def _pivot(rows):
    """[(period, metric, value)] -> [{metric, period: value, ...}]，period 升序。

    行序按指标首次出现顺序保持稳定（KPI List 原顺序），列序按期间字典序升序。
    """
    by_metric: dict = {}
    periods: set = set()
    for r in rows:
        by_metric.setdefault(r["metric"], {})[r["period"]] = r["value"]
        periods.add(r["period"])
    ordered_periods = sorted(periods)
    return [
        {"metric": m, **{p: v.get(p) for p in ordered_periods}}
        for m, v in by_metric.items()
    ]


def _empty_by_gran():
    """各粒度一份空表：{daily: [], weekly: [], monthly: []}。

    统一走这个构造函数，新增粒度时不会漏掉某个数据集（历史上 daily/monthly 是
    手写三遍的字典字面量，加 weekly 时极易漏改其中一处）。
    """
    return {gran: [] for gran in GRANULARITIES}


def _load_live_nur_sla(start: str = "", end: str = ""):
    """NUR/SLA/WO/Per-Site 站点占比以 nur_calc 实时计算为准，返回 {nur, sla, wo, persite_nur}。

    - nur : metric 映射为 NUR_NETWORK/NUR_2G/NUR_3G/NUR_4G（KPI List 语义）
    - sla : 仅取各期间的达成率（achieve），metric 映射为 TTR/TTR_P1..P4
    - wo  : 把 SLA 的 total/pass/achieve 三列展开为 ms_sla_wo 结构（供 WO 表/图）
    - persite_nur : 站点级 NUR 达标占比 {gran: {tech: {period: 占比}}}（PS_NUR_2G/3G 数据源）
    一次调用 compute_overview()，避免各数据集重复计算；start/end 传入后 nur/sla/wo/
    persite_nur 全部限制在时间范围内（默认全量，与 NUR 看板一致）。
    计算失败时降级为空表（不影响 Network/Per-Site 等快照数据集）。
    """
    try:
        from backend.services import nur_calc
    except ImportError:  # 兼容以 backend 为根的导入方式
        from services import nur_calc  # type: ignore
    out: dict = {
        "nur": _empty_by_gran(),
        "sla": _empty_by_gran(),
        "wo": _empty_by_gran(),
        "persite_nur": {gran: {} for gran in GRANULARITIES},
    }
    try:
        ov = nur_calc.compute_overview(start=start, end=end)
        for gran in GRANULARITIES:
            # NUR：metric 名映射为 KPI List 语义名
            for r in ov.get("nur", {}).get(gran, []):
                mapped = NUR_METRIC_MAP.get(r["metric"])
                if not mapped:
                    continue
                out["nur"][gran].append(
                    {"metric": mapped, **{k: v for k, v in r.items() if k != "metric"}})
            # SLA：仅取各期间达成率 + 展开 WO 明细行（period 从 __achieve 键反解）
            # 注意："__achieve" 为 9 字符，k[:-9] 恰好去掉后缀（[:-8] 会残留尾下划线）
            for r in ov.get("sla", {}).get(gran, []):
                mapped = SLA_METRIC_MAP.get(r["metric"], r["metric"])
                periods = [k[:-9] for k in r if k.endswith("__achieve")]
                out["sla"][gran].append(
                    {"metric": mapped, **{p: r.get(f"{p}__achieve") for p in sorted(periods)}})
                for p in sorted(periods):
                    out["wo"][gran].append({
                        "period": p,
                        "metric": mapped,
                        "total": r.get(f"{p}__total"),
                        "within_sla": r.get(f"{p}__pass"),
                        "achieve": r.get(f"{p}__achieve"),
                    })
    except Exception as e:  # noqa: BLE001 - 实时计算失败不阻断整个看板
        logger.warning(f"[MS-SLA-DASH] nur_calc 实时计算失败，NUR/SLA/WO 返回空: {e}")
    # 站点级 NUR 达标占比（PS_NUR_2G/3G 数据源；早退分支无该键时降级空）
    for gran in GRANULARITIES:
        out["persite_nur"][gran] = ov.get("persite_nur", {}).get(gran, {})
    return out


def _apply_live_nur_to_persite(persite: dict, persite_nur: dict) -> dict:
    """Per-Site 的 NUR 行（PS_NUR_2G/PS_NUR_3G）替换为站点 NUR 达标占比。

    列（期间）以快照行为准，实时占比缺该期间时置空；persite_nur 为空（实时计算
    失败）时保留快照值降级。其余 PS_* KPI 行不受影响。
    """
    for gran in GRANULARITIES:
        tech_map = persite_nur.get(gran, {})
        rows = []
        for r in persite.get(gran, []):
            tech = PERSITE_NUR_SRC.get(r["metric"])
            if tech and tech in tech_map:
                ratio_map = tech_map[tech]
                rows.append({"metric": r["metric"],
                             **{p: ratio_map.get(p) for p in r if p != "metric"}})
            else:
                rows.append(r)
        persite[gran] = rows
    return persite


def _load_overview(start: str = "", end: str = ""):
    # 时间范围不同则实时计算区间不同，缓存 key 需带上 start/end
    cache_key = f"overview|{start}|{end}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    out = {
        "meta": {},
        "nur": _empty_by_gran(),
        "sla": _empty_by_gran(),
        "network": _empty_by_gran(),
        "persite": _empty_by_gran(),
        "wo": _empty_by_gran(),
    }

    # NUR/SLA/WO/Per-Site 站点占比以 nur_calc 实时计算为准（不依赖看板快照库；本地
    # sqlite 可能为空/在 PG 模式下快照 nur_daily 已无意义）。计算放最前：即使快照库
    # 缺失/损坏也返回实时数据。
    live = _load_live_nur_sla(start, end)
    out["nur"] = live["nur"]
    out["sla"] = live["sla"]
    out["wo"] = live["wo"]

    if not DASH_DB_PATH.exists():
        return _cache_set(cache_key, out)

    conn = get_raw_connection(str(DASH_DB_PATH), timeout=30)
    try:
        tables = set(list_table_names(conn))
        if "ms_sla_kpi" in tables:
            rows = _rows_as_dicts(conn.execute(
                'SELECT period, dataset, metric, value FROM ms_sla_kpi ORDER BY period'))
            scalar: dict = {}
            for r in rows:
                target = scalar.setdefault(r["dataset"], [])
                target.append(r)
            for ds, data in scalar.items():
                target_key = SCALAR_DATASETS.get(ds)
                if not target_key or target_key in ("nur", "sla"):
                    # NUR/SLA 已由 _load_live_nur_sla() 实时提供，跳过旧快照
                    continue
                gran = "monthly" if ds.endswith("monthly") else "daily"
                if gran not in out[target_key]:
                    continue
                out[target_key][gran] = _pivot(data)
        if "ms_sla_meta" in tables:
            out["meta"] = {r["key"]: r["value"] for r in _rows_as_dicts(
                conn.execute("SELECT key, value FROM ms_sla_meta"))}
    finally:
        conn.close()

    # Per-Site 的 NUR 行（PS_NUR_2G/PS_NUR_3G）替换为 nur_calc 站点 NUR 达标占比
    out["persite"] = _apply_live_nur_to_persite(out["persite"], live["persite_nur"])
    return _cache_set(cache_key, out)


@router.get("/overview")
def ms_sla_overview(start: str = "", end: str = ""):
    """MS SLA 看板总览：NUR / SLA / Network KPI / Per-Site / WO（日/周/月）+ meta。

    粒度键固定为 daily / weekly / monthly。NUR/SLA/WO 三级齐全（nur_calc 实时计算）；
    Network / Per-Site 来自快照库，weekly 恒为空表。

    start/end（YYYY-MM-DD，可选）：限制 nur/sla/wo/Per-Site 站点占比的实时计算区间。
    """
    return _load_overview(start, end)

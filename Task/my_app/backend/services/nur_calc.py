# -*- coding: utf-8 -*-
"""
NUR / SLA 看板计算引擎
======================
数据源：主库 app.eflow_tt + app.cm_site_summary（DB_MODE=pg/sqlite 双模兼容，
经 backend.database.get_raw_connection 透明切换）。

口径
----
1. Tech 模糊匹配（title 最后一个 "]" 之后的告警类型段，避免站名 "Ganta 4" 误匹配）：
   - 单制式：2G/3G/4G(含 LTE)/5G 关键字
   - 整站  ：CSD/PSD/SITE DOWN DUE TO POWER OFF → 该站在 CM 中的全部制式小区
   - 其余  ：小区数 0，不计入 NUR（仍计入 SLA 统计）
2. MTTR = (alarm_clear_time - alarm_occur_time) 分钟，剔除 <=0 或 >=43200；未清除不计 NUR
3. NUR_tech = Σ(小区数×MTTR)×60 / (分母小区数×GR)；GR 日=86400、周=604800、月=天数×86400
   （当期未过完按已过天数），输出原始数值（不乘 100）
4. 分母：默认全网该制式小区总数；Project 筛选生效时按 site_caregory 与站点类型
   归一化包含匹配圈定小区数（分子分母同口径）
5. SLA：ticket_severity 分组 Total / Within SLA(sla_status='Pass') / 达成率
6. 站点四维过滤（trm_type / site_caregory / province_county / region，2026-09-30 新增）：
   属性一律取自站点主数据 master_site_db，**精确匹配**；分子（TT 行）与分母
   （cm_site_summary 小区数）走同一份属性索引，保证两侧圈定的是同一批站点。
   站点归属规则见 attach_site_attrs（site_id 命中优先，重名站点不做站名回退）。

排除名单：FTP 192.168.100.19 /webroot/WEB-INF/reportlets/excel/TT_Exclude.xlsx，
ticket_no 或 tt_no 命中即 Exclude=Y；内存缓存 30 分钟，FTP 失败降级空集不阻断。
"""
import calendar
import ftplib
import io
import logging
import re
import threading
import time
from datetime import date, datetime
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from backend.database import engine, get_raw_connection

logger = logging.getLogger("nur_calc")

TECHS = ["2G", "3G", "4G", "5G"]
GRANULARITIES = ["daily", "weekly", "monthly"]

# ---------- Tech 模糊匹配规则（对 29244 条 title 实测验证） ----------
TECH_KEYWORDS: List[Tuple[str, Tuple[str, ...]]] = [
    ("2G", ("2G",)),
    ("3G", ("3G",)),
    ("4G", ("4G", "LTE")),
    ("5G", ("5G",)),
]
SITEWIDE_KEYWORDS = (
    "COMPLETE SITE DOWN", "CSD",
    "PARTIAL SITE DOWN", "PSD",
    "SITE DOWN DUE TO POWER OFF",
)

EXCLUDE_FTP_PATH = "/webroot/WEB-INF/reportlets/excel/TT_Exclude.xlsx"
EXCLUDE_CACHE_TTL = 1800  # 秒

_TT_COLS = ("title, ticket_no, tt_no, ticket_severity, sla_status, "
            "alarm_occur_time, alarm_clear_time, site_id, site_name, site_information")
_CM_COLS = ('"Site_ID", "Site_Name", "NumberOfCells", "Tech", "site_caregory"')

# ---------- 站点四维过滤（trm_type / site_caregory / province_county / region） ----------
# 属性来源固定为站点主数据 master_site_db（与 GISMap、TT&WO Dashboard 同一个真相源）；
# 元组顺序即前端下拉的展示顺序，也是 /options 下发的顺序。
SITE_FILTER_COLS: Tuple[str, ...] = ("trm_type", "site_caregory", "province_county", "region")
_SITE_COLS = "site_id, site_name, trm_type, site_caregory, province_county, region"
# TT 行/CM 行上挂载的属性列前缀，避免与 eflow_tt 自身的 site_caregory 之类同名列冲突
_SITE_PREFIX = "s_"


def _site_col(col: str) -> str:
    """站点属性列在数据帧上的列名（带前缀，见 _SITE_PREFIX）。"""
    return _SITE_PREFIX + col


# ============================================================
# 工具函数
# ============================================================
def _norm_str(s) -> str:
    """None/NaN → ''，其余转字符串并去首尾空白（向量化前逐元素兜底用）。"""
    if s is None:
        return ""
    try:
        if pd.isna(s):
            return ""
    except (TypeError, ValueError):
        pass
    return str(s).strip()


def _norm_series(s: pd.Series) -> pd.Series:
    """列向量化归一化：None/NaN → ''，其余字符串去首尾空白。"""
    return s.fillna("").astype(str).str.strip()


def _norm_category(v: str) -> str:
    """站点类型归一化：小写 + 去除全/半角括号及其中文变体，用于包含匹配。"""
    return re.sub(r"[（(）)]", "", _norm_str(v)).lower()


def _cat_match(site_caregory_val: str, project: str) -> bool:
    """cm_site_summary.site_caregory 与 Project 站点类型的双向包含匹配。
    例：'REGULAR(Normal)' ↔ 'REGULAR'；空串不匹配任何值。"""
    cat = _norm_category(site_caregory_val)
    prj = _norm_category(project)
    if not cat or not prj:
        return False
    return cat.startswith(prj) or prj.startswith(cat)


# ============================================================
# 数据加载（主库双模）
# ============================================================
def load_tt_df() -> pd.DataFrame:
    """读取 eflow_tt 所需列；表不存在时返回空 DataFrame。"""
    from sqlalchemy import text
    try:
        df = pd.read_sql(text(f"SELECT {_TT_COLS} FROM eflow_tt"), engine)
    except Exception as e:
        logger.warning(f"[NUR] eflow_tt 读取失败: {e}")
        return pd.DataFrame()
    df.columns = [c.lower() for c in df.columns]
    return df


def load_cm_summary() -> pd.DataFrame:
    """读取 cm_site_summary；列名统一转小写（PG 大小写敏感/SQLite 不敏感均兼容）。"""
    from sqlalchemy import text
    try:
        df = pd.read_sql(text(f"SELECT {_CM_COLS} FROM cm_site_summary"), engine)
    except Exception as e:
        logger.warning(f"[NUR] cm_site_summary 读取失败: {e}")
        return pd.DataFrame()
    df.columns = [c.lower() for c in df.columns]
    return df


def get_project_options() -> List[str]:
    """site_information 去重可选值（过滤空值）。"""
    with get_raw_connection() as conn:
        try:
            rows = conn.execute(
                "SELECT DISTINCT site_information FROM eflow_tt "
                "WHERE site_information IS NOT NULL AND site_information <> ''"
            ).fetchall()
        except Exception:
            return []
    return sorted(_norm_str(r[0]) for r in rows if _norm_str(r[0]))


# ============================================================
# 站点四维过滤：主数据加载 / 索引 / 挂载 / 候选值
# ------------------------------------------------------------
# 为什么属性取自 master_site_db 而不是 cm_site_summary：
#   - cm_site_summary 只有 region / province_county / site_caregory 三列、没有
#     trm_type（实测 app.cm_site_summary 7 列）；若三列取自 cm、一列取自主数据，
#     分子与分母就可能落在两个不同的站点集合上，看板数字与下钻行数会对不上。
#   - master_site_db 是 GISMap / TT&WO Dashboard 共用的站点主数据（同一口径），
#     四列齐全（实测 827 行，site_id 无重复）。
# ============================================================
def load_site_master() -> pd.DataFrame:
    """读取站点主数据 master_site_db 的四维属性；列名统一转小写。"""
    from sqlalchemy import text
    try:
        df = pd.read_sql(text(f"SELECT {_SITE_COLS} FROM master_site_db"), engine)
    except Exception as e:
        logger.warning(f"[NUR] master_site_db 读取失败: {e}")
        return pd.DataFrame()
    df.columns = [c.lower() for c in df.columns]
    return df


def build_site_index(sm: pd.DataFrame) -> Dict[str, object]:
    """把站点主数据编译成两套查找表（供 TT 行与 CM 行共用）。

    返回 ``{"sid": {列: {site_id: 值}}, "name": {列: {站名小写: 值}},
             "sids": set, "names": set}``。

    归属规则（与 site_availability_service.build_overview 的唯一归属同源）：
    1. ``site_id`` 命中优先 —— eflow_tt.site_id 与 master_site_db.site_id 同属一个
       站点 ID 空间（实测 36510 行 TT 中 36040 行命中，且 site_id 在主库唯一，不产生扇出）；
    2. 未命中时回退**站名小写**匹配，但**重名站点直接不参与回退** ——
       主数据实测有 11 个重名站（如 'Gbarplay' 同时存在 9049=ERA / 3620=NORMAL），
       任选一个都是静默错归。这类行按「未归属」处理：站点过滤生效时被排除，
       不猜一个属性塞进去（宁可少一行，不可错一行）。
    """
    empty = {"sid": {c: {} for c in SITE_FILTER_COLS},
             "name": {c: {} for c in SITE_FILTER_COLS}, "sids": set(), "names": set()}
    if sm.empty or not set(SITE_FILTER_COLS).issubset(set(sm.columns)):
        return empty
    d = sm.copy()
    d["_sid"] = _norm_series(d["site_id"])
    d["_nm"] = _norm_series(d["site_name"]).str.lower()
    d = d[(d["_sid"] != "") | (d["_nm"] != "")]

    # site_id 维度：按 ID 去重（实测主库 site_id 唯一，这里只是防御性写法）
    sid_rows = d[d["_sid"] != ""].drop_duplicates("_sid", keep="first")
    # 站名维度：重名站整组剔除（不猜），其余按站名唯一
    dup_names = set(d.loc[d["_nm"].duplicated(keep=False), "_nm"]) - {""}
    nm_rows = (d[(d["_nm"] != "") & (~d["_nm"].isin(dup_names))]
               .drop_duplicates("_nm", keep="first"))

    sid_map = {c: sid_rows.set_index("_sid")[c].to_dict() for c in SITE_FILTER_COLS}
    name_map = {c: nm_rows.set_index("_nm")[c].to_dict() for c in SITE_FILTER_COLS}
    return {"sid": sid_map, "name": name_map,
            "sids": set(sid_map[SITE_FILTER_COLS[0]].keys()),
            "names": set(name_map[SITE_FILTER_COLS[0]].keys())}


def attach_site_attrs(df: pd.DataFrame, sid_col: str, name_col: str,
                      site_index: Dict[str, object]) -> pd.DataFrame:
    """给数据帧挂上站点四维属性列 ``s_trm_type`` / ``s_site_caregory`` /
    ``s_province_county`` / ``s_region`` 以及归属标志 ``s_matched``。

    归属规则见 :func:`build_site_index`（site_id 优先、重名站名不回退）。
    未归属的行属性为空串，站点过滤生效时会被自然排除。
    """
    out = df.copy()
    sid = _norm_series(out[sid_col]) if sid_col in out.columns else pd.Series("", index=out.index)
    nm = (_norm_series(out[name_col]).str.lower() if name_col in out.columns
          else pd.Series("", index=out.index))
    sid_map = site_index.get("sid") or {}
    name_map = site_index.get("name") or {}
    if not site_index.get("sids"):
        for c in SITE_FILTER_COLS:
            out[_site_col(c)] = ""
        out["s_matched"] = False
        return out

    for c in SITE_FILTER_COLS:
        v = sid.map((sid_map or {}).get(c) or {})
        v = v.where(v.notna(), nm.map((name_map or {}).get(c) or {}))
        out[_site_col(c)] = v.fillna("")
    out["s_matched"] = sid.isin(site_index["sids"]) | nm.isin(site_index["names"])
    return out


def get_site_filter_options() -> Dict[str, List[str]]:
    """站点四维过滤的候选值（与过滤实现同源：master_site_db 精确匹配）。

    列名来自模块常量 :data:`SITE_FILTER_COLS`（**不来自请求输入**），因此这里
    拼接列名没有注入面；每列最多 200 个候选，与 TT&WO Dashboard 的
    ``site_filter_fields`` / ``filter_options`` 同一约定。
    """
    out: Dict[str, List[str]] = {}
    try:
        with get_raw_connection() as conn:
            for col in SITE_FILTER_COLS:
                try:
                    rows = conn.execute(
                        f"SELECT DISTINCT {col} FROM master_site_db "
                        f"WHERE {col} IS NOT NULL AND {col} <> '' AND {col} <> 'None' "
                        f"ORDER BY {col} LIMIT 200"
                    ).fetchall()
                except Exception:
                    logger.warning(f"[NUR] 站点过滤候选列 {col} 查询失败，已跳过", exc_info=True)
                    continue
                vals = [_norm_str(r[0]) for r in rows]
                vals = [v for v in vals if v]
                if vals:
                    out[col] = vals
    except Exception:
        logger.warning("[NUR] 站点过滤候选值读取失败（前端下拉将为空）", exc_info=True)
    return out


# ============================================================
# 排除名单（FTP + 30 分钟缓存）
# ============================================================
_exclude_cache: Dict[str, object] = {}


def _fetch_exclude_xlsx_bytes() -> bytes:
    """FTP 内存下载 TT_Exclude.xlsx（凭据由 remote_ftp.creds_for 按路径前缀决定）。"""
    try:
        from backend.services.remote_ftp import creds_for
        from backend.config.remote_host import get_ftp_host
    except ImportError:
        from remote_ftp import creds_for  # type: ignore
        from backend.config.remote_host import get_ftp_host
    user, pw = creds_for(EXCLUDE_FTP_PATH)
    buf = bytearray()
    ftp = ftplib.FTP(get_ftp_host(), timeout=30)
    try:
        ftp.login(user, pw)
        ftp.retrbinary(f"RETR {EXCLUDE_FTP_PATH}", buf.extend)
    finally:
        try:
            ftp.quit()
        except Exception:
            pass
    return bytes(buf)


def get_exclude_info(force_refresh: bool = False) -> Dict:
    """加载排除名单（缓存 30 分钟）。FTP 失败降级：有旧缓存用旧缓存，否则空集。"""
    now = time.time()
    if not force_refresh and _exclude_cache.get("loaded_at") \
            and now - _exclude_cache["loaded_at"] < EXCLUDE_CACHE_TTL:
        return dict(_exclude_cache)

    info: Dict[str, object] = {
        "count": 0, "column": None, "loaded_at": None,
        "error": None, "source": "ftp", "set": set(),
    }
    try:
        data = _fetch_exclude_xlsx_bytes()
        df = pd.read_excel(io.BytesIO(data))
        col = None
        for c in df.columns:
            if re.search(r"(tt|ticket|单号)", str(c), re.I):
                col = c
                break
        if col is None and len(df.columns) > 0:
            col = df.columns[0]
        tickets: Set[str] = set()
        if col is not None:
            tickets = {v for v in _norm_series(df[col]) if v}
        info.update(count=len(tickets), column=str(col) if col is not None else None,
                    loaded_at=now, set=tickets)
    except Exception as e:
        logger.warning(f"[NUR] TT_Exclude.xlsx 加载失败，降级处理: {e}")
        if _exclude_cache.get("set"):
            stale = dict(_exclude_cache)
            stale["error"] = f"刷新失败，使用 {int(now - stale['loaded_at']) // 60} 分钟前缓存: {e}"
            stale["source"] = "cache"
            return stale
        info["error"] = str(e)
        info["source"] = "fallback_empty"

    _exclude_cache.update(info)
    return dict(info)


# ============================================================
# Tech 匹配 + 小区数关联
# ============================================================
def classify_title(title: str):
    """返回 ('tech','2G') / ('sitewide',None) / ('none',None)。"""
    s = _norm_str(title).upper()
    seg = s.rsplit("]", 1)[-1]  # 取最后一个 ] 之后的告警类型段
    for tech, kws in TECH_KEYWORDS:
        if any(kw in seg for kw in kws):
            return ("tech", tech)
    if any(kw in seg for kw in SITEWIDE_KEYWORDS):
        return ("sitewide", None)
    return ("none", None)


def build_cell_pivot(cm: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """站点×制式小区数透视（Site_ID 主键索引，site_id 为空的行用站名回退键）。

    返回 (pivot: index=site_key, columns=2G/3G/4G/5G, 值=小区数,
          cells_by_tech: 全网每制式小区总数)。
    """
    if cm.empty:
        empty = pd.DataFrame(0, index=pd.Index([], name="site_key"), columns=TECHS)
        return empty, {t: 0 for t in TECHS}
    d = cm.copy()
    d["site_id_n"] = _norm_series(d["site_id"])
    d["site_name_n"] = _norm_series(d["site_name"]).str.lower()
    d["site_key"] = d["site_id_n"].where(d["site_id_n"] != "", "_" + d["site_name_n"])
    d["tech"] = _norm_series(d["tech"]).str.upper()
    d = d[d["tech"].isin(TECHS)]
    d["cells"] = pd.to_numeric(d["numberofcells"], errors="coerce").fillna(0).astype(int)
    pivot = (d.groupby(["site_key", "tech"], as_index=False)["cells"].sum()
              .pivot(index="site_key", columns="tech", values="cells").fillna(0).astype(int))
    for t in TECHS:
        if t not in pivot.columns:
            pivot[t] = 0
    pivot = pivot[TECHS]
    cells_by_tech = pivot.sum(axis=0).to_dict()
    return pivot, cells_by_tech


def attach_cells(tt: pd.DataFrame, pivot: pd.DataFrame) -> pd.DataFrame:
    """向量化关联：site_id 匹配（空值回退 _站名小写），计算每 TT 的小区数。

    新增列：
    - site_cells_2G..5G : 该站在各制式的小区数（未匹配为 0）
    - cells_weight      : NUR 分子用小区数——tech=对应制式小区数；
                          sitewide=该站所有制式小区数之和；none=0
    """
    tt = tt.copy()
    cls = tt["title"].map(classify_title)
    tt["cls_kind"] = cls.map(lambda x: x[0])
    tt["cls_tech"] = cls.map(lambda x: x[1])

    site_id_n = _norm_series(tt["site_id"])
    site_name_n = _norm_series(tt["site_name"]).str.lower()
    site_key = site_id_n.where(site_id_n != "", "_" + site_name_n)
    # 预存站点键：站点级 NUR 占比对每个制式都要用一次，不存的话要在
    # _site_nur_ratio_for_tech 里对 3.5 万行重复归一化 8 次（实测约 400ms）
    tt["site_key"] = site_key

    for t in TECHS:
        tt[f"site_cells_{t}"] = 0
    if pivot.empty:
        tt["cells_weight"] = 0
        return tt

    pv = pivot.reindex(site_key.values).fillna(0).astype(int)
    pv.index = tt.index
    for t in TECHS:
        tt[f"site_cells_{t}"] = pv[t].values
    tech_arr = tt["cls_tech"].values
    vals = np.where(
        tt["cls_kind"].values == "sitewide",
        pv[TECHS].sum(axis=1).values,
        np.select(
            [tech_arr == t for t in TECHS],
            [pv[t].values for t in TECHS],
            default=0,
        ),
    )
    tt["cells_weight"] = np.where(tt["cls_kind"].values == "none", 0, vals).astype(int)
    return tt


# ============================================================
# 期间 / GR
# ============================================================
def _iso_week_label(d) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def enrich_periods(tt: pd.DataFrame) -> pd.DataFrame:
    """解析时间、计算 MTTR、生成 日/周/月 期间标签（全向量化）。"""
    tt = tt.copy()
    tt["occur_dt"] = pd.to_datetime(tt["alarm_occur_time"], errors="coerce")
    tt["clear_dt"] = pd.to_datetime(tt["alarm_clear_time"], errors="coerce")
    mttr = (tt["clear_dt"] - tt["occur_dt"]).dt.total_seconds() / 60.0
    tt["mttr_min"] = mttr
    # 有效 MTTR：>0 且 <43200 分钟（30 天），沿用 TT&WO 看板口径；未清除不计 NUR
    tt["mttr_valid"] = mttr.notna() & (mttr > 0) & (mttr < 43200)
    tt["cell_minutes"] = np.where(tt["mttr_valid"], tt["cells_weight"] * mttr, 0.0)
    tt["vendor"] = np.where(_norm_series(tt["ticket_no"]).values != "", "ZTE", "3RD")

    occ = tt["occur_dt"]
    tt["day"] = occ.dt.strftime("%Y-%m-%d")
    iso = occ.dt.isocalendar()
    tt["week"] = iso["year"].astype("Int64").astype(str).where(
        occ.notna(), None) + "-W" + iso["week"].astype(str).str.zfill(2)
    tt.loc[occ.isna(), "week"] = None
    tt["month"] = occ.dt.strftime("%Y-%m")
    return tt


def period_seconds(gran: str, period: str, today: date) -> float:
    """GR 秒数：日=86400；周=604800；月=当月天数×86400。当期未过完按已过天数。"""
    if gran == "daily":
        return 86400.0
    if gran == "weekly":
        try:
            year, wk = period.split("-W")
            monday = date.fromisocalendar(int(year), int(wk), 1)
            days = min(7, max(1, (today - monday).days + 1)) if today >= monday else 7
        except Exception:
            days = 7
        return days * 86400.0
    try:
        y, m = period.split("-")
        y, m = int(y), int(m)
        dim = calendar.monthrange(y, m)[1]
        if (y, m) == (today.year, today.month):
            dim = max(1, today.day)
        return dim * 86400.0
    except Exception:
        return 30 * 86400.0


def enumerate_periods(gran: str, tt: pd.DataFrame,
                      start: Optional[str], end: Optional[str]) -> List[str]:
    """按时间范围枚举完整期间列表（升序）；未给范围时用数据自身期间。"""
    col = {"daily": "day", "weekly": "week", "monthly": "month"}[gran]
    valid = tt.dropna(subset=["occur_dt"])
    if start or end:
        lo = pd.to_datetime(start) if start else valid["occur_dt"].min()
        hi = pd.to_datetime(end) if end else valid["occur_dt"].max()
        if pd.isna(lo) or pd.isna(hi) or lo > hi:
            return []
        if gran == "daily":
            return [d.strftime("%Y-%m-%d") for d in pd.date_range(lo.normalize(), hi.normalize())]
        if gran == "weekly":
            monday = (lo.normalize() - pd.Timedelta(days=lo.weekday()))
            out = []
            cur = monday
            while cur <= hi:
                out.append(_iso_week_label(cur.date()))
                cur += pd.Timedelta(days=7)
            return out
        return [p.strftime("%Y-%m") for p in pd.date_range(lo.normalize(), hi.normalize(), freq="MS")]
    return sorted(valid[col].dropna().unique().tolist())


# ============================================================
# 站点级 NUR 达标占比（Per-Site KPIs 的 PS_NUR_2G/3G 数据源）
# ============================================================
# 口径：站点 NUR = Σ(该站该制式小区数×MTTR)×60 / (该站该制式小区数×GR)，
# 与全网 NUR 完全一致（mttr_valid 行；sitewide 单按站制式小区数拆分归属）。
# 达标阈值：站点 NUR ×100000 < 350（即 < 0.0035）；无故障站 NUR=0 视为达标。
# 指标值 = 达标站点数 / 该制式有小区（CM）的站点总数。
SITE_NUR_RATIO_THRESHOLD = 350 / 100000.0  # 0.0035


def _site_nur_ratio_for_tech(df: pd.DataFrame, col: str, periods: List[str],
                             site_cells: pd.Series, tech: str,
                             gran: str, today: date) -> Dict[str, Optional[float]]:
    """单制式站点级 NUR 达标占比：{period: 占比|None}。

    - 分母：CM 中该制式小区数 > 0 的站点（不受 TT 有无影响）
    - 分子：当期站点 NUR < SITE_NUR_RATIO_THRESHOLD 的站点
    全向量化：先按 (期间, 站点) 聚合分子小区分钟，再 reindex 到 期间×站点 全格。
    """
    denom_sites = site_cells[site_cells > 0]
    if denom_sites.empty:
        return {p: None for p in periods}
    d = df[df["mttr_valid"]]
    # site_key 已由 attach_cells 预存；只有外部传入未经处理的 df 时才兜底重算
    if "site_key" not in d.columns:
        _sid = _norm_series(d["site_id"])
        d = d.assign(site_key=_sid.where(_sid != "",
                                        "_" + _norm_series(d["site_name"]).str.lower()))

    # 分子：tech 单按 (期间, 站点) 聚合；sitewide 单按该站该制式小区数拆分。
    # 增量合并而非从空 Series 起步，避免 pandas3 空 Series 与 MultiIndex add 时
    #  “cannot join with no overlapping index names” 报错。
    tech_part = d[(d["cls_kind"] == "tech") & (d["cls_tech"] == tech)]
    num = (tech_part.groupby([col, "site_key"], observed=True)["cell_minutes"].sum()
           if not tech_part.empty else None)
    sw = d[d["cls_kind"] == "sitewide"]
    if not sw.empty:
        cmt = sw[f"site_cells_{tech}"].values * sw["mttr_min"].values
        g2 = (pd.DataFrame({col: sw[col].values, "site_key": sw["site_key"].values,
                            "cm": cmt})
              .groupby([col, "site_key"], observed=True)["cm"].sum())
        num = g2 if num is None else num.add(g2, fill_value=0)
    if num is None or num.empty:
        # 当期无任何故障：全部站点达标
        return {p: 1.0 for p in periods}

    # 全格展开：无故障站点 reindex 后为 0（NUR=0 达标）
    idx = pd.MultiIndex.from_product([periods, denom_sites.index],
                                     names=[col, "site_key"])
    num = num.reindex(idx, fill_value=0.0)
    gr = num.index.get_level_values(0).map(
        lambda p: period_seconds(gran, p, today)).to_numpy()
    cells = denom_sites.reindex(num.index.get_level_values(1)).to_numpy()
    nur = num.to_numpy() * 60.0 / (cells * gr)
    ok = nur < SITE_NUR_RATIO_THRESHOLD
    s = pd.Series(ok, index=idx)
    return {p: round(float(s.xs(p, level=0).mean()), 4) for p in periods}


# ============================================================
# 基础数据缓存（与请求参数无关的那部分）
# ------------------------------------------------------------
# 每次请求都重读 3.5 万行 eflow_tt（约 210ms），并重跑 attach_cells +
# enrich_periods 的逐行预处理（分类、站点键、MTTR、日/周/月标签，约 0.6~1.2s）。
# 这些**只取决于底层表，与 vendor/project/exclude/start/end 全都无关**，
# 却每个请求重算一遍 —— 实测 /api/nur/overview 因此要 2 秒。
#
# 缓存「预处理后的基础表」后，每个请求只剩过滤 + 分组（几十毫秒）。
# 底层表由定时任务同步，2 分钟 TTL 足够安全。
# ============================================================
BASE_CACHE_TTL = 120  # 秒

_base_lock = threading.Lock()
_base_cache: Dict[str, object] = {}

# 整页结果缓存：nur 与 ms_nur_only 两个页面打的是**同一个接口、同一组参数**，
# 缓存后第二个页面直接命中（实测 770ms -> 0ms）。refresh_exclude 时绕过。
RESULT_CACHE_TTL = 120  # 秒
_result_cache: Dict[str, Dict] = {}


def get_base_data(force: bool = False):
    """返回 (enriched_tt, cm, site_pivot, cells_all, site_index)，带 TTL 缓存。

    - enriched_tt / cm 都已挂上站点四维属性列（``s_trm_type`` 等，见 attach_site_attrs）；
    - site_index 是站点主数据索引，供下钻（compute_detail）等非缓存路径复用。

    ⚠ 调用方**不得就地修改**返回的 tt / cm（要加列请先 ``.copy()``），否则会污染缓存。
    """
    def _fresh() -> bool:
        at = _base_cache.get("at")
        return bool(at) and (time.time() - float(at)) < BASE_CACHE_TTL  # type: ignore[arg-type]

    if not force and _fresh():
        return (_base_cache["tt"], _base_cache["cm"], _base_cache["site_pivot"],
                _base_cache["cells_all"], _base_cache["site_index"])
    with _base_lock:
        if not force and _fresh():          # 双检：并发下只重建一次
            return (_base_cache["tt"], _base_cache["cm"], _base_cache["site_pivot"],
                    _base_cache["cells_all"], _base_cache["site_index"])
        t0 = time.time()
        tt = load_tt_df()
        cm = load_cm_summary()
        site_index = build_site_index(load_site_master())
        site_pivot, cells_all = build_cell_pivot(cm)
        # 站点属性：TT 行与 CM 行走**同一份索引**，分子分母必然落在同一批站点上
        cm = attach_site_attrs(cm, "site_id", "site_name", site_index)
        if not tt.empty:
            tt = attach_site_attrs(attach_cells(tt, site_pivot),
                                   "site_id", "site_name", site_index)
            tt = enrich_periods(tt)
        _base_cache.update({"at": time.time(), "tt": tt, "cm": cm,
                            "site_pivot": site_pivot, "cells_all": cells_all,
                            "site_index": site_index})
        logger.info("[NUR] 基础数据已重建 %.0fms (tt=%d 行)",
                    (time.time() - t0) * 1000, len(tt))
        return tt, cm, site_pivot, cells_all, site_index


def invalidate_base_cache() -> None:
    """底层表更新后调用，强制下次请求重建基础数据。"""
    _base_cache.clear()
    _result_cache.clear()


def warmup() -> None:
    """启动期后台预热（不阻塞 startup）。

    冷路径要建基础表 + 首次连库 + 拉 FTP 排除名单，实测首个请求 ~3.9s；
    预热后用户的第一个请求只剩计算（~0.8s），页面总耗时可控在 3s 内。
    """
    def _job() -> None:
        try:
            t0 = time.time()
            get_base_data(force=True)
            get_exclude_info()
            logger.info("[NUR] 启动预热完成 %.0fms", (time.time() - t0) * 1000)
        except Exception:  # noqa: BLE001  预热失败不能影响启动
            logger.warning("[NUR] 启动预热失败（不影响启动）", exc_info=True)

    threading.Thread(target=_job, name="nur-warmup", daemon=True).start()


# ============================================================
# 主计算
# ============================================================
def compute_overview(vendor: str = "", project: str = "", exclude: str = "",
                     start: str = "", end: str = "",
                     refresh_exclude: bool = False,
                     trm_type: str = "", site_caregory: str = "",
                     province_county: str = "", region: str = "") -> Dict:
    """一次计算 6 张表：nur/sla × daily/weekly/monthly。

    筛选适配原则：Vendor/时间/Exclude 只作用于分子（TT 行）；
    Project 同时作用于分子（site_information）与分母（site_caregory 圈定小区数）；
    站点四维（trm_type / site_caregory / province_county / region）同样**同时作用于
    分子与分母**（属性取自主数据 master_site_db，精确匹配）—— 只筛分子会让 NUR
    的分子分母不同口径，比值不再是「这批站点的不可用率」。
    """
    t0 = time.time()
    warnings: List[str] = []

    site_filters = {c: _norm_str(v) for c, v in zip(
        SITE_FILTER_COLS, (trm_type, site_caregory, province_county, region))}
    site_filters = {c: v for c, v in site_filters.items() if v}

    rkey = "|".join([vendor, project, exclude, start, end,
                     *[f"{c}={site_filters.get(c, '')}" for c in SITE_FILTER_COLS]])
    if not refresh_exclude:
        hit = _result_cache.get(rkey)
        if hit and (time.time() - hit["at"]) < RESULT_CACHE_TTL:
            out = dict(hit["data"])
            out["cached"] = True
            out["elapsed_seconds"] = round(time.time() - t0, 3)
            return out

    tt, cm, site_pivot, cells_all, _site_index = get_base_data()
    if tt.empty:
        return {"nur": {}, "sla": {}, "cells_by_tech": {}, "denominator_cells": {},
                "exclude": get_exclude_info(refresh_exclude), "warnings": ["eflow_tt 无数据"],
                "elapsed_seconds": round(time.time() - t0, 2)}

    # 基础表来自共享缓存：下面要加 "excluded" 列，必须先复制，否则污染后续请求
    tt = tt.copy()

    # ---- 排除名单标记 ----
    ex_info = get_exclude_info(refresh_exclude)
    ex_set: Set[str] = ex_info.get("set") or set()
    if ex_info.get("error"):
        warnings.append(f"Exclude 名单: {ex_info['error']}")
    if ex_set:
        tno = _norm_series(tt["ticket_no"])
        ttno = _norm_series(tt["tt_no"])
        tt["excluded"] = (tno.isin(ex_set) | ttno.isin(ex_set)).map({True: "Y", False: "N"})
    else:
        tt["excluded"] = "N"

    # ---- 筛选（分子口径）----
    df = tt
    if vendor in ("ZTE", "3RD"):
        df = df[df["vendor"] == vendor]
    if project:
        df = df[df["site_information"].map(_norm_str) == project]
    if exclude in ("Y", "N"):
        df = df[df["excluded"] == exclude]
    # 站点四维过滤：精确匹配（与 /options 下发的候选值同源），不用 LIKE ——
    # 概览与下钻必须逐字同口径，否则「表里的数」与「下钻的行数」对不上。
    for c, v in site_filters.items():
        df = df[df[_site_col(c)] == v]
    if start:
        df = df[(df["occur_dt"] >= pd.to_datetime(start))]
    if end:
        df = df[(df["occur_dt"] <= pd.to_datetime(end) + pd.Timedelta(days=1))]

    # ---- 分母小区数（Project / 站点四维生效时按同一批站点圈定）----
    # site_pivot 同时供站点级 NUR 达标占比使用（分母站点集合与全网分母同口径）
    # 注：未筛选的 site_pivot/cells_all 已随基础数据缓存，无需重复透视
    if (project or site_filters) and not cm.empty:
        # cm 上的站点属性已随基础数据挂好（与分子同一份索引）
        mask = pd.Series(True, index=cm.index)
        if project:
            mask &= cm["site_caregory"].map(lambda v: _cat_match(_norm_str(v), project))
        for c, v in site_filters.items():
            mask &= (cm[_site_col(c)] == v)
        site_pivot, denom = build_cell_pivot(cm[mask])
        if sum(denom.values()) == 0:
            if project:
                warnings.append(f"Project={project} 未匹配到任何站点（site_caregory），NUR 分母为 0")
            else:
                desc = " ".join(f"{c}={v}" for c, v in site_filters.items())
                warnings.append(
                    f"站点筛选（{desc}）未圈定到任何站点（master_site_db），NUR 分母为 0")
    else:
        denom = cells_all

    today = date.today()
    nur_out: Dict[str, List[Dict]] = {}
    sla_out: Dict[str, List[Dict]] = {}

    for gran in GRANULARITIES:
        periods = enumerate_periods(gran, tt, start or None, end or None)
        col = {"daily": "day", "weekly": "week", "monthly": "month"}[gran]

        # NUR 分子：按期间×制式聚合小区分钟数（仅有效 MTTR 行）。
        # tech 单→全部计入对应制式；sitewide 单→按该站自身各制式小区数分别归属。
        num_df = df[df["mttr_valid"] & (df["cells_weight"] > 0)]
        num_map: Dict[str, Dict[str, float]] = {p: {t: 0.0 for t in TECHS} for p in periods}
        if not num_df.empty:
            is_sw = num_df["cls_kind"] == "sitewide"
            tech_part = num_df.loc[~is_sw & num_df["cls_tech"].isin(TECHS)]
            if not tech_part.empty:
                grp = (tech_part.groupby([col, "cls_tech"], observed=True)["cell_minutes"].sum())
                for (p, tech), v in grp.items():
                    if p in num_map:
                        num_map[p][tech] += float(v)
            sw_part = num_df.loc[is_sw]
            if not sw_part.empty:
                mttr = sw_part["mttr_min"].values
                for t in TECHS:
                    cm_t = sw_part[f"site_cells_{t}"].values * mttr
                    if not cm_t.any():
                        continue
                    grp_sw = (pd.DataFrame({col: sw_part[col].values, "cm": cm_t})
                              .groupby(col, observed=True)["cm"].sum())
                    for p, v in grp_sw.items():
                        if p in num_map:
                            num_map[p][t] += float(v)

        nur_rows = []
        for label, tech in [("Global_NUR", None)] + [(f"{t}_NUR", t) for t in TECHS]:
            row = {"metric": label}
            for p in periods:
                if tech is None:
                    numerator = sum(num_map[p].values())
                    cells = sum(denom.values())
                else:
                    numerator = num_map[p][tech]
                    cells = denom.get(tech, 0)
                gr = period_seconds(gran, p, today)
                row[p] = round(numerator * 60.0 / (cells * gr), 8) if cells > 0 else None
            nur_rows.append(row)
        nur_out[gran] = nur_rows

        # SLA：按期间×严重级别统计 Total / Pass / 达成率
        sub = df[df[col].notna()]
        sla_map: Dict[str, Dict[str, Tuple[int, int]]] = {
            p: {"__all__": (0, 0)} for p in periods}
        if not sub.empty:
            sev = _norm_series(sub["ticket_severity"]).where(
                _norm_series(sub["ticket_severity"]) != "", "Unknown")
            passed = (_norm_series(sub["sla_status"]) == "Pass")
            agg = (pd.DataFrame({"p": sub[col], "sev": sev, "pass": passed})
                   .groupby(["p", "sev"], observed=True)["pass"].agg(["count", "sum"]))
            for (p, sev_v), r in agg.iterrows():
                if p not in sla_map:
                    continue
                sla_map[p][sev_v] = (int(r["count"]), int(r["sum"]))
                tot, ps = sla_map[p]["__all__"]
                sla_map[p]["__all__"] = (tot + int(r["count"]), ps + int(r["sum"]))

        sevs = sorted(s for s in {v for pmap in sla_map.values() for v in pmap} if s != "__all__")
        sla_rows = []
        for sev in sevs + ["Total"]:
            key = "__all__" if sev == "Total" else sev
            total = sum(sla_map[p].get(key, (0, 0))[0] for p in periods)
            ps = sum(sla_map[p].get(key, (0, 0))[1] for p in periods)
            sla_rows.append({"metric": sev, "total": total, "within_sla": ps,
                             "achieve": round(ps / total, 4) if total else None})
            for p in periods:
                c, s = sla_map[p].get(key, (0, 0))
                sla_rows[-1][f"{p}__total"] = c
                sla_rows[-1][f"{p}__pass"] = s
                sla_rows[-1][f"{p}__achieve"] = round(s / c, 4) if c else None
        sla_out[gran] = sla_rows

    # ---- 站点级 NUR 达标占比（daily/monthly，PS_NUR_2G/3G 数据源）----
    site_nur_out: Dict[str, Dict[str, Dict[str, Optional[float]]]] = {}
    for gran in ("daily", "monthly"):
        col = {"daily": "day", "monthly": "month"}[gran]
        periods = enumerate_periods(gran, tt, start or None, end or None)
        site_nur_out[gran] = {}
        for t in TECHS:
            site_nur_out[gran][t] = _site_nur_ratio_for_tech(
                df, col, periods, site_pivot[t], t, gran, today)

    out = {
        "nur": nur_out,
        "sla": sla_out,
        "persite_nur": site_nur_out,
        "cells_by_tech": cells_all,
        "denominator_cells": denom,
        "tt_total": int(len(df)),
        "exclude": {k: v for k, v in ex_info.items() if k != "set"},
        "warnings": warnings,
        "cached": False,
        "elapsed_seconds": round(time.time() - t0, 2),
    }
    if not refresh_exclude:
        _result_cache[rkey] = {"at": time.time(), "data": out}
        if len(_result_cache) > 32:          # 容量保护：清掉最旧的一半
            for k in sorted(_result_cache, key=lambda x: _result_cache[x]["at"])[:16]:
                _result_cache.pop(k, None)
    return out


# ============================================================
# 下钻明细（单元格 → 构成该数值的 TT 明细）
# ============================================================
def compute_detail(metric: str = "nur", gran: str = "daily", period: str = "",
                   tech: str = "", severity: str = "", item: str = "",
                   vendor: str = "", project: str = "", exclude: str = "",
                   trm_type: str = "", site_caregory: str = "",
                   province_county: str = "", region: str = "",
                   max_rows: int = 2000) -> Dict:
    """下钻：返回构成某单元格数值的 TT 明细，筛选口径与 compute_overview 完全一致。

    - metric='nur' ：tech=Global/2G/3G/4G/5G；只返回计入 NUR 的行（mttr_valid 且
      小区数>0）：tech 单直接命中，sitewide 单按该站该制式小区数归属。
      输出附加 drill 列：tech（归属制式，sitewide 单标 SITEWIDE）、cells（归属小区数）。
    - metric='sla'：severity=P1~P4/Unknown/Total；item=total/achieve 返回全部，
      item=pass 仅 sla_status='Pass'。
    明细默认按 alarm_occur_time 降序（项目下钻规范）。
    """
    t0 = time.time()
    warnings: List[str] = []
    tt = load_tt_df()
    cm = load_cm_summary()
    if tt.empty:
        return {"rows": [], "count": 0, "warnings": ["eflow_tt 无数据"],
                "elapsed_seconds": round(time.time() - t0, 2)}
    if gran not in GRANULARITIES:
        raise ValueError(f"gran 必须是 {GRANULARITIES}，got {gran}")
    if metric not in ("nur", "sla"):
        raise ValueError(f"metric 必须是 nur/sla，got {metric}")

    # 站点四维过滤参数（与 overview 同源同口径；空串=不筛）
    site_filters = {c: _norm_str(v) for c, v in zip(
        SITE_FILTER_COLS, (trm_type, site_caregory, province_county, region))}
    site_filters = {c: v for c, v in site_filters.items() if v}

    # 下钻不走基础数据缓存（明细要读全列），站点属性索引现建：与缓存路径同一实现
    site_index = build_site_index(load_site_master())
    tt = attach_site_attrs(attach_cells(tt, build_cell_pivot(cm)[0]),
                           "site_id", "site_name", site_index)
    tt = enrich_periods(tt)

    # ---- 排除名单标记（与 compute_overview 相同口径）----
    ex_info = get_exclude_info()
    ex_set: Set[str] = ex_info.get("set") or set()
    if ex_set:
        tno = _norm_series(tt["ticket_no"])
        ttno = _norm_series(tt["tt_no"])
        tt["excluded"] = (tno.isin(ex_set) | ttno.isin(ex_set)).map({True: "Y", False: "N"})
    else:
        tt["excluded"] = "N"

    # ---- 筛选（与 overview 的分子口径一致）----
    df = tt
    if vendor in ("ZTE", "3RD"):
        df = df[df["vendor"] == vendor]
    if project:
        df = df[df["site_information"].map(_norm_str) == project]
    if exclude in ("Y", "N"):
        df = df[df["excluded"] == exclude]
    for c, v in site_filters.items():
        df = df[df[_site_col(c)] == v]
    col = {"daily": "day", "weekly": "week", "monthly": "month"}[gran]
    if period:
        df = df[df[col] == period]

    if metric == "nur":
        # 分子口径：仅有效 MTTR 且小区数>0 的行
        df = df[df["mttr_valid"] & (df["cells_weight"] > 0)]
        if tech and tech != "Global":
            df = df[(df["cls_tech"] == tech)
                    | ((df["cls_kind"] == "sitewide") & (df[f"site_cells_{tech}"] > 0))]
            df = df[df[f"site_cells_{tech}"] > 0]
            df["drill_tech"] = tech
            df["drill_cells"] = df[f"site_cells_{tech}"]
        else:
            df["drill_tech"] = np.where(df["cls_kind"] == "sitewide", "SITEWIDE", df["cls_tech"])
            df["drill_cells"] = df["cells_weight"]
    else:  # sla
        sev = _norm_series(df["ticket_severity"]).where(
            _norm_series(df["ticket_severity"]) != "", "Unknown")
        if severity and severity != "Total":
            df = df[sev == severity]
        if item == "pass":
            df = df[_norm_series(df["sla_status"]) == "Pass"]

    if len(df) > max_rows:
        warnings.append(f"明细超过 {max_rows} 行，仅返回前 {max_rows} 行")
        df = df.head(max_rows)

    out = df[["ticket_no", "tt_no", "title", "site_id", "site_name",
              "ticket_severity", "sla_status", "alarm_occur_time", "alarm_clear_time",
              "mttr_min", "excluded", "vendor"]].copy()
    if metric == "nur":
        out["tech"] = df["drill_tech"].values
        out["cells"] = df["drill_cells"].values
    # 保留原始 MTTR 精度（前端自行格式化），避免下钻明细汇总与 overview 数值出现舍入差异
    # NaN → None：未清除告警的 alarm_clear_time、空 ticket_no 等，JSON 不允许 NaN（starlette allow_nan=False）
    # 注意 pandas3 中 where(cond, None) 不生效，必须先 astype(object)
    out = out.astype(object).where(pd.notna(out), None)
    out = out.sort_values("alarm_occur_time", ascending=False)
    return {"rows": out.to_dict("records"), "count": int(len(out)),
            "warnings": warnings, "elapsed_seconds": round(time.time() - t0, 2)}

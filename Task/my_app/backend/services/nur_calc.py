# -*- coding: utf-8 -*-
"""
NUR / SLA 看板计算引擎
======================
数据源：主库 app.eflow_tt + app.cm_site_summary（DB_MODE=pg/sqlite 双模兼容，
经 backend.database.get_raw_connection 透明切换）。

口径
----
1. 告警归属（2026-10-05 改为**精确规则表** ALARM_RULES：告警段 → 制式）：
   - 单制式：2G/3G/4G CELL DOWN、2G/3G/4G SITE DOWN，以及 CELL INTERRUPTION
     ALARM→2G、CELL IS OUT OF SERVICE→3G、LTE CELL OUTAGE→4G；
     这些**只**计入本制式，不拆分到其他制式。
   - 整站：CSD/PSD/MW LINK DOWN/FIBER BREAK/SITE DOWN DUE TO POWER OFF 等，
     以及**所有未显式列出的告警**（业务口径：其余告警都算 2/3/4G/5G），
     按该站在 CM 中各制式的小区数**分别**归属（含 5G）。
   - 取段方式：title 最后一个 "]" 之后、upper + strip，**精确匹配整段**
     （不再用 "2G" in seg 之类子串匹配，避免 "DUEUtranCellFDDLTE" 误判）。
2. **小区数按站名取**（2026-10-05 修正，2G_NUR 恒为 0 的根因）：
   TT 的 site_id 是 4G 命名空间，同一站的 2G/3G 小区在 cm_site_summary 里
   属于**另一个 Site_ID**（如 JFK：2G=1397 / 3G=3397 / 4G=4397，TT 只存 4397）。
   故：先按**站名**查（同名多 ID 求和），查不到再回退按 site_id 查；
   两者都查不到 → **不参与计算**（如机房 VMAX-DC）。详见 build_name_pivot。
   分母仍按 site_id 汇总（实测与按站名汇总结果一致：3225/4627/7222/104）。
3. MTTR = (alarm_clear_time - alarm_occur_time) 分钟，剔除 <=0 或 >=43200；未清除不计 NUR
4. NUR_tech = Σ(小区数×MTTR)×60 / (分母小区数×GR)；GR 日=86400、周=604800、月=天数×86400
   （当期未过完按已过天数），输出原始数值（不乘 100）
5. 分母：默认全网该制式小区总数；Project 筛选生效时按 site_caregory 与站点类型
   归一化包含匹配圈定小区数（分子分母同口径）
6. SLA：ticket_severity 分组 Total / Within SLA(sla_status='Pass') / 达成率
7. 站点维度过滤（trm_type / site_caregory / province_county / region /
   starlink_recently_migrated，2026-09-30 新增，2026-10-05 增补 starlink）：
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

# ---------- 告警归属规则（业务口径表，2026-10-05） ----------
# 语义：告警段 → 该告警计入哪些制式的 outage。
#   "2G"/"3G"/"4G" : **只**计入该制式（单制式，不拆分到其他制式）
#   "SW"           : 整站类，按该站在 cm_site_summary 中各制式的小区数
#                    **分别**归属（2G/3G/4G/5G 四个制式都算）
#
# ⚠ 必须**精确匹配整个告警段**（title 最后一个 "]" 之后的部分，已 strip + upper），
#   不得再做 "2G" in seg 这类子串匹配：实测 4G 的原始小区类型串
#   "DUEUtranCellFDDLTE" 同时含 "UTRAN" 与 "LTE"，子串匹配会把制式判错。
#   段名大小写在不同链路下不一致，故键统一以 upper 形式存放，匹配前对段做 upper()。
#
# 覆盖实测：全表 37088 行命中 18 条显式规则 36612 行，其余走 FALLBACK_ATTR（=SW），
# 即**所有**告警都有归属，不再有"未匹配则丢弃"的情况。
ALARM_RULES: Dict[str, str] = {
    # ---- 单制式：小区/站点级，只算本制式 ----
    "2G CELL DOWN": "2G",
    "2G SITE DOWN": "2G",
    "3G CELL DOWN": "3G",
    "3G SITE DOWN": "3G",
    "4G CELL DOWN": "4G",
    "4G SITE DOWN": "4G",
    # 告警名里不含制式字样，但业务上确定归属单一制式（2026-10-05 明确）
    "CELL INTERRUPTION ALARM": "2G",
    "CELL IS OUT OF SERVICE": "3G",
    "LTE CELL OUTAGE": "4G",
    # ---- 整站类：拆到该站全部制式（含 5G） ----
    "BOARD POWER-OFF DUE TO OVERTEMPERATURE PROTECTION": "SW",
    "COMPLETE SITE DOWN (CSD)": "SW",
    "ETHERNET PHYSICAL (ETPI) LOS": "SW",
    "FIBER BREAK": "SW",
    "FIBER/LINK BREAK": "SW",
    "MW LINK DOWN": "SW",
    "OSPF NEIGHBOUR DOWN ALARM": "SW",
    "PARTIAL SITE DOWN (PSD)": "SW",
    "SITE DOWN DUE TO POWER OFF": "SW",
}

# 未在 ALARM_RULES 中显式列出的告警，一律按整站处理（业务口径：其余告警都算 2/3/4G/5G）。
FALLBACK_ATTR = "SW"

# 「整站」多制式归属的制式集合（含 5G——2026-10-05 由 2/3/4G 扩为 2/3/4G/5G）
SW_TECHS: Tuple[str, ...] = ("2G", "3G", "4G", "5G")

EXCLUDE_FTP_PATH = "/webroot/WEB-INF/reportlets/excel/TT_Exclude.xlsx"
EXCLUDE_CACHE_TTL = 1800  # 秒

_TT_COLS = ("title, ticket_no, tt_no, ticket_severity, sla_status, "
            "alarm_occur_time, alarm_clear_time, site_id, site_name, site_information")
_CM_COLS = ('"Site_ID", "Site_Name", "NumberOfCells", "Tech", "site_caregory"')

# ---------- 站点维度过滤（trm_type / site_caregory / province_county / region /
#            starlink_recently_migrated） ----------
# 属性来源固定为站点主数据 master_site_db（与 GISMap、TT&WO Dashboard 同一个真相源）；
# 元组顺序即前端下拉的展示顺序，也是 /options 下发的顺序。
# 各列取值形态不同但**统一走精确匹配**，因此共用同一套机制：
#   - trm_type / site_caregory / province_county / region 为多值分类；
#   - starlink_recently_migrated 是 Yes/No 二值列（2026-10-05 新增，实测 827 行中
#     Yes=48 / No=779，无大小写或空白变体，48 个 Yes 站点在 cm_site_summary 中均有
#     小区记录，故选中 Yes 时分母不会为 0）。
SITE_FILTER_COLS: Tuple[str, ...] = (
    "trm_type", "site_caregory", "province_county", "region",
    "starlink_recently_migrated",
)
_SITE_COLS = ("site_id, site_name, trm_type, site_caregory, province_county, region, "
              "starlink_recently_migrated")
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
# 站点维度过滤：主数据加载 / 索引 / 挂载 / 候选值
# ------------------------------------------------------------
# 为什么属性取自 master_site_db 而不是 cm_site_summary：
#   - cm_site_summary 只有 region / province_county / site_caregory 三列、没有
#     trm_type（实测 app.cm_site_summary 7 列）；若三列取自 cm、一列取自主数据，
#     分子与分母就可能落在两个不同的站点集合上，看板数字与下钻行数会对不上。
#   - master_site_db 是 GISMap / TT&WO Dashboard 共用的站点主数据（同一口径），
#     四列齐全（实测 827 行，site_id 无重复）。
# ============================================================
def load_site_master() -> pd.DataFrame:
    """读取站点主数据 master_site_db 的维度属性；列名统一转小写。"""
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
    """给数据帧挂上站点维度属性列 ``s_trm_type`` / ``s_site_caregory`` /
    ``s_province_county`` / ``s_region`` / ``s_starlink_recently_migrated``
    以及归属标志 ``s_matched``。

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
    """站点维度过滤的候选值（与过滤实现同源：master_site_db 精确匹配）。

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
    """加载排除名单。

    ==================== 2026-10-06 起改为「库优先」 ====================
    真相源从 FTP 上的 `TT_Exclude.xlsx` 改为数据库表 `app.tt_exclude`
    （人工上传维护，见 `services/tt_exclude.py`）。原因：xlsx 名单是隐形的、
    无法审计，且「拉取时间 ≠ 内容时间」会让人把「名单过时导致 NUR 全 0」
    误判成「算错了」（真实踩坑）。

    读取顺序：
      1. **库**（`tt_exclude.fetch_tickets()`）—— 正常路径，命中即返回；
      2. **FTP 兜底** —— 仅在表不可用/读失败时启用（如尚未建表的旧部署），
         行为与改造前一致，保证灰度期不中断；
      3. **旧缓存兜底** —— FTP 也失败时用上次成功结果，避免口径静默变化；
      4. **空集** —— 全部失败，显式标记 `fallback_empty` 并进 warnings。

    区分「库为空」与「库不可用」很重要：**空名单 = 没有任何单被排除**，
    会让 NUR 口径静默变化，调用方需据此告警，不能当成正常状态。
    """
    now = time.time()
    if not force_refresh and _exclude_cache.get("loaded_at") \
            and now - _exclude_cache["loaded_at"] < EXCLUDE_CACHE_TTL:
        return dict(_exclude_cache)

    info: Dict[str, object] = {
        "count": 0, "column": None, "loaded_at": None,
        "error": None, "source": "ftp", "set": set(),
    }

    # ---- 1) 库优先 ----
    try:
        from backend.services import tt_exclude as _tx
        tickets_db = _tx.fetch_tickets()
        if tickets_db is not None:
            meta = _tx.fetch_meta()
            if tickets_db:
                info.update(count=len(tickets_db), column="ticket_no", loaded_at=now,
                            set=tickets_db, source="db",
                            # 内容时间与上传人：页面显示它，取代原先误导性的「拉取时间」
                            import_time=meta.get("import_time"),
                            uploaded_by=meta.get("uploaded_by"),
                            source_file=meta.get("source_file"))
                _exclude_cache.update(info)
                return dict(info)
            # 表在但名单为空：**不是**正常状态，继续走 FTP 兜底并留下痕迹。
            # 若 FTP 也拿不到，最终会以空集返回 —— 此时 error 字段会说明原因。
            logger.warning("[NUR] tt_exclude 表存在但名单为空，尝试 FTP 兜底")
            info["error"] = "tt_exclude 表为空（可能尚未上传名单）"
    except Exception as e:  # noqa: BLE001 - 读库异常不应阻断页面
        logger.warning(f"[NUR] 读取 tt_exclude 表失败，降级 FTP: {e}")
        info["error"] = f"tt_exclude 读取失败: {e}"

    # ---- 2) FTP 兜底（灰度期兼容：尚未建表/表为空的部署）----
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
                    loaded_at=now, set=tickets, source="ftp")
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
    """返回 ('tech', '2G'|'3G'|'4G') / ('sitewide', None)。

    规则见 :data:`ALARM_RULES`：精确匹配告警段（最后一个 "]" 之后，upper + strip）；
    未命中显式规则时走 :data:`FALLBACK_ATTR`（= 整站），因此**不会**再出现
    "归不了制式、被静默排除" 的情况。

    注意：整站类的实际归属在 :func:`attach_cells` 里按该站各制式小区数展开，
    这里只给出"按制式"还是"按整站"两类语义。
    """
    seg = _norm_str(title).upper()
    if "]" in seg:
        seg = seg.rsplit("]", 1)[-1].strip()
    attr = ALARM_RULES.get(seg, FALLBACK_ATTR)
    if attr == "SW":
        return ("sitewide", None)
    return ("tech", attr)


def build_cell_pivot(cm: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """站点×制式小区数透视（Site_ID 主键索引，site_id 为空的行用站名回退键）。

    返回 (pivot: index=site_key, columns=2G/3G/4G/5G, 值=小区数,
          cells_by_tech: 全网每制式小区总数)。

    口径说明（2026-10-05）：本表按 **Site_ID** 汇总，用于 NUR 的**分母**（全网
    各制式小区总数）。分母按 ID 汇总与按站名汇总的实测结果完全一致
    （2G=3225 / 3G=4627 / 4G=7222 / 5G=104），故分母口径不变。
    **分子侧的小区数改用 :func:`build_name_pivot`**，原因见该函数注释。
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


def build_name_pivot(cm: pd.DataFrame) -> pd.DataFrame:
    """站名×制式小区数透视（index = **站名小写**，columns = 2G/3G/4G/5G）。

    为什么分子必须按**站名**取小区数（2026-10-05 修正的核心）：
    ``eflow_tt.site_id`` 存的是**4G 命名空间**的站点 ID，而同一物理站点在
    ``cm_site_summary`` 里按制式分属**不同 Site_ID**（末三位相同、首位不同）。
    实测样例：

    ===========  ==========  ==========  ==========
    站名         2G          3G          4G
    ===========  ==========  ==========  ==========
    JFK          1397(6)     3397(9)     4397(12)   ← TT 里只存 4397
    Palala       1092(3)     3092(6)     4092(3)
    Buttein      2211(1)     —           9211(1)
    ===========  ==========  ==========  ==========

    因此拿 TT 的 site_id 去配 2G 小区**永远配不到**（实测 2G 命中 0 个站点，
    导致 2G_NUR 恒为 0）；按站名配则命中 756 个。

    ⚠ **必须 groupby 求和，不能做表连接**：实测 839 个站名对应多个 Site_ID
    （最大扇出 5，如 'webo'）。若按站名 join，TT 行会翻 N 倍、分子被放大。
    """
    if cm.empty:
        return pd.DataFrame(0, index=pd.Index([], name="nm"), columns=TECHS)
    d = cm.copy()
    d["nm"] = _norm_series(d["site_name"]).str.lower()
    d["tech"] = _norm_series(d["tech"]).str.upper()
    d = d[(d["nm"] != "") & (d["tech"].isin(TECHS))]
    d["cells"] = pd.to_numeric(d["numberofcells"], errors="coerce").fillna(0).astype(int)
    if d.empty:
        return pd.DataFrame(0, index=pd.Index([], name="nm"), columns=TECHS)
    pivot = (d.groupby(["nm", "tech"], as_index=False)["cells"].sum()
              .pivot(index="nm", columns="tech", values="cells").fillna(0).astype(int))
    for t in TECHS:
        if t not in pivot.columns:
            pivot[t] = 0
    return pivot[TECHS]


def attach_cells(tt: pd.DataFrame, pivot: pd.DataFrame,
                 name_pivot: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """给每条 TT 行关联各制式小区数，并算出 NUR 分子用的小区数权重。

    **查找顺序（2026-10-05 业务口径）**：
    1. 先按 **站名小写**（``site_name``）在 ``name_pivot`` 中查该站各制式小区数
       —— 这是主路径（业务要求：「站点名字能在 cm_site_summary 找到，就按告警
       规则取相应制式的小区数」）；
    2. 站名查不到时，回退按 **site_id** 在 ``pivot`` 中查（救回 9 个站名有拼写
       差异、但 ID 能命中的站点，如 'forkelleh' / 'salayea'）；
    3. 两者都查不到 → 该行小区数为 0，**不参与 NUR 计算**
       （如 'VMAX-DC'（机房，非无线站点）/ 'HQ_Site' / 'ODC_Site' /
       'Jamaica Road' / 'Cocacola Co' / 'Duport Road Co' 共 6 个站点、
       361 条有效行会被排除）。

    反向的原因见 :func:`build_name_pivot`：TT 的 site_id 是 4G 命名空间，
    2G/3G 小区挂在同名的另一个 Site_ID 下，按 ID 配 2G 永远命中 0 个站点。

    新增列：
    - site_cells_2G..5G : 该站在各制式的小区数（未匹配为 0）
    - cells_weight      : 单制式行=该制式小区数；整站行=该站**全部**制式小区数之和
    - cells_matched     : 是否取到了小区数（0/1），供告警与下钻区分"未匹配"与"真 0"
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
    tt["site_name_key"] = site_name_n

    for t in TECHS:
        tt[f"site_cells_{t}"] = 0
    if pivot.empty and (name_pivot is None or name_pivot.empty):
        tt["cells_weight"] = 0
        tt["cells_matched"] = 0
        return tt

    # ---- 主路径：按站名查（同名多 ID 已在 name_pivot 里求和，不会扇出）----
    by_name = None
    if name_pivot is not None and not name_pivot.empty:
        by_name = name_pivot.reindex(site_name_n.values).fillna(0).astype(int)
        by_name.index = tt.index
    # ---- 回退：按 site_id 查 ----
    by_id = pivot.reindex(site_key.values).fillna(0).astype(int)
    by_id.index = tt.index

    name_ok = by_name is not None and by_name[TECHS].sum(axis=1).values > 0
    for t in TECHS:
        if by_name is not None:
            tt[f"site_cells_{t}"] = np.where(name_ok, by_name[t].values, by_id[t].values)
        else:
            tt[f"site_cells_{t}"] = by_id[t].values

    # pv 取的是刚写入的 site_cells_* 列（列名带制式后缀，与裸制式名不同）
    pv = tt[[f"site_cells_{t}" for t in TECHS]]
    tech_arr = tt["cls_tech"].values
    vals = np.where(
        tt["cls_kind"].values == "sitewide",
        pv.sum(axis=1).values,          # 整站：该站全部制式小区数之和
        np.select(
            [tech_arr == t for t in TECHS],
            [pv[f"site_cells_{t}"].values for t in TECHS],
            default=0,
        ),
    )
    tt["cells_weight"] = vals.astype(int)
    tt["cells_matched"] = (tt["cells_weight"] > 0).astype(int)
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

    ⚠ 站点维度**按站名小写**（``site_name_key``）聚合，与分子侧 attach_cells 的
    站名优先查找保持一致（2026-10-05）。若沿用 site_id 聚合，2G 会因
    「TT 存 4G ID、2G 小区挂另一个 ID」而全部落空，达标率恒为 1.0（100%）。
    """
    denom_sites = site_cells[site_cells > 0]
    if denom_sites.empty:
        return {p: None for p in periods}
    d = df[df["mttr_valid"]].copy()
    # 站名键由 attach_cells 预存；外部传入未处理 df 时兜底重算
    if "site_name_key" not in d.columns:
        d["site_name_key"] = _norm_series(d["site_name"]).str.lower()
    d = d[d["site_name_key"] != ""]
    if d.empty:
        return {p: 1.0 for p in periods}

    # 分子：tech 单按 (期间, 站名) 聚合；sitewide 单按该站该制式小区数拆分。
    # 增量合并而非从空 Series 起步，避免 pandas3 空 Series 与 MultiIndex add 时
    #  “cannot join with no overlapping index names” 报错。
    site_col = "site_name_key"
    tech_part = d[(d["cls_kind"] == "tech") & (d["cls_tech"] == tech)]
    num = (tech_part.groupby([col, site_col], observed=True)["cell_minutes"].sum()
           if not tech_part.empty else None)
    sw = d[d["cls_kind"] == "sitewide"]
    if not sw.empty:
        cmt = sw[f"site_cells_{tech}"].values * sw["mttr_min"].values
        g2 = (pd.DataFrame({col: sw[col].values, site_col: sw[site_col].values,
                            "cm": cmt})
              .groupby([col, site_col], observed=True)["cm"].sum())
        num = g2 if num is None else num.add(g2, fill_value=0)
    if num is None or num.empty:
        # 当期无任何故障：全部站点达标
        return {p: 1.0 for p in periods}

    # 全格展开：无故障站点 reindex 后为 0（NUR=0 达标）
    idx = pd.MultiIndex.from_product([periods, denom_sites.index],
                                     names=[col, site_col])
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
    """返回 (enriched_tt, cm, site_pivot, cells_all, site_index, name_pivot)，带 TTL 缓存。

    - enriched_tt / cm 都已挂上站点维度属性列（``s_trm_type`` 等，见 attach_site_attrs）；
    - site_index 是站点主数据索引，供下钻（compute_detail）等非缓存路径复用；
    - name_pivot 是「站名×制式小区数」表，分子侧关联用（见 build_name_pivot）。

    ⚠ 调用方**不得就地修改**返回的 tt / cm（要加列请先 ``.copy()``），否则会污染缓存。
    """
    def _fresh() -> bool:
        at = _base_cache.get("at")
        return bool(at) and (time.time() - float(at)) < BASE_CACHE_TTL  # type: ignore[arg-type]

    if not force and _fresh():
        return (_base_cache["tt"], _base_cache["cm"], _base_cache["site_pivot"],
                _base_cache["cells_all"], _base_cache["site_index"],
                _base_cache["name_pivot"])
    with _base_lock:
        if not force and _fresh():          # 双检：并发下只重建一次
            return (_base_cache["tt"], _base_cache["cm"], _base_cache["site_pivot"],
                    _base_cache["cells_all"], _base_cache["site_index"],
                    _base_cache["name_pivot"])
        t0 = time.time()
        tt = load_tt_df()
        cm = load_cm_summary()
        site_index = build_site_index(load_site_master())
        site_pivot, cells_all = build_cell_pivot(cm)
        name_pivot = build_name_pivot(cm)
        # 站点属性：TT 行与 CM 行走**同一份索引**，分子分母必然落在同一批站点上
        cm = attach_site_attrs(cm, "site_id", "site_name", site_index)
        if not tt.empty:
            tt = attach_site_attrs(attach_cells(tt, site_pivot, name_pivot),
                                   "site_id", "site_name", site_index)
            tt = enrich_periods(tt)
        _base_cache.update({"at": time.time(), "tt": tt, "cm": cm,
                            "site_pivot": site_pivot, "cells_all": cells_all,
                            "site_index": site_index, "name_pivot": name_pivot})
        logger.info("[NUR] 基础数据已重建 %.0fms (tt=%d 行)",
                    (time.time() - t0) * 1000, len(tt))
        return tt, cm, site_pivot, cells_all, site_index, name_pivot


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
def _collect_site_filters(**kwargs) -> Dict[str, str]:
    """把请求参数里的站点维度筛选项收成 {列: 值}，空值一律丢弃。

    ⚠ 键名必须落在 :data:`SITE_FILTER_COLS` 内（列名是代码常量，不来自请求输入，
    因此下游拼 SQL / 取列名没有注入面）。传了不在白名单里的键会被忽略。
    """
    out: Dict[str, str] = {}
    for c in SITE_FILTER_COLS:
        v = _norm_str(kwargs.get(c))
        if v:
            out[c] = v
    return out


def compute_overview(vendor: str = "", project: str = "", exclude: str = "",
                     start: str = "", end: str = "",
                     refresh_exclude: bool = False,
                     trm_type: str = "", site_caregory: str = "",
                     province_county: str = "", region: str = "",
                     starlink_recently_migrated: str = "") -> Dict:
    """一次计算 6 张表：nur/sla × daily/weekly/monthly。

    筛选适配原则：Vendor/时间/Exclude 只作用于分子（TT 行）；
    Project 同时作用于分子（site_information）与分母（site_caregory 圈定小区数）；
    站点维度（trm_type / site_caregory / province_county / region /
    starlink_recently_migrated）同样**同时作用于分子与分母**（属性取自主数据
    master_site_db，精确匹配）—— 只筛分子会让 NUR 的分子分母不同口径，
    比值不再是「这批站点的不可用率」。
    """
    t0 = time.time()
    warnings: List[str] = []

    site_filters = _collect_site_filters(
        trm_type=trm_type, site_caregory=site_caregory,
        province_county=province_county, region=region,
        starlink_recently_migrated=starlink_recently_migrated)

    rkey = "|".join([vendor, project, exclude, start, end,
                     *[f"{c}={site_filters.get(c, '')}" for c in SITE_FILTER_COLS]])
    if not refresh_exclude:
        hit = _result_cache.get(rkey)
        if hit and (time.time() - hit["at"]) < RESULT_CACHE_TTL:
            out = dict(hit["data"])
            out["cached"] = True
            out["elapsed_seconds"] = round(time.time() - t0, 3)
            return out

    tt, cm, site_pivot, cells_all, _site_index, name_pivot = get_base_data()
    if tt.empty:
        # 键集合与正常返回保持一致（tt_total / warning_details 都要给），
        # 否则前端在两条路径上要写两套判空逻辑。
        return {"nur": {}, "sla": {}, "cells_by_tech": {}, "denominator_cells": {},
                "exclude": get_exclude_info(refresh_exclude), "warnings": ["eflow_tt 无数据"],
                "warning_details": [], "tt_total": 0,
                "elapsed_seconds": round(time.time() - t0, 2)}

    # 基础表来自共享缓存：下面要加 "excluded" 列，必须先复制，否则污染后续请求
    tt = tt.copy()

    # ---- 排除名单标记 ----
    # 语义（2026-10-06 按业务确认修正，**与修正前相反，别改回去**）：
    #   exclude=空值 → 全部参与计算，**完全不看** TT_Exclude；
    #   exclude=N    → 全部参与计算，不看 TT_Exclude（与空值同义）；
    #   exclude=Y    → 从**全部**里**扣掉**名单内的单（"排除掉它们"之后剩下的）。
    #
    # ⚠ 修正前的实现是 `df[df["excluded"] == exclude]`，即 Y=只保留名单内、
    #   N=只保留名单外 —— 那是"筛选出名单"而不是"排除名单"，方向正好反了。
    #   实测（名单 46 单全在 2026-08-03~09）：旧实现 Y=46 / N=1061，
    #   而业务要的是 Y=1061（扣掉名单）/ N=1107（全部）。这是**用户报的真 bug**。
    #
    # 空名单时 Y 扣掉空集 = 全部，三档自然一致，不会出现"全 0 页面"让人误以为系统坏了。
    ex_info = get_exclude_info(refresh_exclude)
    ex_set: Set[str] = ex_info.get("set") or set()
    if ex_info.get("error"):
        warnings.append(f"Exclude 名单: {ex_info['error']}")
    if ex_set:
        tno = _norm_series(tt["ticket_no"])
        ttno = _norm_series(tt["tt_no"])
        tt["excluded"] = (tno.isin(ex_set) | ttno.isin(ex_set)).map({True: "Y", False: "N"})
    else:
        # 名单不可用/为空：没有任何单需要被扣掉，全部视为"未排除"
        tt["excluded"] = "N"

    # ---- 筛选（分子口径）----
    df = tt
    if vendor in ("ZTE", "3RD"):
        df = df[df["vendor"] == vendor]
    if project:
        df = df[df["site_information"].map(_norm_str) == project]
    # 空值与 N 都是"全部不看名单"；只有 Y 才扣掉名单内的单
    if exclude == "Y":
        df = df[df["excluded"] != "Y"]
    # 站点维度过滤：精确匹配（与 /options 下发的候选值同源），不用 LIKE ——
    # 概览与下钻必须逐字同口径，否则「表里的数」与「下钻的行数」对不上。
    for c, v in site_filters.items():
        df = df[df[_site_col(c)] == v]
    if start:
        df = df[(df["occur_dt"] >= pd.to_datetime(start))]
    if end:
        df = df[(df["occur_dt"] <= pd.to_datetime(end) + pd.Timedelta(days=1))]

    # ---- 分母小区数（Project / 站点维度生效时按同一批站点圈定）----
    # site_pivot 同时供站点级 NUR 达标占比使用（分母站点集合与全网分母同口径）
    # 注：未筛选的 site_pivot/cells_all 已随基础数据缓存，无需重复透视
    if (project or site_filters) and not cm.empty:
        # cm 上的站点属性已随基础数据挂好（与分子同一份索引）
        mask = pd.Series(True, index=cm.index)
        if project:
            mask &= cm["site_caregory"].map(lambda v: _cat_match(_norm_str(v), project))
        for c, v in site_filters.items():
            mask &= (cm[_site_col(c)] == v)
        cm_scoped = cm[mask]
        site_pivot, denom = build_cell_pivot(cm_scoped)
        # ⚠ name_pivot 必须与 site_pivot 用**同一批站点**重建：分子按站名取小区数，
        # 若沿用未筛选的全量 name_pivot，筛选生效时分子会取到范围外站点的小区数，
        # 与分母口径不一致（正是本文件反复强调的「分子分母同口径」纪律）。
        name_pivot = build_name_pivot(cm_scoped)
        if sum(denom.values()) == 0:
            if project:
                warnings.append(f"Project={project} 未匹配到任何站点（site_caregory），NUR 分母为 0")
            else:
                desc = " ".join(f"{c}={v}" for c, v in site_filters.items())
                warnings.append(
                    f"站点筛选（{desc}）未圈定到任何站点（master_site_db），NUR 分母为 0")
    else:
        denom = cells_all

    # ---- 未匹配站点告警（2026-10-05）----
    # 业务口径：站名在 cm_site_summary 查不到、且 site_id 也兜不住的行**不参与计算**。
    # 这类行以前会静默变成 0（2G_NUR 恒为 0 就是这么被当成"算错了"的），
    # 故显式暴露数量与站点名，避免再次出现"看起来是 0、其实是没匹配上"。
    #
    # 站点名清单同时以**结构化形式**放进 warning_details：告警文案里只放前 8 个加省略号，
    # 而实际情况可达 26 个站点，用户需要能展开看全（前端做成可点击弹层）。
    # 不要把全量塞进文案字符串 —— 那样告警条会被撑成一大段，且前端无法做展开/搜索。
    warning_details: List[Dict] = []
    if not df.empty:
        unmatched = df[df["cells_weight"] == 0]
        if not unmatched.empty:
            bad_names = sorted({_norm_str(v) for v in unmatched["site_name"].unique() if _norm_str(v)})
            preview = "、".join(bad_names[:8]) + ("…" if len(bad_names) > 8 else "")
            warnings.append(
                f"{len(unmatched)} 条告警的站点在 cm_site_summary 中找不到小区信息"
                f"（{len(bad_names)} 个站点：{preview}），已按业务口径排除，不计入 NUR")
            # 按站点给出「行数 + 各自告警量」，点开弹层即知哪个站点影响最大
            cnt = unmatched["site_name"].map(_norm_str).value_counts()
            warning_details.append({
                "kind": "unmatched_sites",
                "title": f"{len(unmatched)} 条告警 / {len(bad_names)} 个站点未匹配到小区信息",
                "note": "这些站点在 cm_site_summary 中按站名与 site_id 都查不到小区数，"
                        "按业务口径整行排除，不计入 NUR（分子分母都不含）。",
                "rows": len(unmatched),
                "sites": [{"name": n, "rows": int(cnt.get(n, 0))} for n in bad_names],
            })

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
            # 分母传**按站名**索引的该制式小区数（与分子侧站名聚合同口径）；
            # name_pivot 已在上面按同一批筛选站点重建过（见分母段）
            site_nur_out[gran][t] = _site_nur_ratio_for_tech(
                df, col, periods,
                name_pivot[t] if t in name_pivot.columns
                else pd.Series(0, index=pd.Index([], name="nm")),
                t, gran, today)

    out = {
        "nur": nur_out,
        "sla": sla_out,
        "persite_nur": site_nur_out,
        "cells_by_tech": cells_all,
        "denominator_cells": denom,
        "tt_total": int(len(df)),
        "exclude": {k: v for k, v in ex_info.items() if k != "set"},
        "warnings": warnings,
        # 告警的结构化明细（当前只有 unmatched_sites 一种）；前端据此做「点击看全部站点」弹层。
        # 与 warnings 文案**并列**而非替代：文案供日志/接口消费者，details 供界面展开。
        "warning_details": warning_details,
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
                   starlink_recently_migrated: str = "",
                   start: str = "", end: str = "",
                   max_rows: int = 2000) -> Dict:
    """下钻：返回构成某单元格数值的 TT 明细，筛选口径与 compute_overview 完全一致。

    - metric='nur' ：tech=Global/2G/3G/4G/5G；只返回计入 NUR 的行（mttr_valid 且
      小区数>0）：tech 单直接命中，sitewide 单按该站该制式小区数归属。
      输出附加 drill 列：tech（归属制式，sitewide 单标 SITEWIDE）、cells（归属小区数）。
    - metric='sla'：severity=P1~P4/Unknown/Total；item=total/achieve 返回全部，
      item=pass 仅 sla_status='Pass'。
    - start/end：与 compute_overview 同一时间字段（occur_dt）、同一含端语义
      （end 含当日，+1 天）。**缺了它**，weekly/monthly 单元格会被概览裁到用户选的
      时间窗、而下钻按 period 标签返回**整个 ISO 周/自然月**，行数与表格数字对不上
      （2026-10-06 实测：窗口 2026-08-01~08-31 时 W31 概览 2 / 下钻 1259）。
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

    # 站点维度过滤参数（与 overview 同源同口径；空串=不筛）
    site_filters = _collect_site_filters(
        trm_type=trm_type, site_caregory=site_caregory,
        province_county=province_county, region=region,
        starlink_recently_migrated=starlink_recently_migrated)

    # 下钻不走基础数据缓存（明细要读全列），站点属性索引现建：与缓存路径同一实现。
    # ⚠ name_pivot 必须一起传：下钻的 cells_weight / site_cells_* 若与概览算法不同，
    #   「表格里的数字」与「下钻的行数」就会对不上（本文件反复强调的纪律）。
    site_index = build_site_index(load_site_master())
    tt = attach_site_attrs(
        attach_cells(tt, build_cell_pivot(cm)[0], build_name_pivot(cm)),
        "site_id", "site_name", site_index)
    tt = enrich_periods(tt)

    # ---- 排除名单标记（与 compute_overview 相同口径，含 2026-10-06 的语义修正）----
    ex_info = get_exclude_info()
    ex_set: Set[str] = ex_info.get("set") or set()
    if ex_set:
        tno = _norm_series(tt["ticket_no"])
        ttno = _norm_series(tt["tt_no"])
        tt["excluded"] = (tno.isin(ex_set) | ttno.isin(ex_set)).map({True: "Y", False: "N"})
    else:
        tt["excluded"] = "N"

    # ---- 筛选（与 overview 的分子口径一致）----
    # 空值与 N 都是"全部不看名单"；只有 Y 才扣掉名单内的单（见 compute_overview 的说明）
    df = tt
    if vendor in ("ZTE", "3RD"):
        df = df[df["vendor"] == vendor]
    if project:
        df = df[df["site_information"].map(_norm_str) == project]
    if exclude == "Y":
        df = df[df["excluded"] != "Y"]
    for c, v in site_filters.items():
        df = df[df[_site_col(c)] == v]
    # ⚠ 时间窗必须与 compute_overview:933-936 逐字同口径（同字段 occur_dt、同含端 +1 天）。
    #   缺了它时下面的 period 全等只能定位「整个 ISO 周 / 自然月」，
    #   会把用户时间窗之外的行一并返回（2026-10-06 实测 W31 概览 2 / 下钻 1259）。
    if start:
        df = df[df["occur_dt"] >= pd.to_datetime(start)]
    if end:
        df = df[df["occur_dt"] <= pd.to_datetime(end) + pd.Timedelta(days=1)]
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
        # 概览在算 SLA 时先剔掉「期间标签为空」的行（:1041 `df[df[col].notna()]`），
        # 即 alarm_occur_time 解析不出该粒度桶的行不计入 total。下钻必须同口径，
        # 否则这些行会被下钻算进去而概览不算（2026-10-06 实测 W31 概览 2 / 下钻 335）。
        df = df[df["occur_dt"].notna()]
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

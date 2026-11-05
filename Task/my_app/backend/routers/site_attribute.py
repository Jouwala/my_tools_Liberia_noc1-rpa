# -*- coding: utf-8 -*-
"""
site_attribute.py - 站点属性查询 API
==================================
GET /api/site-attribute?site=xxx     查单个站点的属性（是否 VIP / 站点类型 / 是否枢纽站…）

为什么需要这个接口
------------------
2026-11-03 实测故障：问「站点 lofa bridge 是 VIP 站点吗」，机器人答
「是 VIP 站点，依据 assetType 为 vipSite」—— **结论错、依据错、来源错**：

* 结论错：Lofa Bridge 的 ``vipsite`` 实为 ``No``（三处独立数据源一致）。
* 依据错：``assetType`` 的合法取值只有 NORMAL / COOL / ERA，**没有 vipSite**；
  VIP 是**独立字段** ``vipSite``（1=是 0=否）。模型把两个字段揉成了一个。
* 来源错：答的是「级别怎么按 vipSite 定」的**规则文档**，里面一个站点名都没有；
  全库 40 篇文档检索 ``lofa`` 零命中，检索分数 0.73 纯属「vip / site」词面撞车。

根因是**知识库里根本没有站点实体数据** —— 站点属性在数据库里，不在语料里。
本接口把站点属性变成一条**可查的事实**，让机器人不必再从规则反推。

三处数据源与口径
----------------
VIP 判定在三处都有，**以 eflow_site 为主**，另两处交叉验证：

============  ==================  ==========  ==========================
表            字段                取值        含义
============  ==================  ==========  ==========================
eflow_site    vipsite             Yes / No   eFlow 侧的站点属性（主口径）
master_site_db vip_site           Y / N      主站表维护的 VIP 标记
vip_site_list （整表即名单）       —          独立维护的 VIP 站名单
============  ==================  ==========  ==========================

⚠️ **三处不一致时必须如实报告冲突，不能挑一个顺眼的报。**
``consistency`` 字段会返回 ``agree`` / ``conflict`` / ``single_source``，
调用方（机器人）拿到 conflict 时应当把分歧原样说出来。

列名的方言差异（**本文件的核心难点**）
--------------------------------------
同一张表在两种后端下列名完全不同，实测：

* PG（生产库，schema ``app``）：``site_id`` / ``site_name`` / ``vipsite`` …
* SQLite（本地副本 app.db）：``"Site ID"`` / ``"Site Name"`` / ``vipsite`` …

所以**不能硬编码列名**。本文件用 :func:`table_columns` 探测实际列名，
按「候选列名列表」逐个试，第一个命中的就用它。这样 PG / SQLite 都能跑，
以后上游再加一层命名变体也能扛住。

存储
----
``get_raw_connection()`` 自动分派：PG 模式走生产库（实时），sqlite 模式走
``db/app.db`` 副本（有延迟）。本接口在两种模式下都能工作，调用方可从
返回的 ``source`` 字段看出来源。
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names, table_columns

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["site_attribute"])


# ---------------------------------------------------------------- 表结构探测

#: eflow_site 里各逻辑字段的候选列名（按优先级）。
#: PG 用蛇形，SQLite 副本用标题式，故每项给多个候选。
_EFLOW_SITE_COLS = {
    "site_id": ["site_id", "Site ID"],
    "site_name": ["site_name", "Site Name"],
    "region": ["region", "Region"],
    "province": ["province_county", "Province"],
    "site_type": ["site_type", "Site Type"],
    "vipsite": ["vipsite", "VIPSite", "vip_site"],
    "sitesubtype": ["sitesubtype", "SiteSubType", "site_sub_type"],
    "hubsite": ["hubsite", "HubSite", "hub_site"],
    "site_information": ["site_information", "Site Information"],
    "site_priority": ["site_priority", "Site Priority"],
    "site_class": ["site_class", "Site Class"],
    "ran_site": ["ran_site", "Ran Site"],
    "victims": ["victims", "Victims"],
    "fme_name": ["updated_fme_name_new", "FME Name", "fme_name"],
    "sync_time": ["_sync_time", "Sync Time"],
}

#: master_site_db 里各逻辑字段的候选列名。
_MASTER_SITE_COLS = {
    "site_id": ["site_id", "Site ID"],
    "site_name": ["site_name", "Site Name"],
    "region": ["region", "Region"],
    "province": ["province_county", "Province"],
    "site_type": ["site_type", "Site Type"],
    "vip_site": ["vip_site", "VIPSite", "vipsite"],
    "hub_site": ["hub_site", "HubSite", "hubsite"],
    "site_caregory": ["site_caregory", "Site Category"],
    "victims": ["victims", "Victims"],
    "fme_name": ["fme_name", "FME Name"],
    "latitude": ["latitude", "Latitude"],
    "longitude": ["longitude", "Longitude"],
}

#: vip_site_list 里各逻辑字段的候选列名。
_VIP_LIST_COLS = {
    "site_id": ["site_id", "Site ID"],
    "site_name": ["site_name", "Site Name"],
    "region": ["region", "Region"],
    "province": ["province_county", "Province"],
    "victims": ["victims", "Victims"],
}


def _resolve_cols(conn, table, spec):
    """把「逻辑字段 → 实际列名」解析出来。

    :param spec: 形如 ``{"vipsite": ["vipsite", "VIPSite"], ...}``
    :return: ``{逻辑字段: 实际列名}``；该表不存在的逻辑字段直接不出现。
    """
    try:
        have = set(table_columns(conn, table))
    except Exception:  # noqa: BLE001 - 表不存在/无权限都归为「取不到」
        logger.warning("[SITE-ATTR] 读取 %s 列信息失败", table, exc_info=True)
        return {}
    out = {}
    for logical, candidates in spec.items():
        for c in candidates:
            if c in have:
                out[logical] = c
                break
    return out


def _pick(row, cols, logical):
    """按解析出的列名取值；列不存在返回 None。"""
    col = cols.get(logical)
    if not col:
        return None
    try:
        return row[col]
    except (KeyError, IndexError, TypeError):
        return None


def _norm_yesno(value):
    """把 Yes/No、Y/N、1/0、True/False 归一成 True / False / None（未知）。

    ⚠️ **无法识别的值一律返回 None（未知），绝不猜。**
    站点属性是结论性字段，猜错比说「不知道」危害大得多。
    """
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("yes", "y", "1", "true", "t"):
        return True
    if s in ("no", "n", "0", "false", "f"):
        return False
    return None


def _like_pattern(name):
    """站名模糊匹配用的 pattern（同时匹配小写与原样）。

    站点名在两个库里的大小写写法不统一（``Lofa Bridge`` / ``LOFA BRIDGE``），
    所以用 LOWER() 比较。``%`` / ``_`` 需转义，避免站名里的下划线变成通配符。
    """
    escaped = (
        str(name).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped.lower()}%"


# ---------------------------------------------------------------- 主查询

def _query_eflow_site(conn, site):
    """查 eflow_site（主口径）。返回命中行列表。"""
    tables = set(list_table_names(conn))
    if "eflow_site" not in tables:
        return [], {}
    cols = _resolve_cols(conn, "eflow_site", _EFLOW_SITE_COLS)
    if "site_name" not in cols:
        return [], cols

    name_col = cols["site_name"]
    sql = f'SELECT * FROM "eflow_site" WHERE LOWER("{name_col}") LIKE ?'
    rows = conn.execute(sql, (_like_pattern(site),)).fetchall()
    return list(rows), cols


def _query_master_site(conn, site):
    """查 master_site_db（交叉验证源）。返回命中行列表。"""
    tables = set(list_table_names(conn))
    if "master_site_db" not in tables:
        return [], {}
    cols = _resolve_cols(conn, "master_site_db", _MASTER_SITE_COLS)
    if "site_name" not in cols:
        return [], cols

    name_col = cols["site_name"]
    sql = f'SELECT * FROM "master_site_db" WHERE LOWER("{name_col}") LIKE ?'
    rows = conn.execute(sql, (_like_pattern(site),)).fetchall()
    return list(rows), cols


def _query_vip_list(conn, site):
    """查 vip_site_list（独立 VIP 名单）。返回命中的站名列表。"""
    tables = set(list_table_names(conn))
    if "vip_site_list" not in tables:
        return [], {}
    cols = _resolve_cols(conn, "vip_site_list", _VIP_LIST_COLS)
    if "site_name" not in cols:
        return [], {}

    name_col = cols["site_name"]
    sql = f'SELECT * FROM "vip_site_list" WHERE LOWER("{name_col}") LIKE ?'
    rows = conn.execute(sql, (_like_pattern(site),)).fetchall()
    return list(rows), cols


def _exact_match(rows, cols, site):
    """从模糊命中里挑**完全相等**（忽略大小写）的那一行。

    模糊匹配可能命中「Lofa Bridge Camp」这类同前缀的站；属性结论要精确，
    所以优先用完全相等的行，没有再用第一条模糊命中。
    """
    target = str(site).strip().lower()
    name_col = cols.get("site_name")
    if not name_col:
        return rows[0] if rows else None
    for r in rows:
        try:
            if str(r[name_col] or "").strip().lower() == target:
                return r
        except (KeyError, IndexError, TypeError):
            break
    return rows[0] if rows else None


# ---------------------------------------------------------------- 响应组装

def _build_payload(site, eflow_rows, eflow_cols, master_rows, master_cols,
                   vip_rows, vip_cols, source):
    """把三处查询结果归一化成一份站点属性。"""
    eflow = _exact_match(eflow_rows, eflow_cols, site)
    master = _exact_match(master_rows, master_cols, site)

    # ---- 三处 VIP 判定 ----
    eflow_vip = _norm_yesno(_pick(eflow, eflow_cols, "vipsite")) if eflow else None
    master_vip = _norm_yesno(_pick(master, master_cols, "vip_site")) if master else None
    list_vip = True if vip_rows else None  # 在名单里 = 是 VIP

    votes = [v for v in (eflow_vip, master_vip, list_vip) if v is not None]
    if not votes:
        is_vip = None
        consistency = "unknown"
    elif len(set(votes)) == 1:
        is_vip = votes[0]
        consistency = "agree" if len(votes) > 1 else "single_source"
    else:
        is_vip = eflow_vip if eflow_vip is not None else master_vip
        consistency = "conflict"

    # ---- 主口径字段（eflow_site 优先，master_site_db 补位）----
    def field(logical):
        v = _pick(eflow, eflow_cols, logical) if eflow else None
        if v in (None, ""):
            v = _pick(master, master_cols, logical) if master else None
        return v

    name = _pick(eflow, eflow_cols, "site_name") if eflow else None
    if not name and master:
        name = _pick(master, master_cols, "site_name")

    site_id = _pick(eflow, eflow_cols, "site_id") if eflow else None
    if site_id in (None, "") and master:
        site_id = _pick(master, master_cols, "site_id")

    # hubsite / hub_site 命名在两表不同，且 master 侧只有 hub_site
    hub = _norm_yesno(_pick(eflow, eflow_cols, "hubsite")) if eflow else None
    if hub is None and master:
        hub = _norm_yesno(_pick(master, master_cols, "hub_site"))

    sync_time = _pick(eflow, eflow_cols, "sync_time") if eflow else None

    return {
        "site": str(site),
        "found": bool(eflow or master or vip_rows),
        "site_id": site_id,
        "site_name": name,
        "is_vip": is_vip,
        "consistency": consistency,
        "vip_sources": {
            "eflow_site": eflow_vip,
            "master_site_db": master_vip,
            "vip_site_list": list_vip,
        },
        "site_type": field("site_type"),
        "site_sub_type": field("sitesubtype"),
        "is_hub_site": hub,
        "region": field("region"),
        "province": field("province"),
        "site_information": field("site_information"),
        "site_priority": field("site_priority"),
        "site_class": field("site_class"),
        "is_ran_site": _norm_yesno(field("ran_site")),
        "victims": field("victims"),
        "fme_name": field("fme_name"),
        "latitude": field("latitude"),
        "longitude": field("longitude"),
        "sync_time": sync_time,
        "source": source,
    }


# ---------------------------------------------------------------- 路由

@router.get("/site-attribute")
def get_site_attribute(
    site: str = Query(..., min_length=1, max_length=120,
                       description="站点名或站号（模糊匹配，忽略大小写）"),
):
    """查单个站点的属性：是否 VIP、站点类型、是否枢纽站等。

    返回 ``is_vip``（True/False/null=未知）、``consistency``
    （agree / conflict / single_source / unknown）以及 ``vip_sources``
    （三处判定的原始值），便于调用方在数据源打架时如实说明。

    查无此站时返回 ``found: false``，**不是 404** —— 「查无此站」本身就是一个
    有效答案（机器人要告诉用户「站名可能写错了」），不该被当成接口错误。
    """
    site = str(site).strip()
    if not site:
        raise HTTPException(status_code=400, detail="站点名不能为空")

    try:
        with get_raw_connection() as conn:
            eflow_rows, eflow_cols = _query_eflow_site(conn, site)
            master_rows, master_cols = _query_master_site(conn, site)
            vip_rows, vip_cols = _query_vip_list(conn, site)
    except Exception as e:  # noqa: BLE001
        logger.error("[SITE-ATTR] 查询站点属性失败: %s", site, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询站点属性失败：{e}")

    payload = _build_payload(
        site, eflow_rows, eflow_cols, master_rows, master_cols,
        vip_rows, vip_cols, source="live",
    )
    if not payload["found"]:
        # 查无此站：把三个来源各自的命中情况如实带回，便于排查「是不是写错了」。
        payload["candidates"] = _candidates(eflow_rows, eflow_cols,
                                            master_rows, master_cols)
    return payload


def _candidates(eflow_rows, eflow_cols, master_rows, master_cols):
    """查无此站时，给几个相近的站名供用户核对。"""
    out = []
    for rows, cols in ((eflow_rows, eflow_cols), (master_rows, master_cols)):
        name_col = cols.get("site_name")
        if not name_col:
            continue
        for r in rows[:5]:
            try:
                out.append(str(r[name_col] or "").strip())
            except (KeyError, IndexError, TypeError):
                continue
    # 去重且保序
    seen = set()
    uniq = []
    for n in out:
        if n and n.lower() not in seen:
            seen.add(n.lower())
            uniq.append(n)
    return uniq[:8]


@router.get("/site-attribute/health")
def site_attribute_health():
    """自检：三张表在不在、各表多少行。"""
    out = {"tables": {}, "ok": True}
    try:
        with get_raw_connection() as conn:
            names = set(list_table_names(conn))
            for t in ("eflow_site", "master_site_db", "vip_site_list"):
                if t not in names:
                    out["tables"][t] = {"present": False}
                    out["ok"] = False
                    continue
                try:
                    n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                except Exception:  # noqa: BLE001
                    n = None
                out["tables"][t] = {"present": True, "rows": n}
    except Exception as e:  # noqa: BLE001
        logger.error("[SITE-ATTR] 健康检查失败", exc_info=True)
        return {"ok": False, "error": str(e), "tables": {}}
    return out

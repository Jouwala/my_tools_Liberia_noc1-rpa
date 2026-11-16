# -*- coding: utf-8 -*-
"""IP RAN 看板的 ME / 端口改名自适应（2026-11-16 新增）。

背景
----
`native_catalog.py` 里的 IP RAN SQL 是按 FineBI 原配置生成的，`"ME"='旧设备名'`、
`"Measure Object"='旧端口'` 都是**生成时的字面量**。UME 侧改设备名是日常操作
（实测 2026-11-16：`9000-3EA_LBS_UPE59` 已改名为 `M6K_2s16_LBS_UPE59`，对象 id
`dfe167e4-...` 不变），改名后看板里那条曲线就永远为空 —— 数据其实一直在采，
只是 SQL 找不到旧名字。

本模块做两件事，全部在**查询时**生效，不改 `native_catalog.py`：

1. **ME 改名**：从各 IP RAN 查询配置的 `chartsetting.charts[].mos / mosNames`
   解析出「旧 ME 名 → UME 对象 id」，再向 UME 查对象的当前 `displayName`；两者
   不同就记一条别名。对象 id 是稳定的，改名不影响它。
2. **端口改名**：设备换代/改名后端口名也会变（`P90E-2CGT-Q28[...]-100GE:1` →
   `RPN-02CG-H-VIRTUAL[...]-100GE:1`）。对每个旧端口，在本机 PG 里取旧 ME 的
   历史均值，再在新 ME 的同速率后缀端口里选均值最接近的一个（同后缀优先，
   例如都取 `100GE:1`）。找不到同后缀就留空，不硬猜。

缓存
----
`data/ipran_me_aliases.json`，12 小时刷新一次；刷新失败保留旧缓存（绝不因为
UME 暂时不可用把看板改成空）。首次调用同步刷新一次（约 1~2 秒），之后后台刷新。

安全边界
--------
- 只在 `dashboard_service` 的**本机 PG IP RAN 数据源**上应用（`LOCAL_IPRAN_PG`）；
  远端/历史镜像不动，避免改写旧图。
- 只替换 SQL 里 `"ME"='...'` / `"Measure Object"='...'` 的字面量；替换后原样
  执行，不做任何聚合口径变更。
- 每次刷新把命中的别名写日志（INFO），便于追溯「这条曲线为什么换了名字」。
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable

from backend.database import get_raw_connection

logger = logging.getLogger("ipran_me_alias")

CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "ipran_me_aliases.json"
CACHE_TTL_SEC = 12 * 3600
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_ME_EQ_RE = re.compile(r'("ME"\s*=\s*\')([^\']+)(\')')
_MO_EQ_RE = re.compile(r'("Measure Object"\s*=\s*\')([^\']+)(\')')

_lock = threading.Lock()
_refreshing = False
_cache: Dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# 配置解析：旧 ME 名 -> (UME 对象 id, 表名)
# ---------------------------------------------------------------------------
def _old_me_index() -> Dict[str, Dict[str, str]]:
    """从 IP RAN 查询配置解析出 ``{旧 ME 名: {"id": 对象 id, "table": 表名}}``。"""
    from backend.services.ipran_ume_kpi_service import IPRAN_KPI_QUERY_CONFIGS

    out: Dict[str, Dict[str, str]] = {}
    for cfg in IPRAN_KPI_QUERY_CONFIGS.values():
        table = cfg.get("table_name") or ""
        raw = cfg.get("chartsetting") or ""
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for ch in data.get("charts") or []:
            for mo, name in zip(ch.get("mos") or [], ch.get("mosNames") or []):
                me = _me_from_mosname(str(name))
                uid = _uuid_of(str(mo))
                if me and uid:
                    out.setdefault(me, {"id": uid, "table": table})
    return out


def _me_from_mosname(name: str) -> str:
    """``"ME"-"端口"`` / ``ME-"端口"`` → ``ME``；无法确定 ME 的返回空串。

    例：``M6K_2s16_Gbarnga_UPE76-SmartGroup:20``（整串都是「ME-MO」，没有引号
    分隔）无法可靠切出 ME，返回空串跳过 —— 这类组件若改名，SQL 里的 ME 字面量
    仍可在其它有引号的组件里覆盖到，不能靠猜。
    """
    s = name.strip()
    if s.startswith('"'):
        m = re.match(r'"([^"]+)"', s)
        return m.group(1) if m else ""
    if '-"' in s:
        return s.split('-"', 1)[0].strip()
    return ""


def _uuid_of(mos: str) -> str:
    m = _UUID_RE.match(mos.strip())
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# UME 当前名称
# ---------------------------------------------------------------------------
def _ume_names(ids: Iterable[str]) -> Dict[str, str]:
    from backend.services.ipran_ume_kpi_service import HOST, PORT, UmeSessionClient

    client = UmeSessionClient(HOST, PORT)
    client.login()
    attrs = client.request_with_retry(
        "POST",
        "/api/res/v1/common/query?includeAttr=displayName,id,connectionState",
        json={"id": sorted(set(ids))},
    ).json()
    out: Dict[str, str] = {}
    for a in attrs or []:
        uid, name = str(a.get("id") or ""), str(a.get("displayName") or "")
        if uid and name:
            out[uid] = name
    return out


# ---------------------------------------------------------------------------
# 端口匹配（本机 PG）
# ---------------------------------------------------------------------------
def _numeric_col(conn, table: str) -> str:
    from backend.dialect_helpers import table_columns

    cols = set(table_columns(conn, table))
    for cand in ('Counter Value', 'Send Traffic Rate(Mbps)',
                 'Receive Traffic Rate(Mbps)'):
        if cand in cols:
            return cand
    return ""


def _mo_avg(conn, table: str, me: str, col: str) -> Dict[str, float]:
    if not col:
        return {}
    try:
        cur = conn.cursor()
        cur.execute(
            f'SELECT "Measure Object", AVG(CAST("{col}" AS DOUBLE PRECISION)) '
            f'FROM "{table}" WHERE "ME" = ? GROUP BY 1', (me,))
        return {str(mo): float(avg) for mo, avg in cur.fetchall()
                if mo and avg is not None}
    except Exception as e:  # noqa: BLE001 - 单表/单列失败不回退整次刷新
        logger.warning("[ALIAS] %s 取端口均值失败: %s", table, e)
        return {}


def _suffix(mo: str) -> str:
    """端口名的速率+序号后缀：``P90E-...[0-0-2-0]-100GE:1`` → ``100GE:1``。"""
    parts = str(mo).rsplit("]-", 1)
    return parts[-1] if len(parts) == 2 else ""


def _match_ports(old: Dict[str, float], new: Dict[str, float]) -> Dict[str, str]:
    """旧端口 → 新端口：同后缀里取均值最接近的；没有同后缀则留空。"""
    by_suffix: Dict[str, list] = {}
    for mo, avg in new.items():
        by_suffix.setdefault(_suffix(mo), []).append((mo, avg))
    out: Dict[str, str] = {}
    for omo, oavg in old.items():
        same = by_suffix.get(_suffix(omo)) or []
        if not same:
            continue
        # 相对差最小者；均值 0 时退化为绝对差
        def _score(item):
            mo, avg = item
            if oavg:
                return abs(avg - oavg) / abs(oavg)
            return abs(avg - oavg)
        out[omo] = min(same, key=_score)[0]
    return out


# ---------------------------------------------------------------------------
# 刷新 / 缓存
# ---------------------------------------------------------------------------
def refresh(force: bool = False) -> Dict[str, Any]:
    """重建别名并落盘。失败时返回旧缓存（可能为空 dict）。"""
    global _cache, _refreshing
    with _lock:
        if _refreshing and not force:
            return _cache or {"me": {}}
        _refreshing = True
    try:
        old_index = _old_me_index()
        if not old_index:
            return _cache or {"me": {}}
        names = _ume_names(v["id"] for v in old_index.values())
        renamed = {old: names[v["id"]] for old, v in old_index.items()
                   if names.get(v["id"]) and names[v["id"]] != old}
        payload: Dict[str, Any] = {"fetched_at": time.time(), "me": {}}
        if renamed:
            from backend.services.ipran_ume_kpi_service import DB_PATH

            tables = sorted({old_index[o]["table"] for o in renamed})
            conns = {}
            try:
                for table in tables:
                    try:
                        conns[table] = get_raw_connection(
                            DB_PATH, logical_name="ipran_ume", timeout=30.0)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[ALIAS] 连 PG 取端口均值失败(%s): %s", table, e)
                for old, new in renamed.items():
                    table = old_index[old]["table"]
                    ports: Dict[str, str] = {}
                    conn = conns.get(table)
                    if conn is not None:
                        col = _numeric_col(conn, table)
                        ports = _match_ports(_mo_avg(conn, table, old, col),
                                             _mo_avg(conn, table, new, col))
                    payload["me"][old] = {"new": new, "table": table,
                                          "ports": ports}
                    logger.info("[ALIAS] ME 改名 %s -> %s；端口映射 %d 条 %s",
                                old, new, len(ports), ports)
            finally:
                for conn in conns.values():
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001
                        pass
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                              encoding="utf-8")
        _cache = payload
        return payload
    except Exception as e:  # noqa: BLE001 - 别名失败不能影响看板
        logger.warning("[ALIAS] 刷新失败，沿用旧缓存: %s", e)
        return _cache or {"me": {}}
    finally:
        with _lock:
            _refreshing = False


def _load() -> Dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    if CACHE_PATH.exists():
        try:
            _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            return _cache
        except Exception as e:  # noqa: BLE001
            logger.warning("[ALIAS] 读缓存失败: %s", e)
    return {"me": {}}


def _ensure() -> Dict[str, Any]:
    data = _load()
    age = time.time() - float(data.get("fetched_at") or 0)
    if age > CACHE_TTL_SEC and not _refreshing:
        threading.Thread(target=refresh, name="ipran-me-alias", daemon=True).start()
    return data


def aliases() -> Dict[str, Dict[str, Any]]:
    """``{旧 ME 名: {"new": 新名, "table": 表, "ports": {旧端口: 新端口}}}``。"""
    data = _load()
    if not data.get("me") and not CACHE_PATH.exists():
        # 首次：同步刷一次，保证第一屏就是对的（UME 正常时约 1~2s）
        data = refresh()
    else:
        data = _ensure()
    return data.get("me") or {}


# ---------------------------------------------------------------------------
# 应用到 SQL / 标题
# ---------------------------------------------------------------------------
def apply_sql(sql: str) -> str:
    """把 SQL 里的旧 ME / 旧端口字面量替换成当前值；无别名原样返回。"""
    if not sql:
        return sql
    table = aliases()
    if not table:
        return sql
    m = _ME_EQ_RE.search(sql)
    if not m:
        return sql
    old_me = m.group(2)
    info = table.get(old_me)
    if not info:
        return sql

    sql2 = sql.replace(m.group(0), f"{m.group(1)}{info['new']}{m.group(3)}", 1)
    ports = info.get("ports") or {}
    if not ports:
        return sql2

    # 端口替换只使用**本条 SQL 那个 ME** 的映射，避免同名端口在别的 ME 上误替换
    def _mo_sub(mo: re.Match) -> str:
        new_mo = ports.get(mo.group(2))
        return f"{mo.group(1)}{new_mo}{mo.group(3)}" if new_mo else mo.group(0)

    return _MO_EQ_RE.sub(_mo_sub, sql2)


def apply_text(text: str) -> str:
    """把组件标题里的旧 ME / 旧端口替换成当前值（只影响显示）。"""
    if not text:
        return text
    for old, info in aliases().items():
        new = info.get("new") or old
        if old in text and new != old:
            text = text.replace(old, new)
        for omo, nmo in (info.get("ports") or {}).items():
            if omo in text and nmo != omo:
                text = text.replace(omo, nmo)
    return text

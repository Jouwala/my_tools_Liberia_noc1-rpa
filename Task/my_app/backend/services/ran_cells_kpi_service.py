# -*- coding: utf-8 -*-
"""RAN 2G/3G/4G Cells KPI 看板数据服务（小区级 / 天粒度）。

=========================== 数据源与统计口径 ===========================

数据源
    data/ran_kpi_avalability_1day.sqlite3（本地小区级可用率库，由 RAN_UME 拉取）
        Daily_KPI_RPA_CELL_AVAIL_GSM   2G 小区（BTS Name）
        Daily_KPI_RPA_CELL_AVAIL_UMTS  3G 小区（Cell Name）
        Daily_KPI_RPA_CELL_AVAIL_FDD   4G 小区（E-UTRAN FDD Cell Name）

小区可用率（逐小区折算，0~1 比率）
    2G : 可用信道 / 全部信道
         可用信道   = 可用静态 TCH/H + 可用静态 TCH/F + 平均可用动态信道
         全部信道   = 可用信道 + 不可用静态 TCH/F + 平均不可用动态信道 + 不可用静态 TCH/H
    3G : "Service time of the cell(s)" / 86400
    4G : "Cell Service Time(s)" / 86400
    （分母为 0 / 值缺失 → 该小区当天无有效值，计入 Blank）

统计口径（每个制式 × 每天）
    Total Cells                = 当天有有效可用率的小区数
    Total Cells Meeting Target = 可用率 >= threshold 的小区数
    Total Cells Below Target   = 可用率 <  threshold 的小区数（Total = Meeting + Below）
    Blank                      = 当月小区名册内、当天没有有效数据的小区数
    % of Cells Meeting Target  = Meeting / Total
    % of Cells Below Target    = Below   / Total
    Availability               = 当天所有有效小区可用率的算术平均

    小区名册（roster）= 当月该制式出现过的全部小区名的并集；
    Blank 只在 roster 内计算，因此同一天  Total + Blank = roster 大小。

达标值 threshold 默认 0.9965（99.65%）。
======================================================================
"""
from __future__ import annotations

import calendar
import logging
import os
import re
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ran_cells_kpi")

# ---------- 路径 ----------
# 注意：不能用 Path.resolve()——本机 Y: 是网络映射盘，resolve() 会把它展开成
# \\192.168.100.20\... 的 UNC 路径，sqlite 的 file: URI 无法解析（invalid uri authority）。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "data",
                                           "ran_kpi_avalability_1day.sqlite3"))
KPI_DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "data",
                                           "ran_cells_kpi.sqlite3"))


def _connect_ro(path: str) -> sqlite3.Connection:
    """只读连接本地 sqlite（不走 file: URI，避免网络盘 UNC 路径解析失败）。"""
    conn = sqlite3.connect(path, timeout=60)
    try:
        conn.execute("PRAGMA query_only=ON")
    except Exception:
        pass
    return conn

DEFAULT_THRESHOLD = 0.9965  # 99.65%

# ---------- 制式配置 ----------
# mode = channel : 用动态信道数折算
# mode = service : 用服务时长 / 86400 折算
TECH_SPEC: Dict[str, Dict[str, Any]] = {
    "2G": {
        "table": "Daily_KPI_RPA_CELL_AVAIL_GSM",
        "cell_col": "BTS Name",
        "mode": "channels",
        "avail_cols": [
            "Number of available static TCH/Hs",
            "Number of available static TCH/Fs",
            "Average number of available dynamic radio channel",
        ],
        "unavail_cols": [
            "Number of unavailable defined TCH/Fs",
            "Average number of unavailable dynamic radio channel",
            "Number of unavailable defined TCH/Hs",
        ],
        # 下钻明细附带的身份信息列（统一 key → 原始列名，读取时按 _norm 归一化匹配）
        "meta_cols": {
            "cell_id": "BTS ID",
            "site_id": "SITE ID",
            "site_name": "SITE Name",
            "ne": "Managed Element",     # 网元（BSC）
            "subnet": "SubnetWork Name",
            "band": "FreqBand",
        },
        "label": "2G Cells KPI",
        "desc": "小区可用率 = 可用信道 / 全部信道（静态 TCH/F、TCH/H + 动态信道）",
    },
    "3G": {
        "table": "Daily_KPI_RPA_CELL_AVAIL_UMTS",
        "cell_col": "Cell Name",
        "mode": "service",
        "value_col": "Service time of the cell(s)",
        "meta_cols": {
            "cell_id": "Cell ID",
            "site_id": "NodeB ID",
            "site_name": "NodeB Name",
            "ne": "RNC Managed NE",      # 网元（RNC）
            "subnet": "SubnetWork Name",
            "band": "Frequency Band Indicator",
        },
        "label": "3G Cells KPI",
        "desc": "小区可用率 = 小区服务时长 / 86400",
    },
    "4G": {
        "table": "Daily_KPI_RPA_CELL_AVAIL_FDD",
        "cell_col": "E-UTRAN\xa0FDD\xa0Cell Name",
        "mode": "service",
        "value_col": "Cell Service Time(s)",
        "meta_cols": {
            "cell_id": "E-UTRAN\xa0FDD\xa0Cell ID",
            "site_id": "eNodeB ID",
            "site_name": "eNodeB Name",
            "ne": "Managed\xa0Element",   # 网元（eNodeB）
            "subnet": "SubnetWork Name",
            # 4G FDD 表没有频段列
        },
        "label": "4G Cells KPI",
        "desc": "小区可用率 = 小区服务时长 / 86400",
    },
}

TECHS = ["2G", "3G", "4G"]

# ---------- 缓存（复用项目 cache 服务）----------
try:
    from backend.services.cache import get_cache

    _cache = get_cache()
except Exception:  # pragma: no cover
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
def _norm(s: Any) -> str:
    """归一化列名：不间断空格/全角空格 → 普通空格并压缩。"""
    if not isinstance(s, str):
        return s
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def _to_float(v: Any) -> Optional[float]:
    """原始值 → float；无法解析 / 负数 / NaN 返回 None。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f < 0:  # NaN 或负数
        return None
    return f


def month_bounds(month: str) -> Tuple[str, str]:
    """'YYYY-MM' → ('YYYY-MM-01 00:00:00', 'YYYY-MM-<末日> 23:59:59')。"""
    y, m = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(y, m)[1]
    return f"{month}-01 00:00:00", f"{month}-{last:02d} 23:59:59"


def month_days(month: str) -> List[str]:
    """该月所有日期 YYYY-MM-DD。"""
    y, m = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(y, m)[1]
    return [f"{month}-{d:02d}" for d in range(1, last + 1)]


def current_month() -> str:
    d = datetime.now()
    return f"{d.year}-{d.month:02d}"


# ============ 读原始小区数据 ============
def _resolve_columns(cur: sqlite3.Cursor, table: str) -> Dict[str, str]:
    """返回 {归一化列名: 真实列名}。"""
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")')]
    return {_norm(c): c for c in cols}


def _read_tech_month(tech: str, month: str) -> Dict[str, Dict[str, Optional[float]]]:
    """读某制式整月小区级可用率。

    返回 {cell_name: {day: ratio|None}}，ratio 为 None 表示当天该小区无有效值。
    """
    spec = TECH_SPEC[tech]
    table = spec["table"]
    out: Dict[str, Dict[str, Optional[float]]] = {}
    if not os.path.isfile(RAW_DB_PATH):
        logger.warning("[cells-kpi] 原始可用率库不存在: %s", RAW_DB_PATH)
        return out

    start, end = month_bounds(month)
    conn = None
    try:
        # 独立 sqlite 文件：PG 模式下 get_raw_connection 会解析成 PG schema，
        # 因此这里必须直连 sqlite（只读）。
        conn = _connect_ro(RAW_DB_PATH)
        cur = conn.cursor()
        norm2real = _resolve_columns(cur, table)
        cell_col = norm2real.get(_norm(spec["cell_col"]))
        time_col = norm2real.get("Begin Time")
        if not cell_col or not time_col:
            logger.warning("[cells-kpi] %s 缺少必要列 (cell=%s, time=%s)",
                           table, cell_col, time_col)
            return out

        if spec["mode"] == "channels":
            avail_cols = [norm2real.get(_norm(c)) for c in spec["avail_cols"]]
            unavail_cols = [norm2real.get(_norm(c)) for c in spec["unavail_cols"]]
            if any(c is None for c in avail_cols + unavail_cols):
                logger.warning("[cells-kpi] %s 缺少信道列", table)
                return out
            sel = ", ".join(f'CAST("{c}" AS REAL)' for c in avail_cols + unavail_cols)
            sql = (f'SELECT "{cell_col}", substr("{time_col}",1,10), {sel} '
                   f'FROM "{table}" WHERE "{time_col}" >= ? AND "{time_col}" <= ?')
            n_av = len(avail_cols)
            for row in cur.execute(sql, (start, end)).fetchall():
                cell, day = row[0], row[1]
                if cell is None:
                    continue
                nums = [_to_float(v) for v in row[2:]]
                a = sum(v for v in nums[:n_av] if v is not None)
                u = sum(v for v in nums[n_av:] if v is not None)
                denom = a + u
                ratio = (a / denom) if denom > 0 else None
                if ratio is not None and ratio > 1.0:
                    ratio = 1.0
                out.setdefault(str(cell), {})[str(day)] = ratio
        else:
            value_col = norm2real.get(_norm(spec["value_col"]))
            if not value_col:
                logger.warning("[cells-kpi] %s 缺少服务时长列", table)
                return out
            sql = (f'SELECT "{cell_col}", substr("{time_col}",1,10), '
                   f'CAST("{value_col}" AS REAL) '
                   f'FROM "{table}" WHERE "{time_col}" >= ? AND "{time_col}" <= ?')
            for cell, day, svc in cur.execute(sql, (start, end)).fetchall():
                if cell is None:
                    continue
                v = _to_float(svc)
                ratio = (v / 86400.0) if v is not None else None
                if ratio is not None and ratio > 1.0:
                    ratio = 1.0
                out.setdefault(str(cell), {})[str(day)] = ratio
    except Exception as e:
        logger.warning("[cells-kpi] 读取 %s month=%s 失败: %s", table, month, e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return out


def _read_tech_meta(tech: str, month: str) -> Dict[str, Dict[str, str]]:
    """读某制式整月「小区 → 身份信息」映射（站点 / 网元 / 频段 / 子网…）。

    返回 {cell_name: {cell_id, site_id, site_name, ne, subnet, band}}，
    **只保留非空字段**（不同制式的可用字段不同，4G 没有频段）。
    同一小区名在同一月出现多行时，每个字段取第一次读到的非空值
    （身份信息基本不变，多行只是每天一条）。

    注意：列名必须先用 _resolve_columns 归一化后取真实列名再引用。
    4G FDD 表的列名里含不换行空格（\xa0），若用普通空格写成
    "E-UTRAN FDD Cell Name"，sqlite 会把它当成**字符串常量**而不是列名
    （legacy 双引号误用），从而静默返回看似合理的错误结果。
    """
    spec = TECH_SPEC[tech]
    table = spec["table"]
    ck = f"ran_cells_kpi_meta:{tech}:{month}"
    cached = _cache_get(ck)
    if cached is not None:
        return cached

    out: Dict[str, Dict[str, str]] = {}
    meta_cols = spec.get("meta_cols") or {}
    if not meta_cols or not os.path.isfile(RAW_DB_PATH):
        return _cache_set(ck, out)

    start, end = month_bounds(month)
    conn = None
    try:
        conn = _connect_ro(RAW_DB_PATH)
        cur = conn.cursor()
        norm2real = _resolve_columns(cur, table)
        cell_col = norm2real.get(_norm(spec["cell_col"]))
        time_col = norm2real.get("Begin Time")
        if not cell_col or not time_col:
            logger.warning("[cells-kpi] %s 缺少必要列，无法读取身份信息", table)
            return _cache_set(ck, out)

        wanted = {k: norm2real.get(_norm(c)) for k, c in meta_cols.items()}
        keys = [k for k, v in wanted.items() if v]
        if not keys:
            logger.warning("[cells-kpi] %s 身份信息列全部缺失: %s", table, list(meta_cols))
            return _cache_set(ck, out)

        sel = ", ".join(f'"{wanted[k]}"' for k in keys)
        sql = (f'SELECT "{cell_col}", {sel} FROM "{table}" '
               f'WHERE "{time_col}" >= ? AND "{time_col}" <= ?')
        for row in cur.execute(sql, (start, end)).fetchall():
            cell = row[0]
            if cell is None:
                continue
            slot = out.setdefault(str(cell), {})
            for k, v in zip(keys, row[1:]):
                if k in slot or v is None:
                    continue
                s = str(v).strip()
                if s:
                    slot[k] = s
    except Exception as e:
        logger.warning("[cells-kpi] 读取 %s month=%s 身份信息失败: %s", table, month, e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return _cache_set(ck, out)


# ============ 聚合 ============
def compute_tech(tech: str, month: str, threshold: float = DEFAULT_THRESHOLD,
                 raw: Optional[Dict[str, Dict[str, Optional[float]]]] = None
                 ) -> Dict[str, Any]:
    """计算单制式整月每日 KPI。"""
    if raw is None:
        raw = _read_tech_month(tech, month)
    days = month_days(month)
    roster = set(raw.keys())
    roster_n = len(roster)

    daily: Dict[str, Dict[str, Any]] = {}
    for day in days:
        total = 0
        meeting = 0
        below = 0
        s = 0.0
        for cell, by_day in raw.items():
            v = by_day.get(day)
            if v is None:
                continue
            total += 1
            s += v
            if v >= threshold:
                meeting += 1
            else:
                below += 1
        blank = roster_n - total
        daily[day] = {
            "total": total,
            "meeting": meeting,
            "below": below,
            "blank": blank,
            "pct_meeting": (meeting / total) if total else None,
            "pct_below": (below / total) if total else None,
            "availability": (s / total) if total else None,
        }

    valid_days = [d for d in days if daily[d]["total"] > 0]
    avail_vals = [daily[d]["availability"] for d in valid_days
                  if daily[d]["availability"] is not None]
    month_avg = (sum(avail_vals) / len(avail_vals)) if avail_vals else None
    month_total = sum(daily[d]["total"] for d in valid_days)
    month_meeting = sum(daily[d]["meeting"] for d in valid_days)
    month_below = sum(daily[d]["below"] for d in valid_days)

    return {
        "tech": tech,
        "label": TECH_SPEC[tech]["label"],
        "desc": TECH_SPEC[tech]["desc"],
        "roster_cells": roster_n,
        "days": daily,
        "month": {
            "availability": month_avg,
            "days_with_data": len(valid_days),
            "total": month_total,
            "meeting": month_meeting,
            "below": month_below,
            "pct_meeting": (month_meeting / month_total) if month_total else None,
            "pct_below": (month_below / month_total) if month_total else None,
        },
    }


# ============ 小区级明细（看板数字下钻） ============
# scope 语义与看板指标行的对应关系：
#   all     -> 全部名册小区（total / availability 的下钻）
#   meeting -> 仅达标小区（meeting / pct_meeting 的下钻）
#   below   -> 仅未达标小区（below / pct_below 的下钻）
#   blank   -> 仅当天无有效数据的小区（blank 的下钻）
CELL_SCOPES = ("all", "meeting", "below", "blank")


def _cell_rows_for(tech: str, month: str, day: str,
                   threshold: float) -> List[Dict[str, Any]]:
    """某制式、某天（day 为空则整月）的全部名册小区明细。

    ratio 为 None 表示该小区在该维度下无有效值（计入 Blank）；
    day 为空时 ratio = 该小区当月各有效天可用率的算术平均。

    每行除可用率外，还带上下钻所需的身份信息（cell_id / site_id / site_name /
    ne / subnet / band，来自 _read_tech_meta，缺失的字段不会出现）。
    整月下钻额外给出 days_meeting / days_below，便于区分「长期劣化」与「偶发」。
    """
    raw = _read_tech_month(tech, month)
    meta = _read_tech_meta(tech, month)
    whole_month = not day
    days = [day] if day else month_days(month)
    rows: List[Dict[str, Any]] = []
    for cell in sorted(raw.keys()):
        by_day = raw.get(cell) or {}
        vals = [by_day.get(d) for d in days]
        vals = [v for v in vals if v is not None]
        ratio = (sum(vals) / len(vals)) if vals else None
        if ratio is None:
            status = "blank"
        elif ratio >= threshold:
            status = "meeting"
        else:
            status = "below"
        row: Dict[str, Any] = {
            "cell": cell,
            "ratio": ratio,
            "days_with_data": len(vals),
            "status": status,
        }
        if whole_month:
            row["days_meeting"] = sum(1 for v in vals if v >= threshold)
            row["days_below"] = sum(1 for v in vals if v < threshold)
        row.update(meta.get(cell) or {})
        rows.append(row)
    # 有值小区按可用率升序（最差在前，便于直接定位问题小区），无值小区置末
    rows.sort(key=lambda r: (r["ratio"] is None,
                             r["ratio"] if r["ratio"] is not None else 0.0))
    return rows


def compute_tech_cells(tech: str, month: str, day: str = "",
                       threshold: float = DEFAULT_THRESHOLD,
                       scope: str = "all") -> Dict[str, Any]:
    """小区级明细（下钻）：按 scope 过滤 + 汇总计数，带缓存。"""
    if tech not in TECH_SPEC:
        raise ValueError(f"未知制式: {tech}")
    if scope not in CELL_SCOPES:
        scope = "all"
    day = day or ""
    ck = f"ran_cells_kpi_cells:{tech}:{month}:{day}:{round(threshold, 6)}"
    rows = _cache_get(ck)
    if rows is None:
        rows = _cache_set(ck, _cell_rows_for(tech, month, day, threshold))

    total = sum(1 for r in rows if r["ratio"] is not None)
    meeting = sum(1 for r in rows if r["status"] == "meeting")
    below = sum(1 for r in rows if r["status"] == "below")
    blank = sum(1 for r in rows if r["status"] == "blank")

    if scope == "meeting":
        shown = [r for r in rows if r["status"] == "meeting"]
    elif scope == "below":
        shown = [r for r in rows if r["status"] == "below"]
    elif scope == "blank":
        shown = [r for r in rows if r["status"] == "blank"]
    else:
        shown = rows

    return {
        "tech": tech,
        "label": TECH_SPEC[tech]["label"],
        "desc": TECH_SPEC[tech]["desc"],
        "month": month,
        "day": day,
        "threshold": threshold,
        "scope": scope,
        "roster_cells": len(rows),
        "total": total,
        "meeting": meeting,
        "below": below,
        "blank": blank,
        "rows": shown,
    }


def build_overview(month: str = "", threshold: float = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """看板总览：{meta, techs:[...]}（带缓存）。"""
    month = month or current_month()
    t0 = time.time()
    ck = f"ran_cells_kpi:{month}:{round(threshold, 6)}"
    cached = _cache_get(ck)
    if cached is not None:
        return cached

    warnings: List[str] = []
    # 2026-09-11 修复：RAW_DB_PATH 是 str（os.path.abspath 的返回值），不是 Path，
    # 原来的 RAW_DB_PATH.is_file() 会抛 AttributeError: 'str' object has no attribute 'is_file'。
    # 该分支只在「物化库当月无数据 → 回退实时聚合」时才会走到，因此线上表现是：
    # 物化库为空时接口 500/techs=[]，前端显示「暂无数据」，而不是回退聚合出真实结果。
    if not os.path.isfile(RAW_DB_PATH):
        warnings.append(f"原始可用率库不存在: {RAW_DB_PATH}")

    techs: List[Dict[str, Any]] = []
    for tech in TECHS:
        try:
            techs.append(compute_tech(tech, month, threshold))
        except Exception as e:
            logger.exception("[cells-kpi] %s 计算失败: %s", tech, e)
            warnings.append(f"{tech} 计算失败: {e}")

    payload = {
        "meta": {
            "month": month,
            "threshold": threshold,
            "days": month_days(month),
            "source": "data/ran_kpi_avalability_1day.sqlite3（RAN UME 小区可用率）",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_seconds": round(time.time() - t0, 2),
            "warnings": warnings,
        },
        "techs": techs,
    }
    return _cache_set(ck, payload)


# ============ 物化表（任务写入，看板优先读） ============
KPI_TABLE = "cells_kpi_daily"


def write_month_to_db(month: str, threshold: float = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """计算当月 KPI 并写入物化库，只保留当月数据（幂等，可重跑）。"""
    os.makedirs(os.path.dirname(KPI_DB_PATH), exist_ok=True)
    techs = [compute_tech(t, month, threshold) for t in TECHS]

    conn = sqlite3.connect(KPI_DB_PATH)
    rows_written = 0
    try:
        conn.execute(
            f'''CREATE TABLE IF NOT EXISTS "{KPI_TABLE}" (
                tech TEXT NOT NULL,
                day TEXT NOT NULL,
                total_cells INTEGER,
                meeting INTEGER,
                below INTEGER,
                blank INTEGER,
                roster_cells INTEGER,
                pct_meeting REAL,
                pct_below REAL,
                availability REAL,
                threshold REAL,
                updated_at TEXT,
                PRIMARY KEY (tech, day)
            )''')
        # 只保留当月，且每次按月整体重建：先删掉非当月行（跨月清理），
        # 再删掉本月行（避免上一次写入、本次不再产出的日期——如未来日期——残留）。
        conn.execute(f'DELETE FROM "{KPI_TABLE}" WHERE substr(day,1,7) <> ?', (month,))
        conn.execute(f'DELETE FROM "{KPI_TABLE}" WHERE substr(day,1,7) = ?', (month,))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = []
        for t in techs:
            for day, m in t["days"].items():
                if m["total"] <= 0:  # 当天没有任何有效小区数据（含未来日期）不落库
                    continue
                payload.append((
                    t["tech"], day, m["total"], m["meeting"], m["below"], m["blank"],
                    t["roster_cells"], m["pct_meeting"], m["pct_below"],
                    m["availability"], threshold, now,
                ))
        conn.executemany(
            f'''INSERT OR REPLACE INTO "{KPI_TABLE}"
                (tech, day, total_cells, meeting, below, blank, roster_cells,
                 pct_meeting, pct_below, availability, threshold, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', payload)
        conn.commit()
        rows_written = len(payload)
    finally:
        conn.close()

    summary = {t["tech"]: {"roster_cells": t["roster_cells"],
                           "days_with_data": t["month"]["days_with_data"],
                           "availability": t["month"]["availability"]} for t in techs}
    logger.info("[cells-kpi] 物化写入 %s: %d 行 %s", month, rows_written, summary)
    return {"month": month, "rows": rows_written, "techs": summary}


def read_month_from_db(month: str) -> Optional[Dict[str, Any]]:
    """从物化库读当月 KPI；无数据返回 None。"""
    if not os.path.isfile(KPI_DB_PATH):
        return None
    try:
        conn = _connect_ro(KPI_DB_PATH)
    except Exception:
        return None
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                f'SELECT tech, day, total_cells, meeting, below, blank, roster_cells, '
                f'pct_meeting, pct_below, availability, threshold '
                f'FROM "{KPI_TABLE}" WHERE substr(day,1,7) = ? ORDER BY day', (month,))
        except sqlite3.OperationalError:
            return None
        rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        return None

    days = month_days(month)
    acc: Dict[str, Dict[str, Any]] = {}
    thr = None
    for (tech, day, total, meeting, below, blank, roster, pm, pb, avail, th) in rows:
        d = acc.setdefault(tech, {})
        d[str(day)] = {
            "total": total or 0, "meeting": meeting or 0, "below": below or 0,
            "blank": blank or 0, "pct_meeting": pm, "pct_below": pb,
            "availability": avail,
        }
        if roster:
            d.setdefault("_roster", roster)
        if th:
            thr = th

    techs = []
    for tech in TECHS:
        d = acc.get(tech)
        if not d:
            continue
        roster_n = int(d.pop("_roster", 0) or 0)
        daily = {day: d.get(day, {"total": 0, "meeting": 0, "below": 0, "blank": 0,
                                  "pct_meeting": None, "pct_below": None,
                                  "availability": None}) for day in days}
        valid = [day for day in days if daily[day]["total"] > 0]
        av = [daily[day]["availability"] for day in valid if daily[day]["availability"] is not None]
        mt = sum(daily[day]["total"] for day in valid)
        mm = sum(daily[day]["meeting"] for day in valid)
        mb = sum(daily[day]["below"] for day in valid)
        techs.append({
            "tech": tech,
            "label": TECH_SPEC[tech]["label"],
            "desc": TECH_SPEC[tech]["desc"],
            "roster_cells": roster_n,
            "days": daily,
            "month": {
                "availability": (sum(av) / len(av)) if av else None,
                "days_with_data": len(valid),
                "total": mt, "meeting": mm, "below": mb,
                "pct_meeting": (mm / mt) if mt else None,
                "pct_below": (mb / mt) if mt else None,
            },
        })
    if not techs:
        return None
    return {"month": month, "threshold": thr or DEFAULT_THRESHOLD, "techs": techs}


def load_overview(month: str = "", threshold: float = DEFAULT_THRESHOLD,
                  prefer_db: bool = True) -> Dict[str, Any]:
    """看板入口：优先读物化库（任务写入），缺失时回退实时计算原始库。"""
    month = month or current_month()
    if prefer_db:
        mat = read_month_from_db(month)
        if mat is not None:
            return {
                "meta": {
                    "month": month,
                    "threshold": mat["threshold"],
                    "days": month_days(month),
                    "source": f"物化库 data/ran_cells_kpi.sqlite3（{KPI_TABLE}）",
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "elapsed_seconds": 0,
                    "warnings": [],
                },
                "techs": mat["techs"],
            }
    return build_overview(month, threshold)


if __name__ == "__main__":
    import json
    import sys

    m = sys.argv[1] if len(sys.argv) > 1 else current_month()
    print(json.dumps(build_overview(m), ensure_ascii=False, indent=2, default=str)[:6000])

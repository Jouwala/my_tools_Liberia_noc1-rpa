# -*- coding: utf-8 -*-
"""OLIB SOC VMAX 日粒度 KPI 库 —— 服务与看板共用的「指标字典 + 落库 + 取数聚合」。

为什么单独一层
--------------
1. **原始值落库、派生值查询时算**：库里只存 SQL 直接查得到的原始量（TB / 用户数 / 百分比），
   「视频占比」「缓存占比」这类派生指标在查询时用 分子/分母 现算 —— 这样周汇总永远是
   `sum(分子)/sum(分母)` 的精确加权，而不是「先算每天占比再平均」的错误口径。
2. **指标字典唯一真相源**：卡片标题/单位/小数位/越大越好/日周汇总方式都在 `METRICS` 里声明，
   后端接口、前端卡片、周趋势、明细表全部引用它，避免多处各写一份。
3. **只读查询**：看板进程用 `query_only=ON` 打开，绝不写；写入只发生在报表/同步任务里。

落库位置：`data/olib_soc_report/olib_soc_report.sqlite3` 的 `daily_kpi` 表（与运行记录同库）。

口径来源（全部来自 notebook 移植的 9 段 SQL，见 olib_soc_report_service.py）：
    traffic -> aggr_5gsa_flow_ciservice_day_*     总流量
    active_user -> aggr_ds_250024_day_*          活跃用户
    video -> aggr_5gsa_video_spservice_day_*     视频流量 + 有效下载速率
    cache -> aggr_5gsa_flow_spservice_day_*      缓存/非缓存服务器流量
    tcp -> aggr_5gsa_flow_ciservice_day_*        TCP 建链成功率/重传/RTT
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger("olib_soc_kpi")

_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = _ROOT / "data" / "olib_soc_report"
KPI_DB_PATH = DATA_DIR / "olib_soc_report.sqlite3"
DAILY_TABLE = "daily_kpi"
# 分业务「本地 / 海外 / 未识别服务器」流量明细（看板下钻用，一天一业务一行）。
# 与 daily_kpi 分开存放：daily_kpi 是「一天一行的卡片口径」，这张是「一天一业务一行的下钻」，
# 混在一张表里会让 REQUIRED_COLUMNS 的残缺日自愈把「某个 APP 没取到」误判成整天残缺。
APP_OFFLOAD_TABLE = "daily_app_offload"

# ==========================================================================
# 指标字典（CEO 视角：第一屏业务/成本/体验，第二屏网络质量）
# --------------------------------------------------------------------------
# col        原始列名（直接落库的值）；派生指标用 num/den 现算
# scale      显示单位换算系数（库里 TB，卡片要 GB -> 1024）
# agg_week   周汇总方式：sum(合计) / mean(均值) / wavg:<列>(按该列加权平均)
# better     up=越大越好，down=越小越好，flat=中性（用于配色，不做价值判断）
# group      primary=CEO 主卡片；quality=网络质量
# ==========================================================================
METRICS: List[Dict[str, Any]] = [
    {
        "id": "traffic_gb", "col": "traffic_tb", "scale": 1024.0,
        "title": "总流量", "title_en": "Total Traffic", "unit": "GB", "digits": 0,
        "agg_week": "sum", "better": "up", "group": "primary",
        "note": "全部业务上下行合计（含缓存与非缓存服务器）",
        "note_en": "All services, uplink + downlink (cache and non-cache servers)",
    },
    {
        "id": "active_user_k", "col": "active_user", "scale": 0.001,
        "title": "活跃用户", "title_en": "Active Users", "unit": "K", "digits": 1,
        "agg_week": "mean", "better": "up", "group": "primary",
        "note": "当日去重用户数（distinct msisdn）",
        "note_en": "Distinct subscribers per day (distinct msisdn)",
    },
    {
        "id": "video_thr_kbps", "col": "video_mbps", "scale": 1000.0,
        "title": "视频下载速率", "title_en": "Valid Throughput of Video Download",
        "unit": "kbps", "digits": 0,
        "agg_week": "wavg:video_tb", "better": "up", "group": "primary",
        "note": "按视频流量加权的有效下载速率（越高体验越好）",
        "note_en": "Traffic-weighted valid video download throughput (higher is better)",
    },
    {
        "id": "video_share_pct", "num": "video_tb", "den": "traffic_tb", "scale": 100.0,
        "title": "视频流量占比", "title_en": "Video Traffic Share", "unit": "%", "digits": 1,
        "agg_week": "ratio", "better": "flat", "group": "primary",
        "note": "视频业务流量 / 总流量，反映业务结构",
        "note_en": "Video traffic divided by total traffic (service mix)",
    },
    {
        "id": "video_tb", "col": "video_tb", "scale": 1.0,
        "title": "视频流量", "title_en": "Video Traffic", "unit": "TB", "digits": 1,
        "agg_week": "sum", "better": "up", "group": "business",
        "note": "FACEBOOK_VIDEO / TIKTOK / YOUTUBE 三家合计",
        "note_en": "FACEBOOK_VIDEO + TIKTOK + YOUTUBE",
    },
    {
        "id": "cache_ratio_pct", "num": "cache_tb", "den": "cache_tb+noncache_tb", "scale": 100.0,
        "title": "缓存服务器流量占比", "title_en": "Cache Server Share", "unit": "%", "digits": 1,
        "agg_week": "ratio", "better": "up", "group": "business",
        "note": "缓存服务器承载比例，越高越省国际带宽",
        "note_en": "Share carried by cache servers — higher means less international bandwidth",
    },
    {
        "id": "game_tb", "col": "game_tb", "scale": 1.0,
        "title": "游戏流量", "title_en": "Game Traffic", "unit": "TB", "digits": 1,
        "agg_week": "sum", "better": "up", "group": "business",
        "note": "游戏业务流量，反映新增业务增长点",
        "note_en": "Gaming traffic — an indicator of new service growth",
    },
    {
        "id": "tcp_success_pct", "col": "tcp_success_pct", "scale": 1.0,
        "title": "TCP 建链成功率", "title_en": "TCP Connection Success Rate",
        "unit": "%", "digits": 2, "agg_week": "wavg:tcp_tb", "better": "up", "group": "quality",
        "note": "TCP 建链成功比例，反映接入与承载质量",
        "note_en": "TCP connection success ratio",
    },
    {
        "id": "tcp_dl_retrans_pct", "col": "tcp_dl_retrans_pct", "scale": 1.0,
        "title": "下行重传率", "title_en": "TCP DL Retransmission Rate",
        "unit": "%", "digits": 2, "agg_week": "wavg:tcp_tb", "better": "down", "group": "quality",
        "note": "下行 TCP 重传比例，越低越好",
        "note_en": "Downlink TCP retransmission ratio, lower is better",
    },
    {
        "id": "tcp_dl_rtt_ms", "col": "tcp_dl_rtt_ms", "scale": 1.0,
        "title": "下行时延", "title_en": "Avg TCP DL RTT", "unit": "ms", "digits": 1,
        "agg_week": "wavg:tcp_tb", "better": "down", "group": "quality",
        "note": "下行 TCP 平均往返时延",
        "note_en": "Average downlink TCP round-trip time",
    },
]
METRIC_BY_ID = {m["id"]: m for m in METRICS}
PRIMARY_IDS = [m["id"] for m in METRICS if m.get("group") == "primary"]

# 库里存的原始列（写入用；卡片需要的派生指标不在此列）
RAW_COLUMNS: Tuple[str, ...] = (
    "traffic_tb", "active_user", "video_tb", "video_mbps",
    "cache_tb", "noncache_tb", "tcp_tb",
    "tcp_success_pct", "tcp_ul_retrans_pct", "tcp_dl_retrans_pct",
    "tcp_ul_rtt_ms", "tcp_dl_rtt_ms", "game_tb",
    "top_service", "top_service_tb", "blocks_ok", "suspect_json",
    "run_id", "updated_at",
)


# ==========================================================================
# 建表 / 写入
# ==========================================================================
def iso_day(value: Any) -> str:
    """把 date/datetime/'YYYY-MM-DD'/'YYYYMMDD' 统一成 'YYYY-MM-DD'（主键格式唯一）。

    库里 day 是 TEXT 主键，字符串比较即日期比较 —— 一旦混入 'YYYYMMDD' 写法，
    范围查询会把整天漏掉（'20260907' > '2026-09-30'），所以写入与查询两侧都归一。
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip().replace("/", "-").replace(".", "-")
    if "T" in text or " " in text:
        text = text.replace("T", " ").split(" ")[0]
    if len(text) == 8 and text.isdigit():
        return "%s-%s-%s" % (text[:4], text[4:6], text[6:])
    return text[:10]


def connect(path: Optional[Path] = None, readonly: bool = False) -> sqlite3.Connection:
    """打开 KPI 库：readonly=True 时 `query_only`，看板进程绝不写生产库。"""
    target = Path(path or KPI_DB_PATH)
    if readonly:
        if not target.exists():
            raise FileNotFoundError(str(target))
        conn = sqlite3.connect(str(target), timeout=30)
        conn.execute("PRAGMA query_only=ON")
        return conn
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")                              # 任务写 + 看板读并发
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS %s (
        day TEXT PRIMARY KEY,
        traffic_tb REAL, active_user INTEGER, video_tb REAL, video_mbps REAL,
        cache_tb REAL, noncache_tb REAL, tcp_tb REAL,
        tcp_success_pct REAL, tcp_ul_retrans_pct REAL, tcp_dl_retrans_pct REAL,
        tcp_ul_rtt_ms REAL, tcp_dl_rtt_ms REAL, game_tb REAL,
        top_service TEXT, top_service_tb REAL,
        blocks_ok INTEGER, suspect_json TEXT,
        run_id TEXT, updated_at TEXT)""" % DAILY_TABLE)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_%s_day ON %s(day)"
                 % (DAILY_TABLE, DAILY_TABLE))
    # 下钻明细：主键 (day, appname) —— 重跑同一天覆盖同一天同一业务，天然幂等
    conn.execute("""CREATE TABLE IF NOT EXISTS %s (
        day TEXT, appname TEXT,
        total_tb REAL, local_tb REAL, abroad_tb REAL, unknown_tb REAL,
        run_id TEXT, updated_at TEXT,
        PRIMARY KEY (day, appname))""" % APP_OFFLOAD_TABLE)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_%s_day ON %s(day)"
                 % (APP_OFFLOAD_TABLE, APP_OFFLOAD_TABLE))
    conn.commit()


def upsert_days(rows: Iterable[Dict[str, Any]], path: Optional[Path] = None) -> int:
    """按天 upsert（天数极少，逐行 INSERT OR REPLACE 足够，且天然幂等）。

    更新时用 `COALESCE(excluded.x, x)`：**只覆盖这次真的取到的列**。
    这样「只跑部分块」的补数（例如只跑 game）不会把当天其它指标清成 NULL；
    完整的日常同步所有列都有值，行为与整体覆盖一致。
    """
    items = [r for r in rows if r.get("day") not in (None, "")]
    if not items:
        return 0
    cols = ["day"] + list(RAW_COLUMNS)
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join("%s=COALESCE(excluded.%s,%s)" % (c, c, c) for c in RAW_COLUMNS)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with closing(connect(path)) as conn:
        ensure_schema(conn)
        for row in items:
            values = [iso_day(row.get("day"))]                            # 主键统一 ISO 格式
            for col in RAW_COLUMNS:
                value = row.get(col)
                if col == "suspect_json" and value is not None and not isinstance(value, str):
                    value = json.dumps(value, ensure_ascii=False)
                values.append(value)
            values[-1] = values[-1] or now                               # updated_at 兜底
            conn.execute("INSERT INTO %s (%s) VALUES (%s) ON CONFLICT(day) DO UPDATE SET %s"
                         % (DAILY_TABLE, ",".join(cols), placeholders, updates), values)
        conn.commit()
    return len(items)


APP_OFFLOAD_COLUMNS: Tuple[str, ...] = ("total_tb", "local_tb", "abroad_tb", "unknown_tb")
OFFLOAD_TOP = 40                                            # 下钻表默认展开前 N 个业务，其余并入「其它」


def upsert_app_offload(rows: Iterable[Dict[str, Any]], path: Optional[Path] = None) -> int:
    """写入分业务本地/海外分流明细，按 (day, appname) 覆盖 —— 同一天重跑幂等。"""
    items = [r for r in rows
             if r.get("day") not in (None, "") and r.get("appname") not in (None, "")]
    if not items:
        return 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cols = ["day", "appname"] + list(APP_OFFLOAD_COLUMNS) + ["run_id", "updated_at"]
    placeholders = ",".join("?" for _ in cols)
    with closing(connect(path)) as conn:
        ensure_schema(conn)
        for row in items:
            conn.execute("INSERT OR REPLACE INTO %s (%s) VALUES (%s)"
                         % (APP_OFFLOAD_TABLE, ",".join(cols), placeholders),
                         [iso_day(row["day"]), str(row["appname"])[:120]]
                         + [row.get(c) for c in APP_OFFLOAD_COLUMNS]
                         + [row.get("run_id"), row.get("updated_at") or now])
        conn.commit()
    return len(items)


def app_offload_days(path: Optional[Path] = None) -> List[str]:
    """下钻明细已覆盖的天（升序）。同步用它判断「这天要不要重取」。"""
    try:
        with closing(connect(path, readonly=True)) as conn:
            return [iso_day(r[0]) for r in conn.execute(
                "SELECT DISTINCT day FROM %s ORDER BY day" % APP_OFFLOAD_TABLE)]
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib-kpi] 读取分流日清单失败: %s", exc)
        return []


def _offload_pack(name: str, values: Sequence[Any]) -> Dict[str, Any]:
    total, local, abroad, unknown = [float(v or 0) for v in values[:4]]
    known = local + abroad
    return {"appname": str(name), "total_tb": round(total, 3), "local_tb": round(local, 3),
            "abroad_tb": round(abroad, 3), "unknown_tb": round(unknown, 3),
            # 本地占的分母**只含已识别服务器 IP 的流量**：解析不出 server_ip 的那部分
            # （HTTPS/QUIC/UDP，实测约占全天 9%）既没走本地也没走海外，
            # 塞进任一边都会让比例失真 —— 单列 unknown_tb，分母用 total_tb - unknown_tb。
            "local_pct": (round(local / known * 100.0, 1) if known > 0 else None)}


def _offload_rollup(rows: List[Dict[str, Any]], limit: int
                    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """前 limit 行原样返回，其余合并成一行「其它」；totals 由调用方按全量算，不丢数。"""
    if len(rows) <= limit:
        return rows, None
    tail = rows[limit:]
    rest = [sum(float(r.get(c) or 0) for r in tail) for c in APP_OFFLOAD_COLUMNS]
    return rows[:limit], _offload_pack("", rest)


def build_app_offload(days: int = 90, as_of: Optional[str] = None,
                      top: int = OFFLOAD_TOP, path: Optional[Path] = None) -> Dict[str, Any]:
    """下钻载荷：最新一天的分业务本地/海外拆分 + 窗口累计（同一份数据两种视角）。"""
    days = max(1, min(int(days or 90), 400))
    top = max(5, min(int(top or OFFLOAD_TOP), 200))
    body: Dict[str, Any] = {"status": "ok", "source": "olib_soc_report",
                            "window_days": days, "top": top,
                            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "as_of": None, "window": {}, "day": {"rows": [], "others": None,
                                                                 "totals": None},
                            "window_agg": {"rows": [], "others": None, "totals": None}}
    if not table_exists(path):
        body["status"] = "empty"
        body["message"] = "KPI 库尚未生成，分流明细也就没有"
        return body
    have = app_offload_days(path=path)
    if not have:
        body["status"] = "empty"
        body["message"] = "分业务分流明细为空：跑一次 olib_soc_kpi_daily_sync（或月报）即写入"
        return body
    newest = iso_day(as_of) if as_of else have[-1]
    begin = (date.fromisoformat(newest) - timedelta(days=days - 1)).isoformat()
    body["as_of"] = newest
    body["window"] = {"begin": begin, "end": newest,
                      "stored_days": len([d for d in have if begin <= d <= newest])}
    try:
        with closing(connect(path, readonly=True)) as conn:
            cur = conn.execute("SELECT appname, total_tb, local_tb, abroad_tb, unknown_tb "
                               "FROM %s WHERE day=? ORDER BY total_tb DESC" % APP_OFFLOAD_TABLE,
                               (newest,))
            day_rows = [_offload_pack(r[0], r[1:]) for r in cur.fetchall()]
            cur = conn.execute("SELECT appname, SUM(total_tb), SUM(local_tb), SUM(abroad_tb), "
                               "SUM(unknown_tb) FROM %s WHERE day>=? AND day<=? "
                               "GROUP BY appname ORDER BY SUM(total_tb) DESC"
                               % APP_OFFLOAD_TABLE, (begin, newest))
            win_rows = [_offload_pack(r[0], r[1:]) for r in cur.fetchall()]
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib-kpi] 分流明细查询失败: %s", exc)
        body["status"] = "error"
        body["message"] = "%s: %s" % (type(exc).__name__, exc)
        return body
    for key, rows in (("day", day_rows), ("window_agg", win_rows)):
        shown, others = _offload_rollup(rows, top)
        totals = _offload_pack("", [sum(float(r.get(c) or 0) for r in rows)
                                    for c in APP_OFFLOAD_COLUMNS])
        totals["apps"] = len(rows)
        body[key] = {"rows": shown, "others": others, "totals": totals}
    return body


def stored_days(path: Optional[Path] = None) -> List[str]:
    try:
        with closing(connect(path, readonly=True)) as conn:
            return [iso_day(r[0]) for r in conn.execute(
                "SELECT day FROM %s ORDER BY day" % DAILY_TABLE)]
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib-kpi] 读取日清单失败: %s", exc)
        return []


def table_exists(path: Optional[Path] = None) -> bool:
    """库文件在不在、`daily_kpi` 建没建（看板首次打开时给友好空态，而不是报错）。"""
    target = Path(path or KPI_DB_PATH)
    if not target.exists():
        return False
    try:
        with closing(connect(target, readonly=True)) as conn:
            return conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (DAILY_TABLE,)).fetchone() is not None
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib-kpi] 表检查失败: %s", exc)
        return False


# ==========================================================================
# 取数 + 聚合
# ==========================================================================
def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def _metric_day_value(metric: Dict[str, Any], row: Dict[str, Any]) -> Optional[float]:
    """单日指标值：派生指标现算，普通指标取值 * scale。"""
    if metric.get("den"):
        total = 0.0
        for token in str(metric["den"]).split("+"):
            part = _num(row.get(token.strip()))
            if part is None:
                return None
            total += part
        numer = _num(row.get(metric["num"]))
        if numer is None or total == 0:
            return None
        return numer / total * float(metric.get("scale", 1.0))
    value = _num(row.get(metric.get("col")))
    return None if value is None else value * float(metric.get("scale", 1.0))


def _metric_agg_value(metric: Dict[str, Any], rows: Sequence[Dict[str, Any]]) -> Optional[float]:
    """按周（或任意一段）聚合：sum / mean / wavg:col / ratio —— 全部保持正确口径。"""
    kind = str(metric.get("agg_week") or "mean")
    scale = float(metric.get("scale", 1.0))
    if kind == "ratio" or metric.get("den"):
        total = 0.0
        numer = 0.0
        seen = False
        for row in rows:
            parts, ok = 0.0, True
            for token in str(metric["den"]).split("+"):
                part = _num(row.get(token.strip()))
                if part is None:
                    ok = False
                    break
                parts += part
            num = _num(row.get(metric["num"]))
            if not ok or num is None:
                continue
            total += parts
            numer += num
            seen = True
        if not seen or total == 0:
            return None
        return numer / total * scale
    if kind.startswith("wavg:"):
        weight_col = kind.split(":", 1)[1]
        num, den = 0.0, 0.0
        for row in rows:
            value, weight = _num(row.get(metric.get("col"))), _num(row.get(weight_col))
            if value is None or weight is None or weight <= 0:
                continue
            num += value * weight
            den += weight
        return None if den == 0 else num / den * scale
    values = [v for v in (_metric_day_value(metric, row) for row in rows) if v is not None]
    if not values:
        return None
    if kind == "sum":
        return sum(values)
    return sum(values) / len(values)


def _fetch_rows(conn: sqlite3.Connection, begin: str, end: str) -> List[Dict[str, Any]]:
    cols = ",".join(("day",) + RAW_COLUMNS)
    cur = conn.execute("SELECT %s FROM %s WHERE day >= ? AND day <= ? ORDER BY day"
                       % (cols, DAILY_TABLE), (begin, end))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def fetch_range(begin: str, end: str, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """取 [begin, end] 的原始日值（ISO 日期字符串），按天升序。公开给路由/排查脚本用。"""
    try:
        with closing(connect(path, readonly=True)) as conn:
            return _fetch_rows(conn, iso_day(begin), iso_day(end))
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib-kpi] 区间查询失败: %s", exc)
        return []


def _iso_week(iso: str) -> Tuple[str, str]:
    """返回 (ISO 周标签 '2026-W37', 该周周一 'YYYY-MM-DD')。"""
    d = date.fromisoformat(iso)
    monday = d - timedelta(days=d.weekday())
    year, week, _ = monday.isocalendar()
    return "%d-W%02d" % (year, week), monday.isoformat()


def _spark(values: Sequence[Optional[float]], points: int = 30) -> List[Optional[float]]:
    """把 90 天压成 ~30 个点给卡片迷你走势（保留空值）。"""
    vals = list(values)
    if len(vals) <= points:
        return vals
    step = len(vals) / float(points)
    out: List[Optional[float]] = []
    for i in range(points):
        chunk = [v for v in vals[int(i * step):max(int((i + 1) * step), int(i * step) + 1)]
                 if v is not None]
        out.append(sum(chunk) / len(chunk) if chunk else None)
    return out


def build_overview(days: int = 90, path: Optional[Path] = None,
                   today: Optional[date] = None) -> Dict[str, Any]:
    """看板一次性载荷：卡片（昨日 + 90 天最大/平均/最低）+ 日/周趋势 + 明细表。"""
    today = today or date.today()
    days = max(7, min(int(days or 90), 400))
    end = today - timedelta(days=1)                                      # 当天仍在累积，只用已完成日
    begin = end - timedelta(days=days - 1)
    body: Dict[str, Any] = {
        "status": "ok", "source": "olib_soc_report", "window_days": days,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window": {"begin": begin.isoformat(), "end": end.isoformat()},
        "coverage": {"oldest": None, "newest": None, "stored_days": 0, "expected_days": days,
                     "missing_days": [], "incomplete_days": []},
        "cards": [], "series": {"day": {}, "week": {}}, "table": [], "quality": [],
        "metrics": [{"id": m["id"], "title": m["title"], "title_en": m["title_en"],
                     "unit": m["unit"], "digits": m["digits"], "better": m["better"],
                     "group": m["group"], "note": m.get("note", ""),
                     "note_en": m.get("note_en", "")} for m in METRICS],
    }
    if not table_exists(path):
        body["status"] = "empty"
        body["message"] = "KPI 库尚未生成：先跑 olib_soc_kpi_daily_sync 或 olib_soc_vmax_report"
        return body
    try:
        with closing(connect(path, readonly=True)) as conn:
            rows = _fetch_rows(conn, begin.isoformat(), end.isoformat())
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib-kpi] 查询失败: %s", exc)
        body["status"] = "error"
        body["message"] = "%s: %s" % (type(exc).__name__, exc)
        return body
    if not rows:
        body["status"] = "empty"
        body["message"] = "窗口内没有 KPI 数据"
        return body

    stored = [r["day"] for r in rows]
    expected = [(begin + timedelta(days=i)).isoformat() for i in range(days)]
    # 残缺日：行在、但某个关键指标列为 NULL（该指标卡片会「少一天」）。
    # 直接复用已取到的 rows 判定，不再多查一次库（口径与 all_incomplete_days 一致）。
    incomplete = [r["day"] for r in rows
                  if any(r.get(c) is None for c in REQUIRED_COLUMNS)]
    body["coverage"] = {
        "oldest": stored[0], "newest": stored[-1], "stored_days": len(stored),
        "expected_days": days, "missing_days": [d for d in expected if d not in set(stored)],
        "incomplete_days": incomplete,
    }
    body["updated_at"] = max((r.get("updated_at") or "") for r in rows)
    body["as_of"] = stored[-1]

    # ---- 日序列 ----
    day_dates = [r["day"] for r in rows]
    day_values: Dict[str, List[Optional[float]]] = {}
    for metric in METRICS:
        day_values[metric["id"]] = [_metric_day_value(metric, r) for r in rows]
    body["series"]["day"] = {"dates": day_dates, "values": day_values}

    # ---- 周序列（ISO 周，周一~周日；最后一周可能不满，仍按已有天数汇总并标注天数）----
    weeks: List[Dict[str, Any]] = []
    for row in rows:
        label, monday = _iso_week(row["day"])
        if not weeks or weeks[-1]["label"] != label:
            weeks.append({"label": label, "monday": monday, "rows": []})
        weeks[-1]["rows"].append(row)
    week_labels = [w["label"] for w in weeks]
    week_values: Dict[str, List[Optional[float]]] = {}
    for metric in METRICS:
        week_values[metric["id"]] = [_metric_agg_value(metric, w["rows"]) for w in weeks]
    body["series"]["week"] = {
        "labels": week_labels, "mondays": [w["monday"] for w in weeks],
        "days": [len(w["rows"]) for w in weeks], "values": week_values}

    # ---- 卡片：昨日（最新已完成日）+ 90 天最大/平均/最低 + 周同比/月同比 ----
    for metric in METRICS:
        values = day_values[metric["id"]]
        numbers = [(day_dates[i], values[i]) for i in range(len(values)) if values[i] is not None]
        if not numbers:
            continue
        last_day, last_value = numbers[-1]
        card: Dict[str, Any] = {
            "id": metric["id"], "title": metric["title"], "title_en": metric["title_en"],
            "unit": metric["unit"], "digits": metric["digits"], "better": metric["better"],
            "group": metric["group"], "note": metric.get("note", ""),
            "note_en": metric.get("note_en", ""),
            "latest": {"date": last_day, "value": round(last_value, 6)},
            "avg": round(sum(v for _, v in numbers) / len(numbers), 6),
            "n": len(numbers),
            "spark": [None if v is None else round(v, 6) for v in _spark(values)],
        }
        # max/min 一律是序列的算术最大/最小（"越大越好"只影响前端配色，不改极值语义）
        top = max(numbers, key=lambda x: x[1])
        bottom = min(numbers, key=lambda x: x[1])
        card["max"] = {"date": top[0], "value": round(top[1], 6)}
        card["min"] = {"date": bottom[0], "value": round(bottom[1], 6)}
        # 周同比 / 月同比：与「上周同一天」「4 周前同一天」比，避开星期几季节性
        last_iso = date.fromisoformat(last_day)
        by_day = dict(numbers)
        wow = by_day.get((last_iso - timedelta(days=7)).isoformat())
        mom = by_day.get((last_iso - timedelta(days=28)).isoformat())
        if wow not in (None, 0):
            card["wow_pct"] = round((last_value - wow) / abs(wow) * 100.0, 2)
            card["wow_base"] = {"date": (last_iso - timedelta(days=7)).isoformat(),
                                "value": round(wow, 6)}
        if mom not in (None, 0):
            card["mom_pct"] = round((last_value - mom) / abs(mom) * 100.0, 2)
            card["mom_base"] = {"date": (last_iso - timedelta(days=28)).isoformat(),
                                "value": round(mom, 6)}
        body["cards"].append(card)

    # ---- 明细表（最近 14 天，CEO 页只给近期；完整区间在 CSV/Excel）----
    tail = list(reversed(rows))[:14]
    body["table"] = [{
        "date": r["day"],
        "traffic_gb": None if r.get("traffic_tb") is None else round(r["traffic_tb"] * 1024.0, 0),
        "active_user": r.get("active_user"),
        "video_gb": None if r.get("video_tb") is None else round(r["video_tb"] * 1024.0, 0),
        "video_thr_kbps": None if r.get("video_mbps") is None else round(r["video_mbps"] * 1000.0, 0),
        "cache_ratio_pct": (None if not r.get("noncache_tb") and not r.get("cache_tb") else
                            round((r.get("cache_tb") or 0) /
                                  ((r.get("cache_tb") or 0) + (r.get("noncache_tb") or 0)) * 100.0, 1)),
        "tcp_success_pct": r.get("tcp_success_pct"),
        "top_service": r.get("top_service"),
        "suspect": bool(r.get("suspect_json")),
        # 残缺：某个关键指标列为 NULL（与 coverage.incomplete_days 同口径）
        "incomplete": any(r.get(c) is None for c in REQUIRED_COLUMNS),
    } for r in tail]

    # ---- 数据质量：哪些天被标记过（8/11~8/14 那种上游缺数）----
    for r in rows:
        if r.get("suspect_json"):
            try:
                flags = json.loads(r["suspect_json"])
            except Exception:                                            # noqa: BLE001
                flags = []
            for item in (flags if isinstance(flags, list) else []):
                if not isinstance(item, dict):
                    continue
                # item 里自带 YYYYMMDD 的 day，这里以库里的 ISO 日期为准
                body["quality"].append({"day": r["day"],
                                        **{k: v for k, v in item.items() if k != "day"}})
    return body


def gap_days(days_back: int = 7, path: Optional[Path] = None,
             today: Optional[date] = None) -> List[str]:
    """需要补齐的日期：窗口内库里没有的天（用于每日增量同步，幂等自愈）。"""
    today = today or date.today()
    end = today - timedelta(days=1)
    begin = end - timedelta(days=max(1, int(days_back)) - 1)
    have = set(stored_days(path))
    return [(begin + timedelta(days=i)).isoformat()
            for i in range((end - begin).days + 1)
            if (begin + timedelta(days=i)).isoformat() not in have]


# 判断「这天是否残缺」的核心指标：**看板上每个主数值卡都对应一列**，任一列为 NULL
# 就意味着那张卡片「比别的指标少一天」（卡片取的是该指标自己序列里最后一个有值日）。
# 早期只放了 traffic_tb / active_user / video_tb 三列，结果 2026-09-07 的 traffic_tb 之外
# 其它列缺失时无人发现、永久残留 —— 所以这里覆盖全部主数值列。
# 只列 RAW 数值列，避免把 top_service（TEXT）/ suspect_json 之类可选列算进来。
REQUIRED_COLUMNS: Tuple[str, ...] = (
    "traffic_tb", "active_user", "video_tb", "video_mbps",
    "cache_tb", "noncache_tb", "tcp_tb",
    "tcp_success_pct", "tcp_ul_retrans_pct", "tcp_dl_retrans_pct",
    "tcp_ul_rtt_ms", "tcp_dl_rtt_ms", "game_tb",
)


def incomplete_days(days_back: int = 7, path: Optional[Path] = None,
                    today: Optional[date] = None) -> List[str]:
    """窗口内**行已存在但关键指标为 NULL** 的天（用于每日增量同步的幂等自愈）。

    背景（2026-09-24 事故）：`gap_days` 只看「这天有没有行」，而某次运行若单个块
    临时取数失败，仍会写入一行（其余块有值），只是该块对应的列是 NULL。
    这种「行在但格子空」的天不会被 `gap_days` 认为是缺口，于是 NULL 永久残留 ——
    2026-09-18~23 的 `active_user` 就是这么丢了 6 天。

    因此除了补「没有的天」，还要补「有行但不完整的天」。
    """
    today = today or date.today()
    end = today - timedelta(days=1)
    begin = end - timedelta(days=max(1, int(days_back)) - 1)
    return _incomplete_between(begin.isoformat(), end.isoformat(), path)


def all_incomplete_days(path: Optional[Path] = None) -> List[str]:
    """**全表**扫描：所有「行已存在但关键指标为 NULL」的天（不限窗口）。

    `incomplete_days()` 只看最近 N 天；一旦某个残缺日滑出回看窗口就再也补不到
    （2026-09-07 的 `traffic_tb` 正是这样遗留至今）。这个函数给"全量自愈"用：
    每日同步把它捞出的天一并重取，历史上任何残留都能被自动修正（取数幂等，可重复）。
    """
    return _incomplete_between(None, None, path)


def _incomplete_between(begin: Optional[str], end: Optional[str],
                        path: Optional[Path] = None) -> List[str]:
    """[begin, end] 内关键列为 NULL 的天；begin/end 为 None 时扫全表（共用一份列清单）。"""
    where = " OR ".join("%s IS NULL" % c for c in REQUIRED_COLUMNS)
    sql = "SELECT day FROM %s WHERE (%s)" % (DAILY_TABLE, where)
    params: Tuple[Any, ...] = ()
    if begin is not None and end is not None:
        sql += " AND day >= ? AND day <= ?"
        params = (begin, end)
    sql += " ORDER BY day"
    try:
        with closing(connect(path, readonly=True)) as conn:
            rows = conn.execute(sql, params).fetchall()
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[olib-kpi] 残缺日检查失败: %s", exc)
        return []
    return [iso_day(r[0]) for r in rows]


def incomplete_days_in_window(begin: str, end: str,
                              path: Optional[Path] = None) -> List[str]:
    """任意 [begin, end] 区间内关键列为 NULL 的天（看板 coverage 用，ISO 字符串入参）。"""
    return _incomplete_between(iso_day(begin), iso_day(end), path)

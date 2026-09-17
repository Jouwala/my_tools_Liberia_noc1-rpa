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
                     "missing_days": []},
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
    body["coverage"] = {
        "oldest": stored[0], "newest": stored[-1], "stored_days": len(stored),
        "expected_days": days, "missing_days": [d for d in expected if d not in set(stored)],
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

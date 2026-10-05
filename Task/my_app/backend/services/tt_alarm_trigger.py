"""P1 告警推送的**触发源**：扫描 `realtime_alarm` 找出带 TT 的待推告警。

## 为什么触发源是 realtime_alarm 而不是 eflow_tt（2026-10-05 机制切换）

旧机制每 15 分钟扫 `eflow_tt`（按 alarm_occur_time 取 3 小时窗口），但那张表
只由 `eflow_sync` **每小时 :22** 刷新一次 —— 告警发生到群里看到，平均 ~45 分钟、
最坏 ~75 分钟，对 P1 来说太慢。而 `realtime_alarm` 由 `eflow_active_alarm`
每 30 分钟同步（实时告警接口 `/api/fm-active/v1/activealarms/table`），
行里带 `tt_id`（格式与 eflow_tt.tt_no 一致，实测 'TT202610030077'）、
`alarmraisedtime`（epoch 毫秒）、`alarmcode` —— 是现成的「新 P1 告警出现」信号。
触发之后的详情（级别/更新时间/是否清除）由主服务**实时回 eFlow 查单**补齐，
不再受任何镜像的同步周期约束。

## 触发口径（全部条件同时满足）

1. `tt_id` 非空 —— 没有 TT 的告警无可推送对象（TT 尚未创建的告警会在
   下一次 `eflow_active_alarm` 同步补上 tt_id 后自然触发）；
2. `alarmraisedtime` 在**触发窗口**内（默认 180 分钟）—— 窗口只约束**首推**，
   兼防首次部署时把表里积压的历史未清除告警一次性全推出去；
3. 告警码在白名单内（空 = 不过滤），归一化规则与 eflow_tt 相同
   （`norm_alarm_code`，'99933.0' → '99933'）。

同一 `tt_id` 关联多条告警（如同站 2G/4G CELL DOWN 各一条）时**只保留
alarmraisedtime 最新的一条** —— 推送对象是 TT 不是告警，一条 TT 推一次。

## 表新鲜度检查

`realtime_alarm` 停止同步（eflow_active_alarm 挂了/登录失效）时，本模块扫出的
候选会**静默变空**，推送任务表面一切正常 —— 这正是 2026-10-01「群内静默」事故
的形态。故每轮顺带检查 `max(_sync_time)`：落后超过 `SYNC_STALE_SECONDS`
（默认 45 分钟 = 1.5 个同步周期）即置 `meta["sync_lag_seconds"]`，
由调用方把告警塞进 warnings 喊人。

## 时间口径

`alarmraisedtime` 是 epoch 毫秒。所有窗口比较都在 **epoch 空间**完成
（`now.timestamp()*1000` vs 列值），不依赖机器时区；展示/落库用
`datetime.fromtimestamp(ms/1000)` 转本机wall time，与 eflow_tt 的时间文本同风格。
"""
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.services.tt_alarm_message import norm_alarm_code, s as _s

logger = logging.getLogger("tt_alarm_whatsapp")

TRIGGER_TABLE = "realtime_alarm"

# 心跳滞后阈值（秒）：realtime_alarm 每 30 分钟同步一次，45 分钟没动静
# 说明至少错过一轮同步，触发面可能已经失真，必须喊人。
SYNC_STALE_SECONDS = int(os.environ.get("TT_TRIGGER_SYNC_STALE_SECONDS", "2700"))

# 本模块要读的列。与表实际列求交集（兼容不同同步版本的列差异）；
# alarm_title/codename/perceivedseverityname 仅用于任务结果的现场信息，非必填。
_TRIGGER_COLUMNS = (
    "tt_id", "alarmraisedtime", "alarmcode", "site_id", "site_name",
    "region", "codename", "alarm_title", "perceivedseverityname",
    "clearstatename", "_sync_time",
)


def _available_columns(conn, table: str) -> List[str]:
    """表实际存在的列 ∩ 我们要读的列（双模：sqlite / PG）。"""
    import sqlite3
    if isinstance(conn, sqlite3.Connection):
        present = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    else:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ? "
            "AND table_schema = ANY(current_schemas(false))",
            (table,),
        ).fetchall()
        present = {r[0] for r in rows}
    return [c for c in _TRIGGER_COLUMNS if c in present]


def parse_epoch_ms(val: Any) -> Optional[datetime]:
    """epoch 毫秒 → 本机 wall time；非法/为空返回 None。"""
    text = _s(val)
    if not text:
        return None
    try:
        return datetime.fromtimestamp(float(text) / 1000.0)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def fetch_triggered_tts(now: datetime,
                        window_minutes: int,
                        alarm_codes: Set[str],
                        query_limit: int = 500) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """扫描 realtime_alarm，返回触发窗口内带 TT 的告警（按 tt_id 去重）。

    返回 ``(rows, meta)``：
      * rows —— list[dict]，已按 alarmraisedtime 倒序，字段：
        `tt_no` / `alarm_raised_time`（可读文本）/ `_alarm_raised_dt`（datetime，
        供调用方算 open 时长）/ `_alarm_code_norm` / site / region 等；
      * meta —— {window_since, scanned, truncated, sync_lag_seconds, table_exists}

    告警码白名单在 **Python 侧**过滤：`alarmcode` 与 eflow_tt.alarm_code 同病，
    库里 `'99933'` 与 `'99933.0'` 多形态并存（见 tt_alarm_whatsapp_service 的
    模块 docstring），SQL 侧判等必然漏。`alarm_codes` 为空集 = 不过滤。
    """
    since_ms = int((now.timestamp() - window_minutes * 60) * 1000)
    meta: Dict[str, Any] = {
        "window_minutes": window_minutes,
        "window_since": datetime.fromtimestamp(since_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S"),
        "scanned": 0,
        "truncated": False,
        "sync_lag_seconds": None,
        "table_exists": True,
    }

    from backend.database import get_raw_connection

    with get_raw_connection() as conn:
        if not _table_exists(conn, TRIGGER_TABLE):
            meta["table_exists"] = False
            return [], meta

        cols = _available_columns(conn, TRIGGER_TABLE)
        if "tt_id" not in cols or "alarmraisedtime" not in cols:
            meta["table_exists"] = False
            return [], meta

        # 只下推「有 TT + 时间窗口」两个可安全表达的谓词；告警码在 Python 侧归一化后判等。
        sql = (f"SELECT {', '.join(cols)} FROM {TRIGGER_TABLE} "
               f"WHERE TRIM(CAST(tt_id AS TEXT)) <> '' AND alarmraisedtime >= ? "
               f"ORDER BY alarmraisedtime DESC LIMIT ?")
        cur = conn.execute(sql, (since_ms, query_limit))
        names = [d[0] for d in cur.description]
        raw_rows = [dict(zip(names, r)) for r in cur.fetchall()]

        # 表新鲜度：_sync_time 由 eflow_active_alarm 每轮写入（isoformat 文本）。
        if "_sync_time" in cols:
            cur = conn.execute(f"SELECT MAX(_sync_time) FROM {TRIGGER_TABLE}")
            max_sync = cur.fetchone()[0] if cur.description else None
            try:
                last = datetime.fromisoformat(str(max_sync))
                meta["sync_lag_seconds"] = round((now - last).total_seconds(), 1)
            except (ValueError, TypeError):
                meta["sync_lag_seconds"] = None

    meta["scanned"] = len(raw_rows)
    if len(raw_rows) >= query_limit:
        meta["truncated"] = True

    # 按 tt_id 去重（SQL 已按 alarmraisedtime 倒序，首个即最新）+ 告警码白名单。
    picked: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for r in raw_rows:
        tt_no = _s(r.get("tt_id")).upper()
        if not tt_no or tt_no in seen:
            continue
        code = norm_alarm_code(r.get("alarmcode"))
        if alarm_codes and code not in alarm_codes:
            continue
        raised_dt = parse_epoch_ms(r.get("alarmraisedtime"))
        if raised_dt is None:
            # 时间不可解析的行无法判断新旧（也说明数据形态变了），宁可不触发
            continue
        seen.add(tt_no)
        row = dict(r)
        row["tt_no"] = tt_no
        row["_alarm_code_norm"] = code
        row["_alarm_raised_dt"] = raised_dt
        row["alarm_raised_time"] = raised_dt.strftime("%Y-%m-%d %H:%M:%S")
        picked.append(row)

    logger.info("[TTAlert] 触发扫描：窗口 %s 起，扫描 %s 行，命中 %s 单（告警码白名单 %s）",
                meta["window_since"], meta["scanned"], len(picked),
                sorted(alarm_codes) or "全部")
    return picked, meta


def _is_sqlite(conn) -> bool:
    import sqlite3
    return isinstance(conn, sqlite3.Connection)


def _table_exists(conn, table: str) -> bool:
    """表是否存在（双模：sqlite / PG，限定当前 search_path）。"""
    if _is_sqlite(conn):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table,)).fetchone()
        return row is not None
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = ? "
        "AND table_schema = ANY(current_schemas(false))",
        (table,)).fetchall()
    return bool(rows)

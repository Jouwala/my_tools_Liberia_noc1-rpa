"""P1 告警推送的**触发源**：扫描 `realtime_alarm` 找出带 TT 的待推告警。

## 为什么触发源是 realtime_alarm 而不是 eflow_tt（2026-10-05 机制切换）

旧机制每 15 分钟扫 `eflow_tt`（按 alarm_occur_time 取 3 小时窗口），但那张表
只由 `eflow_sync` **每小时 :22** 刷新一次 —— 告警发生到群里看到，平均 ~45 分钟、
最坏 ~75 分钟。而 `realtime_alarm` 由 `eflow_active_alarm` 同步（注册表默认
`*/30`，**实际周期以任务配置页的调度为准**，2026-10-05 核定生产为 `*/5`），行里带
`tt_id`（格式与 eflow_tt.tt_no 一致，实测 'TT202610030077'）、
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

## 表新鲜度检查（阈值自适应）

`realtime_alarm` 停止同步（eflow_active_alarm 挂了/登录失效）时，本模块扫出的
候选会**静默变空**，推送任务表面一切正常 —— 这正是 2026-10-01「群内静默」事故
的形态。故每轮顺带检查 `max(_sync_time)` 滞后，超过阈值即由调用方喊人。

⚠️ **阈值必须跟随实际调度周期**，不能写死：eflow_active_alarm 的 cron 在任务
配置页可改（注册表默认 `*/30`，2026-10-05 核定生产为 `*/5`）——按 30 分钟定的
45 分钟阈值在 5 分钟周期下形同虚设，告警真挂了也要 45 分钟才有人知道。故阈值按
优先级取：显式环境变量 `TT_TRIGGER_SYNC_STALE_SECONDS` > 从
`task_schedule_config` 读实际 cron 推导（周期 × 1.5，下限 5 分钟防抖）>
内置默认 2700 秒。

## 时间口径

`alarmraisedtime` 是 epoch 毫秒。所有窗口比较都在 **epoch 空间**完成
（`now.timestamp()*1000` vs 列值），不依赖机器时区；展示/落库用
`datetime.fromtimestamp(ms/1000)` 转本机wall time，与 eflow_tt 的时间文本同风格。
"""
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.services.tt_alarm_message import norm_alarm_code, s as _s

logger = logging.getLogger("tt_alarm_whatsapp")

TRIGGER_TABLE = "realtime_alarm"
SYNC_TASK_ID = "eflow_active_alarm"

# 兜底阈值（秒）：仅当 env 未设、且读不到/解析不了实际 cron 时使用。
SYNC_STALE_SECONDS = int(os.environ.get("TT_TRIGGER_SYNC_STALE_SECONDS", "2700"))
# 自适应推导的下限（秒）：周期配得再密（如 */1）也不低于 5 分钟，防同步抖动误报。
SYNC_STALE_FLOOR_SECONDS = 300

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


def estimate_cron_interval_minutes(cron: str) -> Optional[int]:
    """把常见形态的 cron 估算成周期（分钟）；识别不了的返回 None。

    只覆盖这个项目里实际出现的形态（**不追求通用 cron 解析**）：
      * ``*/5 * * * *``       → 5（分钟步进，eflow_active_alarm 生产在用）
      * ``22 * * * *``        → 60（每小时固定分钟，eflow_sync 在用）
      * ``0 */6 * * *``       → 360（每 N 小时）
      * ``0 5 * * *``         → 1440（每天固定时刻）
    """
    cron = (cron or "").strip()
    if not cron:
        return None
    if re.fullmatch(r"\*/(\d+) \* \* \* \*", cron):
        return int(cron.split()[0][2:])
    if re.fullmatch(r"\d+ \* \* \* \*", cron):
        return 60
    if re.fullmatch(r"\d+ \*/(\d+) \* \* \*", cron):
        return int(cron.split()[1][2:]) * 60
    if re.fullmatch(r"\d+ \d+ \* \* \*", cron):
        return 1440
    return None


def _resolve_sync_stale_threshold(conn, env: Optional[Dict[str, str]] = None) -> int:
    """解析表新鲜度阈值（秒）。优先级：env > 实际 cron 推导 > 内置默认。

    读 `task_schedule_config` 里 SYNC_TASK_ID 的**生效** cron —— 任务配置页改的
    就是这张表，注册表里的 default_cron 只是首次注册的初值（2026-10-05 核定：
    该任务默认 */30、生产实际 */5，静态 45 分钟阈值在 5 分钟周期下迟钝 9 倍）。
    表不存在/行不存在/cron 识别不了 → 退回 SYNC_STALE_SECONDS 兜底。
    """
    env_val = (env or os.environ).get("TT_TRIGGER_SYNC_STALE_SECONDS")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    try:
        row = conn.execute(
            "SELECT cron FROM task_schedule_config WHERE task_id = ?",
            (SYNC_TASK_ID,)).fetchone()
    except Exception:  # noqa: BLE001 - 表可能还没建（task_runner 未初始化），走兜底
        return SYNC_STALE_SECONDS
    minutes = estimate_cron_interval_minutes(row[0] if row else None)
    if minutes is None:
        return SYNC_STALE_SECONDS
    return max(SYNC_STALE_FLOOR_SECONDS, int(minutes * 60 * 1.5))


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
        "sync_stale_threshold_seconds": SYNC_STALE_SECONDS,
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
        # 阈值随实际调度自适应（见 _resolve_sync_stale_threshold），与滞后值一并返回。
        meta["sync_stale_threshold_seconds"] = _resolve_sync_stale_threshold(conn)
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

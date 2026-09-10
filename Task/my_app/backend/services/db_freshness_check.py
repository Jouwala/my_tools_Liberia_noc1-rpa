#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_freshness_check.py — 数据库数据新鲜度巡检（每小时）

功能：
    1. 远程库（db_writer_api @ 192.168.100.19:8765）：逐表查询最新 Begin Time，
       与期望新鲜度（daily=昨天 / intraday=最近N小时 / monthly=最近33天）比对
    2. 本地回退库（API 失败时的兜底库）：sqlite3 直查最新 Begin Time
    3. 发现滞后时输出：调用链路（任务 → 服务函数 → 写入方式 → 库文件）与检查方向
    4. 任务执行健康检查（2026-08-12 新增，2026-08-13 收紧，补齐“任务从未执行”盲区）：
       - 注册任务最近 24h 无执行记录（task_execution_log，排除已禁用任务）
       - task_queue 滞留 pending(>10min) / running(>30min) 记录
       - 任务成功逾期（按 cron 周期判定，上次成功后超过一个周期下限仍无成功）
       - task_registry 注册表与 worker_watchdog 分组清单覆盖对比

设计要点：
    - 数据滞后不抛异常、不置 success=False（巡检任务本身执行成功，
      滞后详情放在 result["stale"]，避免 auto_retry 无意义重跑巡检）
    - 任务健康异常（无历史/队列滞留/分组缺失）同样不置 success=False，
      仅检查手段本身不可用（API 不可达 / 历史库连不上 / 配置加载失败）才失败
    - 检查手段本身不可用（API 不可达 / 本地库文件缺失）→ success=False，
      属于环境问题，交由 auto_retry 重试
    - 全程不写库，只读

历史教训（2026-08-11 ran_kpi_daily.sqlite3 损坏事件）：
    远程库损坏 + 客户端静默回退本地 → 任务假成功、远程库长期断档。
    本巡检即为该事件的兜底监控。
"""

import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import json
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============================================================
# 配置
# ============================================================
from backend.config.remote_host import get_api_host  # 远程主机统一来源（FTP/API/SMB 共用）

API_PORT = int(os.environ.get("DB_WRITER_PORT", "8765"))


def _api_base() -> str:
    """远程写入 API 基址（按当前生效主机实时拼装，支持页面热更新）。"""
    return f"http://{get_api_host()}:{API_PORT}"
HTTP_TIMEOUT = 60

MY_APP_DIR = Path(__file__).resolve().parents[2]  # Task/my_app

# 新鲜度规则：
#   daily    -> 期望最新日期 >= today - daily_lag_days（按任务跑完时刻判定）
#   intraday -> 期望最新时间戳距 now <= max_age_hours
#   monthly  -> 期望最新日期距 today <= 33 天
REMOTE_CHECKS = [
    dict(db="ran_kpi_daily.sqlite3", granularity="daily", run_by="05:00",
         task_id="network_kpi_sync", task_cron="0 5 * * *",
         service="backend/services/ran_ume_network_kpi.py::run_network_kpi_sync",
         write_path="DbWriterClient.write_data(upsert, pk=[Begin Time,Group]) → /api/write",
         local_db=str(Path(__file__).resolve().parent / "ran_kpi_daily.sqlite3"),
         allow_empty=False, skip_match=None),
    dict(db="ran_kpi_daily_202606.sqlite3", granularity="daily", run_by="02:30",
         task_id="ran_ume_daily", task_cron="0 2 * * *",
         service="backend/services/ran_ume_service.py::run_ran_ume_full_task",
         write_path="DbWriterClient.write_data(upsert, pk=[Begin Time,Group]) → /api/write",
         local_db=None,  # Orange 库仅远程写，无本地回退
         allow_empty=False, skip_match=None),
    dict(db="db.sqlite3", granularity="daily", run_by="04:30",
         task_id="main_kpi_sync", task_cron="0 4 * * *",
         service="backend/services/ran_ume_main_kpi.py::run_main_kpi_sync",
         write_path="DbWriterClient.upload_excel_bytes → /api/upload",
         local_db=None,  # 纯 API 写，无本地回退
         allow_empty=False, skip_match=lambda t: "Hourly" in t),  # Hourly 表设计上不同步
    dict(db="db_ps_cs_cn.sqlite3", granularity="daily", run_by="06:30",
         task_id="cnn_kpi_sync", task_cron="0 6 * * *",
         service="backend/services/ccn_ume_kpi_service.py::run_cnn_kpi_sync",
         write_path="DbWriterClient.write_data(upsert) → /api/write",
         local_db=None,
         allow_empty=True,   # monthly 模板表可能为空
         skip_match=lambda t: t.startswith("1month_")),  # 月粒度另行按 monthly 检查
    dict(db="ipran_ume_kpi.sqlite3", granularity="intraday", max_age_hours=2.0,
         task_id="ipran_kpi_sync", task_cron="0 8 * * *",
         service="backend/services/ipran_ume_kpi_service.py::run_ipran_kpi_sync",
         write_path="DbWriterClient.write_data(upsert) → /api/write（失败回退本地）",
         local_db=str(MY_APP_DIR / "data" / "ipran_ume" / "ipran_ume_kpi.sqlite3"),
         allow_empty=False, skip_match=None),
    dict(db="lbr_ms_sla_kpi.sqlite3", granularity="daily", run_by="06:30",
         task_id="ms_sla_full", task_cron="0 */6 * * *",
         service="backend/services/ms_sla_sync.py::run_ms_sla_sync",
         write_path="DbWriterClient.write_data(upsert) → /api/write（失败回退本地+日志）",
         local_db=str(MY_APP_DIR / "data" / "ms_sla" / "lbr_ms_sla_kpi.sqlite3"),
         allow_empty=False, skip_match=lambda t: "1month" in t),  # month 表无 Begin Time 日数据
]

# db_ps_cs_cn 的月粒度表单独检查
MONTHLY_CHECKS = [
    dict(db="db_ps_cs_cn.sqlite3", granularity="monthly",
         task_id="cnn_kpi_sync", task_cron="0 6 * * *",
         service="backend/services/ccn_ume_kpi_service.py::run_cnn_kpi_sync",
         write_path="DbWriterClient.write_data(upsert) → /api/write",
         local_db=None, allow_empty=True,
         only_match=lambda t: t.startswith("1month_")),
]

# 本地回退库（API 失败时数据落这里）
LOCAL_CHECKS = [
    dict(label="network_kpi 本地回退库",
         path=str(Path(__file__).resolve().parent / "ran_kpi_daily.sqlite3"),
         task_id="network_kpi_sync"),
    dict(label="ipran 本地回退库",
         path=str(MY_APP_DIR / "data" / "ipran_ume" / "ipran_ume_kpi.sqlite3"),
         task_id="ipran_kpi_sync"),
    dict(label="ms_sla 本地回退库",
         path=str(MY_APP_DIR / "data" / "ms_sla" / "lbr_ms_sla_kpi.sqlite3"),
         task_id="ms_sla_full"),
]

# 任务执行健康检查参数（2026-08-12 新增，2026-08-13 收紧）：
#   - 注册任务最近 N 小时无执行记录 → 告警（日级任务 24h 内必有记录；已禁用任务排除）
#   - task_queue 滞留阈值：pending 超 10 分钟（正常秒级被 worker 认领）、
#     running 超 30 分钟（与 worker.py 回收阈值对齐，实测最长任务 <10 分钟；
#     旧值 2h 与回收阈值相同导致检测窗口为零，eflow_sync 僵尸事件全程未报）
#   - 成功逾期：按 cron 周期判定，上次成功后超过「下次应触发时刻 + 一个周期
#     下限（至少 30 分钟）」仍无成功 → 告警（补 24h 无记录检查对小时级任务
#     不敏感的盲区）
TASK_HEALTH_LOOKBACK_HOURS = 24
TASK_HEALTH_PENDING_MAX_MINUTES = 10
TASK_HEALTH_RUNNING_MAX_MINUTES = 30


# ============================================================
# 远程 API 访问
# ============================================================
def _api_get(path: str):
    with urllib.request.urlopen(_api_base() + path, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode())


def _api_list_tables(db: str) -> list:
    info = _api_get(f"/api/tables?db={db}")
    return [t["name"] for t in info.get("tables", [])]


def _api_window_max(db: str, table: str, since: str):
    """查询窗口 [since, now) 内的 max(Begin Time)。
    用 where 窗口而非全表 limit：服务端无 ORDER BY，大表 limit 截断会取到旧数据导致误报。
    注意：columns 参数带引号列名会触发服务端 SQL 语法错误，故不传 columns。"""
    payload = {"db": db, "table": table,
               "where": f'"Begin Time" >= "{since}"', "limit": 200000}
    req = urllib.request.Request(_api_base() + "/api/read",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode())
    cols = d.get("columns", [])
    if "Begin Time" not in cols:
        return None, "no_begin_time_col"
    bi = cols.index("Begin Time")
    mx = None
    for row in d.get("rows", []):
        v = row[bi]
        if v is None:
            continue
        s = str(v)[:19]
        if mx is None or s > mx:
            mx = s
    return mx, None


# ============================================================
# 本地 SQLite 访问
# ============================================================
def _local_tables(path: str) -> list:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_temp_%'").fetchall()
    return [r[0] for r in rows]


def _local_max_begin_time(path: str, table: str):
    q = lambda c: '"' + c.replace('"', '""') + '"'
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60) as conn:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info({q(table)})').fetchall()]
        if "Begin Time" not in cols:
            return None, "no_begin_time_col"
        row = conn.execute(
            f'SELECT MAX({q("Begin Time")}) FROM {q(table)}').fetchone()
    mx = row[0] if row else None
    return (str(mx)[:19] if mx else None), None


# ============================================================
# 新鲜度判定
# ============================================================
def _window_since(granularity: str, now: datetime, cfg: dict):
    """返回 (窗口起点字符串, 期望描述)。窗口内有数据即视为新鲜。"""
    if granularity == "daily":
        run_by_h, run_by_m = (int(x) for x in cfg.get("run_by", "06:00").split(":"))
        run_done_today = now.replace(hour=run_by_h, minute=run_by_m, second=0, microsecond=0)
        # 任务跑完后期望有“昨天”的数据；跑完前容忍到“前天”
        lag = 1 if now >= run_done_today else 2
        expected_date = (now - timedelta(days=lag)).date()
        return str(expected_date), f"最新日期 >= {expected_date}（任务 {cfg.get('run_by')} 跑完，T+1）"

    if granularity == "intraday":
        since_dt = now - timedelta(hours=cfg.get("max_age_hours", 2.0))
        return since_dt.strftime("%Y-%m-%d %H:%M:%S"), f"最新时间戳距 now <= {cfg.get('max_age_hours')}h"

    if granularity == "monthly":
        since_dt = now - timedelta(days=33)
        return since_dt.strftime("%Y-%m-%d"), "最新日期距 now <= 33 天"

    return None, "未知粒度"


def _check_remote_table(check: dict, table: str, now: datetime, results: list, stale_items: list):
    db = check["db"]
    since, expected = _window_since(check["granularity"], now, check)
    if since is None:
        results.append(dict(scope="remote", db=db, table=table, status="unparsed", detail=expected))
        return
    try:
        mx, err = _api_window_max(db, table, since)
    except Exception as e:
        results.append(dict(scope="remote", db=db, table=table, status="read_error", detail=str(e)[:200]))
        stale_items.append(dict(db=db, table=table, reason=f"远程读取失败: {e}",
                                guidance=_stale_advice(check)))
        return

    if mx is None and err == "no_begin_time_col":
        results.append(dict(scope="remote", db=db, table=table, status="skipped_empty", detail=err))
        return
    if mx is None:
        # 窗口内无数据：滞后（容忍空表的粒度只记录不告警）
        if check.get("allow_empty"):
            results.append(dict(scope="remote", db=db, table=table, status="skipped_empty", detail="窗口内无数据"))
            return
        results.append(dict(scope="remote", db=db, table=table, status="STALE",
                            latest=None, expected=expected))
        stale_items.append(dict(db=db, table=table,
                                reason=f"窗口 [{since} ~ now] 内无数据，期望 {expected}",
                                guidance=_stale_advice(check)))
        return

    results.append(dict(scope="remote", db=db, table=table, status="ok",
                        latest=mx, expected=expected))


def _stale_advice(check: dict, local_max: str = None) -> list:
    """生成滞后时的调用链路与检查方向。"""
    chain = [
        f"定时任务 {check['task_id']} (cron: {check['task_cron']})",
        f"→ {check['service']}",
        f"→ {check['write_path']}",
        f"→ db_writer_api @ {_api_base()} → 远程库 {check['db']}",
    ]
    advice = [
        f"1. Task Manager 查看任务 {check['task_id']} 最近运行历史（success/error）",
        "2. log/worker_runtime*.log（每组 worker 一个文件）搜关键字: \"[API] 写入失败\"、\"回退到本地\"、\"HTTP 500\"",
        f"3. 远程服务端健康: GET {_api_base()}/health 与 /api/tables?db={check['db']}",
        "4. 远程库损坏: 部署机(192.168.100.19)上 PRAGMA integrity_check，损坏则 .recover 重建",
        f"5. 数据源侧: 确认 UME 网管 {check['task_id']} 对应查询在任务窗口内有数据产出",
        "6. 确认后手动触发该任务回补（upsert 模式可重复执行）",
    ]
    if local_max:
        advice.insert(1, f"※ 本地回退库已有数据到 {local_max}，说明远程写入链路失败、数据在本地，重跑任务即可回补")
    return ["调用链路:"] + [f"  {c}" for c in chain] + ["检查方向:"] + [f"  {a}" for a in advice]


# ============================================================
# 任务执行健康检查（防“任务注册但无 worker 认领”盲区）
# ============================================================
def _ensure_my_app_importable():
    """确保 my_app 根目录在 sys.path（独立运行 python 本文件场景）。"""
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)


def _task_health_db_query():
    """连接本机历史库（pg/sqlite 双模），一次查询返回：
    (exec_latest, success_latest, disabled_ids, cron_map, stuck, error)
    - exec_latest: {task_id: 最近 started_at}（GROUP BY 一次取全，避免 N+1）
    - success_latest: {task_id: 最近一次成功的 started_at}（成功逾期检查用）
    - disabled_ids: 已禁用任务集合（task_schedule_config enabled=0）
    - cron_map: {task_id: cron}（调度配置持久化表）
    - stuck: 滞留队列记录 [dict(id, task_id, status, since)]
    表不存在（sqlite 开发模式未建表）视为“无可检查”而非检查手段故障。"""
    try:
        _ensure_my_app_importable()
        from backend.database import get_raw_connection, DB_PATH as _APP_DB
    except Exception as e:
        return None, None, None, None, None, f"导入 backend.database 失败: {e}"
    try:
        with get_raw_connection(str(_APP_DB), timeout=30) as conn:
            exec_latest = {r[0]: r[1] for r in conn.execute(
                "SELECT task_id, MAX(started_at) FROM task_execution_log GROUP BY task_id"
            ).fetchall()}
            success_latest = {r[0]: r[1] for r in conn.execute(
                "SELECT task_id, MAX(started_at) FROM task_execution_log "
                "WHERE success = 1 GROUP BY task_id"
            ).fetchall()}
            sched_rows = conn.execute(
                "SELECT task_id, cron, enabled FROM task_schedule_config"
            ).fetchall()
            disabled_ids = {r[0] for r in sched_rows if r[2] == 0}
            cron_map = {r[0]: r[1] for r in sched_rows if r[1]}
            p_cut = (datetime.now() - timedelta(minutes=TASK_HEALTH_PENDING_MAX_MINUTES)).isoformat()
            r_cut = (datetime.now() - timedelta(minutes=TASK_HEALTH_RUNNING_MAX_MINUTES)).isoformat()
            stuck = [dict(id=q[0], task_id=q[1], status="pending", since=q[2]) for q in conn.execute(
                "SELECT id, task_id, created_at FROM task_queue "
                "WHERE status = 'pending' AND created_at < ?", (p_cut,)).fetchall()]
            stuck += [dict(id=q[0], task_id=q[1], status="running", since=q[2]) for q in conn.execute(
                "SELECT id, task_id, started_at FROM task_queue "
                "WHERE status = 'running' AND started_at < ?", (r_cut,)).fetchall()]
        return exec_latest, success_latest, disabled_ids, cron_map, stuck, None
    except Exception as e:
        msg = str(e)
        if "no such table" in msg or "42P01" in msg or "does not exist" in msg:
            return {}, {}, set(), {}, [], None
        return None, None, None, None, None, f"历史库查询失败: {msg}"


def _task_group_coverage():
    """对比 task_registry 注册表与 worker_watchdog 分组清单。
    返回 (registry_ids, group_ids, specs, error)；specs={task_id: spec} 供
    成功逾期检查取 default_cron（调度配置表无记录时兜底）。"""
    try:
        _ensure_my_app_importable()
        from backend.task_registry import TASK_SPECS
        from backend.worker_watchdog import GROUP_TASK_MAP
    except Exception as e:
        return None, None, None, f"导入任务注册表/分组清单失败: {e}"
    registry = [s["task_id"] for s in TASK_SPECS]
    specs = {s["task_id"]: s for s in TASK_SPECS}
    groups = set()
    for tasks in GROUP_TASK_MAP.values():
        groups.update(x.strip() for x in tasks.split(",") if x.strip())
    return registry, groups, specs, None


def _cron_next_and_interval(cron: str, after: datetime):
    """返回 after 之后的 (下次触发时刻, 调度间隔)；解析失败返回 (None, None)。
    APScheduler 返回 timezone-aware 时间，统一 replace(tzinfo=None) 再与 naive 比较。"""
    try:
        from apscheduler.triggers.cron import CronTrigger
        parts = (cron or "").strip().split()
        if len(parts) != 5:
            return None, None
        minute, hour, day, month, dow = parts
        trig = CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=dow)
        f1 = trig.get_next_fire_time(None, after)
        if f1 is None:
            return None, None
        f2 = trig.get_next_fire_time(None, f1 + timedelta(seconds=1))
        if f1.tzinfo is not None:
            f1 = f1.replace(tzinfo=None)
        return f1, (f2 - f1) if f2 else None
    except Exception:
        return None, None


def _check_task_execution_health(now: datetime, results: list, stale_items: list):
    """任务执行健康检查（4 个维度，均为只读查询）。
    返回 (ok, issues)：ok=False 表示检查手段本身不可用（影响 success）。"""
    registry, groups, specs, err = _task_group_coverage()
    if err or registry is None:
        stale_items.append(dict(db="task_health", table="*",
                                reason=f"任务健康配置加载失败: {err}",
                                guidance=["检查 backend/task_registry.py 与 backend/worker_watchdog.py 能否正常 import"]))
        return False, 1
    issues = 0

    # 1) 注册表 vs worker 分组清单覆盖（新增任务只注册未加分组 → 永远无人认领）
    missing = [t for t in registry if t not in groups]
    if missing:
        issues += 1
        stale_items.append(dict(
            db="task_health", table="worker 分组清单",
            reason=f"任务已注册但不在 worker_watchdog 分组清单: {missing}",
            guidance=[
                f"1. 将 {missing} 加入 backend/worker_watchdog.py GROUP_TASK_MAP 合适分组（如 m 组内务轻任务）",
                "2. 重启 worker_watchdog：taskkill /PID <watchdog_pid> /T /F 后执行 wscript start_hidden.vbs nobrowser",
                "3. 查 task_queue 是否有滞留 pending 记录（新 worker 会自动认领执行）",
            ]))

    exec_latest, success_latest, disabled_ids, cron_map, stuck, err = _task_health_db_query()
    if err:
        stale_items.append(dict(db="task_health", table="task_execution_log/task_queue",
                                reason=err,
                                guidance=["检查后端历史库连接（PG 5432 / db/app.db）与 worker 进程状态"]))
        return False, issues + 1

    # 2) 注册任务最近 24h 无执行记录（排除已禁用任务）
    cutoff = (now - timedelta(hours=TASK_HEALTH_LOOKBACK_HOURS)).isoformat()
    silent = [t for t in registry
              if t not in disabled_ids
              and (not exec_latest.get(t) or exec_latest[t] < cutoff)]
    if silent:
        issues += 1
        stale_items.append(dict(
            db="task_health", table="task_execution_log",
            reason=f"任务最近 {TASK_HEALTH_LOOKBACK_HOURS}h 无执行记录: {silent}",
            guidance=[
                "1. Task Manager 查看这些任务的历史与下次运行时间",
                "2. 查 task_queue 是否有滞留 pending 记录（单飞保护会挡住后续触发）",
                "3. 确认任务在 worker_watchdog GROUP_TASK_MAP 分组清单内（见上方分组覆盖项）",
                "4. log/worker_runtime*.log 搜任务名确认 worker 是否认领过（认领行带 queue_id）",
            ]))

    # 3) task_queue 滞留记录
    if stuck:
        issues += 1
        lines = "\n".join(f"    {s['task_id']} id={s['id']} {s['status']} since={s['since']}"
                           for s in stuck[:10])
        stale_items.append(dict(
            db="task_health", table="task_queue",
            reason=f"队列滞留 {len(stuck)} 条（pending>{TASK_HEALTH_PENDING_MAX_MINUTES}min / running>{TASK_HEALTH_RUNNING_MAX_MINUTES}min）:\n{lines}",
            guidance=[
                "1. pending: 任务可能不在任何 worker 分组清单（见分组覆盖检查）或 worker 未启动",
                "2. running 超 30min: 大概率 worker 已崩溃（僵尸记录），worker 周期回收会自动补写失败并交 auto_retry 重试；也可手动重跑",
                "3. 确认 3 个分组 worker（u/n/m）均在运行: worker_watchdog.log",
            ]))

    # 4) 成功逾期：上次成功之后按 cron 应再产出的周期已过一个完整周期下限，
    #    仍无成功执行（补「24h 无记录」对小时级任务不敏感的盲区：
    #    eflow_sync 僵尸事件中断档 3 小时，旧检查因 9 点有成功记录全程未报）
    overdue = []
    for t in registry:
        if t in disabled_ids:
            continue
        cron = cron_map.get(t) or (specs.get(t) or {}).get("default_cron")
        last_ok = success_latest.get(t)
        if not cron or not last_ok:
            continue
        try:
            last_ok_dt = datetime.fromisoformat(last_ok)
        except Exception:
            continue
        next_fire, interval = _cron_next_and_interval(cron, last_ok_dt)
        if next_fire is None:
            continue
        grace = max(interval or timedelta(hours=1), timedelta(minutes=30))
        if now > next_fire + grace:
            overdue.append(f"{t}（最后成功 {last_ok[:19]}，{next_fire:%m-%d %H:%M} 应产出新一期）")
    if overdue:
        issues += 1
        stale_items.append(dict(
            db="task_health", table="task_execution_log(success)",
            reason=f"任务成功逾期（超过一个调度周期无成功执行）: {overdue}",
            guidance=[
                "1. Task Manager 查看该任务最近失败原因（含「Worker 进程中断」类僵尸失败）",
                "2. 查 task_queue 是否有滞留 running/pending（单飞保护会挡住后续触发）",
                "3. 确认 auto_retry_failed 任务在正常运行（每 10 分钟）",
                "4. 未自动恢复时手动触发该任务回补数据",
            ]))

    results.append(dict(scope="task_health", db="task_health", table="*",
                        status="ok" if not (missing or silent or stuck or overdue) else "STALE",
                        silent_tasks=silent, stuck_queue=len(stuck), group_missing=missing,
                        success_overdue=overdue))
    return True, issues


# ============================================================
# 主流程
# ============================================================
def _check_local_table(check: dict, table: str, now: datetime, results: list, stale_items: list):
    path, label = check["path"], check["label"]
    try:
        mx, err = _local_max_begin_time(path, table)
    except Exception as e:
        results.append(dict(scope="local", db=label, table=table, status="read_error", detail=str(e)[:200]))
        stale_items.append(dict(db=label, table=table, reason=f"本地读取失败: {e}",
                                guidance=[f"检查文件是否被占用/损坏: {path}",
                                          "sqlite3 打开执行 PRAGMA integrity_check"]))
        return
    if mx is None:
        results.append(dict(scope="local", db=label, table=table, status="skipped_empty", detail=err or "空表"))
        return
    # 本地回退库只在远程失败时写入，无固定新鲜度要求：仅记录最新日期供对照
    results.append(dict(scope="local", db=label, table=table, status="info", latest=mx))


def run_db_freshness_check() -> dict:
    """小时级数据新鲜度巡检入口。"""
    t_start = time.time()
    print(f"[FreshnessCheck] 数据新鲜度巡检开始 @ {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"[FreshnessCheck] 远程 API: {_api_base()}")

    now = datetime.now()
    results = []
    stale_items = []
    api_reachable = True

    # ---------- 远程库检查 ----------
    # 预取每个远程库的表清单（一次请求）。
    # 判定变更（2026-08-27）：单个库表清单读取失败不再把整个巡检判失败——只要
    # 至少一个库能取到表清单即视为「API 主机可达」，失败的库作为 stale 条目记录
    # （与数据滞后同处理，不触发 auto_retry 反复重跑巡检）。仅当全部库都取不到时
    # 才判 api_reachable=False（真正的主机不可达 / 环境问题），交 auto_retry。
    # 避免单个库文件被锁/卡（如 ipran_ume_kpi 被写进程持有排它锁）让巡检整上午假失败。
    table_cache = {}
    db_total = 0          # 去重后的远程库总数
    db_reachable = 0      # 表清单读取成功的库数
    for check in REMOTE_CHECKS + MONTHLY_CHECKS:
        db = check["db"]
        if db in table_cache:
            continue
        db_total += 1
        try:
            table_cache[db] = _api_list_tables(db)
            db_reachable += 1
        except Exception as e:
            table_cache[db] = None
            stale_items.append(dict(db=db, table="*", reason=f"远程库表清单读取失败: {e}",
                                    guidance=[
                                        f"1. 若多个库均失败 → API 主机不可达: ping {get_api_host()} / Test-NetConnection {get_api_host()} -Port {API_PORT}，部署机(192.168.100.19)查 db_writer_api 进程",
                                        f"2. 若仅此库失败 → 该库文件可能被锁/损坏: 部署机 handle.exe 查占用进程、查 hot journal(-journal/-wal/-shm)、sqlite3 PRAGMA integrity_check",
                                        "3. 确认后干净重启 db_writer_api（先 kill 持有该库的 python 进程再起服务）",
                                    ]))
    api_reachable = db_reachable > 0

    for check in REMOTE_CHECKS:
        tables = table_cache.get(check["db"])
        if tables is None:
            continue  # 已在 stale_items 记录 API 不可达
        skip = check.get("skip_match")
        for t in tables:
            if skip and skip(t):
                continue
            _check_remote_table(check, t, now, results, stale_items)

    for check in MONTHLY_CHECKS:
        tables = table_cache.get(check["db"])
        if tables is None:
            continue
        only = check.get("only_match")
        for t in tables:
            if only and not only(t):
                continue
            _check_remote_table(check, t, now, results, stale_items)

    # ---------- 本地回退库检查 ----------
    # 同时收集本地库最新日期，用于远程滞后时的对照提示
    local_latest_by_task = {}
    for check in LOCAL_CHECKS:
        path = check["path"]
        if not os.path.exists(path):
            results.append(dict(scope="local", db=check["label"], table="*",
                                status="missing", detail=path))
            continue
        try:
            tables = _local_tables(path)
        except Exception as e:
            stale_items.append(dict(db=check["label"], table="*",
                                    reason=f"本地库无法打开: {e}",
                                    guidance=[f"文件: {path}", "PRAGMA integrity_check 验证完整性"]))
            continue
        for t in tables:
            _check_local_table(check, t, now, results, stale_items)

    # 汇总本地库各任务 max 日期（供远程滞后对照）
    for r in results:
        if r.get("scope") == "local" and r.get("latest"):
            key = r["db"]
            if key not in local_latest_by_task or r["latest"] > local_latest_by_task[key]:
                local_latest_by_task[key] = r["latest"]
    # 把本地对照信息补充到远程滞后项
    label_by_task = {c["task_id"]: c["label"] for c in LOCAL_CHECKS}
    for si in stale_items:
        db = si.get("db", "")
        for check in REMOTE_CHECKS:
            if check["db"] == db and check.get("local_db"):
                lbl = label_by_task.get(check["task_id"])
                lm = local_latest_by_task.get(lbl) if lbl else None
                if lm:
                    si["guidance"].insert(1, f"※ 本地回退库已有数据到 {lm}，优先重跑任务 {check['task_id']} 回补远程")
                break

    # ---------- 任务执行健康检查 ----------
    # 2026-08-12 新增：补齐“任务注册但无 worker 认领 / 从未执行”盲区
    # （db_freshness_check 与 sp_report_generate 曾因此无历史记录）
    task_health_ok, task_health_issues = _check_task_execution_health(now, results, stale_items)

    # ---------- 汇总 ----------
    stale_count = len(stale_items)
    checked = len(results)
    fresh = (stale_count == 0) and api_reachable

    print(f"[FreshnessCheck] 检查 {checked} 项，滞后/异常 {stale_count} 项，"
          f"远程API {'可达' if api_reachable else '不可达'}（{db_reachable}/{db_total} 库可达），"
          f"任务健康检查 {'正常' if task_health_ok else '不可用'}")
    if task_health_issues and task_health_ok:
        print(f"[TASK-HEALTH] 发现 {task_health_issues} 项任务执行健康异常（详见下方 STALE 条目）")
    if stale_items:
        for si in stale_items:
            print(f"[STALE] {si.get('db')}/{si.get('table')}: {si.get('reason')}")
            for line in si.get("guidance", []):
                print(f"    {line}")

    elapsed = time.time() - t_start
    print(f"[FreshnessCheck] 巡检完成，耗时 {elapsed:.2f}s")

    return {
        # 巡检执行本身成功与否只取决于“检查手段是否可用”（远程 API + 任务健康检查手段）；
        # 数据滞后 / 任务健康异常通过 fresh/stale 字段暴露，不触发 auto_retry 重跑巡检
        "success": api_reachable and task_health_ok,
        "fresh": fresh,
        "checked_items": checked,
        "stale_count": stale_count,
        "api_reachable": api_reachable,
        "db_reachable": db_reachable,
        "db_total": db_total,
        "task_health_ok": task_health_ok,
        "task_health_issues": task_health_issues,
        "stale": stale_items,
        "details": results,
        "elapsed_seconds": round(elapsed, 2),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    res = run_db_freshness_check()
    print(f"\n总体: {'全部新鲜' if res['fresh'] else '存在滞后/异常'} "
          f"(checked={res['checked_items']}, stale={res['stale_count']}, "
          f"task_health={'正常' if res['task_health_ok'] else '不可用'}, "
          f"elapsed={res['elapsed_seconds']}s)")

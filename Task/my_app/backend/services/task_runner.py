"""
通用任务调度管理框架
支持：注册任务、自定义调度频率、立即执行、查看历史状态
可扩展：新增任务只需调用 register_task() 即可
"""
import time
import logging
import threading
import sqlite3
import json
import os
import signal
import subprocess
import traceback
import ast
import inspect
import importlib.util
import textwrap
import types
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from backend.database import get_raw_connection
from backend.dialect_helpers import table_columns, upsert

# Phase 4 拆分：以下成员已迁移至 backend.services.task_introspect，反向导入保持本模块引用兼容
from backend.services.task_introspect import (  # noqa: F401,E402
    _auto_call_chain,
    _annotate_call_chain,
    TASK_IO,
    CALL_CHAIN_IO,
)

# Phase 4 拆分：以下成员已迁移至 backend.services.task_stats，反向导入保持本模块引用兼容
from backend.services.task_stats import (  # noqa: F401,E402
    _ensure_task_log_table,
    _fetch_latest_runs,
    get_task_stats,
    get_recent_failures,
    get_task_history_by_task,
)

logger = logging.getLogger("task_runner")

# 微信失败通知（OpenClaw 通道）。导入失败则降级为 no-op，不影响任务调度。
try:
    from .weixin_notifier import notify_task_failure
except Exception:  # noqa: BLE001
    def notify_task_failure(task_id, task_name, error, traceback_text=None):  # type: ignore
        logger.warning(f"weixin_notifier 不可用，跳过失败通知 ({task_id})")

# 任务失败 126 邮箱通知（xin83min@126.com）。导入失败则降级为 no-op，不影响任务调度。
try:
    from .email_notifier import notify_task_failure_email
except Exception:  # noqa: BLE001
    def notify_task_failure_email(task_id, task_name, error, traceback_text=None, receiver=None):  # type: ignore
        logger.warning(f"email_notifier 不可用，跳过失败邮件通知 ({task_id})")

# 路径配置
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BACKEND_DIR / "db" / "app.db"

# ========== 任务注册表 ==========
_task_registry: dict[str, dict] = {}
_task_history: list[dict] = []
MAX_HISTORY = 50
_lock = threading.Lock()

# 任务执行中状态（供前端轮询展示"运行中"）
_active_runs: dict[str, dict] = {}
_active_lock = threading.Lock()

# 全局调度器
_scheduler: Optional[BackgroundScheduler] = None


def get_scheduler() -> BackgroundScheduler:
    """获取或创建全局调度器"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


# ========== 任务队列（Phase 3：调度与执行解耦） ==========
# 环境变量 MY_APP_TASK_QUEUE=1 启用（start.bat 中设置）；未启用时全部走原有
# 进程内线程执行路径，行为零变化。启用后：
#   - Web 进程：定时触发 / 手动触发仅向 task_queue 表投递（enqueue_task）
#   - Worker 进程（backend/worker.py）：轮询 task_queue 认领并执行任务
# 不依赖 Redis/RabbitMQ，SQLite task_queue 表即跨进程队列。
QUEUE_ENABLED = os.environ.get("MY_APP_TASK_QUEUE", "0") == "1"


def _ensure_queue_table(conn):
    """确保 task_queue 表存在（含状态 / task_id 索引，供 worker 轮询认领）"""
    if isinstance(conn, sqlite3.Connection):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL DEFAULT 'manual',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                result_json TEXT,
                error TEXT,
                worker_pid INTEGER
            )
        """)
    else:
        # PG：以 GENERATED ALWAYS AS IDENTITY 取代 sqlite 的 AUTOINCREMENT
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_queue (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                task_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL DEFAULT 'manual',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                result_json TEXT,
                error TEXT,
                worker_pid INTEGER
            )
        """)
    # 幂等迁移：旧库可能没有 worker_pid 列（停止执行功能用它定位执行该任务的 Worker 进程）
    # 2026-08-14 修复：ALTER TABLE 后必须立即 commit，否则后续 SELECT 在同一连接上
    # 可能看不到新列（sqlite 的 DDL 事务语义）。迁移失败时不再静默吞掉，而是抛异常
    # 让调用方感知，避免「列缺失→SELECT 报错→回收失效→任务卡死」的链式故障。
    _cols = table_columns(conn, "task_queue")
    if "worker_pid" not in _cols:
        try:
            conn.execute("ALTER TABLE task_queue ADD COLUMN worker_pid INTEGER")
            conn.commit()  # 立即提交 DDL，确保后续 SELECT 可见新列
            # 验证迁移成功
            _cols2 = table_columns(conn, "task_queue")
            if "worker_pid" not in _cols2:
                raise RuntimeError("task_queue.worker_pid 列添加后验证失败（PRAGMA 仍不可见）")
            logger.info("task_queue 迁移：已添加 worker_pid 列")
        except Exception as _e:
            logger.error(f"task_queue 迁移 worker_pid 列失败: {_e}")
            raise  # 不再静默吞掉——列缺失会导致 _recover_stale_running 完全失效
    conn.execute("CREATE INDEX IF NOT EXISTS ix_task_queue_status ON task_queue(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_task_queue_task_id ON task_queue(task_id)")


def enqueue_task(task_id: str, trigger: str = "manual") -> dict:
    """投递任务到 task_queue，由 Worker 进程执行。

    单飞保护：同一任务已有 pending/running 队列记录时拒绝投递。
    注意：不能用 is_task_running 预判（它自身依赖本函数查队列，会递归），
    且本进程 _active_runs 不反映 Worker 进程的运行状态，必须以队列表为准。
    """
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_queue_table(conn)
            row = conn.execute(
                "SELECT id FROM task_queue WHERE task_id = ? AND status IN ('pending', 'running') LIMIT 1",
                (task_id,),
            ).fetchone()
            if row:
                conn.close()
                return {"accepted": False, "running": True, "queued": True,
                        "error": "任务已在队列中等待或执行"}
            if isinstance(conn, sqlite3.Connection):
                cur = conn.execute(
                    "INSERT INTO task_queue (task_id, trigger_type, status, created_at) VALUES (?, ?, 'pending', ?)",
                    (task_id, trigger, datetime.now().isoformat()),
                )
                queue_id = cur.lastrowid
            else:
                # PG：sqlite 无 RETURNING 等价物；用 RETURNING id 取回自增主键
                cur = conn.execute(
                    "INSERT INTO task_queue (task_id, trigger_type, status, created_at) VALUES (?, ?, 'pending', ?) RETURNING id",
                    (task_id, trigger, datetime.now().isoformat()),
                )
                queue_id = cur.fetchone()[0]
            conn.commit()
            conn.close()
        logger.info(f"[{task_id}] 已投递任务队列 (queue_id={queue_id}, trigger={trigger})")
        return {"accepted": True, "running": False, "queued": True, "queue_id": queue_id,
                "task_id": task_id, "started_at": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"[{task_id}] 投递队列失败: {e}")
        return {"accepted": False, "queued": False, "error": f"投递队列失败: {e}"}


def get_queue_running_task_ids() -> set:
    """队列中处于 pending/running 的 task_id 集合（跨进程运行状态展示，批量一次查出）"""
    if not QUEUE_ENABLED:
        return set()
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_queue_table(conn)
            rows = conn.execute(
                "SELECT DISTINCT task_id FROM task_queue WHERE status IN ('pending', 'running')"
            ).fetchall()
            conn.close()
            return {r[0] for r in rows}
    except Exception as e:
        logger.warning(f"查询队列运行集合失败: {e}")
        return set()


# ========== 任务注册 ==========
def _init_schedule_table():
    """初始化调度配置表"""
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS task_schedule_config (
                task_id TEXT PRIMARY KEY,
                cron TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
        """)
            # 兼容旧表：仅在 enabled 列不存在时才添加（幂等迁移，避免重复加列抛异常）
            cols = table_columns(conn, "task_schedule_config")
            if "enabled" not in cols:
                conn.execute("ALTER TABLE task_schedule_config ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
            conn.commit()
            conn.close()
    except Exception as e:
        logger.warning(f"初始化调度配置表失败: {e}")


def _load_schedule_config(task_id: str) -> tuple:
    """从数据库加载用户自定义的调度配置和启用状态"""
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            row = conn.execute(
                "SELECT cron, enabled FROM task_schedule_config WHERE task_id = ?",
                (task_id,)
            ).fetchone()
            conn.close()
            return (row[0], bool(row[1])) if row else (None, None)
    except Exception as e:
        logger.warning(f"加载调度配置失败 ({task_id}): {e}")
        return (None, None)


def _save_schedule_config(task_id: str, cron: str, enabled: bool = None):
    """保存用户自定义的调度配置到数据库"""
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            now = datetime.now().isoformat()
            if enabled is not None:
                rows = [{"task_id": task_id, "cron": cron,
                         "enabled": 1 if enabled else 0, "updated_at": now}]
            else:
                cur = conn.execute(
                    "SELECT enabled FROM task_schedule_config WHERE task_id = ?", (task_id,))
                r = cur.fetchone()
                rows = [{"task_id": task_id, "cron": cron,
                         "enabled": r[0] if r else 1, "updated_at": now}]
            upsert(conn, "task_schedule_config", rows, conflict_cols=["task_id"])
            conn.commit()
            conn.close()
    except Exception as e:
        logger.warning(f"保存调度配置失败 ({task_id}): {e}")




# 调用链最大递归深度（环境变量可配，默认 2）


# 源码 AST 缓存：{绝对文件路径: ast.Module | None}，注册期一次性解析，避免重复读盘


# ========== 调用链节点 IO 资源映射（数据库 / 文件） ==========
# 维护用途：在 Task Manager 的脚本调用链（Call Chain）中，为每个节点标注其
# 设计上访问的数据库或文件，方便日常维护与问题排查。
#
# - TASK_IO: 以 task_id 为键，标注该任务「入口节点」访问的核心 DB / 文件。
#   懒加载任务（_lazy_loader 包装）的调用链只有入口节点，因此入口标注即可覆盖。
# - CALL_CHAIN_IO: 以函数名为键，标注被调用链展开到的「共享子函数」访问的资源
#   （如 eflow / 告警 / ms_sla / ipran 等任务展开后的子节点）。
#
# 新增 / 调整任务时，只需在此两处补充对应条目，无需改动前端与调度逻辑。



def register_task(
    task_id: str,
    name: str,
    func: Callable,
    description: str = "",
    default_cron: str = "0 2 * * *",   # 默认每天凌晨2点
    category: str = "general",
    gateway: str = "system",
    enabled: bool = True,
    name_en: str = "",
    description_en: str = "",
    call_chain: list | None = None,
):
    """
    注册一个可调度的任务。

    Args:
        task_id: 唯一标识符
        name: 显示名称（中文）
        name_en: 显示名称（英文，留空则回退到 name）
        func: 执行函数，返回 dict 或 str
        description: 任务描述（中文）
        description_en: 任务描述（英文，留空则回退到 description）
        default_cron: 默认 cron 表达式 (分 时 日 月 周)
        category: 分类 (eflow / ran_ume / whatsapp / site_outage / general)
        enabled: 是否启用
    """
    # 尝试加载用户自定义的调度配置
    saved_cron, saved_enabled = _load_schedule_config(task_id)
    current_cron = saved_cron if saved_cron else default_cron
    final_enabled = saved_enabled if saved_enabled is not None else enabled

    # 调用链在注册期一次性烘焙：中/英两份同源同长，请求期按 Accept-Language 取用
    _chain_raw = call_chain if call_chain is not None else _auto_call_chain(func)

    _task_registry[task_id] = {
        "task_id": task_id,
        "name": name,
        "name_en": name_en or name,
        "func": func,
        "description": description,
        "description_en": description_en or description,
        "default_cron": default_cron,
        "current_cron": current_cron,
        "category": category,
        "gateway": gateway,
        "enabled": final_enabled,
        "registered_at": datetime.now().isoformat(),
        "call_chain": _annotate_call_chain(_chain_raw, task_id),
        "call_chain_en": _annotate_call_chain(_chain_raw, task_id, lang="en"),
    }
    logger.info(f"任务已注册: {task_id} ({name}), cron={current_cron}")


def _localize(task: dict, lang: str) -> tuple:
    """根据 lang 返回 (显示名, 显示描述)；非法值回退中文。"""
    if lang == "en":
        return task.get("name_en") or task.get("name"), task.get("description_en") or task.get("description")
    return task.get("name"), task.get("description")


def _localized_chain(task: dict, lang: str) -> list:
    """按语言返回调用链（含资源标注）；EN 缺失时回退中文，绝不返回 None。"""
    if lang == "en":
        return task.get("call_chain_en") or task.get("call_chain") or []
    return task.get("call_chain") or []


def unregister_task(task_id: str):
    """注销任务"""
    if task_id in _task_registry:
        # 移除调度
        sched = get_scheduler()
        job_id = f"task_{task_id}"
        if sched.get_job(job_id):
            sched.remove_job(job_id)
        del _task_registry[task_id]
        logger.info(f"任务已注销: {task_id}")


# ========== 任务执行 ==========
def run_task(task_id: str, trigger: str = "manual") -> dict:
    """
    立即执行指定任务。

    Args:
        task_id: 任务ID
        trigger: 触发方式 (manual / scheduled)

    Returns:
        执行结果 dict
    """
    task = _task_registry.get(task_id)
    if not task:
        return {"success": False, "error": f"任务 {task_id} 未找到"}

    if not task["enabled"]:
        return {"success": False, "error": f"任务 {task_id} 已禁用"}

    logger.info("任务开始执行", extra={"task_id": task_id, "event": "task_start", "trigger": trigger})
    start_time = time.time()

    result = {
        "task_id": task_id,
        "task_name": task["name"],
        "category": task["category"],
        "trigger": trigger,
        "success": False,
        "started_at": datetime.now().isoformat(),
        "elapsed_seconds": 0,
        "result": None,
        "error": None,
        "error_trace": None,
    }

    try:
        func_result = task["func"]()
        if isinstance(func_result, dict):
            result["success"] = func_result.get("success", True)
            result["result"] = func_result
            # 业务失败：任务函数返回 {"success": False, ...} 但未抛异常时，
            # 把其中的 error/message 摘出来，否则页面只显示“失败”却无任何错误信息。
            if not result["success"] and not result.get("error"):
                biz_msg = func_result.get("error") or func_result.get("message")
                if not biz_msg:
                    # 任务函数常以 errors(list) 返回多条错误（如 packet_loss /
                    # site_outage），run_task 默认只取 error/message 字符串，
                    # 会漏掉这类失败原因，导致 Task Manager 显示“空错误”。
                    # 这里把 errors 列表合并进 error，便于排查与失败聚类。
                    errs = func_result.get("errors")
                    if isinstance(errs, (list, tuple)):
                        errs = [e for e in errs if e]
                        if errs:
                            biz_msg = "; ".join(str(e) for e in errs)
                if biz_msg:
                    result["error"] = str(biz_msg)
        else:
            result["success"] = True
            result["result"] = {"message": str(func_result)}
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        result["error_trace"] = traceback.format_exc()
        logger.error("任务执行失败", extra={"task_id": task_id, "event": "task_fail", "error": str(e)})
    except BaseException as e:
        # 捕获 SystemExit / KeyboardInterrupt 等被强行中断的情况
        # （例如 WorkBuddy safe-delete 守卫在 os.remove 时 raise SystemExit）。
        # 必须记录执行历史，否则会出现“任务执行了但历史为空”。
        result["success"] = False
        result["error"] = f"{type(e).__name__}: {e}"
        result["error_trace"] = traceback.format_exc()
        logger.error("任务被强行中断", extra={"task_id": task_id, "event": "task_interrupt", "error_type": type(e).__name__})

    elapsed = time.time() - start_time
    result["elapsed_seconds"] = round(elapsed, 2)
    result["completed_at"] = datetime.now().isoformat()

    # 记录历史
    with _lock:
        _task_history.append(result)
        while len(_task_history) > MAX_HISTORY:
            _task_history.pop(0)

    # 持久化到数据库
    _save_task_result(result)

    # 任务失败时推送微信通知（OpenClaw 通道）。通知失败不影响任务结果记录。
    if not result["success"]:
        try:
            notify_task_failure(
                task_id, task["name"],
                result.get("error") or "未知错误",
                result.get("error_trace"),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{task_id}] 微信失败通知异常: {e}")

        # 任务失败时发送 126 邮箱告警邮件给 xin83min@126.com。
        # 通知失败不影响任务结果记录。
        try:
            notify_task_failure_email(
                task_id, task["name"],
                result.get("error") or "未知错误",
                result.get("error_trace"),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{task_id}] 邮箱失败通知异常: {e}")

    logger.info("任务执行完成", extra={"task_id": task_id, "event": "task_done", "success": result["success"], "elapsed": round(elapsed, 2)})
    return result


# ========== 异步执行 & 运行状态跟踪 ==========
def _execute_task(task_id: str, trigger: str):
    """在后台线程中执行任务，并维护 running 状态（供前端轮询）。"""
    with _active_lock:
        _active_runs[task_id] = {"started_at": datetime.now().isoformat()}
    try:
        run_task(task_id, trigger)
    finally:
        with _active_lock:
            _active_runs.pop(task_id, None)


def _scheduled_run(task_id: str, trigger: str = "scheduled"):
    """调度器回调：复用 _execute_task 以便跟踪运行状态。

    单飞保护（single-flight）：若同一任务的上一轮调度仍在运行
    （例如任务耗时超过其调度间隔，或 UME 单账号单会话被并发互踢导致变慢），
    则跳过本次触发，避免起第二个实例造成资源争用 / 401 互踢。
    手动触发路径（run_task_async）已有相同保护，这里补齐调度路径。

    队列模式（Phase 3）：仅投递 task_queue，由 Worker 进程执行；
    enqueue_task 内部已含队列级单飞保护，拒绝重复投递。
    """
    if QUEUE_ENABLED:
        resp = enqueue_task(task_id, trigger)
        if not resp.get("accepted"):
            logger.warning(f"[{task_id}] 跳过本次调度触发：{resp.get('error')}")
        return
    with _active_lock:
        if task_id in _active_runs:
            logger.warning(
                f"[{task_id}] 跳过本次调度触发：上一轮执行仍在运行中（单飞保护）"
            )
            return
    _execute_task(task_id, trigger)


def run_task_async(task_id: str, trigger: str = "manual") -> dict:
    """
    立即执行任务（队列模式下投递 task_queue 由 Worker 执行，否则进程内后台线程），立即返回。
    返回 {accepted, running}；若已在运行或校验失败则返回错误。
    """
    task = _task_registry.get(task_id)
    if not task:
        return {"success": False, "accepted": False, "error": f"任务 {task_id} 未找到"}
    if not task["enabled"]:
        return {"success": False, "accepted": False, "error": f"任务 {task_id} 已禁用"}
    if QUEUE_ENABLED:
        resp = enqueue_task(task_id, trigger)
        if resp.get("accepted"):
            return resp
        if resp.get("queued"):
            # 队列中已有该任务：与"正在运行"语义一致，正常返回（不污染 _active_runs）
            return {"accepted": False, "running": True, "error": resp.get("error")}
        # 投递失败（DB 锁/超时）：队列模式下不再降级为进程内线程执行——否则会把任务
        # 塞进 web 进程 _active_runs 且易因线程挂起导致永久假"运行中"/拒绝重触发。
        # 直接返回错误，由用户或调度重试，状态更可控。
        logger.warning(f"[{task_id}] 队列投递失败，未降级进程内执行: {resp.get('error')}")
        return {"accepted": False, "error": f"任务队列暂不可用：{resp.get('error')}"}
    # 非队列模式：进程内后台线程执行（沿用原单飞保护）
    with _active_lock:
        if task_id in _active_runs:
            return {"accepted": False, "running": True, "error": "任务正在运行中"}
    threading.Thread(target=_execute_task, args=(task_id, trigger), daemon=True).start()
    return {"accepted": True, "running": True, "task_id": task_id,
            "started_at": datetime.now().isoformat()}


def is_task_running(task_id: str) -> bool:
    # 队列模式：只信跨进程队列状态（task_queue 中 pending/running），不依赖 web 进程
    # 内存的 _active_runs（队列模式任务实际在 Worker 执行，_active_runs 易滞留）
    if QUEUE_ENABLED:
        return task_id in get_queue_running_task_ids()
    with _active_lock:
        return task_id in _active_runs


def get_active_runs() -> dict:
    with _active_lock:
        return dict(_active_runs)




def _is_known_worker_pid(pid: int) -> bool:
    """检查 pid 是否属于本系统某个运行中的 Worker 进程（防止 PID 复用误伤其它进程）。

    Worker PID 由 worker.py / worker_watchdog.py 写入 backend/worker*.pid。
    """
    try:
        backend_dir = Path(__file__).resolve().parent.parent
        known = set()
        for f in backend_dir.glob("worker*.pid"):
            if f.name == "worker_watchdog.pid":
                continue
            try:
                txt = f.read_text(encoding="utf-8").strip()
                if txt.isdigit():
                    known.add(int(txt))
            except Exception:
                continue
        return pid in known
    except Exception:
        return False


def _kill_worker_process(worker_pid) -> bool:
    """终止执行任务的 Worker 进程（含其子树：Playwright / Chromium 等子进程）。

    仅当 worker_pid 确属本系统某个运行中的 Worker 时才强杀，避免 PID 复用误伤。
    返回是否真正发起/完成强杀。
    """
    if not worker_pid:
        return False
    try:
        worker_pid = int(worker_pid)
    except (TypeError, ValueError):
        return False
    if not _is_known_worker_pid(worker_pid):
        logger.warning(f"worker_pid={worker_pid} 不在已知 Worker PID 列表，跳过强杀（可能已被回收或 PID 复用）")
        return False
    try:
        if os.name == "nt":
            res = subprocess.run(
                ["taskkill", "/PID", str(worker_pid), "/T", "/F"],
                capture_output=True, text=True, timeout=15,
            )
            killed = res.returncode == 0
        else:
            os.kill(worker_pid, signal.SIGKILL)
            killed = True
        logger.info(f"已终止 Worker 进程 pid={worker_pid} (killed={killed})")
        return killed
    except Exception as e:  # noqa: BLE001
        logger.warning(f"终止 Worker 进程 pid={worker_pid} 失败: {e}")
        return False


def _resolve_group_worker_pid(task_id: str):
    """按任务所属分组反查当前 Worker PID（兜底：队列 worker_pid 为空时使用）。

    分组定义见 backend.worker_watchdog.GROUP_TASK_MAP；每个分组 worker 的 PID
    写入 backend/worker_{group}.pid。返回 int PID 或 None。
    """
    try:
        from backend.worker_watchdog import GROUP_TASK_MAP
        group = None
        for g, tasks in GROUP_TASK_MAP.items():
            if task_id in {t.strip() for t in tasks.split(",") if t.strip()}:
                group = g
                break
        if not group:
            return None
        pid_file = Path(__file__).resolve().parent.parent / f"worker_{group}.pid"
        if not pid_file.exists():
            return None
        txt = pid_file.read_text(encoding="utf-8").strip()
        if not txt.isdigit():
            return None
        pid = int(txt)
        # 仅当该 PID 确属本系统某个运行中的 Worker 时才返回（防止 PID 复用误伤）
        return pid if _is_known_worker_pid(pid) else None
    except Exception:
        return None


def stop_task(task_id: str) -> dict:
    """停止正在执行的任务（队列模式）。

    队列模式下任务在独立 Worker 进程串行执行，Web 进程无内存句柄，故停止 =
    标记队列记录为 cancelled + 终止执行该任务的 Worker 进程（worker_watchdog
    会在数秒内自动重新拉起该 Worker，pending 任务不丢失）。

    非队列模式（进程内线程）无法安全杀线程，直接返回不支持。
    """
    if not QUEUE_ENABLED:
        return {"success": False, "stopped": False,
                "error": "非队列模式不支持停止运行中的任务（请启用 MY_APP_TASK_QUEUE=1）"}
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_queue_table(conn)
            row = conn.execute(
                "SELECT id, status, worker_pid, started_at FROM task_queue "
                "WHERE task_id = ? AND status IN ('pending', 'running') "
                "ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if not row:
                conn.close()
                return {"success": True, "stopped": False,
                        "message": "任务未处于运行/排队状态，无需停止"}
            queue_id, status, worker_pid, started_at = row[0], row[1], row[2], row[3]
            now_iso = datetime.now().isoformat()

            if status == "pending":
                # 尚未被 Worker 认领：直接取消排队，无需杀进程
                conn.execute(
                    "UPDATE task_queue SET status = 'cancelled', finished_at = ?, "
                    "error = '用户手动取消排队' WHERE id = ?",
                    (now_iso, queue_id),
                )
                conn.commit()
                conn.close()
                logger.info(f"[{task_id}] 已取消排队中的任务 (queue_id={queue_id})")
                return {"success": True, "stopped": True, "message": "已取消排队中的任务"}

            # status == 'running'：终止执行该任务的 Worker 进程
            killed = _kill_worker_process(worker_pid)
            if not killed and not worker_pid:
                # 兜底：队列未记录可用 worker_pid（过渡期老 worker / 异常），
                # 按任务所属分组反查当前 Worker 进程并强杀（worker_watchdog 会重拉）。
                grp_pid = _resolve_group_worker_pid(task_id)
                if grp_pid:
                    killed = _kill_worker_process(grp_pid)
            conn.execute(
                "UPDATE task_queue SET status = 'cancelled', finished_at = ?, "
                "error = '用户手动停止执行' WHERE id = ?",
                (now_iso, queue_id),
            )
            conn.commit()
            conn.close()

            # Worker 被强杀无法回写执行日志，此处补写一条失败记录（带 STOPPED_BY_USER
            # 标记，避免被 auto_retry 误重试）。run_task 内的微信/邮件失败告警不在这里
            # 触发，故手动停止不会骚扰通知渠道。
            task = _task_registry.get(task_id, {})
            _save_task_result({
                "task_id": task_id,
                "task_name": task.get("name"),
                "category": task.get("category"),
                "trigger": "manual_stop",
                "success": False,
                "started_at": started_at,
                "completed_at": now_iso,
                "elapsed_seconds": None,
                "result": None,
                "error": "STOPPED_BY_USER: 用户手动停止执行",
                "error_trace": None,
            })
            logger.info(f"[{task_id}] 已停止执行 (queue_id={queue_id}, worker_pid={worker_pid}, killed={killed})")
            return {"success": True, "stopped": True,
                    "message": "已停止执行" if killed else "任务进程已结束，已标记为已停止"}
    except Exception as e:  # noqa: BLE001
        logger.error(f"[{task_id}] 停止任务失败: {e}")
        return {"success": False, "stopped": False, "error": f"停止任务失败: {e}"}


def _save_task_result(result: dict):
    """将任务执行结果保存到 app.db"""
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            conn.execute("""
            INSERT INTO task_execution_log
            (task_id, task_name, category, trigger_type, success, started_at, completed_at, elapsed_seconds, result_json, error, error_trace)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
                result["task_id"],
                result.get("task_name"),
                result.get("category"),
                result.get("trigger"),
                1 if result["success"] else 0,
                result.get("started_at"),
                result.get("completed_at"),
                result.get("elapsed_seconds"),
                json.dumps(result.get("result"), ensure_ascii=False, default=str) if result.get("result") else None,
                result.get("error"),
                result.get("error_trace"),
            ))
            # 清理超过保留期的旧日志（默认 3 天，可用环境变量 TASK_LOG_RETENTION_DAYS 调整）。
            # 注意：之前此处写死 -1 days（与“3天”注释不符），每日任务的失败记录一天后即被清掉，
            # 导致隔天查看时已无失败信息。改为可配置，默认 3 天。
            try:
                _retention_days = max(1, int(os.environ.get("TASK_LOG_RETENTION_DAYS", "3")))
            except (TypeError, ValueError):
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _save_task_result: exception swallowed", exc_info=True)
                _retention_days = 3
            # PG 无 datetime('now', '-N days')；改用 Python 计算截止时间，双模通用
            from datetime import timedelta
            _cutoff = (datetime.now() - timedelta(days=_retention_days)).isoformat()
            conn.execute(
                "DELETE FROM task_execution_log WHERE started_at < ?", (_cutoff,)
            )
            conn.commit()
            conn.close()
    except Exception as e:
        logger.warning(f"保存任务日志失败: {e}")


# ========== 调度管理 ==========
def schedule_task(task_id: str, cron_expr: str = None):
    """
    将任务加入调度器。

    Args:
        task_id: 任务ID
        cron_expr: cron 表达式，为空则使用默认
    """
    task = _task_registry.get(task_id)
    if not task:
        raise ValueError(f"任务 {task_id} 未找到")

    cron = cron_expr or task["current_cron"] or task["default_cron"]
    parts = cron.strip().split()
    if len(parts) != 5:
        raise ValueError(f"无效的 cron 表达式: {cron}")

    minute, hour, day, month, day_of_week = parts
    trigger = CronTrigger(
        minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week
    )

    sched = get_scheduler()
    job_id = f"task_{task_id}"

    # 移除旧任务
    if sched.get_job(job_id):
        sched.remove_job(job_id)

    sched.add_job(
        _scheduled_run,
        trigger=trigger,
        args=[task_id, "scheduled"],
        id=job_id,
        replace_existing=True,
    )

    task["current_cron"] = cron
    logger.info(f"[{task_id}] 已调度: {cron}")


def schedule_all_tasks():
    """将所有已注册且启用的任务加入调度"""
    for task_id, task in _task_registry.items():
        if task["enabled"]:
            try:
                schedule_task(task_id)
            except Exception as e:
                logger.error(f"[{task_id}] 调度失败: {e}")


def start_scheduler():
    """启动调度器"""
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        logger.info("任务调度器已启动")


def stop_scheduler():
    """停止调度器"""
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        logger.info("任务调度器已停止")


# ========== 查询接口 ==========


def list_tasks(include_runs: bool = False, lang: str = "zh") -> list[dict]:
    """列出所有已注册的任务（include_runs=True 时附带每个任务最新一条执行记录）"""
    sched = get_scheduler()
    latest_runs = _fetch_latest_runs() if include_runs else {}
    # 跨进程运行状态批量一次查出，避免循环内逐任务查库
    with _active_lock:
        local_active = set(_active_runs.keys())
    queue_active = get_queue_running_task_ids()
    # 批量预测「失败任务何时自动重试」，供前端语音播报（单次 SQL，避免 N+1）
    retry_default = {"will_retry": False, "reason": "no recent failure", "next_retry_at": None,
                     "attempts": 0, "max_attempts": 2, "attempts_left": 2,
                     "last_retry_at": None, "failed_at": None}
    try:
        from backend.services import auto_retry
        all_retry = auto_retry.get_all_retry_info()
        retry_default = auto_retry._no_failure_info()
    except Exception:
        all_retry = {}
    tasks = []
    for task_id, task in _task_registry.items():
        job = sched.get_job(f"task_{task_id}")
        disp_name, disp_desc = _localize(task, lang)
        entry = {
            "task_id": task_id,
            "name": disp_name,
            # 同时回传中/英规范名，供前端跨语言搜索（避免用英文搜中文名搜不到）
            "name_zh": task.get("name") or disp_name,
            "name_en": task.get("name_en") or task.get("name") or disp_name,
            "description": disp_desc,
            "category": task["category"],
            "gateway": task.get("gateway", "system"),
            "enabled": task["enabled"],
            "current_cron": task["current_cron"],
            "default_cron": task["default_cron"],
            "next_run": str(job.next_run_time) if job else None,
            "registered_at": task["registered_at"],
            # 队列模式下只信跨进程队列状态 queue_active，避免 web 进程内存 local_active
            # 的滞留条目造成假"运行中"并拒绝重触发（队列模式任务实际在 Worker 进程执行，
            # web 进程 _active_runs 易滞留且无法自愈）
            "running": (task_id in queue_active) if QUEUE_ENABLED else (task_id in local_active),
            "call_chain": _localized_chain(task, lang),
        }
        if include_runs:
            entry["recent_runs"] = latest_runs.get(task_id, [])
        entry["retry_info"] = all_retry.get(task_id, dict(retry_default))
        tasks.append(entry)
    return tasks


def get_task_detail(task_id: str, lang: str = "zh") -> Optional[dict]:
    """获取任务详情"""
    task = _task_registry.get(task_id)
    if not task:
        return None

    sched = get_scheduler()
    job = sched.get_job(f"task_{task_id}")
    disp_name, disp_desc = _localize(task, lang)

    detail = {
        "task_id": task_id,
        "name": disp_name,
        "name_zh": task.get("name") or disp_name,
        "name_en": task.get("name_en") or task.get("name") or disp_name,
        "description": disp_desc,
        "category": task["category"],
        "gateway": task.get("gateway", "system"),
        "enabled": task["enabled"],
        "current_cron": task["current_cron"],
        "default_cron": task["default_cron"],
        "next_run": str(job.next_run_time) if job else None,
        "registered_at": task["registered_at"],
        "running": is_task_running(task_id),
        "call_chain": _localized_chain(task, lang),
    }

    # 从数据库获取最近执行记录
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            rows = conn.execute(
                """            SELECT task_id, task_name, category, trigger_type, success,
                      started_at, completed_at, elapsed_seconds, error, error_trace
               FROM task_execution_log
               WHERE task_id = ?
               ORDER BY started_at DESC LIMIT 10""",
                (task_id,)
            ).fetchall()
            detail["recent_runs"] = [
                {
                    "task_id": r[0], "task_name": r[1], "category": r[2],
                    "trigger": r[3], "success": bool(r[4]),
                    "started_at": r[5], "completed_at": r[6],
                    "elapsed_seconds": r[7], "error": r[8], "error_trace": r[9],
                }
                for r in rows
            ]
            conn.close()
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_task_detail: exception swallowed", exc_info=True)
        detail["recent_runs"] = []

    # 预测「失败任务何时自动重试」，供前端语音播报（失败任务才返回有意义的时间）
    try:
        from backend.services import auto_retry
        detail["retry_info"] = auto_retry.get_retry_info_for_task(task_id)
    except Exception:
        detail["retry_info"] = None

    return detail




def get_task_history(limit: int = 20) -> list[dict]:
    """获取最近的任务执行历史（Phase 4：实现下沉 task_stats，这里补内存兑底）"""
    from backend.services.task_stats import get_task_history as _gh
    return _gh(limit, fallback_history=_task_history)


def update_task_schedule(task_id: str, cron_expr: str) -> dict:
    """更新任务的调度频率"""
    task = _task_registry.get(task_id)
    if not task:
        return {"success": False, "error": f"任务 {task_id} 未找到"}

    try:
        schedule_task(task_id, cron_expr)
        # 持久化用户自定义的调度配置
        _save_schedule_config(task_id, cron_expr)
        return {
            "success": True,
            "task_id": task_id,
            "new_cron": cron_expr,
            "message": f"任务 {task['name']} 调度已更新为: {cron_expr}",
        }
    except Exception as e:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] update_task_schedule: exception swallowed", exc_info=True)
        return {"success": False, "error": str(e)}


def toggle_task(task_id: str, enabled: bool) -> dict:
    """启用/禁用任务"""
    task = _task_registry.get(task_id)
    if not task:
        return {"success": False, "error": f"任务 {task_id} 未找到"}

    task["enabled"] = enabled

    # 持久化启用状态
    _save_schedule_config(task_id, task["current_cron"], enabled=enabled)

    sched = get_scheduler()
    job_id = f"task_{task_id}"

    if enabled:
        schedule_task(task_id)
        return {"success": True, "message": f"任务 {task['name']} 已启用"}
    else:
        if sched.get_job(job_id):
            sched.remove_job(job_id)
        return {"success": True, "message": f"任务 {task['name']} 已禁用"}


def toggle_all_tasks(enabled: bool) -> dict:
    """统一启用/禁用所有已注册任务（Task Manager 主开关）

    与 toggle_task 相同的语义：更新内存状态 + 持久化 task_schedule_config
    + 增删 APScheduler job。逐任务 try/except，单个失败不中断其余任务。
    """
    sched = get_scheduler()
    changed = 0
    errors: list[str] = []
    total = len(_task_registry)
    for task_id, task in list(_task_registry.items()):
        if task["enabled"] == enabled:
            continue
        try:
            task["enabled"] = enabled
            _save_schedule_config(task_id, task["current_cron"], enabled=enabled)
            job_id = f"task_{task_id}"
            if enabled:
                schedule_task(task_id)
            else:
                if sched.get_job(job_id):
                    sched.remove_job(job_id)
            changed += 1
        except Exception as e:
            logger.warning(f"[SILENT-EXCEPT] toggle_all_tasks: {task_id} 处理失败", exc_info=True)
            errors.append(f"{task_id}: {e}")
    return {
        "success": not errors,
        "changed": changed,
        "total": total,
        "enabled": enabled,
        "errors": errors[:5],
    }

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
import traceback
import ast
import inspect
import types
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("task_runner")

# 微信失败通知（OpenClaw 通道）。导入失败则降级为 no-op，不影响任务调度。
try:
    from .weixin_notifier import notify_task_failure
except Exception:  # noqa: BLE001
    def notify_task_failure(task_id, task_name, error, traceback_text=None):  # type: ignore
        logger.warning(f"weixin_notifier 不可用，跳过失败通知 ({task_id})")

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


# ========== 任务注册 ==========
def _init_schedule_table():
    """初始化调度配置表"""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_schedule_config (
                task_id TEXT PRIMARY KEY,
                cron TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
        """)
        # 兼容旧表：尝试添加 enabled 列（表已存在时不会自动加）
        try:
            conn.execute("ALTER TABLE task_schedule_config ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
        except Exception:
            pass  # 列已存在，忽略
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"初始化调度配置表失败: {e}")


def _load_schedule_config(task_id: str) -> tuple:
    """从数据库加载用户自定义的调度配置和启用状态"""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
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
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        if enabled is not None:
            conn.execute("""
                INSERT OR REPLACE INTO task_schedule_config (task_id, cron, enabled, updated_at)
                VALUES (?, ?, ?, ?)
            """, (task_id, cron, 1 if enabled else 0, datetime.now().isoformat()))
        else:
            conn.execute("""
                INSERT OR REPLACE INTO task_schedule_config (task_id, cron, enabled, updated_at)
                VALUES (?, ?, COALESCE((SELECT enabled FROM task_schedule_config WHERE task_id = ?), 1), ?)
            """, (task_id, cron, task_id, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"保存调度配置失败 ({task_id}): {e}")


_BUILTINS = {
    "print", "len", "dict", "list", "str", "int", "float", "bool", "set",
    "tuple", "range", "enumerate", "zip", "sorted", "reversed", "isinstance",
    "format", "getattr", "setattr", "hasattr", "delattr", "super", "open",
    "min", "max", "sum", "any", "all", "map", "filter", "type", "vars",
    "repr", "abs", "round", "divmod", "pow", "id", "hash", "slice", "object",
    "Exception", "ValueError", "TypeError", "KeyError", "RuntimeError",
    "TimeoutError", "OSError", "IOError", "json", "time", "logger", "logging",
    "os", "sqlite3", "threading", "Path",
}

_METHOD_NOISE = {
    "info", "error", "warning", "debug", "critical", "getLogger", "get",
    "post", "put", "delete", "head", "run", "execute", "append", "extend",
    "add", "update", "pop", "keys", "values", "items", "setattr", "getattr",
    "format", "join", "split", "strip", "replace", "upper", "lower",
    "startswith", "endswith", "find", "index", "copy", "close", "commit",
    "rollback", "fetchall", "fetchone", "execute",
}


def _auto_call_chain(func, _depth=0, _seen=None):
    """静态分析 func 的调用链（入口函数 + 1 层递归），供前端 hover 展示。
    零副作用：仅在本模块 globals 内解析同模块函数做一层递归；
    跨模块调用只显示函数名。嵌套 def / 源码不可得时，用字节码 co_names 兜底。
    返回层级字符串列表（子项带 '  → ' 缩进缩进）。"""
    if _seen is None:
        _seen = set()
    qual = f"{getattr(func, '__module__', '')}.{getattr(func, '__qualname__', '')}"
    if qual in _seen or _depth >= 2:
        return []
    _seen.add(qual)

    mod = inspect.getmodule(func)
    mod_globals = getattr(mod, "__dict__", {}) if mod else {}

    raw = []
    try:
        src = inspect.getsource(func)
        tree = ast.parse(src)
        top_defs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute):
                    name = fn.attr
                    if name in _METHOD_NOISE:
                        continue
                elif isinstance(fn, ast.Name):
                    name = fn.id
                else:
                    continue
                if name in _BUILTINS or name.startswith("__"):
                    continue
                if name in top_defs:
                    continue
                raw.append(name)
    except (OSError, TypeError, SyntaxError):
        # 兜底：嵌套 def / 源码不可得时，用字节码引用的全局名
        for name in getattr(getattr(func, "__code__", None), "co_names", ()):
            if "." in name:  # 过滤 import from 产生的完整模块路径
                continue
            if name in _BUILTINS or name.startswith("__") or name in _METHOD_NOISE:
                continue
            if isinstance(mod_globals.get(name), types.ModuleType):
                continue
            raw.append(name)

    out = []
    for name in raw:
        if name in out:
            continue
        out.append(name)
        if _depth < 1:  # 仅入口函数做一层递归
            target = mod_globals.get(name)
            if callable(target) and getattr(target, "__module__", None) == getattr(mod, "__name__", None):
                try:
                    for sub in _auto_call_chain(target, _depth + 1, _seen):
                        out.append(f"  → {sub}")
                except Exception:
                    pass
    return out[:15]


def register_task(
    task_id: str,
    name: str,
    func: Callable,
    description: str = "",
    default_cron: str = "0 2 * * *",   # 默认每天凌晨2点
    category: str = "general",
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
        "enabled": final_enabled,
        "registered_at": datetime.now().isoformat(),
        "call_chain": call_chain if call_chain is not None else _auto_call_chain(func),
    }
    logger.info(f"任务已注册: {task_id} ({name}), cron={current_cron}")


def _localize(task: dict, lang: str) -> tuple:
    """根据 lang 返回 (显示名, 显示描述)；非法值回退中文。"""
    if lang == "en":
        return task.get("name_en") or task.get("name"), task.get("description_en") or task.get("description")
    return task.get("name"), task.get("description")


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

    logger.info(f"[{task_id}] 开始执行 ({trigger})")
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
                if biz_msg:
                    result["error"] = str(biz_msg)
        else:
            result["success"] = True
            result["result"] = {"message": str(func_result)}
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        result["error_trace"] = traceback.format_exc()
        logger.error(f"[{task_id}] 执行失败: {e}")
    except BaseException as e:
        # 捕获 SystemExit / KeyboardInterrupt 等被强行中断的情况
        # （例如 WorkBuddy safe-delete 守卫在 os.remove 时 raise SystemExit）。
        # 必须记录执行历史，否则会出现“任务执行了但历史为空”。
        result["success"] = False
        result["error"] = f"{type(e).__name__}: {e}"
        result["error_trace"] = traceback.format_exc()
        logger.error(f"[{task_id}] 执行被强行中断({type(e).__name__}): {e}")

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

    logger.info(f"[{task_id}] 执行完成: success={result['success']}, {elapsed:.2f}s")
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
    """
    with _active_lock:
        if task_id in _active_runs:
            logger.warning(
                f"[{task_id}] 跳过本次调度触发：上一轮执行仍在运行中（单飞保护）"
            )
            return
    _execute_task(task_id, trigger)


def run_task_async(task_id: str, trigger: str = "manual") -> dict:
    """
    立即执行任务（后台线程，立即返回）。
    返回 {accepted, running}；若已在运行或校验失败则返回错误。
    """
    task = _task_registry.get(task_id)
    if not task:
        return {"success": False, "accepted": False, "error": f"任务 {task_id} 未找到"}
    if not task["enabled"]:
        return {"success": False, "accepted": False, "error": f"任务 {task_id} 已禁用"}
    with _active_lock:
        if task_id in _active_runs:
            return {"accepted": False, "running": True, "error": "任务正在运行中"}
    threading.Thread(target=_execute_task, args=(task_id, trigger), daemon=True).start()
    return {"accepted": True, "running": True, "task_id": task_id,
            "started_at": datetime.now().isoformat()}


def is_task_running(task_id: str) -> bool:
    with _active_lock:
        return task_id in _active_runs


def get_active_runs() -> dict:
    with _active_lock:
        return dict(_active_runs)


def _ensure_task_log_table(conn):
    """确保 task_execution_log 表存在且含 error_trace 列。

    兼容旧库：旧表在 CREATE TABLE IF NOT EXISTS 时已存在但缺 error_trace 列，
    该语句不会自动加列，需通过 PRAGMA 检查后 ALTER 补列，否则查询报错
    'no such column: error_trace'。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_execution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            task_name TEXT,
            category TEXT,
            trigger_type TEXT,
            success INTEGER,
            started_at TEXT,
            completed_at TEXT,
            elapsed_seconds REAL,
            result_json TEXT,
            error TEXT,
            error_trace TEXT
        )
    """)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(task_execution_log)").fetchall()}
        if "error_trace" not in cols:
            conn.execute("ALTER TABLE task_execution_log ADD COLUMN error_trace TEXT")
            conn.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"确保 error_trace 列失败: {e}")


def _save_task_result(result: dict):
    """将任务执行结果保存到 app.db"""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
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
            _retention_days = 3
        conn.execute(
            f"DELETE FROM task_execution_log WHERE started_at < datetime('now', '-{_retention_days} days')"
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
def _fetch_latest_runs() -> dict:
    """
    一次性查出每个任务的最新一条执行记录（单条 SQL + 子查询分组），
    避免前端 list + 逐任务 detail 产生的 N+1 请求。
    返回 {task_id: [run_dict]}（每个任务仅含最新 1 条，足够卡片展示）。
    """
    result: dict = {}
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        _ensure_task_log_table(conn)
        rows = conn.execute(
            """            SELECT l.task_id, l.task_name, l.category, l.trigger_type, l.success,
                      l.started_at, l.completed_at, l.elapsed_seconds, l.error, l.error_trace
               FROM task_execution_log l
               INNER JOIN (
                   SELECT task_id, MAX(id) AS max_id
                   FROM task_execution_log
                   GROUP BY task_id
               ) m ON l.task_id = m.task_id AND l.id = m.max_id"""
        ).fetchall()
        for r in rows:
            result[r[0]] = [{
                "task_id": r[0], "task_name": r[1], "category": r[2],
                "trigger": r[3], "success": bool(r[4]),
                "started_at": r[5], "completed_at": r[6],
                "elapsed_seconds": r[7], "error": r[8], "error_trace": r[9],
            }]
        conn.close()
    except Exception as e:
        logger.warning(f"批量查询最新执行记录失败: {e}")
    return result


def list_tasks(include_runs: bool = False, lang: str = "zh") -> list[dict]:
    """列出所有已注册的任务（include_runs=True 时附带每个任务最新一条执行记录）"""
    sched = get_scheduler()
    latest_runs = _fetch_latest_runs() if include_runs else {}
    tasks = []
    for task_id, task in _task_registry.items():
        job = sched.get_job(f"task_{task_id}")
        disp_name, disp_desc = _localize(task, lang)
        entry = {
            "task_id": task_id,
            "name": disp_name,
            "description": disp_desc,
            "category": task["category"],
            "enabled": task["enabled"],
            "current_cron": task["current_cron"],
            "default_cron": task["default_cron"],
            "next_run": str(job.next_run_time) if job else None,
            "registered_at": task["registered_at"],
            "running": is_task_running(task_id),
            "call_chain": task.get("call_chain", []),
        }
        if include_runs:
            entry["recent_runs"] = latest_runs.get(task_id, [])
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
        "description": disp_desc,
        "category": task["category"],
        "enabled": task["enabled"],
        "current_cron": task["current_cron"],
        "default_cron": task["default_cron"],
        "next_run": str(job.next_run_time) if job else None,
        "registered_at": task["registered_at"],
        "running": is_task_running(task_id),
        "call_chain": task.get("call_chain", []),
    }

    # 从数据库获取最近执行记录
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
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
        detail["recent_runs"] = []

    return detail


def get_task_history(limit: int = 20) -> list[dict]:
    """获取最近的任务执行历史"""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        _ensure_task_log_table(conn)
        rows = conn.execute(
            """            SELECT task_id, task_name, category, trigger_type, success,
                      started_at, completed_at, elapsed_seconds, error, error_trace
               FROM task_execution_log
               ORDER BY started_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        conn.close()
        return [
            {
                "task_id": r[0], "task_name": r[1], "category": r[2],
                "trigger": r[3], "success": bool(r[4]),
                "started_at": r[5], "completed_at": r[6],
                "elapsed_seconds": r[7], "error": r[8], "error_trace": r[9],
            }
            for r in rows
        ]
    except Exception:
        return list(reversed(_task_history[-limit:]))


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

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
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("task_runner")

# 路径配置
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BACKEND_DIR / "db" / "app.db"

# ========== 任务注册表 ==========
_task_registry: dict[str, dict] = {}
_task_history: list[dict] = []
MAX_HISTORY = 50
_lock = threading.Lock()

# 全局调度器
_scheduler: Optional[BackgroundScheduler] = None


def get_scheduler() -> BackgroundScheduler:
    """获取或创建全局调度器"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


# ========== 任务注册 ==========
def register_task(
    task_id: str,
    name: str,
    func: Callable,
    description: str = "",
    default_cron: str = "0 2 * * *",   # 默认每天凌晨2点
    category: str = "general",
    enabled: bool = True,
):
    """
    注册一个可调度的任务。

    Args:
        task_id: 唯一标识符
        name: 显示名称
        func: 执行函数，返回 dict 或 str
        description: 任务描述
        default_cron: 默认 cron 表达式 (分 时 日 月 周)
        category: 分类 (eflow / ran_ume / whatsapp / site_outage / general)
        enabled: 是否启用
    """
    _task_registry[task_id] = {
        "task_id": task_id,
        "name": name,
        "func": func,
        "description": description,
        "default_cron": default_cron,
        "current_cron": default_cron,
        "category": category,
        "enabled": enabled,
        "registered_at": datetime.now().isoformat(),
    }
    logger.info(f"任务已注册: {task_id} ({name})")


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
    }

    try:
        func_result = task["func"]()
        if isinstance(func_result, dict):
            result["success"] = func_result.get("success", True)
            result["result"] = func_result
        else:
            result["success"] = True
            result["result"] = {"message": str(func_result)}
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        logger.error(f"[{task_id}] 执行失败: {e}")

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

    logger.info(f"[{task_id}] 执行完成: success={result['success']}, {elapsed:.2f}s")
    return result


def _save_task_result(result: dict):
    """将任务执行结果保存到 app.db"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
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
                error TEXT
            )
        """)
        conn.execute("""
            INSERT INTO task_execution_log
            (task_id, task_name, category, trigger_type, success, started_at, completed_at, elapsed_seconds, result_json, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ))
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

    cron = cron_expr or task["default_cron"]
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
        run_task,
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
def list_tasks() -> list[dict]:
    """列出所有已注册的任务"""
    sched = get_scheduler()
    tasks = []
    for task_id, task in _task_registry.items():
        job = sched.get_job(f"task_{task_id}")
        tasks.append({
            "task_id": task_id,
            "name": task["name"],
            "description": task["description"],
            "category": task["category"],
            "enabled": task["enabled"],
            "current_cron": task["current_cron"],
            "default_cron": task["default_cron"],
            "next_run": str(job.next_run_time) if job else None,
            "registered_at": task["registered_at"],
        })
    return tasks


def get_task_detail(task_id: str) -> Optional[dict]:
    """获取任务详情"""
    task = _task_registry.get(task_id)
    if not task:
        return None

    sched = get_scheduler()
    job = sched.get_job(f"task_{task_id}")

    detail = {
        "task_id": task_id,
        "name": task["name"],
        "description": task["description"],
        "category": task["category"],
        "enabled": task["enabled"],
        "current_cron": task["current_cron"],
        "default_cron": task["default_cron"],
        "next_run": str(job.next_run_time) if job else None,
        "registered_at": task["registered_at"],
    }

    # 从数据库获取最近执行记录
    try:
        conn = sqlite3.connect(str(DB_PATH))
        rows = conn.execute(
            """SELECT task_id, task_name, category, trigger_type, success,
                      started_at, completed_at, elapsed_seconds, error
               FROM task_execution_log
               WHERE task_id = ?
               ORDER BY id DESC LIMIT 10""",
            (task_id,)
        ).fetchall()
        detail["recent_runs"] = [
            {
                "task_id": r[0], "task_name": r[1], "category": r[2],
                "trigger": r[3], "success": bool(r[4]),
                "started_at": r[5], "completed_at": r[6],
                "elapsed_seconds": r[7], "error": r[8],
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
        conn = sqlite3.connect(str(DB_PATH))
        rows = conn.execute(
            """SELECT task_id, task_name, category, trigger_type, success,
                      started_at, completed_at, elapsed_seconds, error
               FROM task_execution_log
               ORDER BY id DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        conn.close()
        return [
            {
                "task_id": r[0], "task_name": r[1], "category": r[2],
                "trigger": r[3], "success": bool(r[4]),
                "started_at": r[5], "completed_at": r[6],
                "elapsed_seconds": r[7], "error": r[8],
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

    sched = get_scheduler()
    job_id = f"task_{task_id}"

    if enabled:
        schedule_task(task_id)
        return {"success": True, "message": f"任务 {task['name']} 已启用"}
    else:
        if sched.get_job(job_id):
            sched.remove_job(job_id)
        return {"success": True, "message": f"任务 {task['name']} 已禁用"}

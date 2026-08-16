"""任务管理 API —— 从 main.py 拆分（架构优化 Phase 1）

迁移端点（路径与返回结构与迁移前完全一致，前端零改动）：
- /api/eflow/sync、/api/eflow/status          旧 eFlow 兼容接口
- /api/tasks、/api/tasks/history、/api/tasks/failures
- /api/tasks/{task_id}、/run、/status、/stats、/history
- /api/tasks/{task_id}/schedule、/toggle
"""
import logging

from fastapi import APIRouter, Request, Depends, HTTPException

from backend.security import require_protected
from backend.services import task_runner
from backend.task_registry import sync_history

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


def _req_lang(request: Request) -> str:
    """从 Accept-Language 头推断语言（en 优先，其余回退 zh）。"""
    accept = (request.headers.get("Accept-Language") or "").lower()
    return "en" if accept.startswith("en") else "zh"


# ========== 旧 eFlow 兼容接口 ==========

@router.post("/api/eflow/sync", dependencies=[Depends(require_protected)])
def trigger_eflow_sync():
    """手动触发 eFlow API 数据同步（兼容旧接口）"""
    result = task_runner.run_task("eflow_sync", trigger="manual")
    if result.get("result") and isinstance(result["result"], dict):
        # 兼容旧接口返回格式
        inner = result["result"]
        if "tables_synced" in inner:
            sync_history.append(inner)
            while len(sync_history) > 20:
                sync_history.pop(0)
            return inner
    return result


@router.get("/api/eflow/status")
def eflow_sync_status():
    """eFlow API 同步状态（兼容旧接口）"""
    detail = task_runner.get_task_detail("eflow_sync")
    return {
        "scheduler_running": task_runner.get_scheduler().running,
        "next_run": detail.get("next_run") if detail else None,
        "schedule": "每小时第22分钟",
        "history": sync_history[-10:],
    }


# ========== 通用任务管理 API ==========

@router.get("/api/tasks")
def list_all_tasks(request: Request):
    """列出所有已注册的定时任务（含最新执行记录，单次返回，避免前端 N+1）"""
    return {"tasks": task_runner.list_tasks(include_runs=True, lang=_req_lang(request))}


@router.get("/api/tasks/history")
def get_tasks_history(
    limit: int = 50,
    offset: int = 0,
    task_id: str | None = None,
    success: int | None = None,
    trigger: str | None = None,
    keyword: str | None = None,
    start: str | None = None,
    end: str | None = None,
):
    """全局执行历史（总历史记录）—— 跨所有任务，支持按任务/状态/触发/关键字/时间范围过滤与分页

    返回 {"history": [...], "total": int}；不传任何过滤参数时等价于「最近 limit 条全部任务」。
    """
    return task_runner.get_global_history(
        limit=limit, offset=offset, task_id=task_id, success=success,
        trigger=trigger, keyword=keyword, start=start, end=end,
    )


@router.get("/api/tasks/failures")
def tasks_failures(days: int = 3, limit: int = 200):
    """按 error 首行聚类近期失败，便于快速判断是否为同一根因"""
    return task_runner.get_recent_failures(days, limit)


@router.get("/api/tasks/{task_id}")
def get_task_info(task_id: str, request: Request):
    """获取任务详情（含最近执行记录）"""
    detail = task_runner.get_task_detail(task_id, lang=_req_lang(request))
    if not detail:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 未找到")
    return detail


@router.post("/api/tasks/{task_id}/run", dependencies=[Depends(require_protected)])
def run_task_now(task_id: str):
    """立即执行指定任务（后台异步执行，立即返回 accepted）"""
    return task_runner.run_task_async(task_id, trigger="manual")


@router.post("/api/tasks/{task_id}/stop", dependencies=[Depends(require_protected)])
def stop_task_now(task_id: str):
    """停止正在执行的任务（终止 Worker 进程，看门狗会自动重新拉起）"""
    return task_runner.stop_task(task_id)


@router.get("/api/tasks/{task_id}/status")
def task_run_status(task_id: str):
    """查询任务是否正在运行"""
    return {"task_id": task_id, "running": task_runner.is_task_running(task_id)}


@router.get("/api/tasks/{task_id}/stats")
def task_stats(task_id: str, days: int | None = None):
    """任务健康度统计（成功率 / 平均·最大耗时）"""
    return task_runner.get_task_stats(task_id, days)


@router.get("/api/tasks/{task_id}/history")
def task_history(task_id: str, limit: int = 200):
    """某任务的执行历史（分页 / 导出用）"""
    return {"history": task_runner.get_task_history_by_task(task_id, limit)}


@router.post("/api/tasks/{task_id}/schedule")
def update_task_schedule(task_id: str, body: dict):
    """更新任务调度频率
    body: {"cron": "分 时 日 月 周"}
    示例: {"cron": "0 8 * * *"} 每天8点
          {"cron": "30 7 * * 1-5"} 工作日7:30
          {"cron": "0 */4 * * *"} 每4小时
    """
    cron = body.get("cron", "")
    if not cron:
        raise HTTPException(status_code=400, detail="缺少 cron 表达式")
    return task_runner.update_task_schedule(task_id, cron)


@router.post("/api/tasks/{task_id}/toggle")
def toggle_task_enabled(task_id: str, body: dict):
    """启用/禁用任务
    body: {"enabled": true/false}
    """
    enabled = body.get("enabled", True)
    return task_runner.toggle_task(task_id, enabled)


# ========== 任务配置 导出/导入（Settings「任务配置」页签） ==========
# 注意：/config/export 与 /config/import 必须在 /{task_id}/config 之前注册，
# 避免路径参数把 "config" 当成 task_id 解析。

@router.get("/api/tasks/config/export", dependencies=[Depends(require_protected)])
def task_config_export_all():
    """全部任务配置导出（JSON 数组，供 Settings 页签「导出全部」）"""
    return {"configs": task_runner.export_all_task_configs()}


@router.post("/api/tasks/config/import", dependencies=[Depends(require_protected)])
def task_config_import_all(body: dict):
    """批量导入任务配置
    body: {"configs": [{"task_id": "...", "cron"?: "...", "enabled"?: bool}, ...]}
    逐项独立成败：非法项只影响自身，返回 {applied, errors}。
    """
    configs = body.get("configs", [])
    return task_runner.import_task_configs(configs)


@router.get("/api/tasks/{task_id}/config")
def task_config_get(task_id: str):
    """单任务配置（注册表元数据 + 当前 cron/enabled/updated_at）"""
    cfg = task_runner.get_task_config(task_id)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 未找到")
    return cfg


@router.post("/api/tasks/{task_id}/config", dependencies=[Depends(require_protected)])
def task_config_apply(task_id: str, body: dict):
    """应用单任务配置
    body: {"cron"?: "分 时 日 月 周", "enabled"?: true/false}（至少一项）
    """
    cron = body.get("cron")
    enabled = body.get("enabled")
    if cron is None and enabled is None:
        raise HTTPException(status_code=400, detail="至少提供 cron 或 enabled 之一")
    return task_runner.apply_task_config(task_id, cron=cron, enabled=enabled)


@router.post("/api/tasks/toggle-all", dependencies=[Depends(require_protected)])
def toggle_all_tasks_enabled(body: dict):
    """统一启用/禁用所有任务（Task Manager 主开关）
    body: {"enabled": true/false}
    """
    enabled = bool(body.get("enabled", True))
    return task_runner.toggle_all_tasks(enabled)

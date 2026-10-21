"""任务管理 API —— 从 main.py 拆分（架构优化 Phase 1）

迁移端点（路径与返回结构与迁移前完全一致，前端零改动）：
- /api/eflow/sync、/api/eflow/status          旧 eFlow 兼容接口
- /api/tasks、/api/tasks/history、/api/tasks/failures
- /api/tasks/{task_id}、/run、/status、/stats、/history
- /api/tasks/{task_id}/schedule、/toggle
"""
import hashlib
import json
import logging

from fastapi import APIRouter, Request, Depends, HTTPException, Response

from backend.api_i18n import translate_ui_fields

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
def list_all_tasks(request: Request, response: Response):
    """列出所有已注册的定时任务（含最新执行记录，单次返回，避免前端 N+1）

    B6 轮询风暴整改（2026-10-01）：MW 实时看板子帧曾以 ~2.7s/次 的频率轮询本接口
    （单响应 ~77KB，单标签页 10 分钟 212 次 ≈ 100MB/小时）。前端已改为仅标签页可见时
    轮询（TaskSyncWidget 60s + visibilitychange）；本接口在此之上支持 ETag 协商缓存：
    - 首次请求：正常返回 200，并带 `ETag: "<sha1-16hex>"`；
    - 后续请求带 `If-None-Match: "<etag>"`：内容无变化（序列化后 sha1 相同）→ 304 空体，
      传输量从 ~77KB 降到 ~200B；有变化（任务状态/最新执行记录变了）→ 200 全量 + 新 ETag。
    - 为什么用内容哈希而不是版本号：list_tasks 每次现算（队列状态、新鲜度、重试预测
      都是活的），没有可靠的递增版本可用；sha1(序列化结果) 语义即"内容没变就不重传"。
    - Cache-Control: no-cache：允许客户端缓存副本但要求每次协商，绝不返回过期任务状态。
    """
    payload = {"tasks": task_runner.list_tasks(include_runs=True, lang=_req_lang(request))}
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    etag = '"' + hashlib.sha1(body).hexdigest()[:16] + '"'

    inm = request.headers.get("if-none-match")
    if inm:
        # 容忍多值/弱验证器形态：W/"..."、"a, b"、带引号
        candidates = [c.strip().removeprefix("W/").strip() for c in inm.split(",")]
        if etag in candidates:
            # 304 必须直接 return Response —— 若只改 response.status_code 再 return dict，
            # FastAPI 会用返回值重新序列化并覆盖状态码，304 退化成 200 全量（已实测踩坑）。
            return Response(
                status_code=304,
                headers={"ETag": etag, "Cache-Control": "no-cache"},
            )

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return payload


# 必须定义在 /api/tasks/{task_id} 之前，否则 "running" 会被当成 task_id
@router.get("/api/tasks/running")
def tasks_running():
    """轻量运行状态：{task_id: bool}。

    应用顶层 TaskStatusContext 每 8s（有任务运行时 2s）轮询一次，只关心
    running 一个布尔值。走 /api/tasks 的话每次要传 ~75KB 并现算最新执行记录、
    重试预测、中英文名等（实测 150~490ms）；这里约 1KB、几毫秒。
    """
    return {"running": task_runner.get_running_map()}


@router.get("/api/tasks/history")
def get_tasks_history(
    request: Request,
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
    return translate_ui_fields(task_runner.get_global_history(
        limit=limit, offset=offset, task_id=task_id, success=success,
        trigger=trigger, keyword=keyword, start=start, end=end,
    ), request)


@router.get("/api/tasks/failures")
def tasks_failures(request: Request, days: int = 3, limit: int = 200):
    """按 error 首行聚类近期失败，便于快速判断是否为同一根因"""
    return translate_ui_fields(task_runner.get_recent_failures(days, limit), request)


@router.get("/api/tasks/{task_id}")
def get_task_info(task_id: str, request: Request):
    """获取任务详情（含最近执行记录）"""
    detail = task_runner.get_task_detail(task_id, lang=_req_lang(request))
    if not detail:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 未找到")
    return translate_ui_fields(detail, request)


@router.post("/api/tasks/{task_id}/run", dependencies=[Depends(require_protected)])
def run_task_now(request: Request, task_id: str):
    """立即执行指定任务（后台异步执行，立即返回 accepted）"""
    return translate_ui_fields(task_runner.run_task_async(task_id, trigger="manual"), request)


@router.post("/api/tasks/{task_id}/stop", dependencies=[Depends(require_protected)])
def stop_task_now(request: Request, task_id: str):
    """停止正在执行的任务（终止 Worker 进程，看门狗会自动重新拉起）"""
    return translate_ui_fields(task_runner.stop_task(task_id), request)


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
def update_task_schedule(request: Request, task_id: str, body: dict):
    """更新任务调度频率
    body: {"cron": "分 时 日 月 周"}
    示例: {"cron": "0 8 * * *"} 每天8点
          {"cron": "30 7 * * 1-5"} 工作日7:30
          {"cron": "0 */4 * * *"} 每4小时
    """
    cron = body.get("cron", "")
    if not cron:
        raise HTTPException(status_code=400, detail="缺少 cron 表达式")
    return translate_ui_fields(task_runner.update_task_schedule(task_id, cron), request)


@router.post("/api/tasks/{task_id}/toggle")
def toggle_task_enabled(request: Request, task_id: str, body: dict):
    """启用/禁用单个任务（用户显式选择，会被记为「手动停止」）

    body: {"enabled": true/false}
    禁用后该任务的 manually_stopped 置位，主开关再次启用时会跳过它；
    启用时清零标记，恢复受主开关管辖。
    """
    enabled = body.get("enabled", True)
    return translate_ui_fields(task_runner.toggle_task(task_id, enabled), request)


# ========== 任务配置 导出/导入（Settings「任务配置」页签） ==========
# 注意：/config/export 与 /config/import 必须在 /{task_id}/config 之前注册，
# 避免路径参数把 "config" 当成 task_id 解析。

@router.get("/api/tasks/config/export", dependencies=[Depends(require_protected)])
def task_config_export_all():
    """全部任务配置导出（JSON 数组，供 Settings 页签「导出全部」）"""
    return {"configs": task_runner.export_all_task_configs()}


@router.post("/api/tasks/config/import", dependencies=[Depends(require_protected)])
def task_config_import_all(request: Request, body: dict):
    """批量导入任务配置
    body: {"configs": [{"task_id": "...", "cron"?: "...", "enabled"?: bool, "manually_stopped"?: bool}, ...]}
    逐项独立成败：非法项只影响自身，返回 {applied, errors}。
    manually_stopped 可选：省略时由 enabled 推导（false=被导入为手动关过），
    显式给出则以它为准。
    """
    configs = body.get("configs", [])
    return translate_ui_fields(task_runner.import_task_configs(configs), request)


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

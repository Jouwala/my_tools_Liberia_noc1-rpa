"""任务配置文件管理 API（Settings「任务配置」页签 → 配置文件管理）

通用：为注册过配置文件的任务提供 查看/编辑/导入导出。
- GET  /api/task-configs                        已注册配置文件的任务列表（含 schema）
- GET  /api/task-configs/{task_id}              某任务当前配置 + schema + meta
- PUT  /api/task-configs/{task_id}              按 schema 更新（body: {字段: 值}）
- GET  /api/task-configs/{task_id}/export       导出完整配置 JSON
- POST /api/task-configs/{task_id}/import       导入（整体替换，schema 校验）

保存/导入成功后自动重启 u/n 组 Worker（看门狗秒级重拉），使配置在下次
任务运行时即生效（服务在模块导入时读取配置文件，Worker 长驻会缓存旧值）。
"""
import logging
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.security import require_protected
from backend.services import task_config_files

logger = logging.getLogger(__name__)

# Windows 下隐藏 taskkill 子进程的 CMD 窗口（与 services 各模块的 _SUBPROCESS_FLAGS 一致）
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

router = APIRouter(tags=["task-configs"])

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _restart_config_workers():
    """重启 u/n 组 Worker（配置任务所在组），看门狗会自动重新拉起。"""
    for name in ("worker_u.pid", "worker_n.pid"):
        pf = _PROJECT_ROOT / "backend" / name
        try:
            if pf.exists():
                pid = int(pf.read_text(encoding="utf-8").strip())
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, timeout=10,
                               creationflags=_SUBPROCESS_FLAGS)
                logger.info(f"[task-configs] 已重启 Worker {name} (pid={pid}) 使配置生效")
        except Exception as e:
            logger.warning(f"[task-configs] 重启 {name} 失败: {e}")


@router.get("/api/task-configs")
def task_configs_list():
    """已注册配置文件管理的任务（供前端决定给哪些任务显示配置区）"""
    return {"configs": task_config_files.list_configs()}


@router.get("/api/task-configs/{task_id}")
def task_configs_get(task_id: str):
    """某任务当前配置 + schema"""
    resource = task_config_files.get_resource(task_id)
    if resource is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 无配置文件管理")
    return {"meta": resource.meta(), "config": resource.load()}


@router.put("/api/task-configs/{task_id}", dependencies=[Depends(require_protected)])
def task_configs_update(task_id: str, body: dict):
    """按 schema 更新配置（只改 schema 内字段，内部字段保留）；保存后重启 Worker 生效"""
    res = task_config_files.update_config(task_id, body)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "更新失败"))
    _restart_config_workers()
    return res


@router.get("/api/task-configs/{task_id}/export", dependencies=[Depends(require_protected)])
def task_configs_export(task_id: str):
    """导出完整配置 JSON"""
    config = task_config_files.export_config(task_id)
    if config is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 无配置文件管理")
    return config


@router.post("/api/task-configs/{task_id}/import", dependencies=[Depends(require_protected)])
def task_configs_import(task_id: str, body: dict):
    """导入（整体替换，schema 校验）；成功后重启 Worker 生效"""
    res = task_config_files.import_config(task_id, body)
    if res.get("success"):
        _restart_config_workers()
    return res

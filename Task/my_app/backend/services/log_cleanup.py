# -*- coding: utf-8 -*-
"""日志文件清理（2026-09-11 新增，每日定时任务 log_cleanup）

背景
----
my_app/log/ 下的 runtime 日志由各 watchdog 以 ``open(path, "ab", buffering=0)``
打开后把句柄交给子进程继承，Windows 下**被占用的文件无法轮转/删除**，一度没有任何
轮转与大小上限：实测 4 个文件合计 466MB（backend_runtime.log 185MB /
realtime_proxy_fms_console.log 162MB / worker_runtime.log 89.5MB /
backend_watchdog.log 41.7MB）。2026-09-11 已改为「父进程 pipe 泵 + 按大小轮转」
（见 ``backend/log_writer.py``，单文件超 ``LOG_ROTATE_MAX_MB`` 默认 100MB 切 ``_pN``
分片；detached 的 realtime_proxy 因生命周期不同，改为拉起时挑未满分片）。

Windows 下被进程占用的文件仍然无法被外部重命名或删除，因此采用两段式方案：

  1. **写入侧按日期分文件**（已改）：backend_watchdog / worker_watchdog /
     realtime_proxy_ctl 的日志文件名带启动日期，每次启动一个新文件；
  2. **本任务负责收尾**：
     a. 把「已无进程写入的旧命名文件」（不含日期后缀）重命名为
        ``原名_YYYYMMDD.log``，使其进入可清理状态；
     b. 删除 mtime 超过保留期（默认 7 天）的日志文件。

安全边界（防误删）
------------------
  - 只作用于 ``<项目根>/log`` 单级目录，绝不递归其它目录；
  - 只处理 ``*.log`` / ``*.log.*`` 后缀；
  - 严格按 mtime 判定，保留期内一律不动；
  - 重命名失败即视为「仍在被写入」，跳过（不强制、不截断）；
  - ``LOG_CLEANUP_DRY_RUN=1`` 只报告不改动，供首次上线验证。

环境变量
--------
  LOG_RETENTION_DAYS      日志保留天数（默认 7）
  LOG_CLEANUP_DRY_RUN     =1 时只报告不删除（默认 0）
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("log_cleanup")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "log"


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


RETENTION_DAYS = _env_int("LOG_RETENTION_DAYS", 7)
DRY_RUN = os.environ.get("LOG_CLEANUP_DRY_RUN", "0") == "1"

# 需要「补打日期后缀」的持续写入型日志前缀（旧命名，无日期）
LEGACY_PREFIXES = (
    "backend_runtime", "backend_watchdog", "worker_runtime",
    "worker_watchdog", "realtime_proxy",
)


def _is_log_file(p: Path) -> bool:
    """只认 .log 与 .log.<ext>（如 .log.err），其它一律不动。"""
    name = p.name
    return name.endswith(".log") or ".log." in name


def _has_date_suffix(p: Path) -> bool:
    """文件名是否已含 _YYYYMMDD 形式的日期后缀。"""
    stem = p.name.split(".log")[0]
    parts = stem.split("_")
    return any(len(x) == 8 and x.isdigit() for x in parts)


def _rename_legacy(now: datetime) -> tuple:
    """把已无进程写入的旧命名日志补上日期后缀。

    返回 (renamed, skipped_busy, detail_list)。重命名失败 = 文件仍被占用 = 还在写，
    此时绝不强制处理，等它自然进入下一轮。
    """
    renamed, busy, detail = 0, 0, []
    if not LOG_DIR.is_dir():
        return renamed, busy, detail
    for p in sorted(LOG_DIR.iterdir()):
        if not p.is_file() or not _is_log_file(p):
            continue
        if _has_date_suffix(p):
            continue
        if not p.name.startswith(LEGACY_PREFIXES):
            continue
        # 今天刚写过的文件可能仍在被使用，先跳过（下一轮再处理）
        mtime = datetime.fromtimestamp(p.stat().st_mtime)
        if mtime.date() >= now.date():
            continue
        target = p.with_name(f"{p.name.split('.log')[0]}_{mtime:%Y%m%d}.log")
        if target.exists():
            continue
        try:
            if not DRY_RUN:
                p.rename(target)
            renamed += 1
            detail.append(f"{p.name} -> {target.name}")
        except (OSError, PermissionError) as e:
            # 被占用的文件无法重命名：说明仍在写入，跳过
            busy += 1
            detail.append(f"{p.name} 仍被占用，跳过 ({type(e).__name__})")
    return renamed, busy, detail


def _purge_expired(now: datetime) -> tuple:
    """删除 mtime 超过保留期的日志文件，返回 (deleted, freed_bytes, detail_list)。"""
    deleted, freed, detail = 0, 0, []
    if not LOG_DIR.is_dir():
        return deleted, freed, detail
    cutoff = now - timedelta(days=RETENTION_DAYS)
    for p in sorted(LOG_DIR.iterdir()):
        if not p.is_file() or not _is_log_file(p):
            continue
        mtime = datetime.fromtimestamp(p.stat().st_mtime)
        if mtime >= cutoff:
            continue
        try:
            size = p.stat().st_size
            if not DRY_RUN:
                p.unlink()
            deleted += 1
            freed += size
            detail.append(f"{p.name} ({size / 1048576:.1f}MB, {mtime:%Y-%m-%d})")
        except (OSError, PermissionError) as e:
            detail.append(f"{p.name} 删除失败: {type(e).__name__}")
    return deleted, freed, detail


def run_log_cleanup() -> dict:
    """定时任务入口：改名 + 清理，返回汇总 dict。"""
    start = time.time()
    now = datetime.now()
    errors = []
    try:
        renamed, busy, r_detail = _rename_legacy(now)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"旧日志改名失败: {e}", exc_info=True)
        renamed, busy, r_detail, error = 0, 0, [], f"改名阶段异常: {type(e).__name__}: {e}"
        errors.append(error)
    try:
        deleted, freed, d_detail = _purge_expired(now)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"过期日志清理失败: {e}", exc_info=True)
        deleted, freed, d_detail = 0, 0, []
        errors.append(f"清理阶段异常: {type(e).__name__}: {e}")

    summary = {
        "success": not errors,
        "log_dir": str(LOG_DIR),
        "retention_days": RETENTION_DAYS,
        "dry_run": DRY_RUN,
        "renamed": renamed,
        "busy_skipped": busy,
        "deleted": deleted,
        "freed_mb": round(freed / 1048576, 2),
        "renamed_detail": r_detail[:20],
        "deleted_detail": d_detail[:20],
        "errors": errors,
        "message": (
            f"日志清理（保留 {RETENTION_DAYS} 天）：改名 {renamed} 个、"
            f"占用跳过 {busy} 个、删除 {deleted} 个、释放 {freed / 1048576:.1f}MB"
            + ("[DRY RUN 未实际删除]" if DRY_RUN else "")
        ),
        "elapsed_seconds": round(time.time() - start, 2),
    }
    logger.info(summary["message"])
    return summary


if __name__ == "__main__":
    import json
    print(json.dumps(run_log_cleanup(), ensure_ascii=False, indent=2))

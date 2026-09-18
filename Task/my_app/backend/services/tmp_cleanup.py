# -*- coding: utf-8 -*-
"""TMP 目录定期清理（2026-09-18 新增，每日定时任务 tmp_cleanup）

背景
----
按 ``docs/CODE_CLEANUP_GUIDE.md`` 约定，所有临时产物（截图 / 抓包 JSON /
一次性诊断目录）都落在 ``my_app/TMP/``。该目录已被 gitignore，但**体积没人管**：
上线首日实测 462MB，其中 4 个 ``_diag*_eflow_*`` 诊断目录合计约 380MB。
本任务参照 ``log_cleanup.py`` 的两段式安全模型做自动回收。

两段式（防误删，任何阶段都可还原）
----------------------------------
  1. **隔离**：把「最后活动时间」超过保留期（默认 7 天）的条目**同盘 mv** 到
     ``TMP/_quarantine_YYYYMMDD/``，不删除内容，随时可挪回；
  2. ** purge**：删除已超过再一个保留期（默认再 7 天，即总计 14 天）的隔离目录。

条目的「最后活动时间」= 文件 mtime；目录取其子树内所有文件/目录 mtime 的最大值，
只要目录里还有任何新写入就不会被隔离。

安全边界（防误删）
------------------
  - 只作用于 ``<项目根>/TMP`` 单级条目，不碰其它目录；
  - 服务在用路径白名单（见 ``WHITELIST``）永不处理；
  - 被进程占用导致 mv/删除失败 → 跳过，绝不强制；
  - ``TMP_CLEANUP_DRY_RUN=1`` 只报告不改动，供首次上线验证。

环境变量
--------
  TMP_RETENTION_DAYS    保留天数（默认 7，同时是隔离区二次保留天数）
  TMP_CLEANUP_DRY_RUN   =1 时只报告不改动（默认 0）
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("tmp_cleanup")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TMP_DIR = PROJECT_ROOT / "TMP"
QUARANTINE_PREFIX = "_quarantine_"


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


RETENTION_DAYS = _env_int("TMP_RETENTION_DAYS", 7)
DRY_RUN = os.environ.get("TMP_CLEANUP_DRY_RUN", "0") == "1"

# 服务在写 / 被代码或文档引用的路径（见 CODE_CLEANUP_GUIDE 2. 目录归属表）：永不处理
WHITELIST = {
    "ccn_free_rating_charts",   # TMP 出图服务
    "fw_charts",                # FW KPI 报表图
    "ipran_charts",             # iPRAN 报表图
    "dl", "dl_en",              # 邮件报表附件下载目录
    "email_recovery_state.json",
    "task_health_alert_state.json",
    "build_msportal_data.py",   # portal_catalog 引用的 data.js 生成脚本
}


def _tree_latest_mtime(p: Path) -> float:
    """目录取子树内 mtime 最大值；权限异常的子项跳过（视为不可动，返回极大值）。"""
    latest = p.stat().st_mtime
    try:
        for root, dirs, files in os.walk(p):
            for name in dirs + files:
                try:
                    m = Path(root, name).stat().st_mtime
                except OSError:
                    return float("inf")
                latest = max(latest, m)
    except OSError:
        return float("inf")
    return latest


def _entry_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(p):
        for name in files:
            try:
                total += Path(root, name).stat().st_size
            except OSError:
                pass
    return total


def _quarantine_dir_name(now: datetime) -> str:
    return f"{QUARANTINE_PREFIX}{now:%Y%m%d}"


def _quarantine_stale(now: datetime) -> tuple:
    """把过期的顶层条目同盘 mv 进隔离区。返回 (moved, bytes, detail)。"""
    moved, freed, detail = 0, 0, []
    if not TMP_DIR.is_dir():
        return moved, freed, detail
    cutoff = now - timedelta(days=RETENTION_DAYS)
    for p in sorted(TMP_DIR.iterdir()):
        name = p.name
        if name in WHITELIST or name.startswith(QUARANTINE_PREFIX):
            continue
        try:
            latest = p.stat().st_mtime if p.is_file() else _tree_latest_mtime(p)
        except OSError:
            continue
        if datetime.fromtimestamp(latest) >= cutoff:
            continue
        size = _entry_size(p)
        dest = TMP_DIR / _quarantine_dir_name(now) / name
        seq = 0
        while dest.exists():
            seq += 1
            dest = dest.parent / f"{name}_{seq}"
        try:
            if not DRY_RUN:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dest))
            moved += 1
            freed += size
            detail.append(f"{name} ({size / 1048576:.1f}MB) -> {dest.parent.name}/")
        except (OSError, PermissionError) as e:
            # 被占用 mv 不动：跳过，等下一轮；顺手回收本轮可能留下的空隔离目录
            detail.append(f"{name} 仍被占用，跳过 ({type(e).__name__})")
            try:
                qdir = TMP_DIR / _quarantine_dir_name(now)
                if qdir.is_dir() and not any(qdir.iterdir()):
                    qdir.rmdir()
            except OSError:
                pass
    return moved, freed, detail


def _purge_old_quarantine(now: datetime) -> tuple:
    """删除隔离超过 RETENTION_DAYS 的 _quarantine_YYYYMMDD 目录。返回 (purged, bytes, detail)。"""
    purged, freed, detail = 0, 0, []
    if not TMP_DIR.is_dir():
        return purged, freed, detail
    for p in sorted(TMP_DIR.glob(f"{QUARANTINE_PREFIX}*")):
        if not p.is_dir() or len(p.name) != len(QUARANTINE_PREFIX) + 8:
            continue
        try:
            qdate = datetime.strptime(p.name[len(QUARANTINE_PREFIX):], "%Y%m%d")
        except ValueError:
            continue
        if qdate > now - timedelta(days=RETENTION_DAYS):
            continue
        size = _entry_size(p)
        try:
            if not DRY_RUN:
                shutil.rmtree(p)
            purged += 1
            freed += size
            detail.append(f"{p.name} ({size / 1048576:.1f}MB, 隔离于 {qdate:%Y-%m-%d})")
        except (OSError, PermissionError) as e:
            detail.append(f"{p.name} 删除失败: {type(e).__name__}")
    return purged, freed, detail


def run_tmp_cleanup() -> dict:
    """定时任务入口：隔离过期条目 + 清空超期隔离区，返回汇总 dict（禁 sys.exit）。"""
    start = time.time()
    now = datetime.now()
    errors = []
    try:
        moved, mv_bytes, m_detail = _quarantine_stale(now)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"TMP 隔离阶段失败: {e}", exc_info=True)
        moved, mv_bytes, m_detail = 0, 0, []
        errors.append(f"隔离阶段异常: {type(e).__name__}: {e}")
    try:
        purged, pg_bytes, p_detail = _purge_old_quarantine(now)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"TMP 隔离区清空失败: {e}", exc_info=True)
        purged, pg_bytes, p_detail = 0, 0, []
        errors.append(f"清空阶段异常: {type(e).__name__}: {e}")

    total = moved + purged
    summary = {
        "success": not errors,
        "tmp_dir": str(TMP_DIR),
        "retention_days": RETENTION_DAYS,
        "dry_run": DRY_RUN,
        "quarantined": moved,
        "quarantine_mb": round(mv_bytes / 1048576, 2),
        "purged": purged,
        "purged_mb": round(pg_bytes / 1048576, 2),
        "quarantine_detail": m_detail[:30],
        "purge_detail": p_detail[:30],
        "errors": errors,
        "message": (
            f"TMP 清理（保留 {RETENTION_DAYS} 天）：隔离 {moved} 项 "
            f"{mv_bytes / 1048576:.1f}MB、彻底删除过期隔离 {purged} 项 "
            f"{pg_bytes / 1048576:.1f}MB"
            + ("[DRY RUN 未实际改动]" if DRY_RUN else "")
        ),
        "elapsed_seconds": round(time.time() - start, 2),
    }
    logger.info(summary["message"])
    return summary


if __name__ == "__main__":
    import json
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    t0 = time.time()
    print(json.dumps(run_tmp_cleanup(), ensure_ascii=False, indent=2))
    print(f"总运行时间: {time.time() - t0:.2f} 秒")

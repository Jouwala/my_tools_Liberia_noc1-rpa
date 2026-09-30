# -*- coding: utf-8 -*-
"""FineBI 报表 FTP 同步服务
==============================

每小时从 FINEBI 服务器 (192.168.100.19, 账号 FINEBI) 的
``/webroot/WEB-INF/schedule`` 下，找出**每个子文件夹里最新的一份 Excel**
（FineBI 调度输出结构：``<报告>/<YYYY-MM-DD>/<HHMM>/通用结果/*.xlsx``），
下载到本地 ``data/finebi_reports/<报告名>/`` 供页面（Task Report Files →
FINEBI report 页签）下载。

策略：
  - 每个报告文件夹只保留最新 1 份 Excel（旧的本地副本会被清理）。
  - 只递归最新 3 个日期目录，避免调度历史日积月累后全量遍历 FTP。
  - 下载经临时文件 + 原子替换，扛 Windows 文件锁。
  - 某个文件夹本轮没有 Excel 只登记进 missing、不判任务失败：FineBI 在 :53 重算时会先删掉
    上一轮输出目录，新副本约 :02–:05 才落盘，这是源的常态；本机连历史副本都没有才算 error。
"""
from __future__ import annotations

import ftplib
import logging
import os
import time
from pathlib import Path
from typing import List, Optional

from backend.config.remote_host import get_ftp_host, get_ftp_port

logger = logging.getLogger(__name__)

MY_APP_DIR = Path(__file__).resolve().parent.parent.parent
FINEBI_LOCAL_DIR = MY_APP_DIR / "data" / "finebi_reports"
REMOTE_BASE = "/webroot/WEB-INF/schedule"
FTP_USER = "FINEBI"
FTP_PASS = "DX"

_EXCEL_EXTS = (".xlsx", ".xls")
# 每个报告文件夹最多回溯几个日期子目录（目录名 YYYY-MM-DD 字典序即时间序）
_MAX_DATE_DIRS = 3


def _connect() -> ftplib.FTP:
    ftp = ftplib.FTP(timeout=30)
    ftp.connect(get_ftp_host(), get_ftp_port())
    ftp.login(FTP_USER, FTP_PASS)
    return ftp


def _is_excel(name: str) -> bool:
    return name.lower().endswith(_EXCEL_EXTS) and not name.startswith("~$")


def _list_dir(ftp: ftplib.FTP, path: str):
    """MLSD 列出目录，返回 (dirs, files)；files 元素为 (name, size, modify)。"""
    dirs, files = [], []
    try:
        for name, facts in ftp.mlsd(path):
            if name in (".", ".."):
                continue
            if facts.get("type") == "dir":
                dirs.append(name)
            elif facts.get("type") == "file" and _is_excel(name):
                files.append((name, int(facts.get("size") or 0), facts.get("modify") or ""))
    except ftplib.error_perm as e:
        logger.warning(f"[FineBI] MLSD 失败 {path}: {e}")
    return dirs, files


def _find_latest_excel(ftp: ftplib.FTP, report_dir: str, depth: int = 0):
    """在 report_dir 下递归找最新的 Excel，返回 (name, size, modify, full_path) 或 None。

    首层（报告根目录）只下探最新 _MAX_DATE_DIRS 个子目录，其余层全量。
    """
    dirs, files = _list_dir(ftp, report_dir)
    best = None
    for name, size, modify in files:
        cand = (modify, name, size, f"{report_dir}/{name}")
        if best is None or cand > best:
            best = cand
    dirs.sort(reverse=True)
    if depth == 0:
        dirs = dirs[:_MAX_DATE_DIRS]
    for d in dirs:
        sub = _find_latest_excel(ftp, f"{report_dir}/{d}", depth + 1)
        if sub is not None and (best is None or sub > best):
            best = sub
    return best


def _download(ftp: ftplib.FTP, remote_path: str, local: Path) -> Path:
    """下载到临时文件后原子替换；返回最终本地路径。"""
    from backend.services.atomic_write import atomic_replace_file, AtomicReplaceFallback

    local.parent.mkdir(parents=True, exist_ok=True)
    tmp = local.with_suffix(local.suffix + f".{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as f:
            ftp.retrbinary(f"RETR {remote_path}", f.write)
        atomic_replace_file(str(tmp), str(local))
    except AtomicReplaceFallback as e:
        fb = getattr(e, "fallback_path", None)
        if fb and os.path.exists(fb):
            logger.warning(f"[FineBI] 目标被锁，已用备用文件交付: {local} -> {fb}")
            return Path(fb)
        raise
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise
    return local


def _prune_local(report_local_dir: Path, keep: Path) -> None:
    """每个报告文件夹只留最新一份 Excel。"""
    try:
        for f in report_local_dir.iterdir():
            if f.is_file() and _is_excel(f.name) and f != keep:
                try:
                    f.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def _has_local_copy(report: str) -> bool:
    """本机是否已存有该报表的历史副本（用于区分「上游正在重算」与「从没取到过」）。"""
    d = FINEBI_LOCAL_DIR / report
    try:
        return any(_is_excel(f.name) for f in d.iterdir() if f.is_file())
    except OSError:
        return False


def run_finebi_report_sync() -> dict:
    """任务入口：同步 schedule 下每个文件夹的最新 Excel。返回结果摘要。"""
    started = time.time()
    result = {"success": True, "synced": [], "missing": [], "errors": []}
    try:
        ftp = _connect()
    except Exception as e:
        logger.error(f"[FineBI] FTP 连接失败: {e}")
        return {"success": False, "error": f"FTP 连接失败: {e}", "synced": [],
                "missing": [], "errors": [str(e)]}

    try:
        report_dirs, _ = _list_dir(ftp, REMOTE_BASE)
        for report in sorted(report_dirs):
            try:
                best = _find_latest_excel(ftp, f"{REMOTE_BASE}/{report}")
                if best is None:
                    # FineBI 每小时 :53 重算时会先删掉上一轮的 <日期>/<HHMM>/ 目录，新副本约 :02–:05
                    # 才落盘 —— 本轮取不到文件是这个源的常态（incident_overview_sync 曾在 :03 每小时
                    # 误报一次，见该模块说明）。本机已有历史副本时只登记缺失、不判失败：单个目录的
                    # 空档不该把整任务拖红，其余报表其实都同步成功了。本机一份都没有才是真问题。
                    if _has_local_copy(report):
                        result["missing"].append(report)
                        logger.warning(f"[FineBI] {report}: 本轮无 Excel（上游重算窗口），沿用本地副本")
                        continue
                    result["errors"].append(f"{report}: 未找到 Excel，且本机没有历史副本")
                    continue
                modify, name, size, remote_path = best
                local_dir = FINEBI_LOCAL_DIR / report
                local = _download(ftp, remote_path, local_dir / name)
                # 保留远程修改时间，页面展示报表真实产出时间
                try:
                    ts = time.mktime(time.strptime(modify, "%Y%m%d%H%M%S"))
                    os.utime(local, (ts, ts))
                except (ValueError, OSError):
                    pass
                _prune_local(local_dir, local)
                result["synced"].append({
                    "folder": report, "name": local.name, "size": size,
                    "remote": remote_path,
                })
                logger.info(f"[FineBI] {report} -> {local.name} ({size} bytes)")
            except Exception as e:
                logger.error(f"[FineBI] 同步 {report} 失败: {e}")
                result["errors"].append(f"{report}: {e}")
    finally:
        try:
            ftp.quit()
        except Exception:
            pass

    result["success"] = not result["errors"]
    result["elapsed_sec"] = round(time.time() - started, 2)
    return result


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run_finebi_report_sync(), ensure_ascii=False, indent=2))

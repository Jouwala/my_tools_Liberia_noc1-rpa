# -*- coding: utf-8 -*-
"""
Incident Overview 数据同步服务
================================

每小时整点（cron 0 * * * *）从远程 FineBI FTP 拉取最新的 incident_overview.xlsx，
原子替换本地 data/incident_overview/incident_overview.xlsx。

数据源（业务指定）：
  远程目录 /webroot/WEB-INF/schedule/TT_WO/ 下「所有子目录」中，
  修改时间（MDTM）最新的 incident_overview.xlsx 文件。

与 backend/services/ftp_sync.py 使用同一台 FineBI 服务器（192.168.100.19），
仅目录与文件名不同：
  - ftp_sync.py      -> /webroot/WEB-INF/reportlets/excel   (Eflow_TT_FB / Eflow_WO_FB)
  - 本模块           -> /webroot/WEB-INF/schedule/TT_WO     (incident_overview.xlsx)

下载后原子替换本地文件，incident_overview_service 的 mtime 缓存会在下一次请求时
自动失效并重新解析（无需显式清理缓存）。

入口：run_incident_overview_sync()  —— 供 task_registry 以 loader 形式注册。
"""
import ftplib
import os
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("incident_overview_sync")

# ---------------------------------------------------------------------------
# FTP 配置（与 ftp_sync.py 同一台 FineBI 服务器）
# ---------------------------------------------------------------------------
FTP_HOST = "192.168.100.19"
FTP_PORT = 21
FTP_USER = "FINEBI"
FTP_PASS = "DX"
FTP_BASE_DIR = "/webroot/WEB-INF/schedule/TT_WO"
TARGET_FILENAME = "incident_overview.xlsx"

# ---------------------------------------------------------------------------
# 本地落盘路径
# ---------------------------------------------------------------------------
_THIS = Path(__file__).resolve()
BASE_DIR = _THIS.parent.parent.parent
DATA_DIR = BASE_DIR / "data" / "incident_overview"
LOCAL_FILE = DATA_DIR / "incident_overview.xlsx"


# ---------------------------------------------------------------------------
# FTP 连接
# ---------------------------------------------------------------------------
def _connect() -> ftplib.FTP:
    ftp = ftplib.FTP()
    ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
    ftp.login(FTP_USER, FTP_PASS)
    ftp.encoding = "utf-8"
    return ftp


# ---------------------------------------------------------------------------
# 递归遍历，找出最新 incident_overview.xlsx
# ---------------------------------------------------------------------------
def find_latest_incident_overview(ftp: ftplib.FTP):
    """递归遍历 FTP_BASE_DIR 下所有目录，返回最新 incident_overview.xlsx 的元信息。

    返回 {"path", "mtime", "name"} 或 None（未找到）。
    """
    results = []  # list of {"path", "mtime", "name"}

    def walk(current_dir: str):
        try:
            items = []
            ftp.dir(current_dir, items.append)
        except Exception as e:  # noqa: BLE001
            logger.warning("无法列出目录 %s: %s", current_dir, e)
            return

        for line in items:
            parts = line.split()
            if len(parts) < 9:
                continue

            name = parts[-1]
            if name in (".", ".."):
                continue

            full_path = f"{current_dir.rstrip('/')}/{name}"
            # 目录判定：unix 列表以 'd' 开头；部分 FTP 服务器用 'D'
            is_dir = line.startswith("d") or line.startswith("D")

            if is_dir:
                walk(full_path)
            else:
                # 仅匹配 incident_overview.xlsx（大小写不敏感）
                if name.lower() != TARGET_FILENAME.lower():
                    continue
                try:
                    resp = ftp.voidcmd(f"MDTM {full_path}").strip()
                    # MDTM response: "213 YYYYMMDDHHmmss"
                    if resp.startswith("213 "):
                        mtime = datetime.strptime(resp[4:], "%Y%m%d%H%M%S")
                    else:
                        mtime = datetime.min
                except Exception:  # noqa: BLE001
                    try:
                        ftp.size(full_path)
                        mtime = datetime(2000, 1, 1)  # fallback
                    except Exception:  # noqa: BLE001
                        continue
                results.append({"path": full_path, "mtime": mtime, "name": name})

    walk(FTP_BASE_DIR)

    if not results:
        return None
    # 取修改时间最新者
    results.sort(key=lambda r: r["mtime"], reverse=True)
    return results[0]


# ---------------------------------------------------------------------------
# 下载（原子替换）
# ---------------------------------------------------------------------------
def _download_file(ftp: ftplib.FTP, remote_path: str, local_path: Path) -> bool:
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = local_path.with_suffix(".tmp")

        with open(tmp_path, "wb") as f:
            ftp.retrbinary(f"RETR {remote_path}", f.write)

        # 原子替换：先删旧文件再 rename 临时文件
        if local_path.exists():
            local_path.unlink()
        tmp_path.rename(local_path)

        logger.info("下载成功: %s -> %s", remote_path, local_path)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("下载失败: %s: %s", remote_path, e)
        tmp_path = local_path.with_suffix(".tmp")
        if tmp_path.exists():
            tmp_path.unlink()
        return False


# ---------------------------------------------------------------------------
# 任务入口（供 task_runner 注册）
# ---------------------------------------------------------------------------
def run_incident_overview_sync() -> dict:
    """从远程 FTP 拉取最新 incident_overview.xlsx 并替换本地文件。

    返回结构化的执行结果 dict（成功/失败、远程路径、大小、错误列表）。
    """
    result = {
        "success": False,
        "task": "incident_overview_sync",
        "remote_path": None,
        "remote_mtime": None,
        "local_path": str(LOCAL_FILE),
        "size_bytes": 0,
        "downloaded": False,
        "errors": [],
        "timestamp": datetime.now().isoformat(),
    }

    logger.info("开始 Incident Overview FTP 同步 - 连接 %s:%s", FTP_HOST, FTP_PORT)

    try:
        ftp = _connect()
        logger.info("FTP 连接成功: %s", ftp.getwelcome())

        latest = find_latest_incident_overview(ftp)
        if latest is None:
            result["errors"].append(
                f"在 {FTP_BASE_DIR} 及其子目录下未找到 {TARGET_FILENAME}"
            )
            ftp.quit()
            return result

        logger.info(
            "找到最新文件: %s (修改时间: %s)", latest["path"], latest["mtime"]
        )
        if _download_file(ftp, latest["path"], LOCAL_FILE):
            result["downloaded"] = True
            result["success"] = True
            result["remote_path"] = latest["path"]
            result["remote_mtime"] = latest["mtime"].isoformat()
            result["size_bytes"] = LOCAL_FILE.stat().st_size if LOCAL_FILE.exists() else 0
        else:
            result["errors"].append(f"下载失败: {latest['path']}")

        ftp.quit()

    except ftplib.all_errors as e:
        result["errors"].append(f"FTP 错误: {e}")
        logger.error("Incident Overview FTP 同步失败: %s", e)
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"异常: {e}")
        logger.error("Incident Overview 同步异常: %s", e)

    return result


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_incident_overview_sync(), ensure_ascii=False, indent=2))

"""SFTP定时同步服务 - 每小时22分从SFTP下载最新TT文件并更新数据库"""
import os
import re
import stat
import time
import shutil
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("ftp_sync")

# SFTP配置
SFTP_HOST = "10.201.47.62"
SFTP_PORT = 22
SFTP_USER = "ubuntu"
SFTP_PASS = "CloudStudio__123"

# TT 数据：/home/ubuntu/data 下最新文件
TT_REMOTE_DIR = "/home/ubuntu/data"

# 站点列表：/home/ubuntu/reports/SiteList/ 下最新 SiteList.csv
SITE_LIST_REMOTE_DIR = "/home/ubuntu/reports/SiteList"
SITE_LIST_FILENAME = "SiteList.csv"

# 本地配置
DB_DIR = Path(__file__).resolve().parent.parent.parent / "db"
LOCAL_TT = DB_DIR / "Last-month-All-TTs.xlsx"
LOCAL_SITE_LIST = DB_DIR / SITE_LIST_FILENAME

# 文件名匹配模式
TT_PATTERNS = re.compile(r"Last.*TTs?", re.IGNORECASE)


def find_latest_xlsx_on_sftp(sftp, remote_dir: str) -> dict | None:
    """递归遍历SFTP目录，查找最新的TT xlsx文件"""
    latest = None  # {"path": ..., "mtime": ..., "name": ...}

    def walk(path):
        nonlocal latest
        try:
            entries = sftp.listdir_attr(path)
        except IOError as e:
            logger.warning(f"无法列出目录 {path}: {e}")
            return

        for entry in entries:
            full_path = path.rstrip("/") + "/" + entry.filename
            if stat.S_ISDIR(entry.st_mode):
                walk(full_path)
            elif entry.filename.endswith(('.xlsx', '.xls')):
                if TT_PATTERNS.search(entry.filename):
                    mtime = entry.st_mtime
                    if latest is None or mtime > latest["mtime"]:
                        latest = {"path": full_path, "mtime": mtime, "name": entry.filename}

    walk(remote_dir)
    return latest


def find_latest_csv_on_sftp(sftp, remote_dir: str, filename_pattern: str = "") -> dict | None:
    """查找SFTP目录下最新的CSV文件，可按文件名过滤"""
    latest = None

    try:
        entries = sftp.listdir_attr(remote_dir)
    except IOError as e:
        logger.warning(f"无法列出目录 {remote_dir}: {e}")
        return None

    for entry in entries:
        full_path = remote_dir.rstrip("/") + "/" + entry.filename
        if not stat.S_ISDIR(entry.st_mode) and entry.filename.endswith('.csv'):
            if filename_pattern and filename_pattern.lower() not in entry.filename.lower():
                continue
            mtime = entry.st_mtime
            if latest is None or mtime > latest["mtime"]:
                latest = {"path": full_path, "mtime": mtime, "name": entry.filename}

    return latest


def download_file_sftp(sftp, remote_path: str, local_path: Path) -> bool:
    """从SFTP下载文件到本地"""
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = local_path.with_suffix('.tmp')

        sftp.get(remote_path, str(tmp_path))

        # 原子替换
        if local_path.exists():
            local_path.unlink()
        tmp_path.rename(local_path)

        logger.info(f"下载成功: {remote_path} -> {local_path}")
        return True
    except Exception as e:
        logger.error(f"下载失败: {remote_path}: {e}")
        # 清理临时文件
        tmp_path = local_path.with_suffix('.tmp')
        if tmp_path.exists():
            tmp_path.unlink()
        return False


def run_init_db():
    """重新运行init_db.py更新数据库"""
    import subprocess
    import sys

    init_script = Path(__file__).resolve().parent.parent / "scripts" / "init_db.py"
    logger.info(f"重新初始化数据库: {init_script}")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        result = subprocess.run(
            [sys.executable, str(init_script)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(init_script.parent.parent.parent),
            env=env,
            encoding='utf-8',
            errors='replace',
        )
        if result.returncode == 0:
            logger.info("数据库初始化完成")
            return True
        else:
            logger.error(f"数据库初始化失败: {result.stderr[:500]}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("数据库初始化超时")
        return False
    except Exception as e:
        logger.error(f"数据库初始化异常: {e}")
        return False


def sync_from_ftp() -> dict:
    """执行SFTP同步：下载最新TT文件并更新数据库"""
    result = {
        "success": False,
        "downloaded": [],
        "errors": [],
        "db_updated": False,
        "timestamp": datetime.now().isoformat(),
    }

    logger.info(f"开始SFTP同步 - 连接 {SFTP_HOST}:{SFTP_PORT}")

    try:
        import paramiko
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=SFTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)
        logger.info(f"SFTP连接成功")

        try:
            # 1. 查找并下载最新 TT 文件
            tt_file = find_latest_xlsx_on_sftp(sftp, TT_REMOTE_DIR)
            if tt_file is None:
                result["errors"].append(f"SFTP目录 {TT_REMOTE_DIR} 下未找到匹配的TT文件")
            else:
                logger.info(f"发现TT文件: {tt_file['path']} (修改时间戳: {tt_file['mtime']})")
                if download_file_sftp(sftp, tt_file['path'], LOCAL_TT):
                    result["downloaded"].append(f"TT: {tt_file['name']}")

            # 2. 查找并下载最新 SiteList.csv
            site_file = find_latest_csv_on_sftp(sftp, SITE_LIST_REMOTE_DIR, SITE_LIST_FILENAME)
            if site_file is None:
                result["errors"].append(f"SFTP目录 {SITE_LIST_REMOTE_DIR} 下未找到 {SITE_LIST_FILENAME}")
            else:
                logger.info(f"发现SiteList文件: {site_file['path']} (修改时间戳: {site_file['mtime']})")
                if download_file_sftp(sftp, site_file['path'], LOCAL_SITE_LIST):
                    result["downloaded"].append(f"SiteList: {site_file['name']}")

        finally:
            sftp.close()
            transport.close()

        # 重新初始化数据库
        if result["downloaded"]:
            if run_init_db():
                result["db_updated"] = True
                result["success"] = True
            else:
                result["errors"].append("数据库重新初始化失败")
        else:
            result["errors"].append("无文件成功下载")

    except ImportError:
        result["errors"].append("paramiko 未安装，请执行: pip install paramiko")
        logger.error("paramiko 未安装")
    except Exception as e:
        result["errors"].append(f"SFTP同步异常: {e}")
        logger.error(f"SFTP同步失败: {e}")

    return result

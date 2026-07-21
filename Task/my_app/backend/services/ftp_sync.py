"""FTP定时同步服务 - 每小时22分从FTP下载最新TT/WO文件并更新数据库"""
import ftplib
import os
import re
import time
import shutil
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("ftp_sync")

# FTP配置
FTP_HOST = "192.168.100.19"
FTP_PORT = 21
FTP_USER = "FINEBI"
FTP_PASS = "DX"
FTP_BASE_DIR = "/webroot/WEB-INF/reportlets/excel"

# 本地配置
DB_DIR = Path(__file__).resolve().parent.parent.parent / "db"
LOCAL_TT = DB_DIR / "Eflow_TT_FB.xlsx"
LOCAL_WO = DB_DIR / "Eflow_WO_FB.xlsx"

# 文件名匹配模式
TT_PATTERNS = re.compile(r"Eflow_TT_FB", re.IGNORECASE)
WO_PATTERNS = re.compile(r"Eflow_WO_FB", re.IGNORECASE)


def find_latest_files_on_ftp(ftp: ftplib.FTP) -> dict:
    """递归遍历FTP目录，查找最新的TT和WO文件"""
    results = {"tt": None, "wo": None}  # {"path": ..., "mtime": ...}

    def walk_dir(current_dir: str):
        try:
            items = []
            ftp.dir(current_dir, items.append)
        except Exception as e:
            logger.warning(f"无法列出目录 {current_dir}: {e}")
            return

        for line in items:
            parts = line.split()
            if len(parts) < 9:
                continue

            name = parts[-1]
            if name in ('.', '..'):
                continue

            full_path = f"{current_dir.rstrip('/')}/{name}"

            # 判断是否为目录
            is_dir = line.startswith('d') or line.startswith('D')

            if is_dir:
                walk_dir(full_path)
            else:
                # 检查是否匹配TT或WO文件
                if name.endswith(('.xlsx', '.xls')):
                    # 获取文件修改时间
                    try:
                        mdtm_str = ftp.voidcmd(f"MDTM {full_path}").strip()
                        # MDTM response: "213 YYYYMMDDHHmmss"
                        if mdtm_str.startswith("213 "):
                            mdtm = datetime.strptime(mdtm_str[4:], "%Y%m%d%H%M%S")
                        else:
                            mdtm = datetime.min
                    except Exception:
                        # 如果MDTM不可用，使用文件大小作为备选
                        try:
                            size = ftp.size(full_path)
                            mdtm = datetime(2000, 1, 1)  # fallback
                        except Exception:
                            continue

                    if TT_PATTERNS.search(name):
                        if results["tt"] is None or mdtm > results["tt"]["mtime"]:
                            results["tt"] = {"path": full_path, "mtime": mdtm, "name": name}

                    if WO_PATTERNS.search(name):
                        if results["wo"] is None or mdtm > results["wo"]["mtime"]:
                            results["wo"] = {"path": full_path, "mtime": mdtm, "name": name}

    walk_dir(FTP_BASE_DIR)
    return results


def download_file(ftp: ftplib.FTP, remote_path: str, local_path: Path) -> bool:
    """从FTP下载文件到本地"""
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = local_path.with_suffix('.tmp')

        with open(tmp_path, 'wb') as f:
            ftp.retrbinary(f"RETR {remote_path}", f.write)

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

    # 设置UTF-8环境变量避免中文编码问题
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
    """执行FTP同步：下载最新文件并更新数据库"""
    result = {
        "success": False,
        "downloaded": [],
        "errors": [],
        "db_updated": False,
        "timestamp": datetime.now().isoformat(),
    }

    logger.info(f"开始FTP同步 - 连接 {FTP_HOST}:{FTP_PORT}")

    try:
        ftp = ftplib.FTP()
        ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.encoding = "utf-8"
        logger.info(f"FTP连接成功: {ftp.getwelcome()}")

        # 查找最新文件
        files = find_latest_files_on_ftp(ftp)

        if files["tt"] is None and files["wo"] is None:
            result["errors"].append("FTP上未找到Eflow_TT_FB或Eflow_WO_FB文件")
            ftp.quit()
            return result

        # 下载TT文件
        if files["tt"]:
            logger.info(f"发现TT文件: {files['tt']['path']} (修改时间: {files['tt']['mtime']})")
            if download_file(ftp, files["tt"]["path"], LOCAL_TT):
                result["downloaded"].append(f"TT: {files['tt']['name']}")

        # 下载WO文件
        if files["wo"]:
            logger.info(f"发现WO文件: {files['wo']['path']} (修改时间: {files['wo']['mtime']})")
            if download_file(ftp, files["wo"]["path"], LOCAL_WO):
                result["downloaded"].append(f"WO: {files['wo']['name']}")

        ftp.quit()

        # 重新初始化数据库
        if result["downloaded"]:
            if run_init_db():
                result["db_updated"] = True
                result["success"] = True
            else:
                result["errors"].append("数据库重新初始化失败")
        else:
            result["errors"].append("无文件成功下载")

    except ftplib.all_errors as e:
        result["errors"].append(f"FTP错误: {e}")
        logger.error(f"FTP同步失败: {e}")
    except Exception as e:
        result["errors"].append(f"异常: {e}")
        logger.error(f"FTP同步异常: {e}")

    return result

"""SFTP/FTP定时同步服务 - 每小时22分从远程下载最新文件并更新数据库"""
import os
import re
import stat
import json
import time
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("ftp_sync")

# 本地配置路径（持久化，可通过API修改）
DB_DIR = Path(__file__).resolve().parent.parent.parent / "db"
CONFIG_PATH = DB_DIR / "ftp_config.json"

# 默认配置（原始SFTP设置）
DEFAULT_CONFIG = {
    "server": "10.201.47.62",
    "port": 22,
    "username": "ubuntu",
    "password": "CloudStudio__123",
    "protocol": "sftp",
    "tt_remote_dir": "/home/ubuntu/reports/Last-2month-All-TTs",
    "site_list_remote_dir": "/home/ubuntu/reports/SiteList",
    "site_list_filename": "SiteList.csv",
}

# 本地文件
LOCAL_TT = DB_DIR / "Last-month-All-TTs.xlsx"
LOCAL_SITE_LIST = DB_DIR / DEFAULT_CONFIG["site_list_filename"]

# 文件名匹配模式
TT_PATTERNS = re.compile(r"Last.*TTs?", re.IGNORECASE)


def load_config() -> dict:
    """加载配置（优先读文件，不存在则用默认值）"""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            cfg = {**DEFAULT_CONFIG, **saved}
            return cfg
        except Exception as e:
            logger.warning(f"读取配置失败，使用默认值: {e}")
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> bool:
    """保存配置到文件"""
    try:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        return False


# ========== SFTP 相关函数 ==========

def find_latest_xlsx_on_sftp(sftp, remote_dir: str) -> dict | None:
    """递归遍历SFTP目录，查找最新的TT xlsx文件"""
    latest = None

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
    """递归遍历SFTP目录，查找最新的CSV文件（可按文件名过滤）"""
    latest = None

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
            elif entry.filename.endswith('.csv'):
                if filename_pattern and filename_pattern.lower() not in entry.filename.lower():
                    continue
                mtime = entry.st_mtime
                if latest is None or mtime > latest["mtime"]:
                    latest = {"path": full_path, "mtime": mtime, "name": entry.filename}

    walk(remote_dir)
    return latest


def download_file_sftp(sftp, remote_path: str, local_path: Path) -> bool:
    """从SFTP下载文件到本地"""
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = local_path.with_suffix('.tmp')
        sftp.get(remote_path, str(tmp_path))
        if local_path.exists():
            local_path.unlink()
        tmp_path.rename(local_path)
        logger.info(f"下载成功: {remote_path} -> {local_path}")
        return True
    except Exception as e:
        logger.error(f"下载失败: {remote_path}: {e}")
        tmp_path = local_path.with_suffix('.tmp')
        if tmp_path.exists():
            tmp_path.unlink()
        return False


# ========== FTP 相关函数 ==========

def find_latest_xlsx_on_ftp(ftp, remote_dir: str) -> str | None:
    """在FTP目录中查找最新的xlsx文件"""
    latest_name = None
    latest_time = None
    try:
        files = []
        ftp.retrlines(f"LIST {remote_dir}", files.append)
    except Exception as e:
        logger.warning(f"无法列出目录 {remote_dir}: {e}")
        return None
    for line in files:
        parts = line.split()
        if len(parts) < 9:
            continue
        filename = parts[-1]
        if not filename.lower().endswith(('.xlsx', '.xls')):
            continue
        try:
            time_str = f"{parts[0]} {parts[1]}"
            file_time = None
            for fmt in ["%m-%d-%y %I:%M%p", "%m-%d-%Y %H:%M", "%Y-%m-%d %H:%M"]:
                try:
                    file_time = datetime.strptime(time_str, fmt)
                    break
                except ValueError:
                    continue
            if file_time is None:
                file_time = datetime.now()
        except Exception:
            file_time = datetime.now()
        if latest_time is None or file_time > latest_time:
            latest_time = file_time
            latest_name = filename
    return latest_name


def download_file_ftp(ftp, remote_dir: str, filename: str, local_path: Path) -> bool:
    """从FTP下载文件到本地"""
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = local_path.with_suffix('.tmp')
        remote_path = f"{remote_dir}/{filename}"
        with open(tmp_path, 'wb') as f:
            ftp.retrbinary(f"RETR {remote_path}", f.write)
        if local_path.exists():
            local_path.unlink()
        tmp_path.rename(local_path)
        logger.info(f"下载成功: {remote_path} -> {local_path}")
        return True
    except Exception as e:
        logger.error(f"下载失败: {remote_dir}/{filename}: {e}")
        tmp_path = local_path.with_suffix('.tmp')
        if tmp_path.exists():
            tmp_path.unlink()
        return False


# ========== 公共函数 ==========

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
            # 清除schema缓存，让下次请求重新检测数据库结构
            try:
                from backend.routers.tt_wo_dashboard import clear_schema_cache
                clear_schema_cache()
            except Exception:
                pass
            try:
                from backend.routers.gis import _gis_schema_cache
                import backend.routers.gis as gis_mod
                gis_mod._gis_schema_cache = None
            except Exception:
                pass
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


def _sync_sftp(cfg: dict) -> dict:
    """SFTP同步逻辑"""
    result = {
        "success": False,
        "downloaded": 0,
        "errors": [],
        "db_updated": False,
        "elapsed": 0,
        "timestamp": datetime.now().isoformat(),
    }
    start_time = time.time()

    server = cfg["server"]
    port = int(cfg.get("port", 22))
    username = cfg["username"]
    password = cfg.get("password", "")
    tt_remote_dir = cfg.get("tt_remote_dir", "/home/ubuntu/data")
    site_list_remote_dir = cfg.get("site_list_remote_dir", "/home/ubuntu/reports/SiteList")
    site_list_filename = cfg.get("site_list_filename", "SiteList.csv")
    local_site_list = DB_DIR / site_list_filename

    logger.info(f"开始SFTP同步 - 连接 {server}:{port}")

    try:
        import paramiko
        # ⚠ 超时是必需项（2026-10-04 网络风暴专项整改）。
        # paramiko 的 Transport((host, port)) 与 connect() **默认都没有超时**：
        # 上游 SFTP 一旦半死不活（TCP 建连成功但不出 banner），本进程会**永久挂起**，
        # 不报错、不退出，并一直占着连接。若被巡检/看门狗重跑，就会每 5 分钟
        # 叠加一个挂起进程 —— 这是"请求量放大"里最难排查的一类。
        # 写法照搬 my_app 已修复的同类问题：
        # Task/my_app/backend/services/sp_report_gen/gernarate_sp_report.py:476-490
        import socket as _socket
        
        _sock = _socket.create_connection((server, port), timeout=30)
        transport = paramiko.Transport(_sock)
        transport.set_keepalive(30)
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            _chan = sftp.get_channel()
            if _chan is not None:
                _chan.settimeout(180)  # 服务端应用层挂死时，channel 读不再永久阻塞
        except Exception as _e:
            print(f"  [WARN] SFTP channel 超时设置失败（退回无超时模式）: {_e}")
        logger.info("SFTP连接成功")

        try:
            # 1. 查找并下载最新 TT 文件
            tt_file = find_latest_xlsx_on_sftp(sftp, tt_remote_dir)
            if tt_file is None:
                result["errors"].append(f"SFTP目录 {tt_remote_dir} 下未找到匹配的TT文件")
            else:
                logger.info(f"发现TT文件: {tt_file['path']}")
                if download_file_sftp(sftp, tt_file['path'], LOCAL_TT):
                    result["downloaded"] += 1

            # 2. 查找并下载最新 SiteList.csv
            site_file = find_latest_csv_on_sftp(sftp, site_list_remote_dir, site_list_filename)
            if site_file is None:
                result["errors"].append(f"SFTP目录 {site_list_remote_dir} 下未找到 {site_list_filename}")
            else:
                logger.info(f"发现SiteList文件: {site_file['path']}")
                if download_file_sftp(sftp, site_file['path'], local_site_list):
                    result["downloaded"] += 1
        finally:
            sftp.close()
            transport.close()

        # 重新初始化数据库
        if result["downloaded"] > 0:
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

    result["elapsed"] = round(time.time() - start_time, 2)
    return result


def _sync_ftp(cfg: dict) -> dict:
    """FTP同步逻辑"""
    result = {
        "success": False,
        "downloaded": 0,
        "errors": [],
        "db_updated": False,
        "elapsed": 0,
        "timestamp": datetime.now().isoformat(),
    }
    start_time = time.time()

    server = cfg["server"]
    port = int(cfg.get("port", 21))
    username = cfg["username"]
    password = cfg.get("password", "")
    tt_remote_dir = cfg.get("tt_remote_dir", "")

    logger.info(f"开始FTP同步 - 连接 {server}:{port}")

    ftp = None
    try:
        import ftplib
        ftp = ftplib.FTP()
        ftp.connect(server, port, timeout=30)
        ftp.login(username, password)
        ftp.encoding = 'utf-8'
        logger.info("FTP连接成功")

        # 查找并下载最新 TT xlsx
        latest_file = find_latest_xlsx_on_ftp(ftp, tt_remote_dir)
        if not latest_file:
            result["errors"].append(f"FTP目录 {tt_remote_dir} 下未找到xlsx文件")
        else:
            logger.info(f"发现文件: {tt_remote_dir}/{latest_file}")
            if download_file_ftp(ftp, tt_remote_dir, latest_file, LOCAL_TT):
                result["downloaded"] += 1

        # 下载完成后重新初始化数据库
        if result["downloaded"] > 0:
            if run_init_db():
                result["db_updated"] = True
                result["success"] = True
            else:
                result["errors"].append("数据库重新初始化失败")
        else:
            result["errors"].append("未下载到任何文件")

    except Exception as e:
        result["errors"].append(f"FTP同步异常: {e}")
        logger.error(f"FTP同步失败: {e}")
    finally:
        if ftp:
            try:
                ftp.quit()
            except Exception:
                pass

    result["elapsed"] = round(time.time() - start_time, 2)
    return result


def sync_from_ftp() -> dict:
    """执行同步：根据配置选择SFTP或FTP"""
    cfg = load_config()
    protocol = cfg.get("protocol", "sftp").lower()

    if protocol == "ftp":
        return _sync_ftp(cfg)
    else:
        return _sync_sftp(cfg)

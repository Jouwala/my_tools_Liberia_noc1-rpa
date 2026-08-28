# -*- coding: utf-8 -*-
"""
统一的远程主机配置
==================

FTP / API / SMB 全部指向同一台远程服务器（默认 192.168.100.19），仅路径/端口不同。
此前该地址散落在 15+ 个文件里硬编码，改 IP 要逐个改、还容易漏。

本模块将其收敛为单一来源：
- 读取（每次调用实时读取，修改后下一次连接即生效，无需重启进程）：
    1. 环境变量 MY_APP_REMOTE_HOST  （部署级覆盖，优先级最高；设置后页面值不生效）
    2. backend/data/settings.json 的 remote_host 字段（页面写入，默认来源）
    3. 硬编码默认值 192.168.100.19
- 写入：set_remote_host() 原子写 settings.json（供「系统设置 → 远程主机」页面调用）。

各业务模块应 import 本模块的 getter 后在连接/拼 URL 时调用，
切勿再 import 模块级常量（那样会在 import 时固化、失去热更新能力）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_REMOTE_HOST = "192.168.100.19"
DEFAULT_API_PORT = 8765
DEFAULT_FTP_PORT = 21

# backend/data/settings.json（与 backend/ 同级 data 目录）
_SETTINGS_FILE = Path(__file__).resolve().parent.parent / "data" / "settings.json"


def _load_raw() -> str:
    """按优先级解析当前生效的远程主机。"""
    env = os.environ.get("MY_APP_REMOTE_HOST", "").strip()
    if env:
        return env
    try:
        if _SETTINGS_FILE.is_file():
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            host = (data.get("remote_host") or "").strip()
            if host:
                return host
    except Exception:
        # 文件损坏/锁住时不致命，回退默认，避免同步链路整体崩
        pass
    return DEFAULT_REMOTE_HOST


def get_remote_host() -> str:
    """远程主机地址（FTP / API / SMB 共用同一台机器）。"""
    return _load_raw()


# ---- 语义化便捷别名（返回同一地址，便于调用处表意清晰）----
def get_ftp_host() -> str:
    return get_remote_host()


def get_api_host() -> str:
    return get_remote_host()


def get_smb_host() -> str:
    return get_remote_host()


def get_api_port() -> int:
    return int(os.environ.get("DB_WRITER_PORT", str(DEFAULT_API_PORT)))


def get_ftp_port() -> int:
    return int(os.environ.get("FTP_PORT", str(DEFAULT_FTP_PORT)))


def get_api_base_url(port: int | None = None) -> str:
    """远程写入 API 基址，如 http://192.168.100.19:8765。"""
    return f"http://{get_api_host()}:{port or get_api_port()}"


def set_remote_host(host: str) -> str:
    """持久化远程主机到 settings.json（页面写入）。返回生效后的 host。"""
    host = (host or "").strip()
    if not host:
        raise ValueError("remote_host 不能为空")
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if _SETTINGS_FILE.is_file():
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data["remote_host"] = host
    tmp = _SETTINGS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _SETTINGS_FILE)  # 原子替换，避免并发读/写损坏
    return host

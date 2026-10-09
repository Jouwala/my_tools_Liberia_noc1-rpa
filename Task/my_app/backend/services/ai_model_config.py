# -*- coding: utf-8 -*-
"""AI 模型配置服务

运行时配置持久化到 `backend/services/ai_model_config.json`，页面 GET/PUT 即时生效。

openwebui_client.py 在每次 analyze_tt() 入口读取最新值（而非模块导入时），
所以改配置无需重启后端。

Schema
------
provider:         "local" | "openwebui" | "both"   主用方
  local → 只用 WorkBuddy 本地代理
  openwebui → 只用 Open WebUI（需配置邮箱密码）
  both → WorkBuddy 主用，Open WebUI 备用

local_enabled:    bool      是否启用本地代理（both 模式时控制是否加入调用链）
local_model:       str       本地模型 ID
local_base_url:    str       本地代理地址
openwebui_model:   str       Open WebUI 模型（支持 auto / auto:pattern）
openwebui_base_url: str       Open WebUI 地址
openwebui_email:   str       Open WebUI 登录邮箱
openwebui_password: str       Open WebUI 登录密码
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

# ------------------------------------------------------------------ #
# 路径
# ------------------------------------------------------------------ #
_SCRIPT_DIR = Path(__file__).resolve().parent
_CONFIG_FILE = _SCRIPT_DIR / "ai_model_config.json"

# ------------------------------------------------------------------ #
# 默认值（与 backend/.env 同值）
# ------------------------------------------------------------------ #
_DEFAULTS: dict[str, Any] = {
    "provider": "both",
    "local_enabled": True,
    "local_model": "deepseek-v4.1-flash",
    "local_base_url": "http://127.0.0.1:8788/v1",
    "openwebui_model": "agnes-2.5-flash",
    "openwebui_base_url": "http://192.168.100.27:3000",
    "openwebui_email": "",
    "openwebui_password": "",
}


# ------------------------------------------------------------------ #
# 持久化（JSON 文件）
# ------------------------------------------------------------------ #
_lock = threading.Lock()
_cached: dict | None = None


def _load_from_file() -> dict:
    try:
        if _CONFIG_FILE.is_file():
            with open(_CONFIG_FILE, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_to_file(cfg: dict) -> None:
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(_CONFIG_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(_CONFIG_FILE))


# ------------------------------------------------------------------ #
# 主接口
# ------------------------------------------------------------------ #
def get_config(force_refresh: bool = False) -> dict:
    """返回当前生效配置（文件 > 默认）。线程安全。"""
    global _cached
    if not force_refresh and _cached is not None:
        return dict(_cached)
    file_cfg = _load_from_file()
    with _lock:
        if file_cfg:
            _cached = {**_DEFAULTS, **file_cfg}
        elif _cached is None:
            _cached = dict(_DEFAULTS)
    return dict(_cached)


def update_config(patch: dict) -> dict:
    """更新配置：合并 patch → 写文件 → 返回新配置。"""
    global _cached
    new_cfg: dict
    with _lock:
        current = get_config()
        new_cfg = {**current, **patch}
        _cached = new_cfg
    _save_to_file(new_cfg)
    return dict(new_cfg)


def get_effective() -> dict:
    """返回前端需要的「当前生效配置 + 各字段说明」。"""
    cfg = get_config()
    return {
        "config": cfg,
        "defaults": _DEFAULTS,
        "schema": {
            "provider": {
                "type": "enum",
                "options": ["local", "openwebui", "both"],
                "desc_zh": "主用模型方",
                "desc_en": "Primary model provider",
            },
            "local_enabled": {
                "type": "bool",
                "desc_zh": "启用本地 WorkBuddy 代理",
                "desc_en": "Enable local WorkBuddy proxy",
            },
            "local_model": {
                "type": "str",
                "desc_zh": "本地模型 ID",
                "desc_en": "Local model ID",
            },
            "local_base_url": {
                "type": "str",
                "desc_zh": "本地代理地址",
                "desc_en": "Local proxy base URL",
            },
            "openwebui_model": {
                "type": "str",
                "desc_zh": "Open WebUI 模型（支持 auto / auto:pattern 自动选）",
                "desc_en": "Open WebUI model (supports auto / auto:pattern)",
            },
            "openwebui_base_url": {
                "type": "str",
                "desc_zh": "Open WebUI 地址",
                "desc_en": "Open WebUI base URL",
            },
            "openwebui_email": {
                "type": "str",
                "desc_zh": "Open WebUI 登录邮箱",
                "desc_en": "Open WebUI email",
            },
            "openwebui_password": {
                "type": "str",
                "desc_zh": "Open WebUI 登录密码",
                "desc_en": "Open WebUI password",
            },
        },
    }

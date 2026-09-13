# -*- coding: utf-8 -*-
"""auth_switch.py - 共享鉴权总开关（my_app 侧）
=============================================================

目标：日常开发时一条命令就能让 ``/uniplam/`` 与 ``/myapp/`` 都跳过用户登录，
且两个应用读的是**同一个开关**，不会出现「门户免登录、myapp 还要求登录」的错配。

真相源优先级（高 → 低）：

1. 环境变量 ``AUTH_ENABLED``（1/true/on/yes = 开启鉴权；0/false/off/no = 关闭鉴权）
2. 共享开关文件 ``<仓库根>/auth-switch.json`` 的 ``authEnabled`` 字段
3. 缺省 = True（保持原有行为，安全默认）

生产保护：当 ``AUTH_SWITCH_ENV`` / ``NODE_ENV`` / ``APP_ENV`` 任一为 production/prod
时，即使配了关闭也会被强制回「开启鉴权」并打印醒目告警。

与门户侧 ``liberia-noc_soc-数据看板统一门户/server/authSwitch.ts`` 保持**完全一致的
语义**，改一处请同步另一处。

热生效：结论带 TTL 缓存（3 秒），在门户页面上点开关后无需重启进程，本进程最迟
数秒内自动跟上。写入方是门户接口（``POST /api/auth/switch``），本模块只读。

安全边界：本模块只读 ``auth-switch.json``，**绝不触碰** ``auth-data/`` 或数据库中的
用户、申请与登录会话。
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 显式读取 backend/.env，保证本模块在 dotenv 之前被 import 时也能看到 AUTH_ENABLED。
# 顺序与 backend/database.py 保持一致：backend/.env 优先，缺失时回退项目根 .env；
# override=False 保证 OS 环境变量优先。
try:
    from dotenv import load_dotenv

    for _env_file in (
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ):
        if _env_file.is_file():
            load_dotenv(_env_file, override=False)
except Exception:  # noqa: BLE001
    logger.debug("load_dotenv 不可用，已跳过（不影响鉴权开关默认值）")

_TRUTHY = {"1", "true", "yes", "on", "y", "t"}
_FALSY = {"0", "false", "no", "off", "n", "f"}
_PROD_ENVS = {"production", "prod"}


def _default_flag_file() -> Path:
    """共享开关文件默认位置：<仓库根>/auth-switch.json。

    本文件位于 ``<仓库根>/Task/my_app/backend/auth_switch.py``，
    故 parents[3] 即仓库根（D:/01_RPA）。
    """
    from_env = (os.environ.get("AUTH_SWITCH_FILE") or "").strip()
    if from_env:
        return Path(from_env).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "auth-switch.json"


def _parse_bool(raw: Optional[str]) -> Optional[bool]:
    """解析布尔配置；无法识别时返回 None（交给下一优先级）。"""
    value = str(raw or "").strip().lower()
    if not value:
        return None
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    return None


def _current_env() -> str:
    raw = (
        os.environ.get("AUTH_SWITCH_ENV")
        or os.environ.get("NODE_ENV")
        or os.environ.get("APP_ENV")
        or ""
    )
    return str(raw).strip().lower() or "development"


def _read_flag_file(flag_file: Path) -> Optional[bool]:
    """读共享开关文件；不存在/损坏时返回 None（按缺省处理，不抛错打断启动）。"""
    try:
        if not flag_file.is_file():
            return None
        parsed: Any = json.loads(flag_file.read_text(encoding="utf-8"))
        value = parsed.get("authEnabled") if isinstance(parsed, dict) else None
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return _parse_bool(value)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[auth-switch] 开关文件解析失败，按「开启鉴权」处理: %s (%s)", flag_file, exc)
        return None


_state: Optional[dict] = None
_state_at: float = 0.0
_last_logged: Optional[str] = None

# 结论缓存时长（秒）：门户页面点开关后，myapp 最迟这么久跟上，无需重启进程。
# 必须与门户侧 server/authSwitch.ts 的 RELOAD_TTL_MS 保持一致。
_RELOAD_TTL = 3.0


def get_auth_switch() -> dict:
    """解析当前鉴权开关状态（带 TTL 缓存，切换后最迟 _RELOAD_TTL 秒生效）。"""
    global _state, _state_at, _last_logged
    now = time.monotonic()
    if _state is not None and (now - _state_at) < _RELOAD_TTL:
        return _state

    flag_file = _default_flag_file()
    env = _current_env()

    from_env = _parse_bool(os.environ.get("AUTH_ENABLED"))
    if from_env is not None:
        auth_enabled, source = from_env, "env"
    else:
        from_file = _read_flag_file(flag_file)
        if from_file is not None:
            auth_enabled, source = from_file, "file"
        else:
            auth_enabled, source = True, "default"

    reason: Optional[str] = None
    if not auth_enabled and env in _PROD_ENVS:
        auth_enabled, source = True, "guard"
        reason = f"运行环境为 {env}，已忽略「关闭鉴权」配置并强制开启"

    _state = {
        "authEnabled": auth_enabled,
        "mode": "enforced" if auth_enabled else "bypass",
        "source": source,
        "flagFile": str(flag_file),
        "env": env,
        "reason": reason,
        "envOverride": from_env is not None,
    }
    _state_at = now

    # 结论变化时才打日志（正常请求不再刷屏）
    fingerprint = f"{auth_enabled}|{env}|{source}"
    if fingerprint != _last_logged:
        _last_logged = fingerprint
        logger.warning(
            "[auth-switch] 鉴权%s | 环境=%s 来源=%s 开关文件=%s",
            "已开启" if auth_enabled else "已关闭(免登录)",
            env,
            source,
            flag_file,
        )
        if not auth_enabled:
            logger.warning("[auth-switch] 注意：当前 /uniplam/ 与 /myapp/ 均跳过用户登录，仅限日常开发使用。")
        if reason:
            logger.error("[auth-switch] 严重告警：%s。请检查 AUTH_ENABLED / %s", reason, flag_file)
    return _state


def is_auth_bypass() -> bool:
    """当前是否跳过用户登录（仅日常开发为 True）。"""
    return not get_auth_switch()["authEnabled"]


def reset_auth_switch_cache() -> None:
    """清缓存（仅测试/热重载使用）。"""
    global _state, _state_at, _last_logged
    _state = None
    _state_at = 0.0
    _last_logged = None


"""跨子系统的凭据读取入口（供 my_app 之外的脚本使用）。

## 为什么需要这个模块

`credential_store` 住在 `Task/my_app/backend/services/` 里，**只有 my_app 的
代码能直接 import 它**。而工作区里还有几十个独立 RPA 脚本（`Task/sp/`、
`ticket_export_rpa/`、`WareHouseDashBoard/` 等），它们历史上各自把口令写成
字面量常量：

    PASSWORD = "Bry****"          # ← 入库、多副本、无法轮换

口径统一后，这些脚本都改成调本模块。**不要让每个脚本各自写一遍
`sys.path.insert(...)` + try/except fallback** —— 那等于把一份引导逻辑复制
几十遍，又是新的重复真相源（AGENTS.md 三.7：抽象延迟到第二个真实用例
出现时引入；这里已经有几十个用例了）。

## 用法

    from shared.credentials import get_credential

    USERNAME = "admin"                      # 用户名不算敏感，可以留字面量
    PASSWORD = get_credential("eflow", env="EFLOW_PASS")   # 口令不写字面量

    # 取到的是当前生效值；两组都取不到时返回空串，
    # 让登录**明确失败**，而不是静默拿旧口令去认证。

## 取值优先级（与 my_app 内一致）

    环境变量  >  credentials 表（「设置 → 凭据管理」页面）  >  ""

本模块**没有**第 3 级代码默认值 —— 那正是 2026-10-04 清理掉的东西。

## sys.path 引导

调用方可能从任意工作目录运行（计划任务、双击、别的脚本 import）。
本模块自己负责找到 `Task/my_app` 并挂到 `sys.path` 上，调用方无需关心。
查找策略：从本文件向上逐级找含 `Task/my_app/backend/services/credential_store.py`
的目录；找不到时再退回从 `cwd` 找。这样无论仓库被克隆到哪里都能工作。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = ["get_credential", "store_available"]

# 本次查找的结果缓存，避免每次调用都遍历目录树
_CACHED_MY_APP: Path | None = None
_CACHED_STORE = None


def _find_my_app() -> Path | None:
    """定位 `Task/my_app`（`credential_store` 所在项目的根）。

    先按本文件位置向上找，再从 cwd 向上找 —— 后者覆盖"脚本被复制到
    别处、但工作目录仍在仓库内"的情况。
    """
    global _CACHED_MY_APP
    if _CACHED_MY_APP is not None:
        return _CACHED_MY_APP

    marker = Path("backend") / "services" / "credential_store.py"
    roots = [Path(__file__).resolve().parent] + [Path.cwd().resolve()]
    for start in roots:
        for parent in [start, *start.parents]:
            # 情况一：parent 本身就是 my_app
            if (parent / marker).is_file():
                _CACHED_MY_APP = parent
                return parent
            # 情况二：parent 是 Task/，my_app 在其下
            cand = parent / "Task" / "my_app"
            if (cand / marker).is_file():
                _CACHED_MY_APP = cand
                return cand
    return None


def _load_store():
    """import credential_store，成功返回 callable，失败返回 None。

    刻意**不抛异常**：凭据库不可用不应让脚本直接崩溃，而是退回到
    环境变量 / 空口令，让调用方的登录逻辑给出明确错误。
    """
    global _CACHED_STORE
    if _CACHED_STORE is not None:
        return _CACHED_STORE

    my_app = _find_my_app()
    if my_app is None:
        _CACHED_STORE = False
        return None

    p = str(my_app)
    if p not in sys.path:
        sys.path.insert(0, p)
    try:
        from backend.services.credential_store import get_credential as _gc
    except Exception:  # noqa: BLE001  凭据库不可用时降级，不让脚本崩
        _CACHED_STORE = False
        return None
    _CACHED_STORE = _gc
    return _gc


def get_credential(key: str, env: str | None = None, default: str = "") -> str:
    """取当前生效的口令。优先级：环境变量 `env` > 凭据库 `key` 组 > `default`。

    Args:
        key: 凭据组 key（见 credential_store 的 CREDENTIAL_GROUPS）
        env: 可选的环境变量名，优先级最高（便于临时覆盖/调试）
        default: 最后兜底，**默认空串**。除非确知理由，不要传真实口令 ——
            那正是本次清理要消除的写法。

    Returns:
        口令字符串；取不到时返回 `default`（默认空串）。
    """
    if env:
        v = os.environ.get(env)
        if v:
            return v

    gc = _load_store()
    if gc is not None:
        try:
            _user, secret = gc(key)
            if secret:
                return secret
        except Exception:  # noqa: BLE001
            pass
    return default


def store_available() -> bool:
    """凭据库是否可用（供脚本启动时打印诊断信息）。"""
    return _load_store() is not None

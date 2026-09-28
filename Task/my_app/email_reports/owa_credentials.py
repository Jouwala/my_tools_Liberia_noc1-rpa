# -*- coding: utf-8 -*-
"""OWA/EWS 凭据解析的**唯一入口**。

优先级：环境变量(``OWA_USERNAME``/``OWA_PASSWORD``) > 数据库（设置页 credential_store）
> 代码默认值。

## 为什么必须集中在一处
2026-09-18 那次 65 小时邮件全故障，根因就是**同一个密码在代码里有多个来源**：

  * 探测路径 ``owa_mail_report.get_account()`` → 读 credential_store → 一切正常
  * 发送路径 ``ews_send_enhanced`` → 用模块常量 ``OWA_PASSWORD``（硬编码旧密码）→ 401

于是出现"探测说服务正常、发送照样 401"的诡异现象，而且日志里的
``RateLimitError: Max timeout reached`` 看着像服务端限流，把排查方向彻底带偏。

此后所有发信模块都必须经本模块取凭据，**不得**再出现
``password: str = "<字面量>"`` 这类参数默认值 —— 那种写法会在「设置」页改完密码后
继续拿旧值去认证，而且完全不会被察觉。

## 用法
    from owa_credentials import resolve_owa_credentials
    user, pwd = resolve_owa_credentials(username, password)   # 传进来的旧默认值会被忽略
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 代码默认值：仅作最后兜底。正常运行时应由 credential_store（设置页）提供真实凭据。
#
# ⚠ 2026-09-27 说明：全仓库硬编码口令清理后，这里是**唯一**保留明文默认口令的地方，
#   属刻意设计，不是漏网：
#     1) 它是"三级优先级的最后一跳"（env > credential_store > 这里），删掉会让
#        credential_store 不可用时直接认证失败，反而更难诊断；
#     2) _LEGACY_DEFAULTS 依赖它的**值**来识别"调用方传了历史硬编码旧口令"，
#        从而把这种传值当作"没传"。改这个值会同时改变那套识别逻辑。
#   真要彻底消除明文，正确做法是让 credential_store 成为唯一来源并删掉第 3 级，
#   而不是单独改这一行。
DEFAULT_USERNAME = "ZTENOC_OLR"
DEFAULT_PASSWORD = "Postcode@202608"

# 历史上出现过的硬编码默认值。调用方若"显式"传了这些值，等同于没传 ——
# 它们一定不是设置页里的当前密码。
_LEGACY_DEFAULTS = frozenset({DEFAULT_PASSWORD})

# 用户名同理：DEFAULT_USERNAME 就是兜底值，显式传它 ≡ 没传。
_UNSPECIFIED_USERS = frozenset({DEFAULT_USERNAME})

_MY_APP = Path(__file__).resolve().parent.parent


def _ensure_importable() -> None:
    p = str(_MY_APP)
    if p not in sys.path:
        sys.path.insert(0, p)


def store_credentials() -> tuple[str, str]:
    """只读 credential_store（不回退到代码默认值），返回 (user, password)。

    读不到时返回 ``("", "")``，便于调用方区分"库里有值"和"库里没有"。
    """
    _ensure_importable()
    try:
        from backend.services.credential_store import get_credential
        user, pwd = get_credential(
            "owa_mail", "", "",
            env_user="OWA_USERNAME", env_secret="OWA_PASSWORD",
        )
        return (user or ""), (pwd or "")
    except Exception:  # noqa: BLE001
        return os.getenv("OWA_USERNAME", ""), os.getenv("OWA_PASSWORD", "")


def resolve_owa_credentials(username: str | None = None,
                            password: str | None = None) -> tuple[str, str]:
    """返回当前生效的 ``(username, password)``。

    ``username``/``password`` 为 None / 空串 / 已知的旧硬编码默认值时，一律视为
    "调用方没指定"，改由 credential_store 解析；否则尊重调用方的显式传值。
    """
    user, pwd = store_credentials()
    if not username or username in _UNSPECIFIED_USERS:
        username = user or DEFAULT_USERNAME
    if not password or password in _LEGACY_DEFAULTS:
        password = pwd or DEFAULT_PASSWORD
    return username, password

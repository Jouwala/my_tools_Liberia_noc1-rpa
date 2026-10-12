# -*- coding: utf-8 -*-
"""登录失败原因透传 + 账号锁定不重试的回归测试。

背景（2026-10-12）：`ran_ume_daily` 每天 04:35 跑，当天 05:45 告警失败，
错误信息只有一句笼统的「登录失败 - 未获取到 Z-AUTH-CODE cookie」。
人工登服务器复现才发现上游真实返回的是：

    HTTP/1.1 401 Unauthorized
    {"detail":{"code":"4","message":"User has been locked"}}

即**账号被锁定**，而不是密码到期 —— 两者处置方式完全不同
（锁定要找管理员解锁；到期要改密码）。原实现只看「有没有 Z-AUTH-CODE
cookie」，把服务端明确给出的原因整个丢掉了，导致排查方向被误导。

同时，锁定属于**永久性错误**，但 auto_retry 的 NON_RETRYABLE_KEYS 里
没有对应关键字，于是每 10 分钟无谓重投一次、每次都失败并触发告警。

本组测试盯两件事：
  1. `_describe_login_failure` 能把上游真实原因透传出来，并给出可操作建议；
  2. auto_retry 把「账号锁定」判为永久性错误，且不误伤原有判定。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import auth_manager as am  # noqa: E402
from backend.services import auto_retry as ar  # noqa: E402


def _body(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------- 1) 错误透传

def test_locked_account_reason_is_surfaced():
    """账号被锁：必须透出上游原文，并提示这是锁定而非密码到期。"""
    msg = am._describe_login_failure(
        "HTTP/1.1 401 Unauthorized",
        _body({"result": "1", "detail": {"code": "4", "message": "User has been locked"}}),
    )
    assert "User has been locked" in msg        # 上游原文
    assert "code=4" in msg                       # 错误码
    assert "401" in msg                          # HTTP 状态
    assert "锁定" in msg                          # 中文结论
    assert "解锁" in msg                          # 可操作建议
    # 2026-10-12 的核心教训：锁定时不能用这次登录判断密码是否到期
    assert "密码" in msg


def test_locked_message_does_not_duplicate_http_prefix():
    """status 本身已含 'HTTP'，不应拼出 'HTTP HTTP/1.1'。"""
    msg = am._describe_login_failure(
        "HTTP/1.1 401 Unauthorized",
        _body({"detail": {"code": "4", "message": "User has been locked"}}),
    )
    assert "HTTP HTTP" not in msg
    assert "HTTP/1.1 401 Unauthorized" not in msg


def test_password_expiry_reason_is_surfaced():
    """密码到期：应提示改密码并同步 credential_store。"""
    msg = am._describe_login_failure(
        "HTTP/1.1 401 Unauthorized",
        _body({"detail": {"code": "5", "message": "Password has expired"}}),
    )
    assert "Password has expired" in msg
    assert "密码已到期" in msg
    assert "credential_store" in msg


def test_wrong_password_reason_is_surfaced():
    """密码错误：应提示核对凭据，而不是误导为锁定。"""
    msg = am._describe_login_failure(
        "HTTP/1.1 401 Unauthorized",
        _body({"detail": {"code": "2", "message": "Invalid username or password"}}),
    )
    assert "Invalid username or password" in msg
    assert "用户名或密码错误" in msg
    assert "锁定" not in msg


def test_disabled_account_reason_is_surfaced():
    msg = am._describe_login_failure(
        "HTTP/1.1 403 Forbidden",
        _body({"detail": {"code": "9", "message": "User disabled"}}),
    )
    assert "User disabled" in msg
    assert "禁用" in msg


def test_non_json_body_falls_back_to_raw_text():
    """上游返回非 JSON 时不能抛异常，退化为原文截断。"""
    msg = am._describe_login_failure("HTTP/1.1 502 Bad Gateway", b"<html>gateway error</html>")
    assert "gateway error" in msg
    assert "502" in msg


def test_empty_body_still_returns_usable_message():
    msg = am._describe_login_failure("HTTP/1.1 500 Server Error", b"")
    assert "未获取到 Z-AUTH-CODE cookie" in msg
    assert "500" in msg


def test_original_message_shape_is_preserved():
    """保持原有前缀，避免依赖该字符串做关键词匹配的既有代码被打破。"""
    msg = am._describe_login_failure("HTTP/1.1 401 Unauthorized", b"")
    assert msg.startswith("登录失败 - 未获取到 Z-AUTH-CODE cookie")


# ------------------------------------------------- 2) 锁定属永久性错误，不重试

LOCKED_ERROR = (
    "[AUTH] 登录最终失败 (10.100.28.27:28001): 登录失败 - 未获取到 Z-AUTH-CODE cookie "
    "(HTTP 401 Unauthorized, 服务端原因: User has been locked (code=4))；"
    "账号已被上游锁定，重试无意义，需联系 UME 管理员解锁"
)


def test_locked_account_is_non_retryable():
    """2026-10-12 的核心修复：锁定不再每 10 分钟重投一次。"""
    hits = [k for k in ar.NON_RETRYABLE_KEYS if k in LOCKED_ERROR]
    assert hits, "账号锁定必须被 auto_retry 判为永久性错误"


def test_locked_keyword_matches_upstream_verbatim():
    """即使错误里只有上游英文原文（未经过 _describe_login_failure），也要命中。"""
    raw = "login_rsa 401: User has been locked"
    assert any(k in raw for k in ar.NON_RETRYABLE_KEYS)


def test_previous_non_retryable_keywords_still_work():
    """回归：原有的永久性关键字不能被改坏。"""
    for probe in ("BUDGET_EXCEEDED", "任务已禁用", "文件未找到",
                  "无效的 cron", "STOPPED_BY_USER"):
        assert any(k in probe for k in ar.NON_RETRYABLE_KEYS), probe


def test_transient_errors_are_still_retryable():
    """回归：网络类/瞬时错误不能被误判为永久性，否则会丢掉自愈能力。"""
    for probe in ("网络超时 timeout", "RSA 公钥获取失败",
                  "连接被拒绝 10060", "登录成功但解析失败"):
        assert not any(k in probe for k in ar.NON_RETRYABLE_KEYS), probe


# ------------------------------------- 3) 鉴权类失败额度用尽后的一次性宽限
# 背景（2026-10-12）：账号锁定故障横跨 04:01~09:40，8 个任务的 scheduled 1 次
# + auto_retry 2 次额度全部在锁定期内烧光，账号 09:51 解锁后没有任何机制会
# 自动补跑 —— 只能人工重投。而鉴权恢复后第一次重试大概率成功，故在「额度恰好
# 用尽 + 鉴权类失败 + 非锁定类永久错误」时给一次性宽限重投。


def _eval_with_attempts(error, attempts, last_retry_at=None):
    """在标准上下文里调用 _evaluate_candidate（network 层已 mock 掉，走回退路径）。"""
    from backend.services import task_runner
    registry = task_runner._task_registry
    return ar._evaluate_candidate(
        task_id="ran_ume_daily",
        failed_at="2026-10-12T09:40:04",
        error=error,
        retry_attempts=attempts,
        last_retry_at=last_retry_at,
        now=__import__("datetime").datetime(2026, 10, 12, 10, 30, 0),
        registry=registry,
        interval_min=10,
    )


def test_auth_exhausted_budget_gets_one_grace_retry():
    """额度恰好用尽 + 鉴权类失败 → 宽限重投（今天的 8 个任务就是这个场景）。"""
    info = _eval_with_attempts("Login failed - no auth cookie obtained", 2)
    assert info["will_retry"] is True
    assert "宽限" in info["reason"]


def test_grace_is_one_shot_not_infinite():
    """宽限投递计入额度：宽限后再失败 → 明确报「宽限重试仍失败」，不会二次宽限。"""
    info = _eval_with_attempts("Login failed - no auth cookie obtained",
                               ar.MAX_ATTEMPTS + 1)
    assert info["will_retry"] is False
    assert "宽限重试仍失败" in info["reason"]


def test_grace_respects_slow_cooldown():
    """宽限走慢冷却（AUTH_GRACE_COOLDOWN_MIN），不是立即重投。"""
    import datetime as _dt
    info = _eval_with_attempts(
        "Login failed - no auth cookie obtained", ar.MAX_ATTEMPTS,
        last_retry_at="2026-10-12T10:20:00")  # 距 now 仅 10 分钟 < 30
    assert info["will_retry"] is False
    assert "宽限冷却" in info["reason"]
    assert info["next_retry_at"] is not None


def test_locked_account_never_gets_grace():
    """锁定类永久错误不配宽限：解锁前重投只会空跑 + 刷告警。"""
    info = _eval_with_attempts(
        "[AUTH] 登录最终失败 (10.100.28.27:28001): User has been locked；"
        "账号已被上游锁定，重试无意义", ar.MAX_ATTEMPTS)
    assert info["will_retry"] is False
    assert "永久性错误" in info["reason"]


def test_grace_only_for_auth_class_failures():
    """非鉴权类失败额度用尽仍走原「等人工处理」，宽限不扩散。"""
    info = _eval_with_attempts("KeyError: 'column_x'", ar.MAX_ATTEMPTS)
    assert info["will_retry"] is False
    assert "已达上限" in info["reason"]


def test_grace_disabled_by_env():
    """AUTO_RETRY_AUTH_GRACE_ENABLED=0 时回到原行为。"""
    old = ar.AUTH_GRACE_ENABLED
    try:
        ar.AUTH_GRACE_ENABLED = False
        info = _eval_with_attempts("Login failed - no auth cookie obtained",
                                   ar.MAX_ATTEMPTS)
        assert info["will_retry"] is False
        assert "已达上限" in info["reason"]
    finally:
        ar.AUTH_GRACE_ENABLED = old


def test_non_auth_exhausted_untouched():
    """回归：非鉴权类失败额度用尽仍走原「已达上限」路径，宽限不扩散。"""
    info = _eval_with_attempts("KeyError: 'column_x' not found", ar.MAX_ATTEMPTS)
    assert info["will_retry"] is False
    assert "已达上限" in info["reason"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

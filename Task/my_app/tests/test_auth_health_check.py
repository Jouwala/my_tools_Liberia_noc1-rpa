# -*- coding: utf-8 -*-
"""鉴权健康巡检：不要把「没发现验证码」扫成验证码失败。

2026-11-12 17:32~19:12 连续 3 次 CRITICAL「脚本登录无法通过 N 条」，
命中的全是巡检自己的 OK 结论和 auto_retry 回声，没有上游拒登。
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.scripts import auth_health_check as ah  # noqa: E402


def test_ok_report_and_retry_echo_are_not_captcha():
    """当天误报的四类行：否定句、回声，都不得再判 CRITICAL。"""
    lines = [
        "- **总体结论：OK**（未发现验证码/锁定/密码错误迹象）",
        "近 1 天日志中未发现验证码/锁定/密码错误/空密码拦截记录。",
        "2026-11-12 18:35:01,398 [auto_retry] INFO [auth_health_check] "
        "时效窗口内自动重试已投递（第 2/2 次）: "
        "鉴权健康 CRITICAL：上游启用图形验证码，脚本登录无法通过2条",
        "2026-11-12 19:10:20,789 [auto_retry] INFO [auth_health_check] "
        "鉴权宽限投递: 鉴权健康 CRITICAL：上游启用图形验证码，脚本登录无法通过3条",
        "[LOGIN] authorize 页面含验证码关键字（仅提示，仍尝试 RSA 登录）",
        "登录页需图形验证码：只预填账号密码，不自动提交",
    ]
    for line in lines:
        assert ah.classify(line) is None, line


def test_real_upstream_captcha_still_critical():
    """auth_manager / ume_in 的真拒登文案必须仍然命中。"""
    real = [
        "登录失败 - 未获取到 Z-AUTH-CODE cookie "
        "(HTTP 400, 服务端原因: Image verification code is invalid or expired "
        "(code=1300112))；上游已启用图形验证码，脚本登录（含 RSA 接口）无法通过，"
        "重试无意义 —— 需人工登录一次以刷新 auth_info.json",
        "RSA 登录失败 → 上游已启用图形验证码，脚本登录无法通过，需人工登录一次",
        '401 {"error":{"code":401,"message":"captcha required"}}',
    ]
    for line in real:
        hit = ah.classify(line)
        assert hit is not None and hit[0] == "CRITICAL" and hit[1] == "captcha", line


def test_wrong_password_still_not_classified_as_locked():
    line = ("Incorrect user name or password, the account may be locked "
            "if you enter wrong for multiple times")
    hit = ah.classify(line)
    assert hit is not None and hit[1] == "wrong_password"


def test_own_report_log_is_skipped_real_worker_line_is_kept(tmp_path, monkeypatch):
    logdir = tmp_path / "log"
    logdir.mkdir()
    stamp = datetime.now().strftime("%Y%m%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    (logdir / f"auth_health_check_{stamp}.log").write_text(
        "- **总体结论：OK**（未发现验证码/锁定/密码错误迹象）\n"
        "近 1 天日志中未发现验证码/锁定/密码错误/空密码拦截记录。\n",
        encoding="utf-8",
    )
    (logdir / f"worker_m_{stamp}.log").write_text(
        f"{now},100 [auto_retry] INFO 鉴权健康 CRITICAL："
        "上游启用图形验证码，脚本登录无法通过4条\n"
        f"{now},200 [auth_manager] ERROR 登录失败 "
        "Image verification code is invalid or expired；"
        "上游已启用图形验证码，脚本登录（含 RSA 接口）无法通过\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ah, "LOG_DIR", logdir)
    monkeypatch.setattr(ah, "EXTRA_LOG_DIRS", [])
    cats, nfiles = ah.scan_logs(1)
    assert nfiles == 1  # 自己的报告日志不计入
    assert "captcha" in cats
    assert cats["captcha"]["count"] == 1
    assert "Image verification code" in cats["captcha"]["hits"][0]["line"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

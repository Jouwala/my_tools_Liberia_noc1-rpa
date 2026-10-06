# -*- coding: utf-8 -*-
"""pytest 收集配置。
tests/ 目录里混着两类文件：
  1) 真正的 pytest 单元测试（本地临时 DB，零副作用）—— 会被收集
  2) 历史遗留的"手动运行脚本"（模块级就会真连 UME / eFlow / 浏览器 E2E）
     —— 一旦被 pytest 导入就会打生产接口，必须排除

所以这里显式忽略第 2 类，保证 `pytest tests/` 始终安全可跑。
需要跑那些脚本时按文件头注释单独 `python tests/xxx.py` 执行。

⚠️ 2026-09-27 补充：以下文件同样是"手动脚本"形态，但它们**模块级就调用
`sys.exit()`**，一旦被收集会直接把 pytest 打成 INTERNALERROR（不是普通
失败，整个 session 崩掉、连其他文件的用例都跑不了）。这是"跑不起来"而不是
"跑不过"，所以必须排除；要跑它们请单独 `python tests/xxx.py`。
"""
import pytest

collect_ignore = [
    "test_ran_ume_network_kpi.py",  # 真实登录 UME 并导出 xlsx
    "test_all_apis.py",             # 打本地/远端 API 全量巡检
    "test_frontend_deep.py",        # 浏览器深度巡检
    "test_frontend_e2e.py",         # 浏览器 E2E
    "run_all_tests.py",
    "run_backend_tests.py",
    "run_deep_all.py",
    "run_deep_tests.py",
    "report_utils.py",
    # ---- 模块级 sys.exit() 的手动脚本：被收集会让 pytest INTERNALERROR ----
    "test_olib_soc_kpi_store.py",   # :842 sys.exit(1 if FAIL else 0)
    "test_olib_soc_report.py",      # :719 sys.exit(main(...))
    "test_task_config_live_effect.py",  # :443 sys.exit(main())
    "test_task_health_alert.py",    # :142 sys.exit(...)
    "test_task_health_detect.py",   # :151 sys.exit(...)
    "test_vmax_multi_data.py",      # :473 sys.exit(main())
    "test_worker_group_coverage.py",  # :212 sys.exit(...)
]

# ==========================================================
# 全局保险：测试**永远不得发真实邮件**（2026-10-06 事故后加）
# ==========================================================
# 事故经过：P1 告警推送新增"同步发邮件"后，本目录里几条**已经存在**的用例会调用
# 真实的 `run_tt_alarm_whatsapp_alert()`（它们只桩掉了 dispatch / wait_for_job_result
# / render_message_ex，没桩邮件），于是每次 `pytest tests/` 都会真发几封邮件到
# 生产收件人。反复跑全量回归后用户收到十几封 "TT No: TT1 / Site: s"。
#
# 根因不是"某条用例忘了桩"，而是**给一个被测试直接调用的函数新增了外部副作用**。
# 所以在入口处统一封死，而不是指望每个写测试的人记得桩邮件：
# 无论哪条用例、无论将来谁再调用发送路径，都不会真的发信。
#
# 需要验证真实发信能力时，请单独 `python TMP/_probe_xxx.py` 手工跑（探针用完即删），
# 不要在 pytest 里放开。
@pytest.fixture(autouse=True)
def _block_real_email(monkeypatch):
    """把所有真实发信出口替换成"记录但不发送"，并返回记录列表供断言。

    用法（需要断言"确实尝试发了邮件"的用例）：
        def test_x(_block_real_email):
            ...
            assert len(_block_real_email) == 1
    """
    sent = []

    def _fake_send_mail(subject, body, to, cc=None, source="tt_alarm"):
        sent.append({"subject": subject, "body": body, "to": to,
                     "cc": cc, "source": source})
        return True

    try:
        from backend.services import tt_alarm_mailer as _mailer
        monkeypatch.setattr(_mailer, "send_mail", _fake_send_mail, raising=False)
    except Exception:  # noqa: BLE001
        pass

    # 兼容老通道（126），同样封死，避免将来有人接回去又把测试变成真发信
    try:
        from backend.services import email_notifier as _notifier
        monkeypatch.setattr(_notifier, "send_status_email",
                            lambda *a, **k: sent.append({"legacy": True}), raising=False)
    except Exception:  # noqa: BLE001
        pass

    return sent


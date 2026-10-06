# -*- coding: utf-8 -*-
"""P1 TT 通报**邮件通道**单测。

对应 `backend/services/tt_alarm_mailer.py`、`tt_alarm_mail_body.py`，以及
`tt_alarm_whatsapp_service` 里的两个发信触发点。

## 这里锁的是什么

用户 2026-10-06 的要求，逐条转成断言：

  1. **邮件在 WhatsApp 确认发出之后才发** —— 不是"同时"（否则会邮件说发了、
     群里实际没到）；
  2. **每单只有第一次通报发邮件**，重报（20 分钟停滞再推）**不发**；
  3. **单子结束（`alarm_clear_time` 非空）再发一封汇总**；
  4. **收件人来自「Settings → 邮件收件人」**，不写死在代码里；
  5. 主题用**英文**。

## 两个必须锁死的反直觉点

  * **汇总不能挂在活跃告警循环上。** 告警一清除，该单就从 `realtime_alarm`
    消失（2026-10-06 实测 4 个已清除单在实时表里 **0 命中**），所以主循环里
    那个 `if cleared:` 分支几乎永不命中。汇总必须走**日志表 + eflow_tt** 的
    独立扫描 —— `test_summary_scan_uses_log_table_not_realtime` 就是钉这个的。
  * **幂等列不能被后续 upsert 抹掉。** 日志表 upsert 是整行覆盖，一旦
    `mail_summary_time` 被写成 NULL，同一单的汇总会被**反复重发**
    （清除是持久事实，不会自己消失）。`test_mail_columns_survive_upsert` 锁这个。
"""
import sqlite3
from datetime import datetime

import pytest

from backend.services import tt_alarm_mail_body as B
from backend.services import tt_alarm_mailer as M
from backend.services import tt_alarm_store as store
from backend.services import tt_alarm_whatsapp_service as S


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture()
def fresh_mailer():
    """加载一份**未被 conftest 打补丁**的 `tt_alarm_mailer` 副本。

    为什么需要它：`tests/conftest.py` 的 autouse fixture 会把
    `tt_alarm_mailer.send_mail` 换成"记录但不发送"的替身（防测试误发真信）。
    替身恒返回 True、永不抛异常，于是"发送失败要收敛成 False""失败要清缓存"
    这类用例在替身上根本测不到。本 fixture 从磁盘把同一份源码再加载一次，
    得到干净的实现，同时把 `sys.modules` 里的 pytest 摘掉以越过模块内闸门 ——
    但 `_get_account` 仍由各用例换成地雷，所以**依然不会真的连 EWS**。
    """
    import importlib.util
    import types

    spec = importlib.util.spec_from_file_location("_tt_mailer_fresh", M.__file__)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # 模块内闸门靠 `"pytest" in sys.modules` 判断；这里给它一个假的 sys，
    # 使闸门放行，从而能测到闸门之后的真实异常处理逻辑。
    fake_sys = types.SimpleNamespace(modules={})
    mod.sys = fake_sys
    return mod


# ==========================================================
# 一、纯函数层：正文与主题（不碰网络、不碰库）
# ==========================================================
class TestMailBody:
    ROW = {
        "tt_no": "TT202610060021", "ticket_severity": "P1",
        "site_name": "Loguatuo", "alarm_code": "9920.0", "title": "site down",
        "alarm_occur_time": "2026-10-06 03:12:00",
        "alarm_clear_time": "2026-10-06 05:42:00",
        "created_time": "2026-10-06 03:20:00",
        "last_modified_time": "2026-10-06 05:45:00",
    }

    def test_subjects_are_english(self):
        """用户要求主题英文；两个主题都不得含中文。"""
        for subj in (B.SUBJECT_NOTIFIED, B.SUBJECT_SUMMARY):
            assert subj
            assert all(ord(c) < 128 for c in subj), f"主题含非 ASCII: {subj}"
        assert "P1 TT Progress Notification" in B.SUBJECT_NOTIFIED
        assert "P1 TT Progress Notification" in B.SUBJECT_SUMMARY

    def test_notified_body_reuses_whatsapp_text_verbatim(self):
        """用户要求邮件与 WhatsApp「同一份内容」——必须原样内嵌，不重渲染。"""
        wa = "Alarm: CELL DOWN\nMilestone: dispatched 10:00\nDuration: 42 min"
        body = B.build_notified_body(self.ROW, wa)
        assert wa in body, "WhatsApp 原文没有原样出现在邮件正文里"
        assert "TT202610060021" in body

    def test_summary_shows_total_duration(self):
        """汇总要给总历时（occurred -> cleared = 2.5h）。"""
        body = B.build_summary_body(self.ROW)
        assert "2.5 h" in body
        assert "150 min" in body

    def test_alarm_code_tail_is_normalized(self):
        """`alarm_code='9920.0'` 必须显示成 `9920`（库里两种写法并存）。"""
        body = B.build_summary_body(self.ROW)
        assert "Alarm:   9920" in body
        assert "9920.0" not in body

    def test_summary_without_analysis_text_does_not_fabricate(self):
        """已结束的单引擎可能取不到数据 —— 如实说明，不编内容。"""
        body = B.build_summary_body(self.ROW, wa_text=None)
        assert "Analysis unavailable" in body

    def test_missing_values_render_dash_not_zero(self):
        """项目硬规矩：取不到给 —，不得给 0。"""
        body = B.build_summary_body({})
        assert "TT No:   -" in body
        # 总历时取不到时是 '-'，绝不能是 '0 min'（那会谎报秒级恢复）
        assert "0 min" not in body
        assert "Total duration (occurred -> cleared): -" in body

    def test_empty_row_does_not_crash(self):
        """空行不得抛异常（缺列、None、空串都是常态）。"""
        assert B.build_notified_body({}, "")
        assert B.build_summary_body({}, wa_text=None)

    def test_invalid_clear_before_occur_is_reported_truthfully(self):
        """清除早于发生 = 数据异常，如实写明而不是显示负数。"""
        row = dict(self.ROW, alarm_occur_time="2026-10-06 05:00:00",
                   alarm_clear_time="2026-10-06 03:00:00")
        assert "invalid" in B.build_summary_body(row)


# ==========================================================
# 二、发信器：空收件人必须不发（不猜、不兜底到某个人）
# ==========================================================
class TestMailerGuards:
    @pytest.mark.parametrize("bad", ["", "   ", None, ";;", " , "])
    def test_empty_to_never_sends(self, fresh_mailer, monkeypatch, bad):
        """主送为空 → 直接 False，且**不得调用** EWS。

        用 `fresh_mailer`：conftest 的防误发替身会无条件返回 True，
        在它上面测不出"空收件人拒绝发送"这条真实逻辑。
        """
        called = []

        def boom():
            called.append(1)
            raise AssertionError("空收件人竟然去登录 EWS 了")

        monkeypatch.setattr(fresh_mailer, "_get_account", boom)
        assert fresh_mailer.send_mail("s", "b", to=bad) is False
        assert called == []

    @pytest.mark.parametrize("text,expected", [
        ("a@x.com; b@y.com", ["a@x.com", "b@y.com"]),
        ("a@x.com,b@y.com", ["a@x.com", "b@y.com"]),
        ("a@x.com\nb@y.com", ["a@x.com", "b@y.com"]),
        ("a@x.com; a@x.com", ["a@x.com"]),        # 去重
        ("  a@x.com  ", ["a@x.com"]),             # 去空白
    ])
    def test_split_addrs(self, text, expected):
        assert M._split_addrs(text) == expected

    def test_send_failure_returns_false_not_raises(self, fresh_mailer, monkeypatch):
        """EWS 抛异常时必须收敛成 False —— 邮件失败不能炸掉推送任务。

        用 `fresh_mailer`（未被 conftest 打补丁的同源副本）才能真正走到异常
        分支：打了补丁的那个 `send_mail` 恒返回 True、永远不抛。
        """
        def boom():
            raise RuntimeError("EWS 挂了")
        monkeypatch.setattr(fresh_mailer, "_get_account", boom)
        assert fresh_mailer.send_mail("s", "b", to="a@x.com") is False

    def test_failure_resets_cached_account(self, fresh_mailer, monkeypatch):
        """失败要丢弃缓存会话，否则改密后每次都会失败。"""
        monkeypatch.setattr(fresh_mailer, "_ACCOUNT_CACHE", object())

        def boom():
            raise RuntimeError("x")

        monkeypatch.setattr(fresh_mailer, "_get_account", boom)
        fresh_mailer.send_mail("s", "b", to="a@x.com")
        assert fresh_mailer._ACCOUNT_CACHE is None


# ==========================================================
# 三、日志表：幂等列（本特性的正确性根基）
# ==========================================================
@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    store.ensure_log_table(conn)
    yield conn
    conn.close()


class TestStoreMailColumns:
    ROW = {"tt_no": "TT1", "alarm_code": "99933", "ticket_severity": "P1"}

    def test_columns_created(self, db):
        cols = {r[1] for r in db.execute(
            f"PRAGMA table_info({store.LOG_TABLE})")}
        assert set(store.MAIL_COLUMNS) <= cols

    def test_pending_requires_prior_notification(self, db):
        """没发过首次通报的单**不该**发汇总（否则先收到"结束"没见过"开始"）。"""
        store.record_result(db, self.ROW, ok=True)
        assert store.pending_summary_mail(db) == []
        store.mark_mail_sent(db, "TT1", "notified")
        assert store.pending_summary_mail(db) == ["TT1"]

    def test_pending_excludes_never_sent_tickets(self, db):
        """从没确认发出过 WhatsApp 的单不发汇总（没有"进展"可言）。"""
        store.mark_mail_sent(db, "TT1", "notified")
        assert store.pending_summary_mail(db) == []

    def test_marked_summary_is_not_pending_again(self, db):
        """幂等：发了汇总就不再是候选（否则每 5 分钟重发一次）。"""
        store.record_result(db, self.ROW, ok=True)
        store.mark_mail_sent(db, "TT1", "notified")
        assert store.mark_mail_sent(db, "TT1", "summary") is True
        assert store.pending_summary_mail(db) == []

    def test_mail_columns_survive_upsert(self, db):
        """⚠️ 关键回归：整行覆盖的 upsert 不得抹掉幂等列。

        没有这条保护，`mail_summary_time` 会在下一次 record_result 后变 NULL，
        同一单的汇总被反复重发。此处**故意不传 existing**（最脆弱路径）。
        """
        store.record_result(db, self.ROW, ok=True)
        store.mark_mail_sent(db, "TT1", "notified")
        store.mark_mail_sent(db, "TT1", "summary")
        store.record_result(db, self.ROW, ok=True)     # existing 缺省
        row = db.execute(
            "SELECT mail_notified_time, mail_summary_time FROM "
            f"{store.LOG_TABLE} WHERE tt_no='TT1'").fetchone()
        assert row[0], "mail_notified_time 被 upsert 抹掉了"
        assert row[1], "mail_summary_time 被 upsert 抹掉了"
        assert store.pending_summary_mail(db) == []

    def test_mail_columns_survive_when_existing_given(self, db):
        """生产路径（传 existing）同样要保住幂等列。"""
        store.record_result(db, self.ROW, ok=True)
        store.mark_mail_sent(db, "TT1", "notified")
        existing = store.load_records(db, ["TT1"])["TT1"]
        assert existing.get("mail_notified_time")
        store.record_result(db, self.ROW, ok=True, existing=existing)
        assert store.load_records(db, ["TT1"])["TT1"]["mail_notified_time"]

    def test_mark_bad_kind_is_noop(self, db):
        store.record_result(db, self.ROW, ok=True)
        assert store.mark_mail_sent(db, "TT1", "bogus") is False
        assert store.mark_mail_sent(db, "", "notified") is False


# ==========================================================
# 四、服务层：触发点（首次通报 / 结束汇总）
# ==========================================================
class TestServiceMailTriggers:
    def test_summary_scan_uses_log_table_not_realtime(self, monkeypatch):
        """⚠️ 核心设计断言：汇总候选来自**日志表**，而非 realtime_alarm。

        告警清除后该单会从 realtime_alarm 消失（实测 0 命中），若把汇总挂在
        活跃告警循环上，一封都发不出去。
        """
        used = {}

        def fake_pending(conn, limit=200, table=None):
            used["called"] = True
            return ["TT_CLOSED_1"]

        monkeypatch.setattr(S.store, "pending_summary_mail", fake_pending)
        monkeypatch.setattr(S.sources, "cleared_rows",
                            lambda conn, ids: {"TT_CLOSED_1": {
                                "tt_no": "TT_CLOSED_1",
                                "alarm_occur_time": "2026-10-06 03:00:00",
                                "alarm_clear_time": "2026-10-06 05:00:00"}})
        sent = []
        monkeypatch.setattr(S.mailer, "send_mail",
                            lambda **kw: sent.append(kw) or True)
        monkeypatch.setattr(S.store, "mark_mail_sent", lambda *a, **k: True)
        monkeypatch.setattr(S, "MAIL_ENABLED", True)
        monkeypatch.setattr(S, "_mail_recipients", lambda: ("a@x.com", ""))

        out = {"errors": [], "warnings": []}
        S.run_summary_mail_scan(out)
        assert used.get("called"), "没有查日志表"
        assert len(sent) == 1
        assert sent[0]["subject"] == B.SUBJECT_SUMMARY
        assert out["mail_summary_sent"] == 1

    def test_summary_scan_skipped_when_mail_disabled(self, monkeypatch):
        monkeypatch.setattr(S, "MAIL_ENABLED", False)
        monkeypatch.setattr(S.store, "pending_summary_mail",
                            lambda *a, **k: pytest.fail("开关关了还在扫"))
        S.run_summary_mail_scan({"errors": [], "warnings": []})

    def test_summary_scan_skipped_when_no_recipients(self, monkeypatch):
        """收件人未配置 → 不发，也不报错。"""
        monkeypatch.setattr(S, "MAIL_ENABLED", True)
        monkeypatch.setattr(S, "_mail_recipients", lambda: (None, ""))
        monkeypatch.setattr(S.store, "pending_summary_mail",
                            lambda *a, **k: pytest.fail("没配收件人还在扫"))
        S.run_summary_mail_scan({"errors": [], "warnings": []})

    def test_uncleared_ticket_gets_no_summary(self, monkeypatch):
        """`cleared_rows` 只返回已清除的单 —— 未清除的单不发汇总。"""
        monkeypatch.setattr(S, "MAIL_ENABLED", True)
        monkeypatch.setattr(S, "_mail_recipients", lambda: ("a@x.com", ""))
        monkeypatch.setattr(S.store, "pending_summary_mail",
                            lambda conn, limit=200, table=None: ["TT_OPEN"])
        monkeypatch.setattr(S.sources, "cleared_rows", lambda conn, ids: {})
        sent = []
        monkeypatch.setattr(S.mailer, "send_mail",
                            lambda **kw: sent.append(kw) or True)
        out = {"errors": [], "warnings": []}
        S.run_summary_mail_scan(out)
        assert sent == []
        assert out.get("mail_summary_sent") is None

    def test_first_notification_uses_settings_recipients(self, monkeypatch):
        """收件人必须来自 Settings 的 `tt_alarm_p1_email`，不写死在服务里。"""
        asked = {}
        monkeypatch.setattr(S, "_mail_recipients",
                            lambda: asked.setdefault("k", ("to@x.com", "cc@x.com"))
                            or ("to@x.com", "cc@x.com"))
        monkeypatch.setattr(S, "MAIL_ENABLED", True)
        monkeypatch.setattr(S.mailer, "send_mail", lambda **kw: True)
        monkeypatch.setattr(S.store, "mark_mail_sent", lambda *a, **k: True)
        ok = S.send_first_notification_mail({"tt_no": "TT1"}, "wa text")
        assert ok is True
        assert asked.get("k"), "没有走 Settings 收件人读取"

    def test_first_notification_marks_idempotency(self, monkeypatch):
        """发成功要置位 mail_notified_time，否则汇总永远等不到前置条件。"""
        marked = []
        monkeypatch.setattr(S, "MAIL_ENABLED", True)
        monkeypatch.setattr(S, "_mail_recipients", lambda: ("a@x.com", ""))
        monkeypatch.setattr(S.mailer, "send_mail", lambda **kw: True)
        monkeypatch.setattr(S.store, "mark_mail_sent",
                            lambda conn, tt, kind, **k: marked.append((tt, kind)) or True)
        S.send_first_notification_mail({"tt_no": "TT1"}, "t")
        assert ("TT1", "notified") in marked

    def test_first_notification_failure_does_not_mark(self, monkeypatch):
        """发失败**不得**置位 —— 否则这单的汇总条件被错误满足。"""
        marked = []
        monkeypatch.setattr(S, "MAIL_ENABLED", True)
        monkeypatch.setattr(S, "_mail_recipients", lambda: ("a@x.com", ""))
        monkeypatch.setattr(S.mailer, "send_mail", lambda **kw: False)
        monkeypatch.setattr(S.store, "mark_mail_sent",
                            lambda *a, **k: marked.append(a) or True)
        assert S.send_first_notification_mail({"tt_no": "TT1"}, "t") is False
        assert marked == []

    def test_first_notification_skipped_when_disabled(self, monkeypatch):
        monkeypatch.setattr(S, "MAIL_ENABLED", False)
        monkeypatch.setattr(S.mailer, "send_mail",
                            lambda **kw: pytest.fail("开关关了还在发"))
        assert S.send_first_notification_mail({"tt_no": "TT1"}, "t") is False


# ==========================================================
# 五、配置层：开关的 env > file > default 优先级
# ==========================================================
class TestMailConfig:
    def test_default_is_enabled(self, monkeypatch):
        from backend.services import tt_alarm_config as C
        cfg = C.parse_config({}, "test", env={})
        assert cfg["mail_enabled"] is True

    @pytest.mark.parametrize("val,expected", [
        ("false", False), ("0", False), ("no", False), ("off", False),
        ("true", True), ("1", True), ("YES", True),
    ])
    def test_env_overrides_file(self, monkeypatch, val, expected):
        from backend.services import tt_alarm_config as C
        cfg = C.parse_config({"mail_enabled": not expected}, "test",
                             env={C.ENV_MAIL_ENABLED: val})
        assert cfg["mail_enabled"] is expected
        assert cfg["mail_enabled_from"] == "env"

    def test_file_value_used(self):
        from backend.services import tt_alarm_config as C
        cfg = C.parse_config({"mail_enabled": False}, "test", env={})
        assert cfg["mail_enabled"] is False
        assert cfg["mail_enabled_from"] == "file"

    def test_garbage_keeps_mail_on(self):
        """配置写错不该让邮件通道**静默**关闭。"""
        from backend.services import tt_alarm_config as C
        cfg = C.parse_config({"mail_enabled": "maybe"}, "test", env={})
        assert cfg["mail_enabled"] is True


# ==========================================================
# 六、测试防误发（2026-10-06 事故后的回归锁）
# ==========================================================
class TestNoRealMailFromTests:
    """锁死「测试永远不发真信」。

    事故：本特性给 `run_tt_alarm_whatsapp_alert()` 加了发信副作用，而
    `test_tt_alarm_render.py` 里两条**既有**用例会调用它（只桩了 dispatch /
    wait_for_job_result / render_message_ex，没桩邮件）。于是每跑一次全量回归
    就真发几封 "TT No: TT1 / Site: s" 到生产收件人，反复跑几轮后用户收到十几封。

    这几条断言是**回归锁**：谁再把这个洞打开，这里就会红。
    """

    def test_conftest_guard_is_installed(self, _block_real_email):
        """conftest 的全局替身必须生效 —— 否则下面几条都是空测。"""
        from backend.services import tt_alarm_mailer as M
        # 直接调用应当被拦截并记录，而不是真的连 EWS
        assert M.send_mail("s", "b", to="nobody@example.invalid") is True
        assert len(_block_real_email) == 1
        assert _block_real_email[0]["to"] == "nobody@example.invalid"

    def test_mailer_refuses_to_send_under_pytest(self, monkeypatch):
        """纵深防御：即便绕过 conftest 替身，模块自身在 pytest 下也拒发。

        主防线是 conftest 的 autouse fixture（替换 `send_mail`）。这条锁的是
        `send_mail` 函数体内的第二道闸 —— 将来有人直接 import 本模块写测试、
        或把 conftest 的替身删了，依然发不出去。

        做法：把本模块**当普通文件再加载一份**（`_tt_mailer_probe`），
        那份副本没被 conftest 打过补丁，于是走的是真实函数体。
        用合法收件人调用它：若没有闸门，就会去连 EWS ——
        故把 `_get_account` 换成地雷来判定。
        """
        import importlib.util
        import sys as _sys
        from backend.services import tt_alarm_mailer as M
        assert "pytest" in _sys.modules, "本用例前提：跑在 pytest 下"

        spec = importlib.util.spec_from_file_location("_tt_mailer_probe", M.__file__)
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)

        touched = []

        def _tripwire():
            touched.append(1)
            raise AssertionError("pytest 下竟然真的去连 EWS 了")

        monkeypatch.setattr(probe, "_get_account", _tripwire)
        assert probe.send_mail("s", "b", to="a@x.com") is False
        assert touched == [], "模块内闸门没拦住，测试环境真的会发信"

    def test_channel_helpers_exist(self):
        """确认用的是 Orange EWS 通道（用户明确否决 126）。"""
        from backend.services import tt_alarm_mailer as M
        assert "orange" in M.DEFAULT_EWS_SERVER
        assert "orange" in M.DEFAULT_SMTP_ADDRESS

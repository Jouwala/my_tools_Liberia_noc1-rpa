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


def _use_db(monkeypatch, tmp_path, eflow_rows=None):
    """把 DB 切到临时 sqlite，可选预置 eflow_tt 行。

    与 `test_tt_alarm_render.py::_use_db` 同构（列集必须一致：`ticket_no` /
    `wo_no` 是分析引擎依赖的列，缺了会让快照相关断言假失败）。
    """
    db_path = tmp_path / "raw.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS eflow_tt (tt_no TEXT, ticket_severity TEXT, "
        "alarm_code TEXT, alarm_occur_time TEXT, alarm_clear_time TEXT, "
        "site_id TEXT, site_name TEXT, title TEXT, "
        "ticket_no TEXT, wo_no TEXT)")
    for row in (eflow_rows or []):
        conn.execute("INSERT INTO eflow_tt VALUES (?,?,?,?,?,?,?,?,?,?)",
                     tuple(row) + (None, None))
    conn.commit()
    conn.close()

    from backend import database as db
    monkeypatch.setattr(db, "DB_MODE", "sqlite")
    monkeypatch.setattr(db, "DB_PATH", db_path)
    return db_path


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
# 三点五、老表自动补列（2026-10-06 生产事故回归）
#
# 事故：PG 库里的 eflow_tt_whatsapp_alert_log 是早期版本建的，缺 last_error。
# `CREATE TABLE IF NOT EXISTS` 对已存在的表是 no-op（不加列），而旧
# `_ensure_columns` 的补列清单**只覆盖 TRACK+MAIL，漏了 last_error** →
# 每次 record_result upsert 带 last_error → PG 报
# `UndefinedColumn: 字段 "last_error" 不存在`，任务整轮失败。
#
# 修复：补列集合 = 建表列全集（ENSURE_COLUMNS），加列只改 LOG_COLUMNS 一处。
# 这里锁死「老表缺任意列 → ensure_log_table 都能补齐 → 写路径可跑」。
# ==========================================================
# 事故现场：一张缺 last_error 及全部跟踪/邮件列的"老表"
_OLD_TABLE_COLS = (
    "tt_no", "alarm_occur_time", "ticket_severity", "alarm_code",
    "site_id", "site_name", "title", "send_status", "send_count",
    "last_send_time", "last_tt_modified", "first_seen_time", "updated_time",
)


class TestEnsureColumnsBackfill:
    ROW = {"tt_no": "TT1", "alarm_code": "99933", "ticket_severity": "P1"}

    def _make_old_table(self):
        conn = sqlite3.connect(":memory:")
        col_defs = ", ".join(
            f"{c} {'INTEGER' if c in store.COLUMN_TYPES else 'TEXT'}"
            + (" PRIMARY KEY" if c in store.LOG_PK else "")
            for c in _OLD_TABLE_COLS
        )
        conn.execute(f"CREATE TABLE {store.LOG_TABLE} ({col_defs})")
        return conn

    def test_old_table_missing_last_error_is_upgraded(self):
        """核心回归：老表缺 last_error，ensure_log_table 必须补上（否则 PG 报错）。"""
        conn = self._make_old_table()
        before = {r[1] for r in conn.execute(f"PRAGMA table_info({store.LOG_TABLE})")}
        assert "last_error" not in before, "前置条件：老表本应缺 last_error"

        store.ensure_log_table(conn)

        after = {r[1] for r in conn.execute(f"PRAGMA table_info({store.LOG_TABLE})")}
        assert "last_error" in after, "补列后仍缺 last_error（事故未修复）"
        conn.close()

    def test_all_create_columns_covered_by_backfill(self):
        """⚠️ 结构不变量：建表列全集必须等于补列集合 + 主键。

        这条测试是**防止未来加列时又只改建表、忘改补列**的根本保障 ——
        LOG_COLUMNS 是单一事实来源，建表与补列都从它派生。
        """
        assert set(store.ENSURE_COLUMNS) == set(store.LOG_COLUMNS) - set(store.LOG_PK), (
            "ENSURE_COLUMNS 与 LOG_COLUMNS 分叉了：加列必须只改 LOG_COLUMNS 一处"
        )

    def test_old_table_fully_reconciled(self):
        """老表补齐后，列集合必须完整（一个不缺）。"""
        conn = self._make_old_table()
        store.ensure_log_table(conn)
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({store.LOG_TABLE})")}
        assert set(store.LOG_COLUMNS) <= cols, (
            f"补齐后仍缺列: {set(store.LOG_COLUMNS) - cols}"
        )
        conn.close()

    def test_write_path_succeeds_on_upgraded_old_table(self):
        """事故的真实触发点是写路径 —— 补列后 record_result 必须能跑通。

        （PG 下缺列时 upsert 带该列会直接 UndefinedColumn；这里用 sqlite 复现
        同一路径：若补列没生效，INSERT 会因列不存在而报错。）
        """
        conn = self._make_old_table()
        store.ensure_log_table(conn)
        store.record_result(conn, self.ROW, ok=False, error="down")
        row = conn.execute(
            f"SELECT send_status, last_error FROM {store.LOG_TABLE} WHERE tt_no='TT1'"
        ).fetchone()
        assert row[0] == "N"
        assert row[1] == "down"
        conn.close()

    def test_old_table_existing_data_preserved(self):
        """补列是纯增量：老数据不得丢失。"""
        conn = self._make_old_table()
        conn.execute(
            f"INSERT INTO {store.LOG_TABLE} (tt_no, send_status, send_count) "
            f"VALUES ('OLD1', 'Y', 3)"
        )
        store.ensure_log_table(conn)
        row = conn.execute(
            f"SELECT send_status, send_count FROM {store.LOG_TABLE} WHERE tt_no='OLD1'"
        ).fetchone()
        assert row == ("Y", 3)
        conn.close()

    def test_repeated_ensure_is_idempotent(self):
        """补列必须幂等：反复调用不得报错、不得重复加列。"""
        conn = self._make_old_table()
        store.ensure_log_table(conn)
        store.ensure_log_table(conn)  # 第二次：所有列已存在，应静默通过
        n = len([r for r in conn.execute(f"PRAGMA table_info({store.LOG_TABLE})")])
        assert n == len(store.LOG_COLUMNS), "重复调用导致列重复或缺失"
        conn.close()


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


# ==========================================================
# 七、真实单的发信次数（锁"一个生命周期只发 2 封"）
# ==========================================================
class TestRealTicketMailCount:
    """用户 2026-10-06 追问：「真实单子触发也会发三封一样内容的邮件吗？」

    答案必须是**不会**。这里把口径钉死：

      * 首推（`reminder_no == 1`）→ 1 封"首次通报"
      * 重报 N 次（`reminder_no >= 2`）→ **0 封**
      * 告警清除 → 1 封"结束汇总"（且只发一次）

    即**一个单的生命周期共 2 封**，与它重报了几次无关。

    19 封测试邮件是"3 封/轮 × 6 轮回归"造成的，**不是**单次触发发 3 封 ——
    那 3 封来自 3 条不同用例各自的假单（TT1、TT1+TT2），不是同一单发 3 次。
    这条用例防止将来有人把 reminder_no 的判断写错、退回"每轮都发"。
    """

    TT = "TT202610010999"
    ROW = {"tt_no": TT, "alarm_code": "9920", "ticket_severity": "P1",
           "site_name": "Loguatuo", "alarm_occur_time": "2026-10-06 03:00:00",
           "alarm_clear_time": "", "created_time": "2026-10-06 03:05:00",
           "last_modified_time": "2026-10-06 03:05:00"}

    def _reminder_no(self, conn):
        """复刻服务里的口径：`reminder_no = send_count + 1`（:505）。"""
        rec = store.load_records(conn, [self.TT]).get(self.TT)
        return int((rec or {}).get("send_count") or 0) + 1

    def test_full_lifecycle_sends_exactly_two(self, db):
        """首推 + 3 次重报 + 清除 → 共 2 封（1 通报 + 1 汇总）。"""
        sent = []

        # 第 1 轮：首推 —— 应发"首次通报"
        rn = self._reminder_no(db)
        assert rn == 1, f"首推的 reminder_no 应为 1，实际 {rn}"
        store.record_result(db, self.ROW, ok=True,
                            existing=store.load_records(db, [self.TT]).get(self.TT))
        if rn <= 1:
            sent.append("notified")
        store.mark_mail_sent(db, self.TT, "notified")

        # 第 2~4 轮：重报 —— 一封都不该发
        for i in range(3):
            rn = self._reminder_no(db)
            assert rn >= 2, f"第 {i + 2} 轮的 reminder_no 应 >= 2，实际 {rn}"
            store.record_result(db, self.ROW, ok=True,
                                existing=store.load_records(db, [self.TT]).get(self.TT))
            if rn <= 1:
                sent.append("notified")

        # 清除后：汇总只发一次
        assert store.pending_summary_mail(db) == [self.TT]
        if store.pending_summary_mail(db):
            sent.append("summary")
            store.mark_mail_sent(db, self.TT, "summary")
        assert store.pending_summary_mail(db) == [], "汇总不得重发"

        assert sent == ["notified", "summary"], \
            f"真实单一个生命周期应恰好 2 封（1 通报 + 1 汇总），实际 {sent}"

    def test_resend_never_qualifies_for_notification_mail(self, db):
        """`reminder_no >= 2` 一律不发通报邮件 —— 这是"不会发 3 封"的核心保证。"""
        store.record_result(db, self.ROW, ok=True)
        store.mark_mail_sent(db, self.TT, "notified")
        for _ in range(5):
            rn = self._reminder_no(db)
            store.record_result(db, self.ROW, ok=True,
                                existing=store.load_records(db, [self.TT]).get(self.TT))
            assert rn >= 2 and not (rn <= 1), \
                f"重报第 {rn} 次竟然满足发信条件（reminder_no<=1）"

    def test_service_filter_rejects_resend(self, monkeypatch, tmp_path):
        """**直接测服务里那句过滤** —— 重报单必须进不了 `mail_targets`。

        ⚠️ 这条不能只测 store：把服务里的 `reminder_no <= 1` 反转成 `>= 1`
        （每轮都发）时，只有测 store 的用例仍然全绿 —— 那是**假绿**，
        因为过滤发生在服务层，不在 store 层。本用例跑真实的
        `run_tt_alarm_whatsapp_alert()`，并断言只有首推那单发了邮件。
        """
        from backend.services import tt_alarm_sources as src
        from backend.services import tt_alarm_trigger as trig

        now = datetime.now()
        # TT_A 是老单（日志里 send_count=1 → 本轮 reminder_no=2 = 重报）
        # TT_B 是新单（日志无记录 → reminder_no=1 = 首推）
        rows = [
            {"tt_no": "TT_A", "_alarm_code_norm": "9920", "alarm_raised_time": _now(),
             "_alarm_raised_dt": now, "site_id": "1", "site_name": "sa"},
            {"tt_no": "TT_B", "_alarm_code_norm": "9920", "alarm_raised_time": _now(),
             "_alarm_raised_dt": now, "site_id": "2", "site_name": "sb"},
        ]
        monkeypatch.setattr(trig, "fetch_triggered_tts",
                            lambda *a, **k: (rows, {"window_since": "x", "table_exists": True,
                                                    "truncated": False, "sync_lag_seconds": None}))
        monkeypatch.setattr(src, "live_tt_rows", lambda tt_nos: {})
        monkeypatch.setattr(src, "mirror_rows", lambda conn, nos: {
            r["tt_no"]: {"tt_no": r["tt_no"], "ticket_severity": "P1",
                         "site_name": r["site_name"],
                         "alarm_occur_time": "2026-10-06 01:00:00",
                         "last_modified_time": "2026-10-06 01:00:00"}
            for r in rows})
        _use_db(monkeypatch, tmp_path)
        monkeypatch.setattr(S, "render_message_ex", lambda *a, **k: ("msg", None))
        monkeypatch.setattr(S, "dispatch",
                            lambda msgs, groups: {"ok": True, "job_id": "j1",
                                                  "dispatched": len(msgs)})
        monkeypatch.setattr(S, "wait_for_job_result",
                            lambda *a, **k: {"confirmed": True, "ok": True, "timed_out": False,
                                             "sent": ["TT_A", "TT_B"], "message_ids": {},
                                             "errors": []})
        monkeypatch.setattr(S, "MAIL_ENABLED", True)
        monkeypatch.setattr(S, "_mail_recipients", lambda: ("a@x.com", ""))
        monkeypatch.setattr(S.store, "mark_mail_sent", lambda *a, **k: True)
        monkeypatch.setattr(S.store, "pending_summary_mail", lambda *a, **k: [])
        # 让 TT_A 看起来像"已经发过一次"的老单
        monkeypatch.setattr(S, "load_records",
                            lambda conn, nos: {"TT_A": {"tt_no": "TT_A", "send_count": 1}})

        mails = []
        monkeypatch.setattr(S.mailer, "send_mail",
                            lambda **kw: mails.append(kw) or True)

        S.run_tt_alarm_whatsapp_alert()

        subs = [m.get("subject") for m in mails]
        assert len(mails) == 1, (
            f"只有首推单 TT_B 该发通报邮件，实际发了 {len(mails)} 封：{subs}。"
            f"重报单 TT_A 也被发了 = reminder_no 过滤失效")

    def test_one_ticket_appears_once_per_round(self):
        """`due` 由触发扫描去重，同一单每轮最多一条 → 不会一轮发多封。

        若这里失守（例如将来有人改用未去重的来源），同一单就会在一轮内
        append 多次 mail_targets，于是"一轮发 N 封同内容" —— 正是用户担心的情形。
        """
        from backend.services import tt_alarm_trigger as trig
        import inspect as _inspect
        src = _inspect.getsource(trig.fetch_triggered_tts)
        assert "seen" in src and "tt_no in seen" in src, \
            "触发扫描必须按 tt_no 去重，否则同一单会在 due 里出现多次"

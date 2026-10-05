# -*- coding: utf-8 -*-
"""TT 告警消息渲染单测：复用 whatsapp-kb-bot 分析引擎 + 降级策略。

对应 `backend/services/tt_alarm_render.py`。

## 这里锁的是什么

用户要求告警消息与群里机器人回答**同格式**（完整分析：里程碑时间轴、派单依据、
SLA 时效），而那是 `Task/whatsapp-kb-bot/scripts/tt-analyze.py` 的输出。
本任务用子进程复用它，于是新的失败面出现了：

  1. **引擎不在**（部署到没有 kb-bot 的机器、或路径变了）→ 不能整条告警不发；
  2. **单号查不到** → 引擎退出码 1，但 stdout 可能仍有内容。**只能靠退出码判断**，
     否则会把引擎的错误提示当消息发进群；
  3. **引擎超时/抛错** → 不能拖垮整轮告警任务。

故测试分两层：**契约层**（不依赖引擎是否存在，用桩）覆盖降级与错误判据；
**真实层**（引擎在时才跑）用真实单号回放，确认与用户要求的格式逐字一致。
"""
import subprocess
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from backend.services import tt_alarm_render as R
from backend.services import tt_alarm_whatsapp_service as S

# 本文件专用的建库/切库小工具（原与 test_tt_alarm_config 共用；2026-10-05 机制切换后
# config 测试不再碰库，为避免"为复用而跨文件耦合"改为本文件自带）。
def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _use_db(monkeypatch, tmp_path, eflow_rows=None):
    """把 DB 切到临时 sqlite（patch DB_MODE/DB_PATH 属性，与旧测试同模式），
    可选预置 eflow_tt 行。

    快照路径 `_snapshot_tt(tt)` 会 `SELECT * FROM eflow_tt WHERE tt_no=?`；
    任务入口的 ensure_log_table / load_records 也在同一张库上跑。
    """
    db_path = tmp_path / "raw.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS eflow_tt (tt_no TEXT, ticket_severity TEXT, "
        "alarm_code TEXT, alarm_occur_time TEXT, alarm_clear_time TEXT, "
        "site_id TEXT, site_name TEXT, title TEXT)")
    for row in (eflow_rows or []):
        conn.execute("INSERT INTO eflow_tt VALUES (?,?,?,?,?,?,?,?)", row)
    conn.commit()
    conn.close()

    from backend import database as db
    monkeypatch.setattr(db, "DB_MODE", "sqlite")
    monkeypatch.setattr(db, "DB_PATH", db_path)
    return db_path

# 用户 2026-09-29 指定的「应该长这样」样例（真实单号，头部 8 行）
SAMPLE_TT = "TT202609290045"
EXPECTED_HEAD = [
    "TT202609290045 · Loguatuo(4715) | Nimba | Site type NORMAL | Site subtype REGULAR",
    "Title: 4715.[Loguatuo]Partial site down (PSD)",
    "Alarm: 9910(Critical) | RAN | Communication Alarm",
    "Alarm object: BSC1(1)/Loguatuo | 129.0.1.1 | 2G SITE DOWN",
    "Impact: 2G,3G outage | site outage | 1 site(s) down | VIP No",
    "Severity: P2 (matches rule)",
    "Matched rule: #227 无线断站级别重定义-P2-new",
    "Basis: assetType=NORMAL = NORMAL \u2713; alarmCode=9910 in 9970,9980,9990,9910,9920,99933 \u2713; "
    "vipSite=0 = 0 \u2713",
]


# ==========================================================
# 契约层：不依赖引擎是否存在
# ==========================================================
def test_render_returns_none_for_blank_tt_no():
    """空单号连拉起子进程都不必，直接判失败（调用方降级）。"""
    assert R.render_tt_analysis("") is None
    assert R.render_tt_analysis("   ") is None


def test_render_returns_none_when_engine_missing(monkeypatch, tmp_path):
    """引擎不存在 → 返回 None 而不是抛异常，保证整轮告警不被拖垮。"""
    monkeypatch.setattr(R, "engine_path", lambda: tmp_path / "nope.py")
    assert R.render_tt_analysis(SAMPLE_TT) is None


def test_engine_available_follows_path(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "engine_path", lambda: tmp_path / "nope.py")
    assert R.engine_available() is False
    f = tmp_path / "exists.py"
    f.write_text("x", encoding="utf-8")
    monkeypatch.setattr(R, "engine_path", lambda: f)
    assert R.engine_available() is True


def test_nonzero_exit_is_treated_as_failure_even_with_stdout(monkeypatch, tmp_path):
    """引擎用退出码表达「没找到这一单」。

    若只看 stdout 非空就采用，会把引擎的错误提示（或半截输出）当成告警消息
    发进群 —— 故必须同时校验退出码。
    """
    script = tmp_path / "fake.py"
    script.write_text("import sys; print('TT not found: 请检查单号'); sys.exit(1)", encoding="utf-8")
    monkeypatch.setattr(R, "engine_path", lambda: script)
    assert R.render_tt_analysis(SAMPLE_TT) is None, "退出码非 0 时不得采用 stdout"


def test_empty_stdout_with_zero_exit_is_failure(monkeypatch, tmp_path):
    """退出码 0 但无输出 → 仍判失败，不能发一条空消息。"""
    script = tmp_path / "fake.py"
    script.write_text("import sys; sys.exit(0)", encoding="utf-8")
    monkeypatch.setattr(R, "engine_path", lambda: script)
    assert R.render_tt_analysis(SAMPLE_TT) is None


def test_successful_run_returns_stripped_stdout(monkeypatch, tmp_path):
    script = tmp_path / "fake.py"
    script.write_text("print('line1\\nline2\\n\\n')", encoding="utf-8")
    monkeypatch.setattr(R, "engine_path", lambda: script)
    assert R.render_tt_analysis("TT1") == "line1\nline2"


def test_timeout_returns_none(monkeypatch, tmp_path):
    """超时必须返回 None 而不是挂住整个告警任务。"""
    script = tmp_path / "slow.py"
    script.write_text("import time; time.sleep(60)", encoding="utf-8")
    monkeypatch.setattr(R, "engine_path", lambda: script)
    monkeypatch.setattr(R, "TIMEOUT_SECONDS", 1)
    assert R.render_tt_analysis("TT1") is None


def test_engine_env_points_at_my_app_paths():
    """子进程必须拿到 my_app 的真实路径。

    引擎默认读 `Y:/Task/my_app/...`（生产机盘符），本机不存在；
    不覆盖这三个变量，子进程一启动就找不到库和规则表。
    """
    env = R._engine_env()
    assert env["MY_APP_DIR"].replace("\\", "/").endswith("Task/my_app")
    assert env["MY_APP_DB"].replace("\\", "/").endswith("Task/my_app/db/app.db")
    assert env["MY_APP_TT_RULES"].replace("\\", "/").endswith("eflow_TT_rules.xlsx")
    assert env["MY_APP_PUSH_RULES"].replace("\\", "/").endswith("eflow_push_rules.xlsx")
    assert env["PYTHONIOENCODING"] == "utf-8"


# ==========================================================
# 降级原因必须可解释（用于把降级暴露到任务结果）
# ==========================================================
def test_reason_is_empty_on_success(monkeypatch, tmp_path):
    script = tmp_path / "fake.py"
    script.write_text("print('OK')", encoding="utf-8")
    monkeypatch.setattr(R, "engine_path", lambda: script)
    text, reason = R.render_with_reason("TT1")
    assert text == "OK"
    assert reason == "", "成功时不应有降级原因"


def test_reason_explains_missing_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "engine_path", lambda: tmp_path / "nope.py")
    text, reason = R.render_with_reason(SAMPLE_TT)
    assert text is None
    assert "不存在" in reason


def test_reason_explains_timeout(monkeypatch, tmp_path):
    """超时的原因文案要点明「可能磁盘忙」。

    实测踩过：引擎单跑 0.3s，但与 pytest 全量并发时超过 60s 被判超时，
    原因是抢磁盘（读 1.5G 的 app.db）。原因里写清楚，运维才知道去查 IO，
    而不是去怀疑引擎代码坏了。
    """
    script = tmp_path / "slow.py"
    script.write_text("import time; time.sleep(30)", encoding="utf-8")
    monkeypatch.setattr(R, "engine_path", lambda: script)
    monkeypatch.setattr(R, "TIMEOUT_SECONDS", 1)
    text, reason = R.render_with_reason("TT1")
    assert text is None
    assert "超时" in reason
    assert "磁盘" in reason


def test_reason_explains_nonzero_exit(monkeypatch, tmp_path):
    script = tmp_path / "fake.py"
    script.write_text("import sys; print('boom'); sys.exit(3)", encoding="utf-8")
    monkeypatch.setattr(R, "engine_path", lambda: script)
    text, reason = R.render_with_reason("TT1")
    assert text is None
    assert "3" in reason


def test_timeout_default_is_generous():
    """超时余量必须足够大。

    **不要把这个值改小**：实测 60s 会在磁盘忙时造成假超时，把完整消息
    （~30 行）静默降级成 6 行头部摘要。正常耗时是 0.3~0.5s，余量大无副作用。
    """
    assert R.TIMEOUT_SECONDS >= 120


# ==========================================================
# 服务集成层：渲染优先级与降级
# ==========================================================
# 渲染入口实现在 tt_alarm_render，但任务入口通过 service 模块的名字调用，
# 故这里打桩要打 **service 上的那个名字**（它 import 进来的绑定）。
def test_service_prefers_engine_output(monkeypatch):
    monkeypatch.setattr(S, "render_message_ex", lambda *a, **k: ("ENGINE OUTPUT", ""))
    assert S.render_message_ex({"tt_no": "TT1", "site_name": "X"})[0] == "ENGINE OUTPUT"


def test_service_falls_back_to_builtin_template(monkeypatch):
    """引擎不可用时退回头部摘要，而不是漏发整条告警。"""
    monkeypatch.setattr(R, "render_with_reason", lambda *a, **k: (None, "引擎超时"))
    msg = R.render_message({"tt_no": "TT1", "site_name": "Loguatuo", "asset_id": "4715"})
    assert msg.split("\n")[0].startswith("TT1 · Loguatuo(4715)")
    assert "[Milestone timeline]" not in msg


def test_service_reports_degradation_reason(monkeypatch):
    """降级原因要能带出来 —— 供任务入口汇总进 errors。"""
    monkeypatch.setattr(R, "render_with_reason", lambda *a, **k: (None, "引擎超时"))
    text, reason = R.render_message_ex({"tt_no": "TT1", "site_name": "X"})
    assert "TT1" in text
    assert reason == "引擎超时"


def test_service_survives_renderer_exception(monkeypatch):
    """渲染器抛异常也必须降级，不能让一条单的分析失败中断整轮告警。"""
    def boom(*a, **k):
        raise RuntimeError("引擎炸了")

    monkeypatch.setattr(R, "render_with_reason", boom)
    text, reason = R.render_message_ex({"tt_no": "TT1", "site_name": "X"})
    assert "TT1" in text
    assert "RuntimeError" in reason


def test_task_result_surfaces_degradation(monkeypatch, tmp_path):
    """任务结果里必须有 degraded 计数与可读的降级说明。

    降级**不报错、照样发得出去**，只是内容从 ~30 行缩成 7 行 ——
    没有这个字段，运维只能靠群里的人问「这次信息怎么这么少」才发现问题。
    """
    from backend.services import tt_alarm_sources as src
    from backend.services import tt_alarm_trigger as trig

    now = datetime.now()
    trig_row = {"tt_no": "TT1", "_alarm_code_norm": "9920",
                "alarm_raised_time": _now(), "_alarm_raised_dt": now,
                "site_id": "1", "site_name": "s"}
    monkeypatch.setattr(trig, "fetch_triggered_tts",
                        lambda *a, **k: ([trig_row],
                                         {"window_since": "x", "table_exists": True,
                                          "truncated": False, "sync_lag_seconds": None}))
    # 实时层查不到 → 镜像兜底给出级别与更新时间（级别命中 P1）
    monkeypatch.setattr(src, "live_tt_rows", lambda tt_nos: {})
    monkeypatch.setattr(src, "mirror_rows", lambda conn, nos: {
        "TT1": {"tt_no": "TT1", "ticket_severity": "P1", "site_name": "s",
                "alarm_occur_time": _now(), "last_modified_time": _now()}})
    _use_db(monkeypatch, tmp_path)   # 日志表落临时 sqlite
    monkeypatch.setattr(S, "render_message_ex", lambda *a, **k: (None, "引擎超时（>120s）"))
    monkeypatch.setattr(S, "dispatch", lambda *a, **k: {"ok": True, "job_id": "j1", "dispatched": 1})
    # 桩必须含 timed_out（与 wait_for_job_result 的真实返回同形）
    monkeypatch.setattr(S, "wait_for_job_result",
                        lambda *a, **k: {"confirmed": True, "ok": True, "timed_out": False,
                                         "sent": ["TT1"], "message_ids": {}, "errors": []})

    out = S.run_tt_alarm_whatsapp_alert()
    assert out["degraded"] == 1
    assert any("降级" in e and "TT1" in e for e in out["errors"]), \
        f"任务结果应显式说明降级，实际 errors={out['errors']}"
    # 降级不影响发送：消息照样投递，只是短了
    assert out["dispatched"] == 1


def test_analyze_lang_defaults_to_english():
    """告警发给利比里亚现场团队，历史上群里用英文。"""
    assert S.ANALYZE_LANG in ("en", "zh")


def test_task_result_reports_due_count(monkeypatch, tmp_path):
    """`out["due"]` 必须是本轮**真实要发**的单数，不能恒为 0。

    2026-10-05 实测缺陷：`out["due"]` 自初始化后再无赋值，于是任务结果里
    出现过 `{"candidates":7,"due":0,"dispatched":6,"sent":6}` 这种自相矛盾的
    组合（due=0 却 dispatched=6），任务管理页永远显示「应发 0 单」，
    调参与排障时看不出本轮到底该发几单。
    """
    from backend.services import tt_alarm_sources as src
    from backend.services import tt_alarm_trigger as trig

    now = datetime.now()
    # 两单：都通过过滤，都应进入 due
    rows = [
        {"tt_no": "TT1", "_alarm_code_norm": "9920", "alarm_raised_time": _now(),
         "_alarm_raised_dt": now, "site_id": "1", "site_name": "s1"},
        {"tt_no": "TT2", "_alarm_code_norm": "9995", "alarm_raised_time": _now(),
         "_alarm_raised_dt": now, "site_id": "2", "site_name": "s2"},
    ]
    monkeypatch.setattr(trig, "fetch_triggered_tts",
                        lambda *a, **k: (rows,
                                         {"window_since": "x", "table_exists": True,
                                          "truncated": False, "sync_lag_seconds": None}))
    monkeypatch.setattr(src, "live_tt_rows", lambda tt_nos: {})
    monkeypatch.setattr(src, "mirror_rows", lambda conn, nos: {
        r["tt_no"]: {"tt_no": r["tt_no"], "ticket_severity": "P1",
                     "site_name": r["site_name"], "alarm_occur_time": _now(),
                     "last_modified_time": _now()}
        for r in rows})
    _use_db(monkeypatch, tmp_path)
    monkeypatch.setattr(S, "render_message_ex", lambda *a, **k: ("msg", None))
    monkeypatch.setattr(S, "dispatch",
                        lambda msgs, groups: {"ok": True, "job_id": "j1",
                                              "dispatched": len(msgs)})
    # 桩必须与 wait_for_job_result 的真实契约同形（含 timed_out）——
    # 少了它任务会在 `out["timed_out"] = rep["timed_out"]` 抛 KeyError。
    monkeypatch.setattr(S, "wait_for_job_result",
                        lambda *a, **k: {"confirmed": True, "ok": True, "timed_out": False,
                                         "sent": ["TT1", "TT2"], "message_ids": {},
                                         "errors": []})

    out = S.run_tt_alarm_whatsapp_alert()
    assert out["candidates"] == 2
    assert out["due"] == 2, f"due 应为本轮要发的单数 2，实际 {out['due']}"
    # due 与 dispatched 语义不同但本轮应一致（无失败）
    assert out["dispatched"] == 2


# ==========================================================
# 真实层：引擎在时才跑（回放用户给的真实单号）
# ==========================================================
requires_engine = pytest.mark.skipif(
    not R.engine_available()
    or not (R._MY_APP_DIR / "backend" / "services" / "eflow_rules"
            / "eflow_TT_rules.xlsx").is_file(),
    reason="分析引擎或规则表 xlsx 不在本机（gitignore 的产物文件），跳过真实回放",
)


@requires_engine
def test_real_engine_matches_user_specified_format():
    """回放真实单号，确认头部 8 行与用户 2026-09-29 指定的格式逐字一致。

    **改动这里的期望值前先确认用户是否改了要求** —— 这 8 行是需求本身，
    不是实现的副产物。
    """
    msg = R.render_tt_analysis(SAMPLE_TT, lang="en")
    assert msg is not None, "真实单号应能分析出来（否则 SQLite 副本可能停止同步了）"
    lines = msg.split("\n")
    for i, expected in enumerate(EXPECTED_HEAD):
        assert lines[i] == expected, f"第 {i + 1} 行与用户要求的格式不一致"


@requires_engine
def test_real_engine_includes_all_three_sections():
    """用户明确要「全发，不截断」：里程碑、派单依据、时效三段都要在。"""
    msg = R.render_tt_analysis(SAMPLE_TT, lang="en")
    assert msg is not None
    for seg in ("[Milestone timeline]", "[Assignment basis]", "[Timeliness]"):
        assert seg in msg, f"缺少 {seg} 段"


@requires_engine
def test_real_engine_returns_none_for_unknown_tt():
    assert R.render_tt_analysis("TT999999999999") is None


# ==========================================================
# 新鲜度：引擎必须看到**刚从 PG 抄出来**的这一单
# ==========================================================
# 背景（2026-09-29 实测踩到）：引擎写死读 `db/app.db`，那是由 pg_to_sqlite_sync
# **每小时第 45 分**刷新的快照；本任务每 15 分钟跑，筛选用的是生产 PG。
# 副本落后时，PG 选出的新单在引擎里查不到 → 退出码 1 → 消息降级成 6 行模板。
# 实测最坏落后 84 分钟（SQLite 最新 16:17 vs PG 17:41，17 点 PG 5 单 / SQLite 0 单）。
# 修法是渲染前用 _snapshot_tt 造一份单行快照。下面把这条链路钉住。

def test_snapshot_writes_eflow_tt_with_all_columns(tmp_path, monkeypatch):
    """快照必须是引擎能直接查的 SQLite：表名 eflow_tt、列名齐全。"""
    _use_db(monkeypatch, tmp_path, eflow_rows=[("TT9", "P1", "9920", _now(), None, "1", "s", "t")])

    path = R._snapshot_tt("TT9")
    try:
        assert path is not None and path.is_file(), "PG 里有这单时应造出快照"
        con = sqlite3.connect(str(path))
        try:
            names = [r[0] for r in con.execute("PRAGMA table_info(eflow_tt)")]
            assert names, "快照里必须有 eflow_tt 表（引擎的查询目标）"
            row = con.execute("SELECT * FROM eflow_tt WHERE tt_no = ?", ("TT9",)).fetchone()
            assert row is not None, "快照里必须含这一单"
            # 引擎只用字符串比较与正则提取，故 TEXT 足够且不会因类型转换抛错
            assert con.execute("SELECT COUNT(*) FROM eflow_tt").fetchone()[0] == 1
        finally:
            con.close()
    finally:
        R._cleanup_snapshot(path)


def test_snapshot_from_live_row_skips_db(tmp_path, monkeypatch):
    """调用方已备好行（实时查单行）时直接用它造快照，不再查库。

    这是「刚触发、镜像里还没有的新单」也能出完整格式的关键 ——
    引擎读快照时按实际列取交集，实时行的紧凑字段集不会让它报错。
    """
    # get_raw_connection 一被调用就炸：断言这条路真的没走
    from backend import database as db
    monkeypatch.setattr(db, "get_raw_connection",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应查库")))

    live_row = {"tt_no": "TTX", "ticket_severity": "P1",
                "alarm_occur_time": _now(), "site_name": "LEC", "_tt_live_raw": {"x": 1}}
    path = R._snapshot_tt("TTX", row=live_row)
    try:
        assert path is not None and path.is_file()
        con = sqlite3.connect(str(path))
        try:
            # PRAGMA table_info 行结构是 (cid, name, type, ...)，列名在 r[1]
            names = {r[1] for r in con.execute("PRAGMA table_info(eflow_tt)")}
            assert "tt_no" in names and "ticket_severity" in names
            assert "_tt_live_raw" not in names, "内部键不应进快照"
            row = con.execute("SELECT tt_no, site_name FROM eflow_tt").fetchone()
            assert row == ("TTX", "LEC")
        finally:
            con.close()
    finally:
        R._cleanup_snapshot(path)


def test_snapshot_is_none_for_missing_tt(tmp_path, monkeypatch):
    """查不到的单返回 None → 调用方退回镜像库，而不是崩。"""
    _use_db(monkeypatch, tmp_path, eflow_rows=[("TT1", "P1", "9920", _now(), None, "1", "s", "t")])
    path = R._snapshot_tt("TT-NOT-EXIST")
    assert path is None
    R._cleanup_snapshot(path)


def test_cleanup_removes_file_and_dir(tmp_path, monkeypatch):
    """快照用完必须删干净（临时文件不清理会堆满磁盘）。"""
    _use_db(monkeypatch, tmp_path, eflow_rows=[("TT9", "P1", "9920", _now(), None, "1", "s", "t")])
    path = R._snapshot_tt("TT9")
    assert path is not None
    parent = path.parent
    R._cleanup_snapshot(path)
    assert not path.exists(), "快照文件未删除"
    assert not parent.exists(), "快照目录未删除"


def test_render_passes_db_override_to_engine(monkeypatch):
    """render_with_reason 必须把快照路径传给子进程的 MY_APP_DB。

    这条是**防回归的关键**：若哪天有人把 `_run_engine(..., snapshot)` 改回
    `_engine_env()` 不带参数，引擎又会去读滞后镜像，降级会静默回来。
    """
    seen = {}
    monkeypatch.setattr(R, "engine_path", lambda: Path(__file__))

    def fake_run(cmd, **kw):
        seen["db"] = kw.get("env", {}).get("MY_APP_DB")
        raise subprocess.TimeoutExpired(cmd, 1)   # 借超时退出，不真跑引擎

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    monkeypatch.setattr(R, "_snapshot_tt", lambda tt, row=None: Path("X:/snap/tt.db"))
    monkeypatch.setattr(R, "_cleanup_snapshot", lambda p: None)

    R.render_with_reason("TT9", lang="en")
    assert seen.get("db") is not None, "未把快照路径传给引擎"
    assert "snap" in str(seen["db"]).replace("\\", "/"), \
        f"应传快照路径，实际传了 {seen.get('db')}"


def test_render_still_runs_when_snapshot_unavailable(monkeypatch):
    """拿不到快照时必须照跑（用镜像库），不能因快照失败就漏发整条告警。"""
    seen = {}
    monkeypatch.setattr(R, "engine_path", lambda: Path(__file__))

    def fake_run(cmd, **kw):
        seen["db"] = kw.get("env", {}).get("MY_APP_DB")
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(R.subprocess, "run", fake_run)
    monkeypatch.setattr(R, "_snapshot_tt", lambda tt, row=None: None)   # 快照失败

    R.render_with_reason("TT9", lang="en")
    assert seen.get("db"), "快照不可用时也应给引擎一个库路径"
    assert "app.db" in str(seen["db"]), "应退回镜像库 db/app.db"

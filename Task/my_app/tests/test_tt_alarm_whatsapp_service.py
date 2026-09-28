# -*- coding: utf-8 -*-
"""TT 告警 WhatsApp 推送：纯函数单测（不连库、不打网络，可安全被 pytest 收集）。

覆盖三类真正会出错的地方：
  1. 告警码归一化 —— 库里 '99933' 与 '99933.0' 并存，只判前者会漏掉该排除的那批；
  2. 消息渲染 —— 字段兜底与「0 不渲染成 0」的规则（实测 27254 行 down_site_count='0'）；
  3. 重推节流 —— 20 分钟语义（无记录发 / 失败发 / 未到期不发 / 到期发）。

渲染断言以需求样例单 TT202609270103 为基准（该单字段已 2026-09-28 从库中核对）。
配置项（级别/告警码白名单/时间窗/群组）的用例在 test_tt_alarm_config.py。
"""
from datetime import datetime

from backend.services import tt_alarm_whatsapp_service as S
from backend.services.tt_alarm_message import split_multi


# ---------------- 1. 告警码归一化 ----------------

def test_norm_alarm_code_strips_float_tail():
    # 这两种形态在库里真实并存（'99933' 2159 行 / '99933.0' 16599 行）
    assert S.norm_alarm_code("99933") == "99933"
    assert S.norm_alarm_code("99933.0") == "99933"
    assert S.norm_alarm_code(99933.0) == "99933"
    assert S.norm_alarm_code(" 9920 ") == "9920"
    assert S.norm_alarm_code("9920.0") == "9920"


def test_norm_alarm_code_empty_and_none():
    assert S.norm_alarm_code(None) == ""
    assert S.norm_alarm_code("") == ""
    assert S.norm_alarm_code("nan") == ""


def test_99933_both_forms_normalize_to_same_code():
    """两种写法的 99933 归一化后必须相等（这正是不能写进 SQL 的原因）。

    注意归属已变：99933 不再由代码硬编码排除，而是**默认不在告警码白名单里**故被排除；
    用户若把它填进白名单就会推送。此处只锁定归一化行为。
    """
    for raw in ("99933", "99933.0", 99933.0):
        assert S.norm_alarm_code(raw) == "99933"


# ---------------- 2. 消息渲染 ----------------

def _sample_row(**kw):
    """需求样例单 TT202609270103 的字段快照（2026-09-28 从 eflow_tt 实测）。"""
    base = {
        "tt_no": "TT202609270103",
        "site_id": "4530",
        "site_name": "Ganta 4",
        "region_level1": "Nimba",
        "site_type": "NORMAL",
        "site_information": "REGULAR",
        "title": " 4530.[Ganta 4]Complete site down (CSD)",
        "alarm_code": "9920",
        "alarm_severity": "Critical",
        "domain": "RAN",
        "alarm_type": "Communication Alarm",
        "sub_alarm_ne_name": "BSC1(1);\nGanta 4",
        "sub_alarm_ne_ip": "10.17.17.129;\n129.0.1.1",
        "sub_alarm_name": "2G SITE DOWN;\n3G SITE DOWN;\n4G SITE DOWN",
        "specific_problem": "Complete site down (CSD)",
        "impacted_service": "2G,3G,4G",
        "site_outage": "Yes",
        "down_site_count": "1",
        "vip_site": "Yes",
        "ticket_severity": "P1",
        "_alarm_code_norm": "9920",
    }
    base.update(kw)
    return base


def test_build_message_matches_reference_sample():
    """逐行对照需求里给出的样例（这是本任务的验收基准）。"""
    expected = "\n".join([
        "TT202609270103 · Ganta 4(4530) | Nimba | Site type NORMAL | Site subtype REGULAR",
        "Title: 4530.[Ganta 4]Complete site down (CSD)",
        "Alarm: 9920(Critical) | RAN | Communication Alarm",
        "Alarm object: BSC1(1)/Ganta 4 | 10.17.17.129/129.0.1.1 | 2G SITE DOWN",
        "Impact: 2G,3G,4G outage | site outage | 1 site(s) down | VIP Yes",
        "Severity: P1 (matches rule)",
    ])
    assert S.build_tt_message(_sample_row()) == expected


def test_message_is_exactly_six_lines():
    assert len(S.build_tt_message(_sample_row()).split("\n")) == 6


def test_zero_down_site_count_is_not_rendered_as_zero():
    """实测 27254 行 down_site_count='0'：属「无断站」，不得渲染成 '0 site(s) down'。"""
    msg = S.build_tt_message(_sample_row(down_site_count="0", site_outage="No"))
    assert "0 site(s) down" not in msg
    assert "site outage" not in msg
    assert "Impact: 2G,3G,4G outage | VIP Yes" in msg


def test_missing_values_render_as_dash_not_zero():
    """取不到值显示 —，不得显示成 0（AGENTS.md 三.6）。"""
    row = _sample_row(down_site_count=None, vip_site=None, region_level1=None,
                      site_type=None, site_information=None, impacted_service=None,
                      site_outage=None)
    msg = S.build_tt_message(row)
    first = msg.split("\n")[0]
    assert "Site type —" in first and "Site subtype —" in first
    assert "| — |" in first
    assert "Impact: —" in msg


def test_alarm_object_falls_back_for_legacy_rows():
    """历史遗留未清除单的 sub_alarm_* 实测全为空，须回退到 ne_name / specific_problem。"""
    row = _sample_row(sub_alarm_ne_name=None, sub_alarm_ne_ip=None, sub_alarm_name=None,
                      ne_name="Ganta 4")
    line = S.build_tt_message(row).split("\n")[3]
    assert line.startswith("Alarm object: ")
    assert "Ganta 4" in line and "Complete site down (CSD)" in line
    assert line != "Alarm object: —"


def test_alarm_object_dash_when_everything_missing():
    row = _sample_row(sub_alarm_ne_name=None, sub_alarm_ne_ip=None, sub_alarm_name=None,
                      ne_name=None, specific_problem=None, alarm_description=None)
    assert S.build_tt_message(row).split("\n")[3] == "Alarm object: —"


def test_multi_value_split_handles_semicolon_and_newline():
    assert split_multi("BSC1(1);\nGanta 4") == ["BSC1(1)", "Ganta 4"]
    assert split_multi("a;b;c") == ["a", "b", "c"]
    assert split_multi("") == []
    assert split_multi(None) == []


def test_alarm_code_from_row_when_norm_missing():
    """未经 fetch 构造的行（无 _alarm_code_norm）也要能正确渲染告警码。"""
    row = _sample_row(alarm_code="9920.0")
    row.pop("_alarm_code_norm")
    assert "Alarm: 9920(Critical)" in S.build_tt_message(row)


# ---------------- 3. 重推节流（20 分钟） ----------------

_NOW = datetime(2026, 9, 28, 20, 0, 0)


def test_due_when_no_record():
    assert S.is_due(None, _NOW) is True


def test_due_when_previous_attempt_failed():
    rec = {"send_status": "N", "last_send_time": "2026-09-28 19:59:00"}
    assert S.is_due(rec, _NOW) is True


def test_not_due_within_throttle_window():
    rec = {"send_status": "Y", "last_send_time": "2026-09-28 19:55:00"}
    assert S.is_due(rec, _NOW) is False


def test_due_exactly_at_throttle_boundary():
    rec = {"send_status": "Y", "last_send_time": "2026-09-28 19:40:00"}
    assert S.is_due(rec, _NOW) is True


def test_due_when_sent_long_ago_regardless_of_tt_update():
    """单子信息没有更新时也要继续推 —— 这正是需求里的 20 分钟语义。"""
    rec = {"send_status": "Y", "last_send_time": "2026-09-28 19:00:00"}
    assert S.is_due(rec, _NOW) is True


def test_due_when_status_y_but_time_unparsable():
    assert S.is_due({"send_status": "Y", "last_send_time": None}, _NOW) is True
    assert S.is_due({"send_status": "Y", "last_send_time": "bogus"}, _NOW) is True


def test_select_due_filters_and_keeps_order():
    rows = [{"tt_no": "A"}, {"tt_no": "B"}, {"tt_no": "C"}]
    records = {
        "A": {"send_status": "Y", "last_send_time": "2026-09-28 19:58:00"},  # 节流内 → 跳过
        "B": {"send_status": "N", "last_send_time": "2026-09-28 19:58:00"},  # 失败 → 发
    }
    due = S.select_due_tts(rows, records, _NOW)
    assert [r["tt_no"] for r in due] == ["B", "C"]


# ---------------- 4. 时间解析 ----------------

def test_parse_ts_accepts_project_formats():
    assert S._parse_ts("2026-09-28 20:00:00") == _NOW
    assert S._parse_ts("2026-09-28 20:00") == _NOW
    assert S._parse_ts("2026-09-28") == datetime(2026, 9, 28)


def test_parse_ts_rejects_garbage():
    for bad in (None, "", "None", "nan", "not-a-date"):
        assert S._parse_ts(bad) is None


# ---------------- 5. 投递守卫 ----------------

def test_dispatch_refuses_empty_group_list():
    """显式传空群组列表 → 拒投递（群组是必填的投递地址）。

    注意：任务入口在群组为空时会先回退到 DEFAULT_GROUPS（见 test_group_fallback_*），
    所以正常路径不会走到这里；此断言锁的是「有人显式传空列表」这个底层契约。
    """
    res = S.dispatch([{"tt_no": "T1", "text": "x"}], groups=[])
    assert res["ok"] is False
    assert res["dispatched"] == 0
    assert res["errors"]


def test_dispatch_refuses_empty_messages():
    res = S.dispatch([], groups=["g1"])
    assert res["ok"] is False and res["dispatched"] == 0


# ---------------- 7. 窗口字段锁定：只认 alarm_occur_time ----------------

def test_window_anchor_is_alarm_occur_time_not_created_or_modified(tmp_path, monkeypatch):
    """「近 N 小时」必须按 alarm_occur_time 判，不得按 created_time / last_modified_time。

    用 sqlite 临时库造 3 张时间字段互相矛盾的单，断言只有「occur 在窗口内」的被选中。
    这个断言存在的意义：三个时间字段选错**不会报错**，只会静默漏单/多单，
    而需求方（业务）明确口径就是「告警发生时间」。
    """
    import sqlite3
    from datetime import timedelta

    from backend import database as db
    from backend.services import tt_alarm_whatsapp_service as svc2

    monkeypatch.setattr(db, "DB_MODE", "sqlite")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "win.db")

    now = datetime.now()
    new = (now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    old = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(tmp_path / "win.db")
    conn.execute(
        "CREATE TABLE eflow_tt (tt_no TEXT, ticket_severity TEXT, alarm_code TEXT, "
        "alarm_occur_time TEXT, alarm_clear_time TEXT, created_time TEXT, "
        "last_modified_time TEXT, site_id TEXT, site_name TEXT, title TEXT)")
    for tt, occur, created in (("A_occur_new", new, old),
                               ("B_created_new", old, new),
                               ("C_all_new", new, new)):
        conn.execute("INSERT INTO eflow_tt VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (tt, "P1", "9920", occur, None, created, created, "1", "s", "t"))
    conn.commit()
    conn.close()

    picked, _meta = svc2.fetch_candidate_tts()
    assert [r["tt_no"] for r in picked] == ["A_occur_new", "C_all_new"], \
        "窗口锚点不是 alarm_occur_time —— B 单 occur 在窗口外却被选中了"


def test_window_excludes_rows_with_unparsable_occur_time(tmp_path, monkeypatch):
    """alarm_occur_time 为空/非法的行不能入选（无法判定是否在窗口内）。"""
    import sqlite3

    from backend import database as db
    from backend.services import tt_alarm_whatsapp_service as svc2

    monkeypatch.setattr(db, "DB_MODE", "sqlite")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "win2.db")

    now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(tmp_path / "win2.db")
    conn.execute(
        "CREATE TABLE eflow_tt (tt_no TEXT, ticket_severity TEXT, alarm_code TEXT, "
        "alarm_occur_time TEXT, alarm_clear_time TEXT)")
    conn.execute("INSERT INTO eflow_tt VALUES ('OK','P1','9920',?,NULL)", (now_s,))
    conn.execute("INSERT INTO eflow_tt VALUES ('NO_TIME','P1','9920',NULL,NULL)")
    conn.execute("INSERT INTO eflow_tt VALUES ('BAD_TIME','P1','9920','bogus',NULL)")
    conn.commit()
    conn.close()

    picked, _meta = svc2.fetch_candidate_tts()
    assert [r["tt_no"] for r in picked] == ["OK"]


def test_window_uses_uncleared_definition(tmp_path, monkeypatch):
    """「未清除」= alarm_clear_time 为空；已清除的单必须排除。"""
    import sqlite3

    from backend import database as db
    from backend.services import tt_alarm_whatsapp_service as svc2

    monkeypatch.setattr(db, "DB_MODE", "sqlite")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "win3.db")

    now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(tmp_path / "win3.db")
    conn.execute(
        "CREATE TABLE eflow_tt (tt_no TEXT, ticket_severity TEXT, alarm_code TEXT, "
        "alarm_occur_time TEXT, alarm_clear_time TEXT)")
    conn.execute("INSERT INTO eflow_tt VALUES ('UNCLEARED','P1','9920',?,NULL)", (now_s,))
    conn.execute("INSERT INTO eflow_tt VALUES ('CLEARED','P1','9920',?,?)", (now_s, now_s))
    conn.execute("INSERT INTO eflow_tt VALUES ('BLANK_CLEAR','P1','9920',?,'')", (now_s,))
    conn.commit()
    conn.close()

    picked, _meta = svc2.fetch_candidate_tts()
    assert sorted(r["tt_no"] for r in picked) == ["BLANK_CLEAR", "UNCLEARED"], \
        "「未清除」口径不对：已清除的单被选入，或空串未被当作未清除"


# ---------------- 6. 作业状态机（tt_alarm_job） ----------------

def test_job_state_machine_roundtrip(tmp_path, monkeypatch):
    """pending → running → done 全链路；且认领后不可重复认领。"""
    from backend.services import tt_alarm_job as J
    monkeypatch.setattr(J, "JOB_FILE", tmp_path / "job.json")

    assert J.claim_pending_job() is None          # 无作业
    disp = J.dispatch([{"tt_no": "T1", "text": "hi"}], ["g1"])
    assert disp["ok"] is True and disp["dispatched"] == 1

    job = J.claim_pending_job()                    # 认领
    assert job["status"] == "running" and job["kind"] == "text"
    assert J.claim_pending_job() is None           # 不可重复认领

    assert J.complete_job(disp["job_id"], {"ok": True, "sent": ["T1"]}) is True
    done = J.read_job()
    assert done["status"] == "done" and done["result"]["sent"] == ["T1"]


def test_complete_job_rejects_stale_job_id(tmp_path, monkeypatch):
    from backend.services import tt_alarm_job as J
    monkeypatch.setattr(J, "JOB_FILE", tmp_path / "job.json")
    J.dispatch([{"tt_no": "T1", "text": "hi"}], ["g1"])
    assert J.complete_job("bogus-id", {"ok": True, "sent": ["T1"]}) is False


def test_wait_for_job_result_times_out_unconfirmed(tmp_path, monkeypatch):
    """超时必须返回 confirmed=False —— 调用方据此不得置 'Y'。"""
    from backend.services import tt_alarm_job as J
    monkeypatch.setattr(J, "JOB_FILE", tmp_path / "job.json")
    disp = J.dispatch([{"tt_no": "T1", "text": "hi"}], ["g1"])
    rep = J.wait_for_job_result(disp["job_id"], wait_seconds=1)
    assert rep["confirmed"] is False and rep["timed_out"] is True
    assert rep["ok"] is False and rep["sent"] == []


def test_wait_for_job_result_picks_up_report(tmp_path, monkeypatch):
    from backend.services import tt_alarm_job as J
    monkeypatch.setattr(J, "JOB_FILE", tmp_path / "job.json")
    disp = J.dispatch([{"tt_no": "T1", "text": "hi"}], ["g1"])
    J.claim_pending_job()
    J.complete_job(disp["job_id"], {"ok": True, "sent": ["T1"], "errors": []})
    rep = J.wait_for_job_result(disp["job_id"], wait_seconds=3)
    assert rep["confirmed"] is True and rep["ok"] is True and rep["sent"] == ["T1"]


def test_job_file_is_valid_utf8_json(tmp_path, monkeypatch):
    """中文消息要能往返（ensure_ascii=False，避免中文被转义成 \\uXXXX）。"""
    from backend.services import tt_alarm_job as J
    monkeypatch.setattr(J, "JOB_FILE", tmp_path / "job.json")
    J.dispatch([{"tt_no": "T1", "text": "告警未清除 · 站点断站"}], ["群组"])
    raw = (tmp_path / "job.json").read_text(encoding="utf-8")
    assert "告警未清除" in raw and "群组" in raw
    assert J.read_job()["messages"][0]["text"] == "告警未清除 · 站点断站"

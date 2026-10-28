# -*- coding: utf-8 -*-
"""TT 告警 WhatsApp 推送：纯函数单测（不连库、不打网络，可安全被 pytest 收集）。

覆盖几类真正会出错的地方：
  1. 告警码归一化 —— 库里 '99933' 与 '99933.0' 并存，只判前者会漏掉该排除的那批；
  2. 消息渲染 —— 字段兜底、「0 不渲染成 0」、Occurred 行、重报横幅；
  3. 发送决策 `decide_push` —— 首推 / 双档重报（无更新 10m / 有更新 30m）/ 冷却 / 未知退化；
  4. 级别白名单 `severity_passes` —— 「留空 = 不过滤」不是「一单都不发」；
  5. 三层来源合并 `merged_render_row` —— 实时 > 镜像 > 触发行。

配置项（级别/告警码白名单/窗口/群组）的用例在 test_tt_alarm_config.py；
触发扫描（realtime_alarm 口径）在 test_tt_alarm_trigger.py。
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

    注意归属：99933 不由代码硬编码排除，而是**默认不在告警码白名单里**故被排除；
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
        "alarm_occur_time": "2026-09-27 01:03:00",
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


def test_build_message_contains_occurred_line():
    """告警发生时间是消息最关键的元素之一，降级模板里绝不能缺。"""
    msg = S.build_tt_message(_sample_row())
    assert msg.split("\n")[1] == "Occurred: 2026-09-27 01:03:00"


def test_build_message_severity_line_does_not_claim_rule_match():
    """降级模板没跑过规则引擎，绝不能谎报 '(matches rule)'（完整引擎输出才带判定）。"""
    msg = S.build_tt_message(_sample_row())
    assert "Severity: P1" in msg
    assert "matches rule" not in msg


def test_message_is_exactly_seven_lines():
    assert len(S.build_tt_message(_sample_row()).split("\n")) == 7


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
    line = S.build_tt_message(row).split("\n")[4]
    assert line.startswith("Alarm object: ")
    assert "Ganta 4" in line and "Complete site down (CSD)" in line
    assert line != "Alarm object: —"


def test_alarm_object_dash_when_everything_missing():
    row = _sample_row(sub_alarm_ne_name=None, sub_alarm_ne_ip=None, sub_alarm_name=None,
                      ne_name=None, specific_problem=None, alarm_description=None)
    assert S.build_tt_message(row).split("\n")[4] == "Alarm object: —"


def test_multi_value_split_handles_semicolon_and_newline():
    assert split_multi("BSC1(1);\nGanta 4") == ["BSC1(1)", "Ganta 4"]
    assert split_multi("a;b;c") == ["a", "b", "c"]
    assert split_multi("") == []
    assert split_multi(None) == []


def test_alarm_code_from_row_when_norm_missing():
    """未经来源层构造的行（无 _alarm_code_norm）也要能正确渲染告警码。"""
    row = _sample_row(alarm_code="9920.0")
    row.pop("_alarm_code_norm")
    assert "Alarm: 9920(Critical)" in S.build_tt_message(row)


def test_alarm_description_appears_as_codename_in_alarm_line():
    """2026-10-08：eFlow 告警码中文名（`alarm_description`，如 "MW LINK DOWN"）
    拼在 `Alarm:` 行，紧跟 `Alarm code (severity)`、位于 `domain | alarm_type` 之前。

    期望格式：`Alarm: 9995(Critical) | codename: MW LINK DOWN | Communication Alarm`。
    缺 `alarm_description` 时不输出 codename 段（与 domain/alarm_type 同语义）。
    """
    row = _sample_row(alarm_code="9995", _alarm_code_norm="9995", alarm_description="MW LINK DOWN")
    body = S.build_tt_message(row)
    assert "Alarm: 9995(Critical)" in body
    assert "codename: MW LINK DOWN" in body
    # codename 应在 `Alarm:` 行（不是 `Alarm object:`），且在 alarm_type 之前
    alarm_line = next((ln for ln in body.split("\n") if ln.startswith("Alarm:")), "")
    cn_pos = alarm_line.find("codename:")
    at_pos = alarm_line.find("Communication Alarm")
    assert cn_pos > 0, f"codename 段缺失: {alarm_line!r}"
    assert cn_pos < at_pos, f"codename 应在 alarm_type 之前: {alarm_line!r}"


def test_alarm_description_absent_omits_codename_segment():
    """`alarm_description` 缺值时，`Alarm:` 行不带 codename 段（不输出空段、不报错）。"""
    row = _sample_row(alarm_code="9920")
    row.pop("alarm_description", None)
    body = S.build_tt_message(row)
    assert "codename" not in body
    # 仍要保证 Alarm: 9920(Critical) | RAN | Communication Alarm 三段都在
    assert "Alarm: 9920(Critical) | RAN | Communication Alarm" in body


def test_live_row_renders_without_missing_key_errors():
    """实时查单行（base/list 紧凑字段集）缺大量列时也能渲染，不抛 KeyError。"""
    live = {"tt_no": "TT202610050001", "site_name": "LEC", "site_id": "5002",
            "alarm_occur_time": "2026-10-05 08:00:00", "alarm_code": "9971",
            "alarm_severity": "Critical", "ticket_severity": "P1"}
    msg = S.build_tt_message(live)
    assert msg.startswith("TT202610050001 · LEC(5002)")
    assert "Occurred: 2026-10-05 08:00:00" in msg


# ---------------- 2b. 重报横幅 ----------------

def test_reminder_banner_format():
    assert S.reminder_banner(3, 125, 22) == \
        "⚠️ REMINDER #3 · open 2h05m · no update for 22m"
    assert S.reminder_banner(2, 45, 20) == \
        "⚠️ REMINDER #2 · open 45m · no update for 20m"


def test_reminder_banner_clamps_negatives():
    assert "open 0m" in S.reminder_banner(2, -5, -1)


# ---------------- 3. 发送决策 decide_push（双档重报：无更新 10m / 有更新 30m） ----------------

_NOW = datetime(2026, 10, 5, 10, 25, 0)


def _rec(**kw):
    """默认记录：距上次发送 25m、上次发送后工单**无更新**（更新点早于发送）。"""
    base = {
        "send_status": "Y",
        "last_send_time": "2026-10-05 10:00:00",          # 25 分钟前
        "first_seen_time": "2026-10-05 09:00:00",
        "last_known_update_time": "2026-10-05 09:30:00",  # 早于发送 → 无更新档
    }
    base.update(kw)
    return base


def test_first_push_when_no_record():
    assert S.decide_push(None, _NOW) == (True, "first")


def test_no_update_tier_repushes_at_stall_interval():
    """无更新档：距上次发送 25m ≥ 10m → 催报（stalled）。"""
    assert S.decide_push(_rec(), _NOW) == (True, "stalled")


def test_no_update_tier_within_stall_interval_is_cooldown():
    """无更新档但距上次发送只有 5m（<10m）→ 冷却中。"""
    rec = _rec(last_send_time="2026-10-05 10:20:00")
    assert S.decide_push(rec, _NOW) == (False, "cooldown")


def test_update_tier_waits_longer_than_stall():
    """有更新档：上次发送后工单动过，距发送 25m（≥10 但 <30）→ 仍冷却，别打扰。"""
    rec = _rec(last_send_time="2026-10-05 10:00:00",     # 25m 前
               last_known_update_time="2026-10-05 10:10:00")  # 发送后更新过
    assert S.decide_push(rec, _NOW) == (False, "cooldown")


def test_update_tier_repushes_at_resend_interval():
    """有更新档：距上次发送 40m ≥ 30m → 重报（updating）。"""
    rec = _rec(last_send_time="2026-10-05 09:45:00",     # 40m 前
               last_known_update_time="2026-10-05 10:10:00")
    assert S.decide_push(rec, _NOW) == (True, "updating")


def test_live_update_time_beats_recorded_one():
    """实时查到的更新时间比记录里的新：以实时为准 → 落入较缓的有更新档。"""
    rec = _rec(last_known_update_time="2026-10-05 09:00:00",
               last_send_time="2026-10-05 10:00:00")     # 25m 前
    from datetime import datetime as dt
    live_upd = dt(2026, 10, 5, 10, 15)                   # 发送后有更新
    # 有更新档需 30m，25m 不够 → 冷却
    assert S.decide_push(rec, _NOW, last_modified_dt=live_upd) == (False, "cooldown")
    # 若已过 30m（拉到 09:50 发送、40m 前）→ 放行
    rec2 = _rec(last_known_update_time="2026-10-05 09:00:00",
                last_send_time="2026-10-05 09:45:00")
    assert S.decide_push(rec2, _NOW, last_modified_dt=live_upd) == (True, "updating")


def test_stale_unknown_update_falls_back_to_stall_interval():
    """更新时间完全不可知 → 按较短的**无更新档**节流，绝不静默停推。"""
    rec = _rec(last_known_update_time="")                # 25m 前发送
    assert S.decide_push(rec, _NOW) == (True, "stale-unknown-update")
    rec2 = _rec(last_known_update_time="", last_send_time="2026-10-05 10:20:00")
    assert S.decide_push(rec2, _NOW) == (False, "cooldown")


def test_never_confirmed_send_retries():
    """从未确认送达（send_status=N 且无 last_send_time）的重试路径。

    * 更新时间已知且早于首见（无更新档），首见满 10m → 按无更新档重报；
    * 更新时间未知 → 退回首见时间起算的无更新档节流，首见 25m 后放行。
    """
    rec = _rec(send_status="N", last_send_time=None,
               first_seen_time="2026-10-05 10:00:00",
               last_known_update_time="2026-10-05 09:00:00")
    assert S.decide_push(rec, _NOW) == (True, "stalled")
    rec_unknown = _rec(send_status="N", last_send_time=None,
                       first_seen_time="2026-10-05 10:00:00",
                       last_known_update_time="")
    assert S.decide_push(rec_unknown, _NOW) == (True, "stale-unknown-update")
    # 首见才 5 分钟（且从未成功送达）→ 仍在节流内，下一轮再试
    rec_soon = _rec(send_status="N", last_send_time=None,
                    first_seen_time="2026-10-05 10:20:00",
                    last_known_update_time="")
    assert S.decide_push(rec_soon, _NOW) == (False, "cooldown")


def test_custom_intervals():
    """两档间隔都可显式覆盖。"""
    # 无更新档：距发送 5m，默认 10m 冷却；放宽 stall_minutes=1 → 放行
    rec = _rec(last_send_time="2026-10-05 10:20:00")
    assert S.decide_push(rec, _NOW)[0] is False
    assert S.decide_push(rec, _NOW, stall_minutes=1) == (True, "stalled")
    # 有更新档：距发送 25m，默认 30m 冷却；放宽 resend_minutes=20 → 放行
    rec2 = _rec(last_send_time="2026-10-05 10:00:00",
                last_known_update_time="2026-10-05 10:10:00")
    assert S.decide_push(rec2, _NOW)[0] is False
    assert S.decide_push(rec2, _NOW, resend_minutes=20) == (True, "updating")


# ---------------- 3b. 级别白名单 ----------------

def test_empty_severities_means_no_filter_not_drop_all():
    """级别留空 = 不过滤（推送所有级别），**不是**一单都不发。

    回归锁：曾写成 `if sev not in SEVERITIES: continue`，空集时每一行都被 continue
    （`x in set()` 恒为 False），表现为「级别留空 → 一单都不发」。
    实测于 2026-09-28，2026-10-05 重构后由 severity_passes 纯函数继续锁定。
    """
    assert S.severity_passes("P4", severities=set()) is True
    assert S.severity_passes("p2", severities=set()) is True


def test_severity_filter_still_applies_when_set():
    assert S.severity_passes("P1", severities={"P1"}) is True
    assert S.severity_passes("P4", severities={"P1"}) is False
    assert S.severity_passes("p1", severities={"P1"}) is True   # 大小写不敏感
    assert S.severity_passes(None, severities={"P1"}) is False  # 空级别不通过


# ---------------- 3c. 三层来源合并（tt_alarm_sources） ----------------

def test_merged_render_row_live_wins_over_mirror_over_trigger():
    from backend.services.tt_alarm_sources import merged_render_row
    trig = {"tt_no": "T1", "site_name": "触发行站", "status": "trig"}
    mirror = {"tt_no": "T1", "site_name": "镜像站", "status": "mirror", "vip_site": "Yes"}
    live = {"tt_no": "T1", "site_name": "实时站", "last_modified_time": "2026-10-05 10:00:00"}
    row = merged_render_row(trig, mirror, live)
    assert row["site_name"] == "实时站"          # 实时最优先
    assert row["vip_site"] == "Yes"             # 镜像独有字段保留
    assert row["status"] == "mirror"            # 镜像覆盖触发行


def test_merged_render_row_falls_back_to_raised_time():
    """实时/镜像都没有 alarm_occur_time 时，退回触发行的告警升起时间。"""
    from backend.services.tt_alarm_sources import merged_render_row
    trig = {"tt_no": "T1", "alarm_raised_time": "2026-10-05 09:00:00"}
    row = merged_render_row(trig, {"site_name": "x"}, {"ticket_severity": "P1"})
    assert row["alarm_occur_time"] == "2026-10-05 09:00:00"


def test_merged_render_row_live_occur_time_wins():
    from backend.services.tt_alarm_sources import merged_render_row
    trig = {"tt_no": "T1", "alarm_raised_time": "2026-10-05 09:00:00"}
    row = merged_render_row(trig, None, {"alarm_occur_time": "2026-10-05 09:30:00"})
    assert row["alarm_occur_time"] == "2026-10-05 09:30:00"


def test_merged_render_row_empty_live_does_not_blank_mirror():
    """实时行里的空串**不能**覆盖镜像的真值（2026-10-28 修复）。

    eFlow `base/list` 实测会返回空的 `subAlarmName`，也不返回 `downSiteList`；
    裸 update() 会把镜像里的告警对象抹成空，群里就只剩
    「Alarm: 9995 | Communication Alarm」这种没有语义的行。
    """
    from backend.services.tt_alarm_sources import merged_render_row
    trig = {"tt_no": "T1"}
    mirror = {"sub_alarm_name": "2G SITE DOWN", "specific_problem": "MW LINK DOWN",
              "down_site_list": "3299,4104"}
    live = {"sub_alarm_name": "", "specific_problem": "", "down_site_list": None,
            "status": "WaitFOAccept"}
    row = merged_render_row(trig, mirror, live)
    assert row["sub_alarm_name"] == "2G SITE DOWN"
    assert row["specific_problem"] == "MW LINK DOWN"
    assert row["down_site_list"] == "3299,4104"
    assert row["status"] == "WaitFOAccept"   # 非空的新值仍然覆盖


def test_merged_render_row_backfills_codename_and_impact_sites_from_trigger():
    """触发行的 codename / impact_site_list 要落到 eflow_tt 的同义列上。

    首推时刻那一单通常还没进 `eflow_tt` 镜像，实时行又只有 eflow_tt 的少数字段；
    没有这条回填，`Alarm:` 行就没有 codename（9995 = MW LINK DOWN），
    也没有「Total N impact sites」清单 —— 这正是用户 2026-10-28 反馈的问题。
    """
    from backend.services.tt_alarm_sources import merged_render_row
    trig = {"tt_no": "T1", "codename": "MW LINK DOWN",
            "impact_site_list": "3299,4104,9167", "impact_site_number": "3",
            "neip": "129.0.1.1"}
    row = merged_render_row(trig, None, {"alarm_type": "Communication Alarm"})
    assert row["specific_problem"] == "MW LINK DOWN"
    assert row["alarm_description"] == "MW LINK DOWN"
    assert row["down_site_list"] == "3299,4104,9167"
    assert row["down_site_count"] == "3"
    assert row["sub_alarm_ne_ip"] == "129.0.1.1"


def test_merged_render_row_mirror_wins_over_trigger_backfill():
    """回填只在目标列仍为空时生效 —— 镜像/实时有值就以它们为准。"""
    from backend.services.tt_alarm_sources import merged_render_row
    trig = {"tt_no": "T1", "codename": "MW LINK DOWN", "impact_site_list": "1,2"}
    mirror = {"specific_problem": "Fiber Break", "down_site_list": "9,8,7"}
    row = merged_render_row(trig, mirror, None)
    assert row["specific_problem"] == "Fiber Break"
    assert row["down_site_list"] == "9,8,7"


# ---------------- 4. 时间解析 ----------------

def test_parse_ts_accepts_project_formats():
    assert S._parse_ts("2026-09-28 20:00:00") == datetime(2026, 9, 28, 20, 0, 0)
    assert S._parse_ts("2026-09-28 20:00") == datetime(2026, 9, 28, 20, 0)
    assert S._parse_ts("2026-09-28") == datetime(2026, 9, 28)


def test_parse_ts_rejects_garbage():
    for bad in (None, "", "None", "nan", "not-a-date"):
        assert S._parse_ts(bad) is None


# ---------------- 5. 投递守卫（Baileys 通道，wa_notify_service 同名接口） ----------------

def test_dispatch_refuses_empty_group_list():
    """显式传空群组列表 → 拒投递（群组是必填的投递地址）。

    正常路径任务入口会先回退到 DEFAULT_GROUPS，不会走到这里；
    此断言锁的是「有人显式传空列表」这个底层契约。
    """
    res = S.dispatch([{"tt_no": "T1", "text": "x"}], groups=[])
    assert res["ok"] is False
    assert res["dispatched"] == 0
    assert res["errors"]


def test_dispatch_refuses_empty_messages():
    res = S.dispatch([], groups=["g1"])
    assert res["ok"] is False and res["dispatched"] == 0


# ---------------- 6. 作业状态机（tt_alarm_job，扩展通道自测端点仍在用） ----------------

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


# ---------------- 7. 日志表：建表幂等补列 + 跟踪字段 ----------------

def test_store_ensure_log_table_adds_track_columns_to_legacy_table(tmp_path):
    """老表（没有跟踪列**且没有 last_error**）必须被幂等补列，且原有数据不丢。

    2026-10-07 修正：本用例原先伪造的"老表"里**带着 `last_error`**，于是它
    根本覆盖不到 2026-10-06 的真实事故（老库缺的恰恰是 `last_error`），
    只断言了 TRACK 三列 —— 一条"看起来在测、其实测不到"的用例。
    现按**真·老结构**建表（13 列，无跟踪列、无邮件列、无 last_error）。
    """
    import sqlite3

    from backend.services import tt_alarm_store as store

    db_path = tmp_path / "log.db"
    conn = sqlite3.connect(db_path)
    # 造一张 2026-10-05 之前的**真·老结构**表：无跟踪列、无邮件列、无 last_error
    conn.execute(
        "CREATE TABLE eflow_tt_whatsapp_alert_log ("
        "tt_no TEXT PRIMARY KEY, alarm_occur_time TEXT, ticket_severity TEXT, "
        "alarm_code TEXT, site_id TEXT, site_name TEXT, title TEXT, "
        "send_status TEXT, send_count INTEGER, last_send_time TEXT, "
        "last_tt_modified TEXT, first_seen_time TEXT, updated_time TEXT)")
    conn.execute("INSERT INTO eflow_tt_whatsapp_alert_log "
                 "(tt_no, send_status, send_count, first_seen_time, updated_time) "
                 "VALUES ('T1','Y',2,'2026-09-28 09:00:00','2026-09-28 10:00:00')")
    conn.commit()

    # 前置断言：老表**确实**缺 last_error（否则这条用例又退回盲点状态）
    before = {r[1] for r in conn.execute("PRAGMA table_info(eflow_tt_whatsapp_alert_log)")}
    assert "last_error" not in before, "前置条件：老表本应缺 last_error"

    store.ensure_log_table(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(eflow_tt_whatsapp_alert_log)")}
    assert {"last_alarm_seen_time", "last_known_update_time", "last_check_time"} <= cols
    # 2026-10-06 事故列：必须补上
    assert "last_error" in cols, "补列后仍缺 last_error（事故未修复）"
    # 邮件幂等列同样必须补齐
    assert {"mail_notified_time", "mail_summary_time"} <= cols
    # 原有数据不丢
    row = conn.execute("SELECT send_status, send_count FROM eflow_tt_whatsapp_alert_log "
                       "WHERE tt_no='T1'").fetchone()
    assert row == ("Y", 2)
    conn.close()


def test_store_refresh_tracking_does_not_touch_send_fields(tmp_path):
    """refresh_tracking 只动跟踪列；记录不存在时不创建（不给日志表留垃圾行）。"""
    import sqlite3

    from backend.services import tt_alarm_store as store

    conn = sqlite3.connect(":memory:")
    store.ensure_log_table(conn)

    # 记录不存在 → 不创建
    assert store.refresh_tracking(conn, "GHOST", {"last_check_time": "2026-10-05 10:00:00"}) is False
    assert conn.execute("SELECT COUNT(*) FROM eflow_tt_whatsapp_alert_log").fetchone()[0] == 0

    # 先落一条成功发送记录，再刷跟踪
    store.record_result(conn, {"tt_no": "T1", "site_name": "s"}, ok=True)
    before = dict(zip(("send_status", "send_count", "last_send_time"),
                      conn.execute("SELECT send_status, send_count, last_send_time "
                                   "FROM eflow_tt_whatsapp_alert_log WHERE tt_no='T1'").fetchone()))
    assert store.refresh_tracking(
        conn, "T1", {"last_known_update_time": "2026-10-05 10:00:00",
                     "last_check_time": "2026-10-05 10:01:00",
                     "last_alarm_seen_time": "2026-10-05 10:01:00"}) is True
    after = dict(zip(("send_status", "send_count", "last_send_time"),
                     conn.execute("SELECT send_status, send_count, last_send_time "
                                  "FROM eflow_tt_whatsapp_alert_log WHERE tt_no='T1'").fetchone()))
    assert before == after, "refresh_tracking 不得触碰 send_* 字段"
    got = conn.execute("SELECT last_known_update_time, last_check_time "
                       "FROM eflow_tt_whatsapp_alert_log WHERE tt_no='T1'").fetchone()
    assert got == ("2026-10-05 10:00:00", "2026-10-05 10:01:00")
    conn.close()


def test_store_send_count_counts_confirmed_sends_only(tmp_path):
    """send_status/send_count 就是「发没发过 / 发过几次」：失败不计数、不置 Y。"""
    import sqlite3

    from backend.services import tt_alarm_store as store

    conn = sqlite3.connect(":memory:")
    store.ensure_log_table(conn)
    store.record_result(conn, {"tt_no": "T1"}, ok=False, error="通道离线")
    row = conn.execute("SELECT send_status, send_count FROM eflow_tt_whatsapp_alert_log "
                       "WHERE tt_no='T1'").fetchone()
    assert row == ("N", 0), "失败不得计入发送次数，也不得置 Y"
    store.record_result(conn, {"tt_no": "T1"}, ok=True)
    row = conn.execute("SELECT send_status, send_count, last_error "
                       "FROM eflow_tt_whatsapp_alert_log WHERE tt_no='T1'").fetchone()
    assert row == ("Y", 1, "")


# ---------------- 6. ext 通道 fallback（2026-10-08 引入） ----------------
# 三个用例覆盖 try_ext_fallback 的三种结局：
#   ① 投递失败 → 返回 False、out["ext_fallback"]["ok"]=False
#   ② 投递成功但 0 确认（超时 / 扩展没在跑） → 返回 False、warnings 升级
#   ③ 投递成功且部分单确认 → 返回 True、对应 send_status 置 'Y'、未确认仍 'N'
#
# 实现要点（这是 stub 测试的契约，不是端到端）：
#   - 桩 `tt_alarm_job.dispatch` / `tt_alarm_job.wait_for_job_result` —— 不写盘
#   - 桩 `record_result` —— 只入参校验，不连真实库
#   - 真用 `_parse_ts` / `s` 辅助（业务侧已测）


def _fb_due():
    return [
        {"row": {"tt_no": "TT_FB_1"}, "record": None, "tracking": {"last_check_time": "x"},
         "reminder_no": 1, "wa_text": "t1"},
        {"row": {"tt_no": "TT_FB_2"}, "record": None, "tracking": {"last_check_time": "x"},
         "reminder_no": 1, "wa_text": "t2"},
    ]


def test_ext_fallback_dispatch_fail_returns_false(monkeypatch):
    """Baileys 失败后 ext 通道连投递都失败 —— 整批仍 fail，不悄悄 'Y'。"""
    out = {"warnings": [], "errors": []}
    monkeypatch.setattr("backend.services.tt_alarm_job.dispatch",
                        lambda messages, groups: {
                            "ok": False, "job_id": None, "dispatched": 0,
                            "errors": ["扩展未启动（连接失败）"],
                        })
    monkeypatch.setattr("backend.services.tt_alarm_job.wait_for_job_result",
                        lambda *a, **k: {"confirmed": False, "ok": False,
                                          "sent": [], "errors": []})
    sent_log = []

    def _rec_stub(*a, **k):
        sent_log.append((a, k))
    monkeypatch.setattr("backend.services.tt_alarm_whatsapp_service.record_result", _rec_stub)

    ok = S.try_ext_fallback(
        out, [{"tt_no": "TT_FB_1", "text": "t1"}, {"tt_no": "TT_FB_2", "text": "t2"}],
        ["P1 Group"], _fb_due(), {}, fallback_reason="baileys_zero_confirmed")

    assert ok is False
    assert out["ext_fallback"]["attempted"] is True
    assert out["ext_fallback"]["ok"] is False
    # 投递失败时不应该再调 wait_for_job_result（避免无意义等待）
    # record_result 也不该被 try_ext_fallback 调（落 'N' 是调用方的活）
    assert sent_log == [], f"投递失败时不应 record_result，但记录到 {sent_log}"
    # 至少一条 warning 说明 fallback 失败
    assert any("ext 通道 fallback **投递失败**" in w for w in out["warnings"])


def test_ext_fallback_zero_confirmed_marks_n(monkeypatch):
    """扩展**收到了**作业但 0 确认（典型：扩展没在跑 / 超时）→ 全部 'N'，fallback 失败。"""
    out = {"warnings": [], "errors": []}
    monkeypatch.setattr("backend.services.tt_alarm_job.dispatch",
                        lambda messages, groups: {
                            "ok": True, "job_id": "J-EXT-1", "dispatched": len(messages),
                            "errors": []})
    monkeypatch.setattr("backend.services.tt_alarm_job.wait_for_job_result",
                        lambda *a, **k: {
                            "confirmed": True, "ok": False, "timed_out": True,
                            "sent": [], "errors": ["扩展未在 300s 内回报"],
                        })
    sent_log = []

    def _rec_stub(row, ok, error="", existing=None, tracking=None):
        sent_log.append({"tt_no": row.get("tt_no"), "ok": ok, "error": error})
    monkeypatch.setattr("backend.services.tt_alarm_whatsapp_service.record_result", _rec_stub)

    ok = S.try_ext_fallback(
        out, [{"tt_no": "TT_FB_1", "text": "t1"}, {"tt_no": "TT_FB_2", "text": "t2"}],
        ["P1 Group"], _fb_due(), {}, fallback_reason="baileys_zero_confirmed")

    assert ok is False
    assert out["ext_fallback"]["ok"] is False
    assert out["ext_fallback"]["confirmed"] is True
    assert out["ext_fallback"]["timed_out"] is True
    # 两条单据都被落 'N'（带错误信息）
    assert len(sent_log) == 2
    assert all(r["ok"] is False for r in sent_log)
    assert all("扩展未在" in r["error"] for r in sent_log)
    # 警告文案要点名 fallback 失败 + 让人去查 Chrome
    assert any("**仍未确认发送**" in w for w in out["warnings"])
    assert any("Chrome 开着" in w for w in out["warnings"])


def test_ext_fallback_partial_confirmed_returns_true(monkeypatch):
    """扩展确认发出其中 1 单 → 该单 'Y'，未确认那单 'N'，fallback 整体 True。"""
    out = {"warnings": [], "errors": []}
    monkeypatch.setattr("backend.services.tt_alarm_job.dispatch",
                        lambda messages, groups: {
                            "ok": True, "job_id": "J-EXT-2", "dispatched": len(messages),
                            "errors": []})
    # 扩展只回报了 TT_FB_1 发出；TT_FB_2 没出
    monkeypatch.setattr("backend.services.tt_alarm_job.wait_for_job_result",
                        lambda *a, **k: {
                            "confirmed": True, "ok": True, "timed_out": False,
                            "sent": ["TT_FB_1"], "errors": [],
                        })
    sent_log = []

    def _rec_stub(row, ok, error="", existing=None, tracking=None):
        sent_log.append({"tt_no": row.get("tt_no"), "ok": ok, "error": error})
    monkeypatch.setattr("backend.services.tt_alarm_whatsapp_service.record_result", _rec_stub)

    ok = S.try_ext_fallback(
        out, [{"tt_no": "TT_FB_1", "text": "t1"}, {"tt_no": "TT_FB_2", "text": "t2"}],
        ["P1 Group"], _fb_due(), {}, fallback_reason="baileys_dispatch_failed")

    assert ok is True, "至少兜住 1 单就应算成功（与 P1 告警「0 确认即失败」严格语义不同）"
    assert out["ext_fallback"]["ok"] is True
    # 兜住的单 → 'Y'，未兜住的单 → 'N'
    by_no = {r["tt_no"]: r for r in sent_log}
    assert by_no["TT_FB_1"]["ok"] is True
    assert by_no["TT_FB_2"]["ok"] is False
    # 警告文案要把"兜住 N/M 单"打出来，避免值班群收到消息却看不到告警日志
    assert any("兜住 1/2 单" in w for w in out["warnings"])


def test_ext_fallback_empty_messages_short_circuits(monkeypatch):
    """messages 为空直接 short-circuit（不该去写盘）—— 防御性边界。"""
    out = {"warnings": [], "errors": []}
    dispatched = {"called": False}

    def _spy(*a, **k):
        dispatched["called"] = True
        return {"ok": True, "job_id": "J", "dispatched": 0, "errors": []}
    monkeypatch.setattr("backend.services.tt_alarm_job.dispatch", _spy)

    ok = S.try_ext_fallback(out, [], ["P1 Group"], _fb_due(), {},
                            fallback_reason="baileys_dispatch_failed")
    assert ok is False
    assert dispatched["called"] is False, "空 messages 不应触发 dispatch"
    assert out["ext_fallback"]["attempted"] is False

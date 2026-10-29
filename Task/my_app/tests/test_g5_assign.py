# -*- coding: utf-8 -*-
"""5G 站点告警自动派单的纯函数单测（不触网、不碰库）。

覆盖 5G 与 Fiber 的**四处实质差异**（其余判定复用 `eflow_assign/assign_engine.py`，
已由 `tests/test_fiber_assign.py` 覆盖）：
  1. **告警码支持多个** —— 5 个 5G 退服类码任一命中即进入判定；
  2. **一站多小区去重** —— 同一站点多个 cell 的告警按「同站点 + 时间窗」合并成一个 TT；
  3. **不同站点绝不合并** —— 两个站同时退服是两个故障（Fiber 是纯时间窗跨站合并，
     5G 必须按站点分桶，否则会把两个故障并成一单）；
  4. **站点字段形态** —— 5G 的 `site` 已是数字站号、`sitename` 已是站名，不需要从 ME 名解析。

以及通报格式（必须带 Cells 行、正文全英文）与配置解析（多码 / restype / 兜底开关）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.eflow_assign import assign_engine as engine  # noqa: E402
from backend.services.eflow_5g import g5_assign_service as svc  # noqa: E402
from backend.services.eflow_5g import g5_config  # noqa: E402

CODES = {"200201001", "200201018", "200201041", "200201043", "200201060"}


def _ctx(**over) -> engine.AssignContext:
    """按 5G 口径装配判定上下文（与 `g5_assign_service.CTX` 同义，便于逐条改参数）。"""
    kw = dict(
        alarm_codes=set(CODES),
        correlation_codes={"99933"},
        correlation_window_minutes=60,
        window_minutes=180,
        min_age_minutes=15,
        group_window_minutes=10,
        assign_group="ZTE_NOC_FO",
        dry_run=True,
        groups=["test123"],
        push_title=svc.PUSH_TITLE,
        tag="5G",
        outage_label="the same 5G site outage",
    )
    kw.update(over)
    return engine.AssignContext(**kw)


def _alarm(code="200201001", site="4162", sitename="Liscr", cell="52",
           cellname="Liscr-S2", raised_ms=None, key=None, **extra):
    """按 eFlow 原始字段形态造一条告警（字段都是 {value: ...} 对象）。"""
    a = {
        "alarmcode": {"value": code},
        "site": {"value": site},
        "sitename": {"value": sitename},
        "cell": {"value": cell},
        "cellname": {"value": cellname},
        "alarmkey": {"value": key or f"key-{code}-{site}-{cell}"},
    }
    if raised_ms is not None:
        a["alarmraisedtime"] = {"value": raised_ms}
    a.update(extra)
    return a


def _assert_no_cjk(text: str) -> None:
    """群通报正文必须全英文（群里是英文环境，混中文一线看不懂）。"""
    bad = [ch for ch in text if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f"
           or "\uff00" <= ch <= "\uffef"]
    assert not bad, f"通报里出现了中文字符 {''.join(bad)!r}：\n{text}"


# ============================ 字段形态 ============================
def test_alarm_cell_prefers_cellname():
    """小区标识优先 `cellname`（人可读），回退 `cell`，占位符视为没有。"""
    assert svc.alarm_cell(_alarm(cell="52", cellname="Liscr-S2")) == "Liscr-S2"
    assert svc.alarm_cell(_alarm(cell="52", cellname="")) == "52"
    assert svc.alarm_cell(_alarm(cell="52", cellname="--")) == "52"
    assert svc.alarm_cell(_alarm(cell="", cellname="")) == ""
    assert svc.alarm_cell(_alarm(cell="Empty", cellname="none")) == ""


def test_alarm_site_identity_uses_numeric_site_id():
    """站点身份优先数字站号；站名大小写不同视为同一站；UUID 站名不能用。"""
    assert svc.alarm_site_identity(_alarm(site="4162", sitename="Liscr")) == "id:4162"
    # 只有站名 → 折叠大小写与空格
    assert svc.alarm_site_identity(
        _alarm(site="--", sitename="Liscr")) == "name:liscr"
    assert svc.alarm_site_identity(
        _alarm(site="--", sitename="LISCR")) == "name:liscr"
    # ME 名是 UUID（eFlow 未绑定站点）→ 不能当站名键
    uuid = "6784c258-596c-3109-9772-284b02d0df85"
    assert svc.alarm_site_identity(
        _alarm(site="--", sitename="--", mename=uuid)) == ""
    # 什么都没有 → 空（不参与合并）
    assert svc.alarm_site_identity({"alarmcode": {"value": "200201001"}}) == ""


# ============================ 一站多小区合并 ============================
def test_same_site_cells_merge_into_one_group():
    """同一 gNB 的 cell 50/51/52 同时退服 → 合并成一个 TT（组长 = 最早那条）。"""
    now = 1_760_000_000_000
    alarms = [
        _alarm(cell="52", cellname="Liscr-S2", raised_ms=now, key="k52"),
        _alarm(cell="50", cellname="Liscr-S0", raised_ms=now - 60_000, key="k50"),
        _alarm(cell="51", cellname="Liscr-S1", raised_ms=now - 30_000, key="k51"),
    ]
    groups = svc.group_by_site_occurrence(alarms, 10 * 60 * 1000)
    assert len({g["root"] for g in groups.values()}) == 1
    assert groups["k52"]["root"] == "k50"          # 最早升起的当组长
    assert len(groups["k50"]["members"]) == 3
    assert svc.group_cell_labels(groups["k50"]["members"]) == [
        "Liscr-S0", "Liscr-S1", "Liscr-S2"]


def test_different_sites_never_merge():
    """两个站点同时退服 = 两个故障，必须各派一单（与 Fiber 的纯时间窗合并相反）。"""
    now = 1_760_000_000_000
    a = _alarm(site="4162", sitename="Liscr", cell="1", raised_ms=now, key="a")
    b = _alarm(site="4163", sitename="Gbarnga", cell="1", raised_ms=now, key="b")
    groups = svc.group_by_site_occurrence([a, b], 10 * 60 * 1000)
    assert groups["a"]["root"] == "a" and groups["b"]["root"] == "b"
    assert len(groups["a"]["members"]) == 1 and len(groups["b"]["members"]) == 1


def test_same_site_beyond_window_splits():
    """同站先后两次退服（超过合并窗口）→ 两单，不能并成一次故障。"""
    now = 1_760_000_000_000
    old = _alarm(cell="50", cellname="Liscr-S0", raised_ms=now - 60 * 60_000, key="old")
    new = _alarm(cell="50", cellname="Liscr-S0", raised_ms=now, key="new")
    groups = svc.group_by_site_occurrence([old, new], 10 * 60 * 1000)
    assert groups["old"]["root"] == "old" and groups["new"]["root"] == "new"


def test_group_span_is_bounded_by_window():
    """组跨度与**组长**比较（不是与上一条），保证整组不超过窗口。"""
    now = 1_760_000_000_000
    w = 10 * 60 * 1000
    a = _alarm(cell="1", raised_ms=now - 2 * w, key="a")
    b = _alarm(cell="2", raised_ms=now - w + 1000, key="b")  # 与 a 差 > w
    c = _alarm(cell="3", raised_ms=now, key="c")             # 与 b 差 < w，与 a 差 2w
    groups = svc.group_by_site_occurrence([a, b, c], w)
    assert groups["a"]["root"] == "a" and len(groups["a"]["members"]) == 1
    assert groups["c"]["root"] == "b" and len(groups["c"]["members"]) == 2


def test_group_window_zero_disables_merging():
    """合并窗口配 0 = 关闭合并（回滚开关）：每条告警各成一单。"""
    now = 1_760_000_000_000
    alarms = [_alarm(cell=str(i), raised_ms=now, key=f"k{i}") for i in (50, 51, 52)]
    groups = svc.group_by_site_occurrence(alarms, 0)
    assert len({g["root"] for g in groups.values()}) == 3
    for a in alarms:
        assert len(groups[a["alarmkey"]["value"]]["members"]) == 1


def test_group_without_occurrence_time_is_alone():
    """取不到升起时间 → 不参与合并（无法判断是否同一次故障，宁可多派一单）。"""
    now = 1_760_000_000_000
    timed = _alarm(cell="50", raised_ms=now, key="timed")
    no_time = _alarm(cell="51", key="no_time")
    groups = svc.group_by_site_occurrence([timed, no_time], 10 * 60 * 1000)
    assert len(groups["no_time"]["members"]) == 1
    assert len(groups["timed"]["members"]) == 1


def test_group_cell_labels_dedupes_and_keeps_order():
    """同一小区重复告警只列一次（通报里数得清）。"""
    now = 1_760_000_000_000
    members = [
        _alarm(cell="52", cellname="Liscr-S2", raised_ms=now, key="1"),
        _alarm(cell="52", cellname="Liscr-S2", raised_ms=now, key="2"),
        _alarm(cell="50", cellname="Liscr-S0", raised_ms=now, key="3"),
    ]
    assert svc.group_cell_labels(members) == ["Liscr-S2", "Liscr-S0"]


# ============================ 多个告警码 ============================
def test_all_five_alarm_codes_are_due():
    """5 个默认码**任一**命中都进入派单判定（需求：告警码必须可配多个）。"""
    ctx = _ctx()
    now = 1_760_000_000_000
    for code in sorted(CODES):
        verdict, age = engine.due_verdict(
            ctx, _alarm(code=code, raised_ms=now - 20 * 60_000), now)
        assert verdict == engine.DUE_YES, code
        assert age and abs(age - 20.0) < 0.01


def test_non_whitelisted_code_is_not_due():
    """不在白名单里的码（如关联码 99933）不派单。"""
    ctx = _ctx()
    now = 1_760_000_000_000
    verdict, _ = engine.due_verdict(
        ctx, _alarm(code="99933", raised_ms=now - 20 * 60_000), now)
    assert verdict == engine.DUE_NO_CODE


def test_min_age_is_a_lower_bound():
    """存续未满 15 分钟 → 等下一轮（下界），不是一升起就派。"""
    ctx = _ctx()
    now = 1_760_000_000_000
    too_new = _alarm(raised_ms=now - 5 * 60_000)
    exact = _alarm(raised_ms=now - 15 * 60_000)
    assert engine.due_verdict(ctx, too_new, now)[0] == engine.DUE_TOO_NEW
    assert engine.due_verdict(ctx, exact, now)[0] == engine.DUE_YES   # 闭区间


def test_window_is_an_upper_bound():
    """存续超过 180 分钟 → 太老不派（防上线瞬间把积压的历史告警一次性派出去）。"""
    ctx = _ctx()
    now = 1_760_000_000_000
    old = _alarm(raised_ms=now - 4 * 3600_000)
    assert engine.due_verdict(ctx, old, now)[0] == engine.DUE_TOO_OLD


# ============================ 通报格式 ============================
def test_message_lists_cells_and_is_english_only():
    """通报必须带 Cells 行 + 覆盖小区数；正文全英文（中文只留日志/状态表）。"""
    now = 1_760_000_000_000
    alarm = _alarm(code="200201001", cell="52", cellname="Liscr-S2", raised_ms=now,
                   codename="DU cell out-of-service")
    text = svc.build_message(svc.CTX, alarm, "4162", "Liscr", "TT202610280001",
                             dry_run=False,
                             cells=["Liscr-S0", "Liscr-S1", "Liscr-S2"])
    assert "TT Title : 4162_Liscr_200201001" in text
    assert "Cells   : Liscr-S0, Liscr-S1, Liscr-S2" in text
    assert "This TT covers 3 cells on the same site" in text
    assert "TT No.   : TT202610280001" in text
    assert "DRY-RUN" not in text
    _assert_no_cjk(text)


def test_dry_run_message_is_marked():
    """演练通报必须显式标 DRY-RUN，避免群里误以为已建单。"""
    text = svc.build_message(svc.CTX, _alarm(raised_ms=1_760_000_000_000), "4162",
                             "Liscr", "", dry_run=True, cells=["Liscr-S2"])
    assert "DRY-RUN" in text
    assert "TT No." not in text


# ============================ 配置解析 ============================
def test_config_parses_multiple_codes_and_restypes():
    """告警码按逗号拆成集合（去重、去空白）；restype 默认穷举 RAN 形态。"""
    cfg = g5_config.parse_config({}, {})
    assert cfg["alarm_codes"] == CODES
    assert cfg["correlation_codes"] == {"99933"}
    assert cfg["min_age_minutes"] == 15 and cfg["window_minutes"] == 180
    assert cfg["group_window_minutes"] == 10
    assert cfg["dry_run"] is True                     # 默认演练
    assert cfg["cell_dedupe"] is True
    assert cfg["fallback_full_scan"] is True
    assert "zte.ran.gnodeb" in cfg["restypes"] and len(cfg["restypes"]) >= 5
    assert cfg["restypes_from"] == "default"


def test_config_env_overrides_file():
    """环境变量优先于配置文件（页面保存后靠重启 worker 重新 import 生效）。"""
    cfg = g5_config.parse_config(
        {"alarm_codes": "200201001", "min_age_minutes": 5, "dry_run": False},
        {"EFLOW_5G_ASSIGN_ALARM_CODES": "200201001, 200201018 ,",
         "EFLOW_5G_ASSIGN_MIN_AGE_MINUTES": "30",
         "EFLOW_5G_ASSIGN_DRY_RUN": "true",
         "EFLOW_5G_ASSIGN_RESTYPES": "zte.ran.gnodeb"})
    assert cfg["alarm_codes"] == {"200201001", "200201018"}
    assert cfg["min_age_minutes"] == 30 and cfg["min_age_minutes_from"] == "env"
    assert cfg["dry_run"] is True and cfg["dry_run_from"] == "env"
    assert cfg["restypes"] == ["zte.ran.gnodeb"] and cfg["restypes_from"] == "env"


def test_config_blank_codes_fall_back_to_defaults():
    """告警码留空 = 回退 5 个默认码（不能让任务静默变成「永不触发」）。"""
    cfg = g5_config.parse_config({"alarm_codes": ""}, {})
    assert cfg["alarm_codes"] == CODES


def test_config_negative_min_age_clamped_to_zero():
    """下界配成负数按 0 处理（= 立即派单），不能变成「提前 N 分钟派」。"""
    cfg = g5_config.parse_config({}, {"EFLOW_5G_ASSIGN_MIN_AGE_MINUTES": "-5"})
    assert cfg["min_age_minutes"] == 0


def test_cell_dedupe_can_be_disabled():
    """关闭一站多小区去重 = 每个小区各派一单（回滚开关）。"""
    cfg = g5_config.parse_config({}, {"EFLOW_5G_ASSIGN_CELL_DEDUPE": "false"})
    assert cfg["cell_dedupe"] is False

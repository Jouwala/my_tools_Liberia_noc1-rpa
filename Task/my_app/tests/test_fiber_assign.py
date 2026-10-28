# -*- coding: utf-8 -*-
"""Fiber Break 自动派单的纯函数单测（不触网、不碰库）。

覆盖三个最容易回归的点：
  1. ME 名 → 站点名解析（`6180H-A_Kakata_City_UPE29` → `Kakata City`）；
  2. 关联判定（同站点同窗口有 99933 → 跳过派单）；
  3. 触发窗口（超出窗口的历史告警不派单）。
以及消息格式（TT Title = SITE ID_Site name_Alarm Code）。
"""
import importlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.eflow_fiber import eflow_assign_client as client


def _reload_service(**env):
    """按给定环境变量重载服务模块（配置在导入期算好，必须重载）。"""
    import os
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update({k: str(v) for k, v in env.items()})
    try:
        import backend.services.eflow_fiber.fiber_config as cfg
        importlib.reload(cfg)
        import backend.services.eflow_fiber.fiber_assign_service as svc
        return importlib.reload(svc)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _assert_no_cjk(text: str) -> None:
    """断言通报正文里没有中文（2026-10-27 如意要求「通报默认使用英文」）。

    群里是英文环境（`lbr_assistant`），混进中文会让一线看不懂；
    中文允许留在状态表 `last_error`、warnings 与日志里。
    """
    bad = [ch for ch in text if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f"
           or "\uff00" <= ch <= "\uffef"]
    assert not bad, f"通报里出现了中文字符 {''.join(bad)!r}：\n{text}"


def test_site_name_from_me():
    assert client.site_name_from_me("6180H-A_Kakata_City_UPE29") == "Kakata City"
    assert client.site_name_from_me("6120HA_zardun_UPE128") == "zardun"
    assert client.site_name_from_me("M6K_2s16_Gbarnga_UPE76") == "2s16 Gbarnga"
    # 无下划线分段原样返回
    assert client.site_name_from_me("RIA") == "RIA"
    assert client.site_name_from_me("9000-8EA_SPE01") == "9000-8EA_SPE01"
    assert client.site_name_from_me(None) == ""


def test_norm_code():
    from backend.services.eflow_fiber.fiber_config import norm_code
    assert norm_code("4758") == "4758"
    assert norm_code(4758) == "4758"
    assert norm_code("4758.0") == "4758"
    assert norm_code("") == ""
    assert norm_code(None) == ""


def test_is_due_window():
    """触发窗口是**上界**，派单等待时长是**下界**（2026-10-27 业务口径）。

    业务原话：「告警发生到选择超过 15 分钟，才要指派单子和发送 WhatsApp 消息」
    → 告警升起后必须先存在满 15 分钟才派（下界），不是一升起就派。
    """
    svc = _reload_service(FIBER_ASSIGN_ALARM_CODES="4758", FIBER_ASSIGN_WINDOW_MINUTES="180",
                          FIBER_ASSIGN_MIN_AGE_MINUTES="15")
    now = int(time.time() * 1000)
    # 刚升起 1 分钟 → 还没到派单时机（下界挡住）
    too_new = {"alarmcode": {"value": "4758"}, "alarmraisedtime": {"value": now - 60_000}}
    # 存续 20 分钟 → 到点了（下界放行，且在触发窗口内）
    due = {"alarmcode": {"value": "4758"}, "alarmraisedtime": {"value": now - 20 * 60_000}}
    # 存续 5 小时 → 太老（上界挡住）
    old = {"alarmcode": {"value": "4758"}, "alarmraisedtime": {"value": now - 5 * 3600_000}}
    # 告警码不命中 → 不派
    other = {"alarmcode": {"value": "99933"}, "alarmraisedtime": {"value": now - 20 * 60_000}}
    assert svc.is_due(too_new, now) is False
    assert svc.is_due(due, now) is True
    assert svc.is_due(old, now) is False
    assert svc.is_due(other, now) is False


def test_is_due_min_age_zero_restores_immediate_dispatch():
    """`min_age_minutes=0` = 恢复「一升起就派」的旧行为（回滚开关）。"""
    svc = _reload_service(FIBER_ASSIGN_ALARM_CODES="4758", FIBER_ASSIGN_WINDOW_MINUTES="180",
                          FIBER_ASSIGN_MIN_AGE_MINUTES="0")
    now = int(time.time() * 1000)
    fresh = {"alarmcode": {"value": "4758"}, "alarmraisedtime": {"value": now - 60_000}}
    assert svc.is_due(fresh, now) is True


def test_is_due_boundary_exact_minutes():
    """下界是**闭区间**：存续时长正好等于 min_age_minutes 时应放行。"""
    svc = _reload_service(FIBER_ASSIGN_ALARM_CODES="4758", FIBER_ASSIGN_WINDOW_MINUTES="180",
                          FIBER_ASSIGN_MIN_AGE_MINUTES="15")
    now = int(time.time() * 1000)
    exact = {"alarmcode": {"value": "4758"}, "alarmraisedtime": {"value": now - 15 * 60_000}}
    assert svc.is_due(exact, now) is True


def test_age_minutes():
    """`age_minutes`：分钟数；取不到升起时间返回 None；未来时间钳到 0。"""
    svc = _reload_service(FIBER_ASSIGN_ALARM_CODES="4758")
    now = int(time.time() * 1000)
    a10 = {"alarmcode": {"value": "4758"}, "alarmraisedtime": {"value": now - 10 * 60_000}}
    assert abs(svc.age_minutes(a10, now) - 10.0) < 0.01
    # 取不到时间
    assert svc.age_minutes({"alarmcode": {"value": "4758"}}, now) is None
    # 上游时间在将来（时钟漂移）→ 钳到 0，不能判成「已存续很久」
    future = {"alarmcode": {"value": "4758"}, "alarmraisedtime": {"value": now + 600_000}}
    assert svc.age_minutes(future, now) == 0.0


def test_find_correlated_alarm():
    svc = _reload_service(FIBER_ASSIGN_CORRELATION_CODES="99933",
                          FIBER_ASSIGN_CORRELATION_WINDOW_MINUTES="60")
    now = int(time.time() * 1000)
    fiber = {"alarmcode": {"value": "4758"}, "site": {"value": "3462"},
             "alarmraisedtime": {"value": now}}
    # 同站点、同窗口的 99933 → 应命中
    corr_same = {"alarmcode": {"value": "99933"}, "site": {"value": "3462"},
                 "alarmraisedtime": {"value": now - 10 * 60_000}}
    # 不同站点的 99933 → 不命中
    corr_other = {"alarmcode": {"value": "99933"}, "site": {"value": "9999"},
                  "alarmraisedtime": {"value": now}}
    # 同站点但超窗口的 99933 → 不命中
    corr_old = {"alarmcode": {"value": "99933"}, "site": {"value": "3462"},
                "alarmraisedtime": {"value": now - 3 * 3600_000}}
    assert svc.find_correlated_alarm(fiber, [fiber, corr_same], now) is corr_same
    assert svc.find_correlated_alarm(fiber, [fiber, corr_other], now) is None
    assert svc.find_correlated_alarm(fiber, [fiber, corr_old], now) is None


def test_correlation_matches_raw_api_field_shapes():
    """关联判定必须认原始 API 的字段形态（2026-10-27 生产实测发现的回归点）。

    生产实测（`TMP/_probe_site_keys.py`）：
      * 4758：`site` 有时是数字（`4030`）、有时是 ME 名；`sitename` 有时是
        `--`；`mename` 常常是 **UUID**；
      * 99933：`site` 是数字站号、`sitename`/`mename` 都是站点名。

    原实现只认 `site_id`/`site_name`（数据库列名），对原始行取不到值，最后落到
    `mename` 的 UUID 上 —— 键是 UUID 而 99933 的键是站点名，**永远不相交**，
    「同站已有 99933 就不派单」会静默失效。下面三条锁住三种真实形态。
    """
    svc = _reload_service(FIBER_ASSIGN_CORRELATION_CODES="99933",
                          FIBER_ASSIGN_CORRELATION_WINDOW_MINUTES="60")
    now = int(time.time() * 1000)

    # 形态 1：fiber 的 site 是数字、sitename 有真名、mename 是 UUID
    fiber_num = {"alarmcode": {"value": "4758"}, "site": {"value": "4030"},
                 "sitename": {"value": "Old Road"},
                 "mename": {"value": "6784c258-596c-3109-9772-284b02d0df85"},
                 "alarmraisedtime": {"value": now}}
    corr_num = {"alarmcode": {"value": "99933"}, "site": {"value": "4030"},
                "sitename": {"value": "Old Road"},
                "mename": {"value": "Old Road"},
                "alarmraisedtime": {"value": now - 5 * 60_000}}
    assert svc.find_correlated_alarm(fiber_num, [fiber_num, corr_num], now) is corr_num

    # 形态 2：fiber 的 site 是 ME 名、sitename 为 '--' → 应能按站名匹配上
    fiber_me = {"alarmcode": {"value": "4758"},
                "site": {"value": "6120HA_zardun_UPE128"},
                "sitename": {"value": "--"},
                "mename": {"value": "6120HA_zardun_UPE128"},
                "alarmraisedtime": {"value": now}}
    corr_me = {"alarmcode": {"value": "99933"}, "site": {"value": "3462"},
               "sitename": {"value": "Zardun"}, "mename": {"value": "Zardun"},
               "alarmraisedtime": {"value": now - 5 * 60_000}}
    assert svc.find_correlated_alarm(fiber_me, [fiber_me, corr_me], now) is corr_me

    # 形态 3：不同站点（数字站号 + 不同站名）绝不能误判成同站
    other = {"alarmcode": {"value": "99933"}, "site": {"value": "4523"},
             "sitename": {"value": "Tokpah Camp"},
             "mename": {"value": "Tokpah Camp"},
             "alarmraisedtime": {"value": now}}
    assert svc.find_correlated_alarm(fiber_num, [fiber_num, other], now) is None


def test_correlation_verdict_three_states():
    """关联判定三态：`hit` / `none` / `undetermined`（2026-10-27 如意要求「匹配不到就当作没有」）。

    关键约束：**只有 `hit` 才跳过派单**；`none` 与 `undetermined` 都要继续派单。
    `undetermined` 额外写 warnings 留痕，便于事后复核是否重复派单。
    """
    svc = _reload_service(FIBER_ASSIGN_CORRELATION_CODES="99933",
                          FIBER_ASSIGN_CORRELATION_WINDOW_MINUTES="60")
    now = int(time.time() * 1000)

    # ① 有数字站号 + 同站 99933 → hit
    fiber_num = {"alarmcode": {"value": "4758"}, "site": {"value": "4030"},
                 "sitename": {"value": "Old Road"}, "alarmraisedtime": {"value": now}}
    corr_same = {"alarmcode": {"value": "99933"}, "site": {"value": "4030"},
                 "sitename": {"value": "Old Road"},
                 "alarmraisedtime": {"value": now - 5 * 60_000}}
    verdict, hit, _ = svc.correlation_verdict(fiber_num, [fiber_num, corr_same])
    assert verdict == svc.CORRELATION_HIT and hit is corr_same

    # ② 有数字站号、99933 在别的站 → none（确定没有）
    corr_other = {"alarmcode": {"value": "99933"}, "site": {"value": "4523"},
                  "sitename": {"value": "Tokpah Camp"},
                  "alarmraisedtime": {"value": now}}
    verdict, hit, _ = svc.correlation_verdict(fiber_num, [fiber_num, corr_other])
    assert verdict == svc.CORRELATION_NONE and hit is None

    # ③ 站点名写法不同（ME 推导 luogan vs cmdb 的 Luogon）→ 不相交 → undetermined，
    #    但**仍要派单**（旧包装返回 None，调用方据 verdict 决定）
    fiber_me = {"alarmcode": {"value": "4758"},
                "site": {"value": "6120HS_Peter_luogan_town_UPE80"},
                "sitename": {"value": "--"},
                "mename": {"value": "6120HS_Peter_luogan_town_UPE80"},
                "alarmraisedtime": {"value": now}}
    corr_luogon = {"alarmcode": {"value": "99933"}, "site": {"value": "4478"},
                   "sitename": {"value": "Peter Luogon Town"},
                   "alarmraisedtime": {"value": now - 5 * 60_000}}
    verdict, hit, note = svc.correlation_verdict(fiber_me, [fiber_me, corr_luogon])
    assert verdict == svc.CORRELATION_UNDETERMINED and hit is None and note
    assert svc.find_correlated_alarm(fiber_me, [fiber_me, corr_luogon], now) is None

    # ④ 站点信息完全缺失（site/sitename 都是占位符、mename 是 UUID）→ undetermined
    blank = {"alarmcode": {"value": "4758"}, "site": {"value": "--"},
             "sitename": {"value": "--"},
             "mename": {"value": "6784c258-596c-3109-9772-284b02d0df85"},
             "alarmraisedtime": {"value": now}}
    verdict, hit, _ = svc.correlation_verdict(blank, [blank])
    assert verdict == svc.CORRELATION_UNDETERMINED and hit is None


def test_uuid_mename_is_not_a_site_name_key():
    """`mename` 是 UUID 时不能当站点名 —— 否则会造出永远不相交的垃圾键。"""
    svc = _reload_service()
    a = {"site": {"value": "--"}, "sitename": {"value": "--"},
         "mename": {"value": "6784c258-596c-3109-9772-284b02d0df85"}}
    assert svc._alarm_site_keys(a) == set()

    # 有数字站号时，UUID 不能污染键集合，但数字键必须保留
    b = {"site": {"value": "4847"}, "sitename": {"value": "--"},
         "mename": {"value": "6784c258-596c-3109-9772-284b02d0df85"}}
    assert svc._alarm_site_keys(b) == {"id:4847"}


def test_manual_message_format():
    """自动派不了时不能静默：必须生成「需人工处理」通报（2026-10-27 业务要求）。

    两种失败共用一个渲染函数，但「说明」段不同：
      * 站点解析失败 → 补 cmdb 站点 / 手动派单；
      * ttstatus 异常（ME 未关联站点）→ 先在 eFlow 把 ME 绑定到站点。

    ⚠ **通报正文必须英文**（2026-10-27 如意要求「通报默认使用英文」）：
    中文只允许出现在 `last_error`（状态表）与 warnings/日志里。
    """
    svc = _reload_service()
    alarm = {
        "alarmcode": {"value": "4758"},
        "codename": {"value": "Fiber Break"},
        "mename": {"value": "Tokadeh"},
        "alarmraisedtime": {"value": int(time.time() * 1000)},
    }
    text = svc.build_manual_message(
        alarm, "site resolution failed — no numeric site ID matched in cmdb")
    assert "Auto assign failed" in text
    assert "manual action required in eFlow" in text
    assert "Tokadeh" in text
    assert "4758 Fiber Break" in text
    assert "no numeric site ID matched in cmdb" in text
    assert "fix the cmdb site" in text
    _assert_no_cjk(text)

    # ttstatus 异常（ME 未绑定站点）→ 说明段必须指向「绑定 ME 到站点」
    bound = svc.build_manual_message(
        alarm, "eFlow ttstatus=6 (ME not bound to a site); assign was attempted but no TT was created",
        hint_lines=["Note: this ME is not correctly bound to a site in eFlow.",
                    "      Please bind the ME to a numeric site, or assign manually."])
    assert "ttstatus=6" in bound
    assert "bind the ME to a numeric site" in bound
    assert "cmdb site" not in bound
    _assert_no_cjk(bound)


def test_message_format():
    svc = _reload_service()
    alarm = {
        "alarmcode": {"value": "4758"},
        "codename": {"value": "Fiber Break"},
        "mename": {"value": "6120HA_zardun_UPE128"},
        "alarmraisedtime": {"value": int(time.time() * 1000)},
    }
    text = svc.build_message(alarm, "3462", "Zardun", "ZTE_NOC_FO", "TT202610260085", dry_run=False)
    # TT Title 必须是 SITE ID_Site name_Alarm Code
    assert "TT Title : 3462_Zardun_4758" in text
    assert "TT No.   : TT202610260085" in text
    # 演练标记只在 dry_run 出现
    assert "DRY-RUN" not in text
    _assert_no_cjk(text)
    dry = svc.build_message(alarm, "3462", "Zardun", "ZTE_NOC_FO", "", dry_run=True)
    assert "DRY-RUN" in dry
    _assert_no_cjk(dry)
    # 站点名近似匹配时必须留警示，让人核对 cmdb 命名
    noted = svc.build_message(
        alarm, "3462", "Peter Luogon Town", "ZTE_NOC_FO", "TT1", dry_run=False,
        site_note="Site name fuzzy-matched: 'Peter luogan town' -> 'Peter Luogon Town' "
                  "(score 0.93), please verify the cmdb naming")
    assert "fuzzy-matched" in noted
    _assert_no_cjk(noted)
    # 关联判定不了、按「无关联」派单时，通报里也要能看出来（否则群里不知道派单依据）
    with_corr = svc.build_message(
        alarm, "3462", "Zardun", "ZTE_NOC_FO", "TT1", dry_run=False,
        notes=["99933 correlation could not be determined (site keys: name:zardun) — "
               "assigned as no-correlation"])
    assert "correlation could not be determined" in with_corr
    _assert_no_cjk(with_corr)
    # 空的 note 不能留下多余空行/前缀
    assert "⚠ \n" not in with_corr


# ==========================================================
# 站点名解析：精确 → 归一化精确 → 近似（带歧义保护）
# ==========================================================
def _fake_index(names, **kw):
    """构造不触网的 SiteIndex：直接填索引（load() 会拉 cmdb，单测不能走）。"""
    idx = client.SiteIndex(**kw)
    idx._loaded = True  # noqa: SLF001 单测直接注入索引
    for i, name in enumerate(names, start=1):
        rec = {"id": str(1000 + i), "name": name}
        idx._by_name.setdefault(name.lower(), []).append(rec)  # noqa: SLF001
        norm = client._norm_name(name)  # noqa: SLF001
        if norm:
            idx._by_norm.setdefault(norm, []).append(rec)  # noqa: SLF001
    return idx


def test_norm_site_name():
    """归一化只吃分隔符差异，不动字母。"""
    assert client._norm_name("Peter Luogon Town") == "peterluogontown"
    assert client._norm_name("Peter_luogon_town") == "peterluogontown"
    assert client._norm_name(" Peter-Luogon.Town ") == "peterluogontown"
    assert client._norm_name("Peter luogan town") == "peterluogantown"
    assert client._norm_name(None) == ""


def test_site_lookup_exact_and_normalized():
    idx = _fake_index(["Peter Luogon Town", "Zardun"])
    hit = idx.lookup("Zardun")
    assert (hit["id"], hit["name"], hit["matched_by"]) == ("1002", "Zardun", "exact")

    # 只差分隔符 → normalized（不作为「近似匹配」告警）
    hit = idx.lookup("Peter_Luogon Town")
    assert hit["name"] == "Peter Luogon Town"
    assert hit["matched_by"] == "normalized"


def test_site_lookup_fuzzy_fallback():
    """实测案例：ME 推出 `Peter luogan town`，cmdb 写作 `Peter Luogon Town`。

    不开近似匹配时该告警永远派不出去（每轮记 N），开启后必须能解析到。
    """
    idx = _fake_index(["Peter Luogon Town", "Zardun"])
    hit = idx.lookup("Peter luogan town")
    assert hit is not None, "近似匹配没生效，Peter_luogan_town 仍会每轮失败"
    assert hit["name"] == "Peter Luogon Town"
    assert hit["matched_by"] == "fuzzy"
    assert hit["score"] >= 0.9

    # 关掉开关就只剩精确/归一化，查不到
    off = _fake_index(["Peter Luogon Town"], fuzzy_enabled=False)
    assert off.lookup("Peter luogan town") is None

    # 阈值调严到 0.99 → 这点拼写差异不再被接受
    strict = _fake_index(["Peter Luogon Town"], fuzzy_threshold=0.99)
    assert strict.lookup("Peter luogan town") is None


def test_site_lookup_refuses_neighbour_stations():
    """必须拒绝「看起来像拼写差异、其实是另一个站」的候选（生产 cmdb 实测）。

    这些是 Liberia 网络上**互不相同**的站点，相似度却不低于目标案例（0.9333）。
    只按相似度兜底就会把告警派到隔壁站 —— 比不派更难收拾。
    """
    # 只按分数会误配的真实站点对
    for query, wrong in [("Garplay", "Gbarplay"),
                         ("Banwea", "Gbanwea"),
                         ("Butuo", "Buutuo"),
                         ("Sanniquillie 5", "Sanniquillie 1"),
                         ("18th Street", "16th Street"),
                         ("Buchanan 3 AML", "Buchanan AML")]:
        idx = _fake_index([wrong])
        assert idx.lookup(query) is None, f"{query!r} 被误匹配到 {wrong!r}"

    # 但目标案例（等长元音互换）必须仍然生效
    ok = _fake_index(["Peter Luogon Town"])
    assert ok.lookup("Peter luogan town")["matched_by"] == "fuzzy"


def test_vowel_swap_rule():
    """「等长纯元音互换」是本方案唯一的放行条件。"""
    assert client._vowel_swap_only("peterluogantown", "peterluogontown") is True  # a↔o
    assert client._vowel_swap_only("zardan", "zardun") is True                    # a↔u
    # 长度不同（插入/删除字母）→ 拒绝
    assert client._vowel_swap_only("garplay", "gbarplay") is False
    assert client._vowel_swap_only("butuo", "buutuo") is False
    # 辅音差异 → 拒绝
    assert client._vowel_swap_only("banwea", "gbanwea") is False
    # 数字差异 → 拒绝
    assert client._vowel_swap_only("sanniquillie5", "sanniquillie1") is False
    # 完全相同 → 不算近似（应走 exact）
    assert client._vowel_swap_only("zardun", "zardun") is False


def test_site_lookup_fuzzy_refuses_ambiguity():
    """两个候选同样接近时必须放弃 —— 错派到相邻站点比不派更难收拾。

    真实成因：同一站点被以两种拼写重复录入 cmdb。
    """
    idx = _fake_index(["Peter Luogan Town", "Peter Luogen Town"])
    assert idx.lookup("Peter Luogon Town") is None

    # 只有一个候选时仍可采用
    ok = _fake_index(["Peter Luogon Town", "Gbarnga"])
    assert ok.lookup("Peter luogan town")["name"] == "Peter Luogon Town"


def test_site_lookup_refuses_phase_site_by_digit_suffix():
    """分期站点绝不能靠相似度猜（2026-10-27 扫生产 cmdb 发现的真实风险）。

    830 个站点里有 66 对在 0.9 阈值下互相接近，几乎全是 `Johnsonville` /
    `Johnsonville 2` / `Johnsonville 3` 这类分期命名。若 cmdb 里只剩 `Johnsonville 2`，
    查询 `Johnsonville`（1 号站）会唯一领先 → 把 1 号站的告警派到 2 号站。
    """
    assert client._only_digit_suffix_diff("johnsonville", "johnsonville2") is True
    assert client._only_digit_suffix_diff("johnsonville2", "johnsonville") is True
    assert client._only_digit_suffix_diff("skdboulevard", "skdboulevard3") is True
    # 真拼写差异不受影响
    assert client._only_digit_suffix_diff("peterluogantown", "peterluogontown") is False
    assert client._only_digit_suffix_diff("zardun", "zardun") is False
    # 数字在中间、或后缀不是纯数字 → 不算纯后缀差异
    assert client._only_digit_suffix_diff("2s16gbarnga", "gbarnga") is False

    # `Johnsonville` 查不到 → 模糊到 `Johnsonville 2` 必须被拒绝
    idx = _fake_index(["Johnsonville 2", "Johnsonville 3"])
    assert idx.lookup("Johnsonville") is None
    # 反过来「查询带分期号、cmdb 没有」也不猜
    idx2 = _fake_index(["Johnsonville"])
    assert idx2.lookup("Johnsonville 2") is None
    # 精确命中自己的分期号仍正常（走 exact，不进 fuzzy）
    idx3 = _fake_index(["Johnsonville 2"])
    assert idx3.lookup("Johnsonville 2")["matched_by"] == "exact"


def test_site_lookup_does_not_pollute_index():
    """近似匹配打的元字段不能写回索引原始记录，否则后续调用互相污染。"""
    idx = _fake_index(["Peter Luogon Town"])
    idx.lookup("Peter luogan town")
    raw = idx._by_name["peter luogon town"][0]  # noqa: SLF001
    assert "matched_by" not in raw and "score" not in raw and "query" not in raw


def test_resolve_site_trace_marks_fuzzy():
    """resolve_site 必须把匹配方式透出来，供调用方写日志/结果留痕。"""
    idx = _fake_index(["Peter Luogon Town"])
    alarm = {"site": {"value": "6120HS_Peter_luogan_town_UPE80"},
             "sitename": {"value": "--"},
             "mename": "6120HS_Peter_luogan_town_UPE80"}
    trace = {}
    site_id, site_name = client.resolve_site(alarm, idx, trace=trace)
    assert site_id == "1001"
    assert site_name == "Peter Luogon Town"
    assert trace["matched_by"] == "fuzzy"
    assert trace["score"] >= 0.9

    # 解析失败时 trace 里留尝试过的站名，方便排查
    miss = {}
    bad = {"mename": "6120HS_Nowhere_UPE1"}
    assert client.resolve_site(bad, idx, trace=miss) == ("", "")
    assert miss["tried"] == ["Nowhere"]


def test_fiber_config_fuzzy_fields():
    """阈值必须被钳在 [0.5, 1.0]，配歪了等于乱派（0.3 会把不同站点判成同一个）。"""
    from backend.services.eflow_fiber import fiber_config as cfg

    base = {"site_fuzzy_enabled": False, "site_fuzzy_threshold": 0.85}
    out = cfg.parse_config(base, {})
    assert out["site_fuzzy_enabled"] is False
    assert abs(out["site_fuzzy_threshold"] - 0.85) < 1e-9

    # 越界/非法 → 回退默认 0.9
    for bad_val in ("0.3", "1.5", "abc", None):
        out = cfg.parse_config({"site_fuzzy_threshold": bad_val}, {})
        assert abs(out["site_fuzzy_threshold"] - cfg.DEFAULT_SITE_FUZZY_THRESHOLD) < 1e-9

    # env 优先于配置文件
    out = cfg.parse_config(base, {cfg.ENV_SITE_FUZZY_THRESHOLD: "0.95",
                                  cfg.ENV_SITE_FUZZY_ENABLED: "true"})
    assert abs(out["site_fuzzy_threshold"] - 0.95) < 1e-9
    assert out["site_fuzzy_enabled"] is True


def test_fiber_config_min_age_field():
    """派单等待时长（`min_age_minutes`）的解析规则（2026-10-27 新增）。

    优先级与其它字段一致：环境变量 > 配置文件 > 内置默认（15 分钟）。
    负数必须被钳到 0（= 立即派单），不能让负值把「等满 N 分钟」变成「提前 N 分钟派」。
    """
    from backend.services.eflow_fiber import fiber_config as cfg

    # 默认 15 分钟
    out = cfg.parse_config({}, {})
    assert out["min_age_minutes"] == 15
    assert out["min_age_minutes"] == cfg.DEFAULT_MIN_AGE_MINUTES

    # 配置文件覆盖
    out = cfg.parse_config({"min_age_minutes": 20}, {})
    assert out["min_age_minutes"] == 20

    # 环境变量优先于配置文件
    out = cfg.parse_config({"min_age_minutes": 20}, {cfg.ENV_MIN_AGE: "30"})
    assert out["min_age_minutes"] == 30

    # 0 = 立即派单（回滚开关），允许
    out = cfg.parse_config({"min_age_minutes": 0}, {})
    assert out["min_age_minutes"] == 0

    # 负数 → 钳到 0
    out = cfg.parse_config({"min_age_minutes": -5}, {})
    assert out["min_age_minutes"] == 0

    # 非法值（字母）→ 回退默认，不让服务 import 崩掉
    out = cfg.parse_config({"min_age_minutes": "abc"}, {})
    assert out["min_age_minutes"] == cfg.DEFAULT_MIN_AGE_MINUTES


def test_ttstatus_does_not_block_assignment():
    """`ttstatus` 非 0 **不再阻断派单**（2026-10-27 业务要求）。

    历史：切生产首轮发现 `ttstatus=2` 的告警（ME 未在 eFlow 关联站点）派单接口回
    `200 manual assign succeed.` 却永远建不出 TT、`ttid` 一直为空，于是加了
    「非 0 一律跳过」。现在业务要求「不能被 eFlow 侧 ME 未绑定站点挡住」——
    改为**提示信号**：照派，只用最小预算（1 次尝试 × 2 次回查），失败后通报人工。
    """
    svc = _reload_service()

    # 「状态是否干净」的判定保留（只作提示，不再作阻断）
    assert svc.is_clean_ttstatus("0") is True
    assert svc.is_clean_ttstatus({"value": "0"}) is True
    # 字段缺失/空 → 按干净处理（兼容 RAN 告警与老数据）
    assert svc.is_clean_ttstatus("") is True
    assert svc.is_clean_ttstatus(None) is True
    for bad in ("1", "2", "4", "5", "6", {"value": "2"}):
        assert svc.is_clean_ttstatus(bad) is False, f"ttstatus={bad!r} 不该判为干净"

    # 关键：可疑状态仍有派单预算（>0），只是比正常状态小
    suspect_attempts, suspect_verifies = svc.assign_attempt_budget(True)
    assert suspect_attempts >= 1 and suspect_verifies >= 1
    normal_attempts, normal_verifies = svc.assign_attempt_budget(False)
    assert normal_attempts >= suspect_attempts
    assert normal_verifies >= suspect_verifies

    # N / S 都不算已处理 → 下一轮会重新判定/重试，eFlow 修好后自动接上
    assert svc.is_already_handled("N", False) is False
    assert svc.is_already_handled("S", False) is False


def test_existing_upstream_tt_is_skipped():
    """告警上游已带 TT 时不得重复派单（2026-10-26 生产自查发现的回归点）。

    生产上 eFlow 自己的 assign_rule 会给部分 fiber 告警先建 TT；这些告警在本地
    状态表里没有记录，若只看状态表就会重复派单、建出重复 TT。
    """
    svc = _reload_service()

    assert svc.upstream_tt({"ttid": {"value": "TT202610260083"}}) == "TT202610260083"
    assert svc.upstream_tt({"ttid": "TT202610270031"}) == "TT202610270031"
    for placeholder in ("empty", "", None, "-", "None", "null", "EMPTY"):
        assert svc.upstream_tt({"ttid": {"value": placeholder}}) == ""
    assert svc.upstream_tt({}) == ""


def test_dry_run_record_does_not_block_real_assign():
    """演练记录（D）在关闭 dry_run 后必须重新处理，否则会被永久跳过。

    2026-10-26 生产切换自查发现的回归点：若把 D 与 Y 一样当「已处理」，
    演练期扫过的告警在真上线后永远不会派单。
    """
    # ⚠ importlib.reload 原地复用模块对象，两次 reload 拿到的是同一个 module，
    #   故必须在每次 reload 后立刻把常量取出来，不能留着两个模块引用比较。
    assert _reload_service(FIBER_ASSIGN_DRY_RUN="true").DRY_RUN is True
    svc = _reload_service(FIBER_ASSIGN_DRY_RUN="false")
    assert svc.DRY_RUN is False

    assert svc.is_already_handled("Y", True) is True    # 成功过 → 永远跳过
    assert svc.is_already_handled("Y", False) is True
    assert svc.is_already_handled("D", True) is True    # 演练模式内 → 跳过（避免重复记录）
    assert svc.is_already_handled("D", False) is False  # 关闭演练 → 必须重新处理
    assert svc.is_already_handled("N", False) is False  # 失败过 → 重试
    assert svc.is_already_handled("S", False) is False  # 跳过过 → 每轮重新判定关联
    assert svc.is_already_handled("", False) is False


# ==========================================================
# 同一次光纤中断的合并派单（2026-10-27 需求）
# ==========================================================
def _alarm(key: str, ms, me: str = "ME", code: str = "4758"):
    """构造一条 fiber 告警（字段形状与 eFlow 实时告警一致）。"""
    return {
        "alarmkey": key,
        "id": key,
        "alarmcode": code,
        "mename": me,
        "alarmraisedtime": ms,
    }


# 2026-10-27 14:21 的实况：一次光缆中断，9 秒内 5 条告警（R.I.A×3 + Tower Hill + HQ_Site）
_BASE_MS = 1793110873000
_REAL_5 = [
    _alarm("k_ria_1", _BASE_MS, "RIA"),
    _alarm("k_tower", _BASE_MS + 2000, "6120H-S_Tower_Hill_UPE23"),
    _alarm("k_ria_2", _BASE_MS + 2000, "6180H-A_RIA_UPE24"),
    _alarm("k_hq", _BASE_MS + 5000, "9000-8EA_SPE01"),
    _alarm("k_ria_3", _BASE_MS + 9000, "6180H-A_RIA_UPE24"),
]


def test_group_by_occurrence_merges_same_fiber_cut():
    """同一时间窗内升起的告警必须合并成一组（今天 5 条 → 1 组）。"""
    svc = _reload_service()
    groups = svc.group_by_occurrence(_REAL_5, 10 * 60 * 1000)

    # 全部指向同一个组长（升起最早的那条）
    roots = {g["root"] for g in groups.values()}
    assert roots == {"k_ria_1"}, f"应合并为一组，实际组长集合 {roots}"
    assert all(len(g["members"]) == 5 for g in groups.values())


def test_group_span_is_bounded_by_window():
    """组跨度不能超过窗口：用「与组内第一条比」而非链式比较。

    链式比较会让 A→B(9min)→C(9min) 三条形变 18 分钟却同组，窗口形同虚设。
    """
    svc = _reload_service()
    win = 10 * 60 * 1000
    # ⚠ 时间戳不能用 0：`_occur_ms` 里 `x or y` 会把 0 当假值短路掉（既有口径），
    #   真实告警时间戳永不为 0，故这里用真实基准即可。
    chain = [
        _alarm("a", _BASE_MS),
        _alarm("b", _BASE_MS + 9 * 60 * 1000),    # 距 a 9 分钟 → 同组
        _alarm("c", _BASE_MS + 18 * 60 * 1000),   # 距 a 18 分钟 → 必须另开一组
    ]
    groups = svc.group_by_occurrence(chain, win)
    assert groups["a"]["root"] == "a"
    assert groups["b"]["root"] == "a"
    assert groups["c"]["root"] == "c", "c 距组长 18 分钟 > 10 分钟窗口，不得并入"
    assert len(groups["c"]["members"]) == 1


def test_group_window_zero_disables_merging():
    """配 0 = 关闭合并（回滚开关），每条告警自成一组。"""
    svc = _reload_service()
    groups = svc.group_by_occurrence(_REAL_5, 0)
    assert all(g["root"] == k for k, g in groups.items())
    assert all(len(g["members"]) == 1 for g in groups.values())

    # 负数同样按关闭处理（服务层已钳到 0）
    out = _reload_service(FIBER_ASSIGN_GROUP_WINDOW_MINUTES="-5")
    assert out.GROUP_WINDOW_MINUTES == 0


def test_group_alarms_without_occurrence_are_never_merged():
    """取不到升起时间的告警不参与合并 —— 无法判断时序时宁可多派一单。"""
    svc = _reload_service()
    win = 10 * 60 * 1000
    mixed = [
        _alarm("no_time_1", None),
        _alarm("no_time_2", None),
        _alarm("timed", _BASE_MS),
        _alarm("timed_2", _BASE_MS + 1000),
    ]
    groups = svc.group_by_occurrence(mixed, win)
    assert groups["no_time_1"]["root"] == "no_time_1"
    assert groups["no_time_2"]["root"] == "no_time_2", "无时间戳的告警不得互相合并"
    assert groups["timed"]["root"] == "timed"
    assert groups["timed_2"]["root"] == "timed"


def test_group_root_is_earliest_alarm():
    """组长必须是组内升起最早的那条（最可能是根因站点）。

    输入故意乱序，验证分组不受输入顺序影响。
    """
    svc = _reload_service()
    shuffled = list(reversed(_REAL_5))
    groups = svc.group_by_occurrence(shuffled, 10 * 60 * 1000)
    assert groups["k_ria_3"]["root"] == "k_ria_1"
    assert groups["k_hq"]["root"] == "k_ria_1"


def test_message_lists_impacted_sites():
    """合并派单的通报必须列出实际涵盖的站点（正文英文，无中文）。"""
    svc = _reload_service()
    alarm = _alarm("k1", _BASE_MS, "RIA")
    impacted = [("4016", "Tower Hill"), ("HQ_Site", "HQ_Site")]

    text = svc.build_message(alarm, "4017", "R.I.A", "ZTE_NOC_FO", "TT202610270066",
                             dry_run=False, impacted=impacted)
    _assert_no_cjk(text)
    assert "This TT covers 3 sites from the same fiber cut:" in text
    assert "4017/R.I.A  (TT created on this site)" in text
    assert "4016/Tower Hill" in text
    assert "HQ_Site" in text

    # 只有 1 个站点（没合并）时正文保持原样，不追加空段落
    single = svc.build_message(alarm, "4017", "R.I.A", "ZTE_NOC_FO",
                               "TT202610270066", dry_run=False)
    assert "same fiber cut" not in single


def test_fiber_config_group_window_field():
    """合并窗口配置的解析：默认 10 分钟，env > 文件 > 默认，负数钳到 0。"""
    from backend.services.eflow_fiber import fiber_config as cfg

    out = cfg.parse_config({}, {})
    assert out["group_window_minutes"] == cfg.DEFAULT_GROUP_WINDOW_MINUTES == 10

    out = cfg.parse_config({"group_window_minutes": 30}, {})
    assert out["group_window_minutes"] == 30

    out = cfg.parse_config({"group_window_minutes": 30}, {cfg.ENV_GROUP_WINDOW: "5"})
    assert out["group_window_minutes"] == 5

    # 负数 → 0（关闭合并），不能让负值产生「负窗口」这种无意义配置
    out = cfg.parse_config({"group_window_minutes": -1}, {})
    assert out["group_window_minutes"] == 0

    # 非法值 → 回退默认
    out = cfg.parse_config({"group_window_minutes": "abc"}, {})
    assert out["group_window_minutes"] == cfg.DEFAULT_GROUP_WINDOW_MINUTES

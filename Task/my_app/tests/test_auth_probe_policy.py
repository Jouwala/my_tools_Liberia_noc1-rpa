# -*- coding: utf-8 -*-
"""auth_manager 会话探活（probe）与 401 重登策略的回归测试。

背景（2026-10-06）：缓存 TTL 未过期 ≠ 会话可用。实测证据：
  · MW UME 2026-10-04：复用共享会话后立刻 `401 Unauthorized`，
    `{"hasLogged":true}`，两个 MW 任务全部失败。
  · RAN UME 2026-10-06：缓存 04:45 写入、06:38 被 401 证死（存活 113 分钟），
    而 TTL 当时 86400 —— packet_loss_sync 连续四轮拿死 cookie 打，每轮 90s 失败。

本组测试盯的是**策略**（何时探、探失败怎么办、探几次），不盯具体业务端点：
探活函数由调用方注入，这里用假函数精确控制"活/死"。
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import auth_manager as am  # noqa: E402

HOST, PORT = "10.9.9.9", 28001
USER, PWD = "u", "p"


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """把缓存目录指向 tmp，避免污染真实 auth_cache/。"""
    d = tmp_path / "auth_cache"
    d.mkdir()
    monkeypatch.setattr(am, "AUTH_CACHE_DIR", d)
    return d


def _seed_cache(cache_dir: Path, ttl_written: int = 1800, age_sec: int = 0,
                cookie: str = "Z-AUTH-CODE=live", username: str = USER) -> Path:
    """写入一份「按 TTL 还没过期」的缓存，用于验证探活是否真的介入。

    2026-10-13：缓存文件名按 host:port:username 隔离（多账号主机防串号），
    故路径需带 username 片段。
    """
    acct = am._safe_account(username)
    f = cache_dir / (f"{HOST}_{PORT}_{acct}.json" if acct else f"{HOST}_{PORT}.json")
    created = datetime.now(timezone.utc) - timedelta(seconds=age_sec)
    f.write_text(json.dumps({
        "host": HOST, "port": PORT, "username": username,
        "cookie": cookie, "forgery_token": "ft",
        "auth_code": "CODE$10",
        "created_at": created.isoformat(),
        "expires_in": ttl_written,
    }, ensure_ascii=False), encoding="utf-8")
    return f


def _fail_login(monkeypatch):
    """让真实登录必定失败，用于区分「用了缓存」与「走了重登」。"""
    def _boom(*a, **kw):
        raise AssertionError("不应调用 _do_login")
    monkeypatch.setattr(am, "_do_login", _boom)


def _count_relogin(monkeypatch, cookie: str = "Z-AUTH-CODE=NEW"):
    """记录 _do_login 被调用次数，并返回一个可用的新会话。"""
    calls = []

    def _login(host, port, username, password):
        calls.append((host, port))
        return {"cookie": cookie, "forgery_token": "ft-new", "auth_code": "NEW$10"}

    monkeypatch.setattr(am, "_do_login", _login)
    return calls


# ---------- probe=None：保持历史行为（只信 TTL） ----------

def test_no_probe_keeps_legacy_behaviour(cache_dir, monkeypatch):
    """不传 probe 时行为与改动前一致：TTL 内直接用缓存，不探活。

    这是给「不具备探活能力」的主机留的兼容口，必须保持 —— 否则
    eFlow 这类登录协议不同的调用方会被莫名其妙地强制重登。
    """
    _seed_cache(cache_dir)
    _fail_login(monkeypatch)

    r = am.get_auth(HOST, PORT, USER, PWD)
    assert r["from_cache"] is True
    assert r["probed"] is False
    assert r["from_relogin"] is False


# ---------- probe 探活成功：复用缓存，不重登 ----------

def test_probe_alive_reuses_cache(cache_dir, monkeypatch):
    """探活通过 → 复用缓存，且**不发**重登。"""
    _seed_cache(cache_dir)
    _fail_login(monkeypatch)          # 一旦重登就炸
    seen = []

    def probe(cookie, token):
        seen.append((cookie, token))
        return True

    r = am.get_auth(HOST, PORT, USER, PWD, probe=probe)
    assert r["from_cache"] is True
    assert r["probed"] is True
    assert r["from_relogin"] is False
    assert r["cookie"] == "Z-AUTH-CODE=live"
    assert seen == [("Z-AUTH-CODE=live", "ft")], "探活必须拿到缓存里的真实 cookie"


# ---------- probe 探活失败：作废缓存 + 真实重登 ----------

def test_probe_dead_triggers_relogin(cache_dir, monkeypatch):
    """探活判定会话已死 → 作废缓存并真实重登（2026-10-06 事故的直接修复）。"""
    cache_file = _seed_cache(cache_dir)
    calls = _count_relogin(monkeypatch)

    def probe(cookie, token):
        return False

    r = am.get_auth(HOST, PORT, USER, PWD, probe=probe)
    assert len(calls) == 1, "探活失败必须重登且只重登一次"
    assert r["from_cache"] is False
    assert r["from_relogin"] is True
    assert r["cookie"] == "Z-AUTH-CODE=NEW"
    # 缓存文件应被新的会话覆盖（invalidate 后 _write_cache 重建）
    assert json.loads(cache_file.read_text(encoding="utf-8"))["cookie"] == "Z-AUTH-CODE=NEW"


def test_probe_raising_is_treated_as_dead(cache_dir, monkeypatch):
    """探活函数自身抛异常 → 按不可用处理并重登（绝不能把异常抛给调用方）。

    这条区分「探测本身坏了」与「会话死了」只体现在日志里，但**行为**必须
    一致地安全：拿不到证据就不复用，退回真实登录。
    """
    _seed_cache(cache_dir)
    calls = _count_relogin(monkeypatch)

    def probe(cookie, token):
        raise RuntimeError("网络抖动")

    r = am.get_auth(HOST, PORT, USER, PWD, probe=probe)
    assert len(calls) == 1
    assert r["from_relogin"] is True


# ---------- 探活次数：每轮取会话至多一发 ----------

def test_probe_called_at_most_once_on_cache_hit(cache_dir, monkeypatch):
    """命中缓存且探活通过时，探活恰好 1 次、登录 0 次。

    约束来源：探活会向上游发真实请求，本项目已因「每任务登录一次」把 eFlow
    打崩过一次 —— 绝不能让探活退化成请求风暴源。
    """
    _seed_cache(cache_dir)
    _fail_login(monkeypatch)
    n = []

    def probe(cookie, token):
        n.append(1)
        return True

    am.get_auth(HOST, PORT, USER, PWD, probe=probe)
    assert len(n) == 1


def test_probe_not_called_when_cache_miss(cache_dir, monkeypatch):
    """缓存未命中时无从探活（没有 cookie 可探）→ 直接登录，探活 0 次。"""
    calls = _count_relogin(monkeypatch)
    n = []

    def probe(cookie, token):
        n.append(1)
        return True

    r = am.get_auth(HOST, PORT, USER, PWD, probe=probe)
    assert n == [], "没有缓存就不该探活"
    assert len(calls) == 1
    assert r["from_relogin"] is True


# ---------- force_refresh 语义不能被 probe 破坏 ----------

def test_force_refresh_bypasses_cache_and_probe(cache_dir, monkeypatch):
    """force_refresh=True 表示「会话已确认死亡，必须真登录」：
    既不读缓存也不探活，直接重登一次。
    """
    _seed_cache(cache_dir)
    calls = _count_relogin(monkeypatch)
    n = []

    def probe(cookie, token):
        n.append(1)
        return True

    r = am.get_auth(HOST, PORT, USER, PWD, force_refresh=True, probe=probe)
    assert n == [], "force_refresh 语义是必须真登录，不该再探活"
    assert len(calls) == 1
    assert r["from_relogin"] is True


# ---------- TTL 夹紧仍然生效（与 probe 正交，防回归） ----------

def test_expired_cache_still_falls_back_to_login(cache_dir, monkeypatch):
    """TTL 已过期的缓存不采用（probe 未传时的兜底仍按时间判过期）。"""
    _seed_cache(cache_dir, ttl_written=1800, age_sec=3600)
    calls = _count_relogin(monkeypatch)

    r = am.get_auth(HOST, PORT, USER, PWD)
    assert len(calls) == 1
    assert r["from_relogin"] is True


# ---------- 门户探活登记表（2026-10-06 补 battery_ume） ----------

def test_battery_portal_has_probe_registered():
    """battery_ume 门户必须登记了探活端点，且**不能**是门户首页。

    依据：门户首页 /uportal/framework/default.html 对「无 cookie」也返回 200
    （SPA 外壳，与带垃圾 cookie 的响应逐字节相同），拿它探活会把死会话判成活
    （假绿）——这正是「一键登录总落回登录页」的成因之一。Battery 不是 UME
    PM-analysis 协议，必须用它自己的业务接口。
    """
    from backend.services import portal_login_service as p

    path = p.PORTAL_PROBE_PATHS.get("battery_ume")
    assert path, "battery_ume 应已登记探活端点"
    assert "uportal" not in path, "不得用门户首页当探针（对未登录也返回 200）"
    assert path == "/api/monitor-manager/v1/realtime-data/get-by-condition"
    # 必须真的能被 _portal_probe 解析出来（键不在 spec 里，靠反查）
    assert p._portal_probe(p.PORTALS["battery_ume"]) is not None


def test_ume_portals_share_pm_history_but_battery_does_not():
    """UME 系共用 PM history 端点；battery 必须与它们区分开。"""
    from backend.services import portal_login_service as p

    for k in ("zte_ume", "ccn_ume", "ipran_ume", "mw_ume", "ume_in"):
        assert p.PORTAL_PROBE_PATHS.get(k) == "/api/pm-analysis/v2/history"
    assert p.PORTAL_PROBE_PATHS["battery_ume"] != "/api/pm-analysis/v2/history"


def test_eflow_now_registered_with_measured_endpoint():
    """eflow 已登记（2026-10-06 实测），且必须是**业务接口**而非门户首页。"""
    from backend.services import portal_login_service as p

    path = p.PORTAL_PROBE_PATHS.get("eflow")
    assert path, "eflow 应已登记探活端点"
    assert "uportal" not in path, "不得用门户首页当探针（对未登录也返回 200）"
    assert path == "/api/fm-active/v1/activealarms/table"
    assert p._portal_probe(p.PORTALS["eflow"]) is not None


def test_non_getauth_portals_still_return_no_probe():
    """**不走 auth_manager.get_auth 的门户**必须保持不探活。

    rais / vmax_cxo / fw_kpi 的会话是「当场登录、当场种进浏览器」，
    从不经过 auth_manager 缓存 —— 给它们登记探针是**死代码没人调用**，
    只会让人以为覆盖到了。它们"落回登录页"另有原因（验证码、SSO 过期、
    互踢），不是 TTL/探活能修的。
    """
    from backend.services import portal_login_service as p

    for k in ("rais", "vmax_cxo", "fw_kpi"):
        assert p._portal_probe(p.PORTALS[k]) is None, f"{k} 不应被探活"
        # 顺便钉住"它们确实不走 get_auth"这个前提，前提变了本测试要重审
        assert p.PORTALS[k]["kind"] in ("rais", "vmax", "umc")


# ---------- 电池回退链探活（2026-10-06 补） ----------

def test_auth_info_freshness_is_time_based_only():
    """钉住 `auth_info_is_fresh` 的现状语义：**只按时间**判新鲜度。

    这是它必须被探活兜住的原因 —— 落在窗口内、但已被上游作废的会话，
    它一样返回 True。上游实测寿命 58~60 分钟，且可能被同账户别处
    登录踢掉。若哪天改成会探活，本测试会失败，提醒同步更新
    `_acquire_auth` 里的那次补探（否则变成探两次）。
    """
    import inspect

    from backend.services.battary_kpi_fetch import battary_kpi_fetch_socket as sock

    src = inspect.getsource(sock.auth_info_is_fresh)
    assert "probe" not in src.lower(), "若改为探活，请同步 _acquire_auth 的补探"
    assert "max_age_hours" in src


def test_auth_info_fresh_window_has_single_source_of_truth():
    """钉住新鲜度窗口**不再自己写死数字**，必须来自 `auth_manager._resolve_ttl`。

    2026-10-06 之前的写法是 `max_age_hours: float = 1.0` —— 与 auth_manager 的
    `AUTH_TTL_OVERRIDES`（该主机 1800s）是两个独立数字，正是工作区约束第 5 条
    禁止的"第二个真相源"。一旦只改一边就会静默分叉。
    """
    import inspect

    from backend.services import auth_manager as am
    from backend.services.battary_kpi_fetch import battary_kpi_fetch_socket as sock

    # 1) 窗口函数必须真的去问 auth_manager，而不是返回常量
    fsrc = inspect.getsource(sock._fresh_window_hours)
    assert "_resolve_ttl" in fsrc, "新鲜度窗口必须复用 auth_manager._resolve_ttl"

    # 2) 两个入口的默认值都必须是 None（表示"去问 auth_manager"），不得写死
    for fn in (sock.auth_info_is_fresh, sock.ensure_auth_info):
        sig = inspect.signature(fn)
        assert sig.parameters["max_age_hours"].default is None, (
            f"{fn.__name__} 的 max_age_hours 默认值必须是 None（动态取 TTL），"
            "写死数字会重新变成第二个真相源"
        )

    # 3) 真的算一遍：窗口应与 auth_manager 对同一主机给出的值一致
    sock._HOST, sock._PORT = "192.168.170.2", 443
    expected = am._resolve_ttl("192.168.170.2", 443) / 3600.0
    assert abs(sock._fresh_window_hours() - expected) < 1e-9

    # 4) 换一台主机要跟着变（证明不是巧合写死成 0.5）
    sock._HOST, sock._PORT = "10.100.20.8", 28001
    assert sock._fresh_window_hours() == am._resolve_ttl("10.100.20.8", 28001) / 3600.0
    assert sock._fresh_window_hours() != expected, "不同主机的窗口应不同"


def test_battery_acquire_auth_backstop_probes_before_return():
    """`_acquire_auth` 在返回前必须对回退链（login_rsa / auth_info.json）
    拿到的会话**补探一次** —— 否则死 cookie 会被直接交给 fetch_all_realtime。
    """
    import inspect

    from backend.services.battary_kpi_fetch import battery_kpi_service as bat

    src = inspect.getsource(bat._acquire_auth)
    assert "probe_battery_session" in src, "_acquire_auth 必须补探回退链会话"
    # 补探必须在 return 之前
    assert src.index("probe_battery_session") < src.rindex("return auth")

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
                cookie: str = "Z-AUTH-CODE=live") -> Path:
    """写入一份「按 TTL 还没过期」的缓存，用于验证探活是否真的介入。"""
    f = cache_dir / f"{HOST}_{PORT}.json"
    created = datetime.now(timezone.utc) - timedelta(seconds=age_sec)
    f.write_text(json.dumps({
        "host": HOST, "port": PORT, "username": USER,
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

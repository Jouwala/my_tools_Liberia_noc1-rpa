# -*- coding: utf-8 -*-
"""TT 告警推送的**配置项**单测：级别/告警码白名单、时间窗、重推间隔、群组回退。

拆自 `test_tt_alarm_whatsapp_service.py`（原文件超 500 行上限），
对应 `backend/services/tt_alarm_config.py` 的职责边界。

这里锁的是三类**真实发生过或极易踩**的错：
  1. 白名单字段「留空」被当成「全部排除」→ 一单都不发（真实发生过，见下）；
  2. env 与配置文件优先级验错（import 后再 setenv 不会重算常量）；
  3. 群组留空时静默发往测试群而无人知晓。
"""
import os
from datetime import datetime

from backend.services import tt_alarm_config as C
from backend.services import tt_alarm_whatsapp_service as S
from backend.services.tt_alarm_message import norm_alarm_code


def _mk_tt_db(tmp_path, rows):
    """造一个最小 eflow_tt（sqlite），rows: [(tt_no, sev, code, occur, clear)]"""
    import sqlite3
    conn = sqlite3.connect(tmp_path / "f.db")
    conn.execute("CREATE TABLE eflow_tt (tt_no TEXT, ticket_severity TEXT, "
                 "alarm_code TEXT, alarm_occur_time TEXT, alarm_clear_time TEXT)")
    conn.executemany("INSERT INTO eflow_tt VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def _use_db(monkeypatch, tmp_path):
    from backend import database as db
    from backend.services import tt_alarm_whatsapp_service as svc2
    monkeypatch.setattr(db, "DB_MODE", "sqlite")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "f.db")
    return svc2


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------- 白名单字段「留空」的语义 ----------------

def test_empty_severities_means_no_filter_not_drop_all(tmp_path, monkeypatch):
    """级别留空 = 不过滤（推送所有级别），**不是**一条都不发。

    回归锁：曾写成 `if sev not in SEVERITIES: continue`，空集时每一行都被 continue
    （`x in set()` 恒为 False），表现为「级别留空 → 一单都不发」，
    与页面标注的"留空=所有级别"完全相反。实测于 2026-09-28。
    """
    now = _now()
    _mk_tt_db(tmp_path, [("T1", "P1", "9920", now, None),
                         ("T2", "P4", "9920", now, None),
                         ("T3", "P2", "9920", now, None)])
    svc2 = _use_db(monkeypatch, tmp_path)
    monkeypatch.setattr(svc2, "SEVERITIES", set())

    picked, _ = svc2.fetch_candidate_tts()
    assert sorted(r["tt_no"] for r in picked) == ["T1", "T2", "T3"], \
        "级别留空时应不过滤，但部分/全部单被丢弃了"


def test_severity_filter_still_applies_when_set(tmp_path, monkeypatch):
    """级别非空时仍按白名单过滤。"""
    now = _now()
    _mk_tt_db(tmp_path, [("T1", "P1", "9920", now, None),
                         ("T2", "P4", "9920", now, None)])
    svc2 = _use_db(monkeypatch, tmp_path)
    monkeypatch.setattr(svc2, "SEVERITIES", {"P1"})

    picked, _ = svc2.fetch_candidate_tts()
    assert [r["tt_no"] for r in picked] == ["T1"]


def test_empty_alarm_codes_means_no_filter(tmp_path, monkeypatch):
    """告警码白名单留空 = 全部推送（含 99933）。"""
    now = _now()
    _mk_tt_db(tmp_path, [("A", "P1", "9920", now, None),
                         ("B", "P1", "99933", now, None),
                         ("C", "P1", "99933.0", now, None)])
    svc2 = _use_db(monkeypatch, tmp_path)
    monkeypatch.setattr(svc2, "ALARM_CODES", set())

    picked, _ = svc2.fetch_candidate_tts()
    assert sorted(r["tt_no"] for r in picked) == ["A", "B", "C"], \
        "告警码留空时应不过滤"


def test_alarm_code_whitelist_filters_and_normalizes(tmp_path, monkeypatch):
    """白名单命中才算；且 '9920.0' 与 '9920' 归一化后视为同一码。"""
    now = _now()
    _mk_tt_db(tmp_path, [("A", "P1", "9920", now, None),
                         ("B", "P1", "99933", now, None),
                         ("C", "P1", "99933.0", now, None),
                         ("D", "P1", "9920.0", now, None)])
    svc2 = _use_db(monkeypatch, tmp_path)
    monkeypatch.setattr(svc2, "ALARM_CODES", {"9920"})

    picked, _ = svc2.fetch_candidate_tts()
    assert sorted(r["tt_no"] for r in picked) == ["A", "D"], \
        "白名单应同时命中 '9920' 与 '9920.0'，并排除 99933 的两种写法"


def test_non_numeric_alarm_code_does_not_crash(tmp_path, monkeypatch):
    """文本告警码不能让过滤崩掉（库里确有 'Ethernet Physical...' 这类值）。"""
    now = _now()
    _mk_tt_db(tmp_path, [("TXT", "P1", "The link between the server and the ME is broken", now, None),
                         ("NUM", "P1", "9920", now, None)])
    svc2 = _use_db(monkeypatch, tmp_path)
    monkeypatch.setattr(svc2, "ALARM_CODES", {"9920"})

    picked, _ = svc2.fetch_candidate_tts()
    assert [r["tt_no"] for r in picked] == ["NUM"]


# ---------------- parse_config 纯函数：优先级与归一化 ----------------

def _p(conf, env=None):
    return C.parse_config(conf, norm_alarm_code, env or {})


def test_parse_config_defaults_when_nothing_configured():
    got = _p({}, {})
    assert got["window_minutes"] == C.DEFAULT_WINDOW_MINUTES
    assert got["resend_minutes"] == C.DEFAULT_RESEND_MINUTES
    assert got["severities"] == {"P1"}
    assert got["alarm_codes"] == set()
    assert got["groups"] == C.DEFAULT_GROUPS
    assert got["groups_fallback"] is True
    assert got["window_from"] == "default"


def test_parse_config_normalizes_each_field():
    """级别大写、告警码去浮点尾巴、群组去空白。"""
    got = _p({"severities": "p1, p2 ", "alarm_codes": "9920, 9995.0",
              "groups": " A , B ", "window_minutes": 90, "resend_minutes": 7}, {})
    assert got["severities"] == {"P1", "P2"}
    assert got["alarm_codes"] == {"9920", "9995"}
    assert got["groups"] == ["A", "B"]
    assert got["groups_fallback"] is False
    assert got["window_minutes"] == 90 and got["window_from"] == "file"


def test_parse_config_env_beats_file():
    got = _p({"window_minutes": 90, "groups": "FROM_FILE"},
             {"TT_ALERT_WINDOW_MINUTES": "42", "TT_ALERT_WHATSAPP_GROUPS": "FROM_ENV"})
    assert got["window_minutes"] == 42 and got["window_from"] == "env"
    assert got["groups"] == ["FROM_ENV"] and got["groups_from"] == "env"


def test_parse_config_blank_string_means_no_filter():
    """键存在但为空串 = 用户显式清空 = 不过滤（不是"不动"）。"""
    got = _p({"severities": "", "alarm_codes": ""}, {})
    assert got["severities"] == set()
    assert got["alarm_codes"] == set()
    assert got["severities_from"] == "file"


def test_parse_config_blank_groups_falls_back_to_test_group():
    """群组留空 → 回退默认测试群并标记 fallback（调用方据此告警）。"""
    got = _p({"groups": ""}, {})
    assert got["groups"] == C.DEFAULT_GROUPS
    assert got["groups_fallback"] is True


def test_parse_config_ignores_invalid_numbers():
    """非法数字不抛错，保留默认（页面填错不该让任务崩）。"""
    got = _p({"window_minutes": "abc", "resend_minutes": -5}, {})
    assert got["window_minutes"] == C.DEFAULT_WINDOW_MINUTES
    assert got["resend_minutes"] == C.DEFAULT_RESEND_MINUTES


# ---------------- 群组回退的可发现性 ----------------

def test_group_fallback_defaults_to_test_group():
    """群组为空时回退到 DEFAULT_GROUPS 并标记 fallback。"""
    assert C.DEFAULT_GROUPS == ["test123"]
    assert isinstance(S.GROUPS_FALLBACK, bool)
    if not os.environ.get("TT_ALERT_WHATSAPP_GROUPS"):
        assert S.GROUPS == S.DEFAULT_GROUPS
        assert S.GROUPS_FALLBACK is True


def test_group_fallback_is_flagged_in_task_result():
    """回退到测试群时，任务结果必须带 group_fallback=True 与醒目警告。

    这是需求方明确要求的"回退但要有明确提示"：生产 P1 告警发进 test123 是
    "发出去了但没人看"，比不发更隐蔽，必须能被发现。
    """
    out = S.run_tt_alarm_whatsapp_alert()
    assert "group_fallback" in out
    if out.get("group_fallback"):
        assert any("测试群" in e for e in out["errors"]), \
            "回退到测试群时必须有明确警告"


# ---------------- env 优先级必须在**新进程**里验 ----------------

def test_env_wins_over_config_file_in_fresh_process(tmp_path):
    """优先级：环境变量 > 配置文件 —— 必须用**子进程**验证。

    ⚠️ 为什么不能用 monkeypatch.setenv：env 是在 `import tt_alarm_whatsapp_service`
    的**那一刻**被读进模块常量的；import 之后再 setenv 不会让常量重算，
    于是测试会看到旧值而误判"env 没生效"（这是本测试第一版的真实错误）。
    真实运行时该优先级成立，因为 worker 是带着 env 启动的新进程。
    """
    import json as _json
    import subprocess
    import sys
    from pathlib import Path

    app_root = Path(__file__).resolve().parent.parent
    cfg = tmp_path / "tt_alert_whatsapp_config.json"
    cfg.write_text(_json.dumps({"window_minutes": 90, "groups": "FROM_FILE"}), encoding="utf-8")

    script = (
        "import sys, json, pathlib\n"
        f"sys.path.insert(0, r'{app_root}')\n"
        "from backend.services import tt_alarm_config as C\n"
        "from backend.services.tt_alarm_message import norm_alarm_code\n"
        f"C.CONFIG_FILE = pathlib.Path(r'{cfg}')\n"
        "got = C.load_config(norm_alarm_code)\n"
        "print(json.dumps({'window': got['window_minutes'], 'groups': got['groups']}))\n"
    )

    base = {k: v for k, v in os.environ.items() if not k.startswith("TT_ALERT_")}

    r1 = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                        encoding="utf-8", env=base)
    assert r1.returncode == 0, r1.stderr[-500:]
    got1 = _json.loads(r1.stdout.strip().splitlines()[-1])
    assert got1["window"] == 90 and got1["groups"] == ["FROM_FILE"], \
        "无 env 时应采用配置文件的值"

    env2 = dict(base, TT_ALERT_WINDOW_MINUTES="42", TT_ALERT_WHATSAPP_GROUPS="FROM_ENV")
    r2 = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                        encoding="utf-8", env=env2)
    assert r2.returncode == 0, r2.stderr[-500:]
    got2 = _json.loads(r2.stdout.strip().splitlines()[-1])
    assert got2["window"] == 42 and got2["groups"] == ["FROM_ENV"], \
        "env 应胜过配置文件"


# ---------------- 页面注册 ----------------

def test_config_registered_in_task_config_page():
    """任务必须注册进 Settings「任务配置」页，且五个可配置项都在 schema 里。"""
    from backend.services import task_config_files, task_configs_registry  # noqa: F401

    resource = task_config_files.get_resource("tt_alarm_whatsapp_alert")
    assert resource is not None, "tt_alarm_whatsapp_alert 未注册进任务配置页"
    for key in ("window_minutes", "resend_minutes", "severities", "alarm_codes", "groups"):
        assert key in resource.schema, f"schema 缺少可配置项 {key}"

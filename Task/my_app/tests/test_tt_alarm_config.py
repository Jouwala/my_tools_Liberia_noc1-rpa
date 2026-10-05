# -*- coding: utf-8 -*-
"""TT 告警推送的**配置项**单测：级别/告警码白名单、窗口、重报间隔、群组回退。

拆自 `test_tt_alarm_whatsapp_service.py`（原文件超 500 行上限），
对应 `backend/services/tt_alarm_config.py` 的职责边界。

这里锁的是三类**真实发生过或极易踩**的错：
  1. env 与配置文件优先级验错（import 后再 setenv 不会重算常量）；
  2. 群组留空时静默发往测试群而无人知晓；
  3. 「留空」语义被记反（级别/告警码留空 = 不过滤）。

过滤行为的业务用例：级别白名单见 test_tt_alarm_whatsapp_service.py（severity_passes），
告警码白名单见 test_tt_alarm_trigger.py（fetch_triggered_tts）。
"""
import os

from backend.services import tt_alarm_config as C
from backend.services import tt_alarm_whatsapp_service as S
from backend.services.tt_alarm_message import norm_alarm_code


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
    """群组为空时回退到 DEFAULT_GROUPS 并标记 fallback。

    **不要断言模块级常量 `S.GROUPS_FALLBACK is True`** —— 它取决于运行时是否存在
    `backend/services/tt_alert_whatsapp_config.json`。该文件由用户在「任务配置」页保存时
    创建，是**正常的生产状态**：用户一旦显式存了群组（哪怕存的就是 `test123`），
    fallback 就该是 False。

    这个断言曾这样写并在 2026-09-29 15:32 用户保存配置后误报：
        `assert False is True` —— 代码没错，是测试读了环境状态。
    故改为直接测 `parse_config`（纯函数、不受环境影响的唯一真相源）。
    """
    assert C.DEFAULT_GROUPS == ["test123"]

    # 空 → 回退 + 标记
    blank = _p({"groups": ""})
    assert blank["groups"] == C.DEFAULT_GROUPS
    assert blank["groups_fallback"] is True

    # 显式存了值（哪怕等于默认测试群）→ 不算回退，不该误报「正发往测试群」
    explicit = _p({"groups": "test123"})
    assert explicit["groups"] == ["test123"]
    assert explicit["groups_fallback"] is False, \
        "用户显式选择 test123 ≠ 配置缺失回退，两者必须可区分"

    # 完全没有配置来源 → 走内置默认，同样标记回退
    none = _p({})
    assert none["groups"] == C.DEFAULT_GROUPS
    assert none["groups_fallback"] is True


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

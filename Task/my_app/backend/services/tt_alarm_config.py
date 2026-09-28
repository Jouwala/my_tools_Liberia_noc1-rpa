"""TT 告警推送的可配置项（Settings →「任务配置」页面维护）。

从 `tt_alarm_whatsapp_service` 拆出，理由是配置项从 3 个涨到 6 个之后，
「读文件 + 归一化 + env 优先级 + 群组兜底」已是一块独立职责，且**可以纯函数测试**
（`parse_config()` 不碰全局、不碰 import 期状态）。

## 优先级

**环境变量 > 配置文件 > 内置默认。**

⚠️ 关键机制：env 与配置文件都是在 `import tt_alarm_whatsapp_service` 的**那一刻**
读进模块常量的。因此
  * 改页面配置 → 保存 API 会重启各 worker 组，worker 重新 import 才生效；
  * 进程内改 `os.environ`（例如测试里 setenv）**不会**让已算好的常量重算。
    要验证优先级必须起新进程（见 `tests/test_tt_alarm_whatsapp_service.py` 的
    `test_env_wins_over_config_file_in_fresh_process`）。

## 「留空」的语义（易错，三种字段各不相同）

| 字段 | 留空表示 | 为什么 |
| --- | --- | --- |
| `severities` | **不过滤**（所有级别） | 「不限级别」是合理的运维诉求 |
| `alarm_codes` | **不过滤**（所有告警码） | 同上；99933 只有显式填入才推送 |
| `groups` | 回退 `DEFAULT_GROUPS`（测试群）+ 显式告警 | 群组是投递地址，空地址无法投递；回退至少让消息可见 |

⚠️ `severities`/`alarm_codes` 留空时**必须**让调用方走「不过滤」分支：
写成 `if x not in SEVERITIES: continue` 时，空集会让**每一行**都被跳过
（`x in set()` 恒为 False），表现为「留空 = 一单都不发」，与上表完全相反。
这个坑真实发生过（2026-09-28），由
`test_empty_severities_means_no_filter_not_drop_all` 锁定。
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# 默认值（配置文件缺失 / 字段缺失时使用）
DEFAULT_WINDOW_MINUTES = 180
DEFAULT_RESEND_MINUTES = 20
DEFAULT_QUERY_LIMIT = 500
DEFAULT_SEVERITIES = "P1"
DEFAULT_GROUPS = ["test123"]

CONFIG_FILE = Path(__file__).resolve().parent / "tt_alert_whatsapp_config.json"

# 环境变量名（与 backend/.env.example 的键名一致）
ENV_WINDOW = "TT_ALERT_WINDOW_MINUTES"
ENV_RESEND = "TT_ALERT_RESEND_MINUTES"
ENV_LIMIT = "TT_ALERT_QUERY_LIMIT"
ENV_SEVERITIES = "TT_ALERT_SEVERITIES"
ENV_ALARM_CODES = "TT_ALERT_ALARM_CODES"
ENV_GROUPS = "TT_ALERT_WHATSAPP_GROUPS"


def csv_list(value: Any) -> List[str]:
    """逗号分隔 → 去空白非空列表。None/空 → []。"""
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


def csv_int(value: Any) -> Optional[int]:
    """逗号无关的整数字段；非法值返回 None（调用方保留默认，不抛错）。"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def norm_severities(value: Any) -> Set[str]:
    """级别：大写、去空白。空 → 空集（= 不过滤）。"""
    return {x.upper() for x in csv_list(value)}


def norm_alarm_codes(value: Any, norm_code) -> Set[str]:
    """告警码：用 `norm_code` 归一化（去浮点尾巴）。空 → 空集（= 不过滤）。"""
    return {c for c in (norm_code(x) for x in csv_list(value)) if c}


def parse_config(conf: Dict[str, Any], norm_code, env: Dict[str, str]) -> Dict[str, Any]:
    """把配置文件 dict + 环境变量解析成最终生效值（**纯函数**，不改任何全局）。

    返回 {window_minutes, resend_minutes, queries_limit, severities, alarm_codes,
          groups, groups_fallback, window_from, resend_from, ...}。
    `*_from` 标记该项最终来源（env / file / default），便于页面与排障时解释
    「为什么页面写 60 却按 180 跑」（通常是 env 覆盖了页面）。
    """
    out: Dict[str, Any] = {}

    def _int_field(cfg_key: str, env_key: str, default: int, lo: int = 1):
        env_raw = env.get(env_key)
        if env_raw not in (None, ""):
            val = csv_int(env_raw)
            if val is not None and val >= lo:
                return val, "env"
        if cfg_key and cfg_key in conf:
            val = csv_int(conf.get(cfg_key))
            if val is not None and val >= lo:
                return val, "file"
        return default, "default"

    out["window_minutes"], out["window_from"] = _int_field(
        "window_minutes", ENV_WINDOW, DEFAULT_WINDOW_MINUTES, lo=1)
    out["resend_minutes"], out["resend_from"] = _int_field(
        "resend_minutes", ENV_RESEND, DEFAULT_RESEND_MINUTES, lo=1)
    limit, _ = _int_field("query_limit", ENV_LIMIT, DEFAULT_QUERY_LIMIT, lo=1)
    out["query_limit"] = limit

    # 级别与告警码：env 优先，其次文件，最后默认。留空 = 空集 = 不过滤。
    def _set_field(cfg_key: str, env_key: str, default_raw: str, parser):
        env_raw = env.get(env_key)
        if env_raw not in (None, ""):
            return parser(env_raw), "env"
        if cfg_key in conf:
            # 注意：键存在但值为空串 = 用户显式清空 = 不过滤（不是"不动"）
            return parser(conf.get(cfg_key)), "file"
        return parser(default_raw), "default"

    out["severities"], out["severities_from"] = _set_field(
        "severities", ENV_SEVERITIES, DEFAULT_SEVERITIES, norm_severities)

    def _codes_parser(raw):
        return norm_alarm_codes(raw, norm_code)

    out["alarm_codes"], out["alarm_codes_from"] = _set_field(
        "alarm_codes", ENV_ALARM_CODES, "", _codes_parser)

    # 群组：留空 → 回退默认测试群，并标记 fallback（调用方必须据此告警）
    env_groups = csv_list(env.get(ENV_GROUPS))
    if env_groups:
        out["groups"], out["groups_from"], out["groups_fallback"] = env_groups, "env", False
    elif "groups" in conf and csv_list(conf.get("groups")):
        out["groups"] = csv_list(conf.get("groups"))
        out["groups_from"], out["groups_fallback"] = "file", False
    else:
        out["groups"] = list(DEFAULT_GROUPS)
        out["groups_from"], out["groups_fallback"] = "default", True
    return out


def load_config(norm_code, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """读配置文件（缺失/损坏按空处理）后调用 `parse_config`。"""
    import os as _os
    if env is None:
        env = dict(_os.environ)
    conf: Dict[str, Any] = {}
    try:
        from backend.services.task_config_files import load_json_config
    except ImportError:  # 兼容以脚本方式直接运行
        from task_config_files import load_json_config  # type: ignore
    loaded = load_json_config(CONFIG_FILE)
    if isinstance(loaded, dict):
        conf = loaded
    return parse_config(conf, norm_code, env)

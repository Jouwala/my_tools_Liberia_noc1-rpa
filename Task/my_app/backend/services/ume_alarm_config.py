# -*- coding: utf-8 -*-
"""ZTE UME 告警推送的可配置项（Settings →「任务配置」页面维护）。

## 优先级

**环境变量 > 配置文件 > 内置默认**，与 `tt_alarm_config.py` 同款。
env / 文件都在 `import ume_alarm_whatsapp_service` 时读进模块常量，
所以「改页面 → 保存 → worker 组重启 → 重新 import」才生效。

## 「留空」的语义（易错，三种字段各不相同）

| 字段 | 留空表示 | 为什么 |
| --- | --- | --- |
| `alarm_codes` | **不过滤**（所有告警码） | 「不限码」是合理诉求；填了才按白名单过滤 |
| `alarm_levels` | **不过滤**（所有级别） | 同上 |
| `groups` | 回退 `DEFAULT_GROUPS`（测试群）+ 显式告警 | 群组是投递地址，空地址无法投递 |

⚠️ `alarm_codes` / `alarm_levels` 留空时**必须**走「不过滤」分支：
写成 `if x not in CODES: continue` 时空集会跳过**每一行**（`x in set()` 恒 False），
表现为「留空 = 一条都不发」，与上表相反。这个坑在 eFlow 侧真实发生过
（`tt_alarm_config.py:26-31`），故这里同样单独说明并由单测锁定。
"""
from pathlib import Path
from typing import Any, Dict, List, Set

# 默认值（配置文件缺失 / 字段缺失时使用）
# 默认只推 major 及以上的 89029 / 89006 两个码 —— 与需求方给的口径一致；
# 页面可改为任意组合，留空即不过滤。
DEFAULT_ALARM_CODES = "89029,89006"
DEFAULT_ALARM_LEVELS = "major,critical"
DEFAULT_GROUPS = ["test123"]           # 兜底测试群（生产由页面填真实群名）
DEFAULT_RESEND_MINUTES = 10            # 未清除告警的催报间隔（分钟）
DEFAULT_BOOTSTRAP = True               # 首轮只登记不发送（防存量刷群）

CONFIG_FILE = Path(__file__).resolve().parent / "ume_alarm_config.json"

# 环境变量名（与 backend/.env.example 的键名一致）
ENV_ALARM_CODES = "UME_ALARM_CODES"
ENV_ALARM_LEVELS = "UME_ALARM_LEVELS"
ENV_GROUPS = "UME_ALARM_WHATSAPP_GROUPS"
ENV_RESEND = "UME_ALARM_RESEND_MINUTES"
ENV_BOOTSTRAP = "UME_ALARM_BOOTSTRAP"


def truthy(value: Any, default: bool = False) -> bool:
    """宽松布尔解析：'1/true/yes/on' = 真，'0/false/no/off' = 假。

    ⚠️ 不能写 `str(value or "")`：JSON 里的布尔 `false` 是 Python `False`，
    `False or ""` 塌成 `""`，于是「明确写了 false」被当成"没配置"退回默认。
    （`tt_alarm_config.truthy` 的单测逮到过同一问题。）
    """
    if isinstance(value, bool):
        return value
    txt = str("" if value is None else value).strip().lower()
    if txt in ("1", "true", "yes", "on"):
        return True
    if txt in ("0", "false", "no", "off"):
        return False
    return default


def csv_list(value: Any) -> List[str]:
    """逗号分隔 → 去空白非空列表。None/空 → []。"""
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


def csv_int(value: Any):
    """整数字段；非法值返回 None（调用方保留默认，不抛错）。"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def norm_levels(value: Any) -> Set[str]:
    """级别：小写、去空白。空 → 空集（= 不过滤）。"""
    return {x.lower() for x in csv_list(value)}


def norm_codes(value: Any, norm_code) -> Set[str]:
    """告警码：用 `norm_code` 归一化（去浮点尾巴）。空 → 空集（= 不过滤）。"""
    return {c for c in (norm_code(x) for x in csv_list(value)) if c}


def parse_config(conf: Dict[str, Any], norm_code,
                 env: Dict[str, str]) -> Dict[str, Any]:
    """把配置文件 dict + 环境变量解析成最终生效值（**纯函数**）。

    `*_from` 标记每一项的最终来源（env / file / default），便于排障时解释
    「为什么页面写 A 却按 B 跑」（通常是 env 覆盖了页面）。
    """
    out: Dict[str, Any] = {}

    def _int_field(cfg_key: str, env_key: str, default: int, lo: int = 1):
        env_raw = env.get(env_key)
        if env_raw not in (None, ""):
            val = csv_int(env_raw)
            if val is not None and val >= lo:
                return val, "env"
        if cfg_key in conf:
            val = csv_int(conf.get(cfg_key))
            if val is not None and val >= lo:
                return val, "file"
        return default, "default"

    out["resend_minutes"], out["resend_from"] = _int_field(
        "resend_minutes", ENV_RESEND, DEFAULT_RESEND_MINUTES, lo=1)

    def _set_field(cfg_key: str, env_key: str, default_raw: str, parser):
        env_raw = env.get(env_key)
        if env_raw not in (None, ""):
            return parser(env_raw), "env"
        if cfg_key in conf:
            # 键存在但值为空串 = 用户显式清空 = 不过滤（不是"不动"）
            return parser(conf.get(cfg_key)), "file"
        return parser(default_raw), "default"

    out["alarm_codes"], out["alarm_codes_from"] = _set_field(
        "alarm_codes", ENV_ALARM_CODES, DEFAULT_ALARM_CODES,
        lambda raw: norm_codes(raw, norm_code))
    out["alarm_levels"], out["alarm_levels_from"] = _set_field(
        "alarm_levels", ENV_ALARM_LEVELS, DEFAULT_ALARM_LEVELS, norm_levels)

    # 群组：留空 → 回退默认测试群并标记 fallback（调用方必须据此告警）
    env_groups = env.get(ENV_GROUPS)
    if env_groups not in (None, ""):
        groups, groups_from = csv_list(env_groups), "env"
    elif "groups" in conf:
        groups, groups_from = csv_list(conf.get("groups")), "file"
    else:
        groups, groups_from = [], "default"
    fallback = not groups
    out["groups"] = groups or list(DEFAULT_GROUPS)
    out["groups_from"] = groups_from
    out["groups_fallback"] = fallback

    # 首轮只登记不发送
    env_boot = env.get(ENV_BOOTSTRAP)
    if env_boot not in (None, ""):
        out["bootstrap"], out["bootstrap_from"] = truthy(env_boot, True), "env"
    elif "bootstrap" in conf:
        out["bootstrap"], out["bootstrap_from"] = truthy(conf.get("bootstrap"), True), "file"
    else:
        out["bootstrap"], out["bootstrap_from"] = DEFAULT_BOOTSTRAP, "default"

    return out


def load_config(norm_code, env=None) -> Dict[str, Any]:
    """读配置文件 + 环境变量 → 生效配置。文件缺失/损坏时回退默认（记警告）。"""
    from backend.services.task_config_files import load_json_config
    conf = load_json_config(CONFIG_FILE)
    if conf is None:
        conf = {}
    import os
    return parse_config(conf, norm_code, os.environ if env is None else env)

# -*- coding: utf-8 -*-
"""eFlow 自动派单的**共用底座**（Fiber Break / 5G 站点告警共用）。

## 为什么抽出这一层（2026-10-28 立项 5G 派单）

Fiber Break（4758）与 5G 站点告警（200201001 等）走的是**同一条链路**：
查 eFlow 实时告警 → 判定「存续满 N 分钟」→ 站点解析 → 派单 → 回查 ttid →
WhatsApp 通报 → 状态落表。两者只有「告警码集合」与「站点字段形态」不同。

抽出共用底座后，各业务线只需声明自己的告警码与 restype，
**判定口径（15 分钟下界、窗口上界、重试预算、演练开关、通知模板）只有一份实现**，
不会出现「改了 Fiber 的边界，5G 忘了改」这类双份真相源。

## 优先级

**环境变量 > 配置文件 > 内置默认。**

⚠ 与 `tt_alarm_config` / `ume_alarm_config` 一致：配置在
`import <业务服务模块>` 的**那一刻**读进模块常量，改页面后
保存 API 会重启各 worker 组，worker 重新 import 才生效。

## 「留空」语义

| 字段 | 留空表示 |
| --- | --- |
| `alarm_codes` | 回退该业务线的内置默认（不允许全空：没有告警码就无从匹配） |
| `groups` | 回退 `DEFAULT_GROUPS`（测试群）+ 显式告警 |

## 两条时间边界（易混，必须分清）

| 配置项 | 边界 | 含义 |
| --- | --- | --- |
| `min_age_minutes` | **下界** | 告警升起后先存在满 N 分钟才派（默认 15，业务口径「超过 15 分钟才派单」） |
| `window_minutes` | **上界** | 告警升起超过 N 分钟就不再派（默认 180，防上线瞬间把积压告警一次性全派出去） |
| `correlation_window_minutes` | 关联判定 | 两条告警升起时间相差在此窗口内才算「同时间」（默认 60） |

`min_age_minutes` 配 0 = 恢复「一升起就派」的旧行为。
"""
from typing import Any, Dict, List, Set

# 派单目标用户组（从 /api/fms-assign-svr/v1/wo/userGroupList 按名解析 groupId）
DEFAULT_ASSIGN_GROUP = "ZTE_NOC_FO"
# 演练模式：true = 只查+匹配+记录将要派的单，不调用派单接口（首次上线更安全）
DEFAULT_DRY_RUN = True
DEFAULT_GROUPS: List[str] = ["test123"]

# 派单重试：eFlow 派单「时灵时不灵」，必须重试到 TT 真建出为止。
# 环境变量可调，默认 3 次 × 3s。
ASSIGN_MAX_ATTEMPTS = 3
ASSIGN_RETRY_DELAY = 3.0

# 站点名近似匹配阈值（0.5~1.0）：cmdb 与网管命名不一致时的兜底。
# 0.9 能容忍 1~2 个字母的拼写差异，又不会把不同站点判成同一个。
DEFAULT_SITE_FUZZY_ENABLED = True
DEFAULT_SITE_FUZZY_THRESHOLD = 0.9


def truthy(value: Any, default: bool = False) -> bool:
    """宽松布尔解析（与 tt_alarm_config.truthy 同款，避免 `false or ''` 塌成默认）。"""
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


def norm_code(value: Any) -> str:
    """告警码归一化：'4758' / 4758 / '4758.0' → '4758'。空/非法 → ''。"""
    txt = str(value if value is not None else "").strip()
    if not txt:
        return ""
    if txt.endswith(".0") and txt[:-2].isdigit():
        txt = txt[:-2]
    return txt


def parse_common_config(conf: Dict[str, Any], env: Dict[str, str], *,
                        default_alarm_codes: List[str],
                        default_correlation_codes: List[str],
                        env_alarm_codes: str,
                        env_correlation_codes: str,
                        env_correlation_window: str,
                        env_window: str,
                        env_min_age: str,
                        env_group: str,
                        env_dry_run: str,
                        env_groups: str,
                        env_site_fuzzy_enabled: str,
                        env_site_fuzzy_threshold: str,
                        env_group_window: str,
                        default_window_minutes: int = 180,
                        default_min_age_minutes: int = 15,
                        default_correlation_window_minutes: int = 60,
                        default_group_window_minutes: int = 10,
                        ) -> Dict[str, Any]:
    """解析共用配置项 → 生效配置字典（纯函数，不改全局）。

    各业务线在此基础上再叠加自己的字段（如 5G 的 `restypes` / `cell_dedupe`）。

    环境变量名由调用方传入 —— Fiber 用 `FIBER_ASSIGN_*`、5G 用 `EFLOW_5G_*`，
    两者互不干扰（共用底座不硬编码任何业务线的变量名）。
    """
    out: Dict[str, Any] = {}

    # 告警码（必填，留空回退默认）
    env_codes = env.get(env_alarm_codes)
    if env_codes not in (None, ""):
        codes = {norm_code(c) for c in csv_list(env_codes)}
        codes_from = "env"
    elif conf.get("alarm_codes"):
        codes = {norm_code(c) for c in csv_list(conf.get("alarm_codes"))}
        codes_from = "file"
    else:
        codes, codes_from = set(default_alarm_codes), "default"
    out["alarm_codes"] = codes or set(default_alarm_codes)
    out["alarm_codes_from"] = codes_from if codes else "default"

    # 关联告警码（站点已有则跳过派单）
    env_corr = env.get(env_correlation_codes)
    if env_corr not in (None, ""):
        corr = {norm_code(c) for c in csv_list(env_corr)}
        corr_from = "env"
    elif "correlation_codes" in conf:
        corr = {norm_code(c) for c in csv_list(conf.get("correlation_codes"))}
        corr_from = "file"
    else:
        corr, corr_from = set(default_correlation_codes), "default"
    out["correlation_codes"] = corr
    out["correlation_codes_from"] = corr_from

    def _int_field(cfg_key: str, env_key: str, default: int) -> None:
        raw = env.get(env_key)
        src = "env"
        if raw in (None, ""):
            raw = conf.get(cfg_key)
            src = "file"
        try:
            val = int(raw) if raw not in (None, "") else default
            out[cfg_key] = val
            out[cfg_key + "_from"] = src if raw not in (None, "") else "default"
        except (TypeError, ValueError):
            out[cfg_key] = default
            out[cfg_key + "_from"] = "default"

    _int_field("correlation_window_minutes", env_correlation_window,
               default_correlation_window_minutes)
    _int_field("window_minutes", env_window, default_window_minutes)
    # 合并派单时间窗：负数配歪了按 0 处理（= 关闭合并，恢复每条一单）。
    _int_field("group_window_minutes", env_group_window, default_group_window_minutes)
    if out.get("group_window_minutes", 0) < 0:
        out["group_window_minutes"] = 0
        out["group_window_minutes_from"] = "default"
    # 最小存续时长（下界）：负数配歪了按 0 处理（= 立即派单），
    # 不能让负数把「等满 N 分钟」变成「提前 N 分钟派」。
    _int_field("min_age_minutes", env_min_age, default_min_age_minutes)
    if out.get("min_age_minutes", 0) < 0:
        out["min_age_minutes"] = 0
        out["min_age_minutes_from"] = "default"

    # 派单目标组
    env_grp = env.get(env_group)
    if env_grp not in (None, ""):
        out["assign_group"], out["assign_group_from"] = env_grp.strip(), "env"
    elif conf.get("assign_group"):
        out["assign_group"], out["assign_group_from"] = str(conf["assign_group"]).strip(), "file"
    else:
        out["assign_group"], out["assign_group_from"] = DEFAULT_ASSIGN_GROUP, "default"

    # 演练模式
    env_dry = env.get(env_dry_run)
    if env_dry not in (None, ""):
        out["dry_run"], out["dry_run_from"] = truthy(env_dry, True), "env"
    elif "dry_run" in conf:
        out["dry_run"], out["dry_run_from"] = truthy(conf.get("dry_run"), True), "file"
    else:
        out["dry_run"], out["dry_run_from"] = DEFAULT_DRY_RUN, "default"

    # WhatsApp 群组
    env_groups = env.get(env_groups)
    if env_groups not in (None, ""):
        groups, groups_from = csv_list(env_groups), "env"
    elif conf.get("groups"):
        groups, groups_from = csv_list(conf.get("groups")), "file"
    else:
        groups, groups_from = [], "default"
    out["groups"] = groups or list(DEFAULT_GROUPS)
    out["groups_from"] = groups_from
    out["groups_fallback"] = not groups

    # 站点名近似匹配：开关 + 阈值（阈值必须钳在 [0.5, 1.0]，配歪了等于乱派）
    env_fz = env.get(env_site_fuzzy_enabled)
    if env_fz not in (None, ""):
        out["site_fuzzy_enabled"] = truthy(env_fz, DEFAULT_SITE_FUZZY_ENABLED)
        out["site_fuzzy_enabled_from"] = "env"
    elif "site_fuzzy_enabled" in conf:
        out["site_fuzzy_enabled"] = truthy(conf.get("site_fuzzy_enabled"),
                                           DEFAULT_SITE_FUZZY_ENABLED)
        out["site_fuzzy_enabled_from"] = "file"
    else:
        out["site_fuzzy_enabled"] = DEFAULT_SITE_FUZZY_ENABLED
        out["site_fuzzy_enabled_from"] = "default"

    raw_th = env.get(env_site_fuzzy_threshold)
    th_from = "env"
    if raw_th in (None, ""):
        raw_th = conf.get("site_fuzzy_threshold")
        th_from = "file"
    try:
        threshold = float(raw_th) if raw_th not in (None, "") else DEFAULT_SITE_FUZZY_THRESHOLD
    except (TypeError, ValueError):
        threshold, th_from = DEFAULT_SITE_FUZZY_THRESHOLD, "default"
    if not (0.5 <= threshold <= 1.0):
        threshold, th_from = DEFAULT_SITE_FUZZY_THRESHOLD, "default"
    out["site_fuzzy_threshold"] = threshold
    out["site_fuzzy_threshold_from"] = th_from if raw_th not in (None, "") else "default"

    return out


def load_json_config(path) -> Dict[str, Any]:
    """读配置文件 → dict；缺失/损坏返回 {}（调用方回退内置默认）。"""
    from backend.services.task_config_files import load_json_config as _load
    conf = _load(path)
    return conf if isinstance(conf, dict) else {}

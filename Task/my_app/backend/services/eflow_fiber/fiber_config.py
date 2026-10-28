# -*- coding: utf-8 -*-
"""Fiber Break 自动派单的可配置项（Settings →「任务配置」页面维护）。

## 优先级

**环境变量 > 配置文件 > 内置默认。**

⚠ 与 `tt_alarm_config` / `ume_alarm_config` 一致：配置在
`import fiber_assign_service` 的**那一刻**读进模块常量，改页面后
保存 API 会重启各 worker 组，worker 重新 import 才生效。

## 「留空」语义

| 字段 | 留空表示 |
| --- | --- |
| `alarm_codes` | 回退内置默认（4758），不允许全空（没有告警码就无从匹配） |
| `groups` | 回退 `DEFAULT_GROUPS`（测试群）+ 显式告警 |

## 告警码可配置

需求明确要求「告警码要可以配置」：默认 `4758`（Fiber Break），
页面可改成逗号分隔的多个码（如 `4758,4759`），匹配时按文本归一化后判等。

## 两条时间边界（易混，必须分清）

| 配置项 | 边界 | 含义 |
| --- | --- | --- |
| `min_age_minutes` | **下界** | 告警升起后先存在满 N 分钟才派（默认 15，业务口径「超过 15 分钟才派单」） |
| `window_minutes` | **上界** | 告警升起超过 N 分钟就不再派（默认 180，防上线瞬间把积压告警一次性全派出去） |
| `correlation_window_minutes` | 关联判定 | 两条告警升起时间相差在此窗口内才算「同时间」（默认 60） |

`min_age_minutes` 配 0 = 恢复「一升起就派」的旧行为。
"""
from pathlib import Path
from typing import Any, Dict, List, Set

# 默认告警码：4758 = Fiber Break（ZTE TRM IPRAN / DWDM 光路中断）
DEFAULT_ALARM_CODES = ["4758"]
DEFAULT_ALARM_CODE_NAME = "Fiber Break"
# 站点已有该码时不派单（需求：查询该站同时间是否已有 99933 告警，有则不派单）
DEFAULT_CORRELATION_CODES = ["99933"]
# 关联判定的时间窗口（分钟）：告警升起时间相差在此窗口内才算「同时间」
DEFAULT_CORRELATION_WINDOW_MINUTES = 60
# 只在告警升起后该窗口内才派单（防止上线瞬间把积压的历史未清除告警一次性全派出去）
DEFAULT_WINDOW_MINUTES = 180
# 告警**最小存续时长**（分钟）：告警升起后必须先存在满 N 分钟才允许派单。
# 业务口径（2026-10-27）：「告警发生到选择超过 15 分钟才要指派单子和发 WhatsApp」——
# 即**不是一升起就派**，而是等到 15 分钟后才派。留出这段时间是为了让短时闪断
# （瞬时抖动、几分钟内自愈的告警）自然清除，避免建出一堆无效 TT。
# ⚠ 与 `window_minutes` 是**两条独立的边界**：
#     `min_age_minutes` = 下界（太新不派）；`window_minutes` = 上界（太老不派）。
#   配 0 = 恢复「一升起就派」的旧行为（回滚开关）。
DEFAULT_MIN_AGE_MINUTES = 15
# 派单目标用户组（从 /api/fms-assign-svr/v1/wo/userGroupList 按名解析 groupId）
DEFAULT_ASSIGN_GROUP = "ZTE_NOC_FO"
# 演练模式：true = 只查+匹配+记录将要派的单，不调用派单接口（首次上线更安全）
DEFAULT_DRY_RUN = True
DEFAULT_GROUPS: List[str] = ["test123"]

# 同一次光纤中断的「合并派单」时间窗（分钟，2026-10-27 需求）。
# 动机：一条光缆断掉会让链路上**多个站点同时告警**（实测 2026-10-27 14:21
# 一次故障派出 5 个 TT：R.I.A×3 + Tower Hill + HQ_Site，集中在 9 秒内），
# 现场反馈是同一个故障，却建了 5 个重复单。
# 规则：升起时间落在此窗口内的多条 fiber 告警合并为**一个** TT，
# 通报正文列出实际涵盖的站点与告警条数。
#
# ⚠ 为什么用时间窗而不是拓扑：实测项目现有数据**判不出**「同一条光纤」——
#   `probeid` 全库同一个 UUID、`impact_site_list`/`link_path` 全空、
#   `flm_database.fdn` 被 96 个站点共用（太粗）、`victim_topology` 里
#   R.I.A 与 Tower Hill 互不包含且各是独立网关、eFlow `relatedAlarms` 返回 0 条。
#   故时间聚集是唯一立即可用的强信号。
# 配 0 = 关闭合并（恢复「每条告警派一单」的旧行为，回滚开关）。
DEFAULT_GROUP_WINDOW_MINUTES = 10

# 站点名近似匹配兜底（2026-10-27 需求）。
# 动机：cmdb 与网管命名常不一致，实测 `6120HS_Peter_luogan_town_UPE80` 的 fiber
# 告警推出站名 `Peter luogan town`，cmdb 写作 `Peter Luogon Town`（差一字母）→
# 该告警每轮记 N、永远派不出去。开启后在「精确 / 归一化精确」都查不到时，
# 按相似度兜底，并带歧义保护（最优候选必须唯一领先，否则不派）。
DEFAULT_SITE_FUZZY_ENABLED = True
# 相似度阈值（0.5~1.0，越接近 1 越严格）。0.9 能容忍 1~2 个字母的拼写差异，
# 又不会把不同站点判成同一个 —— 调低会显著提高错派风险，谨慎。
DEFAULT_SITE_FUZZY_THRESHOLD = 0.9

CONFIG_FILE = (
    Path(__file__).resolve().parent.parent / "eflow_fiber_config.json"
)

# 环境变量名（与 backend/.env.example 的键名一致）
ENV_ALARM_CODES = "FIBER_ASSIGN_ALARM_CODES"
ENV_CORRELATION_CODES = "FIBER_ASSIGN_CORRELATION_CODES"
ENV_CORRELATION_WINDOW = "FIBER_ASSIGN_CORRELATION_WINDOW_MINUTES"
ENV_WINDOW = "FIBER_ASSIGN_WINDOW_MINUTES"
ENV_MIN_AGE = "FIBER_ASSIGN_MIN_AGE_MINUTES"
ENV_GROUP = "FIBER_ASSIGN_GROUP"
ENV_DRY_RUN = "FIBER_ASSIGN_DRY_RUN"
ENV_GROUPS = "FIBER_ASSIGN_WHATSAPP_GROUPS"
ENV_SITE_FUZZY_ENABLED = "FIBER_ASSIGN_SITE_FUZZY_ENABLED"
ENV_SITE_FUZZY_THRESHOLD = "FIBER_ASSIGN_SITE_FUZZY_THRESHOLD"
ENV_GROUP_WINDOW = "FIBER_ASSIGN_GROUP_WINDOW_MINUTES"


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


def parse_config(conf: Dict[str, Any], env: Dict[str, str]) -> Dict[str, Any]:
    """把配置文件 dict + 环境变量解析成最终生效值（纯函数，不改全局）。"""
    out: Dict[str, Any] = {}

    # 告警码（必填，留空回退默认）
    env_codes = env.get(ENV_ALARM_CODES)
    if env_codes not in (None, ""):
        codes = {norm_code(c) for c in csv_list(env_codes)}
        codes_from = "env"
    elif conf.get("alarm_codes"):
        codes = {norm_code(c) for c in csv_list(conf.get("alarm_codes"))}
        codes_from = "file"
    else:
        codes, codes_from = set(DEFAULT_ALARM_CODES), "default"
    out["alarm_codes"] = codes or set(DEFAULT_ALARM_CODES)
    out["alarm_codes_from"] = codes_from if codes else "default"

    # 关联告警码（站点已有则跳过派单）
    env_corr = env.get(ENV_CORRELATION_CODES)
    if env_corr not in (None, ""):
        corr = {norm_code(c) for c in csv_list(env_corr)}
        corr_from = "env"
    elif "correlation_codes" in conf:
        corr = {norm_code(c) for c in csv_list(conf.get("correlation_codes"))}
        corr_from = "file"
    else:
        corr, corr_from = set(DEFAULT_CORRELATION_CODES), "default"
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

    _int_field("correlation_window_minutes", ENV_CORRELATION_WINDOW,
               DEFAULT_CORRELATION_WINDOW_MINUTES)
    _int_field("window_minutes", ENV_WINDOW, DEFAULT_WINDOW_MINUTES)
    # 合并派单时间窗：负数配歪了按 0 处理（= 关闭合并，恢复每条一单）。
    _int_field("group_window_minutes", ENV_GROUP_WINDOW, DEFAULT_GROUP_WINDOW_MINUTES)
    if out.get("group_window_minutes", 0) < 0:
        out["group_window_minutes"] = 0
        out["group_window_minutes_from"] = "default"
    # 最小存续时长（下界）：负数配歪了按 0 处理（= 立即派单），
    # 不能让负数把「等满 N 分钟」变成「提前 N 分钟派」。
    _int_field("min_age_minutes", ENV_MIN_AGE, DEFAULT_MIN_AGE_MINUTES)
    if out.get("min_age_minutes", 0) < 0:
        out["min_age_minutes"] = 0
        out["min_age_minutes_from"] = "default"

    # 派单目标组
    env_grp = env.get(ENV_GROUP)
    if env_grp not in (None, ""):
        out["assign_group"], out["assign_group_from"] = env_grp.strip(), "env"
    elif conf.get("assign_group"):
        out["assign_group"], out["assign_group_from"] = str(conf["assign_group"]).strip(), "file"
    else:
        out["assign_group"], out["assign_group_from"] = DEFAULT_ASSIGN_GROUP, "default"

    # 演练模式
    env_dry = env.get(ENV_DRY_RUN)
    if env_dry not in (None, ""):
        out["dry_run"], out["dry_run_from"] = truthy(env_dry, True), "env"
    elif "dry_run" in conf:
        out["dry_run"], out["dry_run_from"] = truthy(conf.get("dry_run"), True), "file"
    else:
        out["dry_run"], out["dry_run_from"] = DEFAULT_DRY_RUN, "default"

    # WhatsApp 群组
    env_groups = env.get(ENV_GROUPS)
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
    env_fz = env.get(ENV_SITE_FUZZY_ENABLED)
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

    raw_th = env.get(ENV_SITE_FUZZY_THRESHOLD)
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


def load_config(env=None) -> Dict[str, Any]:
    """读配置文件 + 环境变量 → 生效配置。文件缺失/损坏时回退默认。"""
    from backend.services.task_config_files import load_json_config
    conf = load_json_config(CONFIG_FILE)
    if not isinstance(conf, dict):
        conf = {}
    import os
    return parse_config(conf, os.environ if env is None else env)

# -*- coding: utf-8 -*-
"""5G 站点告警自动派单的可配置项（Settings →「任务配置」页面维护）。

## 与 Fiber 的关系（2026-10-28）

解析本体走共用底座 `backend/services/eflow_assign/assign_config.py`
（与 Fiber Break 派单共用，避免两份真相源）。本模块只声明 5G 自己的：
默认告警码、默认 restype、环境变量名。

## 告警码**必须支持多个**（需求明确要求）

默认 5 个 5G 站点退服类告警码：

| 告警码 | 告警名 |
| --- | --- |
| `200201001` | DU cell out-of-service |
| `200201018` | Super cell CP out-of-service |
| `200201041` | gNodeB DU out-of-service |
| `200201043` | NSA unavailable |
| `200201060` | Super MIMO cell CP out-of-service |

页面可改成逗号分隔的任意多个码，匹配时按文本归一化后判等。

## restype —— 服务端过滤的关键（⚠ 静默失效风险）

5G 派单用**服务端按码过滤**拉实时告警（实测全量 6752 条 / 4.4s，按码过滤
21 条 / 0.03s）。但 eFlow 的 `alarmcodeconds` **必须同时带 `restype`**：
只给 `alarmcode` 会返回 HTTP **499**、0 条（实测）。

⚠ **restype 猜错 = 该码永远静默不触发**（服务端把它整个滤掉，且无任何报错）。
实测存在的 `200201001` 的 restype 是 `zte.ran.gnodeb`；其余 4 个码当前
**无实例**、无法实测其 restype。故：

* 默认配一组**较宽**的 RAN restype 候选（`zte.ran.*` + `zte.trm_mw.nr*`），
  覆盖 gNodeB / nodeB / DU / CP 等；
* 实测确认：**组合里混入当前无实例的码不会让查询失败**（HTTP 200，正常返回），
  且 12 restype × 6 码 = 72 组合仍只要 0.03s；
* 实测确认：**通配 restype（`zte.ran.*` / `*`）不被支持**（返回 0 条），
  故只能穷举具体值；
* 提供 `fallback_full_scan` 开关（默认开）：开启时若按码过滤的结果里
  **一个目标码都没出现**，再拉一次全量做兜底比对 —— 彻底消除
  「restype 配漏导致某码永远不触发」的静默失效。

## 优先级

**环境变量 > 配置文件 > 内置默认。**（配置在 `import` 时读进模块常量，
改页面后保存 API 会重启 worker 组，重新 import 才生效。）
"""
import os
from pathlib import Path
from typing import Any, Dict, List

from backend.services.eflow_assign.assign_config import (
    DEFAULT_ASSIGN_GROUP,
    DEFAULT_DRY_RUN,
    DEFAULT_GROUPS,
    DEFAULT_SITE_FUZZY_ENABLED,
    DEFAULT_SITE_FUZZY_THRESHOLD,
    csv_list,
    norm_code,
    parse_common_config,
    truthy,
)

# 默认告警码：5G 站点退服类（需求给定的 5 个）
DEFAULT_ALARM_CODES: List[str] = [
    "200201001",   # DU cell out-of-service
    "200201018",   # Super cell CP out-of-service
    "200201041",   # gNodeB DU out-of-service
    "200201043",   # NSA unavailable
    "200201060",   # Super MIMO cell CP out-of-service
]
# 告警码 → 告警名（仅用于页面提示与日志，不参与判定）
DEFAULT_ALARM_CODE_NAMES: Dict[str, str] = {
    "200201001": "DU cell out-of-service",
    "200201018": "Super cell CP out-of-service",
    "200201041": "gNodeB DU out-of-service",
    "200201043": "NSA unavailable",
    "200201060": "Super MIMO cell CP out-of-service",
}

# 关联告警码：站点已有小区退服（99933）时不重复派单
DEFAULT_CORRELATION_CODES: List[str] = ["99933"]
# 关联判定时间窗口（分钟）
DEFAULT_CORRELATION_WINDOW_MINUTES = 60
# 触发窗口（分钟）—— 上界：太老的告警不派
DEFAULT_WINDOW_MINUTES = 180
# 派单等待时长（分钟）—— **下界**：存续满 N 分钟才派（业务口径 15 分钟）
DEFAULT_MIN_AGE_MINUTES = 15

# 同一次故障的合并派单时间窗（分钟）：一个 gNB 的多个小区同时退服时合并成一个 TT。
# 实测同一站点多个 cell（50/51/52）会各自产生一条告警，不合并就是一堆重复单。
DEFAULT_GROUP_WINDOW_MINUTES = 10

# 服务端过滤用的 restype 候选（⚠ 只能穷举具体值，通配不被支持 —— 见模块 docstring）。
# 覆盖 gNodeB / nodeB / DU / CP / BBU 等 RAN 形态，宁可多配（多配不报错，只是多几条组合）。
DEFAULT_RESTYPES: List[str] = [
    "zte.ran.gnodeb",     # 实测 200201001 属于这个
    "zte.ran.nodeb",      # 实测 99933（关联码）属于这个
    "zte.ran.itbbu",
    "zte.ran.bbu",
    "zte.ran.du",
    "zte.ran.cp",
    "zte.ran.gbb",
    "zte.ran.mi",
    "zte.ran.nr9150",
    "zte.ran.nr9000",
    "zte.trm_mw.nr9150",
    "zte.trm_mw.nr9000",
]

# 全量兜底扫描：按码过滤一个目标码都没命中时，再拉全量比对。
# 彻底消除「restype 配漏 → 某码永远静默不触发」。代价是极端情况下多花 4.4s。
DEFAULT_FALLBACK_FULL_SCAN = True

# 一站多小区去重：同一站点、同一时间窗内的多个小区告警合并成一个 TT
DEFAULT_CELL_DEDUPE = True

CONFIG_FILE = (
    Path(__file__).resolve().parent.parent / "eflow_5g_config.json"
)

# 环境变量名（与 backend/.env.example 的键名一致）
ENV_ALARM_CODES = "EFLOW_5G_ASSIGN_ALARM_CODES"
ENV_CORRELATION_CODES = "EFLOW_5G_ASSIGN_CORRELATION_CODES"
ENV_CORRELATION_WINDOW = "EFLOW_5G_ASSIGN_CORRELATION_WINDOW_MINUTES"
ENV_WINDOW = "EFLOW_5G_ASSIGN_WINDOW_MINUTES"
ENV_MIN_AGE = "EFLOW_5G_ASSIGN_MIN_AGE_MINUTES"
ENV_GROUP = "EFLOW_5G_ASSIGN_GROUP"
ENV_DRY_RUN = "EFLOW_5G_ASSIGN_DRY_RUN"
ENV_GROUPS = "EFLOW_5G_ASSIGN_WHATSAPP_GROUPS"
ENV_SITE_FUZZY_ENABLED = "EFLOW_5G_ASSIGN_SITE_FUZZY_ENABLED"
ENV_SITE_FUZZY_THRESHOLD = "EFLOW_5G_ASSIGN_SITE_FUZZY_THRESHOLD"
ENV_GROUP_WINDOW = "EFLOW_5G_ASSIGN_GROUP_WINDOW_MINUTES"
ENV_RESTYPES = "EFLOW_5G_ASSIGN_RESTYPES"
ENV_FALLBACK_FULL_SCAN = "EFLOW_5G_ASSIGN_FALLBACK_FULL_SCAN"
ENV_CELL_DEDUPE = "EFLOW_5G_ASSIGN_CELL_DEDUPE"


def parse_config(conf: Dict[str, Any], env: Dict[str, str]) -> Dict[str, Any]:
    """把配置文件 dict + 环境变量解析成最终生效值（纯函数，不改全局）。

    在共用底座之上叠加 5G 自己的字段：`restypes` / `fallback_full_scan` /
    `cell_dedupe`。
    """
    out = parse_common_config(
        conf, env,
        default_alarm_codes=DEFAULT_ALARM_CODES,
        default_correlation_codes=DEFAULT_CORRELATION_CODES,
        env_alarm_codes=ENV_ALARM_CODES,
        env_correlation_codes=ENV_CORRELATION_CODES,
        env_correlation_window=ENV_CORRELATION_WINDOW,
        env_window=ENV_WINDOW,
        env_min_age=ENV_MIN_AGE,
        env_group=ENV_GROUP,
        env_dry_run=ENV_DRY_RUN,
        env_groups=ENV_GROUPS,
        env_site_fuzzy_enabled=ENV_SITE_FUZZY_ENABLED,
        env_site_fuzzy_threshold=ENV_SITE_FUZZY_THRESHOLD,
        env_group_window=ENV_GROUP_WINDOW,
        default_window_minutes=DEFAULT_WINDOW_MINUTES,
        default_min_age_minutes=DEFAULT_MIN_AGE_MINUTES,
        default_correlation_window_minutes=DEFAULT_CORRELATION_WINDOW_MINUTES,
        default_group_window_minutes=DEFAULT_GROUP_WINDOW_MINUTES,
    )

    # restype 候选（服务端过滤用）
    env_rt = env.get(ENV_RESTYPES)
    if env_rt not in (None, ""):
        restypes, rt_from = csv_list(env_rt), "env"
    elif conf.get("restypes"):
        restypes, rt_from = csv_list(conf.get("restypes")), "file"
    else:
        restypes, rt_from = list(DEFAULT_RESTYPES), "default"
    out["restypes"] = restypes or list(DEFAULT_RESTYPES)
    out["restypes_from"] = rt_from

    # 全量兜底扫描开关
    env_fb = env.get(ENV_FALLBACK_FULL_SCAN)
    if env_fb not in (None, ""):
        out["fallback_full_scan"] = truthy(env_fb, DEFAULT_FALLBACK_FULL_SCAN)
        out["fallback_full_scan_from"] = "env"
    elif "fallback_full_scan" in conf:
        out["fallback_full_scan"] = truthy(conf.get("fallback_full_scan"),
                                           DEFAULT_FALLBACK_FULL_SCAN)
        out["fallback_full_scan_from"] = "file"
    else:
        out["fallback_full_scan"] = DEFAULT_FALLBACK_FULL_SCAN
        out["fallback_full_scan_from"] = "default"

    # 一站多小区去重开关
    env_cd = env.get(ENV_CELL_DEDUPE)
    if env_cd not in (None, ""):
        out["cell_dedupe"] = truthy(env_cd, DEFAULT_CELL_DEDUPE)
        out["cell_dedupe_from"] = "env"
    elif "cell_dedupe" in conf:
        out["cell_dedupe"] = truthy(conf.get("cell_dedupe"), DEFAULT_CELL_DEDUPE)
        out["cell_dedupe_from"] = "file"
    else:
        out["cell_dedupe"] = DEFAULT_CELL_DEDUPE
        out["cell_dedupe_from"] = "default"

    return out


def load_config(env=None) -> Dict[str, Any]:
    """读配置文件 + 环境变量 → 生效配置。文件缺失/损坏时回退默认。"""
    from backend.services.task_config_files import load_json_config
    conf = load_json_config(CONFIG_FILE)
    if not isinstance(conf, dict):
        conf = {}
    return parse_config(conf, os.environ if env is None else env)

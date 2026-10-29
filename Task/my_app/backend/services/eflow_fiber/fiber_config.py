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

## 与共用底座的关系（2026-10-28）

共用解析逻辑已抽到 `backend/services/eflow_assign/assign_config.py`
（与 5G 站点告警派单共用，避免两份真相源）。本模块只保留 Fiber 自己的
默认值与环境变量名 —— 解析本体走 `parse_common_config`。
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

# 同一次光纤中断的「合并派单」时间窗（分钟，2026-10-27 需求）。
# 动机：一条光缆断掉会让链路上**多个站点同时告警**（实测 2026-10-27 14:21
# 一次故障派出 5 个 TT：R.I.A×3 + Tower Hill + HQ_Site，集中在 9 秒内），
# 现场反馈是同一个故障，却建了 5 个重复单。
# 规则：升起时间落在此窗口内的多条 fiber 告警合并为**一个** TT，
# 通报正文列出实际涵盖的站点与告警条数。
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
DEFAULT_SITE_FUZZY_ENABLED = DEFAULT_SITE_FUZZY_ENABLED
# 相似度阈值（0.5~1.0，越接近 1 越严格）。0.9 能容忍 1~2 个字母的拼写差异，
# 又不会把不同站点判成同一个 —— 调低会显著提高错派风险，谨慎。
DEFAULT_SITE_FUZZY_THRESHOLD = DEFAULT_SITE_FUZZY_THRESHOLD

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


def parse_config(conf: Dict[str, Any], env: Dict[str, str]) -> Dict[str, Any]:
    """把配置文件 dict + 环境变量解析成最终生效值（纯函数，不改全局）。

    解析本体走共用底座 `parse_common_config`（与 5G 派单同一份实现）。
    """
    return parse_common_config(
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


def load_config(env=None) -> Dict[str, Any]:
    """读配置文件 + 环境变量 → 生效配置。文件缺失/损坏时回退默认。"""
    from backend.services.task_config_files import load_json_config
    conf = load_json_config(CONFIG_FILE)
    if not isinstance(conf, dict):
        conf = {}
    return parse_config(conf, os.environ if env is None else env)

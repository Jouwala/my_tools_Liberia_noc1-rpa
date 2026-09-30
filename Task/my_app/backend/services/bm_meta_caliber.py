# -*- coding: utf-8 -*-
"""Meta 基准报告口径（ORANGE vs MTN 速率 PK + FDD 网络侧 KPI）—— **唯一真相源**。

数据源：`meta_data`（由 Meta_20260923.xlsx 的 `_Download speed vs competitors` 表导入）。
改口径只改本模块；`bm_meta_service.py` 只负责把这里的表达式拼成查询。

## 表结构实测（2026-09-30 导入的那一版，612 行）

| 列 | 说明 |
| --- | --- |
| `time` | 统计日，**时间部分恒为 00:00:00**（实测 612 行全部如此），按 `::date` 处理 |
| `orange_liberia` | Orange Liberia 速率指标（**越大越好**） |
| `mtn_liberia` | MTN Liberia 速率指标（**越大越好**） |
| `bp` | 比率，实测 0.0131 ~ 0.1650（**越小越好**） |
| `fdd_dl_ip_throughput_mbps_sdr_itbbu` | FDD 下行 IP 吞吐，Mbps（**越大越好**） |
| `fdd_dl_prb_utilization_rate_sdr_itbbu` | FDD 下行 PRB 利用率，比率（**越小越好**） |
| `fdd_ul_prb_utilization_rate_sdr_itbbu` | FDD 上行 PRB 利用率，比率（**越小越好**） |
| `fdd_traffic_volume_gb` | FDD 流量，GB（**越大越好**） |
| `rrc连接建立最大用户数` | RRC 连接建立最大用户数（**越大越好**） |
| `_source_file` / `_source_sheet` / `_import_time` | 导入溯源，实测各只有 1 个取值 |

## 为什么分「两家 PK」与「网络侧 KPI」两组

本表 9 个指标列里，**只有 `orange_liberia` / `mtn_liberia` 是两家运营商的对比值**；
其余 7 列（`bp`、FDD 吞吐、DL/UL PRB、流量、RRC 用户数）是**网络侧 KPI，不属于任何一家**。

因此**不能**把 9 个指标混进同一个「综合竞争力评分」里 —— 那会把「Orange 比 MTN 快多少」
和「全网 PRB 利用率多高」算成同一件事的两个选手，结论是假的。
分组如下（用户 2026-09-30 确认）：

- `BRAND_METRICS`：两家 PK 的指标，进综合评分与胜负统计；
- `NETWORK_METRICS`：网络侧 KPI，只做趋势与汇总，**不参与 PK、不打分**。

## 比率的表达

`bp` 与两个 PRB 利用率在库里是**小数比率**（0.1956 表示 19.56%），已在实测中确认
612 行**无一超过 1**（若超过 1 就说明是百分数，本模块的 ×100 会错，届时需改
`RATIO_METRICS` 的处理方式）。展示层统一 ×100 后带 `%`。

## 空值与「无数据」的表达

- 本表实测 9 个指标列**全部无空值**（612 行），但取子区间仍可能为空；
- 某区间内无数据 → 返回 `None`（前端渲染 `—`），**不是 0**；
- 两家速率相同时 `winner_of` 返回 `None`（实测有 1 天相等），
  该日**不计入胜负统计**，避免把「打平」当成某一方输。
"""
from __future__ import annotations

# 数据表（表名只此一处，改名时改这里即可）
TABLE = "meta_data"
# 时间列（与 speedtest_data 的 aggregate_date 不同名，故显式声明）
TIME_COL = "time"

# 两家运营商（顺序即前端固定顺序：先 ORANGE 后 MTN）
BRANDS = ("ORANGE", "MTN")
BRAND_LABELS = {"ORANGE": "Orange", "MTN": "MTN"}

# 两家 PK 的指标：{key: 列名}
#   kind → 'higher' 越大越好 / 'lower' 越小越好（决定胜负与评分方向）
#   unit → 展示单位（与 NETWORK_METRICS 同构；源表头只写 "Download speed"，
#          未给单位，按同表 `fdd_dl_ip_throughput_mbps` 的量级与列名判断为 Mbps）
BRAND_METRICS: dict[str, dict] = {
    "speed": {"col": "orange_liberia", "mtn_col": "mtn_liberia",
              "kind": "higher", "unit": "Mbps"},
}

# 网络侧 KPI（不属于任何一家，只展示不 PK）：
#   key      → 前端 i18n 键后缀与明细列名
#   col      → 列名（中文列名照抄数据库，不做翻译，见下方 NOTE）
#   unit     → 'ratio' 表示库中是小数比率、展示时 ×100 带 %；其余为字面单位
#   kind     → 'higher' 越大越好 / 'lower' 越小越好（仅用于趋势着色，不参与 PK）
#
# NOTE（中文列名）：`rrc连接建立最大用户数` 是数据库里真实的中文列名，PostgreSQL 允许
# 非 ASCII 标识符。这里**原样保留**，不改成拼音/英文 —— 它与 `_source_file` 里那份
# Excel 表头一一对应，改名会让"这一列到底对应哪个表头"失去可追溯性。
NETWORK_METRICS: dict[str, dict] = {
    "bp": {"col": "bp", "unit": "ratio", "kind": "lower"},
    "dl_throughput": {"col": "fdd_dl_ip_throughput_mbps_sdr_itbbu", "unit": "Mbps", "kind": "higher"},
    "dl_prb": {"col": "fdd_dl_prb_utilization_rate_sdr_itbbu", "unit": "ratio", "kind": "lower"},
    "ul_prb": {"col": "fdd_ul_prb_utilization_rate_sdr_itbbu", "unit": "ratio", "kind": "lower"},
    "traffic": {"col": "fdd_traffic_volume_gb", "unit": "GB", "kind": "higher"},
    "rrc_users": {"col": "rrc连接建立最大用户数", "unit": "count", "kind": "higher"},
}

# 明细下钻的列（前端表格列顺序）
DETAIL_COLS = ("speed", "bp", "dl_throughput", "dl_prb", "ul_prb", "traffic", "rrc_users")

# 综合评分权重（只覆盖 BRAND_METRICS；当前仅 speed 一项，故为 1.0）
# 说明：本表的 PK 维度只有「速率」一个，暂无可加权项。保留权重结构是为了与
# bm_speedtest 的评分实现同构，将来若 Excel 增加第二组对比列，加进 BRAND_METRICS
# 并在此补权重即可，评分函数无需改动。
SCORE_WEIGHTS = {"speed": 1.0}

# 明细默认取样上限：显著大于单页最大展示量，避免静默截断（AGENTS.md 第三节 1b）
MAX_DETAIL_ROWS = 3000


def all_metrics() -> dict[str, dict]:
    """两家 PK 指标 + 网络侧 KPI 的合并视图（供明细列与 i18n 键使用）。"""
    out = {}
    for k, v in BRAND_METRICS.items():
        out[k] = {**v, "group": "brand"}
    for k, v in NETWORK_METRICS.items():
        out[k] = {**v, "group": "network"}
    return out


def metric_meta(key: str) -> dict:
    """取一个指标的元信息；未知 key 抛错（不静默返回空，避免前端拿到空列）。"""
    m = all_metrics().get(key)
    if m is None:
        raise KeyError(f"未知指标: {key}")
    return m


def default_window(days: int = 365) -> tuple[str, str]:
    """默认时间窗（半开区间 [start, end)）。

    取 365 天而不是 90 天：本表跨度 2025-01-18 ~ 2026-09-23（612 天），
    速率类指标的季节性/长期趋势需要更长的窗才看得出，90 天会把
    「Orange 长期领先但近期收窄」这类结论切掉。
    """
    from datetime import date, timedelta

    end = date.today() + timedelta(days=1)
    return (end - timedelta(days=days)).isoformat(), end.isoformat()


def winner_of(orange: float | None, mtn: float | None) -> str | None:
    """两家 PK 的胜者。相等或任一为空 → None（不计入胜负）。"""
    if orange is None or mtn is None:
        return None
    if orange > mtn:
        return "ORANGE"
    if mtn > orange:
        return "MTN"
    return None


def score_brands(pairs: dict[str, dict[str, float | None]]) -> dict[str, dict]:
    """按 SCORE_WEIGHTS 算综合得分，**强者恒为 100**（相对分，不是绝对分）。

    `pairs` 形如 {"speed": {"ORANGE": 12.3, "MTN": 13.4}}。
    某一方缺数据的指标会被跳过，剩余权重重新归一 —— 否则缺数据会被算成 0 分。
    """
    total_w = 0.0
    acc = {b: 0.0 for b in BRANDS}
    for key, w in SCORE_WEIGHTS.items():
        vals = pairs.get(key) or {}
        o, m = vals.get("ORANGE"), vals.get("MTN")
        if o is None or m is None:
            continue
        best, worst = max(o, m), min(o, m)
        if best == worst:
            acc["ORANGE"] += 50.0 * w
            acc["MTN"] += 50.0 * w
        else:
            for b, v in (("ORANGE", o), ("MTN", m)):
                acc[b] += (100.0 if v == best else (worst / best) * 100.0) * w
        total_w += w
    if total_w == 0:
        return {b: {"score": None, "parts": {}} for b in BRANDS}
    out = {}
    for b in BRANDS:
        out[b] = {"score": round(acc[b] / total_w, 1), "parts": {}}
    # parts 单独算，便于前端逐指标展示
    for key, w in SCORE_WEIGHTS.items():
        vals = pairs.get(key) or {}
        o, m = vals.get("ORANGE"), vals.get("MTN")
        if o is None or m is None:
            continue
        best, worst = max(o, m), min(o, m)
        if best == worst:
            out["ORANGE"]["parts"][key] = 50.0
            out["MTN"]["parts"][key] = 50.0
        else:
            out["ORANGE"]["parts"][key] = round(100.0 if o == best else (worst / best) * 100.0, 1)
            out["MTN"]["parts"][key] = round(100.0 if m == best else (worst / best) * 100.0, 1)
    return out

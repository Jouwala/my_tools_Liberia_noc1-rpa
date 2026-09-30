# -*- coding: utf-8 -*-
"""Speedtest 竞对分析口径（ORANGE vs MTN）—— **唯一真相源**。

数据源：`speedtest_data`（由 Speedtest.xlsx 导入，见 `_source_file` / `_import_time`）。
改口径只改本模块；`bm_speedtest_service.py` 只负责把这里的表达式拼成查询。

## 表结构实测（2026-09-30 导入的那一版，854 行）

| 列 | 说明 |
| --- | --- |
| `provider` | 运营商原始名。实测只有 `Orange` 与 `Lonestar Cell MTN` 两个取值 |
| `location` | 实测**恒为 `Liberia`**（全国汇总，无城市维度） |
| `device` | 实测为 `all` 或空串两种写法，**表达的是同一件事**，不可当维度 |
| `aggregate_date` | 统计日，**时间部分恒为 00:00:00**，按 `::date` 处理 |
| `technology_type` | 实测**恒为 `cellular`** |
| `metric_type` | 实测**恒为 `median`**（聚合方式，不是可筛维度） |
| `test_count` / `sample_count` / `device_count` | 测试数 / 样本数 / 设备数 |
| `minimum_latency` / `multi_server_latency` / `multi_server_jitter` | 时延(ms) / 多服务器时延(ms) / 抖动(ms) |
| `download_speed` / `upload_speed` | 原始单位（kbps 量级整数） |
| `download_speed_mbps` / `upload_speed_mbps` | **页面一律用这两个**（已是 Mbps，勿再换算） |

**因此本页不提供 location / device / technology_type / metric_type 四个筛选器** ——
它们各只有一个有效取值，做成下拉框只会让用户以为「筛选没生效」。
`device` 的两种写法（`all` 与空串）在数据里成对出现，差集为 0，属上游导出写法差异，
已在口径层显式合并，**不是**缺失数据。

## 品牌归一

`provider` 原始值大小写与写法不完全可控，故用**参数化 LIKE**匹配后归一为两个品牌键：

- `ORANGE` ← provider 含 `orange`
- `MTN`    ← provider 含 `mtn` 或 `lonestar`（Lonestar Cell MTN 是 MTN 在利比里亚的品牌名）

⚠️ **展示名（`BRAND_LABELS`）与匹配 pattern（`MTN_PATTERNS`）是两件事，改一个别动另一个。**
页面上 MTN 一律显示简称 `MTN`（用户 2026-09-30 要求），但匹配 pattern **必须保留 `%lonestar%`**
——数据库里的原始值就是全称 `Lonestar Cell MTN`。若照着展示名把 pattern 也改成 `%mtn%` 一个，
MTN 的 420 行会全部落进 `OTHER`，页面直接变成只有一家有数据。

⚠️ **pattern 必须作为绑定参数传入，不能写成 SQL 字面量 `'%orange%'`。**
本项目 `backend/database.py:215` 的 `_qmark_to_pyformat` 在**带参数**路径下会跳过字符串
字面量里的 `%`（它只转义字面量外的 `%`），于是字面量 `'%orange%'` 会被 psycopg2 当成
格式化符，报 `IndexError: list index out of range`。实测踩过这个坑。

## 下钻一致性（AGENTS.md 第三节 1b 的铁律）

概览、趋势、逐日胜负、下钻明细**共用** `base_sql()` 与同一份 `where` 片段：
- 时间字段一律 `aggregate_date >= :start AND aggregate_date < :end`（**左闭右开**，`end` 为次日）；
- 品牌过滤一律 `brand_expr()` 归一后再比 `=`，**不用 LIKE 做下钻、用 `=` 做概览**那类不一致写法。

## 空值与「无数据」的表达

- 某品牌区间内无数据 → 该品牌各指标返回 `None`（前端渲染 `—`），**不是 0**；
- 某日只有一家有数据 → 逐日对比里另一家为 `None`，该日**不计入胜负统计**
  （`unpaired_days` 单独计数并暴露给前端，避免把「没测」当成「输了」）。
"""
from __future__ import annotations

# 数据表（表名只此一处，改名时改这里即可）
TABLE = "speedtest_data"

# 品牌键与展示名（顺序即前端固定顺序：先 ORANGE 后 MTN）
# 展示名一律用简称 MTN：Lonestar Cell MTN 是它在利比里亚的注册全称，
# 页面上过长的名字会把表格列宽和图表图例挤变形，用户要求直接显示 MTN。
BRANDS = ("ORANGE", "MTN")
BRAND_LABELS = {"ORANGE": "Orange", "MTN": "MTN"}

# provider → 品牌 的匹配 pattern（**作为绑定参数传入**，见模块 docstring 的警告）
ORANGE_PATTERNS = ("%orange%",)
MTN_PATTERNS = ("%mtn%", "%lonestar%")

# 可下钻的指标（前端每张卡/每个点都对应这里的一个键）
#   key      → 前端 i18n 键后缀与明细列名
#   kind     → 'speed' 越大越好 / 'latency' 越小越好
METRICS: dict[str, dict] = {
    "download": {"col": "download_speed_mbps", "kind": "speed", "unit": "Mbps"},
    "upload": {"col": "upload_speed_mbps", "kind": "speed", "unit": "Mbps"},
    "latency": {"col": "multi_server_latency", "kind": "latency", "unit": "ms"},
    "jitter": {"col": "multi_server_jitter", "kind": "latency", "unit": "ms"},
}
SPEED_METRICS = ("download", "upload")
LATENCY_METRICS = ("latency", "jitter")

# 明细返回上限：显著大于单页最大展示量，截断时由 meta.truncated 显式暴露
MAX_DETAIL_ROWS = 3000

# 综合评分权重（四项指标等权，各自先归一再加权）。
# 口径说明写在页面上，避免用户把评分当成官方结论。
SCORE_WEIGHTS = {"download": 0.35, "upload": 0.20, "latency": 0.30, "jitter": 0.15}


def brand_patterns() -> list[str]:
    """按 (ORANGE 的 pattern..., MTN 的 pattern...) 顺序展开，供 SQL 绑定使用。"""
    return [*ORANGE_PATTERNS, *MTN_PATTERNS]


def brand_case_sql() -> str:
    """provider 归一为品牌键的 CASE 表达式。

    占位符顺序与 `brand_patterns()` 严格一致，调用方拼 SQL 时**先绑 `brand_patterns()`**，
    再绑区间参数 —— 顺序错了会把 pattern 当日期用，且不会报语法错（只会得到空结果）。
    """
    orange = len(ORANGE_PATTERNS)
    mtn = len(MTN_PATTERNS)
    orange_cond = " OR ".join(["LOWER(provider) LIKE ?"] * orange)
    mtn_cond = " OR ".join(["LOWER(provider) LIKE ?"] * mtn)
    return f"""CASE
        WHEN {orange_cond} THEN 'ORANGE'
        WHEN {mtn_cond} THEN 'MTN'
        ELSE 'OTHER' END"""


def base_sql() -> str:
    """统一的取数子查询：一行 = 一天 × 一个品牌。

    列名刻意用业务名（`dl` / `ul` / `lat` / `jit`），与 `METRICS` 的 key 对应，
    避免下游再写一遍列名映射。`OTHER`（既非 Orange 也非 MTN）默认被外层过滤掉。

    同时投影出描述列（`provider` / `location` / `device` / 技术制式 / 聚合方式 /
    来源文件 / 导入时间），供下钻明细直接取用 —— 下钻必须能回答
    「这行数据哪来的」，所以来源列不能丢。

    ⚠️ 时间列只有 `day`（`aggregate_date::date`）。
    **外层 WHERE 一律过滤 `day`，不要写 `aggregate_date`**（子查询里已无此列名）。
    """
    return f"""SELECT
        {brand_case_sql()} AS brand,
        aggregate_date::date AS day,
        download_speed_mbps AS dl,
        upload_speed_mbps   AS ul,
        multi_server_latency AS lat,
        multi_server_jitter  AS jit,
        test_count   AS tests,
        sample_count AS samples,
        device_count AS devices,
        provider,
        location,
        COALESCE(NULLIF(device, ''), 'all') AS device,
        technology_type,
        metric_type,
        _source_file,
        _import_time
    FROM {TABLE}"""


def metric_col(metric: str) -> str:
    """指标键 → base_sql() 里的列名。未知键回落 download（调用方应先校验）。"""
    return {"download": "dl", "upload": "ul", "latency": "lat", "jitter": "jit"}.get(metric, "dl")


def default_window(days: int = 90) -> tuple[str, str]:
    """默认统计窗口：最近 N 天（左闭右开，返回 (start, end_exclusive)）。

    默认 90 天：数据跨度约 14 个月，90 天既能看出近期趋势，
    又不至于把 435 个日点全画进一张图里。
    """
    from datetime import date, timedelta

    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


def score_brands(summary: dict) -> dict:
    """按 SCORE_WEIGHTS 给两品牌算综合竞争力评分（0~100，双方相对得分）。

    归一方式：每个指标取两家的较大/较小值作为基准（速率取大、时延取小），
    强者得 100 分，弱者按比例得分。**这是两家的相对分，不是绝对分**：
    只回答「这两家谁更强、强多少」，不回答「绝对水平好不好」。
    某指标任一方缺数据时，该指标不参与评分，权重在剩余指标间重新归一。
    """
    rows = {b: summary.get(b) or {} for b in BRANDS}
    out: dict[str, dict] = {b: {"score": None, "parts": {}} for b in BRANDS}
    total_weight = 0.0
    acc = {b: 0.0 for b in BRANDS}

    for metric, weight in SCORE_WEIGHTS.items():
        vals = {}
        for b in BRANDS:
            v = rows[b].get(metric)
            vals[b] = v if isinstance(v, (int, float)) else None
        if any(v is None for v in vals.values()):
            continue  # 该指标有一方没数据 → 不参与，权重留给其他指标
        if METRICS[metric]["kind"] == "speed":
            best = max(vals.values())
            if best <= 0:
                continue
            ratio = {b: vals[b] / best for b in BRANDS}
        else:
            # 时延：越小越好。用 best/v 的反比；v 为 0 时保护（抖动为 0 是可能的）
            best = min(vals.values())
            ratio = {b: (best / vals[b] if vals[b] > 0 else 1.0) for b in BRANDS}
        for b in BRANDS:
            acc[b] += ratio[b] * weight
        total_weight += weight
        out_parts = {b: round(ratio[b] * 100, 1) for b in BRANDS}
        for b in BRANDS:
            out[b]["parts"][metric] = out_parts[b]

    if total_weight <= 0:
        return out
    for b in BRANDS:
        out[b]["score"] = round(acc[b] / total_weight * 100, 1)
    return out


def winner_of(a, b, kind: str) -> str | None:
    """比较两家数值，返回胜者品牌键；任一为空或完全相等时返回 None（平局/无数据）。

    平局返回 None 而不是随便挑一家：界面上「平」和「赢」是两件事。
    """
    if a is None or b is None:
        return None
    if a == b:
        return None
    if kind == "speed":
        return "ORANGE" if a > b else "MTN"
    return "ORANGE" if a < b else "MTN"

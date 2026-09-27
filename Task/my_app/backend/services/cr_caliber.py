# -*- coding: utf-8 -*-
"""CR 变更分析 —— 口径层：表名、时间字段、SQL 谓词与窗口规整。

**本模块是 CR 分析口径的唯一真相源。** 概览（`SUM(CASE ...)` 聚合）与下钻
（`WHERE` 谓词）都从这里取表达式，这是「卡片数字 == 明细行数」的根本保证
（AGENTS.md 第三节 1b 的铁律）。改口径只改这里。

从 `cr_analysis_service.py` 拆出（原文件 535 行，超出 AGENTS.md 第三节 2
的单文件 500 行上限）：口径是**最需要被单独审视**的部分，独立成文件后
可以直接读、直接比对，不必在取数逻辑里翻找。
"""
from __future__ import annotations

from datetime import datetime, timedelta

# 表名白名单：本模块只读这一张表（防注入的同时也表明数据边界）
TABLE = "eflow_cr"

# 时间字段（见本文件「时间字段」一节的说明）
TIME_COL = "request_registration_time"

# 终态词表，与 routers/portal_qc.py:102 的 _CR_OPEN 互补
CLOSED_STATUS = "Closed"
CANCELED_STATUS = "Canceled"

# 「类别」列可能为空的兜底显示名
UNCATEGORIZED = "(未分类)"

CATEGORY_COL = "change_category"

# 明细取样上限。必须显著大于单页最大数据量（前端 pageSize 最大 200），
# 否则会静默截断，让下钻行数少于卡片数字 —— 铁律见 AGENTS.md 第三节 1b。
MAX_DETAIL_ROWS = 5000

# 下钻明细返回的列（顺序即界面列顺序）。全部是本页分析用得到的字段，
# 不返回 post_analysis 这类超长文本（单行可达上千字符，进表格与导出都很难看）。
DETAIL_COLUMNS = (
    "change_request_id",
    "cr_title",
    "status",
    "change_category",
    "sub_category",
    "change_type",
    "request_registration_time",
    "planned_start_time",
    "planned_end_time",
    "actual_start_time",
    "actual_end_time",
    "closed_time",
    "implement_result",
    "creator",
    "current_handler",
    "implementer",
    "vender",
    "ne_node_name",
    "downtime_required",
    "operating_circle_sub_center",
)

# ---------------- SQL 谓词 ----------------

# 「进行中」= 既没关闭也没取消
OPEN_SQL = "UPPER(TRIM(COALESCE(status,''))) NOT IN ('CLOSED','CANCELED')"
CLOSED_SQL = "UPPER(TRIM(COALESCE(status,''))) = 'CLOSED'"
CANCELED_SQL = "UPPER(TRIM(COALESCE(status,''))) = 'CANCELED'"


def not_blank(col: str) -> str:
    """字段非空的判定。

    源表里空值既有 NULL 也有空串（导出链路两种都见过，与
    `routers/portal_qc.py:97` 的 `_ALARM_UNCLEARED` 是同一个教训），
    必须两种都判，只判一种会漏。
    """
    return f"({col} IS NOT NULL AND TRIM(CAST({col} AS TEXT)) <> '')"


def blank(col: str) -> str:
    """字段为空的判定（NULL 或空串）"""
    return f"({col} IS NULL OR TRIM(CAST({col} AS TEXT)) = '')"


PLANNED_SQL = not_blank("planned_start_time")
EXECUTED_SQL = not_blank("actual_start_time")
# 按时 = 实际开始 <= 计划开始。源表两者都是同格式文本，字典序即时间序。
ON_TIME_SQL = f"({EXECUTED_SQL} AND actual_start_time <= planned_start_time)"
DELAYED_SQL = f"({EXECUTED_SQL} AND actual_start_time > planned_start_time)"
# 未执行 = 排了期但没动
UNEXECUTED_SQL = f"({PLANNED_SQL} AND {blank('actual_start_time')})"

# metric 名 → 布尔表达式。**白名单**，未知 metric 返回 None。
# 这些表达式同时被 build_overview（SUM 聚合）与 build_drilldown（WHERE 谓词）
# 使用，是两端口径一致的唯一保证。
_BUCKETS = {
    "total": "1=1",
    "planned": PLANNED_SQL,
    "executed": EXECUTED_SQL,
    "unexecuted": UNEXECUTED_SQL,
    "on_time": ON_TIME_SQL,
    "delayed": DELAYED_SQL,
    "closed": CLOSED_SQL,
    "open": OPEN_SQL,
    "canceled": CANCELED_SQL,
}

# 可下钻的 metric 全集（与 _BUCKETS 的键一致）
DRILL_METRICS = tuple(_BUCKETS.keys())


def bucket_expr(metric: str):
    """把 metric 名映射成布尔计数表达式；未知 metric 返回 None"""
    return _BUCKETS.get(metric)


# ---------------- 时间窗口 ----------------


def default_window(days: int = 240) -> tuple[str, str]:
    """默认统计窗口。

    取 240 天（约 8 个月）而不是常见的 30 天：本表实测 247 行、登记时间从
    2026-01-02 到 2026-09-09，30 天窗口只有个位数 CR，页面会几乎是空的。

    ⚠️ `build_overview` / `build_drilldown` 在入参非法时会回落到这个**滚动**窗口，
    而 `/filters` 返回的 default_start 是**全表实际起点**（通常更早）。
    两者不一致是刻意的：filters 面向「首次进页面该看什么」，这里面向
    「调用方传了坏参数时的安全兜底」—— 后者不该为了一次坏请求去多查一次库。
    前端一定会先调 filters 拿到全表窗口，故正常流程不会走到这个兜底。
    """
    end = datetime.now()
    start = end - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def normalize_window(start: str, end: str) -> tuple[str, str]:
    """把日期（YYYY-MM-DD）规整成与 TIME_COL 可比的时间戳文本。

    非法输入直接回落到默认窗口，避免拼出坏 SQL。
    起止都按**闭区间**处理（start 00:00:00 ~ end 23:59:59）。
    """
    def _ok(v: str) -> bool:
        if not v or len(v) < 10:
            return False
        try:
            datetime.strptime(v[:10], "%Y-%m-%d")
            return True
        except ValueError:
            return False

    if not _ok(start) or not _ok(end):
        return default_window()
    # 规整后再比一次：end 早于 start 时同样回落，否则会查出空集而不报错
    if end[:10] < start[:10]:
        return default_window()
    return f"{start[:10]} 00:00:00", f"{end[:10]} 23:59:59"


def base_where(start_ts: str, end_ts: str, category: str = "") -> tuple[str, list]:
    """**唯一**的 WHERE 构造处 —— 概览与下钻都调它。

    返回 (sql_fragment, params)。fragment 不含前导 'WHERE'，便于调用方拼接。
    ⚠️ 一律用 `?` 占位符：`get_raw_connection` 的 PG 包装层会自动转 `%s`，
    写死 `%s` 在 SQLite 模式下会炸（见 routers/portal_qc.py 模块 docstring）。
    """
    where = [f"{TIME_COL} >= ?", f"{TIME_COL} <= ?"]
    params: list = [start_ts, end_ts]
    if category:
        # 精确匹配（=），不是 LIKE —— 下钻与概览必须同一写法
        where.append(f"TRIM(COALESCE({CATEGORY_COL},'')) = ?")
        params.append(category)
    return " AND ".join(where), params

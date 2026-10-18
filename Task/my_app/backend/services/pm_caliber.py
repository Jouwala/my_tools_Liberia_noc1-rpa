# -*- coding: utf-8 -*-
"""PM（预防性维护工单 PMT）分析 —— 口径层：表名、时间字段、SQL 谓词与窗口规整。

**本模块是 PM 分析口径的唯一真相源。** 概览（`SUM(CASE ...)` 聚合）与下钻
（`WHERE` 谓词）都从这里取表达式，这是「卡片数字 == 明细行数」的根本保证
（AGENTS.md 第三节 1b 的铁律）。改口径只改这里。

与 `cr_caliber.py` 同构 —— 两个页面共用一套「口径层 / 取数层」结构，
便于对照维护。

---
## 字段与流程（2026-09-25 实测，1632 行）

`eflow_pm` 是本表**动态建表**的产物：同时存在小写（`status`）与大写（`Status`）
两套列名，**只有小写列有数据**，大写列是历史遗留的空列（`eflow_cr` 同样如此，
见 `docs/manual/11-feature-guide.md` 第 27 节的记录）。一律只用小写列。

真实流程顺序（2026-10-17 以 `queryAllSteps` 流程图重新校准，见下）：

    created_time                     工单生成（Create）
      → last_create_time             创建动作
      → last_schedule_time           排期（Schedule）
      → last_accept_time             受理（Accept）
      → last_process_time            执行（Process）
      → last_pm_manager_approve_time PM 经理审批（PMManagerApprove）
      → last_flm_leader_approve_time FLM 领导审批（FLMLeaderApprove）
      → Closed

⚠️ 与旧记录的差异：「执行」在「PM 经理审批」**之前**。依据是 eFlow 的
Workflow History（`queryAllSteps`，payload `eflow-pm-task`）：
Create → Schedule → Accept → Process → PMManagerApprove → FLMLeaderApprove → Closed，
且 `Process` 对 Transfer / WaitReProcess 有自环（驳回回处理）。
字段侧也印证：`last_process_time` 是**进入** Process 的时刻，
2458 行中 95% 的单 `last_pm_manager_approve_time` 与 `last_process_time` 只差 1 秒，
其余相差数周 —— 二者是相邻两步，在导出上几乎同时落库。

⚠️ **字段名有误导性，不要按名字猜顺序**：`last_accept_time` 早于
`last_process_time`，`last_flm_leader_approve_time` 最晚。页面按上面的顺序展示。
"""
from __future__ import annotations

from datetime import datetime, timedelta

# 表名白名单：本模块只读这一张表
TABLE = "eflow_pm"

# 时间字段。用 `created_time`（工单生成时间）而不是任务窗口
# `current_task_start_time`：任务窗口会被改期，拿它做统计窗口会让同一工单
# 在窗口移动时反复进出统计口径。实测 created_time 100% 非空、长度全为 19，
# 字典序即时间序，PG / SQLite 双模可直接字符串比较。
TIME_COL = "created_time"

# 终态：实测 6 个状态里只有 Closed 是终态，其余 5 个都是「等待某一步」
CLOSED_STATUS = "Closed"

# 维度列
PMP_COL = "pmp_no"          # PM 计划号：一张计划下挂多个 PMT 工单（实测 27 个计划）
SITE_COL = "site_name"      # 站点
HANDLER_COL = "current_handler"
TEMPLATE_COL = "template"
OVERDUE_COL = "pmt_overdue"  # 'Yes' / 'No'

# 条目进度（文本存储，需 CAST 成整数）
COMPLETED_COL = "completed_items"
TOTAL_COL = "total_items"

# 明细取样上限。必须显著大于单页最大数据量（前端 pageSize 最大 200），
# 否则会静默截断，让下钻行数少于卡片数字（AGENTS.md 第三节 1b）。
MAX_DETAIL_ROWS = 5000

# 下钻明细返回的列（顺序即界面列顺序）
DETAIL_COLUMNS = (
    "pmt_no",
    "status",
    "title",
    "pmp_no",
    "pmt_overdue",
    "site_name",
    "asset_id",
    "template",
    "completed_items",
    "total_items",
    "current_task_start_time",
    "current_task_end_time",
    "created_time",
    "last_schedule_time",
    "last_accept_time",
    "last_pm_manager_approve_time",
    "last_process_time",
    "last_flm_leader_approve_time",
    "last_modified_time",
    "creator",
    "current_handler",
    "source",
)

# ---------------- SQL 谓词 ----------------


def not_blank(col: str) -> str:
    """字段非空判定：NULL 与空串都要判（导出链路两种都见过）"""
    return f"({col} IS NOT NULL AND TRIM(CAST({col} AS TEXT)) <> '')"


def blank(col: str) -> str:
    """字段为空判定（NULL 或空串）"""
    return f"({col} IS NULL OR TRIM(CAST({col} AS TEXT)) = '')"


# 已完成 = 走到终态 Closed
CLOSED_SQL = "UPPER(TRIM(COALESCE(status,''))) = 'CLOSED'"
# 未完成 = 尚未 Closed（含 Wait Accept / Wait Process / Wait FLM Leader Approve /
# Wait PM Manager Approve / Transfer）
OPEN_SQL = "UPPER(TRIM(COALESCE(status,''))) <> 'CLOSED'"

# 超期：直接用源表的 `pmt_overdue` 标记，**不自己算**。
# 语义已实测确认：表示「该工单未在任务窗口内完成」——
#   已完成但超期 229 条（晚于 current_task_end_time 才签收）
#   未完成且截止已过 855 条中标记 Yes 的 701 条
# 自己按日期比会与上游口径不一致（上游的任务窗口含时区与工作日历），
# 这里只做一次「标记归一」，见 overdue_expr()。
OVERDUE_SQL = "UPPER(TRIM(COALESCE(pmt_overdue,''))) = 'YES'"
NOT_OVERDUE_SQL = "UPPER(TRIM(COALESCE(pmt_overdue,''))) <> 'YES'"

# 条目进度：CAST 成整数做比较（源表是文本）。空值按 0 处理。
_COMPLETED_INT = f"CAST(NULLIF(TRIM(COALESCE({COMPLETED_COL},'')), '') AS INTEGER)"
# 「一件都没做」：完成条目为 0（或空）
NOT_STARTED_SQL = f"(COALESCE({_COMPLETED_INT}, 0) = 0)"

# 流程步骤：某一步是否走过（对应时间字段非空）
STEP_COLUMNS = {
    "created": "created_time",
    "scheduled": "last_schedule_time",
    "accepted": "last_accept_time",
    "pm_approved": "last_pm_manager_approve_time",
    "processed": "last_process_time",
    "flm_approved": "last_flm_leader_approve_time",
}

# metric 名 → 布尔表达式。**白名单**，未知 metric 返回 None。
# 同时被 build_overview（SUM 聚合）与 build_drilldown（WHERE 谓词）使用。
_BUCKETS = {
    "total": "1=1",
    "closed": CLOSED_SQL,
    "open": OPEN_SQL,
    "overdue": OVERDUE_SQL,
    "on_time": NOT_OVERDUE_SQL,
    "not_started": NOT_STARTED_SQL,
    # 「已完成且超期」= 事后补录 / 迟交；「未完成且超期」= 真正压着的
    "closed_overdue": f"({CLOSED_SQL} AND {OVERDUE_SQL})",
    "open_overdue": f"({OPEN_SQL} AND {OVERDUE_SQL})",
    "open_on_time": f"({OPEN_SQL} AND {NOT_OVERDUE_SQL})",
}

# 可下钻的 metric 全集（与 _BUCKETS 的键一致）
DRILL_METRICS = tuple(_BUCKETS.keys())


def bucket_expr(metric: str):
    """把 metric 名映射成布尔计数表达式；未知 metric 返回 None"""
    return _BUCKETS.get(metric)


def step_expr(step: str):
    """流程步骤 → 「该步骤已发生」的表达式；未知步骤返回 None"""
    col = STEP_COLUMNS.get(step)
    return not_blank(col) if col else None


# ---------------- 时间窗口 ----------------


def default_window(days: int = 300) -> tuple[str, str]:
    """默认统计窗口。

    取 300 天（约 10 个月）：实测 created_time 从 2026-01-02 到 2026-07-28，
    跨度约 7 个月。给足余量以免默认视图漏掉最早的一批工单。

    入参非法时 `normalize_window` 回落到这个**滚动**窗口，而 `/filters`
    返回的 default_start 是**全表实际起点**（通常更早）—— 两者不一致是刻意的：
    filters 面向「首次进页面该看什么」，这里面向「调用方传了坏参数时的安全兜底」。
    """
    end = datetime.now()
    start = end - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def normalize_window(start: str, end: str) -> tuple[str, str]:
    """把日期（YYYY-MM-DD）规整成与 TIME_COL 可比的时间戳文本。

    非法输入回落到默认窗口，避免拼出坏 SQL。起止按**闭区间**处理。
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
    if end[:10] < start[:10]:
        return default_window()
    return f"{start[:10]} 00:00:00", f"{end[:10]} 23:59:59"


def base_where(start_ts: str, end_ts: str, pmp_no: str = "") -> tuple[str, list]:
    """**唯一**的 WHERE 构造处 —— 概览与下钻都调它。

    返回 (sql_fragment, params)。fragment 不含前导 'WHERE'。
    ⚠️ 一律用 `?` 占位符：`get_raw_connection` 的 PG 包装层会自动转 `%s`，
    写死 `%s` 在 SQLite 模式下会炸。
    """
    where = [f"{TIME_COL} >= ?", f"{TIME_COL} <= ?"]
    params: list = [start_ts, end_ts]
    if pmp_no:
        # 精确匹配（=），不是 LIKE —— 下钻与概览必须同一写法
        where.append(f"TRIM(COALESCE({PMP_COL},'')) = ?")
        params.append(pmp_no)
    return " AND ".join(where), params

# -*- coding: utf-8 -*-
"""CR 审批流程 —— 各步骤的到达量与**停留耗时**。

## 为什么要这个模块

`eflow_cr.status` 只说明「现在卡在哪一步」，说不出「这一步已经卡了多久、
平均卡多久、谁那边最慢」。而源表把每一步的操作记录压进了 8 个 `*_detail`
文本列（eFlow 导出的 `Workflow History`，一格一步，格式固定）：

    Operation Step:CM Head Approval. Operation Result:Approve. Operation Time:2026-1-14 17:24:44.
    Operator:Alhaji Dukulay(NOC_FO_102). Operator Group:... . Next Status:Waiting for Implement.
    Assign To:... . Assignee Group:... . Remark:Approved

本模块把这 8 列解析成「一步一条时间线」，据此算：
  - 每一步的**到达量**（有几张 CR 走过这一步）；
  - 每一步的**平均停留耗时**（相邻两步 Operation Time 之差）；
  - 当前停在每一步上的 CR **已经等了多久**（从未关闭的 CR 的当前步骤）。
  - 审批驳回次数（Operation Result 含 Reject）。

## 口径

  - 步骤按 `cr_caliber.WORKFLOW_STEPS` 的**真实时序**排列，不按列名字母序
    （`domain_td_approval_detail` 在 `cm_head_approval_detail` 之前，字母序会颠倒）。
  - `Closed` 那一步的 detail 是空壳（无时间无操作人），只表示终态，
    不参与耗时计算 —— 关闭时间要看 `result_feedback_detail` 的 `Next Status:Closed`。
  - 时间解析失败的步骤**跳过并计入 warnings**，不抛异常：这是分析辅助数据，
    不能因为一行脏数据让整页 500。
  - 时长为负（源表时间倒挂）时按 0 计并计数告警，不静默吞掉。

本模块只读 `eflow_cr`，与 `cr_analysis_service` 共用 `cr_caliber` 的口径常量。
数据量实测 247 行，全表扫一次即可；下钻按状态/步骤过滤在**内存里**做，
因此 `status_rows` / `workflow` 与下钻必须用同一份解析结果（见 `rows_of`）。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from backend.database import get_raw_connection
from backend.services import cr_caliber as cal

logger = logging.getLogger(__name__)

# 各步骤的 detail 列 ↔ 显示名。顺序即真实时序（见 cr_caliber.WORKFLOW_STEPS）。
_STEP_COLUMN = {
    "created": "create_detail",
    "update": "update_detail",
    "bo_fo": "bo_fo_head_approval_detail",
    "td": "domain_td_approval_detail",
    "cm": "cm_head_approval_detail",
    "implement": "start_implementing_detail",
    "feedback": "result_feedback_detail",
}

# 状态名（大写）→ 当前所在步骤。**只列「在途」状态**，终态不在表里。
# ⚠️ 键是 `UPPER(TRIM(status))` 的结果 —— 源表里「Head Approval」是大写开头，
#    归一后会变成「HEAD APPROVAL」，键必须按大写写，否则查不到（2026-10-17 踩过）。
_STATUS_TO_STEP = {
    "BO/FO HEAD APPROVAL": "created",
    "DOMAIN TD APPROVAL": "bo_fo",
    "CM HEAD APPROVAL": "td",
    "WAITING FOR IMPLEMENT": "cm",
    "IMPLEMENTING": "implement",
    "WAITING FOR UPDATE": "created",
}

# 各步骤「谁在等」—— 下钻时用来解释当前卡在谁那里（来自 Next Status 的语义）
_FIELD_RE = {
    "time": re.compile(r"Operation Time:(.*?)\. Operator:"),
    "result": re.compile(r"Operation Result:(.*?)\. Operation Time:"),
    "next": re.compile(r"Next Status:(.*?)\. Assign To:"),
    "operator": re.compile(r"Operator:(.*?)\. Operator Group:"),
    "remark": re.compile(r"Remark:(.*)$"),
}


def _field(text: str, key: str) -> str:
    """从 detail 文本里取一个字段（取不到返回空串）"""
    m = _FIELD_RE[key].search(text + ". ")
    if not m:
        m = _FIELD_RE[key].search(text)
    return (m.group(1).strip() if m else "")


def _parse_time(text: str) -> datetime | None:
    """`2026-1-14 17:24:44` —— 月/日不补零，必须用 %-m/%-d 的等价写法。"""
    raw = _field(text, "time")
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _steps_of(row: dict) -> list[dict]:
    """一张 CR 的步骤时间线（按时序，只保留有时间戳的步骤）。"""
    out = []
    for key in _STEP_COLUMN:
        text = (row.get(_STEP_COLUMN[key]) or "").strip()
        if not text:
            continue
        ts = _parse_time(text)
        if ts is None:
            continue
        out.append({
            "step": key,
            "time": ts,
            "result": _field(text, "result"),
            "next_status": _field(text, "next"),
            "operator": _field(text, "operator"),
        })
    out.sort(key=lambda s: s["time"])
    return out


def step_of_status(status: str) -> str:
    """状态名 → **当前所在步骤**（空串 = 已终态或未知）。

    为什么不用时间线倒推：实测 2026-10-17 全表交叉表显示，Closed 的 CR
    最后一步多种多样（141 张停在 feedback、15 张停在 implement ——
    后者**根本没走 Result Feedback 就关单了**）。拿「最后一步」当当前步骤
    会把已关闭的单全算成「卡在 feedback」，耗时统计完全失真。

    `status` 是权威的「谁在等」信号。注意 `status` 说的是**等待中**的那个
    审批节点，而 detail 记录的是**已经完成**的操作，所以语义上要错开一格：

        BO/FO Head Approval     = 正在等 BO/FO 批 → 当前步骤 = created（已建单）
        Domain TD Approval      = 正在等 TD 批    → 当前步骤 = bo_fo
        CM Head Approval        = 正在等 CM 批    → 当前步骤 = td
        Waiting for Implement   = 审批全过，等实施 → 当前步骤 = cm
        Implementing            = 实施中          → 当前步骤 = implement
        Waiting for Update      = 被驳回等修改    → 当前步骤 = created（同建单语义）

    Closed / Canceled 不在表里 —— 它们没有「当前步骤」，也不计入滞留。
    """
    return _STATUS_TO_STEP.get(status.strip().upper(), "")


def _is_closed(status: str) -> bool:
    return status.strip().upper() in ("CLOSED", "CANCELED")


def load_rows(start: str, end: str) -> tuple[list[dict], list[str]]:
    """读取窗口内全部 CR 的**解析后**时间线。返回 (rows, warnings)。

    每行只保留分析所需字段，避免把 post_analysis 这类超长文本带进内存。
    """
    start_ts, end_ts = cal.normalize_window(start, end)
    where, params = cal.base_where(start_ts, end_ts)
    cols = ["change_request_id", "status", "change_category"] + list(_STEP_COLUMN.values())
    sql = f"SELECT {', '.join(cols)} FROM {cal.TABLE} WHERE {where}"

    warnings: list[str] = []
    try:
        conn = get_raw_connection()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[cr-workflow] 连接失败: %s", exc)
        return [], [f"数据库连接失败: {exc}"]

    raw: list[tuple] = []
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        raw = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[cr-workflow] 查询失败: %s", exc)
        return [], [f"数据查询失败: {exc}"]
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    rows = []
    for r in raw:
        row = dict(zip(cols, r))
        status = (row.get("status") or "").strip()
        rows.append({
            "change_request_id": row.get("change_request_id") or "",
            "status": status,
            # 与概览/下钻同一个 UPPER(TRIM())，保证三处匹配口径一致
            "status_key": status.upper(),
            "category": (row.get("change_category") or "").strip(),
            "steps": _steps_of(row),
        })

    if not raw:
        warnings.append("所选时间窗口内没有 CR 记录。")
    return rows, warnings


# ---------------- 聚合 ----------------


def build_workflow(start: str, end: str) -> dict:
    """步骤到达量 + 停留耗时 + 当前滞留量。

    返回结构（前端 `crTypes.ts` 的 `Workflow` 一一对应）：

        steps: [{ step, arrived, avg_days, max_days, current, current_max_days }]
        rejected: 被驳回过的 CR 数
        total: 窗口内 CR 总数
        warnings: [...]
    """
    rows, warnings = load_rows(start, end)
    start_ts, end_ts = cal.normalize_window(start, end)

    # 耗时桶：每个步骤的「该步时间 → 下一步时间」间隔，只统计**真正离开**该步的单
    durations: dict[str, list[float]] = {k: [] for k in _STEP_COLUMN}
    # 滞留桶：当前停在该步、还没走的单，记录「已经等了多久」
    current: dict[str, list[float]] = {k: [] for k in _STEP_COLUMN}
    rejected = 0
    negative = 0
    missing_status = 0

    now = datetime.now()
    for r in rows:
        steps = r["steps"]
        if any("reject" in (s["result"] or "").lower() for s in steps):
            rejected += 1

        closed = _is_closed(r["status"])
        cur_step = "" if closed else step_of_status(r["status"])
        if not closed and not cur_step:
            # 状态是表里没见过的值（上游新增状态）—— 计入告警，不静默丢
            missing_status += 1

        for i, s in enumerate(steps):
            step = s["step"]
            if i + 1 < len(steps):
                delta = (steps[i + 1]["time"] - s["time"]).total_seconds() / 86400.0
                if delta < 0:
                    negative += 1
                    delta = 0.0
                durations[step].append(delta)

        # 在途单：以**该单当前步骤那条记录的进入时间**为起点算已等待时长
        if cur_step:
            entered = next((s["time"] for s in reversed(steps) if s["step"] == cur_step), None)
            if entered is None:
                # 步骤按状态推断，但记录缺失（历史导出不全）—— 用最早一步兜底
                entered = steps[0]["time"] if steps else None
            if entered is not None:
                current[cur_step].append(max(0.0, (now - entered).total_seconds() / 86400.0))

    def _round(v: float) -> float:
        return round(v, 2)

    # 到达数 = 走过该步的 **CR 数**（不是停留次数）。
    # ⚠️ 不能写成 len(durations)+len(current)：同一张 CR 可能在同一列留下多条
    #    记录（驳回后重走），那样停留次数 > CR 数，下钻（按 CR 去重）行数会比
    #    卡片少 —— 2026-10-17 实测 created 卡片 248 / 下钻 247 就是这么来的。
    arrived_sets: dict[str, set[str]] = {k: set() for k in _STEP_COLUMN}
    for r in rows:
        for s in r["steps"]:
            arrived_sets[s["step"]].add(r["change_request_id"])

    step_rows = []
    for key in _STEP_COLUMN:
        ds = durations[key]
        cs = current[key]
        step_rows.append({
            "step": key,
            "arrived": len(arrived_sets[key]),
            "avg_days": _round(sum(ds) / len(ds)) if ds else None,
            "max_days": _round(max(ds)) if ds else None,
            "current": len(cs),
            "current_max_days": _round(max(cs)) if cs else None,
        })

    if negative:
        warnings.append(f"有 {negative} 处步骤时间倒挂（下一步早于上一步），耗时已按 0 计。")
    if missing_status:
        warnings.append(f"有 {missing_status} 张在途 CR 的状态不在已知流程内，未计入滞留统计。")

    in_flight = sum(1 for r in rows if not _is_closed(r["status"]))
    return {
        "meta": {"start": start_ts, "end": end_ts,
                 "table": cal.TABLE, "warnings": warnings},
        "steps": step_rows,
        # 里程碑条（按 queryAllSteps 的 Workflow History 顺序，见 cr_caliber.MILESTONES）
        "milestones": _milestones(rows, now),
        "rejected": rejected,
        "total": len(rows),
        "in_flight": in_flight,
    }


def _milestones(rows: list[dict], now: datetime) -> list[dict]:
    """页面顶部 Workflow 里程碑条的数据。

    每个里程碑给出三样东西，与前端「字号极大的进度条」一一对应：

      - `done`        已完成该里程碑的 CR 数（终态单全部算已成）
      - `waiting`     当前停在该里程碑、等待下一环节的 CR 数
      - `waiting_max_days`  这些滞留单里等得最久的天数

    ⚠️ 与状态卡的关系：状态卡按 `status` 逐值分组（7 个技术状态全列），
    里程碑按**流程节点**分组，`update` 并入 `bo_fo`、Closed 单列。
    两者是同一份数据的两种切法，数字可互相印证：
    `sum(waiting) + done(closed) == total`（`total` 时）。
    """
    out = []
    for m in cal.MILESTONES:
        key, step = m["key"], m["step"]
        waiting_statuses = set(m["waiting_statuses"])

        done = 0
        waits: list[float] = []
        for r in rows:
            closed = _is_closed(r["status"])
            # 已完成该里程碑：走过对应步骤（终态单一律算走完，避免记录缺失误判）
            if closed or any(s["step"] == step for s in r["steps"]):
                done += 1
            # 当前停在该里程碑：状态落在 waiting_statuses 里
            if not closed and r["status_key"] in waiting_statuses:
                entered = next(
                    (s["time"] for s in reversed(r["steps"]) if s["step"] == step), None)
                if entered is None:
                    entered = r["steps"][0]["time"] if r["steps"] else None
                if entered is not None:
                    waits.append(max(0.0, (now - entered).total_seconds() / 86400.0))

        out.append({
            "key": key,
            "step": step,
            "done": done,
            "waiting": len(waits),
            "waiting_max_days": round(max(waits), 2) if waits else None,
        })

    # 终态里程碑：已关闭的单
    closed_n = sum(1 for r in rows if _is_closed(r["status"]))
    out.append({
        "key": cal.CLOSED_MILESTONE_KEY, "step": "", "done": closed_n,
        "waiting": 0, "waiting_max_days": None,
    })
    return out


def drill_workflow(start: str, end: str, step: str, kind: str,
                   status: str = "", limit: int = cal.MAX_DETAIL_ROWS) -> dict:
    """步骤下钻：列出走过/停在某一步的 CR。

    kind:
      - `arrived`  走了这一步的 CR（含已离开的）
      - `current`  当前停在这一步的 CR（按已等待天数倒序）
    与 `build_workflow` 用**同一份**解析结果，故行数与卡片数字一致。
    """
    rows, warnings = load_rows(start, end)
    if step not in _STEP_COLUMN:
        warnings.append(f"未知的步骤: {step}")
        rows = []

    key_status = status.strip().upper() if status else ""
    now = datetime.now()
    out = []
    for r in rows:
        if key_status and r["status_key"] != key_status:
            continue
        steps = r["steps"]
        idx = next((i for i, s in enumerate(steps) if s["step"] == step), None)
        if idx is None:
            continue  # 没走过这一步

        # 与 build_workflow 完全同一个判定：当前步骤由 status 决定，
        # 不用「时间线最后一步」（Closed 的单很多没走 feedback，见 step_of_status）
        cur_step = "" if _is_closed(r["status"]) else step_of_status(r["status"])
        is_current = cur_step == step
        if kind == "current" and not is_current:
            continue

        entered = steps[idx]
        # 「走过」的单取离开时间；「当前停留」的单取现在
        left = steps[idx + 1]["time"] if idx + 1 < len(steps) else None
        if is_current:
            left = None
        end_ts = left or now
        days = max(0.0, (end_ts - entered["time"]).total_seconds() / 86400.0)

        out.append({
            "change_request_id": r["change_request_id"],
            "status": r["status"],
            "change_category": r["category"],
            "step": step,
            "entered_at": entered["time"].strftime("%Y-%m-%d %H:%M:%S"),
            "left_at": left.strftime("%Y-%m-%d %H:%M:%S") if left else None,
            "days": round(days, 2),
            "operator": entered["operator"] or None,
            "result": entered["result"] or None,
            "next_status": entered["next_status"] or None,
            "current": is_current,
        })

    # 当前滞留：等得最久的在前（这是这个视图的核心价值）
    if kind == "current":
        out.sort(key=lambda x: (-x["days"], x["change_request_id"]))
    else:
        out.sort(key=lambda x: (x["entered_at"], x["change_request_id"]))

    truncated = len(out) > limit
    if truncated:
        warnings.append(f"结果共 {len(out)} 条，仅返回等待最久的 {limit} 条，请缩小时间范围后重试。")

    start_ts, end_ts = cal.normalize_window(start, end)
    return {
        "meta": {"start": start_ts, "end": end_ts,
                 "step": step, "kind": kind, "status": key_status,
                 "warnings": warnings},
        "step": step, "kind": kind, "status": key_status,
        "total": len(out), "truncated": truncated, "rows": out[:limit],
    }

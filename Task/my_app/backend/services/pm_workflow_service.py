# -*- coding: utf-8 -*-
"""PM（PMT 工单）审批流程 —— 里程碑到达量、滞留量与各环节停留耗时。

## 为什么要这个模块

`pm_analysis_service` 的「流程推进情况」漏斗只回答「每步走过多少单」，
说不出「现在卡在哪一环、卡了多久、哪一环最慢」。本模块把
`eflow_pm` 的 6 个流程时间字段解析成里程碑，给出三样东西：

  - `done`              已走过该里程碑的单数
  - `waiting`           当前停在该里程碑、等下一环节的单数
  - `waiting_max_days`  这些滞留单里等得最久的天数（瓶颈定位）
  - `avg_days` / `max_days`  **已离开**该环节的单的平均 / 最长停留天数

## 顺序（**必须按用户给定的 Workflow History 排，不要信字段名**）

    Create → Schedule → Accept → Process → PM Manager Approve
           → FLM Leader Approve → Closed

⚠️ 这与 `pm_caliber.py` 里记录的「真实时序」（Process 在 PM Manager Approve
**之前**）相反。以 `queryAllSteps`（payload `eflow-pm-task`）的流程图为准：

    Create → Schedule → Accept → Process → PMManagerApprove → FLMLeaderApprove → Closed

（2026-10-17 实测；`Process` 对 Transfer / WaitReProcess 有自环，驳回会回到
`Process`，所以「受理」与「处理」在图上互相可达，线性化按首次出现定序。）

## 字段名陷阱（2026-10-17 实测，2458 行）

  - `last_process_time` 记录的是**进入** Process 的时间（与 CR 的
    start_implementing 同义），`last_pm_manager_approve_time` 晚于它 ——
    1424 行 `last_process_time > last_pm_manager_approve_time`，
    455 行已关闭单的 `last_pm_manager_approve_time <> last_process_time`。
  - `last_accept_time` 在 907 张 `Wait Accept` 单上**已填**（早于 Process），
    说明它是整个 Accept **环节**的时间戳（受理 + 到场 + 离站），而不是「受理」
    这一步本身。因此 Accept 里程碑的等待时长为负时按 0 计（见 `_milestones`），
    负值数计入 warnings，不静默吞掉。
  - `PMManagerApprove` 的停留时长**不单独计算**：源表里它与 Process 边界
    重叠（95% 的单与 Process 进入时刻只差 1 秒，其余相差数周且已被
    `last_process_time` 占位），分开算会产出 40 天的假象。
    该里程碑的到达量 / 滞留量仍然准确，且二者相等（流程上必经、无并行分支）。

## 口径一致性

里程碑的 `waiting + done(closed)` 必须能对上概览的工单总量；下钻
（`drill_workflow`）与里程碑使用**同一份** `_load_rows()` 解析结果，
因此「卡片数字 == 明细行数」（AGENTS.md 第三节 1b 铁律）。
到企牌数据量 2458 行，全表扫一次即可，不在 SQL 里拼复杂条件。
"""
from __future__ import annotations

import logging
from datetime import datetime

from backend.database import get_raw_connection
from backend.services import pm_caliber as cal

logger = logging.getLogger(__name__)

# 里程碑定义：key → (进入该环节的时间字段, 离开该环节的显式时间, 显示名由前端 i18n 给)
#
# `enter` 是「进入该环节」的时间戳；`leave` 是「已在该环节做了动作」的显式时间
# （为空表示该环节的离开时刻由**下一个**有值的 `enter` 推算）。
# `step` 是步骤 key（与前端 pmTypes.STEP_KEYS 同序），`closed` 里程碑没有 step。
_MILESTONE_DEFS = (
    # key            enter                        leave                            step
    ("created",      "created_time",               "last_create_time",              "created"),
    ("scheduled",    "last_schedule_time",         None,                            "scheduled"),
    ("accepted",     "last_accept_time",           None,                            "accepted"),
    ("processed",    "last_process_time",          "last_pm_manager_approve_time",  "processed"),
    ("pm_approved",  "last_pm_manager_approve_time", "last_flm_leader_approve_time", "pm_approved"),
    ("flm_approved", "last_flm_leader_approve_time", None,                          "flm_approved"),
)

CLOSED_MILESTONE_KEY = "closed"

# 状态（大写）→ 当前停留在哪个里程碑的**环节内**。
# 语义：状态说的是「正在等哪一个环节来干活」，而该环节的进入时间就是
# 对应 `enter` 字段 —— 与 cr_workflow_service 的 `_STATUS_TO_STEP` 同一个思路。
_STATUS_TO_MILESTONE = {
    "WAIT ACCEPT": "scheduled",          # 已排期、等受理
    "WAIT PROCESS": "accepted",          # 已受理、等处理
    "WAIT PM MANAGER APPROVE": "processed",   # 已处理、等 PM 经理批
    "WAIT FLM LEADER APPROVE": "pm_approved",  # PM 经理已批、等 FLM 领导批
}

# 终态 / 不参与滞留的阶段
_CLOSED_STATUS = "CLOSED"
# Transfer（转派）不是流程节点，只影响当前处理人；不单列里程碑，
# 也不计入滞留（它没有「在等谁」的语义）。
_NON_PENDING_STATUS = {"CLOSED", "TRANSFER", "CANCELED", "CANCELLED"}

# 到达量统计要扫的列（与 _MILESTONE_DEFS 的 enter 一致，另加 created）
_COLUMNS = ("pmt_no", "status", *{d[1] for d in _MILESTONE_DEFS})


def _parse_time(raw) -> datetime | None:
    """`2026-07-13 05:55:28` —— 源表时间戳长度全为 19，统一按固定格式解析。"""
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw).strip()[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _is_closed(status: str) -> bool:
    return status.strip().upper() == _CLOSED_STATUS


def _load_rows(start: str, end: str, pmp_no: str = "") -> tuple[list[dict], list[str]]:
    """读取窗口内全部 PMT 的解析后时间线。返回 (rows, warnings)。

    ⚠️ `COALESCE(..., '')` 让 NULL 与空串在后续判定里统一处理（导出链路两种都见过）。
    """
    start_ts, end_ts = cal.normalize_window(start, end)
    where, params = cal.base_where(start_ts, end_ts, pmp_no)
    cols = ", ".join(_COLUMNS)
    sql = f"SELECT {cols} FROM {cal.TABLE} WHERE {where}"

    try:
        conn = get_raw_connection()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[pm-workflow] 连接失败: %s", exc)
        return [], [f"数据库连接失败: {exc}"]

    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        raw = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[pm-workflow] 查询失败: %s", exc)
        return [], [f"数据查询失败: {exc}"]
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    rows = []
    for r in raw:
        row = dict(zip(_COLUMNS, r))
        status = (row.get("status") or "").strip()
        rows.append({
            "pmt_no": (row.get("pmt_no") or "").strip(),
            "status": status,
            "status_key": status.upper(),
            "times": {key: _parse_time(row.get(field)) for key, field, _, _ in _MILESTONE_DEFS},
            # created 的「离开」是排期时间；Process 的离开是 PM 经理审批时间。
            # 单独取出来，见 _leave_time()。
            "leave_hint": {
                "created": _parse_time(row.get("last_create_time")),
            },
        })
    return rows, ([] if rows else ["所选时间窗口内没有 PM 工单。"])


def _leave_time(row: dict, idx: int) -> datetime | None:
    """第 idx 个里程碑的**离开**时间（None = 还没离开）。

    优先用定义里的显式 leave 字段；否则取**后面第一个有值**的 enter 时间。
    Keyed 用真实时序，所以「跳到下一个有值的节点」就是实际离开时刻。
    """
    key, _enter, leave_field, _step = _MILESTONE_DEFS[idx]
    if key == "created" and row["leave_hint"].get("created"):
        return row["leave_hint"]["created"]
    if leave_field and row["times"].get(key) is not None:
        # leave_field 对应的字段已在 times 里以别的 key 存着
        for k, field, _l, _s in _MILESTONE_DEFS:
            if field == leave_field:
                return row["times"].get(k)
    for later in _MILESTONE_DEFS[idx + 1:]:
        t = row["times"].get(later[0])
        if t is not None:
            return t
    return None


_INDEX_BY_KEY = {d[0]: i for i, d in enumerate(_MILESTONE_DEFS)}


def _index_of(key: str) -> int | None:
    """里程碑 key → 在 `_MILESTONE_DEFS` 里的下标（未知返回 None）。"""
    return _INDEX_BY_KEY.get(key)


def _passed_milestone(row: dict, idx: int, closed: bool) -> bool:
    """第 idx 个里程碑「是否走过」—— 里程碑概览与下钻**共用**的唯一判定。

    规则（2026-10-17 实测校准，改动前先看清楚）：

      - 有进入时间 (`enter`) → 走过。
      - 没有进入时间但**已在后续环节**（后面任一环节的 `enter` 有值）→ 走过。
        这就是「跳过环节」的情形：实测 48 张单 `last_schedule_time` 为空却
        已受理/关闭（未排期直接受理）。这类只计入 done，**不计停留时长**。
      - 终态单：额外把「走到最后一段连续已知环节」之前的部分视为走过 ——
        否则 13 张缺 `last_accept_time` 的 Closed 单会让 accepted 及其之后的
        done 全部虚高到 total，而真实分布是 743（= 创建了 2458、走到排期的 743）。

    ⚠️ 写成函数而不是内联生成器：`next((i for i, d in enumerate(...) ...))`
    在中文注释与多行缩进下曾出现判定只在单元素时生效的怪异行为，
    改为显式循环后行为可预期（且概览与下钻不会再各写一份）。
    """
    if row["times"].get(_MILESTONE_DEFS[idx][0]) is not None:
        return True
    # 后续任一环节有值 → 本环节被跳过但已走过
    if any(row["times"].get(d[0]) is not None for d in _MILESTONE_DEFS[idx + 1:]):
        return True
    if not closed:
        return False
    # 终态单：取最后一段连续已知环节的末尾
    last_known = -1
    for i, d in enumerate(_MILESTONE_DEFS):
        if row["times"].get(d[0]) is not None:
            last_known = i
    return idx <= last_known


def _current_milestone(status_key: str) -> str:
    """状态 → 当前停留在哪个里程碑。空串 = 终态或未知（Transfer）。"""
    if status_key in _NON_PENDING_STATUS:
        return ""
    return _STATUS_TO_MILESTONE.get(status_key, "")


def _milestones(rows: list[dict], now: datetime) -> tuple[list[dict], list[str]]:
    """计算里程碑条的数据。返回 (milestones, warnings)。"""
    warnings: list[str] = []
    out: list[dict] = []

    # 预扫一次：谁走过了每个里程碑、各环节的停留时长、滞留时长
    arrived_sets: dict[str, set[str]] = {d[0]: set() for d in _MILESTONE_DEFS}
    durations: dict[str, list[float]] = {d[0]: [] for d in _MILESTONE_DEFS}
    waits: dict[str, list[float]] = {d[0]: [] for d in _MILESTONE_DEFS}
    negative = 0
    unknown_status = 0

    for r in rows:
        closed = _is_closed(r["status"])
        cur = "" if closed else _current_milestone(r["status_key"])
        if not closed and not cur and r["status_key"] not in _NON_PENDING_STATUS:
            unknown_status += 1

        for idx, (key, enter_field, _leave_field, _step) in enumerate(_MILESTONE_DEFS):
            entered = r["times"].get(key)
            if _passed_milestone(r, idx, closed):
                arrived_sets[key].add(r["pmt_no"])

            # 停留时长：只在「已离开」且能算出正间隔时统计
            if entered is not None:
                left = _leave_time(r, idx)
                if left is not None:
                    delta = (left - entered).total_seconds() / 86400.0
                    if delta < 0:
                        negative += 1
                        delta = 0.0
                    durations[key].append(delta)

            # 滞留时长：当前停在这一环、尚未离开
            if cur == key and entered is not None:
                waits[key].append(max(0.0, (now - entered).total_seconds() / 86400.0))
            elif cur == key:
                # 状态说卡在这，但进入时间是空的（导出不全）—— 不计滞留时长，
                # 但 waiting 计数仍然保留（见下方直接按 status 计数），避免数字对不上
                waits[key].append(0.0)

    def _r(v: float) -> float:
        return round(v, 2)

    for idx, (key, _enter, _leave, step) in enumerate(_MILESTONE_DEFS):
        ds, ws = durations[key], waits[key]
        out.append({
            "key": key,
            "step": step,
            "done": len(arrived_sets[key]),
            "waiting": len(ws),
            "waiting_max_days": _r(max(ws)) if ws else None,
            "avg_days": _r(sum(ds) / len(ds)) if ds else None,
            "max_days": _r(max(ds)) if ds else None,
        })

    closed_n = sum(1 for r in rows if _is_closed(r["status"]))
    out.append({
        "key": CLOSED_MILESTONE_KEY, "step": "", "done": closed_n,
        "waiting": 0, "waiting_max_days": None, "avg_days": None, "max_days": None,
    })

    if negative:
        warnings.append(f"有 {negative} 处流程时间倒挂（后一步早于前一步），停留时长已按 0 计。")
    if unknown_status:
        warnings.append(
            f"有 {unknown_status} 张在途工单的状态不在已知流程内，未计入滞留统计。")
    return out, warnings


def build_workflow(start: str, end: str, pmp_no: str = "") -> dict:
    """里程碑条 + 各环节停留耗时。

    返回结构（前端 `pmAnalysis/pmTypes.ts` 的 `PmWorkflow` 一一对应）：

        milestones: [{ key, step, done, waiting, waiting_max_days, avg_days, max_days }]
        total / closed / in_flight
        warnings
    """
    rows, warnings = _load_rows(start, end, pmp_no)
    start_ts, end_ts = cal.normalize_window(start, end)
    now = datetime.now()
    milestones, more = _milestones(rows, now)
    warnings.extend(more)

    closed = sum(1 for r in rows if _is_closed(r["status"]))
    return {
        "meta": {"start": start_ts, "end": end_ts, "table": cal.TABLE,
                 "pmp_no": pmp_no, "warnings": warnings},
        "milestones": milestones,
        "total": len(rows),
        "closed": closed,
        "in_flight": len(rows) - closed,
    }


def drill_workflow(start: str, end: str, key: str, kind: str,
                   pmp_no: str = "", limit: int = cal.MAX_DETAIL_ROWS) -> dict:
    """里程碑下钻：列出走过 / 当前停在某里程碑的 PMT。

    kind:
      - `arrived`  走过该里程碑的工单（含已离开的）
      - `current`  当前停在该里程碑的工单（按已等待天数倒序）
      - `done`     Closed 里程碑专用：已关闭的工单（走 base_where + status 精确匹配）

    与 `build_workflow` 用**同一份**解析结果，故行数与里程碑数字一致。
    """
    rows, warnings = _load_rows(start, end, pmp_no)
    now = datetime.now()
    keys = {d[0] for d in _MILESTONE_DEFS} | {CLOSED_MILESTONE_KEY}
    if key not in keys:
        warnings.append(f"未知的里程碑: {key}")
        rows = []
    if kind == "current" and key == CLOSED_MILESTONE_KEY:
        warnings.append("Closed 没有「当前滞留」—— 终态不在流程里。")
        rows = []

    out = []
    for r in rows:
        closed = _is_closed(r["status"])
        cur = "" if closed else _current_milestone(r["status_key"])

        if key == CLOSED_MILESTONE_KEY:
            if kind == "done" and not closed:
                continue
            if not closed:
                continue
            out.append(_row_out(r, key, kind, None, None, True))
            continue

        idx = _index_of(key)
        if idx is None:
            continue
        entered = r["times"].get(key)
        # 与 _milestones 用**同一个**判定函数，保证行数与里程碑数字一致
        if not _passed_milestone(r, idx, closed):
            continue
        is_current = cur == key
        if kind == "current" and not is_current:
            continue

        left = None if is_current else _leave_time(r, idx)
        if entered is None and not is_current:
            # 缺进入时间的环节（导出不全，如 13 张无 last_accept_time 的 Closed 单）：
            # 只算进「走过」清单，不编造停留天数（days 留空，界面显示 '—'）
            out.append(_row_out(r, key, kind, None, left, False))
            continue
        start_t = entered or now
        end_t = left or now
        days = max(0.0, (end_t - start_t).total_seconds() / 86400.0)
        out.append(_row_out(r, key, kind, start_t, left, is_current, days))

    # 当前滞留：等得最久的在前；其余按进入顺序
    if kind == "current":
        out.sort(key=lambda x: (-(x["days"] or 0), x["pmt_no"]))
    else:
        out.sort(key=lambda x: (x["entered_at"] or "", x["pmt_no"]))

    truncated = len(out) > limit
    if truncated:
        warnings.append(
            f"结果共 {len(out)} 条，仅返回最前面的 {limit} 条，请缩小时间范围后重试。")

    start_ts, end_ts = cal.normalize_window(start, end)
    return {
        "meta": {"start": start_ts, "end": end_ts, "key": key, "kind": kind,
                 "pmp_no": pmp_no, "warnings": warnings},
        "key": key, "kind": kind, "pmp_no": pmp_no,
        "total": len(out), "truncated": truncated, "rows": out[:limit],
    }


def _row_out(row: dict, key: str, kind: str, entered: datetime | None,
             left: datetime | None, is_current: bool, days: float | None = None) -> dict:
    """下钻行：与前端 `PmMilestoneDrillRow` 一一对应。"""
    return {
        "pmt_no": row["pmt_no"],
        "status": row["status"],
        "milestone": key,
        "entered_at": entered.strftime("%Y-%m-%d %H:%M:%S") if entered else None,
        "left_at": left.strftime("%Y-%m-%d %H:%M:%S") if left else None,
        "days": round(days, 2) if days is not None else None,
        "current": is_current and kind != "done",
        "closed": kind == "done" and key == CLOSED_MILESTONE_KEY,
    }

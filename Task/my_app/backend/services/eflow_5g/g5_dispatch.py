# -*- coding: utf-8 -*-
"""5G 站点告警的**单条告警判定与派单**（服务主流程的判定内核）。

## 拆分原因（2026-10-29）

`g5_assign_service.py` 一度长到 750 行，超出 AGENTS.md 第三节第 2 条的
「新增文件单个不超过 500 行」。主流程拆成三块：

| 模块 | 职责 |
| --- | --- |
| `g5_assign_service.py` | 装配口径、拉告警、主循环编排、结果汇总 |
| `g5_dispatch.py`（本模块） | **单条告警**的判定 → 派单/演练 → 状态落表 |
| `g5_rules.py` / `g5_fetch.py` / `g5_notify.py` | 纯规则 / 拉取审计 / 通报渲染 |

## 单条告警的判定顺序（每一步都有明确出口，**不静默漏派**）

1. 已处理（`Y` / 演练 `D`）→ 跳过（永久不再处理）；
2. 上游已有 TT（`ttid` 非空）→ 跳过（eFlow 自己的规则先建了单，不重复建）；
3. 存续时长 < `min_age_minutes`（默认 15）→ **等待**（等下轮），不是跳过；
4. 存续时长 > `window_minutes`（默认 180）→ **过期**，不派；
5. 同站同窗口已有 99933 → 跳过（关联判定命中）；
6. 关联判定**无法完成** → 按「无关联」继续派单并留痕（不因名字对不上就长期漏派）；
7. 站点解析失败 → 记 `N` + 群里通报「需人工处理」（`send_status` 抑制重复）；
8. 本条已被组长的 TT 覆盖（**一站多小区合并**）→ 并入该组，不单独派单；
9. 演练模式 → 记 `D` 并渲染「将发的正文」（不投递）；
10. 真派单 → 内置重试 + 回查 `ttid`，**回查得到才算成功**。

## 返回值

`process_alarm` 返回一个 dict，形如
`{"action": "assign"|"dry_run"|"merged"|"skip"|"wait"|"expired"|"fail",
  "assigned": bool, "tt_no": str, "cells": [...], ...}`，
供主循环统一计数与渲染。
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.services.eflow_assign import assign_engine as engine
from backend.services.eflow_assign import eflow_assign_client as client
from backend.services.eflow_assign.assign_config import norm_code
from backend.services.eflow_5g import g5_rules as rules
from backend.services.eflow_5g import g5_store as store

logger = logging.getLogger("eflow_5g_dispatch")

# 单条告警的处理动作（主循环据此分桶计数）
ACTION_ASSIGN = "assign"
ACTION_DRY_RUN = "dry_run"
ACTION_MERGED = "merged"
ACTION_SKIP = "skip"
ACTION_WAIT = "wait"
ACTION_EXPIRED = "expired"
ACTION_FAIL = "fail"


def build_base_record(alarm: Dict[str, Any], rec: Dict[str, Any]) -> Dict[str, Any]:
    """告警 → 状态表基础行（各判定分支共用）。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    occ = engine.occur_ms(alarm)
    return {
        "alarm_key": engine.alarm_key_of(alarm),
        "alarm_id": engine.s(engine.val(alarm.get("id"))),
        "alarm_code": norm_code(engine.val(alarm.get("alarmcode"))),
        "site_id": engine.s(engine.val(alarm.get("site_id"))) or engine.s(engine.val(alarm.get("site"))),
        "site_name": engine.s(engine.val(alarm.get("site_name"))) or engine.s(engine.val(alarm.get("sitename"))),
        "cell_name": rules.alarm_cell(alarm),
        "me_name": engine.s(engine.val(alarm.get("mename")) or engine.val(alarm.get("site"))),
        "occur_time": (datetime.fromtimestamp(occ / 1000).strftime("%Y-%m-%d %H:%M:%S")
                       if occ else None),
        "last_seen_time": now_str,
        "first_seen_time": rec.get("first_seen_time") or now_str,
    }


def process_alarm(alarm: Dict[str, Any],
                  ctx: engine.AssignContext,
                  rec: Dict[str, Any],
                  group: Dict[str, Any],
                  index: client.SiteIndex,
                  conn,
                  all_alarms: List[Dict[str, Any]],
                  group_map: Dict[str, Dict[str, Any]],
                  group_tt: Dict[str, str],
                  group_cells: Dict[str, List[str]],
                  now_ms: int,
                  ) -> Dict[str, Any]:
    """处理单条告警 → 判定结果 dict（不抛异常，失败以 action=fail 表达）。

    `group_tt` / `group_cells` 是**就地更新**的跨条状态（组长建出的 TT 号与
    本组涵盖的小区），成员告警据此并入组长的 TT。
    """
    a = alarm
    akey = engine.alarm_key_of(a)
    base = build_base_record(a, rec)
    out: Dict[str, Any] = {"action": ACTION_SKIP, "alarm_key": akey,
                           "assigned": False, "tt_no": "", "cells": [],
                           "sample": None, "warning": None, "manual": None}
    prev = engine.s(rec.get("assign_status"))
    first_sight = not prev

    # ① 已确认派单成功（Y）→ 永久跳过；演练记录（D）只在演练模式下算已处理
    if engine.is_already_handled(prev, ctx.dry_run):
        store.upsert_record(conn, base)
        out["action"] = ACTION_SKIP
        out["sample"] = {"alarm_key": akey, "action": "skip_already_handled"}
        return out

    # ② 上游已带 TT（eFlow 自己的派单规则先建了）→ 不重复派
    upstream_tt_no = engine.upstream_tt(a)
    if upstream_tt_no:
        out["skipped"] = True
        base.update({"assign_status": "Y", "tt_no": upstream_tt_no,
                     "skip_reason": "上游已存在 TT（eFlow 规则已派单），不重复派"})
        store.upsert_record(conn, base)
        out["action"] = ACTION_SKIP
        out["sample"] = {"alarm_key": akey, "action": "skip_existing_tt",
                         "tt_no": upstream_tt_no}
        logger.info("[5G] 跳过 %s：上游已有 TT %s", akey, upstream_tt_no)
        return out

    # ③ 触发条件：告警码命中 + 存续时长落在 [下界, 上界]
    verdict, age = engine.due_verdict(ctx, a, now_ms)
    if verdict == engine.DUE_TOO_NEW:
        # 还没到派单时机（默认等满 15 分钟）→ 本轮不派，下轮再看
        out["action"] = ACTION_WAIT
        out["age_minutes"] = round(age or 0, 1)
        return out
    if verdict in (engine.DUE_TOO_OLD, engine.DUE_NO_TIME):
        out["action"] = ACTION_EXPIRED
        out["age_minutes"] = round(age or 0, 1)
        out["reason"] = verdict
        return out
    if verdict != engine.DUE_YES:
        out["action"] = ACTION_SKIP
        return out

    # ④ eFlow 侧 ttstatus：**提示信号，不是阻断条件**（同 Fiber 口径）
    tt_status = engine.s(engine.val(a.get("ttstatus")))
    status_suspect = not engine.is_clean_ttstatus(tt_status)
    if status_suspect:
        out["suspect_ttstatus"] = True
        out["ttstatus"] = tt_status
        if first_sight:
            out["warning"] = (f"{akey} eFlow 侧 ttstatus={tt_status}"
                              f"（ME 可能未关联站点），仍尝试派单")
        logger.warning("[5G] %s ttstatus=%s（ME 未关联站点），不阻断、仍尝试派单",
                       akey, tt_status)

    # ⑤ 关联判定：同站同窗口已有 99933 → 跳过
    # ⚠ `due` 的口径：**通过了全部前置判定、进入派单阶段**的告警条数
    #   （含合并到组长 TT 的成员、含演练）—— 即「本该派但还没派出去的」。
    #   关联命中/存续不够/太老的都不算 due。
    corr_note_for_msg = ""
    corr_verdict, corr, corr_note = engine.correlation_verdict(ctx, a, all_alarms)
    if corr_verdict == engine.CORRELATION_HIT and corr is not None:
        reason = (f"同站点已有 {norm_code(engine.val(corr.get('alarmcode')))} 告警"
                  f"（id={engine.s(engine.val(corr.get('id')))}），不重复派单")
        base.update({"assign_status": "S", "skip_reason": reason})
        store.upsert_record(conn, base)
        out["action"] = ACTION_SKIP
        out["sample"] = {"alarm_key": akey, "action": "skip", "reason": reason}
        logger.info("[5G] 跳过 %s：%s", akey, reason)
        return out
    if corr_verdict == engine.CORRELATION_UNDETERMINED:
        out["correlation_undetermined"] = True
        out["corr_note_detail"] = corr_note
        out["site_keys"] = sorted(engine.alarm_site_keys(a))
        if first_sight:
            out["warning"] = (f"{akey} 关联判定无法完成（{corr_note}），"
                              f"按「无关联」继续派单")
        logger.warning("[5G] %s 关联判定无法完成：%s；按无关联继续派单",
                       akey, corr_note)
        site_keys_txt = ", ".join(out["site_keys"]) or "-"
        corr_note_for_msg = ("99933 correlation could not be determined "
                             f"(site keys: {site_keys_txt}) — "
                             "assigned as no-correlation")

    # 通过全部前置判定 → 进入派单阶段（关联命中/存续不够/太老的都不算）
    out["due"] = True

    # ⑥ 合并派单：本条已被组长告警的 TT 覆盖
    grp = group_map.get(akey) or {"root": akey, "members": [a]}
    root_key = grp["root"]
    if root_key != akey and root_key in group_tt:
        # 仍要解析站点：通报里要列出本组实际涵盖哪些小区
        _mtrace: Dict[str, Any] = {}
        m_site_id, m_site_name = client.resolve_site(a, index, trace=_mtrace)
        if not m_site_name:
            m_site_name = base.get("me_name") or akey
        cells = group_cells.setdefault(root_key, [])
        _cell = rules.alarm_cell(a)
        if _cell and _cell not in cells:
            cells.append(_cell)
        if m_site_id:
            base["site_id"] = m_site_id
            base["site_name"] = m_site_name
        base.update({
            "assign_status": "D" if ctx.dry_run else "Y",
            "tt_no": group_tt.get(root_key) or None,
            "skip_reason": (f"同一站点的多小区告警，已合并到组长告警 {root_key} 的 TT"
                            f"（本组共 {len(grp['members'])} 条告警）"),
        })
        store.upsert_record(conn, base)
        out["action"] = ACTION_MERGED
        out["root"] = root_key
        out["cells"] = list(cells)
        out["sample"] = {"alarm_key": akey, "action": "merged_into_group",
                         "root": root_key, "cell": _cell}
        logger.info("[5G] %s 合并到组长 %s 的 TT（本组 %d 条告警），不单独派单",
                    akey, root_key, len(grp["members"]))
        return out

    # ⑦ 站点解析（5G 的 site 已是数字站号 → 通常第 1 档直接命中）
    trace: Dict[str, Any] = {}
    site_id, site_name = client.resolve_site(a, index, trace=trace)
    if not site_id:
        tried = trace.get("tried") or []
        hint = f"；已尝试站名 {tried}" if tried else ""
        reason = f"站点解析失败（site/site_name 均无法映射到 cmdb 站点{hint}）"
        tried_txt = f" (tried site names: {', '.join(map(str, tried))})" if tried else ""
        reason_en = ("site resolution failed — no numeric site ID matched in cmdb"
                     f"{tried_txt}")
        base.update({"assign_status": "N", "last_error": reason})
        store.upsert_record(conn, base)
        if first_sight:
            out["warning"] = f"{akey} 站点解析失败，未派单：{reason}"
        # 自动派不了，但不能静默：同一条只往群里通报一次（send_status 抑制）
        if engine.s(rec.get("send_status")) != "Y":
            out["manual"] = {"alarm_key": akey, "alarm": a, "reason": reason_en}
        out["action"] = ACTION_FAIL
        out["reason"] = reason
        return out
    base.update({"site_id": site_id, "site_name": site_name})

    fuzzy_note = ""      # 中文：进 warnings / 日志
    fuzzy_note_en = ""   # 英文：进群通报
    if trace.get("matched_by") == "fuzzy":
        fuzzy_note = (f"站点名近似匹配：{trace.get('query')!r} → {site_name!r}"
                      f"（相似度 {trace.get('score')}），请核对 cmdb 命名")
        fuzzy_note_en = (f"Site name fuzzy-matched: {trace.get('query')!r} -> "
                         f"{site_name!r} (score {trace.get('score')}), "
                         f"please verify the cmdb naming")
        if first_sight:
            out["warning"] = f"{akey} {fuzzy_note}"
        logger.warning("[5G] %s %s", akey, fuzzy_note)

    # ⑧ 演练模式：只记录
    if ctx.dry_run:
        base.update({"assign_status": "D",
                     "skip_reason": "dry-run 演练模式，未真派单"
                                    + (f"（{fuzzy_note}）" if fuzzy_note else "")})
        store.upsert_record(conn, base)
        group_tt.setdefault(root_key, "")
        cells = group_cells.setdefault(root_key, [])
        _cell = rules.alarm_cell(a)
        if _cell and _cell not in cells:
            cells.append(_cell)
        out["action"] = ACTION_DRY_RUN
        out["site_id"] = site_id
        out["site_name"] = site_name
        out["cell"] = _cell
        out["cells"] = list(cells)
        out["site_matched_by"] = trace.get("matched_by")
        out["site_score"] = trace.get("score")
        out["group_size"] = len(grp["members"])
        out["root"] = root_key
        out["site_note"] = fuzzy_note_en
        out["corr_note"] = corr_note_for_msg
        out["sample"] = {"alarm_key": akey, "action": "dry_run",
                         "site_id": site_id, "site_name": site_name,
                         "cell": _cell,
                         "site_matched_by": trace.get("matched_by"),
                         "site_score": trace.get("score"),
                         "group_size": len(grp["members"])}
        logger.info("[5G] DRY-RUN 将派单 %s site=%s/%s cell=%s（本组 %d 条告警）",
                    akey, site_id, site_name, _cell, len(grp["members"]))
        return out

    # ⑨ 真派单（含重试 + 回查 ttid，eFlow 派单时灵时不灵）
    max_attempts, verify_tries = engine.assign_attempt_budget(ctx, status_suspect)
    tt_no, last_err = engine.assign_with_retry(
        ctx, a, group, site_id, site_name, akey, max_attempts, verify_tries)

    if tt_no:
        base.update({"assign_status": "Y", "tt_no": tt_no,
                     "tt_proc_id": engine.s(engine.val(a.get("procid"))) or None})
        store.upsert_record(conn, base)
        group_tt[root_key] = tt_no
        cells = group_cells.setdefault(root_key, [])
        _cell = rules.alarm_cell(a)
        if _cell and _cell not in cells:
            cells.append(_cell)
        out["action"] = ACTION_ASSIGN
        out["assigned"] = True
        out["tt_no"] = tt_no
        out["site_id"] = site_id
        out["site_name"] = site_name
        out["cell"] = _cell
        out["cells"] = list(cells)
        out["root"] = root_key
        out["group_size"] = len(grp["members"])
        out["site_matched_by"] = trace.get("matched_by")
        out["site_note"] = fuzzy_note_en
        out["corr_note"] = corr_note_for_msg
        logger.info("[5G] 派单成功 %s → TT %s（本组 %d 条告警）",
                    akey, tt_no, len(grp["members"]))
        return out

    # ⑩ 派单失败 → 记 N + 必要时通报人工
    out["action"] = ACTION_FAIL
    reason = last_err
    reason_en = last_err
    if status_suspect:
        reason = (f"eFlow 侧 ttstatus={tt_status}（ME 未关联站点），"
                  f"已尝试派单但未建出 TT：{last_err}")
        reason_en = (f"eFlow ttstatus={tt_status} "
                     f"(ME not bound to a site); assign was attempted "
                     f"but no TT was created: {last_err}")
    base.update({"assign_status": "N", "last_error": reason})
    store.upsert_record(conn, base)
    if first_sight:
        out["warning"] = f"{akey} 派单失败（尝试 {max_attempts} 次）：{reason}"
    logger.warning("[5G] 派单失败 %s：%s", akey, reason)
    if status_suspect and engine.s(rec.get("send_status")) != "Y":
        out["manual"] = {
            "alarm_key": akey, "alarm": a,
            "reason": reason_en,
            "hint": ["Note: this ME is not correctly bound to a site in eFlow",
                     "      (site still holds the ME name, sitename is empty),",
                     "      so eFlow will never create a TT for it.",
                     "      Please bind the ME to a numeric site in eFlow,",
                     "      or assign the TT manually. Once the binding is",
                     "      fixed, this task retries automatically."],
        }
    out["reason"] = reason
    return out

# -*- coding: utf-8 -*-
"""5G 站点告警自动派单 + WhatsApp 通报（每 5 分钟一轮，cron `8-59/5 * * * *`）。

## 业务口径（2026-10-28 立项，参考 Fiber Break Alarm Auto Assign）

**触发源**：eFlow 实时告警（直接查 eFlow API，不读本地镜像）。

**派单条件（全部满足）**：
  1. 告警码命中白名单（**支持多个**，默认 5 个 5G 退服类码，页面可配）；
  2. 告警未清除（实时告警接口本身只返回未清除的）；
  3. 告警**存续时长**落在 `[min_age_minutes, window_minutes]` 区间内
     （默认 **下界 15 分钟**、上界 180 分钟）——
     **下界 15 分钟**是需求明确的口径：「告警发生 15 分钟条件满足后派单和推送」，
     即**不是一升起就派**，要等满 15 分钟才派（留时间让短时抖动自然清除）；
  4. 该告警**尚未派过单**（状态表 `eflow_5g_assign_log` 无 Y/D 记录），
     且上游没有自带 TT（`ttid` 为空）；
  5. **同站点在同时间窗口内没有关联告警**（默认 `99933` 小区退服，窗口 60 分钟）。

**一站多小区必须去重**（5G 特有，Fiber 没有）：
实测一个 gNB 的多个小区（cell 50/51/52）各自产生一条告警，同一故障会派出一堆
重复单。故**按「同一站点 + 同一时间窗」合并成一个 TT**，通报正文列出本单实际
涵盖的小区。

## 与 Fiber 的字段形态差异（实测，决定了实现方式）

| | Fiber（4758） | 5G（2002xxxxx） |
| --- | --- | --- |
| `site` | **ME 名**（`6120HA_zardun_UPE128`） | **已是数字站点 ID**（`4162`） |
| `sitename` | `--` | **已是站点名**（`Liscr`） |
| `restype` | 不限 | `zte.ran.gnodeb`（实测 `200201001`） |
| `cell` | 无 | **有**（`52`）、`cellname`（`Liscr-S2`） |

故 5G **不需要**从 ME 名解析站点（`resolve_site` 的第 1 档直接命中
`alarm_fields`），但仍走同一个 `resolve_site` 兜底（万一某天网管改了字段形态，
或站点名与 cmdb 不一致，还能靠 cmdb 校准）。

## 服务端过滤 + 全量兜底审计（⚠ 消除静默失效）

eFlow 的 `alarmcodeconds` **必须带 `restype`**（只给 `alarmcode` → HTTP 499，
实测）。而目标 5 码里 4 个当前**无实例**、无法实测其 restype ——
若猜错，服务端会把该码整个滤掉，**任务永远收不到它且无任何报错**。

对策（两道）：
  1. 默认配 **12 个**候选 RAN restype（实测 12 restype × 6 码 = 72 组合，
     仍只要 **0.03s**，且混入无实例的码不会让查询失败 —— HTTP 200）；
  2. **定期全量审计**（默认每 60 分钟一次）：拉一次全量实时告警，与按码过滤的
     结果对账。一旦发现「全量里有、过滤里没有」的目标码，就写 warnings
     明确报出「该码被 restype 配置漏掉了」，而不是让它静默失效。

实测基线：全量 6752 条 / 4.45s；按码过滤 21 条 / 0.03s。

## 演练模式

`dry_run` 默认开：只查+匹配+记录将要派的单（状态 'D'），**不调用派单接口**。
首次上线先看日志/结果确认无误，再在页面关掉 dry_run。
"""
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.database import get_raw_connection
from backend.services import wa_notify_service as wa_notify
from backend.services.eflow_assign import assign_engine as engine
from backend.services.eflow_assign import eflow_assign_client as client
from backend.services.eflow_assign.assign_config import norm_code
from backend.services.eflow_5g import g5_config as config_mod
from backend.services.eflow_5g import g5_dispatch as dispatch_mod
from backend.services.eflow_5g import g5_fetch
from backend.services.eflow_5g import g5_notify
from backend.services.eflow_5g import g5_rules as rules
from backend.services.eflow_5g import g5_store as store
from backend.services.wa_notify_service import dispatch, wait_for_job_result

logger = logging.getLogger("eflow_5g_assign")

# ========== 配置（导入期一次算好；改页面后需 worker 重启） ==========
_CFG = config_mod.load_config()

# 派单重试（eFlow 派单时灵时不灵，必须重试到 TT 真建出为止）
ASSIGN_MAX_ATTEMPTS = max(1, int(os.environ.get("EFLOW_5G_ASSIGN_MAX_ATTEMPTS", "3")))
ASSIGN_RETRY_DELAY = float(os.environ.get("EFLOW_5G_ASSIGN_RETRY_DELAY", "3"))

# 全量审计间隔（分钟）：定期拉全量与按码过滤对账，暴露「restype 配漏」
AUDIT_INTERVAL_MINUTES = max(
    1, int(os.environ.get("EFLOW_5G_ASSIGN_AUDIT_INTERVAL_MINUTES", "60")))

# 消息抬头（群里每条通报都带）
PUSH_TITLE = "5G Site Alarm TT Assign Notification"

# 判定口径装配（共用引擎的唯一载体）
CTX = engine.AssignContext(
    alarm_codes=set(_CFG["alarm_codes"]),
    correlation_codes=set(_CFG["correlation_codes"]),
    correlation_window_minutes=int(_CFG["correlation_window_minutes"]),
    window_minutes=int(_CFG["window_minutes"]),
    min_age_minutes=int(_CFG["min_age_minutes"]),
    group_window_minutes=int(_CFG["group_window_minutes"]),
    assign_group=str(_CFG["assign_group"]),
    dry_run=bool(_CFG["dry_run"]),
    groups=list(_CFG["groups"]),
    site_fuzzy_enabled=bool(_CFG["site_fuzzy_enabled"]),
    site_fuzzy_threshold=float(_CFG["site_fuzzy_threshold"]),
    assign_max_attempts=ASSIGN_MAX_ATTEMPTS,
    assign_retry_delay=ASSIGN_RETRY_DELAY,
    push_title=PUSH_TITLE,
    tag="5G",
    outage_label="the same 5G site outage",
)

# ---- 模块级常量（配置页 defaults_factory 与单测读取） ----
ALARM_CODES = CTX.alarm_codes
ALARM_CODE_NAMES = dict(config_mod.DEFAULT_ALARM_CODE_NAMES)
CORRELATION_CODES = CTX.correlation_codes
CORRELATION_WINDOW_MINUTES = CTX.correlation_window_minutes
WINDOW_MINUTES = CTX.window_minutes
MIN_AGE_MINUTES = CTX.min_age_minutes
ASSIGN_GROUP = CTX.assign_group
DRY_RUN = CTX.dry_run
GROUPS = CTX.groups
GROUPS_FALLBACK = bool(_CFG["groups_fallback"])
SITE_FUZZY_ENABLED = CTX.site_fuzzy_enabled
SITE_FUZZY_THRESHOLD = CTX.site_fuzzy_threshold
GROUP_WINDOW_MINUTES = CTX.group_window_minutes
RESTYPES = list(_CFG["restypes"])
FALLBACK_FULL_SCAN = bool(_CFG["fallback_full_scan"])
CELL_DEDUPE = bool(_CFG["cell_dedupe"])
SAMPLE_LIMIT = engine.SAMPLE_LIMIT

# 判定结论常量（与 Fiber 同名同义）
CORRELATION_HIT = engine.CORRELATION_HIT
CORRELATION_NONE = engine.CORRELATION_NONE
CORRELATION_UNDETERMINED = engine.CORRELATION_UNDETERMINED
DUE_YES = engine.DUE_YES
DUE_TOO_NEW = engine.DUE_TOO_NEW
DUE_TOO_OLD = engine.DUE_TOO_OLD
DUE_NO_CODE = engine.DUE_NO_CODE
DUE_NO_TIME = engine.DUE_NO_TIME

# ==========================================================
# 5G 特有的纯函数与拉取逻辑（已拆到独立模块，这里只做再导出）
# ==========================================================
# `g5_rules` —— 小区标识 / 站点身份 / 一站多小区合并分组 / 小区标签（纯函数）
# `g5_fetch` —— 服务端按码过滤拉取 + 定期全量审计（防 restype 配漏导致静默失效）
alarm_cell = rules.alarm_cell
alarm_site_identity = rules.alarm_site_identity
group_by_site_occurrence = rules.group_by_site_occurrence
group_cell_labels = rules.group_cell_labels
fetch_target_alarms = g5_fetch.fetch_target_alarms


# ==========================================================
# 通报正文渲染（已拆到 g5_notify）
# ==========================================================
build_message = g5_notify.build_message
build_manual_message = g5_notify.build_manual_message


# ==========================================================
# 主流程
# ==========================================================
def run_5g_assign() -> Dict[str, Any]:
    """每 5 分钟执行：拉告警 → 匹配 → 关联判定 → 合并去重 → 派单（或演练）→ 通报 → 落库。"""
    started = time.time()
    now_ms = int(time.time() * 1000)
    out: Dict[str, Any] = {
        "success": False, "dry_run": CTX.dry_run, "fetched": 0,
        "target_alarms": 0, "due": 0, "assigned": 0, "skipped": 0,
        "failed": 0, "notified": 0,
        # 还没到派单时机（存续时长 < min_age_minutes，默认 15 分钟）→ 等下轮
        "waiting": 0, "waiting_samples": [],
        # 存续时长超过触发窗口（太老）→ 不派
        "expired": 0, "expired_samples": [],
        # 关联判定「无法判定 → 按无关联继续派单」
        "correlation_undetermined": 0, "correlation_undetermined_samples": [],
        # eFlow 侧 ttstatus 非 0（ME 未关联站点）—— 不阻断，只收缩重试预算
        "suspect_ttstatus": 0, "suspect_ttstatus_samples": [],
        # 自动派不了 → 群里通报「需人工处理」的计数
        "manual_notified": 0,
        # 一站多小区合并：被组长的 TT 覆盖、未单独建单的告警条数
        "merged": 0,
        # 演练模式下本轮匹配到、但未真派单的告警条数
        "dry_run_count": 0,
        # 合并后实际会派出/演出的单数（站点级）
        "groups": 0,
        "group_window_minutes": CTX.group_window_minutes,
        "cell_dedupe": CELL_DEDUPE,
        "assign_group": CTX.assign_group, "alarm_codes": sorted(CTX.alarm_codes),
        "correlation_codes": sorted(CTX.correlation_codes),
        "restypes": list(RESTYPES),
        "groups_wa": list(CTX.groups), "group_fallback": GROUPS_FALLBACK,
        "samples": [], "errors": [], "warnings": [], "elapsed_seconds": 0,
        # 演练模式下「将发但未发」的通报正文（关掉 dry_run 前用它核对文案）
        "dry_run_preview": [],
    }

    def _finish() -> Dict[str, Any]:
        out["elapsed_seconds"] = round(time.time() - started, 2)
        logger.info("[5G] 完成 dry_run=%s fetched=%s target=%s due=%s waiting=%s expired=%s "
                    "assigned=%s skipped=%s failed=%s notified=%s merged=%s groups=%s 用时%.2fs",
                    CTX.dry_run, out["fetched"], out["target_alarms"], out["due"],
                    out["waiting"], out["expired"], out["assigned"], out["skipped"],
                    out["failed"], out["notified"], out.get("merged", 0),
                    out.get("groups", 0), out["elapsed_seconds"])
        return out

    # ---------- 1. 拉取实时告警（服务端按码过滤 + 定期全量审计） ----------
    try:
        target_alarms, fetched = fetch_target_alarms(
            CTX.alarm_codes, CTX.correlation_codes, RESTYPES, time.time(),
            fallback_full_scan=FALLBACK_FULL_SCAN,
            audit_interval_minutes=AUDIT_INTERVAL_MINUTES)
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"拉取实时告警失败: {type(e).__name__}: {e}")
        logger.exception("[5G] 拉取实时告警失败")
        return _finish()

    all_alarms = fetched["all_rows"]
    out["fetched"] = len(all_alarms)
    out["target_alarms"] = len(target_alarms)
    diag = fetched["diag"]
    out["audit_ran"] = bool(diag.get("audit_ran"))
    if diag.get("missed_codes"):
        # ⚠ 静默失效已变成显式告警：全量里有、过滤里没有的目标码
        out["warnings"].append(
            f"全量审计发现 {len(diag['missed_codes'])} 个告警码被 restype 配置漏掉"
            f"（{', '.join(diag['missed_codes'])}）—— 这些码实时存在但按码过滤拉不到，"
            f"请把它们的 restype 加进「任务配置」的 restypes 字段")
    if not target_alarms:
        out["success"] = True
        out["message"] = "无 5G 目标告警"
        return _finish()

    # ---------- 2. 解析目标派单组 ----------
    try:
        group = client.resolve_group(CTX.assign_group)
    except Exception as e:  # noqa: BLE001
        group = None
        out["errors"].append(f"解析用户组失败: {type(e).__name__}: {e}")
    if group is None:
        out["errors"].append(f"找不到派单用户组 {CTX.assign_group!r}，本轮不派单")
        return _finish()

    # ---------- 3. 读状态表 ----------
    conn = get_raw_connection()
    try:
        store.ensure_log_table(conn)
        keys = [engine.alarm_key_of(a) for a in target_alarms]
        records = store.load_records(conn, keys)

        index = client.SiteIndex(fuzzy_enabled=CTX.site_fuzzy_enabled,
                                 fuzzy_threshold=CTX.site_fuzzy_threshold)
        messages: List[Dict[str, Any]] = []
        pending_success: List[Dict[str, Any]] = []
        pending_manual: List[Dict[str, Any]] = []

        # ---------- 3.1 一站多小区合并分组 ----------
        # 同一 gNB 的多个小区各自一条告警 → 合并成一个 TT（5G 特有）
        group_map = group_by_site_occurrence(
            target_alarms, CTX.group_window_ms if CELL_DEDUPE else 0)
        out["groups"] = len({g["root"] for g in group_map.values()})
        # 组长（组内升起最早）必须先处理，成员才能跟随它建出的 TT 号
        target_alarms = sorted(
            target_alarms,
            key=lambda x: (engine.occur_ms(x) is None, engine.occur_ms(x) or 0,
                           engine.alarm_key_of(x)))
        # 组长 key → 该组建出的 TT 号（dry-run 时为空串，表示「演练已覆盖」）
        group_tt: Dict[str, str] = {}
        # 组长 key → 本组涵盖的小区标签（去重保序）
        group_cells: Dict[str, List[str]] = {}
        # 演练模式下每个「将派单」组的渲染素材（组长告警 + 站点 + 关联留痕）
        # 目的：dry_run 是上线前的核对手段，若连通报正文都看不到，
        #       就只能靠「关掉演练真建一单」来核对，违背演练的初衷。
        dry_root_info: Dict[str, Dict[str, Any]] = {}
        merged = 0

        for a in target_alarms:
            akey = engine.alarm_key_of(a)
            res = dispatch_mod.process_alarm(
                a, CTX, records.get(akey) or {}, group, index, conn,
                all_alarms, group_map, group_tt, group_cells, now_ms)

            # ---- 分桶计数（每种结论都有明确去处，便于排障）----
            if res.get("due"):
                # 进入派单阶段（通过了全部前置判定）的告警条数
                out["due"] += 1
            if res.get("action") == dispatch_mod.ACTION_SKIP:
                out["skipped"] += 1
            elif res.get("action") == dispatch_mod.ACTION_WAIT:
                out["waiting"] += 1
                if len(out["waiting_samples"]) < SAMPLE_LIMIT:
                    out["waiting_samples"].append(
                        {"alarm_key": akey, "age_minutes": res.get("age_minutes")})
            elif res.get("action") == dispatch_mod.ACTION_EXPIRED:
                out["expired"] += 1
                if len(out["expired_samples"]) < SAMPLE_LIMIT:
                    out["expired_samples"].append(
                        {"alarm_key": akey, "age_minutes": res.get("age_minutes"),
                         "reason": res.get("reason")})
            elif res.get("action") == dispatch_mod.ACTION_MERGED:
                merged += 1
            elif res.get("action") == dispatch_mod.ACTION_DRY_RUN:
                out["dry_run_count"] = out.get("dry_run_count", 0) + 1
                dry_root_info.setdefault(res.get("root") or akey, {
                    "alarm": a, "site_id": res.get("site_id"),
                    "site_name": res.get("site_name"),
                    "site_note": res.get("site_note") or "",
                    "corr_note": res.get("corr_note") or "",
                    "group_size": res.get("group_size"),
                })
            elif res.get("action") == dispatch_mod.ACTION_ASSIGN:
                out["assigned"] += 1
                pending_success.append({
                    "alarm_key": akey, "alarm": a,
                    "site_id": res.get("site_id"), "site_name": res.get("site_name"),
                    "tt_no": res.get("tt_no"),
                    "group_key": res.get("root") or akey,
                    "group_size": res.get("group_size"),
                    "cell": res.get("cell"),
                    "site_matched_by": res.get("site_matched_by"),
                    "site_note": res.get("site_note") or "",
                    "corr_note": res.get("corr_note") or "",
                })
            elif res.get("action") == dispatch_mod.ACTION_FAIL:
                out["failed"] += 1

            # ---- 判定链上的「疑似/无法判定」留痕（不阻断派单，但必须可追溯）----
            if res.get("suspect_ttstatus"):
                out["suspect_ttstatus"] += 1
                out["suspect_ttstatus_samples"].append(
                    {"alarm_key": akey, "ttstatus": res.get("ttstatus")})
            if res.get("correlation_undetermined"):
                out["correlation_undetermined"] += 1
                out["correlation_undetermined_samples"].append(
                    {"alarm_key": akey, "me_name": engine.s(
                        engine.val(a.get("mename")) or engine.val(a.get("site"))),
                     "site_keys": res.get("site_keys") or [],
                     "note": res.get("corr_note_detail")})

            if res.get("warning"):
                out["warnings"].append(res["warning"])
            if res.get("sample"):
                out["samples"].append(res["sample"])
            if res.get("manual"):
                pending_manual.append(res["manual"])

        out["merged"] = merged

        # ---------- 3.2 演练模式：渲染「将发的正文」（只落结果，不投递） ----------
        # dry_run 的唯一用途就是「核对无误后再关掉」，所以正文必须看得见 ——
        # 否则只能靠真建一单来核对，违背演练的初衷（Fiber 当年也是这么过来的）。
        if CTX.dry_run:
            for rk, info in dry_root_info.items():
                if len(out["dry_run_preview"]) >= SAMPLE_LIMIT:
                    break
                _cells = group_cells.get(rk) or []
                out["dry_run_preview"].append({
                    "alarm_key": rk,
                    "site_id": info["site_id"], "site_name": info["site_name"],
                    "cells": _cells, "group_size": info.get("group_size"),
                    "text": build_message(CTX, info["alarm"], info["site_id"],
                                          info["site_name"], "", dry_run=True,
                                          cells=_cells,
                                          site_note=info.get("site_note") or "",
                                          notes=[info.get("corr_note") or ""]),
                })
            if out["dry_run_preview"]:
                logger.info("[5G] DRY-RUN 将发通报 %d 条，首条正文：\n%s",
                            len(dry_root_info), out["dry_run_preview"][0]["text"])

        # ---------- 4. WhatsApp 通报 ----------
        for p in pending_success:
            gkey = p.get("group_key") or p["alarm_key"]
            cells = group_cells.get(gkey, [])
            messages.append({
                "tt_no": p["tt_no"] or p["alarm_key"],
                "text": build_message(CTX, p["alarm"], p["site_id"], p["site_name"],
                                      p["tt_no"], dry_run=False,
                                      cells=cells,
                                      site_note=p.get("site_note") or "",
                                      notes=[p.get("corr_note") or ""]),
            })
        for p in pending_manual:
            messages.append({
                "tt_no": p["alarm_key"],
                "text": build_manual_message(CTX, p["alarm"], p["reason"],
                                             hint_lines=p.get("hint")),
            })

        if messages:
            out["samples"] = [{"alarm_key": m["tt_no"], "text": m["text"][:200]}
                              for m in messages[:SAMPLE_LIMIT]]
            wa_notify.check_channel_before_dispatch(out, len(messages), 30)
            disp = dispatch(messages, CTX.groups)
            out["errors"].extend(disp.get("errors") or [])
            if not disp.get("ok"):
                out["warnings"].append(
                    f"WhatsApp 通报投递失败：{'; '.join(disp.get('errors') or [])}")
            else:
                rep = wait_for_job_result(disp.get("job_id"))
                out["errors"].extend(rep.get("errors") or [])
                confirmed_ok = rep.get("confirmed") and rep.get("ok")
                if confirmed_ok:
                    sent = {engine.s(x) for x in rep.get("sent") or []}
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    for p in pending_success:
                        if p["tt_no"] in sent:
                            store.upsert_record(conn, {"alarm_key": p["alarm_key"],
                                                       "send_status": "Y", "send_time": now_str})
                            out["notified"] += 1
                    for p in pending_manual:
                        if p["alarm_key"] in sent:
                            store.upsert_record(conn, {"alarm_key": p["alarm_key"],
                                                       "send_status": "Y", "send_time": now_str})
                            out["manual_notified"] += 1
                elif rep.get("timed_out"):
                    out["warnings"].append("WhatsApp 通报未在超时内获确认（不判失败，请人工核对群消息）")

        out["success"] = not out["errors"]
        out["message"] = (f"演练" if CTX.dry_run else f"派单 {out['assigned']} 单") + \
                         f"，跳过 {out['skipped']}，失败 {out['failed']}"
        return _finish()
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

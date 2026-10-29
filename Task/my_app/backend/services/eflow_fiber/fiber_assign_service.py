# -*- coding: utf-8 -*-
"""Fiber Break 告警自动派单 + WhatsApp 通报（每 5 分钟一轮，cron `3-59/5 * * * *`）。

## 业务口径（2026-10-26 立项）

**触发源**：实时告警（`eflow_assign_client.fetch_active_alarms`，直接查 eFlow，
不读本地镜像 —— 上游就是实时的，没有同步时延）。

**派单条件（全部满足）**：
  1. 告警码命中白名单（默认 `4758` Fiber Break，页面可配多个）；
  2. 告警未清除（实时告警接口本身只返回未清除的）；
  3. 告警**存续时长**落在 `[min_age_minutes, window_minutes]` 区间内
     （默认 **下界 15 分钟**、上界 180 分钟）：
       * **下界 15 分钟**（2026-10-27 业务口径「告警发生到选择超过 15 分钟，
         才要指派单子和发送 WhatsApp 消息」）—— **不是一升起就派**，
         要等满 15 分钟才派。留这段时间给短时闪断自然清除，避免建出无效 TT。
         配 0 = 恢复「一升起就派」。
       * 上界 180 分钟 —— 兼防上线瞬间把积压的历史未清除 fiber 告警一次性全派出去；
  4. 该告警**尚未派过单**（状态表 `eflow_fiber_assign_log` 无 Y/D 记录），
     且上游没有自带 TT（`ttid` 为空）；
  5. **同站点在同时间窗口内没有关联告警**（默认 `99933`，窗口默认 60 分钟）。
     这是需求的核心：站点已经因 99933 派过单时，fiber 告警不再重复派单。
     ⚠ 只有**确认命中**才跳过；站名写法对不上（无法判定）时按「无关联」
     **继续派单**（2026-10-27 业务要求：不能因为站名匹配不到就卡住派单），
     结果里写 `correlation_undetermined` 留痕可复核。

**不构成阻断的两个坑（都吃过）**：
  * 99933 站名对不上 → 见上，按「无关联」继续；
  * eFlow 侧 `ttstatus` 非 0（ME 未关联站点）→ **仍然尝试派单**，只是收缩重试预算，
    失败后通报人工（2026-10-27 业务要求：不能被 eFlow 侧数据问题挡住）。

**站点解析（关键，实测教训）**：Fiber（TRM/IPRAN）告警的 `site` 是 ME 名
（如 `6120HA_zardun_UPE128`）、`sitename` 为 `--`，eFlow 的 TT 引擎无法据此
建 TT。必须解析出**数字站点 ID + 站点名**再放进派单 payload，TT 才真正生成。
解析顺序见 `eflow_assign_client.resolve_site`：告警自带 `site_id`（纯数字）→
`site_name` 查 cmdb → 从 ME 名解析站点名查 cmdb。解析不出站点则跳过（不派无站点的单）。

**派单后**：回查告警的 `ttid`，确认 TT 真的建出来才记 'Y'（接口返回 `status:true`
不代表建成功，见 `eflow_assign_client` docstring）。确认后 WhatsApp 通报。

**演练模式**（`dry_run`，默认开）：只查+匹配+记录将要派的单（状态 'D'），
**不调用派单接口**。首次上线先看日志/结果确认无误，再在页面关掉 dry_run。

## 状态表

`eflow_fiber_assign_log`（见 `fiber_store.py`）：`assign_status`
（Y 成功 / N 失败 / S 跳过 / D 演练）、`tt_no`、`skip_reason`、`send_status`。

## 发送通道

WhatsApp 走 Baileys 推送进程（`wa_notify_service`），投递前查心跳，只有服务端
回执确认后才置 `send_status='Y'`。

## 与共用引擎的关系（2026-10-28）

判定口径（时间边界、关联三态、合并分组、重试回查、消息渲染）已抽到
`backend/services/eflow_assign/assign_engine.py`，与 5G 站点告警派单共用。
本模块只保留 Fiber 自己的差异：告警码、ME 名解析、消息抬头。
"""
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.database import get_raw_connection
from backend.services import wa_notify_service as wa_notify
from backend.services.eflow_assign import assign_engine as engine
from backend.services.eflow_assign import eflow_assign_client as client
from backend.services.eflow_assign.assign_config import norm_code
from backend.services.eflow_fiber import fiber_config as config_mod
from backend.services.eflow_fiber import fiber_store as store
from backend.services.wa_notify_service import dispatch, wait_for_job_result

logger = logging.getLogger("eflow_fiber_assign")

# ========== 配置（导入期一次算好；改页面后需 worker 重启） ==========
_CFG = config_mod.load_config()

# 派单重试（Fiber 派单时灵时不灵，必须重试到 TT 真建出为止）：
# 单轮最多尝试 ASSIGN_MAX_ATTEMPTS 次，每次之间等 ASSIGN_RETRY_DELAY 秒。
# 环境变量可调，默认 3 次 × 3s。
ASSIGN_MAX_ATTEMPTS = max(1, int(os.environ.get("FIBER_ASSIGN_MAX_ATTEMPTS", "3")))
ASSIGN_RETRY_DELAY = float(os.environ.get("FIBER_ASSIGN_RETRY_DELAY", "3"))

# 消息抬头（群里每条通报都带）
PUSH_TITLE = "Fiber Break Alarm TT Assign Notification"

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
    tag="Fiber",
    outage_label="the same fiber cut",
)

# ---- 兼容旧引用（单测与外部调用点读模块级常量） ----
ALARM_CODES = CTX.alarm_codes
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
SAMPLE_LIMIT = engine.SAMPLE_LIMIT

# 判定结论常量（单测按名字断言，见 tests/test_fiber_assign.py）
CORRELATION_HIT = engine.CORRELATION_HIT
CORRELATION_NONE = engine.CORRELATION_NONE
CORRELATION_UNDETERMINED = engine.CORRELATION_UNDETERMINED
DUE_YES = engine.DUE_YES
DUE_TOO_NEW = engine.DUE_TOO_NEW
DUE_TOO_OLD = engine.DUE_TOO_OLD
DUE_NO_CODE = engine.DUE_NO_CODE
DUE_NO_TIME = engine.DUE_NO_TIME


# ==========================================================
# 薄封装（保持既有调用点/单测的签名不变）
# ==========================================================
def due_verdict(alarm: Dict[str, Any], now_ms: int) -> Tuple[str, Optional[float]]:
    """派单判定（唯一真相源在共用引擎 `assign_engine.due_verdict`）。"""
    return engine.due_verdict(CTX, alarm, now_ms)


def is_due(alarm: Dict[str, Any], now_ms: int) -> bool:
    """告警码命中 + 存续时长落在 [最小存续时长, 触发窗口] 区间内。"""
    return engine.due_verdict(CTX, alarm, now_ms)[0] == engine.DUE_YES


def age_minutes(alarm: Dict[str, Any], now_ms: int) -> Optional[float]:
    """告警升起至今的分钟数；取不到升起时间返回 None。"""
    return engine.age_minutes(alarm, now_ms)


def upstream_tt(alarm: Dict[str, Any]) -> str:
    """告警上游（eFlow 自身派单规则）已带的 TT 编号；没有则返回空串。"""
    return engine.upstream_tt(alarm)


def is_already_handled(prev_status: str, dry_run: bool) -> bool:
    """状态表命中「已处理」的判定。"""
    return engine.is_already_handled(prev_status, dry_run)


def is_clean_ttstatus(ttstatus: Any) -> bool:
    """eFlow 侧 `ttstatus` 是否处于「正常可派」状态。"""
    return engine.is_clean_ttstatus(ttstatus)


def assign_attempt_budget(status_suspect: bool) -> Tuple[int, int]:
    """本轮派单预算 → (接口尝试次数, 每次回查次数)。"""
    return engine.assign_attempt_budget(CTX, status_suspect)


def correlation_verdict(alarm: Dict[str, Any], all_alarms: List[Dict[str, Any]]
                        ) -> Tuple[str, Optional[Dict[str, Any]], str]:
    """判定「同站同窗口是否已有关联告警」，返回 (结论, 命中告警, 说明)。"""
    return engine.correlation_verdict(CTX, alarm, all_alarms)


def find_correlated_alarm(alarm: Dict[str, Any], all_alarms: List[Dict[str, Any]],
                          now_ms: int = 0) -> Optional[Dict[str, Any]]:
    """兼容包装：只返回命中的关联告警（`none` / `undetermined` 都返回 None）。"""
    verdict, hit, _ = engine.correlation_verdict(CTX, alarm, all_alarms)
    return hit if verdict == engine.CORRELATION_HIT else None


def group_by_occurrence(alarms: List[Dict[str, Any]], window_ms: int
                        ) -> Dict[str, Dict[str, Any]]:
    """按升起时间把告警聚类成「同一次故障」组（合并派单的判据）。"""
    return engine.group_by_occurrence(alarms, window_ms)


def alarm_key_of(alarm: Dict[str, Any]) -> str:
    """告警唯一键：优先 `alarmkey`，回退 `id`。"""
    return engine.alarm_key_of(alarm)


def _alarm_site_keys(alarm: Dict[str, Any]) -> set:
    """关联判定用的站点键集合（数字站号 / 站点名）。"""
    return engine.alarm_site_keys(alarm)


def build_message(alarm: Dict[str, Any], site_id: str, site_name: str,
                  group_name: str, tt_no: str, dry_run: bool,
                  site_note: str = "",
                  notes: Optional[List[str]] = None,
                  impacted: Optional[List[Tuple[str, str]]] = None) -> str:
    """按需求格式渲染通报：TT Title = SITE ID_Site name_Alarm Code。

    ⚠ **群通报正文一律英文**（2026-10-27 如意要求「通报默认使用英文」）。
    故调用方传入的 `site_note` / `notes` 必须已是英文；中文只留在日志与状态表里。

    `impacted` 是**同一次光纤中断里被本 TT 一并覆盖的其它站点**（合并派单，
    2026-10-27）：`[(site_id, site_name), ...]`，已去重，**不含**本条自己的站点。
    非空时在正文追加一段，说明「这一单实际涵盖 N 个站点」，避免群里误以为
    只坏了这一个站。只有 1 个站点（没有合并）时调用方传空 → 正文保持原样。
    """
    ctx = engine.AssignContext(**{**CTX.__dict__, "assign_group": group_name})
    return engine.render_message(ctx, alarm, site_id, site_name, tt_no, dry_run,
                                  site_note=site_note, notes=notes, impacted=impacted)


def _age_text(minutes: float) -> str:
    """分钟数 → 人读的存续时长（`154d 10h` / `43h 12m` / `26m`）。"""
    mins = int(max(0, minutes))
    days, rem = divmod(mins, 1440)
    hours, mins2 = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins2}m"
    return f"{mins2}m"


def build_stale_message(items: List[Dict[str, Any]], window_minutes: int) -> str:
    """超窗（长期未清除）fiber 告警的**汇总**提醒（2026-10-28 业务要求）。

    ## 为什么需要

    `window_minutes` 上界（默认 180）会把「升起超过 N 分钟仍未清除」的告警直接
    排除出派单范围。设计初衷是防上线瞬间把积压告警一次性全派出去，但生产实况是：
    这类告警在 eFlow 侧**长期挂着不清除**（实测 Alarm 1764190014919 已 154 天），
    于是每轮都判 `too_old`，**永远轮不到派单**。

    自动派单不该给僵尸告警建 TT（会污染 TT 池），但也**绝不能静默吞掉** ——
    万一现场真断着，就等于永久漏派且无人知晓。故汇总成**一条**消息推群，
    由人工核对后决定是否手动派单。

    ## 为什么汇总成一条

    超窗告警往往一次好几条（实测 6 条）。逐条推会刷屏，且它们本质是同一类问题。
    汇总后一轮只发一条，且同一告警只提醒一次（调用方按状态表 `send_status` 抑制）。

    ⚠ 正文一律英文（与其它群通报一致，2026-10-27 如意要求）。
    """
    lines = [PUSH_TITLE, ""]
    lines.append("⚠ Stale Fiber Break alarms — NO TT created automatically")
    lines.append(f"{len(items)} uncleared alarm(s) have been active longer than the "
                 f"{window_minutes}-minute trigger window,")
    lines.append("so this task did NOT auto-assign them.")
    lines.append("Please verify on site and assign the TT manually if the fault is real.")
    lines.append("")
    for it in items:
        lines.append(f"  - Alarm {it.get('alarm_id') or '-'} | {it.get('site_label') or '-'} | "
                     f"raised {it.get('raised_txt') or '-'} | uncleared {it.get('age_txt') or '-'}")
    lines.append("")
    lines.append("Note: these alarms remain in the eFlow active list. They will NOT be "
                 "auto-assigned unless the trigger window is widened.")
    return "\n".join(lines)


def build_manual_message(alarm: Dict[str, Any], reason: str,
                         hint_lines: Optional[List[str]] = None) -> str:
    """自动派单失败时的「需人工处理」通报（2026-10-27 业务要求：不能静默漏派）。

    ⚠ **群通报正文一律英文**（2026-10-27 如意要求「通报默认使用英文」）：
    `reason` / `hint_lines` 必须由调用方传入英文；中文原因走 `last_error` 落状态表。
    """
    return engine.render_manual_message(CTX, alarm, reason, hint_lines=hint_lines)


def _verify_tt(alarm_key: str, alarm: Dict[str, Any], index: client.SiteIndex,
               max_tries: int = 3) -> str:
    """派单后回查该告警的 ttid，确认 TT 真的建出来。

    兼容包装：保留旧的 `index` 参数（历史签名），实际逻辑走共用引擎。
    """
    return engine.verify_tt(alarm_key, alarm, max_tries=max_tries)


# ==========================================================
# 主流程
# ==========================================================
def run_fiber_assign() -> Dict[str, Any]:
    """每 5 分钟执行：拉实时告警 → 匹配 → 关联判定 → 派单（或演练）→ 通报 → 落库。"""
    started = time.time()
    now_ms = int(time.time() * 1000)
    out: Dict[str, Any] = {
        "success": False, "dry_run": CTX.dry_run, "fetched": 0,
        "fiber_alarms": 0, "due": 0, "assigned": 0, "skipped": 0,
        "failed": 0, "notified": 0,
        # 还没到派单时机（存续时长 < min_age_minutes，默认 15 分钟）→ 本轮不派，
        # 等下一轮再看。分出来是为了让排障能区分「等一等」与「真有问题」。
        "waiting": 0, "waiting_samples": [],
        # 存续时长超过触发窗口（太老）→ 不派。
        "expired": 0, "expired_samples": [],
        # 超窗（长期未清除）告警已汇总提醒人工的条数（每条告警只提醒一次）
        "stale_notified": 0,
        # 关联判定「无法判定 → 按无关联继续派单」的计数与明细（可审计，2026-10-27）
        "correlation_undetermined": 0, "correlation_undetermined_samples": [],
        # eFlow 侧 ttstatus 非 0（ME 未关联站点）的条数 —— 不再阻断，只收缩重试预算
        "suspect_ttstatus": 0, "suspect_ttstatus_samples": [],
        # 自动派不了（站点解析失败 / ttstatus 异常）→ 群里通报「需人工处理」的计数
        "manual_notified": 0,
        # 同一次光纤中断合并派单：被组长的 TT 覆盖、未单独建单的告警条数
        "merged": 0,
        "group_window_minutes": CTX.group_window_minutes,
        "assign_group": CTX.assign_group, "alarm_codes": sorted(CTX.alarm_codes),
        "correlation_codes": sorted(CTX.correlation_codes),
        "groups": list(CTX.groups), "group_fallback": GROUPS_FALLBACK,
        "samples": [], "errors": [], "warnings": [], "elapsed_seconds": 0,
    }

    def _finish() -> Dict[str, Any]:
        out["elapsed_seconds"] = round(time.time() - started, 2)
        logger.info("[Fiber] 完成 dry_run=%s fetched=%s fiber=%s due=%s waiting=%s expired=%s "
                    "assigned=%s skipped=%s failed=%s notified=%s stale_notified=%s "
                    "corr_undet=%s suspect_ttstatus=%s merged=%s 用时%.2fs",
                    CTX.dry_run, out["fetched"], out["fiber_alarms"], out["due"],
                    out["waiting"], out["expired"],
                    out["assigned"], out["skipped"], out["failed"], out["notified"],
                    out.get("stale_notified", 0),
                    out["correlation_undetermined"], out["suspect_ttstatus"],
                    out.get("merged", 0),
                    out["elapsed_seconds"])
        # 超窗明细单独打一行：原来只有计数（expired=4），排障时看不出是哪几条、
        # 存续多久 —— 2026-10-28 查 Alarm 1764190014919 就卡在这里。
        if out.get("expired_samples"):
            logger.info("[Fiber] 超窗未派明细: %s",
                        "; ".join(
                            "id=%s age=%smin(%s)" % (
                                x.get("alarm_id") or "-", x.get("age_minutes"), x.get("reason"))
                            for x in out["expired_samples"]))
        return out

    # ---------- 1. 拉取实时告警 ----------
    try:
        all_alarms = client.fetch_active_alarms()
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"拉取实时告警失败: {type(e).__name__}: {e}")
        logger.exception("[Fiber] 拉取实时告警失败")
        return _finish()
    out["fetched"] = len(all_alarms)

    fiber_alarms = [a for a in all_alarms
                    if norm_code(engine.val(a.get("alarmcode"))) in CTX.alarm_codes]
    out["fiber_alarms"] = len(fiber_alarms)
    if not fiber_alarms:
        out["success"] = True
        out["message"] = "无 fiber 告警"
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
        keys = [engine.s(engine.val(a.get("alarmkey"))) or engine.s(engine.val(a.get("id")))
                for a in fiber_alarms]
        records = store.load_records(conn, keys)

        index = client.SiteIndex(fuzzy_enabled=CTX.site_fuzzy_enabled,
                                 fuzzy_threshold=CTX.site_fuzzy_threshold)
        messages: List[Dict[str, Any]] = []
        pending_success: List[Dict[str, Any]] = []
        # 自动派不了（站点解析失败 / ttstatus 异常）→ 需人工处理，同一告警只发一次
        pending_manual: List[Dict[str, Any]] = []
        # 超窗（长期未清除）→ 汇总提醒人工，同一告警只发一次（2026-10-28）
        pending_stale: List[Dict[str, Any]] = []

        # ---------- 3.1 同一次光纤中断的合并分组（2026-10-27） ----------
        # 一次光缆中断会让链路上多个站点同时告警 → 合并成**一个** TT，
        # 正文列出实际涵盖的站点（判据与理由见 `group_by_occurrence`）。
        group_map = engine.group_by_occurrence(fiber_alarms, CTX.group_window_ms)
        # 组长（组内升起最早）必须先处理，成员才能跟随它建出的 TT 号。
        fiber_alarms = sorted(
            fiber_alarms,
            key=lambda x: (engine.occur_ms(x) is None, engine.occur_ms(x) or 0,
                           engine.alarm_key_of(x)))
        # 组长 key → 该组建出的 TT 号（dry-run 时为空串，表示「演练已覆盖」）
        group_tt: Dict[str, str] = {}
        # 组长 key → 本组涵盖的站点 [(site_id, site_name), ...]（去重后）
        group_sites: Dict[str, List[Tuple[str, str]]] = {}
        # 合并掉的告警条数（被组长的 TT 覆盖、未单独派单）
        merged = 0

        for a in fiber_alarms:
            akey = engine.alarm_key_of(a)
            rec = records.get(akey) or {}
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            base = {
                "alarm_key": akey,
                "alarm_id": engine.s(engine.val(a.get("id"))),
                "alarm_code": norm_code(engine.val(a.get("alarmcode"))),
                "me_name": engine.s(engine.val(a.get("mename")) or engine.val(a.get("site"))),
                "occur_time": (datetime.fromtimestamp(engine.occur_ms(a) / 1000).strftime("%Y-%m-%d %H:%M:%S")
                               if engine.occur_ms(a) else None),
                "last_seen_time": now_str,
                "first_seen_time": rec.get("first_seen_time") or now_str,
            }

            # 已确认派单成功（Y）→ 永久跳过，避免对同一告警重复建 TT。
            # ⚠ 演练记录（D）**只在演练模式下**算「已处理」：一旦关掉 dry_run，
            #   之前演练过的告警必须重新走完整流程去真派单，否则它们会被永久跳过
            #   （2026-10-26 生产切换自查发现）。所以 D 只在 DRY_RUN 为真时跳过。
            prev = engine.s(rec.get("assign_status"))
            # 首次见到这条告警（状态表无历史状态）。
            # ⚠ 为什么需要：`warnings` 非空会让 `task_runner` 判「任务降级完成」并推**一条
            #   微信通知**。而「站点名近似匹配」「关联判定不了」「ttstatus 异常」这些是
            #   **告警级**的长期状态 —— 每轮都写 warnings 就等于每 5 分钟推一条微信。
            #   故 warnings 只报首次（人知道一次就够），后续轮次只留在 samples / 状态表里。
            first_sight = not prev
            if engine.is_already_handled(prev, CTX.dry_run):
                out["skipped"] += 1
                store.upsert_record(conn, base)
                continue

            # ⚠ 告警**上游已经带 TT** 时绝不能重复派单（2026-10-26 生产切换自查发现）。
            # 生产上 eFlow 自己的派单规则（assign_rule）会给部分 fiber 告警先建 TT，
            # 这些告警在我方状态表里没有记录，若只看状态表就会再派一次、建出重复单。
            # ttid 非空且不是占位值 → 视为已派单，登记 Y 跳过。
            upstream_tt_no = engine.upstream_tt(a)
            if upstream_tt_no:
                out["skipped"] += 1
                base.update({"assign_status": "Y", "tt_no": upstream_tt_no,
                             "skip_reason": "上游已存在 TT（eFlow 规则已派单），不重复派"})
                store.upsert_record(conn, base)
                out["samples"].append({"alarm_key": akey, "action": "skip_existing_tt",
                                       "tt_no": upstream_tt_no})
                logger.info("[Fiber] 跳过 %s：上游已有 TT %s", akey, upstream_tt_no)
                continue

            # 触发条件：告警码命中 + 存续时长落在 [最小存续时长, 触发窗口] 内。
            # ⚠ 分三种「不派」的原因分别计数，否则排障时分不清「还没到派单时机」
            #   和「太老已过期」—— 前者正常（等下轮），后者要查为何积压。
            #   判定口径见 `due_verdict`（唯一真相源），这里只做分桶。
            _verdict, _age = engine.due_verdict(CTX, a, now_ms)
            if _verdict == engine.DUE_TOO_NEW:
                # 还没到派单时机（默认等满 15 分钟）→ 本轮不派，下轮再看
                out["waiting"] += 1
                if len(out["waiting_samples"]) < SAMPLE_LIMIT:
                    out["waiting_samples"].append(
                        {"alarm_key": akey, "age_minutes": round(_age or 0, 1)})
                continue
            if _verdict in (engine.DUE_TOO_OLD, engine.DUE_NO_TIME):
                # 太老（超过触发窗口）或取不到升起时间 → 不派。
                # ⚠ **必须写状态表**：原实现只计数、不落库，导致「这条为什么没派单」
                #   在 `eflow_fiber_assign_log` 里**查无此人** —— 2026-10-28 排障时
                #   Alarm 1764190014919（存续 154 天）按 id / alarmkey 都查 0 行，
                #   只能翻 task_queue.result_json 才看得到。留痕后一眼可查。
                out["expired"] += 1
                if _verdict == engine.DUE_TOO_OLD:
                    reason = (f"超出触发窗口：已存续 {round(_age or 0)} 分钟，"
                              f"超过上界 {CTX.window_minutes} 分钟"
                              f"（告警长期未清除，不自动派单，已汇总提醒人工）")
                else:
                    reason = ("取不到告警升起时间（alarmraisedtime/servertime 均空），"
                              "无法判断存续时长")
                if len(out["expired_samples"]) < SAMPLE_LIMIT:
                    out["expired_samples"].append(
                        {"alarm_key": akey, "alarm_id": engine.s(engine.val(a.get("id"))),
                         "age_minutes": round(_age or 0, 1),
                         "reason": _verdict, "note": reason})
                # 解析站点：① 状态表留痕能看出是哪个站；② 汇总提醒里要认得出
                _st_trace: Dict[str, Any] = {}
                _st_sid, _st_sname = client.resolve_site(a, index, trace=_st_trace)
                if _st_sid:
                    base["site_id"] = _st_sid
                    base["site_name"] = _st_sname
                base.update({"assign_status": "S", "skip_reason": reason})
                store.upsert_record(conn, base)
                # 超窗告警 → 汇总提醒人工（同一告警只提醒一次，靠 send_status 抑制）。
                # 不写 warnings：那会触发微信通知，而群里已收到汇总，不必双通道打扰。
                if _verdict == engine.DUE_TOO_OLD and engine.s(rec.get("send_status")) != "Y":
                    _occ = engine.occur_ms(a)
                    pending_stale.append({
                        "alarm_key": akey,
                        "alarm_id": engine.s(engine.val(a.get("id"))),
                        "site_label": (f"{_st_sname} ({_st_sid})" if _st_sid
                                       else (base.get("me_name") or akey[:40])),
                        "raised_txt": (datetime.fromtimestamp(_occ / 1000)
                                       .strftime("%Y-%m-%d %H:%M") if _occ else "-"),
                        "age_txt": _age_text(_age or 0),
                    })
                continue
            if _verdict != engine.DUE_YES:
                # 告警码不命中白名单 → 不算本任务的告警，不计数
                continue

            # eFlow 侧 `ttstatus`：**提示信号，不是阻断条件**。
            # 2026-10-27 业务要求：不能被「ME 未关联站点」挡住 —— 该试还得试，
            # 试失败才通报人工。实测这类告警接口回 succeed 却不建 TT，故只用最小
            # 预算（见 `assign_attempt_budget`），避免每轮白烧 70 秒并反复刷群。
            tt_status = engine.s(engine.val(a.get("ttstatus")))
            status_suspect = not engine.is_clean_ttstatus(tt_status)
            if status_suspect:
                out["suspect_ttstatus"] += 1
                out["suspect_ttstatus_samples"].append(
                    {"alarm_key": akey, "ttstatus": tt_status})
                if first_sight:
                    out["warnings"].append(
                        f"{akey} eFlow 侧 ttstatus={tt_status}（ME 可能未关联站点），仍尝试派单")
                logger.warning("[Fiber] %s ttstatus=%s（ME 未关联站点），不阻断、仍尝试派单",
                               akey, tt_status)

            # 关联判定：同站同窗口已有 99933 → 跳过。
            # ⚠ 站点名对不上（fiber 的 ME 站名 vs 99933 的 cmdb 站名写法不同）时
            #   `correlation_verdict` 返回 undetermined：**按「没有关联」继续派单**
            #   （2026-10-27 业务要求：不能因为站名匹配不到就卡住派单），
            #   但写进 warnings / correlation_undetermined 留痕，事后可复核是否重复派单。
            corr_note_for_msg = ""
            verdict, corr, corr_note = engine.correlation_verdict(CTX, a, all_alarms)
            if verdict == engine.CORRELATION_HIT and corr is not None:
                reason = (f"同站点已有 {norm_code(engine.val(corr.get('alarmcode')))} 告警"
                          f"（id={engine.s(engine.val(corr.get('id')))}），不重复派单")
                out["skipped"] += 1
                base.update({"assign_status": "S", "skip_reason": reason})
                store.upsert_record(conn, base)
                out["samples"].append({"alarm_key": akey, "action": "skip", "reason": reason})
                logger.info("[Fiber] 跳过 %s：%s", akey, reason)
                continue
            if verdict == engine.CORRELATION_UNDETERMINED:
                out["correlation_undetermined"] += 1
                out["correlation_undetermined_samples"].append(
                    {"alarm_key": akey, "me_name": base.get("me_name"),
                     "site_keys": sorted(engine.alarm_site_keys(a)), "note": corr_note})
                if first_sight:
                    out["warnings"].append(
                        f"{akey} 关联判定无法完成（{corr_note}），按「无关联」继续派单")
                logger.warning("[Fiber] %s 关联判定无法完成：%s；按无关联继续派单",
                               akey, corr_note)
                # 通报里也写一句，群里能看到「这条是判定不了关联、按无关联派的」。
                # ⚠ 通报正文必须英文（corr_note 是中文，只留在 warnings/日志里），
                #   故这里用英文重述，并带上可核查的站点键。
                site_keys_txt = ", ".join(sorted(engine.alarm_site_keys(a))) or "-"
                corr_note_for_msg = ("99933 correlation could not be determined "
                                     f"(site keys: {site_keys_txt}) — "
                                     "assigned as no-correlation")

            out["due"] += 1

            # ---------- 合并派单：本条已被组长告警的 TT 覆盖 ----------
            # 组长（组内升起最早）在上一轮迭代里已经派单成功/演练覆盖，
            # 本条不再单独建单，只登记同一个 TT 号，让通报错开重复单。
            grp = group_map.get(akey) or {"root": akey, "members": [a]}
            root_key = grp["root"]
            if root_key != akey and root_key in group_tt:
                # 仍要解析站点：通报里要列出本组实际涵盖哪些站点
                _mtrace: Dict[str, Any] = {}
                m_site_id, m_site_name = client.resolve_site(a, index, trace=_mtrace)
                # 解析不出站点时用 ME 名兜底：通报里必须露出这条告警属于哪个站，
                # 否则群里只看到「涵盖 3 个站点」却数不出第三个是谁。
                if not m_site_name:
                    m_site_name = base.get("me_name") or akey
                label = f"{m_site_id}/{m_site_name}" if m_site_id else m_site_name
                bucket = group_sites.setdefault(root_key, [])
                if (m_site_id, m_site_name) not in bucket:
                    bucket.append((m_site_id, m_site_name))
                if m_site_id:
                    base["site_id"] = m_site_id
                    base["site_name"] = m_site_name
                base.update({
                    "assign_status": "D" if CTX.dry_run else "Y",
                    "tt_no": group_tt.get(root_key) or None,
                    "skip_reason": (f"同一次光纤中断，已合并到组长告警 {root_key} 的 TT"
                                    f"（本组共 {len(grp['members'])} 条告警）"),
                })
                store.upsert_record(conn, base)
                merged += 1
                out["samples"].append({"alarm_key": akey, "action": "merged_into_group",
                                       "root": root_key, "site": label})
                logger.info("[Fiber] %s 合并到组长 %s 的 TT（本组 %d 条告警），不单独派单",
                            akey, root_key, len(grp["members"]))
                continue

            # 站点解析（trace 留痕：近似匹配必须让人能一眼看出来）
            trace: Dict[str, Any] = {}
            site_id, site_name = client.resolve_site(a, index, trace=trace)
            if not site_id:
                tried = trace.get("tried") or []
                hint = f"；已尝试站名 {tried}" if tried else ""
                # 中文：进状态表 last_error / warnings / 日志
                reason = f"站点解析失败（site_id/site_name/ME 均无法映射到 cmdb 站点{hint}）"
                # 英文：进群通报（通报默认英文）
                tried_txt = f" (tried site names: {', '.join(map(str, tried))})" if tried else ""
                reason_en = ("site resolution failed — no numeric site ID matched in cmdb"
                             f"{tried_txt}")
                out["failed"] += 1
                base.update({"assign_status": "N", "last_error": reason})
                store.upsert_record(conn, base)
                if first_sight:
                    out["warnings"].append(f"{akey} 站点解析失败，未派单：{reason}")
                # 自动派不了，但不能静默：同一条只往群里通报一次（send_status 抑制），
                # 否则每 5 分钟刷一条同样的失败消息（2026-10-27 如意要求）。
                if engine.s(rec.get("send_status")) != "Y":
                    pending_manual.append({"alarm_key": akey, "alarm": a,
                                           "reason": reason_en})
                continue
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
                    out["warnings"].append(f"{akey} {fuzzy_note}")
                logger.warning("[Fiber] %s %s", akey, fuzzy_note)

            # 演练模式：只记录
            if CTX.dry_run:
                base.update({"assign_status": "D",
                             "skip_reason": "dry-run 演练模式，未真派单"
                                            + (f"（{fuzzy_note}）" if fuzzy_note else "")})
                store.upsert_record(conn, base)
                # 标记本组已覆盖：后续同组成员跟随本条，演练里也能看出会合并成几单
                group_tt.setdefault(root_key, "")
                if (site_id, site_name) not in group_sites.setdefault(root_key, []):
                    group_sites[root_key].append((site_id, site_name))
                out["samples"].append({"alarm_key": akey, "action": "dry_run",
                                       "site_id": site_id, "site_name": site_name,
                                       "site_matched_by": trace.get("matched_by"),
                                       "site_score": trace.get("score"),
                                       "group_size": len(grp["members"])})
                logger.info("[Fiber] DRY-RUN 将派单 %s site=%s/%s（匹配方式 %s，本组 %d 条告警）",
                            akey, site_id, site_name, trace.get("matched_by"),
                            len(grp["members"]))
                continue

            # 真派单。⚠ eFlow 的 Fiber 派单**时灵时不灵**（2026-10-26 实测：
            # 同一告警、同一 payload，有时建出 TT、有时接口回 success 却不建）。
            # 故不能「调一次算一次」，必须「调一次 → 回查 ttid → 没建出就重试」，
            # 正常状态最多 ASSIGN_MAX_ATTEMPTS 次。这是本任务能稳定出单的关键。
            # ttstatus 可疑时也照派（不阻断），只是预算收窄到 1 次 × 2 回查。
            max_attempts, verify_tries = engine.assign_attempt_budget(CTX, status_suspect)
            tt_no, last_err = engine.assign_with_retry(
                CTX, a, group, site_id, site_name, akey,
                max_attempts, verify_tries)

            if tt_no:
                base.update({"assign_status": "Y", "tt_no": tt_no,
                             "tt_proc_id": engine.s(engine.val(a.get("procid"))) or None})
                store.upsert_record(conn, base)
                out["assigned"] += 1
                # 本组组长已建出 TT → 同组其余告警跟随这个单号，不再单独建单
                group_tt[root_key] = tt_no
                if (site_id, site_name) not in group_sites.setdefault(root_key, []):
                    group_sites[root_key].append((site_id, site_name))
                pending_success.append({"alarm_key": akey, "alarm": a,
                                        "site_id": site_id, "site_name": site_name,
                                        "tt_no": tt_no,
                                        "group_key": root_key,
                                        "group_size": len(grp["members"]),
                                        "site_matched_by": trace.get("matched_by"),
                                        "site_note": fuzzy_note_en,
                                        "corr_note": corr_note_for_msg})
                logger.info("[Fiber] 派单成功 %s → TT %s（本组 %d 条告警）",
                            akey, tt_no, len(grp["members"]))
            else:
                # 重试预算用完仍未建出 TT：如实记失败（下一轮还会重试，因状态不是 Y）
                out["failed"] += 1
                reason = last_err
                reason_en = last_err
                if status_suspect:
                    # ttstatus 可疑 = eFlow 侧 ME 未关联站点（数据问题，不是 payload 问题）。
                    # 代码改不动它，只能让人去 eFlow 修 —— 故写清原因并通报一次。
                    reason = (f"eFlow 侧 ttstatus={tt_status}（ME 未关联站点），"
                              f"已尝试派单但未建出 TT：{last_err}")
                    reason_en = (f"eFlow ttstatus={tt_status} "
                                 f"(ME not bound to a site); assign was attempted "
                                 f"but no TT was created: {last_err}")
                base.update({"assign_status": "N", "last_error": reason})
                store.upsert_record(conn, base)
                if first_sight:
                    out["warnings"].append(
                        f"{akey} 派单失败（尝试 {max_attempts} 次）：{reason}")
                logger.warning("[Fiber] 派单失败 %s：%s", akey, reason)
                if status_suspect and engine.s(rec.get("send_status")) != "Y":
                    # 同一条只通报一次（send_status 抑制），否则每 5 分钟刷一条
                    pending_manual.append({
                        "alarm_key": akey, "alarm": a,
                        "reason": reason_en,
                        "hint": ["Note: this ME is not correctly bound to a site in eFlow",
                                 "      (site still holds the ME name, sitename is empty),",
                                 "      so eFlow will never create a TT for it.",
                                 "      Please bind the ME to a numeric site in eFlow,",
                                 "      or assign the TT manually. Once the binding is",
                                 "      fixed, this task retries automatically."],
                    })

        out["merged"] = merged

        # ---------- 4. WhatsApp 通报 ----------
        # ① 真派单成功的；② 自动派不了、需人工处理的（同一条只发一次）。
        for p in pending_success:
            # 合并派单：把本组涵盖的其它站点列进正文（排除本条自己的站点）
            gkey = p.get("group_key") or p["alarm_key"]
            others = [s for s in group_sites.get(gkey, [])
                      if s != (p["site_id"], p["site_name"])]
            messages.append({
                "tt_no": p["tt_no"] or p["alarm_key"],
                "text": build_message(p["alarm"], p["site_id"], p["site_name"],
                                      CTX.assign_group, p["tt_no"], dry_run=False,
                                      site_note=p.get("site_note") or "",
                                      notes=[p.get("corr_note") or ""],
                                      impacted=others or None),
            })
        for p in pending_manual:
            messages.append({
                "tt_no": p["alarm_key"],
                "text": build_manual_message(p["alarm"], p["reason"],
                                             hint_lines=p.get("hint")),
            })

        # ③ 超窗（长期未清除）告警的**汇总**提醒 —— 一轮只发一条，列出全部待提醒的告警。
        # 为什么不逐条：实测一次 6 条，逐条会刷屏；且它们本质是同一类问题（长期未清除），
        # 合并后人工一眼能看完。同一告警只提醒一次，靠状态表 send_status 抑制。
        STALE_MSG_KEY = "__STALE_SUMMARY__"
        if pending_stale:
            messages.append({
                "tt_no": STALE_MSG_KEY,
                "text": build_stale_message(pending_stale, CTX.window_minutes),
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
                    # 人工派单通报也标记已发，避免下一轮重复刷同一条
                    for p in pending_manual:
                        if p["alarm_key"] in sent:
                            store.upsert_record(conn, {"alarm_key": p["alarm_key"],
                                                       "send_status": "Y", "send_time": now_str})
                            out["manual_notified"] += 1
                    # 超窗汇总提醒：一条消息覆盖多条告警，确认送达后逐条标记已发
                    if pending_stale and STALE_MSG_KEY in sent:
                        for p in pending_stale:
                            store.upsert_record(conn, {"alarm_key": p["alarm_key"],
                                                       "send_status": "Y", "send_time": now_str})
                            out["stale_notified"] += 1
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

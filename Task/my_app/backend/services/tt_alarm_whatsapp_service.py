"""eFlow P1 告警 → WhatsApp 推送服务（触发制：realtime_alarm 触发 + 实时查单）。

## 业务口径（2026-10-05 机制切换，每 5 分钟运行一次）

**触发**：扫描 `realtime_alarm`（由 `eflow_active_alarm` 同步的实时告警表；
该任务注册表默认 `*/30`，2026-10-05 核定生产实际为 `*/5`），
挑出「带 TT + 告警升起时间在窗口内 + 告警码白名单」的告警（口径细节与
「为什么触发源不是 eflow_tt」见 `tt_alarm_trigger.py` 的模块 docstring）。

⚠️ **本任务的周期与相位以 `task_schedule_config` 为准，不是代码默认值**
（2026-10-05 定：本任务 `2-59/5`、上游 `eflow_active_alarm` 为 `*/5`，错开 2 分钟
起跑以保证每次读到的都是刚同步完的数据）。这里此前长期写着「生产已配置 `*/5`」
而库里其实是 `*/15` —— 改 cron 请用任务管理页，**改代码默认值对已存在的任务
完全无效**（`task_runner.py:330-345` 有专门的启动告警来暴露这种「以为改了其实
没生效」，2026-10-04 的 sp_online_sync 就栽在这里）。

**实时查单**：对触发单实时回 eFlow 拉取最新工单行（`fetch_tt_live_batch`，
一次分页遍历匹配全部目标单），拿到**当前**的 `ticket_severity` /
`last_modified_time` / `alarm_clear_time`，不受任何镜像同步周期约束。
实时查不到（单子太久没动、超出扫描窗口）时回退本地 `eflow_tt` 镜像 ——
对「一直没更新的停滞单」，镜像里的 last_modified 恰好是准确的。

**推送与重报**（20 分钟 = `RESEND_MINUTES`，页面可调）：

1. 首推 —— 单子首次触发（日志表无记录）即推；
2. 重报 —— 距**最近一次已知工单更新**达 20 分钟（停滞）**且**距上次成功
   发送达 20 分钟（冷却）→ 再次通报，消息头带
   `⚠️ REMINDER #N · open Xh Ym · no update for Zm` 横幅；
3. 不报 —— 工单 20 分钟内有更新（有人在处理）只刷新跟踪字段，不打扰群里；
   告警已清除（`alarm_clear_time` 非空，或告警从 realtime_alarm 消失）自然止损。

首推时延 ≈ realtime_alarm 同步周期（生产 */5）+ 本任务轮询（≤5 分钟），
平均 ~5 分钟、最坏 ~10 分钟，对比旧机制（eflow_tt 每小时 :22 才落库）的
45~75 分钟大幅缩短。

## 配置 / 告警码过滤 / 发送通道 / 状态落库

* 配置（触发窗口 / 重报间隔 / 级别 / 告警码白名单 / 群组）页面维护在
  Settings →「任务配置」，优先级与「留空」语义见 `tt_alarm_config.py`；
  本文件只在**导入期**接收结果，改页面后需等 worker 重启。`window_minutes`
  的含义已随机制切换变为**触发窗口**（alarmraisedtime 距今 N 分钟内才触发首推）。
* 告警码必须在 Python 侧过滤：`alarmcode`（realtime_alarm）与
  `eflow_tt.alarm_code` 同病，库里 `'99933'` / `'99933.0'` 多形态并存，
  SQL 判等必漏、CAST 又会在文本码上抛错 → 统一 `norm_alarm_code()` 后判等。
* 发送通道是 Baileys 推送进程（`whatsapp-kb-bot/src/notify.js`），切换理由见
  `wa_notify_service.py`；防护链路：投递前查心跳（`check_channel_before_dispatch`）、
  回报超时有上限（`WAIT_SECONDS`）、未确认发送经 `warnings` 走微信/邮件喊人。
* 状态落库见 `tt_alarm_store.py`：`send_status`（发没发过）/ `send_count`
  （发送几次）/ `last_known_update_time`（停滞时钟基准）/
  `last_alarm_seen_time`（告警仍在 realtime_alarm 的凭据，恢复通知的数据基础）。

## 模块拆分

本文件只保留**编排与决策**；触发扫描在 `tt_alarm_trigger.py`，单据来源合并
（实时查单/镜像兜底/三层合并）在 `tt_alarm_sources.py`，渲染纯函数在
`tt_alarm_message.py`，配置解析在 `tt_alarm_config.py`，发送通道在
`wa_notify_service.py`（Baileys），实时查单实现在 `eflow_data_mapper.py`。
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.database import get_raw_connection
from backend.services import tt_alarm_config as config_mod
from backend.services import tt_alarm_mail_body as mail_body
from backend.services import tt_alarm_mailer as mailer
from backend.services import tt_alarm_sources as sources
from backend.services import tt_alarm_store as store
from backend.services import tt_alarm_trigger as trigger
from backend.services import wa_notify_service as wa_notify
from backend.services.tt_alarm_config import DEFAULT_GROUPS, load_config
# 发送通道：Baileys 推送进程（whatsapp-kb-bot/src/notify.js）。
# 接口（dispatch / wait_for_job_result / WAIT_SECONDS）与旧扩展通道同名同形，
# 业务层只认这三个名字，通道细节全部封在 wa_notify_service 里。
from backend.services.wa_notify_service import (
    WAIT_SECONDS,
    dispatch,
    wait_for_job_result,
)
from backend.services.tt_alarm_message import (
    build_tt_message,
    dash as _dash,
    norm_alarm_code,
    reminder_banner,
    s as _s,
)
from backend.services.tt_alarm_render import (
    engine_available,
    render_message_ex,
    render_tt_analysis,
    render_with_reason,
)

logger = logging.getLogger("tt_alarm_whatsapp")

# ========== 配置（导入期一次算好；改页面后需 worker 重启） ==========
# 优先级 环境变量 > 配置文件 > 内置默认；读盘/归一化/「留空」语义都在 tt_alarm_config。
_CFG = load_config(norm_alarm_code)

WINDOW_MINUTES = _CFG["window_minutes"]    # 触发窗口（分钟）：alarmraisedtime 距今 N 分钟内才触发首推
RESEND_MINUTES = _CFG["resend_minutes"]    # 重报间隔（分钟）：停滞 ≥N 且冷却 ≥N 才重报
QUERY_LIMIT = _CFG["query_limit"]          # realtime_alarm 单轮扫描上限（防静默截断）
SEVERITIES = _CFG["severities"]            # 级别白名单；空集 = 不过滤（所有级别）
ALARM_CODES = _CFG["alarm_codes"]          # 告警码白名单；空集 = 不过滤（所有码）
GROUPS = _CFG["groups"]                    # 目标群组；留空时已回退到 DEFAULT_GROUPS
GROUPS_FALLBACK = _CFG["groups_fallback"]  # True = 正发往测试群，调用方须显式告警
DEFAULT_GROUPS = config_mod.DEFAULT_GROUPS
SAMPLE_LIMIT = 3                           # 结果里附带的消息样例上限
# 邮件通道开关（2026-10-06 新增）。True 时：每单首次通报确认发出后发一封邮件，
# 该单告警清除后再发一封结束汇总。收件人来自「Settings → 邮件收件人」
# 的 `tt_alarm_p1_email` 组（默认 dong.xinmin@zte.com.cn），**不写死在本模块**。
MAIL_ENABLED = _CFG["mail_enabled"]
# 分析引擎的输出语言。告警消息发给利比里亚现场团队，历史上群里用的是英文，
# 故默认 en（引擎支持 zh/en，见 whatsapp-kb-bot/scripts/tt-analyze.py:77）。
ANALYZE_LANG = os.environ.get("TT_ALERT_LANG", "en")
# 各项最终来源（env / file / default），供排障解释"为何页面值与实际不符"
CONFIG_SOURCES = {k: v for k, v in _CFG.items() if k.endswith("_from")}

LOG_TABLE = store.LOG_TABLE
LOG_TABLE_INDEX = store.LOG_TABLE_INDEX


def _parse_ts(val: Any) -> Optional[datetime]:
    """解析 eflow_tt / 日志表的时间文本（'YYYY-MM-DD HH:MM:SS'），失败返回 None。"""
    text = _s(val)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:len(fmt) + 4], fmt)
        except ValueError:
            continue
    return None


# ==========================================================
# 建表 / 日志表
# ==========================================================
def ensure_log_table(conn) -> None:
    """幂等建表 + 老表补跟踪列 + 建索引（双模：sqlite / PG）。实现见 tt_alarm_store。"""
    store.ensure_log_table(conn, LOG_TABLE)


def load_records(conn, tt_nos) -> Dict[str, Dict[str, Any]]:
    """批量读日志表（tt_no → 记录）。见 tt_alarm_store.load_records。"""
    return store.load_records(conn, tt_nos, LOG_TABLE)


# ==========================================================
# 邮件通道（2026-10-06 新增）
#
# 用户要求：发送 WhatsApp 的同时也发邮件，主题英文 "P1 TT Progress Notification"。
# 用户进一步明确两点时序：
#   * 邮件在 **WhatsApp 确认发出后** 才发（不是同时）——否则邮件说发了、群里没到；
#   * **每单第一次通报**发一封；该单 **结束（告警清除）** 再发一封汇总。
# 重报（20 分钟停滞再推）**不发**邮件。
#
# 幂等靠日志表两列（见 tt_alarm_store.MAIL_COLUMNS）：mail_notified_time /
# mail_summary_time，非空即"已发过"，永不重发。
# ==========================================================
def _mail_recipients() -> tuple:
    """从「Settings → 邮件收件人」取当前生效的 (to, cc)。读不到返回 (None, "")。"""
    try:
        from backend.services.email_recipient_store import get_email_recipients
        return get_email_recipients("tt_alarm_p1_email")
    except Exception as e:  # noqa: BLE001
        logger.warning("[TTAlert] 读邮件收件人失败: %s", e)
        return None, ""


def send_first_notification_mail(row: Dict[str, Any], wa_text: str) -> bool:
    """发「首次通报」邮件并在日志表置位。失败返回 False（调用方记 warnings）。

    **只在该单第一次推送确认发出后调用**（`reminder_no == 1`）。
    """
    tt_no = _s(row.get("tt_no"))
    if not MAIL_ENABLED:
        return False
    to, cc = _mail_recipients()
    if not _s(to):
        logger.info("[TTAlert] %s 首次通报邮件跳过：未配置收件人", tt_no)
        return False
    ok = mailer.send_mail(
        subject=mail_body.SUBJECT_NOTIFIED,
        body=mail_body.build_notified_body(row, wa_text),
        to=to, cc=cc, source="tt_alarm_notify")
    if ok:
        try:
            with get_raw_connection() as conn:
                store.mark_mail_sent(conn, tt_no, "notified", table=LOG_TABLE)
        except Exception as e:  # noqa: BLE001
            # 置位失败只影响幂等（下轮可能重发一次），不能因此判定发送失败
            logger.warning("[TTAlert] %s 置首次通报标记失败: %s", tt_no, e)
    return ok


def run_summary_mail_scan(out: Dict[str, Any]) -> None:
    """扫描「已发过通报且未发汇总」的单，对其中**已清除**的发结束汇总邮件。

    ⚠️ 必须走日志表而不是 `realtime_alarm`：告警清除后该单会从实时表消失
    （2026-10-06 实测 4 个已清除单在 realtime_alarm 里 0 命中），所以主循环
    的 `if cleared:` 分支几乎永不命中 —— 汇总若挂在那个分支上，一封都发不出去。
    本函数独立回 `eflow_tt` 查 `alarm_clear_time`，与告警是否还活跃无关。
    """
    if not MAIL_ENABLED:
        return
    to, cc = _mail_recipients()
    if not _s(to):
        return
    try:
        with get_raw_connection() as conn:
            pending = store.pending_summary_mail(conn, table=LOG_TABLE)
            if not pending:
                return
            # 批量查 eflow_tt：只要「已清除」的（alarm_clear_time 非空）
            cleared = sources.cleared_rows(conn, pending)
    except Exception as e:  # noqa: BLE001
        logger.warning("[TTAlert] 汇总扫描失败: %s", e)
        out["errors"].append(f"汇总邮件扫描失败: {type(e).__name__}: {e}")
        return

    sent_n, fail_n = 0, 0
    for tt_no, row in cleared.items():
        try:
            ok = mailer.send_mail(
                subject=mail_body.SUBJECT_SUMMARY,
                body=mail_body.build_summary_body(row, wa_text=None),
                to=to, cc=cc, source="tt_alarm_summary")
            if ok:
                sent_n += 1
                with get_raw_connection() as conn:
                    store.mark_mail_sent(conn, tt_no, "summary", table=LOG_TABLE)
            else:
                fail_n += 1
        except Exception as e:  # noqa: BLE001
            fail_n += 1
            logger.warning("[TTAlert] %s 汇总邮件异常: %s", tt_no, e)
    if sent_n or fail_n:
        out["mail_summary_sent"] = sent_n
        out["mail_summary_failed"] = fail_n
        if fail_n:
            out["warnings"].append(
                f"{fail_n} 单的结束汇总邮件发送失败（WhatsApp 推送不受影响）")


# ==========================================================
# 发送决策（纯函数，便于单测）
# ==========================================================
def severity_passes(severity: str, severities: Optional[set] = None) -> bool:
    """级别是否通过白名单。`severities` 空集 = 不过滤（推送所有级别）。

    ⚠️ 必须显式判 `if not allowed` —— 写成 `sev not in SEVERITIES` 时，空集会让
    **每一单**都被丢掉（`x in set()` 恒为 False），结果是"留空 = 一单都不发"，
    与页面标注的"留空=所有级别"完全相反。这个坑 2026-09-28 真实发生过。
    """
    allowed = SEVERITIES if severities is None else severities
    if not allowed:
        return True
    return _s(severity).upper() in allowed


def decide_push(record: Optional[Dict[str, Any]], now: datetime,
                last_modified_dt: Optional[datetime] = None,
                resend_minutes: Optional[int] = None) -> "tuple[bool, str]":
    """判定该单本轮是否发送。返回 (是否发送, 原因)。

    语义（N = RESEND_MINUTES，默认 20 分钟）：
      * 无记录（首次触发）→ 发（first）；
      * 距「最近一次已知工单更新」≥ N（停滞）且距上次成功发送 ≥ N（冷却）→ 发
        （stalled）—— 「20 分钟没有更新就再次通报」；
      * 工单 N 分钟内有更新 → 不发（recent-update）：有人在处理，别刷屏；
      * 冷却期内 → 不发（cooldown）；
      * 更新时间完全不可知 → 退化为纯冷却节流（stale-unknown-update），
        绝不因数据缺失静默停推。

    「最近一次已知工单更新」的优先级：实时查单结果（`last_modified_dt`）>
    记录里的 `last_known_update_time`。更新时间不可知时以
    `last_send_time`（从未成功则 `first_seen_time`）做纯时间节流，
    失败重试也走同一条路。
    """
    minutes = RESEND_MINUTES if resend_minutes is None else int(resend_minutes)
    if not record:
        return True, "first"
    update_dt = last_modified_dt or _parse_ts(record.get("last_known_update_time"))
    send_dt = (_parse_ts(record.get("last_send_time"))
               or _parse_ts(record.get("first_seen_time")))
    if update_dt is None:
        if send_dt is None or (now - send_dt) >= timedelta(minutes=minutes):
            return True, "stale-unknown-update"
        return False, "cooldown"
    stalled = (now - update_dt) >= timedelta(minutes=minutes)
    cooled = send_dt is None or (now - send_dt) >= timedelta(minutes=minutes)
    if stalled and cooled:
        return True, "stalled"
    if not cooled:
        return False, "cooldown"
    return False, "recent-update"


# ==========================================================
# 状态落库
# ==========================================================
def record_result(row: Dict[str, Any], ok: bool, error: str = "",
                  existing: Optional[Dict[str, Any]] = None,
                  tracking: Optional[Dict[str, Any]] = None) -> None:
    """写入/更新一条发送记录（send_status / send_count / 跟踪列）。

    成功：`send_status='Y'`、`send_count`+1、`last_send_time=now`。
    失败：`send_status='N'`、`send_count` **不变**、`last_error` 记原因。
    见 tt_alarm_store.record_result。
    """
    with get_raw_connection() as conn:
        ensure_log_table(conn)
        store.record_result(conn, row, ok, error, existing, LOG_TABLE,
                            tracking=tracking)


def refresh_tracking(tt_no: str, tracking: Dict[str, Any]) -> bool:
    """只刷新跟踪列（不触碰 send_* 字段），记录不存在时不创建。见 tt_alarm_store。"""
    with get_raw_connection() as conn:
        ensure_log_table(conn)
        return store.refresh_tracking(conn, tt_no, tracking, LOG_TABLE)


# ==========================================================
# 任务入口
# ==========================================================
def run_tt_alarm_whatsapp_alert() -> Dict[str, Any]:
    """每 5 分钟执行：触发扫描 → 实时查单 → 决策 → 渲染 → 投递 → 回报 → 落库。

    返回结构化结果，供任务管理页展示。**零触发是成功**（`sent=0`），不是失败。
    """
    started = time.time()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    out: Dict[str, Any] = {
        "success": False, "candidates": 0, "due": 0, "dispatched": 0,
        "groups": list(GROUPS), "group_fallback": GROUPS_FALLBACK,
        "job_id": None, "samples": [], "errors": [], "elapsed_seconds": 0,
        "degraded": 0, "cleared": 0,
        "skipped_cooldown": 0, "skipped_recent_update": 0,
        "dropped_severity": 0, "dropped_unknown_severity": 0,
        # 与 task_runner 约定的**降级告警**通道（`task_runner.py:545-565`）：
        # 任务本身 success=True，但这里报出"主链路成功、旁路失败"的事项，
        # 由 task_runner 汇总成一条微信/邮件通知。用于「告警没发出去」这类
        # 不该被 success=True 掩盖的情况。
        "warnings": [],
    }

    def _finish() -> Dict[str, Any]:
        out["elapsed_seconds"] = round(time.time() - started, 2)
        logger.info("[TTAlert] 完成 success=%s candidates=%s due=%s dispatched=%s 用时 %.2fs",
                    out["success"], out["candidates"], out["due"], out["dispatched"],
                    out["elapsed_seconds"])
        return out

    try:
        # 群组为空时会回退到默认测试群（见 DEFAULT_GROUPS）。这里显式告警：
        # 生产 P1 告警发进 test123 是"发出去了但没人看"，比不发更隐蔽，
        # 必须在任务结果与日志里都能一眼看到。
        if GROUPS_FALLBACK:
            warn = (f"未配置 WhatsApp 群组，已回退到测试群 {DEFAULT_GROUPS} —— "
                    f"真实告警不会到达值班群！请在「设置 → 任务配置 → "
                    f"eFlow P1 Alarm WhatsApp Push」填写群组名")
            out["errors"].append(warn)
            logger.warning("[TTAlert] %s", warn)

        # 建表**必须无条件执行**：正常情况下每轮触发的多为 0，
        # 若把建表放进「有候选单」分支，日志表将永远建不出来。
        with get_raw_connection() as conn:
            ensure_log_table(conn)

        # ---------- 1. 触发扫描（realtime_alarm） ----------
        rows, meta = trigger.fetch_triggered_tts(now, WINDOW_MINUTES, ALARM_CODES,
                                                 QUERY_LIMIT)
        out["candidates"] = len(rows)
        out["window_since"] = meta["window_since"]
        if not meta.get("table_exists"):
            raise RuntimeError("realtime_alarm 表不存在或缺少 tt_id/alarmraisedtime 列"
                               "（eflow_active_alarm 未同步？）")
        if meta.get("truncated"):
            out["errors"].append(f"触发扫描达到采样上限 {QUERY_LIMIT}，结果可能被截断")
        lag = meta.get("sync_lag_seconds")
        # 阈值随 eflow_active_alarm 实际调度自适应（任务配置页改 cron 即生效），
        # meta 缺键时退回静态兜底 —— 只防老快照，正常路径不会走。
        stale_at = int(meta.get("sync_stale_threshold_seconds") or trigger.SYNC_STALE_SECONDS)
        if lag is not None and lag > stale_at:
            warn = (f"realtime_alarm 已 {int(lag // 60)} 分钟未同步"
                    f"（阈值 {stale_at // 60} 分钟），"
                    f"新 P1 告警可能触发不了 —— 请检查 eflow_active_alarm 任务")
            out["warnings"].append(warn)
            logger.warning("[TTAlert] %s", warn)

        if not rows:
            out["success"] = True
            out["message"] = f"触发窗口 {meta['window_since']} 起无带 TT 的白名单告警"
            # ⚠️ 早退也必须跑汇总扫描：没有新告警的轮次恰恰是最常发生的情况，
            # 而"某单已清除该发汇总了"与"本轮有没有新告警"完全无关。漏了这句，
            # 汇总就只在有告警的轮次才可能发出（且那些轮次多半没有已清除的单）。
            run_summary_mail_scan(out)
            return _finish()

        tt_nos = [r["tt_no"] for r in rows]
        with get_raw_connection() as conn:
            records = load_records(conn, tt_nos)

        # ---------- 2. 实时查单（一次分页遍历匹配全部） + 镜像兜底 ----------
        live_rows = sources.live_tt_rows(tt_nos)
        out["live_hits"] = len(live_rows)
        missed = [t for t in tt_nos if t not in live_rows]
        with get_raw_connection() as conn:
            mirrors = sources.mirror_rows(conn, missed) if missed else {}
        if missed and not mirrors:
            logger.warning("[TTAlert] %s 单实时与镜像均未命中，按未知处理", len(missed))

        # ---------- 3. 逐单决策 ----------
        due: List[Dict[str, Any]] = []
        tracking_updates: List[tuple] = []   # (tt_no, tracking) —— 本轮不发送也要记录
        for trig in rows:
            tt_no = trig["tt_no"]
            rec = records.get(tt_no)
            live = live_rows.get(tt_no)
            mir = mirrors.get(tt_no)

            # 级别过滤：新单必须有级别（实时/镜像至少一处拿得到）；
            # 在跟单的级别若被 eFlow 改掉（P1→P2），同样停止推送。
            sev = (_s((live or {}).get("ticket_severity"))
                   or _s((mir or {}).get("ticket_severity"))
                   or _s((rec or {}).get("ticket_severity")))
            if not sev:
                out["dropped_unknown_severity"] += 1
                logger.info("[TTAlert] %s 级别未知（实时/镜像均未命中），本轮不推", tt_no)
                continue
            if not severity_passes(sev):
                out["dropped_severity"] += 1
                continue

            # 已清除 → 止损：告警从 realtime_alarm 消失后候选自然不来，
            # 这里兜的是「告警还在表里但 TT 已被清除」的间隙窗口。
            cleared = (_s((live or {}).get("alarm_clear_time"))
                       or _s((mir or {}).get("alarm_clear_time")))
            # 本轮跟踪字段：无论发不发都记录（在跟单才真正落库）
            upd_dt = (_parse_ts((live or {}).get("last_modified_time"))
                      or _parse_ts((mir or {}).get("last_modified_time")))
            track = {"last_alarm_seen_time": now_str, "last_check_time": now_str}
            if upd_dt:
                track["last_known_update_time"] = upd_dt.strftime("%Y-%m-%d %H:%M:%S")
            if cleared:
                out["cleared"] += 1
                if rec:
                    tracking_updates.append((tt_no, track))
                continue

            send, reason = decide_push(rec, now, upd_dt)
            if not send:
                if reason == "cooldown":
                    out["skipped_cooldown"] += 1
                else:
                    out["skipped_recent_update"] += 1
                if rec:
                    tracking_updates.append((tt_no, track))
                continue

            merged = sources.merged_render_row(trig, mir, live)
            merged["_alarm_code_norm"] = trig.get("_alarm_code_norm")
            merged["ticket_severity"] = sev
            due.append({"row": merged, "reason": reason, "record": rec,
                        "tracking": track, "raised_dt": trig.get("_alarm_raised_dt")})

        # 本轮不发送的单：只刷新跟踪字段（不触碰 send_*，不创建新记录）
        for tt_no, track in tracking_updates:
            try:
                refresh_tracking(tt_no, track)
            except Exception:  # noqa: BLE001
                logger.warning("[TTAlert] 刷新跟踪字段异常 tt_no=%s", tt_no, exc_info=True)
        out["tracked_skipped"] = len(tracking_updates)

        # ⚠️ 必须把 due 的**真实条数**写回 out（2026-10-05 修复）：
        # `out["due"]` 此前从初始化后**再没有任何一处赋值**，于是任务结果里恒为 0，
        # 而实际发出 6 单 —— 出现过 `{"candidates":7,"due":0,"dispatched":6,"sent":6}`
        # 这种自相矛盾的结果，任务管理页永远显示「应发 0 单」，运维据此看不出
        # 本轮到底该发几单（调参与排障时尤其误导）。
        # 口径：due = 通过全部过滤、**本轮确实要投递**的单数（不含冷却/有更新被跳过的）。
        out["due"] = len(due)

        if not due:
            out["success"] = True
            out["message"] = (f"候选 {len(rows)} 单：重报冷却/有更新 {out['skipped_cooldown'] + out['skipped_recent_update']}"
                              f"，已清除 {out['cleared']}，级别不符 {out['dropped_severity']}，本轮不发")
            run_summary_mail_scan(out)
            return _finish()

        # ---------- 4. 渲染（重报带横幅） ----------
        messages = []
        degraded: List[str] = []
        for d in due:
            row = d["row"]
            rec = d["record"]
            text, deg_reason = render_message_ex(row, lang=ANALYZE_LANG)
            if deg_reason:
                degraded.append(f"{_s(row.get('tt_no'))}（{deg_reason}）")
            reminder_no = int((rec or {}).get("send_count") or 0) + 1
            if reminder_no > 1:
                # 横幅口径：open = 告警发生至今；no update = 距最近已知更新。
                # 更新时间拿不到时后者用 first_seen 兜底（停滞时长只会算多不会漏）。
                open_dt = (_parse_ts(row.get("alarm_occur_time"))
                           or d.get("raised_dt")
                           or _parse_ts((rec or {}).get("first_seen_time")))
                open_min = int((now - open_dt).total_seconds() // 60) if open_dt else 0
                upd_dt = (_parse_ts(row.get("last_modified_time"))
                          or _parse_ts((rec or {}).get("last_known_update_time")))
                stale_min = (int((now - upd_dt).total_seconds() // 60)
                             if upd_dt else RESEND_MINUTES)
                banner = reminder_banner(reminder_no, open_min, stale_min)
                text = f"{banner}\n{text}"
            # 回挂到 d：发送结果确认后要据此判断"是否首次通报"以及复用**同一份**
            # 文本发邮件（用户要求邮件与 WhatsApp 内容一致，不重新渲染）。
            d["reminder_no"] = reminder_no
            d["wa_text"] = text
            messages.append({"tt_no": _s(row.get("tt_no")), "text": text})

        out["samples"] = [{"tt_no": m["tt_no"], "text": m["text"]}
                          for m in messages[:SAMPLE_LIMIT]]
        out["degraded"] = len(degraded)
        if degraded:
            # 降级会让消息从 ~30 行缩成 7 行，且**不报错**（照样发得出去）。
            # 群里的人只会觉得「这次信息怎么这么少」，故必须在任务结果里显式暴露。
            out["errors"].append(
                f"以下 {len(degraded)} 单已降级为头部摘要（分析引擎不可用）："
                + "; ".join(degraded[:5])
                + ("…" if len(degraded) > 5 else ""))

        # ---------- 5. 投递前：先确认推送通道在线（实现与三态语义见 wa_notify_service） ----------
        wa_notify.check_channel_before_dispatch(out, len(due), RESEND_MINUTES)

        disp = dispatch(messages, GROUPS)
        out["job_id"] = disp.get("job_id")
        out["dispatched"] = disp.get("dispatched", 0)
        out["errors"].extend(disp.get("errors") or [])
        if not disp.get("ok"):
            # 作业都没投出去：全部记失败，绝不置 'Y'
            for d in due:
                tt_no = _s(d["row"].get("tt_no"))
                try:
                    record_result(d["row"], ok=False,
                                  error="; ".join(disp.get("errors") or ["投递失败"]),
                                  existing=records.get(tt_no), tracking=d["tracking"])
                except Exception:  # noqa: BLE001
                    logger.warning("[TTAlert] 写失败状态异常 tt_no=%s", tt_no,
                                   exc_info=True)
            # 作业连投都没投出去，同样属于"告警没发出去"，必须走降级告警通道。
            out["warnings"].append(
                f"本轮 {len(due)} 单 P1 告警**投递失败**，值班群没有收到："
                + "; ".join(str(e) for e in (disp.get("errors") or ["投递失败"]))
            )
            # 投递失败不影响"别的单该发汇总了"这件事，故仍要跑（且此时本轮的
            # 首次通报邮件一律不发 —— 因为一条都没确认发出）。
            run_summary_mail_scan(out)
            return _finish()

        # ---------- 6. 等推送进程回报：只有确认真实发出的单才置 'Y' ----------
        logger.info("[TTAlert] 作业 %s 已投递，等待推送进程回报（最长 %ds）…",
                    disp["job_id"], WAIT_SECONDS)
        rep = wait_for_job_result(disp["job_id"])
        out["confirmed"] = rep["confirmed"]
        out["timed_out"] = rep["timed_out"]
        out["sent_count"] = len(rep["sent"])
        out["errors"].extend(rep["errors"])

        sent_ids = {_s(x) for x in rep["sent"]}
        ok_count, fail_count = 0, 0
        # 首次通报邮件：只对"本轮确认发出且是该单第一次通报"的单发（用户要求）。
        # 必须在**确认发出之后**才发 —— 否则会出现邮件说发了、群里实际没到。
        mail_targets: List[tuple] = []
        for d in due:
            tt_no = _s(d["row"].get("tt_no"))
            try:
                if rep["confirmed"] and rep["ok"] and tt_no in sent_ids:
                    record_result(d["row"], ok=True, existing=records.get(tt_no),
                                  tracking=d["tracking"])
                    ok_count += 1
                    # reminder_no 见上方渲染段：== 1 即该单第一次通报
                    if int(d.get("reminder_no") or 1) <= 1:
                        mail_targets.append((d, tt_no))
                else:
                    err = ("; ".join(rep["errors"])
                           or ("推送进程未确认该单发送成功" if rep["confirmed"] else "未获推送进程回报"))
                    record_result(d["row"], ok=False, error=err,
                                  existing=records.get(tt_no), tracking=d["tracking"])
                    fail_count += 1
            except Exception:  # noqa: BLE001
                logger.warning("[TTAlert] 写发送状态异常 tt_no=%s", tt_no, exc_info=True)
                fail_count += 1

        out["sent"] = ok_count
        out["failed"] = fail_count
        out["success"] = bool(rep["confirmed"] and ok_count > 0)
        if out["success"]:
            out["message"] = f"已确认发送 {ok_count} 条（job={disp['job_id']}），状态已置 Y"
        elif rep["confirmed"]:
            out["message"] = f"推送进程已回报但无成功单（成功 0 / 失败 {fail_count}）"
        else:
            out["message"] = f"作业已投递但未获推送进程回报（{fail_count} 单保持未发送）"

        # **告警没发出去必须吵**（2026-10-01 事故）。
        # 走到这里说明本轮有 due 单却一条都没确认发出 —— 值班群实际收不到告警。
        # 且一旦通道恢复、下一轮候选变 0，任务立刻回到 success=True，
        # 「这几小时没发出去」就此埋掉。故显式产出 warnings 交给 task_runner 主动通知。
        if ok_count == 0 and fail_count > 0:
            out["warnings"].append(
                f"本轮 {fail_count} 单 P1 告警**均未确认发送**，值班群可能没收到"
                f"（job={disp.get('job_id')}；{out['message']}）。"
                f"请检查 whatsapp-kb-bot 推送进程（node src/notify.js --check 自检），"
                f"必要时 npm run relogin 重新扫码"
            )

        # ---------- 7. 邮件通道（WhatsApp 确认发出之后才发，见用户 2026-10-06 要求） ----------
        # 邮件失败**绝不**影响 out["success"] / send_status —— 它只是附加通道，
        # 只记 warnings 让人知道"群里发了但邮件没发出去"。
        if MAIL_ENABLED and mail_targets:
            mail_ok, mail_fail = 0, 0
            for d, tt_no in mail_targets:
                try:
                    if send_first_notification_mail(d["row"], d.get("wa_text") or ""):
                        mail_ok += 1
                    else:
                        mail_fail += 1
                except Exception as e:  # noqa: BLE001
                    mail_fail += 1
                    logger.warning("[TTAlert] %s 通报邮件异常: %s", tt_no, e)
            out["mail_notified_sent"] = mail_ok
            out["mail_notified_failed"] = mail_fail
            if mail_fail:
                out["warnings"].append(
                    f"{mail_fail} 单的首次通报邮件发送失败"
                    f"（WhatsApp 已有 {mail_ok} 单正常发出，不受影响）")

        # 结束汇总：独立扫描（不能挂在上面的活跃告警循环上，理由见 run_summary_mail_scan）
        run_summary_mail_scan(out)

    except Exception as e:  # noqa: BLE001
        logger.exception("[TTAlert] 任务执行失败")
        out["errors"].append(f"{type(e).__name__}: {e}")

    return _finish()


__all__ = [
    "GROUPS", "WINDOW_MINUTES", "RESEND_MINUTES", "QUERY_LIMIT", "SEVERITIES",
    "ALARM_CODES", "DEFAULT_GROUPS", "GROUPS_FALLBACK", "CONFIG_FILE", "CONFIG_SOURCES",
    "LOG_TABLE", "LOG_TABLE_INDEX", "SAMPLE_LIMIT", "ANALYZE_LANG",
    "ensure_log_table", "load_records", "decide_push", "severity_passes",
    "record_result", "refresh_tracking", "run_tt_alarm_whatsapp_alert",
    "norm_alarm_code", "_s", "_dash", "_parse_ts",
    "WAIT_SECONDS", "dispatch", "wait_for_job_result",
    "render_message_ex", "render_tt_analysis", "render_with_reason", "engine_available",
    "build_tt_message", "reminder_banner",
    "MAIL_ENABLED", "send_first_notification_mail", "run_summary_mail_scan",
]

# 配置文件路径的对外别名（配置模块拥有它；这里转发便于调用方只 import 本模块）
CONFIG_FILE = config_mod.CONFIG_FILE


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    print("群组:", GROUPS or "(未配置)")
    print("触发窗口(分钟):", WINDOW_MINUTES, " 重报间隔(分钟):", RESEND_MINUTES)
    print(json.dumps(run_tt_alarm_whatsapp_alert(), ensure_ascii=False, indent=2))

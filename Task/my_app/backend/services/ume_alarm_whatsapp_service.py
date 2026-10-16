# -*- coding: utf-8 -*-
"""ZTE UME 告警 → WhatsApp 推送（每分钟一轮）。

## 业务口径（2026-10-16 立项）

**触发源**：`ume_alarm_client.fetch_alarms()` 实时拉 `10.121.8.2` 的当前告警
（`/api/v2.0/fm/alarmsWithDetail`，客户端分页）。与 eFlow 那套「读本地
realtime_alarm 表」不同：本任务**直接查上游**，不落中间镜像表 —— 上游接口
就是实时的，没有同步时延问题，也就不需要镜像。

**筛选**：命中「**告警码 且 级别**」白名单才推。两个白名单**都留空 = 不过滤**
（见 `ume_alarm_config.py` 的留空语义表；写成 `in set()` 会让留空变"全丢"，
是已知坑）。比对在 Python 侧做：上游告警码多形态（`89069` / `3305119853`），
统一 `norm_alarm_code()` 后判等。

**推送与催报**：
  1. 首推 —— 某条告警首次出现（日志表无记录）→ 立即推；
  2. 催报 —— 告警未清除，距上次成功发送满 `resend_minutes` → 再报一次
     （带 `⚠️ REMINDER #N` 横幅）；
  3. 恢复通知 —— 上次见过的告警这次**不在列表里了** → 补发一条「已恢复」，
     并把 `cleared_time` / `recover_notified` 落库（幂等，至多一条）。

**首轮只登记不发送**（`bootstrap=True`，默认开）：第一次运行时当前存量告警
只写进日志表（标 `send_count=0`）不推送，从第二轮起只推**新出现**的告警，
避免上线瞬间把历史存量一次性刷进群。

去重 / 状态落 `ume_alarm_store`（表 `ume_alarm_whatsapp_log`）：`send_status`
（发没发过）/ `send_count`（发了几次）/ `last_send_time`（催报冷却基准）/
`cleared_time` + `recover_notified`（恢复通知幂等键）。

发送通道：`wa_notify_service`（Baileys 推送进程 `whatsapp-kb-bot/src/notify.js`），
投递前查心跳、回报超时有上限，**只有服务端回执确认后才置 `send_status='Y'`**。
"""
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.database import get_raw_connection
from backend.services import ume_alarm_client as client
from backend.services import ume_alarm_config as config_mod
from backend.services import ume_alarm_store as store
from backend.services.wa_notify_service import (
    WAIT_SECONDS,
    dispatch,
    wait_for_job_result,
)
from backend.services import wa_notify_service as wa_notify
from backend.services.ume_alarm_client import norm_alarm_code

logger = logging.getLogger("ume_alarm_whatsapp")

# ========== 配置（导入期一次算好；改页面后需 worker 重启） ==========
_CFG = config_mod.load_config(norm_alarm_code)

ALARM_CODES = _CFG["alarm_codes"]        # 告警码白名单；空集 = 不过滤
ALARM_LEVELS = _CFG["alarm_levels"]      # 级别白名单；空集 = 不过滤
GROUPS = _CFG["groups"]                  # 目标群组；留空时已回退 DEFAULT_GROUPS
GROUPS_FALLBACK = _CFG["groups_fallback"]  # True = 正发往测试群，须显式告警
RESEND_MINUTES = _CFG["resend_minutes"]  # 催报间隔（分钟）
BOOTSTRAP = _CFG["bootstrap"]            # 首轮只登记不发送
# 恢复通知的「新鲜度」窗口（分钟）：只有上一轮还在、这一轮消失的告警才报恢复。
# 取 2× 催报间隔，既覆盖「隔一轮才判定消失」的正常节奏，又能挡住改了筛选口径后
# 一次性把陈年 rows 全报成恢复。上限兜底 60 分钟，避免催报间隔被调很大时窗口失控。
RECOVER_STALE_MINUTES = max(RESEND_MINUTES * 2, 5)
DEFAULT_GROUPS = config_mod.DEFAULT_GROUPS
SAMPLE_LIMIT = 3                         # 结果里附带的消息样例上限

# 消息抬头：值班群每条消息都带，便于辨认来源。
PUSH_TITLE = "ZTE UME Alarm Notification"
RECOVER_TITLE = "ZTE UME Alarm Cleared"

# 各项最终来源（env / file / default），供排障解释"为何页面值与实际不符"
CONFIG_SOURCES = {k: v for k, v in _CFG.items() if k.endswith("_from")}


def _s(val: Any) -> str:
    return "" if val is None else str(val).strip()


def _parse_ts(val: Any) -> Optional[datetime]:
    """解析 `%Y-%m-%d %H:%M:%S` 文本，失败返回 None。"""
    text = _s(val)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:len(fmt) + 4], fmt)
        except ValueError:
            continue
    return None


def matches(alarm: Dict[str, Any]) -> bool:
    """是否命中「告警码 且 级别」白名单（空集 = 不过滤，**不是**全丢）。"""
    code = norm_alarm_code(alarm.get("alarm_code"))
    level = _s(alarm.get("level")).lower()
    if ALARM_CODES and code not in ALARM_CODES:
        return False
    if ALARM_LEVELS and level not in ALARM_LEVELS:
        return False
    return True


def _minutes_since(ts_text: Any, now: datetime) -> Optional[int]:
    dt = _parse_ts(ts_text)
    if dt is None:
        return None
    return int((now - dt).total_seconds() // 60)


def build_alarm_message(alarm: Dict[str, Any], reminder_no: int,
                        open_min: Optional[int] = None) -> str:
    """渲染一条告警推送文本（中英混排，与现场群既有习惯一致用英文标题）。"""
    lines = [PUSH_TITLE]
    if reminder_no > 1:
        span = f" · open {open_min}m" if open_min is not None else ""
        lines.append(f"⚠️ REMINDER #{reminder_no}{span}")
    lines.append(f"Code   : {_s(alarm.get('alarm_code'))}  [{_s(alarm.get('level'))}]")
    lines.append(f"Object : {_s(alarm.get('object')) or '-'}")
    desc = _s(alarm.get("description"))
    if desc:
        lines.append(f"Desc   : {desc}")
    occur = _s(alarm.get("occur_time"))
    if occur:
        lines.append(f"Time   : {occur}")
    loc = _s(alarm.get("location"))
    if loc:
        lines.append(f"Loc    : {loc}")
    return "\n".join(lines)


def build_recover_message(alarm_key: str, rec: Dict[str, Any]) -> str:
    """渲染一条「告警已恢复」通知。"""
    lines = [RECOVER_TITLE]
    lines.append(f"Code   : {_s(rec.get('alarm_code'))}  [{_s(rec.get('level'))}]")
    lines.append(f"Object : {_s(rec.get('object')) or '-'}")
    first = _s(rec.get("first_seen_time"))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if first:
        lines.append(f"From   : {first}")
    lines.append(f"To     : {now_str}")
    return "\n".join(lines)


def run_ume_alarm_whatsapp() -> Dict[str, Any]:
    """每分钟执行：拉告警 → 过滤 → 决策（首推/催报/恢复）→ 投递 → 回报 → 落库。

    返回结构化结果，供任务管理页展示。**零触发是成功**（`sent=0`）。
    """
    started = time.time()
    now = datetime.now()
    out: Dict[str, Any] = {
        "success": False, "fetched": 0, "matched": 0, "due": 0,
        "sent": 0, "failed": 0, "cleared_notified": 0,
        "bootstrap_mode": BOOTSTRAP, "bootstrap_registered": 0,
        "groups": list(GROUPS), "group_fallback": GROUPS_FALLBACK,
        "job_id": None, "samples": [], "errors": [], "warnings": [],
        "truncated": False, "elapsed_seconds": 0,
    }

    def _finish() -> Dict[str, Any]:
        out["elapsed_seconds"] = round(time.time() - started, 2)
        logger.info("[UMEAlarm] 完成 success=%s fetched=%s matched=%s due=%s sent=%s 用时 %.2fs",
                    out["success"], out["fetched"], out["matched"], out["due"],
                    out["sent"], out["elapsed_seconds"])
        return out

    try:
        # 群组回退到测试群必须显式告警（发进测试群比不发更隐蔽）
        if GROUPS_FALLBACK:
            warn = (f"未配置 WhatsApp 群组，已回退到测试群 {DEFAULT_GROUPS} —— "
                    f"真实告警不会到达值班群！请在「设置 → 任务配置 → "
                    f"ZTE UME Alarm WhatsApp Push」填写群组名")
            out["errors"].append(warn)
            logger.warning("[UMEAlarm] %s", warn)

        # 建表无条件执行（正常情况下候选多为 0，放进候选分支会永远建不出表）
        with get_raw_connection() as conn:
            store.ensure_log_table(conn)

        # ---------- 1. 拉当前告警 ----------
        fetched = client.fetch_alarms()
        alarms: List[Dict[str, Any]] = fetched["alarms"]
        out["fetched"] = fetched["fetched"]
        out["truncated"] = bool(fetched.get("truncated"))
        if out["truncated"]:
            out["errors"].append(
                f"上游告警数（{fetched['total']}）超过单轮翻页上限，结果被截断")

        # ---------- 2. 过滤（码 + 级别） ----------
        matched = [a for a in alarms if matches(a)]
        out["matched"] = len(matched)
        current_keys = {_s(a["alarm_id"]) for a in matched if _s(a["alarm_id"])}

        # ---------- 3. 读状态表，决策 ----------
        with get_raw_connection() as conn:
            records = store.load_records(conn, current_keys)
            open_records = store.load_open_records(conn)

            # 3a. 首轮只登记（bootstrap）：当前命中的告警全部入库、不发送
            if BOOTSTRAP and not records:
                registered = 0
                for a in matched:
                    key = _s(a["alarm_id"])
                    if not key:
                        continue
                    store.touch_seen(conn, a, existing=None)
                    # 打上 bootstrap 标记：下一轮起不再把它当成"新告警"补发首推
                    store.mark_bootstrapped(conn, key)
                    registered += 1
                out["bootstrap_registered"] = registered
                out["success"] = True
                out["message"] = (f"首轮只登记不发送：已登记 {registered} 条存量告警，"
                                  f"下一轮起只推新增")
                logger.info("[UMEAlarm] bootstrap：登记 %s 条存量告警（不发送）", registered)
                return _finish()

            # 3b. 挑出要发的：首推（无记录）或催报（超期未清除）
            due: List[Dict[str, Any]] = []
            reminder_no: Dict[str, int] = {}
            for a in matched:
                key = _s(a["alarm_id"])
                if not key:
                    continue
                rec = records.get(key)
                if rec is None:
                    # 新告警 → 首推
                    due.append(a)
                    reminder_no[key] = 1
                    continue
                # bootstrap 登记的历史存量：视为"已告知过"，不再补发首推
                # （这正是「首轮只登记不发送」的落地：存量不刷群，只有真新增才推）
                if _s(rec.get("bootstrapped")) == "Y":
                    continue
                if _s(rec.get("send_status")) != "Y":
                    # 有过登记但从未成功发出 → 本轮补发（首推语义）
                    due.append(a)
                    reminder_no[key] = 1
                    continue
                since = _minutes_since(rec.get("last_send_time"), now)
                if since is not None and since >= RESEND_MINUTES:
                    due.append(a)
                    reminder_no[key] = int(rec.get("send_count") or 0) + 1
            out["due"] = len(due)

            # 3c. 恢复通知：**曾经推送过**（send_status='Y'）、本轮不在列表里、
            #     且未发过恢复的告警 → 补发一条「已恢复」。
            #     ⚠️ 两个保守条件，缺一会误报恢复：
            #       · send_status=='Y' —— 只有真正推过群的才谈得上「恢复」；
            #         仅 bootstrap 登记过、从未发出的不报（群里从没见它出现过）。
            #       · last_seen_time 在 RECOVER_STALE_MINUTES 内 —— 只对「上一轮
            #         还在、这一轮消失」的报恢复。若某行是很久以前留下的（改了
            #         筛选口径、或上游长时间没这个告警），不该补一条陈年恢复通知。
            recover_msgs: List[Dict[str, Any]] = []
            for k, rec in open_records.items():
                if k in current_keys:
                    continue
                if _s(rec.get("send_status")) != "Y":
                    continue
                seen_min = _minutes_since(rec.get("last_seen_time"), now)
                if seen_min is None or seen_min > RECOVER_STALE_MINUTES:
                    continue
                recover_msgs.append({
                    "alarm_key": k,
                    "rec": rec,
                    "text": build_recover_message(k, rec),
                })
            if recover_msgs:
                out["recovered"] = len(recover_msgs)

            # ---------- 4. 渲染待发消息 ----------
            messages: List[Dict[str, Any]] = []
            for a in due:
                key = _s(a["alarm_id"])
                open_min = _minutes_since(a.get("occur_time"), now)
                text = build_alarm_message(a, reminder_no.get(key, 1), open_min)
                messages.append({"tt_no": key, "text": text})
            for r in recover_msgs:
                messages.append({"tt_no": r["alarm_key"], "text": r["text"]})

            out["samples"] = [{"alarm_id": m["tt_no"], "text": m["text"]}
                              for m in messages[:SAMPLE_LIMIT]]

            # 无消息：仅刷新"仍在列表"的登记，收工
            if not messages:
                for a in matched:
                    store.touch_seen(conn, a, existing=records.get(_s(a["alarm_id"])))
                out["success"] = True
                out["message"] = "无新增/催报/恢复"
                return _finish()

            # ---------- 5. 投递前查通道在线 ----------
            wa_notify.check_channel_before_dispatch(out, len(messages), RESEND_MINUTES)

            disp = dispatch(messages, GROUPS)
            out["job_id"] = disp.get("job_id")
            out["dispatched"] = disp.get("dispatched", 0)
            out["errors"].extend(disp.get("errors") or [])
            if not disp.get("ok"):
                err = "; ".join(disp.get("errors") or ["投递失败"])
                for a in due:
                    store.record_send(conn, a, ok=False, error=err,
                                      existing=records.get(_s(a["alarm_id"])))
                out["warnings"].append(
                    f"本轮 {len(messages)} 条告警**投递失败**，值班群没有收到：{err}")
                out["failed"] = len(due)
                out["success"] = True   # 任务本身跑通了，失败通过 warnings 暴露
                return _finish()

            # ---------- 6. 等回报：只有确认发出的才置 'Y' ----------
            logger.info("[UMEAlarm] 作业 %s 已投递，等待推送进程回报（最长 %ds）…",
                        disp["job_id"], WAIT_SECONDS)
            rep = wait_for_job_result(disp["job_id"])
            out["confirmed"] = rep["confirmed"]
            out["timed_out"] = rep["timed_out"]
            out["errors"].extend(rep["errors"])
            sent_ids = {_s(x) for x in rep["sent"]}

            ok_count = fail_count = 0
            confirmed_ok = rep["confirmed"] and rep["ok"]
            due_keys = set()
            for a in due:
                key = _s(a["alarm_id"])
                due_keys.add(key)
                if confirmed_ok and key in sent_ids:
                    store.record_send(conn, a, ok=True, existing=records.get(key))
                    ok_count += 1
                else:
                    err = ("; ".join(rep["errors"])
                           or ("推送进程未确认" if rep["confirmed"] else "未获推送进程回报"))
                    store.record_send(conn, a, ok=False, error=err,
                                      existing=records.get(key))
                    fail_count += 1

            # 恢复通知：确认发出后落幂等键
            rec_ok = rec_fail = 0
            for r in recover_msgs:
                key = r["alarm_key"]
                if confirmed_ok and key in sent_ids:
                    store.mark_recover_notified(conn, key)
                    rec_ok += 1
                else:
                    rec_fail += 1
            out["cleared_notified"] = rec_ok

            # ---------- 7. 刷新"仍在告警列表"的登记 ----------
            # ⚠️ 必须**跳过本轮已发送的告警**：`records` 是本轮发送**之前**的快照，
            # 用它 touch_seen 会把 record_send 刚写好的 send_status/send_count
            # 整行覆盖回发送前的值（2026-10-16 实测踩到：确认发出但库里仍是 N/0）。
            for a in matched:
                key = _s(a["alarm_id"])
                if key in current_keys and key not in due_keys:
                    store.touch_seen(conn, a, existing=records.get(key))

            out["sent"] = ok_count
            out["failed"] = fail_count
            if fail_count or rec_fail:
                out["warnings"].append(
                    f"{fail_count} 条告警/ {rec_fail} 条恢复通知未获推送进程确认，"
                    f"未置为已发送（下轮会重试）")
            out["success"] = True
            out["message"] = (f"发送 {ok_count} 条，催报 {max(0, len(due) - ok_count)} 条，"
                              f"恢复通知 {rec_ok} 条")
    except Exception as e:  # noqa: BLE001
        logger.exception("[UMEAlarm] 任务异常")
        out["errors"].append(f"任务异常：{e}")
        return _finish()

    return _finish()

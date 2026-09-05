# -*- coding: utf-8 -*-
"""
EWS 恢复后自动补发失败的邮件任务
================================

背景：Exchange/EWS 服务器降级（TCP 可达但 SOAP 超时）时，所有邮件任务会失败。
本模块作为一个**低频次定时任务**（默认每 20 分钟）运行：

  1. 探测 EWS 是否真正恢复（做一次真实鉴权 SOAP 调用，而非仅 TCP 连通性）；
  2. 仅当恢复时，扫描近 3 小时内因 EWS 超时失败、且尚未被正常调度补发的邮件任务；
  3. 自动重新执行这些邮件任务（复用既有 service 函数），并将补发结果记入
     task_execution_log（task_id = "email_recovery:<原任务>"）。

设计要点：
  - 只对「EWS 相关失败」补发，不对缺附件/数据源等失败误补发；
  - **报告时效窗口**：数据目录只保留最新一期报告文件，补发总是取最新文件。
    若失败记录已越过其自然周期（小时报告进入下一整点、8小时报告进入下一个
    8 小时块、日报超过 24 小时），补发会发出已被新一期覆盖的旧数据，故直接
    放弃补发；时间不敏感的日报类在 24 小时内仍可补发；
  - 若同一任务在失败之后已有成功记录，说明正常调度已补发，跳过（防重复）；
  - 单次最多补发 3 个，避免恢复瞬间风暴；
  - BUDGET_EXCEEDED（脱离主线程）类不补发，避免后台已成功时重复发送。
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timedelta

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
from pathlib import Path
from backend.database import get_raw_connection

logger = logging.getLogger("email_recovery")

MY_APP_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = MY_APP_DIR / "db" / "app.db"
RECOVERY_STATE_FILE = MY_APP_DIR / "TMP" / "email_recovery_state.json"

_MANAGED_VENV_PY = (
    r"C:\Users\ZTEEMS\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
)
_SCRIPT_DIR = MY_APP_DIR / "email_reports"

# 所有邮件类任务
# 2026-09-05 补录：sp_email_details / sp_online_report_send / packet_loss_email /
# ccn_free_rating_chart_email / battery_email / ipran_m6k_chart_email 此前不在名单，
# 落入 auto_retry（仅 2 次重试、15min 冷却），邮箱长时间降级时重试额度先于恢复耗尽，
# 恢复后无人补发。补录后 auto_retry 的排除集同步生效（避免双重补发）。
EMAIL_TASK_IDS = {
    "liberia_email_1h",
    "liberia_email_8h",
    "kpi_ms_contract",
    "kpi_ms_wo_sla",
    "kpi_sp_spareparts",
    "kpi_sp_consumables",
    "kpi_ran_availability",
    "sp_email_details",
    "sp_online_report_send",
    "packet_loss_email",
    "ccn_free_rating_chart_email",
    "battery_email",
    "ipran_m6k_chart_email",
}

# 仅当错误含这些关键字时才视为 EWS 失败（避免对非 EWS 失败误补发）
EWS_FAIL_KEYS = (
    "ReadTimeout",
    "ConnectionReset",
    "TransportError",
    "10054",
    "timed out",
    "Connection aborted",
    "RemoteDisconnected",
    "ConnectionError",
    "cls.resolve",
    "GetFolder",
    "SOAP",
    # 2026-08-25: 服务端限流（RateLimit/退避）与 CreateItem/SendItem SOAP 失败
    # 同属 EWS 服务端故障，恢复后应补发；缺这些关键字会导致日报类任务漏补发。
    "CreateItem",
    "CreateAttachment",
    "SendItem",
    "RateLimit",
    "back off",
    # 2026-09-05: .NET HttpWebRequest + NTLM 通道（kpi_email_report 等）的报错措辞
    # 与 exchangelib 完全不同——DNS 解析失败 / 连接失败此前全部匹配不上，
    # 导致 6 个失败任务被永久跳过、恢复后无人补发。
    "could not be resolved",                # The remote name could not be resolved: 'exchmail...'
    "Unable to connect to the remote server",
    "NameResolutionError",                  # exchangelib/urllib3 DNS 失败路径
    "getaddrinfo failed",
)

WINDOW_HOURS = 24  # 扫描窗口（小时）。实际补发还受各任务时效窗口约束
MAX_PER_RUN = 3   # 单次最多补发 N 个，避免服务刚恢复时任务风暴

# 失败链补发策略：EWS 未恢复期间，每 10 分钟仅做真实 SOAP 探测，绝不消耗次数。
# 首次探测恢复时，对时效内的未闭合失败链立即补发一次；只有该次业务邮件发送仍失败，
# 才按以下“相对第一次 recovery 实发”的节点继续尝试。连续失败不会重置失败链，
# 任一 success=true 会关闭整条链。
#
# hourly: 首发失败后 +10/+20/+30/+40 分钟（加上恢复后立即首发，共 5 次）。
# eight_hour: 首发失败后 +10/+30/+60/+90/+120/+180 分钟（共 7 次）。
# daily: 首发失败后 +10/+60/+90/+120/+150/+180 分钟，之后每小时一次至 +8h（共 12 次）。
RETRY_POLICIES = {
    "hourly": (10, 20, 30, 40),
    "eight_hour": (10, 30, 60, 90, 120, 180),
    "daily": (10, 60, 90, 120, 150, 180, 240, 300, 360, 420, 480),
}

TASK_POLICY = {
    "liberia_email_1h": "hourly",
    "liberia_email_8h": "eight_hour",
    **{task_id: "daily" for task_id in EMAIL_TASK_IDS
       if task_id not in {"liberia_email_1h", "liberia_email_8h"}},
}


def _parse_iso(ts: str):
    """解析 task_execution_log 中的 ISO 时间字符串，失败返回 None。"""
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _window_expired(task_id: str, failed_dt: datetime, now: datetime) -> bool:
    """判断失败记录是否已越过其报告时效窗口（True = 过期，不应补发）。

    数据目录只保留最新一期报告文件，补发必然发出"当前最新"那一份：
      - liberia_email_1h（每小时）：报告每小时被新一期覆盖。失败后一旦进入
        下一个整点小时，补发将发出新一期数据（而非失败那一期）→ 不补发。
      - liberia_email_8h（每8小时）：同理，进入下一个 8 小时块（按 00/08/16
        对齐）后不再补发。
      - 其余天粒度日报（MS KPI / WOs SLA / 备件 / 可用率）：时间不敏感，
        报告文件到次日才被新一期覆盖，24 小时内均可补发。
    """
    if task_id == "liberia_email_1h":
        hour_end = failed_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return now >= hour_end
    if task_id == "liberia_email_8h":
        block_start = failed_dt.replace(
            hour=(failed_dt.hour // 8) * 8, minute=0, second=0, microsecond=0
        )
        return now >= block_start + timedelta(hours=8)
    # 天粒度/时间不敏感报告：24 小时内可补发
    return now >= failed_dt + timedelta(hours=WINDOW_HOURS)


def _load_state() -> dict:
    """读取恢复状态，兼容旧版 {execution_id: timestamp} 文件。"""
    try:
        if RECOVERY_STATE_FILE.exists():
            raw = json.loads(RECOVERY_STATE_FILE.read_text(encoding="utf-8"))
            # 旧版以失败日志 id 为键且值为 float；历史补发已完成，不迁入新失败链。
            return raw if isinstance(raw, dict) else {}
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _load_state: exception swallowed", exc_info=True)
    return {}


def _chain_key(task_id: str, first_failed_at: str) -> str:
    """失败链唯一键：上次成功后的首次失败时刻，不依赖每次失败新产生的日志 id。"""
    return f"chain:{task_id}:{first_failed_at}"


def _chain_state(state: dict, task_id: str, first_failed_at: str) -> dict:
    """取得失败链状态；旧状态文件不存在该 key 时返回未尝试的初始状态。"""
    value = state.get(_chain_key(task_id, first_failed_at))
    return value if isinstance(value, dict) else {"attempts": 0}


def _due_attempt(first_recovery_at: datetime | None, attempts: int, policy_name: str,
                 now: datetime) -> tuple[bool, str, str | None]:
    """判断失败链是否到达下一次补发节点。

    EWS 首次恢复时 first_recovery_at 为空，立即允许第 1 次补发。之后仅当业务邮件补发
    实际失败才增加 attempts；后续节点以第一次 recovery 实发时间为基准，确保 EWS 降级
    期间的探测不会提前耗尽邮件重发预算。
    """
    delays = RETRY_POLICIES[policy_name]
    if attempts == 0 or first_recovery_at is None:
        return True, f"EWS 恢复后立即第 1/{len(delays) + 1} 次补发", now.isoformat(timespec="seconds")
    if attempts > len(delays):
        return False, f"{policy_name} 补发计划已耗尽 ({len(delays) + 1} 次)", None
    due_at = first_recovery_at + timedelta(minutes=delays[attempts - 1])
    next_at = due_at.isoformat(timespec="seconds")
    if now < due_at:
        return False, f"未到第 {attempts + 1} 次补发时间", next_at
    return True, f"第 {attempts + 1}/{len(delays) + 1} 次补发", next_at


def _save_state(state: dict):
    try:
        RECOVERY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        RECOVERY_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning("保存补发状态失败: %s", e)


def probe_ews_reachable() -> bool:
    """探测 EWS 是否真正恢复：做一次真实鉴权 SOAP 调用（访问 inbox 触发 GetFolder）。

    仅 TCP 通不代表 SOAP 通（已知降级状态），所以必须发起真实 SOAP。
    返回 True = 服务端可用。探测超时/异常均视为不可用。
    """
    probe = (
        "import sys; sys.path.insert(0, r'%s');"
        "from owa_mail_1hour_TT_Report import get_account;"
        "a = get_account(); _ = a.inbox.total_count; print('EWS_OK')" % _SCRIPT_DIR
    )
    # 必须用 .total_count 强制一次真实 SOAP 往返（GetFolder）：
    # Account/inbox 均为惰性构造，直接访问不发起网络请求，会造成"已恢复"假阳性。
    try:
        r = subprocess.run(
            [_MANAGED_VENV_PY, "-c", probe],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, cwd=str(MY_APP_DIR),
            creationflags=_SUBPROCESS_FLAGS,
        )
        ok = r.returncode == 0 and "EWS_OK" in r.stdout
        if not ok:
            logger.info("EWS 探测: 仍不可用 (rc=%s): %s", r.returncode, (r.stderr or r.stdout)[-300:])
        return ok
    except subprocess.TimeoutExpired:
        logger.info("EWS 探测: 超时 120s（服务端仍降级）")
        return False
    except Exception as e:
        logger.warning("EWS 探测异常: %s", e)
        return False


def _log_recovery(orig_task_id: str, success: bool, detail: str, started_iso: str, elapsed: float,
                  chain_first_failed_at: str, attempt: int, policy_name: str):
    """记录补发结果：同时写入原 task_id（Run History 可见）和 email_recovery: 前缀（分类统计）。"""
    try:
        from backend.database import get_raw_connection
        conn = get_raw_connection(str(DB_PATH), timeout=30)
        # 1) 写入原 task_id，trigger_type=recovery —— 让 Run History 能看到补发成功
        _task_name_map = {
            "liberia_email_1h": "Liberia 1H Report Email",
            "liberia_email_8h": "Liberia 8H Report Email",
            "kpi_ms_contract": "MS Contract KPIs Daily Report",
            "kpi_ms_wo_sla": "MS WO SLA Daily Report",
            "kpi_sp_spareparts": "SpareParts Report Email",
            "kpi_sp_consumables": "Comsumables Report Email",
            "kpi_ran_availability": "MS Network Availability Daily Report",
            "sp_email_details": "SP Spare Parts Details Report Email",
            "sp_online_report_send": "SP Online Open Tickets Report Send",
            "packet_loss_email": "Packet Loss Daily Report Email",
            "ccn_free_rating_chart_email": "CNN Free Rating Chart Email",
            "battery_email": "Battery KPI Email",
            "ipran_m6k_chart_email": "IP RAN M6K-FW Chart Email",
        }
        orig_name = _task_name_map.get(orig_task_id, orig_task_id)
        conn.execute(
            """INSERT INTO task_execution_log
               (task_id, task_name, category, trigger_type, success, started_at, completed_at, elapsed_seconds, error, result_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                orig_task_id,
                f"[Recovery] {orig_name}",
                "email_recovery",
                "recovery",
                1 if success else 0,
                started_iso,
                datetime.now().isoformat(timespec="seconds"),
                round(elapsed, 2),
                None if success else detail[:2000],
                json.dumps({
                    "recovery": True,
                    "orig_task_id": orig_task_id,
                    "detail": detail[:1500],
                    "policy": policy_name,
                    "chain_first_failed_at": chain_first_failed_at,
                    "attempt": attempt,
                    "max_attempts": len(RETRY_POLICIES[policy_name]) + 1,
                }, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("记录补发结果失败: %s", e)


def _run_task(orig_task_id: str) -> dict:
    """调用对应邮件任务的 service 函数重新发送。"""
    try:
        if orig_task_id == "liberia_email_1h":
            from backend.services.liberia_email_report import run_1h_report
            return run_1h_report()
        if orig_task_id == "liberia_email_8h":
            from backend.services.liberia_email_report import run_8h_report
            return run_8h_report()
        if orig_task_id == "kpi_ms_contract":
            from backend.services.kpi_email_report import run_ms_contract_kpi
            return run_ms_contract_kpi()
        if orig_task_id == "kpi_ms_wo_sla":
            from backend.services.kpi_email_report import run_ms_wo_sla
            return run_ms_wo_sla()
        if orig_task_id == "kpi_sp_spareparts":
            from backend.services.kpi_email_report import run_sp_spareparts
            return run_sp_spareparts()
        if orig_task_id == "kpi_sp_consumables":
            from backend.services.kpi_email_report import run_sp_consumables
            return run_sp_consumables()
        if orig_task_id == "kpi_ran_availability":
            from backend.services.kpi_email_report import run_ran_availability
            return run_ran_availability()
        # 2026-09-05 补录：与 EMAIL_TASK_IDS 新增项一一对应
        if orig_task_id == "sp_email_details":
            from backend.services.kpi_email_report import run_sp_details_email
            return run_sp_details_email()
        if orig_task_id == "sp_online_report_send":
            from backend.services.kpi_email_report import run_sp_online_report
            return run_sp_online_report()
        if orig_task_id == "packet_loss_email":
            from backend.services.kpi_email_report import run_packet_loss_email
            return run_packet_loss_email()
        if orig_task_id == "ccn_free_rating_chart_email":
            from backend.services.ccn_free_rating_chart_service import run_ccn_free_rating_chart_email
            return run_ccn_free_rating_chart_email()
        if orig_task_id == "battery_email":
            from backend.services.battary_kpi_fetch.battery_kpi_service import run_battery_email
            return run_battery_email()
        if orig_task_id == "ipran_m6k_chart_email":
            from backend.services.ipran_chart_service import run_ipran_m6k_chart_email
            return run_ipran_m6k_chart_email()
    except Exception as e:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _run_task: exception swallowed", exc_info=True)
        return {"success": False, "error": f"调用失败: {e}"}
    return {"success": False, "error": f"未知任务: {orig_task_id}"}


def recover_failed_emails() -> dict:
    """按任务失败链和时效策略扫描并补发邮件。"""
    if not probe_ews_reachable():
        return {"recovered": 0, "attempted": 0, "skipped": 0, "expired": 0, "reason": "ews_down"}

    now_dt = datetime.now()
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            since = (now_dt - timedelta(hours=WINDOW_HOURS)).isoformat(timespec="seconds")
            rows = conn.execute(
                """SELECT task_id, success, started_at, error
                   FROM task_execution_log
                   WHERE task_id IN (%s) AND started_at >= ?
                   ORDER BY task_id, started_at ASC, id ASC""" % ",".join("?" * len(EMAIL_TASK_IDS)),
                list(EMAIL_TASK_IDS) + [since],
            ).fetchall()
    except Exception as e:
        logger.error("查询失败邮件记录异常: %s", e)
        return {"recovered": 0, "attempted": 0, "skipped": 0, "expired": 0, "reason": f"db_error:{e}"}

    # 只保留每个 task_id 上一次成功之后的失败记录，形成唯一的未闭合失败链。
    chains: dict[str, list] = {}
    for task_id, success, started_at, error in rows:
        if success:
            chains[task_id] = []
        else:
            chains.setdefault(task_id, []).append((started_at, error or ""))

    state = _load_state()
    recovered = attempted = skipped = expired = 0
    details = []
    for task_id in sorted(chains):
        failures = chains[task_id]
        if not failures:
            continue
        latest_started_at, latest_error = failures[-1]
        # 只对当前未闭合链的最新失败仍属于邮箱/EWS的问题补发。
        if "BUDGET_EXCEEDED" in latest_error or not any(k in latest_error for k in EWS_FAIL_KEYS):
            skipped += 1
            continue
        ews_failures = [(ts, err) for ts, err in failures if any(k in err for k in EWS_FAIL_KEYS)]
        first_failed_at, _first_error = ews_failures[0]
        first_failed_dt = _parse_iso(first_failed_at)
        if first_failed_dt is None:
            skipped += 1
            continue
        policy_name = TASK_POLICY.get(task_id, "daily")
        chain_key = _chain_key(task_id, first_failed_at)
        chain = _chain_state(state, task_id, first_failed_at)

        if _window_expired(task_id, first_failed_dt, now_dt):
            expired += 1
            state[chain_key] = {**chain, "status": "expired", "updated_at": now_dt.isoformat(timespec="seconds")}
            continue

        first_recovery_at = _parse_iso(chain.get("first_recovery_at", ""))
        due, due_reason, next_retry_at = _due_attempt(
            first_recovery_at, int(chain.get("attempts", 0)), policy_name, now_dt
        )
        if not due:
            skipped += 1
            continue
        if attempted >= MAX_PER_RUN:
            details.append({"task_id": task_id, "success": False, "deferred": True, "detail": "单次补发上限已达"})
            continue

        attempt_no = int(chain.get("attempts", 0)) + 1
        started_iso = datetime.now().isoformat(timespec="seconds")
        # 此字段仅在 EWS 已真正恢复、即将首次调用业务发送函数时写入；EWS 探测失败
        # 会在本函数开头返回，故不会消耗任何邮件重发次数或创建该时间锚点。
        first_recovery_iso = chain.get("first_recovery_at") or started_iso
        first_recovery_dt = _parse_iso(first_recovery_iso) or now_dt
        t0 = time.time()
        res = _run_task(task_id)
        elapsed = time.time() - t0
        attempted += 1
        ok = bool(res.get("success"))
        state[chain_key] = {
            "attempts": attempt_no,
            "first_recovery_at": first_recovery_iso,
            "last_attempt_at": started_iso,
            "last_result": "success" if ok else "failed",
            "policy": policy_name,
            "next_retry_at": None if ok else _due_attempt(
                first_recovery_dt, attempt_no, policy_name, now_dt
            )[2],
        }
        detail = res.get("error") or res.get("message") or ""
        _log_recovery(task_id, ok, detail, started_iso, elapsed, first_failed_at, attempt_no, policy_name)
        if ok:
            recovered += 1
        details.append({
            "task_id": task_id,
            "success": ok,
            "policy": policy_name,
            "attempt": attempt_no,
            "detail": detail[:200],
            "next_retry_at": state[chain_key]["next_retry_at"],
        })

    _save_state(state)
    return {
        "recovered": recovered,
        "attempted": attempted,
        "skipped": skipped,
        "expired": expired,
        "reason": "ews_up",
        "details": details,
    }


def _already_recovered_since(task_id: str, failed_started_at: str) -> bool:
    """失败后是否已有成功记录（说明正常调度已经补发过）。"""
    try:
        import sqlite3
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            n = conn.execute(
                """SELECT COUNT(*) FROM task_execution_log
               WHERE task_id=? AND success=1 AND started_at > ?""",
                (task_id, failed_started_at),
            ).fetchone()[0]
            conn.close()
            return n > 0
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _already_recovered_since: exception swallowed", exc_info=True)
        return False


def run_email_recovery_task() -> dict:
    """供 Task Manager 直接调用的入口（返回 dict）。"""
    logger.info("开始 EWS 恢复后邮件补发检查")
    summary = recover_failed_emails()
    logger.info("邮件补发检查完成: %s", summary)
    # 将 reason 提到 message 字段，方便在 Run History 的 error 列直接看到 EWS 状态
    reason = summary.get("reason", "")
    if reason == "ews_down":
        summary["success"] = False
        summary["error"] = "EWS 仍不可用（探测失败），等待下次重试"
    elif reason == "ews_up" and summary.get("recovered", 0) == 0 and summary.get("attempted", 0) == 0:
        # EWS 可用但没有需要补发的邮件
        summary["message"] = "EWS 正常，无需补发"
    elif reason == "ews_up":
        summary["message"] = f"EWS 正常，补发 {summary.get('recovered', 0)}/{summary.get('attempted', 0)} 封"
    return summary


if __name__ == "__main__":
    import pprint
    pprint.pprint(run_email_recovery_task())
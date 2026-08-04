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
import time
from datetime import datetime, timedelta
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
EMAIL_TASK_IDS = {
    "liberia_email_1h",
    "liberia_email_8h",
    "kpi_ms_contract",
    "kpi_ms_wo_sla",
    "kpi_sp_spareparts",
    "kpi_sp_consumables",
    "kpi_ran_availability",
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
)

WINDOW_HOURS = 24         # 扫描窗口（小时）。实际补发还受各任务时效窗口约束
RETRY_COOLDOWN_MIN = 60   # 同一失败记录在 N 分钟内不重复补发
MAX_PER_RUN = 3           # 单次最多补发 N 个


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
    try:
        if RECOVERY_STATE_FILE.exists():
            return json.loads(RECOVERY_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _load_state: exception swallowed", exc_info=True)
        pass
    return {}


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
            timeout=45, cwd=str(MY_APP_DIR),
        )
        ok = r.returncode == 0 and "EWS_OK" in r.stdout
        if not ok:
            logger.info("EWS 探测: 仍不可用 (rc=%s): %s", r.returncode, (r.stderr or r.stdout)[-300:])
        return ok
    except subprocess.TimeoutExpired:
        logger.info("EWS 探测: 超时（服务端仍降级）")
        return False
    except Exception as e:
        logger.warning("EWS 探测异常: %s", e)
        return False


def _log_recovery(orig_task_id: str, success: bool, detail: str, started_iso: str, elapsed: float):
    """记录补发结果：同时写入原 task_id（Run History 可见）和 email_recovery: 前缀（分类统计）。"""
    try:
        conn = __import__("sqlite3").connect(str(DB_PATH), timeout=30)
        # 1) 写入原 task_id，trigger_type=recovery —— 让 Run History 能看到补发成功
        _task_name_map = {
            "liberia_email_1h": "Liberia 1H Report Email",
            "liberia_email_8h": "Liberia 8H Report Email",
            "kpi_ms_contract": "MS Contract KPIs Daily Report",
            "kpi_ms_wo_sla": "MS WO SLA Daily Report",
            "kpi_sp_spareparts": "SpareParts Report Email",
            "kpi_sp_consumables": "Comsumables Report Email",
            "kpi_ran_availability": "MS Network Availability Daily Report",
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
                json.dumps({"recovery": True, "orig_task_id": orig_task_id, "detail": detail[:1500]}, ensure_ascii=False),
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
    except Exception as e:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _run_task: exception swallowed", exc_info=True)
        return {"success": False, "error": f"调用失败: {e}"}
    return {"success": False, "error": f"未知任务: {orig_task_id}"}


def recover_failed_emails() -> dict:
    """扫描并补发失败邮件。返回汇总 dict。"""
    if not probe_ews_reachable():
        return {"recovered": 0, "attempted": 0, "skipped": 0, "expired": 0, "reason": "ews_down"}

    try:
        import sqlite3
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            since = (datetime.now() - timedelta(hours=WINDOW_HOURS)).isoformat(timespec="seconds")
            rows = conn.execute(
                """SELECT id, task_id, started_at, error
               FROM task_execution_log
               WHERE task_id IN (%s) AND success=0 AND started_at >= ?
               ORDER BY started_at DESC""" % ",".join("?" * len(EMAIL_TASK_IDS)),
                list(EMAIL_TASK_IDS) + [since],
            ).fetchall()
            conn.close()
    except Exception as e:
        logger.error("查询失败邮件记录异常: %s", e)
        return {"recovered": 0, "attempted": 0, "skipped": 0, "expired": 0, "reason": f"db_error:{e}"}

    state = _load_state()
    now_ts = time.time()
    now_dt = datetime.now()
    recovered = attempted = skipped = expired = 0
    details = []

    for exec_id, task_id, started_at, error in rows:
        err = (error or "")
        # 只补发 EWS 相关失败
        if not any(k in err for k in EWS_FAIL_KEYS):
            skipped += 1
            continue
        # 脱离主线程类不补发（防后台已成功时重复）
        if "BUDGET_EXCEEDED" in err:
            skipped += 1
            continue
        # 报告时效窗口：越过自然周期（小时报告进入下一整点等）则放弃补发，
        # 避免把已被新一期覆盖的数据当作失败那一期发出
        failed_dt = _parse_iso(started_at)
        if failed_dt is not None and _window_expired(task_id, failed_dt, now_dt):
            expired += 1
            state[str(exec_id)] = now_ts  # 标记已处理，后续轮次不再评估
            continue
        # 冷却期内的同一条失败不重复补发
        last = state.get(str(exec_id))
        if last and (now_ts - float(last)) < RETRY_COOLDOWN_MIN * 60:
            skipped += 1
            continue
        # 若该任务在失败后已有成功记录（正常调度已补发），跳过
        if _already_recovered_since(task_id, started_at):
            state[str(exec_id)] = now_ts
            skipped += 1
            continue

        if attempted >= MAX_PER_RUN:
            break

        started_iso = datetime.now().isoformat(timespec="seconds")
        t0 = time.time()
        res = _run_task(task_id)
        elapsed = time.time() - t0
        attempted += 1
        ok = bool(res.get("success"))
        state[str(exec_id)] = now_ts
        _log_recovery(task_id, ok, res.get("error") or res.get("message") or "", started_iso, elapsed)
        if ok:
            recovered += 1
        details.append({"task_id": task_id, "success": ok,
                        "detail": (res.get("error") or res.get("message") or "")[:200]})

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
    return summary


if __name__ == "__main__":
    import pprint
    pprint.pprint(run_email_recovery_task())
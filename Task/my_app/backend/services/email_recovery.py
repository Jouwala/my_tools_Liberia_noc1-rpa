# -*- coding: utf-8 -*-
"""
EWS 恢复后自动补发失败的邮件任务
================================

背景：Exchange/EWS 服务器降级（TCP 可达但 SOAP 超时）时，所有邮件任务会失败。
本模块作为一个**低频次定时任务**（每 10 分钟）运行：

  1. 探测 EWS 是否真正恢复（做一次真实鉴权 SOAP 调用，而非仅 TCP 连通性）；
  2. 仅当恢复时，扫描近 3 小时内因 EWS 超时失败、且尚未被正常调度补发的邮件任务；
  3. 自动重新执行这些邮件任务（复用既有 service 函数），并将补发结果记入
     task_execution_log（task_id = "email_recovery:<原任务>"）。

**探测与补发不受告警静默影响**：每一轮都照常发起真实 SOAP 探测；一旦探测成功，
本轮立即对时效内的未闭合失败链补发（见 _due_attempt 的"立即首发"分支），
不存在"因为静默而跳过补发"的代码路径。

告警语义（2026-09-15 引入方案 C；2026-09-18 增加三态判定与持续故障升级）：
  - EWS 不可用属于「依赖不可用」，不是本任务故障。此时任务返回 success=True，
    不再触发 task_runner 的失败告警：否则 EWS 长时间降级时，会因"每 10 分钟跑一次
    + 30 分钟告警冷却"而稳定每 30 分钟刷一封"任务执行失败"邮件。
  - **状态翻转时各通知一次**：刚进入故障通知一次、恢复通知一次；持续期间不刷屏。
    状态持久化在本模块 state 文件的 __ews_probe__ 键，跨进程/重启保持。
  - **故障分三类，不再混为一谈**（2026-09-18 教训：密码失效被记成"服务端降级"，
    告警文案还写着"连接 exchmail 超时…已静默"，把人引向"等服务端恢复"）：
      * ``server_down``   —— 服务端/网络不可用，只能等
      * ``auth_error``    —— 凭据被拒（401），**不会自行恢复，需人工改密码**
      * ``cred_mismatch`` —— 各发信模块解析出的凭据与 credential_store 不一致（代码缺陷）
    后两类使用明确的「需人工介入」文案。
  - **持续故障升级**：同一故障状态持续超过 ``EWS_ESCALATE_AFTER_HOURS``（默认 6h）后，
    每 ``EWS_ESCALATE_EVERY_HOURS``（默认 24h）再提醒一次。原方案只有翻转通知，
    导致 2026-09-15 21:54 之后整整 65 小时全静默、无人被再叫醒。
  - 本任务自身的异常（探测子进程异常、DB 读写异常等）仍照常按失败上报，不受影响。

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
import os
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
#
# ⚠️ 这份手写名单是**兜底**，不再是唯一来源：`_effective_email_task_ids()` 会用
# `email_task_coverage.discover_email_tasks()` 从任务注册表静态推导出「走 EWS 发信」
# 的任务并自动并入。手写名单漏登记已发生过三次（09-05 六个、09-15 sp_material_report、
# 09-18 fw_kpi_sync），故新增任务**无需**再改这里。
_EXPLICIT_EMAIL_TASK_IDS = frozenset({
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
    # 2026-09-15 补录：sp_material_report（SP Material Stock & Consumption Report Email）
    # 与上面 6 个同批漏补，其失败原因完全一致（returncode=3 + "Unable to connect to the
    # remote server"），却因不在名单而从未被补发 —— 2026-09-15 EWS 降级期间又漏了一次。
    "sp_material_report",
    # 2026-09-18 补录：fw_kpi_sync（run_fw_kpi_sync 经 owa_mail_report.py 发 FW KPI 日报）。
    # 它此前不在名单，落到 auto_retry（2 次 + 15min 冷却）。09-18 08:44/09:00 两次失败
    # 就是它，靠 auto_retry 第二次侥幸成功；邮箱长时间降级时额度必然先耗尽。
    "fw_kpi_sync",
})


def _effective_email_task_ids() -> frozenset:
    """手写名单 ∪ 静态推导。推导失败时安全退化为手写名单（绝不因此漏补发）。"""
    try:
        from backend.services.email_task_coverage import discover_email_tasks
        discovered = frozenset(discover_email_tasks())
    except Exception as exc:  # noqa: BLE001
        logger.warning("EWS 发信任务自动推导失败，回退手写名单: %s", exc)
        return _EXPLICIT_EMAIL_TASK_IDS
    extra = discovered - _EXPLICIT_EMAIL_TASK_IDS
    if extra:
        logger.info("EWS 发信任务自动推导补充 %d 个未登记任务: %s", len(extra), sorted(extra))
    return _EXPLICIT_EMAIL_TASK_IDS | discovered


EMAIL_TASK_IDS = _effective_email_task_ids()

# 明确**不可补发**的失败：补发会造成重复发送或毫无意义。判定优先级高于 EWS_FAIL_KEYS。
#
# 2026-09-18：`_run_script` 超时杀掉子进程时，错误串是
# ``"timeout: Command '[...]' timed out after 120 seconds"``，其中含 "timed out"，
# 而 "timed out" 在 EWS_FAIL_KEYS 里 → 被当成 EWS 失败 → 补发 → 同一封邮件重复发送
# （服务端可能已接收，只是响应慢）。这里显式排除。
NOT_RESENDABLE_KEYS = (
    "BUDGET_EXCEEDED",     # 已脱离主线程，后台仍在发送
    "timed out after",     # subprocess.TimeoutExpired：本地主动放弃，不代表服务端没收到
)

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


def is_ews_resendable(error: str) -> bool:
    """该失败是否属于 email_recovery 会**真正补发**的 EWS 发信失败。

    这是 auto_retry 与补发通道之间的**唯一判据**，两边必须共用，否则会出现两种事故：

    * **互相谦让**：auto_retry 因为任务在 `EMAIL_TASK_IDS` 里而跳过，补发通道又因为
      失败不是 EWS 类而跳过 —— 任务再没人重试。2026-09-18 就踩到了：`fw_kpi_sync`
      被登记进 `EMAIL_TASK_IDS` 后，它的远端 API 连接失败（`[WinError 10065]`）落进
      空档，而历史上正是 auto_retry 把它救回来的（09:00 失败 → 10:07 trig=auto_retry 成功）。
    * **互相争抢**：补发通道本来会补发，auto_retry 又重跑一遍 → 重复发送。

    `NOT_RESENDABLE_KEYS` 优先判定：`BUDGET_EXCEEDED`（后台仍在发）与子进程超时
    （`"timed out after N seconds"`）补发会造成重复发送，这两类应留给 auto_retry 重试。
    """
    err = error or ""
    if any(k in err for k in NOT_RESENDABLE_KEYS):
        return False
    return any(k in err for k in EWS_FAIL_KEYS)

WINDOW_HOURS = 24  # 扫描窗口（小时）。实际补发还受各任务时效窗口约束
MAX_PER_RUN = 3   # 单次最多补发 N 个，避免服务刚恢复时任务风暴

# EWS 探测子进程的重试预算（秒）与超时（秒）。
# 必须大于 email_reports/*.py 的 OWA_RETRY_MAX_WAIT 默认值(60)，否则服务端限流下发的
# 退避序列(10/20/40/80s)会在拿到真实结论前就触发 RateLimitError，把"限流"误判成"降级"。
# 240 可覆盖到 80s 那一档退避（累计 150s），超时留出余量。
_PROBE_RETRY_MAX_WAIT = 240
_PROBE_TIMEOUT = 300

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

# 补发队列优先级：时效越紧的越先补。
# MAX_PER_RUN=3 意味着每轮只有 3 个名额，若按字母序排（原实现），hourly 任务可能被排在
# 日报类之后、等上好几轮才轮到，而它的时效窗口只有 1 小时 —— 等排到就已经过期、永久丢失。
_POLICY_PRIORITY = {"hourly": 0, "eight_hour": 1, "daily": 2}


def _chain_order_key(task_id: str):
    """补发顺序：先按时效紧急度（hourly → eight_hour → daily），同档再按 task_id 稳定排序。"""
    return (_POLICY_PRIORITY.get(TASK_POLICY.get(task_id, "daily"), 9), task_id)


def _parse_iso(ts: str):
    """解析 task_execution_log 中的 ISO 时间字符串，失败返回 None。"""
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _window_expired(task_id: str, failed_dt: datetime, now: datetime) -> bool:
    """判断失败记录是否已越过其报告时效窗口（True = 过期，不应补发）。

    ``failed_dt`` 必须是**该失败链内最近一次「报告期」失败的时间**（见
    recover_failed_emails 里的 anchor_dt），而不是链首失败时间：
    补发取的是数据目录里"当前最新"那一份报告，对应的就是最近一个未发出的
    报告期。若拿链首失败做锚，EWS 长时间降级（如 1H 报告从 01:12 连挂到
    21:12）时链首早已越过窗口，整条链会被误判过期，连仍在时效内的最新一期
    也一并丢弃 → 恢复后永远补发不出来。

    数据目录只保留最新一期报告文件，补发必然发出"当前最新"那一份：
      - liberia_email_1h（每小时）：报告每小时被新一期覆盖。最近一次失败后
        一旦进入下一个整点小时，补发将发出新一期数据（而非失败那一期）→ 不补发。
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


# ========== EWS 状态跟踪 ==========
EWS_STATE_KEY = "__ews_probe__"

# 探测结果分类（由 email_reports/ews_probe.py 给出）
PROBE_OK = "ok"
PROBE_AUTH_ERROR = "auth_error"          # 凭据被拒（401）—— 需要人工改密码
PROBE_CRED_MISMATCH = "cred_mismatch"    # 各发送方解析出的凭据不一致 —— 代码缺陷
PROBE_SERVER_DOWN = "server_down"        # 服务端/网络不可用

# 「需要人工介入」类：不是"等等就好"，必须明确叫醒人
_ACTIONABLE_KINDS = (PROBE_AUTH_ERROR, PROBE_CRED_MISMATCH)

# 持续故障升级告警（2026-09-18 新增）。
# 原设计只有"状态翻转时通知一次"，配置类故障（密码失效）看起来就是 down，于是
# 2026-09-15 21:54 报过一次之后整整 65 小时全静默 —— 没人被再叫醒。现在：
# 同一故障状态持续超过 _ESCALATE_AFTER_HOURS 后，每 _ESCALATE_EVERY_HOURS 再提醒一次。
_ESCALATE_AFTER_HOURS = float(os.environ.get("EWS_ESCALATE_AFTER_HOURS", "6"))
_ESCALATE_EVERY_HOURS = float(os.environ.get("EWS_ESCALATE_EVERY_HOURS", "24"))


def _last_json_line(text: str):
    """取文本中最后一行可解析的 JSON 对象。"""
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except Exception:  # noqa: BLE001
                continue
    return None


def probe_ews_reachable() -> tuple[str, str]:
    """运行 ``email_reports/ews_probe.py``，返回 ``(kind, detail)``。

    kind ∈ {"ok", "auth_error", "cred_mismatch", "server_down"}。

    探测脚本本身**只读、不发信**，内部依次做：各发送方凭据一致性校验 →
    requests_ntlm 快速预检（401 立即定性，约 1s）→ 真实 SOAP 只读往返（GetFolder）。

    ⚠️ 关于 ``OWA_RETRY_MAX_WAIT``：exchangelib 会把**任何** HTTP 401 包装成
    ``ErrorServerBusy``，再按 ``RETRY_WAIT(=10)`` 起做**客户端**指数退避
    （10/20/40/80s）——这是 ``exchangelib/services/common.py`` 的行为，
    **不是"服务端下发的退避序列"**（本文件旧注释写错了）。仍显式抬高预算，是为了让
    真正的服务端限流也能跑到结论；而 401 现在由探测脚本的 NTLM 预检提前定性，
    不必再干等退避跑完（旧探测在 401 下要白等 300s）。
    """
    script = _SCRIPT_DIR / "ews_probe.py"
    if not script.is_file():
        return PROBE_SERVER_DOWN, f"探测脚本不存在: {script}"

    env = dict(os.environ)
    env["OWA_RETRY_MAX_WAIT"] = str(_PROBE_RETRY_MAX_WAIT)
    try:
        r = subprocess.run(
            [_MANAGED_VENV_PY, str(script)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=_PROBE_TIMEOUT, cwd=str(MY_APP_DIR), env=env,
            creationflags=_SUBPROCESS_FLAGS,
        )
    except subprocess.TimeoutExpired:
        logger.info("EWS 探测: 超时 %ss（服务端仍降级）", _PROBE_TIMEOUT)
        return PROBE_SERVER_DOWN, f"探测超时 {_PROBE_TIMEOUT}s"
    except Exception as e:  # noqa: BLE001
        logger.warning("EWS 探测异常: %s", e)
        return PROBE_SERVER_DOWN, f"探测异常: {e}"

    payload = _last_json_line(r.stdout)
    if payload is None:
        tail = (r.stderr or r.stdout or "")[-300:]
        logger.info("EWS 探测: 无结构化结果 (rc=%s): %s", r.returncode, tail)
        return PROBE_SERVER_DOWN, f"探测无结构化结果 (rc={r.returncode}): {tail}"

    kind = str(payload.get("kind") or PROBE_SERVER_DOWN)
    detail = str(payload.get("detail") or "")
    if kind == PROBE_OK:
        logger.info("EWS 探测: 正常 — %s", detail)
    elif kind in _ACTIONABLE_KINDS:
        logger.warning("EWS 探测: **需人工介入** [%s] — %s", kind, detail)
    else:
        logger.info("EWS 探测: 仍不可用 — %s", detail)
    return kind, detail


def _probe_and_track(state: dict, now: datetime) -> dict:
    """探测 EWS 并把结果写入 state。

    Returns dict:
        ok / kind / detail        本次探测结论
        transition                翻转事件，None 表示状态未变；取值：
                                  "recovered" / "went_down" / "went_auth_error" /
                                  "went_cred_mismatch" / "changed_fault"
        fault_count               同一故障状态连续出现次数（ok 时归零）
        since                     当前状态起始时刻
        escalate                  是否应发"持续故障"升级提醒

    **每轮都会真实发起探测**，不受任何静默逻辑影响；结果落定后才更新 state。
    """
    kind, detail = probe_ews_reachable()
    ok = kind == PROBE_OK
    now_iso = now.isoformat(timespec="seconds")

    prev = state.get(EWS_STATE_KEY)
    prev = prev if isinstance(prev, dict) else {}
    prev_status = prev.get("status")
    prev_kind = prev.get("kind")
    fault_count = int(prev.get("fault_count") or prev.get("down_count") or 0)

    if ok:
        transition = "recovered" if prev_status not in (None, "up") else None
        since = prev.get("since") if prev_status == "up" else now_iso
        fault_count = 0
    else:
        if prev_status == "up" or prev_status is None:
            transition = f"went_{kind}"
            since = now_iso
            fault_count = 1
        elif prev_kind != kind:
            # 故障类型变了（如 server_down → auth_error）也是重要信息，需要通知
            transition = "changed_fault"
            since = now_iso
            fault_count = 1
        else:
            transition = None
            since = prev.get("since") or now_iso
            fault_count += 1

    new_state = {
        "status": "up" if ok else "down",
        "kind": kind,
        "detail": detail[:400],
        "since": since,
        "last_probe_at": now_iso,
        "fault_count": fault_count,
        "down_count": fault_count,   # 兼容旧字段名（前端/历史状态文件）
    }

    # ---- 持续故障升级 ----
    escalate = False
    last_esc = _parse_iso(prev.get("last_escalation_at") or "")
    if not ok:
        fault_since = _parse_iso(since)
        if fault_since is not None:
            age_h = (now - fault_since).total_seconds() / 3600.0
            due_by_age = age_h >= _ESCALATE_AFTER_HOURS
            due_by_interval = (
                last_esc is None
                or (now - last_esc).total_seconds() / 3600.0 >= _ESCALATE_EVERY_HOURS
            )
            if due_by_age and due_by_interval:
                escalate = True
        if escalate:
            new_state["last_escalation_at"] = now_iso
        elif prev.get("last_escalation_at"):
            new_state["last_escalation_at"] = prev["last_escalation_at"]

    state[EWS_STATE_KEY] = new_state
    return {
        "ok": ok,
        "kind": kind,
        "detail": detail,
        "transition": transition,
        "fault_count": fault_count,
        "since": since,
        "escalate": escalate,
    }


def _notify_ews_state(kind: str, message: str, escalate: bool = False):
    """EWS 状态翻转 / 持续故障升级时推送通知（微信 + 126 邮箱）。

    复用 task_runner 的同一套通道，但标题按语义区分——避免把"依赖不可用/已恢复/
    凭据异常"一律包装成"任务执行失败"。翻转本身天然去重；持续故障由 escalate 触发，
    不会退化成每轮刷屏。通知失败只记日志，绝不影响本任务的执行结果。
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ok = kind == PROBE_OK
    if ok:
        head = "EWS 已恢复"
        subject = "[EWS 恢复] 邮件通道已恢复"
    elif kind in _ACTIONABLE_KINDS:
        head = "【需要人工处理】EWS 凭据异常"
        subject = "[EWS 凭据异常] 邮件通道不可用，需人工介入"
    elif escalate:
        head = "【持续故障】EWS 仍未恢复"
        subject = "[EWS 持续故障] 邮件通道长时间不可用"
    else:
        head = "EWS 探测失败（已进入降级静默）"
        subject = "[EWS 降级] 邮件通道不可用，已静默"

    try:
        from backend.services.weixin_notifier import send_weixin_message
        res = send_weixin_message(f"{head}\n时间：{ts}\n{message}")
        if not res.get("success"):
            logger.warning("EWS 状态通知发送失败: %s", res.get("error"))
    except Exception as e:  # noqa: BLE001
        logger.warning("EWS 状态通知异常: %s", e)

    try:
        from backend.services.email_notifier import send_ews_status_email
        send_ews_status_email(subject=subject, title=head, message=message, ts=ts, ok=ok)
    except Exception as e:  # noqa: BLE001
        logger.warning("EWS 状态邮件通知异常: %s", e)


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
            "sp_material_report": "SP Material Stock & Consumption Report Email",
            "packet_loss_email": "Packet Loss Daily Report Email",
            "ccn_free_rating_chart_email": "CNN Free Rating Chart Email",
            "battery_email": "Battery KPI Email",
            "ipran_m6k_chart_email": "IP RAN M6K-FW Chart Email",
            "fw_kpi_sync": "FW KPI Daily Report Email",
            "ume_in_osg_report": "Customer Service KPI + OSG Weekly Report Email",
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


# 补发分发表：task_id -> (模块路径, 函数名)。
# 2026-09-18 由长 if 链改为表：新增发信任务只需在此加一行，避免"登记了任务却忘了
# 加分发分支"（EMAIL_TASK_IDS 自动推导会纳入新任务，但分发必须显式声明）。
_TASK_DISPATCH = {
    "liberia_email_1h": ("backend.services.liberia_email_report", "run_1h_report"),
    "liberia_email_8h": ("backend.services.liberia_email_report", "run_8h_report"),
    "kpi_ms_contract": ("backend.services.kpi_email_report", "run_ms_contract_kpi"),
    "kpi_ms_wo_sla": ("backend.services.kpi_email_report", "run_ms_wo_sla"),
    "kpi_sp_spareparts": ("backend.services.kpi_email_report", "run_sp_spareparts"),
    "kpi_sp_consumables": ("backend.services.kpi_email_report", "run_sp_consumables"),
    "kpi_ran_availability": ("backend.services.kpi_email_report", "run_ran_availability"),
    "sp_email_details": ("backend.services.kpi_email_report", "run_sp_details_email"),
    # 2026-09-30 新增：SP 备件明细分文件邮件（5 份 xlsx 各自作附件发 NOC）。
    # 它的入口经 _run_script 调 owa_mail_report，故被 email_task_coverage 自动推导
    # 纳入 EMAIL_TASK_IDS；不在此登记会命中 _UNDISPATCHED_EMAIL_TASKS 自检告警，
    # 且邮箱降级后无法补发。
    "sp_details_files_email": ("backend.services.kpi_email_report", "run_sp_details_files_email"),
    "sp_online_report_send": ("backend.services.kpi_email_report", "run_sp_online_report"),
    "sp_material_report": ("backend.services.kpi_email_report", "run_sp_material_stock_consumption"),
    "packet_loss_email": ("backend.services.kpi_email_report", "run_packet_loss_email"),
    "ccn_free_rating_chart_email": (
        "backend.services.ccn_free_rating_chart_service", "run_ccn_free_rating_chart_email"),
    "battery_email": ("backend.services.battary_kpi_fetch.battery_kpi_service", "run_battery_email"),
    "ipran_m6k_chart_email": ("backend.services.ipran_chart_service", "run_ipran_m6k_chart_email"),
    # 2026-09-18 新增：FW KPI 日报（经 owa_mail_report.py 走 EWS）
    "fw_kpi_sync": ("backend.services.fw_kpi.fw_kpi_services", "run_fw_kpi_sync"),
    # 2026-09-18 新增：客户业务 KPI + OSG 周报邮件。
    # 这一条不是手写补录的 —— 是 email_task_coverage 的静态推导发现的**第 4 个**
    # 漏登记任务（前三个：09-05 六个、09-15 sp_material_report、09-18 fw_kpi_sync）。
    # 推导把它自动纳入 EMAIL_TASK_IDS，但补发分发必须在这里显式声明。
    "ume_in_osg_report": ("backend.services.ume_in.osg_report_task", "run_ume_in_osg_report"),
}


# 自检：推导/手写纳入 EMAIL_TASK_IDS 的任务必须有补发分发分支，否则 email_recovery
# 会在补发时记 "未知任务（_TASK_DISPATCH 未登记）" 而**静默无法补发**。
# 在 import 时就吼一声，别等真出故障才发现（P2-12 的自动推导会持续带出新任务，
# 这正是它第一次运行就抓出 ume_in_osg_report 的场景）。
_UNDISPATCHED_EMAIL_TASKS = sorted(set(EMAIL_TASK_IDS) - set(_TASK_DISPATCH))
if _UNDISPATCHED_EMAIL_TASKS:
    logger.warning(
        "以下 EWS 发信任务已在 EMAIL_TASK_IDS 中但没有补发分发分支，"
        "邮箱降级后无法补发，请在 _TASK_DISPATCH 补登记: %s",
        _UNDISPATCHED_EMAIL_TASKS,
    )


def _run_task(orig_task_id: str) -> dict:
    """调用对应邮件任务的 service 函数重新发送。"""
    target = _TASK_DISPATCH.get(orig_task_id)
    if target is None:
        return {"success": False, "error": f"未知任务（_TASK_DISPATCH 未登记）: {orig_task_id}"}
    module_path, func_name = target
    try:
        import importlib
        module = importlib.import_module(module_path)
        return getattr(module, func_name)()
    except Exception as e:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _run_task: exception swallowed", exc_info=True)
        return {"success": False, "error": f"调用失败: {e}"}


def recover_failed_emails() -> dict:
    """按任务失败链和时效策略扫描并补发邮件。

    每轮先做一次**真实** EWS 探测（结果落盘为翻转状态，供通知判定）；一旦探测成功，
    本轮立即对时效内的未闭合失败链补发——补发路径与告警静默完全无关。
    """
    now_dt = datetime.now()
    state = _load_state()
    probe = _probe_and_track(state, now_dt)
    transition = probe["transition"]

    if not probe["ok"]:
        # 依赖不可用 / 凭据异常：落盘状态后直接返回，本轮不扫库、不发送任何邮件。
        # 凭据类故障补发毫无意义（只会再失败一次），必须靠通知叫人处理。
        _save_state(state)
        logger.info("EWS 不可用 [%s]（连续第 %d 次），本轮不补发；翻转=%s%s",
                    probe["kind"], probe["fault_count"], transition,
                    "；已发持续故障升级提醒" if probe["escalate"] else "")
        return {
            "recovered": 0, "attempted": 0, "skipped": 0, "expired": 0,
            "reason": "ews_down", "ews_transition": transition,
            "ews_kind": probe["kind"], "ews_detail": probe["detail"],
            "ews_escalate": probe["escalate"],
            "ews_down_count": probe["fault_count"], "ews_down_since": probe["since"],
        }

    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            since = (now_dt - timedelta(hours=WINDOW_HOURS)).isoformat(timespec="seconds")
            rows = conn.execute(
                """SELECT task_id, success, started_at, error, COALESCE(trigger_type,'') AS trigger_type
                   FROM task_execution_log
                   WHERE task_id IN (%s) AND started_at >= ?
                   ORDER BY task_id, started_at ASC, id ASC""" % ",".join("?" * len(EMAIL_TASK_IDS)),
                list(EMAIL_TASK_IDS) + [since],
            ).fetchall()
    except Exception as e:
        logger.error("查询失败邮件记录异常: %s", e)
        _save_state(state)
        return {"recovered": 0, "attempted": 0, "skipped": 0, "expired": 0,
                "reason": f"db_error:{e}", "ews_transition": transition}

    # 只保留每个 task_id 上一次成功之后的失败记录，形成唯一的未闭合失败链。
    chains: dict[str, list] = {}
    for task_id, success, started_at, error, trig in rows:
        if success:
            chains[task_id] = []
        else:
            chains.setdefault(task_id, []).append((started_at, error or "", trig or ""))

    recovered = attempted = skipped = expired = 0
    details = []
    for task_id in sorted(chains, key=_chain_order_key):
        failures = chains[task_id]
        if not failures:
            continue
        latest_started_at, latest_error, _latest_trig = failures[-1]
        # 只对当前未闭合链的最新失败仍属于邮箱/EWS的问题补发。
        # 判据与 auto_retry 共用 is_ews_resendable()：NOT_RESENDABLE_KEYS 优先
        # （BUDGET_EXCEEDED 后台仍在发、子进程超时补发会重复发送），
        # 其次必须命中 EWS_FAIL_KEYS（非 EWS 失败留给 auto_retry 重试）。
        if not is_ews_resendable(latest_error):
            skipped += 1
            continue
        ews_failures = [(ts, err) for ts, err, _t in failures if is_ews_resendable(err)]
        first_failed_at, _first_error = ews_failures[0]
        first_failed_dt = _parse_iso(first_failed_at)
        if first_failed_dt is None:
            skipped += 1
            continue
        # 时效窗口锚点 = 链内最近一次「由调度/手工触发」的失败时间。
        # 补发自身写回的 recovery 记录只代表"尝试过发送"，不代表报告重新生成，
        # 故不参与锚定；否则补发失败会不断把窗口往后推，可能把已被次日新一期
        # 覆盖的旧报告当成有效数据补发出去。
        period_failures = [ts for ts, _e, t in failures if t != "recovery"] or [latest_started_at]
        anchor_dt = _parse_iso(period_failures[-1])
        if anchor_dt is None:
            skipped += 1
            continue
        policy_name = TASK_POLICY.get(task_id, "daily")
        chain_key = _chain_key(task_id, first_failed_at)
        chain = _chain_state(state, task_id, first_failed_at)

        if _window_expired(task_id, anchor_dt, now_dt):
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
        "ews_transition": transition,
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
    """供 Task Manager 直接调用的入口（返回 dict）。

    告警语义：EWS 不可用属「依赖不可用」，不是本任务故障，故返回 success=True，
    不再触发 task_runner 的失败告警（否则 EWS 长时间降级时会因"每 10 分钟跑一次
    + 30 分钟告警冷却"稳定每 30 分钟刷一封失败邮件）；改由**状态翻转 + 持续故障升级**
    通知。**探测与补发逻辑不受影响**——探测成功即在本轮立即补发时效内的失败链。

    2026-09-18 修正：原方案只有"翻转时通知一次"，于是密码失效这类**配置故障**
    （表现为长期 down）在 09-15 21:54 报过一次之后就永久静默，65 小时无人处理。
    现在 `_probe_and_track` 会在同一故障持续超过阈值后周期性升级提醒，且
    凭据类故障（auth_error / cred_mismatch）使用**明确的"需人工介入"文案**，
    不再写成"连接超时…已静默"。
    """
    logger.info("开始 EWS 恢复后邮件补发检查")
    summary = recover_failed_emails()
    logger.info("邮件补发检查完成: %s", summary)

    reason = summary.get("reason", "")
    transition = summary.get("ews_transition")

    if reason == "ews_down":
        summary["success"] = True
        kind = summary.get("ews_kind") or PROBE_SERVER_DOWN
        detail = summary.get("ews_detail") or ""
        n = int(summary.get("ews_down_count") or 1)
        since = summary.get("ews_down_since", "")
        escalate = bool(summary.get("ews_escalate"))

        if kind == PROBE_AUTH_ERROR:
            summary["message"] = (
                f"EWS 凭据被拒（连续第 {n} 次），本轮无补发。"
                "需人工到「设置 → Exchange/OWA Mailbox」更新密码。"
            )
        elif kind == PROBE_CRED_MISMATCH:
            summary["message"] = (
                f"各发信模块解析出的凭据与 credential_store 不一致（连续第 {n} 次），"
                "本轮无补发。这是代码缺陷，需修发信模块的凭据解析。"
            )
        else:
            summary["message"] = f"EWS 仍不可用（连续第 {n} 次探测失败），本轮无补发，降级期间静默"

        head = "EWS 探测失败" if kind not in _ACTIONABLE_KINDS else "EWS 凭据异常（需人工介入）"
        body = (
            f"{head}：{detail}\n"
            f"故障类型：{kind}\n"
            f"本次故障开始：{since}（已连续 {n} 次探测失败）\n"
        )
        if kind in _ACTIONABLE_KINDS:
            body += ("处理建议：检查「设置 → Exchange/OWA Mailbox」里的账号密码是否仍有效；"
                     "确认账号未被锁定/禁用。此类故障**不会**自行恢复。\n")
        else:
            body += "降级期间每 10 分钟继续真实探测；恢复后当轮即补发时效内的失败邮件。\n"

        if transition in ("went_down", "went_auth_error", "went_cred_mismatch", "changed_fault"):
            # 保留上面按故障类型写好的可操作文案（任务历史里能直接看到"该去设置页改密码"），
            # 只补一句已推送通知，不要用 body 首行把它覆盖掉。
            summary["message"] += "（已推送状态通知）"
            _notify_ews_state(kind, body, escalate=False)
        elif escalate:
            summary["message"] += "（已推送持续故障升级提醒）"
            _notify_ews_state(
                kind,
                f"【持续故障提醒】EWS 已连续不可用超过 {_ESCALATE_AFTER_HOURS:.0f} 小时，仍未恢复。\n"
                f"故障类型：{kind}\n开始时间：{since}（已连续 {n} 次探测失败）\n{detail}\n"
                + ("该故障不会自行恢复，请尽快人工处理。\n"
                   if kind in _ACTIONABLE_KINDS else
                   "补发通道将在恢复后自动工作；若长时间不恢复请检查 Orange 侧。\n"),
                escalate=True,
            )
    elif reason == "ews_up":
        summary["success"] = True
        if summary.get("attempted", 0) == 0:
            summary["message"] = "EWS 正常，无需补发"
        else:
            summary["message"] = (
                f"EWS 正常，补发 {summary.get('recovered', 0)}/{summary.get('attempted', 0)} 封"
            )
        if transition == "recovered":
            _notify_ews_state(PROBE_OK, (
                "EWS 邮件通道已恢复。\n"
                f"本轮补发：成功 {summary.get('recovered', 0)} 封 / 尝试 {summary.get('attempted', 0)} 封，"
                f"时效过期跳过 {summary.get('expired', 0)} 封。"
            ))
    else:
        # 非 EWS 依赖问题（如 DB 查询异常）属真实故障，必须照常告警，不能被静默逻辑吞掉。
        summary["success"] = False
        summary["error"] = f"邮件补发检查异常: {reason}"
    return summary


if __name__ == "__main__":
    import pprint
    pprint.pprint(run_email_recovery_task())
# -*- coding: utf-8 -*-
"""
失败任务自动重试（时效窗口约束）+ 漏跑任务补投
================================

背景：Task Manager 中的任务失败后（网络抖动 / 网管会话互踢 / 服务端短暂降级等），
若无人工干预会一直停留在失败状态，直到下一次自然调度；另一类场景是任务在
调度时刻**根本没有执行**（服务重启 / APScheduler misfire / worker 全部宕机），
执行日志里没有任何记录，失败扫描对这类「静默漏跑」完全无感。
本模块作为一个**低频次定时任务**（默认每 10 分钟）运行：

  1. 扫描 task_execution_log，找出「最新一条执行记录为失败」的任务（单条 SQL，
     含每个任务自上次成功以来的自动重试次数 / 最近一次重试时间，一次查出）；
  2. 时效窗口判定：失败后若已有成功执行（数据缺口已补上）或超过扫描窗口
     硬上限，才放弃重试。
     （2026-08-13 教训：旧逻辑「越过下一个 cron 触发时刻即过期」假设新一期
     调度已经运行，但僵尸 running 记录会挡住后续调度，导致缺口真实存在却被
     误判过期永久放弃，改为按「失败后是否有成功记录」判定）；
  3. 漏跑补投（2026-08-14 新增）：对每个启用且有 cron 的任务，计算最近一个
     应触发时刻；若越过宽限期仍没有任何执行记录（成功或失败都没有），
     判定为静默漏跑，同样以 auto_retry 触发补投一次。补投一旦产生执行记录
     即不再判定漏跑；若补投失败则转入上面的失败重试链路。
  4. 通过重试次数上限 + 冷却时间 + 不可重试错误关键字过滤后，
     调用 task_runner.run_task_async(trigger="auto_retry") 重新投递执行
     （自动兼容队列模式与单飞保护，重试记录在 Run History 中可见）。

设计要点：
  - 邮件类任务由 email_recovery（EWS 探测 + 报告时效窗口）专属补发，本模块默认
    排除，避免双重补发（可用 AUTO_RETRY_INCLUDE_EMAIL=1 打开）；
  - 失败后若已有成功记录（正常调度 / recovery 补发），最新记录不再是失败，天然跳过；
  - BUDGET_EXCEEDED（脱离主线程后台仍在发送）等永久性失败不重试；
  - 单次扫描最多触发 N 个重试（失败重试与漏跑补投共享额度），避免恢复瞬间的任务风暴；
  - 环境变量：
      AUTO_RETRY_ENABLED            总开关（默认 1）
      AUTO_RETRY_MAX_ATTEMPTS       同一失败链最多自动重试次数（默认 2）
      AUTO_RETRY_COOLDOWN_MIN       两次自动重试的最小间隔分钟（默认 15）
      AUTO_RETRY_SCAN_WINDOW_HOURS  失败记录扫描窗口小时（默认 24，同时是
                                    放弃重试的硬上限与漏跑回溯上限）
      AUTO_RETRY_MAX_PER_RUN        单次扫描最多触发的重试个数（默认 3）
      AUTO_RETRY_EXTRA_EXCLUDE      追加排除的 task_id（逗号分隔）
      AUTO_RETRY_INCLUDE_EMAIL      =1 时把邮件类任务也纳入（默认排除）
      AUTO_RETRY_MISS_ENABLED       漏跑补投开关（默认 1）
      AUTO_RETRY_MISS_GRACE_MIN     漏跑判定宽限分钟（默认 15，实际取
                                    max(调度间隔, 该值) 并封顶 30 分钟，给慢启动留余量
                                    又避免小时/天级任务漏跑拖满一个调度周期）
       AUTO_RETRY_MISS_MIN_INTERVAL_MIN  调度间隔小于该分钟数的任务不做漏跑补投
                                     （默认 30：高频任务下一期很快就到，补投无意义）

   5. 探测驱动重试（2026-09-11 新增，C+ 方案）：
      网络层失败（连接超时/拒绝）先从 error 文本提取故障目标 host:port，做 TCP 探测：
        - 目标不可达 → 跳过本次重试（不投递，因此不产生执行记录、不消耗重试额度），
          等下次扫描再探，实现「恢复即投」；
        - 目标已恢复 → 立即重试，仅受恢复后冷却约束。
      非网络层失败（鉴权/业务类）或提取不到目标 → 回退到按调度粒度计算的差异化冷却
      （小时级约 15 分钟，天级封顶 60 分钟）。
      环境变量：
       AUTO_RETRY_PROBE_ENABLED       探测门控开关（默认 1）
       AUTO_RETRY_PROBE_TIMEOUT_SEC   TCP 探测超时秒（默认 3）
       AUTO_RETRY_PROBE_CACHE_SEC     探测结果缓存秒（默认 60，同轮多任务复用）
       AUTO_RETRY_RECOVER_COOLDOWN_MIN  恢复后重试仍失败时的最小间隔（默认 10）
       AUTO_RETRY_PROBE_MAX_SKIP_MIN  连续不可达超过该分钟数则强制重试一次（默认 60，
                                      防止 host/port 提取错误导致任务被永久跳过）

   6. 会话/UI 类失败的自愈重试（2026-10-11 新增）：
      WhatsApp 类任务失败常表现为「网络通、页面在，但点不动 / 等不到登录态」
      （Playwright 报 ``intercepts pointer events`` 或 ``等待登录超时``）。这类失败
      TCP 探测判不出来（端口一直通），原样重投也无效（坏会话状态未变）。处理方式：
        - 归类为 ``session``（排在 network 之前，避免被日志里的 ``Timeout`` 带偏）；
        - 跳过 TCP 探测门控，走冷却；
        - **投递前**先调 whatsapp_service._kill_stale_chrome 清理 stale chrome，
          让自动重试带上「人工重跑」时的那一步清理动作。
      仅对 ``WHATSAPP_TASK_IDS`` 且判定为会话类失败的候选生效；自愈失败不阻断重试。
"""
from __future__ import annotations

import logging
import os
import re
import socket
import time
from datetime import datetime, timedelta
from pathlib import Path

from backend.database import get_raw_connection

logger = logging.getLogger("auto_retry")

MY_APP_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = MY_APP_DIR / "db" / "app.db"

SELF_TASK_ID = "auto_retry_failed"


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    """安全读取整型环境变量，非法值回退默认。"""
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


AUTO_RETRY_ENABLED = os.environ.get("AUTO_RETRY_ENABLED", "1") == "1"
MAX_ATTEMPTS = _env_int("AUTO_RETRY_MAX_ATTEMPTS", 2)
COOLDOWN_MIN = _env_int("AUTO_RETRY_COOLDOWN_MIN", 15)
SCAN_WINDOW_HOURS = _env_int("AUTO_RETRY_SCAN_WINDOW_HOURS", 24)
MAX_PER_RUN = _env_int("AUTO_RETRY_MAX_PER_RUN", 3)
MISS_ENABLED = os.environ.get("AUTO_RETRY_MISS_ENABLED", "1") == "1"
MISS_GRACE_MIN = _env_int("AUTO_RETRY_MISS_GRACE_MIN", 15)
MISS_MIN_INTERVAL_MIN = _env_int("AUTO_RETRY_MISS_MIN_INTERVAL_MIN", 30)

# --- 2026-09-11 新增：探测驱动重试（C+ 方案） ---
# 背景：旧逻辑的冷却只在「预测路径」算 next_retry_at，投递路径没有任何时间门控，
# 真实节拍退化为扫描周期（5 分钟）。持续故障会在几分钟内烧光 2 次额度，网络恢复后
# 反而因「已达上限」不再重试（09-11 UME 中断中 ran_ume_daily / cell_availability_sync
# 因此丢掉当天数据）。改为：先探故障目标是否活着，活着才投，不通则跳过且不计额度。
PROBE_ENABLED = os.environ.get("AUTO_RETRY_PROBE_ENABLED", "1") == "1"
PROBE_TIMEOUT_SEC = _env_int("AUTO_RETRY_PROBE_TIMEOUT_SEC", 3)
PROBE_CACHE_SEC = _env_int("AUTO_RETRY_PROBE_CACHE_SEC", 60)
# 探测通过后重试仍失败（TCP 通但应用层未就绪）时的最小间隔，防止反复轰炸长任务
RECOVER_COOLDOWN_MIN = _env_int("AUTO_RETRY_RECOVER_COOLDOWN_MIN", 10)
# 安全阀：因「目标不可达」跳过累计超过该时长后，强制按冷却逻辑投一次，
# 避免 host/port 提取错误或目标被防火墙静默丢弃时任务被永久跳过
PROBE_MAX_SKIP_MIN = _env_int("AUTO_RETRY_PROBE_MAX_SKIP_MIN", 60)

# 网络层失败特征（连接/超时类）→ 走 TCP 探测；探不通则跳过并保留重试额度
NETWORK_ERROR_KEYS = (
    "Max retries exceeded", "Connection timed out", "ERR_CONNECTION_TIMED_OUT",
    "Connection refused", "ConnectionRefused", "Name or service not known",
    "Temporary failure in name resolution", "Network is unreachable",
    "10060", "10054", "timed out", "Timeout",
)
# 应用层失败特征（端口通但鉴权/业务失败）→ TCP 探测无意义，直接走冷却
APP_ERROR_KEYS = (
    "鉴权", "登录失败", "登录未成功", "Unauthorized", "Forbidden", "RSA",
    "未获取到", "无可用", "未通过",
)

# 永久性失败关键字：重试无意义（甚至有害），直接放弃
NON_RETRYABLE_KEYS = (
    "BUDGET_EXCEEDED",   # 邮件发送脱离主线程后仍在后台执行，重试可能造成重复发送
    "已禁用",
    "未找到",
    "无效的 cron",
    "STOPPED_BY_USER",   # 用户手动停止执行，重试无意义
    # 账号被上游锁定（2026-10-12 新增）：解锁只能靠管理员人工操作，
    # 重试不会成功。2026-10-12 的 ran_ume_daily 在 NOC 账号被锁后，
    # 每 10 分钟被 auto_retry 无谓重投一次、每次都失败并触发告警，
    # 直到人工发现为止 —— 纯粹是告警噪音，且会持续消耗 worker 与上游登录额度。
    "User has been locked",
    "has been locked",
    "账号已被上游锁定",
)

# ---- 会话/UI 类失败（2026-10-11 新增） ----
# 特征：网络通、页面在，但「点不动 / 等不到登录态」。TCP 探测对这种失败无意义
# （端口一直是通的），必须换成「重试前先自愈会话」。
# 2026-10-11 05:55~08:25 连续 7 次 WhatsApp 发送失败全部命中这组特征，且当天
# 10:12 手工重跑即成功 —— 说明是会话状态问题而非业务/网络问题。
# 判定与 whatsapp_service.SESSION_BLOCKED_KEYS 共用同一组关键字，避免分叉。
SESSION_ERROR_KEYS = (
    "intercepts pointer events",   # Playwright：元素被遮罩层挡住
    "WhatsAppSessionBlocked",      # whatsapp_service 显式打的会话类标记
    "等待登录超时",                 # #side 未出现
)

# 需要「重试前自愈会话」的 WhatsApp 任务（USER_DATA_DIR 被这些任务共用，
# 一个进程把会话搅乱会连累后面所有任务，故统一在重试前清理 stale chrome）。
WHATSAPP_TASK_IDS = (
    "sp_whatsapp_report",
    "sp_online_report_send",
    "sp_email_details",
)


def _parse_iso(ts: str):
    """解析 task_execution_log 中的 ISO 时间字符串，失败返回 None。"""
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _email_task_ids() -> set:
    """邮件类任务集合（email_recovery 专属补发的对象）。"""
    if os.environ.get("AUTO_RETRY_INCLUDE_EMAIL", "0") == "1":
        return set()
    try:
        from backend.services.email_recovery import EMAIL_TASK_IDS
        return set(EMAIL_TASK_IDS)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"加载 EMAIL_TASK_IDS 失败，邮件任务未被排除: {e}")
        return set()


def _is_excluded_from_retry(task_id: str, error=None) -> bool:
    """auto_retry 是否应跳过该任务（判定「要不要重试」的唯一入口）。

    - 自身任务 / `AUTO_RETRY_EXTRA_EXCLUDE`：永远跳过
    - 邮件类任务：**只有「失败会被补发通道真正处理」时才跳过**。非 EWS 失败
      （数据源、网络、子进程超时）必须留给 auto_retry —— 否则 auto_retry 因任务在
      `EMAIL_TASK_IDS` 里跳过、补发通道又因失败不是 EWS 类跳过，两边互相谦让，
      任务再没人重试。判据复用 `email_recovery.is_ews_resendable()`，两边共用一套规则，
      既避免「互相谦让」也避免「互相争抢」（重复发送）。
    - 传 `error=None`（漏跑扫描没有失败原因）时按任务级粗排除处理。
    - `AUTO_RETRY_INCLUDE_EMAIL=1` 时邮件任务完全不被排除。

    2026-09-18：`fw_kpi_sync` 登记进 `EMAIL_TASK_IDS` 后，它的远端 API 连接失败
    （`[WinError 10065]`）正落进这个空档；历史上它靠 auto_retry 恢复过
    （09:00 失败 → 10:07 trig=auto_retry 成功）。
    """
    if task_id == SELF_TASK_ID:
        return True
    extra = {t.strip() for t in os.environ.get("AUTO_RETRY_EXTRA_EXCLUDE", "").split(",") if t.strip()}
    if task_id in extra:
        return True
    if task_id not in _email_task_ids():
        return False
    if error is None:
        return True  # 没有失败原因可用 → 维持任务级粗排除
    try:
        from backend.services.email_recovery import is_ews_resendable
    except Exception as e:  # noqa: BLE001
        logger.warning(f"加载 is_ews_resendable 失败，邮件任务按原行为全部让路: {e}")
        return True  # 保守：维持旧行为，宁可漏重试也不重复发送
    return is_ews_resendable(error)


def _exclude_task_ids() -> set:
    """排除集：自身 + 邮件类（email_recovery 专属补发）+ 环境变量追加。

    仅用于**拿不到失败原因**的场合（漏跑扫描）。判定「失败是否重试」请用
    `_is_excluded_from_retry(task_id, error)`，它会按失败原因细分。
    """
    ids = {SELF_TASK_ID}
    ids |= _email_task_ids()
    extra = os.environ.get("AUTO_RETRY_EXTRA_EXCLUDE", "")
    ids |= {t.strip() for t in extra.split(",") if t.strip()}
    return ids


def _fetch_failed_candidates(cutoff_iso: str) -> list:
    """单条 SQL 查出「最新一条执行记录为失败」的任务及其重试状态。

    retry_attempts / last_retry_at 均只统计「上一次成功之后」的 auto_retry 记录，
    即同一失败链内的重试次数，成功后自动清零。
    """
    sql = """
        SELECT
            l.task_id,
            l.id          AS fail_id,
            l.started_at  AS failed_at,
            l.error       AS error,
            (SELECT COUNT(*) FROM task_execution_log r
              WHERE r.task_id = l.task_id
                AND r.trigger_type = 'auto_retry'
                AND r.id > COALESCE((SELECT MAX(s.id) FROM task_execution_log s
                                      WHERE s.task_id = l.task_id AND s.success = 1), 0)
            ) AS retry_attempts,
            (SELECT MAX(r.started_at) FROM task_execution_log r
              WHERE r.task_id = l.task_id
                AND r.trigger_type = 'auto_retry'
                AND r.id > COALESCE((SELECT MAX(s.id) FROM task_execution_log s
                                      WHERE s.task_id = l.task_id AND s.success = 1), 0)
            ) AS last_retry_at
        FROM task_execution_log l
        INNER JOIN (
            SELECT task_id, MAX(id) AS max_id
            FROM task_execution_log
            GROUP BY task_id
        ) m ON l.task_id = m.task_id AND l.id = m.max_id
        WHERE l.success = 0
          AND l.started_at >= ?
        ORDER BY l.started_at DESC
    """
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            rows = conn.execute(sql, (cutoff_iso,)).fetchall()
            conn.close()
        return rows
    except Exception as e:
        logger.warning(f"查询失败候选任务失败: {e}")
        return []


def _window_expired(task_id: str, failed_dt: datetime, now: datetime) -> tuple:
    """判断失败造成的数据缺口是否已被后续执行补上。

    返回 (expired: bool, reason: str)：
      - 失败时刻之后已有成功执行记录 → 缺口已补，无需重试；
      - 超过 SCAN_WINDOW_HOURS 硬上限 → 过期（避免重试过旧失败）；
      - 其余情况 → 缺口仍在，允许重试。

    2026-08-13 教训：旧逻辑用 cron 算「下一个触发时刻」作窗口终点，越过即
    放弃；但当僵尸 running 记录挡住后续调度时，越过 next_fire 后新一期根本没
    跑，数据缺口真实存在却被误判过期（eflow_sync 断档至人工介入）。
    改为按事实判定：只有失败后真有成功执行才放弃。若后续各期也连续失败，
    候选 SQL 取的是最新失败记录（fail_dt 自然前移），行为仍正确。
    """
    if now >= failed_dt + timedelta(hours=SCAN_WINDOW_HOURS):
        return True, f"超过 {SCAN_WINDOW_HOURS}h 硬上限"
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            row = conn.execute(
                "SELECT 1 FROM task_execution_log WHERE task_id = ? AND success = 1 "
                "AND started_at > ? LIMIT 1",
                (task_id, failed_dt.isoformat())).fetchone()
            conn.close()
        if row:
            return True, "失败后已有成功执行，数据缺口已补上"
    except Exception as e:  # noqa: BLE001
        # 查询失败时保守放行（宁可多重试一次，不可漏掉真实缺口）
        logger.warning(f"[{task_id}] 查询后续成功记录失败，按未过期处理: {e}")
    return False, ""


# ========== 漏跑补投（2026-08-14）：时效窗口内根本没执行的任务也要重试 ==========

def _cron_prev_fire_and_interval(cron: str, now: datetime):
    """返回 now 之前最近一次的 (应触发时刻, 调度间隔)；解析失败返回 (None, None)。

    用 APScheduler CronTrigger 从回溯起点逐次前推，兼容任意合法 cron 表达式，
    不引入 croniter 新依赖。回溯起点取 SCAN_WINDOW_HOURS + 7 天（覆盖周级任务）。
    """
    try:
        from apscheduler.triggers.cron import CronTrigger
        parts = (cron or "").strip().split()
        if len(parts) != 5:
            return None, None
        minute, hour, day, month, dow = parts
        trig = CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=dow)
        cur = now - timedelta(hours=SCAN_WINDOW_HOURS, days=7)
        prev, nxt = None, None
        while True:
            f = trig.get_next_fire_time(None, cur)
            if f is None:
                break
            if f.tzinfo is not None:
                f = f.replace(tzinfo=None)
            if f >= now:
                break
            prev, nxt, cur = f, None, f + timedelta(seconds=1)
            # 顺手记录相邻两次触发间隔（再算一次）
            f2 = trig.get_next_fire_time(None, cur)
            if f2 is not None:
                if f2.tzinfo is not None:
                    f2 = f2.replace(tzinfo=None)
                nxt = f2
        if prev is None:
            return None, None
        interval = (nxt - prev) if nxt else None
        return prev, interval
    except Exception:
        return None, None


def _fetch_latest_exec_times(task_ids: list) -> dict:
    """一次 SQL 批量取出各任务最新执行时间（成功/失败都算）。

    向量化查询：避免逐任务 N 次往返。返回 {task_id: latest_started_at}，
    无记录的任务不在返回 dict 中。
    """
    if not task_ids:
        return {}
    ph = ",".join("?" * len(task_ids))
    sql = (f"SELECT task_id, MAX(started_at) FROM task_execution_log "
           f"WHERE task_id IN ({ph}) GROUP BY task_id")
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            rows = conn.execute(sql, tuple(task_ids)).fetchall()
            conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"批量查询最新执行时间失败: {e}")
        return {}


def _fetch_queued_task_ids() -> set:
    """当前队列中 pending/running 的 task_id 集合（已认领/待认领，不该再补投）。"""
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            rows = conn.execute(
                "SELECT DISTINCT task_id FROM task_queue "
                "WHERE status IN ('pending', 'running')").fetchall()
            conn.close()
        return {r[0] for r in rows}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"查询队列占位失败，按空集处理: {e}")
        return set()


def _scan_missed_tasks(now: datetime, registry: dict, exclude_ids: set) -> list:
    """找出「时效窗口内应触发但根本没有任何执行记录」的任务。

    判定条件（全部满足才算漏跑）：
      - 任务已启用、不在排除集、有合法 cron；
      - 调度间隔 >= MISS_MIN_INTERVAL_MIN（高频任务下一期很快到，补投无意义）；
      - 最近应触发时刻 prev_fire 距今 > max(调度间隔, MISS_GRACE_MIN)，
        给慢启动/长任务留余量；
      - prev_fire 之后没有任何执行记录（成功或失败都没有——有失败记录的
        交给失败重试链路处理，避免双重投递）；
      - 队列中无该任务的 pending/running 占位（单飞保护之外的双保险）。

    返回 [(task_id, prev_fire), ...]。补投成功后会产生执行记录，
    下一轮扫描自然不再判定漏跑；补投失败则转入失败重试链路。
    """
    candidates = []
    for task_id, task in registry.items():
        if task_id in exclude_ids:
            continue
        if not task.get("enabled", True):
            continue
        cron = task.get("current_cron") or task.get("default_cron")
        if not cron:
            continue
        prev_fire, interval = _cron_prev_fire_and_interval(cron, now)
        if prev_fire is None:
            continue
        interval_min = (interval.total_seconds() / 60) if interval else None
        if interval_min is None or interval_min < MISS_MIN_INTERVAL_MIN:
            continue
        # 2026-08-15 加固：宽限期封顶 30 分钟。旧逻辑 grace = max(15min, 调度间隔)，
        # 对小时/天级任务意味着「静默漏跑」要等满一个调度周期才被判定（如 11:00 漏跑
        # 最早 12:00 才补投），与"服务重启/misfire 补投"的设计目标相悖。
        # 封顶后运行中的任务不会误判：队列模式有 pending/running 占位，进程内模式
        # 有执行记录（last_dt >= prev_fire 判定）双重保护。
        grace = min(
            max(timedelta(minutes=MISS_GRACE_MIN), interval or timedelta(minutes=MISS_GRACE_MIN)),
            timedelta(minutes=30),
        )
        if now <= prev_fire + grace:
            continue  # 还在宽限期内，可能正在启动/执行
        candidates.append((task_id, prev_fire, grace))
    if not candidates:
        return []

    latest = _fetch_latest_exec_times([t for t, _f, _g in candidates])
    queued = _fetch_queued_task_ids()
    missed = []
    for task_id, prev_fire, _grace in candidates:
        if task_id in queued:
            continue
        last_exec = latest.get(task_id)
        last_dt = _parse_iso(last_exec) if last_exec else None
        if last_dt is not None and last_dt >= prev_fire:
            continue  # prev_fire 之后已有执行记录（成功/失败），不算漏跑
        missed.append((task_id, prev_fire))
    return missed


def _scan_interval_min(registry) -> int:
    """从 auto_retry_failed 任务的实际 cron 推断扫描间隔（分钟），默认 10。

    与注册表 cron 保持一致：若管理员改了 auto_retry_failed 的调度频率，
    预测的重试时间也跟着变，避免预测与真实扫描节拍脱节。
    """
    try:
        task = registry.get(SELF_TASK_ID)
        cron = (task or {}).get("current_cron", "*/10 * * * *")
        minute_field = cron.split()[0]
        if minute_field.startswith("*/"):
            return max(1, int(minute_field[2:]))
    except Exception:
        pass
    return 10


def _next_scan_after(dt: datetime, interval_min: int) -> datetime:
    """返回严格晚于 dt 的下一个扫描边界（每 interval_min 分钟一次，从整点对齐）。"""
    epoch = datetime(1970, 1, 1)
    mins = (dt - epoch).total_seconds() // 60
    nxt_mins = ((mins // interval_min) + 1) * interval_min
    base = epoch + timedelta(minutes=nxt_mins)
    if base <= dt:
        base += timedelta(minutes=interval_min)
    return base


# ============ 探测驱动重试（2026-09-11）：恢复即投，故障期不烧额度 ============

_HOST_PORT_PATTERNS = (
    # requests: HTTPSConnectionPool(host='10.100.2.99', port=28001)
    re.compile(r"host=['\"](?P<host>[^'\"]+)['\"]\s*,\s*port=(?P<port>\d+)"),
    # Playwright: net::ERR_CONNECTION_TIMED_OUT at https://10.100.20.8:28001/...
    re.compile(r"https?://(?P<host>[0-9A-Za-z_.\-]+):(?P<port>\d+)"),
    # 元组形态：('10.100.2.99', 28001)
    re.compile(r"['\"](?P<host>\d{1,3}(?:\.\d{1,3}){3})['\"]\s*,\s*(?P<port>\d+)"),
)

# {(host, port): (ts, alive)}：同一次扫描内多任务复用，避免重复 connect
_PROBE_CACHE: dict = {}


def _is_session_error(error) -> bool:
    """是否为 WhatsApp 会话/UI 类失败（需自愈后重试，TCP 探测无意义）。"""
    text = error or ""
    return any(k in text for k in SESSION_ERROR_KEYS)


def _classify_error(error) -> str:
    """把失败原因分层：session（自愈重试）/ network（走探测）/ app（走冷却）/ unknown。

    session 必须排在 network 之前：会话失败的 Playwright 日志里常夹带
    ``Timeout``（元素等待超时），若先命中 NETWORK_ERROR_KEYS 会被误判成网络问题，
    进而去 TCP 探测一个本就可达的端口 —— 2026-10-11 的 7 次失败正是被这样
    「探测通过 → 原样重试 → 再失败」空转掉的。
    """
    text = error or ""
    if _is_session_error(text):
        return "session"
    if any(k in text for k in APP_ERROR_KEYS):
        return "app"
    if any(k in text for k in NETWORK_ERROR_KEYS):
        return "network"
    return "unknown"


def _heal_session_before_retry(task_id: str, error) -> bool:
    """会话类失败重试前先自愈：清掉可能锁住 WhatsApp profile 的 stale chrome。

    为什么放在投递前：worker 是串行执行，多个 WhatsApp 任务共用同一个
    ``USER_DATA_DIR``；一个进程把会话写坏后，后面每个任务 launch 到的都是同一份
    坏状态。仅「原样重投」等于把坏状态再跑一遍（2026-10-11 的 auto_retry 就是
    这么空转的）。这里复用 whatsapp_service 的 ``_kill_stale_chrome``，与「手动重跑
    即成功」的人工动作一致 —— 让自动重试也带上这一步。

    只对注册在案、且失败类型为会话类的 WhatsApp 任务生效；其余任务直接放行（返回
    False 表示无需自愈），避免对无关任务做多余的进程清理。
    """
    if not _is_session_error(error):
        return False
    if task_id not in WHATSAPP_TASK_IDS:
        return False
    try:
        from backend.services.whatsapp_service import _kill_stale_chrome, USER_DATA_DIR
        _kill_stale_chrome(USER_DATA_DIR)
        logger.info(f"[{task_id}] 会话类失败，重试前已清理 WhatsApp stale chrome 会话")
        return True
    except Exception as e:  # noqa: BLE001
        # 自愈失败不阻断重试 —— 清理是「尽力而为」，清理不了仍按原逻辑重投
        logger.warning(f"[{task_id}] 重试前会话自愈失败（不阻断重试）: {e}")
        return False


def _extract_targets(error) -> list:
    """从失败信息中提取 [(host, port)]，按出现顺序去重。"""
    text = error or ""
    out, seen = [], set()
    for pat in _HOST_PORT_PATTERNS:
        for m in pat.finditer(text):
            key = (m.group("host"), int(m.group("port")))
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


def _probe_alive(host: str, port: int) -> bool:
    """TCP 连通性探测（带短缓存）。

    只验证端口可达，不验证 TLS/鉴权：故障期绝大多数失败是网络层超时，
    「TCP 通但应用层未就绪」的残余风险由 RECOVER_COOLDOWN_MIN 兜底。
    """
    now_ts = time.time()
    hit = _PROBE_CACHE.get((host, port))
    if hit and now_ts - hit[0] < PROBE_CACHE_SEC:
        return hit[1]
    ok = False
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT_SEC):
            ok = True
    except Exception as e:  # noqa: BLE001
        logger.debug(f"探测 {host}:{port} 不可达: {e}")
        ok = False
    _PROBE_CACHE[(host, port)] = (now_ts, ok)
    return ok


def _probe_targets(targets) -> tuple:
    """探测一组目标，返回 (是否全部可达, 不可达目标描述)。"""
    dead = [f"{h}:{p}" for h, p in (targets or []) if not _probe_alive(h, p)]
    return (not dead), ",".join(dead)


def _adaptive_cooldown_min(registry, task_id, now) -> int:
    """按调度粒度算冷却分钟数（小时级 ~15min，天级封顶 60min）。

    用于「非网络层失败」或「提取不到故障目标」的回退路径：保证天级任务
    不会像小时级那样在几分钟内耗尽重试额度。
    """
    task = (registry or {}).get(task_id) or {}
    cron = task.get("current_cron") or task.get("default_cron")
    if not cron:
        return COOLDOWN_MIN
    _prev, interval = _cron_prev_fire_and_interval(cron, now)
    if not interval:
        return COOLDOWN_MIN
    return int(min(max(interval.total_seconds() / 60 / 4, COOLDOWN_MIN), 60))


def _mk_retry_info(will_retry, reason, next_retry_at, attempts, last_retry_at, failed_at, probe=None):
    return {
        "will_retry": will_retry,
        "reason": reason,
        "next_retry_at": next_retry_at,
        "attempts": attempts,
        "max_attempts": MAX_ATTEMPTS,
        "attempts_left": max(0, MAX_ATTEMPTS - attempts),
        "last_retry_at": last_retry_at,
        "failed_at": failed_at,
        "probe": probe,
    }


def _evaluate_candidate(task_id, failed_at, error, retry_attempts, last_retry_at,
                         now, registry, interval_min) -> dict:
    """判定某失败任务是否会被自动重试，并预测下次重试时间。

    与 scan_and_retry_failed_tasks 共用同一套判定规则（次数上限 / 冷却 / 永久错误 /
    时效窗口），保证「语音播报的预计重试时间」与真实扫描行为一致。
    「正在运行」是瞬时态，不在此判定（扫描会跳过当次、下一轮若仍失败再重试）。
    """
    fail_dt = _parse_iso(failed_at)
    if not fail_dt:
        return _mk_retry_info(False, f"失败时间无法解析: {failed_at}", None, retry_attempts, last_retry_at, failed_at)
    if now >= fail_dt + timedelta(hours=SCAN_WINDOW_HOURS):
        return _mk_retry_info(False, f"超过 {SCAN_WINDOW_HOURS}h 硬上限", None, retry_attempts, last_retry_at, failed_at)
    if _is_excluded_from_retry(task_id, error):
        return _mk_retry_info(False, "任务被排除（EWS 发信失败由 recovery 补发）", None, retry_attempts, last_retry_at, failed_at)
    task = registry.get(task_id)
    if task and not task.get("enabled", True):
        return _mk_retry_info(False, "任务已禁用", None, retry_attempts, last_retry_at, failed_at)
    if retry_attempts >= MAX_ATTEMPTS:
        return _mk_retry_info(False, f"自动重试已达上限 {MAX_ATTEMPTS} 次，等待人工处理", None, retry_attempts, last_retry_at, failed_at)
    err_text = error or ""
    if any(k in err_text for k in NON_RETRYABLE_KEYS):
        return _mk_retry_info(False, "永久性错误，重试无意义", None, retry_attempts, last_retry_at, failed_at)

    last_dt = _parse_iso(last_retry_at)

    # ---- 探测门控（2026-09-11）：网络层失败先探目标，不通则跳过且不消耗额度 ----
    if PROBE_ENABLED and _classify_error(err_text) == "network":
        targets = _extract_targets(err_text)
        if targets:
            alive, dead_desc = _probe_targets(targets)
            probe = {
                "targets": [f"{h}:{p}" for h, p in targets],
                "reachable": alive,
                "dead": dead_desc or None,
                "mode": "tcp",
                "checked_at": now.isoformat(),
            }
            stuck_min = (now - fail_dt).total_seconds() / 60
            if not alive:
                # 安全阀：长时间探测不通（host/port 提取错误或目标静默丢包）时
                # 强制回退到冷却逻辑投一次，避免任务被永久跳过
                if stuck_min > PROBE_MAX_SKIP_MIN and (
                    not last_dt or now >= last_dt + timedelta(minutes=COOLDOWN_MIN)
                ):
                    return _mk_retry_info(
                        True,
                        f"目标 {dead_desc} 连续不可达 {int(stuck_min)} 分钟"
                        f"（超过安全阀 {PROBE_MAX_SKIP_MIN} 分钟），强制重试一次",
                        now.isoformat(), retry_attempts, last_retry_at, failed_at, probe,
                    )
                return _mk_retry_info(
                    False,
                    f"故障目标 {dead_desc} 仍不可达，保留重试额度（已等待 {int(stuck_min)} 分钟）",
                    None, retry_attempts, last_retry_at, failed_at, probe,
                )
            # 目标已恢复 → 立即重试，仅受「恢复后冷却」约束（防 TCP 通但应用未就绪）
            if last_dt and now < last_dt + timedelta(minutes=RECOVER_COOLDOWN_MIN):
                nxt_cool = last_dt + timedelta(minutes=RECOVER_COOLDOWN_MIN)
                return _mk_retry_info(
                    False,
                    f"目标已恢复，恢复后冷却中（{RECOVER_COOLDOWN_MIN} 分钟），"
                    f"预计 {nxt_cool:%H:%M} 重试",
                    nxt_cool.isoformat(), retry_attempts, last_retry_at, failed_at, probe,
                )
            return _mk_retry_info(
                True,
                f"目标已恢复，立即重试（第 {retry_attempts + 1}/{MAX_ATTEMPTS} 次）",
                now.isoformat(), retry_attempts, last_retry_at, failed_at, probe,
            )

    # ---- 回退路径：非网络层失败 / 提取不到目标 → 按调度粒度的差异化冷却 ----
    # 2026-09-11 修复：旧实现只在预测路径算 next_retry_at，投递路径没有时间门控，
    # 导致冷却形同虚设、所有任务节拍退化为扫描周期。此处 earliest > now 即跳过。
    cooldown = _adaptive_cooldown_min(registry, task_id, now)
    earliest = max(now, last_dt + timedelta(minutes=cooldown)) if last_dt else now
    if earliest > now:
        nxt = _next_scan_after(earliest, interval_min)
        if nxt > fail_dt + timedelta(hours=SCAN_WINDOW_HOURS):
            return _mk_retry_info(
                False, f"时效窗口已过（超过 {SCAN_WINDOW_HOURS}h），放弃重试",
                None, retry_attempts, last_retry_at, failed_at,
            )
        return _mk_retry_info(
            False,
            f"冷却中（粒度冷却 {cooldown} 分钟），预计 {nxt:%m-%d %H:%M} 重试",
            nxt.isoformat(), retry_attempts, last_retry_at, failed_at,
        )
    return _mk_retry_info(
        True,
        f"将在自动重试扫描中重投（第 {retry_attempts + 1}/{MAX_ATTEMPTS} 次）",
        now.isoformat(),
        retry_attempts,
        last_retry_at,
        failed_at,
    )


def _no_failure_info() -> dict:
    return _mk_retry_info(False, "no recent failure", None, 0, None, None)


def get_all_retry_info() -> dict:
    """一次性算出当前所有「最新执行为失败」任务的重试信息，供 /api/tasks 批量挂载。"""
    now = datetime.now()
    cutoff_iso = (now - timedelta(hours=SCAN_WINDOW_HOURS)).isoformat()
    try:
        from backend.services import task_runner
        registry = task_runner._task_registry
    except Exception:
        registry = {}
    interval_min = _scan_interval_min(registry)
    rows = _fetch_failed_candidates(cutoff_iso)
    out = {}
    for task_id, _fid, failed_at, error, attempts, last_retry_at in rows:
        out[task_id] = _evaluate_candidate(
            task_id, failed_at, error, attempts, last_retry_at, now, registry, interval_min
        )
    return out


def get_retry_info_for_task(task_id: str) -> dict:
    """单个任务的重试信息（失败则返回预测，否则返回「无近期失败」）。"""
    return get_all_retry_info().get(task_id, _no_failure_info())


def scan_and_retry_failed_tasks() -> dict:
    """扫描失败任务并在时效窗口内重新投递执行。返回汇总 dict。"""
    if not AUTO_RETRY_ENABLED:
        return {"success": True, "retried": 0, "message": "AUTO_RETRY_ENABLED=0，已关闭自动重试"}

    # 延迟导入，避免与 task_runner 的注册期循环依赖
    from backend.services import task_runner

    now = datetime.now()
    cutoff_iso = (now - timedelta(hours=SCAN_WINDOW_HOURS)).isoformat()
    exclude_ids = _exclude_task_ids()

    rows = _fetch_failed_candidates(cutoff_iso)
    registry = task_runner._task_registry
    interval_min = _scan_interval_min(registry)
    summary = {
        "success": True,
        "scanned": len(rows),
        "retried": 0,
        "expired": 0,
        "healed": 0,
        "retried_tasks": [],
        "missed_filled": [],
        "skipped": {},
    }

    # 主机聚类：同一故障目标本轮只放行一个任务，其余错峰（2026-09-11）
    released_targets = set()

    for task_id, _fail_id, failed_at, error, retry_attempts, last_retry_at in rows:
        if summary["retried"] >= MAX_PER_RUN:
            summary["skipped"][task_id] = f"单次重试上限 {MAX_PER_RUN} 已达，排队待下次扫描"
            continue
        if _is_excluded_from_retry(task_id, error):
            continue  # 排除集静默跳过，不计入 skipped（每 10 分钟一次，避免日志噪音）

        task = registry.get(task_id)
        if not task:
            summary["skipped"][task_id] = "任务未注册"
            continue
        if not task["enabled"]:
            summary["skipped"][task_id] = "任务已禁用"
            continue

        # 与前端语音播报共用同一判定规则，保证预测一致
        info = _evaluate_candidate(
            task_id, failed_at, error, retry_attempts, last_retry_at, now, registry, interval_min
        )
        if not info["will_retry"]:
            summary["skipped"][task_id] = info["reason"]
            if "硬上限" in info["reason"]:
                summary["expired"] += 1
            continue

        # 运行中保护（队列模式查跨进程队列状态）
        try:
            if task_runner.is_task_running(task_id):
                summary["skipped"][task_id] = "任务正在运行中"
                continue
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{task_id}] 运行状态检查异常: {e}")

        # 主机聚类错峰：同一故障目标本轮已放行一个任务时，其余排队到下次扫描，
        # 避免服务刚恢复就被多个长任务同时压垮（2026-09-11）
        tgt_key = tuple((info.get("probe") or {}).get("targets") or [])
        if tgt_key and tgt_key in released_targets:
            summary["skipped"][task_id] = (
                f"同故障目标 {'、'.join(tgt_key)} 本轮已放行一个任务，错峰到下次扫描"
            )
            continue
        if tgt_key:
            released_targets.add(tgt_key)

        # 会话类失败：投递前先自愈（清理 stale chrome），否则等于把坏会话再跑一遍
        healed = _heal_session_before_retry(task_id, error)
        if healed:
            summary["healed"] = summary.get("healed", 0) + 1

        resp = task_runner.run_task_async(task_id, trigger="auto_retry")
        if resp.get("accepted"):
            summary["retried"] += 1
            summary["retried_tasks"].append(task_id)
            logger.info(
                f"[{task_id}] 时效窗口内自动重试已投递（第 {retry_attempts + 1}/{MAX_ATTEMPTS} 次，"
                f"失败于 {failed_at}{'，已自愈会话' if healed else ''}）: {(error or '')[:200]}"
            )
        else:
            summary["skipped"][task_id] = f"投递被拒绝: {resp.get('error')}"

    # ---- 漏跑补投：应触发时刻已过但根本没有任何执行记录（服务重启 /
    # misfire / worker 全宕）——失败扫描对这类静默漏跑无感，必须单独补。 ----
    if MISS_ENABLED and summary["retried"] < MAX_PER_RUN:
        try:
            missed = _scan_missed_tasks(now, registry, exclude_ids)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"漏跑扫描异常: {e}")
            missed = []
        for task_id, prev_fire in missed:
            if summary["retried"] >= MAX_PER_RUN:
                summary["skipped"][task_id] = f"单次重试上限 {MAX_PER_RUN} 已达，排队待下次扫描"
                continue
            try:
                if task_runner.is_task_running(task_id):
                    summary["skipped"][task_id] = "任务正在运行中"
                    continue
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[{task_id}] 运行状态检查异常: {e}")
            resp = task_runner.run_task_async(task_id, trigger="auto_retry")
            if resp.get("accepted"):
                summary["retried"] += 1
                summary["missed_filled"].append(task_id)
                logger.info(
                    f"[{task_id}] 漏跑补投已投递（应触发于 {prev_fire:%m-%d %H:%M}，无任何执行记录）"
                )
            else:
                summary["skipped"][task_id] = f"投递被拒绝: {resp.get('error')}"

    if summary["retried_tasks"] or summary["missed_filled"]:
        parts = []
        if summary["retried_tasks"]:
            retry_desc = f"失败重试 {len(summary['retried_tasks'])} 个: {', '.join(summary['retried_tasks'])}"
            if summary["healed"]:
                retry_desc += f"（其中 {summary['healed']} 个会话类失败已自愈）"
            parts.append(retry_desc)
        if summary["missed_filled"]:
            parts.append(f"漏跑补投 {len(summary['missed_filled'])} 个: {', '.join(summary['missed_filled'])}")
        summary["message"] = "自动重试：" + "；".join(parts)
    else:
        summary["message"] = f"扫描 {summary['scanned']} 个失败任务，无需重试（过期 {summary['expired']}）"
    return summary


def run_auto_retry_task() -> dict:
    """供 Task Manager 调度的入口（返回 dict，含全程耗时）。"""
    start_time = time.time()
    logger.info("开始失败任务自动重试扫描")
    try:
        summary = scan_and_retry_failed_tasks()
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] scan_and_retry_failed_tasks: exception swallowed", exc_info=True)
        summary = {"success": False, "error": f"{type(e).__name__}: {e}"}
    elapsed = round(time.time() - start_time, 2)
    summary["elapsed_seconds"] = elapsed
    logger.info(f"失败任务自动重试扫描完成，耗时 {elapsed}s: {summary.get('message')}")
    return summary


if __name__ == "__main__":
    import pprint
    logging.basicConfig(level=logging.INFO)
    t0 = time.time()
    pprint.pprint(run_auto_retry_task())
    print(f"总耗时: {time.time() - t0:.2f} 秒")

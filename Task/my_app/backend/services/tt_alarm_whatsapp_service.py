"""eFlow P1 未清除 TT 告警 → WhatsApp 推送服务。

## 业务口径（每 15 分钟运行一次）

从本地 `eflow_tt` 镜像中挑出满足**全部**条件的工单，渲染成文本消息推送到 WhatsApp：

1. **告警未清除** —— `alarm_clear_time` 为空。实测该列为空**只有 NULL 一种**形态
   （74 行；空串/`'None'` 均 0 行），细节与保留防御分支的理由见 `UNCLEARED_SQL`。
2. **告警码在白名单内** —— 白名单为空表示不过滤。99933 是「免推单」码，
   默认不在白名单里故被排除（见下方「为什么告警码在 Python 侧过滤」）。
3. **`ticket_severity = P1`** —— 大小写/前后空格不敏感。
4. **近 3 小时内** —— 按 `alarm_occur_time` 取窗口，见下方「时间窗口」。

命中的单落库到 `eflow_tt_whatsapp_alert_log`；**发送成功后**该行 `send_status='Y'`。

## 重推语义（20 分钟）

`is_due()` 决定同一单本轮是否发送：日志表无该单 → 发（首次）；`send_status != 'Y'`
→ 发（上轮失败重试）；距 `last_send_time` 达 `TT_ALERT_RESEND_MINUTES`（默认 20）分钟
→ 发；否则跳过。即 20 分钟是**重推节流下限，与单子是否更新无关**：工单没更新也照推，
更新了也要等过节流。15 分钟调度 × 20 分钟节流 ⇒ 实际约每 30 分钟重推一次。

## 配置（环境变量 > 配置文件 > 内置默认）

可配置项为**时间窗 / 重推间隔 / 级别 / 告警码白名单 / 目标群组**，页面上维护在
Settings →「任务配置」→ `eFlow P1 Alarm WhatsApp Push`
（文件 `tt_alert_whatsapp_config.json`）。读盘、归一化与「留空」语义见
`tt_alarm_config.py`；本文件只在**导入期**接收结果，故改页面后需等 worker 重启。

## 为什么告警码必须在 Python 侧过滤（不能写进 SQL）

`eflow_tt.alarm_code` 在库里有**多种形态**（2026-09-28 全表实测）：
`'99933'`（2159 行）与 `'99933.0'`（16599 行）并存，还有 `'9920'` / `'9920.0'`
这类混合形态。若写 `alarm_code <> '99933'` 会把 `'99933.0'` 全部漏过；
写 `CAST(alarm_code AS INTEGER)` 又会在非数字告警码上抛错
（库里存在 `'Ethernet Physical (ETPI) Receive bandwidth usage rate threshold crossed'`
这类文本告警码）。故统一走 `norm_alarm_code()` 归一化后在 Python 侧判等。
（同一坑在 `backend/services/tt_postmortem/__init__.py:85` 的 `_norm_alarm_id` 已有先例。）

## 时间窗口

**锚点字段确认为 `alarm_occur_time`（告警发生时间）** —— 业务口径如此。
不要改成 `created_time`（工单创建）或 `last_modified_time`（最后变更）：三者选错
**不会报错**，只会静默漏单/多单。
`test_window_anchor_is_alarm_occur_time_not_created_or_modified` 用三张时间字段
互相矛盾的单锁死了这一点。

该列在库中是 `'YYYY-MM-DD HH:MM:SS'` 文本，字典序即时间序，可直接字符串比较
（与 `backend/routers/portal_qc.py:123-127` 一致）。为空或不可解析的行不入选。

> ⚠️ **实测（2026-09-28）**：「未清除 + P1」的单绝大多数是历史遗留老单（最新一单
> occur 于 2026-06-24），故正常情况下**每轮通常发出 0 条消息** —— 这是数据分布
> 决定的正常结果，不是故障。要放宽推送面（如纳入 P2 断站单）改级别配置即可。
>
> ⚠️ **本期交付边界**：扩展侧的**纯文本发送**尚未实现（现有扩展只发图片）。在补齐
> 之前任务会正常投递作业但无人认领 → `send_status` 停在 `'N'` 并记录 `last_error`，
> **不会伪造 `'Y'`**。宁可状态如实为未发送，也不写假成功。

## 模块拆分

本文件只保留**业务口径与调度**（取数 / 节流 / 落库 / 编排）：渲染纯函数在
`tt_alarm_message.py`（可脱离数据库单测），作业文件状态机在 `tt_alarm_job.py`，
配置解析在 `tt_alarm_config.py`。
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names
from backend.services import tt_alarm_config as config_mod
from backend.services import tt_alarm_store as store
from backend.services.tt_alarm_config import DEFAULT_GROUPS, load_config
from backend.services.tt_alarm_job import (
    JOB_FILE,
    WAIT_SECONDS,
    claim_pending_job,
    complete_job,
    dispatch,
    read_job,
    wait_for_job_result,
)
from backend.services.tt_alarm_message import (
    build_tt_message,
    dash as _dash,
    norm_alarm_code,
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

WINDOW_MINUTES = _CFG["window_minutes"]    # 时间窗（分钟），按 alarm_occur_time 取
RESEND_MINUTES = _CFG["resend_minutes"]    # 重推节流（分钟）
QUERY_LIMIT = _CFG["query_limit"]          # 采样上限（防静默截断）
SEVERITIES = _CFG["severities"]            # 级别白名单；空集 = 不过滤（所有级别）
ALARM_CODES = _CFG["alarm_codes"]          # 告警码白名单；空集 = 不过滤（所有码）
GROUPS = _CFG["groups"]                    # 目标群组；留空时已回退到 DEFAULT_GROUPS
GROUPS_FALLBACK = _CFG["groups_fallback"]  # True = 正发往测试群，调用方须显式告警
DEFAULT_GROUPS = config_mod.DEFAULT_GROUPS
SAMPLE_LIMIT = 3                           # 结果里附带的消息样例上限
# 分析引擎的输出语言。告警消息发给利比里亚现场团队，历史上群里用的是英文，
# 故默认 en（引擎支持 zh/en，见 whatsapp-kb-bot/scripts/tt-analyze.py:77）。
ANALYZE_LANG = os.environ.get("TT_ALERT_LANG", "en")
# 各项最终来源（env / file / default），供排障解释"为何页面值与实际不符"
CONFIG_SOURCES = {k: v for k, v in _CFG.items() if k.endswith("_from")}

LOG_TABLE = store.LOG_TABLE
LOG_TABLE_INDEX = store.LOG_TABLE_INDEX

# 「未清除」口径：`alarm_clear_time` 为空。与 `backend/routers/portal_qc.py:93-100`
# 的 `_TT_UNCLEARED` 逐字一致 —— 两处必须同源，各写一份必然分叉。
#
# ⚠️ 实测（2026-09-28，全表 36348 行逐口径核对）：为空的形态**只有 NULL 一种**
# （IS NULL=74 行；空串 / TRIM 后为空 / 'None' / 'nan' 全为 0 行），故当前数据上
# 等价于 `alarm_clear_time IS NULL`。保留 `OR TRIM(...)=''` 是**防御性**的：
# 空串现在为 0 行，但上游导出换版后可能出现，届时纯 IS NULL 会静默漏单，
# 而多判一种空形态不改变现有命中集。若确认上游永不出空串，可简化并同步改 portal_qc。
UNCLEARED_SQL = "(alarm_clear_time IS NULL OR TRIM(CAST(alarm_clear_time AS TEXT)) = '')"


def _parse_ts(val: Any) -> Optional[datetime]:
    """解析 eflow_tt 的时间文本（'YYYY-MM-DD HH:MM:SS'），失败返回 None。"""
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
# 建表
# ==========================================================
def ensure_log_table(conn) -> None:
    """幂等建表 + 建索引（双模：sqlite / PG）。实现见 tt_alarm_store.ensure_log_table。"""
    store.ensure_log_table(conn, LOG_TABLE)


# ==========================================================
# 取数
# ==========================================================
# 本模块要读的列。取数时与 eflow_tt 实际列求交集，以兼容不同同步版本的列差异。
_TT_COLUMNS = (
    "tt_no", "site_id", "site_name", "title", "alarm_code", "alarm_severity",
    "alarm_type", "alarm_category", "alarm_description", "ticket_severity", "status",
    "alarm_occur_time", "alarm_clear_time", "created_time", "last_modified_time",
    "region_level1", "site_type", "site_information", "asset_id", "impacted_service",
    "down_site_count", "site_outage", "vip_site",
    "ne_name", "ne_id", "specific_problem",
    "sub_alarm_ne_name", "sub_alarm_ne_ip",
    "sub_alarm_name", "alarm_reason_type", "domain",
)


def _is_sqlite(conn) -> bool:
    import sqlite3
    return isinstance(conn, sqlite3.Connection)


def _available_columns(conn) -> List[str]:
    """eflow_tt 实际存在的列 ∩ 我们要读的列（兼容不同同步版本的列差异）。"""
    if _is_sqlite(conn):
        present = {r[1] for r in conn.execute("PRAGMA table_info(eflow_tt)").fetchall()}
    else:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ? "
            "AND table_schema = ANY(current_schemas(false))",
            ("eflow_tt",),
        ).fetchall()
        present = {r[0] for r in rows}
    return [c for c in _TT_COLUMNS if c in present]


def fetch_candidate_tts(now: Optional[datetime] = None,
                        window_minutes: Optional[int] = None) -> tuple:
    """取候选单（未清除 + 级别匹配 + 时间窗口内）。

    返回 ``(rows, meta)``：
      * rows —— list[dict]，已按 alarm_occur_time 倒序；
      * meta —— {window_since, limit, truncated, scanned, excluded_alarm_codes, severity_filter}

    级别与 `alarm_code != 99933` 的过滤在**Python 侧**做（原因见模块 docstring）。
    为让「扫描量」可控，SQL 侧用 limit 且 limit 取显著大于真实候选量的值；
    若命中上限则在 meta 里显式标记 `truncated`，不静默截断。
    """
    now = now or datetime.now()
    minutes = WINDOW_MINUTES if window_minutes is None else int(window_minutes)
    since = (now - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")

    meta = {
        "window_since": since,
        "window_minutes": minutes,
        "limit": QUERY_LIMIT,
        "truncated": False,
        "scanned": 0,
        "excluded_alarm_codes": sorted(ALARM_CODES),
        "severity_filter": sorted(SEVERITIES),
    }

    with get_raw_connection() as conn:
        if "eflow_tt" not in set(list_table_names(conn)):
            raise RuntimeError("eflow_tt 表不存在（数据未同步？）")
        cols = _available_columns(conn)
        if not cols:
            raise RuntimeError("eflow_tt 缺少所需列")

        # SQL 侧只下推「未清除 + 时间窗口」两个可安全表达的谓词。
        sql = (f"SELECT {', '.join(cols)} FROM eflow_tt "
               f"WHERE {UNCLEARED_SQL} AND alarm_occur_time >= ? "
               "ORDER BY alarm_occur_time DESC LIMIT ?")
        cur = conn.execute(sql, (since, QUERY_LIMIT))
        names = [d[0] for d in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]

    meta["scanned"] = len(rows)
    if len(rows) >= QUERY_LIMIT:
        meta["truncated"] = True
        logger.warning("[TTAlert] 候选单达到采样上限 %s，结果可能被截断", QUERY_LIMIT)

    picked: List[Dict[str, Any]] = []
    for r in rows:
        # 级别白名单：空集表示不过滤（推送所有级别）。
        # ⚠️ 必须显式判 `SEVERITIES and ...` —— 写成 `if sev not in SEVERITIES: continue`
        #    时，空集会让**每一行**都被 continue 掉（`x in set()` 恒为 False），
        #    结果是"留空 = 一条都不发"，与页面标注的"留空=所有级别"完全相反。
        if SEVERITIES and _s(r.get("ticket_severity")).upper() not in SEVERITIES:
            continue
        code = norm_alarm_code(r.get("alarm_code"))
        # 告警码白名单：空集表示不过滤（全部推送）
        if ALARM_CODES and code not in ALARM_CODES:
            continue
        # alarm_occur_time 必须可解析（窗口判定依据）
        if _parse_ts(r.get("alarm_occur_time")) is None:
            continue
        r["_alarm_code_norm"] = code
        picked.append(r)

    logger.info("[TTAlert] 窗口 %s 起，扫描 %s 行，命中 %s 单（级别 %s，告警码白名单 %s）",
                since, meta["scanned"], len(picked),
                sorted(SEVERITIES) or "全部", sorted(ALARM_CODES) or "全部")
    return picked, meta


# ==========================================================
# 节流判定（纯函数，便于单测）
# ==========================================================
def is_due(record: Optional[Dict[str, Any]], now: datetime,
           resend_minutes: Optional[int] = None) -> bool:
    """依据日志记录判断该单本轮是否应发送。

    record 为 None（首次）→ True；上一轮未成功（send_status != 'Y'）→ True；
    距 last_send_time 已达重推间隔 → True；否则 False。
    """
    if not record:
        return True
    if _s(record.get("send_status")).upper() != "Y":
        return True
    last = _parse_ts(record.get("last_send_time"))
    if last is None:
        return True
    minutes = RESEND_MINUTES if resend_minutes is None else int(resend_minutes)
    return (now - last) >= timedelta(minutes=minutes)


def select_due_tts(rows: Iterable[Dict[str, Any]], records: Dict[str, Dict[str, Any]],
                   now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """筛出本轮需要发送的单（保持输入顺序，即 alarm_occur_time 倒序）。"""
    now = now or datetime.now()
    return [r for r in rows if is_due(records.get(_s(r.get("tt_no"))), now)]


def load_records(conn, tt_nos: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """批量读日志表（tt_no → 记录）。见 tt_alarm_store.load_records。"""
    return store.load_records(conn, tt_nos, LOG_TABLE)


# ==========================================================
# 状态落库
# ==========================================================
def record_result(row: Dict[str, Any], ok: bool, error: str = "",
                  existing: Optional[Dict[str, Any]] = None) -> None:
    """写入/更新一条发送记录。

    成功：`send_status='Y'`、`send_count`+1、`last_send_time=now`、快照 `last_tt_modified`。
    失败：`send_status='N'`、`send_count` **不变**（失败不计入发送次数）、`last_error` 记原因。
    """
    with get_raw_connection() as conn:
        ensure_log_table(conn)
        store.record_result(conn, row, ok, error, existing, LOG_TABLE)


# ==========================================================
# 任务入口
# ==========================================================
def run_tt_alarm_whatsapp_alert() -> Dict[str, Any]:
    """每 15 分钟执行：取 P1 未清除单 → 节流筛选 → 渲染 → 投递 → 等回报 → 落库。

    返回结构化结果，供任务管理页展示。**零候选是成功**（`sent=0`），不是失败。
    """
    started = time.time()
    out: Dict[str, Any] = {
        "success": False, "candidates": 0, "due": 0, "dispatched": 0,
        "groups": list(GROUPS), "group_fallback": GROUPS_FALLBACK,
        "job_id": None, "samples": [], "errors": [], "elapsed_seconds": 0,
        "degraded": 0,
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

        rows, meta = fetch_candidate_tts()
        out["candidates"] = len(rows)
        out["window_since"] = meta["window_since"]
        if meta.get("truncated"):
            out["errors"].append(f"候选单达到采样上限 {meta['limit']}，结果可能被截断")

        # 建表**必须无条件执行**，不能只在「有候选单」时做：
        # 实测正常情况下每轮候选为 0（未清除的 P1 单多是历史遗留，不在 3 小时窗口内），
        # 若把建表放进 `if rows:` 分支，日志表将永远建不出来 —— 运维查
        # /api/whatsapp/tt-alert/log 会直接报表不存在，直到某天真有单时才发现。
        with get_raw_connection() as conn:
            ensure_log_table(conn)
            records = load_records(conn, [_s(r.get("tt_no")) for r in rows]) if rows else {}

        if not rows:
            out["success"] = True
            out["message"] = f"窗口 {meta['window_since']} 起无符合条件的未清除告警单"
            return _finish()

        due = select_due_tts(rows, records)
        out["due"] = len(due)
        if not due:
            out["success"] = True
            out["message"] = (f"候选 {len(rows)} 单，均在 {RESEND_MINUTES} 分钟重推节流内，本轮不发")
            return _finish()

        messages = []
        degraded: List[str] = []
        for r in due:
            text, reason = render_message_ex(r, lang=ANALYZE_LANG)
            messages.append({"tt_no": _s(r.get("tt_no")), "text": text})
            if reason:
                degraded.append(f"{_s(r.get('tt_no'))}（{reason}）")
        out["samples"] = [{"tt_no": m["tt_no"], "text": m["text"]}
                          for m in messages[:SAMPLE_LIMIT]]
        out["degraded"] = len(degraded)
        if degraded:
            # 降级会让消息从 ~30 行缩成 6 行，且**不报错**（照样发得出去）。
            # 群里的人只会觉得「这次信息怎么这么少」，故必须在任务结果里显式暴露。
            out["errors"].append(
                f"以下 {len(degraded)} 单已降级为头部摘要（分析引擎不可用）："
                + "; ".join(degraded[:5])
                + ("…" if len(degraded) > 5 else ""))

        disp = dispatch(messages, GROUPS)
        out["job_id"] = disp.get("job_id")
        out["dispatched"] = disp.get("dispatched", 0)
        out["errors"].extend(disp.get("errors") or [])

        if not disp.get("ok"):
            # 作业都没投出去：全部记失败，绝不置 'Y'
            for r in due:
                try:
                    record_result(r, ok=False,
                                  error="; ".join(disp.get("errors") or ["投递失败"]),
                                  existing=records.get(_s(r.get("tt_no"))))
                except Exception:  # noqa: BLE001
                    logger.warning("[TTAlert] 写失败状态异常 tt_no=%s", r.get("tt_no"),
                                   exc_info=True)
            # 作业连投都没投出去，同样属于"告警没发出去"，必须走降级告警通道（见下）。
            out["warnings"].append(
                f"本轮 {len(due)} 单 P1 告警**投递失败**，值班群没有收到："
                + "; ".join(str(e) for e in (disp.get("errors") or ["投递失败"]))
            )
            return _finish()

        # 等扩展回报：只有**确认真实发出**的单才置 'Y'
        logger.info("[TTAlert] 作业 %s 已投递，等待扩展回报（最长 %ds）…",
                    disp["job_id"], WAIT_SECONDS)
        rep = wait_for_job_result(disp["job_id"])
        out["confirmed"] = rep["confirmed"]
        out["timed_out"] = rep["timed_out"]
        out["sent_count"] = len(rep["sent"])
        out["errors"].extend(rep["errors"])

        sent_ids = {_s(x) for x in rep["sent"]}
        ok_count, fail_count = 0, 0
        for r in due:
            tt_no = _s(r.get("tt_no"))
            try:
                if rep["confirmed"] and rep["ok"] and tt_no in sent_ids:
                    record_result(r, ok=True, existing=records.get(tt_no))
                    ok_count += 1
                else:
                    err = ("; ".join(rep["errors"])
                           or ("扩展未确认该单发送成功" if rep["confirmed"] else "未获扩展回报"))
                    record_result(r, ok=False, error=err, existing=records.get(tt_no))
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
            out["message"] = f"扩展已回报但无成功单（成功 0 / 失败 {fail_count}）"
        else:
            out["message"] = f"作业已投递但未获扩展回报（{fail_count} 单保持未发送）"

        # **告警没发出去必须吵**（2026-10-01 事故）。
        # 走到这里说明本轮有 due 单却一条都没确认发出 —— 值班群实际收不到告警。
        # 此前这条路径只在 `errors` 里留一行文本：任务 success=False 时固然会告警，
        # 但**一旦扩展恢复、下一轮候选变 0，任务立刻回到 success=True**，
        # 于是"这几小时没发出去"就此埋掉，无人复盘（实测 04:15~04:55 连续 4 轮
        # 告警未达，群里静默，而 07:00 后监控全绿）。
        # 故显式产出一条 warnings，交给 task_runner 的降级通道主动通知。
        if ok_count == 0 and fail_count > 0:
            out["warnings"].append(
                f"本轮 {fail_count} 单 P1 告警**均未确认发送**，值班群可能没收到"
                f"（job={disp.get('job_id')}；{out['message']}）。"
                f"请确认 Chrome 已打开并登录 WhatsApp Web、扩展已启用且能发纯文本"
            )

    except Exception as e:  # noqa: BLE001
        logger.exception("[TTAlert] 任务执行失败")
        out["errors"].append(f"{type(e).__name__}: {e}")

    return _finish()


__all__ = [
    "GROUPS", "WINDOW_MINUTES", "RESEND_MINUTES", "QUERY_LIMIT", "SEVERITIES",
    "ALARM_CODES", "DEFAULT_GROUPS", "GROUPS_FALLBACK", "CONFIG_FILE", "CONFIG_SOURCES",
    "LOG_TABLE", "JOB_FILE", "UNCLEARED_SQL", "SAMPLE_LIMIT", "CONFIG_FILE",
    "ensure_log_table", "fetch_candidate_tts", "is_due", "select_due_tts", "load_records",
    "record_result", "run_tt_alarm_whatsapp_alert", "norm_alarm_code",
    "claim_pending_job", "complete_job", "read_job", "dispatch",
    "wait_for_job_result", "_s", "_dash", "_parse_ts", "ANALYZE_LANG",
    # 渲染入口转发（实现在 tt_alarm_render；调用方常只 import 本模块）
    "render_message_ex", "render_tt_analysis", "render_with_reason",
    # 降级模板（实现在 tt_alarm_message；对外保留别名，既有测试与调用方依赖它）
    "build_tt_message",
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
    print("窗口(分钟):", WINDOW_MINUTES, " 重推节流(分钟):", RESEND_MINUTES)
    print(json.dumps(run_tt_alarm_whatsapp_alert(), ensure_ascii=False, indent=2))

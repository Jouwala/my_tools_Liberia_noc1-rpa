# -*- coding: utf-8 -*-
"""
只读 NL2SQL 服务（Data Agent 原型）

定位
----
把「自然语言 → 只读 SQL → 结果」做进 TableBrowser，**不触碰任何生产报表链路**。
失败只影响一个探索性页面。

三条设计原则
------------
1. **表/列白名单由服务端提供，模型不猜。**
   实测发现 `eflow_tt` 同时存在于 `app`(36,226 行/161 列/snake_case)
   与 `eflow`(28,455 行/161 列/Title Case) 两个 schema，列名分叉
   （`title` vs `Title`、`site_name` vs `Site Name`）。
   若让模型自由生成 SQL，查错 schema**不报错，只是数字不一样** —— 这是最危险的失败模式。
   因此这里先取真实列元数据喂给模型，再用 `sql_guard` 白名单复验。

2. **护栏是服务端强制的，不依赖模型自觉。**
   生成结果一律过 `validate_sql()`；任何写操作/多语句/schema 前缀/未知表都被拒绝。

3. **结果自带 SQL 与行数。**
   LLM 可能生成「语法正确、语义错误」的 SQL，这无法自动消除。
   把实际执行的 SQL 一起返回，用户能自行核对 —— 而不是盲信一段自然语言结论。

api_key 处理沿用既有约定（与 `incident_ai_service.py` 一致）：
由前端请求体传入，服务端**不落盘、不写日志**。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.database import get_raw_connection, list_tables
from backend.services.sql_guard import (
    DEFAULT_LIMIT, SqlGuardError, _strip_literals, enforce_limit, validate_sql,
)

logger = logging.getLogger(__name__)

# 喂给模型的表清单上限：避免把上百张表的全部列塞进 prompt 撑爆上下文。
#
# ⚠️ 上限值与「可见表排序」必须一起看（2026-11-03）：app schema 有 78 张表，
# 上限 60 意味着**必然丢掉 18 张**。排序修好后核心表都排前面，但为了不让
# eflow_pm / cm_cell_data 这类次核心表也被砍掉，这里放宽到 80 —— 实测 schema
# 文本约 12K tokens，在 32K 上下文的模型上完全放得下，且每次查询只多几秒。
MAX_TABLES_IN_PROMPT = 80
# 非核心表每张展示多少列。
# ⚠️ 40 → 60（2026-11-04）：40 列时连「级别」「发生时间」这类最常问的字段
# 都可能被截掉（history_alarm 的 perceivedseverity 在第 57 列）。
MAX_COLS_PER_TABLE = 60

#: 核心表允许展示**全部列**（列数再多也全给）。
#: history_alarm 有 175 列，全给约 1.1K tokens，换来模型能写对列名 ——
#: 比省这点 token 值得多（列名猜错 = SQL 直接失败，2026-11-04 实测）。
MAX_COLS_CORE_TABLE = 400

#: 列展示优先级（**顺序即权重**）。这些是运维高频问的字段，必须让模型看见，
#: 否则模型只能瞎猜列名。
#:
#: 2026-11-04 实测教训：history_alarm 按物理序截断到 40 列时，
#: perceivedseverity(57) / perceivedseverityname(112) / alarmcode(50) /
#: alarmraisedtime(66) / servertime(82) / tt_id(84) / region(101)
#: **全部在截断线之外** —— 模型看不到「级别」列，就写出了
#: `WHERE alarm_level = 1`，报「字段 alarm_level 不存在」。
_PRIORITY_COL_TOKENS = (
    "severity",
    "occur",
    "raised",
    "servertime",
    "server_time",
    "cleared",
    "clear_time",
    "alarmcode",
    "alarm_code",
    "codename",
    "site_name",
    "sitename",
    "status",
    "state",
    "region",
    "province",
    "tt_no",
    "tt_id",
    "wo_no",
    "alarm_title",
    "title",
    "level",
    "priority",
    "count",
    "time",
    "date",
)


#: 列的**时间格式语义**标注。写错不会报错，只会**静默返回 0 行** ——
#: 2026-11-04 实测：模型把 history_alarm 的毫秒时间戳当日期串比，
#: 「最近 7 天 Critical 告警」答成 0 条，而正确答案是 766 条。
#:
#: 值：
#:   "ms_epoch"      13 位毫秒时间戳（数字字符串）—— 比较前必须数值化
#:   "text_datetime" 'YYYY-MM-DD HH24:MI:SS' 文本 —— 可直接与日期串比较
_SPECIAL_COL_HINTS = {
    "history_alarm": {
        "alarmraisedtime": "ms_epoch",
        "servertime": "ms_epoch",
        "alarmclearedtime": "ms_epoch",
        "historyservertime": "ms_epoch",
        "alarmchangedtime": "ms_epoch",
        "assigned_time": "text_datetime",
    },
    # realtime_alarm 与 history_alarm 同源，时间列同样是毫秒时间戳
    # （实测 servertime = 1793777863631）。
    "realtime_alarm": {
        "alarmraisedtime": "ms_epoch",
        "servertime": "ms_epoch",
        "alarmclearedtime": "ms_epoch",
        "historyservertime": "ms_epoch",
        "alarmchangedtime": "ms_epoch",
        "assigned_time": "text_datetime",
    },
    "eflow_tt": {
        "created_time": "text_datetime",
        "alarm_occur_time": "text_datetime",
    },
    "eflow_wo": {
        "created_time": "text_datetime",
        "last_modified_time": "text_datetime",
        "alarm_occur_time": "text_datetime",
        "alarm_clear_time": "text_datetime",
    },
}


def _col_priority(name: str) -> int:
    """列名的展示优先级权重（越小越靠前）。"""
    n = str(name or "").lower()
    for i, tok in enumerate(_PRIORITY_COL_TOKENS):
        if tok in n:
            return i
    return len(_PRIORITY_COL_TOKENS)


def _is_core_table(t: str) -> bool:
    """是否核心业务表（核心表给全部列）。"""
    low = str(t or "").lower()
    return any(low.startswith(p) for p in _CORE_TABLE_PREFIXES)


#: 核心业务表前缀（**顺序即优先级**）。这些表是运维问答的主力数据源，
#: 必须优先进入模型的 schema 上下文 —— 见 `_visible_tables()` 的排序说明。
_CORE_TABLE_PREFIXES = (
    "eflow_",
    "history_alarm",
    "master_site_db",
    "vip_site_list",
    "cm_cell_data",
    "cm_site_summary",
    "victim_topology",
    "topology",
    "ipt_power_",
    "inventory_details",
    "transfer_details",
    "tt_",
    "wo_",
    "sp_",
    "task_",
)
# 单次对话保留的历史轮数
MAX_HISTORY = 3

# 备份/临时表名特征。
# 实测当前库里有 `kml_mw_links_bak_20260922_100914` 这类手工快照表
# （项目习惯 `_bak_<日期>_<说明>`，见 AGENTS.md 第三节原则 9）。
# 它们**不是**业务真相源：喂给模型会让它查到一个过期快照并给出「看起来对」的答案 ——
# 正是本模块要避免的失败模式。故从 NL2SQL 可见清单中排除（仍可在 TableBrowser 手工浏览）。
_NOISE_TABLE_RE = re.compile(
    r"(_bak(_\d{8})?$|_bak_\d{8}|_\d{8}_\d{4,6}$|_old$|_copy$|_tmp$|_temp$|_test$|_backup$)",
    re.IGNORECASE,
)


def _visible_tables() -> List[str]:
    """可见表清单：排除 `_` 前缀内部表与备份/临时表，**核心业务表优先**。

    `_` 前缀约定与 TableBrowser 一致（`backend/routers/tables.py:209`）。

    ⚠️ **排序是关键，不是可有可无的优化**（2026-11-03 修复）：
    ``list_tables()`` 返回的是**数据库物理顺序**，不是字母序。原实现直接取前
    ``MAX_TABLES_IN_PROMPT`` 张，结果前 60 张恰好是一堆 ``kml_mw_links`` /
    ``task_queue`` 之类的低频表，而 ``eflow_tt`` / ``eflow_wo`` / ``eflow_site`` /
    ``eflow_pm`` 这些**问答主力表全被截断在 60 张之外** —— 模型压根看不到 TT 表，
    自然写不出查 TT 的 SQL，「能问数据库」这件事在最核心的场景上是失效的。

    所以这里改成：**核心业务表排前面，其余按字母序**，让有限的 prompt 预算
    先花在真正会被问到的表上。
    """
    try:
        tables = [t for t in list_tables() if not t.startswith("_")]
    except Exception:  # noqa: BLE001
        logger.warning("[nl2sql] list_tables 失败", exc_info=True)
        return []
    tables = [t for t in tables if not _NOISE_TABLE_RE.search(t)]

    def _rank(t: str) -> tuple:
        for i, p in enumerate(_CORE_TABLE_PREFIXES):
            if t.startswith(p):
                return (i, t)
        return (len(_CORE_TABLE_PREFIXES), t)

    return sorted(tables, key=_rank)


def _column_metadata(conn, table_name: str) -> List[Dict[str, Any]]:
    """取列元数据，复用 `backend/routers/tables.py:116` 的双模实现。

    这里直接 import 复用，而不是重写一份 —— 保持「列元数据只有一个真相源」。
    """
    from backend.routers.tables import _column_metadata as impl
    return impl(conn, table_name)


def build_schema_context(max_tables: int = MAX_TABLES_IN_PROMPT) -> Tuple[str, List[str]]:
    """构造给模型的 schema 文本，返回 (schema_desc, 可用表名清单)。

    只包含表名 + 列名 + 类型，**不含任何数据行** —— 避免把业务数据送进第三方 API。
    """
    tables = _visible_tables()[:max_tables]
    if not tables:
        return "", []
    lines: List[str] = []
    with get_raw_connection() as conn:
        for t in tables:
            try:
                cols = _column_metadata(conn, t)
            except Exception:  # noqa: BLE001
                logger.warning("[nl2sql] 取列元数据失败: %s", t, exc_info=True)
                continue
            if not cols:
                continue
            # ⚠️ 展示顺序 = **优先级排序**，不是物理序。
            # 宽表（history_alarm 175 列）按物理序展示时，级别/时间/编号这些
            # 高频字段全在截断线之外，模型看不见就瞎猜列名（见 _col_priority）。
            ordered = sorted(cols, key=lambda c: (_col_priority(c["name"]),))
            limit = MAX_COLS_CORE_TABLE if _is_core_table(t) else MAX_COLS_PER_TABLE
            shown = ordered[:limit]
            col_txt = ", ".join(
                "{}{}".format(c["name"], "" if (c.get("type") or "") == "" else f" {c['type']}")
                for c in shown
            )
            if len(ordered) > len(shown):
                col_txt += f" ...(共 {len(ordered)} 列)"
            # ⚠️ 给时间列**标注格式**。写错格式不会报错，只会静默返回 0 行 ——
            # 模型看不到格式就按「日期字符串」猜，答案会安静地变成 0。
            hints = _SPECIAL_COL_HINTS.get(t.lower(), {})
            if hints:
                marked = []
                for c in shown:
                    h = hints.get(c["name"].lower())
                    t_suffix = "" if (c.get("type") or "") == "" else f" {c['type']}"
                    marked.append(
                        f"{c['name']}{t_suffix}" + (f" [{h}]" if h else "")
                    )
                col_txt = ", ".join(marked)
            lines.append(f"- {t}({col_txt})")
        conn.close()
    return "\n".join(lines), tables


SYSTEM_PROMPT = """You are a SQL generator for a PostgreSQL data platform.

RULES (must follow, no exceptions):
1. Output ONLY one read-only SQL statement. Start with SELECT or WITH.
2. NEVER write INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/COPY/SET/CALL.
3. Only use tables and columns from the SCHEMA below. Never invent names.
4. Never prefix a table with a schema (write `eflow_tt`, NOT `app.eflow_tt`).
5. Use double quotes for identifiers that contain spaces or uppercase letters.
6. Add a LIMIT clause (max 1000).
7. Output the SQL only - no explanation, no markdown fences.

8. ⚠️ **TIME COLUMNS ARE NOT ALL THE SAME FORMAT - getting this wrong silently
   returns 0 rows instead of an error.** You MUST follow the per-column hints
   given in the SCHEMA below:
   - A column marked `ms_epoch` holds a **13-digit millisecond epoch as a
     numeric string** (e.g. '1793760098000'). It is NOT a date string and NOT a
     timestamp. **Both sides of a comparison must have the same type.**
     Convert the column to a timestamp with to_timestamp():
       WHERE to_timestamp(alarmraisedtime::bigint / 1000.0) >= now() - interval '7 days'
     or convert the threshold to millis:
       WHERE (CASE WHEN alarmraisedtime ~ '^[0-9]+$' THEN alarmraisedtime::bigint END)
             >= (extract(epoch from now() - interval '7 days') * 1000)::bigint
     NEVER write `servertime >= now() - interval '7 days'` (bigint vs timestamptz
     -> type error) and NEVER write `date_trunc('day', servertime)` (date_trunc
     does not accept bigint).
   - A column marked `text_datetime` holds 'YYYY-MM-DD HH24:MI:SS' and can be
     compared directly:
       WHERE created_time >= to_char(now() - interval '7 days', 'YYYY-MM-DD HH24:MI:SS')

9. ⚠️ **SYSTEM / MODULE NAMES ARE NOT DATA VALUES - never filter on them.**
   The question often names the SYSTEM or MODULE being asked about
   (e.g. "my_app", "Data Insight", "task manager", "kb bot"). Those words are
   CONTEXT, not data. NEVER turn them into a WHERE filter:
     -- WRONG (this is the #1 cause of silently-empty results):
     WHERE task_id ILIKE '%my_app%' OR task_name ILIKE '%my_app%'
     WHERE site_name ILIKE '%my_app%'
     -- RIGHT: pick the table that holds that system's data, and don't filter:
     SELECT ... FROM task_execution_log WHERE success = 1
   Reason: no column in this platform stores a value like 'my_app' /
   'task manager' / 'data insight', so such a filter matches **0 rows** and
   the answer silently becomes "no records" even though the data is there.
   If the user says "my_app's tasks" / "the task manager", just SELECT from the
   relevant table and apply only REAL conditions (time range, status, site).
   If a genuine filter IS needed on some other column (a real site name, a
   real task name, a status), filter on THAT value - never on the system name.

If the request cannot be answered with the given schema, output exactly:
CANNOT_ANSWER: <short reason>

KEY TABLE SEMANTICS (pick the RIGHT table - the two alarm tables are NOT the same):
- history_alarm  : 历史告警**记录**（已发生的告警，带清除时间）。问「最近/过去 N 天有多少条告警」
                   「某站历史上有哪些告警」→ 用这张。
- realtime_alarm : 当前**活动**告警（还没闭环的）。问「现在有多少告警」「当前未处理告警」→ 用这张。
- eflow_tt      : TT 告警工单（工单号、状态、处理人、SLA）。
- eflow_wo      : WO 工作单（现场维修单、SLA 剩余、根因诊断）。
- eflow_site    : 站点主数据（站名、类型、VIP、枢纽站、区域）。
- ipt_power_sites / ipt_power_snapshots : 站点供电状态与读数。

SCHEMA:
{schema}
"""


def _extract_sql(text: str) -> str:
    """从模型输出里抠出 SQL。

    模型即使被要求「只输出 SQL」，仍可能带 ```sql 围栏或一句解释 —— 这是实测常见行为，
    所以这里做容错提取，而不是指望 prompt 完全约束住它。

    ⚠ 2026-10-05 修正（真实故障：`错误: 语法错误 在 "AND" 或附近的 ... LINE 5`）
    --------------------------------------------------------------------------
    原实现是「无脑从第一个 `\\b(select|with)\\b` 处截断」。问题在于 `with` 是**普通英文词**：
    模型常先写一句解释，例如

        I will build this by joining tickets with their alarm records.
        ```sql
        SELECT ... FROM eflow_tt ... LIMIT 10
        ```
        AND created_time > alarm_clear_time

    正则命中的是散文里的 `with`，于是**围栏被绕过、散文被当成 SQL 开头**，
    残留的尾句就成了悬空的 `AND created_time > alarm_clear_time`。更糟的是，截取结果
    以 `with` 开头，能**通过** sql_guard 的 `SELECT|WITH` 白名单（`sql_guard.py:216`），
    直到真正执行才在数据库层炸掉 —— 用户看到的是 PG 的原始语法错误，完全无从下手。

    现按可靠性从高到低取来源：
      1. **代码围栏**（```sql / ```）：模型明确标注的 SQL，最可信，直接取内容；
      2. **行首锚定**：找真正以 SELECT / WITH 开头的**行**，且要求 `with` 后紧跟
         `RECURSIVE`/标识符+`AS`（CTE 形态），避免散文里的 `with` 被误判；
      3. 都没有 → 返回原文，交给 sql_guard 拒绝（宁可明确拒绝，不可猜错后误执行）。
    """
    if not text:
        return ""
    t = text.strip()

    # ① 代码围栏：优先取带 sql 标注的围栏，退而取任意围栏
    for pat in (r"```sql\s*(.+?)```", r"```\s*(.+?)```"):
        fence = re.search(pat, t, re.IGNORECASE | re.DOTALL)
        if fence:
            body = fence.group(1).strip()
            if body:
                return body.strip().rstrip(";").strip()

    return _anchor_statement(t).strip().rstrip(";").strip()


def _anchor_statement(text: str) -> str:
    """无围栏时：按「行首」锚定语句起点，避免命中散文中的 with/select。

    返回从锚点起的全部内容（含后续行）——多行 SQL 必须整段保留。
    """
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # CTE：with 后面必须跟 recursive 或「标识符 + as」(，排除散文里的 with
        if re.match(r"(?i)^with\s+(recursive\s+)?[\w\"`\[\]]+\s+as\s*\(", stripped):
            return "\n".join(lines[idx:])
        # 普通语句：整行以 select 开头（允许前导括号，如 (SELECT ...)）
        if re.match(r"(?i)^\(?\s*select\b", stripped):
            return "\n".join(lines[idx:])
    # 没有任何行首锚点：原样返回，让 sql_guard 去拒绝
    return text


class Nl2SqlError(ValueError):
    """NL2SQL 流程错误：携带适合展示给用户的中文原因。"""


def _strip_sql_comments(sql: str) -> str:
    """剥离 SQL 的行注释（``--``）与块注释（``/* */``），保留字符串字面量内容。

    ⚠️ **这不是锦上添花，是修一个真实的失败模式**（2026-11-03 实测）：
    模型偶尔会生成这种 SQL::

        SELECT ... FROM history_alarm
        WHERE site_name LIKE '%Wood Camp%'  -- 只看近 30 天
        AND historyservertime IS NOT NULL

    这里的 ``--`` 注释会把**它那一行之后**的内容当成注释吞掉，于是 WHERE 子句
    断在中间，PG 报「语法错误 在 "AND" 附近的」，而 ``LINE 5`` 指到的位置
    离真正的原因（上面那行注释）隔了好几行 —— **回传报错让模型自己改，它改不对**
    （实测重试一次仍然失败）。

    单引号字符串内的 ``--`` 不会被误删：这里做了引号状态机，并处理了 ``''`` 转义。
    """
    out = []
    i = 0
    n = len(sql)
    in_str = False
    while i < n:
        c = sql[i]
        if in_str:
            out.append(c)
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":   # '' 是转义的单引号
                    out.append(sql[i + 1])
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if c == "'":
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "-" and i + 1 < n and sql[i + 1] == "-":       # 行注释
            while i < n and sql[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and sql[i + 1] == "*":       # 块注释
            j = sql.find("*/", i + 2)
            if j == -1:
                i = n
                continue
            i = j + 2
            out.append(" ")                                 # 占位，避免把两行并成一行
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _db_error_brief(e: Exception) -> str:
    """把数据库异常压成一行、但**保留 LINE 位置**的短描述。

    PG 的报错是两行：
        错误:  语法错误 在 "AND" 或附近的
        LINE 5:      AND historyservertime IS NOT NULL
    只取第一行会丢掉「错在哪一行」—— 那正是模型改对 SQL 需要的信息。
    """
    text = str(e).strip()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return " | ".join(lines[:3])[:400]


#: ---------------------------------------------------------------- 系统名守卫
#:
#: **系统名 / 模块名不是数据值** —— 这一点必须由代码兜底，不能只靠 prompt。
#:
#: 2026-11-04 真实故障：用户问「my_app 的 task manager 有多少任务成功，多少失败」，
#: 模型生成
#:     WHERE task_id ILIKE '%my_app%' OR task_name ILIKE '%my_app%'
#: 而 `task_execution_log.task_name` 存的是中文任务名（"eFlow 实时告警同步"…），
#: 没有一条含 "my_app" → 命中 0 行 → 机器人自信地回答「没有匹配到任何记录」，
#: 而库里明明有 3 万多条执行记录。
#:
#: 词表是**实测筛出来的**，不是拍脑袋：
#:   - `my_app` / `data insight` / `task manager` / `kb bot`
#:     → 在 app schema 全部表的**标识类列**上命中数均为 **0**（2026-11-05 实测），
#:       它们是纯系统名/模块名，当过滤条件必然命中 0 行。
#:   - `eflow` / `whatsapp` **故意不收录** ——
#:     它们在数据里是**真值**（`task_execution_log.task_name` 有 12192 行含 "eflow"，
#:     `category` 列有 20408 行等于 "whatsapp"）。收录了会误伤正常查询。
#:
#: 判定只针对**标识类列**（排除 result_json / error / description 这类载荷列），
#: 因为载荷列里出现 "my_app" 是正常的（任务返回体里会带自己的模块名）。
_SYSTEM_NAME_TOKENS = (
    "my_app", "my app", "myapp",
    "data insight", "data_insight",
    "task manager", "task_manager",
    "kb bot", "kb_bot",
)

#: 载荷类列名特征 —— 这些列里出现系统名是**正常**的，不参与守卫判定。
_SYSTEM_NAME_EXEMPT_COL_PATTERNS = (
    "json", "error", "desc", "message", "content", "trace", "payload",
    "reason", "note", "comment", "remark", "detail", "body", "result",
    "title", "path", "log", "cmd", "command", "raw",
)

#: 形如 `col ILIKE '%my_app%'` / `col = 'my_app'` 的比较表达式。
_SYS_FILTER_RE = re.compile(
    r"""(?P<col>[A-Za-z_][\w.]*)\s*
         (?:ILIKE|LIKE|=|<>)\s*
         '(?P<val>[^']*)'""",
    re.IGNORECASE | re.VERBOSE,
)


def _normalize_name_token(s: str) -> str:
    """归一化一个名字：去分隔符 + 小写。

    `my_app` / `my app` / `my-app` / `MyApp` → 同一个 token `myapp`。
    """
    return re.sub(r"[\s_\-.]+", "", str(s or "")).lower()


#: 归一化后的系统名集合（比较时用）。
_SYSTEM_NAME_NORM = {_normalize_name_token(t) for t in _SYSTEM_NAME_TOKENS}


def _is_exempt_column(col: str) -> bool:
    """该列是否是「载荷列」（可以合法出现系统名，不参与守卫）。"""
    low = str(col or "").lower()
    return any(p in low for p in _SYSTEM_NAME_EXEMPT_COL_PATTERNS)


def detect_system_name_filter(sql: str) -> List[str]:
    """找出 SQL 里「拿系统名当数据值过滤」的片段。

    返回命中的列名列表（去重）。空列表 = 没有这个问题。

    ⚠️ 只在**标识类列**上判定，且只认「归一化后与系统名完全相等」的过滤值：
    `ILIKE '%my_app%'` 命中，但 `ILIKE '%eflow%'`（数据里的真值）不命中，
    `ILIKE '%my_app_task%'` 也不命中（那是别的词）。
    """
    if not sql:
        return []
    hits: List[str] = []
    for m in _SYS_FILTER_RE.finditer(sql):
        col = m.group("col")
        if _is_exempt_column(col):
            continue
        val = m.group("val")
        # 去掉 LIKE 通配符再比 —— `%my_app%` 与 `my_app` 是同一个意思
        core = val.strip().strip("%").strip()
        if not core:
            continue
        if _normalize_name_token(core) in _SYSTEM_NAME_NORM:
            hits.append(col)
    # 去重且保序
    seen = set()
    out = []
    for c in hits:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _split_top_level(clause: str, keyword: str) -> List[Tuple[int, int]]:
    """在 WHERE 子句里找出**顶层**（括号深度 0、字符串字面量外）的关键字位置。

    返回 [(start, end)]，end 是关键字**之后**的位置 —— 即切分点。
    """
    spans: List[Tuple[int, int]] = []
    depth = 0
    i = 0
    n = len(clause)
    in_str = False
    kw = keyword.upper()
    klen = len(kw)
    while i < n:
        ch = clause[i]
        if in_str:
            if ch == "'":
                if i + 1 < n and clause[i + 1] == "'":
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            i += 1
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth -= 1
            i += 1
            continue
        if depth == 0 and clause[i:i + klen].upper() == kw:
            before_ok = i == 0 or not (clause[i - 1].isalnum() or clause[i - 1] == "_")
            j = i + klen
            after_ok = j >= n or not (clause[j].isalnum() or clause[j] == "_")
            if before_ok and after_ok:
                spans.append((i, j))
                i = j
                continue
        i += 1
    return spans


def _find_where_span(sql: str) -> Optional[Tuple[int, int, int]]:
    """找出顶层 WHERE 子句的位置。

    返回 (where_kw_start, clause_start, clause_end)；
    找不到顶层 WHERE 时返回 None。

    clause_end 在下一个顶层子句关键字（GROUP BY / ORDER BY / LIMIT / …）之前。
    """
    upper = sql.upper()
    depth = 0
    i = 0
    n = len(sql)
    in_str = False
    kw_start = -1
    while i < n:
        ch = sql[i]
        if in_str:
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            i += 1
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth -= 1
            i += 1
            continue
        if depth == 0 and upper.startswith("WHERE", i):
            before_ok = i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")
            after_ok = i + 5 >= n or not (sql[i + 5].isalnum() or sql[i + 5] == "_")
            if before_ok and after_ok:
                kw_start = i
                clause_start = i + 5
                break
        i += 1
    if kw_start < 0:
        return None

    # 子句结束位置：下一个顶层关键字
    end = len(sql)
    depth = 0
    i = clause_start
    in_str = False
    while i < n:
        ch = sql[i]
        if in_str:
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            i += 1
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth -= 1
            i += 1
            continue
        if depth == 0:
            for kw in ("GROUP BY", "ORDER BY", "LIMIT", "HAVING", "UNION",
                       "INTERSECT", "EXCEPT", "WINDOW", "OFFSET", "FETCH"):
                if upper.startswith(kw, i):
                    before_ok = i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")
                    if before_ok:
                        end = i
                        break
            else:
                i += 1
                continue
            break
        i += 1
    return kw_start, clause_start, end


def _conjunct_is_system_filter(text: str) -> bool:
    """一个 AND 合取项是否「整体都在拿系统名过滤」。

    判定：文本里**所有**与字符串字面量的比较都是系统名过滤。
    没有任何比较（如 `EXISTS (...)`）→ False（不是系统名问题）。
    """
    found = False
    for m in _SYS_FILTER_RE.finditer(text):
        col = m.group("col")
        if _is_exempt_column(col):
            return False
        core = m.group("val").strip().strip("%").strip()
        if not core or _normalize_name_token(core) not in _SYSTEM_NAME_NORM:
            return False
        found = True
    return found


def strip_system_name_filters(sql: str) -> str:
    """把 WHERE 里「拿系统名当过滤值」的条件**剔除**，返回改写后的 SQL。

    为什么需要它
    ------------
    prompt 讲过了、模型也被明确告知过一次，仍然可能改不掉（模型记一半是常态，
    与 `_normalize_ms_epoch_compare` 面对的是同一类问题）。所以最后还有一道
    **确定性**的兜底：把这种条件直接删掉，让查询回到「只按真实条件过滤」。

    怎么删才不出错
    --------------
    SQL 布尔优先级是 AND > OR，所以 WHERE 子句要先按**顶层 OR** 切成分支，
    每个分支再按**顶层 AND** 切成合取项：
      - 分支里含被污染的合取项 → 把该合取项**删掉**（保留分支里真实的条件）
      - 删完分支空了 → 整个分支对结果没有贡献（真值 OR 分支恒为 FALSE）→ 删掉分支
      - 所有分支都空了 → 整个 WHERE 没有贡献 → **整个 WHERE 子句删掉**
    这样既不会把真实条件（时间、状态、真实站名）误删，也不会留下恒假条件。

    剥离不成功时返回原 SQL（宁可不动，也不能改坏）。
    """
    if not sql:
        return sql
    span = _find_where_span(sql)
    if not span:
        return sql
    kw_start, clause_start, clause_end = span
    clause = sql[clause_start:clause_end]
    if not clause.strip():
        return sql

    # 顶层 OR → 分支
    or_spans = _split_top_level(clause, "OR")
    branches: List[str] = []
    prev = 0
    for s, e in or_spans:
        branches.append(clause[prev:s])
        prev = e
    branches.append(clause[prev:])

    kept_branches: List[str] = []
    dropped_any = False
    for br in branches:
        if not br.strip():
            continue
        # 顶层 AND → 合取项
        and_spans = _split_top_level(br, "AND")
        conjuncts: List[str] = []
        prev = 0
        for s, e in and_spans:
            conjuncts.append(br[prev:s])
            prev = e
        conjuncts.append(br[prev:])
        kept = []
        for c in conjuncts:
            if not c.strip():
                continue
            if _conjunct_is_system_filter(c):
                dropped_any = True
                continue
            kept.append(c)
        if kept:
            kept_branches.append(" AND ".join(c.strip() for c in kept))

    # 什么都没剥离 → 原样返回。
    # ⚠️ 这一步不只是"省事"：重组会引入多余空格，让"没动过"的 SQL 文本发生变化。
    #   守卫必须满足「不该碰的，一个字节都不碰」—— 否则用户核对 SQL 时会看到
    #   莫名其妙的差异，无法判断到底改了什么。
    if not dropped_any:
        return sql

    if not kept_branches:
        # 所有分支都是系统名过滤 → 整个 WHERE 没有贡献，删掉整个子句
        head = sql[:kw_start].rstrip()
        tail = sql[clause_end:].lstrip()
        if not head:
            return tail
        if not tail:
            return head
        return f"{head} {tail}"

    new_clause = " OR ".join(kept_branches)
    return sql[:clause_start] + " " + new_clause + " " + sql[clause_end:]


def _system_filter_hint(cols: List[str]) -> str:
    """给模型的纠错提示：说清楚「系统名不是数据值」。"""
    col_txt = "、".join(f"`{c}`" for c in cols) if cols else "相关列"
    return (
        "你上一条 SQL 执行成功，但**结果为 0 行**，原因是过滤条件用错了。\n\n"
        f"你在 {col_txt} 上拿**系统名/模块名**做了过滤（如 ILIKE '%my_app%'）。\n"
        "但库里没有任何一列存着这样的值 —— 'my_app'、'task manager'、"
        "'data insight' 是**系统本身的名字**，不是数据值，"
        "拿它当过滤条件必然命中 0 行。\n\n"
        "请重新给出 SQL：\n"
        "1. **删掉**这些系统名过滤条件；\n"
        "2. 选对该数据所在的表（任务管理相关 → task_execution_log；"
        "工单 → eflow_wo；告警 → history_alarm / realtime_alarm）；\n"
        "3. 只保留真实存在的条件（时间范围、状态、真实站名等）。\n\n"
        "只输出 SQL，不要解释。"
    )


def generate_sql(question: str, provider: str, api_key: str,
                 model: str = "", base_url: str = "",
                 history: Optional[List[Dict[str, str]]] = None,
                 error_hint: str = "",
                 semantic_hint: str = "") -> Dict[str, Any]:
    """自然语言 → 校验通过的只读 SQL。不执行。"""
    question = (question or "").strip()
    if not question:
        raise Nl2SqlError("问题不能为空")
    if not api_key:
        raise Nl2SqlError("缺少 API key")
    if not provider:
        raise Nl2SqlError("缺少 AI provider")

    schema_desc, tables = build_schema_context()
    if not tables:
        raise Nl2SqlError("未找到可查询的表")

    system = SYSTEM_PROMPT.replace("{schema}", schema_desc)
    messages = [{"role": "system", "content": system}]
    for h in (history or [])[-MAX_HISTORY:]:
        q, s = (h or {}).get("question", ""), (h or {}).get("sql", "")
        if q and s:
            messages.append({"role": "user", "content": q})
            messages.append({"role": "assistant", "content": s})
    messages.append({"role": "user", "content": question})

    # 上一次生成的 SQL 执行失败时，把**数据库的真实报错**回传给模型让它自己改。
    # 这是最有效的纠错手段 —— 模型看不到自己的 SQL 报什么错时只能瞎猜，
    # 而「列不存在 / 语法错误」这类反馈通常一次就能纠正（2026-11-03 实测：
    # 首轮生成的 SQL 在 WHERE 子句处断行导致语法错误，回传报错后一次改对）。
    if error_hint:
        messages.append({
            "role": "user",
            "content": (
                "你上一条 SQL 执行失败，数据库报错如下：\n"
                f"{error_hint}\n\n"
                "请根据报错修正后重新给出完整 SQL（只输出 SQL，不要解释）。"
            ),
        })

    # 语义纠错（比 error_hint 更"软"但更有指向性）：SQL **能跑**，却查不出东西。
    # 最常见的就是拿系统名当过滤值 —— 数据库不报错，只是返回 0 行。
    # 这时把原因直接讲给模型听，让它自己改写（见 detect_system_name_filter）。
    if semantic_hint:
        messages.append({"role": "user", "content": semantic_hint})

    raw = _call_provider(provider, api_key, model, base_url, messages)

    if raw.strip().upper().startswith("CANNOT_ANSWER"):
        reason = raw.split(":", 1)[1].strip() if ":" in raw else raw
        raise Nl2SqlError(f"无法用现有表回答该问题：{reason}")

    sql = _extract_sql(raw)
    if not sql:
        raise Nl2SqlError("模型未返回 SQL")

    # ---- 服务端强制护栏（不信任模型输出） ----
    # 先剥注释再校验：见 _strip_sql_comments 的说明（注释会吞掉 WHERE 续行，
    # 也会让关键字黑名单误判）。
    sql = _strip_sql_comments(sql)
    sql, referenced = validate_sql(sql, tables)
    sql = enforce_limit(sql, DEFAULT_LIMIT)
    return {"sql": sql, "tables_referenced": referenced, "raw_model_output": raw}


def _call_provider(provider: str, api_key: str, model: str,
                   base_url: str, messages: List[Dict[str, str]]) -> str:
    """调用 LLM。复用 `incident_ai_service.PROVIDERS` 的分发能力。

    注意：`incident_ai_service.py` 已达项目单文件 500 行上限，**不修改该文件**。
    这里读取它的 `PROVIDERS` 做能力探测；由于它的 `call_*` 签名是
    (api_key, prompt, model)，为支持多轮 messages，这里对支持的 provider 走
    统一的 OpenAI 兼容调用，保持「provider 名称集合」与其一致。
    """
    import requests

    from backend.services.incident_ai_service import PROVIDERS

    if provider not in PROVIDERS:
        raise Nl2SqlError(
            f"不支持的 provider: {provider}（可用: {', '.join(sorted(PROVIDERS))}）"
        )

    # 统一的 OpenAI 兼容端点（含自定义 base_url，便于接自建模型）
    defaults = {
        "openai": "https://api.openai.com/v1/chat/completions",
        "deepseek": "https://api.deepseek.com/v1/chat/completions",
        "qianwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "glm-coding": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "doubao": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "agnes": "https://apihub.agnes-ai.com/v1/chat/completions",
    }
    url = base_url or defaults.get(provider)
    if not url:
        # gemini 走的是 generateContent 协议，与这里统一的 OpenAI 兼容
        # `/chat/completions` 不同构，**不能**靠默认值兜底打通，也不接受 base_url。
        # 此前只报「需提供 base_url」，会诱导用户去填一个必然失败的地址 —— 这里把
        # 真实原因说清楚（前端 DataAgentBar 已同步把它标注为「仅归因可用」）。
        if provider == "gemini":
            raise Nl2SqlError(
                "gemini 不支持 NL2SQL：它使用 generateContent 协议，与本功能的 "
                "OpenAI 兼容调用不同构。请改用 deepseek / openai / qianwen 等 provider。"
            )
        raise Nl2SqlError(
            f"provider {provider} 暂不支持 NL2SQL（需提供 base_url）"
        )

    payload = {
        "model": model or _default_model(provider),
        "messages": messages,
        "temperature": 0,  # 取数要稳定，不要创造性
        "max_tokens": 1200,
    }
    # 超时：一次 NL2SQL 要连跑两次 LLM（生成 SQL + 结果解读），
    # 60s 在 OWU 冷启动时偏紧，故做成可配（NL2SQL_TIMEOUT，默认 120s）。
    try:
        timeout = float(os.environ.get("NL2SQL_TIMEOUT") or 120)
    except (TypeError, ValueError):
        timeout = 120.0

    # 私有 CA：OWU（192.168.100.27:8443）用的是内网自签证书，requests 默认会
    # 做证书校验 → SSL 失败。用 NL2SQL_CA_FILE 指定 CA 文件路径即可；
    # 不配则走默认校验（公网端点仍受保护）。
    ca_file = (os.environ.get("NL2SQL_CA_FILE") or "").strip()
    verify: Any = True
    if ca_file:
        if os.path.isfile(ca_file):
            verify = ca_file
        else:
            logger.warning("[nl2sql] NL2SQL_CA_FILE 指向的文件不存在: %s", ca_file)

    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload, timeout=timeout, verify=verify,
        )
    except requests.exceptions.RequestException as e:
        raise Nl2SqlError(f"请求 AI 服务失败: {e}") from e

    if r.status_code != 200:
        raise Nl2SqlError(f"AI 服务返回 {r.status_code}: {r.text[:200]}")
    try:
        return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:  # noqa: BLE001
        raise Nl2SqlError(f"无法解析 AI 响应: {e}") from e


def _default_model(provider: str) -> str:
    return {
        "openai": "gpt-4o-mini",
        "deepseek": "deepseek-chat",
        "qianwen": "qwen-plus",
        "glm-coding": "glm-4",
        "doubao": "doubao-pro-32k",
        "agnes": "agnes-2.5-flash",
    }.get(provider, "")


def execute_readonly(sql: str, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    """执行已通过护栏的 SQL。

    纵深防御：即便上游已校验，这里**再校验一次**并显式开只读事务 ——
    因为 `_PsycopgRaw` 是 autocommit（`backend/database.py:324`），
    一旦校验环节将来被改动，只读事务是最后一道闸。
    """
    tables = _visible_tables()
    try:
        # ⚠️ 剥离注释**必须在校验之前**：注释里出现 DELETE / UPDATE 这类字样会被
        # 关键字黑名单误判成写操作；反过来，注释里的内容也会被 _strip_literals
        # 当成代码扫。先剥掉再校验，两边都干净。
        sql = _strip_sql_comments(sql)
        sql, referenced = validate_sql(sql, tables)
        sql = enforce_limit(sql, limit)
    except SqlGuardError as e:
        raise Nl2SqlError(str(e)) from e

    # 判定截断要按**实际生效的 LIMIT**，而不是本函数的 limit 参数。
    # 此前用 `len(rows) >= limit` 是错的：用户写 `LIMIT 5` 时，enforce_limit 会
    # 原样保留 5，返回 5 行，但比较对象仍是 limit（默认上限），于是 5 >= 50000 为假，
    # **明明触顶却不报截断**。反之在旧默认值 200 下，用户写 `LIMIT 1000` 拿到 1000 行
    # 也会被判成「未截断」。两种都让前端拿到错的信号。
    effective_limit = _effective_limit(sql, fallback=limit)

    with get_raw_connection() as conn:
        try:
            # 只读事务（PG）：SQLite 分支忽略该语句也不应报错，故做容错
            try:
                conn.execute("SET TRANSACTION READ ONLY")
            except Exception:  # noqa: BLE001
                pass
            cur = conn.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
        except Exception as e:  # noqa: BLE001
            # ⚠️ 护栏拦下的（SqlGuardError）**不重试** —— 模型再生成一次也绕不过去，
            # 重试只是白烧一次 LLM。数据库执行错误（语法错、列不存在）才值得回传纠错。
            # 这里统一转成 Nl2SqlError，避免直接冒泡成 HTTP 500 —— 机器人需要知道
            # 「查询没跑通」，而不是「服务炸了」。
            raise Nl2SqlError(
                f"SQL 执行失败：{_db_error_brief(e)}"
            ) from e
        finally:
            conn.close()

    out_rows = [dict(zip(columns, r)) for r in rows]
    return {
        "sql": sql,
        "tables_referenced": referenced,
        "columns": columns,
        "rows": out_rows,
        "row_count": len(out_rows),
        # 达到生效的 LIMIT 说明可能被截断，显式暴露（沿用项目下钻截断的约定）。
        # 前端用它决定是否显示「已达上限」标签 —— 只在真的触顶时才出现。
        "truncated": len(out_rows) >= effective_limit,
    }


def _effective_limit(sql: str, fallback: int) -> int:
    """取出 SQL 实际生效的 LIMIT 数值，供截断判定使用。

    `enforce_limit` 之后的 SQL 必然是这两种形态之一：
      - 结尾自带 `LIMIT n`（用户写的，或超限被改写成 MAX_LIMIT）；
      - 外层包裹 `... ) AS _guard_sub LIMIT n`（原本没有 LIMIT）。
    两者都能用同一个正则从**结尾**匹配到 —— 只看 `$` 锚定的那一处，
    避免命中子查询内部的 LIMIT。
    """
    m = re.search(r"\blimit\s+(\d+)\s*$", _strip_literals(sql).strip(), re.IGNORECASE)
    if m:
        return int(m.group(1))
    return fallback


def _normalize_ms_epoch_compare(sql: str) -> str:
    """把「毫秒时间戳列 ↔ 时间表达式」的比较**自动改写成类型一致**的写法。

    为什么需要它（比 prompt 可靠）
    -----------------------------
    2026-11-04 实测：模型知道「这列是毫秒时间戳」后，仍然会写出
    ``servertime >= NOW() - INTERVAL '7 days'``（bigint 与 timestamptz 比较）
    或 ``date_trunc('day', servertime)``（date_trunc 不接受 bigint）——
    前者直接报错，后者更糟：某些写法不报错但**静默返回 0 行**，
    机器人于是自信地回答「最近 7 天没有 Critical 告警」，而真实有 766 条。

    靠 prompt 提醒模型「要转换」是不够的 —— 它会记住一半、漏掉另一半。
    所以这里在**执行前**做一次保守的语法改写：

      ① ``date_trunc('day', C)``        → ``date_trunc('day', to_timestamp(C::bigint/1000.0))``
      ② ``C <op> <含时间的表达式>``      → ``to_timestamp(C::bigint/1000.0) <op> <表达式>``
      ③ ``<含时间的表达式> <op> C``      → 同上
      ④ ``C::timestamp``                → ``to_timestamp(C::bigint/1000.0)``

    只在**明确命中毫秒列 + 明确命中时间表达式**时才改写，其余一律原样保留 ——
    改写器宁可漏改（模型重试一次即可），也不能把好 SQL 改坏。
    """
    if not sql:
        return sql
    out = sql
    for table, cols in _SPECIAL_COL_HINTS.items():
        for col, kind in cols.items():
            if kind != "ms_epoch":
                continue
            # 只处理出现在该表语境里的列名（SQL 里没有 FROM 限定时按列名全局匹配，
            # 因为 history_alarm 的这几个列名足够独特）
            c = re.escape(col)

            # ① date_trunc('unit', C) —— 保留 unit 语义
            out = re.sub(
                r"(date_trunc\s*\(\s*'[^']*'\s*,\s*)" + c + r"(?!\s*::)",
                lambda m: m.group(1) + f"to_timestamp({col}::bigint / 1000.0)",
                out,
                flags=re.IGNORECASE,
            )

            # ④ C::timestamp → to_timestamp(C::bigint/1000.0)
            out = re.sub(
                c + r"\s*::\s*timestamp(?!\w)",
                f"to_timestamp({col}::bigint / 1000.0)",
                out,
                flags=re.IGNORECASE,
            )

            # ② / ③ 列与时间表达式比较 —— 两侧类型必须一致
            # 前瞻里允许**一个**左括号 —— 模型很爱把时间阈值写成
            # `(NOW() - INTERVAL '7 days')`，没有这个括号就会漏判。
            time_expr = r"(?=[^()]*?\(?(?:now\s*\(\s*\)|current_timestamp|interval|extract\s*\(|date_trunc|to_char))"
            out = re.sub(
                r"\b" + c + r"\b" + time_expr + r"(\s*(?:>=|<=|>|<|=|!=)\s*)"
                r"(\(?\s*(?:now\s*\(\s*\)|current_timestamp)[^\n]*?)(?=\s*(?:\)|\s*and\b|\s*or\b|\s*;|$))",
                lambda m: f"to_timestamp({col}::bigint / 1000.0){m.group(1)}{m.group(2)}",
                out,
                flags=re.IGNORECASE,
            )
            out = re.sub(
                r"((?:now\s*\(\s*\)|current_timestamp)[^\n]*?\s*(?:>=|<=|>|<|=|!=)\s*)"
                r"\b" + c + r"\b",
                lambda m: m.group(1) + f"to_timestamp({col}::bigint / 1000.0)",
                out,
                flags=re.IGNORECASE,
            )
    return out


def ask(question: str, provider: str, api_key: str, model: str = "",
        base_url: str = "", run: bool = True, sql: str = "",
        history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """一问一答：生成 SQL（可选执行）。

    sql 非空时跳过生成、直接执行 —— 供用户**手改 SQL 后重跑**，
    这是「让用户能核对」的关键交互：模型给的 SQL 用户可改、可看、可复用。
    """
    if sql:
        gen = {"sql": sql, "tables_referenced": [], "raw_model_output": ""}
    else:
        gen = generate_sql(question, provider, api_key, model, base_url, history)

    # ⚠️ 执行前把「毫秒时间戳列 ↔ 时间表达式」的比较改写成类型一致的写法。
    # 详见 _normalize_ms_epoch_compare 的说明：模型记住「要转换」却漏掉一半
    # 是常态（2026-11-04 实测两种错法都出现过），靠 prompt 兜不住。
    # 改写后的 SQL 才是真正执行的 SQL，也会返回给用户核对。
    gen["sql"] = _normalize_ms_epoch_compare(gen["sql"])

    result: Dict[str, Any] = {
        "sql": gen["sql"],
        "tables_referenced": gen["tables_referenced"],
    }
    if not run:
        return result

    # ---- 系统名守卫：拿系统名当过滤值 → 命中 0 行 ----
    # 这类错误**不报错**，只是查不出东西，所以不能等到 0 行才发现 ——
    # 那时用户已经拿到「没有匹配到任何记录」这种误导性答案了。
    # 这里在执行前就拦下来，把原因讲清楚让模型自己改写。
    # 只对**模型生成的** SQL 生效；用户手改的 SQL 是他的本意，不动。
    if not sql:
        bad_cols = detect_system_name_filter(gen["sql"])
        if bad_cols:
            logger.warning(
                "[nl2sql] 检出系统名过滤（列: %s），让模型改写后重试",
                ", ".join(bad_cols),
            )
            gen = generate_sql(question, provider, api_key, model, base_url, history,
                               semantic_hint=_system_filter_hint(bad_cols))
            gen["sql"] = _normalize_ms_epoch_compare(gen["sql"])
            # 模型有时「记住一半」—— 提示了仍然用系统名过滤。
            # 这时走**确定性兜底**：把这种条件直接剥离掉（见 strip_system_name_filters）。
            # 不做无限重试：再烧一次 LLM 也未必改得掉，而剥离是必然收敛的。
            still_bad = detect_system_name_filter(gen["sql"])
            if still_bad:
                stripped = strip_system_name_filters(gen["sql"])
                if stripped and stripped != gen["sql"]:
                    logger.warning(
                        "[nl2sql] 模型改写后仍用系统名过滤（列: %s），确定性剥离",
                        ", ".join(still_bad),
                    )
                    gen["sql"] = stripped
            result["sql"] = gen["sql"]
            result["tables_referenced"] = gen["tables_referenced"]

    try:
        exec_result = execute_readonly(gen["sql"])
    except Nl2SqlError as e:
        # 只有**数据库执行错误**才回传报错让模型重写一次 SQL。
        # 护栏拒绝（写操作 / 未知表 / 多语句）重试也没用 —— 那不是模型能改的。
        msg = str(e)
        if not msg.startswith("SQL 执行失败") or not sql:
            raise
        logger.warning("[nl2sql] 生成的 SQL 执行失败，回传报错让模型重试一次: %s", msg)
        gen = generate_sql(question, provider, api_key, model, base_url, history,
                           error_hint=msg)
        result["sql"] = gen["sql"]
        result["tables_referenced"] = gen["tables_referenced"]
        exec_result = execute_readonly(gen["sql"])

    result.update({
        "columns": exec_result["columns"],
        "rows": exec_result["rows"],
        "row_count": exec_result["row_count"],
        "truncated": exec_result["truncated"],
        "executed_sql": exec_result["sql"],
    })
    return result

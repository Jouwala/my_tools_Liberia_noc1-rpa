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
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.database import get_raw_connection, list_tables
from backend.services.sql_guard import (
    DEFAULT_LIMIT, SqlGuardError, enforce_limit, validate_sql,
)

logger = logging.getLogger(__name__)

# 喂给模型的表清单上限：避免把上百张表的全部列塞进 prompt 撑爆上下文。
MAX_TABLES_IN_PROMPT = 60
MAX_COLS_PER_TABLE = 40
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
    """可见表清单：排除 `_` 前缀内部表与备份/临时表。

    `_` 前缀约定与 TableBrowser 一致（`backend/routers/tables.py:209`）。
    """
    try:
        tables = [t for t in list_tables() if not t.startswith("_")]
    except Exception:  # noqa: BLE001
        logger.warning("[nl2sql] list_tables 失败", exc_info=True)
        return []
    return [t for t in tables if not _NOISE_TABLE_RE.search(t)]


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
            shown = cols[:MAX_COLS_PER_TABLE]
            col_txt = ", ".join(
                "{}{}".format(c["name"], "" if (c.get("type") or "") == "" else f" {c['type']}")
                for c in shown
            )
            if len(cols) > MAX_COLS_PER_TABLE:
                col_txt += f" ...(共 {len(cols)} 列)"
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

If the request cannot be answered with the given schema, output exactly:
CANNOT_ANSWER: <short reason>

SCHEMA:
{schema}
"""


def _extract_sql(text: str) -> str:
    """从模型输出里抠出 SQL。

    模型即使被要求「只输出 SQL」，仍可能带 ```sql 围栏或一句解释 —— 这是实测常见行为，
    所以这里做容错提取，而不是指望 prompt 完全约束住它。
    """
    if not text:
        return ""
    t = text.strip()
    # 去掉 markdown 代码围栏
    fence = re.search(r"```(?:sql)?\s*(.+?)```", t, re.IGNORECASE | re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    # 从第一个 SELECT / WITH 开始截取
    m = re.search(r"\b(select|with)\b", t, re.IGNORECASE)
    if m:
        t = t[m.start():]
    return t.strip().rstrip(";").strip()


class Nl2SqlError(ValueError):
    """NL2SQL 流程错误：携带适合展示给用户的中文原因。"""


def generate_sql(question: str, provider: str, api_key: str,
                 model: str = "", base_url: str = "",
                 history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
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

    raw = _call_provider(provider, api_key, model, base_url, messages)

    if raw.strip().upper().startswith("CANNOT_ANSWER"):
        reason = raw.split(":", 1)[1].strip() if ":" in raw else raw
        raise Nl2SqlError(f"无法用现有表回答该问题：{reason}")

    sql = _extract_sql(raw)
    if not sql:
        raise Nl2SqlError("模型未返回 SQL")

    # ---- 服务端强制护栏（不信任模型输出） ----
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
        raise Nl2SqlError(
            f"provider {provider} 暂不支持 NL2SQL（需提供 base_url）"
        )

    payload = {
        "model": model or _default_model(provider),
        "messages": messages,
        "temperature": 0,  # 取数要稳定，不要创造性
        "max_tokens": 1200,
    }
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload, timeout=60,
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
        sql, referenced = validate_sql(sql, tables)
        sql = enforce_limit(sql, limit)
    except SqlGuardError as e:
        raise Nl2SqlError(str(e)) from e

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
        finally:
            conn.close()

    out_rows = [dict(zip(columns, r)) for r in rows]
    return {
        "sql": sql,
        "tables_referenced": referenced,
        "columns": columns,
        "rows": out_rows,
        "row_count": len(out_rows),
        # 达到 LIMIT 说明可能被截断，显式暴露（沿用项目下钻截断的约定）
        "truncated": len(out_rows) >= limit,
    }


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

    result: Dict[str, Any] = {
        "sql": gen["sql"],
        "tables_referenced": gen["tables_referenced"],
    }
    if not run:
        return result

    exec_result = execute_readonly(gen["sql"])
    result.update({
        "columns": exec_result["columns"],
        "rows": exec_result["rows"],
        "row_count": exec_result["row_count"],
        "truncated": exec_result["truncated"],
        "executed_sql": exec_result["sql"],
    })
    return result

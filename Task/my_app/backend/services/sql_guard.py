# -*- coding: utf-8 -*-
"""
只读 SQL 护栏（Data Agent NL2SQL 原型）

为什么需要它
------------
PG 模式下 `get_raw_connection()` 返回的 `_PsycopgRaw` 把连接设成
**autocommit = True**（`backend/database.py:324`）。这意味着：

    靠「事务不回滚」来兜住写操作是**行不通的** —— 一条 DELETE 会立即生效。

所以只读必须靠**语句层面**的拦截，本模块就是那层拦截。

设计取向：宁可误拒，不可放过
----------------------------
一个被误拒的正常查询，用户换个问法就能过；一条漏放的 DROP TABLE，代价是生产库。
因此本模块**默认拒绝**任何无法明确判定为只读的语句。

关键点：先剥离注释与字符串字面量，再做判定
------------------------------------------
朴素的正则黑名单会被这些绕过：

    SELECT 1; DROP TABLE x           -- 多语句拼接，必须拦
    SELECT 1 /* ; DELETE FROM t */   -- 注释里的语句会被真实执行，必须拦

因此判定前必须先做 `_strip_literals()`，在「剩余代码」上找关键字。

**一个容易搞错的边界（本模块的测试专门覆盖）**：

    SELECT 'a; DROP TABLE t' AS x FROM t

这一条**应该放行**，不是漏洞。它是一个完全正常的查询 —— 只是返回了一个
内容为 "a; DROP TABLE t" 的字符串。给它加参数化绑定会更严谨，但它没有任何副作用。

真正的威胁不是「SQL 文本里出现了 DROP 这四个字母」，而是
**「分号把语句切成了两条，且第二条会真的执行」**。所以：

- 字符串/注释**内部**的分号与关键字 → 放行（无副作用）；
- 字符串/注释**外部**残留的分号 → 拦截（多语句）。

这个区分是本模块与「朴素黑名单」的本质差别，也是 `_strip_literals()` 存在的理由。
"""
from __future__ import annotations

import re
from typing import List, Tuple

# --------------------------------------------------------------------------
# 写操作 / DDL / 危险关键字黑名单
# --------------------------------------------------------------------------
# 覆盖：DML、DDL、权限、事务、锁、以及 PG 特有的危险动作（COPY / pg_sleep 之外的文件操作）。
FORBIDDEN_KEYWORDS = (
    # ---- DML ----
    "insert", "update", "delete", "merge", "upsert",
    # ---- DDL ----
    "drop", "alter", "create", "truncate", "rename",
    # ---- 权限 / 事务 / 会话 ----
    "grant", "revoke", "commit", "rollback", "savepoint", "begin", "end",
    "vacuum", "analyze", "reindex", "cluster", "checkpoint", "discard",
    # ---- 数据搬运 / 执行 ----
    "copy", "call", "do", "execute", "prepare", "listen", "notify", "load",
    "attach", "detach", "pragma", "set", "reset", "lock", "unlock",
    # ---- 文件 / 扩展 ----
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "lo_import", "lo_export",
    "dblink", "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf",
)
_FORBIDDEN_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in FORBIDDEN_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# 语句必须以这些开头（大小写不敏感），且允许前置的括号（如 (SELECT ...) UNION ...）
_ALLOWED_STARTS = ("select", "with")

# 标识符：用于从 SQL 中抽取表名。支持 "quoted" / schema."table" / plain
_IDENT_PAT = r'(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_]*)'
_TABLE_REF_RE = re.compile(
    r"\b(?:from|join)\s+"
    r"(?:(?P<schema>" + _IDENT_PAT + r")\s*\.\s*)?"
    r"(?P<table>" + _IDENT_PAT + r")",
    re.IGNORECASE,
)
# CTE 名（WITH x AS (...), y AS (...))：这些不是真实表，需从表引用中排除
_CTE_RE = re.compile(
    r"(?:\bwith\b|,)\s*(" + _IDENT_PAT + r")\s+as\s*\(",
    re.IGNORECASE,
)

# 返回行数上限（2026-10-05 调整 200 → 50000）
#
# 原为 DEFAULT_LIMIT=200 / MAX_LIMIT=1000。用户反馈两点：
#   1. 200 行对探索性查询太紧，动不动就「已达上限」，而实际数据量并不大；
#   2. 截断告警条在结果接近上限时频繁弹出，属于噪声。
#
# 现把上限一次性放宽到 50000，与 `remote_readonly.MAX_LIMIT`（远端数据库单次
# 读取上限）对齐 —— 两者是同类约束，用同一个数量级避免「本地放行、远端拒绝」
# 的错配。取值依据：本功能是排查用的只读副驾，结果在浏览器里渲染并导出 Excel，
# 5 万行 × 有限列仍在可接受范围；且真正的防护是**只读白名单 + 单语句**
# （见本文件顶部的三道闸），而非行数限制。
#
# 注意：`enforce_limit` 对无 LIMIT 的查询会外层包裹 `LIMIT {DEFAULT_LIMIT}`，
# 放宽后意味着「用户不写 LIMIT」时会**真的返回最多 5 万行**。这是刻意的 ——
# 与「不写 LIMIT 就不该被悄悄砍到 200 行」的直觉一致。
DEFAULT_LIMIT = 50000
MAX_LIMIT = 50000


class SqlGuardError(ValueError):
    """护栏拒绝：携带给用户看的中文原因。"""


def _strip_literals(sql: str) -> str:
    """把字符串字面量与注释替换成空格，保留其余结构。

    目的：让 `SELECT 'a; DROP TABLE x'` 中的 DROP 不再被当成关键字，
    同时 `SELECT 1 /* ; DELETE */` 里的 DELETE 同样消失。

    不是完整的 SQL 词法器，但对「防御性拦截」足够：
    它只会让判定**更严格**（剥离后关键字减少），不会制造假阴性。
    """
    out: List[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        # 单引号字符串（'' 为转义）
        if ch == "'":
            out.append(" ")
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        # 双引号标识符（"" 为转义）—— 注意：不清除内容，因为双引号里是列名/表名，
        # 后续表名抽取依赖它。但内部不会有关键字逃逸问题，故原样保留。
        if ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                out.append(sql[i])
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        out.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        # 行注释 --
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] not in "\r\n":
                i += 1
            out.append(" ")
            continue
        # 块注释 /* */（PG 支持嵌套）
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            depth = 1
            i += 2
            while i < n and depth > 0:
                if sql[i] == "/" and i + 1 < n and sql[i + 1] == "*":
                    depth += 1
                    i += 2
                elif sql[i] == "*" and i + 1 < n and sql[i + 1] == "/":
                    depth -= 1
                    i += 2
                else:
                    i += 1
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _normalize_ident(name: str) -> str:
    """去掉引号，供表名比对使用。"""
    name = (name or "").strip()
    if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
        return name[1:-1].replace('""', '"')
    return name


def extract_tables(sql: str) -> List[str]:
    """抽取 SQL 引用的表名（去重、保序），排除 CTE 别名。

    仅返回**不带 schema 前缀**的表名；带 schema 的引用会被拒绝（见 validate_sql），
    因为项目约定走 search_path（`backend/database.py:320`），
    显式 schema 前缀会绕过「先看 app、再看 eflow」的既有语义，正是 2.2 节陷阱的来源。
    """
    stripped = _strip_literals(sql)
    ctes = {_normalize_ident(m.group(1)).lower() for m in _CTE_RE.finditer(stripped)}
    tables: List[str] = []
    seen = set()
    for m in _TABLE_REF_RE.finditer(stripped):
        table = _normalize_ident(m.group("table"))
        if not table:
            continue
        low = table.lower()
        # 子查询 `FROM (` 不会匹配到（正则要求标识符），无需特判
        if low in ctes or low in seen:
            continue
        seen.add(low)
        tables.append(table)
    return tables


def validate_sql(sql: str, allowed_tables: List[str]) -> Tuple[str, List[str]]:
    """校验并归一化 SQL。通过则返回 (清理后的 SQL, 引用到的表)；否则抛 SqlGuardError。

    allowed_tables：真实存在的表名清单（由调用方用 list_tables() 提供）。
    """
    if not sql or not sql.strip():
        raise SqlGuardError("SQL 不能为空")

    # ---- 多语句阻断：剥离字面量后，不允许残留 ';'（末尾单个分号容许） ----
    stripped = _strip_literals(sql)
    body = stripped.strip()
    if body.endswith(";"):
        body = body[:-1]
    if ";" in body:
        raise SqlGuardError("只允许执行单条语句（检测到分号分隔的多条语句）")

    # ---- 起始关键字白名单 ----
    lead = re.match(r"\s*\(*\s*([A-Za-z_]+)", body)
    if not lead or lead.group(1).lower() not in _ALLOWED_STARTS:
        raise SqlGuardError("只允许 SELECT 或 WITH 开头的只读查询")

    # ---- 关键字黑名单（在剥离字面量后的代码上判定） ----
    hit = _FORBIDDEN_RE.search(body)
    if hit:
        raise SqlGuardError(f"查询包含被禁止的关键字：{hit.group(1).upper()}（仅允许只读查询）")

    # ---- 显式 schema 前缀阻断 ----
    for m in _TABLE_REF_RE.finditer(body):
        if m.group("schema"):
            raise SqlGuardError(
                "不允许在表名前写 schema（如 app.eflow_tt）："
                "跨 schema 存在同名但列结构不同的表，请直接写表名走 search_path"
            )

    # ---- 表白名单 ----
    allowed_lower = {t.lower() for t in allowed_tables}
    referenced = extract_tables(body)
    if not referenced:
        raise SqlGuardError("未能识别查询中的表，请显式使用 FROM <表名>")
    unknown = [t for t in referenced if t.lower() not in allowed_lower]
    if unknown:
        raise SqlGuardError(f"表不存在或不可访问：{', '.join(unknown)}")

    return body.strip(), referenced


def enforce_limit(sql: str, limit: int = DEFAULT_LIMIT) -> str:
    """确保查询带上受控的 LIMIT。

    - 无 LIMIT：包一层 `SELECT * FROM (<sql>) AS _guard_sub LIMIT n`，
      比「在末尾追加 LIMIT」更稳 —— 后者遇到已有 ORDER BY / 括号结尾会语法错误。
    - 有 LIMIT：解析出数值统一**收敛到 MAX_LIMIT 以内**。

    收敛策略（2026-10-05 修正）：
    此前是「超过 MAX_LIMIT 就抛错」，于是出现一个静默灰区 ——
    用户写 `LIMIT 1000` 原样放行、写 `LIMIT 999999` 直接报错，而 `LIMIT 500`
    这类介于 DEFAULT_LIMIT(200) 与 MAX_LIMIT(1000) 之间的值，既不被收敛，
    执行端也不会置 `truncated`（`nl2sql_service.py:298` 用的是
    `len(rows) >= limit`，比较对象是 DEFAULT_LIMIT），用户无法判断
    自己拿到的是否为全量 —— 与项目「截断必须显式暴露」的约定相抵。

    现改为：一律把用户写法**压到 MAX_LIMIT**（而非拒绝），
    使「请求的 LIMIT」与「护栏允许的上限」始终自洽；
    是否真的截断，仍由执行端按实际返回行数判定。
    """
    if limit < 1:
        limit = DEFAULT_LIMIT
    limit = min(limit, MAX_LIMIT)

    body = _strip_literals(sql)
    m = re.search(r"\blimit\s+(\d+)\s*$", body.strip(), re.IGNORECASE)
    if m:
        if int(m.group(1)) > MAX_LIMIT:
            # 超上限：把数值改写成 MAX_LIMIT 而不是抛错（见上方 docstring 的收敛策略）
            return sql[:m.start(1)] + str(MAX_LIMIT) + sql[m.end(1):]
        return sql
    # 无 LIMIT：外层包裹，强制收敛返回行数
    return f"SELECT * FROM (\n{sql}\n) AS _guard_sub LIMIT {limit}"

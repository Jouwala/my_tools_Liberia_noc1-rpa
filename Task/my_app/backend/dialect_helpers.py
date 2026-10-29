"""方言无关助手（sqlite / pg 双模）。

设计原则
--------
调用方（服务 / 路由）继续保持 sqlite 原生写法：``?`` 占位符 +
``conn.execute(sql, params).fetchall()``。PG 模式下由 ``backend.database``
的 ``_PsycopgRaw`` 在连接层把 ``?`` 转成 ``%s`` 并暴露同构接口，本模块
**只负责方言耦合**的部分：

* 表枚举（sqlite_master  ↔ information_schema）
* 列枚举（PRAGMA table_info ↔ information_schema.columns）
* 调优类 PRAGMA（PG 无等价物，静默跳过）
* upsert（INSERT OR REPLACE ↔ INSERT ... ON CONFLICT）
* PG 标识符截断（pg_trunc_ident：UTF-8 前 63 字节，与 NAMEDATALEN-1 一致）
* DataFrame 写入（pandas to_sql，走 SQLAlchemy 引擎）

判定方式：``isinstance(conn, sqlite3.Connection)`` 走 sqlite 分支，否则走 PG
分支。这样服务/路由代码无需 import DB_MODE，纯靠连接对象类型分派。
"""
import logging
import sqlite3

from backend.database import engine  # SQLAlchemy 引擎（双模），供 write_df / to_sql 使用


PG_MAX_IDENT = 63  # PG 标识符上限（NAMEDATALEN-1），单位：UTF-8 字节


def pg_trunc_ident(name):
    """PG 标识符截断：UTF-8 编码后 <=63 字节原样返回；>63 字节取前 63 字节，
    再按 .decode('utf-8', errors='ignore') 丢弃尾部可能残缺的多字节字符。

    sqlite 无此限制，调用方仅在 PG 分支使用本函数。
    """
    s = str(name)
    raw = s.encode("utf-8")
    if len(raw) <= PG_MAX_IDENT:
        return s
    return raw[:PG_MAX_IDENT].decode("utf-8", errors="ignore")


def _quote_ident(name):
    """单个标识符加双引号并转义内部双引号（sqlite / PG 通用）。"""
    return '"' + str(name).replace('"', '""') + '"'


def pg_quote_ident(name):
    """PG 参数化 SQL 中的标识符：双引号包裹 + 内部引号翻倍。

    列名里的 ``%``（如 ``A(%)``）**不再**在此双写：统一的 ``%``→``%%`` 转义由
    backend.database._qmark_to_pyformat(escape_pct=True) 在带参数执行路径完成
    （psycopg2 格式化时还原为 ``%``）。此处若再双写会与转义层叠加成双重转义
    （PG 收到 ``%``），导致含 % 列名的 upsert/INSERT 报“字段不存在”。
    """
    return '"' + str(name).replace('"', '""') + '"'


def _quote_table(name, truncate=False):
    """表名加双引号；支持 ``schema.table`` 限定名按段处理。

    PG 分支（truncate=True）对每一段先做 63 字节 UTF-8 截断。
    """
    parts = str(name).split(".")
    if truncate:
        parts = [pg_trunc_ident(p) for p in parts]
    return ".".join(_quote_ident(p) for p in parts)


def _pg_quote_table(name):
    """PG 参数化 SQL 中的表名（支持 schema.table），按段引号包裹。"""
    return ".".join(pg_quote_ident(p) for p in str(name).split("."))


def list_table_names(conn):
    """当前连接可见的基表名（list，按名）。"""
    if isinstance(conn, sqlite3.Connection):
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        return [r[0] for r in cur.fetchall()]
    cur = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = ANY(current_schemas(false)) AND table_type='BASE TABLE'"
    )
    return [r[0] for r in cur.fetchall()]


def table_columns(conn, table):
    """表列名（list，按定义顺序）。"""
    if isinstance(conn, sqlite3.Connection):
        cur = conn.execute(f"PRAGMA table_info({table})")
        return [r[1] for r in cur.fetchall()]
    cur = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = ? AND table_schema = ANY(current_schemas(false)) ORDER BY ordinal_position",
        (table,),
    )
    return [r[0] for r in cur.fetchall()]


def safe_pragma(conn, stmt):
    """仅 sqlite 执行 PRAGMA（调优类：busy_timeout / WAL / synchronous 等）。

    PG 无等价物，静默跳过。返回 cursor 或 None。
    """
    if isinstance(conn, sqlite3.Connection):
        return conn.execute(stmt)
    return None


def upsert(conn, table, rows, conflict_cols):
    """批量 upsert。rows: list[dict]。

    sqlite: ``INSERT OR REPLACE``；pg: ``INSERT ... ON CONFLICT (conflict_cols) DO UPDATE``。
    列名/表名全部按方言加双引号（含空格、保留字、引号的列名安全）；
    PG 分支的列名先按 63 字节 UTF-8 截断（pg_trunc_ident），与建表/加列保持一致。
    返回写入行数。
    """
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ", ".join("?" * len(cols))
    if isinstance(conn, sqlite3.Connection):
        col_sql = ", ".join(_quote_ident(c) for c in cols)
        table_sql = _quote_table(table)
        sql = f"INSERT OR REPLACE INTO {table_sql} ({col_sql}) VALUES ({placeholders})"
        for r in rows:
            conn.execute(sql, [r[c] for c in cols])
        conn.commit()
        return len(rows)
    # PG：列名按 63 字节截断（与 CREATE TABLE / ALTER ADD COLUMN 一致）
    pcols = [pg_trunc_ident(c) for c in cols]
    pconf = [pg_trunc_ident(c) for c in conflict_cols]
    col_sql = ", ".join(pg_quote_ident(c) for c in pcols)
    table_sql = _pg_quote_table(table)
    conflict_sql = ", ".join(pg_quote_ident(c) for c in pconf)
    set_cols = [c for c in pcols if c not in set(pconf)]
    if set_cols:
        set_sql = ", ".join(
            f"{pg_quote_ident(c)}=EXCLUDED.{pg_quote_ident(c)}" for c in set_cols
        )
        sql = (
            f"INSERT INTO {table_sql} ({col_sql}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {set_sql}"
        )
    else:
        # 全部列都是冲突键：DO UPDATE SET 为空会语法错误，等价退化为 DO NOTHING
        sql = (
            f"INSERT INTO {table_sql} ({col_sql}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_sql}) DO NOTHING"
        )
    for r in rows:
        # 兼容调用方传原始列名或已截断列名两种情况
        params = [r[orig] if orig in r else r.get(trunc)
                  for orig, trunc in zip(cols, pcols)]
        conn.execute(sql, params)
    conn.commit()
    return len(rows)


def dedupe_rows(conn, table, key_cols, *, logger=None):
    """按 ``key_cols`` 去重，每组只保留一行（保留物理位置最早的那行）。

    为什么必须有这个函数（2026-10-28）
    ----------------------------------
    ``DELETE FROM t WHERE ctid NOT IN (SELECT MIN(ctid) FROM t GROUP BY <pk>)``
    在 PG 上会被优化器展开成嵌套循环（对每个 ctid 跑一次子查询），复杂度近似
    O(n²)。实测：``ipran_ume.Metro_ring_me_15mins`` 上这条语句跑了 **25.9 小时
    仍未结束**（pid 15116，backend_start 2026-10-27 18:47:24 UTC），期间一直
    ``active`` 且 ``wait_event=IO/BufFileRead``（外部排序不停刷临时文件），
    持有 ``RowExclusiveLock`` 挡住该表上的 ``CREATE/DROP INDEX``，并持续吃磁盘 IO。
    同一反模式在 ``packet_loss_service.py:362`` 的注释里早有记录（「134 万行实测
    卡死 11 分钟未完成」），但仍有 4 处调用点没改，故抽到本模块统一。

    实现要点
    --------
    1. **先探查再删**：``GROUP BY ... HAVING count(*) > 1 LIMIT 1`` 命中即停。
       正常情况（已有唯一索引 / 上游已去重）只需一次索引扫描就返回，完全跳过
       排序与写入 —— 这是本函数相对原写法的**主要收益**，因为它在每次同步时都会跑。
    2. 真有重复时走窗口函数单次排序 + ``ctid``/``rowid`` 回删，保留 ``rn = 1``。
    3. **不 commit**：事务边界由调用方掌握（PG 分支的连接本身是 autocommit）。

    参数
    ----
    conn      : sqlite3.Connection（走 rowid）或 PG 连接包装（走 ctid）
    table     : 表名，可含 ``schema.`` 前缀
    key_cols  : 参与去重的列名（空则直接返回 0）
    logger    : 可选，用于记录实际删除了多少行

    返回：删除的行数（0 表示本来就没有重复）。
    """
    log = logger or logging.getLogger(__name__)
    keys = [str(k) for k in (key_cols or []) if str(k)]
    if not keys:
        return 0

    is_pg = not isinstance(conn, sqlite3.Connection)
    table_sql = _quote_table(table, truncate=is_pg)
    # PG 下建表时列名已按 63 字节截断（见 upsert），这里必须用同一套名字
    key_sql = ", ".join(
        _quote_ident(pg_trunc_ident(k) if is_pg else k) for k in keys
    )
    rowid_col = "ctid" if is_pg else "rowid"

    # ── 1. 先探查：没有重复就完全不碰这张表 ──
    has_dup = conn.execute(
        f"SELECT 1 FROM {table_sql} GROUP BY {key_sql} HAVING count(*) > 1 LIMIT 1"
    ).fetchone()
    if not has_dup:
        return 0

    # ── 2. 窗口函数单次排序定位重复行，再按物理行号回删 ──
    if is_pg:
        # PG 支持 DELETE ... USING，直接把 ctid 集合连上去，避免再套一层 IN
        sql = (
            f"DELETE FROM {table_sql} p USING ("
            f"SELECT {rowid_col} AS rid, row_number() OVER ("
            f"PARTITION BY {key_sql} ORDER BY {rowid_col}) AS rn "
            f"FROM {table_sql}) d "
            f"WHERE p.{rowid_col} = d.rid AND d.rn > 1"
        )
    else:
        sql = (
            f"DELETE FROM {table_sql} WHERE {rowid_col} IN ("
            f"SELECT rid FROM ("
            f"SELECT {rowid_col} AS rid, row_number() OVER ("
            f"PARTITION BY {key_sql} ORDER BY {rowid_col}) AS rn "
            f"FROM {table_sql}) x WHERE x.rn > 1)"
        )

    cur = conn.execute(sql)
    deleted = cur.rowcount if cur is not None and cur.rowcount and cur.rowcount > 0 else 0
    if deleted:
        log.warning(
            "[DEDUPE] %s 按 (%s) 删除 %d 行重复数据（保留每组物理最早一行）",
            table, ", ".join(keys), deleted,
        )
    return deleted


def write_df(df, table, engine_override=None, if_exists="append", index=False):
    """DataFrame 写入表（双模，走 SQLAlchemy 引擎）。

    engine_override 不传时用全局 engine（= app.db / 默认 PG schema）。
    写非 app 库时由调用方传入对应 engine。
    """
    eng = engine_override or engine
    df.to_sql(table, eng, if_exists=if_exists, index=index)
    return len(df)


# ============ 导入类操作的索引约定（单一事实来源） ============
# 凡是「Excel/CSV → 建表」的入口（init_db 初始化、表浏览器导入、上传建表）
# 都调用 ensure_table_indexes()，避免各处各写一份清单导致索引漂移。
#
# 每项为 (索引名后缀, 需要同时存在的列元组)。列表顺序 = 建索引顺序。
# 命名沿用 init_db 的历史命名（含 region_level1 → region1 这种缩写），
# 以兼容已存在的旧索引；改名会让老库上多出一份重复索引。
TABLE_INDEX_SPECS = (
    ("site_id", ("site_id",)),
    ("region1", ("region_level1",)),
    ("region", ("region",)),
    ("status", ("status",)),
    ("created_time", ("created_time",)),
    ("alarm_occur", ("alarm_occur_time",)),
    # 复合索引：时间+站点（加速 JOIN + 时间过滤）
    ("alarm_site", ("alarm_occur_time", "site_id")),
    ("site_name", ("site_name",)),
    ("ticket_no", ("ticket_no",)),
)


def ensure_table_indexes(conn, table, columns, *, logger=None):
    """按 ``TABLE_INDEX_SPECS`` 为 ``table`` 建索引（双模）。

    columns: 该表的最终列名集合（如 ``df.columns``）。
    返回：本次已建立的索引名列表（供调用方打印 / 审计）。

    行为约定
    --------
    * 仅当某项 spec 要求的列**全部存在**时才建该索引，否则跳过（不算失败）。
    * 表名 / 列名 / 索引名一律按方言加双引号；PG 下索引名与表名按 63 字节
      UTF-8 截断（PG 会静默截断超长标识符，不截断会报 relation does not exist）。
    * 失败**不再静默吞掉**：记录 warning 日志后继续建其余索引，最后一个都不
      因前一个失败而丢。
    * **不 commit**：事务边界由调用方掌握。

    关于失败隔离（为何不需要 SAVEPOINT）
    ------------------------------------
    PG 分支的连接是 autocommit=True（backend/database.py 的 _PsycopgRaw），
    每条 DDL 独立提交，因此不存在「一条失败导致整个事务 aborted、后续语句
    全部报 current transaction is aborted」的问题；sqlite 分支的 DDL 失败
    也不会污染已开启的事务。故此处只需逐条 try/except。
    """
    log = logger or logging.getLogger(__name__)
    is_pg = not isinstance(conn, sqlite3.Connection)
    have = set(columns)
    table_sql = _quote_table(table, truncate=is_pg)

    done = []
    for suffix, spec_cols in TABLE_INDEX_SPECS:
        if not all(c in have for c in spec_cols):
            continue
        idx_name = pg_trunc_ident(f"idx_{table}_{suffix}") if is_pg else f"idx_{table}_{suffix}"
        col_sql = ", ".join(_quote_ident(c) for c in spec_cols)
        try:
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {_quote_ident(idx_name)} "
                f"ON {table_sql} ({col_sql})"
            )
            done.append(idx_name)
        except Exception as e:  # noqa: BLE001 - 单个索引失败不应中断导入
            log.warning("[INDEX] 建索引失败: %s ON %s(%s) -> %s",
                        idx_name, table, ", ".join(spec_cols), e)
    return done

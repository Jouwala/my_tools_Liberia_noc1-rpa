"""Phase 5 迁移公共库：SQLite -> PostgreSQL（按 schema 搬运）。

职责：
1. 只读打开 SQLite（URI mode=ro），枚举业务表（排除 sqlite_% 系统对象）。
2. 用 PRAGMA table_info 反推 DDL：先 DROP TABLE IF EXISTS 再 CREATE TABLE，
   类型映射 INTEGER->BIGINT、REAL->DOUBLE PRECISION、其余（含 TEXT/BLOB）->TEXT；
   所有标识符（schema/table/column）一律双引号转义，兼容 "2G_..."、"Begin Time"、
   "[FDD]..." 这类不能裸写的标识符。
3. 分批搬运：默认 psycopg2 executemany + 每 5000 行一提交；也提供 pandas
   read_sql_query(chunksize) + to_sql 备选路径。
4. 对账：表清单、行数、全行流式 MD5 三方校验。

幂等（R4）：每次迁移先 DROP 目标表再重建，可反复重跑；SQLite 源库只读、永不删除。
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import sqlite3
import sys
from datetime import date, datetime, time
from pathlib import Path
from urllib.parse import quote

logger = logging.getLogger("transfer_lib")

DEFAULT_BATCH_SIZE = 5000

# SQLite 声明类型 -> PG 类型（大小写不敏感；不在表内的都归 TEXT）
_SQLITE_TO_PG_TYPE = {
    "INTEGER": "BIGINT",
    "REAL": "DOUBLE PRECISION",
}


def _force_utf8_stdio():
    """Windows 控制台默认 cp1252 无法输出中文，这里统一改为 UTF-8。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def load_env(env_path=None):
    """尽量加载 backend/.env（DATABASE_URL 等）；失败仅告警，不阻断。"""
    env_path = Path(env_path) if env_path else Path(__file__).resolve().parent.parent / ".env"
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
    except Exception:  # noqa: BLE001
        logger.warning("dotenv unavailable or failed to load; skip (%s)", env_path)


def get_pg_url():
    """返回 PG 连接串；优先环境变量 DATABASE_URL，其次读 backend/.env。"""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        try:
            for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except OSError:
            pass
    return url


def pg_quote(ident):
    """PG/SQLite 通用标识符转义：双引号包裹，内部引号翻倍。"""
    return '"' + str(ident).replace('"', '""') + '"'


def pg_sql_quote(ident):
    """PG 侧 SQL 文本用标识符：pg_quote 基础上把 % 写成 %%。

    psycopg2 用 Python % 风格处理占位符，SQL 文本里的字面 %（例如
    "Rate(%)_x" 列名）必须转义为 %%，否则会触发 tuple index out of range。
    """
    return pg_quote(ident).replace("%", "%%")


def open_sqlite(path):
    """只读打开 SQLite（URI mode=ro），不产生写锁、不修改源文件。"""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        raise FileNotFoundError(f"SQLite 源不存在或为空: {p}")
    uri = f"file:{quote(p.resolve().as_posix(), safe='/:')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def sqlite_tables(conn):
    """枚举业务表：排除 sqlite_% 系统表。"""
    cur = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [row["name"] for row in cur.fetchall()]


def sqlite_table_info(conn, table):
    """PRAGMA table_info -> 列定义（保留 pk 序号，用于复合主键排序）。"""
    cur = conn.execute(f"PRAGMA table_info({pg_quote(table)})")
    cols = []
    for row in cur.fetchall():
        cols.append(
            {
                "name": row["name"],
                "type": (row["type"] or "TEXT").strip(),
                "notnull": bool(row["notnull"]),
                "pk": int(row["pk"] or 0),
                "default": row["dflt_value"],
            }
        )
    return cols


def map_pg_type(sqlite_type):
    """SQLite 类型 -> PG 类型：INTEGER->BIGINT、REAL->DOUBLE PRECISION、其余->TEXT。"""
    t = (sqlite_type or "TEXT").strip().upper()
    return _SQLITE_TO_PG_TYPE.get(t, "TEXT")


def build_create_table(schema, table, cols, types=None):
    """由 PRAGMA 列信息生成 DROP + CREATE 两条 DDL（全部标识符加引号）。"""
    col_sql = []
    pk_cols = sorted((c for c in cols if c["pk"] > 0), key=lambda c: c["pk"])
    pg_types = types if types is not None else [map_pg_type(c["type"]) for c in cols]
    for i, c in enumerate(cols):
        # DDL 无参数执行：psycopg2 不会反转义 %%，标识符里的 % 直接裸写即可
        parts = [pg_quote(c["name"]), pg_types[i]]
        if c["notnull"] and c["pk"] == 0:
            parts.append("NOT NULL")
        col_sql.append(" ".join(parts))
    if pk_cols:
        col_sql.append(
            "PRIMARY KEY (" + ", ".join(pg_quote(c["name"]) for c in pk_cols) + ")"
        )
    drop = f"DROP TABLE IF EXISTS {pg_quote(schema)}.{pg_quote(table)}"
    create = (
        f"CREATE TABLE {pg_quote(schema)}.{pg_quote(table)} (\n  "
        + ",\n  ".join(col_sql)
        + "\n)"
    )
    return drop, create


def coerce_value(value, pg_type, where):
    """按目标 PG 类型校正 SQLite 动态类型值（TEXT 列统一转 str，数值列严格校验）。"""
    if value is None:
        return None
    if pg_type == "BIGINT":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if value.is_integer():
                return int(value)
            raise ValueError(f"{where}: BIGINT 列收到非整型 float {value!r}")
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            try:
                return int(s)
            except ValueError:
                f = float(s)
                if f.is_integer():
                    return int(f)
                raise ValueError(f"{where}: BIGINT 列无法解析 {value!r}")
        raise ValueError(f"{where}: BIGINT 列不支持类型 {type(value).__name__} 的值 {value!r}")
    if pg_type == "DOUBLE PRECISION":
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            return float(s)
        raise ValueError(
            f"{where}: DOUBLE PRECISION 列不支持类型 {type(value).__name__} 的值 {value!r}"
        )
    # TEXT（含原 BLOB 与其它声明类型）
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        # latin-1 逐字节无损映射，可完整还原原字节序列
        return bytes(value).decode("latin-1")
    return str(value)


def _sqlite_select_sql(table, cols):
    quoted = ", ".join(pg_quote(c["name"]) for c in cols)
    return f"SELECT {quoted} FROM {pg_quote(table)}"


def _order_by_clause(cols, for_pg, pg_types=None):
    """ORDER BY 全部列；PG 侧 TEXT 列加 COLLATE "C"，与 SQLite BINARY 字节序对齐。"""
    parts = []
    for i, c in enumerate(cols):
        col = pg_quote(c["name"])
        t = pg_types[i] if pg_types is not None else map_pg_type(c["type"])
        if for_pg:
            if t == "TEXT":
                col += ' COLLATE "C"'
            # SQLite ASC 默认 NULL 最前，PG 默认 NULL 最后；对齐后流式 MD5 才一致
            col += " NULLS FIRST"
        parts.append(col)
    return " ORDER BY " + ", ".join(parts)


def _copy_table_executemany(src, select_sql, pg_conn, schema, table, cols, pg_types, batch_size, progress):
    insert_sql = (
        f"INSERT INTO {pg_sql_quote(schema)}.{pg_sql_quote(table)} "
        f"({', '.join(pg_sql_quote(c['name']) for c in cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))})"
    )
    copied = 0
    src_cur = src.execute(select_sql)
    try:
        while True:
            rows = src_cur.fetchmany(batch_size)
            if not rows:
                break
            converted = [
                tuple(
                    coerce_value(row[i], pg_types[i], f"{schema}.{table}.{cols[i]['name']}")
                    for i in range(len(cols))
                )
                for row in rows
            ]
            with pg_conn.cursor() as cur:
                cur.executemany(insert_sql, converted)
            pg_conn.commit()
            copied += len(converted)
            if progress:
                progress(copied)
    finally:
        src_cur.close()
    return copied


def _copy_table_pandas(src, select_sql, engine, schema, table, batch_size, progress):
    import pandas as pd

    copied = 0
    for chunk in pd.read_sql_query(select_sql, src, chunksize=batch_size):
        chunk.to_sql(
            table,
            engine,
            schema=schema,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=batch_size,
        )
        copied += len(chunk)
        if progress:
            progress(copied)
    return copied


def pg_table_exists(pg_conn, schema, table):
    """PG 中指定 schema.table 是否存在。"""
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            (schema, table),
        )
        return cur.fetchone() is not None


def pg_column_names(pg_conn, schema, table):
    """PG 中指定表的列名（按 ordinal_position）。"""
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s "
            "ORDER BY ordinal_position",
            (schema, table),
        )
        return [r[0] for r in cur.fetchall()]


def pg_column_types(pg_conn, schema, table, cols):
    """按源列顺序返回 PG 实际列类型（映射为 BIGINT/DOUBLE PRECISION/TEXT）。"""
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            (schema, table),
        )
        info = dict(cur.fetchall())
    out = []
    for c in cols:
        t = (info.get(c["name"]) or "text").lower()
        if t in ("bigint", "integer", "smallint", "bigserial", "serial", "smallserial"):
            out.append("BIGINT")
        elif t in ("double precision", "real", "numeric", "decimal"):
            out.append("DOUBLE PRECISION")
        elif t in (
            "timestamp without time zone",
            "timestamp with time zone",
            "date",
            "time without time zone",
            "time with time zone",
            "interval",
            "json",
            "jsonb",
            "uuid",
            "boolean",
            "bytea",
        ):
            out.append("OTHER")
        else:
            out.append("TEXT")
    return out


def validate_pg_columns(pg_conn, schema, table, cols):
    """insert-only 前置校验：PG 已有表的列集合必须与 SQLite 源一致。"""
    pg_cols = set(pg_column_names(pg_conn, schema, table))
    src_cols = {c["name"] for c in cols}
    if pg_cols != src_cols:
        raise ValueError(
            f"{schema}.{table} 列不一致: "
            f"PG 多出 {sorted(pg_cols - src_cols)}, "
            f"缺少 {sorted(src_cols - pg_cols)}"
        )


def _infer_pg_types(src, table, cols, batch_size=DEFAULT_BATCH_SIZE):
    """为 insert-only 新建表推断安全类型：声明为数值但含非数值文本的列降级为 TEXT。"""
    types = [map_pg_type(c["type"]) for c in cols]
    numeric_idx = [i for i, t in enumerate(types) if t in ("BIGINT", "DOUBLE PRECISION")]
    if not numeric_idx:
        return types
    cur = src.execute(_sqlite_select_sql(table, cols))
    try:
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                for i in numeric_idx:
                    if types[i] == "TEXT":
                        continue
                    try:
                        coerce_value(row[i], types[i], f"{table}.{cols[i]['name']}")
                    except (TypeError, ValueError, OverflowError):
                        types[i] = "TEXT"
    finally:
        cur.close()
    return types


def copy_table(
    sqlite_path,
    pg_conn,
    schema,
    table,
    batch_size=DEFAULT_BATCH_SIZE,
    method="executemany",
    engine=None,
    progress=None,
    drop_existing=True,
    create_if_missing=True,
):
    """搬运单表数据，返回搬运行数。

    drop_existing=True（默认，Wave1）：先 DROP 再 CREATE，幂等可重跑。
    drop_existing=False（insert-only，Wave2 app）：绝不 DROP；
        目标表已存在则只做列校验 + INSERT；不存在且 create_if_missing=True
        时仅 CREATE（不 DROP）后 INSERT。
    """
    src = open_sqlite(sqlite_path)
    try:
        cols = sqlite_table_info(src, table)
        pg_types = [map_pg_type(c["type"]) for c in cols]
        if drop_existing:
            drop_sql, create_sql = build_create_table(schema, table, cols, pg_types)
            with pg_conn.cursor() as cur:
                cur.execute(drop_sql)
                cur.execute(create_sql)
            pg_conn.commit()
        elif pg_table_exists(pg_conn, schema, table):
            validate_pg_columns(pg_conn, schema, table, cols)
            pg_types = pg_column_types(pg_conn, schema, table, cols)
        elif create_if_missing:
            pg_types = _infer_pg_types(src, table, cols)
            _, create_sql = build_create_table(schema, table, cols, pg_types)
            with pg_conn.cursor() as cur:
                cur.execute(create_sql)
            pg_conn.commit()
        else:
            raise RuntimeError(f"{schema}.{table} 不存在且 create_if_missing=False")

        select_sql = _sqlite_select_sql(table, cols)
        if method == "pandas":
            if engine is None:
                raise ValueError("method=pandas 时须传入 SQLAlchemy engine")
            copied = _copy_table_pandas(src, select_sql, engine, schema, table, batch_size, progress)
        elif method == "executemany":
            copied = _copy_table_executemany(
                src, select_sql, pg_conn, schema, table, cols, pg_types, batch_size, progress
            )
        else:
            raise ValueError(f"未知搬运方法: {method!r}（可选 executemany|pandas）")
        return copied
    finally:
        src.close()


def _serialize_value(v):
    """把单值序列化为稳定字节流，用于双端行哈希。"""
    if v is None:
        return "N"
    if isinstance(v, str):
        return "S" + v
    if isinstance(v, (date, time)):
        # PG timestamp 返回 datetime/date/time；按字符串参与哈希，与 SQLite 文本一致
        return "S" + str(v)
    if isinstance(v, (bytes, bytearray)):
        return "B" + bytes(v).hex()
    if isinstance(v, float):
        # 数值统一按 float 表示：sqlite 的 REAL 列可能返回 int，PG 侧为 float
        return "F" + repr(float(v))
    if isinstance(v, int):
        return "F" + repr(float(v))
    return "O" + repr(v)


def _hash_select(conn, sql, batch_size=DEFAULT_BATCH_SIZE, types=None):
    """对查询结果做全行流式 MD5（源/目标同列序，结果可直接比较）。"""
    h = hashlib.md5()
    cur = _execute(conn, sql)
    try:
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                for i, v in enumerate(row):
                    if types is not None:
                        v = coerce_value(v, types[i], f"hash:{i}")
                    h.update(_serialize_value(v).encode("utf-8", errors="surrogatepass"))
                    h.update(b"\x1f")
                h.update(b"\x1e")
    finally:
        cur.close()
    return h.hexdigest()


def _execute(conn, sql):
    """统一执行入口：sqlite3.Connection 有 .execute，psycopg2 需先建 cursor。"""
    if hasattr(conn, "execute"):
        return conn.execute(sql)
    cur = conn.cursor()
    cur.execute(sql)
    return cur


def pg_count(pg_conn, schema, table):
    cur = _execute(
        pg_conn,
        f"SELECT COUNT(*) FROM {pg_quote(schema)}.{pg_quote(table)}",
    )
    return cur.fetchone()[0]


def verify_table(sqlite_path, pg_conn, schema, table, batch_size=DEFAULT_BATCH_SIZE):
    """单表对账：源/目标行数 + 全行 MD5。返回结果 dict。"""
    src = open_sqlite(sqlite_path)
    try:
        cols = sqlite_table_info(src, table)
        pg_types = pg_column_types(pg_conn, schema, table, cols)
        select_sql = _sqlite_select_sql(table, cols) + _order_by_clause(cols, for_pg=False)
        src_count = src.execute(f"SELECT COUNT(*) FROM {pg_quote(table)}").fetchone()[0]
        dst_count = pg_count(pg_conn, schema, table)
        src_hash = _hash_select(src, select_sql, batch_size, types=pg_types)
        dst_sql = (
            f"SELECT {', '.join(pg_quote(c['name']) for c in cols)} "
            f"FROM {pg_quote(schema)}.{pg_quote(table)}"
            f"{_order_by_clause(cols, for_pg=True, pg_types=pg_types)}"
        )
        dst_hash = _hash_select(pg_conn, dst_sql, batch_size, types=pg_types)
        ok = src_count == dst_count and src_hash == dst_hash
        return {
            "schema": schema,
            "table": table,
            "src_rows": src_count,
            "pg_rows": dst_count,
            "src_md5": src_hash,
            "pg_md5": dst_hash,
            "ok": ok,
        }
    finally:
        src.close()


def verify_migration(
    sqlite_path,
    pg_conn,
    schema,
    tables=None,
    exclude_tables=None,
    batch_size=DEFAULT_BATCH_SIZE,
):
    """整库对账：返回每表校验结果列表。"""
    src = open_sqlite(sqlite_path)
    try:
        src_tables = set(sqlite_tables(src)) - set(exclude_tables or ())
    finally:
        src.close()
    target_tables = set(tables) if tables is not None else src_tables
    if target_tables != src_tables:
        raise ValueError(
            f"表清单不一致: 源={sorted(src_tables)} 目标={sorted(target_tables)}"
        )
    return [
        verify_table(sqlite_path, pg_conn, schema, table, batch_size=batch_size)
        for table in sorted(src_tables)
    ]


def ensure_schema(pg_conn, schema):
    with pg_conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {pg_quote(schema)}")
    pg_conn.commit()


def backup_sqlite_files(paths, backup_root, timestamp=None, phase="phase5_wave1"):
    """R0 前置备份：文件级拷贝 sqlite（含 -wal/-shm 副作用文件）。"""
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(backup_root) / f"{phase}_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for p in paths:
        src = Path(p)
        if not src.exists():
            logger.warning("backup skip (missing): %s", src)
            continue
        dest = backup_dir / src.name
        shutil.copy2(src, dest)
        copied.append(str(dest))
        for suffix in ("-wal", "-shm"):
            side = Path(str(src) + suffix)
            if side.exists():
                shutil.copy2(side, backup_dir / side.name)
                copied.append(str(backup_dir / side.name))
    return backup_dir, copied


def inspect_source(sqlite_path):
    """只读查看 sqlite 源：表名、行数、列。"""
    src = open_sqlite(sqlite_path)
    try:
        tables = sqlite_tables(src)
        info = []
        for t in tables:
            cols = sqlite_table_info(src, t)
            cnt = src.execute(f"SELECT COUNT(*) FROM {pg_quote(t)}").fetchone()[0]
            info.append(
                {
                    "table": t,
                    "rows": cnt,
                    "columns": [c["name"] for c in cols],
                    "pg_types": [map_pg_type(c["type"]) for c in cols],
                }
            )
        return info
    finally:
        src.close()


def _run_inspect(args):
    for p in args.sqlite:
        print(f"==== {p}")
        for t in inspect_source(p):
            print(
                f"  {t['table']}  rows={t['rows']}  "
                f"cols={len(t['columns'])}  types={t['pg_types']}"
            )


def _run_backup(args):
    backup_dir, copied = backup_sqlite_files(args.sqlite, args.root)
    print(f"备份目录: {backup_dir}")
    for c in copied:
        print(f"  {c}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Phase 5 migration library CLI")
    sub = parser.add_subparsers(dest="action", required=True)

    p_inspect = sub.add_parser("inspect", help="read-only inspect sqlite source")
    p_inspect.add_argument("sqlite", nargs="+")

    p_backup = sub.add_parser("backup", help="R0 file-level backup")
    p_backup.add_argument("--root", default=str(Path(__file__).resolve().parent.parent.parent / "backup"))
    p_backup.add_argument("sqlite", nargs="+")

    args = parser.parse_args(argv)
    if args.action == "inspect":
        _run_inspect(args)
    elif args.action == "backup":
        _run_backup(args)
    else:  # pragma: no cover
        parser.error(f"unknown action: {args.action}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()

"""数据库连接管理"""
import logging
import os
import sqlite3
from sqlalchemy import create_engine, text, inspect, event
from sqlalchemy.orm import sessionmaker, declarative_base
from pathlib import Path

try:
    from dotenv import load_dotenv
    # 显式读取 backend/.env（DATABASE_URL / MY_APP_DB_MODE）；
    # 缺失则跳过，不影响 sqlite 默认模式。
    # 顺序：backend/.env 优先，缺失时回退项目根 .env；override=False 保证 OS 环境变量优先。
    for _env_file in (
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ):
        if _env_file.is_file():
            load_dotenv(_env_file, override=False)
except Exception:  # noqa: BLE001
    logging.getLogger(__name__).warning("load_dotenv 不可用，已跳过（不影响 sqlite 默认模式）", exc_info=True)

# ---------------- DB_MODE 熔断开关（回退方案 R7，已落地）----------------
# 默认 "sqlite"：行为与迁移前**逐字节一致**（引擎 / PRAGMA / get_raw_connection 全同）。
# "pg"：引擎改用 DATABASE_URL（psycopg2），get_raw_connection 按路径推断 PG schema。
# 回退 = 仅改环境变量 MY_APP_DB_MODE=sqlite，无需改代码。
DB_MODE = os.environ.get("MY_APP_DB_MODE", "sqlite").strip().lower()
if DB_MODE not in ("sqlite", "pg"):
    raise RuntimeError(f"MY_APP_DB_MODE 必须为 sqlite|pg，收到: {DB_MODE!r}")

DB_PATH = Path(__file__).parent.parent / "db" / "app.db"

# PG 连接串：仅 DB_MODE=pg 时使用；缺失则启动即明确报错（宁可失败也不静默）
PG_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# 解析后的当前连接串（保留 DATABASE_URL 属性名，兼容旧导入方）
DATABASE_URL = PG_DATABASE_URL if DB_MODE == "pg" else f"sqlite:///{DB_PATH}"

# 鉴权库硬排除集合（R8）：这些路径无论 DB_MODE 为何值，绝不走 PG。
_HARD_EXCLUDED_DB_PATHS = set()


def register_hard_excluded(db_path) -> None:
    """登记硬排除路径（如 credential_store），R8 保证其永不走 PG。"""
    _HARD_EXCLUDED_DB_PATHS.add(Path(db_path).resolve())


def _build_engine():
    if DB_MODE == "pg":
        if not PG_DATABASE_URL:
            raise RuntimeError("DB_MODE=pg 但环境变量 DATABASE_URL 未设置")
        return create_engine(
            DATABASE_URL,
            pool_size=int(os.environ.get("PG_POOL_SIZE", "20")),
            max_overflow=int(os.environ.get("PG_MAX_OVERFLOW", "10")),
            pool_pre_ping=True,
            echo=False,
        )
    # sqlite（默认）：与迁移前完全一致
    return create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30},
        echo=False,
        pool_pre_ping=True,
    )


engine = _build_engine()


# 统一所有连接的并发语义：写冲突时等待而非立刻报 "database is locked"。
# 仅设置每连接安全参数（busy_timeout 让写冲突等待，synchronous=NORMAL 提升性能）。
# 说明：WAL 模式虽能进一步解耦读写，但会在 -wal/-shm 文件上引入额外的并发/状态管理，
# 在长时间运行的服务里偶发 "closed database"；busy_timeout 已足以消除原始 locked 错误，
# 故此处不启用 WAL，改用更稳健的 rollback-journal + busy_timeout 方案。
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    # 仅对 sqlite 连接执行；PG 连接（psycopg2）走此事件时直接跳过
    if not isinstance(dbapi_conn, sqlite3.Connection):
        return
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
    finally:
        cur.close()


if DB_MODE == "sqlite":
    event.listen(engine, "connect", _set_sqlite_pragmas)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI依赖注入：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class _ClosingConnection(sqlite3.Connection):
    """带"退出即关闭"语义的 sqlite3 连接。

    ⚠️ 标准库陷阱：`with sqlite3.connect(...) as conn:` 是**事务**上下文管理器，
    退出时只 commit/rollback，**永远不会关闭连接**。因此单纯用 `with` 包裹
    并不能修复连接泄漏，这是本项目 "database is locked" 的根因之一。

    本子类重写 __exit__：先提交/回滚，再真正 close()。同时对"业务代码已在块内
    提前调用 conn.close()"的历史写法保持幂等，不再抛
    ProgrammingError: Cannot operate on a closed database。

    幂等实现：追踪 _closed 标志（覆盖 close()），__exit__ 若检测到连接已被块内
    提前关闭，则跳过 commit/rollback，直接走 finally 的 close()，避免对已关闭句柄
    调用 commit 触发 "closed database"。
    """

    _closed = False

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            super().close()
        except Exception:
            pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if not self._closed:
                if exc_type is None:
                    self.commit()
                else:
                    self.rollback()
        except Exception:  # noqa: BLE001 - 极小概率的提交期异常，幂等吞掉
            pass
        finally:
            self.close()
        return False  # 不吞原始异常


def get_raw_connection(db_path=None, timeout=30, check_same_thread=False, logical_name=None):
    """获取原始数据库连接（动态表查询 / 直接读写 db 文件）。

    双模（DB_MODE 熔断开关 R7）：
    - sqlite 模式（默认）：行为与迁移前**完全一致**——sqlite 连接 + busy_timeout/synchronous
      PRAGMA + _ClosingConnection（with 退出提交并关闭）。
    - pg 模式：按 db_path 推断（或 logical_name 显式指定）PG schema，返回 psycopg2 连接，
      search_path 设到对应 schema。原 sqlite 路径语义映射到 PG schema（见 _resolve_pg_schema）。

    db_path: 可传入其它 db 文件路径；缺省使用项目主库 DB_PATH。
    logical_name: pg 模式下显式指定 schema（可选，缺省由路径推断）。
    """
    path = Path(db_path) if db_path is not None else DB_PATH

    if DB_MODE == "pg":
        return _pg_raw_connection(path, logical_name=logical_name, timeout=timeout)

    # ---- sqlite 模式：与迁移前完全一致 ----
    conn = sqlite3.connect(
        str(path),
        timeout=timeout,
        check_same_thread=check_same_thread,
        factory=_ClosingConnection,
    )
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        # busy_timeout 让写冲突时等待而非立刻报 "database is locked"；
        # synchronous=NORMAL 在 rollback-journal 模式下提升写性能。
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_raw_connection: exception swallowed", exc_info=True)
        pass
    finally:
        cur.close()
    return conn


def _resolve_pg_schema(db_path) -> str:
    """把 sqlite 文件路径映射到 PG schema 名（pg 模式用）。

    规则：取文件名 stem（去 .sqlite3）映射到规范 schema；不在映射表时直接用 stem。
    例：app.db→app，eflow.sqlite3→eflow，lte_pl.sqlite3→lte_pl，
        lbr_ms_sla_kpi.sqlite3→ms_sla，battery_kpi.sqlite3→battery，
        ipran_ume_kpi.sqlite3→ipran_ume，fw_db.sqlite3→fw，ran_ume→ran_ume。
    读写分离：data/ran_ume 目录下的读库（ran_kpi_daily.sqlite3 与写库
    backend/services/ran_kpi_daily.sqlite3 同 stem）→ ran_ume_ro。
    """
    path = Path(db_path)
    if any(part.lower() == "ran_ume" for part in path.parent.parts):
        return "ran_ume_ro"
    stem = path.stem.lower()
    mapping = {
        "app": "app",
        "eflow": "eflow",
        "lte_pl": "lte_pl",
        "battery_kpi": "battery",
        "lbr_ms_sla_kpi": "ms_sla",
        "fw_db": "fw",
        "ipran_ume_kpi": "ipran_ume",
        "ran_ume": "ran_ume",
        "ran_ume_ro": "ran_ume_ro",
        "ran_kpi_daily": "ran_ume",
        "ran_kpi_daily_202606": "ran_ume",
    }
    return mapping.get(stem, stem)


def _qmark_to_pyformat(sql, escape_pct=False):
    """sqlite 原生用 '?' 占位符；psycopg2 用 '%s'。PG 模式下把 '?' 转成 '%s'，
    跳过字符串字面量（含 '' 转义），避免误转。

    escape_pct=True（仅带参数路径）：把字面 '%' 转成 '%%'（psycopg2 的 % 转义），
    否则列名含 %（如 "Packet Loss Rate(%)"）会被 psycopg2 当作格式化符报
    IndexError/ValueError。无参数路径不转义（psycopg2 无参数时不格式化）。
    """
    out = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            out.append(ch); i += 1
            while i < n:
                out.append(sql[i])
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        out.append("'"); i += 2; continue
                    break
                i += 1
            i += 1
            continue
        if ch == "?":
            out.append("%s"); i += 1; continue
        if escape_pct and ch == "%":
            out.append("%%"); i += 1; continue
        out.append(ch); i += 1
    return "".join(out)


class _PsycopgRawCursor:
    """PG 模式游标包装：把 sqlite 原生 '?' 占位符转成 psycopg2 的 '%s'，
    并补齐 executemany（psycopg2 原生），使现有 '?'-风格 + 'with' + cursor 用法
    在 PG 模式零改动即可运行。"""

    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=None):
        converted = _qmark_to_pyformat(sql, escape_pct=bool(params))
        if not params:
            # 无参数时直接执行：psycopg2 传空元组仍会做 % 格式化，
            # 遇到列名含 %（如 "Packet Loss Rate(%)"）会误伤。
            self._cur.execute(converted)
        else:
            self._cur.execute(converted, params)
        return self

    def executemany(self, sql, seq_of_params):
        self._cur.executemany(_qmark_to_pyformat(sql, escape_pct=True), seq_of_params or [])
        return self

    def fetchall(self):
        names = [d[0] for d in self._cur.description] if self._cur.description else []
        return [_PsycopgRow(r, names) for r in self._cur.fetchall()]

    def fetchone(self):
        names = [d[0] for d in self._cur.description] if self._cur.description else []
        row = self._cur.fetchone()
        return _PsycopgRow(row, names) if row is not None else None

    @property
    def description(self):
        return self._cur.description

    @property
    def rowcount(self):
        return self._cur.rowcount

    def close(self):
        return self._cur.close()


class _PsycopgRow(tuple):
    """PG 原始行：与 sqlite3.Row 对齐，同时支持整数索引和列名字符串索引。

    这样后端既有 ``r[0]`` 也有 ``row["col"]`` 的写法在 PG 模式零改动即可运行。
    """
    def __new__(cls, values, names):
        obj = super().__new__(cls, values)
        obj._names = {name: i for i, name in enumerate(names)}
        return obj

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._names[key])
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._names)


class _PsycopgRaw:
    """PG 模式原始连接包装：对外暴露与 sqlite3.Connection 一致的接口
    （with 上下文管理 / conn.execute(sql, params).fetchall() /
    conn.cursor().execute("?") / conn.cursor().executemany("?") / .description /
    .commit() / .rollback() / .close()），内部把 '?' 转成 '%s'
    交给 psycopg2。search_path 默认全 schema（兼容跨库查询），
    可经构造函数传入每连接独立的 search_path（解析出的目标 schema 置顶，
    消除 ran_ume/ran_ume_ro 同名表歧义）。

    这样后端大量 sqlite 原生 '?' 写法 + 'with get_raw_connection() as conn'
    在 PG 模式零改动即可运行。
    """
    _SEARCH_PATH = "app,eflow,lte_pl,battery,ms_sla,fw,ipran_ume,ran_ume,ran_ume_ro,public"

    def __init__(self, conn, search_path=None):
        self._c = conn
        self._c.autocommit = True
        cur = self._c.cursor()
        cur.execute(f"SET search_path TO {search_path or self._SEARCH_PATH}")
        self._c.commit()

    def execute(self, sql, params=None):
        cur = self._c.cursor()
        converted = _qmark_to_pyformat(sql, escape_pct=bool(params))
        if not params:
            cur.execute(converted)
        else:
            cur.execute(converted, params)
        return _PsycopgRawCursor(cur)

    def executemany(self, sql, seq_of_params):
        """连接层批量执行：与 sqlite3.Connection.executemany 对齐（'?' → '%s'）。"""
        cur = self._c.cursor()
        cur.executemany(_qmark_to_pyformat(sql, escape_pct=True), seq_of_params or [])
        return _PsycopgRawCursor(cur)

    def executescript(self, sql_script):
        """多语句 DDL 脚本执行：与 sqlite3.Connection.executescript 对齐。

        PG 无参数多语句串可直接发送（libpq 依次执行）；autocommit 模式下
        每条语句独立事务，与 sqlite 脚本语义一致。无参数路径不做 %% 转义
        （psycopg2 无参数时不格式化，列名含 % 原样发给 PG）。

        并发容错：两个执行者同时建表时，CREATE TABLE IF NOT EXISTS 存在
        TOCTOU 竞态（PG 已知限制），会报 duplicate_table/duplicate_column。
        捕获该类错误回滚后整体重试一次（已建成的表被 IF NOT EXISTS 跳过），
        使幂等建表脚本在并发下也能成功。
        """
        converted = _qmark_to_pyformat(sql_script)
        cur = self._c.cursor()
        try:
            cur.execute(converted)
        except Exception as e:  # noqa: BLE001
            pgcode = getattr(getattr(e, "diag", None), "sqlstate", "") or ""
            if pgcode not in ("42P07", "42701", "42P06"):  # duplicate_table/column/schema
                raise
            try:
                self._c.rollback()
            except Exception:  # noqa: BLE001
                pass
            cur.execute(converted)
        return _PsycopgRawCursor(cur)

    def cursor(self):
        return _PsycopgRawCursor(self._c.cursor())

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        self._c.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self._c.commit()
            else:
                self._c.rollback()
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                self._c.close()
            except Exception:  # noqa: BLE001
                pass
        return False  # 不吞原始异常


def _pg_raw_connection(db_path, logical_name=None, timeout=30):
    """PG 模式：返回 _PsycopgRaw 包装连接。

    search_path = 目标 schema 置顶 + 全局列表其余项（去重保序）：
    目标 schema 由 logical_name 显式指定（优先）或 _resolve_pg_schema(db_path)
    按路径推断。这样读 data/ran_ume 命中 ran_ume_ro、写 ran_ume 命中 ran_ume，
    同名表不再歧义；跨 schema 限定名查询仍可用（其余 schema 仍在路径中）。

    鉴权库（credential_store）硬排除（R8）：绝不走 PG。
    """
    import psycopg2  # 延迟导入：sqlite 模式下不要求安装 psycopg2
    if Path(db_path).resolve() in _HARD_EXCLUDED_DB_PATHS:
        raise RuntimeError(f"鉴权库 {db_path} 硬排除，禁止走 PG (R8)")
    if not PG_DATABASE_URL:
        raise RuntimeError("DB_MODE=pg 但 DATABASE_URL 未设置")
    target_schema = logical_name if logical_name else _resolve_pg_schema(db_path)
    rest = [s for s in _PsycopgRaw._SEARCH_PATH.split(",") if s != target_schema]
    search_path = ",".join([target_schema] + rest)
    conn = psycopg2.connect(PG_DATABASE_URL, connect_timeout=int(timeout))
    return _PsycopgRaw(conn, search_path=search_path)


def list_tables():
    """列出所有用户表（双模）。"""
    insp = inspect(engine)
    if DB_MODE == "sqlite":
        return [t for t in insp.get_table_names() if not t.startswith('sqlite_')]
    # pg：当前默认 schema（app）
    return [t for t in insp.get_table_names(schema="app")
            if not t.startswith('pg_') and t != 'information_schema']

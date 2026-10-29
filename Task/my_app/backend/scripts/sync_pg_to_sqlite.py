"""PG → SQLite 全量同步脚本

用途：把远程 PostgreSQL (myapp 库) 的所有用户数据同步到本地 SQLite 文件，
     作为离线备份 / 回退快照。

映射规则：
  - PG schema "app"  → db/app.db（表名不变）
  - PG 其它 schema   → db/app.db（表名加 schema 前缀，如 battery.battery_latest → battery_battery_latest）

运行方式：
  python backend/scripts/sync_pg_to_sqlite.py

依赖：
  - psycopg2（PG 模式已安装）
  - 环境变量从 backend/.env 自动加载
"""

import os
import sys
import sqlite3
import time
import logging
from pathlib import Path

# ── 路径 / 环境 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent          # 项目根
sys.path.insert(0, str(ROOT))

# 读 backend/.env
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env", override=False)
except Exception:
    pass

import psycopg2
import psycopg2.extras

# ── 配置 ──────────────────────────────────────────────────────
PG_URL = os.environ.get("DATABASE_URL", "")
SQLITE_PATH = ROOT / "db" / "app.db"
LOCK_PATH = ROOT / "db" / "pg_sync.lock"  # 跨进程单飞锁（防重复实例并发写 app.db）
BATCH_SIZE = 5000  # 每批写入行数

# 需要跳过的表。
#
# 分两类：
#  1) 系统/元数据表（PG 侧无意义）
#  2) **本地权威表** —— 由本机应用直接写 SQLite（db/app.db），PG 不是它们的权威来源。
#     这类表必须跳过，否则 sync_table 会对 SQLite 侧执行 `DROP TABLE` 再从 PG 重建，
#     把本地数据整体抹掉。
#
# ⚠️ 2026-09-18 事故（本注释即事故记录）：PG 里存在 `app.credentials`
#    （SQLAlchemy 建的壳表，恒为 0 行），`get_pg_tables()` 会把它列出来，而
#    `sanitize_table_name("app", ...)` 又把 app schema 映射成**无前缀**表名 —— 于是
#    每小时 :45 的同步把 SQLite 的 `credentials` 整表重建为空。用户在「设置」页保存的
#    邮箱密码因此最多只活 1 小时就被抹掉，应用随即回退到代码里已失效的
#    Postcode@202608，EWS 全线 HTTP 401（表现为"密码改了也没用、过一阵又坏"）。
#    实例：用户 14:48:47 保存密码 → 15:45 那次同步（15:50:30 落盘）后消失。
#
# 判定标准：看这张表的**写入方**是否与 DB 模式无关地固定写 SQLite。
#   - credentials      → backend/services/credential_store.py 硬编码 sqlite3.connect
#   - email_recipients → backend/services/email_recipient_store.py 同样硬编码
#   - task_schedule_config → backend/services/task_runner.py::_save_schedule_config
#       无条件写 SQLite（`load_schedule_config_rows` / `_load_schedule_config` /
#       `schedule_all_tasks` / 执行前的 `_refresh_task_schedule_from_db` 都读它）。
#       **代码里没有任何判定依据 PG 那份**：它只是 `_save_schedule_config` 双写出来的
#       镜像，供 pg_dump 备份、直接查库的人，以及漂移核对（`log_schedule_store_drift`）用。
# 反例：issue_reports（routers/feedback.py）走 get_raw_connection 双模，pg 模式下 PG
# 才是权威，故**不能**跳过。
#
# ⚠️ 2026-10-21 事故（同 09-18 credentials 的模式，第二次）：本表未跳过时，
#    sync_table 对 SQLite 执行 `DROP TABLE` + 按 PG 的**列**建裸表 ——
#      ① 表上的 PRIMARY KEY 连同手工补的 ux_task_schedule_config_task_id 一起丢失，
#         于是 `INSERT OR REPLACE` 不再替换而是**追加重复行**（73 任务变 146 行）；
#      ② PG 侧的陈旧 enabled 被灌回 SQLite。
#    实例：用户 15:26 点主开关（日志 138 行「DB 写入成功」）→ 16:15:40 本次同步结束
#    后覆盖，24 个任务随即按「任务 xxx 已禁用」被跳过，页面显示的 70 运行/3 停用
#    与实际持久状态相反。
SKIP_TABLES = {
    "alembic_version",     # 迁移版本表
    "credentials",         # 凭据：本地权威（设置页写 SQLite）
    "email_recipients",    # 邮件收件人名单：本地权威（设置页写 SQLite）
    "task_schedule_config",  # 任务启停/cron：本地权威（Task Manager 写 SQLite + 双写 PG）
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pg2sqlite")


# ── 工具函数 ──────────────────────────────────────────────────
def _pid_alive(pid: int) -> bool:
    """跨平台检查进程是否存活（Windows 用 OpenProcess，POSIX 用 kill 0）"""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            kernel32.CloseHandle(h)
            return True
        except Exception:
            return True  # 无法判定时保守视为存活，宁可跳过本次也不并发
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_sync_lock():
    """获取跨进程单飞锁。返回 True=拿到锁；False=另一实例正在同步（本次跳过）。

    背景（2026-08-31）：队列侧单飞曾因 stale-recovery 误回收在跑记录而失效，
    导致两个同步进程同时 DROP/CREATE app.db（database is locked /
    table already exists）。此锁为脚本级兜底，与队列保护独立。
    """
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                old_pid = int(LOCK_PATH.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                old_pid = 0
            if old_pid > 0 and _pid_alive(old_pid):
                return False  # 另一实例在跑
            # 持锁进程已死（或锁文件损坏）：清掉残留锁重试
            try:
                LOCK_PATH.unlink()
            except OSError:
                return False
    return False


def release_sync_lock():
    try:
        if LOCK_PATH.exists() and LOCK_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK_PATH.unlink()
    except OSError:
        pass


def get_pg_tables(conn):
    """获取所有用户表及其 schema，返回 [(schema, table), ...]"""
    cur = conn.cursor()
    cur.execute("""
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY schemaname, tablename
    """)
    return cur.fetchall()


def get_pg_columns(conn, schema, table):
    """获取指定表的列信息 [(col_name, data_type), ...]"""
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """, (schema, table))
    return cur.fetchall()


def pg_type_to_sqlite(pg_type: str) -> str:
    """把 PG 数据类型粗映射到 SQLite 类型"""
    t = pg_type.lower()
    if t in ("integer", "bigint", "smallint", "serial", "bigserial"):
        return "INTEGER"
    if t.startswith("numeric") or t in ("real", "double precision", "float"):
        return "REAL"
    if t == "boolean":
        return "INTEGER"
    if t in ("jsonb", "json"):
        return "TEXT"
    if t.startswith("timestamp") or t in ("date", "time"):
        return "TEXT"
    if t in ("bytea",):
        return "BLOB"
    return "TEXT"


def sanitize_table_name(schema: str, table: str) -> str:
    """生成 SQLite 表名：app schema 保持原名，其它加前缀"""
    if schema == "app":
        return table
    return f"{schema}_{table}"


def _end_pg_read_txn(pg_conn):
    """结束 PG 侧读事务，尽快释放表上的 ACCESS SHARE 锁。

    背景（2026-10-28 排查）：本脚本原先只 `set_session(readonly=True)`，
    **全脚本没有一处 commit/rollback**（psycopg2 默认 autocommit=False）→
    113 张表的 SELECT 全落在同一个事务里，ACCESS SHARE 锁从第一张表一直
    持到最后一张表（实测 577~1174s）。而 `app.realtime_alarm` 的写入走
    「影子表 + DROP + RENAME」（`eflow_alarm_service.py::_replace_table_via_engine`
    → `_swap_in_staging_table`，PG 分支是单条 DO 块 DDL），需要
    ACCESS EXCLUSIVE，与 ACCESS SHARE 互斥 → 等锁。

    实测证据：每一轮同步里 `eflow_active_alarm` 的 completed_at 都比本脚本的
    finished_at 早 0.6~1.7 秒（10-26~10-28 共 6 轮全部吻合），单次挂
    341~720s；它挂住期间每分钟触发被队列单飞保护拒绝，`task_execution_log`
    没有新记录 → sync 页时间线出现 5~10 分钟空白。

    commit 与 rollback 语义等价（会话是 read-only、无写操作），但必须二选一：
    SELECT 失败后 PG 事务进入 aborted 状态，只 commit 不 rollback 会让同一
    连接上的下一次 execute 报 "current transaction is aborted"。
    """
    try:
        pg_conn.commit()
    except Exception:  # noqa: BLE001 - 事务已 aborted / 连接已断，退回 rollback
        try:
            pg_conn.rollback()
        except Exception:  # noqa: BLE001 - 连接不可用时不阻断同步流程
            pass


def sync_table(pg_conn, sqlite_conn, schema: str, table: str):
    """同步单张表。

    ⚠️ 本函数会在这张表上开启 PG 读事务（`get_pg_columns` + `SELECT`），
    但**不负责结束它** —— 由调用方 `main()` 的循环在每张表之后调用
    `_end_pg_read_txn()`。这样「跳过表 / 无列信息 / 同步失败」三种提前返回
    路径也能释放锁，不必在每个 return 前重复写一遍。
    """
    sqlite_name = sanitize_table_name(schema, table)

    if table in SKIP_TABLES:
        log.info(f"  跳过（系统表）: {schema}.{table}")
        return 0

    # 1. 读取 PG 列定义
    columns = get_pg_columns(pg_conn, schema, table)
    if not columns:
        log.warning(f"  无列信息: {schema}.{table}，跳过")
        return 0

    col_names_raw = [c[0] for c in columns]
    # PG 可能有仅大小写不同的同名列（如 STATUS / status），SQLite 不区分，需去重
    seen_lower = {}
    col_names = []
    for name in col_names_raw:
        key = name.lower()
        if key in seen_lower:
            continue
        seen_lower[key] = True
        col_names.append(name)
    col_defs = ", ".join(f'"{c}" {pg_type_to_sqlite(next(ct[1] for ct in columns if ct[0] == c))}' for c in col_names)

    # 2. 在 SQLite 中原子重建表：DROP+CREATE+INSERT 放进同一事务，
    #    失败则回滚——旧快照数据保持完整，不会出现"空表/半张表"。
    sqlite_conn.execute("BEGIN IMMEDIATE")
    try:
        sqlite_conn.execute(f'DROP TABLE IF EXISTS "{sqlite_name}"')
        sqlite_conn.execute(f'CREATE TABLE "{sqlite_name}" ({col_defs})')

        # 3. 从 PG 读取数据并批量写入 SQLite
        cur = pg_conn.cursor()
        col_list = ", ".join(f'"{c}"' for c in col_names)
        cur.execute(f'SELECT {col_list} FROM "{schema}"."{table}"')

        placeholders = ", ".join(["?"] * len(col_names))
        insert_sql = f'INSERT INTO "{sqlite_name}" VALUES ({placeholders})'

        total = 0
        while True:
            rows = cur.fetchmany(BATCH_SIZE)
            if not rows:
                break
            # 处理不可序列化的类型
            cleaned = []
            for row in rows:
                cleaned.append(tuple(
                    str(v) if isinstance(v, (list, dict, bytes)) else v
                    for v in row
                ))
            sqlite_conn.executemany(insert_sql, cleaned)
            total += len(cleaned)

        sqlite_conn.execute("COMMIT")
    except Exception:
        try:
            sqlite_conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    return total


def main():
    """定时任务入口：PG → SQLite 全量快照同步，返回 result dict 供 task_runner 记录"""
    if not PG_URL:
        log.error("DATABASE_URL 未设置，无法连接 PG")
        return {"success": False, "error": "DATABASE_URL not set"}

    log.info(f"PG 连接: {PG_URL.split('@')[-1]}")
    log.info(f"SQLite 目标: {SQLITE_PATH}")

    pg_conn = None
    sqlite_conn = None
    if not acquire_sync_lock():
        msg = "另一同步实例正在运行，本次跳过（单飞锁保护）"
        log.warning(msg)
        return {"success": True, "skipped": True, "note": msg}
    try:
        # 连接 PG
        pg_conn = psycopg2.connect(PG_URL, connect_timeout=10)
        # 只读会话：本脚本对 PG 只做 SELECT，绝不允许误写。
        # ⚠️ 只读不等于「不持锁」—— 读事务一样持 ACCESS SHARE，所以事务边界
        #    必须按表切断（见 _end_pg_read_txn 与下方循环里的 finally）。
        pg_conn.set_session(readonly=True)

        # 连接 SQLite（isolation_level=None：显式 BEGIN/COMMIT，配合 sync_table 的原子表替换）
        sqlite_conn = sqlite3.connect(str(SQLITE_PATH), timeout=120, isolation_level=None)
        sqlite_conn.execute("PRAGMA busy_timeout=120000")
        sqlite_conn.execute("PRAGMA synchronous=NORMAL")

        # 获取所有表
        tables = get_pg_tables(pg_conn)
        log.info(f"发现 {len(tables)} 张 PG 表")

        # 逐表同步
        t0 = time.time()
        total_rows = 0
        errors = []

        for schema, table in tables:
            sqlite_name = sanitize_table_name(schema, table)
            try:
                rows = sync_table(pg_conn, sqlite_conn, schema, table)
                if rows > 0:
                    log.info(f"  ✓ {schema}.{table} → {sqlite_name}  ({rows:,} 行)")
                total_rows += rows
            except Exception as e:
                log.error(f"  ✗ {schema}.{table} 失败: {e}")
                errors.append(f"{schema}.{table}: {e}")
            finally:
                # 每张表都结束 PG 读事务 → ACCESS SHARE 只持有「读这一张表」的时间，
                # 不再跨越整轮同步（原因见 _end_pg_read_txn 的说明）。
                # 放在 finally 是为了让「跳过 / 无列 / 失败」路径同样释放锁。
                _end_pg_read_txn(pg_conn)

        # 汇总
        elapsed = time.time() - t0
        log.info("=" * 60)
        log.info(f"同步完成: {total_rows:,} 行, 耗时 {elapsed:.1f}s")

        # 显示文件大小
        size_mb = SQLITE_PATH.stat().st_size / (1024 * 1024)
        log.info(f"SQLite 文件大小: {size_mb:.1f} MB")

        success = len(errors) == 0
        return {
            "success": success,
            "tables_synced": len(tables) - len(errors),
            "tables_failed": len(errors),
            "total_rows": total_rows,
            "elapsed_seconds": round(elapsed, 1),
            "sqlite_size_mb": round(size_mb, 1),
            "errors": errors if errors else None,
        }
    except Exception as e:
        log.error(f"同步异常: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if pg_conn:
            pg_conn.close()
        if sqlite_conn:
            sqlite_conn.close()
        release_sync_lock()


if __name__ == "__main__":
    main()

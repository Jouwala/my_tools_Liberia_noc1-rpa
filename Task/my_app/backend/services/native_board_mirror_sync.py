"""看板远端数据源 -> 本机 SQLite 镜像。

2026-11-04 如意要求：「数据是本机产生的，远端是给其他 BI 工具用的，
看板不要跨机取数」。核查后发现三个历史库的**采集脚本当年只写远端**
（DbWriter API 192.168.100.19:8765），本机留下的都是不完整/过期副本：

  db.sqlite3          D:\\01_RPA\\Task\\RAN\\db.sqlite3 停在 2026-06，远端到 11-04
  db_ps_cs_cn.sqlite3 D:\\01_RPA\\Task\\PS_CS_CORE_Scripts\\ 只有 17/40 张表
  fw_db.sqlite        PG fw.device_whole_throughput 只有 1/2 台设备且数值口径不同

因此不直接改上游（跨项目、5+ 个服务），改为在 my_app 侧维护一份本机镜像：
  - 只镜像 native_catalog 里**实际被看板 SQL 引用**的表（用 /api/tables 交集核准）
  - 按 rowid 水位增量追加；发现远端行数变少 / rowid 倒退（full_replace 重建）
    或超过 FULL_RESYNC_HOURS 未做全量时，自动整表重拉，覆盖 UPDATE 类改动
  - 列**不声明类型**，SQLite 按值本身存储，数值列仍是数值（看板 SUM/ROUND 不变）
  - 写事务尽量短；看板以 mode=ro 打开同一文件，未提交事务读到的是旧快照

CLI:
  python -m backend.services.native_board_mirror_sync            # 增量
  python -m backend.services.native_board_mirror_sync --full     # 强制全量
  python -m backend.services.native_board_mirror_sync --dry-run  # 只打印计划

开关（backend/.env）：
  NATIVE_BOARD_MIRROR=0          看板回退读远端，且后台同步不启动
  NATIVE_BOARD_MIRROR_TTL=900    后台同步间隔（秒）
  NATIVE_BOARD_MIRROR_PAGE=5000  分页大小
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MIRROR_DIR = ROOT / "data" / "native_board_mirror"

REMOTE_DBS: Tuple[str, ...] = (
    "db.sqlite3",
    "db_ps_cs_cn.sqlite3",
    "fw_db.sqlite",
)

MIRROR_ENABLED = os.environ.get(
    "NATIVE_BOARD_MIRROR", "1").strip().lower() not in ("0", "false", "no", "off")
MIRROR_TTL = int(os.environ.get("NATIVE_BOARD_MIRROR_TTL", "900"))
PAGE = int(os.environ.get("NATIVE_BOARD_MIRROR_PAGE", "5000"))
FULL_RESYNC_HOURS = float(os.environ.get("NATIVE_BOARD_MIRROR_FULL_HOURS", "24"))
# 每轮最多整表重拉几张：33 张表例行校准分散到多轮，避免某一轮把远端打满。
# 「必须全量」（首次 / 表被重建 / 行数变少）不受此预算限制。
MAX_FULL_PER_RUN = int(os.environ.get("NATIVE_BOARD_MIRROR_MAX_FULL", "3"))
QUERY_TIMEOUT = 90

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_SYNC_LOCK = threading.Lock()

# FROM / JOIN 后面的表名（支持带双引号、数字开头的表名）
_FROM_RE = re.compile(
    r'\b(?:FROM|JOIN)\s+(?:"([^"]+)"|\'([^\']+)\'|([A-Za-z0-9_][A-Za-z0-9_]*))',
    re.IGNORECASE)


# ----------------------------------------------------------------------
# 远端只读 API
# ----------------------------------------------------------------------
def _api_base() -> str:
    from backend.config.remote_host import get_api_base_url
    return get_api_base_url().rstrip("/")


def remote_query(db: str, sql: str, limit: int = PAGE,
                 timeout: int = QUERY_TIMEOUT) -> Dict[str, Any]:
    payload = json.dumps({"db": db, "sql": sql, "limit": limit},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _api_base() + "/api/query", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with _OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def remote_tables(db: str) -> Set[str]:
    url = _api_base() + "/api/tables?db=" + urllib.parse.quote(db)
    with _OPENER.open(url, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    return {x["name"] for x in (data.get("tables") or [])}


# ----------------------------------------------------------------------
# 表清单：只镜像看板真正引用的表
# ----------------------------------------------------------------------
def referenced_tables() -> Dict[str, Set[str]]:
    from backend.services.native_catalog import DASHBOARDS

    raw: Dict[str, Set[str]] = {d: set() for d in REMOTE_DBS}
    for board in DASHBOARDS:
        for w in board.get("widgets") or []:
            db = w.get("db") or ""
            if db not in raw:
                continue
            sql = w.get("sql") or ""
            for m in _FROM_RE.finditer(sql):
                name = m.group(1) or m.group(2) or m.group(3)
                if name:
                    raw[db].add(name)
    # SQL 里的子查询别名（agg / e / u / sk / ...）用远端真实表清单过滤掉
    out: Dict[str, Set[str]] = {}
    for db, names in raw.items():
        actual = remote_tables(db)
        keep = names & actual
        out[db] = keep
        skipped = sorted(names - actual)
        logger.info("[MIRROR] %s 引用 %d 张表，别名/无效 %d：%s",
                    db, len(keep), len(skipped), skipped[:8])
    return out


def mirror_path(db: str) -> Path:
    return MIRROR_DIR / (db.replace(".", "_") + ".sqlite3")


def mirror_alias(db: str) -> str:
    return "__local_mirror_" + db.replace(".", "_") + "__"


def _ident(name: str) -> str:
    """双引号标识符，内部双引号加倍。"""
    return '"' + str(name).replace('"', '""') + '"'


# ----------------------------------------------------------------------
# 本机镜像库
# ----------------------------------------------------------------------
def _open_local(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=60)
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute(
        "CREATE TABLE IF NOT EXISTS _mirror_meta ("
        "db TEXT NOT NULL, tbl_name TEXT NOT NULL, max_rid INTEGER NOT NULL, "
        "row_count INTEGER NOT NULL, synced_at REAL NOT NULL, full_at REAL NOT NULL, "
        "PRIMARY KEY (db, tbl_name))")
    con.commit()
    return con


def _meta(con: sqlite3.Connection, db: str, table: str):
    return con.execute(
        "SELECT max_rid, row_count, full_at FROM _mirror_meta "
        "WHERE db=? AND tbl_name=?", (db, table)).fetchone()


def _signature(db: str, table: str) -> Tuple[int, int]:
    res = remote_query(
        db, f'SELECT COUNT(*) AS n, COALESCE(MAX(rowid),0) AS mx FROM {_ident(table)}',
        limit=5)
    row = (res.get("rows") or [[0, 0]])[0]
    return int(row[0] or 0), int(row[1] or 0)


def _fetch_pages(db: str, table: str,
                 since_rid: int) -> Iterable[List[list]]:
    """按 rowid 分页拉整表 / 增量，yield 整行（含首列 __rid）。"""
    rid = since_rid
    while True:
        sql = (f'SELECT rowid AS "__rid", * FROM {_ident(table)} '
               f'WHERE rowid > {rid} ORDER BY rowid')
        res = remote_query(db, sql, limit=PAGE)
        if not res.get("success", True):
            raise RuntimeError(f"{db}.{table} 分页查询失败: {res.get('error')}")
        rows = res.get("rows") or []
        if not rows:
            return
        yield rows
        rid = int(rows[-1][0])
        if len(rows) < PAGE:
            return


def _create_table(con: sqlite3.Connection, table: str, cols: List[str]) -> None:
    con.execute(f"DROP TABLE IF EXISTS {_ident(table)}")
    # 不声明类型：数字保持数字、文本保持文本，与远端完全一致
    con.execute(f"CREATE TABLE {_ident(table)} ("
                + ", ".join(_ident(c) for c in cols) + ")")


def _insert(con: sqlite3.Connection, table: str, cols: List[str],
            body: List[list]) -> None:
    if not body:
        return
    ph = ",".join("?" for _ in cols)
    con.executemany(
        f"INSERT INTO {_ident(table)} VALUES ({ph})", body)


def sync_table(con: sqlite3.Connection, db: str, table: str,
               force_full: bool = False, dry_run: bool = False,
               allow_full: bool = True) -> Dict[str, Any]:
    t0 = time.time()
    n_remote, max_rid = _signature(db, table)
    meta = _meta(con, db, table)
    local_n = meta[1] if meta else 0
    local_rid = meta[0] if meta else 0
    full_at = meta[2] if meta else 0.0

    # 必须全量：首次 / 上游删行 / rowid 倒退（表被重建）/ CLI --full。
    # 例行校准：24h 到点，为覆盖「UPDATE 改内容但 rowid 不变」的情况；
    # 这类可以分摊到多轮（allow_full），不必一轮把 33 张表全拉一遍。
    hard_full = (force_full or meta is None or n_remote < local_n
                 or max_rid < local_rid)
    soft_full = (not hard_full
                 and (time.time() - full_at) > FULL_RESYNC_HOURS * 3600)
    if soft_full and not allow_full:
        return {"table": table, "mode": "skip", "rows": 0,
                "elapsed": round(time.time() - t0, 2)}
    need_full = hard_full or soft_full

    # 远端没变且不需要全量 -> 直接跳过
    if not need_full and n_remote == local_n and max_rid == local_rid:
        return {"table": table, "mode": "skip", "rows": 0,
                "elapsed": round(time.time() - t0, 2)}

    if dry_run:
        return {"table": table, "mode": "full" if need_full else "delta",
                "rows": n_remote if need_full else n_remote - local_n,
                "elapsed": 0.0}

    # 拿真实列名（远端 SELECT * 的 columns）
    probe = remote_query(db, f'SELECT * FROM {_ident(table)}', limit=1)
    cols = list(probe.get("columns") or [])
    if not cols:
        # 空表：用远端 sqlite_master 拿列定义
        raise RuntimeError(f"{db}.{table} 为空表且无法取列名，跳过镜像")

    written = 0
    start_rid = 0 if need_full else local_rid

    # DDL 与 INSERT 放同一事务：中途失败可整体回滚，不会留下半张空表
    con.execute("BEGIN")
    try:
        if need_full:
            _create_table(con, table, cols)
        for rows in _fetch_pages(db, table, start_rid):
            body = [r[1:] for r in rows]  # 去掉 __rid
            _insert(con, table, cols, body)
            written += len(body)
        con.execute(
            "INSERT OR REPLACE INTO _mirror_meta "
            "(db, tbl_name, max_rid, row_count, synced_at, full_at) "
            "VALUES (?,?,?,?,?,?)",
            (db, table, max_rid, (written if need_full else local_n + written),
             time.time(), time.time() if need_full else full_at))
        con.commit()
    except Exception:
        con.rollback()
        raise

    return {"table": table, "mode": "full" if need_full else "delta",
            "rows": written, "elapsed": round(time.time() - t0, 2)}


def sync_all(force_full: bool = False, dry_run: bool = False,
             only: Optional[List[str]] = None,
             tables: Optional[Dict[str, Set[str]]] = None) -> Dict[str, Any]:
    """同步全部（或指定的）库。返回每库每表的结果。"""
    if not _SYNC_LOCK.acquire(blocking=False):
        return {"status": "busy", "detail": "已有同步在进行"}
    started = time.time()
    result: Dict[str, Any] = {"status": "ok", "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "dbs": {}, "errors": []}
    try:
        plans = tables or referenced_tables()
        for db in REMOTE_DBS:
            if only and db not in only:
                continue
            names = sorted(plans.get(db) or set())
            if not names:
                continue
            path = mirror_path(db)
            # dry-run 不建库
            con = None if dry_run else _open_local(path)
            items = []
            full_used = 0
            try:
                for t in names:
                    try:
                        r = sync_table(con, db, t, force_full, dry_run,
                                       allow_full=full_used < MAX_FULL_PER_RUN) if con \
                            else _dry_table(db, t, force_full)
                        if r["mode"] == "full":
                            full_used += 1
                        r["table"] = t
                        items.append(r)
                        logger.info("[MIRROR] %-22s %-40s %-5s %7d rows %6.1fs",
                                    db, t, r["mode"], r["rows"], r["elapsed"])
                    except Exception as e:  # noqa: BLE001 - 单表失败不影响其它表
                        msg = f"{db}.{t}: {e!r}"
                        logger.warning("[MIRROR] %s", msg)
                        result["errors"].append(msg)
                        if con:
                            con.rollback()
                if con:
                    con.commit()
            finally:
                if con:
                    con.close()
            result["dbs"][db] = {
                "path": str(path), "tables": items,
                "rows": sum(x["rows"] for x in items),
                "size_mb": round(path.stat().st_size / 1048576, 2) if path.exists() else 0,
            }
    finally:
        _SYNC_LOCK.release()
    result["elapsed_s"] = round(time.time() - started, 1)
    result["status"] = "ok" if not result["errors"] else "partial"
    return result


def _dry_table(db: str, table: str, force_full: bool) -> Dict[str, Any]:
    n, rid = _signature(db, table)
    return {"mode": "full" if force_full else "delta", "rows": n,
            "elapsed": 0.0}


# ----------------------------------------------------------------------
# 后台守护（uvicorn 进程内，随 watchdog 拉起自动恢复）
# ----------------------------------------------------------------------
_daemon_started = False


def start_mirror_daemon(initial_delay: float = 60) -> None:
    global _daemon_started
    if _daemon_started or not MIRROR_ENABLED:
        return
    _daemon_started = True

    def _loop() -> None:
        # 默认启动后先等一会儿，避免刚拉起就抢远端带宽
        if initial_delay > 0:
            time.sleep(initial_delay)
        while True:
            try:
                r = sync_all()
                logger.info("[MIRROR] 后台同步完成 status=%s %.1fs errors=%d",
                            r["status"], r["elapsed_s"], len(r["errors"]))
            except Exception as e:  # noqa: BLE001 - 守护线程绝不能死
                logger.warning("[MIRROR] 后台同步异常: %r", e)
            time.sleep(max(60, MIRROR_TTL))

    threading.Thread(target=_loop, name="native-board-mirror", daemon=True).start()
    logger.info("[MIRROR] 后台同步已启动 ttl=%ss page=%d", MIRROR_TTL, PAGE)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="看板远端数据源本机镜像")
    ap.add_argument("--full", action="store_true", help="强制整表重拉")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划")
    ap.add_argument("--db", action="append", help="只同步指定库（可重复）")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    r = sync_all(force_full=a.full, dry_run=a.dry_run, only=a.db)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["status"] in ("ok", "busy") else 1


if __name__ == "__main__":
    sys.exit(main())

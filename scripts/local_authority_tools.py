#!/usr/bin/env python
"""local_authority_tools.py —— 迁移时保住 SQLite「本地权威表」的工具
=====================================================================

为什么需要它（2026-11-11 实测事故）：
    运行副本 ``D:\\01_olbr_portal`` 从编辑区 ``D:\\01_RPA`` 迁移过来后，
    16 个任务同时报「拒绝以空密码登录」。根因不是网络、不是上游，而是副本
    ``Task\\my_app\\db\\app.db`` 里的三张表**一行都没有**：

        credentials            → 设置页填的口令（20 组全空 → 所有任务拿空密码）
        task_schedule_config   → 任务启停 / cron（74 行全空 → 任务管理页的禁用全丢，
                                 原本被手动停掉的 4 个 WhatsApp 任务反而开始跑）
        email_recipients       → 邮件收件人名单（10 行全空 → 邮件任务没有收件人）

这三张表与 ``MY_APP_DB_MODE`` 无关，由应用**固定写 SQLite**，PG 里那份只是镜像：

    - credentials          ← backend/services/credential_store.py 硬编码 sqlite3.connect
    - email_recipients     ← backend/services/email_recipient_store.py 同样硬编码
    - task_schedule_config ← backend/services/task_runner.py::_save_schedule_config

正因如此，``backend/scripts/sync_pg_to_sqlite.py`` 把它们列进 ``SKIP_TABLES``
（否则 PG→SQLite 同步会把本地数据 DROP 掉，见该文件 61-85 行的两次事故记录）。
副作用是：**从 PG 重建 app.db 的部署路径永远不会带出这三张表**，而同步器又
从不搬 ``db/`` 目录。迁移时没人补这一步，就必然出现本次的「全空密码 + 启停全丢」。

本工具只做两件事，都刻意不打印任何口令/Token：

    check    比对源/目标 app.db 的三表行数，目标为空而源非空时以非零码退出，
             让部署脚本**当场拦住**「静默丢凭据」而不是等任务批量失败才被发现。
    migrate  把三张表从源 app.db 复制到目标 app.db（先备份到 TMP、事务内替换、
             逐行哈希校验），幂等，可 -dry-run 预览。

用法（在编辑区运行，路径按实际调整）：

    python scripts\\local_authority_tools.py check ^
        --source Task\\my_app\\db\\app.db --target D:\\01_olbr_portal\\Task\\my_app\\db\\app.db

    python scripts\\local_authority_tools.py migrate ^
        --source Task\\my_app\\db\\app.db --target D:\\01_olbr_portal\\Task\\my_app\\db\\app.db

退出码：0 正常；2 需要迁移（check 专用）；3 参数/文件错误；4 执行失败。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

# Windows 控制台默认按系统代码页（cp936/cp1252）编码 stdout，直接 print 中文会
# UnicodeEncodeError。这里显式改 UTF-8；deploy_to_copy.ps1 调用时会同时设
# PYTHONIOENCODING=utf-8 与 Console.OutputEncoding=UTF8，两边一致。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # 老解释器/被重定向时忽略，不因此影响主流程
    pass

# 与 backend/scripts/sync_pg_to_sqlite.py::SKIP_TABLES 中的「本地权威表」保持一致。
# 加表/删表时两处必须同改 —— 这里只做迁移校验，不参与运行时读写。
LOCAL_AUTHORITY_TABLES = ("credentials", "task_schedule_config", "email_recipients")

EXIT_OK = 0
EXIT_NEED_MIGRATE = 2
EXIT_USAGE = 3
EXIT_FAILED = 4


def _ro(path: Path) -> sqlite3.Connection:
    """只读打开；文件不存在直接报错，避免「空库也算通过」的假阴性。"""
    if not path.is_file():
        raise FileNotFoundError(f"找不到数据库文件：{path}")
    uri = "file:%s?mode=ro" % str(path).replace("\\", "/")
    con = sqlite3.connect(uri, uri=True, timeout=5)
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _rw(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _count(con: sqlite3.Connection, table: str) -> int:
    if table not in _tables(con):
        return -1
    return int(con.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0])


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute("PRAGMA table_info(%s)" % table)]


def _digest(rows: list[tuple]) -> str:
    """逐行序列化后整体哈希；只在本进程内比对，不落盘、不打印。"""
    h = hashlib.sha256()
    for row in sorted((tuple(str(x) for x in r) for r in rows)):
        h.update(json.dumps(row, ensure_ascii=False).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _table_rows(con: sqlite3.Connection, table: str) -> list[tuple]:
    cols = _columns(con, table)
    if not cols:
        return []
    return con.execute('SELECT %s FROM "%s"' % (",".join(cols), table)).fetchall()


def _summary(source: Path, target: Path) -> dict:
    out = {"source": str(source), "target": str(target), "tables": {}}
    with _ro(source) as s, _ro(target) as t:
        for table in LOCAL_AUTHORITY_TABLES:
            out["tables"][table] = {
                "source_rows": _count(s, table),
                "target_rows": _count(t, table),
            }
    return out


def cmd_check(args: argparse.Namespace) -> int:
    source, target = Path(args.source), Path(args.target)
    try:
        info = _summary(source, target)
    except FileNotFoundError as exc:
        print(f"[FAIL] {exc}")
        print("[HINT] 目标 app.db 不存在：副本至少要启动过一次才会建库；建库后再跑一次本检查。")
        return EXIT_FAILED

    need = []
    for table, counts in info["tables"].items():
        print(
            "  %-22s source=%-4s target=%-4s" % (table, counts["source_rows"], counts["target_rows"])
        )
        if counts["target_rows"] <= 0 and counts["source_rows"] > 0:
            need.append(table)

    if args.json:
        print(json.dumps({"info": info, "need_migrate": need}, ensure_ascii=False))

    if need:
        print("")
        print("[FAIL] 副本缺本地权威表数据：" + ", ".join(need))
        print("       这三张表不走 PG、同步器也不搬 db/，迁移时必须单独搬一次：")
        print(
            "       python scripts\\local_authority_tools.py migrate "
            "--source <旧 app.db> --target <新 app.db>"
        )
        return EXIT_NEED_MIGRATE

    print("[ OK ] 本地权威表在副本中已有数据（或源库本身为空，无可迁移内容）")
    return EXIT_OK


def cmd_migrate(args: argparse.Namespace) -> int:
    source, target = Path(args.source), Path(args.target)
    if source.resolve() == target.resolve():
        print("[FAIL] 源与目标是同一个文件，拒绝自我覆盖")
        return EXIT_USAGE
    try:
        info = _summary(source, target)
    except FileNotFoundError as exc:
        print(f"[FAIL] {exc}")
        return EXIT_USAGE

    todo = [t for t, c in info["tables"].items() if c["source_rows"] > 0]
    if not todo:
        print("[ OK ] 源库三张表都是空的，没有可迁移的内容（新部署请按设置页填）")
        return EXIT_OK

    if args.dry_run:
        for table in LOCAL_AUTHORITY_TABLES:
            c = info["tables"][table]
            print("  %-22s source=%-4s target=%-4s" % (table, c["source_rows"], c["target_rows"]))
        print("[DRY-RUN] 以上为计划；加 -DryRun 去掉后正式执行（会先备份到 TMP/）。")
        return EXIT_OK

    # 备份目标表当前内容（JSON，含敏感值，只落 TMP/ 且不入库）
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_dir = target.parent.parent.parent / "TMP"
    if not tmp_dir.is_dir():
        tmp_dir = Path(args.backup_dir) if args.backup_dir else Path.cwd() / "TMP"
        tmp_dir.mkdir(parents=True, exist_ok=True)
    backup = tmp_dir / ("_bak_local_authority_%s.json" % stamp)

    with _ro(source) as s, _rw(target) as t:
        snapshot = {}
        for table in todo:
            snapshot[table] = {"columns": _columns(t, table), "rows": _table_rows(t, table)}
        backup.write_text(json.dumps(snapshot, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"[INFO] 已备份目标表现状 -> {backup}")

        for table in todo:
            dcols = _columns(t, table)
            scols = _columns(s, table)
            if not dcols or not scols:
                print(f"[WARN] 跳过 {table}：源或目标缺表（目标会在应用启动时重建，重跑一次即可）")
                continue
            if set(scols) != set(dcols):
                print(f"[FAIL] {table} 列不一致：source={scols} target={dcols}")
                return EXIT_USAGE
            srows = s.execute('SELECT %s FROM "%s"' % (",".join(scols), table)).fetchall()
            # 按目标列名重排，避免 two DB 的列顺序不同（task_schedule_config 就不同）
            order = [scols.index(c) for c in dcols]
            mapped = [tuple(r[i] for i in order) for r in srows]
            with t:  # 事务：要么整表替换成功，要么保持原样
                t.execute('DELETE FROM "%s"' % table)
                t.executemany(
                    'INSERT OR REPLACE INTO "%s" (%s) VALUES (%s)'
                    % (table, ",".join(dcols), ",".join("?" for _ in dcols)),
                    mapped,
                )
            after = _count(t, table)
            same = _digest(mapped) == _digest(_table_rows(t, table))
            print(f"  {table:<22} 写入 {len(mapped):<4} 行，目标现有 {after:<4} 行，哈希一致={same}")
            if after != len(mapped) or not same:
                print(f"[FAIL] {table} 校验不通过，停止。可用备份回滚：{backup}")
                return EXIT_FAILED

    print("[ OK ] 本地权威表迁移完成（credentials / task_schedule_config / email_recipients）")
    print("[HINT] 若后端在运行：凭据 30 秒内生效；任务启停请到任务管理页确认（或重开页面）。")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SQLite 本地权威表检查/迁移工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="比对源/目标三表行数；目标空而源非空时退出码 2")
    p_check.add_argument("--source", required=True, help="旧/权威 app.db 路径")
    p_check.add_argument("--target", required=True, help="新/运行副本 app.db 路径")
    p_check.add_argument("--json", action="store_true", help="额外输出 JSON")
    p_check.set_defaults(func=cmd_check)

    p_mig = sub.add_parser("migrate", help="把三张本地权威表从源复制到目标")
    p_mig.add_argument("--source", required=True, help="旧/权威 app.db 路径")
    p_mig.add_argument("--target", required=True, help="新/运行副本 app.db 路径")
    p_mig.add_argument("--dry-run", action="store_true", help="只打印计划，不写库")
    p_mig.add_argument("--backup-dir", default="", help="备份目录（默认取副本 TMP/）")
    p_mig.set_defaults(func=cmd_migrate)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except sqlite3.OperationalError as exc:
        print(f"[FAIL] SQLite 操作失败（目标库被占用时会这样，稍后重试）：{exc}")
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())

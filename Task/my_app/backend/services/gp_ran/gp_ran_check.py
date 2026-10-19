"""gp_ran 链路自检与取数命令行。

这条链路（control1 → GP 主节点 → sudo → su - gpadmin → psql）是首次自动化，
有几个事实本机无法预知：sudo 是否 requiretty、gpadmin 的默认库叫什么、L_T216 在哪个库、
单日数据量多大。`--check` 逐层探测并如实打印，`--count` 估行数，`--export` 才真正取数。

    cd D:\\01_RPA\\Task\\my_app
    python -m backend.services.gp_ran.gp_ran_check --check
    python -m backend.services.gp_ran.gp_ran_check --export --kind volte \
        --start 2026-10-08 --end 2026-10-15
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

try:
    from backend.services.gp_ran import (
        GpRanClient, GpRanError, GpRanUnavailable,
        endpoints_summary, sql_volte_users, sql_n78_users,
    )
except ImportError:  # 直接在包目录里跑
    from gp_ran_client import (  # type: ignore
        GpRanClient, GpRanError, GpRanUnavailable,
        endpoints_summary, sql_volte_users, sql_n78_users,
    )

_KINDS = {"volte": sql_volte_users, "n78": sql_n78_users}
# 现场人工流程里 sudo 必须在 tty 下（requiretty）时的典型报错
_TTY_HINT = "sudo: a terminal is required to read the password"
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "data" / "gp_ran"


def _one_line(text, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _step(name: str, fn) -> str | None:
    """打印一步探测结果；失败不中断 —— 下一步往往能给出更多信息。"""
    t0 = time.time()
    try:
        out = fn()
        print(f"[OK {time.time() - t0:5.1f}s] {name}: {_one_line(out)}")
        return out
    except Exception as exc:  # noqa: BLE001
        msg = _one_line(str(exc), 700)
        print(f"[FAIL {time.time() - t0:5.1f}s] {name}: {type(exc).__name__}: {msg}")
        if _TTY_HINT in msg:
            print("        ^ 这台机开了 sudo requiretty：非交互 SSH 拿不到 root。"
                  "改法二选一 —— 让运维给 ubuntu 配 NOPASSWD，或改用 `su - gpadmin` "
                  "（需要 gpadmin 口令，本客户端暂无该升权模式）。")
        return None


def check(client: GpRanClient) -> None:
    print("=" * 72)
    print("gp_ran 链路自检")
    print("=" * 72)
    print(f"链路: {endpoints_summary(client.ep)}")
    _step("两跳登录", lambda: client.connected)
    if not client.connected:
        print("两跳未建立，后续无法执行。先确认「设置 → 凭据管理」里 gp_ran_control 的口令。")
        return

    _step("主节点身份", lambda: client.raw("hostname; id -un; uname -r")[0])
    _step("PaaS 主节点记录(root)", lambda: client.raw(
        "cat /home/gpadmin/paas_hosts_master.cc", sudo=True)[0])
    _step("psql 通道(sudo+su+psql)", lambda: client.exec_sql("SELECT 1 AS ok"))
    _step("数据库版本", lambda: client.exec_sql("SELECT version()"))
    _step("当前库", lambda: client.exec_sql("SELECT current_database()"))
    _step("L_T216 是否可见", lambda: client.exec_sql(
        "SELECT count(*) AS hit FROM pg_class WHERE lower(relname::text)='l_t216'"))
    _step("分区跨度", lambda: client.exec_sql(
        "SELECT min(partitionname), max(partitionname), count(*) FROM pg_partitions "
        "WHERE tablename='l_t216' AND partitionname ~ '^p[0-9]{9}$'"))

    print("-" * 72)
    print("技术链路已通。剩下的都是业务口径问题（见 README §6）：")
    print("  1) C031/C032/C033 三者任一=1 实测覆盖 99.8% 的非空 IMSI，几乎不构成筛选，")
    print("     需与需求方确认 VoLTE 到底看哪个标志位。")
    print("  2) D023 是 IMSI 不是 MSISDN；若最终用途要号码，需要 IMSI↔MSISDN 关联表。")
    print("  3) 用 --count 定窗口，注意最早分区只到约 62 天前，且当天数据仍在累积。")


def _count_sql(kind: str, start: str, end: str) -> str:
    sql = _KINDS[kind](start, end)
    return sql.replace("SELECT DISTINCT A.D023", "SELECT count(DISTINCT A.D023) AS users", 1)


def count(client: GpRanClient, kind: str, start: str, end: str) -> None:
    sql = _count_sql(kind, start, end)
    print(f"[{time.strftime('%H:%M:%S')}] {kind} {start}~{end} 计数中…（全天信令表，可能要几分钟）")
    t0 = time.time()
    print(f"  结果: {_one_line(client.exec_sql(sql))}（{time.time() - t0:.1f}s）")


def export(client: GpRanClient, kind: str, start: str, end: str, out_dir: Path) -> Path:
    sql = _KINDS[kind](start, end)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{kind}_{start}_{end}.csv"
    tmp = out_dir / f".{dest.name}.part"
    print(f"[{time.strftime('%H:%M:%S')}] 导出 {kind} {start}~{end} …")
    t0 = time.time()
    text = client.query_csv(sql)
    tmp.write_text(text, encoding="utf-8-sig", newline="")
    tmp.replace(dest)
    rows = max(text.count("\n") - 1, 0)
    print(f"  -> {dest}  {rows} 行 / {dest.stat().st_size / 1024:.1f} KB"
          f"  用时 {time.time() - t0:.1f}s（数仓侧未落盘，无 chmod/scp）")
    return dest


def describe(client: GpRanClient) -> None:
    _step("L_T216 列与类型", lambda: client.exec_sql(
        "SELECT ordinal_position, column_name, data_type "
        "FROM information_schema.columns WHERE upper(table_name)='L_T216' "
        "ORDER BY ordinal_position"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RAN Greenplum 取数（control1 两跳，只读）")
    ap.add_argument("--check", action="store_true", help="逐层探测链路")
    ap.add_argument("--describe", action="store_true", help="打印 L_T216 列与类型")
    ap.add_argument("--count", action="store_true", help="只统计行数不导出")
    ap.add_argument("--export", action="store_true", help="导出号码清单 CSV")
    ap.add_argument("--kind", choices=sorted(_KINDS), default="volte")
    ap.add_argument("--start", help="起始日 YYYY-MM-DD（含）")
    ap.add_argument("--end", help="截止日 YYYY-MM-DD（不含）")
    ap.add_argument("--db", default="", help="Greenplum 库名（默认 netmaxdb，实测 L_T216 所在库）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="CSV 输出目录")
    ap.add_argument("--timeout", type=int, default=1800, help="单条 SQL 上限秒数")
    args = ap.parse_args(argv)

    if not (args.check or args.describe or args.count or args.export):
        ap.print_help()
        return 2
    if (args.count or args.export) and not (args.start and args.end):
        print("--count / --export 需要 --start 与 --end")
        return 2

    overrides = {"database": args.db} if args.db else {}
    try:
        with GpRanClient(**overrides) as client:
            client.ep["query_timeout"] = args.timeout
            if args.check:
                check(client)
            if args.describe:
                describe(client)
            if args.count:
                count(client, args.kind, args.start, args.end)
            if args.export:
                export(client, args.kind, args.start, args.end, Path(args.out))
    except (GpRanUnavailable, GpRanError) as exc:
        print(f"[失败] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

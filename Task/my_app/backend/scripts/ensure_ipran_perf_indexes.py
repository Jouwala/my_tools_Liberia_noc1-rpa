# -*- coding: utf-8 -*-
"""给本机 PG 的 ipran_ume 表补「按设备+端口」侧的查询索引（可重复执行）。

为什么需要（2026-11-05）
------------------------
IP RAN 四个看板自 11-04 起读本机 PG `ipran_ume`，11-05 默认窗口又从 7 天放到 31 天，
`finebi_metro_ring` 整页冷取涨到 **9~21 秒**。原因不在数据量而在**索引形状**：

    现有唯一索引 = ("Begin Time", "ME", "Measure Object"[, "Counter"])
    看板 SQL 的谓词 = WHERE "ME"=? AND "Measure Object"=? AND "Begin Time" 区间

前导列是 `Begin Time`，等值条件用不上，于是每查一个端口都要把时间区间内的
**全部**索引条目走一遍（Metro_ring 31 天 ≈ 340 万条）再丢掉 99.9%。
实测线性放大：5 天窗口 1.2s、31 天约 10s。补一个以等值列打头的索引，
扫描条目直接降到匹配行数本身（约 3 千条）。

用法（生产 Python 3.12，需要 psycopg2）::

    cd D:\\01_RPA\\Task\\my_app
    # 只看要执行什么、并记录当前耗时基线（不建索引）
    py -3.12 -m backend.scripts.ensure_ipran_perf_indexes --dry-run --measure
    # 实建（CONCURRENTLY，不阻塞采集写入；重复执行是幂等的）
    py -3.12 -m backend.scripts.ensure_ipran_perf_indexes --measure
    # 只补指定表
    py -3.12 -m backend.scripts.ensure_ipran_perf_indexes --tables Metro_ring_me_15mins

为什么用 CREATE INDEX CONCURRENTLY
----------------------------------
采集每小时往这些表 upsert 数据，普通 `CREATE INDEX` 会持 SHARE 锁把写入挡住；
CONCURRENTLY 不阻塞写，代价是扫描两遍、耗时更长，且**中途失败会留下 INVALID 索引**
（不占用于查询，但会让后续 CONCURRENTLY 因重名失败）—— 本脚本每次都回查
`pg_index.indisvalid` 并显式报出来，附清理命令。

设计取舍
--------
- 索引列**按各表真实谓词给**：`Gbarnga_Buchanna_RIA_Kakata_me_15mins` 的 8 个组件
  只按 ME 过滤（区域聚合，不指定端口），所以它建 `(ME, "Begin Time")` 而不是
  顺手多加一列 `Measure Object` —— 不为「以后也许用得上」付索引体积。
- 不动那个唯一索引：`mirror_rows_to_local` 的 `ON CONFLICT` 依赖它，upsert 幂等靠它。
- 不在采集服务的热路径里做 DDL：本脚本独立可重跑，新机器/重建库后执行一次即可。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:   # backend 可导入
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCHEMA = "ipran_ume"

# 表名 → (索引列, 用于计时/探测的代表性谓词)
# 谓词取自 backend/services/native_catalog.py 里该表真实组件的 WHERE（见各注释）。
PLAN: dict[str, tuple[tuple[str, ...], dict[str, str]]] = {
    # metro_ring 8 个组件：ME + Measure Object（native_catalog c1..c8）
    "Metro_ring_me_15mins": (
        ("ME", "Measure Object", "Begin Time"),
        {"ME": "9000-8EA_SPE01", "Measure Object": "P90E-2CGT-Q28[0-0-4-0]-100GE:1"},
    ),
    # ipran_4region 8 个组件：只按 ME 过滤（区域聚合，Measure Object 不限）
    "Gbarnga_Buchanna_RIA_Kakata_me_15mins": (
        ("ME", "Begin Time"),
        {"ME": "6180H-A_RIA_UPE24"},
    ),
    # ipran_hq c5/c6：ME + Measure Object
    "Banjor_ELWA_me_15mins": (
        ("ME", "Measure Object", "Begin Time"),
        {"ME": "6120H-S_Banjor_UPE18", "Measure Object": "SMGD[0-1-1]-25GE:20"},
    ),
    # ipran_hq c1/c2（pivot 按 Counter 再分）：ME + Measure Object
    "IPCORE_HQ_ODC_bnctp_15mins": (
        ("ME", "Measure Object", "Begin Time"),
        {"ME": "HQ-M6K-8S_Plus_PS01", "Measure Object": "SmartGroup:9"},
    ),
    # ipran_hq c3：ME + Measure Object
    "OLT_bnctp_15mins": (
        ("ME", "Measure Object", "Begin Time"),
        {"ME": "9000-8EA_SPE02", "Measure Object": "P90E-4XGET-SFP+[0-0-0-1]-10GE:3"},
    ),
    # ipran_hq c4：ME + Measure Object
    "HQ_M6K_FW_bnctp_15mins": (
        ("ME", "Measure Object", "Begin Time"),
        {"ME": "HQ-M6K-8S_Plus_PS01", "Measure Object": "SmartGroup:3"},
    ),
}

DAYS = 31     # 计时窗口 = 看板默认窗口（PUSH_DOWN_DAYS）


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _index_name(table: str, cols: tuple[str, ...]) -> str:
    """索引名：ix_<表名>_<列首字母>，控制在 PG 的 63 字节标识符上限内。"""
    tag = "_".join(c[0] for c in cols)
    name = f"ix_{table}_{tag}"
    return name[:63]


def _existing(conn, table: str) -> list[tuple[str, list[str], bool]]:
    """返回该表现有索引 (名称, 列清单, 是否有效)。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname,
                   (SELECT array_agg(pg_get_indexdef(i.indexrelid, k.attnum, true))
                      FROM generate_series(1, i.indnatts) AS k(attnum)) AS cols,
                   i.indisvalid
              FROM pg_index i
              JOIN pg_class c ON c.oid = i.indexrelid
             WHERE i.indrelid = (%s::regclass)::oid
            """,
            (f"{SCHEMA}.{_q(table)}",))
        rows = cur.fetchall()
    out = []
    for name, cols, valid in rows:
        # pg_get_indexdef(.., true) 返回带引号的标识符，剥掉以便比较
        plain = [str(c).strip().strip('"') for c in (cols or [])]
        out.append((name, plain, bool(valid)))
    return out


def _probe_sql(table: str, cols: tuple[str, ...], pred: dict[str, str]) -> str:
    """与看板同形的计时查询：等值列 + Begin Time 区间 + 按时间分组。"""
    where = [f'{_q(k)} = %s' for k in pred]
    where.append(f'{_q("Begin Time")} >= \'-WSTART\' AND {_q("Begin Time")} < \'-WEND\'')
    return (f'SELECT substr({_q("Begin Time")},1,16) AS t, COUNT(*) '
            f'FROM {_q(table)} WHERE ' + " AND ".join(where) +
            f' GROUP BY 1 ORDER BY 1')


def _run_probes(conn, tables: list[str]) -> dict[str, dict]:
    """跑代表性查询计时（不建索引，用于前后对比）。"""
    from datetime import date, timedelta
    today = date.today()
    w_start = (today - timedelta(days=DAYS)).isoformat()
    w_end = (today + timedelta(days=1)).isoformat()
    res: dict[str, dict] = {}
    for t in tables:
        cols, pred = PLAN[t]
        sql = _probe_sql(t, cols, pred).replace("-WSTART", w_start).replace("-WEND", w_end)
        t0 = time.time()
        with conn.cursor() as cur:
            cur.execute(sql, tuple(pred.values()))
            n = len(cur.fetchall())
        res[t] = {"ms": round((time.time() - t0) * 1000, 1), "rows": n}
        print(f"    计时 {t:38s} {res[t]['ms']:9.1f}ms  返回 {n:6d} 行", flush=True)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables", default="", help="只处理指定表，逗号分隔（默认全部）")
    ap.add_argument("--dry-run", action="store_true", help="只打印要执行的 DDL，不建索引")
    ap.add_argument("--measure", action="store_true", help="顺带跑代表性查询计时（前后对比用）")
    args = ap.parse_args()

    from backend.database import DB_MODE, PG_DATABASE_URL
    if DB_MODE != "pg" or not PG_DATABASE_URL:
        print("ERROR: 需要 MY_APP_DB_MODE=pg 且 DATABASE_URL 可用", file=sys.stderr)
        return 2

    import psycopg2
    tables = ([x.strip() for x in args.tables.split(",") if x.strip()]
              if args.tables else list(PLAN))
    unknown = [t for t in tables if t not in PLAN]
    if unknown:
        print(f"ERROR: 不在 PLAN 清单里的表名: {unknown}", file=sys.stderr)
        return 2

    # CONCURRENTLY 不能在事务块里 → autocommit
    conn = psycopg2.connect(PG_DATABASE_URL, connect_timeout=15,
                            options=f"-c search_path={SCHEMA}")
    conn.set_session(readonly=False, autocommit=True)
    print(f"目标 schema={SCHEMA} 表={len(tables)} dry_run={args.dry_run}\n")

    if args.measure:
        print("=== 计时（执行前）===")
        _run_probes(conn, tables)

    created, skipped, invalid = [], [], []
    for t in tables:
        cols, _pred = PLAN[t]
        name = _index_name(t, cols)
        before = _existing(conn, t)
        same = [n for n, c, _v in before if tuple(c) == tuple(cols)]
        if same:
            print(f"[SKIP] {t}: 已有等价索引 {same}")
            skipped.append({"table": t, "indexes": same})
            continue
        ddl = f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_q(name)} ON {SCHEMA}.{_q(t)} ({', '.join(_q(c) for c in cols)})"
        print(f"[DDL ] {t}\n        {ddl}", flush=True)
        if args.dry_run:
            continue
        t0 = time.time()
        try:
            with conn.cursor() as cur:
                cur.execute(ddl)
        except psycopg2.Error as e:
            print(f"  FAILED: {str(e).strip()[:220]}", file=sys.stderr, flush=True)
            print("  若留下 INVALID 索引，清理后重试：\n"
                  f"    DROP INDEX CONCURRENTLY {SCHEMA}.{_q(name)};", file=sys.stderr)
            return 1
        el = time.time() - t0
        after = _existing(conn, t)
        bad = [n for n, _c, v in after if not v]
        invalid += bad
        with conn.cursor() as cur:
            cur.execute("SELECT pg_size_pretty(pg_relation_size(%s::regclass))", (f"{SCHEMA}.{_q(name)}",))
            size = cur.fetchone()[0]
        print(f"  建好 {name} 用时 {el:.1f}s 体积 {size}", flush=True)
        created.append({"table": t, "index": name, "seconds": round(el, 1), "size": size})

    if args.measure and not args.dry_run:
        print("\n=== 计时（执行后）===")
        _run_probes(conn, tables)
        # ANALYZE 让规划器立刻看到新索引的选择率
        with conn.cursor() as cur:
            for t in tables:
                cur.execute(f"ANALYZE {SCHEMA}.{_q(t)}")
        print("  已 ANALYZE（只更新统计信息，不改数据）")

    conn.close()
    print("\n=== 汇总 ===")
    print(json.dumps({"created": created, "skipped": skipped, "invalid": invalid},
                     ensure_ascii=False, indent=2))
    if invalid:
        print("⚠ 存在 INVALID 索引，必须 DROP 后重建（它们不会被查询使用）："
              f"{invalid}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

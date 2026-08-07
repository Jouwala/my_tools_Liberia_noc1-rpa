"""my_app 迁移 R5 一致性对账脚本（只读）。

比对 sqlite 源库 vs PostgreSQL 目标 schema：
  ① 表存在性 ② rowcount(COUNT(*)) ③ 抽样行 hash(固定种子, <=200 行, md5)
  ④ 数值列聚合(SUM/MIN/MAX, 可空跳过)

结论: PASS(差异率<0.1%) / FAIL / NOT_READY(全库空或表缺失)。
产物: 控制台摘要表 + JSON 差异报告 (默认 TMP/reconcile_report_<ts>.json)。

红线: 只读对账 —— PG 会话 READ ONLY，sqlite 以 mode=ro 打开，
绝不执行 INSERT/UPDATE/DELETE/DROP。密码不打印（仅输出脱敏连接串）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras

PROJECT_ROOT = Path(__file__).resolve().parents[2]   # D:\01_RPA\Task\my_app
BACKEND_DIR = PROJECT_ROOT / "backend"
TMP_DIR = PROJECT_ROOT / "TMP"

SAMPLE_SIZE = 200          # 每表抽样上限
RANDOM_SEED = 20260807     # 固定抽样种子
DIFF_THRESHOLD = 0.001     # 差异率阈值 0.1%
CHUNK_SIZE = 50_000        # sqlite 分块读取
PG_FETCH_SIZE = 10_000     # PG 服务端游标批读

PG_NUMERIC_TYPES = (
    "smallint", "integer", "bigint", "decimal", "numeric",
    "real", "double precision", "serial", "bigserial", "smallserial",
)

# 预期分叉表：sqlite 侧 alembic stamp 停在 0002，PG 侧已升级到 0004，
# 版本戳本就不同，不参与数据一致性判定。
EXCLUDE_TABLES = {"alembic_version"}

# PG 标识符上限（NAMEDATALEN-1）：超过 63 字节的列名会被静默截断，
# 对账时以此规则回退映射 sqlite 长列名 → PG 截断列名。
PG_MAX_IDENT = 63

# ---------------- 内置对账域（可被 --config JSON 覆盖） ----------------
# 每条 = {sqlite 路径(相对项目根), pg schema, 表清单(null=自动发现)}
DEFAULT_DOMAINS = {
    "battery": {
        "sqlite": "data/battery/battery_kpi.sqlite3",
        "pg_schema": "battery",
        "tables": None,
    },
    "ms_sla": {
        "sqlite": "data/ms_sla/lbr_ms_sla_kpi.sqlite3",
        "pg_schema": "ms_sla",
        "tables": None,
    },
    # ran_ume 读写两库分离：写库(backend/services) → ran_ume；读库(data/ran_ume) → ran_ume_ro
    "ran_ume": {
        "sqlite": "backend/services/ran_kpi_daily.sqlite3",
        "pg_schema": "ran_ume",
        "tables": None,
    },
    "ran_ume_ro": {
        "sqlite": "data/ran_ume/ran_kpi_daily.sqlite3",
        "pg_schema": "ran_ume_ro",
        "tables": None,
    },
    "lte_pl": {
        "sqlite": "data/packet_lost/lte_pl.sqlite3",
        "pg_schema": "lte_pl",
        "tables": None,
    },
    "fw": {
        "sqlite": "backend/services/fw_kpi/fw_db.sqlite",
        "pg_schema": "fw",
        "tables": None,
    },
    "eflow": {
        "sqlite": "data/eflow/eflow.sqlite3",
        "pg_schema": "eflow",
        "tables": None,
    },
    # app.db → PG app schema；PG 未搬运时应报 NOT_READY 而非崩溃。
    "app": {
        "sqlite": "db/app.db",
        "pg_schema": "app",
        "tables": None,
    },
}


# ---------------- 工具函数 ----------------
def load_env_file(path: Path) -> dict:
    """解析 backend/.env（不依赖 python-dotenv）。"""
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def mask_url(url: str) -> str:
    """脱敏连接串：隐藏密码，只留 host/db。"""
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", url)


def resolve_path(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else PROJECT_ROOT / path


def pick_output_path(base: Path) -> Path:
    """文件被占用时按规则追加 '_序号' 另存。"""
    if not base.exists():
        return base
    stem, suffix = base.stem, base.suffix
    for i in range(1, 100):
        cand = base.with_name(f"{stem}_{i}{suffix}")
        if not cand.exists():
            return cand
    raise RuntimeError("无法为报告找到可用文件名")


def md5_of_row(row) -> str:
    """对一行所有列归一化后拼接再 md5（跨库一致：NULL→空串、数值统一 float repr）。"""
    joined = "|".join(_norm_cell(v) for v in row)
    return hashlib.md5(joined.encode("utf-8", errors="replace")).hexdigest()


def _norm_cell(v) -> str:
    """跨库一致归一化：NULL→空串；数值统一 float repr（sqlite int 与 PG double 对齐）。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return repr(float(v))
    return str(v)


# ---------------- sqlite 侧（只读） ----------------
class SqliteSide:
    def __init__(self, path: Path):
        self.path = path
        self.exists = path.exists() and path.stat().st_size > 0
        self.conn = None
        if self.exists:
            # mode=ro 强制只读，杜绝任何写入
            self.conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)

    def tables(self) -> list:
        if not self.conn:
            return []
        if getattr(self, "_tables_cache", None) is None:
            rows = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            self._tables_cache = [r[0] for r in rows]
        return self._tables_cache

    def rowcount(self, table: str) -> int:
        return self.conn.execute(
            f'SELECT COUNT(*) FROM "{table}"'
        ).fetchone()[0]

    def sample_hashes(self, table: str, count: int) -> set:
        """rowid 取模抽样（固定种子），原生游标逐行 md5（与 PG 侧 ctid 物理位置对齐：
        rowid 从 1 起而 PG 位置从 0 起，故用 (rowid-1) 对齐）。"""
        if count <= 0:
            return set()
        mod = max(1, count // SAMPLE_SIZE)
        offset = RANDOM_SEED % mod
        cur = self.conn.execute(
            f'SELECT * FROM "{table}" '
            f"WHERE (rowid - 1) % {mod} = {offset} LIMIT {SAMPLE_SIZE}"
        )
        return {md5_of_row(r) for r in cur.fetchall()}

    def multiset_hashes(self, table: str) -> dict:
        """全表逐行 md5 计数（多重集）。顺序无关：行序/rowid 空洞不影响比对。"""
        out = {}
        for r in self.conn.execute(f'SELECT * FROM "{table}"'):
            hv = md5_of_row(r)
            out[hv] = out.get(hv, 0) + 1
        return out

    def numeric_columns(self, table: str) -> list:
        """以样本数据的实际可转数值性判定数值列（sqlite 类型亲和不可信）。"""
        try:
            sample = pd.read_sql(
                f'SELECT * FROM "{table}" LIMIT 1000', self.conn
            )
        except Exception:
            return []
        cols = []
        for col in sample.columns:
            s = sample[col].dropna()
            if s.empty:
                continue
            conv = pd.to_numeric(s, errors="coerce")
            if conv.notna().mean() >= 0.99:
                cols.append(str(col))
        return cols

    def aggregates(self, table: str, cols: list) -> dict:
        if not cols:
            return {}
        parts = ", ".join(
            f'SUM("{c}"), MIN("{c}"), MAX("{c}")' for c in cols
        )
        row = self.conn.execute(f'SELECT {parts} FROM "{table}"').fetchone()
        out = {}
        for i, c in enumerate(cols):
            out[c] = {"sum": row[3 * i], "min": row[3 * i + 1], "max": row[3 * i + 2]}
        return out

    def close(self):
        if self.conn:
            self.conn.close()


# ---------------- PG 侧（只读） ----------------
class PgSide:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.conn = psycopg2.connect(dsn, connect_timeout=15)
        self.conn.autocommit = False
        cur = self.conn.cursor()
        # 只读对账红线：会话级 READ ONLY，任何写语句都会被 PG 拒绝
        cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        cur.close()
        self.conn.commit()

    def schema_exists(self, schema: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (schema,))
        ok = cur.fetchone() is not None
        cur.close()
        return ok

    def tables(self, schema: str) -> list:
        cache = getattr(self, "_tables_cache", None) or {}
        if schema not in cache:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name",
                (schema,),
            )
            cache[schema] = [r[0] for r in cur.fetchall()]
            cur.close()
            self._tables_cache = cache
        return cache[schema]

    def rowcount(self, schema: str, table: str) -> int:
        cur = self.conn.cursor()
        cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
        n = cur.fetchone()[0]
        cur.close()
        return n

    def sample_hashes(self, schema: str, table: str, count: int) -> set:
        """按 ctid 物理位置取模抽样（与 sqlite 侧 rowid 取模对齐：搬运按原顺序写入，
        ctid 序 ≈ rowid 序），服务端游标流扫，逐行 md5。"""
        if count <= 0:
            return set()
        mod = max(1, count // SAMPLE_SIZE)
        offset = RANDOM_SEED % mod
        hashes = set()
        cur = self.conn.cursor(name=f"reconcile_{schema}_{table}"[:60])
        cur.arraysize = PG_FETCH_SIZE
        try:
            cur.execute(f'SELECT * FROM "{schema}"."{table}" ORDER BY ctid')
            i = 0
            for row in cur:
                if i % mod == offset:
                    hashes.add(md5_of_row(row))
                    if len(hashes) >= SAMPLE_SIZE:
                        break
                i += 1
        finally:
            cur.close()
        self.conn.rollback()  # 关闭服务端游标事务，保持 READ ONLY
        return hashes

    def column_names(self, schema: str, table: str) -> list:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
            (schema, table),
        )
        cols = [r[0] for r in cur.fetchall()]
        cur.close()
        return cols

    def multiset_hashes(self, schema: str, table: str, cols: list) -> dict:
        """全表逐行 md5 计数（多重集），服务端游标流扫；
        按传入列序显式 SELECT，与 sqlite 侧列序对齐，保证跨库 hash 可比。"""
        out = {}
        cur = self.conn.cursor(name=f"recon_ms_{schema}_{table}"[:60])
        cur.arraysize = PG_FETCH_SIZE
        try:
            sel = ", ".join(f'"{c}"' for c in cols)
            cur.execute(f'SELECT {sel} FROM "{schema}"."{table}"')
            for r in cur:
                hv = md5_of_row(r)
                out[hv] = out.get(hv, 0) + 1
        finally:
            cur.close()
        self.conn.rollback()
        return out

    def numeric_columns(self, schema: str, table: str) -> list:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name=%s AND data_type IN %s "
            "ORDER BY ordinal_position",
            (schema, table, PG_NUMERIC_TYPES),
        )
        cols = [r[0] for r in cur.fetchall()]
        cur.close()
        return cols

    def aggregates(self, schema: str, table: str, cols: list) -> dict:
        if not cols:
            return {}
        parts = ", ".join(
            f'SUM("{c}"), MIN("{c}"), MAX("{c}")' for c in cols
        )
        cur = self.conn.cursor()
        cur.execute(f'SELECT {parts} FROM "{schema}"."{table}"')
        row = cur.fetchone()
        cur.close()
        self.conn.rollback()
        out = {}
        for i, c in enumerate(cols):
            out[c] = {"sum": row[3 * i], "min": row[3 * i + 1], "max": row[3 * i + 2]}
        return out

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


# ---------------- 比对逻辑 ----------------
def _agg_match(a, b) -> bool:
    """数值聚合比较：同为 None 视为一致；否则相对误差 <1e-6 或绝对差 <1e-6。"""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)
    return abs(fa - fb) <= 1e-6 * max(1.0, abs(fa), abs(fb))


def compare_table(sq: SqliteSide, pg: PgSide, domain: str, table: str,
                  schema: str, pg_schema_empty: bool = False) -> dict:
    res = {
        "domain": domain, "table": table,
        "sqlite_exists": False, "pg_exists": False,
        "sqlite_rows": None, "pg_rows": None,
        "row_diff": None, "sample_size": SAMPLE_SIZE,
        "hash_only_sqlite": None, "hash_only_pg": None, "hash_common": None,
        "agg_checked": 0, "agg_mismatch": [],
        "truncated_columns": [],
        "diff_rate": None, "status": None, "note": "",
    }
    try:
        res["sqlite_exists"] = table in sq.tables()
        res["pg_exists"] = table in pg.tables(schema)
        if not res["sqlite_exists"] and not res["pg_exists"]:
            res["status"] = "NOT_READY"
            res["note"] = "两侧均无此表"
            return res
        if not res["sqlite_exists"]:
            res["status"] = "NOT_READY"
            res["note"] = "sqlite 源缺表（目标已有数据则需人工确认）"
            res["pg_rows"] = pg.rowcount(schema, table)
            return res
        if not res["pg_exists"]:
            res["sqlite_rows"] = sq.rowcount(table)
            if pg_schema_empty:
                res["status"] = "NOT_READY"
                res["note"] = "PG schema 为空（尚未搬运），0 行已迁"
            else:
                res["status"] = "FAIL" if res["sqlite_rows"] > 0 else "NOT_READY"
                res["note"] = "PG 缺表"
            return res

        s_cnt = sq.rowcount(table)
        p_cnt = pg.rowcount(schema, table)
        res["sqlite_rows"], res["pg_rows"] = s_cnt, p_cnt
        res["row_diff"] = abs(s_cnt - p_cnt)

        if s_cnt == 0 and p_cnt == 0:
            res["status"] = "NOT_READY"
            res["note"] = "两侧均为空表"
            return res

        # 全量多重集哈希对账（顺序无关：行序/rowid 空洞均不影响；
        # PG 侧按 sqlite 列序显式 SELECT，规避两库列序不一致导致的假差异）
        s_cols = [r[1] for r in sq.conn.execute(f'PRAGMA table_info("{table}")')]
        p_cols = pg.column_names(schema, table)
        p_cols_lc = {c.lower(): c for c in p_cols}
        # 先精确匹配；失败则按 PG 63 字节截断规则回退（超长 KPI 列名被 PG 截断）
        sel_cols, truncated = [], []
        for c in s_cols:
            m = p_cols_lc.get(c.lower())
            if m is None:
                m = p_cols_lc.get(c.encode("utf-8")[:PG_MAX_IDENT]
                                  .decode("utf-8", errors="ignore").lower())
                if m is not None:
                    truncated.append(c)
            sel_cols.append(m)
        res["truncated_columns"] = truncated
        if None in sel_cols:
            missing = [c for c, m in zip(s_cols, sel_cols) if m is None]
            res["status"] = "FAIL"
            res["note"] = f"PG 缺列: {missing}"
            return res
        s_hash = sq.multiset_hashes(table)
        p_hash = pg.multiset_hashes(schema, table, sel_cols)
        res["hash_only_sqlite"] = sum(
            max(0, c - p_hash.get(k, 0)) for k, c in s_hash.items())
        res["hash_only_pg"] = sum(
            max(0, c - s_hash.get(k, 0)) for k, c in p_hash.items())
        res["hash_common"] = sum(min(c, p_hash.get(k, 0)) for k, c in s_hash.items())

        # 数值列聚合抽查（两侧取交集；可空列全 NULL 自动跳过）
        s_num = set(sq.numeric_columns(table))
        p_num = set(pg.numeric_columns(schema, table))
        common_num = sorted(s_num & p_num)
        if common_num:
            s_agg = sq.aggregates(table, common_num)
            p_agg = pg.aggregates(schema, table, common_num)
            for c in common_num:
                res["agg_checked"] += 1
                for stat in ("sum", "min", "max"):
                    if not _agg_match(s_agg[c][stat], p_agg[c][stat]):
                        res["agg_mismatch"].append(
                            {"column": c, "stat": stat,
                             "sqlite": s_agg[c][stat], "pg": p_agg[c][stat]}
                        )

        # 差异率 = 差异行数 / 总行数（行数差 + 抽样 hash 不对称差）
        total = max(s_cnt, p_cnt, 1)
        hash_diff = res["hash_only_sqlite"] + res["hash_only_pg"]
        res["diff_rate"] = (res["row_diff"] + hash_diff) / total
        fail_reasons = []
        if res["row_diff"] > 0:
            fail_reasons.append(f"行数差 {res['row_diff']}")
        if hash_diff > 0:
            fail_reasons.append(f"全量行hash差异 {hash_diff}")
        if res["agg_mismatch"]:
            fail_reasons.append(f"聚合不一致 {len(res['agg_mismatch'])} 项")
        if fail_reasons and res["diff_rate"] >= DIFF_THRESHOLD:
            res["status"] = "FAIL"
            res["note"] = "; ".join(fail_reasons)
        elif fail_reasons:
            res["status"] = "PASS"
            res["note"] = "低差异(<0.1%): " + "; ".join(fail_reasons)
        else:
            res["status"] = "PASS"
            res["note"] = "完全一致"
        if truncated:
            res["note"] += f"（{len(truncated)} 列名超 63 字符被 PG 截断，已映射核对）"
        return res
    except Exception as e:  # noqa: BLE001
        res["status"] = "FAIL"
        res["note"] = f"比对异常: {type(e).__name__}: {e}"
        return res


def reconcile_domain(name: str, cfg: dict, pg: PgSide) -> dict:
    dom = {"domain": name, "sqlite": cfg["sqlite"], "pg_schema": cfg["pg_schema"],
           "status": None, "note": "", "tables": []}
    sq_path = resolve_path(cfg["sqlite"])
    sq = SqliteSide(sq_path)
    try:
        if not sq.exists:
            dom["status"] = "NOT_READY"
            dom["note"] = f"sqlite 源文件不存在或为空: {sq_path}"
            return dom
        if not pg.schema_exists(cfg["pg_schema"]):
            dom["status"] = "NOT_READY"
            dom["note"] = f"PG schema 不存在: {cfg['pg_schema']}"
            return dom

        want = [t for t in (cfg.get("tables") or sq.tables())
                if t not in EXCLUDE_TABLES]
        pg_tables = set(pg.tables(cfg["pg_schema"]))
        if not want:
            dom["status"] = "NOT_READY"
            dom["note"] = "sqlite 源库无任何表"
            return dom
        if not pg_tables:
            dom["status"] = "NOT_READY"
            dom["note"] = f"PG schema {cfg['pg_schema']} 为空（0 表），尚未搬运"
            # 仍逐表出 0 行差异明细，便于跟踪
        for t in want:
            dom["tables"].append(
                compare_table(sq, pg, name, t, cfg["pg_schema"],
                              pg_schema_empty=not pg_tables)
            )

        statuses = {t["status"] for t in dom["tables"]}
        if "FAIL" in statuses:
            dom["status"] = "FAIL"
        elif statuses == {"NOT_READY"}:
            dom["status"] = "NOT_READY"
        else:
            dom["status"] = "PASS"
        return dom
    finally:
        sq.close()


# ---------------- 输出 ----------------
def print_summary(report: dict):
    print("=" * 100)
    print(f"my_app 迁移 R5 一致性对账  结论: {report['overall']}   "
          f"(阈值 {DIFF_THRESHOLD:.1%}, 抽样种子 {RANDOM_SEED}, 每表<= {SAMPLE_SIZE} 行)")
    print(f"PG: {mask_url(report['pg_url'])}")
    print("=" * 100)
    hdr = f"{'域':<10}{'表':<32}{'sqlite行':>10}{'pg行':>10}{'行差':>8}{'hash差':>8}{'聚合异':>7}  {'结论':<10}"
    print(hdr)
    print("-" * 100)
    for dom in report["domains"]:
        if not dom["tables"]:
            print(f"{dom['domain']:<10}{'(无表) ':<32}{'-':>10}{'-':>10}{'-':>8}{'-':>8}{'-':>7}  {dom['status']:<10} {dom['note']}")
            continue
        for t in dom["tables"]:
            s = "-" if t["sqlite_rows"] is None else str(t["sqlite_rows"])
            p = "-" if t["pg_rows"] is None else str(t["pg_rows"])
            rd = "-" if t["row_diff"] is None else str(t["row_diff"])
            hd = "-" if t["hash_only_sqlite"] is None else str(t["hash_only_sqlite"] + t["hash_only_pg"])
            am = str(len(t["agg_mismatch"])) if t["agg_checked"] else "-"
            note = f" {t['note']}" if t["note"] else ""
            print(f"{dom['domain']:<10}{t['table'][:30]:<32}{s:>10}{p:>10}{rd:>8}{hd:>8}{am:>7}  {t['status']:<10}{note}")
    print("-" * 100)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    t0 = time.perf_counter()
    ap = argparse.ArgumentParser(description="my_app R5 一致性对账（只读）")
    ap.add_argument("--config", help="对账域 JSON 文件路径；缺省用内置域")
    ap.add_argument("--domain", action="append", help="只跑指定域，可重复；缺省全跑")
    ap.add_argument("--out", default=str(TMP_DIR), help="报告输出目录，默认 TMP/")
    args = ap.parse_args(argv)

    env = load_env_file(BACKEND_DIR / ".env")
    dsn = os.environ.get("DATABASE_URL") or env.get("DATABASE_URL", "")
    if not dsn:
        print("[NOT_READY] 未找到 DATABASE_URL（backend/.env 或环境变量），无法连接 PG。")
        return 0

    domains = DEFAULT_DOMAINS
    if args.config:
        domains = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if args.domain:
        domains = {k: v for k, v in domains.items() if k in set(args.domain)}
        if not domains:
            print(f"[错误] --domain 过滤后无对账域；可选: {list(DEFAULT_DOMAINS)}")
            return 2

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pg_url": mask_url(dsn),
        "threshold": DIFF_THRESHOLD,
        "sample_size": SAMPLE_SIZE,
        "seed": RANDOM_SEED,
        "domains": [], "overall": None, "elapsed_sec": None,
    }

    try:
        pg = PgSide(dsn)
    except Exception as e:  # noqa: BLE001
        report["overall"] = "NOT_READY"
        report["note"] = f"PG 连接失败: {type(e).__name__}: {e}"
        report["elapsed_sec"] = round(time.perf_counter() - t0, 2)
        print(f"[NOT_READY] {report['note']}")
        _write_report(report, args.out)
        return 0

    try:
        for name, cfg in domains.items():
            print(f"... 对账域 [{name}] {cfg['sqlite']} -> PG schema {cfg['pg_schema']}")
            report["domains"].append(reconcile_domain(name, cfg, pg))
    finally:
        pg.close()

    dom_status = {d["status"] for d in report["domains"]}
    if "FAIL" in dom_status:
        report["overall"] = "FAIL"
    elif dom_status == {"NOT_READY"}:
        report["overall"] = "NOT_READY"
    else:
        report["overall"] = "PASS"
    report["elapsed_sec"] = round(time.perf_counter() - t0, 2)

    print_summary(report)
    out_path = _write_report(report, args.out)
    print(f"JSON 差异报告: {out_path}")
    print(f"总耗时: {report['elapsed_sec']} 秒")
    return 0 if report["overall"] != "FAIL" else 1


def _write_report(report: dict, out_dir: str) -> Path:
    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = out_dir_p / f"reconcile_report_{ts}.json"
    path = pick_output_path(base)
    try:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
    except PermissionError:
        # 目标被占用：名字后加 "_" 和序号另存
        for i in range(1, 100):
            cand = out_dir_p / f"reconcile_report_{ts}_{i}.json"
            try:
                cand.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                                encoding="utf-8")
                return cand
            except PermissionError:
                continue
        raise
    return path


if __name__ == "__main__":
    sys.exit(main())

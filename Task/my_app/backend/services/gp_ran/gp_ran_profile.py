"""gp_ran 用户宽表：一个 IMSI 一行，把散在 80 列里的判据收敛成可直接筛选的画像。

为什么是这个形状
----------------
需求方要的是「该给谁开通什么」。已交付的两份扁平清单（VoLTE / N78）只能整包推送，
做不了交集判断；而开通决策要的是「终端支持 N78 × 但还没在用 5G × 近 7 天活跃」这类组合条件。

列的选择受一个硬约束：**全部要在一次 `GROUP BY d023` 里算出来**。
7 天窗口约 10 亿行明细，任何 `DISTINCT ON` + join（取"最后一次记录的各字段"）都要对
10 亿行排序 —— Greenplum 的 `runaway_cleaner` 内存熔断在本表上真实触发过一次
（80 路 UNION ALL 那次），所以不赌。由此产生三条取舍：

* 文本列（机型、频段串）用 `max()` 取「该用户任一非空申报值」，列名以 `_any` 结尾明示；
* **不放经纬度**。同一用户 `max(c070)` 与 `max(c071)` 很可能来自不同记录，
  拼出来是一个谁都没去过的坐标 —— 宁可不给，也不能给假的。这里只给 `geo_recs`
  （该用户有多少条记录带定位），要"最新位置"得另做一版并实测内存；
* 0/1 业务位用 `bool_or`：窗口内**出现过一次**即记 1（"用过"语义）。这与"当前是否开通"
  是两回事，ZTE 答复 Q2 之前不要当开通状态用。

口径提醒（详见 ZTE_FIELD_QUESTIONS.md 的 P0）：
`imsi` 是 IMSI 不是号码；`bands_any`(c043) 只写在约 11% 的记录上，
所以 `n78_in_bands=false` **不等于**"终端不支持 N78"，只代表"窗口内没采到"。

    python -m backend.services.gp_ran.gp_ran_profile --start 2026-10-12 --end 2026-10-19
    python -m backend.services.gp_ran.gp_ran_profile --start 2026-10-12 --end 2026-10-19 --show-sql
"""
from __future__ import annotations

import argparse
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
        GpRanClient, GpRanError, GpRanUnavailable, epoch_of)
    from backend.services.gp_ran.gp_ran_store import DATA_DIR
except ImportError:      # 直接在包目录里跑
    from gp_ran_client import (  # type: ignore
        GpRanClient, GpRanError, GpRanUnavailable, epoch_of)
    from gp_ran_store import DATA_DIR  # type: ignore

# c027~c040 里的 0/1 位（c031/c032/c033 单列在上面，含义待 ZTE 确认后一并解释）。
# 排除项：c028 恒为 0；c036/c037 是文本频段串，不是位。
BOOL_FLAGS = ["c027", "c029", "c030", "c034", "c035",
              "c038", "c039", "c040", "issupportedtm8tdd"]

# 首行样例里要掩码的列下标：imsi / imeisv_any / tac
_MASK_COLS = (0, 4, 5)


def sql_user_profile(start: str, end: str) -> str:
    """一个 IMSI 一行的宽表 SELECT。start 含、end 不含（UTC 自然日）。"""
    cols = [
        "A.D023 AS imsi",
        "to_char(to_timestamp(min(A.D027) + 946684800),"
        "'YYYY-MM-DD HH24:MI:SS') AS first_seen_utc",
        "to_char(to_timestamp(max(A.D027) + 946684800),"
        "'YYYY-MM-DD HH24:MI:SS') AS last_seen_utc",
        "count(*) AS records",
        "max(A.imeisv) AS imeisv_any",
        "left(max(A.imeisv),8) AS tac",
        "max(A.c043) AS bands_any",
        "max(A.c075) AS band_combo_any",
        # c036/c037 曾经带出过（各 44.6% 覆盖），实测其取值只含 LTE 频段
        # （1A$3A$7A$8A$20A$28A$38A$40A$41A…，**没有 78**），对 NR/N78 判据无用，
        # 却占了单日文件 314MB 里的 139MB（44%）→ 裁掉。要查 LTE 能力再单独取。
        "bool_or(position('$78$' in '$'||A.c043||'$') > 0) AS n78_in_bands",
        "bool_or(A.c075 LIKE '%n78%') AS n78_in_combo",
        "bool_or(A.c031 = 1 OR A.c032 = 1 OR A.c033 = 1) AS volte_any",
        "bool_or(A.c031 = 1) AS c031_any",
        "bool_or(A.c032 = 1) AS c032_any",
        "bool_or(A.c033 = 1) AS c033_any",
        "count(DISTINCT A.c001) AS cell_cnt",
        "count(A.c070) AS geo_recs",
        "count(NULLIF(A.c004,'')) AS ip_recs",
    ]
    cols += [f"bool_or(A.{col} = 1) AS {col}_any" for col in BOOL_FLAGS]
    return ("SELECT\n  " + ",\n  ".join(cols) +
            "\nFROM L_T216 A\n"
            f"WHERE A.D027 >= {epoch_of(start)} AND A.D027 < {epoch_of(end)}\n"
            "  AND A.D023 IS NOT NULL AND A.D023 <> ''\n"
            "GROUP BY A.D023")


def run_profile(start: str, end: str, out_dir: Path, timeout: int = 3600) -> Path:
    """取宽表并落成 CSV。返回文件路径。"""
    client = GpRanClient()
    client.ep["query_timeout"] = timeout
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"user_profile_{start}_{end}.csv"
    tmp = out_dir / f".{dest.name}.part"
    print(f"[{time.strftime('%H:%M:%S')}] 生成宽表 {start} ~ {end}"
          "（GROUP BY IMSI，10 亿行级扫描，可能要几分钟）…")
    t0 = time.time()
    with client:
        text = client.query_csv(sql_user_profile(start, end), timeout=timeout)
    rows = max(text.count("\n") - 1, 0)
    head = text.split("\n", 2)[:2]
    tmp.write_text(text, encoding="utf-8-sig", newline="")
    tmp.replace(dest)
    print(f"  -> {dest}")
    print(f"  {rows:,} 行 / {dest.stat().st_size / 1048576:.1f} MB / "
          f"用时 {time.time() - t0:.1f}s")
    if head:
        print(f"  列（{len(head[0].split(','))} 个）：{head[0]}")
    if len(head) > 1:
        cells = head[1].split(",")
        masked = [(c[:4] + "***") if i in _MASK_COLS else c
                  for i, c in enumerate(cells)]
        print(f"  首行样例（IMSI/IMEISV/TAC 已掩码）：{','.join(masked)}")
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RAN Greenplum 用户宽表（IMSI 粒度，只读）")
    ap.add_argument("--start", required=True, help="起始日 YYYY-MM-DD（含）")
    ap.add_argument("--end", required=True, help="截止日 YYYY-MM-DD（不含）")
    ap.add_argument("--out", default=str(DATA_DIR), help="输出目录（默认 backend/data/gp_ran）")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--show-sql", action="store_true", help="只打印 SQL 不执行")
    args = ap.parse_args(argv)
    if args.show_sql:
        print(sql_user_profile(args.start, args.end))
        return 0
    try:
        run_profile(args.start, args.end, Path(args.out), args.timeout)
    except (GpRanUnavailable, GpRanError) as exc:
        print(f"[失败] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

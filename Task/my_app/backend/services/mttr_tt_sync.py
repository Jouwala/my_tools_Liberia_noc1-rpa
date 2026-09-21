# -*- coding: utf-8 -*-
"""mttr_tt 宽表重建（看板 `mttr` = MTTR Bashboard Monthly&Weekly 的数据源）。

=========================== 这张表是什么 ===========================

`mttr_tt.sqlite3.tt_full` 是 `Eflow_TT_FB` 的**宽表**：在 TT 原始字段之外补上
FineBI 计算列（Vender / MTTR1 / MTTR2 / MTTR_RANG_2H / Month / WK /
Outage_Mins / Site Category / 2G-3G-FDD-TDD Cell Count），
口径解析自 FineDB 数据集 `4bc5a679` 的 operatorBeans：

    Vender       = IF(WO No. 非空且 != 'nan', 'ZTE', '3rd')
    MTTR1(h)     = (Alarm Clear Time - Alarm Occur Time) 小时
    MTTR2        = IF(0 < MTTR1 < 48, MTTR1, NULL)
    MTTR_RANG_2H = CEILING(MTTR2/2)*2
    Month        = substr(Alarm Occur Time,1,7)
    WK           = year||'-W'||week(周一起)        （FineBI WEEK(t,"F1") 的近似）
    Outage_Mins  = 分钟差 × (2G+3G+FDD+TDD Cell Count)
    Site Category= Site_Maintainer_Category[Site ID]
    Cell Counts  = OLR_CELLS[Site Name]

=========================== 为什么收进 my_app ===========================

原实现是 my-finebi 项目的一次性脚本 `TMP/etl_mttr_tt.py`，与
`etl_avail_recon.py` / `etl_progress.py` 一样属于**手工「ETL 快照刷新」**
（其 PROJECT_DOCS 原话：FineBI 自助数据集变更后**重跑**）。my-finebi 门户退役后
没有任何调度再跑它 —— 表冻结在 2026-08-31，`?page=finebi_mttr` 静默停更
（2026-09-21 与 avail_recon 一并发现）。

现在由定时任务 `mttr_tt_sync` 每日重建到本机 `data/mttr_tt.sqlite3`。

=========================== 数据来源 ===========================

- **TT 明细**：远端 `db.sqlite3`.`Eflow_TT_FB`（经只读 API，35k 行 < 上限 5 万）
- **站点主数据/小区数**：本机 `data/excel_ds.sqlite3`，是 my-finebi 时代从
  FineBI **Excel 服务器数据集**镜像出来的小参考库（114KB，3 张表：
  `OLR_CELLS` 789 / `Site_Maintainer_Category` 805 / `tt_exclude` 46），
  2026-08-31 后未再变化，故随代码一起固化到 my_app。
  ⚠ 若 FineBI 侧那两个 Excel 数据集将来有更新，需重新导出覆盖本文件
  （源文件：`D:\\01_RPA\\Task\\my-finebi\\data\\excel_ds.sqlite3`）。
"""
from __future__ import annotations

import logging
import math
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.services.remote_readonly import query_dicts

logger = logging.getLogger("mttr_tt_sync")

SERVICE_DIR = Path(__file__).resolve().parent
DATA_DIR = SERVICE_DIR.parent.parent / "data"
OUT_DB = DATA_DIR / "mttr_tt.sqlite3"
REF_DB = DATA_DIR / "excel_ds.sqlite3"   # OLR_CELLS / Site_Maintainer_Category

SRC_DB = "db.sqlite3"
TT_TABLE = "Eflow_TT_FB"

# 与 my-finebi 原脚本逐字一致（顺序即写入顺序）
TT_COLS = ("Ticket No.", "WO No.", "Site Name", "Site ID", "Ticket Severity", "Status",
           "Current Handler", "Region ID", "Created Time", "Alarm Occur Time",
           "Alarm Clear Time")

DDL = """CREATE TABLE tt_full (
  "Ticket No." TEXT, "WO No." TEXT, "Site Name" TEXT, "Site ID" TEXT,
  "Ticket Severity" TEXT, "Status" TEXT, "Current Handler" TEXT, "Region ID" TEXT,
  "Created Time" TEXT, "Alarm Occur Time" TEXT, "Alarm Clear Time" TEXT,
  "Vender" TEXT, "Site Category" TEXT,
  "2G Cell Count" REAL, "3G Cell Count" REAL, "FDD Cell Count" REAL, "TDD Cell Count" REAL,
  "MTTR1" REAL, "MTTR2" REAL, "MTTR_RANG_2H" REAL,
  "Month" TEXT, "WK" TEXT, "Outage_Mins" REAL)"""

NULLISH = ("", "nan", "NaT", "None")


class MttrTtError(Exception):
    """重建失败（远端不可达 / 参考库缺失等）。"""


# ----------------------------------------------------------------------
# 口径辅助（逐字移植自 TMP/etl_mttr_tt.py，勿随意"优化"）
# ----------------------------------------------------------------------
def parse_ts(s: Any) -> Optional[datetime]:
    """FineBI 的日期解析：'nan'/'NaT'/'' 一律当空。"""
    if s is None:
        return None
    s = str(s).strip()
    if s in NULLISH:
        return None
    for fmt, cut in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16),
                     ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:cut], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def week_f1(dt: datetime) -> str:
    """周一起始年周（FineBI WEEK(t,"F1") 的近似，与原脚本一致用 %W）。"""
    return dt.strftime("%Y") + "-W" + dt.strftime("%W")


def _num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _load_ref(path: Path) -> Tuple[Dict[str, str], Dict[str, Tuple[float, ...]]]:
    """读 excel_ds 参考库：Site ID → Site Category、Site Name → 四制式小区数。"""
    if not path.is_file():
        raise MttrTtError(f"参考库不存在: {path}（需从 my-finebi data/ 同步过来）")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    try:
        smc = {r[0]: r[1] for r in con.execute(
            'SELECT "Site ID", "Site Category" FROM "Site_Maintainer_Category"')}
        olr = {r[0]: (_num(r[1]), _num(r[2]), _num(r[3]), _num(r[4]))
               for r in con.execute(
                   'SELECT "Site Name", "2G Cell Count", "3G Cell Count", '
                   '"FDD Cell Count", "TDD Cell Count" FROM "OLR_CELLS"')}
    finally:
        con.close()
    return smc, olr


# ----------------------------------------------------------------------
# 重建
# ----------------------------------------------------------------------
def build(target: Path = OUT_DB, progress=None) -> Dict[str, Any]:
    """全量重建 tt_full 到 target（原子替换）。"""
    t0 = time.time()
    say = progress or (lambda m: logger.info("%s", m))

    say(f"[1/4] 读取参考库 {REF_DB.name} ...")
    smc, olr = _load_ref(REF_DB)
    say(f"      Site_Maintainer_Category={len(smc)}  OLR_CELLS={len(olr)}")

    say(f"[2/4] 读取远端 {SRC_DB}.{TT_TABLE} ...")
    rows = query_dicts(
        SRC_DB,
        "SELECT " + ",".join(f'"{c}"' for c in TT_COLS) + f' FROM "{TT_TABLE}"')
    if not rows:
        raise MttrTtError("TT 明细为空，拒绝重建（否则会把看板写成空）")
    say(f"      {len(rows)} 行")

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    out = sqlite3.connect(str(tmp), timeout=60)
    try:
        out.execute(DDL)
        batch: List[Tuple[Any, ...]] = []
        n_smc = n_olr = 0
        for d in rows:
            wo = (d.get("WO No.") or "").strip()
            vender = "ZTE" if (wo and wo != "nan") else "3rd"

            sid = (d.get("Site ID") or "").strip()
            # SMC 的 Site ID 可能为 '3043' / '3043.0'
            cat = smc.get(sid) or smc.get(sid.replace(".0", "")) or smc.get(sid + ".0")
            if cat:
                n_smc += 1

            sname = (d.get("Site Name") or "").strip()
            cells = olr.get(sname)
            if cells:
                n_olr += 1
            else:
                cells = (0.0, 0.0, 0.0, 0.0)

            o = parse_ts(d.get("Alarm Occur Time"))
            c = parse_ts(d.get("Alarm Clear Time"))
            mttr1 = mttr2 = rang = None
            if o and c:
                mttr1 = (c - o).total_seconds() / 3600.0
                if 0 < mttr1 < 48:
                    mttr2 = mttr1
                    rang = math.ceil(mttr2 / 2) * 2
            # 注意：Month 取的是**原始字符串**前 7 位（脏值 'NaT' 会原样进来），
            # 与原脚本一致；源库脏行由 Eflow 同步侧负责清理。
            raw_occur = d.get("Alarm Occur Time")
            month = raw_occur[:7] if raw_occur else None
            wk = week_f1(o) if o else None
            outage = None
            if o and c:
                outage = (c - o).total_seconds() / 60.0 * sum(cells)

            batch.append((
                d.get("Ticket No."), d.get("WO No."), d.get("Site Name"),
                d.get("Site ID"), d.get("Ticket Severity"), d.get("Status"),
                d.get("Current Handler"), d.get("Region ID"), d.get("Created Time"),
                d.get("Alarm Occur Time"), d.get("Alarm Clear Time"),
                vender, cat, cells[0], cells[1], cells[2], cells[3],
                mttr1, mttr2, rang, month, wk, outage))

        out.executemany(
            "INSERT INTO tt_full VALUES (" + ",".join("?" * 23) + ")", batch)
        out.execute('CREATE INDEX idx_tt_month ON tt_full("Month")')
        out.execute('CREATE INDEX idx_tt_wk ON tt_full("WK")')
        out.commit()
        stat = out.execute('SELECT MIN("Alarm Occur Time"), MAX("Alarm Occur Time"), '
                           'COUNT(*) FROM tt_full WHERE "Alarm Occur Time" LIKE \'2%\''
                           ).fetchone()
    finally:
        out.close()

    os.replace(tmp, target)
    elapsed = round(time.time() - t0, 2)
    say(f"[3/4] 写入 {len(batch)} 行（SMC 命中 {n_smc} / OLR 命中 {n_olr}）")
    say(f"[4/4] 完成：真实日期范围 {stat[0]} ~ {stat[1]}，耗时 {elapsed}s -> {target}")
    return {
        "success": True,
        "rows": len(batch),
        "smc_matched": n_smc,
        "olr_matched": n_olr,
        "min_occur": stat[0],
        "max_occur": stat[1],
        "path": str(target),
        "elapsed_seconds": elapsed,
    }


def run_mttr_tt_sync(target: Path = OUT_DB) -> Dict[str, Any]:
    """task_registry 入口：重建本机 mttr_tt.sqlite3。"""
    started = datetime.now().isoformat(timespec="seconds")
    logger.info("[mttr_tt] 开始重建，目标 %s", target)
    try:
        res = build(target)
    except Exception as e:  # noqa: BLE001 — 任务层要把失败回报给调度器
        logger.error("[mttr_tt] 重建失败: %s", e, exc_info=True)
        return {"success": False, "started": started, "errors": [str(e)]}
    res["started"] = started
    res["finished"] = datetime.now().isoformat(timespec="seconds")
    logger.info("[mttr_tt] 重建成功: %s", res)
    return res


if __name__ == "__main__":
    import json
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    r = run_mttr_tt_sync(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DB)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("success") else 1)

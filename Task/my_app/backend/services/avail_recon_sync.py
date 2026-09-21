# -*- coding: utf-8 -*-
"""avail_recon 重建服务（可用率核对宽表）。

=========================== 为什么需要这张表 ===========================

看板 `daily_availability`(id=9) 与 `availability_tt`(id=11) 共 15 个组件读
`avail_recon.sqlite3.availability_daily`。**它不是任何业务系统的原生表**：

FineBI 原版 1neE / 435X 看板的可用率依赖 FineBI **自助数据集**
（`FME_Availability` → `Availability`），基表在 FineDB 内部、不在已注册的
SQLite 源里；且区域维度需要跨库 JOIN `Master_Site_Database`，而远端只读
API 一次只能查一个库。经用户确认后采用**近似口径**重建。

=========================== 口径（v2，勿回退） ===========================

    2G/3G/4G_Main_Kpi_Site_Daily 按站点名匹配 Master_Site_Database_.Region，
    按 (Begin_Time, Tech, FME_Region, Cell_Group) 聚合：

        Cell_Availability = AVG(rate)                       站点可用率算术平均
        Denominator       = COUNT(rate 非空)
        Numerator         = ROUND(AVG(rate) * Denominator)  保留整数字段以便加权

    ⚠ v1 曾把 Cell_Availability 算成**达成率**
      （`Numerator=COUNT(rate>=0.985)`、`Denominator=COUNT(rate 非空)`），
      值域 40%~100%，与 FineBI 原版的 95%~100% 不符。
      「达标站点占比」是 `Site Availability Achievment` 口径（AIfA 看板用），
      不是「可用率」。详见 my-finebi 的 `.workbuddy-ai/memory/2026-09-15.md`。

    跨库 join 的绕法：站点名单很小（每 Region 一两百个），把名单内联进
    `WHERE "SITE Name" IN (...)`，聚合就在**远端**完成，只回传每 Region
    ~259×3 行，不必拉 57 万行原始明细。

=========================== 为什么收进 my_app ===========================

原实现是 my-finebi 项目里的**一次性脚本** `TMP/etl_avail_recon_v2.py`，
my-finebi 的 PROJECT_DOCS 把它归类为「ETL 快照刷新 …… 变更后**重跑**」——
即**手工执行、无调度**。my-finebi 门户退役后无人再跑，表就冻结在
2026-09-13，`?page=finebi_daily_availability` 静默停更（2026-09-21 发现）。

本模块把该 ETL 收进 my_app：读远端只读 API，重建到**本机**
`data/avail_recon.sqlite3`，由定时任务 `avail_recon_sync` 每日刷新。
看板侧同步改为读本机库（`dashboard_service.LOCAL_SQLITE_FILES`），
从而彻底切断对已退役 my-finebi 目录的运行时依赖。

=========================== 部署方式 ===========================

原子替换：先写 `avail_recon.sqlite3.tmp` 再 `os.replace`。
后端对本地库是**每请求只读打开**（`file:...?mode=ro`），替换无需停服。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.config.remote_host import get_api_base_url

logger = logging.getLogger("avail_recon_sync")

# 远端只读 SQL API（内网地址绝不能被 HTTP_PROXY 劫持）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 输出库：my_app 自持，看板经 LOCAL_SQLITE_FILES 读它
SERVICE_DIR = Path(__file__).resolve().parent
OUT_DB = SERVICE_DIR.parent.parent / "data" / "avail_recon.sqlite3"

# 源库（远端逻辑库名，见 db_writer_api 的 GET /api/dbs）
SRC_DB = "db.sqlite3"
MASTER_DB = "olbr_ms_master_database.sqlite3"
MASTER_TABLE = "Master_Site_Database_"

# (Tech 标签, 源表, 可用率列, 站点名列)
TECHS: List[Tuple[str, str, str, str]] = [
    ("2G", "2G_Main_Kpi_Site_Daily", "306004:TCH in service rate(%)", "SITE Name"),
    ("3G", "3G_Main_Kpi_Site_Daily", "300857:Cell Validity Rate(%)", "NodeB Name"),
    ("4G", "4G_Main_Kpi_Site_Daily",
     "1638004469345:[FDD]Cell Availability[SDR_ITBBU]", "eNodeB Name"),
]

QUERY_TIMEOUT = 600

DDL = """CREATE TABLE availability_daily(
      Begin_Time TEXT, End_Time TEXT, Tech TEXT, FME_Region TEXT, Cell_Group TEXT,
      Numerator INTEGER, Denominator INTEGER, Cell_Availability REAL, WK TEXT, Month TEXT)"""


class AvailReconError(Exception):
    """重建失败（远端不可达 / 源表缺失等）。"""


# ----------------------------------------------------------------------
# 远端只读查询
# ----------------------------------------------------------------------
def _q(db: str, sql: str, limit: int = 200000,
       timeout: int = QUERY_TIMEOUT) -> List[List[Any]]:
    """远端只读查询（实现收敛在 remote_readonly，避免每个 ETL 各写一份）。"""
    from backend.services.remote_readonly import MAX_LIMIT, query_rows
    return query_rows(db, sql, limit=min(limit, MAX_LIMIT), timeout=timeout)


def _sql_str(s: Any) -> str:
    return "'" + str(s or "").replace("'", "''") + "'"


def site_type(grp: Any) -> str:
    """调度规则 Group -> 站点类型标签（与 FineBI 计算列 `Regular` 的 SWITCH 同构）。"""
    if not grp:
        return "Other"
    if "_Regular_Normal" in grp:
        return "Regular"
    if "_ERA_ERA" in grp or "_RRA_ERA" in grp:
        return "ERA"
    if "_Regular_COOLI" in grp:
        return "Cooli"
    # LTE_NERA 等未映射值：去掉技术前缀后原样保留（FineBI 的 SWITCH 也是回落原值）
    for p in ("LTE_", "UMTS_", "GSM_"):
        if grp.startswith(p):
            return grp[len(p):]
    return grp


# ----------------------------------------------------------------------
# 重建
# ----------------------------------------------------------------------
def build(target: Path = OUT_DB, progress=None) -> Dict[str, Any]:
    """全量重建 availability_daily 到 target（原子替换）。

    全量而非增量：源库是 upsert 保留全历史的，站点主数据也可能变；
    整表只有 ~8k 行、十余条远端聚合查询，全量重建最省心也最自愈。
    """
    t0 = time.time()
    say = progress or (lambda m: logger.info("%s", m))

    # 1) 站点 -> Region（主数据）
    say(f"[1/4] 读取站点主数据 {MASTER_DB}.{MASTER_TABLE} ...")
    ms = _q(MASTER_DB, f'SELECT "Site_Name","Region" FROM "{MASTER_TABLE}"',
            limit=50000)
    reg_sites: Dict[str, List[str]] = {}
    for name, region in ms:
        key = (region or "").strip()
        if not key:
            continue
        reg_sites.setdefault(key, []).append((name or "").strip())
    if not reg_sites:
        raise AvailReconError("站点主数据为空，拒绝重建（否则会把整表写成空）")
    say(f"      主数据 {len(ms)} 行 -> {len(reg_sites)} 个 Region："
        + ", ".join(f"{k}={len(v)}" for k, v in sorted(reg_sites.items())))

    known_up = {(s or "").strip().upper() for v in reg_sites.values() for s in v}

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()

    out = sqlite3.connect(str(tmp), timeout=60)
    try:
        out.execute(DDL)
        total = 0

        for tech, tbl, rate_col, name_col in TECHS:
            say(f"[2/4] {tech} 聚合 {tbl} ...")
            allsites = [r[0] for r in _q(
                SRC_DB,
                f'SELECT DISTINCT "{name_col}" FROM "{tbl}"',
                limit=50000)]
            unmatched = [s for s in allsites
                         if (s or "").strip().upper() not in known_up]
            groups = list(reg_sites.items()) + [(None, unmatched)]
            say(f"      {tech} 站点 {len(allsites)}，未匹配主数据 {len(unmatched)}")

            rows: List[Tuple[Any, ...]] = []
            cg_suffix = " FDD" if tech == "4G" else ""
            for region, sites in groups:
                sites = [s for s in sites if s]
                if not sites:
                    continue
                # 站点名单可能上千，SQL 很长；按 800 个一批切分再合并，
                # 避免个别环境对 SQL 长度有限制。
                for chunk in _chunks(sites, 800):
                    inlist = ",".join(_sql_str(s) for s in chunk)
                    sql = (
                        'SELECT substr("Begin Time",1,10), substr("End Time",1,10), '
                        '"Group", COUNT("%s"), ROUND(AVG("%s")*100, 4) '
                        'FROM "%s" WHERE "%s" IN (%s) GROUP BY 1,2,3'
                    ) % (rate_col, rate_col, tbl, name_col, inlist)
                    for bt, et, grp, den, avail in _q(SRC_DB, sql):
                        if not den:
                            continue
                        cg = f"{tech}{cg_suffix} {site_type(grp)}"
                        num = int(round((avail or 0) / 100.0 * den))
                        rows.append((bt, et, tech, region, cg, num, den,
                                     (avail or 0) / 100.0, None, (bt or "")[:7]))

            out.executemany(
                "INSERT INTO availability_daily VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
            total += len(rows)
            say(f"      {tech} 写入 {len(rows)} 行")

        say("[3/4] 计算 WK 周标签 + 建索引 ...")
        # 周一起算的 ISO 周（与 FineBI/原脚本口径一致）
        out.execute("""
        UPDATE availability_daily SET WK =
          strftime('%Y', Begin_Time) || '-W' ||
          printf('%02d', ((CAST(strftime('%j', Begin_Time) AS INTEGER) + 6
                           - CAST(strftime('%w', Begin_Time) AS INTEGER)) / 7))
        """)
        # 看板主查询按 Begin_Time 取 MAX / 最新日，加索引让本机查询是毫秒级
        out.execute("CREATE INDEX IF NOT EXISTS idx_avail_begin "
                    "ON availability_daily(Begin_Time)")
        out.commit()

        stat = out.execute(
            "SELECT MIN(Begin_Time), MAX(Begin_Time), COUNT(*), "
            "COUNT(DISTINCT Begin_Time) FROM availability_daily").fetchone()
    finally:
        out.close()

    if not total:
        tmp.unlink(missing_ok=True)
        raise AvailReconError("重建结果 0 行，拒绝覆盖现有库")

    os.replace(tmp, target)  # 原子替换，读方无需停服

    min_d, max_d, n, days = stat
    elapsed = round(time.time() - t0, 2)
    say(f"[4/4] 完成：{n} 行 / {days} 天（{min_d} ~ {max_d}），"
        f"耗时 {elapsed}s -> {target}")
    return {
        "success": True,
        "rows": n,
        "days": days,
        "min_date": min_d,
        "max_date": max_d,
        "path": str(target),
        "elapsed_seconds": elapsed,
    }


def _chunks(seq: List[Any], size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


# ----------------------------------------------------------------------
# 定时任务入口
# ----------------------------------------------------------------------
def run_avail_recon_sync(target: Path = OUT_DB) -> Dict[str, Any]:
    """task_registry 入口：重建本机 avail_recon.sqlite3。

    排在 main_kpi_sync(04:00) / network_kpi_sync(05:00) 之后，
    保证当日 Site_Daily 已入库再聚合。
    """
    started = datetime.now().isoformat(timespec="seconds")
    logger.info("[avail_recon] 开始重建，目标 %s", target)
    try:
        res = build(target)
    except Exception as e:  # noqa: BLE001 — 任务层要把失败回报给调度器
        logger.error("[avail_recon] 重建失败: %s", e, exc_info=True)
        return {"success": False, "started": started, "errors": [str(e)]}
    res["started"] = started
    res["finished"] = datetime.now().isoformat(timespec="seconds")
    logger.info("[avail_recon] 重建成功: %s", res)
    return res


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    tgt = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DB
    r = run_avail_recon_sync(tgt)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("success") else 1)

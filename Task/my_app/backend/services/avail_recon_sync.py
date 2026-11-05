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

# 站点主数据来源：local = 本机 master_site_db（my_app 真源，导入器负责列名映射）
#                 remote = 远端 olbr_ms_master_database.Master_Site_Database_（历史口径）
#                 auto  = 先本机，本机读不到再回落远端
# 默认 local：区域维度必须与本机主数据同源，否则「矩阵按老区、TT 按新区」会再次分叉。
REGION_SOURCE = "local"

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

# ============================================================
# 外部化配置（Settings →「任务配置」维护的 avail_recon_config.json）
#   优先级：环境变量 > 配置文件 > 内置默认。这里配的是「远端库逻辑名/表名」，不是本地路径。
# ============================================================
try:
    from backend.services.task_config_files import apply_config_overrides
except ImportError:
    from task_config_files import apply_config_overrides  # type: ignore

apply_config_overrides(
    globals(),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "avail_recon_config.json"),
    {
        "src_db": ("SRC_DB", str, "AVAIL_RECON_SRC_DB"),
        "master_db": ("MASTER_DB", str, None),
        "master_table": ("MASTER_TABLE", str, None),
        "region_source": ("REGION_SOURCE",
                          lambda v: str(v or "local").strip().lower(),
                          "AVAIL_RECON_REGION_SOURCE"),
        "query_timeout": ("QUERY_TIMEOUT", lambda v: max(30, int(v)), None),
    },
    log_name="avail_recon",
)


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


# 站点主数据的列名在不同来源里大小写/命名不一：本机 PG 是 region/site_name，
# 远端 SQLite 是 Region/Site_Name，历史 Excel 换过列位也换过列名。
# 按候选名做**大小写不敏感**匹配；匹配不到就报错并列出真实列名，绝不静默用错列。
_REGION_COLS = ("region", "fme_region", "region_name", "area", "zone", "cluster")
_SITE_NAME_COLS = ("site_name", "sitename", "site name", "site", "name", "site_id")


def _pick_col(cols: List[str], candidates: Tuple[str, ...], what: str,
              table: str) -> str:
    """按候选名挑列（大小写不敏感），挑不到就带着真实列名抛错。"""
    lower = {str(c).strip().lower(): c for c in cols}
    for cand in candidates:
        if cand in lower:
            return lower[cand]
    raise AvailReconError(
        f"{table} 找不到{what}列：候选={list(candidates)} 实际列={list(cols)}")


def _group_by_region(rows) -> Dict[str, List[str]]:
    """[(站点名, Region), ...] -> {Region: [站点名, ...]}，空 Region 丢弃。"""
    out: Dict[str, List[str]] = {}
    for r in rows:
        if len(r) < 2:
            continue
        name, region = r[0], r[1]
        key = str(region or "").strip()
        if not key:
            continue
        out.setdefault(key, []).append(str(name or "").strip())
    return out


def _regions_from_local() -> Dict[str, List[str]]:
    """本机 master_site_db（my_app 真源；PG / SQLite 双模都能走）。"""
    from backend.database import get_raw_connection

    table = "master_site_db"
    with get_raw_connection(timeout=60) as conn:
        # 先探列名（WHERE 1=0 两种方言都成立），再按真实列名取数
        probe = conn.execute(f"SELECT * FROM {table} WHERE 1=0")
        cols = [d[0] for d in (probe.description or [])]
        if not cols:
            raise AvailReconError(f"{table} 不存在或为空")
        rcol = _pick_col(cols, _REGION_COLS, "Region", table)
        ncol = _pick_col(cols, _SITE_NAME_COLS, "站点名", table)
        rows = conn.execute(f'SELECT "{ncol}", "{rcol}" FROM {table}').fetchall()
    return _group_by_region(rows)


def _regions_from_remote() -> Dict[str, List[str]]:
    """远端 olbr_ms_master_database.Master_Site_Database_（历史口径，仅作兜底）。"""
    rows = _q(MASTER_DB, f'SELECT "Site_Name","Region" FROM "{MASTER_TABLE}"',
              limit=50000)
    return _group_by_region(rows)


def _load_site_regions() -> Tuple[Dict[str, List[str]], str]:
    """站点 -> Region 映射，返回 (映射, 实际来源)。

    为什么不再固定读远端主库：本机 `master_site_db` 由导入器按**列名**写入 Excel
    当前列，是页面其它维度（TT 列表、站点类型）已经在用的真源；而远端
    `olbr_ms_master_database` 是另一条人工维护的链路。两边一旦异步，就会出现
    「矩阵按老区、TT 按新区」的分叉（2026-11-04 实测：矩阵仍 Montserrado/North East/
    South West，TT 已是 North/South，下钻恒空）。区域维度只能有一个真源。

    `REGION_SOURCE` = local(默认) / remote / auto。local 失败时按 auto 语义回落远端，
    但**来源会写进返回结果**，让日志和任务结果能看出本次用的是哪一份。
    """
    src = (REGION_SOURCE or "local").strip().lower()
    order: List[str] = []
    if src != "remote":
        order.append("local")
    if src != "local":
        order.append("remote")
    if not order:                      # 配了非法值：按 local 优先 + 远端兜底处理
        order = ["local", "remote"]

    errors: List[str] = []
    for name in order:
        try:
            rs = _regions_from_local() if name == "local" else _regions_from_remote()
            if rs:
                if name == "remote" and "local" in order:
                    logger.warning("[avail_recon] 本机主数据不可用，回落到远端主库")
                return rs, name
            errors.append(f"{name}=空")
        except Exception as e:  # noqa: BLE001 — 逐个来源试，最后统一报错
            errors.append(f"{name}={e}")
    raise AvailReconError("站点主数据读取失败（" + "; ".join(errors) + "）")


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
    say(f"[1/4] 读取站点主数据（region_source={REGION_SOURCE}）...")
    reg_sites, region_source_used = _load_site_regions()
    if not reg_sites:
        raise AvailReconError("站点主数据为空，拒绝重建（否则会把整表写成空）")
    total_sites = sum(len(v) for v in reg_sites.values())
    say(f"      来源={region_source_used}，{total_sites} 个站点 -> "
        f"{len(reg_sites)} 个 Region："
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
        "region_source": region_source_used,
        "regions": sorted(reg_sites),
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

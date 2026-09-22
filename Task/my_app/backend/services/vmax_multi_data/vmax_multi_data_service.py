#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vmax_multi_data_service.py —— 按 url.txt 里的 vReport 报表从 VMAX 采集指标
==========================================================================

做的事情（对齐 RAN_UME 的方法：配置化取数 → 解析 → 落盘/落库 → 定时任务）：

    1. 读 vmax_multi_data_config.json（可由「设置 → 任务配置」维护），
       逐个报表：报告名 report_part（URL 里的 rpt_home/<report_part>）在 url.txt 中给出，
       即 sys_5gsa_traffic_ciservice 与 sys_5gsa_video_ciservice。
    2. 经 vmax_report_client 拉设计/初值（design.json / init_data.json / metadata），
       按默认选中维度+指标（或配置里的 dims/kpis）组 `show`，
       用 build_report_condition 组时间窗条件，POST server/report_query。
    3. 解析 `field/header/data`，落盘：
         data/vmax_multi_data/<key>_latest.json     全量快照（含 field/header/records）
         data/vmax_multi_data/vmax_multi_data.sqlite3  明细行（kpi_rows）+ 运行记录（sync_runs）
       可选：db_writer_client 写远程 DB Orange（默认关闭，配置 persist.write_remote_db）。
    4. 返回统计摘要（任务队列里能看到 rows/errors/elapsed）。

命令行（不依赖 FastAPI / 任务队列，排障用）：

    # 健康检查：8790 代理/直连是否可用、能不能取到会话
    python -m backend.services.vmax_multi_data.vmax_multi_data_service --check

    # 列出配置里的报表
    python -m backend.services.vmax_multi_data.vmax_multi_data_service --list

    # 取最近 24 小时（小时粒度），只打印到 stdout
    python -m backend.services.vmax_multi_data.vmax_multi_data_service --report traffic --days 1

    # 指定窗口 + 落盘
    python -m backend.services.vmax_multi_data.vmax_multi_data_service --report all \
        --start "2026-09-16 00:00" --end "2026-09-16 23:00" --granularity hour

    # 90 天全量（date 粒度；上游滚动保留期就是 90 天）——分片拉，落盘
    python -m backend.services.vmax_multi_data.vmax_multi_data_service --report all \
        --days 90 --granularity date --progress

    注意两层上限（实测，见 vmax_report_client 头注释）：
      · 上游保留期：date 粒度 90 天；hour 粒度 ~30 天，再往前单请求会超时；
      · 单请求行数上限 = topN/pageSize（服务端按默认排序截断，翻页无效）——
        故 top_n 默认 20000，并按 chunk_days 分片，结果带 truncated 标记。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

if __package__ in (None, ""):                                            # 直接 python 跑本文件时
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.services.vmax_multi_data import vmax_report_client as vrc

logger = logging.getLogger("vmax_multi_data")

_ROOT = Path(__file__).resolve().parents[3]          # my_app/
# 与 backend/services/ran_ume_config.json 等一致：任务配置放在 services/ 下，
# 这样「设置 → 任务配置」页（task_configs_registry 的 _cfg）改的就是本文件。
CONFIG_PATH = Path(__file__).resolve().parents[1] / "vmax_multi_data_config.json"
DATA_DIR = _ROOT / "data" / "vmax_multi_data"
SQLITE_PATH = DATA_DIR / "vmax_multi_data.sqlite3"

DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "transport": "auto",
    "granularity": "hour",
    "days_back": 1,
    # top_n 必须给大：上游单次请求按 topN 截断（按报表默认排序，日期跨度看着就"缺一段"）。
    # 实测 date 粒度 90 天全量 = 656 行，topN=200 时只会回 200 行。
    "top_n": 20000,
    "page_size": 20000,
    "chunk_days": dict(vrc.DEFAULT_CHUNK_DAYS),
    "persist": {"write_json": True, "write_sqlite": True, "write_remote_db": False,
                "remote_db": "vmax_kpi_daily.sqlite3", "remote_table": "vmax_multi_data_kpi"},
    "reports": [],
}


# ==========================================================================
# 配置
# ==========================================================================
def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """读配置（缺文件/字段时回退 DEFAULTS），环境变量可覆盖传输与天数。"""
    cfg = json.loads(json.dumps(DEFAULTS))                               # deep copy
    real = Path(path or CONFIG_PATH)
    if real.exists():
        try:
            data = json.loads(real.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key, value in data.items():
                    if key == "persist" and isinstance(value, dict):
                        cfg["persist"].update(value)
                    else:
                        cfg[key] = value
        except Exception as exc:                                         # noqa: BLE001
            logger.warning("[vmax_multi_data] 配置读取失败，使用默认: %s", exc)
    if os.environ.get("VMAX_TRANSPORT"):
        cfg["transport"] = os.environ["VMAX_TRANSPORT"]
    if os.environ.get("VMAX_MULTI_DAYS_BACK"):
        try:
            cfg["days_back"] = max(1, int(os.environ["VMAX_MULTI_DAYS_BACK"]))
        except ValueError:
            pass
    return cfg


def enabled_reports(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [r for r in (cfg.get("reports") or []) if r.get("enabled", True) and r.get("report_part")]


def select_reports(cfg: Dict[str, Any], keys: Optional[Iterable[str]]) -> List[Dict[str, Any]]:
    reports = enabled_reports(cfg)
    if not keys or "all" in [str(k).lower() for k in keys]:
        return reports
    wanted = {str(k).lower() for k in keys}
    return [r for r in reports if str(r.get("key", "")).lower() in wanted
            or str(r.get("report_part", "")).lower() in wanted]


# ==========================================================================
# 取数
# ==========================================================================
def fetch_report(report: Dict[str, Any], cfg: Dict[str, Any],
                 client: Optional[vrc.VmaxReportClient] = None,
                 begin: Any = None, end: Any = None,
                 granularity: Optional[str] = None,
                 progress: bool = False) -> Dict[str, Any]:
    """取单个报表的指标（分片拉全窗口，返回扁平化后的结果，供落盘/展示）。

    行数上限与分片策略见 vmax_report_client 头注释（上游 date 粒度只留 90 天；
    TopN 会截断结果，所以默认 top_n 给大并用 truncated 标记兜底）。
    """
    client = client or vrc.VmaxReportClient(transport=cfg.get("transport"))
    part = report["report_part"]
    gran = vrc.normalize_granularity(granularity or report.get("granularity")
                                     or cfg.get("granularity") or "hour")
    days = int(report.get("days_back") or cfg.get("days_back") or 1)
    if begin is None or end is None:
        begin, end = vrc.time_window(days, gran)
    top_n = int(report.get("top_n") or cfg.get("top_n") or 20000)
    # page_size 单独可配：上游 paging.pageSize 决定单请求实际返回行数（不配则跟 top_n 一致）
    page_size = int(report.get("page_size") or cfg.get("page_size") or top_n)
    res = client.query_kpis_range(
        part, begin, end, granularity=gran,
        dims=report.get("dims"), kpis=report.get("kpis"), top_n=top_n,
        page_size=page_size,
        chunk_days=report.get("chunk_days") or cfg.get("chunk_days"),
        filters=report.get("filters") or [], progress=progress)
    if not res["fields"] and res.get("errors"):
        raise vrc.VmaxReportError("%s 取数失败: %s" % (part, res["errors"][0]))
    records = res["records"]
    if res.get("truncated"):
        logger.warning("[vmax_multi_data] %s 单分片行数达到 top_n=%d，可能被截断，"
                       "请调大 top_n 或调小 chunk_days", part, top_n)
    return {
        "key": report.get("key") or part,
        "title": report.get("title") or part,
        "report_part": part,
        "table": report.get("table") or _table_name(client, part),
        "granularity": gran,
        "window": res["window"],
        "fields": res.get("fields") or [],
        "raw_fields": res.get("raw_fields") or [],
        "headers": res.get("headers") or [],
        "columns": res.get("columns") or [],
        "records": records,
        "total": len(records),
        "slices": res.get("slices") or 1,
        "truncated": bool(res.get("truncated")),
        "slice_errors": res.get("errors") or [],
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _table_name(client: vrc.VmaxReportClient, report_part: str) -> str:
    try:
        meta = client.report_config(report_part).get("metadata") or {}
        tables = meta.get("table") or []
        if tables and isinstance(tables[0], dict):
            return str(tables[0].get("id") or "")
    except Exception:                                                    # noqa: BLE001
        pass
    return ""


# ==========================================================================
# 落盘
# ==========================================================================
def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def persist_json(result: Dict[str, Any]) -> Path:
    path = DATA_DIR / ("%s_latest.json" % result["key"])
    _write_json_atomic(path, result)
    return path


def persist_sqlite(result: Dict[str, Any], db_path: Optional[Path] = None) -> int:
    """明细行写入本地 SQLite（同一报表+窗口+粒度先删后插，便于重跑覆盖）。"""
    path = Path(db_path or SQLITE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    begin = result["window"]["begin"]
    end = result["window"]["end"]
    gran = result["granularity"]
    conn = sqlite3.connect(str(path), timeout=30)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kpi_rows (
                report_key TEXT NOT NULL,
                report_part TEXT NOT NULL,
                granularity TEXT NOT NULL,
                window_begin TEXT NOT NULL,
                window_end TEXT NOT NULL,
                row_no INTEGER NOT NULL,
                row_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (report_key, granularity, window_begin, window_end, row_no)
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_key TEXT NOT NULL,
                report_part TEXT NOT NULL,
                granularity TEXT NOT NULL,
                window_begin TEXT NOT NULL,
                window_end TEXT NOT NULL,
                rows INTEGER NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                started_at TEXT,
                finished_at TEXT
            )""")
        conn.execute("DELETE FROM kpi_rows WHERE report_key=? AND granularity=? "
                     "AND window_begin=? AND window_end=?", (result["key"], gran, begin, end))
        conn.executemany(
            "INSERT INTO kpi_rows (report_key, report_part, granularity, window_begin, "
            "window_end, row_no, row_json, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            [(result["key"], result["report_part"], gran, begin, end, i,
              json.dumps(row, ensure_ascii=False), result["fetched_at"])
             for i, row in enumerate(result["records"])])
        conn.commit()
    finally:
        conn.close()                        # 必须显式 close：with 语句只提交不关连接
    return len(result["records"])


def persist_run(report_part: str, report_key: str, granularity: str, window: Dict[str, Any],
                rows: int, status: str, error: str = "", started_at: str = "",
                finished_at: str = "", db_path: Optional[Path] = None) -> None:
    """记录一次采集运行（成功/失败都记），便于排查「某小时为什么没数据」。"""
    path = Path(db_path or SQLITE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_key TEXT NOT NULL,
                report_part TEXT NOT NULL,
                granularity TEXT NOT NULL,
                window_begin TEXT NOT NULL,
                window_end TEXT NOT NULL,
                rows INTEGER NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                started_at TEXT,
                finished_at TEXT
            )""")
        conn.execute("INSERT INTO sync_runs (report_key, report_part, granularity, window_begin, "
                     "window_end, rows, status, error, started_at, finished_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (report_key, report_part, granularity, str(window.get("begin", "")),
                      str(window.get("end", "")), int(rows), status, error[:500],
                      started_at, finished_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    finally:
        conn.close()


def persist_remote(result: Dict[str, Any], persist_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """可选的远程 DB 写入（db_writer_client，默认关闭）。"""
    if not persist_cfg.get("write_remote_db"):
        return {"skipped": True}
    try:
        from backend.services.db_writer_client import write_data
    except Exception as exc:                                             # noqa: BLE001
        return {"error": "db_writer_client 不可用: %s" % exc}
    columns = ["report_key", "report_part", "granularity", "window_begin", "window_end",
               "row_no", "row_json", "fetched_at"]
    rows = [[result["key"], result["report_part"], result["granularity"],
             result["window"]["begin"], result["window"]["end"], i,
             json.dumps(row, ensure_ascii=False), result["fetched_at"]]
            for i, row in enumerate(result["records"])]
    try:
        write_data(persist_cfg.get("remote_db") or "vmax_kpi_daily.sqlite3",
                   persist_cfg.get("remote_table") or "vmax_multi_data_kpi",
                   columns, rows, create_if_missing=True)
        return {"rows": len(rows)}
    except Exception as exc:                                             # noqa: BLE001
        return {"error": str(exc)}


# ==========================================================================
# 任务入口
# ==========================================================================
def run_vmax_multi_data_sync(reports: Optional[Iterable[str]] = None,
                             begin: Any = None, end: Any = None,
                             granularity: Optional[str] = None,
                             persist: bool = True,
                             top_n: Optional[int] = None,
                             chunk_days: Optional[int] = None,
                             progress: bool = False,
                             include_records: bool = False,
                             config_path: Optional[Path] = None) -> Dict[str, Any]:
    """任务入口：逐个报表取指标并落盘。返回摘要（含 errors）。

    top_n / chunk_days 显式传入时覆盖配置（CLI 与一次性补数用；config 里那份是默认值）。
    include_records=True 时把明细行一并放进 reports[]（CLI 打印样本用，避免为了打印再拉一次）。
    """
    started = time.time()
    cfg = load_config(config_path)
    targets = select_reports(cfg, reports)
    for r in targets:                                    # 覆盖项要落在选出来的这批上
        if top_n:
            r["top_n"] = int(top_n)
        if chunk_days:
            r["chunk_days"] = int(chunk_days)
    if not cfg.get("enabled", True):
        return {"status": "disabled", "reports": [], "rows": 0, "elapsed_seconds": 0}
    if not targets:
        return {"status": "no_report", "reports": [], "rows": 0,
                "error": "配置里没有启用的报表（vmax_multi_data_config.json）"}

    client = vrc.VmaxReportClient(transport=cfg.get("transport"))
    health = client.healthy()
    if not health.get("ready"):
        return {"status": "unavailable", "transport": health.get("transport"),
                "error": "VMAX 不可达: %s" % (health.get("detail"),),
                "reports": [], "rows": 0, "elapsed_seconds": round(time.time() - started, 2)}

    results: List[Dict[str, Any]] = []
    errors: List[str] = []
    total_rows = 0
    started_at = datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S")
    write_runs = persist and cfg["persist"].get("write_sqlite", True)
    for report in targets:
        part = report.get("report_part")
        try:
            result = fetch_report(report, cfg, client=client, begin=begin, end=end,
                                  granularity=granularity, progress=progress)
        except Exception as exc:                                         # noqa: BLE001
            logger.warning("[vmax_multi_data] %s 取数失败: %s", part, exc)
            errors.append("%s: %s" % (part, exc))
            if write_runs:
                persist_run(part, report.get("key") or part,
                            vrc.normalize_granularity(granularity or report.get("granularity")
                                                      or cfg.get("granularity") or "hour"),
                            {"begin": str(begin or ""), "end": str(end or "")}, 0,
                            "failed", str(exc), started_at)
            continue
        total_rows += len(result["records"])
        entry = {"key": result["key"], "report_part": result["report_part"],
                 "table": result["table"], "window": result["window"],
                 "granularity": result["granularity"], "rows": len(result["records"]),
                 "slices": result.get("slices"), "truncated": result.get("truncated"),
                 "fields": result["fields"], "fetched_at": result["fetched_at"]}
        if result.get("truncated"):
            errors.append("%s 单分片达到 top_n 上限，可能被截断（调大 top_n 或调小 chunk_days）"
                          % result["key"])
        if result.get("slice_errors"):
            errors.append("%s 有分片失败: %s" % (result["key"], result["slice_errors"][0]))
        if persist:
            if cfg["persist"].get("write_json", True):
                entry["json"] = str(persist_json(result))
            if cfg["persist"].get("write_sqlite", True):
                entry["sqlite_rows"] = persist_sqlite(result)
            remote = persist_remote(result, cfg["persist"])
            if remote.get("error"):
                entry["remote_error"] = remote["error"]
                errors.append("%s 远程写入失败: %s" % (result["key"], remote["error"]))
        if write_runs:
            persist_run(result["report_part"], result["key"], result["granularity"],
                        result["window"], len(result["records"]),
                        "ok" if not entry.get("remote_error") else "partial",
                        entry.get("remote_error", ""), started_at, result["fetched_at"])
        if include_records:
            entry["headers"] = result["headers"]
            entry["columns"] = result["columns"]
            entry["records"] = result["records"]
        results.append(entry)

    summary = {"status": "ok" if not errors else "partial",
               "transport": health.get("transport"),
               "reports": results, "rows": total_rows,
               "errors": errors[:10],
               "elapsed_seconds": round(time.time() - started, 2)}
    print("[vmax_multi_data] %s reports=%d rows=%d elapsed=%ss errors=%s"
          % (summary["status"], len(results), total_rows, summary["elapsed_seconds"], errors[:3]))
    return summary


# ==========================================================================
# CLI
# ==========================================================================
def _cmd_check(cfg: Dict[str, Any]) -> int:
    client = vrc.VmaxReportClient(transport=cfg.get("transport"))
    health = client.healthy()
    print("transport :", health.get("transport"), "ready =", health.get("ready"))
    print("detail    :", json.dumps(health.get("detail"), ensure_ascii=False)[:300])
    if not health.get("ready"):
        return 2
    try:
        print("vreport session:", client.vreport_session())
    except Exception as exc:                                             # noqa: BLE001
        print("vreport session 获取失败:", exc)
        return 3
    for report in enabled_reports(cfg):
        try:
            client.report_config(report["report_part"])
            print("配置 OK   :", report["report_part"], "-> show =",
                  client.default_show(report["report_part"], report.get("dims"), report.get("kpis"))[:12])
        except Exception as exc:                                         # noqa: BLE001
            print("配置失败  :", report["report_part"], exc)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    # 必须在 parse_args 之前：否则 --help 的中文说明写到重定向的管道（Windows 默认 cp1252）会崩
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="VMAX vReport 指标采集（url.txt 的两个 CIService 报表）")
    ap.add_argument("--report", action="append", help="报表 key/report_part，可多次；默认 all")
    ap.add_argument("--list", action="store_true", help="列出配置中的报表")
    ap.add_argument("--check", action="store_true", help="健康检查（代理/直连 + 会话 + 报表配置）")
    ap.add_argument("--start", default=None, help="开始时间 YYYY-MM-DD[ HH:MM[:SS]]")
    ap.add_argument("--end", default=None, help="结束时间 YYYY-MM-DD[ HH:MM[:SS]]")
    ap.add_argument("--days", type=int, default=None,
                    help="最近 N 天（date 粒度上游只保留 90 天；hour 粒度 ≈30 天，再往前会很慢）")
    ap.add_argument("--granularity", default=None, help="hour|date|week|month|5min|quarter")
    ap.add_argument("--top-n", type=int, default=None,
                    help="单分片行数上限（默认取配置 20000；上游按 topN 截断结果）")
    ap.add_argument("--chunk-days", type=int, default=None, help="分片跨度天数（默认按粒度取配置）")
    ap.add_argument("--progress", action="store_true", help="打印每个分片的进度")
    ap.add_argument("--no-persist", action="store_true", help="只打印，不落盘")
    ap.add_argument("--full", action="store_true", help="打印全部记录（默认只打印前 5 行）")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.list:
        for r in cfg.get("reports") or []:
            print("%-8s %-32s %s" % (r.get("key"), r.get("report_part"),
                                     "启用" if r.get("enabled", True) else "停用"))
        return 0
    if args.check:
        return _cmd_check(cfg)

    begin = end = None
    if args.start and args.end:
        begin, end = args.start, args.end
    elif args.days:
        begin, end = vrc.time_window(int(args.days), args.granularity or cfg.get("granularity") or "hour")

    targets = select_reports(cfg, args.report)
    for r in targets:                                    # 与 run_vmax_multi_data_sync 一致的覆盖
        if args.top_n:
            r["top_n"] = args.top_n
        if args.chunk_days:
            r["chunk_days"] = args.chunk_days
    if not targets:
        print("没有匹配的报表（用 --list 查看）")
        return 1

    client = vrc.VmaxReportClient(transport=cfg.get("transport"))
    summary = run_vmax_multi_data_sync(
        reports=[r["key"] for r in targets], begin=begin, end=end,
        granularity=args.granularity, persist=not args.no_persist,
        top_n=args.top_n, chunk_days=args.chunk_days, progress=args.progress,
        include_records=True)                        # 明细随摘要带回来，避免为了打印再拉一次
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("reports", "errors")} | {"errors": summary.get("errors")},
                     ensure_ascii=False, indent=1))

    if summary.get("status") in ("unavailable", "no_report"):
        return 2
    for entry in summary["reports"]:                                     # 直接打印样本
        recs = entry.get("records") or []
        print("\n=== %s (%s) %s ~ %s rows=%d fields=%d 分片=%s 截断=%s"
              % (entry["key"], entry["report_part"], entry["window"]["begin"],
                 entry["window"]["end"], entry["rows"], len(entry.get("fields") or []),
                 entry.get("slices"), entry.get("truncated")))
        if entry.get("headers"):
            print("header:", json.dumps(entry["headers"], ensure_ascii=False)[:400])
        for row in (recs if args.full else recs[:5]):
            print("  ", json.dumps(row, ensure_ascii=False)[:400])
    for err in summary.get("errors") or []:
        print("警告:", err)
    return 0


if __name__ == "__main__":
    sys.exit(main())

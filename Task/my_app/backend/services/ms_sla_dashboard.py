# -*- coding: utf-8 -*-
"""MS SLA 看板数据写入服务

职责
----
把 MS Contract KPIs / MS WOs SLA 两份日报的底层数据（KPI List 解析结果 +
lbr_ms_sla_kpi.sqlite3 的 Network/Per-Site KPI）全量写入独立看板库
``data/ms_sla/ms_sla_dashboard.sqlite3``，供看板 API（backend/routers/ms_sla_dashboard.py）
读取。邮件发送功能（kpi_email_report.py / owa_mail_report.py）与本模块无关，不受影响。

数据来源（全部由 ms_sla_report.run_contract_kpis_report 主流程产出的数据集）
-------------------------------------------------------------------------
- ``nur_daily`` / ``nur_monthly``  : KPI List NUR Daily/Monthly（NUR_NETWORK/NUR_2G/NUR_3G/NUR_4G）
- ``sla_daily`` / ``sla_monthly``  : KPI List SLA Daily/Monthly（TTR/TTR_P1..P4 的 SLA 达成率）
- WO 详情（sla_detail_daily/monthly）: 同一 KPI List 的 Total/Within SLA/Achieve 三列
- Network KPIs（2G_CSSR 等 7 项）与 Per-Site 占比（PS_NUR_2G 等 11 项）:
  从 lbr_ms_sla_kpi.sqlite3 按日期/月份查询（复用 ms_sla_report.get_db_value / get_persite_ratio）

写入策略
--------
全量 upsert（INSERT OR REPLACE / ON CONFLICT DO UPDATE）：每次运行把所有期间
重写一遍，天然实现历史回填与数据自愈，无需单独 backfill 脚本。

表结构
------
- ms_sla_kpi(period, dataset, metric, value)  : 标量指标；dataset 取值
  nur_daily / nur_monthly / sla_daily / sla_monthly / network_daily /
  network_monthly / persite_daily / persite_monthly
- ms_sla_wo(period, metric, total, within_sla, achieve) : WO SLA 详情
- ms_sla_meta(key, value)  : last_sync_time / kpi_list_mtime 等数据新鲜度信息

容错
----
写库过程中任何解析/查询/写入异常都显式向上抛出（数据完整性问题不得静默），
由调用方（ms_sla_report.run_contract_kpis_report）捕获并记入任务结果，
不影响原有 Excel 更新与邮件发送主流程。
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from backend.database import get_raw_connection
from backend.dialect_helpers import upsert

from backend.services.ms_sla_service import DATA_DIR, DB_PATH, KPI_LIST_FILE, logger  # noqa: F401  (复用路径/logger)

try:
    from backend.services.ms_sla_report import (
        NETWORK_KPI_DAILY_MAP,
        NETWORK_KPI_MONTHLY_MAP,
        PERSITE_KPI_DAILY_MAP,
        PERSITE_KPI_MONTHLY_MAP,
        get_db_value,
        get_persite_ratio,
        read_sla_detail_daily,
        read_sla_detail_monthly,
    )
except ImportError:  # 兼容以 backend 为根的导入方式
    from ms_sla_report import (
        NETWORK_KPI_DAILY_MAP,
        NETWORK_KPI_MONTHLY_MAP,
        PERSITE_KPI_DAILY_MAP,
        PERSITE_KPI_MONTHLY_MAP,
        get_db_value,
        get_persite_ratio,
        read_sla_detail_daily,
        read_sla_detail_monthly,
    )

# 看板库：独立文件（遵循 packet_loss 看板 lte_pl.sqlite3 先例；PG 模式映射 ms_sla_dashboard schema）
DASH_DB_PATH = Path(DATA_DIR) / "ms_sla_dashboard.sqlite3"

_DDL = """
CREATE TABLE IF NOT EXISTS ms_sla_kpi (
    period  TEXT NOT NULL,
    dataset TEXT NOT NULL,
    metric  TEXT NOT NULL,
    value   REAL,
    PRIMARY KEY (period, dataset, metric)
);
CREATE TABLE IF NOT EXISTS ms_sla_wo (
    period     TEXT NOT NULL,
    metric     TEXT NOT NULL,
    total      REAL,
    within_sla REAL,
    achieve    REAL,
    PRIMARY KEY (period, metric)
);
CREATE TABLE IF NOT EXISTS ms_sla_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _ensure_schema(conn) -> None:
    """幂等建表（sqlite / PG 双模）。

    PG 分支先 ``CREATE SCHEMA IF NOT EXISTS`` 确保目标 schema 存在再建表：
    PG 的 search_path 会静默跳过不存在的 schema，若 schema 缺失，未限定
    schema 的 CREATE TABLE 会被建到第一个存在的 schema（如 app），导致
    看板 API 查不到数据——因此这里显式建 schema 并保持幂等。
    """
    if isinstance(conn, sqlite3.Connection):
        conn.executescript(_DDL)
        return
    conn.execute("CREATE SCHEMA IF NOT EXISTS ms_sla_dashboard")
    conn.executescript(_DDL)


def _to_float(v):
    """Excel/SQLite 读出的值统一转 float；无法转换返回 None。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return None


def _collect_network_kpis(periods, kpi_map, conn_src) -> dict:
    """按 KPI List 的期间列表查询 Network KPI，返回 {period: {metric: value}}。"""
    out: dict = {}
    for metric, cfg in kpi_map.items():
        for p in periods:
            v = get_db_value(conn_src, cfg["table"], cfg["column"], p)
            if v is not None:
                out.setdefault(p, {})[metric] = _to_float(v)
    return out


def _collect_persite_kpis(periods, kpi_map, conn_src) -> dict:
    """按 KPI List 的期间列表查询 Per-Site 占比（满足阈值的站点比例）。"""
    out: dict = {}
    for metric, cfg in kpi_map.items():
        for p in periods:
            v = get_persite_ratio(conn_src, cfg["table"], cfg["column"], p, cfg["op"], cfg["threshold"])
            if v is not None:
                out.setdefault(p, {})[metric] = _to_float(v)
    return out


def _collect_wo_details() -> tuple[dict, dict]:
    """从 KPI List 工作簿读取 WO SLA 日/月详情（Total/Within SLA/Achieve 三列）。"""
    wb = load_workbook(str(KPI_LIST_FILE), data_only=True)
    try:
        daily = read_sla_detail_daily(wb["KPI List SLA Daily"]) if "KPI List SLA Daily" in wb.sheetnames else {}
        monthly = read_sla_detail_monthly(wb["KPI List SLA Monthly"]) if "KPI List SLA Monthly" in wb.sheetnames else {}
    finally:
        wb.close()
    return daily, monthly


def write_dashboard_data(datasets: dict) -> dict:
    """全量 upsert 看板数据（自包含：内部读取 WO 详情与 Network/Per-Site KPI）。

    参数 datasets: ``_load_kpi_list_datasets()`` 返回的 4 数据集 dict
    （nur_daily / nur_monthly / sla_daily / sla_monthly）。

    返回 {"rows": 写入行数, "elapsed_seconds": 耗时}。
    任何异常显式抛出，由调用方决定是否影响主流程。
    """
    t0 = time.time()
    if not DASH_DB_PATH.parent.is_dir():
        raise FileNotFoundError(f"看板数据目录不存在: {DASH_DB_PATH.parent}")

    daily_periods = sorted(set(datasets.get("nur_daily", {})) | set(datasets.get("sla_daily", {})))
    monthly_periods = sorted(set(datasets.get("nur_monthly", {})) | set(datasets.get("sla_monthly", {})))

    # ---- 1. 从 lbr_ms_sla_kpi.sqlite3 查询 Network / Per-Site KPI ----
    conn_src = get_raw_connection(str(DB_PATH), timeout=30)
    try:
        network_daily = _collect_network_kpis(daily_periods, NETWORK_KPI_DAILY_MAP, conn_src)
        network_monthly = _collect_network_kpis(monthly_periods, NETWORK_KPI_MONTHLY_MAP, conn_src)
        persite_daily = _collect_persite_kpis(daily_periods, PERSITE_KPI_DAILY_MAP, conn_src)
        persite_monthly = _collect_persite_kpis(monthly_periods, PERSITE_KPI_MONTHLY_MAP, conn_src)
    finally:
        conn_src.close()

    # ---- 2. 读取 WO SLA 详情 ----
    wo_daily, wo_monthly = _collect_wo_details()

    # ---- 3. 全量写入看板库 ----
    rows = 0
    with get_raw_connection(str(DASH_DB_PATH), timeout=30) as conn:
        _ensure_schema(conn)

        # 3a. KPI List 4 个数据集
        for ds in ("nur_daily", "nur_monthly", "sla_daily", "sla_monthly"):
            kpi_rows = [
                {"period": p, "dataset": ds, "metric": m, "value": _to_float(v)}
                for p, metrics in datasets.get(ds, {}).items()
                for m, v in metrics.items()
            ]
            if kpi_rows:
                rows += upsert(conn, "ms_sla_kpi", kpi_rows, ["period", "dataset", "metric"])

        # 3b. Network / Per-Site KPI
        for ds, data in (
            ("network_daily", network_daily),
            ("network_monthly", network_monthly),
            ("persite_daily", persite_daily),
            ("persite_monthly", persite_monthly),
        ):
            kpi_rows = [
                {"period": p, "dataset": ds, "metric": m, "value": v}
                for p, metrics in data.items()
                for m, v in metrics.items()
            ]
            if kpi_rows:
                rows += upsert(conn, "ms_sla_kpi", kpi_rows, ["period", "dataset", "metric"])

        # 3c. WO SLA 详情（日/月共用 ms_sla_wo，月份行 period 为 YYYY-MM）
        for p, metrics in {**wo_daily, **wo_monthly}.items():
            wo_rows = [
                {
                    "period": p,
                    "metric": m,
                    "total": _to_float(d.get("total")),
                    "within_sla": _to_float(d.get("within_sla")),
                    "achieve": _to_float(d.get("achieve")),
                }
                for m, d in metrics.items()
            ]
            if wo_rows:
                rows += upsert(conn, "ms_sla_wo", wo_rows, ["period", "metric"])

        # 3d. 元信息（数据新鲜度）
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta_rows = [
            {"key": "last_sync_time", "value": now_str},
            {"key": "kpi_list_path", "value": str(KPI_LIST_FILE)},
            {"key": "kpi_list_mtime", "value": str(datetime.fromtimestamp(KPI_LIST_FILE.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")) if KPI_LIST_FILE.exists() else ""},
        ]
        rows += upsert(conn, "ms_sla_meta", meta_rows, ["key"])

    elapsed = time.time() - t0
    logger.info(f"MS SLA 看板数据写入完成: {rows} 行 -> {DASH_DB_PATH.name} ({elapsed:.1f}s)")
    return {"rows": rows, "elapsed_seconds": round(elapsed, 2)}


if __name__ == "__main__":
    # 独立运行调试：读取现有 KPI List 并写库
    sys_out = __import__("sys")
    try:
        sys_out.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from backend.services.ms_sla_report import _load_kpi_list_datasets  # noqa: E402

    t_start = time.time()
    ds = _load_kpi_list_datasets()
    result = write_dashboard_data(ds)
    result["total_elapsed"] = round(time.time() - t_start, 2)
    print(f"[MS-SLA-DASH] done: {result}")

"""MS SLA Contract KPIs 报表服务（Phase 4 从 ms_sla_service.py 拆分）

负责 Contract KPIs & WOs Achievement 报表的生成与分发：
- 从本地 SQLite 读取 NUR/SLA 日/月指标（read_nur_*/read_sla_*）
- 更新模板 Excel（WO SLA 报表 + Contract KPIs 月/日行）并保留原格式
- 条件格式/着色、HTML/PNG 导出、FTP 上传与旧文件清理
路径/FTP 等共享常量仍由 ms_sla_service 提供（本模块单向依赖，无循环）。
"""

import base64
import gc
import glob
import gzip
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
import copy
import logging
import warnings
import threading
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, date, timezone, timedelta
from ftplib import FTP, error_perm
from pathlib import Path

import openpyxl
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import PatternFill, Font
from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names, table_columns

try:
    from backend.services.atomic_write import atomic_save_workbook, AtomicReplaceFallback
except ImportError:
    from atomic_write import atomic_save_workbook, AtomicReplaceFallback

# PNG 导出依赖 PIL（可选；未安装时 HAS_PIL=False，export_sheet_to_png 自动跳过）
try:
    from PIL import Image, ImageDraw, ImageFont  # noqa: F401
except ImportError:
    Image = ImageDraw = ImageFont = None

from backend.services.ms_sla_service import (  # Phase 4 拆分：共享常量/基础函数
    DATA_DIR,
    DB_PATH,
    FTP_SRC_BASE_DIR,
    FTP_SRC_HOST,
    FTP_SRC_PASS,
    FTP_SRC_PORT,
    FTP_SRC_USER,
    FTP_UP_HOST,
    FTP_UP_PASS,
    FTP_UP_PORT,
    FTP_UP_REMOTE_DIR,
    FTP_UP_USER,
    KPI_LIST_FILE,
    TARGET_FILE,
    HAS_PIL,
    logger,
)


TARGET_COL_NUR_NETWORK = 2    # B
TARGET_COL_NUR_2G = 3         # C
TARGET_COL_NUR_3G = 4         # D
TARGET_COL_NUR_4G = 5         # E
TARGET_COL_TTR = 6            # F
TARGET_COL_TTR_P1 = 7         # G
TARGET_COL_TTR_P2 = 8         # H
TARGET_COL_TTR_P3 = 9         # I
TARGET_COL_TTR_P4 = 10        # J

TARGET_COL_2G_CSSR = 11       # K
TARGET_COL_2G_DCR = 12        # L
TARGET_COL_3G_CSSR = 13       # M
TARGET_COL_3G_DCR = 14        # N
TARGET_COL_3G_CSSR_HSDPA = 15 # O
TARGET_COL_3G_DCR_HSDPA = 16  # P
TARGET_COL_3G_2G_HO = 17      # Q

TARGET_COL_PS_NUR_2G = 18       # R
TARGET_COL_PS_DCR_2G = 19       # S
TARGET_COL_PS_CSSR_2G = 20      # T
TARGET_COL_PS_TCH_BLK = 21      # U
TARGET_COL_PS_NUR_3G = 22       # V
TARGET_COL_PS_CSSR_3G = 23      # W
TARGET_COL_PS_DCR_3G = 24       # X
TARGET_COL_PS_CSSR_HSDPA = 25   # Y
TARGET_COL_PS_DCR_HSDPA = 26    # Z
TARGET_COL_PS_3G_2G_HO = 27     # AA
TARGET_COL_PS_RADIO_CONG = 28   # AB

TARGET_SHEET = "Contract KPIs Report (New)"
WO_SHEET = "WOs SLA achievement Report"
NETWORK_KPI_DAILY_MAP = {
    "2G_CSSR": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_NW", "column": "OCI_2G_CSSR_CS(%)", "target_col": TARGET_COL_2G_CSSR},
    "2G_DCR": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_NW", "column": "TCH in call drop rate(include handover)(%)", "target_col": TARGET_COL_2G_DCR},
    "3G_CSSR": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_NW", "column": "U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO", "target_col": TARGET_COL_3G_CSSR},
    "3G_DCR": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_NW", "column": "Ratio of CS Call Drop(%)", "target_col": TARGET_COL_3G_DCR},
    "3G_CSSR_HSDPA": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_NW", "column": "U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO", "target_col": TARGET_COL_3G_CSSR_HSDPA},
    "3G_DCR_HSDPA": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_NW", "column": "U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO", "target_col": TARGET_COL_3G_DCR_HSDPA},
    "3G_2G_HO": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_NW", "column": "Cell Inter-RAT CS Outgoing Handover Success Rate(WCDMA->GSM)(%)", "target_col": TARGET_COL_3G_2G_HO},
}

NETWORK_KPI_MONTHLY_MAP = {
    "2G_CSSR": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_NW", "column": "OCI_2G_CSSR_CS(%)", "target_col": TARGET_COL_2G_CSSR},
    "2G_DCR": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_NW", "column": "TCH in call drop rate(include handover)(%)", "target_col": TARGET_COL_2G_DCR},
    "3G_CSSR": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_NW", "column": "U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO", "target_col": TARGET_COL_3G_CSSR},
    "3G_DCR": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_NW", "column": "Ratio of CS Call Drop(%)", "target_col": TARGET_COL_3G_DCR},
    "3G_CSSR_HSDPA": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_NW", "column": "U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO", "target_col": TARGET_COL_3G_CSSR_HSDPA},
    "3G_DCR_HSDPA": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_NW", "column": "U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO", "target_col": TARGET_COL_3G_DCR_HSDPA},
    "3G_2G_HO": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_NW", "column": "Cell Inter-RAT CS Outgoing Handover Success Rate(WCDMA->GSM)(%)", "target_col": TARGET_COL_3G_2G_HO},
}
PERSITE_KPI_DAILY_MAP = {
    "PS_NUR_2G": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_SITE", "column": "TCH in service rate(%)", "op": ">=", "threshold": 0.9965, "target_col": TARGET_COL_PS_NUR_2G},
    "PS_DCR_2G": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_SITE", "column": "TCH in call drop rate(include handover)(%)", "op": "<=", "threshold": 0.02, "target_col": TARGET_COL_PS_DCR_2G},
    "PS_CSSR_2G": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_SITE", "column": "OCI_2G_CSSR_CS(%)", "op": ">=", "threshold": 0.97, "target_col": TARGET_COL_PS_CSSR_2G},
    "PS_TCH_BLK": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_SITE", "column": "TCH in congestion rate(include handover)(%)", "op": "<=", "threshold": 0.02, "target_col": TARGET_COL_PS_TCH_BLK},
    "PS_NUR_3G": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE", "column": "Cell Validity Rate(%)", "op": ">=", "threshold": 0.9965, "target_col": TARGET_COL_PS_NUR_3G},
    "PS_CSSR_3G": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE", "column": "U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO", "op": ">=", "threshold": 0.97, "target_col": TARGET_COL_PS_CSSR_3G},
    "PS_DCR_3G": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE", "column": "Ratio of CS Call Drop(%)", "op": "<=", "threshold": 0.02, "target_col": TARGET_COL_PS_DCR_3G},
    "PS_CSSR_HSDPA": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE", "column": "U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO", "op": ">=", "threshold": 0.98, "target_col": TARGET_COL_PS_CSSR_HSDPA},
    "PS_DCR_HSDPA": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE", "column": "U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO", "op": "<=", "threshold": 0.02, "target_col": TARGET_COL_PS_DCR_HSDPA},
    "PS_3G_2G_HO": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE", "column": "Cell Inter-RAT CS Outgoing Handover Success Rate(WCDMA->GSM)(%)", "op": ">=", "threshold": 0.95, "target_col": TARGET_COL_PS_3G_2G_HO},
    "PS_RADIO_CONG": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE", "column": "U31_3G & 3G+ Radio Congestion Rate_901620_2_UROP.RNC-MO", "op": "<=", "threshold": 0.02, "target_col": TARGET_COL_PS_RADIO_CONG},
}

PERSITE_KPI_MONTHLY_MAP = {
    "PS_NUR_2G": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_SITE", "column": "TCH in service rate(%)", "op": ">=", "threshold": 0.9965, "target_col": TARGET_COL_PS_NUR_2G},
    "PS_DCR_2G": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_SITE", "column": "TCH in call drop rate(include handover)(%)", "op": "<=", "threshold": 0.02, "target_col": TARGET_COL_PS_DCR_2G},
    "PS_CSSR_2G": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_SITE", "column": "OCI_2G_CSSR_CS(%)", "op": ">=", "threshold": 0.97, "target_col": TARGET_COL_PS_CSSR_2G},
    "PS_TCH_BLK": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_SITE", "column": "TCH in congestion rate(include handover)(%)", "op": "<=", "threshold": 0.02, "target_col": TARGET_COL_PS_TCH_BLK},
    "PS_NUR_3G": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE", "column": "Cell Validity Rate(%)", "op": ">=", "threshold": 0.9965, "target_col": TARGET_COL_PS_NUR_3G},
    "PS_CSSR_3G": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE", "column": "U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO", "op": ">=", "threshold": 0.97, "target_col": TARGET_COL_PS_CSSR_3G},
    "PS_DCR_3G": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE", "column": "Ratio of CS Call Drop(%)", "op": "<=", "threshold": 0.02, "target_col": TARGET_COL_PS_DCR_3G},
    "PS_CSSR_HSDPA": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE", "column": "U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO", "op": ">=", "threshold": 0.98, "target_col": TARGET_COL_PS_CSSR_HSDPA},
    "PS_DCR_HSDPA": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE", "column": "U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO", "op": "<=", "threshold": 0.02, "target_col": TARGET_COL_PS_DCR_HSDPA},
    "PS_3G_2G_HO": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE", "column": "Cell Inter-RAT CS Outgoing Handover Success Rate(WCDMA->GSM)(%)", "op": ">=", "threshold": 0.95, "target_col": TARGET_COL_PS_3G_2G_HO},
    "PS_RADIO_CONG": {"table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE", "column": "U31_3G & 3G+ Radio Congestion Rate_901620_2_UROP.RNC-MO", "op": "<=", "threshold": 0.02, "target_col": TARGET_COL_PS_RADIO_CONG},
}
FILL_GREEN = PatternFill(start_color="FF006100", end_color="FF006100", fill_type="solid")
FILL_RED = PatternFill(start_color="FF9C0006", end_color="FF9C0006", fill_type="solid")
FILL_LIGHT_GREEN = PatternFill(start_color="FFD9EAD3", end_color="FFD9EAD3", fill_type="solid")
FONT_WHITE = Font(color="FFFFFFFF")
FONT_BLACK = Font(color="FF000000")

NETWORK_KPI_NEGATIVE_COLS = {TARGET_COL_2G_DCR, TARGET_COL_3G_DCR, TARGET_COL_3G_DCR_HSDPA}

NUR_COLS = list(range(TARGET_COL_NUR_NETWORK, TARGET_COL_NUR_4G + 1))
TTR_COLS = list(range(TARGET_COL_TTR, TARGET_COL_TTR_P4 + 1))
NETWORK_COLS = list(range(TARGET_COL_2G_CSSR, TARGET_COL_3G_2G_HO + 1))
PERSITE_COLS = list(range(TARGET_COL_PS_NUR_2G, TARGET_COL_PS_RADIO_CONG + 1))
def _safe_load_workbook(filepath, max_retries=3, **kwargs):
    """带重试的 load_workbook，处理文件被占用的情况"""
    for attempt in range(1, max_retries + 1):
        try:
            return load_workbook(str(filepath), **kwargs)
        except PermissionError:
            if attempt < max_retries:
                wait = attempt * 2
                logger.warning(f"文件被占用({attempt}/{max_retries})，等待{wait}s: {os.path.basename(str(filepath))}")
                time.sleep(wait)
            else:
                raise
    return load_workbook(str(filepath), **kwargs)
@contextmanager
def _safe_open_workbook(filepath, max_retries=3, **kwargs):
    """带重试和自动关闭的 load_workbook 上下文管理器"""
    wb = _safe_load_workbook(filepath, max_retries=max_retries, **kwargs)
    try:
        yield wb
    finally:
        try:
            wb.close()
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _safe_open_workbook: exception swallowed", exc_info=True)
            pass


def _safe_save_workbook(wb, filepath, max_retries=45):
    """原子落盘 workbook：先写临时文件再 os.replace（固定间隔重试），专治文件被占用(Permission denied)。
    重试耗尽后走 fallback 备用路径，数据不丢失，返回 fallback 路径或 None。
    """
    try:
        atomic_save_workbook(wb, filepath, max_retries=max_retries, base_wait=2.0)
        return None
    except AtomicReplaceFallback as e:
        logger.warning(f"文件被锁，数据已保存到备用路径: {e.fallback_path}")
        return e.fallback_path
def read_nur_daily(ws):
    """读取 KPI List NUR Daily sheet"""
    data = {}
    headers = []
    for col in range(1, ws.max_column + 1):
        val = ws.cell(row=1, column=col).value
        if val is not None:
            headers.append((col, str(val).strip()))
    date_cols = {}
    for col_idx, header in headers[1:]:
        try:
            dt = datetime.strptime(header, "%Y-%m-%d")
            date_cols[col_idx] = dt.strftime("%Y-%m-%d")
        except ValueError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] read_nur_daily: exception swallowed", exc_info=True)
            continue
    metric_map = {
        "Global_NUR_Daily": "NUR_NETWORK",
        "2G_NUR_Daily": "NUR_2G",
        "3G_NUR_Daily": "NUR_3G",
        "4G NUR Daily": "NUR_4G",
        "4G_NUR_Daily": "NUR_4G",
    }
    for row_idx in range(2, ws.max_row + 1):
        metric_name = ws.cell(row=row_idx, column=1).value
        if metric_name is None:
            continue
        metric_name = str(metric_name).strip()
        if metric_name not in metric_map:
            continue
        metric_key = metric_map[metric_name]
        for col_idx, date_str in date_cols.items():
            value = ws.cell(row=row_idx, column=col_idx).value
            if value is not None:
                if date_str not in data:
                    data[date_str] = {}
                data[date_str][metric_key] = value
    return data


def read_nur_monthly(ws):
    """读取 KPI List NUR Monthly sheet"""
    data = {}
    headers = []
    for col in range(1, ws.max_column + 1):
        val = ws.cell(row=1, column=col).value
        if val is not None:
            headers.append((col, str(val).strip()))
    month_cols = {}
    for col_idx, header in headers[1:]:
        if header and len(header) >= 7:
            month_cols[col_idx] = header[:7]
    metric_map = {
        "Global_NUR_Monthly": "NUR_NETWORK",
        "2G_NUR_Monthly": "NUR_2G",
        "3G_NUR_Monthly": "NUR_3G",
        "4G_NUR_Monthly": "NUR_4G",
    }
    for row_idx in range(2, ws.max_row + 1):
        metric_name = ws.cell(row=row_idx, column=1).value
        if metric_name is None:
            continue
        metric_name = str(metric_name).strip()
        if metric_name not in metric_map:
            continue
        metric_key = metric_map[metric_name]
        for col_idx, month_str in month_cols.items():
            value = ws.cell(row=row_idx, column=col_idx).value
            if value is not None:
                if month_str not in data:
                    data[month_str] = {}
                data[month_str][metric_key] = value
    return data


def read_sla_daily(ws):
    """读取 KPI List SLA Daily sheet"""
    data = {}
    date_cols = {}
    for col in range(2, ws.max_column + 1, 3):
        val = ws.cell(row=1, column=col).value
        if val is not None:
            val_str = str(val).strip()
            try:
                dt = datetime.strptime(val_str, "%Y-%m-%d")
                date_cols[col] = dt.strftime("%Y-%m-%d")
            except ValueError:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] read_sla_daily: exception swallowed", exc_info=True)
                continue
    severity_map = {"Global": "TTR", "P1": "TTR_P1", "P2": "TTR_P2", "P3": "TTR_P3", "P4": "TTR_P4"}
    for row_idx in range(3, ws.max_row + 1):
        severity = ws.cell(row=row_idx, column=1).value
        if severity is None:
            continue
        severity = str(severity).strip()
        if severity not in severity_map:
            continue
        metric_key = severity_map[severity]
        for date_col, date_str in date_cols.items():
            value = ws.cell(row=row_idx, column=date_col).value
            if value is not None:
                if date_str not in data:
                    data[date_str] = {}
                data[date_str][metric_key] = value
    return data


def read_sla_monthly(ws):
    """读取 KPI List SLA Monthly sheet"""
    data = {}
    month_cols = {}
    for col in range(2, ws.max_column + 1):
        val = ws.cell(row=1, column=col).value
        if val is not None:
            val_str = str(val).strip()
            if len(val_str) >= 7 and val_str[0].isdigit():
                month_cols[col] = val_str[:7]
    severity_map = {"Global": "TTR", "P1": "TTR_P1", "P2": "TTR_P2", "P3": "TTR_P3", "P4": "TTR_P4"}
    for row_idx in range(2, ws.max_row + 1):
        severity = ws.cell(row=row_idx, column=1).value
        if severity is None:
            continue
        severity = str(severity).strip()
        if severity not in severity_map:
            continue
        metric_key = severity_map[severity]
        for col_idx, month_str in month_cols.items():
            value = ws.cell(row=row_idx, column=col_idx + 2).value
            if value is not None:
                if month_str not in data:
                    data[month_str] = {}
                data[month_str][metric_key] = value
    return data


def get_db_value(conn, table_name, column_name, date_str):
    """从数据库获取指定日期/月份的值"""
    if table_name not in set(list_table_names(conn)):
        return None
    existing_cols = set(table_columns(conn, table_name))
    cursor = conn.cursor()
    safe_col = column_name.replace('"', '""')
    if safe_col not in existing_cols and column_name not in existing_cols:
        # PG 63 字节标识符截断回退（与 migrations/reconcile.py 同算法）：
        # 超长列名在 PG 侧为 UTF-8 前 63 字节截断形式，命中则改用截断名查询；
        # sqlite 模式列名原样存在，此回退天然不触发，行为不变。
        if len(column_name.encode("utf-8")) > 63:
            truncated = column_name.encode("utf-8")[:63].decode("utf-8", errors="ignore")
            if truncated in existing_cols:
                column_name = truncated
                safe_col = truncated.replace('"', '""')
        if safe_col not in existing_cols and column_name not in existing_cols:
            return None
    date_col_candidates = ["Date", "Begin Time", "date", "begin_time", "Month", "month"]
    date_col = None
    for candidate in date_col_candidates:
        if candidate in existing_cols:
            date_col = candidate
            break
    if date_col is None:
        return None
    safe_col_escaped = f'"{safe_col}"'
    date_col_escaped = f'"{date_col}"'

    def to_number(val):
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return val
        try:
            f = float(val)
            if f == int(f):
                return int(f)
            return f
        except (ValueError, TypeError):
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] to_number: exception swallowed", exc_info=True)
            return val

    try:
        query = f'SELECT {safe_col_escaped} FROM "{table_name}" WHERE {date_col_escaped} = ? LIMIT 1'
        cursor.execute(query, (date_str,))
        result = cursor.fetchone()
        if result:
            return to_number(result[0])
        query = f'SELECT {safe_col_escaped} FROM "{table_name}" WHERE {date_col_escaped} LIKE ? LIMIT 1'
        cursor.execute(query, (f"{date_str}%",))
        result = cursor.fetchone()
        if result:
            return to_number(result[0])
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_db_value: exception swallowed", exc_info=True)
        pass
    return None


def get_persite_ratio(conn, table_name, column_name, date_str, op, threshold):
    """计算满足阈值的站点占比"""
    if table_name not in set(list_table_names(conn)):
        return None
    existing_cols = set(table_columns(conn, table_name))
    cursor = conn.cursor()
    safe_col = column_name.replace('"', '""')
    if safe_col not in existing_cols and column_name not in existing_cols:
        # PG 63 字节标识符截断回退（与 get_db_value 同款）：
        # sqlite 模式列名原样存在，此回退天然不触发，行为不变。
        if len(column_name.encode("utf-8")) > 63:
            truncated = column_name.encode("utf-8")[:63].decode("utf-8", errors="ignore")
            if truncated in existing_cols:
                column_name = truncated
                safe_col = truncated.replace('"', '""')
        if safe_col not in existing_cols and column_name not in existing_cols:
            return None
    date_col = None
    for candidate in ["Begin Time", "Date", "date", "begin_time", "Month", "month"]:
        if candidate in existing_cols:
            date_col = candidate
            break
    if date_col is None:
        return None
    col_escaped = f'"{safe_col}"'
    date_escaped = f'"{date_col}"'
    try:
        query = f'SELECT CAST({col_escaped} AS REAL) FROM "{table_name}" WHERE {date_escaped} LIKE ? AND {col_escaped} IS NOT NULL'
        cursor.execute(query, (f"{date_str}%",))
        rows = cursor.fetchall()
        if not rows:
            return None
        total = len(rows)
        if op == ">=":
            compliant = sum(1 for r in rows if r[0] is not None and r[0] >= threshold)
        elif op == "<=":
            compliant = sum(1 for r in rows if r[0] is not None and r[0] <= threshold)
        else:
            return None
        return compliant / total if total > 0 else None
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_persite_ratio: exception swallowed", exc_info=True)
        return None
def read_sla_detail_daily(ws):
    """读取 KPI List SLA Daily sheet 全部3列值"""
    data = {}
    date_cols = {}
    for col in range(2, ws.max_column + 1, 3):
        val = ws.cell(row=1, column=col).value
        if val is not None:
            val_str = str(val).strip()
            try:
                dt = datetime.strptime(val_str, "%Y-%m-%d")
                date_cols[col] = dt.strftime("%Y-%m-%d")
            except ValueError:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] read_sla_detail_daily: exception swallowed", exc_info=True)
                continue
    severity_map = {"Global": "TTR", "P1": "TTR_P1", "P2": "TTR_P2", "P3": "TTR_P3", "P4": "TTR_P4"}
    for row_idx in range(3, ws.max_row + 1):
        severity = ws.cell(row=row_idx, column=1).value
        if severity is None:
            continue
        severity = str(severity).strip()
        if severity not in severity_map:
            continue
        metric_key = severity_map[severity]
        for date_col, date_str in date_cols.items():
            achieve = ws.cell(row=row_idx, column=date_col).value
            total = ws.cell(row=row_idx, column=date_col + 1).value
            within_sla = ws.cell(row=row_idx, column=date_col + 2).value
            if achieve is not None or total is not None or within_sla is not None:
                if date_str not in data:
                    data[date_str] = {}
                data[date_str][metric_key] = {"achieve": achieve, "total": total, "within_sla": within_sla}
    return data


def read_sla_detail_monthly(ws):
    """读取 KPI List SLA Monthly sheet 全部3列值"""
    data = {}
    month_cols = {}
    for col in range(2, ws.max_column + 1):
        val = ws.cell(row=1, column=col).value
        if val is not None:
            val_str = str(val).strip()
            if len(val_str) >= 7 and val_str[0].isdigit():
                month_cols[col] = val_str[:7]
    severity_map = {"Global": "TTR", "P1": "TTR_P1", "P2": "TTR_P2", "P3": "TTR_P3", "P4": "TTR_P4"}
    for row_idx in range(2, ws.max_row + 1):
        severity = ws.cell(row=row_idx, column=1).value
        if severity is None:
            continue
        severity = str(severity).strip()
        if severity not in severity_map:
            continue
        metric_key = severity_map[severity]
        for col_idx, month_str in month_cols.items():
            total = ws.cell(row=row_idx, column=col_idx).value
            within_sla = ws.cell(row=row_idx, column=col_idx + 1).value
            achieve = ws.cell(row=row_idx, column=col_idx + 2).value
            if achieve is not None or total is not None or within_sla is not None:
                if month_str not in data:
                    data[month_str] = {}
                data[month_str][metric_key] = {"achieve": achieve, "total": total, "within_sla": within_sla}
    return data
def update_wo_sla_report(kpi_list_file):
    """更新 WOs SLA achievement Report sheet"""
    logger.info("更新 WOs SLA achievement Report...")
    wb_kpi = load_workbook(kpi_list_file, data_only=True)
    try:
        sla_detail_daily = read_sla_detail_daily(wb_kpi["KPI List SLA Daily"])
        sla_detail_monthly = read_sla_detail_monthly(wb_kpi["KPI List SLA Monthly"])
    finally:
        wb_kpi.close()

    wb_target = _safe_load_workbook(TARGET_FILE)
    ws = wb_target[WO_SHEET]

    COL_MAP = {
        "TTR":    {"total": 2, "within_sla": 3, "achieve": 4},
        "TTR_P1": {"total": 5, "within_sla": 6, "achieve": 7},
        "TTR_P2": {"total": 8, "within_sla": 9, "achieve": 10},
        "TTR_P3": {"total": 11, "within_sla": 12, "achieve": 13},
        "TTR_P4": {"total": 14, "within_sla": 15, "achieve": 16},
    }

    month_row = None
    date_rows = []
    for row_idx in range(1, ws.max_row + 1):
        cell_val = ws.cell(row=row_idx, column=1).value
        if cell_val is not None:
            if str(cell_val).strip().lower() == "month":
                month_row = row_idx
            elif hasattr(cell_val, 'year'):
                date_rows.append(row_idx)
            elif isinstance(cell_val, str) and cell_val.startswith("20"):
                date_rows.append(row_idx)

    if month_row is None:
        logger.warning("WOs SLA: 未找到 Month 行")
        return

    current_month = datetime.now().strftime("%Y-%m")

    # 更新 Month 行
    monthly_data = sla_detail_monthly.get(current_month, {})
    for metric_key, cols in COL_MAP.items():
        detail = monthly_data.get(metric_key, {})
        ws.cell(row=month_row, column=cols["total"]).value = detail.get("total")
        ws.cell(row=month_row, column=cols["within_sla"]).value = detail.get("within_sla")
        ws.cell(row=month_row, column=cols["achieve"]).value = detail.get("achieve")

    # 更新每日数据行
    updated = 0
    for row_idx in date_rows:
        cell_date = ws.cell(row=row_idx, column=1).value
        if cell_date is None:
            continue
        if isinstance(cell_date, datetime):
            date_key = cell_date.strftime("%Y-%m-%d")
        elif isinstance(cell_date, date):
            date_key = cell_date.strftime("%Y-%m-%d")
        elif isinstance(cell_date, str):
            try:
                date_key = cell_date.strip()[:10]
                datetime.strptime(date_key, "%Y-%m-%d")
            except ValueError:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] update_wo_sla_report: exception swallowed", exc_info=True)
                continue
        else:
            continue
        daily_data = sla_detail_daily.get(date_key, {})
        for metric_key, cols in COL_MAP.items():
            detail = daily_data.get(metric_key, {})
            if detail.get("total") is not None or detail.get("within_sla") is not None or detail.get("achieve") is not None:
                ws.cell(row=row_idx, column=cols["total"]).value = detail.get("total")
                ws.cell(row=row_idx, column=cols["within_sla"]).value = detail.get("within_sla")
                ws.cell(row=row_idx, column=cols["achieve"]).value = detail.get("achieve")
            else:
                ws.cell(row=row_idx, column=cols["total"]).value = None
                ws.cell(row=row_idx, column=cols["within_sla"]).value = None
                ws.cell(row=row_idx, column=cols["achieve"]).value = None
        updated += 1

    # 清空今天日期的行
    today_str = datetime.now().strftime("%Y-%m-%d")
    for row_idx in date_rows:
        cell_date = ws.cell(row=row_idx, column=1).value
        if cell_date is None:
            continue
        if isinstance(cell_date, datetime):
            date_key = cell_date.strftime("%Y-%m-%d")
        elif isinstance(cell_date, date):
            date_key = cell_date.strftime("%Y-%m-%d")
        elif isinstance(cell_date, str):
            try:
                date_key = cell_date.strip()[:10]
                datetime.strptime(date_key, "%Y-%m-%d")
            except ValueError:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] update_wo_sla_report: exception swallowed", exc_info=True)
                continue
        else:
            continue
        if date_key == today_str:
            for metric_key, cols in COL_MAP.items():
                ws.cell(row=row_idx, column=cols["total"]).value = None
                ws.cell(row=row_idx, column=cols["within_sla"]).value = None
                ws.cell(row=row_idx, column=cols["achieve"]).value = None

    apply_wo_sla_formatting(ws)
    try:
        _safe_save_workbook(wb_target, TARGET_FILE)
    finally:
        wb_target.close()
    logger.info(f"  WOs SLA 更新完成: {updated} 行")
def apply_conditional_formatting(ws, month_row, date_rows):
    """对 Contract KPIs Report (New) 应用条件格式化"""
    target_row = None
    for row_idx in range(1, ws.max_row + 1):
        val = ws.cell(row=row_idx, column=1).value
        if val is not None and str(val).strip().lower() == "target":
            target_row = row_idx
            break
    if target_row is None:
        return

    targets = {}
    for col in NUR_COLS + TTR_COLS + NETWORK_COLS + PERSITE_COLS:
        tv = ws.cell(row=target_row, column=col).value
        if tv is not None:
            try:
                targets[col] = float(tv)
            except (ValueError, TypeError):
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] apply_conditional_formatting: exception swallowed", exc_info=True)
                pass

    data_rows = [month_row] + date_rows if month_row else date_rows
    for row_idx in data_rows:
        for col in NUR_COLS:
            cell = ws.cell(row=row_idx, column=col)
            val = cell.value
            if val is None:
                continue
            try:
                v = float(val)
            except (ValueError, TypeError):
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] apply_conditional_formatting: exception swallowed", exc_info=True)
                continue
            target = targets.get(col)
            if target is None:
                continue
            cell.fill = FILL_GREEN if v <= target else FILL_RED
            cell.font = FONT_WHITE

        for col in TTR_COLS:
            cell = ws.cell(row=row_idx, column=col)
            val = cell.value
            if val is None:
                continue
            try:
                v = float(val)
            except (ValueError, TypeError):
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] apply_conditional_formatting: exception swallowed", exc_info=True)
                continue
            target = targets.get(col)
            if target is None:
                continue
            cell.fill = FILL_GREEN if v >= target else FILL_RED
            cell.font = FONT_WHITE

        for col in NETWORK_COLS:
            cell = ws.cell(row=row_idx, column=col)
            val = cell.value
            if val is None:
                continue
            try:
                v = float(val)
            except (ValueError, TypeError):
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] apply_conditional_formatting: exception swallowed", exc_info=True)
                continue
            target = targets.get(col)
            if target is None:
                continue
            if col in NETWORK_KPI_NEGATIVE_COLS:
                cell.fill = FILL_GREEN if v <= target else FILL_RED
            else:
                cell.fill = FILL_GREEN if v >= target else FILL_RED
            cell.font = FONT_WHITE

        for col in PERSITE_COLS:
            cell = ws.cell(row=row_idx, column=col)
            val = cell.value
            if val is None:
                continue
            try:
                v = float(val)
            except (ValueError, TypeError):
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] apply_conditional_formatting: exception swallowed", exc_info=True)
                continue
            cell.fill = FILL_GREEN if v >= 0.9 else FILL_RED
            cell.font = FONT_WHITE


def apply_wo_sla_formatting(ws):
    """对 WOs SLA achievement Report 应用条件格式化"""
    sub_header_row = None
    for r in range(1, ws.max_row + 1):
        vals = [str(ws.cell(row=r, column=c).value).strip().lower()
                for c in range(1, min(ws.max_column + 1, 20))
                if ws.cell(row=r, column=c).value is not None]
        if "total" in vals and "achieve" in vals:
            sub_header_row = r
            break
    if sub_header_row is None or sub_header_row < 2:
        return

    target_row = sub_header_row - 1
    achieve_cols = []
    for c in range(1, ws.max_column + 1):
        val = ws.cell(row=sub_header_row, column=c).value
        if val is not None and str(val).strip().lower() == "achieve":
            achieve_cols.append(c)
    if not achieve_cols:
        return

    targets = {}
    for col in achieve_cols:
        target_col = ((col - 2) // 3) * 3 + 2
        tv = ws.cell(row=target_row, column=target_col).value
        if tv is not None:
            try:
                targets[col] = float(tv)
            except (ValueError, TypeError):
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] apply_wo_sla_formatting: exception swallowed", exc_info=True)
                targets[col] = 0.98
        else:
            targets[col] = 0.98

    data_rows = []
    for r in range(sub_header_row + 1, ws.max_row + 1):
        val = ws.cell(row=r, column=1).value
        if val is None:
            continue
        val_str = str(val).strip()
        if val_str.lower() == "month" or hasattr(val, 'year') or val_str.startswith("20"):
            data_rows.append(r)
    if not data_rows:
        return

    for row_idx in data_rows:
        for col in achieve_cols:
            total_col = col - 2
            within_sla_col = col - 1
            for c in (total_col, within_sla_col):
                if c < 1:
                    continue
                c_cell = ws.cell(row=row_idx, column=c)
                c_cell.fill = FILL_LIGHT_GREEN
                c_cell.font = FONT_BLACK
            cell = ws.cell(row=row_idx, column=col)
            val = cell.value
            if val is None:
                cell.fill = FILL_LIGHT_GREEN
                cell.font = FONT_BLACK
                continue
            try:
                v = float(val)
            except (ValueError, TypeError):
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] apply_wo_sla_formatting: exception swallowed", exc_info=True)
                continue
            target = targets.get(col, 0.98)
            cell.fill = FILL_GREEN if v >= target else FILL_RED
            cell.font = FONT_WHITE


def clean_sparse_date_rows(ws, month_row, date_rows):
    """清理稀疏日期行"""
    max_col = ws.max_column
    data_cols = list(range(2, max_col + 1))
    total_data_cols = len(data_cols)
    threshold = total_data_cols / 2
    for row_idx in date_rows:
        if row_idx == month_row:
            continue
        non_empty = sum(1 for col in data_cols if ws.cell(row=row_idx, column=col).value is not None)
        if total_data_cols - non_empty > threshold:
            for col in data_cols:
                ws.cell(row=row_idx, column=col).value = None
def export_without_sla_tt_details(kpi_list_file, upload_ftp=True):
    """从 KPI List 导出当月 WithoutSLATTDetails"""
    logger.info("导出 WithoutSLATTDetails...")
    sheet_name = "WithoutSLATTDetails"

    wb_src = None
    wb_new = None
    output_path = None
    try:
        try:
            wb_src = _safe_load_workbook(kpi_list_file)
        except Exception as e:
            logger.warning(f"无法打开 KPI List: {e}")
            return
        if sheet_name not in wb_src.sheetnames:
            logger.warning(f"未找到 sheet: {sheet_name}")
            return

        ws_src = wb_src[sheet_name]
        alarm_col = None
        for c in range(1, ws_src.max_column + 1):
            val = ws_src.cell(row=1, column=c).value
            if val is not None and "alarm occur time" in str(val).strip().lower():
                alarm_col = c
                break
        if alarm_col is None:
            return

        current_month = datetime.now().strftime("%Y-%m")
        rows_to_keep = [1]
        for r in range(2, ws_src.max_row + 1):
            cell_val = ws_src.cell(row=r, column=alarm_col).value
            if cell_val is None:
                continue
            if isinstance(cell_val, datetime):
                month_str = cell_val.strftime("%Y-%m")
            elif isinstance(cell_val, date):
                month_str = cell_val.strftime("%Y-%m")
            elif isinstance(cell_val, str):
                month_str = cell_val.strip()[:7]
            else:
                continue
            if month_str == current_month:
                rows_to_keep.append(r)

        wb_new = _safe_load_workbook(kpi_list_file)
        sheets_to_remove = [s for s in wb_new.sheetnames if s != sheet_name]
        for s in sheets_to_remove:
            del wb_new[s]
        ws_new = wb_new[sheet_name]

        all_rows = set(range(1, ws_src.max_row + 1))
        keep_set = set(rows_to_keep)
        rows_to_delete = sorted(all_rows - keep_set, reverse=True)
        for r in rows_to_delete:
            ws_new.delete_rows(r, 1)

        for c in range(1, ws_src.max_column + 1):
            col_letter = get_column_letter(c)
            if col_letter in ws_src.column_dimensions:
                ws_new.column_dimensions[col_letter].width = ws_src.column_dimensions[col_letter].width

        output_name = f"WithoutSLATTDetails_{current_month}.xlsx"
        output_path = DATA_DIR / output_name
        atomic_save_workbook(wb_new, output_path)
        logger.info(f"  保存: {output_name}")
    finally:
        if wb_new:
            try:
                wb_new.close()
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] export_without_sla_tt_details: exception swallowed", exc_info=True)
                pass
        if wb_src:
            try:
                wb_src.close()
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] export_without_sla_tt_details: exception swallowed", exc_info=True)
                pass

    if upload_ftp and output_path:
        upload_files_to_ftp([str(output_path)])
def cleanup_old_exports(local_dir, today_str, current_month=None):
    """清理本地和 FTP 上的旧导出文件"""
    if current_month is None:
        current_month = today_str[:7]
    import glob as _glob

    # 本地清理
    patterns = [
        ("ZTE OLR MS Contract KPIs Achievements Daily Report_*", today_str),
        ("ZTE OLR MS WOs SLA Achievements Daily Report_*", today_str),
        ("WithoutSLATTDetails_*", current_month),
    ]
    for pattern_glob, keep_str in patterns:
        for fpath in _glob.glob(os.path.join(str(local_dir), pattern_glob + ".*")):
            fname = os.path.basename(fpath)
            if keep_str in fname:
                continue
            try:
                os.remove(fpath)
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] cleanup_old_exports: exception swallowed", exc_info=True)
                pass

    # FTP 清理
    ftp = None
    try:
        ftp = FTP()
        ftp.connect(FTP_UP_HOST, FTP_UP_PORT, timeout=30)
        ftp.encoding = "utf-8"
        ftp.login(FTP_UP_USER, FTP_UP_PASS)
        dirs = FTP_UP_REMOTE_DIR.strip("/").split("/")
        current = ""
        for d in dirs:
            current += f"/{d}"
            try:
                ftp.cwd(current)
            except error_perm:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] cleanup_old_exports: exception swallowed", exc_info=True)
                ftp.mkd(current)
                ftp.cwd(current)
        items = []
        ftp.dir(items.append)
        ftp_prefixes = [
            ("ZTE OLR MS Contract KPIs Achievements Daily Report_", today_str),
            ("ZTE OLR MS WOs SLA Achievements Daily Report_", today_str),
            ("WithoutSLATTDetails_", current_month),
        ]
        for item in items:
            parts = item.split(None, 8)
            if len(parts) >= 9:
                name = parts[8]
                perms = parts[0]
                if perms.startswith('d'):
                    continue
                for prefix, keep_str in ftp_prefixes:
                    if name.startswith(prefix):
                        date_part = name.replace(prefix, "").split(".")[0][:10]
                        if date_part != keep_str:
                            try:
                                ftp.delete(name)
                            except Exception:
                                logging.getLogger(__name__).warning("[SILENT-EXCEPT] cleanup_old_exports: exception swallowed", exc_info=True)
                                pass
                        break
        ftp.quit()
    except Exception as e:
        logger.warning(f"FTP清理失败: {e}")
        if ftp:
            try:
                ftp.close()
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] cleanup_old_exports: exception swallowed", exc_info=True)
                pass
def export_sheet_to_xlsx(src_file, sheet_name, output_path):
    """从源 Excel 复制单个 sheet 到新文件"""
    for attempt in range(1, 4):
        try:
            shutil.copy2(str(src_file), str(output_path))
            break
        except PermissionError:
            if attempt < 3:
                time.sleep(attempt * 2)
            else:
                logger.warning(f"文件被占用，无法导出: {os.path.basename(str(output_path))}")
                return
    wb = None
    try:
        wb = load_workbook(str(output_path))
        sheets_to_remove = [s for s in wb.sheetnames if s != sheet_name]
        for s in sheets_to_remove:
            del wb[s]
        atomic_save_workbook(wb, output_path)
    finally:
        if wb:
            wb.close()
    logger.info(f"  导出 xlsx: {os.path.basename(str(output_path))}")


def get_cell_color_hex(cell):
    """获取单元格填充颜色的十六进制值"""
    try:
        fill = cell.fill
        if fill and fill.fgColor and fill.fgColor.rgb and fill.fgColor.rgb != '00000000':
            rgb = str(fill.fgColor.rgb)
            if len(rgb) == 8:
                return rgb[2:]
            elif len(rgb) == 6:
                return rgb
        return None
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_cell_color_hex: exception swallowed", exc_info=True)
        return None


def get_cell_font_info(cell):
    """获取单元格字体信息"""
    try:
        font = cell.font
        bold = font.bold if font else False
        color = None
        if font and font.color and font.color.rgb:
            rgb = str(font.color.rgb)
            if len(rgb) == 8:
                color = rgb[2:]
            elif len(rgb) == 6:
                color = rgb
        size = font.size if font and font.size else None
        return {"bold": bold, "color": color, "size": size}
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_cell_font_info: exception swallowed", exc_info=True)
        return {"bold": False, "color": None, "size": None}


def format_cell_value(val, is_percentage_col=None):
    """格式化单元格值用于 HTML/PNG 显示"""
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        if isinstance(val, bool):
            return str(val)
        if is_percentage_col is False:
            if val == 0:
                return "0"
            if isinstance(val, float) and val == int(val):
                return str(int(val))
            if abs(val) > 100:
                return f"{val:.2f}"
            if isinstance(val, float):
                return f"{val:.4f}"
            return str(val)
        if 0 < abs(val) <= 1:
            return f"{val*100:.2f}%"
        if val == 0:
            return "0"
        if isinstance(val, float) and val == int(val):
            return str(int(val))
        if abs(val) > 100:
            return f"{val:.2f}"
        if isinstance(val, float):
            return f"{val:.4f}"
        return str(val)
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, date):
        return val.strftime("%Y-%m-%d")
    return str(val)


def _detect_achieve_cols(ws):
    """检测 Achieve 列位置集合和子表头行号"""
    sub_header_row = None
    for r in range(1, ws.max_row + 1):
        vals = [str(ws.cell(row=r, column=c).value).strip().lower()
                for c in range(1, min(ws.max_column + 1, 20))
                if ws.cell(row=r, column=c).value is not None]
        if "total" in vals and "achieve" in vals:
            sub_header_row = r
            break
    if sub_header_row is None:
        return set(), None
    achieve_cols = set()
    for c in range(1, ws.max_column + 1):
        val = ws.cell(row=sub_header_row, column=c).value
        if val is not None and str(val).strip().lower() == "achieve":
            achieve_cols.add(c)
    return achieve_cols, sub_header_row


def export_sheet_to_html(src_file, sheet_name, output_path):
    """将 Excel 单个 sheet 导出为 HTML 表格"""
    try:
        with _safe_open_workbook(src_file, data_only=True) as wb:
            ws = wb[sheet_name]
            achieve_cols, sub_header_row = _detect_achieve_cols(ws)
            has_achieve_cols = len(achieve_cols) > 0
            merged_ranges = list(ws.merged_cells.ranges)
            merged_cells_set = set()
            merge_info = {}
            for mr in merged_ranges:
                start_r, start_c = mr.min_row, mr.min_col
                end_r, end_c = mr.max_row, mr.max_col
                rowspan = end_r - start_r + 1
                colspan = end_c - start_c + 1
                merge_info[(start_r, start_c)] = (rowspan, colspan)
                for r in range(start_r, end_r + 1):
                    for c in range(start_c, end_c + 1):
                        if r != start_r or c != start_c:
                            merged_cells_set.add((r, c))
            col_widths = {}
            for col_idx in range(1, ws.max_column + 1):
                col_letter = get_column_letter(col_idx)
                dim = ws.column_dimensions.get(col_letter)
                col_widths[col_idx] = dim.width if dim and dim.width else 12

            html_parts = ["<!DOCTYPE html>", "<html><head><meta charset='utf-8'>", "<style>",
                          "body { font-family: 'Calibri', 'Arial', sans-serif; font-size: 11px; margin: 10px; }",
                          "table { border-collapse: collapse; empty-cells: show; }",
                          "td, th { border: 1px solid #B0B0B0; padding: 3px 6px; text-align: center; vertical-align: middle; white-space: nowrap; }",
                          "</style>", "</head><body>", "<table>"]

            for row_idx in range(1, ws.max_row + 1):
                html_parts.append("<tr>")
                for col_idx in range(1, ws.max_column + 1):
                    if (row_idx, col_idx) in merged_cells_set:
                        continue
                    cell = ws.cell(row=row_idx, column=col_idx)
                    merge_attr = ""
                    if (row_idx, col_idx) in merge_info:
                        rowspan, colspan = merge_info[(row_idx, col_idx)]
                        if rowspan > 1:
                            merge_attr += f' rowspan="{rowspan}"'
                        if colspan > 1:
                            merge_attr += f' colspan="{colspan}"'
                    styles = []
                    bg = get_cell_color_hex(cell)
                    if bg:
                        styles.append(f"background-color: #{bg}")
                    font_info = get_cell_font_info(cell)
                    if font_info["bold"]:
                        styles.append("font-weight: bold")
                    if font_info["color"] and font_info["color"] != "000000":
                        styles.append(f"color: #{font_info['color']}")
                    if font_info["size"]:
                        styles.append(f"font-size: {font_info['size']}px")
                    if cell.alignment and cell.alignment.horizontal:
                        styles.append(f"text-align: {cell.alignment.horizontal}")
                    w = col_widths.get(col_idx, 12)
                    styles.append(f"min-width: {int(w * 7)}px")
                    style_attr = f' style={"; ".join(styles)}' if styles else ""
                    if has_achieve_cols and sub_header_row and row_idx >= sub_header_row:
                        is_pct = (col_idx in achieve_cols) if row_idx > sub_header_row else None
                    else:
                        is_pct = None
                    val = format_cell_value(cell.value, is_percentage_col=is_pct)
                    html_parts.append(f"<td{merge_attr}{style_attr}>{val}</td>")
                html_parts.append("</tr>")

            html_parts.append("</table>")
            html_parts.append("</body></html>")
            with open(str(output_path), "w", encoding="utf-8") as f:
                f.write("\n".join(html_parts))
    except PermissionError:
        logger.warning(f"文件被占用，无法导出HTML: {os.path.basename(str(output_path))}")
        return
    logger.info(f"  导出 html: {os.path.basename(str(output_path))}")


def _find_font(size=11):
    """查找可用的中文字体"""
    font_candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]
    for fp in font_candidates:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _find_font: exception swallowed", exc_info=True)
                continue
    try:
        return ImageFont.truetype("arial", size)
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _find_font: exception swallowed", exc_info=True)
        return ImageFont.load_default()


def export_sheet_to_png(src_file, sheet_name, output_path, max_col=None):
    """将 Excel 单个 sheet 导出为 PNG 图片

    Args:
        src_file: 源 Excel 文件路径
        sheet_name: sheet 名称
        output_path: 输出 PNG 路径
        max_col: 可选，限制导出的最大列数（仅导出 1 ~ max_col 列），默认导出全部列
    """
    if not HAS_PIL:
        logger.info(f"  PNG导出跳过 (Pillow未安装)")
        return
    try:
        with _safe_open_workbook(src_file, data_only=True) as wb:
            ws = wb[sheet_name]
            achieve_cols, sub_header_row = _detect_achieve_cols(ws)
            has_achieve_cols = len(achieve_cols) > 0
            max_row = ws.max_row
            if max_col is None:
                max_col = ws.max_column
            if max_row == 0 or max_col == 0:
                return

            font = _find_font(11)
            font_bold = _find_font(12)
            col_widths = {}
            for c in range(1, max_col + 1):
                cl = get_column_letter(c)
                dim = ws.column_dimensions.get(cl)
                w = dim.width if dim and dim.width else 12
                col_widths[c] = max(int(w * 7.5), 50)
            row_height = 22
            header_row_height = 28
            img_width = sum(col_widths[c] for c in range(1, max_col + 1)) + 2
            img_height = header_row_height + (max_row - 1) * row_height + 2
            img = Image.new("RGB", (img_width, img_height), "white")
            draw = ImageDraw.Draw(img)

            merged_map = {}
            skip_cells = set()
            for mr in ws.merged_cells.ranges:
                sr, sc = mr.min_row, mr.min_col
                er, ec = mr.max_row, mr.max_col
                merged_map[(sr, sc)] = (er - sr + 1, ec - sc + 1)
                for r in range(sr, er + 1):
                    for c in range(sc, ec + 1):
                        if r != sr or c != sc:
                            skip_cells.add((r, c))

            col_x = [0] * (max_col + 2)
            for c in range(1, max_col + 1):
                col_x[c] = col_x[c - 1] + col_widths.get(c, 80)
            col_x[max_col + 1] = img_width

            def row_y(r):
                if r == 1:
                    return 0
                return header_row_height + (r - 2) * row_height

            def cell_width(c, colspan=1):
                w = 0
                for i in range(colspan):
                    w += col_widths.get(c + i, 80)
                return w

            def cell_height(r, rowspan=1):
                h_base = header_row_height if r == 1 else row_height
                if rowspan == 1:
                    return h_base
                h = 0
                for i in range(rowspan):
                    rr = r + i
                    h += header_row_height if rr == 1 else row_height
                return h

            for r in range(1, max_row + 1):
                for c in range(1, max_col + 1):
                    if (r, c) in skip_cells:
                        continue
                    cell = ws.cell(row=r, column=c)
                    x0 = col_x[c - 1]
                    y0 = row_y(r)
                    rs, cs_span = 1, 1
                    if (r, c) in merged_map:
                        rs, cs_span = merged_map[(r, c)]
                    w = cell_width(c, cs_span)
                    h = cell_height(r, rs)
                    x1 = x0 + w
                    y1 = y0 + h
                    bg = get_cell_color_hex(cell)
                    fill_color = f"#{bg}" if bg else "white"
                    draw.rectangle([x0, y0, x1, y1], fill=fill_color, outline="#B0B0B0")
                    if has_achieve_cols and sub_header_row and r >= sub_header_row:
                        is_pct = (c in achieve_cols) if r > sub_header_row else None
                    else:
                        is_pct = None
                    val = format_cell_value(cell.value, is_percentage_col=is_pct)
                    if val:
                        font_info = get_cell_font_info(cell)
                        use_font = font_bold if font_info["bold"] else font
                        text_color = f"#{font_info['color']}" if font_info["color"] and font_info["color"] != "000000" else "black"
                        bbox = draw.textbbox((0, 0), val, font=use_font)
                        tw = bbox[2] - bbox[0]
                        th = bbox[3] - bbox[1]
                        tx = x0 + (w - tw) // 2
                        ty = y0 + (h - th) // 2
                        tx = max(tx, x0 + 2)
                        ty = max(ty, y0 + 1)
                        draw.text((tx, ty), val, fill=text_color, font=use_font)

            img.save(str(output_path), "PNG")
    except PermissionError:
        logger.warning(f"文件被占用，无法导出PNG: {os.path.basename(str(output_path))}")
        return
    logger.info(f"  导出 png: {os.path.basename(str(output_path))}")
def upload_files_to_ftp(file_paths):
    """上传文件列表到 FTP 服务器"""
    ftp = None
    try:
        ftp = FTP()
        ftp.connect(FTP_UP_HOST, FTP_UP_PORT, timeout=30)
        ftp.encoding = "utf-8"
        ftp.login(FTP_UP_USER, FTP_UP_PASS)
        dirs = FTP_UP_REMOTE_DIR.strip("/").split("/")
        current = ""
        for d in dirs:
            current += f"/{d}"
            try:
                ftp.cwd(current)
            except error_perm:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] upload_files_to_ftp: exception swallowed", exc_info=True)
                ftp.mkd(current)
                ftp.cwd(current)
        uploaded = 0
        for fpath in file_paths:
            fname = os.path.basename(fpath)
            try:
                with open(fpath, "rb") as f:
                    ftp.storbinary(f"STOR {fname}", f)
                uploaded += 1
            except Exception as e:
                logger.warning(f"  FTP上传失败 {fname}: {e}")
        ftp.quit()
        logger.info(f"  FTP上传完成: {uploaded}/{len(file_paths)}")
        return uploaded
    except Exception as e:
        logger.warning(f"  FTP连接失败: {e}")
        if ftp:
            try:
                ftp.close()
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] upload_files_to_ftp: exception swallowed", exc_info=True)
                pass
        return 0


def download_kpi_list_from_ftp(local_path):
    """从FTP下载最新 KPI List 文件"""
    logger.info("FTP下载 KPI List...")
    ftp = None
    try:
        ftp = FTP()
        ftp.connect(FTP_SRC_HOST, FTP_SRC_PORT, timeout=30)
        ftp.encoding = "utf-8"
        ftp.login(FTP_SRC_USER, FTP_SRC_PASS)
        ftp.cwd(FTP_SRC_BASE_DIR)

        date_dirs = []
        items = []
        ftp.dir(items.append)
        for item in items:
            parts = item.split(None, 8)
            if len(parts) >= 9:
                name = parts[8]
                perms = parts[0]
                if perms.startswith('d') and name not in ('.', '..'):
                    try:
                        dt = datetime.strptime(name, "%Y-%m-%d")
                        date_dirs.append((name, dt))
                    except ValueError:
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] download_kpi_list_from_ftp: exception swallowed", exc_info=True)
                        continue
        if not date_dirs:
            logger.warning("  未找到日期文件夹")
            return False

        date_dirs.sort(key=lambda x: x[1], reverse=True)
        latest_date = date_dirs[0][0]
        logger.info(f"  最新日期: {latest_date}")

        TARGET_FILENAME = "KPI list - Operation.xlsx"

        def find_xlsx(path, depth=0, found_any=None):
            if depth > 5:
                return None
            if found_any is None:
                found_any = []
            try:
                sub_items = []
                ftp.dir(path, sub_items.append)
                for si in sub_items:
                    sp = si.split(None, 8)
                    if len(sp) >= 9:
                        sn = sp[8]
                        sp_perms = sp[0]
                        if sp_perms.startswith('d') and sn not in ('.', '..'):
                            result = find_xlsx(f"{path}/{sn}", depth + 1, found_any)
                            if result and os.path.basename(result) == TARGET_FILENAME:
                                return result
                            if result and not found_any:
                                found_any.append(result)
                        elif not sp_perms.startswith('d') and sn.lower().endswith('.xlsx'):
                            full_path = f"{path}/{sn}"
                            if sn == TARGET_FILENAME:
                                return full_path
                            if not found_any:
                                found_any.append(full_path)
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] find_xlsx: exception swallowed", exc_info=True)
                pass
            return found_any[0] if found_any else None

        search_path = f"{FTP_SRC_BASE_DIR}/{latest_date}"
        remote_file = find_xlsx(search_path)
        if not remote_file:
            logger.warning(f"  在 {search_path} 下未找到xlsx文件")
            return False

        logger.info(f"  远程文件: {remote_file}")
        with open(str(local_path), 'wb') as f:
            ftp.retrbinary(f"RETR {remote_file}", f.write)
        file_size = os.path.getsize(str(local_path))
        logger.info(f"  下载完成: {file_size / 1024:.1f} KB")
        ftp.quit()
        return True
    except Exception as e:
        logger.warning(f"  FTP下载失败: {e}")
        if ftp:
            try:
                ftp.close()
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] download_kpi_list_from_ftp: exception swallowed", exc_info=True)
                pass
        return False
def _seed_template_files():
    """确保 TARGET_FILE 存在，自动创建最小模板（项目自包含）。"""
    if TARGET_FILE.exists():
        return True

    logger.info("模板文件不存在，创建最小模板...")
    wb = openpyxl.Workbook()

    ws1 = wb.active
    ws1.title = TARGET_SHEET
    ws1.cell(row=1, column=1, value="Month")
    ws1.cell(row=4, column=1, value="Date")
    today = datetime.now()
    for i in range(62):
        d = today - timedelta(days=i)
        ws1.cell(row=5 + i, column=1, value=d)
    for c in range(2, 29):
        ws1.cell(row=4, column=c, value=f"KPI {c}")

    ws2 = wb.create_sheet(title=WO_SHEET)
    ws2.cell(row=1, column=1, value="Month")
    for i in range(62):
        d = today - timedelta(days=i)
        ws2.cell(row=2 + i, column=1, value=d)

    atomic_save_workbook(wb, TARGET_FILE)
    wb.close()
    logger.info(f"最小模板已创建: {TARGET_FILE}")
    return True


def _seed_kpi_list_file():
    """确保 KPI List 文件存在（后续依赖 FTP 下载完整版）。"""
    if KPI_LIST_FILE.exists():
        return True

    logger.warning("KPI List 文件无法自举，需依赖 FTP 下载")
    return False
def _load_kpi_list_datasets():
    """读取 KPI List 工作簿的 4 个 sheet 数据集，返回 dict"""
    logger.info("[1] 读取 KPI List 数据...")
    wb_kpi = load_workbook(str(KPI_LIST_FILE), data_only=True)
    try:
        nur_daily_data = {}
        if "KPI List NUR Daily" in wb_kpi.sheetnames:
            nur_daily_data = read_nur_daily(wb_kpi["KPI List NUR Daily"])
            logger.info(f"  NUR Daily: {len(nur_daily_data)} 天")

        nur_monthly_data = {}
        if "KPI List NUR Monthly" in wb_kpi.sheetnames:
            nur_monthly_data = read_nur_monthly(wb_kpi["KPI List NUR Monthly"])
            logger.info(f"  NUR Monthly: {len(nur_monthly_data)} 月")

        sla_daily_data = {}
        if "KPI List SLA Daily" in wb_kpi.sheetnames:
            sla_daily_data = read_sla_daily(wb_kpi["KPI List SLA Daily"])
            logger.info(f"  SLA Daily: {len(sla_daily_data)} 天")

        sla_monthly_data = {}
        if "KPI List SLA Monthly" in wb_kpi.sheetnames:
            sla_monthly_data = read_sla_monthly(wb_kpi["KPI List SLA Monthly"])
            logger.info(f"  SLA Monthly: {len(sla_monthly_data)} 月")
    finally:
        wb_kpi.close()
    return {
        "nur_daily": nur_daily_data,
        "nur_monthly": nur_monthly_data,
        "sla_daily": sla_daily_data,
        "sla_monthly": sla_monthly_data,
    }


def _locate_report_rows(ws):
    """扫描目标 sheet 第 1 列，定位 Month 行与日期行，返回 (month_row, date_rows)"""
    month_row = None
    date_rows = []
    for row_idx in range(1, ws.max_row + 1):
        cell_val = ws.cell(row=row_idx, column=1).value
        if cell_val is not None:
            if str(cell_val).strip().lower() == "month":
                month_row = row_idx
            elif hasattr(cell_val, 'year'):
                date_rows.append(row_idx)
    return month_row, date_rows


def _update_month_row(ws, month_row, conn, nur_monthly, sla_monthly, current_month):
    """用月度 NUR/SLA 数据与数据库月度 KPI 更新 Month 行"""
    ws.cell(row=month_row, column=TARGET_COL_NUR_NETWORK).value = nur_monthly.get("NUR_NETWORK")
    ws.cell(row=month_row, column=TARGET_COL_NUR_2G).value = nur_monthly.get("NUR_2G")
    ws.cell(row=month_row, column=TARGET_COL_NUR_3G).value = nur_monthly.get("NUR_3G")
    ws.cell(row=month_row, column=TARGET_COL_NUR_4G).value = nur_monthly.get("NUR_4G")
    ws.cell(row=month_row, column=TARGET_COL_TTR).value = sla_monthly.get("TTR")
    ws.cell(row=month_row, column=TARGET_COL_TTR_P1).value = sla_monthly.get("TTR_P1")
    ws.cell(row=month_row, column=TARGET_COL_TTR_P2).value = sla_monthly.get("TTR_P2")
    ws.cell(row=month_row, column=TARGET_COL_TTR_P3).value = sla_monthly.get("TTR_P3")
    ws.cell(row=month_row, column=TARGET_COL_TTR_P4).value = sla_monthly.get("TTR_P4")

    for kpi_name, kpi_config in NETWORK_KPI_MONTHLY_MAP.items():
        value = get_db_value(conn, kpi_config["table"], kpi_config["column"], current_month)
        if value is not None:
            ws.cell(row=month_row, column=kpi_config["target_col"]).value = value

    for kpi_name, kpi_config in PERSITE_KPI_MONTHLY_MAP.items():
        value = get_persite_ratio(conn, kpi_config["table"], kpi_config["column"], current_month, kpi_config["op"], kpi_config["threshold"])
        if value is not None:
            ws.cell(row=month_row, column=kpi_config["target_col"]).value = value


def _row_date_key(cell_date):
    """将行首单元格值规范化为 YYYY-MM-DD 字符串，无法解析返回 None"""
    if cell_date is None:
        return None
    if isinstance(cell_date, (datetime, date)):
        return cell_date.strftime("%Y-%m-%d")
    if isinstance(cell_date, str):
        try:
            return datetime.strptime(cell_date, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _row_date_key: exception swallowed", exc_info=True)
            return None
    return None


def _update_daily_rows(ws, date_rows, conn, nur_daily_data, sla_daily_data):
    """逐行更新每日数据（NUR/SLA + 数据库日度 KPI），返回更新行数"""
    updated_daily = 0
    for row_idx in date_rows:
        date_key = _row_date_key(ws.cell(row=row_idx, column=1).value)
        if date_key is None:
            continue

        nur = nur_daily_data.get(date_key, {})
        if nur:
            ws.cell(row=row_idx, column=TARGET_COL_NUR_NETWORK).value = nur.get("NUR_NETWORK")
            ws.cell(row=row_idx, column=TARGET_COL_NUR_2G).value = nur.get("NUR_2G")
            ws.cell(row=row_idx, column=TARGET_COL_NUR_3G).value = nur.get("NUR_3G")
            ws.cell(row=row_idx, column=TARGET_COL_NUR_4G).value = nur.get("NUR_4G")

        sla = sla_daily_data.get(date_key, {})
        if sla:
            ws.cell(row=row_idx, column=TARGET_COL_TTR).value = sla.get("TTR")
            ws.cell(row=row_idx, column=TARGET_COL_TTR_P1).value = sla.get("TTR_P1")
            ws.cell(row=row_idx, column=TARGET_COL_TTR_P2).value = sla.get("TTR_P2")
            ws.cell(row=row_idx, column=TARGET_COL_TTR_P3).value = sla.get("TTR_P3")
            ws.cell(row=row_idx, column=TARGET_COL_TTR_P4).value = sla.get("TTR_P4")

        for kpi_name, kpi_config in NETWORK_KPI_DAILY_MAP.items():
            value = get_db_value(conn, kpi_config["table"], kpi_config["column"], date_key)
            if value is not None:
                ws.cell(row=row_idx, column=kpi_config["target_col"]).value = value

        for kpi_name, kpi_config in PERSITE_KPI_DAILY_MAP.items():
            value = get_persite_ratio(conn, kpi_config["table"], kpi_config["column"], date_key, kpi_config["op"], kpi_config["threshold"])
            if value is not None:
                ws.cell(row=row_idx, column=kpi_config["target_col"]).value = value

        updated_daily += 1
    return updated_daily


def _export_and_upload_reports(today_str, current_month):
    """导出 Contract KPIs / WOs SLA 报表（xlsx/html/png）并上传 FTP，返回导出文件数"""
    logger.info("[5] 导出并上传...")
    export_files = []

    # (名称前缀, sheet, 导出格式, png 的 max_col)
    export_specs = [
        ("ZTE OLR MS Contract KPIs Achievements Daily Report", TARGET_SHEET, True, TARGET_COL_TTR_P4),
        ("ZTE OLR MS WOs SLA Achievements Daily Report", WO_SHEET, True, None),
    ]
    for name_prefix, sheet, _with_png, png_max_col in export_specs:
        xlsx_path = DATA_DIR / f"{name_prefix}_{today_str}.xlsx"
        export_sheet_to_xlsx(TARGET_FILE, sheet, xlsx_path)
        export_files.append(str(xlsx_path))

        html_path = DATA_DIR / f"{name_prefix}_{today_str}.html"
        export_sheet_to_html(TARGET_FILE, sheet, html_path)
        export_files.append(str(html_path))

        png_path = DATA_DIR / f"{name_prefix}_{today_str}.png"
        if png_max_col is not None:
            export_sheet_to_png(TARGET_FILE, sheet, png_path, max_col=png_max_col)
        else:
            export_sheet_to_png(TARGET_FILE, sheet, png_path)
        if os.path.exists(str(png_path)):
            export_files.append(str(png_path))

    upload_files_to_ftp(export_files)
    cleanup_old_exports(DATA_DIR, today_str, current_month)
    return len(export_files)


def run_contract_kpis_report():
    """Contract KPIs 报表自动更新主流程（编排层）"""
    t_start = time.time()
    logger.info("Contract KPIs 报表更新开始")

    # 确保模板文件存在
    _seed_template_files()

    # 检查目标文件和数据库
    for fpath, fname in [(TARGET_FILE, "目标文件"), (DB_PATH, "数据库")]:
        if not os.path.exists(str(fpath)):
            msg = f"{fname}不存在: {fpath}"
            logger.error(msg)
            return {"success": False, "error": msg}

    # 0. 从FTP下载最新 KPI List
    ftp_ok = download_kpi_list_from_ftp(KPI_LIST_FILE)
    if not ftp_ok:
        logger.warning("  FTP下载失败，尝试使用本地文件...")
        _seed_kpi_list_file()
    if not os.path.exists(str(KPI_LIST_FILE)):
        msg = f"KPI List 文件不存在: {KPI_LIST_FILE}"
        logger.error(msg)
        return {"success": False, "error": msg}

    # 1. 读取 KPI List 数据集
    datasets = _load_kpi_list_datasets()

    # 2. 连接数据库
    logger.info("[2] 连接数据库...")
    with get_raw_connection(str(DB_PATH)) as conn:

        # 3. 更新目标文件
        logger.info("[3] 更新目标文件...")
        wb_target = _safe_load_workbook(TARGET_FILE)
        ws = wb_target[TARGET_SHEET]

        month_row, date_rows = _locate_report_rows(ws)
        if month_row is None:
            wb_target.close()
            conn.close()
            return {"success": False, "error": "未找到 Month 行"}

        current_month = datetime.now().strftime("%Y-%m")
        nur_monthly = datasets["nur_monthly"].get(current_month, {})
        sla_monthly = datasets["sla_monthly"].get(current_month, {})

        # 更新 Month 行与每日数据行
        _update_month_row(ws, month_row, conn, nur_monthly, sla_monthly, current_month)
        updated_daily = _update_daily_rows(ws, date_rows, conn, datasets["nur_daily"], datasets["sla_daily"])

        clean_sparse_date_rows(ws, month_row, date_rows)
        apply_conditional_formatting(ws, month_row, date_rows)
        try:
            _safe_save_workbook(wb_target, TARGET_FILE)
        finally:
            wb_target.close()
        conn.close()
        logger.info(f"  Contract KPIs Report 更新: 日度 {updated_daily} 行, 月度 1 行")

        # 4. 更新 WOs SLA achievement Report
        update_wo_sla_report(str(KPI_LIST_FILE))

        # 4b. 导出 WithoutSLATTDetails
        export_without_sla_tt_details(str(KPI_LIST_FILE))

        # 5. 导出并上传
        today_str = datetime.now().strftime("%Y-%m-%d")
        exported_count = _export_and_upload_reports(today_str, current_month)

        # 6. 写看板库（附加功能：失败仅记录，不影响报表/邮件主流程）
        dashboard_result = {}
        try:
            from backend.services.ms_sla_dashboard import write_dashboard_data
            dashboard_result = write_dashboard_data(datasets)
        except Exception as e:
            logger.warning(f"[SILENT-EXCEPT] write_dashboard_data: exception swallowed: {e}", exc_info=True)
            dashboard_result = {"success": False, "error": f"看板写库失败: {e}"}

        elapsed = time.time() - t_start
        logger.info(f"Contract KPIs 报表更新完成: {elapsed:.1f}s")
        return {
            "success": True,
            "daily_rows_updated": updated_daily,
            "exported_files": exported_count,
            "dashboard_rows": dashboard_result.get("rows", 0),
            "dashboard_error": dashboard_result.get("error"),
            "elapsed_seconds": round(elapsed, 2),
        }

# -*- coding: utf-8 -*-
"""
Contract KPIs Report 自动更新脚本
功能：
  1. 从 KPI list - Operation.xlsx 读取 NUR/TTR 日度和月度数据
  2. 从 lbr_ms_sla_kpi.sqlite3 读取 Network KPIs 数据
  3. 更新 ZTE OLR MS Contract KPIs & WOs Achievement Auto-Reports.xlsx
     的 "Contract KPIs Report (New)" sheet

数据结构说明：
  - KPI List NUR Daily/Monthly: 日期/月份是列，指标是行 (转置结构)
  - KPI List SLA Daily: 每个日期占3列 (SLA, Total, Achievement)
  - KPI List SLA Monthly: 月份是列，Ticket Severity是行
"""

import os
import sys
import copy
import sqlite3
from datetime import datetime, date
from ftplib import FTP, error_perm
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import PatternFill, Font
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============================================================
# 配置
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 文件路径 (KPI List 在同目录下)
TARGET_FILE = os.path.join(
    SCRIPT_DIR,
    "ZTE OLR MS Contract KPIs & WOs Achievement Auto-Reports.xlsx"
)
KPI_LIST_FILE = os.path.join(SCRIPT_DIR, "KPI list - Operation.xlsx")
DB_PATH = os.path.join(SCRIPT_DIR, "lbr_ms_sla_kpi.sqlite3")

# FTP 下载配置
FTP_SRC_HOST = "192.168.100.19"
FTP_SRC_PORT = 21
FTP_SRC_USER = "FINEBI"
FTP_SRC_PASS = "DX"
FTP_SRC_BASE_DIR = "/webroot/WEB-INF/schedule/NUR_SLA"

# FTP 上传配置
FTP_UP_HOST = "192.168.100.19"
FTP_UP_PORT = 21
FTP_UP_USER = "ZTEEMS"
FTP_UP_PASS = "DX"
FTP_UP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/MS_SLA"

# Sheet 名称
TARGET_SHEET = "Contract KPIs Report (New)"
WO_SHEET = "WOs SLA achievement Report"

# ============================================================
# 目标文件列映射 (Row 4 是表头, Row 6+ 是数据)
# ============================================================
# Operation KPIs 列 (B-J)
TARGET_COL_NUR_NETWORK = 2    # B: NUR Network (n)
TARGET_COL_NUR_2G = 3         # C: NUR 2G (n)
TARGET_COL_NUR_3G = 4         # D: NUR 3G (n)
TARGET_COL_NUR_4G = 5         # E: NUR 4G (n)
TARGET_COL_TTR = 6            # F: TTR (%)
TARGET_COL_TTR_P1 = 7         # G: TTR_P1_4h (%)
TARGET_COL_TTR_P2 = 8         # H: TTR_P2_8h (%)
TARGET_COL_TTR_P3 = 9         # I: TTR_P3_16h (%)
TARGET_COL_TTR_P4 = 10        # J: TTR_P4_2Days (%)

# Network KPIs 列 (K-Q)
TARGET_COL_2G_CSSR = 11       # K: 2G CSSR voice (%)
TARGET_COL_2G_DCR = 12        # L: 2G DCR (%)
TARGET_COL_3G_CSSR = 13       # M: 3G CSSR (%)
TARGET_COL_3G_DCR = 14        # N: 3G DCR (%)
TARGET_COL_3G_CSSR_HSDPA = 15 # O: 3G CSSR HSDPA (%)
TARGET_COL_3G_DCR_HSDPA = 16  # P: 3G DCR HSDPA (%)
TARGET_COL_3G_2G_HO = 17      # Q: 3G to 2G Handover Success Rate (%)

# PerSite KPIs 列 (R-AB)
TARGET_COL_PS_NUR_2G = 18       # R: NUR (2G)
TARGET_COL_PS_DCR_2G = 19       # S: DCR 2G (%)
TARGET_COL_PS_CSSR_2G = 20      # T: 2G CSSR voice (%)
TARGET_COL_PS_TCH_BLK = 21      # U: 2G TCH Blocking at BH (%)
TARGET_COL_PS_NUR_3G = 22       # V: NUR (3G)
TARGET_COL_PS_CSSR_3G = 23      # W: 3G CSSR (%)
TARGET_COL_PS_DCR_3G = 24       # X: 3G DCR (%)
TARGET_COL_PS_CSSR_HSDPA = 25   # Y: 3G CSSR HSDPA (%)
TARGET_COL_PS_DCR_HSDPA = 26    # Z: 3G DCR HSDPA (%)
TARGET_COL_PS_3G_2G_HO = 27     # AA: 3G to 2G Handover Success Rate (%)
TARGET_COL_PS_RADIO_CONG = 28   # AB: 3G/3G+ Radio congestion at BH(%)

# 数据行自动检测（不硬编码）

# ============================================================
# Network KPIs 数据库映射
# ============================================================
NETWORK_KPI_DAILY_MAP = {
    "2G_CSSR": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_NW",
        "column": "OCI_2G_CSSR_CS(%)",
        "target_col": TARGET_COL_2G_CSSR
    },
    "2G_DCR": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_NW",
        "column": "TCH in call drop rate(include handover)(%)",
        "target_col": TARGET_COL_2G_DCR
    },
    "3G_CSSR": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_NW",
        "column": "U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO",
        "target_col": TARGET_COL_3G_CSSR
    },
    "3G_DCR": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_NW",
        "column": "Ratio of CS Call Drop(%)",
        "target_col": TARGET_COL_3G_DCR
    },
    "3G_CSSR_HSDPA": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_NW",
        "column": "U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO",
        "target_col": TARGET_COL_3G_CSSR_HSDPA
    },
    "3G_DCR_HSDPA": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_NW",
        "column": "U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO",
        "target_col": TARGET_COL_3G_DCR_HSDPA
    },
    "3G_2G_HO": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_NW",
        "column": "Cell Inter-RAT CS Outgoing Handover Success Rate(WCDMA->GSM)(%)",
        "target_col": TARGET_COL_3G_2G_HO
    }
}

NETWORK_KPI_MONTHLY_MAP = {
    "2G_CSSR": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_NW",
        "column": "OCI_2G_CSSR_CS(%)",
        "target_col": TARGET_COL_2G_CSSR
    },
    "2G_DCR": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_NW",
        "column": "TCH in call drop rate(include handover)(%)",
        "target_col": TARGET_COL_2G_DCR
    },
    "3G_CSSR": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_NW",
        "column": "U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO",
        "target_col": TARGET_COL_3G_CSSR
    },
    "3G_DCR": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_NW",
        "column": "Ratio of CS Call Drop(%)",
        "target_col": TARGET_COL_3G_DCR
    },
    "3G_CSSR_HSDPA": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_NW",
        "column": "U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO",
        "target_col": TARGET_COL_3G_CSSR_HSDPA
    },
    "3G_DCR_HSDPA": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_NW",
        "column": "U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO",
        "target_col": TARGET_COL_3G_DCR_HSDPA
    },
    "3G_2G_HO": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_NW",
        "column": "Cell Inter-RAT CS Outgoing Handover Success Rate(WCDMA->GSM)(%)",
        "target_col": TARGET_COL_3G_2G_HO
    }
}

# ============================================================
# PerSite KPIs 配置
# 计算满足阈值的站点个数 / 总站点个数
# ============================================================
PERSITE_KPI_DAILY_MAP = {
    "PS_NUR_2G": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_SITE",
        "column": "TCH in service rate(%)",
        "op": ">=", "threshold": 0.9965,
        "target_col": TARGET_COL_PS_NUR_2G
    },
    "PS_DCR_2G": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_SITE",
        "column": "TCH in call drop rate(include handover)(%)",
        "op": "<=", "threshold": 0.02,
        "target_col": TARGET_COL_PS_DCR_2G
    },
    "PS_CSSR_2G": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_SITE",
        "column": "OCI_2G_CSSR_CS(%)",
        "op": ">=", "threshold": 0.97,
        "target_col": TARGET_COL_PS_CSSR_2G
    },
    "PS_TCH_BLK": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_SITE",
        "column": "TCH in congestion rate(include handover)(%)",
        "op": "<=", "threshold": 0.02,
        "target_col": TARGET_COL_PS_TCH_BLK
    },
    "PS_NUR_3G": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE",
        "column": "Cell Validity Rate(%)",
        "op": ">=", "threshold": 0.9965,
        "target_col": TARGET_COL_PS_NUR_3G
    },
    "PS_CSSR_3G": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE",
        "column": "U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO",
        "op": ">=", "threshold": 0.97,
        "target_col": TARGET_COL_PS_CSSR_3G
    },
    "PS_DCR_3G": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE",
        "column": "Ratio of CS Call Drop(%)",
        "op": "<=", "threshold": 0.02,
        "target_col": TARGET_COL_PS_DCR_3G
    },
    "PS_CSSR_HSDPA": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE",
        "column": "U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO",
        "op": ">=", "threshold": 0.98,
        "target_col": TARGET_COL_PS_CSSR_HSDPA
    },
    "PS_DCR_HSDPA": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE",
        "column": "U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO",
        "op": "<=", "threshold": 0.02,
        "target_col": TARGET_COL_PS_DCR_HSDPA
    },
    "PS_3G_2G_HO": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE",
        "column": "Cell Inter-RAT CS Outgoing Handover Success Rate(WCDMA->GSM)(%)",
        "op": ">=", "threshold": 0.95,
        "target_col": TARGET_COL_PS_3G_2G_HO
    },
    "PS_RADIO_CONG": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE",
        "column": "U31_3G & 3G+ Radio Congestion Rate_901620_2_UROP.RNC-MO",
        "op": "<=", "threshold": 0.02,
        "target_col": TARGET_COL_PS_RADIO_CONG
    }
}

PERSITE_KPI_MONTHLY_MAP = {
    "PS_NUR_2G": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_SITE",
        "column": "TCH in service rate(%)",
        "op": ">=", "threshold": 0.9965,
        "target_col": TARGET_COL_PS_NUR_2G
    },
    "PS_DCR_2G": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_SITE",
        "column": "TCH in call drop rate(include handover)(%)",
        "op": "<=", "threshold": 0.02,
        "target_col": TARGET_COL_PS_DCR_2G
    },
    "PS_CSSR_2G": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_SITE",
        "column": "OCI_2G_CSSR_CS(%)",
        "op": ">=", "threshold": 0.97,
        "target_col": TARGET_COL_PS_CSSR_2G
    },
    "PS_TCH_BLK": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_SITE",
        "column": "TCH in congestion rate(include handover)(%)",
        "op": "<=", "threshold": 0.02,
        "target_col": TARGET_COL_PS_TCH_BLK
    },
    "PS_NUR_3G": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE",
        "column": "Cell Validity Rate(%)",
        "op": ">=", "threshold": 0.9965,
        "target_col": TARGET_COL_PS_NUR_3G
    },
    "PS_CSSR_3G": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE",
        "column": "U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO",
        "op": ">=", "threshold": 0.97,
        "target_col": TARGET_COL_PS_CSSR_3G
    },
    "PS_DCR_3G": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE",
        "column": "Ratio of CS Call Drop(%)",
        "op": "<=", "threshold": 0.02,
        "target_col": TARGET_COL_PS_DCR_3G
    },
    "PS_CSSR_HSDPA": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE",
        "column": "U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO",
        "op": ">=", "threshold": 0.98,
        "target_col": TARGET_COL_PS_CSSR_HSDPA
    },
    "PS_DCR_HSDPA": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE",
        "column": "U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO",
        "op": "<=", "threshold": 0.02,
        "target_col": TARGET_COL_PS_DCR_HSDPA
    },
    "PS_3G_2G_HO": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE",
        "column": "Cell Inter-RAT CS Outgoing Handover Success Rate(WCDMA->GSM)(%)",
        "op": ">=", "threshold": 0.95,
        "target_col": TARGET_COL_PS_3G_2G_HO
    },
    "PS_RADIO_CONG": {
        "table": "Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE",
        "column": "U31_3G & 3G+ Radio Congestion Rate_901620_2_UROP.RNC-MO",
        "op": "<=", "threshold": 0.02,
        "target_col": TARGET_COL_PS_RADIO_CONG
    }
}


def get_persite_ratio(conn, table_name, column_name, date_str, op, threshold):
    """
    计算满足阈值的站点占比。
    返回: float (0~1之间的比值) 或 None
    """
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    if not cursor.fetchone():
        return None

    cursor.execute(f'PRAGMA table_info("{table_name}")')
    existing_cols = {row[1] for row in cursor.fetchall()}

    safe_col = column_name.replace('"', '""')
    if safe_col not in existing_cols and column_name not in existing_cols:
        return None

    # 查找日期列
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
        # 查询该日期所有站点的KPI值
        query = (
            f'SELECT CAST({col_escaped} AS REAL) FROM "{table_name}" '
            f'WHERE {date_escaped} LIKE ? AND {col_escaped} IS NOT NULL'
        )
        cursor.execute(query, (f"{date_str}%",))
        rows = cursor.fetchall()

        if not rows:
            return None

        total = len(rows)
        # 统计满足阈值的站点数
        if op == ">=":
            compliant = sum(1 for r in rows if r[0] is not None and r[0] >= threshold)
        elif op == "<=":
            compliant = sum(1 for r in rows if r[0] is not None and r[0] <= threshold)
        else:
            return None

        return compliant / total if total > 0 else None

    except Exception:
        return None


def read_nur_daily(ws):
    """
    读取 KPI List NUR Daily sheet
    结构: Row1=表头(Date列+日期列), Row2-5=指标行
    - Col1: 指标名 (Global_NUR_Daily, 2G_NUR_Daily, 3G_NUR_Daily, 4G NUR Daily)
    - Col2+: 日期列 (最新日期在前)
    返回: {date_str: {metric: value}}
    """
    data = {}
    
    # 读取表头获取日期列位置
    headers = []
    for col in range(1, ws.max_column + 1):
        val = ws.cell(row=1, column=col).value
        if val is not None:
            headers.append((col, str(val).strip()))
    
    # 解析日期列 (Col 2+)
    date_cols = {}  # {col_idx: date_str}
    for col_idx, header in headers[1:]:  # 跳过第一列
        try:
            # 尝试解析日期格式 "2026-07-02"
            dt = datetime.strptime(header, "%Y-%m-%d")
            date_cols[col_idx] = dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    # 读取指标行 (Row 2-5)
    metric_map = {
        "Global_NUR_Daily": "NUR_NETWORK",
        "2G_NUR_Daily": "NUR_2G",
        "3G_NUR_Daily": "NUR_3G",
        "4G NUR Daily": "NUR_4G",  # 注意: 实际是 "4G NUR Daily" 不是 "4G_NUR_Daily"
        "4G_NUR_Daily": "NUR_4G"   # 兼容两种格式
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
    """
    读取 KPI List NUR Monthly sheet
    结构: Row1=表头(Month列+月份列), Row2-5=指标行
    返回: {month_str: {metric: value}}
    """
    data = {}
    
    headers = []
    for col in range(1, ws.max_column + 1):
        val = ws.cell(row=1, column=col).value
        if val is not None:
            headers.append((col, str(val).strip()))
    
    # 解析月份列
    month_cols = {}
    for col_idx, header in headers[1:]:
        if header and len(header) >= 7:  # "2026-07"
            month_cols[col_idx] = header[:7]
    
    metric_map = {
        "Global_NUR_Monthly": "NUR_NETWORK",
        "2G_NUR_Monthly": "NUR_2G",
        "3G_NUR_Monthly": "NUR_3G",
        "4G_NUR_Monthly": "NUR_4G"
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
    """
    读取 KPI List SLA Daily sheet
    结构: 
    - Row1: Date_YYYY-MM-DD, 日期(每3列一个日期)
    - Row2: Ticket Severity, SLA, Total, Achievement (重复)
    - Row3+: Global, P1, P2, P3, P4 数据
    每个日期占3列: SLA, Total, Achievement
    返回: {date_str: {severity: sla_value}}
    注意：取SLA列（百分比值），不是Achievement列
    """
    data = {}
    
    # 读取第一行获取日期位置
    # 日期出现在 Col 2, 5, 8, 11, ... (每3列)
    date_cols = {}  # {col_idx: date_str}
    for col in range(2, ws.max_column + 1, 3):
        val = ws.cell(row=1, column=col).value
        if val is not None:
            val_str = str(val).strip()
            try:
                dt = datetime.strptime(val_str, "%Y-%m-%d")
                date_cols[col] = dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
    
    # 读取指标行 (Row 3+)
    severity_map = {
        "Global": "TTR",
        "P1": "TTR_P1",
        "P2": "TTR_P2",
        "P3": "TTR_P3",
        "P4": "TTR_P4"
    }
    
    for row_idx in range(3, ws.max_row + 1):
        severity = ws.cell(row=row_idx, column=1).value
        if severity is None:
            continue
        
        severity = str(severity).strip()
        if severity not in severity_map:
            continue
        
        metric_key = severity_map[severity]
        
        # SLA 列在日期列同一位置 (date_col + 0)
        for date_col, date_str in date_cols.items():
            value = ws.cell(row=row_idx, column=date_col).value
            if value is not None:
                if date_str not in data:
                    data[date_str] = {}
                data[date_str][metric_key] = value
    
    return data


def read_sla_monthly(ws):
    """
    读取 KPI List SLA Monthly sheet
    结构:
    - Row1: Month, 月份列(每3列一个月)
    - Row2: Ticket Severity, Total, Within SLA, Achieve (重复)
    - Row3+: Global, P1, P2, P3, P4 数据
    返回: {month_str: {severity: achieve_value}}
    """
    data = {}
    
    # 解析 Row 1 找月份列
    month_cols = {}  # {col_idx: month_str}
    for col in range(2, ws.max_column + 1):
        val = ws.cell(row=1, column=col).value
        if val is not None:
            val_str = str(val).strip()
            if len(val_str) >= 7 and val_str[0].isdigit():
                month_cols[col] = val_str[:7]
    
    severity_map = {
        "Global": "TTR",
        "P1": "TTR_P1",
        "P2": "TTR_P2",
        "P3": "TTR_P3",
        "P4": "TTR_P4"
    }
    
    for row_idx in range(2, ws.max_row + 1):
        severity = ws.cell(row=row_idx, column=1).value
        if severity is None:
            continue
        
        severity = str(severity).strip()
        if severity not in severity_map:
            continue
        
        metric_key = severity_map[severity]
        
        # Achieve 在 col+2 (Monthly: Total(col), Within SLA(col+1), Achieve(col+2))
        for col_idx, month_str in month_cols.items():
            value = ws.cell(row=row_idx, column=col_idx + 2).value
            if value is not None:
                if month_str not in data:
                    data[month_str] = {}
                data[month_str][metric_key] = value
    
    return data


def get_db_value(conn, table_name, column_name, date_str):
    """
    从数据库获取指定日期/月份的值。
    数据库列类型为TEXT，返回值会尝试转为数字(float)。
    """
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    if not cursor.fetchone():
        return None
    
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    existing_cols = {row[1] for row in cursor.fetchall()}
    
    safe_col = column_name.replace('"', '""')
    if safe_col not in existing_cols and column_name not in existing_cols:
        return None
    
    # 尝试不同的日期列名
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
        """尝试将文本值转为数字，失败则返回原值"""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return val
        try:
            # 尝试转float
            f = float(val)
            # 如果是整数则返回int
            if f == int(f):
                return int(f)
            return f
        except (ValueError, TypeError):
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
        pass
    
    return None


# ============================================================
# WOs SLA achievement Report 相关函数
# ============================================================

def read_sla_detail_daily(ws):
    """
    读取 KPI List SLA Daily sheet，返回全部3列值。
    Daily列顺序: Achieve(col), Total(col+1), Within SLA(col+2)
    返回: {date_str: {severity: {"achieve": v, "total": v, "within_sla": v}}}
    """
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
                data[date_str][metric_key] = {
                    "achieve": achieve,
                    "total": total,
                    "within_sla": within_sla
                }
    return data


def read_sla_detail_monthly(ws):
    """
    读取 KPI List SLA Monthly sheet，返回全部3列值。
    Monthly列顺序: Total(col), Within SLA(col+1), Achieve(col+2)
    返回: {month_str: {severity: {"achieve": v, "total": v, "within_sla": v}}}
    """
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
                data[month_str][metric_key] = {
                    "achieve": achieve,
                    "total": total,
                    "within_sla": within_sla
                }
    return data


def update_wo_sla_report(kpi_list_file):
    """
    更新 WOs SLA achievement Report sheet。
    从 KPI List SLA Daily/Monthly 读取 Total/Within SLA/Achieve 写入目标。
    """
    print("\n[5] 更新 WOs SLA achievement Report...")

    wb_kpi = load_workbook(kpi_list_file, data_only=True)

    # 读取详细 SLA 数据
    sla_detail_daily = read_sla_detail_daily(wb_kpi["KPI List SLA Daily"])
    sla_detail_monthly = read_sla_detail_monthly(wb_kpi["KPI List SLA Monthly"])
    wb_kpi.close()

    # 目标文件
    wb_target = load_workbook(TARGET_FILE)
    ws = wb_target["WOs SLA achievement Report"]

    # 列映射: TTR=C2-4, TTR_P1=C5-7, TTR_P2=C8-10, TTR_P3=C11-13, TTR_P4=C14-16
    COL_MAP = {
        "TTR":    {"total": 2, "within_sla": 3, "achieve": 4},
        "TTR_P1": {"total": 5, "within_sla": 6, "achieve": 7},
        "TTR_P2": {"total": 8, "within_sla": 9, "achieve": 10},
        "TTR_P3": {"total": 11, "within_sla": 12, "achieve": 13},
        "TTR_P4": {"total": 14, "within_sla": 15, "achieve": 16},
    }

    # 检测 Month 行和日期行
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
        print("  [WARN] 未找到 Month 行")
        return

    current_month = datetime.now().strftime("%Y-%m")
    print(f"  Month 行: Row {month_row}")
    print(f"  日期行: {len(date_rows)} 行")

    # ---- 更新 Month 行 ----
    monthly_data = sla_detail_monthly.get(current_month, {})
    for metric_key, cols in COL_MAP.items():
        detail = monthly_data.get(metric_key, {})
        ws.cell(row=month_row, column=cols["total"]).value = detail.get("total")
        ws.cell(row=month_row, column=cols["within_sla"]).value = detail.get("within_sla")
        ws.cell(row=month_row, column=cols["achieve"]).value = detail.get("achieve")

    # ---- 更新每日数据行 ----
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
                continue
        else:
            continue

        daily_data = sla_detail_daily.get(date_key, {})
        
        # 无论是否有数据，都尝试更新（有数据则写入，无数据则清空）
        for metric_key, cols in COL_MAP.items():
            detail = daily_data.get(metric_key, {})
            # 如果有数据则写入，否则清空单元格
            if detail.get("total") is not None or detail.get("within_sla") is not None or detail.get("achieve") is not None:
                ws.cell(row=row_idx, column=cols["total"]).value = detail.get("total")
                ws.cell(row=row_idx, column=cols["within_sla"]).value = detail.get("within_sla")
                ws.cell(row=row_idx, column=cols["achieve"]).value = detail.get("achieve")
            else:
                # 没有数据时清空单元格，让后续格式化函数填充浅绿色
                ws.cell(row=row_idx, column=cols["total"]).value = None
                ws.cell(row=row_idx, column=cols["within_sla"]).value = None
                ws.cell(row=row_idx, column=cols["achieve"]).value = None

        updated += 1

    # ---- 清空今天日期的行 ----
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
                continue
        else:
            continue

        if date_key == today_str:
            for metric_key, cols in COL_MAP.items():
                ws.cell(row=row_idx, column=cols["total"]).value = None
                ws.cell(row=row_idx, column=cols["within_sla"]).value = None
                ws.cell(row=row_idx, column=cols["achieve"]).value = None

    # ---- 应用条件格式化 ----
    apply_wo_sla_formatting(ws)

    wb_target.save(TARGET_FILE)
    wb_target.close()
    print(f"  日度行更新: {updated} 行")
    print(f"  [完成] WOs SLA achievement Report 更新完成")


# ============================================================
# 条件格式化配置
# ============================================================
# 深绿色 / 深红色 填充
FILL_GREEN = PatternFill(start_color="FF006100", end_color="FF006100", fill_type="solid")
FILL_RED   = PatternFill(start_color="FF9C0006", end_color="FF9C0006", fill_type="solid")
# 浅绿色填充（用于空白单元格）
FILL_LIGHT_GREEN = PatternFill(start_color="FFD9EAD3", end_color="FFD9EAD3", fill_type="solid")
FONT_WHITE = Font(color="FFFFFFFF")
FONT_BLACK = Font(color="FF000000")

# Network KPIs 中反向指标（越低越好，<= 目标值 = 绿色）
NETWORK_KPI_NEGATIVE_COLS = {TARGET_COL_2G_DCR, TARGET_COL_3G_DCR, TARGET_COL_3G_DCR_HSDPA}

# 列分组范围
NUR_COLS     = list(range(TARGET_COL_NUR_NETWORK, TARGET_COL_NUR_4G + 1))          # B-E
TTR_COLS     = list(range(TARGET_COL_TTR, TARGET_COL_TTR_P4 + 1))                  # F-J
NETWORK_COLS = list(range(TARGET_COL_2G_CSSR, TARGET_COL_3G_2G_HO + 1))            # K-Q
PERSITE_COLS = list(range(TARGET_COL_PS_NUR_2G, TARGET_COL_PS_RADIO_CONG + 1))     # R-AB


def apply_conditional_formatting(ws, month_row, date_rows):
    """
    对 Contract KPIs Report (New) sheet 应用条件格式化：
    - NUR 列：<= 目标值 → 深绿色，否则 → 深红色
    - TTR 列：>= 目标值 → 深绿色，否则 → 深红色
    - Network KPIs：正向指标 >= 目标值 → 深绿色，反向指标 <= 目标值 → 深绿色
    - PerSite KPIs：>= 90% → 深绿色，否则 → 深红色
    """
    print("\n[4] 应用条件格式化...")

    # 查找 Target 行（列A值为 "Target" 的行）
    target_row = None
    for row_idx in range(1, ws.max_row + 1):
        val = ws.cell(row=row_idx, column=1).value
        if val is not None and str(val).strip().lower() == "target":
            target_row = row_idx
            break

    if target_row is None:
        print("  [WARN] 未找到 Target 行，跳过格式化")
        return

    print(f"  Target 行: Row {target_row}")

    # 读取各列目标值
    targets = {}
    for col in NUR_COLS + TTR_COLS + NETWORK_COLS + PERSITE_COLS:
        tv = ws.cell(row=target_row, column=col).value
        if tv is not None:
            try:
                targets[col] = float(tv)
            except (ValueError, TypeError):
                pass

    # 需要格式化的数据行 = month_row + date_rows
    data_rows = [month_row] + date_rows if month_row else date_rows
    formatted_count = 0

    for row_idx in data_rows:
        # ---- NUR 列：<= 目标值 → 绿色 ----
        for col in NUR_COLS:
            cell = ws.cell(row=row_idx, column=col)
            val = cell.value
            if val is None:
                continue
            try:
                v = float(val)
            except (ValueError, TypeError):
                continue
            target = targets.get(col)
            if target is None:
                continue
            cell.fill = FILL_GREEN if v <= target else FILL_RED
            cell.font = FONT_WHITE
            formatted_count += 1

        # ---- TTR 列：>= 目标值 → 绿色 ----
        for col in TTR_COLS:
            cell = ws.cell(row=row_idx, column=col)
            val = cell.value
            if val is None:
                continue
            try:
                v = float(val)
            except (ValueError, TypeError):
                continue
            target = targets.get(col)
            if target is None:
                continue
            cell.fill = FILL_GREEN if v >= target else FILL_RED
            cell.font = FONT_WHITE
            formatted_count += 1

        # ---- Network KPIs 列 ----
        for col in NETWORK_COLS:
            cell = ws.cell(row=row_idx, column=col)
            val = cell.value
            if val is None:
                continue
            try:
                v = float(val)
            except (ValueError, TypeError):
                continue
            target = targets.get(col)
            if target is None:
                continue
            if col in NETWORK_KPI_NEGATIVE_COLS:
                # 反向指标（DCR）：<= 目标值 → 绿色
                cell.fill = FILL_GREEN if v <= target else FILL_RED
            else:
                # 正向指标（CSSR, HO）：>= 目标值 → 绿色
                cell.fill = FILL_GREEN if v >= target else FILL_RED
            cell.font = FONT_WHITE
            formatted_count += 1

        # ---- PerSite KPIs 列：>= 90% → 绿色 ----
        for col in PERSITE_COLS:
            cell = ws.cell(row=row_idx, column=col)
            val = cell.value
            if val is None:
                continue
            try:
                v = float(val)
            except (ValueError, TypeError):
                continue
            cell.fill = FILL_GREEN if v >= 0.9 else FILL_RED
            cell.font = FONT_WHITE
            formatted_count += 1

    print(f"  格式化单元格: {formatted_count} 个")
    print(f"  [完成] 条件格式化应用完成")


def apply_wo_sla_formatting(ws):
    """
    对 WOs SLA achievement Report sheet 应用条件格式化：
    Achieve 列：>= 目标值（Row 3）→ 深绿色，否则 → 深红色
    """
    print("\n  应用 WOs SLA 条件格式化...")

    # 动态检测子表头行（含 "Total" 和 "Achieve" 的行）
    sub_header_row = None
    for r in range(1, ws.max_row + 1):
        vals = [str(ws.cell(row=r, column=c).value).strip().lower()
                for c in range(1, min(ws.max_column + 1, 20))
                if ws.cell(row=r, column=c).value is not None]
        if "total" in vals and "achieve" in vals:
            sub_header_row = r
            break

    if sub_header_row is None or sub_header_row < 2:
        print("  [WARN] 未找到子表头行，跳过格式化")
        return

    target_row = sub_header_row - 1  # 目标值在子表头上一行
    print(f"  目标值行: Row {target_row}，子表头行: Row {sub_header_row}")

    # 找出 Achieve 列位置
    achieve_cols = []
    for c in range(1, ws.max_column + 1):
        val = ws.cell(row=sub_header_row, column=c).value
        if val is not None and str(val).strip().lower() == "achieve":
            achieve_cols.append(c)

    if not achieve_cols:
        print("  [WARN] 未找到 Achieve 列")
        return

    # 每组占 3 列（Total/Within SLA/Achieve），目标值在每组首列
    targets = {}
    for col in achieve_cols:
        target_col = ((col - 2) // 3) * 3 + 2
        tv = ws.cell(row=target_row, column=target_col).value
        if tv is not None:
            try:
                targets[col] = float(tv)
            except (ValueError, TypeError):
                targets[col] = 0.98
        else:
            targets[col] = 0.98

    # 检测数据行：Month 行 + 日期行
    data_rows = []
    for r in range(sub_header_row + 1, ws.max_row + 1):
        val = ws.cell(row=r, column=1).value
        if val is None:
            continue
        val_str = str(val).strip()
        if val_str.lower() == "month" or hasattr(val, 'year') or val_str.startswith("20"):
            data_rows.append(r)

    if not data_rows:
        print("  [WARN] 未找到数据行")
        return

    print(f"  Achieve 列: {achieve_cols}")
    print(f"  数据行: {len(data_rows)} 行")

    formatted_count = 0
    for row_idx in data_rows:
        for col in achieve_cols:
            total_col = col - 2
            within_sla_col = col - 1
            achieve_col = col
            
            # 对于 Total 和 Within SLA 列，无论是否空白都应用浅绿色背景
            for c in (total_col, within_sla_col):
                if c < 1: continue
                c_cell = ws.cell(row=row_idx, column=c)
                c_cell.fill = FILL_LIGHT_GREEN
                c_cell.font = FONT_BLACK

            # 对于 Achieve 列
            cell = ws.cell(row=row_idx, column=achieve_col)
            val = cell.value
            # 对于空白单元格，应用浅绿色背景
            if val is None:
                cell.fill = FILL_LIGHT_GREEN
                cell.font = FONT_BLACK
                continue
            try:
                v = float(val)
            except (ValueError, TypeError):
                continue
            target = targets.get(col, 0.98)
            cell.fill = FILL_GREEN if v >= target else FILL_RED
            cell.font = FONT_WHITE
            formatted_count += 1

    print(f"  格式化单元格: {formatted_count} 个")
    print(f"  [完成] WOs SLA 条件格式化应用完成")


def clean_sparse_date_rows(ws, month_row, date_rows):
    """
    清理稀疏日期行：如果日期行超过一半的单元格为空，则清空该行所有数值。
    但保留浅绿色背景。
    """
    print("\n  清理稀疏日期行...")
    max_col = ws.max_column
    data_cols = list(range(2, max_col + 1))
    total_data_cols = len(data_cols)
    threshold = total_data_cols / 2
    cleaned = 0

    for row_idx in date_rows:
        if row_idx == month_row:
            continue
        non_empty = sum(1 for col in data_cols
                        if ws.cell(row=row_idx, column=col).value is not None)
        empty_count = total_data_cols - non_empty
        if empty_count > threshold:
            for col in data_cols:
                cell = ws.cell(row=row_idx, column=col)
                # 只清空数值，保留或设置浅绿色背景
                cell.value = None
                # 不改变填充色，让后续的 apply_wo_sla_formatting 来处理
            cleaned += 1

    print(f"  清理稀疏行: {cleaned} 行")


def export_without_sla_tt_details(kpi_list_file, upload_ftp=True):
    """
    从 KPI List 读取 WithoutSLATTDetails sheet，
    过滤 Alarm Occur Time 属于当前月的数据，保留格式另存并上传FTP。
    """
    print("\n[导出 WithoutSLATTDetails]")

    sheet_name = "WithoutSLATTDetails"
    wb_src = None
    try:
        wb_src = load_workbook(kpi_list_file)
    except Exception as e:
        print(f"  [WARN] 无法打开 KPI List: {e}")
        return

    if sheet_name not in wb_src.sheetnames:
        print(f"  [WARN] 未找到 sheet: {sheet_name}")
        wb_src.close()
        return

    ws_src = wb_src[sheet_name]

    # 查找 Alarm Occur Time 列
    alarm_col = None
    for c in range(1, ws_src.max_column + 1):
        val = ws_src.cell(row=1, column=c).value
        if val is not None and "alarm occur time" in str(val).strip().lower():
            alarm_col = c
            break

    if alarm_col is None:
        print(f"  [WARN] 未找到 Alarm Occur Time 列")
        wb_src.close()
        return

    print(f"  Alarm Occur Time 列: Col {alarm_col}")

    current_month = datetime.now().strftime("%Y-%m")
    print(f"  当前月份: {current_month}")

    # 收集表头行(1) + 当月数据行
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

    data_count = len(rows_to_keep) - 1
    print(f"  当月数据: {data_count} 行")

    # 创建新工作簿并复制数据（保留格式）
    wb_new = load_workbook(kpi_list_file)
    sheets_to_remove = [s for s in wb_new.sheetnames if s != sheet_name]
    for s in sheets_to_remove:
        del wb_new[s]

    ws_new = wb_new[sheet_name]

    # 标记需要删除的行（从后向前删）
    all_rows = set(range(1, ws_src.max_row + 1))
    keep_set = set(rows_to_keep)
    rows_to_delete = sorted(all_rows - keep_set, reverse=True)

    for r in rows_to_delete:
        ws_new.delete_rows(r, 1)

    # 复制列宽
    for c in range(1, ws_src.max_column + 1):
        col_letter = get_column_letter(c)
        if col_letter in ws_src.column_dimensions:
            ws_new.column_dimensions[col_letter].width = ws_src.column_dimensions[col_letter].width

    # 保存
    today_str = datetime.now().strftime("%Y-%m-%d")
    output_name = f"WithoutSLATTDetails_{current_month}.xlsx"
    output_path = os.path.join(SCRIPT_DIR, output_name)
    wb_new.save(output_path)
    wb_new.close()
    wb_src.close()

    file_size = os.path.getsize(output_path)
    print(f"  保存: {output_name} ({file_size / 1024:.1f} KB)")

    # 上传到 FTP（主流程的 cleanup_old_exports 会统一清理旧文件）
    if upload_ftp:
        upload_files_to_ftp([output_path])


def clean_wo_sparse_rows(ws):
    """
    清理 WOs SLA achievement Report 中的稀疏日期行。
    但保留浅绿色背景，让后续的 apply_wo_sla_formatting 来处理。
    """
    # 找子表头行
    sub_header_row = None
    for r in range(1, ws.max_row + 1):
        vals = [str(ws.cell(row=r, column=c).value).strip().lower()
                for c in range(1, min(ws.max_column + 1, 20))
                if ws.cell(row=r, column=c).value is not None]
        if "total" in vals and "achieve" in vals:
            sub_header_row = r
            break
    if sub_header_row is None:
        return

    max_col = ws.max_column
    data_cols = list(range(2, max_col + 1))
    total_data_cols = len(data_cols)
    threshold = total_data_cols - 1  # 只清理完全空的行
    cleaned = 0

    for r in range(sub_header_row + 1, ws.max_row + 1):
        val_a = ws.cell(row=r, column=1).value
        if val_a is None:
            continue
        val_str = str(val_a).strip()
        # 跳过 Month 行
        if val_str.lower() == "month":
            continue
        # 只处理日期行
        if not (hasattr(val_a, 'year') or val_str.startswith("20")):
            continue

        non_empty = sum(1 for col in data_cols
                        if ws.cell(row=r, column=col).value is not None)
        empty_count = total_data_cols - non_empty
        if empty_count > threshold:
            for col in data_cols:
                cell = ws.cell(row=r, column=col)
                # 只清空数值，不改变填充色，让后续的 apply_wo_sla_formatting 来处理
                cell.value = None
            cleaned += 1

    if cleaned > 0:
        print(f"  WOs SLA 清理稀疏行: {cleaned} 行")


def cleanup_old_exports(local_dir, today_str, current_month=None):
    """
    清理本地和 FTP 上的旧导出文件，只保留最新上传的。
    today_str: 当天日期 YYYY-MM-DD（用于日维度报告）
    current_month: 当前月份 YYYY-MM（用于月维度文件如 WithoutSLATTDetails）
    """
    if current_month is None:
        current_month = today_str[:7]
    print("\n[清理旧文件]")

    # ---------- 本地清理 ----------
    local_deleted = 0
    patterns = [
        # (glob_pattern, date_str_to_keep)
        ("ZTE OLR MS Contract KPIs Achievements Daily Report_*", today_str),
        ("ZTE OLR MS WOs SLA Achievements Daily Report_*", today_str),
        ("WithoutSLATTDetails_*", current_month),
    ]
    for pattern_glob, keep_str in patterns:
        import glob as _glob
        for fpath in _glob.glob(os.path.join(local_dir, pattern_glob + ".*")):
            fname = os.path.basename(fpath)
            if keep_str in fname:
                continue
            try:
                os.remove(fpath)
                print(f"  [本地删除] {fname}")
                local_deleted += 1
            except Exception as e:
                print(f"  [WARN] 删除失败 {fname}: {e}")

    if local_deleted:
        print(f"  本地清理: 删除 {local_deleted} 个旧文件")
    else:
        print(f"  本地无旧文件需清理")

    # ---------- FTP 清理 ----------
    print("  连接到 FTP...")
    ftp = None
    try:
        ftp = FTP()
        ftp.connect(FTP_UP_HOST, FTP_UP_PORT, timeout=30)
        ftp.encoding = "utf-8"
        ftp.login(FTP_UP_USER, FTP_UP_PASS)

        # 导航到目标目录
        dirs = FTP_UP_REMOTE_DIR.strip("/").split("/")
        current = ""
        for d in dirs:
            current += f"/{d}"
            try:
                ftp.cwd(current)
            except error_perm:
                ftp.mkd(current)
                ftp.cwd(current)

        # 列出远程文件
        items = []
        ftp.dir(items.append)

        ftp_prefixes = [
            ("ZTE OLR MS Contract KPIs Achievements Daily Report_", today_str),
            ("ZTE OLR MS WOs SLA Achievements Daily Report_", today_str),
            ("WithoutSLATTDetails_", current_month),
        ]
        ftp_deleted = 0
        for item in items:
            parts = item.split(None, 8)
            if len(parts) >= 9:
                name = parts[8]
                perms = parts[0]
                if perms.startswith('d'):
                    continue
                # 匹配任意前缀 + 非当天的文件
                matched = False
                for prefix, keep_str in ftp_prefixes:
                    if name.startswith(prefix):
                        # 提取日期/月份部分
                        date_part = name.replace(prefix, "").split(".")[0][:10]
                        if date_part != keep_str:
                            matched = True
                        break
                if matched:
                    try:
                        ftp.delete(name)
                        print(f"  [FTP删除] {name}")
                        ftp_deleted += 1
                    except Exception as e:
                        print(f"  [WARN] FTP删除失败 {name}: {e}")

        if ftp_deleted:
            print(f"  FTP清理: 删除 {ftp_deleted} 个旧文件")
        else:
            print(f"  FTP无旧文件需清理")

        ftp.quit()
    except Exception as e:
        print(f"  [WARN] FTP清理失败: {e}")
        if ftp:
            try:
                ftp.close()
            except Exception:
                pass

    print(f"  [完成] 旧文件清理完毕")


# ============================================================
# 导出 & 上传 相关函数
# ============================================================

def export_sheet_to_xlsx(src_file, sheet_name, output_path):
    """
    从源 Excel 文件中复制单个 sheet 到新文件，保留原格式。
    方法：复制整个工作簿，删除其他 sheet。
    """
    import shutil
    import time
    # 复制整个文件（带重试，防止文件被占用）
    for attempt in range(1, 4):
        try:
            shutil.copy2(src_file, output_path)
            break
        except PermissionError:
            if attempt < 3:
                print(f"  [WARN] 文件被占用，{attempt*2}秒后重试...")
                time.sleep(attempt * 2)
            else:
                print(f"  [SKIP] 文件被占用，无法导出: {os.path.basename(output_path)}")
                print(f"         请关闭正在打开该文件的 Excel 后重新运行")
                return
    
    # 打开副本，删除不需要的 sheet
    wb = load_workbook(output_path)
    sheets_to_remove = [s for s in wb.sheetnames if s != sheet_name]
    for s in sheets_to_remove:
        del wb[s]
    wb.save(output_path)
    wb.close()
    print(f"  导出 xlsx: {os.path.basename(output_path)}")


def get_cell_color_hex(cell):
    """获取单元格填充颜色的十六进制值"""
    try:
        fill = cell.fill
        if fill and fill.fgColor and fill.fgColor.rgb and fill.fgColor.rgb != '00000000':
            rgb = str(fill.fgColor.rgb)
            if len(rgb) == 8:
                return rgb[2:]  # 去掉 alpha 通道
            elif len(rgb) == 6:
                return rgb
        return None
    except Exception:
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
        return {"bold": False, "color": None, "size": None}


def format_cell_value(val, is_percentage_col=None):
    """格式化单元格值用于 HTML/PNG 显示
    is_percentage_col:
        None  - 默认行为：0~1之间的值显示为百分比
        True  - 百分比列：0~1之间的值显示为百分比
        False - 非百分比列：始终显示为整数/小数，不转百分比
    """
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        if isinstance(val, bool):
            return str(val)
        # 非百分比列：不转换百分比，直接显示数值
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
        # 默认或百分比列：0~1 之间显示为百分比
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
    """
    检测 sheet 中的 Achieve 列位置集合和子表头行号。
    通过查找含 'total' 和 'achieve' 的子表头行来定位。
    返回: (achieve_cols: set, sub_header_row: int or None)
    """
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
    """
    将 Excel 中的单个 sheet 导出为 HTML 表格，保留样式。
    """
    try:
        wb = load_workbook(src_file, data_only=True)
    except PermissionError:
        print(f"  [SKIP] 文件被占用，无法导出HTML: {os.path.basename(output_path)}")
        return
    ws = wb[sheet_name]
    
    # 检测 Achieve 列和子表头行（仅 WOs SLA 报告有）
    achieve_cols, sub_header_row = _detect_achieve_cols(ws)
    has_achieve_cols = len(achieve_cols) > 0  # 是否启用 Achieve 列限制模式
    
    # 获取合并单元格信息
    merged_ranges = list(ws.merged_cells.ranges)
    
    # 构建被合并单元格覆盖的集合
    merged_cells_set = set()
    merge_info = {}  # {(start_row, start_col): (rowspan, colspan)}
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
    
    # 获取列宽
    col_widths = {}
    for col_idx in range(1, ws.max_column + 1):
        col_letter = get_column_letter(col_idx)
        dim = ws.column_dimensions.get(col_letter)
        if dim and dim.width:
            col_widths[col_idx] = dim.width
        else:
            col_widths[col_idx] = 12  # 默认宽度
    
    html_parts = []
    html_parts.append("<!DOCTYPE html>")
    html_parts.append("<html><head><meta charset='utf-8'>")
    html_parts.append("<style>")
    html_parts.append("body { font-family: 'Calibri', 'Arial', sans-serif; font-size: 11px; margin: 10px; }")
    html_parts.append("table { border-collapse: collapse; empty-cells: show; }")
    html_parts.append("td, th { border: 1px solid #B0B0B0; padding: 3px 6px; text-align: center; vertical-align: middle; white-space: nowrap; }")
    html_parts.append("</style>")
    html_parts.append("</head><body>")
    html_parts.append(f"<table>")
    
    for row_idx in range(1, ws.max_row + 1):
        html_parts.append("<tr>")
        for col_idx in range(1, ws.max_column + 1):
            # 跳过被合并覆盖的单元格
            if (row_idx, col_idx) in merged_cells_set:
                continue
            
            cell = ws.cell(row=row_idx, column=col_idx)
            
            # 合并单元格属性
            merge_attr = ""
            if (row_idx, col_idx) in merge_info:
                rowspan, colspan = merge_info[(row_idx, col_idx)]
                if rowspan > 1:
                    merge_attr += f' rowspan="{rowspan}"'
                if colspan > 1:
                    merge_attr += f' colspan="{colspan}"'
            
            # 样式
            styles = []
            
            # 背景色
            bg = get_cell_color_hex(cell)
            if bg:
                styles.append(f"background-color: #{bg}")
            
            # 字体
            font_info = get_cell_font_info(cell)
            if font_info["bold"]:
                styles.append("font-weight: bold")
            if font_info["color"] and font_info["color"] != "000000":
                styles.append(f"color: #{font_info['color']}")
            if font_info["size"]:
                styles.append(f"font-size: {font_info['size']}px")
            
            # 对齐
            if cell.alignment and cell.alignment.horizontal:
                styles.append(f"text-align: {cell.alignment.horizontal}")
            
            # 列宽
            w = col_widths.get(col_idx, 12)
            styles.append(f"min-width: {int(w * 7)}px")
            
            style_attr = f' style="{'; '.join(styles)}"' if styles else ""
            
            # 子表头行以上的行（含目标值行）按默认百分比格式；数据行仅 Achieve 列用百分比
            if has_achieve_cols and sub_header_row and row_idx >= sub_header_row:
                is_pct = (col_idx in achieve_cols) if row_idx > sub_header_row else None
            else:
                is_pct = None
            val = format_cell_value(cell.value, is_percentage_col=is_pct)
            html_parts.append(f"<td{merge_attr}{style_attr}>{val}</td>")
        
        html_parts.append("</tr>")
    
    html_parts.append("</table>")
    html_parts.append("</body></html>")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))
    
    wb.close()
    print(f"  导出 html: {os.path.basename(output_path)}")


def _find_font(size=11):
    """查找可用的支持中文的字体"""
    font_candidates = [
        "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
        "C:/Windows/Fonts/msyhbd.ttc",     # 微软雅黑粗体
        "C:/Windows/Fonts/simsun.ttc",     # 宋体
        "C:/Windows/Fonts/arial.ttf",      # Arial
        "C:/Windows/Fonts/calibri.ttf",    # Calibri
    ]
    for fp in font_candidates:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    try:
        return ImageFont.truetype("arial", size)
    except Exception:
        return ImageFont.load_default()


def export_sheet_to_png(src_file, sheet_name, output_path):
    """
    将 Excel 中的单个 sheet 导出为 PNG 图片。
    需要 Pillow 库，未安装时跳过。
    """
    if not HAS_PIL:
        print(f"  [SKIP] PNG导出跳过 (Pillow未安装): {os.path.basename(output_path)}")
        return
    
    try:
        wb = load_workbook(src_file, data_only=True)
    except PermissionError:
        print(f"  [SKIP] 文件被占用，无法导出PNG: {os.path.basename(output_path)}")
        return
    ws = wb[sheet_name]

    # 检测 Achieve 列和子表头行（仅 WOs SLA 报告有）
    achieve_cols, sub_header_row = _detect_achieve_cols(ws)
    has_achieve_cols = len(achieve_cols) > 0  # 是否启用 Achieve 列限制模式

    max_row = ws.max_row
    max_col = ws.max_column
    if max_row == 0 or max_col == 0:
        wb.close()
        return

    # 字体
    font = _find_font(11)
    font_bold = _find_font(12)

    # 计算列宽 (像素)
    col_widths = {}
    for c in range(1, max_col + 1):
        cl = get_column_letter(c)
        dim = ws.column_dimensions.get(cl)
        w = dim.width if dim and dim.width else 12
        col_widths[c] = max(int(w * 7.5), 50)

    # 行高
    row_height = 22
    header_row_height = 28

    # 计算图像尺寸
    img_width = sum(col_widths[c] for c in range(1, max_col + 1)) + 2
    img_height = header_row_height + (max_row - 1) * row_height + 2

    img = Image.new("RGB", (img_width, img_height), "white")
    draw = ImageDraw.Draw(img)

    # 合并单元格信息
    merged_map = {}  # (r,c) -> (rowspan, colspan)
    skip_cells = set()
    for mr in ws.merged_cells.ranges:
        sr, sc = mr.min_row, mr.min_col
        er, ec = mr.max_row, mr.max_col
        merged_map[(sr, sc)] = (er - sr + 1, ec - sc + 1)
        for r in range(sr, er + 1):
            for c in range(sc, ec + 1):
                if r != sr or c != sc:
                    skip_cells.add((r, c))

    # 列位置累加
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

    # 绘制单元格
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

            # 背景色
            bg = get_cell_color_hex(cell)
            fill_color = f"#{bg}" if bg else "white"
            draw.rectangle([x0, y0, x1, y1], fill=fill_color, outline="#B0B0B0")

            # 文本
            # 子表头行以上的行（含目标值行）按默认百分比格式；数据行仅 Achieve 列用百分比
            if has_achieve_cols and sub_header_row and r >= sub_header_row:
                is_pct = (c in achieve_cols) if r > sub_header_row else None
            else:
                is_pct = None
            val = format_cell_value(cell.value, is_percentage_col=is_pct)
            if val:
                font_info = get_cell_font_info(cell)
                use_font = font_bold if font_info["bold"] else font
                text_color = f"#{font_info['color']}" if font_info["color"] and font_info["color"] != "000000" else "black"
                # 文本位置 (居中)
                bbox = draw.textbbox((0, 0), val, font=use_font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                tx = x0 + (w - tw) // 2
                ty = y0 + (h - th) // 2
                # 确保不超出单元格
                tx = max(tx, x0 + 2)
                ty = max(ty, y0 + 1)
                draw.text((tx, ty), val, fill=text_color, font=use_font)

    img.save(output_path, "PNG")
    wb.close()
    print(f"  导出 png: {os.path.basename(output_path)}")


def upload_files_to_ftp(file_paths):
    """
    上传文件列表到 FTP 服务器。
    """
    print(f"\n[上传到 FTP]")
    print(f"  服务器: {FTP_UP_HOST}:{FTP_UP_PORT}")
    print(f"  远程目录: {FTP_UP_REMOTE_DIR}")
    
    try:
        ftp = FTP()
        ftp.connect(FTP_UP_HOST, FTP_UP_PORT, timeout=30)
        ftp.encoding = "utf-8"
        ftp.login(FTP_UP_USER, FTP_UP_PASS)
        print(f"  登录成功")
        
        # 确保远程目录存在
        dirs = FTP_UP_REMOTE_DIR.strip("/").split("/")
        current = ""
        for d in dirs:
            current += f"/{d}"
            try:
                ftp.cwd(current)
            except error_perm:
                ftp.mkd(current)
                ftp.cwd(current)
        
        uploaded = 0
        for fpath in file_paths:
            fname = os.path.basename(fpath)
            try:
                with open(fpath, "rb") as f:
                    ftp.storbinary(f"STOR {fname}", f)
                fsize = os.path.getsize(fpath)
                print(f"  [OK] {fname} ({fsize/1024:.1f} KB)")
                uploaded += 1
            except Exception as e:
                print(f"  [FAIL] {fname}: {e}")
        
        ftp.quit()
        print(f"  上传完成: {uploaded}/{len(file_paths)} 个文件")
        return uploaded
    except Exception as e:
        print(f"  [ERROR] FTP连接失败: {e}")
        return 0


def download_kpi_list_from_ftp(local_path):
    """
    从FTP服务器下载最新的 KPI List Operation 文件。
    结构: /webroot/WEB-INF/schedule/NUR_SLA/日期/ID/通用结果/Operation.xlsx
    查找最新的日期文件夹，递归找到xlsx文件并下载。
    返回: True/False
    """
    print("[FTP Download]")
    print(f"  服务器: {FTP_SRC_HOST}:{FTP_SRC_PORT}")
    print(f"  目录: {FTP_SRC_BASE_DIR}")
    
    ftp = None
    try:
        ftp = FTP()
        ftp.connect(FTP_SRC_HOST, FTP_SRC_PORT, timeout=30)
        ftp.encoding = "utf-8"
        ftp.login(FTP_SRC_USER, FTP_SRC_PASS)
        print(f"  登录成功")
        
        ftp.cwd(FTP_SRC_BASE_DIR)
        
        # 获取所有日期文件夹
        date_dirs = []
        items = []
        ftp.dir(items.append)
        for item in items:
            parts = item.split(None, 8)  # 最多分割8次，第9个元素为完整文件名
            if len(parts) >= 9:
                name = parts[8]  # 文件名可能含空格
                perms = parts[0]
                if perms.startswith('d') and name not in ('.', '..'):
                    # 尝试解析日期格式 YYYY-MM-DD
                    try:
                        dt = datetime.strptime(name, "%Y-%m-%d")
                        date_dirs.append((name, dt))
                    except ValueError:
                        continue
        
        if not date_dirs:
            print("  [WARN] 未找到日期文件夹")
            return False
        
        # 按日期排序，取最新的
        date_dirs.sort(key=lambda x: x[1], reverse=True)
        latest_date = date_dirs[0][0]
        print(f"  最新日期: {latest_date}")
        
        # 目标文件名（优先查找）
        TARGET_FILENAME = "KPI list - Operation.xlsx"
        
        # 递归查找xlsx文件，优先找目标文件名
        def find_xlsx(path, depth=0, found_any=None):
            """递归查找xlsx文件，优先返回目标文件名，否则返回任意xlsx"""
            if depth > 5:
                return None
            if found_any is None:
                found_any = []
            try:
                sub_items = []
                ftp.dir(path, sub_items.append)
                for si in sub_items:
                    sp = si.split(None, 8)  # 最多分割8次，第9个元素为完整文件名
                    if len(sp) >= 9:
                        sn = sp[8]  # 完整文件名（可能含空格）
                        sp_perms = sp[0]
                        if sp_perms.startswith('d') and sn not in ('.', '..'):
                            # 优先精确匹配目标文件名
                            result = find_xlsx(f"{path}/{sn}", depth + 1, found_any)
                            if result and os.path.basename(result) == TARGET_FILENAME:
                                return result  # 精确匹配，立即返回
                            if result and not found_any:
                                found_any.append(result)
                        elif not sp_perms.startswith('d') and sn.lower().endswith('.xlsx'):
                            full_path = f"{path}/{sn}"
                            if sn == TARGET_FILENAME:
                                return full_path  # 精确匹配，立即返回
                            if not found_any:
                                found_any.append(full_path)
            except Exception:
                pass
            return found_any[0] if found_any else None
        
        search_path = f"{FTP_SRC_BASE_DIR}/{latest_date}"
        remote_file = find_xlsx(search_path)
        
        if not remote_file:
            print(f"  [WARN] 在 {search_path} 下未找到xlsx文件")
            return False
        
        remote_filename = os.path.basename(remote_file)
        print(f"  远程文件: {remote_file}")
        print(f"  下载到: {local_path}")
        
        # 下载文件
        with open(local_path, 'wb') as f:
            ftp.retrbinary(f"RETR {remote_file}", f.write)
        
        file_size = os.path.getsize(local_path)
        print(f"  [OK] 下载完成: {file_size / 1024:.1f} KB")
        
        ftp.quit()
        return True
        
    except Exception as e:
        print(f"  [ERROR] FTP下载失败: {e}")
        if ftp:
            try:
                ftp.close()
            except Exception:
                pass
        return False


def main():
    print("=" * 60)
    print("Contract KPIs Report 自动更新")
    print("=" * 60)
    print(f"目标文件: {os.path.basename(TARGET_FILE)}")
    print(f"KPI List: {os.path.basename(KPI_LIST_FILE)}")
    print(f"数据库: {os.path.basename(DB_PATH)}")
    print()
    
    # 检查目标文件和数据库
    for fpath, fname in [(TARGET_FILE, "目标文件"), (DB_PATH, "数据库")]:
        if not os.path.exists(fpath):
            print(f"[ERROR] {fname}不存在: {fpath}")
            return
    
    # ============================================================
    # 0. 从FTP下载最新 KPI List 文件
    # ============================================================
    ftp_ok = download_kpi_list_from_ftp(KPI_LIST_FILE)
    if not ftp_ok:
        print("  [WARN] FTP下载失败，尝试使用本地文件...")
    
    if not os.path.exists(KPI_LIST_FILE):
        print(f"[ERROR] KPI List 文件不存在: {KPI_LIST_FILE}")
        return
    print()
    
    # ============================================================
    # 1. 读取 KPI List 文件
    # ============================================================
    print("[1] 读取 KPI List 数据...")
    
    wb_kpi = load_workbook(KPI_LIST_FILE, data_only=True)
    
    # NUR Daily
    nur_daily_data = {}
    if "KPI List NUR Daily" in wb_kpi.sheetnames:
        ws = wb_kpi["KPI List NUR Daily"]
        nur_daily_data = read_nur_daily(ws)
        print(f"  NUR Daily: {len(nur_daily_data)} 天")
    else:
        print("  [WARN] KPI List NUR Daily sheet 不存在")
    
    # NUR Monthly
    nur_monthly_data = {}
    if "KPI List NUR Monthly" in wb_kpi.sheetnames:
        ws = wb_kpi["KPI List NUR Monthly"]
        nur_monthly_data = read_nur_monthly(ws)
        print(f"  NUR Monthly: {len(nur_monthly_data)} 月")
    else:
        print("  [WARN] KPI List NUR Monthly sheet 不存在")
    
    # SLA Daily
    sla_daily_data = {}
    if "KPI List SLA Daily" in wb_kpi.sheetnames:
        ws = wb_kpi["KPI List SLA Daily"]
        sla_daily_data = read_sla_daily(ws)
        print(f"  SLA Daily: {len(sla_daily_data)} 天")
    else:
        print("  [WARN] KPI List SLA Daily sheet 不存在")
    
    # SLA Monthly
    sla_monthly_data = {}
    if "KPI List SLA Monthly" in wb_kpi.sheetnames:
        ws = wb_kpi["KPI List SLA Monthly"]
        sla_monthly_data = read_sla_monthly(ws)
        print(f"  SLA Monthly: {len(sla_monthly_data)} 月")
    else:
        print("  [WARN] KPI List SLA Monthly sheet 不存在")
    
    wb_kpi.close()
    
    # ============================================================
    # 2. 连接数据库
    # ============================================================
    print("\n[2] 连接数据库...")
    conn = sqlite3.connect(DB_PATH)
    print(f"  已连接: {DB_PATH}")
    
    # ============================================================
    # 3. 更新目标文件
    # ============================================================
    print("\n[3] 更新目标文件...")
    
    wb_target = load_workbook(TARGET_FILE)
    ws = wb_target[TARGET_SHEET]
    
    # 自动检测 Month 行和日期行范围
    month_row = None
    date_rows = []
    for row_idx in range(1, ws.max_row + 1):
        cell_val = ws.cell(row=row_idx, column=1).value
        if cell_val is not None:
            if str(cell_val).strip().lower() == "month":
                month_row = row_idx
            elif hasattr(cell_val, 'year'):  # datetime 对象
                date_rows.append(row_idx)
    
    if month_row is None:
        print("  [ERROR] 未找到 Month 行")
        wb_target.close()
        conn.close()
        return
    
    print(f"  Month 行: Row {month_row}")
    if date_rows:
        print(f"  日期行: Row {date_rows[0]} ~ Row {date_rows[-1]}")
    
    current_month = datetime.now().strftime("%Y-%m")
    print(f"  当前月份: {current_month}")
    
    # 获取月度数据
    nur_monthly = nur_monthly_data.get(current_month, {})
    sla_monthly = sla_monthly_data.get(current_month, {})
    
    updated_daily = 0
    
    # ---- 先更新 Month 行 ----
    print(f"  更新月度行 (Row {month_row})...")
    
    # NUR Monthly
    ws.cell(row=month_row, column=TARGET_COL_NUR_NETWORK).value = nur_monthly.get("NUR_NETWORK")
    ws.cell(row=month_row, column=TARGET_COL_NUR_2G).value = nur_monthly.get("NUR_2G")
    ws.cell(row=month_row, column=TARGET_COL_NUR_3G).value = nur_monthly.get("NUR_3G")
    ws.cell(row=month_row, column=TARGET_COL_NUR_4G).value = nur_monthly.get("NUR_4G")
    
    # TTR Monthly
    ws.cell(row=month_row, column=TARGET_COL_TTR).value = sla_monthly.get("TTR")
    ws.cell(row=month_row, column=TARGET_COL_TTR_P1).value = sla_monthly.get("TTR_P1")
    ws.cell(row=month_row, column=TARGET_COL_TTR_P2).value = sla_monthly.get("TTR_P2")
    ws.cell(row=month_row, column=TARGET_COL_TTR_P3).value = sla_monthly.get("TTR_P3")
    ws.cell(row=month_row, column=TARGET_COL_TTR_P4).value = sla_monthly.get("TTR_P4")
    
    # Network KPIs Monthly
    for kpi_name, kpi_config in NETWORK_KPI_MONTHLY_MAP.items():
        value = get_db_value(conn, kpi_config["table"], kpi_config["column"], current_month)
        if value is not None:
            ws.cell(row=month_row, column=kpi_config["target_col"]).value = value
    
    # PerSite KPIs Monthly
    for kpi_name, kpi_config in PERSITE_KPI_MONTHLY_MAP.items():
        value = get_persite_ratio(
            conn, kpi_config["table"], kpi_config["column"],
            current_month, kpi_config["op"], kpi_config["threshold"]
        )
        if value is not None:
            ws.cell(row=month_row, column=kpi_config["target_col"]).value = value
    
    # ---- 遍历每日数据行 ----
    for row_idx in date_rows:
        cell_date = ws.cell(row=row_idx, column=1).value
        if cell_date is None:
            continue
        
        # 转换日期
        if isinstance(cell_date, datetime):
            date_key = cell_date.strftime("%Y-%m-%d")
        elif isinstance(cell_date, date):
            date_key = cell_date.strftime("%Y-%m-%d")
        elif isinstance(cell_date, str):
            try:
                date_key = datetime.strptime(cell_date, "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                continue
        else:
            continue
        
        # ---- Operation KPIs: NUR ----
        nur = nur_daily_data.get(date_key, {})
        if nur:
            ws.cell(row=row_idx, column=TARGET_COL_NUR_NETWORK).value = nur.get("NUR_NETWORK")
            ws.cell(row=row_idx, column=TARGET_COL_NUR_2G).value = nur.get("NUR_2G")
            ws.cell(row=row_idx, column=TARGET_COL_NUR_3G).value = nur.get("NUR_3G")
            ws.cell(row=row_idx, column=TARGET_COL_NUR_4G).value = nur.get("NUR_4G")
        
        # ---- Operation KPIs: TTR ----
        sla = sla_daily_data.get(date_key, {})
        if sla:
            ws.cell(row=row_idx, column=TARGET_COL_TTR).value = sla.get("TTR")
            ws.cell(row=row_idx, column=TARGET_COL_TTR_P1).value = sla.get("TTR_P1")
            ws.cell(row=row_idx, column=TARGET_COL_TTR_P2).value = sla.get("TTR_P2")
            ws.cell(row=row_idx, column=TARGET_COL_TTR_P3).value = sla.get("TTR_P3")
            ws.cell(row=row_idx, column=TARGET_COL_TTR_P4).value = sla.get("TTR_P4")
        
        # ---- Network KPIs ----
        for kpi_name, kpi_config in NETWORK_KPI_DAILY_MAP.items():
            value = get_db_value(conn, kpi_config["table"], kpi_config["column"], date_key)
            if value is not None:
                ws.cell(row=row_idx, column=kpi_config["target_col"]).value = value
        
        # ---- PerSite KPIs ----
        for kpi_name, kpi_config in PERSITE_KPI_DAILY_MAP.items():
            value = get_persite_ratio(
                conn, kpi_config["table"], kpi_config["column"],
                date_key, kpi_config["op"], kpi_config["threshold"]
            )
            if value is not None:
                ws.cell(row=row_idx, column=kpi_config["target_col"]).value = value
        
        updated_daily += 1
    
    # ---- 清理稀疏日期行 ----
    clean_sparse_date_rows(ws, month_row, date_rows)

    # ---- 应用条件格式化 ----
    apply_conditional_formatting(ws, month_row, date_rows)

    # 保存
    wb_target.save(TARGET_FILE)
    wb_target.close()
    conn.close()
    
    print(f"\n[完成] Contract KPIs Report (New)")
    print(f"  日度行更新: {updated_daily} 行")
    print(f"  月度行更新: 1 行")
    
    # ============================================================
    # 4. 更新 WOs SLA achievement Report
    # ============================================================
    update_wo_sla_report(KPI_LIST_FILE)

    # ============================================================
    # 4b. 导出 WithoutSLATTDetails（当月数据）
    # ============================================================
    export_without_sla_tt_details(KPI_LIST_FILE)
    
    print(f"\n[完成] 全部更新完成")
    print(f"  保存: {TARGET_FILE}")
    
    # ============================================================
    # 5. 导出单个 sheet 文件 + HTML + 上传 FTP
    # ============================================================
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    print(f"\n[5] 导出并上传...")
    
    # 导出文件列表
    export_files = []
    
    # --- Contract KPIs Report (New) ---
    kpi_xlsx_name = f"ZTE OLR MS Contract KPIs Achievements Daily Report_{today_str}.xlsx"
    kpi_xlsx_path = os.path.join(SCRIPT_DIR, kpi_xlsx_name)
    export_sheet_to_xlsx(TARGET_FILE, TARGET_SHEET, kpi_xlsx_path)
    export_files.append(kpi_xlsx_path)
    
    kpi_html_name = f"ZTE OLR MS Contract KPIs Achievements Daily Report_{today_str}.html"
    kpi_html_path = os.path.join(SCRIPT_DIR, kpi_html_name)
    export_sheet_to_html(TARGET_FILE, TARGET_SHEET, kpi_html_path)
    export_files.append(kpi_html_path)
    
    kpi_png_name = f"ZTE OLR MS Contract KPIs Achievements Daily Report_{today_str}.png"
    kpi_png_path = os.path.join(SCRIPT_DIR, kpi_png_name)
    export_sheet_to_png(TARGET_FILE, TARGET_SHEET, kpi_png_path)
    if os.path.exists(kpi_png_path):
        export_files.append(kpi_png_path)
    
    # --- WOs SLA achievement Report ---
    wo_xlsx_name = f"ZTE OLR MS WOs SLA Achievements Daily Report_{today_str}.xlsx"
    wo_xlsx_path = os.path.join(SCRIPT_DIR, wo_xlsx_name)
    export_sheet_to_xlsx(TARGET_FILE, WO_SHEET, wo_xlsx_path)
    export_files.append(wo_xlsx_path)
    
    wo_html_name = f"ZTE OLR MS WOs SLA Achievements Daily Report_{today_str}.html"
    wo_html_path = os.path.join(SCRIPT_DIR, wo_html_name)
    export_sheet_to_html(TARGET_FILE, WO_SHEET, wo_html_path)
    export_files.append(wo_html_path)
    
    wo_png_name = f"ZTE OLR MS WOs SLA Achievements Daily Report_{today_str}.png"
    wo_png_path = os.path.join(SCRIPT_DIR, wo_png_name)
    export_sheet_to_png(TARGET_FILE, WO_SHEET, wo_png_path)
    if os.path.exists(wo_png_path):
        export_files.append(wo_png_path)
    
    # --- FTP 上传 ---
    upload_files_to_ftp(export_files)

    # --- 清理本地和FTP旧文件（只保留当天最新） ---
    cleanup_old_exports(SCRIPT_DIR, today_str, current_month)
    
    print(f"\n[全部完成]")


if __name__ == "__main__":
    main()

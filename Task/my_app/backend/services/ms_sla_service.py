# -*- coding: utf-8 -*-
"""
MS SLA / NUR 服务集成
整合 ran_ume_sla.py + update_contract_kpis_report.py
功能：
  1. RAN UME SLA 指标同步（API 查询 → xlsx → SQLite → API写入远程/FTP回退）
  2. Contract KPIs 报表自动更新（FTP 下载 → 数据更新 → 导出 → FTP 上传）
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

try:
    from .atomic_write import atomic_save_workbook, AtomicReplaceFallback, cleanup_stale_tmp_files
except ImportError:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ms_sla_service>: exception swallowed", exc_info=True)
    from atomic_write import atomic_save_workbook, AtomicReplaceFallback, cleanup_stale_tmp_files

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ms_sla_service>: exception swallowed", exc_info=True)
    HAS_PIL = False

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# 远程写入 API 配置（替代 FTP 上传整个 db 文件）
try:
    from backend.services.db_writer_client import DbWriterClient
except ImportError:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ms_sla_service>: exception swallowed", exc_info=True)
    from db_writer_client import DbWriterClient
try:
    _db_writer = DbWriterClient()
except Exception:
    _db_writer = None
    print("[WARNING] db_writer_client 初始化失败，将回退到 FTP 模式")

logger = logging.getLogger("ms_sla_service")

# ============================================================
# 路径配置
# ============================================================
DATA_DIR = Path(r"d:\01_RPA\Task\my_app\data\ms_sla")
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_NAME = "lbr_ms_sla_kpi.sqlite3"
DB_PATH = DATA_DIR / DB_NAME

# 报表文件
TARGET_FILE = DATA_DIR / "ZTE OLR MS Contract KPIs & WOs Achievement Auto-Reports.xlsx"
KPI_LIST_FILE = DATA_DIR / "KPI list - Operation.xlsx"

# SLA 导出临时目录
SLA_OUTPUT_DIR = str(DATA_DIR / "sla_exports")
os.makedirs(SLA_OUTPUT_DIR, exist_ok=True)

# ============================================================
# FTP 配置
# ============================================================
# 上传 FTP（ZTEEMS 账号）
FTP_UP_HOST = "192.168.100.19"
FTP_UP_PORT = 21
FTP_UP_USER = "ZTEEMS"
FTP_UP_PASS = "DX"
FTP_UP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/MS_SLA"

# 下载 FTP（FINEBI 账号）
FTP_SRC_HOST = "192.168.100.19"
FTP_SRC_PORT = 21
FTP_SRC_USER = "FINEBI"
FTP_SRC_PASS = "DX"
FTP_SRC_BASE_DIR = "/webroot/WEB-INF/schedule/NUR_SLA"

# SQLite 批量插入大小
BATCH_SIZE = 2000

# ============================================================
# RAN UME API 配置
# ============================================================
UME_HOST = "10.100.28.27"
UME_PORT = 28001
UME_USERNAME = "NOC"
UME_PASSWORD = "Zte@2025!"

# 并行查询线程数
MAX_PARALLEL_WORKERS = int(os.environ.get("SLA_PARALLEL_WORKERS", "4"))

# ========== 重试 / 超时配置（环境变量可调） ==========
HTTP_MAX_RETRIES = max(0, int(os.environ.get("SLA_HTTP_MAX_RETRIES", "3")))
HTTP_RETRY_DELAY = float(os.environ.get("SLA_HTTP_RETRY_DELAY", "1"))
HTTP_CONNECT_TIMEOUT = float(os.environ.get("SLA_CONNECT_TIMEOUT", "15"))
HTTP_READ_TIMEOUT = float(os.environ.get("SLA_READ_TIMEOUT", "90"))
# 时间范围：默认最近 32 天
DAYS_BACK = int(os.environ.get("SLA_DAYS_BACK", "7"))
# 1Month 粒度查询的回溯窗口：保持覆盖整月（报表 Month 行依赖月度值）
SLA_MONTH_DAYS_BACK = int(os.environ.get("SLA_MONTH_DAYS_BACK", "32"))

# _SITE 表主键的站点/网元标识列（精确匹配，避免 SubnetWork ID 等被关键字误选）
_SITE_PK_COLUMN_CANDIDATES = [
    "SITE ID", "Site ID", "NodeB ID", "NodeBId",
    "eNodeB ID", "eNodeBId", "ENodeB ID",
    "ME ID", "ManagedElement ID", "Managed\xa0Element", "ME",
]


def _detect_site_pk_column(headers: list) -> str | None:
    """在 _SITE 表头中查找真正的站点/网元标识列。"""
    for cand in _SITE_PK_COLUMN_CANDIDATES:
        if cand in headers:
            return cand
    return None


def _cols_unique(headers: list, data: list, cols: list) -> bool:
    """判断当批数据按 cols 组合是否唯一（用于避免 upsert 主键塌缩）。"""
    idxs = [headers.index(c) for c in cols if c in headers]
    if not idxs:
        return False
    seen = set()
    for row in data:
        key = tuple((row[i] if i < len(row) else None) for i in idxs)
        if key in seen:
            return False
        seen.add(key)
    return True


def _choose_pk_columns(headers: list, data: list, table_name: str) -> list:
    """为 ms_sla 表选择 upsert 主键，保证所选主键在当批数据内唯一。

    - _SITE 表：首列(时间) + 站点/网元列
    - 非 _SITE 表：首列(时间)；若首列不唯一，依次附加后续列直到唯一
    - 实在凑不出唯一键则抛异常（调用方据此报错/降级，而非静默塌缩）
    """
    if not headers or not data:
        raise Exception(f"[{table_name}] 无表头或数据，无法选择主键")
    pk_cols = [headers[0]]
    if "_SITE" in table_name:
        site_pk = _detect_site_pk_column(headers)
        if site_pk:
            pk_cols.append(site_pk)
    if _cols_unique(headers, data, pk_cols):
        return pk_cols
    # 首列（或 _SITE 主键）不唯一 -> 尝试附加后续列凑出唯一键
    for extra in headers[1:]:
        if extra in pk_cols:
            continue
        cand = pk_cols + [extra]
        if _cols_unique(headers, data, cand):
            logger.warning(f"[{table_name}] 主键首列非唯一，已扩展为 {cand}")
            return cand
    raise Exception(
        f"[{table_name}] 无法凑出唯一主键（首列={headers[0]!r}，"
        f"附加其余列仍不能去重），放弃 upsert 以免数据塌缩。请检查导出表结构。"
    )


# SLA 接口路径
SLA_HISTORY_PATH = "/api/pm-analysis/v2/history"
SLA_HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
SLA_HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"
SLA_REFERER = f"https://{UME_HOST}:{UME_PORT}/iui/pm/angularTask/dist/pmManagement.html"

# 备用鉴权信息
FALLBACK_COOKIE = (
    "X-Rm-Data-Version-zenap=1773367620002_0_0_0_0_0_0_0_0; "
    "Z-AUTH-CODE-28001=1154983705_f188b025b7b64878ae0f4511e90ab1a2; "
    "x-dexmesh-user-28001=D86935A99B38A02CDAEA05C225E9303A21FA22B872499884D7B2A1E26A5645FE; "
    "forgerydefense-28001=cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"
)
FALLBACK_FORGERY = "cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"

# grouplayer / gr 显示名称替换规则
GROUP_LAYER_RENAME = {
    "me,WV4.IubLink": "Sites",
    "me,gv4.BTSSiteManager": "Sites",
    "me,eNodeBFunction": "Sites",
    "all": "NW",
}
GR_RENAME = {
    "2592000": "1Month",
    "86400": "1Day",
}

# SLA 查询配置
SLA_QUERY_CONFIGS = {
    "GSM": {
        "templateid": "1638004472426",
        "templatename": "KPI_RPA_SITE_MS_SLA_GSM",
        "motid": "gsmPm.cell",
        "nfctid": "MRNC",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "showbusinesscolumn": False,
        "versiondatacompare": False,
        "items": [
            "306024", "900241213", "901415213", "306002", "306006", "306003",
            "306008", "306035", "306036", "900008213", "1675910745777", "306004",
            "1638004469689", "1675910745799",
        ],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    "UMTS": {
        "templateid": "1638004472427",
        "templatename": "KPI_RPA_SITE_MS_SLA_UMTS",
        "motid": "wPm.UtranCell,wPm.LogicCell",
        "nfctid": "MRNC",
        "containvcell": 2,
        "indexfillingtype": "zeroDenominator",
        "showbusinesscolumn": False,
        "versiondatacompare": False,
        "items": [
            "300249", "300240", "300294", "300243", "901593214", "300020",
            "300046", "300073", "300476", "300478", "300532", "300857",
            "300824", "300840", "901597214", "901598214", "300139", "900005214",
            "901411214", "901410214", "901620214", "901621214", "901622214",
            "901623214", "901604214", "901605214", "901603214", "901596214",
        ],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    "FDD": {
        "templateid": "1638004472428",
        "templatename": "KPI_RPA_SITE_MS_SLA_FDD",
        "motid": "EUtranCellFDD",
        "businessmotid": "EUtranCellFDD,FDDV3.EUtranCellFDD",
        "nfctid": "ITBBU,SDR,#",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "showbusinesscolumn": True,
        "items": [
            "1638004469333", "1638004469335", "1638004469337", "1638004469340",
            "1638004469341", "1638004469330", "1638004469331", "C373343602",
            "C373343605", "1638004469342", "1638004469343", "1638004469344",
            "1638004469345", "C373200029", "C373364118", "C373353961",
            "1638004469332", "1638004469785", "1603456136636", "1638004477799",
        ],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [2, 2, 2, 2, 2, 2, 2, 1, 1, 2, 2, 2, 2, 1, 1, 1, 2, 2, 2, 2],
        "itempositionbusiness": [0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0],
    },
}

# ============================================================
# 目标文件列映射 (Row 4 是表头, Row 6+ 是数据)
# ============================================================
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

# ============================================================
# Network KPIs 数据库映射
# ============================================================
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

# ============================================================
# PerSite KPIs 配置
# ============================================================
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

# ============================================================
# 条件格式化配置
# ============================================================
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


# ============================================================
# 通用工具函数
# ============================================================

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


def read_xlsx_streaming(filepath):
    """流式读取xlsx文件，返回 (headers, data)"""
    with open(filepath, 'rb') as f:
        file_bytes = f.read()
    return read_xlsx_bytes(file_bytes)


def read_xlsx_bytes(file_bytes: bytes):
    """从内存字节直接解析 xlsx，不经磁盘。"""
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    try:
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        header_row = next(rows_iter)
        headers = [str(col).strip() if col is not None else f"col_{i}"
                   for i, col in enumerate(header_row)]
        data = []
        for row in rows_iter:
            if all(v is None for v in row):
                continue
            data.append(list(row))
    finally:
        wb.close()
    del file_bytes
    return headers, data


def write_to_db(db_path, table_name, headers, data):
    """将数据增量写入 SQLite 数据库（按主键 upsert，保留历史）。

    主键：首列（时间）+ _SITE 表的站点/网元标识列，与远程 API 写入的 pk 规则保持一致。
    """
    with get_raw_connection(str(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=OFF")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.execute("PRAGMA temp_store=MEMORY")

        def _q(col):
            return f'"{col.replace(chr(34), chr(34)+chr(34))}"'

        # 建表（幂等，全部 TEXT，不强制 NOT NULL）
        col_defs = ", ".join(f"{_q(h)} TEXT" for h in headers)
        cursor.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({col_defs})')

        # 补充缺失列
        exist_cols = {r[1] for r in cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()}
        for h in headers:
            if h not in exist_cols:
                cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN {_q(h)} TEXT')

        # 主键：优先用 _choose_pk_columns（保证唯一，避免 upsert 塌缩）；
        # 若实在凑不出唯一键，降级为"无唯一索引的普通写入"（不塌缩、仅可能重复）并告警
        try:
            pk_cols = _choose_pk_columns(headers, data, table_name)
        except Exception as pk_err:
            logger.warning(f"[{table_name}] 无法选出唯一主键({pk_err})，本地写入降级为无唯一索引模式(不塌缩)")
            pk_cols = None

        # 保证唯一约束存在：先清理历史重复行，再建唯一索引（upsert 才能生效）
        if pk_cols:
            pk_q = ", ".join(_q(k) for k in pk_cols)
            try:
                cursor.execute(
                    f'DELETE FROM "{table_name}" WHERE rowid NOT IN ('
                    f'SELECT MIN(rowid) FROM "{table_name}" GROUP BY {pk_q})'
                )
                # 先删除旧的同名唯一索引，避免主键列变更后 IF NOT EXISTS 跳过导致旧索引残留
                cursor.execute(f'DROP INDEX IF EXISTS "u_{table_name}"')
                cursor.execute(
                    f'CREATE UNIQUE INDEX "u_{table_name}" ON "{table_name}" ({pk_q})'
                )
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] write_to_db: exception swallowed", exc_info=True)
                conn.rollback()

        quoted_headers = [_q(h) for h in headers]
        placeholders = ", ".join(["?"] * len(headers))
        insert_sql = f'INSERT OR REPLACE INTO "{table_name}" ({", ".join(quoted_headers)}) VALUES ({placeholders})'

        row_count = 0
        batch = []
        for row in data:
            if len(row) < len(headers):
                row.extend([None] * (len(headers) - len(row)))
            elif len(row) > len(headers):
                row = row[:len(headers)]
            str_row = [str(v) if v is not None else None for v in row]
            batch.append(str_row)
            row_count += 1
            if len(batch) >= BATCH_SIZE:
                cursor.executemany(insert_sql, batch)
                batch.clear()
        if batch:
            cursor.executemany(insert_sql, batch)
        conn.commit()

        if headers:
            first_col = headers[0].replace('"', '""')
            try:
                cursor.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_{first_col}" ON "{table_name}" ("{first_col}")')
                conn.commit()
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] write_to_db: exception swallowed", exc_info=True)
                pass
        conn.close()
        return row_count


def _upload_to_ftp(local_path, remote_dir, filename, max_retries=2):
    """上传文件到 FTP 服务器（带重试）"""
    for attempt in range(1, max_retries + 1):
        ftp = None
        try:
            ftp = FTP(FTP_UP_HOST, timeout=30)
            ftp.encoding = "utf-8"
            ftp.login(FTP_UP_USER, FTP_UP_PASS)
            ftp.cwd("/")
            parts = remote_dir.strip("/").split("/")
            for i in range(len(parts)):
                abs_path = "/" + "/".join(parts[:i + 1])
                try:
                    ftp.cwd(abs_path)
                except error_perm:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] _upload_to_ftp: exception swallowed", exc_info=True)
                    try:
                        ftp.mkd(abs_path)
                        ftp.cwd(abs_path)
                    except error_perm:
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _upload_to_ftp: exception swallowed", exc_info=True)
                        pass
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f)
            ftp.quit()
            return True
        except Exception as e:
            logger.warning(f"FTP上传失败(第{attempt}次): {e}")
            if ftp:
                try:
                    ftp.close()
                except Exception:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] _upload_to_ftp: exception swallowed", exc_info=True)
                    pass
    return False


# ============================================================
# RAN UME HTTP / SSL 工具函数（连接复用 + bytearray + 截断检测）
# ============================================================
_http_local = threading.local()


def _create_ssl_socket():
    """创建绕过证书校验的 TLS socket。"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers('ALL:@SECLEVEL=0')
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(HTTP_CONNECT_TIMEOUT)
    ssock = ctx.wrap_socket(sock)
    ssock.connect((UME_HOST, UME_PORT))
    ssock.settimeout(HTTP_READ_TIMEOUT)
    return ssock


def _get_thread_socket():
    ssock = getattr(_http_local, "socket", None)
    if ssock is None:
        ssock = _create_ssl_socket()
        _http_local.socket = ssock
    return ssock


def _close_thread_socket():
    ssock = getattr(_http_local, "socket", None)
    _http_local.socket = None
    if ssock is not None:
        try:
            ssock.close()
        except OSError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _close_thread_socket: exception swallowed", exc_info=True)
            pass


def _run_with_cleanup(fn, *args, **kwargs):
    """Wrap a pipeline task to ensure its TLS connection is released afterwards."""
    try:
        return fn(*args, **kwargs)
    finally:
        _close_thread_socket()


def _decode_chunked(data):
    """解码 HTTP chunked 响应体。"""
    result = bytearray()
    pos = 0
    while pos < len(data):
        line_end = data.find(b"\r\n", pos)
        if line_end == -1:
            break
        chunk_size_str = data[pos:line_end].decode('utf-8', errors='replace').strip()
        try:
            chunk_size = int(chunk_size_str, 16)
        except ValueError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _decode_chunked: exception swallowed", exc_info=True)
            break
        if chunk_size == 0:
            break
        pos = line_end + 2
        result.extend(data[pos:pos + chunk_size])
        pos += chunk_size + 2
    return bytes(result)


def _http_request(method, path, headers_extra=None, body=None, retry=0):
    """发送原始 HTTP 请求，带连接复用、bytearray接收、截断检测和重试。"""
    try:
        ssock = _get_thread_socket()
    except (ssl.SSLError, socket.timeout, ConnectionError, OSError) as e:
        if retry < HTTP_MAX_RETRIES:
            delay = HTTP_RETRY_DELAY * (2 ** retry) + random.uniform(0, 0.25)
            logger.warning(f"[SLA][HTTP] Connect failed (attempt {retry+1}): {e}, retry in {delay:.1f}s")
            time.sleep(delay)
            return _http_request(method, path, headers_extra=headers_extra, body=body, retry=retry + 1)
        raise

    headers = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {UME_HOST}:{UME_PORT}\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Language: en-US,en;q=0.9\r\n"
        f"Accept-Encoding: identity\r\n"
        f"Connection: keep-alive\r\n"
        f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\r\n"
    )
    if headers_extra:
        headers += headers_extra
    if body:
        headers += f"Content-Length: {len(body)}\r\n"
    headers += "\r\n"

    request_bytes = headers.encode('utf-8')
    if body:
        request_bytes += body if isinstance(body, bytes) else body.encode('utf-8')

    try:
        ssock.sendall(request_bytes)
    except (socket.timeout, ConnectionError, OSError) as e:
        _close_thread_socket()
        if retry < HTTP_MAX_RETRIES:
            delay = HTTP_RETRY_DELAY * (2 ** retry) + random.uniform(0, 0.25)
            logger.warning(f"[SLA][HTTP] Send failed (attempt {retry+1}): {e}, retry in {delay:.1f}s")
            time.sleep(delay)
            return _http_request(method, path, headers_extra=headers_extra, body=body, retry=retry + 1)
        raise

    response_data = bytearray()
    content_length = None
    header_end_found = False
    header_end_pos = 0

    while True:
        try:
            chunk = ssock.recv(65536)
            if not chunk:
                break
            response_data.extend(chunk)
        except socket.timeout:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _http_request: exception swallowed", exc_info=True)
            break

        if not header_end_found:
            pos = response_data.find(b"\r\n\r\n")
            if pos != -1:
                header_end_found = True
                header_end_pos = pos
                hp = response_data[:pos].decode('utf-8', errors='replace')
                for line in hp.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        try:
                            content_length = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _http_request: exception swallowed", exc_info=True)
                            pass
                        break

        if header_end_found and content_length is not None:
            if len(response_data) - (header_end_pos + 4) >= content_length:
                break

    if header_end_found and content_length is not None:
        body_data = response_data[header_end_pos + 4:]
        if len(body_data) < content_length:
            _close_thread_socket()
            raise ConnectionError(f"Response truncated: {len(body_data)}/{content_length} bytes")

    header_end = response_data.find(b"\r\n\r\n")
    if header_end == -1:
        _close_thread_socket()
        if retry < HTTP_MAX_RETRIES:
            delay = HTTP_RETRY_DELAY * (2 ** retry) + random.uniform(0, 0.25)
            logger.warning(f"[SLA][HTTP] Cannot parse response (attempt {retry+1}), retry in {delay:.1f}s")
            time.sleep(delay)
            return _http_request(method, path, headers_extra=headers_extra, body=body, retry=retry + 1)
        raise Exception("Cannot parse HTTP response")

    header_part = response_data[:header_end].decode('utf-8', errors='replace')
    resp_body = bytes(response_data[header_end + 4:])
    status_line = header_part.split("\r\n")[0]

    resp_headers = {}
    for line in header_part.split("\r\n")[1:]:
        if ": " in line:
            k, v = line.split(": ", 1)
            resp_headers[k.lower()] = v

    if "chunked" in resp_headers.get("transfer-encoding", ""):
        resp_body = _decode_chunked(resp_body)
        _close_thread_socket()
    elif "close" in resp_headers.get("connection", "").lower() or content_length is None:
        _close_thread_socket()

    if "gzip" in resp_headers.get("content-encoding", ""):
        try:
            resp_body = gzip.decompress(resp_body)
        except Exception as exc:
            raise Exception(f"Failed to decompress gzip response: {exc}")

    return status_line, resp_headers, header_part, resp_body


def _rsa_encrypt_pem(plaintext, public_key_b64):
    """使用 RSA 公钥对明文进行 PKCS1v15 加密，返回 Base64 密文。"""
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import serialization
    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())
    encrypted = public_key.encrypt(plaintext.encode('utf-8'), asym_padding.PKCS1v15())
    return base64.b64encode(encrypted).decode('ascii')


# ============================================================
# RAN UME 登录
# ============================================================

def _ume_login(max_retries=2):
    """执行 RAN UME 登录流程（优先使用共享缓存，避免同账户重复登录）。

    Args:
        max_retries: 登录失败时最大重试次数（含首次），默认2次
    """
    try:
        try:
            from backend.services.auth_manager import get_auth
        except ImportError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _ume_login: exception swallowed", exc_info=True)
            from auth_manager import get_auth
        result = get_auth(UME_HOST, UME_PORT, UME_USERNAME, UME_PASSWORD)
        source = "缓存" if result["from_cache"] else "重新登录"
        logger.info(f"[LOGIN] 鉴权成功（来源: {source}）")
        return {"cookie": result["cookie"], "forgery_token": result["forgery_token"]}
    except Exception as e:
        logger.warning(f"[LOGIN] auth_manager 失败: {e}，使用备用 Cookie")
        return {"cookie": FALLBACK_COOKIE, "forgery_token": FALLBACK_FORGERY}


# ============================================================
# SLA 查询函数
# ============================================================

def _sla_auth_headers(cookie, forgery_token, extra=None):
    """构造 SLA 接口鉴权请求头。"""
    headers = (
        f"Content-Type: application/json; charset=UTF-8\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Encoding: gzip\r\n"
        f"Cookie: {cookie}\r\n"
        f"Referer: {SLA_REFERER}\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
    )
    if forgery_token:
        headers += f"forgerydefense: {forgery_token}\r\n"
    if extra:
        for k, v in extra.items():
            headers += f"{k}: {v}\r\n"
    return headers


def _http_request_with_retry(method, path, headers_extra=None, body=None, max_retries=2, retry_statuses=None):
    """带重试的 HTTP 请求封装。"""
    if retry_statuses is None:
        retry_statuses = ("499", "500", "502", "503", "504")
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            status, hdrs, raw_hdrs, resp_body = _http_request(method, path, headers_extra=headers_extra, body=body)
            if any(code in status for code in retry_statuses):
                last_exception = Exception(f"Retryable status: {status}")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
            return status, hdrs, raw_hdrs, resp_body
        except Exception as e:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _http_request_with_retry: exception swallowed", exc_info=True)
            last_exception = e
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            else:
                break
    raise last_exception or Exception(f"HTTP request failed after {max_retries + 1} attempts")


def _build_sla_payload(tech, grouplayer, gr_seconds, start_iso=None, end_iso=None):
    """构造 SLA 历史指标查询 Payload。"""
    cfg = SLA_QUERY_CONFIGS.get(tech)
    if not cfg:
        raise ValueError(f"Unsupported tech: {tech}")
    now = datetime.now(timezone.utc)
    if end_iso is None:
        end_iso = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if start_iso is None:
        # 1Day 查询用小窗口（本地库增量累积），1Month 查询保持整月窗口
        days_back = SLA_MONTH_DAYS_BACK if gr_seconds == "2592000" else DAYS_BACK
        start_dt = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    items = cfg["items"]
    item_count = len(items)
    timeinfo = {
        "mode": 1, "start": start_iso, "end": end_iso, "relative": -1,
        "timezonetype": "1", "clienttimezone": "Atlantic/Reykjavik",
        "showtimezoneoffset": False, "querylongtime": {"type": 3, "value": 1},
        "timespanfilter": "00:00:00-24:00:00", "dayfiltertype": 0,
        "dayinmonthfilter": "1111111111111111111111111111111",
    }
    payload = {
        "arraycounterinfos": [], "datatype": 0, "displaymode": 0,
        "favoriteconditionname": cfg["templatename"], "gr": gr_seconds,
        "groupattributetype": 0, "groupbygroup": False, "groupbyplmn": False,
        "grouptype": 0, "items": items,
        "itemsposition": cfg.get("itemsposition", [0] * item_count),
        "itemsposition1": cfg.get("itemsposition1", [0] * item_count),
        "motid": cfg["motid"], "nfctid": cfg["nfctid"],
        "plmnpdfdisplaymode": False, "queryallbusiness": False,
        "showbusinesscolumn": cfg["showbusinesscolumn"], "showintegrity": False,
        "straightquery": False, "templatename": cfg["templatename"],
        "templateid": cfg["templateid"],
    }
    if "versiondatacompare" in cfg:
        payload["versiondatacompare"] = cfg["versiondatacompare"]
    payload.update({"needdeployfilter": False, "timeinfo": timeinfo, "indexfillingtype": cfg["indexfillingtype"]})
    if "businessmotid" in cfg:
        payload["businessmotid"] = cfg["businessmotid"]
    if "itempositionbusiness" in cfg:
        payload["itempositionbusiness"] = cfg["itempositionbusiness"]
    payload.update({
        "thresholdinfos": [], "templatetype": 0, "filterlayer": "all",
        "grouplayer": grouplayer, "containvcell": cfg["containvcell"],
        "resfilterattribute": "", "uilocations": [], "reslocation": [], "inexistenceres": False,
    })
    if "businessmotid" in cfg:
        payload["groupbusinessids"] = []
        payload["businessfilterscope"] = []
    payload.update({"firstDayOfWeek": 7, "iswireless": True, "hidehistorystopbutton": True,
                    "opencustomizehistoryexport": False, "opentemplatecustomcolumn": False})
    return payload


def _create_sla_history_query(cookie, forgery_token, payload):
    """创建 SLA 历史指标查询任务，返回 queryid。"""
    logger.info(f"[SLA] 创建查询: {payload.get('templatename')} / {payload.get('grouplayer')} / {payload.get('gr')}")
    body = json.dumps(payload, ensure_ascii=False)
    headers = _sla_auth_headers(cookie, forgery_token)
    status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
        "POST", SLA_HISTORY_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=2,
    )
    if "200" not in status:
        raise Exception(f"Create SLA query failed: {status}")
    data = json.loads(resp_body.decode('utf-8', errors='replace'))
    queryid = data.get("queryid") or data.get("id")
    if not queryid:
        raise Exception(f"No queryid returned")
    logger.info(f"[SLA] Query ID: {queryid}")
    return queryid


def _wait_sla_history_ready(cookie, forgery_token, queryid, timeout=300, interval=5):
    """轮询 SLA 查询进度直到完成。"""
    path = f"{SLA_HISTORY_POLL_PATH}?type=0&queryid={queryid}"
    headers = _sla_auth_headers(cookie, forgery_token, extra={"Accept": "application/json, text/plain, */*"})
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, hdrs, raw_hdrs, resp_body = _http_request_with_retry("GET", path, headers_extra=headers, max_retries=1)
        data = json.loads(resp_body.decode('utf-8', errors='replace'))
        progress = data.get("progress", 0)
        querystate = data.get("querystate", 0)
        if querystate == 1 or progress >= 100:
            return data
        time.sleep(interval)
    raise Exception(f"SLA query timed out after {timeout}s")


def _export_sla_history(cookie, forgery_token, queryid, filename, output_path=None) -> bytes:
    """导出并下载 SLA 历史指标结果，直接返回 xlsx 字节（不落盘）。"""
    payload = {
        "id": queryid, "filename": filename, "chartlayout": 1, "contentmode": 0,
        "customizefieldtype": "0", "exportfiletype": 1, "exportserialnumber": False,
        "exporttableheaders": False, "formatwithts": 0, "imageinfo": [],
        "itemshowtype": 0, "tableheaders": {},
    }
    body = json.dumps(payload, ensure_ascii=False)
    headers = _sla_auth_headers(cookie, forgery_token)
    status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
        "POST", SLA_HISTORY_EXPORT_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=2,
    )
    if "200" not in status:
        raise Exception(f"Export SLA history failed: {status}")
    logger.info(f"[SLA] 已导出: {filename}.xlsx ({len(resp_body)} bytes, in-memory)")
    return resp_body


# ============================================================
# SLA 文件命名与表名
# ============================================================

def _build_sla_filename(templatename, grouplayer, gr_seconds):
    """构造 SLA 导出文件名。"""
    group_label = GROUP_LAYER_RENAME.get(grouplayer, grouplayer)
    gr_label = GR_RENAME.get(gr_seconds, gr_seconds)
    return f"{templatename}_{group_label}_{gr_label}"


def _build_legacy_table_name(tech, grouplayer, gr_seconds):
    """构造与旧脚本兼容的表名。"""
    period = "1month" if gr_seconds == "2592000" else "1day"
    layer = "SITE" if grouplayer != "all" else "NW"
    templatename = SLA_QUERY_CONFIGS[tech]["templatename"]
    return f"Hourly_{templatename}{period}_{layer}"


def _derive_table_name(filepath):
    """根据文件路径生成表名。"""
    base = os.path.splitext(os.path.basename(filepath))[0]
    base = re.sub(r'_\d{14}$', '', base)
    return f"Hourly_{base}"


# ============================================================
# SLA 查询执行与清理
# ============================================================

def _run_single_sla_query(cookie, forgery_token, task_cfg):
    """执行单个 SLA 查询任务（用于多线程并行）。"""
    tech = task_cfg["tech"]
    grouplayer = task_cfg["grouplayer"]
    gr_seconds = task_cfg["gr"]
    task_index = task_cfg.get("index", 0)

    stagger_sec = task_index * 0.8
    if stagger_sec > 0:
        time.sleep(stagger_sec)

    cfg = SLA_QUERY_CONFIGS[tech]
    filename = _build_sla_filename(cfg["templatename"], grouplayer, gr_seconds)
    output_path = os.path.join(SLA_OUTPUT_DIR, f"{filename}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.xlsx")

    logger.info(f"[SLA] 开始查询 [{tech}/{grouplayer}/{gr_seconds}]...")
    payload = _build_sla_payload(tech, grouplayer, gr_seconds)
    queryid = _create_sla_history_query(cookie, forgery_token, payload)
    status = _wait_sla_history_ready(cookie, forgery_token, queryid)
    logger.info(f"[SLA] 查询完成 [{tech}/{grouplayer}/{gr_seconds}]: totalcount={status.get('totalcount')}")

    xlsx_bytes = _export_sla_history(cookie, forgery_token, queryid, filename=filename)
    table_name = _build_legacy_table_name(tech, grouplayer, gr_seconds)
    return {"xlsx_bytes": xlsx_bytes, "table_name": table_name}


def _cleanup_sla_exports():
    """清理所有 SLA 导出文件。"""
    deleted = 0
    for cfg in SLA_QUERY_CONFIGS.values():
        templatename = cfg["templatename"]
        for grouplayer in GROUP_LAYER_RENAME.keys():
            for gr_seconds in GR_RENAME.keys():
                base_name = _build_sla_filename(templatename, grouplayer, gr_seconds)
                pattern = os.path.join(SLA_OUTPUT_DIR, f"{base_name}_*.xlsx")
                for fpath in glob.glob(pattern):
                    if os.path.basename(fpath).startswith("~$"):
                        continue
                    try:
                        os.remove(fpath)
                        deleted += 1
                    except PermissionError:
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _cleanup_sla_exports: exception swallowed", exc_info=True)
                        try:
                            subprocess.run(
                                ['powershell', '-Command', f'Remove-Item -Path "{fpath}" -Force -ErrorAction Stop'],
                                capture_output=True, timeout=15,
                                creationflags=_SUBPROCESS_FLAGS,
                            )
                            if not os.path.exists(fpath):
                                deleted += 1
                        except Exception:
                            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _cleanup_sla_exports: exception swallowed", exc_info=True)
                            pass
                    except Exception:
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _cleanup_sla_exports: exception swallowed", exc_info=True)
                        pass
    return deleted


# ============================================================
# 入口函数 1: RAN UME SLA 指标同步
# ============================================================

def run_ms_sla_sync(max_workers=None):
    """
    执行完整的 SLA 指标同步流程：API 查询 -> 入库 -> FTP 上传 -> 清理。
    替代原来的 run_ms_sla_daily_import + run_ms_sla_monthly_import。
    """
    if max_workers is None:
        max_workers = MAX_PARALLEL_WORKERS
    t_start = time.time()
    logger.info(f"RAN UME SLA 同步开始 (workers={max_workers}, days_back={DAYS_BACK})")

    # 1. 登录
    auth = _ume_login()
    cookie = auth["cookie"]
    forgery_token = auth["forgery_token"]

    # 2. 构建任务列表: 3 tech × (Sites + NW) × (1Day + 1Month) = 12 个任务
    task_configs = []
    idx = 0
    tech_layer_map = {"GSM": "me,gv4.BTSSiteManager", "UMTS": "me,WV4.IubLink", "FDD": "me,eNodeBFunction"}
    for tech in SLA_QUERY_CONFIGS.keys():
        for grouplayer in (tech_layer_map[tech], "all"):
            for gr in ("2592000", "86400"):
                task_configs.append({"tech": tech, "grouplayer": grouplayer, "gr": gr, "index": idx})
                idx += 1

    logger.info(f"  总任务数: {len(task_configs)}")

    # 3. 并行获取所有 SLA 文件
    download_results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_cfg = {
            executor.submit(_run_with_cleanup, _run_single_sla_query, cookie, forgery_token, cfg): cfg
            for cfg in task_configs
        }
        for future in as_completed(future_to_cfg):
            cfg = future_to_cfg[future]
            try:
                result = future.result()
                if result:
                    download_results.append(result)
            except Exception as e:
                logger.warning(f"  SLA查询失败 [{cfg['tech']}/{cfg['grouplayer']}/{cfg['gr']}]: {e}")

    if not download_results:
        elapsed = time.time() - t_start
        logger.error("SLA 同步失败: 无文件下载")
        return {"success": False, "error": "无文件下载", "elapsed_seconds": round(elapsed, 2)}

    # 4. 顺序导入数据库（从内存读取）
    logger.info(f"  导入 {len(download_results)} 个文件到数据库...")
    total_imported = 0
    imported_tables = []
    table_data_cache = []  # 缓存 (table_name, headers, data) 用于 API 写入
    for item in download_results:
        xlsx_bytes = item["xlsx_bytes"]
        table_name = item["table_name"]
        try:
            headers, data = read_xlsx_bytes(xlsx_bytes)
            row_count = write_to_db(DB_PATH, table_name, headers, data)
            total_imported += row_count
            imported_tables.append(table_name)
            table_data_cache.append((table_name, headers, data))
            logger.info(f"    {table_name}: {row_count} 行")
        except Exception as e:
            logger.warning(f"    导入失败 {table_name}: {e}")

    # 5. API 优先写入远程数据库，失败则回退 FTP 上传
    api_ok = False
    if _db_writer is not None:
        api_ok = True
        for table_name, headers, data in table_data_cache:
            try:
                if not data:
                    raise Exception(f"解析后无数据行: {table_name}")
                str_data = [[str(v) if v is not None else None for v in row] for row in data]
                # 主键：用 _choose_pk_columns 保证唯一，避免 upsert 静默塌缩；
                # 凑不出唯一键时抛出明确异常（被下方 except 捕获并标记 API 失败，不塌缩）
                pk_cols = _choose_pk_columns(headers, data, table_name)
                api_result = _db_writer.write_data(
                    db=DB_NAME,
                    table=table_name,
                    columns=headers,
                    rows=str_data,
                    mode="upsert",
                    pk_columns=pk_cols if headers else None,
                )
                api_rows = api_result.get("rows_written", 0)
                if api_rows == 0:
                    raise Exception(f"API 返回 0 行写入: {table_name}")
                logger.info(f"  [API] {table_name}: {api_rows} rows")
            except Exception as e:
                logger.error(f"  [API] {table_name} 写入失败: {e}")
                api_ok = False
        if api_ok:
            logger.info("  [API] 远程写入完成，跳过 FTP 上传")
        else:
            logger.warning("  [API] 部分表写入失败，回退到 FTP 上传")

    if not api_ok:
        logger.warning("  [API] 部分表写入失败，数据已保留在本地 SQLite")

    # 释放缓存
    del table_data_cache
    gc.collect()

    # 6. 清理本地 xlsx 文件
    deleted = _cleanup_sla_exports()
    logger.info(f"  清理文件: {deleted} 个")

    gc.collect()
    elapsed = time.time() - t_start
    logger.info(f"RAN UME SLA 同步完成: {total_imported} 行, {len(imported_tables)} 表, {elapsed:.1f}s")
    return {
        "success": True,
        "downloaded": len(download_results),
        "total_rows": total_imported,
        "tables": imported_tables,
        "api_ok": api_ok,
        "ftp_uploaded": False,
        "files_cleaned": deleted,
        "elapsed_seconds": round(elapsed, 2),
    }


# ============================================================
# KPI 数据读取函数
# ============================================================

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
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if not cursor.fetchone():
        return None
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    existing_cols = {row[1] for row in cursor.fetchall()}
    safe_col = column_name.replace('"', '""')
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
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if not cursor.fetchone():
        return None
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    existing_cols = {row[1] for row in cursor.fetchall()}
    safe_col = column_name.replace('"', '""')
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


# ============================================================
# WOs SLA 详细数据读取
# ============================================================

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


# ============================================================
# WOs SLA achievement Report 更新
# ============================================================

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


# ============================================================
# 条件格式化
# ============================================================

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


# ============================================================
# 导出 WithoutSLATTDetails
# ============================================================

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


# ============================================================
# 清理旧文件
# ============================================================

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


# ============================================================
# 导出函数
# ============================================================

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


# ============================================================
# FTP 上传/下载
# ============================================================

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


# ============================================================
# 模板文件自举（项目自包含，不依赖外部文件）
# ============================================================



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


# ============================================================
# 入口函数 3: Contract KPIs 报表更新（P2#8 拆分：原 203 行 → 单一职责助手 + 编排）
# ============================================================

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

        elapsed = time.time() - t_start
        logger.info(f"Contract KPIs 报表更新完成: {elapsed:.1f}s")
        return {"success": True, "daily_rows_updated": updated_daily, "exported_files": exported_count, "elapsed_seconds": round(elapsed, 2)}


# ============================================================
# 统一同步入口（SLA 同步 + Contract KPIs 报表更新）
# ============================================================

def run_full_sync():
    """完整同步流程：先执行 SLA 指标同步，再执行 Contract KPIs 报表更新。"""
    total_start = time.time()
    logger.info("=" * 60)
    logger.info("完整同步开始: SLA 同步 + Contract KPIs 报表更新")
    logger.info("=" * 60)

    # 清理上次异常退出残留的临时文件
    cleanup_stale_tmp_files(DATA_DIR)

    result = {"success": True}

    # Step 1: SLA 同步
    logger.info("\n----- Step 1/2: RAN UME SLA 同步 -----")
    sla_stats = run_ms_sla_sync()
    result["sla_sync"] = sla_stats
    if not sla_stats.get("success"):
        logger.warning("SLA 同步失败，继续执行报表更新...")
        result["success"] = False

    # Step 2: Contract KPIs 报表更新
    logger.info("\n----- Step 2/2: Contract KPIs 报表更新 -----")
    report_stats = run_contract_kpis_report()
    result["report"] = report_stats
    if not report_stats.get("success"):
        logger.warning("Contract KPIs 报表更新失败")
        result["success"] = False

    elapsed = time.time() - total_start
    logger.info("=" * 60)
    logger.info(f"完整同步结束: {elapsed:.1f}s")
    logger.info("=" * 60)
    return result


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ms_sla_service>: exception swallowed", exc_info=True)
        pass
    total_start = time.time()
    print(f"[MAIN] MS SLA service started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[MAIN] Data dir: {DATA_DIR}")
    print(f"[MAIN] DB: {DB_PATH}")

    mode = sys.argv[1] if len(sys.argv) > 1 else "full"

    if mode == "full":
        stats = run_full_sync()
        print(f"\n[MAIN] Full sync completed in {time.time() - total_start:.1f}s")

    elif mode == "sync":
        stats = run_ms_sla_sync()
        print(f"\n[MAIN] SLA sync completed:")
        if stats.get("success"):
            print(f"  Downloaded: {stats['downloaded']} files")
            print(f"  Imported: {stats['total_rows']} rows")
            print(f"  Tables: {stats['tables']}")
            print(f"  FTP: {'OK' if stats.get('ftp_uploaded') else 'FAILED'}")
        else:
            print(f"  Error: {stats.get('error')}")

    elif mode == "report":
        stats = run_contract_kpis_report()
        print(f"\n[MAIN] Contract KPIs report completed:")
        if stats.get("success"):
            print(f"  Daily rows: {stats['daily_rows_updated']}")
            print(f"  Exported: {stats['exported_files']} files")
        else:
            print(f"  Error: {stats.get('error')}")

    elif mode == "help":
        print("Usage: python ms_sla_service.py [mode]")
        print("  modes:")
        print("    full     Complete sync: SLA sync + Contract KPIs report (default)")
        print("    sync     Run RAN UME SLA sync only")
        print("    report   Run Contract KPIs report only")

    else:
        print(f"[MAIN] Unknown mode: {mode}, use 'full', 'sync', or 'report'")

    total_elapsed = time.time() - total_start
    print(f"\n[MAIN] Total elapsed: {total_elapsed:.2f} seconds")
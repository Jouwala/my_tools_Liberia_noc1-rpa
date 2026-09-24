# -*- coding: utf-8 -*-
"""
Download data from SFTP, then generate Comsumables & SpareParts
Inbound&Outbound&Inventory Excel files with Summary images.

Pipeline:
  sftp_download() → load_data() → apply_exclude_to_details()（按 in&out_exclude.xlsx
  剔除指定单据行并写回明细）→ apply_status_filters()（出库剔除 Status=WaitingForUpdate）
  → apply_inventory_fields()（用 inventory 的 Material Name / Material Type 覆盖明细并写回）
  → preprocess() → build_lookup() → fill_missing()
  → generate_report() (Excel + Summary PNG image)
"""
import pandas as pd
import numpy as np
import paramiko
import stat
import os
import shutil
import math
import unicodedata
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins
from openpyxl import load_workbook
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ==============================================================================
# Config
# ==============================================================================
_SCRIPT_DIR = Path(__file__).resolve().parent
# my_app 数据根：backend/services/sp_report_gen -> my_app
_APP_ROOT = _SCRIPT_DIR.parent.parent.parent
# 报表数据统一存放 my_app/data/sp_email（原始下载数据在 data/ 子目录）
DATA_DIR = str(_APP_ROOT / 'data' / 'sp_email' / 'data')
OUT_DIR = str(_APP_ROOT / 'data' / 'sp_email')
EXCLUDE_WAREHOUSE = 'Liberia Monrovia material warehouse'

INB_PATH = f'{DATA_DIR}/inband_details.xlsx'
INV_PATH = f'{DATA_DIR}/inventory_details.xlsx'
OUTB_PATH = f'{DATA_DIR}/outband_details.xlsx'
# 转仓明细：只进 SP Details Report（Transfer / Transfer Return 两个 sheet），不参与
# Inbound&Outbound&Inventory 报表统计
TRANSFER_PATH = f'{DATA_DIR}/transfer_details.xlsx'
TRANSFER_RETURN_PATH = f'{DATA_DIR}/transfer_return_details.xlsx'

# 原始快照：下载后、任何过滤之前原样复制一份 <明细名>_source.xlsx。
# SP Details Report（邮件附件 + 页面 ?page=sp_details）读这份未过滤数据；
# *_details.xlsx 仍是 Step 2.1~2.5 处理过的，供 SpareParts/Comsumables 报表与下游任务用。
RAW_SUFFIX = '_source'
DETAIL_PATHS = (INB_PATH, INV_PATH, OUTB_PATH, TRANSFER_PATH, TRANSFER_RETURN_PATH)


def raw_source_path(detail_path):
    """明细路径 -> 原始快照路径（inband_details.xlsx -> inband_details_source.xlsx）。"""
    root, ext = os.path.splitext(detail_path)
    return f'{root}{RAW_SUFFIX}{ext}'


# SFTP config
SFTP_HOST = "10.100.20.11"
SFTP_PORT = 22
SFTP_USER = "ubuntu"
SFTP_PASS = "UbuntU1!2@3#4$"

# /home/ubuntu/sp 下每个数据集一个目录，结构为
#   sp/<目录名>/<yyyymmdd>/<yyyymmddHHMMSSfff>/<文件名>.xlsx
# 取「最新的、且文件名匹配」的那一份（2026-09-16 用户指定）。
# 本地一律落到 *_details.xlsx —— 下游 sp_email_details / sp_online / sp_material_summary
# 都依赖这些本地文件名，不要改。
SFTP_FOLDERS = {
    "inbound": {
        "filename": "inbound.xlsx",
        "local_path": "data/inband_details.xlsx",
    },
    "outbound": {
        "filename": "outbound.xlsx",
        "local_path": "data/outband_details.xlsx",
    },
    "inventory_management": {
        "filename": "inventory_management.xlsx",
        "local_path": "data/inventory_details.xlsx",
    },
    "wh_transfer": {
        "filename": "wh_transfer.xlsx",
        "local_path": "data/transfer_details.xlsx",
    },
    "wh_transfer_return": {
        "filename": "wh_transfer_return.xlsx",
        "local_path": "data/transfer_return_details.xlsx",
    },
}

SFTP_SPECIAL = {
    "ocrule": {
        "remote_folder": "OCAuto/OCAutoOutput",
        "local_path": "data/ocrule_details.xlsx",
        "search_func": "find_latest_ocrule_csv_recursive",
        "convert_to_excel": True,
    },
    # transfer（WH Transfer）2026-09-16 起改由 SFTP_FOLDERS 处理
    # （sp/wh_transfer/<日期>/<时间戳>/wh_transfer.xlsx），不再走旧的 sp-wh_transfer 递归搜索。
}

CS_INBOUND_COLS = ['Inbound No.', 'Status', 'Inbound Type', 'Warehouse Name', 'Material No.',
                   'Serial No.', 'Material Name', 'Domain', 'Inbound Qty',
                   'Unit', 'Location No.', 'Inbound Time']
SP_INBOUND_COLS = ['Inbound No.', 'Status', 'Inbound Type', 'Warehouse Name', 'Material No.',
                   'Serial No.', 'Material Name', 'Domain', 'Material Type',
                   'Inbound Qty', 'Unit', 'Inbound Time']

CS_OUTBOUND_COLS = ['Outbound No.', 'Status', 'Warehouse Name', 'Outbound Type', 'Recipient',
                    'Recipient Phone', 'Request Time', 'Related Ticket Type',
                    'Description', 'Domain', 'Outbound Time', 'Borrow Duration',
                    'Related Ticket No.', 'Serial No.', 'Material No.',
                    'Material Name', 'Outbound Qty', 'Unit']
SP_OUTBOUND_COLS = ['Outbound No.', 'Status', 'Warehouse Name', 'Outbound Type',
                    'Recipient', 'Recipient Phone', 'Request Time',
                    'Related Ticket Type', 'Description', 'Domain', 'Create Time',
                    'Outbound Time', 'Closed Time', 'Borrow Duration',
                    'Related Ticket No.', 'Serial No.', 'Material No.',
                    'Material Name', 'Outbound Qty', 'Unit', 'Return Serial No.']

INVENTORY_COLS = ['Serial No.', 'Material No.', 'Material Name', 'Material Status',
                  'Warehouse Name', 'Domain', 'Storage Age', 'Stock Qty', 'Unit ',
                  'Location Name']

# ------------------------------------------------------------------------------
# 补库建议（Summary-Current 汇总表右侧的附加列，按 Material Name 与主表同行对齐）
# ------------------------------------------------------------------------------
# 出库明细中剔除的异常单据：不计入历史消耗
REPLENISH_EXCLUDE_ORDERS = ('SPOB202608160004', 'SPOB202609120014')
# 历史消耗中剔除的出库类型：Repair Outbound（报修出库）不算真实消耗
REPLENISH_EXCLUDE_OUTBOUND_TYPE = 'Repair Outbound'
# 历史消耗窗口（月）：不再写死，改用「起算月 → 当前月」的自然月个数（2026-09-24 起）。
#
# 为什么改：原值 9.5 是「出库数据当前覆盖 9.5 个月」的**一次性快照**，会随时间失效 ——
# 每过一个月数据就多覆盖一个月，分母却不变，月均消耗被系统性高估。
#
# 口径（与用户确认）：
#   分母 = 当前年月的月份序号 − 起算月的月份序号 + 1，即「含首尾的自然月个数」。
#   例：2026-09 跑 → 9 - 1 + 1 = 9；2026-10 跑 → 10。
#   已过天数不折算（不用 8.77 这种小数），这样同一个自然月内分母恒定，
#   月度内跨天对账不会因小数位漂移而"数字每天都在变"。
#
# 为什么固定 2026-01 而不是滚动 9 个月：出库明细最早数据即 2026-01-07，
# 历史不会回补，固定起算点让分母只增不减、口径可追溯。
REPLENISH_HISTORY_START = (2026, 1)
# 兜底值：仅当起算月晚于当前月（时钟异常/被改配置）时使用，避免出现 0 或负分母
REPLENISH_HISTORY_MONTHS_FALLBACK = 1
# 安全库存 = 6 个月历史平均消耗后向上取整（2026-09-19 起 Avg 保留小数，Safety 取整）
REPLENISH_SAFETY_MONTHS = 6
# 补库建议的列（全英文，避免报表出现中文）；Remark 紧跟在 Safety Stock 之后
REPLENISH_COLS = ['Material Name', 'Avg Monthly Consumption', 'Safety Stock', 'Remark',
                  'Replenishment Qty', 'Alert Level']
# 并入 Summary-Current 主表时追加的列（不含 Material Name，它是主表已有的键）
REPLENISH_EXTRA_COLS = REPLENISH_COLS[1:]
REPLENISH_ALERT_COL = 'Alert Level'
REPLENISH_REMARK_COL = 'Remark'
# 月均消耗为 0 的物料按「故障率」备件处理：安全库存 = 主表 Inbound/Outbound/Inventory
# 三列最大值的 20% 向上取整（2026-09-19 起，替代旧的保底 1），Remark 记 Failure Rate
REPLENISH_ZERO_CONSUMPTION_SAFETY_PCT = 0.2
REMARK_FAILURE_RATE = 'Failure Rate'
REMARK_ACTUAL_CONSUMPTION = 'Actual Consumption'
# Avg Monthly Consumption 保留 2 位小数（2026-09-19 起不再取整）；
# Safety Stock = ceil(6 x Avg)，与 Replenishment Qty 同为向上取整的整数列
REPLENISH_DEC_COLS = ('Avg Monthly Consumption',)
REPLENISH_INT_COLS = ('Safety Stock', 'Replenishment Qty')
# 报表上方的口径说明（Excel 表头上方、PNG 标题下方）：拆成多行，否则超过合并区的显示宽度会被裁掉。
#
# ⚠️ 必须以**函数**形式提供，不能是模块级常量元组：历史月数已改为动态（见 history_months），
#    常量在 import 时就求值，跨月跑的长驻进程会一直印着第一次的月数。
# ⚠️ 返回的行数 = Summary-Current 表头之前的说明行数，改动行数必须同步
#    backend/services/sp_report_service.py 的 SHEET_CONFIG["Summary-Current"]["header_row"]（现为 7）。
def replenish_notes(as_of=None):
    """报表口径说明行（4 行）。行数变动必须同步 SHEET_CONFIG 的 header_row。"""
    months = history_months(as_of)
    start_month = f'{REPLENISH_HISTORY_START[0]}-{REPLENISH_HISTORY_START[1]:02d}'
    return (
        'Replenishment basis:  Excluded orders ' + ' / '.join(REPLENISH_EXCLUDE_ORDERS)
        + f'  |  Excluded outbound type {REPLENISH_EXCLUDE_OUTBOUND_TYPE}'
        + f'  |  History {months} months ({start_month} to current month, inclusive)'
        + f'  |  Safety Stock = ceil({REPLENISH_SAFETY_MONTHS} x Avg Monthly Consumption)',
        f'Zero-consumption materials (Remark = {REMARK_FAILURE_RATE}): '
        + f'Safety Stock = ceil({int(REPLENISH_ZERO_CONSUMPTION_SAFETY_PCT * 100)}%'
        + ' x max(Inbound Qty, net Outbound Qty, Inventory Qty))',
        'Outbound split:  Outbound Repair Qty = Repair Outbound type only'
        + '  |  Outbound Site Qty = Outbound Qty - Outbound Repair Qty'
        + '  (they always sum to Outbound Qty)'
        + '  |  Replenishment Qty = Safety Stock - Inventory Qty (<= 0 left blank, rounded up)'
        + '  |  Alert Level = Inventory Qty / Safety Stock'
        + '  |  Note: the Outbound Qty column still includes the 2 excluded orders'
        + f' and {REPLENISH_EXCLUDE_OUTBOUND_TYPE}',
        f'Remark: {REMARK_FAILURE_RATE} = Avg Monthly Consumption is 0'
        + f'  |  {REMARK_ACTUAL_CONSUMPTION} = Avg Monthly Consumption > 0',
    )
ALERT_URGENT = 'Urgent Replenish'
ALERT_REPLENISH = 'Replenish'
ALERT_EXCESS = 'Excess'
# 预警级别 → (背景色, 文字色)，Excel 与 PNG 共用
ALERT_COLORS = {
    ALERT_URGENT: ((255, 199, 206), (156, 0, 6)),
    ALERT_REPLENISH: ((255, 235, 156), (156, 101, 0)),
    ALERT_EXCESS: ((198, 239, 206), (0, 97, 0)),
}

# ==============================================================================
# Cached Styles
# ==============================================================================
_SIDE_THIN = Side(style='thin', color='B4C6E7')
SIDE_BOTTOM_THICK = Side(style='medium', color='4472C4')
BORDER_HEADER = Border(left=_SIDE_THIN, right=_SIDE_THIN, top=_SIDE_THIN, bottom=SIDE_BOTTOM_THICK)
BORDER_CELL = Border(left=_SIDE_THIN, right=_SIDE_THIN, top=_SIDE_THIN, bottom=_SIDE_THIN)
BORDER_TOTAL = Border(left=_SIDE_THIN, right=_SIDE_THIN, top=SIDE_BOTTOM_THICK, bottom=SIDE_BOTTOM_THICK)

FONT_HEADER = Font(name='Calibri', bold=True, size=11, color='FFFFFF')
FONT_CELL = Font(name='Calibri', size=10)
FONT_TOTAL = Font(name='Calibri', bold=True, size=11, color='1F3864')
FONT_TITLE = Font(name='Calibri', bold=True, size=14, color='1F3864')
FONT_SUBTITLE = Font(name='Calibri', size=9, color='808080')
FONT_FILTER = Font(name='Calibri', size=9, color='4472C4')

FILL_HEADER = PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')
FILL_TOTAL = PatternFill(start_color='D6DCE4', end_color='D6DCE4', fill_type='solid')
FILL_ZEBRA = PatternFill(start_color='F2F2F2', end_color='F2F2F2', fill_type='solid')
FILL_WHITE = PatternFill(start_color='FFFFFF', end_color='FFFFFF', fill_type='solid')

FILL_RED = PatternFill(start_color='FFC7CE', end_color='FFC7CE', fill_type='solid')
FONT_RED = Font(name='Calibri', size=10, color='9C0006')
FILL_YELLOW = PatternFill(start_color='FFEB9C', end_color='FFEB9C', fill_type='solid')
FONT_YELLOW = Font(name='Calibri', size=10, color='9C6500')
FILL_GREEN = PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
FONT_GREEN = Font(name='Calibri', size=10, color='006100')

ALIGN_HEADER = Alignment(horizontal='center', vertical='center', wrap_text=True)
ALIGN_CELL = Alignment(vertical='center', wrap_text=False)
ALIGN_NUM = Alignment(horizontal='right', vertical='center')
ALIGN_LEFT = Alignment(horizontal='left', vertical='center')

NUM_FMT_INT = '#,##0'
NUM_FMT_DEC = '#,##0.00'

SHEET_COLORS = {
    'Summary': '2F5496',
    'Inbound': '548235',
    'Outbound': 'BF8F00',
    'Inventory': '843C0C',
}


def _display_width(text):
    """估算文本显示宽度：CJK 全角字符按 2 个半角字符宽计算。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1 for ch in str(text))


def _fmt_replenish_value(val):
    """补库建议取整列的数值文本：向上取整后的整数（千分位）；空值（NaN）留白不显示。"""
    if val is None or pd.isna(val):
        return ''
    if isinstance(val, (int, float, np.integer, np.floating)):
        return f'{int(math.ceil(float(val))):,}'
    return str(val)


def _fmt_replenish_dec(val):
    """补库建议小数列（Avg Monthly Consumption）的数值文本：保留 2 位小数（千分位）。"""
    if val is None or pd.isna(val):
        return ''
    if isinstance(val, (int, float, np.integer, np.floating)):
        return f'{float(val):,.2f}'
    return str(val)


def _fmt_replenish_cell(col, val):
    """补库建议数值列的显示文本：小数列 2 位，其余（Replenishment Qty）向上取整。"""
    if col in REPLENISH_DEC_COLS:
        return _fmt_replenish_dec(val)
    return _fmt_replenish_value(val)


def _fmt_summary_cell(col, val):
    """Summary-Current 单元格的显示文本。

    Avg Monthly Consumption：保留 2 位小数千分位；
    Safety Stock / Replenishment Qty：向上取整的整数千分位（Replenishment Qty 空值留白，<= 0 不显示）；
    主表原有列：整数千分位，空值按 0 显示。
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return '' if col in REPLENISH_EXTRA_COLS else '0'
    if col in REPLENISH_DEC_COLS:
        return _fmt_replenish_dec(val)
    if col in REPLENISH_INT_COLS:
        return _fmt_replenish_value(val)
    if isinstance(val, (int, float, np.integer, np.floating)):
        return f'{int(val):,}'
    return str(val)

# ==============================================================================
# SFTP Download Functions
# ==============================================================================
def _find_latest_subfolder(sftp, base_path):
    """找到 base_path 下修改时间最新的子目录"""
    dirs = []
    try:
        for f in sftp.listdir_attr(base_path):
            if stat.S_ISDIR(f.st_mode):
                dirs.append(f)
    except IOError:
        return None
    if not dirs:
        return None
    dirs.sort(key=lambda x: x.st_mtime, reverse=True)
    return dirs[0].filename


def _find_latest_excel_in_nested(sftp, folder_path):
    """进入日期文件夹后，再进入最新的时间戳文件夹，再找 Excel 文件"""
    latest_date = _find_latest_subfolder(sftp, folder_path)
    if not latest_date:
        return None
    date_path = f"{folder_path}/{latest_date}"

    latest_time = _find_latest_subfolder(sftp, date_path)
    if not latest_time:
        return None
    time_path = f"{date_path}/{latest_time}"

    files = []
    try:
        for f in sftp.listdir_attr(time_path):
            if not stat.S_ISDIR(f.st_mode) and f.filename.lower().endswith(('.xlsx', '.xls')):
                files.append(f)
    except IOError:
        return None
    if not files:
        return None
    files.sort(key=lambda x: x.st_mtime, reverse=True)
    return f"{time_path}/{files[0].filename}"


def _list_subdirs(sftp, path):
    """列出目录下的子目录名，按修改时间倒序（最新在前）。读不到返回 []。"""
    try:
        dirs = [f for f in sftp.listdir_attr(path) if stat.S_ISDIR(f.st_mode)]
    except IOError:
        return []
    dirs.sort(key=lambda x: x.st_mtime, reverse=True)
    return [d.filename for d in dirs]


def _find_latest_named_excel(sftp, folder_path, filename, max_dates=5, max_slots=3):
    """在 sp/<name>/<yyyymmdd>/<yyyymmddHHMMSSfff>/<name>.xlsx 结构里，
    取**文件名精确匹配**（忽略大小写）的最新一份。

    从最新的日期目录往前找（最多 max_dates 天、每天最多 max_slots 个时间戳目录），
    命中即返回，避免对整棵树做全量递归。
    """
    target = filename.lower()
    for date_dir in _list_subdirs(sftp, folder_path)[:max_dates]:
        date_path = f"{folder_path}/{date_dir}"
        for ts_dir in _list_subdirs(sftp, date_path)[:max_slots]:
            ts_path = f"{date_path}/{ts_dir}"
            try:
                names = [f.filename for f in sftp.listdir_attr(ts_path)
                         if not stat.S_ISDIR(f.st_mode)]
            except IOError:
                continue
            for n in names:
                if n.lower() == target:
                    return f"{ts_path}/{n}"
    return None


def _find_latest_ocrule_csv_recursive(sftp, folder_path):
    """递归搜索包含 OCRule 的最新 csv 文件"""
    all_csv = []

    def scan(path):
        try:
            for f in sftp.listdir_attr(path):
                full = f"{path}/{f.filename}"
                if stat.S_ISDIR(f.st_mode):
                    scan(full)
                elif "ocrule" in f.filename.lower() and f.filename.lower().endswith(".csv"):
                    all_csv.append((f, full))
        except IOError:
            pass

    scan(folder_path)
    if not all_csv:
        return None
    all_csv.sort(key=lambda x: x[0].st_mtime, reverse=True)
    return all_csv[0][1]


def _find_latest_transfer_xlsx_recursive(sftp, folder_path):
    """递归搜索包含 sp-wh_transfer 的最新 xlsx 文件"""
    all_xlsx = []

    def scan(path):
        try:
            for f in sftp.listdir_attr(path):
                full = f"{path}/{f.filename}"
                if stat.S_ISDIR(f.st_mode):
                    scan(full)
                elif "sp-wh_transfer" in f.filename.lower() and f.filename.lower().endswith(('.xlsx', '.xls')):
                    all_xlsx.append((f, full))
        except IOError:
            pass

    scan(folder_path)
    if not all_xlsx:
        return None
    all_xlsx.sort(key=lambda x: x[0].st_mtime, reverse=True)
    return all_xlsx[0][1]


_SFTP_SEARCH_FUNCS = {
    "find_latest_ocrule_csv_recursive": _find_latest_ocrule_csv_recursive,
    "find_latest_transfer_xlsx_recursive": _find_latest_transfer_xlsx_recursive,
}


def _sftp_download_file(sftp, remote_file, local_path, convert_to_excel=False):
    """下载文件，可选择是否从 CSV 转换为 Excel"""
    # 相对路径统一解析到 DATA_DIR 下，避免依赖进程 cwd
    if not os.path.isabs(local_path):
        local_path = os.path.join(DATA_DIR, os.path.basename(local_path))
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    if convert_to_excel:
        temp_csv = f"{DATA_DIR}/temp.csv"
        sftp.get(remote_file, temp_csv)
        df = pd.read_csv(temp_csv)
        df.to_excel(local_path, index=False)
        os.remove(temp_csv)
    else:
        sftp.get(remote_file, local_path)


def sftp_download():
    """Download all data files from SFTP server."""
    print("=== SFTP Download ===")
    # 2026-09-20 加固（同 get_sp_table._connect_sftp 事故）：原写法 Transport((host,port))
    # 无连接超时、无 channel 读超时——服务端应用层挂死时 channel 读永久阻塞，
    # worker 卡死后整组任务 pending。改为：连接 30s 超时 + keepalive + channel 读 180s 超时。
    import socket as _socket
    _sock = _socket.create_connection((SFTP_HOST, SFTP_PORT), timeout=30)
    client = paramiko.Transport(_sock)
    client.set_keepalive(30)
    client.connect(username=SFTP_USER, password=SFTP_PASS)
    sftp = paramiko.SFTPClient.from_transport(client)
    try:
        _chan = sftp.get_channel()
        if _chan is not None:
            _chan.settimeout(180)
    except Exception as _e:
        print(f"  [WARN] SFTP channel 超时设置失败（退回无超时模式）: {_e}")

    # Special files
    for name, cfg in SFTP_SPECIAL.items():
        search_fn = _SFTP_SEARCH_FUNCS[cfg["search_func"]]
        remote = search_fn(sftp, cfg["remote_folder"])
        if remote:
            _sftp_download_file(sftp, remote, cfg["local_path"], cfg["convert_to_excel"])
            print(f"  [OK] {name}: {remote} → {cfg['local_path']}")
        else:
            print(f"  [WARN] {name}: file not found")

    # Regular folders: sp/<目录名>/<yyyymmdd>/<时间戳>/<文件名>.xlsx —— 取最新且文件名匹配的一份
    for folder, cfg in SFTP_FOLDERS.items():
        remote = _find_latest_named_excel(sftp, f"sp/{folder}", cfg["filename"])
        if remote:
            _sftp_download_file(sftp, remote, cfg["local_path"])
            print(f"  [OK] {folder}: {remote} → {cfg['local_path']}")
        else:
            print(f"  [WARN] {folder}: {cfg['filename']} not found under sp/{folder}")

    sftp.close()
    client.close()
    print("SFTP download done.\n")


# ==============================================================================
# load_data
# ==============================================================================
def load_data():
    inb = pd.read_excel(INB_PATH)
    inv = pd.read_excel(INV_PATH)
    outb = pd.read_excel(OUTB_PATH)
    return inb, inv, outb


# ==============================================================================
# exclude rules - 按 in&out_exclude.xlsx 剔除指定单据行（生成报告前执行）
# ==============================================================================
# 明细侧匹配列：  Inbound  -> Inbound No.; Material No.; Serial No.; Inbound Qty
#                Outbound -> Outbound No.; Material No.; Serial No.; Outbound Qty
# 排除表侧列（sheet「3_剔除单据Serial明细」）：
#                方向; 单据号; 单据类型; Serial No.; 物料号; 数量; 仓库
# 命中口径（二选一即剔除）：
#   1) full  = (No, Material No., Serial No., Qty) 四字段全等
#   2) loose = (No, Serial No.) 单据号 + Serial 命中即剔除（物料号/数量对不上时兜底）
EXCLUDE_FILE = f'{DATA_DIR}/in&out_exclude.xlsx'
EXCLUDE_SHEET = '3_剔除单据Serial明细'
# 表头行自动探测：sheet 顶部有标题行 + 空行，扫描前 10 行找含指定列名的那一行
EXCLUDE_HEADER_SCAN_ROWS = 10
_EXCLUDE_HEADER_KEYS = ('单据号', 'Serial No.', '物料号', '数量')

# (明细名, 明细路径, No 列, Qty 列, 方向关键字)
_EXCLUDE_SPECS = [
    ('inbound', INB_PATH, 'Inbound No.', 'Inbound Qty', '入库'),
    ('outbound', OUTB_PATH, 'Outbound No.', 'Outbound Qty', '出库'),
]


def _norm_excl_value(v):
    """归一化单个匹配值：去空格；数字统一成最简形式（1.0 -> 1，4.50 -> 4.5）。

    明细里物料号常带前导零（033030100337），排除表里被 Excel 存成数字（33030100337），
    故纯数字串必须统一成 int 形式再比较，否则大面积不命中。
    """
    if v is None:
        return ''
    s = str(v).strip()
    if s == '' or s.lower() in ('nan', 'none', 'nat'):
        return ''
    try:
        f = float(s)
    except ValueError:
        return s
    if f == int(f):
        return str(int(f))
    return ('%.6f' % f).rstrip('0').rstrip('.')


def load_exclude_rules(path=EXCLUDE_FILE):
    """读取剔除清单。

    返回 {'入库': {'full': set((no, mat, serial, qty)), 'loose': set((no, serial))},
           '出库': {...}}
    文件缺失 / sheet 缺失 / 列缺失 → 打印 WARN 并返回空规则（不阻断主流程）。
    """
    def _empty():
        return {'full': set(), 'loose': set()}

    empty = {'入库': _empty(), '出库': _empty()}
    if not os.path.isfile(path):
        print(f'[Exclude][WARN] 剔除清单不存在，跳过剔除: {path}')
        return empty
    try:
        raw = pd.read_excel(path, sheet_name=EXCLUDE_SHEET, header=None,
                            nrows=EXCLUDE_HEADER_SCAN_ROWS)
        hdr_row = None
        for i in range(len(raw)):
            vals = {str(v).strip() for v in raw.iloc[i].tolist()}
            if all(k in vals for k in _EXCLUDE_HEADER_KEYS):
                hdr_row = i
                break
        if hdr_row is None:
            print(f'[Exclude][WARN] 剔除清单未找到表头行（需含 {list(_EXCLUDE_HEADER_KEYS)}），跳过剔除')
            return empty
        df = pd.read_excel(path, sheet_name=EXCLUDE_SHEET, header=hdr_row)
    except Exception as e:
        print(f'[Exclude][WARN] 读取剔除清单失败({e})，跳过剔除')
        return empty

    need = ['方向', '单据号', 'Serial No.', '物料号', '数量']
    missing = [c for c in need if c not in df.columns]
    if missing:
        print(f'[Exclude][WARN] 剔除清单缺少列 {missing}（实际列: {list(df.columns)}），跳过剔除')
        return empty

    rules = {'入库': _empty(), '出库': _empty()}
    skipped = 0
    for _, row in df.iterrows():
        no = _norm_excl_value(row['单据号'])
        serial = _norm_excl_value(row['Serial No.'])
        if not no:            # 无单据号 → 无法定位，跳过
            skipped += 1
            continue
        direction = str(row['方向']).strip()
        d = direction.lower()
        if '入' in direction or 'in' in d:
            bucket = rules['入库']
        elif '出' in direction or 'out' in d:
            bucket = rules['出库']
        else:
            skipped += 1
            continue
        qty = _norm_excl_value(row['数量'])
        if serial:
            bucket['loose'].add((no, serial))
        if qty and serial:
            bucket['full'].add((no, _norm_excl_value(row['物料号']), serial, qty))
    print(f'[Exclude] 规则载入: 入库 full={len(rules["入库"]["full"])}/loose={len(rules["入库"]["loose"])}, '
          f'出库 full={len(rules["出库"]["full"])}/loose={len(rules["出库"]["loose"])}'
          f'{f", 忽略 {skipped} 条" if skipped else ""}')
    return rules


def drop_excluded_rows(df, rule, no_col, qty_col):
    """按 full(No+Mat+Serial+Qty) 或 loose(No+Serial) 剔除命中行。

    返回 (新 df, 精确命中数, 仅 loose 命中数)。
    """
    if not rule or df is None or df.empty or not (rule['full'] or rule['loose']):
        return df, 0, 0
    for c in (no_col, 'Material No.', 'Serial No.', qty_col):
        if c not in df.columns:
            print(f'[Exclude][WARN] 明细缺少列 "{c}"，跳过剔除')
            return df, 0, 0

    nos = df[no_col].map(_norm_excl_value)
    mats = df['Material No.'].map(_norm_excl_value)
    sers = df['Serial No.'].map(_norm_excl_value)
    qtys = df[qty_col].map(_norm_excl_value)

    full, loose = rule['full'], rule['loose']
    mask = []
    n_full = n_loose_only = 0
    for no, mat, ser, qty in zip(nos, mats, sers, qtys):
        hit_full = (no, mat, ser, qty) in full
        hit_loose = (not hit_full) and bool(ser) and ((no, ser) in loose)
        if hit_full:
            n_full += 1
        elif hit_loose:
            n_loose_only += 1
        mask.append(hit_full or hit_loose)

    if not any(mask):
        return df, 0, 0
    return df.loc[[not m for m in mask]].reset_index(drop=True), n_full, n_loose_only


def apply_exclude_to_details(inb, outb):
    """下载后、生成报告前执行：剔除指定单据行并把结果写回明细 xlsx（下游任务同口径）。

    返回 (inb, outb, stats)；写回失败只 WARN（文件被 Excel 占用等），内存数据仍是已剔除的。
    """
    rules = load_exclude_rules()
    stats = {}
    if not (rules['入库']['full'] or rules['入库']['loose']
            or rules['出库']['full'] or rules['出库']['loose']):
        return inb, outb, stats

    for name, path, no_col, qty_col, direction in _EXCLUDE_SPECS:
        df = inb if name == 'inbound' else outb
        new_df, n_full, n_loose = drop_excluded_rows(df, rules[direction], no_col, qty_col)
        dropped = n_full + n_loose
        stats[name] = dropped
        if dropped == 0:
            print(f'[Exclude] {name}: 无命中，保持原样（{len(df)} 行）')
            continue
        print(f'[Exclude] {name}: 剔除 {dropped} 行（精确 {n_full} + 单号&Serial 兜底 {n_loose}），'
              f'{len(df)} -> {len(new_df)} 行')
        # 写回保存（先写临时文件再原子替换，避免中断损坏原文件）
        if not _save_detail_xlsx(new_df, path):
            print(f'[Exclude][WARN] {name}: 写回失败，下游任务将使用未剔除的旧文件')
        if name == 'inbound':
            inb = new_df
        else:
            outb = new_df
    return inb, outb, stats


def _save_detail_xlsx(df, path):
    """把明细 df 原子写回 xlsx（先写 tmp 再 replace），成功返回 True。"""
    tmp = f'{path}.tmp.xlsx'
    try:
        df.to_excel(tmp, index=False)
        os.replace(tmp, path)
        print(f'[Save] 已保存 {path}')
        return True
    except Exception as e:
        print(f'[Save][WARN] 写回失败（{e}），下游任务将使用旧文件: {path}')
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


# ==============================================================================
# raw snapshot - 下载后先留一份未过滤数据，供 SP Details Report 使用
# ==============================================================================
def snapshot_raw_details():
    """把刚下载的明细原样复制成 *_details_source.xlsx（固定名，每次覆盖）。

    必须在 Step 2.1 之前调用——之后 *_details.xlsx 已经被就地过滤过了。
    单个文件复制失败只告警：下游读不到快照会回退用过滤后的明细，
    不能因为快照故障把整个报表任务拖挂。
    """
    print('=== Step 1.5: Raw Snapshot ===')
    for src in DETAIL_PATHS:
        if not os.path.exists(src):
            print(f'[Raw][WARN] 明细缺失，跳过快照: {src}')
            continue
        dst = raw_source_path(src)
        tmp = f'{dst}.tmp.xlsx'
        try:
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            print(f'[Raw] {os.path.basename(src)} -> {os.path.basename(dst)}')
        except Exception as e:
            print(f'[Raw][WARN] 快照失败（{e}），下游将回退读过滤后的明细: {dst}')
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass


# ==============================================================================
# status filter - 出库明细剔除 Status='WaitingForUpdate'
# ==============================================================================
# 从 SFTP 取回的 outband 明细里，WaitingForUpdate 是尚未生效的出库单，生成报表前剔除
OUTBOUND_DROP_STATUS = ('WaitingForUpdate',)


def drop_outbound_status(df, statuses=OUTBOUND_DROP_STATUS):
    """剔除出库明细中 Status 命中 statuses 的行，返回 (新 df, 剔除行数)。"""
    if df is None or df.empty or 'Status' not in df.columns:
        return df, 0
    targets = {str(s).strip().casefold() for s in statuses}
    mask = df['Status'].map(lambda v: str(v).strip().casefold() in targets)
    n = int(mask.sum())
    if n == 0:
        return df, 0
    return df.loc[~mask].reset_index(drop=True), n


def apply_status_filters(inb, outb):
    """出库明细剔除 WaitingForUpdate 并写回保存。返回 (inb, outb, stats)。"""
    new_outb, n = drop_outbound_status(outb)
    if n == 0:
        print('[Status] outbound: 无 WaitingForUpdate 行，保持原样')
        return inb, outb, {}
    print(f'[Status] outbound: 剔除 Status=WaitingForUpdate {n} 行，'
          f'{len(outb)} -> {len(new_outb)} 行')
    if not _save_detail_xlsx(new_outb, OUTB_PATH):
        print('[Status][WARN] outbound: 写回失败，下游任务将使用未过滤的旧文件')
    return inb, new_outb, {'outbound': n}


# ==============================================================================
# operation result filter - 剔除 Operation Result Status='Canceled' 的明细行
# ==============================================================================
# 2026-09-16 用户指定：入库 / 出库 / 转仓明细里 Operation Result Status='Canceled'
# 的都是已作废单据，不参与 SP Details Report，也不进 Inbound&Outbound&Inventory 报表。
# inventory_management 没有该列，不受影响。
OP_RESULT_COL = 'Operation Result Status'
OP_RESULT_DROP_STATUS = ('Canceled',)


def drop_operation_result_canceled(df, statuses=OP_RESULT_DROP_STATUS):
    """剔除 Operation Result Status 命中 statuses 的行，返回 (新 df, 剔除行数)。"""
    if df is None or df.empty or OP_RESULT_COL not in df.columns:
        return df, 0
    targets = {str(s).strip().casefold() for s in statuses}
    mask = df[OP_RESULT_COL].map(lambda v: str(v).strip().casefold() in targets)
    n = int(mask.sum())
    if n == 0:
        return df, 0
    return df.loc[~mask].reset_index(drop=True), n


def apply_operation_result_filter(inb, outb):
    """入库 / 出库明细剔除 Operation Result Status='Canceled' 并写回。返回 (inb, outb, stats)。"""
    new_inb, n_in = drop_operation_result_canceled(inb)
    if n_in:
        print(f'[OpResult] inbound: 剔除 Operation Result Status=Canceled {n_in} 行，'
              f'{len(inb)} -> {len(new_inb)} 行')
        if not _save_detail_xlsx(new_inb, INB_PATH):
            print('[OpResult][WARN] inbound: 写回失败，下游任务将使用未过滤的旧文件')
    else:
        print('[OpResult] inbound: 无 Canceled 行，保持原样')

    new_outb, n_out = drop_operation_result_canceled(outb)
    if n_out:
        print(f'[OpResult] outbound: 剔除 Operation Result Status=Canceled {n_out} 行，'
              f'{len(outb)} -> {len(new_outb)} 行')
        if not _save_detail_xlsx(new_outb, OUTB_PATH):
            print('[OpResult][WARN] outbound: 写回失败，下游任务将使用未过滤的旧文件')
    else:
        print('[OpResult] outbound: 无 Canceled 行，保持原样')

    stats = {}
    if n_in:
        stats['inbound'] = n_in
    if n_out:
        stats['outbound'] = n_out
    return new_inb, new_outb, stats


def apply_operation_result_filter_to_file(path, label):
    """对只用于 SP Details Report 的转仓明细文件就地过滤 Canceled 行并写回。

    文件缺失 / 无该列时只打印说明并返回 0，不影响主流程。
    """
    if not os.path.exists(path):
        print(f'[OpResult][WARN] {label}: 文件不存在，跳过（{path}）')
        return 0
    try:
        df = pd.read_excel(path)
    except Exception as e:
        print(f'[OpResult][WARN] {label}: 读取失败，跳过（{e}）')
        return 0
    if OP_RESULT_COL not in df.columns:
        print(f'[OpResult] {label}: 无 {OP_RESULT_COL} 列，保持原样')
        return 0
    new_df, n = drop_operation_result_canceled(df)
    if n == 0:
        print(f'[OpResult] {label}: 无 Canceled 行，保持原样')
        return 0
    print(f'[OpResult] {label}: 剔除 Operation Result Status=Canceled {n} 行，'
          f'{len(df)} -> {len(new_df)} 行')
    if not _save_detail_xlsx(new_df, path):
        print(f'[OpResult][WARN] {label}: 写回失败，下游任务将使用未过滤的旧文件')
    return n


# ==============================================================================
# material fields sync - Material Name 取数据库表 sp_material，Material Type 取 inventory
# ==============================================================================
# 物料主数据表 sp_material：由任务 sp_material_sync（每天 04:55）从 eFlow SP 接口
# 拉全量写入，字段 materialNo / materialName / materialType（PG 模式在 app schema）。
MATERIAL_TABLE = os.environ.get("SP_MATERIAL_TABLE", "sp_material")

_PROJECT_ROOT = Path(__file__).resolve().parents[3]      # my_app 根目录


def _read_database_url():
    """取 PG 连接串：环境变量 DATABASE_URL > backend/.env。取不到返回 None（回退 sqlite）。"""
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url:
        return url
    env_file = _PROJECT_ROOT / 'backend' / '.env'
    try:
        for line in env_file.read_text(encoding='utf-8').splitlines():
            if line.strip().startswith('DATABASE_URL='):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception as e:
        print(f'[MatSync][WARN] 读取 backend/.env 失败({e})')
    return None


def load_material_maps_from_db():
    """从数据库表 sp_material 读 {materialNo: materialName}、{materialNo: materialType}
    与 {materialName: domain}（2026-09-19 起，Summary-Current 的 Domain 列用）。

    PG（DATABASE_URL / backend/.env）优先，失败回退 sqlite db/app.db；
    都不可用或表不存在时返回 ({}, {}, {})，由调用方回退到 inventory。
    domain 列缺失时只丢 domain 映射，不影响 Name/Type（2026-09-19 防旧表无该列）。
    """
    def _pack(rows):
        name_lut, type_lut, domain_lut = {}, {}, {}
        for no, nm, tp, dm in rows:
            k = _norm_excl_value(no)
            if not k:
                continue
            if nm and str(nm).strip() and str(nm).strip().lower() not in ('nan', 'none'):
                name_lut.setdefault(k, str(nm).strip())
            if tp and str(tp).strip() and str(tp).strip().lower() not in ('nan', 'none'):
                type_lut.setdefault(k, str(tp).strip())
            # domain 按 materialName 建映射（同一名称多值时取首个非空）
            nk = _norm_excl_value(nm)
            if nk and dm and str(dm).strip() and str(dm).strip().lower() not in ('nan', 'none'):
                domain_lut.setdefault(nk, str(dm).strip())
        return name_lut, type_lut, domain_lut

    # 1) PostgreSQL
    url = _read_database_url()
    if url and url.startswith('postgres'):
        try:
            import psycopg2
            conn = psycopg2.connect(url)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT table_schema FROM information_schema.tables "
                    "WHERE table_name=%s ORDER BY CASE WHEN table_schema='app' THEN 0 ELSE 1 END LIMIT 1",
                    (MATERIAL_TABLE,))
                row = cur.fetchone()
                if not row:
                    print(f'[MatSync][WARN] PG 中不存在表 {MATERIAL_TABLE}，回退 inventory')
                else:
                    schema = row[0]
                    cur.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema=%s AND table_name=%s",
                        (schema, MATERIAL_TABLE))
                    has_domain = any(r[0].lower() == 'domain' for r in cur.fetchall())
                    sel = ('"materialNo", "materialName", "materialType"'
                           + (', "domain"' if has_domain else ''))
                    cur.execute(f'SELECT {sel} FROM "{schema}"."{MATERIAL_TABLE}" ORDER BY "materialNo"')
                    rows = [(*r, None) if len(r) == 3 else r for r in cur.fetchall()]
                    lut = _pack(rows)
                    print(f'[MatSync] 读取 sp_material(PG {schema}.{MATERIAL_TABLE}): '
                          f'Name {len(lut[0])} 条, Type {len(lut[1])} 条, Domain {len(lut[2])} 条'
                          + ('' if has_domain else '（无 domain 列）'))
                    return lut
            finally:
                conn.close()
        except Exception as e:
            print(f'[MatSync][WARN] 读取 PG sp_material 失败({e})，回退 sqlite/inventory')

    # 2) SQLite（db/app.db）
    db_file = _PROJECT_ROOT / 'db' / 'app.db'
    if db_file.is_file():
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_file))
            try:
                cols = {r[1].lower() for r in conn.execute(f'PRAGMA table_info({MATERIAL_TABLE})')}
                if not cols:
                    print(f'[MatSync][WARN] sqlite 中无表 {MATERIAL_TABLE}，回退 inventory')
                    return {}, {}, {}
                sel = ('materialNo, materialName, materialType'
                       + (', domain' if 'domain' in cols else ''))
                cur = conn.execute(f'SELECT {sel} FROM {MATERIAL_TABLE} ORDER BY materialNo')
                rows = [(*r, None) if len(r) == 3 else r for r in cur.fetchall()]
                lut = _pack(rows)
                if lut[0] or lut[1]:
                    print(f'[MatSync] 读取 sp_material(sqlite): Name {len(lut[0])} 条, '
                          f'Type {len(lut[1])} 条, Domain {len(lut[2])} 条'
                          + ('' if 'domain' in cols else '（无 domain 列）'))
                    return lut
                print(f'[MatSync][WARN] sqlite 中无 {MATERIAL_TABLE} 数据，回退 inventory')
            finally:
                conn.close()
        except Exception as e:
            print(f'[MatSync][WARN] 读取 sqlite sp_material 失败({e})，回退 inventory')
    return {}, {}, {}


# 进程内缓存：同一次报表运行里多个 sheet 都要用 domain 映射，只读一次库
_MATERIAL_MAPS_CACHE = None


def get_material_maps():
    """load_material_maps_from_db() 的进程内缓存版（返回 (name_lut, type_lut, domain_lut)）。"""
    global _MATERIAL_MAPS_CACHE
    if _MATERIAL_MAPS_CACHE is None:
        _MATERIAL_MAPS_CACHE = load_material_maps_from_db()
    return _MATERIAL_MAPS_CACHE


def build_material_maps(inv):
    """inventory_details -> ({Material No.: Material Name}, {Material No.: Material Type})

    同一物料存在多个不同值时取首个非空，冲突条数会打印。
    """
    if inv is None or inv.empty or 'Material No.' not in inv.columns:
        print('[MatSync][WARN] inventory 缺少 Material No. 列，跳过字段同步')
        return {}, {}
    has_name = 'Material Name' in inv.columns
    has_type = 'Material Type' in inv.columns
    if not (has_name or has_type):
        print('[MatSync][WARN] inventory 缺少 Material Name/Material Type 列，跳过字段同步')
        return {}, {}

    name_lut, type_lut = {}, {}
    name_conflict = type_conflict = 0
    keys = inv['Material No.'].map(_norm_excl_value)
    names = inv['Material Name'] if has_name else [None] * len(inv)
    types = inv['Material Type'] if has_type else [None] * len(inv)
    for no, nm, tp in zip(keys, names, types):
        if not no:
            continue
        for lut, val, flag in ((name_lut, nm, has_name), (type_lut, tp, has_type)):
            if not flag:
                continue
            s = '' if val is None else str(val).strip()
            if not s or s.lower() in ('nan', 'none'):
                continue
            if no in lut:
                if lut[no] != s:
                    if lut is name_lut:
                        name_conflict += 1
                    else:
                        type_conflict += 1
                continue
            lut[no] = s
    print(f'[MatSync] inventory 映射: Material Name {len(name_lut)} 条'
          + (f'（冲突 {name_conflict}，取首个）' if name_conflict else '')
          + f', Material Type {len(type_lut)} 条'
          + (f'（冲突 {type_conflict}，取首个）' if type_conflict else ''))
    return name_lut, type_lut


def _overlay_column(df, keys, col, lut):
    """用 lut 覆盖 df[col]，返回 (变更数, 未命中数)。"""
    if col not in df.columns:
        df[col] = ''
    new_vals, changed, missing = [], 0, 0
    for k, old in zip(keys, df[col]):
        v = lut.get(k, '')
        if v:
            old_s = '' if old is None or (isinstance(old, float) and pd.isna(old)) else str(old).strip()
            if old_s != v:
                changed += 1
            new_vals.append(v)
        else:
            missing += 1
            new_vals.append(old)
    df[col] = new_vals
    return changed, missing


def apply_inventory_fields(inb, outb, inv):
    """剔除/状态过滤后执行：覆盖两份明细的 Material Name / Material Type，并写回保存。

    - Material Name：优先取数据库表 `sp_material`（物料主数据），取不到时回退 inventory
    - Material Type：取 inventory（同物料多值取首个）
    命中才替换，未命中保留原值。返回 (inb, outb, stats)。
    """
    db_name, _db_type, _db_domain = get_material_maps()
    inv_name, inv_type = build_material_maps(inv)
    if db_name:
        name_lut, name_src = db_name, f'sp_material(DB)'
    else:
        name_lut, name_src = inv_name, 'inventory(回退)'
    type_lut = inv_type
    print(f'[MatSync] Material Name 来源={name_src}（{len(name_lut)} 条）, '
          f'Material Type 来源=inventory（{len(type_lut)} 条）')
    if not name_lut and not type_lut:
        return inb, outb, {}

    stats = {}
    for name, path, df in (('inbound', INB_PATH, inb), ('outbound', OUTB_PATH, outb)):
        if df is None or df.empty or 'Material No.' not in df.columns:
            continue
        keys = df['Material No.'].map(_norm_excl_value)
        df = df.copy()
        parts, changed_total = [], 0
        for col, lut in (('Material Name', name_lut), ('Material Type', type_lut)):
            if not lut:
                continue
            changed, missing = _overlay_column(df, keys, col, lut)
            changed_total += changed
            parts.append(f'{col} 替换 {changed} 行（未命中 {missing} 行保留原值）')
        if changed_total == 0:
            print(f'[MatSync] {name}: 无需替换')
            continue
        print(f'[MatSync] {name}: ' + '; '.join(parts))
        _save_detail_xlsx(df, path)
        stats[name] = changed_total
        if name == 'inbound':
            inb = df
        else:
            outb = df
    return inb, outb, stats


# ==============================================================================
# filter_data - filter specified Inbound Type and Outbound Type
# ==============================================================================
def filter_data(inb_df, outb_df):
    """Filter out 'Borrow Return Inbound' from inbound and 'Repair Outbound' from outbound."""
    # Filter inbound: exclude 'Borrow Return Inbound'
    inb_filtered = inb_df[~inb_df['Inbound Type'].astype(str).str.strip().eq('Borrow Return Inbound')].reset_index(drop=True)
    
    # Filter outbound: exclude 'Repair Outbound'
    outb_filtered = outb_df[~outb_df['Outbound Type'].astype(str).str.strip().eq('Repair Outbound')].reset_index(drop=True)
    
    return inb_filtered, outb_filtered


# ==============================================================================
# preprocess - filter warehouse (vectorized)
# ==============================================================================
def preprocess(dfs):
    """Exclude 'Liberia Monrovia material warehouse' rows from all DataFrames."""
    result = []
    for df in dfs:
        mask = df['Warehouse Name'].astype(str).str.strip().ne(EXCLUDE_WAREHOUSE)
        result.append(df.loc[mask].reset_index(drop=True))
    return result


# ==============================================================================
# split_by_warehouse - split data by Warehouse Name
# ==============================================================================
def split_by_warehouse(inb_df, outb_df, inv_df):
    """Split data by Warehouse Name, return dict of {warehouse_name: (inb, outb, inv)}."""
    # Get all unique warehouse names from all dataframes
    warehouses = set()
    for df in [inb_df, outb_df, inv_df]:
        if 'Warehouse Name' in df.columns:
            warehouses.update(df['Warehouse Name'].dropna().astype(str).str.strip().unique())
    warehouses = sorted(list(warehouses))
    
    warehouse_data = {}
    for wh in warehouses:
        # Filter each dataframe for this warehouse
        inb_wh = inb_df[inb_df['Warehouse Name'].astype(str).str.strip().eq(wh)].reset_index(drop=True)
        outb_wh = outb_df[outb_df['Warehouse Name'].astype(str).str.strip().eq(wh)].reset_index(drop=True)
        inv_wh = inv_df[inv_df['Warehouse Name'].astype(str).str.strip().eq(wh)].reset_index(drop=True)
        warehouse_data[wh] = (inb_wh, outb_wh, inv_wh)
    
    return warehouse_data


# ==============================================================================
# build_lookup - vectorized
# ==============================================================================
def build_lookup(dfs):
    """Build Material No.->Material Name and Material Name->Domain lookup Series."""
    combined = pd.concat(
        [df[['Material No.', 'Material Name', 'Domain']] for df in dfs],
        ignore_index=True
    )
    valid_mno = combined.dropna(subset=['Material No.', 'Material Name'])
    valid_mno = valid_mno[valid_mno['Material No.'].astype(str).str.strip().ne('')]
    mno_to_name = (
        valid_mno.assign(key=valid_mno['Material No.'].astype(str).str.strip())
        .drop_duplicates('key', keep='first')
        .set_index('key')['Material Name']
    )
    valid_mn = combined.dropna(subset=['Material Name', 'Domain'])
    valid_mn = valid_mn[valid_mn['Material Name'].astype(str).str.strip().ne('')]
    mn_to_domain = (
        valid_mn.assign(key=valid_mn['Material Name'].astype(str).str.strip())
        .drop_duplicates('key', keep='first')
        .set_index('key')['Domain']
    )
    return mno_to_name, mn_to_domain


# ==============================================================================
# fill_missing - vectorized map
# ==============================================================================
def fill_missing(df, mno_to_name, mn_to_domain):
    """Fill missing Material Name and Domain using vectorized map."""
    name_blank = df['Material Name'].isna() | df['Material Name'].astype(str).str.strip().eq('')
    if name_blank.any():
        keys = df.loc[name_blank, 'Material No.'].astype(str).str.strip()
        df.loc[name_blank, 'Material Name'] = keys.map(mno_to_name)

    domain_blank = df['Domain'].isna() | df['Domain'].astype(str).str.strip().eq('')
    if domain_blank.any():
        keys = df.loc[domain_blank, 'Material Name'].astype(str).str.strip()
        df.loc[domain_blank, 'Domain'] = keys.map(mn_to_domain)

    return df


# ==============================================================================
# build_summary - vectorized, with Difference (Balance 列 2026-09-19 已删)
# ==============================================================================
def build_summary(inb_df, outb_df, inv_df):
    """Build summary with Material Name, Domain, Inbound, Outbound, Inventory, Difference.
    Total row at the top.

    Domain 取自数据库表 sp_material（materialName→domain，2026-09-19 起），
    库里取不到的物料回退 Inventory 明细的 Domain；同一物料多行时取第一个非空值。
    Balance 列 2026-09-19 删除；Difference 口径不变 = Inventory Qty - (Inbound Qty - Outbound Qty)。

    Outbound 拆分（2026-09-24 新增，紧跟 Outbound Qty 右侧）：
      - Outbound Repair Qty = 出库明细中 Outbound Type == REPLENISH_EXCLUDE_OUTBOUND_TYPE
        （'Repair Outbound'，报修出库）的 Outbound Qty 合计；
      - Outbound Site Qty   = Outbound Qty - Outbound Repair Qty（**用减法而非再筛一类**）。
    两者之和恒等于 Outbound Qty：上游日后新增 Outbound Type、或出现空白值，
    都会自动落到 Outbound Site Qty 里，恒等式不会被新类型打破。
    注意本拆分与「补库消耗」不同：补库消耗还额外剔除了 REPLENISH_EXCLUDE_ORDERS 两张
    异常单据（见 build_replenishment），本表的 Outbound Qty 仍是**未剔除**的原值。
    """
    inb_sum = inb_df.groupby('Material Name', sort=True)['Inbound Qty'].sum()
    outb_sum = outb_df.groupby('Material Name', sort=True)['Outbound Qty'].sum()
    inv_sum = inv_df.groupby('Material Name', sort=True)['Stock Qty'].sum()

    # 报修出库（Repair Outbound）单列统计；其余出库一律算「站点出库」。
    if outb_df is not None and len(outb_df) > 0 and 'Outbound Type' in outb_df.columns:
        repair_mask = outb_df['Outbound Type'].astype(str).str.strip().eq(
            REPLENISH_EXCLUDE_OUTBOUND_TYPE)
        repair_sum = pd.to_numeric(
            outb_df.loc[repair_mask].groupby('Material Name')['Outbound Qty'].sum(),
            errors='coerce').fillna(0)
    else:
        repair_sum = pd.Series(dtype='float64')

    merged = pd.DataFrame({
        'Inbound Qty': inb_sum, 'Outbound Qty': outb_sum, 'Inventory Qty': inv_sum,
    }).reset_index().sort_values('Material Name').reset_index(drop=True)

    for c in ['Inbound Qty', 'Outbound Qty', 'Inventory Qty']:
        merged[c] = merged[c].fillna(0)

    # 按 Material Name 对齐报修量（主表没有报修记录的物料记 0）
    merged['Outbound Repair Qty'] = pd.to_numeric(
        merged['Material Name'].map(repair_sum), errors='coerce').fillna(0)
    merged['Outbound Site Qty'] = merged['Outbound Qty'] - merged['Outbound Repair Qty']

    # Domain：优先取数据库表 sp_material（按 materialName），取不到回退 Inventory 明细
    inv_domain = {}
    if inv_df is not None and len(inv_df) > 0 and 'Domain' in inv_df.columns:
        for nm, dm in zip(inv_df['Material Name'], inv_df['Domain']):
            k = _norm_excl_value(nm)
            if k and dm is not None and not (isinstance(dm, float) and pd.isna(dm)) \
                    and str(dm).strip():
                inv_domain.setdefault(k, str(dm).strip())
    db_domain = get_material_maps()[2]
    merged['Domain'] = [db_domain.get(k) or inv_domain.get(k, '')
                        for k in merged['Material Name'].map(_norm_excl_value)]

    merged['Difference'] = merged['Inventory Qty'] - (merged['Inbound Qty'] - merged['Outbound Qty'])
    merged = merged[['Material Name', 'Domain', 'Inbound Qty', 'Outbound Qty',
                     'Outbound Site Qty', 'Outbound Repair Qty',
                     'Inventory Qty', 'Difference']]

    total = pd.DataFrame({
        'Material Name': ['Total'],
        'Domain': [''],                       # Total 行不显示 Domain
        'Inbound Qty': [merged['Inbound Qty'].sum()],
        'Outbound Qty': [merged['Outbound Qty'].sum()],
        'Outbound Site Qty': [merged['Outbound Site Qty'].sum()],
        'Outbound Repair Qty': [merged['Outbound Repair Qty'].sum()],
        'Inventory Qty': [merged['Inventory Qty'].sum()],
        'Difference': [merged['Difference'].sum()],
    })
    return pd.concat([total, merged], ignore_index=True)


# ==============================================================================
# build_replenishment - 补库建议（历史月均消耗 / 安全库存 / 需补库数量 / 预警级别）
# ==============================================================================
def history_months(as_of=None):
    """历史消耗窗口的月数 = 起算月到 as_of 所在自然月的**含首尾月个数**。

    例（起算月 2026-01）：2026-01 → 1；2026-02 → 2；2026-09 → 9；2027-01 → 13。

    已过天数**不折算**：同一自然月内分母恒定，报表数字不会逐日漂移。
    as_of 缺省取当前时间；起算月晚于 as_of 时退回兜底值 1（防 0/负分母）。
    """
    now = as_of if as_of is not None else datetime.now()
    sy, sm = REPLENISH_HISTORY_START
    n = (now.year - sy) * 12 + (now.month - sm) + 1
    return n if n > 0 else REPLENISH_HISTORY_MONTHS_FALLBACK


def build_replenishment(outb_df, inv_df, base_index=None, summary_qty=None, as_of=None):
    """按 Material Name 统计补库建议，直接并到 Summary-Current 主表右侧。

    - Avg Monthly Consumption = 出库数量合计（先剔除 REPLENISH_EXCLUDE_ORDERS 两张异常单据，
      再剔除 Outbound Type = 'Repair Outbound' 的报修出库）÷「历史月数」，保留 2 位小数，
      不再向上取整（2026-09-19 起）。
      历史月数由 ``history_months(as_of)`` 动态计算（2026-09-24 起替代写死的 9.5）：
      起算月 REPLENISH_HISTORY_START（2026-01）到当前自然月的含首尾月个数，2026-09 跑 = 9。
    - Safety Stock = ceil(6 * Avg Monthly Consumption)（整数，月均按 2 位小数验算：
      Safety = 向上取整(6 x Avg)）；
      月均消耗为 0 的物料按「故障率」备件处理：Safety Stock =
      ceil(20% * max(Inbound Qty, net Outbound Qty, Inventory Qty))（三列取自 summary_qty，整数；
      net Outbound Qty 为已剔除异常单据与 Repair Outbound 的净消耗）
    - Remark = Actual Consumption（月均消耗 > 0）/ Failure Rate（月均消耗 = 0）
    - Replenishment Qty = Safety Stock - Inventory Qty，<= 0 记为空（不显示，便于求和）；结果向上取整
    - Alert Level = Inventory Qty / Safety Stock：< 50% Urgent Replenish；50% ~ 100% Replenish；> 100% Excess

    base_index：主表的 Material Name 序列。给了就按它逐行对齐（主表里没有出库消耗的物料
    按 0 消耗计算，保证与主表行数、顺序一一对应）；不给则只输出有出库消耗的物料。
    summary_qty：主表的 Material Name + Inbound/Outbound/Inventory Qty 列（月均=0 的物料
    算安全库存用），缺省时退化为全 0（旧行为保底 1 已删，不会触发）。
    as_of：计算历史月数用的时间基准，缺省当前时间；显式传入便于测试与回算历史报表。
    """
    consumed = pd.Series(dtype='float64')
    df = outb_df if outb_df is not None else pd.DataFrame()
    if len(df) > 0:
        if REPLENISH_EXCLUDE_ORDERS:
            orders = {str(o).strip() for o in REPLENISH_EXCLUDE_ORDERS}
            df = df.loc[~df['Outbound No.'].astype(str).str.strip().isin(orders)]
        # 报修出库（Repair Outbound）不代表真实消耗，同样计入剔除
        if REPLENISH_EXCLUDE_OUTBOUND_TYPE and 'Outbound Type' in df.columns:
            df = df.loc[~df['Outbound Type'].astype(str).str.strip()
                        .eq(REPLENISH_EXCLUDE_OUTBOUND_TYPE)]
        consumed = pd.to_numeric(df.groupby('Material Name')['Outbound Qty'].sum(), errors='coerce').fillna(0)

    if inv_df is not None and len(inv_df) > 0:
        stock = pd.to_numeric(inv_df.groupby('Material Name')['Stock Qty'].sum(), errors='coerce').fillna(0)
    else:
        stock = pd.Series(dtype='float64')

    base = consumed.index if base_index is None else pd.Index(list(base_index))
    consumed_qty = consumed.reindex(base).fillna(0).to_numpy(dtype='float64')
    stock_qty = stock.reindex(base).fillna(0).to_numpy(dtype='float64')

    # 月均=0 物料的安全库存基数：主表三列数量逐行最大值（按归一化物料名对齐 base）
    # 注意：主表 Outbound Qty 含 Repair Outbound，这里换成与 consumed 同口径的净出库量，
    # 否则「只报修过、从未真实消耗」的物料会靠 Outbound Qty 拿到一份虚假的安全库存。
    qty_cols = ['Inbound Qty', 'Outbound Qty', 'Inventory Qty']
    if summary_qty is not None and len(summary_qty) > 0:
        q = pd.DataFrame({'__key': pd.Index(summary_qty['Material Name'].tolist()).map(_norm_excl_value)})
        for c in qty_cols:
            q[c] = pd.to_numeric(summary_qty[c].to_numpy(), errors='coerce')
        # Outbound Qty 替换为已剔除异常单据 + Repair Outbound 的净消耗（无记录即 0）
        net_out = consumed.reindex(
            pd.Index(q['__key']).drop_duplicates()).fillna(0)
        q['Outbound Qty'] = q['__key'].map(net_out).fillna(0).to_numpy()
        mx = q.groupby('__key')[qty_cols].max().max(axis=1)
        base_keys = pd.Index(base).map(_norm_excl_value)
        max_qty = mx.reindex(base_keys).fillna(0).to_numpy(dtype='float64')
    else:
        max_qty = np.zeros(len(base), dtype='float64')

    result = pd.DataFrame({'Material Name': base})
    # 历史月数按「起算月 → 当前自然月」动态算（2026-09-24 起，替代写死的 9.5）。
    # 保留 2 位小数（2026-09-19 起不再向上取整）；Safety = ceil(6 x Avg)，仍为整数
    months = history_months(as_of)
    avg = np.round(consumed_qty / months, 2)
    result['Avg Monthly Consumption'] = avg
    # 月均消耗为 0 → 按「故障率」备件处理：安全库存 = max(三列数量) x 20% 向上取整
    # 先 round(x, 6) 再 ceil：防浮点误差误进位（如 15 * 0.2 = 3.0000000000000004 → ceil 会变 4）
    has_consumption = consumed_qty > 0
    safety = np.where(has_consumption,
                      np.ceil(np.round(avg * REPLENISH_SAFETY_MONTHS, 6)),
                      np.ceil(np.round(max_qty * REPLENISH_ZERO_CONSUMPTION_SAFETY_PCT, 6)))
    result['Safety Stock'] = safety
    result[REPLENISH_REMARK_COL] = np.where(has_consumption, REMARK_ACTUAL_CONSUMPTION,
                                            REMARK_FAILURE_RATE)

    need = safety - stock_qty
    # <= 0 留空（不显示负数/0），避免影响求和；结果同样向上取整
    result['Replenishment Qty'] = np.where(need > 0, np.ceil(need), np.nan)

    # 分母保护：无消耗且三列数量全 0 时 Safety Stock 可能为 0，不能拿它除
    ratio = np.full(len(result), np.inf)
    has_safety = safety > 0
    ratio[has_safety] = stock_qty[has_safety] / safety[has_safety]
    result[REPLENISH_ALERT_COL] = np.select(
        [ratio < 0.5, ratio <= 1.0],
        [ALERT_URGENT, ALERT_REPLENISH],
        default=ALERT_EXCESS,
    )

    return result[REPLENISH_COLS]


# ==============================================================================
# build_summary_changed - Daily inbound/outbound statistics by warehouse
# ==============================================================================
def build_summary_changed(inb_df, outb_df, timestamp_str):
    """Build Summary-Changed sheet with daily statistics by warehouse.
    
    Args:
        inb_df: Inbound dataframe with 'Inbound Time' and 'Warehouse Name'
        outb_df: Outbound dataframe with 'Outbound Time' and 'Warehouse Name'
        timestamp_str: Timestamp string to extract current month (format: YYYY-MM-DD HH-MM-SS)
    
    Returns:
        DataFrame with dates as rows and warehouses as columns for both Inbound and Outbound
    """
    # Extract current date from timestamp
    current_date = datetime.strptime(timestamp_str.split()[0], '%Y-%m-%d')
    current_month = current_date.month
    current_year = current_date.year
    current_day = current_date.day
    
    # Get all days in current month
    import calendar
    num_days = calendar.monthrange(current_year, current_month)[1]
    dates = [f"{i}-{datetime(current_year, current_month, 1).strftime('%b')}" for i in range(1, num_days + 1)]
    
    # Get unique warehouses (sorted alphabetically)
    all_warehouses = sorted(set(
        list(inb_df['Warehouse Name'].dropna().astype(str).str.strip().unique()) +
        list(outb_df['Warehouse Name'].dropna().astype(str).str.strip().unique())
    ))
    
    # Build result DataFrame with proper column names
    # Column 0: WH&DOP (dates)
    # Columns 1 to n: Inbound warehouses
    # Columns n+1 to 2n: Outbound warehouses
    result_data = {'WH&DOP': dates}
    
    # Add Inbound columns for each warehouse
    for wh in all_warehouses:
        result_data[f'{wh}'] = [None] * len(dates)  # Initialize with None for numeric type
    
    # Add Outbound columns for each warehouse (use same warehouse names)
    for wh in all_warehouses:
        result_data[f'{wh}_out'] = [None] * len(dates)  # Initialize with None for numeric type
    
    df_result = pd.DataFrame(result_data)
    
    # Calculate daily inbound counts by warehouse (only up to yesterday)
    if len(inb_df) > 0:
        inb_df_copy = inb_df.copy()
        inb_df_copy['Inbound Date'] = pd.to_datetime(inb_df_copy['Inbound Time']).dt.date
        inb_df_copy['Month'] = pd.to_datetime(inb_df_copy['Inbound Time']).dt.month
        inb_df_copy['Day'] = pd.to_datetime(inb_df_copy['Inbound Time']).dt.day
        inb_df_copy['Year'] = pd.to_datetime(inb_df_copy['Inbound Time']).dt.year
        inb_df_copy['Warehouse Name'] = inb_df_copy['Warehouse Name'].astype(str).str.strip()
        
        # Filter for current month and only up to yesterday
        inb_filtered = inb_df_copy[
            (inb_df_copy['Month'] == current_month) & 
            (inb_df_copy['Year'] == current_year) &
            (inb_df_copy['Day'] < current_day)
        ]
        
        # Group by day and warehouse
        inb_grouped = inb_filtered.groupby(['Day', 'Warehouse Name']).size().unstack(fill_value=0)
        
        # Fill into result
        for idx, date_str in enumerate(dates):
            day_num = int(date_str.split('-')[0])
            # Only fill data for days before today
            if day_num < current_day and day_num in inb_grouped.index:
                for wh in all_warehouses:
                    col_name = wh
                    if wh in inb_grouped.columns:
                        df_result.at[idx, col_name] = inb_grouped.loc[day_num, wh]
    
    # Calculate daily outbound counts by warehouse (only up to yesterday)
    if len(outb_df) > 0:
        outb_df_copy = outb_df.copy()
        outb_df_copy['Outbound Date'] = pd.to_datetime(outb_df_copy['Outbound Time']).dt.date
        outb_df_copy['Month'] = pd.to_datetime(outb_df_copy['Outbound Time']).dt.month
        outb_df_copy['Day'] = pd.to_datetime(outb_df_copy['Outbound Time']).dt.day
        outb_df_copy['Year'] = pd.to_datetime(outb_df_copy['Outbound Time']).dt.year
        outb_df_copy['Warehouse Name'] = outb_df_copy['Warehouse Name'].astype(str).str.strip()
        
        # Filter for current month and only up to yesterday
        outb_filtered = outb_df_copy[
            (outb_df_copy['Month'] == current_month) & 
            (outb_df_copy['Year'] == current_year) &
            (outb_df_copy['Day'] < current_day)
        ]
        
        # Group by day and warehouse
        outb_grouped = outb_filtered.groupby(['Day', 'Warehouse Name']).size().unstack(fill_value=0)
        
        # Fill into result (outbound columns have _out suffix)
        for idx, date_str in enumerate(dates):
            day_num = int(date_str.split('-')[0])
            # Only fill data for days before today
            if day_num < current_day and day_num in outb_grouped.index:
                for wh in all_warehouses:
                    col_name = f'{wh}_out'
                    if wh in outb_grouped.columns:
                        df_result.at[idx, col_name] = outb_grouped.loc[day_num, wh]
    
    return df_result, all_warehouses


# ==============================================================================
# style_excel
# ==============================================================================
def _auto_width(ws, min_w=10, max_w=42):
    for col_idx in range(1, ws.max_column + 1):
        letter = get_column_letter(col_idx)
        max_len = len(str(ws.cell(1, col_idx).value or ''))
        for row_idx in range(2, min(ws.max_row + 1, 202)):
            val = ws.cell(row_idx, col_idx).value
            if val is not None:
                max_len = max(max_len, len(str(val)))
        ws.column_dimensions[letter].width = min(max(max_len + 2, min_w), max_w)


def _insert_title(ws, title, sheet_name, filter_note='', extra_notes=()):
    """Insert title rows and return the 1-based index of the sheet's header row.

    Row 1 = title, Row 2 = Generated/Sheet, Row 3 = filter note (only when filter_note is given),
    then one row per entry in extra_notes（补库口径说明等，紧贴表头之上）.
    """
    ws.insert_rows(1, 2)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ws.max_column)
    c = ws.cell(1, 1)
    c.value = title
    c.font = FONT_TITLE
    c.alignment = ALIGN_LEFT

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ws.max_column)
    c = ws.cell(2, 1)
    c.value = f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}    |    Sheet: {sheet_name}'
    c.font = FONT_SUBTITLE
    c.alignment = ALIGN_LEFT

    next_row = 3
    if filter_note:
        ws.insert_rows(next_row, 1)
        ws.merge_cells(start_row=next_row, start_column=1, end_row=next_row, end_column=ws.max_column)
        c = ws.cell(next_row, 1)
        c.value = filter_note
        c.font = FONT_FILTER
        c.alignment = ALIGN_LEFT
        next_row += 1

    # 附加说明行：紧贴表头之上，样式与过滤条件说明一致
    for text in (extra_notes or ()):
        ws.insert_rows(next_row, 1)
        ws.merge_cells(start_row=next_row, start_column=1, end_row=next_row, end_column=ws.max_column)
        c = ws.cell(next_row, 1)
        c.value = text
        c.font = FONT_FILTER
        c.alignment = ALIGN_LEFT
        next_row += 1

    return next_row


def _apply_header(ws, header_row=3):
    for cell in ws[header_row]:
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_HEADER
        cell.border = BORDER_HEADER


def _num_fmt_for_col(header_names, col_idx):
    """Avg Monthly Consumption 保留 2 位小数（2026-09-19 起）；其余数值列（含 Safety Stock）整数格式。"""
    if header_names.get(col_idx) in REPLENISH_DEC_COLS:
        return NUM_FMT_DEC
    return NUM_FMT_INT


def _apply_zebra(ws, start_row=4, header_row=None, end_row=None):
    header_names = {}
    if header_row:
        header_names = {c: ws.cell(header_row, c).value for c in range(1, ws.max_column + 1)}
    last_row = end_row if end_row else ws.max_row
    for row_idx in range(start_row, last_row + 1):
        fill = FILL_ZEBRA if row_idx % 2 == 0 else FILL_WHITE
        for cell in ws[row_idx]:
            cell.fill = fill
            cell.font = FONT_CELL
            cell.border = BORDER_CELL
            cell.alignment = ALIGN_CELL
            if isinstance(cell.value, (int, float)):
                cell.alignment = ALIGN_NUM
                cell.number_format = _num_fmt_for_col(header_names, cell.column)


def _apply_total_row(ws, row_idx=4, header_row=None):
    header_names = {}
    if header_row:
        header_names = {c: ws.cell(header_row, c).value for c in range(1, ws.max_column + 1)}
    for cell in ws[row_idx]:
        cell.font = FONT_TOTAL
        cell.fill = FILL_TOTAL
        cell.border = BORDER_TOTAL
        if isinstance(cell.value, (int, float)):
            cell.alignment = ALIGN_NUM
            cell.number_format = _num_fmt_for_col(header_names, cell.column)


def _apply_conditional(ws, sheet_name, header_row=3, data_start=5, data_end=None):
    last_row = data_end if data_end is not None else ws.max_row
    # Only apply conditional formatting if there's data
    if data_start <= last_row:
        if sheet_name == 'Summary':
            headers = {ws.cell(header_row, c).value: get_column_letter(c)
                        for c in range(1, ws.max_column + 1)}
            diff_col = headers.get('Difference')
            if diff_col:
                rng = f'{diff_col}{data_start}:{diff_col}{last_row}'
                ws.conditional_formatting.add(rng, ColorScaleRule(
                   # start_type='min', start_color='F8696B',
                    start_type='min', start_color='F41518',
                    mid_type='num', mid_value=0, mid_color='FFFFFF',
                    end_type='max', end_color='63BE7B',
                ))
        elif sheet_name == 'Inventory':
            headers = {ws.cell(header_row, c).value: get_column_letter(c)
                        for c in range(1, ws.max_column + 1)}
            qty_col = headers.get('Stock Qty')
            if qty_col:
                rng = f'{qty_col}{data_start}:{qty_col}{last_row}'
                ws.conditional_formatting.add(rng, CellIsRule(operator='equal', formula=['0'], fill=FILL_RED, font=FONT_RED))
                ws.conditional_formatting.add(rng, CellIsRule(operator='lessThan', formula=['10'], fill=FILL_YELLOW, font=FONT_YELLOW))
                ws.conditional_formatting.add(rng, CellIsRule(operator='greaterThan', formula=['100'], fill=FILL_GREEN, font=FONT_GREEN))


def _style_replenish_columns(ws, header_row, data_end):
    """Summary-Current 右侧补库建议列的收尾样式：Alert Level 三色 + 列宽。

    只对实际存在这几列的 sheet 生效（其它 sheet 的 headers 里查不到列名，直接跳过）。
    Alert Level 的取值文案较长，_auto_width 按字符数估算会偏窄，这里按显示宽度重撑一遍。
    """
    headers = {ws.cell(header_row, c).value: c for c in range(1, ws.max_column + 1)}
    for name in REPLENISH_COLS[1:]:
        col = headers.get(name)
        if not col:
            continue
        letter = get_column_letter(col)
        is_alert = (name == REPLENISH_ALERT_COL)
        need = _display_width(name) + 3
        for r in range(header_row + 1, data_end + 1):
            cell = ws.cell(r, col)
            val = cell.value
            if is_alert:
                fill_rgb, font_rgb = ALERT_COLORS.get(str(val).strip(), (None, None))
                if fill_rgb:
                    rgb = f'{fill_rgb[0]:02X}{fill_rgb[1]:02X}{fill_rgb[2]:02X}'
                    cell.fill = PatternFill(start_color=rgb, end_color=rgb, fill_type='solid')
                    cell.font = Font(name='Calibri', size=10,
                                     color=f'{font_rgb[0]:02X}{font_rgb[1]:02X}{font_rgb[2]:02X}')
                cell.alignment = ALIGN_HEADER
            if val is not None:
                need = max(need, _display_width(_fmt_replenish_cell(name, val)) + 3)
        ws.column_dimensions[letter].width = max(ws.column_dimensions[letter].width or 0, min(need, 42))


def _style_replenish_note(ws, first_row, n_cols, notes=None):
    """【已停用，保留供回退】补库口径说明写在表身下方的老版式。

    说明行现已改到表头之上（由 `_insert_title(..., extra_notes=replenish_notes())` 写入），
    本函数不再被调用。若日后要退回「表身下方」版式，改回 `generate_report` 里的调用即可。
    注：`notes` 缺省改为 None 后按 `replenish_notes()` 现算（历史月数是动态的，不能用常量默认值）。
    """
    if notes is None:
        notes = replenish_notes()
    if n_cols < 1:
        return
    for i, text in enumerate(notes):
        row = first_row + i
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=n_cols)
        for col in range(1, n_cols + 1):
            cell = ws.cell(row, col)
            cell.fill = FILL_WHITE
            cell.border = Border()
        c = ws.cell(row, 1)
        c.value = text
        c.font = FONT_FILTER
        c.alignment = ALIGN_LEFT


def _apply_page_setup(ws):
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=0.4, right=0.4, top=0.5, bottom=0.5, header=0.3, footer=0.3)


def style_excel(ws, sheet_name, has_total_row=False, title='', filter_note='',
                table_rows=None, extra_notes=()):
    """套用 sheet 样式并返回表头行号。

    table_rows：表身（表头 + 数据）占用的行数。给了就把它作为条件格式与自动筛选的
    下界，避免同一 sheet 下方的附加区块被卷进去。
    extra_notes：表头之上、过滤条件说明之下的附加说明行（如补库口径）。
    """
    has_title = bool(title)
    if has_title:
        header_row = _insert_title(ws, title, sheet_name, filter_note, extra_notes)
    else:
        header_row = 1
    data_start = header_row + 1
    total_row = data_start
    table_end = header_row + table_rows - 1 if table_rows else ws.max_row

    _apply_header(ws, header_row)
    _apply_zebra(ws, start_row=data_start, header_row=header_row, end_row=table_end)
    if has_total_row:
        _apply_total_row(ws, row_idx=total_row, header_row=header_row)
    _apply_conditional(ws, sheet_name, header_row=header_row, data_start=total_row + 1, data_end=table_end)
    _auto_width(ws)
    # 补库建议 4 列（已并到主表右侧）：Alert Level 三色 + 列宽按实际显示宽度撑开
    _style_replenish_columns(ws, header_row=header_row, data_end=table_end)
    ws.freeze_panes = f'A{header_row + 1}'
    ws.auto_filter.ref = f'A{header_row}:{get_column_letter(ws.max_column)}{table_end}'
    if sheet_name in SHEET_COLORS:
        ws.sheet_properties.tabColor = SHEET_COLORS[sheet_name]
    _apply_page_setup(ws)
    return header_row


def _style_replenishment(ws, title_row, note_row, header_row, block_len, blank_row=None):
    """【已停用，保留供回退】补库建议独立区块的样式。

    补库 4 列现已并进 Summary-Current 主表右侧（按 Material Name 同行对齐），
    样式由 `_style_replenish_columns()` + `_style_replenish_note()` 负责，本函数不再被调用。
    若日后要退回「表身下方独立区块」的老版式，改回 `generate_report` 里的调用即可。

    title_row / note_row / header_row 为套用 sheet 标题行之后的 1-based 行号。
    """
    n_cols = len(REPLENISH_COLS)
    last_col = max(ws.max_column, n_cols)

    # 区块上方留白行与标题、说明行：清掉斑马纹与边框，只留文字
    for r in ([blank_row] if blank_row else []) + [title_row, note_row]:
        for col in range(1, last_col + 1):
            cell = ws.cell(r, col)
            cell.fill = FILL_WHITE
            cell.border = Border()
            cell.font = FONT_CELL

    c = ws.cell(title_row, 1)
    c.font = FONT_TOTAL
    c.alignment = ALIGN_LEFT
    c = ws.cell(note_row, 1)
    c.font = FONT_FILTER
    c.alignment = ALIGN_LEFT

    # 表头
    for col in range(1, n_cols + 1):
        cell = ws.cell(header_row, col)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_HEADER
        cell.border = BORDER_HEADER

    # 数据行
    last_data_row = header_row + block_len
    for r in range(header_row + 1, last_data_row + 1):
        zebra = FILL_ZEBRA if r % 2 == 0 else FILL_WHITE
        for col in range(1, n_cols + 1):
            cell = ws.cell(r, col)
            cell.border = BORDER_CELL
            if col == 1:
                cell.font = FONT_CELL
                cell.alignment = ALIGN_CELL
                cell.fill = zebra
            elif col == n_cols:
                fill_rgb, font_rgb = ALERT_COLORS.get(str(cell.value).strip(), (None, None))
                if fill_rgb:
                    rgb = f'{fill_rgb[0]:02X}{fill_rgb[1]:02X}{fill_rgb[2]:02X}'
                    cell.fill = PatternFill(start_color=rgb, end_color=rgb, fill_type='solid')
                    cell.font = Font(name='Calibri', size=10,
                                     color=f'{font_rgb[0]:02X}{font_rgb[1]:02X}{font_rgb[2]:02X}')
                else:
                    cell.font = FONT_CELL
                    cell.fill = zebra
                cell.alignment = ALIGN_HEADER
            else:
                cell.font = FONT_CELL
                cell.alignment = ALIGN_NUM
                cell.fill = zebra
                if isinstance(cell.value, (int, float)):
                    cell.number_format = NUM_FMT_DEC

    # 列宽：中文字符按 2 个半角宽度计算，避免表头被截断
    for idx, col_name in enumerate(REPLENISH_COLS, start=1):
        letter = get_column_letter(idx)
        need = _display_width(col_name) + 2
        for r in range(header_row + 1, last_data_row + 1):
            val = ws.cell(r, idx).value
            if val is not None:
                need = max(need, _display_width(_fmt_replenish_value(val)) + 2)
        ws.column_dimensions[letter].width = max(ws.column_dimensions[letter].width or 0, min(need, 42))


def style_summary_changed(ws, sheet_name, warehouses, title='', filter_note=''):
    """Style the Summary-Changed sheet with merged headers for Inbound and Outbound sections."""
    has_title = bool(title)
    if has_title:
        header_row = _insert_title(ws, title, sheet_name, filter_note)
    else:
        header_row = 1
    data_start = header_row + 1

    # Handle case when no warehouses exist
    num_warehouses = len(warehouses)
    if num_warehouses == 0:
        # No warehouses, just apply basic styling
        second_row = header_row + 1
        date_cell = ws.cell(second_row, 1)
        date_cell.value = 'WH&DOP'
        date_cell.font = FONT_HEADER
        date_cell.fill = FILL_HEADER
        date_cell.alignment = ALIGN_HEADER
        date_cell.border = BORDER_HEADER
        
        for row_idx in range(data_start + 1, ws.max_row + 1):
            fill = FILL_ZEBRA if row_idx % 2 == 0 else FILL_WHITE
            for cell in ws[row_idx]:
                cell.fill = fill
                cell.font = FONT_CELL
                cell.border = BORDER_CELL
                cell.alignment = ALIGN_CELL
                if isinstance(cell.value, (int, float)):
                    cell.alignment = ALIGN_NUM
                    cell.number_format = NUM_FMT_INT
        
        _auto_width(ws)
        ws.freeze_panes = f'A{data_start + 1}'
        ws.auto_filter.ref = f'A{second_row}:{get_column_letter(ws.max_column)}{ws.max_row}'
        if sheet_name in SHEET_COLORS:
            ws.sheet_properties.tabColor = SHEET_COLORS[sheet_name]
        _apply_page_setup(ws)
        return

    # First row: merge cells for "Inbound" and "Outbound" sections
    inbound_start_col = 2  # Column B
    inbound_end_col = 1 + num_warehouses
    outbound_start_col = inbound_end_col + 1
    outbound_end_col = outbound_start_col + num_warehouses - 1

    # Create "Inbound" merged header
    ws.merge_cells(start_row=header_row, start_column=inbound_start_col, 
                   end_row=header_row, end_column=inbound_end_col)
    inbound_cell = ws.cell(header_row, inbound_start_col)
    inbound_cell.value = 'Inbound'
    inbound_cell.font = FONT_HEADER
    inbound_cell.fill = PatternFill(start_color='FF8C00', end_color='FF8C00', fill_type='solid')
    inbound_cell.alignment = Alignment(horizontal='center', vertical='center')
    inbound_cell.border = BORDER_HEADER

    # Create "Outbound" merged header
    ws.merge_cells(start_row=header_row, start_column=outbound_start_col,
                   end_row=header_row, end_column=outbound_end_col)
    outbound_cell = ws.cell(header_row, outbound_start_col)
    outbound_cell.value = 'Outbound'
    outbound_cell.font = FONT_HEADER
    outbound_cell.fill = PatternFill(start_color='FF8C00', end_color='FF8C00', fill_type='solid')
    outbound_cell.alignment = Alignment(horizontal='center', vertical='center')
    outbound_cell.border = BORDER_HEADER

    # Second row: individual warehouse names
    second_row = header_row + 1
    # Date column header
    date_cell = ws.cell(second_row, 1)
    date_cell.value = 'WH&DOP'
    date_cell.font = FONT_HEADER
    date_cell.fill = FILL_HEADER
    date_cell.alignment = ALIGN_HEADER
    date_cell.border = BORDER_HEADER

    # Warehouse names for Inbound section (columns without _out suffix)
    for i, wh in enumerate(warehouses):
        cell = ws.cell(second_row, inbound_start_col + i)
        cell.value = wh
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_HEADER
        cell.border = BORDER_HEADER

    # Warehouse names for Outbound section (columns with _out suffix)
    for i, wh in enumerate(warehouses):
        cell = ws.cell(second_row, outbound_start_col + i)
        cell.value = wh
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_HEADER
        cell.border = BORDER_HEADER

    # Apply zebra striping to data rows with conditional formatting
    FILL_LIGHT_GRAY = PatternFill(start_color='E0E0E0', end_color='E0E0E0', fill_type='solid')
    FONT_BOLD_GREEN = Font(name='Calibri', bold=True, size=10, color='006100')
    FONT_LIGHT_GRAY = Font(name='Calibri', size=10, color='C0C0C0')
    
    for row_idx in range(data_start + 1, ws.max_row + 1):
        is_zebra = row_idx % 2 == 0
        base_fill = FILL_ZEBRA if is_zebra else FILL_WHITE
        
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row_idx, col_idx)
            
            # Skip the first column (WH&DOP date column)
            if col_idx == 1:
                cell.fill = base_fill
                cell.font = FONT_CELL
                cell.border = BORDER_CELL
                cell.alignment = ALIGN_CELL
                continue
            
            # For numeric columns (Inbound/Outbound values)
            value = cell.value
            # Check if value is a number (not None or empty string)
            if value is not None and isinstance(value, (int, float)):
                if value == 0:
                    # Zero value: light gray font
                    cell.fill = base_fill
                    cell.font = FONT_LIGHT_GRAY
                elif value > 0:
                    # Positive value: bold and dark green text
                    cell.fill = base_fill
                    cell.font = FONT_BOLD_GREEN
                cell.alignment = ALIGN_NUM
                cell.number_format = NUM_FMT_INT
            else:
                # Empty/None value: keep base fill
                cell.fill = base_fill
                cell.font = FONT_CELL
                cell.alignment = ALIGN_CELL
            
            cell.border = BORDER_CELL

    _auto_width(ws)
    ws.freeze_panes = f'A{data_start + 1}'
    ws.auto_filter.ref = f'A{second_row}:{get_column_letter(ws.max_column)}{ws.max_row}'
    if sheet_name in SHEET_COLORS:
        ws.sheet_properties.tabColor = SHEET_COLORS[sheet_name]
    _apply_page_setup(ws)


# ==============================================================================
# Summary PNG image generation
# ==============================================================================
def _diff_color(val):
    """Return fill color for Difference value: red←0→green."""
    if val == 0:
        return (255, 255, 255)
    elif val < 0:
        intensity = min(abs(val) / 50, 1.0)
        r = int(255 - intensity * (255 - 248))
        g = int(255 - intensity * (255 - 105))
        b = int(255 - intensity * (255 - 107))
        return (r, g, b)
    else:
        intensity = min(abs(val) / 50, 1.0)
        r = int(255 - intensity * (255 - 99))
        g = int(255 - intensity * (255 - 190))
        b = int(255 - intensity * (255 - 123))
        return (r, g, b)


def _load_cjk_font(size, bold=False):
    """加载支持中文的字体（补库建议区块用）；找不到时退回 Arial / 默认位图字体。"""
    for name in (('msyhbd.ttc', 'simhei.ttf', 'msyh.ttc') if bold else ('msyh.ttc', 'simhei.ttf', 'simsun.ttc')):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.truetype('arialbd.ttf' if bold else 'arial.ttf', size)
    except Exception:
        return ImageFont.load_default()


def _render_summary_image(summary_df, out_img_path, title='', has_total_row=True,
                          row_h=28, char_w=9, font_size=14, section_groups=None,
                          extra_df=None, extra_title='', notes='', footer=''):
    """Render Summary DataFrame as a PNG image using Pillow.

    Args:
        section_groups: optional list of (label, start_col, end_col) tuples
                        for merged section header row (0-based, inclusive).
        extra_df: optional second table rendered below the main table（补库建议早期版本用，
                  现已并入主表右侧，保留以备回退）。
        extra_title: caption line above the second table.
        notes: optional caption lines right below the title（补库口径说明），str 或 tuple。
        footer: optional caption lines under the table.
    """
    cols = summary_df.columns.tolist()
    n_rows = len(summary_df)
    n_cols = len(cols)
    has_extra = extra_df is not None and len(extra_df) > 0
    extra_cols = extra_df.columns.tolist() if has_extra else []
    n_extra_rows = len(extra_df) if has_extra else 0

    # Dimensions (use positional access to support duplicate column names)
    # 文本宽度按实际显示口径算（补库小数列保留 2 位小数，避免用整数宽度截断）
    col_widths = []
    for i, c in enumerate(cols):
        max_w = _display_width(c)
        for v in summary_df.iloc[:, i]:
            max_w = max(max_w, _display_width(_fmt_summary_cell(c, v)))
        col_widths.append(max_w + 4)

    extra_widths = []
    for i, c in enumerate(extra_cols):
        max_w = _display_width(c)
        for v in extra_df.iloc[:, i]:
            max_w = max(max_w, _display_width(_fmt_replenish_value(v)))
        extra_widths.append(max_w + 4)

    try:
        font = ImageFont.truetype("arial.ttf", font_size)
        font_bold = ImageFont.truetype("arialbd.ttf", font_size)
        font_title = ImageFont.truetype("arialbd.ttf", font_size + 4)
    except Exception:
        font = ImageFont.load_default()
        font_bold = font
        font_title = font

    # 补库建议区块含中文，Arial 无 CJK 字形，单独取中文字体
    extra_font = extra_font_bold = extra_font_title = None
    if has_extra:
        extra_font = _load_cjk_font(font_size)
        extra_font_bold = _load_cjk_font(font_size, bold=True)
        extra_font_title = _load_cjk_font(font_size + 4, bold=True)

    header_h = font_size + 18
    title_h = font_size + 26
    section_h = header_h if section_groups else 0
    padding = 16

    # 主表与补库表之间留 1 行空行；补库表 = [标题] + 表头 + 数据行
    extra_h = (row_h + (title_h if extra_title else 0) + header_h + n_extra_rows * row_h
               if has_extra else 0)

    table_w = max(sum(col_widths) * char_w, sum(extra_widths) * char_w)
    # 补库表等比拉伸到与主表同宽，避免右侧留白、与标题右边界错位
    extra_w = sum(extra_widths) * char_w
    if has_extra and 0 < extra_w < table_w:
        extra_widths = [w * table_w / extra_w for w in extra_widths]
    title_w = _display_width(extra_title) * char_w if (has_extra and extra_title) else 0
    # 注意：notes/footer 默认是 ''，空串必须当作「没有说明行」，否则会多出一行空白高度
    notes_lines = (notes,) if isinstance(notes, str) else tuple(notes or ())
    notes_lines = tuple(t for t in notes_lines if t)
    notes_h = len(notes_lines) * (font_size + 12)
    notes_w = max((_display_width(t) * char_w for t in notes_lines), default=0)
    footer_lines = (footer,) if isinstance(footer, str) else tuple(footer or ())
    footer_lines = tuple(t for t in footer_lines if t)
    footer_h = len(footer_lines) * (font_size + 12)
    footer_w = max((_display_width(t) * char_w for t in footer_lines), default=0)
    total_w = max(table_w, title_w, notes_w, footer_w) + padding * 2
    total_h = (title_h + notes_h + section_h + header_h + n_rows * row_h
               + extra_h + footer_h + padding * 2)

    img = Image.new('RGB', (total_w, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = padding
    # Title
    if title:
        draw.text((padding, y), title, fill=(47, 84, 150), font=font_title)
        y += title_h

    # 口径说明（表头之上）
    for i, line in enumerate(notes_lines):
        draw.text((padding, y + 6 + i * (font_size + 12)), line, fill=(68, 114, 196), font=font)
    if notes_lines:
        y += notes_h

    # Section header row (optional)
    if section_groups:
        x = padding
        for i in range(n_cols):
            w = col_widths[i] * char_w
            draw.rectangle([x, y, x + w, y + section_h], fill=(47, 84, 150), outline=(180, 198, 231))
            x += w
        for label, start_idx, end_idx in section_groups:
            x_start = padding + sum(col_widths[:start_idx]) * char_w
            x_end = padding + sum(col_widths[:end_idx + 1]) * char_w
            draw.rectangle([x_start, y, x_end, y + section_h], fill=(255, 140, 0), outline=(180, 198, 231))
            label_w = len(label) * char_w
            tx = x_start + (x_end - x_start - label_w) // 2
            draw.text((tx, y + 5), label, fill=(255, 255, 255), font=font_bold)
        y += section_h

    # Column header
    x = padding
    for i, col in enumerate(cols):
        w = col_widths[i] * char_w
        draw.rectangle([x, y, x + w, y + header_h], fill=(47, 84, 150))
        draw.text((x + 4, y + 5), str(col), fill=(255, 255, 255), font=font_bold)
        x += w
    y += header_h

    # Data rows
    for row_idx in range(n_rows):
        row = summary_df.iloc[row_idx]
        is_total = (row_idx == 0) and has_total_row
        is_zebra = (row_idx % 2 == 0)

        x = padding
        for i, col in enumerate(cols):
            w = col_widths[i] * char_w
            val = row.iloc[i]

            is_alert = (col == REPLENISH_ALERT_COL)
            alert_bg, alert_fg = (None, None)
            if is_alert:
                alert_bg, alert_fg = ALERT_COLORS.get(str(val).strip(), (None, None))

            # Background
            if is_total:
                bg = (214, 220, 228)
            elif is_alert and alert_bg:
                bg = alert_bg
            elif col == 'Difference' and not is_total:
                bg = _diff_color(val if isinstance(val, (int, float)) else 0)
            elif is_zebra:
                bg = (242, 242, 242)
            else:
                bg = (255, 255, 255)

            draw.rectangle([x, y, x + w, y + row_h], fill=bg, outline=(180, 198, 231))

            # Text
            txt = _fmt_summary_cell(col, val)
            f = font_bold if is_total else font
            is_numeric = isinstance(val, (int, float)) or val is None or (isinstance(val, float) and pd.isna(val))
            is_zero = is_numeric and (val == 0 or val is None or (isinstance(val, float) and pd.isna(val)))
            # Center text horizontally
            tx = x + (w - _display_width(txt) * char_w) // 2
            # Text color: light gray for 0 values, dark blue for total row, black otherwise
            if is_alert and alert_fg:
                text_color = alert_fg
            elif is_zero:
                text_color = (192, 192, 192)
            elif is_total:
                text_color = (31, 56, 100)
            else:
                text_color = (0, 0, 0)
            draw.text((tx, y + 3), txt, fill=text_color, font=f)
            x += w
        y += row_h

    # 补库建议表（主表下方）：空 1 行 → 标题 → 表头 → 数据
    if has_extra:
        y += row_h
        if extra_title:
            draw.text((padding, y), extra_title, fill=(47, 84, 150), font=extra_font_title)
            y += title_h

        x = padding
        for i, col in enumerate(extra_cols):
            w = extra_widths[i] * char_w
            draw.rectangle([x, y, x + w, y + header_h], fill=(47, 84, 150))
            draw.text((x + 4, y + 5), str(col), fill=(255, 255, 255), font=extra_font_bold)
            x += w
        y += header_h

        for row_idx in range(n_extra_rows):
            row = extra_df.iloc[row_idx]
            zebra = (242, 242, 242) if row_idx % 2 == 0 else (255, 255, 255)
            x = padding
            for i, col in enumerate(extra_cols):
                w = extra_widths[i] * char_w
                val = row.iloc[i]
                txt = _fmt_replenish_value(val)
                if col == REPLENISH_ALERT_COL:
                    bg, fg = ALERT_COLORS.get(str(val).strip(), (zebra, (0, 0, 0)))
                else:
                    bg, fg = zebra, (0, 0, 0)
                draw.rectangle([x, y, x + w, y + row_h], fill=bg, outline=(180, 198, 231))
                tx = x + (w - _display_width(txt) * char_w) // 2
                draw.text((tx, y + 3), txt, fill=fg, font=extra_font)
                x += w
            y += row_h

    for i, line in enumerate(footer_lines):
        draw.text((padding, y + 6 + i * (font_size + 12)), line, fill=(120, 120, 120), font=font)

    img.save(out_img_path, 'PNG')
    print(f"  Summary image: {out_img_path}")


# ==============================================================================
# generate_report
# ==============================================================================
def _resolve_output_path(out_path):
    """If out_path is locked by another process, append _1, _2, ... to find an available name."""
    p = Path(out_path)
    try:
        with open(out_path, 'a'):
            pass
        return out_path
    except (PermissionError, OSError):
        stem = p.stem
        suffix = p.suffix
        parent = p.parent
        seq = 1
        while True:
            candidate = parent / f'{stem}_{seq}{suffix}'
            if not candidate.exists():
                return str(candidate)
            try:
                with open(str(candidate), 'a'):
                    pass
                return str(candidate)
            except (PermissionError, OSError):
                seq += 1


# 过滤条件说明行：写在每个 sheet 标题下方，方便收件人直接核对报表口径。
# kind: 'inbound' / 'outbound' / 'inventory' / 'summary'
def _build_filter_note(kind, material_type, warehouse_name=''):
    """Build the filter-condition caption shown under a sheet title."""
    parts = [f'Material Type = {material_type}']
    if warehouse_name:
        parts.append(f"Warehouse Name = '{warehouse_name}'")
    parts.append(f"Warehouse Name \u2260 '{EXCLUDE_WAREHOUSE}'")
    if kind in ('inbound', 'outbound'):
        parts.append('Excluded orders: in&out_exclude.xlsx [sheet 3: excluded order serial details]')
        parts.append(f"Operation Result Status \u2260 '{OP_RESULT_DROP_STATUS[0]}'")
    if kind == 'outbound':
        parts.append(f"Status \u2260 '{OUTBOUND_DROP_STATUS[0]}'")
    if kind == 'summary':
        parts.append('same exclusions as the Inbound / Outbound / Inventory sheets')
    return 'Filters:  ' + '  |  '.join(parts)


def generate_report(material_type, out_path, inb_src, outb_src, inv_src, timestamp_str, warehouse_name='', generate_image=True):
    """Generate one output workbook + Summary image (optional) for a given Material Type and Warehouse."""
    out_path = _resolve_output_path(out_path)
    is_sp = material_type == 'SpareParts'
    inbound_cols = SP_INBOUND_COLS if is_sp else CS_INBOUND_COLS
    outbound_cols = SP_OUTBOUND_COLS if is_sp else CS_OUTBOUND_COLS

    inb_df = inb_src.loc[inb_src['Material Type'].eq(material_type), inbound_cols]
    outb_df = outb_src.loc[outb_src['Material Type'].eq(material_type), outbound_cols]
    inv_df = inv_src.loc[inv_src['Material Type'].eq(material_type), INVENTORY_COLS]

    summary = build_summary(inb_df, outb_df, inv_df)
    # 补库建议：4 列按 Material Name 并到 Summary-Current 汇总表右侧（同一行）
    # （历史消耗已剔除 REPLENISH_EXCLUDE_ORDERS 两张异常单据，以及 Repair Outbound 报修出库）
    base_cols = list(summary.columns)
    total_mask = summary['Material Name'].astype(str).str.strip().eq('Total')
    body = summary.loc[~total_mask].copy()
    replenish = build_replenishment(outb_df, inv_df,
                                    base_index=body['Material Name'].tolist(),
                                    summary_qty=body[['Material Name', 'Inbound Qty',
                                                      'Outbound Qty', 'Inventory Qty']])
    body[REPLENISH_EXTRA_COLS] = replenish[REPLENISH_EXTRA_COLS].to_numpy()
    total_row = summary.loc[total_mask].copy()
    for c in REPLENISH_DEC_COLS:                          # Avg：各行保留 2 位小数，合计也为 2 位小数
        total_row[c] = round(float(body[c].sum()), 2)
    for c in REPLENISH_INT_COLS:                         # Safety / Replenishment Qty：各行已取整，合计仍为整数
        total_row[c] = int(body[c].sum())
    total_row[REPLENISH_ALERT_COL] = None                 # Alert Level 合计无意义，留空
    total_row[REPLENISH_REMARK_COL] = None                # Remark 合计无意义，留空
    summary = pd.concat([total_row, body], ignore_index=True)[base_cols + REPLENISH_EXTRA_COLS]
    summary_changed, warehouses = build_summary_changed(inb_df, outb_df, timestamp_str)
    title_prefix = 'SpareParts' if is_sp else 'Consumables'
    
    # Add warehouse name to title if provided
    warehouse_suffix = f' - {warehouse_name}' if warehouse_name else ''

    # Fill None with 0 for Excel output
    summary_changed_filled = summary_changed.fillna(0)

    # 每个 sheet 标题下的过滤条件说明（与 generate_report 实际套用的过滤链保持一致）
    note_in = _build_filter_note('inbound', material_type, warehouse_name)
    note_out = _build_filter_note('outbound', material_type, warehouse_name)
    note_inv = _build_filter_note('inventory', material_type, warehouse_name)
    note_sum = _build_filter_note('summary', material_type, warehouse_name)

    # Write Excel
    with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
        summary.to_excel(writer, sheet_name='Summary-Current', index=False)
        summary_changed_filled.to_excel(writer, sheet_name='Summary-Changed', index=False)
        inb_df.to_excel(writer, sheet_name='Inbound', index=False)
        outb_df.to_excel(writer, sheet_name='Outbound', index=False)
        inv_df.to_excel(writer, sheet_name='Inventory', index=False)

        # 补库建议的 4 列已并进汇总表右侧；口径说明写在表头之上（见 extra_notes）
        cur = writer.sheets['Summary-Current']
        cur_len = len(summary) + 1                                   # 汇总表占用的行数（表头 + 数据）

        style_excel(cur, 'Summary-Current', has_total_row=True,
                    title=f'{title_prefix} Inbound & Outbound & Inventory Summary{warehouse_suffix}',
                    filter_note=note_sum, table_rows=cur_len,
                    extra_notes=replenish_notes())
        style_summary_changed(writer.sheets['Summary-Changed'], 'Summary-Changed', warehouses,
                              title=f'{title_prefix} Daily Statistics{warehouse_suffix}',
                              filter_note=note_sum)
        style_excel(writer.sheets['Inbound'], 'Inbound',
                    title=f'{title_prefix} Inbound Details{warehouse_suffix}',
                    filter_note=note_in)
        style_excel(writer.sheets['Outbound'], 'Outbound',
                    title=f'{title_prefix} Outbound Details{warehouse_suffix}',
                    filter_note=note_out)
        style_excel(writer.sheets['Inventory'], 'Inventory',
                    title=f'{title_prefix} Inventory Details{warehouse_suffix}',
                    filter_note=note_inv)

    print(f'Generated: {out_path}')
    print(f'  Inbound: {len(inb_df)}, Outbound: {len(outb_df)}, Inventory: {len(inv_df)}, Summary: {len(summary)}')

    # Generate Summary PNG (optional)
    if generate_image:
        # Summary-Current image
        img_path = Path(out_path).with_suffix('.png')
        img_path = _resolve_output_path(str(img_path))
        _render_summary_image(summary, img_path,
                              title=f'{title_prefix} Summary{warehouse_suffix}  |  {timestamp_str}',
                              notes=replenish_notes())

        # Summary-Changed image: filter by date, keep rows up to yesterday
        if len(summary_changed) > 0:
            current_date = datetime.strptime(timestamp_str.split()[0], '%Y-%m-%d')
            current_day = current_date.day
            # Parse day number from WH&DOP column (format: "1-Jul", "2-Jul", etc.)
            day_nums = summary_changed['WH&DOP'].astype(str).str.split('-').str[0].astype(int)
            mask = day_nums < current_day
            summary_changed_filtered = summary_changed.loc[mask].fillna(0)

            # Rename columns for display: remove _out suffix (section header shows Inbound/Outbound)
            col_rename = {}
            for c in summary_changed_filtered.columns:
                if c == 'WH&DOP':
                    col_rename[c] = c
                elif str(c).endswith('_out'):
                    col_rename[c] = str(c)[:-4]
                else:
                    col_rename[c] = c
            summary_changed_display = summary_changed_filtered.rename(columns=col_rename)

            # Build section groups: Inbound columns and Outbound columns
            num_wh = len(warehouses)
            section_groups = [
                ('Inbound', 1, num_wh),
                ('Outbound', num_wh + 1, 2 * num_wh),
            ] if num_wh > 0 else None

            changed_img_path = str(Path(out_path).parent / f'{Path(out_path).stem} Summary-Changed.png')
            changed_img_path = _resolve_output_path(changed_img_path)
            _render_summary_image(summary_changed_display, changed_img_path,
                                  title=f'{title_prefix} Daily Statistics{warehouse_suffix}  |  {timestamp_str}',
                                  has_total_row=False,
                                  row_h=56, char_w=7, font_size=16,
                                  section_groups=section_groups)


# ==============================================================================
# main
# ==============================================================================
def _cleanup_old_reports():
    """Delete ALL previously generated report files (xlsx & png), keep only the latest of each warehouse and type."""
    prefixes = [
        'Comsumables Inbound&Outbound&Inventory',
        'SpareParts Inbound&Outbound&Inventory',
    ]
    out_dir = Path(OUT_DIR)
    for prefix in prefixes:
        for ext_pattern in ('xlsx', 'png'):
            # Group files by warehouse name in the filename
            files = list(out_dir.glob(f'{prefix}*.{ext_pattern}'))
            # Group by warehouse (extract from filename)
            file_groups = {}
            for f in files:
                # Try to extract warehouse name from filename
                # Format: "Comsumables Inbound&Outbound&Inventory - WarehouseName 2024-01-01 12-00-00.xlsx"
                name = f.stem
                is_changed = 'Summary-Changed' in name
                if ' - ' in name:
                    parts = name.split(' - ', 1)
                    wh_part = parts[1].rsplit(' ', 2)[0]  # remove timestamp part
                    key = f"{prefix} - {wh_part}{' Summary-Changed' if is_changed else ''}"
                else:
                    key = f"{prefix}{' Summary-Changed' if is_changed else ''}"  # no warehouse in name

                if key not in file_groups:
                    file_groups[key] = []
                file_groups[key].append(f)

            # Keep only latest in each group, delete the rest
            for group, group_files in file_groups.items():
                group_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                for f in group_files[1:]:  # skip the first (newest), delete the rest
                    try:
                        f.unlink()
                        print(f'  Deleted old: {f.name}')
                    except Exception as e:
                        print(f'  Failed to delete {f.name}: {e}')


def main():
    t0 = datetime.now()
    timestamp_str = datetime.now().strftime('%Y-%m-%d %H-%M-%S')

    # Step 1: SFTP download
    sftp_download()

    # Step 1.5: 原样留一份未过滤快照（SP Details Report 用），必须在任何过滤之前
    snapshot_raw_details()

    # Step 2: Load data
    inb, inv, outb = load_data()
    print(f'Loaded - inbound: {len(inb)}, inventory: {len(inv)}, outbound: {len(outb)}')

    # Step 2.1: 按 in&out_exclude.xlsx 剔除指定单据行（先处理，再生成报告 / 保存）
    inb, outb, _excl_stats = apply_exclude_to_details(inb, outb)
    print(f'After exclude list: inbound: {len(inb)}, outbound: {len(outb)}')

    # Step 2.2: 出库明细剔除 Status='WaitingForUpdate'，并写回保存
    inb, outb, _status_stats = apply_status_filters(inb, outb)

    # Step 2.3: 入库/出库明细剔除 Operation Result Status='Canceled'，并写回保存
    inb, outb, _opres_stats = apply_operation_result_filter(inb, outb)

    # Step 2.4: 转仓明细（只进 SP Details Report）同样剔除 Canceled 行，并写回保存
    _opres_transfer = apply_operation_result_filter_to_file(TRANSFER_PATH, 'transfer')
    _opres_transfer_ret = apply_operation_result_filter_to_file(TRANSFER_RETURN_PATH, 'transfer_return')

    # Step 2.5: 用 inventory 的 Material Name / Material Type 覆盖两份明细同名字段，并写回保存
    inb, outb, _matname_stats = apply_inventory_fields(inb, outb, inv)

    # Step 3: Filter inbound and outbound types  —— 2026-09-08 停用（保留 ②仓库 与 ③Material Type）
    # inb, outb = filter_data(inb, outb)
    # print(f'After filtering: inbound: {len(inb)}, outbound: {len(outb)}')

    # Step 4: Preprocess (exclude warehouse)
    inb, inv, outb = preprocess([inb, inv, outb])
    print(f'After excluding "{EXCLUDE_WAREHOUSE}": inbound: {len(inb)}, inventory: {len(inv)}, outbound: {len(outb)}')

    # Step 5: Build lookup tables
    mno_to_name, mn_to_domain = build_lookup([inb, inv, outb])
    print(f'Lookup tables: mat_no_to_name={len(mno_to_name)}, mat_name_to_domain={len(mn_to_domain)}')

    # Step 6: Fill missing values
    for name, df in [('inbound', inb), ('inventory', inv), ('outbound', outb)]:
        before_mn = df['Material Name'].isna().sum()
        before_dm = df['Domain'].isna().sum()
        fill_missing(df, mno_to_name, mn_to_domain)
        after_mn = df['Material Name'].isna().sum()
        after_dm = df['Domain'].isna().sum()
        print(f'  {name}: Material Name filled={before_mn - after_mn}, Domain filled={before_dm - after_dm}')

    # Step 7: Generate total reports (keep original logic, with image)
    cs_total_out = f'{OUT_DIR}/Comsumables Inbound&Outbound&Inventory {timestamp_str}.xlsx'
    sp_total_out = f'{OUT_DIR}/SpareParts Inbound&Outbound&Inventory {timestamp_str}.xlsx'
    generate_report('Consumables', cs_total_out, inb, outb, inv, timestamp_str, warehouse_name='', generate_image=True)
    generate_report('SpareParts', sp_total_out, inb, outb, inv, timestamp_str, warehouse_name='', generate_image=True)

    # Step 8: Split data by warehouse
    warehouse_data = split_by_warehouse(inb, outb, inv)
    print(f'\nFound {len(warehouse_data)} warehouses: {list(warehouse_data.keys())}')

    # Step 9: Generate reports for each warehouse (no image)
    for warehouse, (inb_wh, outb_wh, inv_wh) in warehouse_data.items():
        # Sanitize warehouse name for filename (remove invalid chars)
        safe_wh = warehouse.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')

        # Generate Consumables report (no image)
        cs_out = f'{OUT_DIR}/Comsumables Inbound&Outbound&Inventory - {safe_wh} {timestamp_str}.xlsx'
        generate_report('Consumables', cs_out, inb_wh, outb_wh, inv_wh, timestamp_str, warehouse_name=warehouse, generate_image=False)

        # Generate SpareParts report (no image)
        sp_out = f'{OUT_DIR}/SpareParts Inbound&Outbound&Inventory - {safe_wh} {timestamp_str}.xlsx'
        generate_report('SpareParts', sp_out, inb_wh, outb_wh, inv_wh, timestamp_str, warehouse_name=warehouse, generate_image=False)

    # Step 10: Cleanup old reports, keep only the latest
    print('\nCleaning up old reports...')
    _cleanup_old_reports()

    # 末尾复述剔除结果（任务日志只保留尾部输出，方便线上核对）
    if _excl_stats:
        print(f'[Exclude] 汇总: inbound 剔除 {_excl_stats.get("inbound", 0)} 行, '
              f'outbound 剔除 {_excl_stats.get("outbound", 0)} 行')
    if _status_stats:
        print(f'[Status] 汇总: outbound 剔除 WaitingForUpdate {_status_stats.get("outbound", 0)} 行')
    if _matname_stats:
        print(f'[MatSync] 汇总: inbound 覆盖 {_matname_stats.get("inbound", 0)} 行, '
              f'outbound 覆盖 {_matname_stats.get("outbound", 0)} 行')
    if _opres_stats or _opres_transfer or _opres_transfer_ret:
        print(f'[OpResult] 汇总: inbound 剔除 {_opres_stats.get("inbound", 0)} 行, '
              f'outbound 剔除 {_opres_stats.get("outbound", 0)} 行, '
              f'transfer 剔除 {_opres_transfer} 行, '
              f'transfer_return 剔除 {_opres_transfer_ret} 行')

    elapsed = (datetime.now() - t0).total_seconds()
    print(f'Done. Total time: {elapsed:.1f}s')


if __name__ == '__main__':
    main()

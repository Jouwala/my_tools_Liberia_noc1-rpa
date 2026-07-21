# -*- coding: utf-8 -*-
"""
Download data from SFTP, then generate Comsumables & SpareParts
Inbound&Outbound&Inventory Excel files with Summary images.

Pipeline:
  sftp_download() → load_data() → preprocess() → build_lookup() → fill_missing()
  → generate_report() (Excel + Summary PNG image)
"""
import pandas as pd
import numpy as np
import paramiko
import stat
import os
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
DATA_DIR = str(_SCRIPT_DIR / 'data')
OUT_DIR = str(_SCRIPT_DIR)
EXCLUDE_WAREHOUSE = 'Liberia Monrovia material warehouse'

INB_PATH = f'{DATA_DIR}/inband_details.xlsx'
INV_PATH = f'{DATA_DIR}/inventory_details.xlsx'
OUTB_PATH = f'{DATA_DIR}/outband_details.xlsx'

# SFTP config
SFTP_HOST = "10.100.20.11"
SFTP_PORT = 22
SFTP_USER = "ubuntu"
SFTP_PASS = "UbuntU1!2@3#4$"

SFTP_FOLDERS = {
    "spinbound": "data/inband_details.xlsx",
    "spoutbound": "data/outband_details.xlsx",
    "spinventory": "data/inventory_details.xlsx",
}

SFTP_SPECIAL = {
    "ocrule": {
        "remote_folder": "OCAuto/OCAutoOutput",
        "local_path": "data/ocrule_details.xlsx",
        "search_func": "find_latest_ocrule_csv_recursive",
        "convert_to_excel": True,
    },
    "transfer": {
        "remote_folder": "sp/sp-wh_transfer",
        "local_path": "data/transfer_details.xlsx",
        "search_func": "find_latest_transfer_xlsx_recursive",
        "convert_to_excel": False,
    },
}

CS_INBOUND_COLS = ['Inbound No.', 'Inbound Type', 'Warehouse Name', 'Material No.',
                   'Serial No.', 'Material Name', 'Domain', 'Inbound Qty',
                   'Unit', 'Location No.', 'Inbound Time']
SP_INBOUND_COLS = ['Inbound No.', 'Inbound Type', 'Warehouse Name', 'Material No.',
                   'Serial No.', 'Material Name', 'Domain', 'Material Type',
                   'Inbound Qty', 'Unit', 'Inbound Time']

CS_OUTBOUND_COLS = ['Outbound No.', 'Warehouse Name', 'Outbound Type', 'Recipient',
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

INVENTORY_COLS = ['Serial No.', 'Material No.', 'Material Name', 'Warehouse Name',
                  'Domain', 'Storage Age', 'Stock Qty', 'Unit ', 'Location Name']

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

SHEET_COLORS = {
    'Summary': '2F5496',
    'Inbound': '548235',
    'Outbound': 'BF8F00',
    'Inventory': '843C0C',
}

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
    client = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    client.connect(username=SFTP_USER, password=SFTP_PASS)
    sftp = paramiko.SFTPClient.from_transport(client)

    # Special files
    for name, cfg in SFTP_SPECIAL.items():
        search_fn = _SFTP_SEARCH_FUNCS[cfg["search_func"]]
        remote = search_fn(sftp, cfg["remote_folder"])
        if remote:
            _sftp_download_file(sftp, remote, cfg["local_path"], cfg["convert_to_excel"])
            print(f"  [OK] {name}: {remote} → {cfg['local_path']}")
        else:
            print(f"  [WARN] {name}: file not found")

    # Regular folders
    for folder, local_path in SFTP_FOLDERS.items():
        remote_folder = f"sp/{folder}"
        remote = _find_latest_excel_in_nested(sftp, remote_folder)
        if remote:
            _sftp_download_file(sftp, remote, local_path)
            print(f"  [OK] {folder}: {remote} → {local_path}")
        else:
            print(f"  [WARN] {folder}: file not found")

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
# build_summary - vectorized with Balance & Difference
# ==============================================================================
def build_summary(inb_df, outb_df, inv_df):
    """Build summary with Material Name, Inbound, Outbound, Inventory, Balance, Difference.
    Total row at the top."""
    inb_sum = inb_df.groupby('Material Name', sort=True)['Inbound Qty'].sum()
    outb_sum = outb_df.groupby('Material Name', sort=True)['Outbound Qty'].sum()
    inv_sum = inv_df.groupby('Material Name', sort=True)['Stock Qty'].sum()

    merged = pd.DataFrame({
        'Inbound Qty': inb_sum, 'Outbound Qty': outb_sum, 'Inventory Qty': inv_sum,
    }).reset_index().sort_values('Material Name').reset_index(drop=True)

    for c in ['Inbound Qty', 'Outbound Qty', 'Inventory Qty']:
        merged[c] = merged[c].fillna(0)

    merged['Balance'] = merged['Inbound Qty'] - merged['Outbound Qty']
    merged['Difference'] = merged['Inventory Qty'] - merged['Balance']
    merged = merged[['Material Name', 'Inbound Qty', 'Outbound Qty', 'Inventory Qty', 'Balance', 'Difference']]

    total = pd.DataFrame({
        'Material Name': ['Total'],
        'Inbound Qty': [merged['Inbound Qty'].sum()],
        'Outbound Qty': [merged['Outbound Qty'].sum()],
        'Inventory Qty': [merged['Inventory Qty'].sum()],
        'Balance': [merged['Balance'].sum()],
        'Difference': [merged['Difference'].sum()],
    })
    return pd.concat([total, merged], ignore_index=True)


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


def _insert_title(ws, title, sheet_name):
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


def _apply_header(ws, header_row=3):
    for cell in ws[header_row]:
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_HEADER
        cell.border = BORDER_HEADER


def _apply_zebra(ws, start_row=4):
    for row_idx in range(start_row, ws.max_row + 1):
        fill = FILL_ZEBRA if row_idx % 2 == 0 else FILL_WHITE
        for cell in ws[row_idx]:
            cell.fill = fill
            cell.font = FONT_CELL
            cell.border = BORDER_CELL
            cell.alignment = ALIGN_CELL
            if isinstance(cell.value, (int, float)):
                cell.alignment = ALIGN_NUM
                cell.number_format = NUM_FMT_INT


def _apply_total_row(ws, row_idx=4):
    for cell in ws[row_idx]:
        cell.font = FONT_TOTAL
        cell.fill = FILL_TOTAL
        cell.border = BORDER_TOTAL
        if isinstance(cell.value, (int, float)):
            cell.alignment = ALIGN_NUM
            cell.number_format = NUM_FMT_INT


def _apply_conditional(ws, sheet_name, header_row=3, data_start=5):
    last_row = ws.max_row
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


def _apply_page_setup(ws):
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=0.4, right=0.4, top=0.5, bottom=0.5, header=0.3, footer=0.3)


def style_excel(ws, sheet_name, has_total_row=False, title=''):
    has_title = bool(title)
    if has_title:
        _insert_title(ws, title, sheet_name)

    header_row = 3 if has_title else 1
    data_start = 4 if has_title else 2
    total_row = data_start

    _apply_header(ws, header_row)
    _apply_zebra(ws, start_row=data_start)
    if has_total_row:
        _apply_total_row(ws, row_idx=total_row)
    _apply_conditional(ws, sheet_name, header_row=header_row, data_start=total_row + 1)
    _auto_width(ws)
    ws.freeze_panes = f'A{header_row + 1}'
    ws.auto_filter.ref = f'A{header_row}:{get_column_letter(ws.max_column)}{ws.max_row}'
    if sheet_name in SHEET_COLORS:
        ws.sheet_properties.tabColor = SHEET_COLORS[sheet_name]
    _apply_page_setup(ws)


def style_summary_changed(ws, sheet_name, warehouses, title=''):
    """Style the Summary-Changed sheet with merged headers for Inbound and Outbound sections."""
    has_title = bool(title)
    if has_title:
        _insert_title(ws, title, sheet_name)

    header_row = 3 if has_title else 1
    data_start = 4 if has_title else 2

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
                    # Zero value: light gray background
                    cell.fill = FILL_LIGHT_GRAY
                    cell.font = FONT_CELL
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


def _render_summary_image(summary_df, out_img_path, title=''):
    """Render Summary DataFrame as a PNG image using Pillow."""
    cols = summary_df.columns.tolist()
    n_rows = len(summary_df)
    n_cols = len(cols)

    # Dimensions
    col_widths = []
    for c in cols:
        max_w = len(str(c))
        for v in summary_df[c]:
            max_w = max(max_w, len(str(v)))
        col_widths.append(max_w + 4)

    try:
        font = ImageFont.truetype("arial.ttf", 14)
        font_bold = ImageFont.truetype("arialbd.ttf", 14)
        font_title = ImageFont.truetype("arialbd.ttf", 18)
    except Exception:
        font = ImageFont.load_default()
        font_bold = font
        font_title = font

    char_w = 9
    char_h = 22
    row_h = 28
    header_h = 32
    title_h = 40
    padding = 16

    total_w = sum(col_widths) * char_w + padding * 2
    total_h = title_h + header_h + n_rows * row_h + padding * 2

    img = Image.new('RGB', (total_w, total_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = padding
    # Title
    if title:
        draw.text((padding, y), title, fill=(47, 84, 150), font=font_title)
        y += title_h

    # Header
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
        is_total = (row_idx == 0)
        is_zebra = (row_idx % 2 == 0)

        x = padding
        for i, col in enumerate(cols):
            w = col_widths[i] * char_w
            val = row[col]

            # Background
            if is_total:
                bg = (214, 220, 228)
            elif col == 'Difference' and not is_total:
                bg = _diff_color(val if isinstance(val, (int, float)) else 0)
            elif is_zebra:
                bg = (242, 242, 242)
            else:
                bg = (255, 255, 255)

            draw.rectangle([x, y, x + w, y + row_h], fill=bg, outline=(180, 198, 231))

            # Text
            txt = f"{int(val):,}" if isinstance(val, (int, float)) else str(val)
            f = font_bold if is_total else font
            align_right = isinstance(val, (int, float))
            tx = x + w - len(txt) * char_w - 4 if align_right else x + 4
            draw.text((tx, y + 3), txt, fill=(31, 56, 100) if is_total else (0, 0, 0), font=f)
            x += w
        y += row_h

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
    summary_changed, warehouses = build_summary_changed(inb_df, outb_df, timestamp_str)
    title_prefix = 'SpareParts' if is_sp else 'Consumables'
    
    # Add warehouse name to title if provided
    warehouse_suffix = f' - {warehouse_name}' if warehouse_name else ''

    # Write Excel
    with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
        summary.to_excel(writer, sheet_name='Summary-Current', index=False)
        summary_changed.to_excel(writer, sheet_name='Summary-Changed', index=False)
        inb_df.to_excel(writer, sheet_name='Inbound', index=False)
        outb_df.to_excel(writer, sheet_name='Outbound', index=False)
        inv_df.to_excel(writer, sheet_name='Inventory', index=False)

        style_excel(writer.sheets['Summary-Current'], 'Summary-Current', has_total_row=True,
                    title=f'{title_prefix} Inbound & Outbound & Inventory Summary{warehouse_suffix}')
        style_summary_changed(writer.sheets['Summary-Changed'], 'Summary-Changed', warehouses,
                              title=f'{title_prefix} Daily Statistics{warehouse_suffix}')
        style_excel(writer.sheets['Inbound'], 'Inbound',
                    title=f'{title_prefix} Inbound Details{warehouse_suffix}')
        style_excel(writer.sheets['Outbound'], 'Outbound',
                    title=f'{title_prefix} Outbound Details{warehouse_suffix}')
        style_excel(writer.sheets['Inventory'], 'Inventory',
                    title=f'{title_prefix} Inventory Details{warehouse_suffix}')

    print(f'Generated: {out_path}')
    print(f'  Inbound: {len(inb_df)}, Outbound: {len(outb_df)}, Inventory: {len(inv_df)}, Summary: {len(summary)}')

    # Generate Summary PNG (optional)
    if generate_image:
        img_path = Path(out_path).with_suffix('.png')
        img_path = _resolve_output_path(str(img_path))
        # If the xlsx got a suffix like _1, apply same suffix to png
        _render_summary_image(summary, img_path,
                              title=f'{title_prefix} Summary{warehouse_suffix}  |  {timestamp_str}')


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
                if ' - ' in name:
                    parts = name.split(' - ', 1)
                    wh_part = parts[1].rsplit(' ', 2)[0]  # remove timestamp part
                    key = f"{prefix} - {wh_part}"
                else:
                    key = prefix  # no warehouse in name

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

    # Step 2: Load data
    inb, inv, outb = load_data()
    print(f'Loaded - inbound: {len(inb)}, inventory: {len(inv)}, outbound: {len(outb)}')

    # Step 3: Filter inbound and outbound types
    inb, outb = filter_data(inb, outb)
    print(f'After filtering: inbound: {len(inb)}, outbound: {len(outb)}')

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

    elapsed = (datetime.now() - t0).total_seconds()
    print(f'Done. Total time: {elapsed:.1f}s')


if __name__ == '__main__':
    main()

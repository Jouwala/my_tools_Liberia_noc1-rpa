import os
import sys
import sqlite3
import pandas as pd
from flask import Flask, render_template, jsonify, request, session, make_response
from datetime import datetime, timedelta
from functools import wraps

# 添加当前目录和父目录到 sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from shared.dashboard_email_renderer import render_dashboard_email_html

# 动态导入 user_manager，确保能找到模块
try:
    from user_manager import UserManager, login_required, admin_required
except ImportError:
    import importlib.util
    user_manager_path = os.path.join(current_dir, 'user_manager.py')
    spec = importlib.util.spec_from_file_location("user_manager", user_manager_path)
    if spec and spec.loader:
        user_manager_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(user_manager_module)
        UserManager = user_manager_module.UserManager
        login_required = user_manager_module.login_required
        admin_required = user_manager_module.admin_required
    else:
        raise ImportError("无法加载 user_manager 模块")

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OVERVIEW_PATH = os.path.join(DATA_DIR, "sp_overview.xlsx")
DB_PATH = os.path.join(os.path.dirname(__file__), "inventory.db")
USERS_DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")
COLUMN_MAPPING_PATH = os.path.join(os.path.dirname(__file__), "detect_column_name", "column_mapping.xlsx")
DETAIL_FILES = {
    "inband": os.path.join(DATA_DIR, "inband_details.xlsx"),
    "outband": os.path.join(DATA_DIR, "outband_details.xlsx"),
    "inventory": os.path.join(DATA_DIR, "inventory_details.xlsx"),
}
DETAIL_TITLES = {
    "inband": "Inband Details View",
    "outband": "Outbound Details View",
    "inventory": "Inventory Details View",
}

# 初始化用户管理器
user_manager = UserManager(USERS_DB_PATH)

# 将 user_manager 附加到装饰器上，以便在装饰器中使用
login_required.user_manager = user_manager
admin_required.user_manager = user_manager


def load_excel_data():
    """读取 overview Excel 所有 Sheet 并转换为字典格式"""
    if not os.path.exists(OVERVIEW_PATH):
        return {}
    excel_data = pd.read_excel(OVERVIEW_PATH, sheet_name=None)
    result = {}
    for sheet_name, df in excel_data.items():
        result[sheet_name] = df.fillna("").to_dict(orient="records")
    return result


def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def parse_date_from_string(date_str):
    """从字符串解析日期，返回 datetime 对象或 None"""
    if not date_str:
        return None
    date_str = str(date_str).strip()
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str[:19] if len(date_str) > 19 else date_str, fmt)
        except ValueError:
            continue
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except ValueError:
        return None


def load_inband_stats_from_db(date_start=None, date_end=None):
    """
    从 inventory.db 的 inband_details 表获取 Inbound Ticket 统计数据。
    时间从 Inbound Time 列过滤。
    返回: {'Total': X, 'Closed': Y, 'Unclosed': Z}
    """
    if not os.path.exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0}
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT `Inbound No.`, `Status`, `Inbound Time` FROM inband_details"
    params = []
    
    if date_start or date_end:
        conditions = []
        if date_start:
            conditions.append("`Inbound Time` >= ?")
            params.append(date_start + " 00:00:00")
        if date_end:
            conditions.append("`Inbound Time` <= ?")
            params.append(date_end + " 23:59:59")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    inbound_nos = set()
    closed_nos = set()
    unclosed_nos = set()
    
    for row in rows:
        inbound_no = row['Inbound No.']
        status = row['Status']
        
        if inbound_no:
            inbound_nos.add(inbound_no)
            if status and status.lower() == 'closed':
                closed_nos.add(inbound_no)
            else:
                unclosed_nos.add(inbound_no)
    
    return {
        "Total": len(inbound_nos),
        "Closed": len(closed_nos),
        "Unclosed": len(unclosed_nos)
    }


def load_inbound_details_from_db(date_start=None, date_end=None):
    """
    从 inventory.db 的 inband_details 表获取 Inbound Details 数据。
    时间从 Inbound Time 列过滤。
    根据 Inbound Type 类别统计：
    - Total: Inbound No. 列非重复的个数
    - Inbound Qty: Stock Qty 列数字求和 (注意: 数据库中是 Inbound Qty)
    - Closed: Inbound No. 列非重复的个数并且 Status 列是 "Closed"
    - Unclosed: Inbound No. 列非重复的个数并且 Status 列不是 "Closed"
    """
    if not os.path.exists(DB_PATH):
        return []
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT `Inbound No.`, `Status`, `Inbound Type`, `Inbound Qty`, `Inbound Time`
        FROM inband_details
    """
    params = []
    
    if date_start or date_end:
        conditions = []
        if date_start:
            conditions.append("`Inbound Time` >= ?")
            params.append(date_start + " 00:00:00")
        if date_end:
            conditions.append("`Inbound Time` <= ?")
            params.append(date_end + " 23:59:59")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    type_stats = {}
    
    for row in rows:
        inbound_type = row['Inbound Type'] or 'Unknown'
        inbound_no = row['Inbound No.']
        status = row['Status']
        inbound_qty = row['Inbound Qty'] or 0
        
        if inbound_type not in type_stats:
            type_stats[inbound_type] = {
                'inbound_nos': set(),
                'closed_nos': set(),
                'unclosed_nos': set(),
                'total_qty': 0
            }
        
        if inbound_no:
            type_stats[inbound_type]['inbound_nos'].add(inbound_no)
            type_stats[inbound_type]['total_qty'] += int(inbound_qty) if inbound_qty else 0
            
            if status and status.lower() == 'closed':
                type_stats[inbound_type]['closed_nos'].add(inbound_no)
            else:
                type_stats[inbound_type]['unclosed_nos'].add(inbound_no)
    
    result = []
    for inbound_type, stats in type_stats.items():
        result.append({
            'Inbound Type': inbound_type,
            'Total': len(stats['inbound_nos']),
            'Inbound Qty': stats['total_qty'],
            'Closed': len(stats['closed_nos']),
            'Unclosed': len(stats['unclosed_nos'])
        })
    
    return result


def load_outband_stats_from_db(date_start=None, date_end=None):
    """
    从 inventory.db 的 outband_details 表获取 Outbound Ticket 统计数据。
    时间从 Outbound Time 列过滤。
    返回: {'Total': X, 'Closed': Y, 'Unclosed': Z}
    """
    if not os.path.exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0}
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT `Outbound No.`, `Status`, `Outbound Time` FROM outband_details"
    params = []
    
    if date_start or date_end:
        conditions = []
        if date_start:
            conditions.append("`Outbound Time` >= ?")
            params.append(date_start + " 00:00:00")
        if date_end:
            conditions.append("`Outbound Time` <= ?")
            params.append(date_end + " 23:59:59")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    outbound_nos = set()
    closed_nos = set()
    unclosed_nos = set()
    
    for row in rows:
        outbound_no = row['Outbound No.']
        status = row['Status']
        
        if outbound_no:
            outbound_nos.add(outbound_no)
            if status and status.lower() == 'closed':
                closed_nos.add(outbound_no)
            else:
                unclosed_nos.add(outbound_no)
    
    return {
        "Total": len(outbound_nos),
        "Closed": len(closed_nos),
        "Unclosed": len(unclosed_nos)
    }


def load_outbound_details_from_db(date_start=None, date_end=None):
    """
    从 inventory.db 的 outband_details 表获取 Outbound Details 数据。
    时间从 Outbound Time 列过滤。
    根据 Outbound Type 类别统计：
    - Total: Outbound No. 列非重复的个数
    - Stock Qty: Stock Qty 列数字求和
    - Closed: Outbound No. 列非重复的个数并且 Status 列是 "Closed"
    - Unclosed: Outbound No. 列非重复的个数并且 Status 列不是 "Closed"
    """
    if not os.path.exists(DB_PATH):
        return []
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT `Outbound No.`, `Status`, `Outbound Type`, `Stock Qty`, `Outbound Time`
        FROM outband_details
    """
    params = []
    
    if date_start or date_end:
        conditions = []
        if date_start:
            conditions.append("`Outbound Time` >= ?")
            params.append(date_start + " 00:00:00")
        if date_end:
            conditions.append("`Outbound Time` <= ?")
            params.append(date_end + " 23:59:59")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    type_stats = {}
    
    for row in rows:
        outbound_type = row['Outbound Type'] or 'Unknown'
        outbound_no = row['Outbound No.']
        status = row['Status']
        stock_qty = row['Stock Qty'] or 0
        
        if outbound_type not in type_stats:
            type_stats[outbound_type] = {
                'outbound_nos': set(),
                'closed_nos': set(),
                'unclosed_nos': set(),
                'total_qty': 0
            }
        
        if outbound_no:
            type_stats[outbound_type]['outbound_nos'].add(outbound_no)
            type_stats[outbound_type]['total_qty'] += int(stock_qty) if stock_qty else 0
            
            if status and status.lower() == 'closed':
                type_stats[outbound_type]['closed_nos'].add(outbound_no)
            else:
                type_stats[outbound_type]['unclosed_nos'].add(outbound_no)
    
    result = []
    for outbound_type, stats in type_stats.items():
        result.append({
            'Outbound Type': outbound_type,
            'Total': len(stats['outbound_nos']),
            'Stock Qty': stats['total_qty'],
            'Closed': len(stats['closed_nos']),
            'Unclosed': len(stats['unclosed_nos'])
        })
    
    return result


def load_special_outbound_stats_from_db(outbound_type, sla_days, date_start=None, date_end=None):
    """
    从数据库获取特定类型 Outbound 的统计数据。
    用于 Borrow Outbound, Repair Outbound, Inventory Lost Outbound。
    """
    if not os.path.exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0, "SLA": 0}
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT `Outbound No.`, `Status`, `Outbound Time`, `Borrow Duration`
        FROM outband_details
        WHERE `Outbound Type` = ?
    """
    params = [outbound_type]
    
    if date_start:
        query += " AND `Outbound Time` >= ?"
        params.append(date_start + " 00:00:00")
    if date_end:
        query += " AND `Outbound Time` <= ?"
        params.append(date_end + " 23:59:59")
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    outbound_nos = set()
    closed_nos = set()
    unclosed_nos = set()
    sla_count = 0
    
    for row in rows:
        outbound_no = row['Outbound No.']
        status = row['Status']
        borrow_duration = row['Borrow Duration']
        
        if outbound_no:
            outbound_nos.add(outbound_no)
            if status and status.lower() == 'closed':
                closed_nos.add(outbound_no)
            else:
                unclosed_nos.add(outbound_no)
                if borrow_duration and float(borrow_duration) > sla_days:
                    sla_count += 1
    
    return {
        "Total": len(outbound_nos),
        "Closed": len(closed_nos),
        "Unclosed": len(unclosed_nos),
        "SLA": sla_count
    }


def load_inventory_stats_from_db(date_start=None, date_end=None):
    """
    从 inventory.db 的 inventory_details 表获取 Inventory 统计数据。
    ⚠️ 特别注意：此卡片不受顶部日期选择器的影响。
    始终只查询数据库中 update_date 为最新一天的数据，代表当前实时库存状况。
    
    统计逻辑（按 Stock Qty 总和）：
    - Total: 最新一天数据中，Stock Qty 列的总和
    - Consumables: 最新一天数据中，Material Type 为 "Consumables" 的 Stock Qty 总和
    - SpareParts: 最新一天数据中，Material Type 不是 "Consumables" 的 Stock Qty 总和
    """
    if not os.path.exists(DB_PATH):
        return {"Total": 0, "Consumables_QTY": 0, "SpareParts_QTY": 0}
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 首先获取最新的 update_date
    cursor.execute("""
        SELECT MAX(`update_date`) as latest_date
        FROM inventory_details
        WHERE `update_date` IS NOT NULL AND `update_date` != ''
    """)
    latest_date_row = cursor.fetchone()
    
    if not latest_date_row or not latest_date_row['latest_date']:
        conn.close()
        return {"Total": 0, "Consumables_QTY": 0, "SpareParts_QTY": 0}
    
    latest_date = latest_date_row['latest_date']
    
    # 查询最新一天的数据
    query = """
        SELECT `Serial No.`, `Material Type`, `Stock Qty`
        FROM inventory_details
        WHERE `update_date` = ?
    """
    params = [latest_date]
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    total_qty = 0
    consumables_qty = 0
    spare_parts_qty = 0
    
    for row in rows:
        material_type = row['Material Type']
        stock_qty = row['Stock Qty'] or 0
        
        # 将 Stock Qty 转换为数字
        try:
            qty = int(stock_qty) if stock_qty else 0
        except (ValueError, TypeError):
            qty = 0
        
        # 累加总量
        total_qty += qty
        
        # 按物料类型分类累加
        if material_type and material_type.lower() == 'consumables':
            consumables_qty += qty
        else:
            spare_parts_qty += qty
    
    return {
        "Total": total_qty,
        "Consumables_QTY": consumables_qty,
        "SpareParts_QTY": spare_parts_qty
    }


def load_inventory_trend_from_db(date_start=None, date_end=None):
    """
    从 inventory.db 的 inventory_details 表获取 Inventory Quantity Trend 数据。
    时间从 update_date 列过滤。
    按时间统计：
    - Total: Stock Qty 列的总和
    - Consumables: Material Type 列是 "Consumables" 的 Stock Qty 总和
    - SpareParts: Material Type 列不是 "Consumables" 的 Stock Qty 总和
    """
    if not os.path.exists(DB_PATH):
        return []
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT `Serial No.`, `Material Type`, `update_date`, `Stock Qty`
        FROM inventory_details
    """
    params = []
    
    if date_start or date_end:
        conditions = []
        if date_start:
            conditions.append("`update_date` >= ?")
            params.append(date_start)
        if date_end:
            conditions.append("`update_date` <= ?")
            params.append(date_end)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    date_stats = {}
    
    for row in rows:
        update_date = row['update_date']
        serial_no = row['Serial No.']
        material_type = row['Material Type']
        stock_qty = row['Stock Qty'] or 0
        
        if not update_date:
            continue
        
        if update_date not in date_stats:
            date_stats[update_date] = {
                'total_qty': 0,
                'consumables_qty': 0,
                'spare_parts_qty': 0
            }
        
        # 将 Stock Qty 转换为数字
        try:
            qty = int(stock_qty) if stock_qty else 0
        except (ValueError, TypeError):
            qty = 0
        
        # 按日期累加 Stock Qty
        date_stats[update_date]['total_qty'] += qty
        
        if material_type and material_type.lower() == 'consumables':
            date_stats[update_date]['consumables_qty'] += qty
        else:
            date_stats[update_date]['spare_parts_qty'] += qty
    
    result = []
    for update_date in sorted(date_stats.keys()):
        stats = date_stats[update_date]
        result.append({
            'update_date': update_date,
            'Total': stats['total_qty'],
            'Consumables_QTY': stats['consumables_qty'],
            'SpareParts_QTY': stats['spare_parts_qty']
        })
    
    return result


def load_inbound_outbound_trend_from_db(date_start=None, date_end=None):
    """
    从数据库获取 Inbound & Outbound Tickets Trend 数据。
    时间从 update_date 列过滤（用于统一日期显示）。
    按天统计：
    - Inbound_Document_Count: inband_details 表按 Inbound Time 列统计 Inbound No. 非重复个数
    - Outbound_Document_Count: outband_details 表按 Outbound Time 列统计 Outbound No. 非重复个数
    """
    if not os.path.exists(DB_PATH):
        return []
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    inbound_query = """
        SELECT date(`Inbound Time`) as doc_date, `Inbound No.`
        FROM inband_details
        WHERE `Inbound Time` IS NOT NULL AND `Inbound Time` != ''
    """
    inbound_params = []
    if date_start:
        inbound_query += " AND `Inbound Time` >= ?"
        inbound_params.append(date_start + " 00:00:00")
    if date_end:
        inbound_query += " AND `Inbound Time` <= ?"
        inbound_params.append(date_end + " 23:59:59")
    
    cursor.execute(inbound_query, inbound_params)
    inbound_rows = cursor.fetchall()
    
    outbound_query = """
        SELECT date(`Outbound Time`) as doc_date, `Outbound No.`
        FROM outband_details
        WHERE `Outbound Time` IS NOT NULL AND `Outbound Time` != ''
    """
    outbound_params = []
    if date_start:
        outbound_query += " AND `Outbound Time` >= ?"
        outbound_params.append(date_start + " 00:00:00")
    if date_end:
        outbound_query += " AND `Outbound Time` <= ?"
        outbound_params.append(date_end + " 23:59:59")
    
    cursor.execute(outbound_query, outbound_params)
    outbound_rows = cursor.fetchall()
    conn.close()
    
    date_stats = {}
    
    for row in inbound_rows:
        doc_date = row['doc_date']
        inbound_no = row['Inbound No.']
        if doc_date and inbound_no:
            if doc_date not in date_stats:
                date_stats[doc_date] = {'inbound_nos': set(), 'outbound_nos': set()}
            date_stats[doc_date]['inbound_nos'].add(inbound_no)
    
    for row in outbound_rows:
        doc_date = row['doc_date']
        outbound_no = row['Outbound No.']
        if doc_date and outbound_no:
            if doc_date not in date_stats:
                date_stats[doc_date] = {'inbound_nos': set(), 'outbound_nos': set()}
            date_stats[doc_date]['outbound_nos'].add(outbound_no)
    
    result = []
    for doc_date in sorted(date_stats.keys()):
        stats = date_stats[doc_date]
        result.append({
            'Unified_Date': doc_date,
            'Inbound_Document_Count': len(stats['inbound_nos']),
            'Outbound_Document_Count': len(stats['outbound_nos'])
        })
    
    return result


def load_detail_data(detail_type, filter_column=None, filter_value=None, filter_mode="exact",
                     first_column=None, first_value=None, date_start=None, date_end=None):
    """
    加载 inband / outband / inventory 详情。
    从数据库读取并支持时间过滤。
    先按 first_column == first_value 精确过滤（若提供），再按 filter_column/value/mode 过滤。
    filter_mode: exact | contains | not_contains
    返回 (title, columns, records)。
    """
    if detail_type == "inband" and os.path.exists(DB_PATH):
        return load_inband_detail_from_db(filter_column, filter_value, filter_mode,
                                          first_column, first_value, date_start, date_end)
    elif detail_type == "outband" and os.path.exists(DB_PATH):
        return load_outband_detail_from_db(filter_column, filter_value, filter_mode,
                                           first_column, first_value, date_start, date_end)
    elif detail_type == "inventory" and os.path.exists(DB_PATH):
        return load_inventory_detail_from_db(filter_column, filter_value, filter_mode,
                                             first_column, first_value, date_start, date_end)
    
    path = DETAIL_FILES.get(detail_type)
    if not path or not os.path.exists(path):
        return DETAIL_TITLES.get(detail_type, detail_type), [], []
    df = pd.read_excel(path)
    df = df.fillna("")
    if first_column and first_column in df.columns and first_value is not None:
        first_val_str = str(first_value).strip()
        if first_val_str:
            fc = df[first_column].astype(str).str.strip()
            df = df.loc[fc == first_val_str]
    if filter_column and filter_column in df.columns and filter_value is not None:
        filter_val_str = str(filter_value).strip()
        if filter_val_str:
            col = df[filter_column].astype(str).str.strip()
            mode = (filter_mode or "exact").strip().lower()
            if mode == "contains":
                df = df.loc[col.str.lower().str.contains(filter_val_str.lower(), na=False)]
            elif mode == "not_contains":
                df = df.loc[~col.str.lower().str.contains(filter_val_str.lower(), na=False)]
            else:
                df = df.loc[col == filter_val_str]
    columns = list(df.columns)
    records = df.to_dict(orient="records")
    for r in records:
        for k, v in r.items():
            if not isinstance(v, (str, int, float, type(None))):
                r[k] = str(v)
    return DETAIL_TITLES.get(detail_type, detail_type), columns, records


def load_inband_detail_from_db(filter_column=None, filter_value=None, filter_mode="exact",
                               first_column=None, first_value=None, date_start=None, date_end=None):
    """
    从数据库加载 inband 详情数据，支持时间过滤。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(inband_details)")
    columns_info = cursor.fetchall()
    columns = [col[1] for col in columns_info]
    
    query = "SELECT * FROM inband_details WHERE 1=1"
    params = []
    
    if date_start:
        query += " AND `Inbound Time` >= ?"
        params.append(date_start + " 00:00:00")
    if date_end:
        query += " AND `Inbound Time` <= ?"
        params.append(date_end + " 23:59:59")
    
    if first_column and first_value:
        query += f" AND `{first_column}` = ?"
        params.append(first_value)
    
    if filter_column and filter_value:
        filter_val_str = str(filter_value).strip()
        if filter_mode == "contains":
            query += f" AND LOWER(`{filter_column}`) LIKE ?"
            params.append(f"%{filter_val_str.lower()}%")
        elif filter_mode == "not_contains":
            query += f" AND LOWER(`{filter_column}`) NOT LIKE ?"
            params.append(f"%{filter_val_str.lower()}%")
        else:
            query += f" AND `{filter_column}` = ?"
            params.append(filter_val_str)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    records = []
    for row in rows:
        record = {}
        for col in columns:
            val = row[col]
            if isinstance(val, bytes):
                val = val.decode('utf-8', errors='ignore')
            record[col] = val if val is not None else ""
        records.append(record)
    
    return DETAIL_TITLES.get("inband", "Inband Details View"), columns, records


def load_outband_detail_from_db(filter_column=None, filter_value=None, filter_mode="exact",
                                first_column=None, first_value=None, date_start=None, date_end=None):
    """
    从数据库加载 outband 详情数据，支持时间过滤。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(outband_details)")
    columns_info = cursor.fetchall()
    columns = [col[1] for col in columns_info]
    
    query = "SELECT * FROM outband_details WHERE 1=1"
    params = []
    
    if date_start:
        query += " AND `Outbound Time` >= ?"
        params.append(date_start + " 00:00:00")
    if date_end:
        query += " AND `Outbound Time` <= ?"
        params.append(date_end + " 23:59:59")
    
    if first_column and first_value:
        query += f" AND `{first_column}` = ?"
        params.append(first_value)
    
    if filter_column and filter_value:
        filter_val_str = str(filter_value).strip()
        if filter_mode == "contains":
            query += f" AND LOWER(`{filter_column}`) LIKE ?"
            params.append(f"%{filter_val_str.lower()}%")
        elif filter_mode == "not_contains":
            query += f" AND LOWER(`{filter_column}`) NOT LIKE ?"
            params.append(f"%{filter_val_str.lower()}%")
        else:
            query += f" AND `{filter_column}` = ?"
            params.append(filter_val_str)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    records = []
    for row in rows:
        record = {}
        for col in columns:
            val = row[col]
            if isinstance(val, bytes):
                val = val.decode('utf-8', errors='ignore')
            record[col] = val if val is not None else ""
        records.append(record)
    
    return DETAIL_TITLES.get("outband", "Outbound Details View"), columns, records


def load_inventory_detail_from_db(filter_column=None, filter_value=None, filter_mode="exact",
                                  first_column=None, first_value=None, date_start=None, date_end=None):
    """
    从数据库加载 inventory 详情数据，支持时间过滤。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("PRAGMA table_info(inventory_details)")
    columns_info = cursor.fetchall()
    columns = [col[1] for col in columns_info]
    
    query = "SELECT * FROM inventory_details WHERE 1=1"
    params = []
    
    if date_start:
        query += " AND `update_date` >= ?"
        params.append(date_start)
    if date_end:
        query += " AND `update_date` <= ?"
        params.append(date_end)
    
    if first_column and first_value:
        query += f" AND `{first_column}` = ?"
        params.append(first_value)
    
    if filter_column and filter_value:
        filter_val_str = str(filter_value).strip()
        if filter_mode == "contains":
            query += f" AND LOWER(`{filter_column}`) LIKE ?"
            params.append(f"%{filter_val_str.lower()}%")
        elif filter_mode == "not_contains":
            query += f" AND LOWER(`{filter_column}`) NOT LIKE ?"
            params.append(f"%{filter_val_str.lower()}%")
        else:
            query += f" AND `{filter_column}` = ?"
            params.append(filter_val_str)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    records = []
    for row in rows:
        record = {}
        for col in columns:
            val = row[col]
            if isinstance(val, bytes):
                val = val.decode('utf-8', errors='ignore')
            record[col] = val if val is not None else ""
        records.append(record)
    
    return DETAIL_TITLES.get("inventory", "Inventory Details View"), columns, records


# ============ 路由和 API ============

@app.route('/')
def index():
    """主页路由，检查登录状态"""
    session_token = request.cookies.get('session_token')
    if session_token:
        user = user_manager.get_user_by_session(session_token)
        if user:
            return render_template('index.html')
    return render_template('index.html', require_login=True)


@app.route('/api/data')
def get_data():
    try:
        date_start = request.args.get('date_start')
        date_end = request.args.get('date_end')
        
        data = load_excel_data()
        
        inband_stats = load_inband_stats_from_db(date_start, date_end)
        data['Inband Ticket'] = [inband_stats]
        
        inbound_details = load_inbound_details_from_db(date_start, date_end)
        data['Inbound'] = inbound_details
        
        outband_stats = load_outband_stats_from_db(date_start, date_end)
        data['Outband Ticket'] = [outband_stats]
        
        outbound_details = load_outbound_details_from_db(date_start, date_end)
        data['Outbound'] = outbound_details
        
        borrow_stats = load_special_outbound_stats_from_db('Borrow Outbound', 45, date_start, date_end)
        data['Borrow Outbound'] = [borrow_stats]
        
        repair_stats = load_special_outbound_stats_from_db('Repair Outbound', 180, date_start, date_end)
        data['Repair Outbound'] = [repair_stats]
        
        inventory_lost_stats = load_special_outbound_stats_from_db('Inventory Lost Outbound', 1, date_start, date_end)
        data['Inventory Lost Outbound'] = [inventory_lost_stats]
        
        inventory_stats = load_inventory_stats_from_db(date_start, date_end)
        data['Inventory'] = [inventory_stats]
        
        inventory_trend = load_inventory_trend_from_db(date_start, date_end)
        data['Inventory Quantity Trend'] = inventory_trend
        
        inbound_outbound_trend = load_inbound_outbound_trend_from_db(date_start, date_end)
        data['Inbound & Outbound Ticket T'] = inbound_outbound_trend
        
        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/details')
def get_details():
    """详情数据：type=inband|outband|inventory，可选 column & value 过滤"""
    try:
        detail_type = (request.args.get("type") or "").strip().lower()
        if detail_type not in DETAIL_FILES:
            return jsonify({"status": "error", "message": "invalid type"}), 400
        filter_column = request.args.get("column") or None
        filter_value = request.args.get("value")
        filter_mode = request.args.get("mode") or "exact"
        first_column = request.args.get("first_column") or None
        first_value = request.args.get("first_value")
        date_start = request.args.get("date_start")
        date_end = request.args.get("date_end")
        title, columns, data = load_detail_data(
            detail_type, filter_column, filter_value, filter_mode,
            first_column=first_column, first_value=first_value,
            date_start=date_start, date_end=date_end,
        )
        return jsonify({
            "status": "success",
            "title": title,
            "columns": columns,
            "data": data,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ============ 用户管理 API ============

@app.route('/api/user/register', methods=['POST'])
def register_user():
    """用户注册"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        email = data.get('email', '').strip()
        full_name = data.get('full_name', '').strip()
        
        if not username:
            return jsonify({"status": "error", "message": "用户名不能为空"})
        
        if not password or len(password) < 6:
            return jsonify({"status": "error", "message": "密码长度至少为 6 位"})
        
        result = user_manager.register_user(
            username=username,
            password=password,
            email=email if email else None,
            full_name=full_name if full_name else None,
            role='user'
        )
        
        if result['success']:
            return jsonify({"status": "success", "message": result['message']})
        else:
            return jsonify({"status": "error", "message": result['message']}), 400
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/user/login', methods=['POST'])
def login_user():
    """用户登录"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        remember_me = data.get('remember_me', False)
        
        if not username or not password:
            return jsonify({"status": "error", "message": "用户名和密码不能为空"})
        
        result = user_manager.login(username, password, remember_me)
        
        if result['success']:
            response = make_response(jsonify({
                "status": "success",
                "message": result['message'],
                "user": result['user']
            }))
            response.set_cookie('session_token', result['session_token'], 
                              max_age=30*24*60*60 if remember_me else 7*24*60*60,
                              httponly=True,
                              samesite='Lax')
            return response
        else:
            return jsonify({"status": "error", "message": result['message']}), 401
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/user/logout', methods=['POST'])
def logout_user():
    """用户登出（不需要登录验证，因为可能已经失效）"""
    try:
        session_token = request.cookies.get('session_token')
        if session_token:
            user_manager.logout(session_token)
        
        response = make_response(jsonify({"status": "success", "message": "登出成功"}))
        response.delete_cookie('session_token')
        return response
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/user/current', methods=['GET'])
@login_required
def get_current_user():
    """获取当前登录用户信息"""
    try:
        return jsonify({
            "status": "success",
            "user": request.current_user  # type: ignore[attr-defined]
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/user/update', methods=['POST'])
@login_required
def update_user_profile():
    """更新用户信息"""
    try:
        data = request.get_json()
        user_id = request.current_user['id']  # type: ignore[attr-defined]
        
        email = data.get('email', '').strip()
        full_name = data.get('full_name', '').strip()
        avatar_url = data.get('avatar_url', '').strip()
        
        result = user_manager.update_user(
            user_id=user_id,
            email=email if email else None,
            full_name=full_name if full_name else None,
            avatar_url=avatar_url if avatar_url else None
        )
        
        if result['success']:
            return jsonify({"status": "success", "message": result['message']})
        else:
            return jsonify({"status": "error", "message": result['message']}), 400
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/user/change-password', methods=['POST'])
@login_required
def change_password():
    """修改密码"""
    try:
        data = request.get_json()
        user_id = request.current_user['id']  # type: ignore[attr-defined]
        old_password = data.get('old_password', '')
        new_password = data.get('new_password', '')
        
        if not old_password or not new_password:
            return jsonify({"status": "error", "message": "密码不能为空"})
        
        if len(new_password) < 6:
            return jsonify({"status": "error", "message": "新密码长度至少为 6 位"})
        
        result = user_manager.change_password(user_id, old_password, new_password)
        
        if result['success']:
            return jsonify({"status": "success", "message": result['message']})
        else:
            return jsonify({"status": "error", "message": result['message']}), 400
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/user/list', methods=['GET'])
@admin_required
def list_users():
    """获取所有用户列表（仅管理员）"""
    try:
        users = user_manager.get_all_users()
        return jsonify({
            "status": "success",
            "users": users
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/user/delete/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    """删除用户（仅管理员）"""
    try:
        current_user = request.current_user  # type: ignore[attr-defined]
        if user_id == current_user['id']:
            return jsonify({"status": "error", "message": "不能删除自己的账户"})
        
        result = user_manager.delete_user(user_id)
        
        if result['success']:
            return jsonify({"status": "success", "message": result['message']})
        else:
            return jsonify({"status": "error", "message": result['message']}), 400
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/user/check-auth', methods=['GET'])
def check_auth():
    """检查用户登录状态"""
    try:
        session_token = request.cookies.get('session_token')
        
        if not session_token:
            return jsonify({
                "status": "unauthorized",
                "authenticated": False
            })
        
        user = user_manager.get_user_by_session(session_token)
        
        if user:
            return jsonify({
                "status": "success",
                "authenticated": True,
                "user": user
            })
        else:
            return jsonify({
                "status": "unauthorized",
                "authenticated": False
            })
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7038, debug=True)

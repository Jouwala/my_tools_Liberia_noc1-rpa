import os
import sqlite3
import pandas as pd
from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OVERVIEW_PATH = os.path.join(DATA_DIR, "sp_overview.xlsx")
DB_PATH = os.path.join(os.path.dirname(__file__), "inventory.db")
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

COL_INBOUND_TYPE = "Type/whinType"
COL_INBOUND_NO = "Order Number/woNum"
COL_INBOUND_STATUS = "Status/status"
COL_INBOUND_TIME = "Create Time/createTime"
COL_INBOUND_WAREHOUSE = "Warehouse/warehouseID"
COL_INBOUND_QTY = "Material Num/materialNum"

COL_OUTBOUND_NO = "Order Number/woNum"
COL_OUTBOUND_STATUS = "Status/status"
COL_OUTBOUND_TYPE = "Outstock Type/whoutType"
COL_OUTBOUND_TIME = "Outbound Time/outboundTime"
COL_OUTBOUND_WAREHOUSE = "Warehouse/warehouseID"
COL_OUTBOUND_QTY = "Material Num/materialNum"


def load_column_mapping():
    mapping_data = {}
    if os.path.exists(COLUMN_MAPPING_PATH):
        try:
            df = pd.read_excel(COLUMN_MAPPING_PATH)
            for _, row in df.iterrows():
                table_name = row.get('db_table_name', '')
                column_name = row.get('column_name', '')
                mapping_name = row.get('column_mapping_name', '')
                if table_name and column_name and mapping_name:
                    if table_name not in mapping_data:
                        mapping_data[table_name] = {}
                    if mapping_name not in mapping_data[table_name]:
                        mapping_data[table_name][mapping_name] = []
                    mapping_data[table_name][mapping_name].append(column_name)
            print(f"[INFO] Loaded column mapping from: {COLUMN_MAPPING_PATH}")
        except Exception as e:
            print(f"[WARN] Failed to load column mapping: {e}")
    return mapping_data


def detect_column_name(columns, mapping_info, mapping_name):
    if mapping_name in mapping_info:
        possible_cols = mapping_info[mapping_name]
        for target_col in possible_cols:
            if target_col in columns:
                return target_col
    for col in columns:
        col_lower = col.lower()
        mapping_lower = mapping_name.lower()
        if mapping_lower in col_lower or col_lower in mapping_lower:
            return col
    return mapping_name


def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    return conn


def init_column_names():
    global COL_INBOUND_TYPE, COL_INBOUND_NO, COL_INBOUND_STATUS, COL_INBOUND_TIME, COL_INBOUND_WAREHOUSE, COL_INBOUND_QTY
    global COL_OUTBOUND_NO, COL_OUTBOUND_STATUS, COL_OUTBOUND_TYPE, COL_OUTBOUND_TIME, COL_OUTBOUND_WAREHOUSE, COL_OUTBOUND_QTY
    
    if not os.path.exists(DB_PATH):
        return
    
    column_mapping = load_column_mapping()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("PRAGMA table_info(inband_details)")
        inband_cols = [col[1] for col in cursor.fetchall()]
        inband_mapping = column_mapping.get('inband_details', {})
        
        COL_INBOUND_TYPE = detect_column_name(inband_cols, inband_mapping, 'Inbound Type')
        COL_INBOUND_NO = detect_column_name(inband_cols, inband_mapping, 'Inbound No.')
        COL_INBOUND_STATUS = detect_column_name(inband_cols, inband_mapping, 'Status')
        COL_INBOUND_TIME = detect_column_name(inband_cols, inband_mapping, 'Inbound Time')
        COL_INBOUND_WAREHOUSE = detect_column_name(inband_cols, inband_mapping, 'Warehouse Name')
        COL_INBOUND_QTY = detect_column_name(inband_cols, inband_mapping, 'Inbound Qty')
        
        cursor.execute("PRAGMA table_info(outband_details)")
        outband_cols = [col[1] for col in cursor.fetchall()]
        outband_mapping = column_mapping.get('outband_details', {})
        
        COL_OUTBOUND_NO = detect_column_name(outband_cols, outband_mapping, 'Outbound No.')
        COL_OUTBOUND_STATUS = detect_column_name(outband_cols, outband_mapping, 'Status')
        COL_OUTBOUND_TYPE = detect_column_name(outband_cols, outband_mapping, 'Outbound Type')
        COL_OUTBOUND_TIME = detect_column_name(outband_cols, outband_mapping, 'Outbound Time')
        COL_OUTBOUND_WAREHOUSE = detect_column_name(outband_cols, outband_mapping, 'Warehouse Name')
        COL_OUTBOUND_QTY = detect_column_name(outband_cols, outband_mapping, 'Stock Qty')
        
        print(f"[INFO] Detected columns:")
        print(f"  Inbound: type={COL_INBOUND_TYPE}, no={COL_INBOUND_NO}, status={COL_INBOUND_STATUS}, time={COL_INBOUND_TIME}, warehouse={COL_INBOUND_WAREHOUSE}")
        print(f"  Outbound: no={COL_OUTBOUND_NO}, status={COL_OUTBOUND_STATUS}, type={COL_OUTBOUND_TYPE}, time={COL_OUTBOUND_TIME}, warehouse={COL_OUTBOUND_WAREHOUSE}")
    except Exception as e:
        print(f"[WARN] Failed to detect columns: {e}")
    finally:
        conn.close()


init_column_names()


def load_excel_data():
    """读取 overview Excel 所有 Sheet 并转换为字典格式"""
    if not os.path.exists(OVERVIEW_PATH):
        return {}
    excel_data = pd.read_excel(OVERVIEW_PATH, sheet_name=None)
    result = {}
    for sheet_name, df in excel_data.items():
        result[sheet_name] = df.fillna("").to_dict(orient="records")
    return result


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


def load_inband_stats_from_db(date_start=None, date_end=None, warehouse=None):
    """
    从 inventory.db 的 inband_details 表获取 Inbound Ticket 统计数据。
    有日期时：先按 Create Time 筛出「在范围内有记录」的单号，再按这些单号的全表状态算 Closed/Unclosed，
    避免未关闭单因 Create Time 为空被排除导致 Unclosed 变成 0。
    返回: {'Total': X, 'Closed': Y, 'Unclosed': Z}
    """
    if not os.path.exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0}

    conn = get_db_connection()
    cursor = conn.cursor()

    if date_start or date_end or warehouse:
        cond_parts = []
        params = []
        if date_start:
            cond_parts.append("`Confirm Time` >= ?")
            params.append(date_start + " 00:00:00")
        if date_end:
            cond_parts.append("`Confirm Time` <= ?")
            params.append(date_end + " 23:59:59")
        if warehouse:
            cond_parts.append("`Warehouse Name` = ?")
            params.append(warehouse)
        where_sql = " AND ".join(cond_parts)
        cursor.execute(
            "SELECT DISTINCT `In Stock Number` FROM inband_details WHERE " + where_sql,
            params
        )
        ticket_ids = [row['In Stock Number'] for row in cursor.fetchall() if row['In Stock Number']]
        if not ticket_ids:
            conn.close()
            return {"Total": 0, "Closed": 0, "Unclosed": 0}
        placeholders = ",".join("?" * len(ticket_ids))
        cursor.execute(
            "SELECT `In Stock Number`, `Status` FROM inband_details WHERE `In Stock Number` IN (" + placeholders + ")",
            ticket_ids
        )
        rows = cursor.fetchall()
    else:
        cursor.execute(
            "SELECT `In Stock Number`, `Status` FROM inband_details"
        )
        rows = cursor.fetchall()

    ticket_status = {}
    for row in rows:
        inbound_no = row['In Stock Number']
        status = row['Status']
        if not inbound_no:
            continue
        is_closed = bool(status and str(status).strip().lower() == 'closed')
        if inbound_no not in ticket_status:
            ticket_status[inbound_no] = False
        if not is_closed:
            ticket_status[inbound_no] = True
    total = len(ticket_status)
    unclosed = sum(1 for v in ticket_status.values() if v)
    closed = total - unclosed
    conn.close()
    return {
        "Total": total,
        "Closed": closed,
        "Unclosed": unclosed
    }


def load_inbound_details_from_db(date_start=None, date_end=None, warehouse=None):
    """
    从 inventory.db 的 inband_details 表获取 Inbound Details 数据。
    有日期时：先按日期筛出在范围内有记录的单号，再按这些单号的全表状态算 Closed/Unclosed，与 Inbound Ticket 卡片一致。
    """
    if not os.path.exists(DB_PATH):
        return []

    conn = get_db_connection()
    cursor = conn.cursor()

    ticket_status = {}
    params = []
    conditions = []
    if date_start:
        conditions.append("`Confirm Time` >= ?")
        params.append(date_start + " 00:00:00")
    if date_end:
        conditions.append("`Confirm Time` <= ?")
        params.append(date_end + " 23:59:59")
    if warehouse:
        conditions.append("`Warehouse Name` = ?")
        params.append(warehouse)

    if conditions:
        where_sql = " AND ".join(conditions)
        cursor.execute(
            "SELECT DISTINCT `In Stock Number` FROM inband_details WHERE " + where_sql,
            params
        )
        ticket_ids = [row['In Stock Number'] for row in cursor.fetchall() if row['In Stock Number']]
        if not ticket_ids:
            conn.close()
            return []
        placeholders = ",".join("?" * len(ticket_ids))
        cursor.execute(
            "SELECT `In Stock Number`, `Status` FROM inband_details WHERE `In Stock Number` IN (" + placeholders + ")",
            ticket_ids
        )
        for row in cursor.fetchall():
            inbound_no = row['In Stock Number']
            status = row['Status']
            if not inbound_no:
                continue
            is_closed = bool(status and str(status).strip().lower() == 'closed')
            if inbound_no not in ticket_status:
                ticket_status[inbound_no] = False
            if not is_closed:
                ticket_status[inbound_no] = True
        cursor.execute(
            """SELECT `In Stock Number`, `In Stock Type`, `Quantity` FROM inband_details WHERE """ + where_sql,
            params
        )
        rows = cursor.fetchall()
    else:
        cursor.execute(
            "SELECT `In Stock Number`, `Status`, `In Stock Type`, `Quantity` FROM inband_details"
        )
        rows = cursor.fetchall()
        for row in rows:
            inbound_no = row['In Stock Number']
            status = row['Status']
            if not inbound_no:
                continue
            is_closed = bool(status and str(status).strip().lower() == 'closed')
            if inbound_no not in ticket_status:
                ticket_status[inbound_no] = False
            if not is_closed:
                ticket_status[inbound_no] = True

    type_stats = {}
    for row in rows:
        inbound_type = row['In Stock Type'] or 'Unknown'
        inbound_no = row['In Stock Number']
        inbound_qty = row['Quantity'] or 0
        if not inbound_no:
            continue
        if inbound_type not in type_stats:
            type_stats[inbound_type] = {
                'inbound_nos': set(),
                'closed_nos': set(),
                'unclosed_nos': set(),
                'total_qty': 0
            }
        type_stats[inbound_type]['inbound_nos'].add(inbound_no)
        type_stats[inbound_type]['total_qty'] += int(inbound_qty) if inbound_qty else 0
        if ticket_status.get(inbound_no, False):
            type_stats[inbound_type]['unclosed_nos'].add(inbound_no)
        else:
            type_stats[inbound_type]['closed_nos'].add(inbound_no)

    result = []
    for inbound_type, stats in type_stats.items():
        result.append({
            'Inbound Type': inbound_type,
            'Total': len(stats['inbound_nos']),
            'Inbound Qty': stats['total_qty'],
            'Closed': len(stats['closed_nos']),
            'Unclosed': len(stats['unclosed_nos'])
        })
    conn.close()
    return result


def load_outband_stats_from_db(date_start=None, date_end=None, warehouse=None):
    """
    从 inventory.db 的 outband_details 表获取 Outbound Ticket 统计数据。
    时间从 Request Time 列过滤。
    返回: {'Total': X, 'Closed': Y, 'Unclosed': Z}
    """
    if not os.path.exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0}

    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT `Out Stock Number`, `Status`, `Confirm Time`, `Warehouse Name` FROM outband_details"
    params = []
    conditions = []

    if date_start:
        conditions.append("`Confirm Time` >= ?")
        params.append(date_start + " 00:00:00")
    if date_end:
        conditions.append("`Confirm Time` <= ?")
        params.append(date_end + " 23:59:59")
    if warehouse:
        conditions.append("`Warehouse Name` = ?")
        params.append(warehouse)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    outbound_nos = set()
    closed_nos = set()
    unclosed_nos = set()

    for row in rows:
        outbound_no = row['Out Stock Number']
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


def load_outbound_details_from_db(date_start=None, date_end=None, warehouse=None):
    """
    从 inventory.db 的 outband_details 表获取 Outbound Details 数据。
    时间从 Request Time 列过滤。
    根据 Out Type 类别统计：
    - Total: Out Stock Number 列非重复的个数
    - Stock Qty: Quantity 列数字求和
    - Closed: Out Stock Number 列非重复的个数并且 Status 列是 "Closed"
    - Unclosed: Out Stock Number 列非重复的个数并且 Status 列不是 "Closed"
    """
    if not os.path.exists(DB_PATH):
        return []

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT `Out Stock Number`, `Status`, `Out Type`, `Quantity`, `Confirm Time`, `Warehouse Name`
        FROM outband_details
    """
    params = []
    conditions = []

    if date_start:
        conditions.append("`Confirm Time` >= ?")
        params.append(date_start + " 00:00:00")
    if date_end:
        conditions.append("`Confirm Time` <= ?")
        params.append(date_end + " 23:59:59")
    if warehouse:
        conditions.append("`Warehouse Name` = ?")
        params.append(warehouse)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    type_stats = {}

    for row in rows:
        outbound_type = row['Out Type'] or 'Unknown'
        outbound_no = row['Out Stock Number']
        status = row['Status']
        stock_qty = row['Quantity'] or 0

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


def load_special_outbound_stats_from_db(outbound_type, sla_days, date_start=None, date_end=None, warehouse=None):
    """
    从数据库获取特定类型 Outbound 的统计数据。
    用于 Borrow Outbound, Repair Outbound, Inventory Lost Outbound。
    SLA计算: Close Time - Confirm Time，如果没有Close Time则使用当前时间
    """
    if not os.path.exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0, "SLA": 0}

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT `Out Stock Number`, `Status`, `Confirm Time`, `Close Time`, `Warehouse Name`
        FROM outband_details
        WHERE `Out Type` = ?
    """
    params = [outbound_type]

    if date_start:
        query += " AND `Confirm Time` >= ?"
        params.append(date_start + " 00:00:00")
    if date_end:
        query += " AND `Confirm Time` <= ?"
        params.append(date_end + " 23:59:59")
    if warehouse:
        query += " AND `Warehouse Name` = ?"
        params.append(warehouse)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    outbound_nos = set()
    closed_nos = set()
    unclosed_nos = set()
    sla_nos = set()
    now = datetime.now()

    for row in rows:
        outbound_no = row['Out Stock Number']
        status = row['Status']
        confirm_time_str = row['Confirm Time']
        close_time_str = row['Close Time']

        if outbound_no:
            outbound_nos.add(outbound_no)
            if status and status.lower() == 'closed':
                closed_nos.add(outbound_no)
            else:
                unclosed_nos.add(outbound_no)
            
            if confirm_time_str and outbound_no not in sla_nos:
                try:
                    confirm_time = datetime.strptime(confirm_time_str[:19], '%Y-%m-%d %H:%M:%S')
                    if close_time_str:
                        close_time = datetime.strptime(close_time_str[:19], '%Y-%m-%d %H:%M:%S')
                    else:
                        close_time = now
                    days_diff = (close_time - confirm_time).days
                    if days_diff > sla_days:
                        sla_nos.add(outbound_no)
                except (ValueError, TypeError):
                    pass

    return {
        "Total": len(outbound_nos),
        "Closed": len(closed_nos),
        "Unclosed": len(unclosed_nos),
        "SLA": len(sla_nos)
    }


def load_inventory_stats_from_db(date_start=None, date_end=None, warehouse=None):
    """
    从 inventory.db 的 inventory_details 表获取 Inventory 统计数据。
    始终显示最新一天的数据，不受时间范围影响。
    
    统计逻辑（按 Quantity 总和）：
    - Total: 最新一天数据中，Quantity 列的总和
    - Consumables: 最新一天数据中，Material Type 为 "Consumable" 的 Quantity 总和
    - SpareParts: 最新一天数据中，Material Type 不是 "Consumable" 的 Quantity 总和
    """
    if not os.path.exists(DB_PATH):
        return {"Total": 0, "Consumables_QTY": 0, "SpareParts_QTY": 0}

    conn = get_db_connection()
    cursor = conn.cursor()

    # 首先获取最新的 update_date
    latest_date_query = "SELECT MAX(`update_date`) as latest_date FROM inventory_details WHERE `update_date` IS NOT NULL AND `update_date` != ''"
    cursor.execute(latest_date_query)
    latest_date_result = cursor.fetchone()
    latest_date = latest_date_result['latest_date'] if latest_date_result and latest_date_result['latest_date'] else None
    
    if not latest_date:
        conn.close()
        return {"Total": 0, "Consumables_QTY": 0, "SpareParts_QTY": 0}

    query = """
        SELECT `Serial No`, `Material Type`, `Quantity`
        FROM inventory_details
        WHERE `update_date` = ?
    """
    params = [latest_date]
    
    if warehouse:
        query += " AND `Warehouse Name` = ?"
        params.append(warehouse)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    total_qty = 0
    consumables_qty = 0
    spare_parts_qty = 0

    for row in rows:
        material_type = row['Material Type']
        quantity = row['Quantity'] or 0
        
        # 将 Quantity 转换为数字
        try:
            qty = int(quantity) if quantity else 0
        except (ValueError, TypeError):
            qty = 0
        
        # 累加总量
        total_qty += qty
        
        # 按物料类型分类累加
        if material_type and material_type.lower() == 'consumable':
            consumables_qty += qty
        else:
            spare_parts_qty += qty

    return {
        "Total": total_qty,
        "Consumables_QTY": consumables_qty,
        "SpareParts_QTY": spare_parts_qty
    }


def load_inventory_trend_from_db(date_start=None, date_end=None, warehouse=None):
    """
    从 inventory.db 的 inventory_details 表获取 Inventory Quantity Trend 数据。
    时间从 update_date 列过滤。
    按时间统计：
    - Total: Quantity 列的总和
    - Consumables: Material Type 列是 "Consumable" 的 Quantity 总和
    - SpareParts: Material Type 列不是 "Consumable" 的 Quantity 总和
    """
    if not os.path.exists(DB_PATH):
        return []

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT `Serial No`, `Material Type`, `update_date`, `Quantity`, `Warehouse Name`
        FROM inventory_details
    """
    params = []
    conditions = []

    if date_start:
        conditions.append("`update_date` >= ?")
        params.append(date_start)
    if date_end:
        conditions.append("`update_date` <= ?")
        params.append(date_end)
    if warehouse:
        conditions.append("`Warehouse Name` = ?")
        params.append(warehouse)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    date_stats = {}

    for row in rows:
        update_date = row['update_date']
        serial_no = row['Serial No']
        material_type = row['Material Type']
        quantity = row['Quantity'] or 0

        if not update_date:
            continue

        if update_date not in date_stats:
            date_stats[update_date] = {
                'total_qty': 0,
                'consumables_qty': 0,
                'spare_parts_qty': 0
            }

        # 将 Quantity 转换为数字
        try:
            qty = int(quantity) if quantity else 0
        except (ValueError, TypeError):
            qty = 0

        # 按日期累加 Quantity
        date_stats[update_date]['total_qty'] += qty

        if material_type and material_type.lower() == 'consumable':
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


def load_inbound_outbound_trend_from_db(date_start=None, date_end=None, warehouse=None):
    """
    从数据库获取 Inbound & Outbound Tickets Trend 数据。
    时间从 update_date 列过滤（用于统一日期显示）。
    按天统计：
    - Inbound_Qty_Sum: inband_details 表按 Confirm Time 列统计 Quantity 之和
    - Outbound_Qty_Sum: outband_details 表按 Confirm Time 列统计 Quantity 之和
    """
    if not os.path.exists(DB_PATH):
        return []

    conn = get_db_connection()
    cursor = conn.cursor()

    inbound_query = """
        SELECT date(`Confirm Time`) as doc_date, SUM(`Quantity`) as qty_sum
        FROM inband_details
        WHERE `Confirm Time` IS NOT NULL AND `Confirm Time` != ''
    """
    inbound_params = []
    if date_start:
        inbound_query += " AND `Confirm Time` >= ?"
        inbound_params.append(date_start + " 00:00:00")
    if date_end:
        inbound_query += " AND `Confirm Time` <= ?"
        inbound_params.append(date_end + " 23:59:59")
    if warehouse:
        inbound_query += " AND `Warehouse Name` = ?"
        inbound_params.append(warehouse)
    inbound_query += " GROUP BY date(`Confirm Time`)"

    cursor.execute(inbound_query, inbound_params)
    inbound_rows = cursor.fetchall()

    outbound_query = """
        SELECT date(`Confirm Time`) as doc_date, SUM(`Quantity`) as qty_sum
        FROM outband_details
        WHERE `Confirm Time` IS NOT NULL AND `Confirm Time` != ''
    """
    outbound_params = []
    if date_start:
        outbound_query += " AND `Confirm Time` >= ?"
        outbound_params.append(date_start + " 00:00:00")
    if date_end:
        outbound_query += " AND `Confirm Time` <= ?"
        outbound_params.append(date_end + " 23:59:59")
    if warehouse:
        outbound_query += " AND `Warehouse Name` = ?"
        outbound_params.append(warehouse)
    outbound_query += " GROUP BY date(`Confirm Time`)"

    cursor.execute(outbound_query, outbound_params)
    outbound_rows = cursor.fetchall()
    conn.close()

    date_stats = {}

    for row in inbound_rows:
        doc_date = row['doc_date']
        qty_sum = row['qty_sum'] or 0
        if doc_date:
            if doc_date not in date_stats:
                date_stats[doc_date] = {'inbound_qty': 0, 'outbound_qty': 0}
            date_stats[doc_date]['inbound_qty'] += int(qty_sum) if qty_sum else 0

    for row in outbound_rows:
        doc_date = row['doc_date']
        qty_sum = row['qty_sum'] or 0
        if doc_date:
            if doc_date not in date_stats:
                date_stats[doc_date] = {'inbound_qty': 0, 'outbound_qty': 0}
            date_stats[doc_date]['outbound_qty'] += int(qty_sum) if qty_sum else 0

    result = []
    for doc_date in sorted(date_stats.keys()):
        stats = date_stats[doc_date]
        result.append({
            'Unified_Date': doc_date,
            'Inbound_Qty_Sum': stats['inbound_qty'],
            'Outbound_Qty_Sum': stats['outbound_qty']
        })

    return result


def get_inbound_outbound_date_range():
    """获取 Inbound & Outbound 的 Confirm Time 日期范围"""
    if not os.path.exists(DB_PATH):
        return None, None
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    min_date = None
    max_date = None
    
    cursor.execute("""
        SELECT MIN(date(`Confirm Time`)) as min_d, MAX(date(`Confirm Time`)) as max_d
        FROM inband_details
        WHERE `Confirm Time` IS NOT NULL AND `Confirm Time` != ''
    """)
    row = cursor.fetchone()
    if row:
        if row['min_d'] and (min_date is None or row['min_d'] < min_date):
            min_date = row['min_d']
        if row['max_d'] and (max_date is None or row['max_d'] > max_date):
            max_date = row['max_d']
    
    cursor.execute("""
        SELECT MIN(date(`Confirm Time`)) as min_d, MAX(date(`Confirm Time`)) as max_d
        FROM outband_details
        WHERE `Confirm Time` IS NOT NULL AND `Confirm Time` != ''
    """)
    row = cursor.fetchone()
    if row:
        if row['min_d'] and (min_date is None or row['min_d'] < min_date):
            min_date = row['min_d']
        if row['max_d'] and (max_date is None or row['max_d'] > max_date):
            max_date = row['max_d']
    
    conn.close()
    
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    if max_date and today > max_date:
        max_date = today
    
    return min_date, max_date


def load_inbound_outbound_trend_full_range(date_start=None, date_end=None, warehouse=None):
    """
    获取 Inbound & Outbound QTY Trend 数据，填充完整日期范围
    从 Confirm Time 最小值到最大值（或今天）
    """
    from datetime import datetime, timedelta
    
    min_db_date, max_db_date = get_inbound_outbound_date_range()
    
    if not min_db_date:
        return []
    
    if not date_start:
        date_start = min_db_date
    if not date_end:
        date_end = max_db_date or datetime.now().strftime('%Y-%m-%d')
    
    date_stats = load_inbound_outbound_trend_from_db(date_start, date_end, warehouse)
    
    date_dict = {item['Unified_Date']: item for item in date_stats}
    
    result = []
    start_dt = datetime.strptime(date_start, '%Y-%m-%d')
    end_dt = datetime.strptime(date_end, '%Y-%m-%d')
    current_dt = start_dt
    
    while current_dt <= end_dt:
        current_date = current_dt.strftime('%Y-%m-%d')
        if current_date in date_dict:
            result.append(date_dict[current_date])
        else:
            result.append({
                'Unified_Date': current_date,
                'Inbound_Qty_Sum': 0,
                'Outbound_Qty_Sum': 0
            })
        current_dt += timedelta(days=1)
    
    return result


def get_latest_update_time_from_db():
    """
    从 inventory.db 的 inventory_details 表格获取 update_time 列的最新时间
    """
    if not os.path.exists(DB_PATH):
        return ""

    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT MAX(`update_time`) as latest_time FROM inventory_details"
    cursor.execute(query)
    result = cursor.fetchone()
    conn.close()

    return result['latest_time'] if result and result['latest_time'] else ""


def load_detail_data(detail_type, filter_column=None, filter_value=None, filter_mode="exact",
                     first_column=None, first_value=None, date_start=None, date_end=None, warehouse=None,
                     status_column=None, status_value=None, status_mode="exact", sla_filter=False, sla_type=None):
    """
    加载 inband / outband / inventory 详情。
    从数据库读取并支持时间过滤。
    先按 first_column == first_value 精确过滤（若提供），再按 filter_column/value/mode 过滤。
    filter_mode: exact | contains | not_contains
    status_column/status_value/status_mode: 额外的状态过滤条件
    返回 (title, columns, records)。
    """
    if detail_type == "inband" and os.path.exists(DB_PATH):
        return load_inband_detail_from_db(filter_column, filter_value, filter_mode,
                                          first_column, first_value, date_start, date_end, warehouse,
                                          status_column, status_value, status_mode)
    elif detail_type == "outband" and os.path.exists(DB_PATH):
        return load_outband_detail_from_db(filter_column, filter_value, filter_mode,
                                           first_column, first_value, date_start, date_end, warehouse,
                                           status_column, status_value, status_mode, sla_filter, sla_type)
    elif detail_type == "inventory" and os.path.exists(DB_PATH):
        return load_inventory_detail_from_db(filter_column, filter_value, filter_mode,
                                             first_column, first_value, date_start, date_end, warehouse)

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
                               first_column=None, first_value=None, date_start=None, date_end=None, warehouse=None,
                               status_column=None, status_value=None, status_mode="exact"):
    """
    从数据库加载 inband 详情数据，支持时间过滤和状态过滤。
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(inband_details)")
    columns_info = cursor.fetchall()
    columns = [col[1] for col in columns_info]

    query = "SELECT * FROM inband_details WHERE 1=1"
    params = []

    if date_start:
        query += " AND `Confirm Time` >= ?"
        params.append(date_start + " 00:00:00")
    if date_end:
        query += " AND `Confirm Time` <= ?"
        params.append(date_end + " 23:59:59")
    if warehouse:
        query += " AND `Warehouse Name` = ?"
        params.append(warehouse)

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

    if status_column and status_value:
        status_val_str = str(status_value).strip()
        if status_mode == "contains":
            query += f" AND LOWER(`{status_column}`) LIKE ?"
            params.append(f"%{status_val_str.lower()}%")
        elif status_mode == "not_contains":
            query += f" AND LOWER(`{status_column}`) NOT LIKE ?"
            params.append(f"%{status_val_str.lower()}%")
        else:
            query += f" AND `{status_column}` = ?"
            params.append(status_val_str)

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
                                first_column=None, first_value=None, date_start=None, date_end=None, warehouse=None,
                                status_column=None, status_value=None, status_mode="exact", sla_filter=False, sla_type=None):
    """
    从数据库加载 outband 详情数据，支持时间过滤和状态过滤。
    sla_filter: 是否过滤SLA超期记录
    sla_type: SLA类型 (Borrow Outbound, Repair Outbound, Inventory Outbound)
    """
    if sla_filter and sla_type:
        print(f"[DEBUG] SLA filter requested: sla_type={sla_type}")
        early_warning_data = load_early_warning_from_db(date_start, date_end, warehouse)
        print(f"[DEBUG] Early warning data: total_records={len(early_warning_data['records'])}")
        if early_warning_data['records']:
            print(f"[DEBUG] Sample record SLA_Types: {[r.get('SLA_Type') for r in early_warning_data['records'][:5]]}")
        filtered_records = [r for r in early_warning_data['records'] if r.get('SLA_Type') == sla_type]
        print(f"[DEBUG] Filtered records for '{sla_type}': count={len(filtered_records)}")
        columns = early_warning_data['columns']
        return DETAIL_TITLES.get("outband", "Outbound Details View"), columns, filtered_records
    
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(outband_details)")
    columns_info = cursor.fetchall()
    columns = [col[1] for col in columns_info]

    query = "SELECT * FROM outband_details WHERE 1=1"
    params = []

    if date_start:
        query += " AND `Confirm Time` >= ?"
        params.append(date_start + " 00:00:00")
    if date_end:
        query += " AND `Confirm Time` <= ?"
        params.append(date_end + " 23:59:59")
    if warehouse:
        query += " AND `Warehouse Name` = ?"
        params.append(warehouse)

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

    if status_column and status_value:
        status_val_str = str(status_value).strip()
        if status_mode == "contains":
            query += f" AND LOWER(`{status_column}`) LIKE ?"
            params.append(f"%{status_val_str.lower()}%")
        elif status_mode == "not_contains":
            query += f" AND LOWER(`{status_column}`) NOT LIKE ?"
            params.append(f"%{status_val_str.lower()}%")
        else:
            query += f" AND `{status_column}` = ?"
            params.append(status_val_str)

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
                                  first_column=None, first_value=None, date_start=None, date_end=None, warehouse=None):
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
    if warehouse:
        query += " AND `Warehouse Name` = ?"
        params.append(warehouse)

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


def load_early_warning_from_db(date_start=None, date_end=None, warehouse=None):
    """
    从 outband_details 表获取 SLA 预警详细数据。
    获取 Borrow Outbound (>45天), Repair Outbound (>180天), Inventory Outbound (>1天) 的 SLA 超期单据。
    SLA计算: Close Time - Confirm Time，如果没有Close Time则使用当前时间
    """
    if not os.path.exists(DB_PATH):
        return {'columns': [], 'records': []}

    sla_configs = [
        {'outbound_type': 'Borrow Outbound', 'sla_days': 45},
        {'outbound_type': 'Repair Outbound', 'sla_days': 180},
        {'outbound_type': 'Inventory Outbound', 'sla_days': 1},
    ]

    all_records = []

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(outband_details)")
    columns_info = cursor.fetchall()
    columns = [col[1] for col in columns_info]

    now = datetime.now()

    for config in sla_configs:
        outbound_type = config['outbound_type']
        sla_days = config['sla_days']

        query = """
            SELECT * FROM outband_details
            WHERE `Out Type` = ?
        """
        params = [outbound_type]

        if date_start:
            query += " AND `Confirm Time` >= ?"
            params.append(date_start + " 00:00:00")
        if date_end:
            query += " AND `Confirm Time` <= ?"
            params.append(date_end + " 23:59:59")
        if warehouse:
            query += " AND `Warehouse Name` = ?"
            params.append(warehouse)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        for row in rows:
            confirm_time_str = row['Confirm Time']
            close_time_str = row['Close Time']
            
            if not confirm_time_str:
                continue
            
            try:
                confirm_time = datetime.strptime(confirm_time_str[:19], '%Y-%m-%d %H:%M:%S')
                if close_time_str:
                    close_time = datetime.strptime(close_time_str[:19], '%Y-%m-%d %H:%M:%S')
                else:
                    close_time = now
                
                days_diff = (close_time - confirm_time).days
                
                if days_diff > sla_days:
                    record = {}
                    for col in columns:
                        val = row[col]
                        if isinstance(val, bytes):
                            val = val.decode('utf-8', errors='ignore')
                        record[col] = val if val is not None else ""
                    record['SLA_Days'] = sla_days
                    record['SLA_Type'] = outbound_type
                    record['Actual_Days'] = days_diff
                    all_records.append(record)
            except (ValueError, TypeError):
                continue

    conn.close()
    
    extra_cols = ['SLA_Days', 'SLA_Type', 'Actual_Days']
    return {'columns': columns + extra_cols, 'records': all_records}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/data')
def get_data():
    try:
        date_start = request.args.get('date_start')
        date_end = request.args.get('date_end')
        warehouse = request.args.get('warehouse')

        # 全部数据来自数据库，不再使用 Excel
        data = {}

        # 获取最新更新时间
        latest_update_time = get_latest_update_time_from_db()
        data['Time'] = [{"update_time": latest_update_time}]

        inband_stats = load_inband_stats_from_db(date_start, date_end, warehouse)
        data['Inbound Ticket'] = [inband_stats]

        inbound_details = load_inbound_details_from_db(date_start, date_end, warehouse)
        data['Inbound'] = inbound_details

        outband_stats = load_outband_stats_from_db(date_start, date_end, warehouse)
        data['Outbound Ticket'] = [outband_stats]

        outbound_details = load_outbound_details_from_db(date_start, date_end, warehouse)
        data['Outbound'] = outbound_details

        borrow_stats = load_special_outbound_stats_from_db('Borrow Outbound', 45, date_start, date_end, warehouse)
        data['Borrow Outbound'] = [borrow_stats]

        repair_stats = load_special_outbound_stats_from_db('Repair Outbound', 180, date_start, date_end, warehouse)
        data['Repair Outbound'] = [repair_stats]

        inventory_lost_stats = load_special_outbound_stats_from_db('Inventory Outbound', 1, date_start, date_end,
                                                                   warehouse)
        data['Inventory Lost Outbound'] = [inventory_lost_stats]

        inventory_stats = load_inventory_stats_from_db(date_start, date_end, warehouse)
        data['Inventory'] = [inventory_stats]

        inventory_trend = load_inventory_trend_from_db(date_start, date_end, warehouse)
        data['Inventory Quantity Trend'] = inventory_trend

        inbound_outbound_trend = load_inbound_outbound_trend_full_range(date_start, date_end, warehouse)
        data['Inbound & Outbound Ticket T'] = inbound_outbound_trend

        data['Early Warning Document Detail'] = load_early_warning_from_db(date_start, date_end, warehouse)

        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/warehouses')
def get_warehouses():
    """获取所有仓库列表"""
    try:
        if not os.path.exists(DB_PATH):
            return jsonify({"status": "success", "warehouses": []})

        conn = get_db_connection()
        cursor = conn.cursor()

        warehouses = set()

        # 从 inband_details 获取
        cursor.execute(
            "SELECT DISTINCT `Warehouse Name` FROM inband_details WHERE `Warehouse Name` IS NOT NULL AND `Warehouse Name` != ''")
        for row in cursor.fetchall():
            if row['Warehouse Name']:
                warehouses.add(row['Warehouse Name'])

        # 从 outband_details 获取
        cursor.execute(
            "SELECT DISTINCT `Warehouse Name` FROM outband_details WHERE `Warehouse Name` IS NOT NULL AND `Warehouse Name` != ''")
        for row in cursor.fetchall():
            if row['Warehouse Name']:
                warehouses.add(row['Warehouse Name'])

        # 从 inventory_details 获取
        cursor.execute(
            "SELECT DISTINCT `Warehouse Name` FROM inventory_details WHERE `Warehouse Name` IS NOT NULL AND `Warehouse Name` != ''")
        for row in cursor.fetchall():
            if row['Warehouse Name']:
                warehouses.add(row['Warehouse Name'])

        conn.close()

        return jsonify({"status": "success", "warehouses": sorted(list(warehouses))})
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
        warehouse = request.args.get("warehouse")
        status_column = request.args.get("status_column") or None
        status_value = request.args.get("status_value")
        status_mode = request.args.get("status_mode") or "exact"
        sla_filter = request.args.get("sla_filter") == "true"
        sla_type = request.args.get("sla_type")
        title, columns, data = load_detail_data(
            detail_type, filter_column, filter_value, filter_mode,
            first_column=first_column, first_value=first_value,
            date_start=date_start, date_end=date_end, warehouse=warehouse,
            status_column=status_column, status_value=status_value, status_mode=status_mode,
            sla_filter=sla_filter, sla_type=sla_type,
        )
        return jsonify({
            "status": "success",
            "title": title,
            "columns": columns,
            "data": data,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


if __name__ == '__main__':
    # 工业系统通常运行在固定端口
    app.run(host='0.0.0.0', port=7038, debug=True)

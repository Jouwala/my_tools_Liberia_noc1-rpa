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

COL_INBOUND_TYPE = "In Stock Type"
COL_INBOUND_NO = "In Stock Number"
COL_INBOUND_STATUS = "Status"
COL_INBOUND_TIME = "Confirm Time"
COL_INBOUND_WAREHOUSE = "Warehouse Name"

COL_OUTBOUND_NO = "Out Stock Number"
COL_OUTBOUND_STATUS = "Status"
COL_OUTBOUND_TYPE = "Out Type"
COL_OUTBOUND_TIME = "Confirm Time"
COL_OUTBOUND_WAREHOUSE = "Warehouse Name"


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
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def init_column_names():
    global COL_INBOUND_TYPE, COL_INBOUND_NO, COL_INBOUND_STATUS, COL_INBOUND_TIME, COL_INBOUND_WAREHOUSE
    global COL_OUTBOUND_NO, COL_OUTBOUND_STATUS, COL_OUTBOUND_TYPE, COL_OUTBOUND_TIME, COL_OUTBOUND_WAREHOUSE
    
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
        
        cursor.execute("PRAGMA table_info(outband_details)")
        outband_cols = [col[1] for col in cursor.fetchall()]
        outband_mapping = column_mapping.get('outband_details', {})
        
        COL_OUTBOUND_NO = detect_column_name(outband_cols, outband_mapping, 'Outbound No.')
        COL_OUTBOUND_STATUS = detect_column_name(outband_cols, outband_mapping, 'Status')
        COL_OUTBOUND_TYPE = detect_column_name(outband_cols, outband_mapping, 'Outbound Type')
        COL_OUTBOUND_TIME = detect_column_name(outband_cols, outband_mapping, 'Outbound Time')
        COL_OUTBOUND_WAREHOUSE = detect_column_name(outband_cols, outband_mapping, 'Warehouse Name')
        
        print(f"[INFO] Detected columns:")
        print(f"  Inbound: type={COL_INBOUND_TYPE}, no={COL_INBOUND_NO}, status={COL_INBOUND_STATUS}, time={COL_INBOUND_TIME}, warehouse={COL_INBOUND_WAREHOUSE}")
        print(f"  Outbound: no={COL_OUTBOUND_NO}, status={COL_OUTBOUND_STATUS}, type={COL_OUTBOUND_TYPE}, time={COL_OUTBOUND_TIME}, warehouse={COL_OUTBOUND_WAREHOUSE}")
    except Exception as e:
        print(f"[WARN] Failed to detect columns: {e}")
    finally:
        conn.close()


init_column_names()


def load_excel_data():
    if not os.path.exists(OVERVIEW_PATH):
        return {}
    excel_data = pd.read_excel(OVERVIEW_PATH, sheet_name=None)
    result = {}
    for sheet_name, df in excel_data.items():
        result[sheet_name] = df.fillna("").to_dict(orient="records")
    return result


def parse_date_from_string(date_str):
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
    if not os.path.exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0}

    conn = get_db_connection()
    cursor = conn.cursor()

    if date_start or date_end or warehouse:
        cond_parts = []
        params = []
        if date_start:
            cond_parts.append(f"`{COL_INBOUND_TIME}` >= ?")
            params.append(date_start + " 00:00:00")
        if date_end:
            cond_parts.append(f"`{COL_INBOUND_TIME}` <= ?")
            params.append(date_end + " 23:59:59")
        if warehouse:
            cond_parts.append(f"`{COL_INBOUND_WAREHOUSE}` = ?")
            params.append(warehouse)
        where_sql = " AND ".join(cond_parts)
        cursor.execute(
            f"SELECT DISTINCT `{COL_INBOUND_NO}` FROM inband_details WHERE " + where_sql,
            params
        )
        ticket_ids = [row[COL_INBOUND_NO] for row in cursor.fetchall() if row[COL_INBOUND_NO]]
        if not ticket_ids:
            conn.close()
            return {"Total": 0, "Closed": 0, "Unclosed": 0}
        placeholders = ",".join("?" * len(ticket_ids))
        cursor.execute(
            f"SELECT `{COL_INBOUND_NO}`, `{COL_INBOUND_STATUS}` FROM inband_details WHERE `{COL_INBOUND_NO}` IN (" + placeholders + ")",
            ticket_ids
        )
        rows = cursor.fetchall()
    else:
        cursor.execute(
            f"SELECT `{COL_INBOUND_NO}`, `{COL_INBOUND_STATUS}` FROM inband_details"
        )
        rows = cursor.fetchall()

    ticket_status = {}
    for row in rows:
        inbound_no = row[COL_INBOUND_NO]
        status = row[COL_INBOUND_STATUS]
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
    return {"Total": total, "Closed": closed, "Unclosed": unclosed}


def load_inbound_details_from_db(date_start=None, date_end=None, warehouse=None):
    if not os.path.exists(DB_PATH):
        return []

    conn = get_db_connection()
    cursor = conn.cursor()

    ticket_status = {}
    params = []
    conditions = []
    if date_start:
        conditions.append(f"`{COL_INBOUND_TIME}` >= ?")
        params.append(date_start + " 00:00:00")
    if date_end:
        conditions.append(f"`{COL_INBOUND_TIME}` <= ?")
        params.append(date_end + " 23:59:59")
    if warehouse:
        conditions.append(f"`{COL_INBOUND_WAREHOUSE}` = ?")
        params.append(warehouse)

    if conditions:
        where_sql = " AND ".join(conditions)
        cursor.execute(
            f"SELECT DISTINCT `{COL_INBOUND_NO}` FROM inband_details WHERE " + where_sql,
            params
        )
        ticket_ids = [row[COL_INBOUND_NO] for row in cursor.fetchall() if row[COL_INBOUND_NO]]
        if not ticket_ids:
            conn.close()
            return []
        placeholders = ",".join("?" * len(ticket_ids))
        cursor.execute(
            f"SELECT `{COL_INBOUND_NO}`, `{COL_INBOUND_STATUS}` FROM inband_details WHERE `{COL_INBOUND_NO}` IN (" + placeholders + ")",
            ticket_ids
        )
        for row in cursor.fetchall():
            inbound_no = row[COL_INBOUND_NO]
            status = row[COL_INBOUND_STATUS]
            if not inbound_no:
                continue
            is_closed = bool(status and str(status).strip().lower() == 'closed')
            if inbound_no not in ticket_status:
                ticket_status[inbound_no] = False
            if not is_closed:
                ticket_status[inbound_no] = True
        cursor.execute(
            f"SELECT `{COL_INBOUND_NO}`, `{COL_INBOUND_TYPE}` FROM inband_details WHERE " + where_sql,
            params
        )
        rows = cursor.fetchall()
    else:
        cursor.execute(
            f"SELECT `{COL_INBOUND_NO}`, `{COL_INBOUND_STATUS}`, `{COL_INBOUND_TYPE}` FROM inband_details"
        )
        rows = cursor.fetchall()
        for row in rows:
            inbound_no = row[COL_INBOUND_NO]
            status = row[COL_INBOUND_STATUS]
            if not inbound_no:
                continue
            is_closed = bool(status and str(status).strip().lower() == 'closed')
            if inbound_no not in ticket_status:
                ticket_status[inbound_no] = False
            if not is_closed:
                ticket_status[inbound_no] = True

    type_stats = {}
    for row in rows:
        inbound_type = row[COL_INBOUND_TYPE] or 'Unknown'
        inbound_no = row[COL_INBOUND_NO]
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
        type_stats[inbound_type]['total_qty'] += 1
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
    if not os.path.exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0}

    conn = get_db_connection()
    cursor = conn.cursor()

    query = f"SELECT `{COL_OUTBOUND_NO}`, `{COL_OUTBOUND_STATUS}`, `{COL_OUTBOUND_TIME}`, `{COL_OUTBOUND_WAREHOUSE}` FROM outband_details"
    params = []
    conditions = []

    if date_start:
        conditions.append(f"`{COL_OUTBOUND_TIME}` >= ?")
        params.append(date_start + " 00:00:00")
    if date_end:
        conditions.append(f"`{COL_OUTBOUND_TIME}` <= ?")
        params.append(date_end + " 23:59:59")
    if warehouse:
        conditions.append(f"`{COL_OUTBOUND_WAREHOUSE}` = ?")
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
        outbound_no = row[COL_OUTBOUND_NO]
        status = row[COL_OUTBOUND_STATUS]

        if outbound_no:
            outbound_nos.add(outbound_no)
            if status and status.lower() == 'closed':
                closed_nos.add(outbound_no)
            else:
                unclosed_nos.add(outbound_no)

    return {"Total": len(outbound_nos), "Closed": len(closed_nos), "Unclosed": len(unclosed_nos)}


def load_outbound_details_from_db(date_start=None, date_end=None, warehouse=None):
    if not os.path.exists(DB_PATH):
        return []

    conn = get_db_connection()
    cursor = conn.cursor()

    query = f"""
        SELECT `{COL_OUTBOUND_NO}`, `{COL_OUTBOUND_STATUS}`, `{COL_OUTBOUND_TYPE}`, `{COL_OUTBOUND_TIME}`, `{COL_OUTBOUND_WAREHOUSE}`
        FROM outband_details
    """
    params = []
    conditions = []

    if date_start:
        conditions.append(f"`{COL_OUTBOUND_TIME}` >= ?")
        params.append(date_start + " 00:00:00")
    if date_end:
        conditions.append(f"`{COL_OUTBOUND_TIME}` <= ?")
        params.append(date_end + " 23:59:59")
    if warehouse:
        conditions.append(f"`{COL_OUTBOUND_WAREHOUSE}` = ?")
        params.append(warehouse)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    type_stats = {}

    for row in rows:
        outbound_type = row[COL_OUTBOUND_TYPE] or 'Unknown'
        outbound_no = row[COL_OUTBOUND_NO]
        status = row[COL_OUTBOUND_STATUS]

        if outbound_type not in type_stats:
            type_stats[outbound_type] = {
                'outbound_nos': set(),
                'closed_nos': set(),
                'unclosed_nos': set(),
                'total_qty': 0
            }

        if outbound_no:
            type_stats[outbound_type]['outbound_nos'].add(outbound_no)
            type_stats[outbound_type]['total_qty'] += 1

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
    if not os.path.exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0, "SLA": 0}

    conn = get_db_connection()
    cursor = conn.cursor()

    query = f"""
        SELECT `{COL_OUTBOUND_NO}`, `{COL_OUTBOUND_STATUS}`, `{COL_OUTBOUND_TIME}`, `{COL_OUTBOUND_WAREHOUSE}`
        FROM outband_details
        WHERE `{COL_OUTBOUND_TYPE}` = ?
    """
    params = [outbound_type]

    if date_start:
        query += f" AND `{COL_OUTBOUND_TIME}` >= ?"
        params.append(date_start + " 00:00:00")
    if date_end:
        query += f" AND `{COL_OUTBOUND_TIME}` <= ?"
        params.append(date_end + " 23:59:59")
    if warehouse:
        query += f" AND `{COL_OUTBOUND_WAREHOUSE}` = ?"
        params.append(warehouse)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    outbound_nos = set()
    closed_nos = set()
    unclosed_nos = set()
    sla_count = 0

    for row in rows:
        outbound_no = row[COL_OUTBOUND_NO]
        status = row[COL_OUTBOUND_STATUS]

        if outbound_no:
            outbound_nos.add(outbound_no)
            if status and status.lower() == 'closed':
                closed_nos.add(outbound_no)
            else:
                unclosed_nos.add(outbound_no)

    return {"Total": len(outbound_nos), "Closed": len(closed_nos), "Unclosed": len(unclosed_nos), "SLA": sla_count}


def load_inventory_stats_from_db(date_start=None, date_end=None, warehouse=None):
    if not os.path.exists(DB_PATH):
        return {"Total": 0, "Consumables_QTY": 0, "SpareParts_QTY": 0}

    conn = get_db_connection()
    cursor = conn.cursor()

    latest_date_query = "SELECT MAX(`update_date`) as latest_date FROM inventory_details"
    cursor.execute(latest_date_query)
    latest_date_result = cursor.fetchone()
    latest_date = latest_date_result['latest_date'] if latest_date_result and latest_date_result['latest_date'] else None

    query = "SELECT `Serial No`, `Material Type`, `update_date`, `Warehouse Name` FROM inventory_details"
    params = []
    conditions = []

    if latest_date:
        conditions.append("`update_date` = ?")
        params.append(latest_date)

    if warehouse:
        conditions.append("`Warehouse Name` = ?")
        params.append(warehouse)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    serial_nos = set()
    consumables_count = 0
    spare_parts_count = 0

    for row in rows:
        serial_no = row['Serial No']
        material_type = row['Material Type']

        if serial_no:
            serial_nos.add(serial_no)
            if material_type and material_type.lower() == 'consumable':
                consumables_count += 1
            else:
                spare_parts_count += 1

    return {"Total": len(serial_nos), "Consumables_QTY": consumables_count, "SpareParts_QTY": spare_parts_count}


def load_inventory_trend_from_db(date_start=None, date_end=None, warehouse=None):
    if not os.path.exists(DB_PATH):
        return []

    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT `Serial No`, `Material Type`, `update_date`, `Warehouse Name` FROM inventory_details"
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

        if not update_date:
            continue

        if update_date not in date_stats:
            date_stats[update_date] = {'serial_nos': set(), 'consumables': 0, 'spare_parts': 0}

        if serial_no:
            date_stats[update_date]['serial_nos'].add(serial_no)
            if material_type and material_type.lower() == 'consumable':
                date_stats[update_date]['consumables'] += 1
            else:
                date_stats[update_date]['spare_parts'] += 1

    result = []
    for update_date in sorted(date_stats.keys()):
        stats = date_stats[update_date]
        result.append({
            'update_date': update_date,
            'Total': len(stats['serial_nos']),
            'Consumables_QTY': stats['consumables'],
            'SpareParts_QTY': stats['spare_parts']
        })

    return result


def load_inbound_outbound_trend_from_db(date_start=None, date_end=None, warehouse=None):
    if not os.path.exists(DB_PATH):
        return []

    conn = get_db_connection()
    cursor = conn.cursor()

    inbound_query = f"""
        SELECT date(`{COL_INBOUND_TIME}`) as doc_date, COUNT(*) as qty_sum
        FROM inband_details
        WHERE `{COL_INBOUND_TIME}` IS NOT NULL AND `{COL_INBOUND_TIME}` != ''
    """
    inbound_params = []
    if date_start:
        inbound_query += f" AND `{COL_INBOUND_TIME}` >= ?"
        inbound_params.append(date_start + " 00:00:00")
    if date_end:
        inbound_query += f" AND `{COL_INBOUND_TIME}` <= ?"
        inbound_params.append(date_end + " 23:59:59")
    if warehouse:
        inbound_query += f" AND `{COL_INBOUND_WAREHOUSE}` = ?"
        inbound_params.append(warehouse)
    inbound_query += f" GROUP BY date(`{COL_INBOUND_TIME}`)"

    cursor.execute(inbound_query, inbound_params)
    inbound_rows = cursor.fetchall()

    outbound_query = f"""
        SELECT date(`{COL_OUTBOUND_TIME}`) as doc_date, COUNT(*) as qty_sum
        FROM outband_details
        WHERE `{COL_OUTBOUND_TIME}` IS NOT NULL AND `{COL_OUTBOUND_TIME}` != ''
    """
    outbound_params = []
    if date_start:
        outbound_query += f" AND `{COL_OUTBOUND_TIME}` >= ?"
        outbound_params.append(date_start + " 00:00:00")
    if date_end:
        outbound_query += f" AND `{COL_OUTBOUND_TIME}` <= ?"
        outbound_params.append(date_end + " 23:59:59")
    if warehouse:
        outbound_query += f" AND `{COL_OUTBOUND_WAREHOUSE}` = ?"
        outbound_params.append(warehouse)
    outbound_query += f" GROUP BY date(`{COL_OUTBOUND_TIME}`)"

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
    """获取 Inbound & Outbound 的时间日期范围"""
    if not os.path.exists(DB_PATH):
        return None, None
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    min_date = None
    max_date = None
    
    cursor.execute(f"""
        SELECT MIN(date(`{COL_INBOUND_TIME}`)) as min_d, MAX(date(`{COL_INBOUND_TIME}`)) as max_d
        FROM inband_details
        WHERE `{COL_INBOUND_TIME}` IS NOT NULL AND `{COL_INBOUND_TIME}` != ''
    """)
    row = cursor.fetchone()
    if row:
        if row['min_d'] and (min_date is None or row['min_d'] < min_date):
            min_date = row['min_d']
        if row['max_d'] and (max_date is None or row['max_d'] > max_date):
            max_date = row['max_d']
    
    cursor.execute(f"""
        SELECT MIN(date(`{COL_OUTBOUND_TIME}`)) as min_d, MAX(date(`{COL_OUTBOUND_TIME}`)) as max_d
        FROM outband_details
        WHERE `{COL_OUTBOUND_TIME}` IS NOT NULL AND `{COL_OUTBOUND_TIME}` != ''
    """)
    row = cursor.fetchone()
    if row:
        if row['min_d'] and (min_date is None or row['min_d'] < min_date):
            min_date = row['min_d']
        if row['max_d'] and (max_date is None or row['max_d'] > max_date):
            max_date = row['max_d']
    
    conn.close()
    
    today = datetime.now().strftime('%Y-%m-%d')
    if max_date and today > max_date:
        max_date = today
    
    return min_date, max_date


def load_inbound_outbound_trend_full_range(date_start=None, date_end=None, warehouse=None):
    """
    获取 Inbound & Outbound QTY Trend 数据，填充完整日期范围
    从 Inbound Time/Outbound Time 最小值到最大值（或今天）
    """
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
                     status_column=None, status_value=None, status_mode="exact"):
    if detail_type == "inband" and os.path.exists(DB_PATH):
        return load_inband_detail_from_db(filter_column, filter_value, filter_mode,
                                          first_column, first_value, date_start, date_end, warehouse,
                                          status_column, status_value, status_mode)
    elif detail_type == "outband" and os.path.exists(DB_PATH):
        return load_outband_detail_from_db(filter_column, filter_value, filter_mode,
                                           first_column, first_value, date_start, date_end, warehouse,
                                           status_column, status_value, status_mode)
    elif detail_type == "inventory" and os.path.exists(DB_PATH):
        return load_inventory_detail_from_db(filter_column, filter_value, filter_mode,
                                             first_column, first_value, date_start, date_end, warehouse,
                                             status_column, status_value, status_mode)

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
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(inband_details)")
    columns_info = cursor.fetchall()
    columns = [col[1] for col in columns_info]

    query = "SELECT * FROM inband_details WHERE 1=1"
    params = []

    if date_start:
        query += f" AND `{COL_INBOUND_TIME}` >= ?"
        params.append(date_start + " 00:00:00")
    if date_end:
        query += f" AND `{COL_INBOUND_TIME}` <= ?"
        params.append(date_end + " 23:59:59")
    if warehouse:
        query += f" AND `{COL_INBOUND_WAREHOUSE}` = ?"
        params.append(warehouse)

    if first_column and first_value:
        query += f" AND `{first_column}` LIKE ?"
        params.append(f"{first_value}%")

    if filter_column and filter_value:
        filter_val_str = str(filter_value).strip()
        if filter_mode == "contains":
            query += f" AND LOWER(`{filter_column}`) LIKE ?"
            params.append(f"%{filter_val_str.lower()}%")
        elif filter_mode == "not_contains":
            query += f" AND LOWER(`{filter_column}`) NOT LIKE ?"
            params.append(f"%{filter_val_str.lower()}%")
        else:
            query += f" AND `{filter_column}` LIKE ?"
            params.append(f"{filter_val_str}%")

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
                                status_column=None, status_value=None, status_mode="exact"):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(outband_details)")
    columns_info = cursor.fetchall()
    columns = [col[1] for col in columns_info]

    query = "SELECT * FROM outband_details WHERE 1=1"
    params = []

    if date_start:
        query += f" AND `{COL_OUTBOUND_TIME}` >= ?"
        params.append(date_start + " 00:00:00")
    if date_end:
        query += f" AND `{COL_OUTBOUND_TIME}` <= ?"
        params.append(date_end + " 23:59:59")
    if warehouse:
        query += f" AND `{COL_OUTBOUND_WAREHOUSE}` = ?"
        params.append(warehouse)

    if first_column and first_value:
        query += f" AND `{first_column}` LIKE ?"
        params.append(f"{first_value}%")

    if filter_column and filter_value:
        filter_val_str = str(filter_value).strip()
        if filter_mode == "contains":
            query += f" AND LOWER(`{filter_column}`) LIKE ?"
            params.append(f"%{filter_val_str.lower()}%")
        elif filter_mode == "not_contains":
            query += f" AND LOWER(`{filter_column}`) NOT LIKE ?"
            params.append(f"%{filter_val_str.lower()}%")
        else:
            query += f" AND `{filter_column}` LIKE ?"
            params.append(f"{filter_val_str}%")

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
                                  first_column=None, first_value=None, date_start=None, date_end=None, warehouse=None,
                                  status_column=None, status_value=None, status_mode="exact"):
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
        query += f" AND `{first_column}` LIKE ?"
        params.append(f"{first_value}%")

    if filter_column and filter_value:
        filter_val_str = str(filter_value).strip()
        if filter_mode == "contains":
            query += f" AND LOWER(`{filter_column}`) LIKE ?"
            params.append(f"%{filter_val_str.lower()}%")
        elif filter_mode == "not_contains":
            query += f" AND LOWER(`{filter_column}`) NOT LIKE ?"
            params.append(f"%{filter_val_str.lower()}%")
        else:
            query += f" AND `{filter_column}` LIKE ?"
            params.append(f"{filter_val_str}%")

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

    return DETAIL_TITLES.get("inventory", "Inventory Details View"), columns, records


def load_early_warning_from_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(ocrule_details)")
    columns_info = cursor.fetchall()
    columns = [col[1] for col in columns_info]

    query = """
        SELECT * FROM ocrule_details 
        WHERE woType LIKE '%-sp-%' 
        AND (triggerStep LIKE '%_Create%' OR triggerStep LIKE '%_Verify%')
    """
    cursor.execute(query)
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

    grouped_by_rule_type = {}
    for record in records:
        rule_type = record.get('ruleType', '')
        if rule_type not in grouped_by_rule_type:
            grouped_by_rule_type[rule_type] = []
        grouped_by_rule_type[rule_type].append(record)

    result = []
    for rule_type, group_records in grouped_by_rule_type.items():
        create_records = [r for r in group_records if '_Create' in r.get('triggerStep', '')]
        verify_records = [r for r in group_records if '_Verify' in r.get('triggerStep', '')]
        
        if create_records and verify_records:
            create_handlers = set()
            for r in create_records:
                handler = str(r.get('targetHandlerName', '')).strip()
                if handler:
                    create_handlers.add(handler)
            
            verify_handlers = set()
            for r in verify_records:
                handler = str(r.get('targetHandlerName', '')).strip()
                if handler:
                    verify_handlers.add(handler)
            
            common_handlers = create_handlers & verify_handlers
            
            if common_handlers:
                for r in create_records:
                    handler = str(r.get('targetHandlerName', '')).strip()
                    if handler in common_handlers:
                        result.append(r)
                for r in verify_records:
                    handler = str(r.get('targetHandlerName', '')).strip()
                    if handler in common_handlers:
                        result.append(r)

    seen = set()
    unique_result = []
    for r in result:
        key = (r.get('ruleName', ''), r.get('triggerStep', ''))
        if key not in seen:
            seen.add(key)
            unique_result.append(r)

    return unique_result


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/data')
def get_data():
    try:
        date_start = request.args.get('date_start')
        date_end = request.args.get('date_end')
        warehouse = request.args.get('warehouse')

        data = {}

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

        borrow_stats = load_special_outbound_stats_from_db('Borrow Outbound/50202001', 45, date_start, date_end, warehouse)
        data['Borrow Outbound'] = [borrow_stats]

        repair_stats = load_special_outbound_stats_from_db('Repair Outbound/50202005', 180, date_start, date_end, warehouse)
        data['Repair Outbound'] = [repair_stats]

        inventory_lost_stats = load_special_outbound_stats_from_db('Inventory Outbound/50202003', 1, date_start, date_end, warehouse)
        data['Inventory Lost Outbound'] = [inventory_lost_stats]

        inventory_stats = load_inventory_stats_from_db(date_start, date_end, warehouse)
        data['Inventory'] = [inventory_stats]

        inventory_trend = load_inventory_trend_from_db(date_start, date_end, warehouse)
        data['Inventory Quantity Trend'] = inventory_trend

        inbound_outbound_trend = load_inbound_outbound_trend_full_range(date_start, date_end, warehouse)
        data['Inbound & Outbound Ticket T'] = inbound_outbound_trend

        data['Early Warning Document Detail'] = load_early_warning_from_db()

        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


def get_table_columns(cursor, table_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [col[1] for col in cursor.fetchall()]


def find_warehouse_column(columns):
    for col in columns:
        if 'warehouse' in col.lower() or '仓库' in col:
            return col
    return None


@app.route('/api/warehouses')
def get_warehouses():
    try:
        if not os.path.exists(DB_PATH):
            return jsonify({"status": "success", "warehouses": []})

        conn = get_db_connection()
        cursor = conn.cursor()

        warehouses = set()

        inband_cols = get_table_columns(cursor, 'inband_details')
        inband_wh_col = find_warehouse_column(inband_cols)
        if inband_wh_col:
            cursor.execute(
                f"SELECT DISTINCT `{inband_wh_col}` FROM inband_details WHERE `{inband_wh_col}` IS NOT NULL AND `{inband_wh_col}` != ''")
            for row in cursor.fetchall():
                if row[inband_wh_col]:
                    warehouses.add(row[inband_wh_col])

        outband_cols = get_table_columns(cursor, 'outband_details')
        outband_wh_col = find_warehouse_column(outband_cols)
        if outband_wh_col:
            cursor.execute(
                f"SELECT DISTINCT `{outband_wh_col}` FROM outband_details WHERE `{outband_wh_col}` IS NOT NULL AND `{outband_wh_col}` != ''")
            for row in cursor.fetchall():
                if row[outband_wh_col]:
                    warehouses.add(row[outband_wh_col])

        inv_cols = get_table_columns(cursor, 'inventory_details')
        inv_wh_col = find_warehouse_column(inv_cols)
        if inv_wh_col:
            cursor.execute(
                f"SELECT DISTINCT `{inv_wh_col}` FROM inventory_details WHERE `{inv_wh_col}` IS NOT NULL AND `{inv_wh_col}` != ''")
            for row in cursor.fetchall():
                if row[inv_wh_col]:
                    warehouses.add(row[inv_wh_col])

        conn.close()

        return jsonify({"status": "success", "warehouses": sorted(list(warehouses))})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/details')
def get_details():
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
        title, columns, data = load_detail_data(
            detail_type, filter_column, filter_value, filter_mode,
            first_column=first_column, first_value=first_value,
            date_start=date_start, date_end=date_end, warehouse=warehouse,
            status_column=status_column, status_value=status_value, status_mode=status_mode,
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
    app.run(host='0.0.0.0', port=7038, debug=True)

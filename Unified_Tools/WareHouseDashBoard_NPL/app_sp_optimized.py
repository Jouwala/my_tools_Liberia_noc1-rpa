import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sqlite3
import pandas as pd
from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta

from shared.db_manager_optimized import get_db_connection, check_db_exists
from shared.cache_manager import get_cache_manager
from shared.query_optimizer import QueryOptimizer
from shared.performance_monitor import get_performance_monitor

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OVERVIEW_PATH = os.path.join(DATA_DIR, "sp_overview.xlsx")
DB_PATH = os.path.join(os.path.dirname(__file__), "inventory.db")

cache_mgr = get_cache_manager()
perf_monitor = get_performance_monitor()

CACHE_NAMESPACE = "NPL"

cache_mgr.set_namespace(CACHE_NAMESPACE)
cache_mgr.invalidate_all()
print(f"[INFO] Cache cleared for NPL Dashboard")


@app.before_request
def set_cache_namespace():
    cache_mgr.set_namespace(CACHE_NAMESPACE)


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


def detect_column_name(columns, keywords):
    for keyword in keywords:
        for col in columns:
            if col == keyword:
                return col
    for keyword in keywords:
        keyword_lower = keyword.lower()
        for col in columns:
            if keyword_lower == col.lower():
                return col
    for keyword in keywords:
        keyword_lower = keyword.lower()
        for col in columns:
            if keyword_lower in col.lower():
                return col
    return None


def get_table_columns(conn, table_name):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    return [col[1] for col in cursor.fetchall()]


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_inband_stats_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0}
    
    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        columns = get_table_columns(conn, 'inband_details')
        
        col_in_stock_number = detect_column_name(columns, ['In Stock Number', 'In_Stock_Number', 'in_stock_number'])
        col_status = detect_column_name(columns, ['Status', 'status'])
        col_confirm_time = detect_column_name(columns, ['Confirm Time', 'Confirm_Time', 'confirm_time'])
        col_warehouse = detect_column_name(columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
        
        if date_start or date_end or warehouse:
            cond_parts = []
            params = []
            if date_start and col_confirm_time:
                cond_parts.append(f"`{col_confirm_time}` >= ?")
                params.append(date_start + " 00:00:00")
            if date_end and col_confirm_time:
                cond_parts.append(f"`{col_confirm_time}` <= ?")
                params.append(date_end + " 23:59:59")
            if warehouse and col_warehouse:
                cond_parts.append(f"`{col_warehouse}` = ?")
                params.append(warehouse)
            
            if cond_parts:
                where_sql = " AND ".join(cond_parts)
                cursor.execute(
                    f"SELECT DISTINCT `{col_in_stock_number}` FROM inband_details WHERE " + where_sql,
                    params
                )
            else:
                cursor.execute(f"SELECT DISTINCT `{col_in_stock_number}` FROM inband_details")
            
            ticket_ids = [row[col_in_stock_number] for row in cursor.fetchall() if row[col_in_stock_number]]
            if not ticket_ids:
                return {"Total": 0, "Closed": 0, "Unclosed": 0}
            
            placeholders = ",".join("?" * len(ticket_ids))
            cursor.execute(
                f"SELECT `{col_in_stock_number}`, `{col_status}` FROM inband_details WHERE `{col_in_stock_number}` IN (" + placeholders + ")",
                ticket_ids
            )
            rows = cursor.fetchall()
        else:
            cursor.execute(
                f"SELECT `{col_in_stock_number}`, `{col_status}` FROM inband_details"
            )
            rows = cursor.fetchall()
        
        ticket_status = {}
        for row in rows:
            inbound_no = row[col_in_stock_number]
            status = row[col_status]
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
        
        return {
            "Total": total,
            "Closed": closed,
            "Unclosed": unclosed
        }


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_inbound_details_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return []
    
    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        columns = get_table_columns(conn, 'inband_details')
        
        col_in_stock_number = detect_column_name(columns, ['In Stock Number', 'In_Stock_Number', 'in_stock_number'])
        col_status = detect_column_name(columns, ['Status', 'status'])
        col_in_stock_type = detect_column_name(columns, ['In Stock Type', 'In_Stock_Type', 'in_stock_type'])
        col_quantity = detect_column_name(columns, ['Quantity', 'quantity'])
        col_confirm_time = detect_column_name(columns, ['Confirm Time', 'Confirm_Time', 'confirm_time'])
        col_warehouse = detect_column_name(columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
        
        ticket_status = {}
        params = []
        conditions = []
        
        if date_start and col_confirm_time:
            conditions.append(f"`{col_confirm_time}` >= ?")
            params.append(date_start + " 00:00:00")
        if date_end and col_confirm_time:
            conditions.append(f"`{col_confirm_time}` <= ?")
            params.append(date_end + " 23:59:59")
        if warehouse and col_warehouse:
            conditions.append(f"`{col_warehouse}` = ?")
            params.append(warehouse)
        
        if conditions:
            where_sql = " AND ".join(conditions)
            cursor.execute(
                f"SELECT DISTINCT `{col_in_stock_number}` FROM inband_details WHERE " + where_sql,
                params
            )
            ticket_ids = [row[col_in_stock_number] for row in cursor.fetchall() if row[col_in_stock_number]]
            if not ticket_ids:
                return []
            
            placeholders = ",".join("?" * len(ticket_ids))
            cursor.execute(
                f"SELECT `{col_in_stock_number}`, `{col_status}` FROM inband_details WHERE `{col_in_stock_number}` IN (" + placeholders + ")",
                ticket_ids
            )
            for row in cursor.fetchall():
                inbound_no = row[col_in_stock_number]
                status = row[col_status]
                if not inbound_no:
                    continue
                is_closed = bool(status and str(status).strip().lower() == 'closed')
                if inbound_no not in ticket_status:
                    ticket_status[inbound_no] = False
                if not is_closed:
                    ticket_status[inbound_no] = True
            
            cursor.execute(
                f"""SELECT `{col_in_stock_number}`, `{col_in_stock_type}`, `{col_quantity}` FROM inband_details WHERE """ + where_sql,
                params
            )
            rows = cursor.fetchall()
        else:
            cursor.execute(
                f"SELECT `{col_in_stock_number}`, `{col_status}`, `{col_in_stock_type}`, `{col_quantity}` FROM inband_details"
            )
            rows = cursor.fetchall()
            for row in rows:
                inbound_no = row[col_in_stock_number]
                status = row[col_status]
                if not inbound_no:
                    continue
                is_closed = bool(status and str(status).strip().lower() == 'closed')
                if inbound_no not in ticket_status:
                    ticket_status[inbound_no] = False
                if not is_closed:
                    ticket_status[inbound_no] = True
        
        type_stats = {}
        for row in rows:
            inbound_type = row[col_in_stock_type] or 'Unknown'
            inbound_no = row[col_in_stock_number]
            inbound_qty = row[col_quantity] or 0
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
        
        return result


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_outband_stats_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0}
    
    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        columns = get_table_columns(conn, 'outband_details')
        
        col_out_stock_number = detect_column_name(columns, ['Out Stock Number', 'Out_Stock_Number', 'out_stock_number'])
        col_status = detect_column_name(columns, ['Status', 'status'])
        col_confirm_time = detect_column_name(columns, ['Confirm Time', 'Confirm_Time', 'confirm_time'])
        col_warehouse = detect_column_name(columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
        
        query = f"SELECT `{col_out_stock_number}`, `{col_status}`, `{col_confirm_time}`, `{col_warehouse}` FROM outband_details"
        params = []
        conditions = []
        
        if date_start and col_confirm_time:
            conditions.append(f"`{col_confirm_time}` >= ?")
            params.append(date_start + " 00:00:00")
        if date_end and col_confirm_time:
            conditions.append(f"`{col_confirm_time}` <= ?")
            params.append(date_end + " 23:59:59")
        if warehouse and col_warehouse:
            conditions.append(f"`{col_warehouse}` = ?")
            params.append(warehouse)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        outbound_nos = set()
        closed_nos = set()
        unclosed_nos = set()
        
        for row in rows:
            outbound_no = row[col_out_stock_number]
            status = row[col_status]
            
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


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_outbound_details_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return []
    
    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        columns = get_table_columns(conn, 'outband_details')
        
        col_out_stock_number = detect_column_name(columns, ['Out Stock Number', 'Out_Stock_Number', 'out_stock_number'])
        col_status = detect_column_name(columns, ['Status', 'status'])
        col_out_type = detect_column_name(columns, ['Out Type', 'Out_Type', 'out_type'])
        col_quantity = detect_column_name(columns, ['Quantity', 'quantity'])
        col_confirm_time = detect_column_name(columns, ['Confirm Time', 'Confirm_Time', 'confirm_time'])
        col_warehouse = detect_column_name(columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
        
        query = f"""
            SELECT `{col_out_stock_number}`, `{col_status}`, `{col_out_type}`, `{col_quantity}`, `{col_confirm_time}`, `{col_warehouse}`
            FROM outband_details
        """
        params = []
        conditions = []
        
        if date_start and col_confirm_time:
            conditions.append(f"`{col_confirm_time}` >= ?")
            params.append(date_start + " 00:00:00")
        if date_end and col_confirm_time:
            conditions.append(f"`{col_confirm_time}` <= ?")
            params.append(date_end + " 23:59:59")
        if warehouse and col_warehouse:
            conditions.append(f"`{col_warehouse}` = ?")
            params.append(warehouse)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        type_stats = {}
        
        for row in rows:
            outbound_type = row[col_out_type] or 'Unknown'
            outbound_no = row[col_out_stock_number]
            status = row[col_status]
            stock_qty = row[col_quantity] or 0
            
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


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_special_outbound_stats_from_db(outbound_type, sla_days, date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0, "SLA": 0}
    
    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        columns = get_table_columns(conn, 'outband_details')
        
        col_out_stock_number = detect_column_name(columns, ['Out Stock Number', 'Out_Stock_Number', 'out_stock_number'])
        col_status = detect_column_name(columns, ['Status', 'status'])
        col_out_type = detect_column_name(columns, ['Out Type', 'Out_Type', 'out_type'])
        col_confirm_time = detect_column_name(columns, ['Confirm Time', 'Confirm_Time', 'confirm_time'])
        col_close_time = detect_column_name(columns, ['Close Time', 'Close_Time', 'close_time'])
        col_warehouse = detect_column_name(columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
        
        query = f"""
            SELECT `{col_out_stock_number}`, `{col_status}`, `{col_confirm_time}`, `{col_close_time}`, `{col_warehouse}`
            FROM outband_details
            WHERE `{col_out_type}` = ?
        """
        params = [outbound_type]
        
        if date_start and col_confirm_time:
            query += f" AND `{col_confirm_time}` >= ?"
            params.append(date_start + " 00:00:00")
        if date_end and col_confirm_time:
            query += f" AND `{col_confirm_time}` <= ?"
            params.append(date_end + " 23:59:59")
        if warehouse and col_warehouse:
            query += f" AND `{col_warehouse}` = ?"
            params.append(warehouse)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        outbound_nos = set()
        closed_nos = set()
        unclosed_nos = set()
        sla_nos = set()
        now = datetime.now()
        
        for row in rows:
            outbound_no = row[col_out_stock_number]
            status = row[col_status]
            confirm_time_str = row[col_confirm_time] if col_close_time else None
            close_time_str = row[col_close_time] if col_close_time else None
            
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


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_inventory_stats_from_db(date_start=None, date_end=None, warehouse=None):
    """
    从 inventory.db 的 inventory_details 表获取 Inventory 统计数据。
    始终显示最新一天的数据，不受时间范围影响。
    
    统计逻辑（按 Quantity 总和）：
    - Total: 最新一天数据中，Quantity 列的总和
    - Consumables: 最新一天数据中，Material Type 为 "Consumable" 的 Quantity 总和
    - SpareParts: 最新一天数据中，Material Type 不是 "Consumable" 的 Quantity 总和
    """
    if not check_db_exists(DB_PATH):
        return {"Total": 0, "Consumables_QTY": 0, "SpareParts_QTY": 0}
    
    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        columns = get_table_columns(conn, 'inventory_details')
        
        col_serial_no = detect_column_name(columns, ['Serial No', 'Serial_No', 'serial_no'])
        col_material_type = detect_column_name(columns, ['Material Type', 'Material_Type', 'material_type'])
        col_update_date = detect_column_name(columns, ['update_date', 'Update_Date', 'updateDate'])
        col_warehouse = detect_column_name(columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
        col_quantity = detect_column_name(columns, ['Quantity', 'quantity'])
        
        # 首先获取最新的 update_date
        latest_date_query = f"SELECT MAX(`{col_update_date}`) as latest_date FROM inventory_details WHERE `{col_update_date}` IS NOT NULL AND `{col_update_date}` != ''"
        cursor.execute(latest_date_query)
        latest_date_result = cursor.fetchone()
        latest_date = latest_date_result['latest_date'] if latest_date_result and latest_date_result['latest_date'] else None
        
        if not latest_date:
            return {"Total": 0, "Consumables_QTY": 0, "SpareParts_QTY": 0}
        
        query = f"""
            SELECT `{col_serial_no}`, `{col_material_type}`, `{col_quantity}`, `{col_warehouse}`
            FROM inventory_details
            WHERE `{col_update_date}` = ?
        """
        params = [latest_date]
        
        if warehouse and col_warehouse:
            query += f" AND `{col_warehouse}` = ?"
            params.append(warehouse)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        total_qty = 0
        consumables_qty = 0
        spare_parts_qty = 0
        
        for row in rows:
            material_type = row[col_material_type]
            quantity = row[col_quantity] or 0
            
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


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_inventory_trend_from_db(date_start=None, date_end=None, warehouse=None):
    """
    从 inventory.db 的 inventory_details 表获取 Inventory Quantity Trend 数据。
    时间从 update_date 列过滤。
    按时间统计：
    - Total: Quantity 列的总和
    - Consumables: Material Type 列是 "Consumable" 的 Quantity 总和
    - SpareParts: Material Type 列不是 "Consumable" 的 Quantity 总和
    """
    if not check_db_exists(DB_PATH):
        return []
    
    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        columns = get_table_columns(conn, 'inventory_details')
        
        col_serial_no = detect_column_name(columns, ['Serial No', 'Serial_No', 'serial_no'])
        col_material_type = detect_column_name(columns, ['Material Type', 'Material_Type', 'material_type'])
        col_update_date = detect_column_name(columns, ['update_date', 'Update_Date', 'updateDate'])
        col_warehouse = detect_column_name(columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
        col_quantity = detect_column_name(columns, ['Quantity', 'quantity'])
        
        query = f"""
            SELECT `{col_serial_no}`, `{col_material_type}`, `{col_update_date}`, `{col_quantity}`, `{col_warehouse}`
            FROM inventory_details
        """
        params = []
        conditions = []
        
        if date_start:
            conditions.append(f"`{col_update_date}` >= ?")
            params.append(date_start)
        if date_end:
            conditions.append(f"`{col_update_date}` <= ?")
            params.append(date_end)
        if warehouse and col_warehouse:
            conditions.append(f"`{col_warehouse}` = ?")
            params.append(warehouse)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        date_stats = {}
        
        for row in rows:
            update_date = row[col_update_date]
            serial_no = row[col_serial_no]
            material_type = row[col_material_type]
            quantity = row[col_quantity] or 0
            
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


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_inbound_outbound_trend_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return []
    
    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        
        inband_columns = get_table_columns(conn, 'inband_details')
        outband_columns = get_table_columns(conn, 'outband_details')
        
        col_confirm_time_in = detect_column_name(inband_columns, ['Confirm Time', 'Confirm_Time', 'confirm_time'])
        col_quantity_in = detect_column_name(inband_columns, ['Quantity', 'quantity'])
        col_warehouse_in = detect_column_name(inband_columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
        
        col_confirm_time_out = detect_column_name(outband_columns, ['Confirm Time', 'Confirm_Time', 'confirm_time'])
        col_quantity_out = detect_column_name(outband_columns, ['Quantity', 'quantity'])
        col_warehouse_out = detect_column_name(outband_columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
        
        inbound_query = f"""
            SELECT date(`{col_confirm_time_in}`) as doc_date, SUM(`{col_quantity_in}`) as qty_sum
            FROM inband_details
            WHERE `{col_confirm_time_in}` IS NOT NULL AND `{col_confirm_time_in}` != ''
        """
        inbound_params = []
        if date_start:
            inbound_query += f" AND `{col_confirm_time_in}` >= ?"
            inbound_params.append(date_start + " 00:00:00")
        if date_end:
            inbound_query += f" AND `{col_confirm_time_in}` <= ?"
            inbound_params.append(date_end + " 23:59:59")
        if warehouse and col_warehouse_in:
            inbound_query += f" AND `{col_warehouse_in}` = ?"
            inbound_params.append(warehouse)
        inbound_query += f" GROUP BY date(`{col_confirm_time_in}`)"
        
        cursor.execute(inbound_query, inbound_params)
        inbound_rows = cursor.fetchall()
        
        outbound_query = f"""
            SELECT date(`{col_confirm_time_out}`) as doc_date, SUM(`{col_quantity_out}`) as qty_sum
            FROM outband_details
            WHERE `{col_confirm_time_out}` IS NOT NULL AND `{col_confirm_time_out}` != ''
        """
        outbound_params = []
        if date_start:
            outbound_query += f" AND `{col_confirm_time_out}` >= ?"
            outbound_params.append(date_start + " 00:00:00")
        if date_end:
            outbound_query += f" AND `{col_confirm_time_out}` <= ?"
            outbound_params.append(date_end + " 23:59:59")
        if warehouse and col_warehouse_out:
            outbound_query += f" AND `{col_warehouse_out}` = ?"
            outbound_params.append(warehouse)
        outbound_query += f" GROUP BY date(`{col_confirm_time_out}`)"
        
        cursor.execute(outbound_query, outbound_params)
        outbound_rows = cursor.fetchall()
        
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


@cache_mgr.cached_stats()
@perf_monitor.timed
def get_inbound_outbound_date_range():
    """获取 Inbound & Outbound 的 Confirm Time 日期范围"""
    if not check_db_exists(DB_PATH):
        return None, None
    
    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        
        inband_columns = get_table_columns(conn, 'inband_details')
        outband_columns = get_table_columns(conn, 'outband_details')
        
        col_confirm_time_in = detect_column_name(inband_columns, ['Confirm Time', 'Confirm_Time', 'confirm_time'])
        col_confirm_time_out = detect_column_name(outband_columns, ['Confirm Time', 'Confirm_Time', 'confirm_time'])
        
        min_date = None
        max_date = None
        
        if col_confirm_time_in:
            cursor.execute(f"""
                SELECT MIN(date(`{col_confirm_time_in}`)) as min_d, MAX(date(`{col_confirm_time_in}`)) as max_d
                FROM inband_details
                WHERE `{col_confirm_time_in}` IS NOT NULL AND `{col_confirm_time_in}` != ''
            """)
            row = cursor.fetchone()
            if row:
                if row['min_d'] and (min_date is None or row['min_d'] < min_date):
                    min_date = row['min_d']
                if row['max_d'] and (max_date is None or row['max_d'] > max_date):
                    max_date = row['max_d']
        
        if col_confirm_time_out:
            cursor.execute(f"""
                SELECT MIN(date(`{col_confirm_time_out}`)) as min_d, MAX(date(`{col_confirm_time_out}`)) as max_d
                FROM outband_details
                WHERE `{col_confirm_time_out}` IS NOT NULL AND `{col_confirm_time_out}` != ''
            """)
            row = cursor.fetchone()
            if row:
                if row['min_d'] and (min_date is None or row['min_d'] < min_date):
                    min_date = row['min_d']
                if row['max_d'] and (max_date is None or row['max_d'] > max_date):
                    max_date = row['max_d']
        
        from datetime import datetime, timedelta
        today = datetime.now().strftime('%Y-%m-%d')
        if max_date and today > max_date:
            max_date = today
        
        return min_date, max_date


@cache_mgr.cached_stats()
@perf_monitor.timed
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


@cache_mgr.cached_stats()
@perf_monitor.timed
def get_latest_update_time_from_db():
    if not check_db_exists(DB_PATH):
        return ""
    
    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        columns = get_table_columns(conn, 'inventory_details')
        col_update_time = detect_column_name(columns, ['update_time', 'Update_Time', 'updateTime'])
        
        query = f"SELECT MAX(`{col_update_time}`) as latest_time FROM inventory_details"
        cursor.execute(query)
        result = cursor.fetchone()
        
        return result['latest_time'] if result and result['latest_time'] else ""


def load_inband_detail_from_db(filter_column=None, filter_value=None, filter_mode="exact",
                               first_column=None, first_value=None, date_start=None, date_end=None, warehouse=None,
                               status_column=None, status_value=None, status_mode="exact"):
    if not check_db_exists(DB_PATH):
        return DETAIL_TITLES.get("inband", "Inband Details View"), [], []
    
    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        columns = get_table_columns(conn, 'inband_details')
        
        col_confirm_time = detect_column_name(columns, ['Confirm Time', 'Confirm_Time', 'confirm_time'])
        col_warehouse = detect_column_name(columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
        
        query = "SELECT * FROM inband_details WHERE 1=1"
        params = []
        
        if date_start and col_confirm_time:
            query += f" AND `{col_confirm_time}` >= ?"
            params.append(date_start + " 00:00:00")
        if date_end and col_confirm_time:
            query += f" AND `{col_confirm_time}` <= ?"
            params.append(date_end + " 23:59:59")
        if warehouse and col_warehouse:
            query += f" AND `{col_warehouse}` = ?"
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
    sla_filter: 是否过滤 SLA 超期记录
    sla_type: SLA 类型 (Borrow Outbound, Repair Outbound, Inventory Outbound)
    """
    if sla_filter and sla_type:
        print(f"[DEBUG] SLA filter requested: sla_type={sla_type}", flush=True)
        early_warning_data = load_early_warning_from_db(date_start, date_end, warehouse)
        print(f"[DEBUG] Early warning data: total_records={len(early_warning_data['records'])}", flush=True)
        if early_warning_data['records']:
            print(f"[DEBUG] Sample record SLA_Types: {[r.get('SLA_Type') for r in early_warning_data['records'][:5]]}", flush=True)
        filtered_records = [r for r in early_warning_data['records'] if r.get('SLA_Type') == sla_type]
        print(f"[DEBUG] Filtered records for '{sla_type}': count={len(filtered_records)}", flush=True)
        columns = early_warning_data['columns']
        return DETAIL_TITLES.get("outband", "Outbound Details View"), columns, filtered_records
    
    with get_db_connection(DB_PATH) as conn:
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
    if not check_db_exists(DB_PATH):
        return DETAIL_TITLES.get("inventory", "Inventory Details View"), [], []
    
    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        columns = get_table_columns(conn, 'inventory_details')
        
        col_update_date = detect_column_name(columns, ['update_date', 'Update_Date', 'updateDate'])
        col_warehouse = detect_column_name(columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
        
        query = "SELECT * FROM inventory_details WHERE 1=1"
        params = []
        
        if date_start:
            query += f" AND `{col_update_date}` >= ?"
            params.append(date_start)
        if date_end:
            query += f" AND `{col_update_date}` <= ?"
            params.append(date_end)
        if warehouse and col_warehouse:
            query += f" AND `{col_warehouse}` = ?"
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


def load_detail_data(detail_type, filter_column=None, filter_value=None, filter_mode="exact",
                     first_column=None, first_value=None, date_start=None, date_end=None, warehouse=None,
                     status_column=None, status_value=None, status_mode="exact", sla_filter=False, sla_type=None):
    db_exists = check_db_exists(DB_PATH)
    if detail_type == "inband" and db_exists:
        return load_inband_detail_from_db(filter_column, filter_value, filter_mode,
                                          first_column, first_value, date_start, date_end, warehouse,
                                          status_column, status_value, status_mode)
    elif detail_type == "outband" and db_exists:
        return load_outband_detail_from_db(filter_column, filter_value, filter_mode,
                                           first_column, first_value, date_start, date_end, warehouse,
                                           status_column, status_value, status_mode, sla_filter, sla_type)
    elif detail_type == "inventory" and db_exists:
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


@perf_monitor.timed
def load_early_warning_from_db(date_start=None, date_end=None, warehouse=None):
    """
    从 outband_details 表获取 SLA 预警详细数据。
    获取 Borrow Outbound (>45天), Repair Outbound (>180天), Inventory Outbound (>1天) 的 SLA 超期单据。
    SLA计算: Close Time - Confirm Time，如果没有Close Time则使用当前时间
    """
    if not check_db_exists(DB_PATH):
        return {'columns': [], 'records': []}

    sla_configs = [
        {'outbound_type': 'Borrow Outbound', 'sla_days': 45},
        {'outbound_type': 'Repair Outbound', 'sla_days': 180},
        {'outbound_type': 'Inventory Outbound', 'sla_days': 1},
    ]

    all_records = []

    with get_db_connection(DB_PATH) as conn:
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
        
        borrow_stats = load_special_outbound_stats_from_db('Borrow Outbound', 45, date_start, date_end, warehouse)
        data['Borrow Outbound'] = [borrow_stats]
        
        repair_stats = load_special_outbound_stats_from_db('Repair Outbound', 180, date_start, date_end, warehouse)
        data['Repair Outbound'] = [repair_stats]
        
        inventory_lost_stats = load_special_outbound_stats_from_db('Inventory Outbound', 1, date_start, date_end, warehouse)
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
    try:
        if not check_db_exists(DB_PATH):
            return jsonify({"status": "success", "warehouses": []})
        
        with get_db_connection(DB_PATH) as conn:
            cursor = conn.cursor()
            
            warehouses = set()
            
            inband_columns = get_table_columns(conn, 'inband_details')
            col_warehouse_in = detect_column_name(inband_columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
            cursor.execute(
                f"SELECT DISTINCT `{col_warehouse_in}` FROM inband_details WHERE `{col_warehouse_in}` IS NOT NULL AND `{col_warehouse_in}` != ''"
            )
            for row in cursor.fetchall():
                if row[col_warehouse_in]:
                    warehouses.add(row[col_warehouse_in])
            
            outband_columns = get_table_columns(conn, 'outband_details')
            col_warehouse_out = detect_column_name(outband_columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
            cursor.execute(
                f"SELECT DISTINCT `{col_warehouse_out}` FROM outband_details WHERE `{col_warehouse_out}` IS NOT NULL AND `{col_warehouse_out}` != ''"
            )
            for row in cursor.fetchall():
                if row[col_warehouse_out]:
                    warehouses.add(row[col_warehouse_out])
            
            inventory_columns = get_table_columns(conn, 'inventory_details')
            col_warehouse_inv = detect_column_name(inventory_columns, ['Warehouse Name', 'Warehouse_Name', 'warehouse_name'])
            cursor.execute(
                f"SELECT DISTINCT `{col_warehouse_inv}` FROM inventory_details WHERE `{col_warehouse_inv}` IS NOT NULL AND `{col_warehouse_inv}` != ''"
            )
            for row in cursor.fetchall():
                if row[col_warehouse_inv]:
                    warehouses.add(row[col_warehouse_inv])
            
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


@app.route('/api/performance')
def get_performance_stats():
    return jsonify({
        "status": "success",
        "data": perf_monitor.get_metrics()
    })


@app.route('/api/cache/stats')
def get_cache_stats():
    hits, misses, hit_rate = cache_mgr.get_stats()
    return jsonify({
        "status": "success",
        "data": {
            "hits": hits,
            "misses": misses,
            "hit_rate": hit_rate
        }
    })


@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    cache_mgr.invalidate_all()
    return jsonify({"status": "success", "message": "Cache cleared"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7038, debug=True)

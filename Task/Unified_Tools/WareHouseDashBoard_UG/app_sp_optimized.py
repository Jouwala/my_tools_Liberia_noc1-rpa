
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sqlite3
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

COL_INBOUND_TYPE = "入库类型/whinType"
COL_INBOUND_NO = "入库单号/woNum"
COL_INBOUND_STATUS = "状态/status"
COL_INBOUND_TIME = "创建时间/createTime"
COL_INBOUND_WAREHOUSE = "仓库/warehouseID"

COL_OUTBOUND_NO = "ticketNum/ticketNum"
COL_OUTBOUND_STATUS = "单据状态/status"
COL_OUTBOUND_TYPE = "出库单类型/whoutType"
COL_OUTBOUND_TIME = "outboundTime/outboundTime"
COL_OUTBOUND_WAREHOUSE = "仓库/warehouseID"


def detect_column_name(columns, keywords):
    for col in columns:
        col_lower = col.lower()
        for keyword in keywords:
            if keyword.lower() in col_lower:
                return col
    return None


def init_column_names():
    global COL_INBOUND_TYPE, COL_INBOUND_NO, COL_INBOUND_STATUS, COL_INBOUND_TIME, COL_INBOUND_WAREHOUSE
    global COL_OUTBOUND_NO, COL_OUTBOUND_STATUS, COL_OUTBOUND_TYPE, COL_OUTBOUND_TIME, COL_OUTBOUND_WAREHOUSE
    
    if not os.path.exists(DB_PATH):
        return
    
    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        
        try:
            cursor.execute("PRAGMA table_info(inband_details)")
            inband_cols = [col[1] for col in cursor.fetchall()]
            
            COL_INBOUND_TYPE = detect_column_name(inband_cols, ['whinType', '入库类型']) or COL_INBOUND_TYPE
            COL_INBOUND_NO = detect_column_name(inband_cols, ['woNum', '入库单号']) or COL_INBOUND_NO
            COL_INBOUND_STATUS = detect_column_name(inband_cols, ['status', '状态']) or COL_INBOUND_STATUS
            COL_INBOUND_TIME = detect_column_name(inband_cols, ['createTime', '创建时间']) or COL_INBOUND_TIME
            COL_INBOUND_WAREHOUSE = detect_column_name(inband_cols, ['warehouse', '仓库']) or COL_INBOUND_WAREHOUSE
            
            cursor.execute("PRAGMA table_info(outband_details)")
            outband_cols = [col[1] for col in cursor.fetchall()]
            
            COL_OUTBOUND_NO = detect_column_name(outband_cols, ['ticketNum', '出库单编号']) or COL_OUTBOUND_NO
            COL_OUTBOUND_STATUS = detect_column_name(outband_cols, ['status', '单据状态']) or COL_OUTBOUND_STATUS
            COL_OUTBOUND_TYPE = detect_column_name(outband_cols, ['whoutType', '出库单类型']) or COL_OUTBOUND_TYPE
            COL_OUTBOUND_TIME = detect_column_name(outband_cols, ['outboundTime', 'woOutboundTime']) or COL_OUTBOUND_TIME
            COL_OUTBOUND_WAREHOUSE = detect_column_name(outband_cols, ['warehouse', '仓库']) or COL_OUTBOUND_WAREHOUSE
            
            print(f"[INFO] Detected columns:")
            print(f"  Inbound: type={COL_INBOUND_TYPE}, no={COL_INBOUND_NO}, status={COL_INBOUND_STATUS}, time={COL_INBOUND_TIME}, warehouse={COL_INBOUND_WAREHOUSE}")
            print(f"  Outbound: no={COL_OUTBOUND_NO}, status={COL_OUTBOUND_STATUS}, type={COL_OUTBOUND_TYPE}, time={COL_OUTBOUND_TIME}, warehouse={COL_OUTBOUND_WAREHOUSE}")
        except Exception as e:
            print(f"[WARN] Failed to detect columns: {e}")


init_column_names()

CACHE_NAMESPACE = "UG"

cache_mgr.set_namespace(CACHE_NAMESPACE)
cache_mgr.invalidate_all()
print(f"[INFO] Cache cleared for UG Dashboard")


@app.before_request
def set_cache_namespace():
    cache_mgr.set_namespace(CACHE_NAMESPACE)


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_inband_stats_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0}

    query, params = QueryOptimizer.optimize_inband_stats_query(
        COL_INBOUND_NO, COL_INBOUND_STATUS, COL_INBOUND_TIME, COL_INBOUND_WAREHOUSE,
        date_start, date_end, warehouse
    )

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        return {
            "Total": row['Total'] if row else 0,
            "Closed": row['Closed'] if row else 0,
            "Unclosed": row['Unclosed'] if row else 0
        }


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_inbound_details_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return []

    query, params = QueryOptimizer.optimize_inbound_details_query(
        COL_INBOUND_NO, COL_INBOUND_STATUS, COL_INBOUND_TYPE,
        COL_INBOUND_TIME, COL_INBOUND_WAREHOUSE,
        date_start, date_end, warehouse
    )

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [{
            'Inbound Type': row['inbound_type'],
            'Total': row['Total'],
            'Inbound Qty': row['total_qty'],
            'Closed': row['closed_count'],
            'Unclosed': row['unclosed_count']
        } for row in rows]


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_outband_stats_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0}

    query, params = QueryOptimizer.optimize_outband_stats_query(
        COL_OUTBOUND_NO, COL_OUTBOUND_STATUS, COL_OUTBOUND_TIME, COL_OUTBOUND_WAREHOUSE,
        date_start, date_end, warehouse
    )

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        return {
            "Total": row['Total'] if row else 0,
            "Closed": row['Closed'] if row else 0,
            "Unclosed": row['Unclosed'] if row else 0
        }


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_outbound_details_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return []

    query, params = QueryOptimizer.optimize_outbound_details_query(
        COL_OUTBOUND_NO, COL_OUTBOUND_STATUS, COL_OUTBOUND_TYPE,
        COL_OUTBOUND_TIME, COL_OUTBOUND_WAREHOUSE,
        date_start, date_end, warehouse
    )

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [{
            'Outbound Type': row['outbound_type'],
            'Total': row['Total'],
            'Stock Qty': row['stock_qty'],
            'Closed': row['Closed'],
            'Unclosed': row['Unclosed']
        } for row in rows]


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_special_outbound_stats_from_db(outbound_type, sla_days, date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0, "SLA": 0}

    conditions = [f"`{COL_OUTBOUND_TYPE}` = ?"]
    params = [outbound_type]

    if date_start:
        conditions.append(f"`{COL_OUTBOUND_TIME}` >= ?")
        params.append(date_start + " 00:00:00")
    if date_end:
        conditions.append(f"`{COL_OUTBOUND_TIME}` <= ?")
        params.append(date_end + " 23:59:59")
    if warehouse:
        conditions.append(f"`{COL_OUTBOUND_WAREHOUSE}` = ?")
        params.append(warehouse)

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT 
            COUNT(DISTINCT `{COL_OUTBOUND_NO}`) as Total,
            COUNT(DISTINCT CASE WHEN LOWER(TRIM(`{COL_OUTBOUND_STATUS}`)) = 'closed' THEN `{COL_OUTBOUND_NO}` END) as Closed,
            COUNT(DISTINCT CASE WHEN LOWER(TRIM(`{COL_OUTBOUND_STATUS}`)) != 'closed' THEN `{COL_OUTBOUND_NO}` END) as Unclosed
        FROM outband_details
        WHERE {where_clause}
    """

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        return {
            "Total": row['Total'] if row else 0,
            "Closed": row['Closed'] if row else 0,
            "Unclosed": row['Unclosed'] if row else 0,
            "SLA": 0
        }


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_inventory_stats_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return {"Total": 0, "Consumables_QTY": 0, "SpareParts_QTY": 0}

    query, params = QueryOptimizer.optimize_inventory_stats_query(warehouse)

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        return {
            "Total": row['Total'] if row else 0,
            "Consumables_QTY": row['Consumables_QTY'] if row else 0,
            "SpareParts_QTY": row['SpareParts_QTY'] if row else 0
        }


@cache_mgr.cached_data()
@perf_monitor.timed
def load_inventory_trend_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return []

    query, params = QueryOptimizer.optimize_inventory_trend_query(date_start, date_end, warehouse)

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [{
            'update_date': row['update_date'],
            'Total': row['Total'],
            'Consumables_QTY': row['Consumables_QTY'],
            'SpareParts_QTY': row['SpareParts_QTY']
        } for row in rows]


@cache_mgr.cached_data()
@perf_monitor.timed
def load_inbound_outbound_trend_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return []

    query, params = QueryOptimizer.optimize_inbound_outbound_trend_query(
        COL_INBOUND_TIME, COL_INBOUND_WAREHOUSE,
        COL_OUTBOUND_TIME, COL_OUTBOUND_WAREHOUSE,
        date_start, date_end, warehouse
    )

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            return load_inbound_outbound_trend_fallback(date_start, date_end, warehouse)
        
        return [{
            'Unified_Date': row['Unified_Date'],
            'Inbound_Qty_Sum': row['Inbound_Qty_Sum'],
            'Outbound_Qty_Sum': row['Outbound_Qty_Sum']
        } for row in rows]


def load_inbound_outbound_trend_fallback(date_start=None, date_end=None, warehouse=None):
    """备用方案，当FULL OUTER JOIN不支持时使用"""
    with get_db_connection(DB_PATH) as conn:
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


@cache_mgr.cached_data()
@perf_monitor.timed
def get_latest_update_time_from_db():
    if not check_db_exists(DB_PATH):
        return ""

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(`update_time`) as latest_time FROM inventory_details")
        result = cursor.fetchone()
        return result['latest_time'] if result and result['latest_time'] else ""


@cache_mgr.cached_data()
@perf_monitor.timed
def load_early_warning_from_db():
    if not check_db_exists(DB_PATH):
        return []

    with get_db_connection(DB_PATH) as conn:
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
@perf_monitor.timed
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

        inbound_outbound_trend = load_inbound_outbound_trend_from_db(date_start, date_end, warehouse)
        data['Inbound & Outbound Ticket T'] = inbound_outbound_trend

        data['Early Warning Document Detail'] = load_early_warning_from_db()

        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/warehouses')
@cache_mgr.cached_query(ttl=300)
@perf_monitor.timed
def get_warehouses():
    try:
        if not check_db_exists(DB_PATH):
            return jsonify({"status": "success", "warehouses": []})

        warehouses = set()

        with get_db_connection(DB_PATH) as conn:
            cursor = conn.cursor()

            def get_table_columns(table_name):
                cursor.execute(f"PRAGMA table_info({table_name})")
                return [col[1] for col in cursor.fetchall()]

            def find_warehouse_column(columns):
                for col in columns:
                    if 'warehouse' in col.lower() or '仓库' in col:
                        return col
                return None

            inband_cols = get_table_columns('inband_details')
            inband_wh_col = find_warehouse_column(inband_cols)
            if inband_wh_col:
                cursor.execute(
                    f"SELECT DISTINCT `{inband_wh_col}` FROM inband_details WHERE `{inband_wh_col}` IS NOT NULL AND `{inband_wh_col}` != ''")
                for row in cursor.fetchall():
                    if row[inband_wh_col]:
                        warehouses.add(row[inband_wh_col])

            outband_cols = get_table_columns('outband_details')
            outband_wh_col = find_warehouse_column(outband_cols)
            if outband_wh_col:
                cursor.execute(
                    f"SELECT DISTINCT `{outband_wh_col}` FROM outband_details WHERE `{outband_wh_col}` IS NOT NULL AND `{outband_wh_col}` != ''")
                for row in cursor.fetchall():
                    if row[outband_wh_col]:
                        warehouses.add(row[outband_wh_col])

            inv_cols = get_table_columns('inventory_details')
            inv_wh_col = find_warehouse_column(inv_cols)
            if inv_wh_col:
                cursor.execute(
                    f"SELECT DISTINCT `{inv_wh_col}` FROM inventory_details WHERE `{inv_wh_col}` IS NOT NULL AND `{inv_wh_col}` != ''")
                for row in cursor.fetchall():
                    if row[inv_wh_col]:
                        warehouses.add(row[inv_wh_col])

        return jsonify({"status": "success", "warehouses": sorted(list(warehouses))})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/api/performance')
def performance_report():
    """性能报告接口"""
    try:
        perf_monitor.print_report()
        cache_stats = cache_mgr.get_stats()
        perf_summary = perf_monitor.get_summary()
        return jsonify({
            "status": "success",
            "cache": {
                "hits": cache_stats[0],
                "misses": cache_stats[1],
                "hit_rate": cache_stats[2]
            },
            "performance": perf_summary
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7038, debug=False)

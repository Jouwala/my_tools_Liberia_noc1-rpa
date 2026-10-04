import os
import sys

# --- 凭据引导（2026-10-04）：口令不写在源码里，统一走共享入口 ---
# 优先环境变量，其次「设置 → 凭据管理」页面（credential_store）。
import os as _os, sys as _sys
# 注意：判据是 credentials.py 这个**文件**，不是 shared/ 这个**目录**。
# Task/Unified_Tools/shared 也存在但里面没有 credentials.py，只判目录会
# 命中它、import 失败后被 except 吞掉 -> 静默降级为空口令（实测踩过）。
_ws = _os.path.dirname(_os.path.abspath(__file__))
_cand = None
while _ws:
    _try = _os.path.join(_ws, "Unified_Tools", "shared", "credentials.py")
    if _os.path.isfile(_try):
        _cand = _try
        break
    _p = _os.path.dirname(_ws)
    if _p == _ws:
        break
    _ws = _p
if _cand:
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_cand)))
try:
    from shared.credentials import get_credential as _get_credential
except Exception:  # 凭据库不可用时降级，不让脚本直接崩
    def _get_credential(_key, env=None, default=""):
        return (_os.environ.get(env, "") if env else "") or default

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sqlite3
from flask import Flask, render_template, jsonify, request, session, make_response
from datetime import datetime, timedelta
from functools import wraps

from shared.db_manager_optimized import get_db_connection, check_db_exists
from shared.cache_manager import get_cache_manager
from shared.query_optimizer import QueryOptimizer
from shared.performance_monitor import get_performance_monitor
from shared.dashboard_email_renderer import render_dashboard_email_html

# 动态导入 user_manager，确保能找到模块
current_dir = os.path.dirname(os.path.abspath(__file__))
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

# 初始化用户管理器
user_manager = UserManager(USERS_DB_PATH)

# 将 user_manager 附加到装饰器上，以便在装饰器中使用
login_required.user_manager = user_manager
admin_required.user_manager = user_manager

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

COL_INBOUND_TYPE = "Inbound Type"
COL_INBOUND_NO = "Inbound No."
COL_INBOUND_STATUS = "Status"
COL_INBOUND_TIME = "Inbound Time"
COL_INBOUND_WAREHOUSE = "Warehouse Name"
COL_INBOUND_QTY = "Inbound Qty"
COL_INBOUND_RETURN_QTY = "return QTY"

COL_OUTBOUND_NO = "Outbound No."
COL_OUTBOUND_STATUS = "Status"
COL_OUTBOUND_TYPE = "Outbound Type"
COL_OUTBOUND_TIME = "Outbound Time"
COL_OUTBOUND_WAREHOUSE = "Warehouse Name"
COL_OUTBOUND_QTY = "Outbound Qty"
COL_OUTBOUND_BORROW_DURATION = "Borrow Duration"


def load_column_mapping():
    mapping_data = {}
    if os.path.exists(COLUMN_MAPPING_PATH):
        try:
            import pandas as pd
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


def init_column_names():
    global COL_INBOUND_TYPE, COL_INBOUND_NO, COL_INBOUND_STATUS, COL_INBOUND_TIME, COL_INBOUND_WAREHOUSE, COL_INBOUND_QTY, COL_INBOUND_RETURN_QTY
    global COL_OUTBOUND_NO, COL_OUTBOUND_STATUS, COL_OUTBOUND_TYPE, COL_OUTBOUND_TIME, COL_OUTBOUND_WAREHOUSE, COL_OUTBOUND_QTY, COL_OUTBOUND_BORROW_DURATION
    
    if not os.path.exists(DB_PATH):
        return
    
    column_mapping = load_column_mapping()
    
    with get_db_connection(DB_PATH) as conn:
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
            COL_INBOUND_RETURN_QTY = detect_column_name(inband_cols, inband_mapping, 'return QTY')
            
            cursor.execute("PRAGMA table_info(outband_details)")
            outband_cols = [col[1] for col in cursor.fetchall()]
            outband_mapping = column_mapping.get('outband_details', {})
            
            COL_OUTBOUND_NO = detect_column_name(outband_cols, outband_mapping, 'Outbound No.')
            COL_OUTBOUND_STATUS = detect_column_name(outband_cols, outband_mapping, 'Status')
            COL_OUTBOUND_TYPE = detect_column_name(outband_cols, outband_mapping, 'Outbound Type')
            COL_OUTBOUND_TIME = detect_column_name(outband_cols, outband_mapping, 'Outbound Time')
            COL_OUTBOUND_WAREHOUSE = detect_column_name(outband_cols, outband_mapping, 'Warehouse Name')
            COL_OUTBOUND_QTY = detect_column_name(outband_cols, outband_mapping, 'Outbound Qty')
            COL_OUTBOUND_BORROW_DURATION = detect_column_name(outband_cols, outband_mapping, 'Borrow Duration')
            
            print(f"[INFO] Detected columns:")
            print(f"  Inbound: type={COL_INBOUND_TYPE}, no={COL_INBOUND_NO}, status={COL_INBOUND_STATUS}, time={COL_INBOUND_TIME}, warehouse={COL_INBOUND_WAREHOUSE}, return_qty={COL_INBOUND_RETURN_QTY}")
            print(f"  Outbound: no={COL_OUTBOUND_NO}, status={COL_OUTBOUND_STATUS}, type={COL_OUTBOUND_TYPE}, time={COL_OUTBOUND_TIME}, warehouse={COL_OUTBOUND_WAREHOUSE}")
        except Exception as e:
            print(f"[WARN] Failed to detect columns: {e}")


init_column_names()

CACHE_NAMESPACE = "Main"

cache_mgr.set_namespace(CACHE_NAMESPACE)
cache_mgr.invalidate_all()
print(f"[INFO] Cache cleared for Dashboard")


@app.before_request
def set_cache_namespace():
    cache_mgr.set_namespace(CACHE_NAMESPACE)


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_inband_stats_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return {"Total": 0, "Closed": 0, "Unclosed": 0}

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
        
        with get_db_connection(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT DISTINCT `{COL_INBOUND_NO}` FROM inband_details WHERE " + where_sql,
                params
            )
            ticket_ids = [row[COL_INBOUND_NO] for row in cursor.fetchall() if row[COL_INBOUND_NO]]
            if not ticket_ids:
                return {"Total": 0, "Closed": 0, "Unclosed": 0}
            placeholders = ",".join("?" * len(ticket_ids))
            cursor.execute(
                f"SELECT `{COL_INBOUND_NO}`, `{COL_INBOUND_STATUS}` FROM inband_details WHERE `{COL_INBOUND_NO}` IN (" + placeholders + ")",
                ticket_ids
            )
            rows = cursor.fetchall()
    else:
        with get_db_connection(DB_PATH) as conn:
            cursor = conn.cursor()
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
        
        with get_db_connection(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT DISTINCT `{COL_INBOUND_NO}` FROM inband_details WHERE " + where_sql,
                params
            )
            ticket_ids = [row[COL_INBOUND_NO] for row in cursor.fetchall() if row[COL_INBOUND_NO]]
            if not ticket_ids:
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
                f"SELECT `{COL_INBOUND_NO}`, `{COL_INBOUND_TYPE}`, `{COL_INBOUND_QTY}` FROM inband_details WHERE " + where_sql,
                params
            )
            rows = cursor.fetchall()
    else:
        with get_db_connection(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT `{COL_INBOUND_NO}`, `{COL_INBOUND_STATUS}`, `{COL_INBOUND_TYPE}`, `{COL_INBOUND_QTY}` FROM inband_details"
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
        inbound_qty = row[COL_INBOUND_QTY] or 0
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

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

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

    query = f"""
        SELECT `{COL_OUTBOUND_NO}`, `{COL_OUTBOUND_STATUS}`, `{COL_OUTBOUND_TYPE}`, `{COL_OUTBOUND_QTY}`, `{COL_OUTBOUND_TIME}`, `{COL_OUTBOUND_WAREHOUSE}`
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

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

    type_stats = {}

    for row in rows:
        outbound_type = row[COL_OUTBOUND_TYPE] or 'Unknown'
        outbound_no = row[COL_OUTBOUND_NO]
        status = row[COL_OUTBOUND_STATUS]
        stock_qty = row[COL_OUTBOUND_QTY] or 0

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

    query = f"""
        SELECT `{COL_OUTBOUND_NO}`, `{COL_OUTBOUND_STATUS}`, `{COL_OUTBOUND_TIME}`, `{COL_OUTBOUND_BORROW_DURATION}`, `{COL_OUTBOUND_WAREHOUSE}`
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

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

    outbound_nos = set()
    closed_nos = set()
    unclosed_nos = set()
    sla_nos = set()

    for row in rows:
        outbound_no = row[COL_OUTBOUND_NO]
        status = row[COL_OUTBOUND_STATUS]
        borrow_duration = row[COL_OUTBOUND_BORROW_DURATION]

        if outbound_no:
            outbound_nos.add(outbound_no)
            if status and status.lower() == 'closed':
                closed_nos.add(outbound_no)
            else:
                unclosed_nos.add(outbound_no)
                if borrow_duration and float(borrow_duration) > sla_days and outbound_no not in sla_nos:
                    sla_nos.add(outbound_no)

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
    ⚠️ 特别注意：此卡片不受顶部日期选择器的影响。
    始终只查询数据库中 update_date 为最新一天的数据，代表当前实时库存状况。
    
    统计逻辑（按 Stock Qty 总和）：
    - Total: 最新一天数据中，Stock Qty 列的总和
    - Consumables: 最新一天数据中，Material Type 为 "Consumables" 的 Stock Qty 总和
    - SpareParts: 最新一天数据中，Material Type 不是 "Consumables" 的 Stock Qty 总和
    """
    if not check_db_exists(DB_PATH):
        return {"Total": 0, "Consumables_QTY": 0, "SpareParts_QTY": 0}

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        # 首先获取最新的 update_date
        latest_date_query = "SELECT MAX(`update_date`) as latest_date FROM inventory_details WHERE `update_date` IS NOT NULL AND `update_date` != ''"
        cursor.execute(latest_date_query)
        latest_date_result = cursor.fetchone()
        latest_date = latest_date_result['latest_date'] if latest_date_result and latest_date_result['latest_date'] else None
        
        if not latest_date:
            return {"Total": 0, "Consumables_QTY": 0, "SpareParts_QTY": 0}

        query = """
            SELECT `Serial No.`, `Material Type`, `Stock Qty`, `Warehouse Name`
            FROM inventory_details
            WHERE `update_date` = ?
        """
        params = [latest_date]
        
        if warehouse:
            query += " AND `Warehouse Name` = ?"
            params.append(warehouse)

        cursor.execute(query, params)
        rows = cursor.fetchall()

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


@cache_mgr.cached_data()
@perf_monitor.timed
def load_inventory_trend_from_db(date_start=None, date_end=None, warehouse=None):
    """
    从 inventory.db 的 inventory_details 表获取 Inventory Quantity Trend 数据。
    时间从 update_date 列过滤。
    按时间统计：
    - Total: Stock Qty 列的总和
    - Consumables: Material Type 列是 "Consumables" 的 Stock Qty 总和
    - SpareParts: Material Type 列不是 "Consumables" 的 Stock Qty 总和
    """
    if not check_db_exists(DB_PATH):
        return []

    query = """
        SELECT `Serial No.`, `Material Type`, `update_date`, `Stock Qty`, `Warehouse Name`
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

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

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


@cache_mgr.cached_data()
@perf_monitor.timed
def load_inbound_outbound_trend_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return []

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        
        inbound_query = f"""
            SELECT date(`{COL_INBOUND_TIME}`) as doc_date, 
                   SUM(COALESCE(`{COL_INBOUND_QTY}`, 0) + COALESCE(`{COL_INBOUND_RETURN_QTY}`, 0)) as qty_sum
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
            SELECT date(`{COL_OUTBOUND_TIME}`) as doc_date, SUM(`{COL_OUTBOUND_QTY}`) as qty_sum
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


@cache_mgr.cached_stats()
@perf_monitor.timed
def get_inbound_outbound_date_range():
    """获取 Inbound & Outbound 的时间日期范围"""
    if not check_db_exists(DB_PATH):
        return None, None
    
    with get_db_connection(DB_PATH) as conn:
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
        
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        if max_date and today > max_date:
            max_date = today
        
        return min_date, max_date


@cache_mgr.cached_stats()
@perf_monitor.timed
def load_inbound_outbound_trend_full_range(date_start=None, date_end=None, warehouse=None):
    """
    获取 Inbound & Outbound QTY Trend 数据，填充完整日期范围
    从 Inbound Time/Outbound Time 最小值到最大值（或今天）
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


@cache_mgr.cached_data()
@perf_monitor.timed
def get_latest_update_time_from_db():
    if not check_db_exists(DB_PATH):
        return ""

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        query = "SELECT MAX(`update_time`) as latest_time FROM inventory_details"
        cursor.execute(query)
        result = cursor.fetchone()
        return result['latest_time'] if result and result['latest_time'] else ""


@cache_mgr.cached_data()
@perf_monitor.timed
def load_sla_details_from_db(date_start=None, date_end=None, warehouse=None):
    if not check_db_exists(DB_PATH):
        return []

    sla_configs = [
        {'outbound_type': 'Borrow Outbound', 'sla_days': 45},
        {'outbound_type': 'Repair Outbound', 'sla_days': 180},
        {'outbound_type': 'Inventory Lost Outbound', 'sla_days': 1},
    ]

    all_records = []
    seen_outbound_nos = set()

    with get_db_connection(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(outband_details)")
        columns_info = cursor.fetchall()
        columns = [col[1] for col in columns_info]

        for config in sla_configs:
            outbound_type = config['outbound_type']
            sla_days = config['sla_days']

            query = f"""
                SELECT * FROM outband_details
                WHERE `{COL_OUTBOUND_TYPE}` = ?
                AND (`{COL_OUTBOUND_STATUS}` IS NULL OR LOWER(`{COL_OUTBOUND_STATUS}`) != 'closed')
                AND `{COL_OUTBOUND_BORROW_DURATION}` IS NOT NULL
                AND `{COL_OUTBOUND_BORROW_DURATION}` != ''
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

            for row in rows:
                try:
                    borrow_duration = float(row[COL_OUTBOUND_BORROW_DURATION] or 0)
                except (ValueError, TypeError):
                    continue

                if borrow_duration > sla_days:
                    outbound_no = row[COL_OUTBOUND_NO]
                    if outbound_no and outbound_no not in seen_outbound_nos:
                        seen_outbound_nos.add(outbound_no)
                        record = {}
                        for col in columns:
                            val = row[col]
                            if isinstance(val, bytes):
                                val = val.decode('utf-8', errors='ignore')
                            record[col] = val if val is not None else ""
                        record['SLA_Days'] = sla_days
                        record['SLA_Type'] = outbound_type
                        all_records.append(record)

    return all_records


# ============ 路由和 API ============

@app.route('/')
def index():
    """主页路由，检查登录状态"""
    session_token = request.cookies.get('session_token')
    if session_token:
        user = user_manager.get_user_by_session(session_token)
        if user:
            # 已登录，正常显示页面
            return render_template('index.html')
    # 未登录，重定向到登录页面或显示登录提示
    return render_template('index.html', require_login=True)


@app.route('/login')
def login_page():
    """登录页面"""
    return render_template('login.html')


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

        borrow_stats = load_special_outbound_stats_from_db('Borrow Outbound', 45, date_start, date_end, warehouse)
        data['Borrow Outbound'] = [borrow_stats]

        repair_stats = load_special_outbound_stats_from_db('Repair Outbound', 180, date_start, date_end, warehouse)
        data['Repair Outbound'] = [repair_stats]

        inventory_lost_stats = load_special_outbound_stats_from_db('Inventory Lost Outbound', 1, date_start, date_end,
                                                                   warehouse)
        data['Inventory Lost Outbound'] = [inventory_lost_stats]

        inventory_stats = load_inventory_stats_from_db(date_start, date_end, warehouse)
        data['Inventory'] = [inventory_stats]

        inventory_trend = load_inventory_trend_from_db(date_start, date_end, warehouse)
        data['Inventory Quantity Trend'] = inventory_trend

        inbound_outbound_trend = load_inbound_outbound_trend_full_range(date_start, date_end, warehouse)
        data['Inbound & Outbound Ticket T'] = inbound_outbound_trend

        data['Early Warning Document Detail'] = load_sla_details_from_db(date_start, date_end, warehouse)

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

            cursor.execute(
                "SELECT DISTINCT `Warehouse Name` FROM inband_details WHERE `Warehouse Name` IS NOT NULL AND `Warehouse Name` != ''")
            for row in cursor.fetchall():
                if row['Warehouse Name']:
                    warehouses.add(row['Warehouse Name'])

            cursor.execute(
                "SELECT DISTINCT `Warehouse Name` FROM outband_details WHERE `Warehouse Name` IS NOT NULL AND `Warehouse Name` != ''")
            for row in cursor.fetchall():
                if row['Warehouse Name']:
                    warehouses.add(row['Warehouse Name'])

            cursor.execute(
                "SELECT DISTINCT `Warehouse Name` FROM inventory_details WHERE `Warehouse Name` IS NOT NULL AND `Warehouse Name` != ''")
            for row in cursor.fetchall():
                if row['Warehouse Name']:
                    warehouses.add(row['Warehouse Name'])

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


def load_detail_data(detail_type, filter_column=None, filter_value=None, filter_mode="exact",
                     first_column=None, first_value=None, date_start=None, date_end=None, warehouse=None,
                     status_column=None, status_value=None, status_mode="exact", sla_filter=False, sla_type=None):
    if not check_db_exists(DB_PATH):
        path = DETAIL_FILES.get(detail_type)
        if not path or not os.path.exists(path):
            return DETAIL_TITLES.get(detail_type, detail_type), [], []
        import pandas as pd
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

    if detail_type == "inband":
        return load_inband_detail_from_db(filter_column, filter_value, filter_mode,
                                          first_column, first_value, date_start, date_end, warehouse,
                                          status_column, status_value, status_mode)
    elif detail_type == "outband":
        return load_outband_detail_from_db(filter_column, filter_value, filter_mode,
                                           first_column, first_value, date_start, date_end, warehouse,
                                           status_column, status_value, status_mode, sla_filter, sla_type)
    elif detail_type == "inventory":
        return load_inventory_detail_from_db(filter_column, filter_value, filter_mode,
                                             first_column, first_value, date_start, date_end, warehouse)
    
    return DETAIL_TITLES.get(detail_type, detail_type), [], []


@cache_mgr.cached_data()
@perf_monitor.timed
def load_inband_detail_from_db(filter_column=None, filter_value=None, filter_mode="exact",
                               first_column=None, first_value=None, date_start=None, date_end=None, warehouse=None,
                               status_column=None, status_value=None, status_mode="exact"):
    with get_db_connection(DB_PATH) as conn:
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


@cache_mgr.cached_data()
@perf_monitor.timed
def load_outband_detail_from_db(filter_column=None, filter_value=None, filter_mode="exact",
                                first_column=None, first_value=None, date_start=None, date_end=None, warehouse=None,
                                status_column=None, status_value=None, status_mode="exact", sla_filter=False, sla_type=None):
    """
    从数据库加载 outband 详情数据，支持时间过滤和状态过滤。
    sla_filter: 是否过滤SLA超期记录
    sla_type: SLA类型 (Borrow Outbound, Repair Outbound, Inventory Lost Outbound)
    """
    if sla_filter and sla_type:
        print(f"[DEBUG] SLA filter requested: sla_type={sla_type}", flush=True)
        early_warning_data = load_sla_details_from_db(date_start, date_end, warehouse)
        print(f"[DEBUG] Early warning data: total_records={len(early_warning_data)}", flush=True)
        if early_warning_data:
            print(f"[DEBUG] Sample record SLA_Types: {[r.get('SLA_Type') for r in early_warning_data[:5]]}", flush=True)
        filtered_records = [r for r in early_warning_data if r.get('SLA_Type') == sla_type]
        print(f"[DEBUG] Filtered records for '{sla_type}': count={len(filtered_records)}", flush=True)
        if filtered_records:
            columns = list(filtered_records[0].keys())
        else:
            columns = []
        return DETAIL_TITLES.get("outband", "Outbound Details View"), columns, filtered_records
    
    with get_db_connection(DB_PATH) as conn:
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


@cache_mgr.cached_data()
@perf_monitor.timed
def load_inventory_detail_from_db(filter_column=None, filter_value=None, filter_mode="exact",
                                  first_column=None, first_value=None, date_start=None, date_end=None, warehouse=None):
    with get_db_connection(DB_PATH) as conn:
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


@app.route('/api/performance')
def performance_report():
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


@app.route('/api/email/send', methods=['POST'])
@app.route('/api/send_dashboard_email', methods=['POST'])
def send_dashboard_email():
    """发送仪表板报表邮件"""
    try:
        from shared.email_sender import create_email_sender
        
        data = request.get_json()
        dashboard_type = data.get('dashboard_type', 'sp')
        date_start = data.get('date_start')
        date_end = data.get('date_end')
        custom_subject = data.get('subject')
        to_emails = data.get('to_emails')
        
        dashboard_names = {
            "sp": "SP Warehouse Dashboard",
            "lbr": "LBR Warehouse Dashboard",
            "ug": "UG Warehouse Dashboard",
            "cg": "CG Warehouse Dashboard",
            "mmr": "MMR Warehouse Dashboard",
            "npl": "NPL Warehouse Dashboard"
        }
        
        dashboard_name = dashboard_names.get(dashboard_type, "Warehouse Dashboard")
        
        email_config = {
            "smtp_server": "smtp.126.com",
            "smtp_port": 465,
            "sender_email": os.environ.get("EMAIL_SENDER", "xin83min@126.com"),
            "sender_password": _get_credential("mail_126", env="EMAIL_PASSWORD"),
            "db_path": DB_PATH
        }
        
        sender = create_email_sender(email_config)
        
        dashboard_data = {
            'inband_stats': load_inband_stats_from_db(date_start, date_end),
            'outband_stats': load_outband_stats_from_db(date_start, date_end),
            'inventory_stats': load_inventory_stats_from_db(date_start, date_end),
            'inventory_trend': load_inventory_trend_from_db(date_start, date_end),
            'inbound_outbound_trend': load_inbound_outbound_trend_full_range(date_start, date_end),
            'generated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'date_range': f"{date_start or 'N/A'} ~ {date_end or 'N/A'}"
        }
        
        html_content = render_dashboard_email_html(dashboard_name, dashboard_data)
        
        if to_emails:
            result = sender.send_email(to_emails, custom_subject or f"{dashboard_name} Report", html_content)
        else:
            result = sender.send_dashboard_report(dashboard_type, html_content, custom_subject)
        
        if not result["success"] and "No active subscribers" in result["message"]:
            return jsonify({
                "status": "error",
                "message": "没有找到订阅用户。请先添加订阅用户或提供收件人邮箱地址。",
                "need_recipients": True
            })
        
        return jsonify({
            "status": "success" if result["success"] else "error",
            "message": result["message"],
            "sent_count": result.get("sent_count", 0),
            "recipients": result.get("recipients", [])
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
    app.run(host='0.0.0.0', port=7038, debug=False)

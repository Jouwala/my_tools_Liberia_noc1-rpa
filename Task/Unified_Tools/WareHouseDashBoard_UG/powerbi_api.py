import os
import sqlite3
import pandas as pd
from flask import Flask, jsonify, request
from datetime import datetime

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "inventory.db")

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


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_powerbi_data(date_start=None, date_end=None, warehouse=None):
    conn = get_db_connection()
    cursor = conn.cursor()

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

    where_sql = " AND ".join(conditions) if conditions else ""

    # Inbound Ticket Stats
    cursor.execute(
        f"SELECT `{COL_INBOUND_NO}`, `{COL_INBOUND_STATUS}` FROM inband_details WHERE " + where_sql,
        params
    )
    inbound_tickets = cursor.fetchall()
    inbound_total = len(inbound_tickets)
    inbound_closed = sum(1 for t in inbound_tickets if t[COL_INBOUND_STATUS] and str(t[COL_INBOUND_STATUS]).strip().lower() == 'closed')
    inbound_unclosed = inbound_total - inbound_closed

    # Outbound Ticket Stats
    cursor.execute(
        f"SELECT `{COL_OUTBOUND_NO}`, `{COL_OUTBOUND_STATUS}` FROM outband_details WHERE " + where_sql,
        params
    )
    outbound_tickets = cursor.fetchall()
    outbound_total = len(outbound_tickets)
    outbound_closed = sum(1 for t in outbound_tickets if t[COL_OUTBOUND_STATUS] and str(t[COL_OUTBOUND_STATUS]).strip().lower() == 'closed')
    outbound_unclosed = outbound_total - outbound_closed

    # Inventory Stats
    cursor.execute("SELECT `Serial No`, `Material Type`, `update_date` FROM inventory_details WHERE `update_date` IS NOT NULL")
    inventory_rows = cursor.fetchall()
    inventory_total = len(inventory_rows)
    inventory_consumables = sum(1 for r in inventory_rows if r['Material Type'] and r['Material Type'].lower() == 'consumable')
    inventory_spare_parts = inventory_total - inventory_consumables

    # Inbound Details by Type
    cursor.execute(
        f"SELECT `{COL_INBOUND_TYPE}`, COUNT(*) as qty FROM inband_details WHERE " + where_sql,
        params
    )
    inbound_by_type = {row[COL_INBOUND_TYPE]: row['qty'] for row in cursor.fetchall()}

    # Outbound Details by Type
    cursor.execute(
        f"SELECT `{COL_OUTBOUND_TYPE}`, COUNT(*) as qty FROM outband_details WHERE " + where_sql,
        params
    )
    outbound_by_type = {row[COL_OUTBOUND_TYPE]: row['qty'] for row in cursor.fetchall()}

    # Inbound & Outbound Trend
    cursor.execute(
        f"SELECT date(`{COL_INBOUND_TIME}`) as date, COUNT(*) as qty FROM inband_details WHERE `{COL_INBOUND_TIME}` IS NOT NULL AND `{COL_INBOUND_TIME}` != '' " + where_sql,
        params
    )
    inbound_trend = {row['date']: row['qty'] for row in cursor.fetchall()}

    cursor.execute(
        f"SELECT date(`{COL_OUTBOUND_TIME}`) as date, COUNT(*) as qty FROM outband_details WHERE `{COL_OUTBOUND_TIME}` IS NOT NULL AND `{COL_OUTBOUND_TIME}` != '' " + where_sql,
        params
    )
    outbound_trend = {row['date']: row['qty'] for row in cursor.fetchall()}

    # Special Outbound Types
    cursor.execute(
        f"SELECT `{COL_OUTBOUND_TYPE}`, COUNT(*) as qty FROM outband_details WHERE `{COL_OUTBOUND_TYPE}` = ? AND " + where_sql,
        ['Borrow Outbound/50202001'] + params
    )
    borrow_outbound = cursor.fetchone()['qty'] if cursor.fetchone() else 0

    cursor.execute(
        f"SELECT `{COL_OUTBOUND_TYPE}`, COUNT(*) as qty FROM outband_details WHERE `{COL_OUTBOUND_TYPE}` = ? AND " + where_sql,
        ['Repair Outbound/50202005'] + params
    )
    repair_outbound = cursor.fetchone()['qty'] if cursor.fetchone() else 0

    cursor.execute(
        f"SELECT `{COL_OUTBOUND_TYPE}`, COUNT(*) as qty FROM outband_details WHERE `{COL_OUTBOUND_TYPE}` = ? AND " + where_sql,
        ['Inventory Outbound/50202003'] + params
    )
    inventory_outbound = cursor.fetchone()['qty'] if cursor.fetchone() else 0

    conn.close()

    # Build Power BI optimized response
    result = {
        "metadata": {
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "date_range": {
                "start": date_start,
                "end": date_end,
                "warehouse": warehouse
            }
        },
        "inbound_summary": {
            "total_tickets": inbound_total,
            "closed_tickets": inbound_closed,
            "unclosed_tickets": inbound_unclosed
        },
        "outbound_summary": {
            "total_tickets": outbound_total,
            "closed_tickets": outbound_closed,
            "unclosed_tickets": outbound_unclosed
        },
        "inventory_summary": {
            "total_items": inventory_total,
            "consumables": inventory_consumables,
            "spare_parts": inventory_spare_parts
        },
        "inbound_by_type": inbound_by_type,
        "outbound_by_type": outbound_by_type,
        "inbound_trend": inbound_trend,
        "outbound_trend": outbound_trend,
        "special_outbound": {
            "borrow_outbound": borrow_outbound,
            "repair_outbound": repair_outbound,
            "inventory_outbound": inventory_outbound
        }
    }

    return jsonify({"status": "success", "data": result})


@app.route('/api/powerbi')
def get_powerbi_data():
    try:
        date_start = request.args.get('date_start')
        date_end = request.args.get('date_end')
        warehouse = request.args.get('warehouse')
        return load_powerbi_data(date_start, date_end, warehouse)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/')
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Power BI API for Warehouse Dashboard</title>
    </head>
    <body>
        <h1>Power BI API for Warehouse Dashboard</h1>
        <h2>Available Endpoints:</h2>
        <ul>
            <li><strong>GET /api/powerbi</strong> - Get Power BI optimized data</li>
            <li><strong>Parameters:</strong></li>
            <ul>
                <li>date_start (optional): Filter by start date (YYYY-MM-DD)</li>
                <li>date_end (optional): Filter by end date (YYYY-MM-DD)</li>
                <li>warehouse (optional): Filter by warehouse ID</li>
            </ul>
        </ul>
        <h2>Data Structure:</h2>
        <pre>
{
  "metadata": {
    "last_update": "2026-02-27 14:30:00",
    "date_range": { "start": "2026-01-01", "end": "2026-01-31", "warehouse": "WH001" }
  },
  "inbound_summary": {
    "total_tickets": 293,
    "closed_tickets": 289,
    "unclosed_tickets": 4
  },
  "outbound_summary": {
    "total_tickets": 670,
    "closed_tickets": 625,
    "unclosed_tickets": 45
  },
  "inventory_summary": {
    "total_items": 12845,
    "consumables": 669,
    "spare_parts": 12176
  },
  "inbound_by_type": {
    "eflow_instock": 293
  },
  "outbound_by_type": {
    "Borrow Outbound/50202001": 188,
    "Repair Outbound/50202005": 6,
    "Install Outbound/50202004": 463,
    "Inventory Outbound/50202003": 13
  },
  "inbound_trend": [
    { "date": "2026-01-01", "inbound_qty": 5 },
    { "date": "2026-01-02", "inbound_qty": 3 }
  ],
  "outbound_trend": [
    { "date": "2026-01-01", "outbound_qty": 2 }
  ],
  "special_outbound": {
    "borrow_outbound": 188,
    "repair_outbound": 6,
    "inventory_outbound": 13
  }
}
        </pre>
    </body>
    </html>
    """


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7040, debug=True)

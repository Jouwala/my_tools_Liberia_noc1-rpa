"""
import logging
SP（备件）仓库看板数据计算服务。

计算逻辑完整对齐 Unified_Tools/WareHouseDashBoard/app_sp_optimized.py 的
load_* 系列函数，数据来源为本项目的 db/app.db（由 get_sp_table.py 写入的
inband_details / outband_details / inventory_details 三张表）。

对外提供：
  - get_dashboard_data(date_start, date_end, warehouse)  -> 对齐 /api/data 的返回结构
  - get_warehouses()                                      -> 仓库下拉列表
  - get_latest_update_time()                              -> 卡片顶部更新时间
  - get_detail_rows(...)                                  -> 对齐 /api/details 的明细查询
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.database import get_raw_connection  # 复用已加固的连接（busy_timeout+WAL）

# ====== 路径配置（与 get_sp_table.py 一致：项目根 db/app.db）======
SERVICE_DIR = Path(__file__).resolve().parent          # backend/services
BACKEND_DIR = SERVICE_DIR.parent                       # backend
DB_PATH = SERVICE_DIR.parent.parent / "db" / "app.db"

# 列名探测缓存，避免每次请求重复 PRAGMA
_COLUMN_CACHE: Dict[str, List[str]] = {}


# ============ 通用工具 ============
def _get_columns(table: str) -> List[str]:
    """返回指定表的实际列名（带缓存）。表不存在时返回空列表。"""
    if table in _COLUMN_CACHE:
        return _COLUMN_CACHE[table]
    cols: List[str] = []
    try:
        with get_raw_connection() as conn:
            cur = conn.cursor()
            cur.execute(f'PRAGMA table_info("{table}")')
            cols = [r[1] for r in cur.fetchall()]
    except sqlite3.OperationalError:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _get_columns: exception swallowed", exc_info=True)
        cols = []
    _COLUMN_CACHE[table] = cols
    return cols


def detect_column_name(table: str, mapping_name: str) -> str:
    """按列名探测（对齐 app_sp_optimized.detect_column_name 的回退逻辑）：
    1) 精确匹配；2) 大小写无关的包含匹配；3) 退回原期望名。"""
    cols = _get_columns(table)
    if mapping_name in cols:
        return mapping_name
    ml = mapping_name.lower()
    for col in cols:
        cl = col.lower()
        if ml in cl or cl in ml:
            return col
    return mapping_name


def _db_exists() -> bool:
    return DB_PATH.exists()


def _connect() -> sqlite3.Connection:
    # 复用已加固的连接（busy_timeout=30000 + synchronous=NORMAL），避免 locked 错误。
    # 注意：调用方必须用 `with _connect() as conn:`，退出时会自动提交并关闭。
    return get_raw_connection()


def _cond_sql(date_start: Optional[str], date_end: Optional[str], warehouse: Optional[str],
             col_time: str, col_wh: str) -> (str, list):
    """拼装日期 + 仓库过滤条件，返回以 ` AND ` 开头的片段（不含 WHERE 关键字），
    便于在已有 WHERE 子句后直接拼接，或配合 `WHERE 1=1` 使用。"""
    parts: List[str] = []
    params: List[Any] = []
    if date_start:
        parts.append(f"`{col_time}` >= ?")
        params.append(date_start + " 00:00:00")
    if date_end:
        parts.append(f"`{col_time}` <= ?")
        params.append(date_end + " 23:59:59")
    if warehouse:
        parts.append(f"`{col_wh}` = ?")
        params.append(warehouse)
    cond = (" AND " + " AND ".join(parts)) if parts else ""
    return cond, params


# 探测列名（模块加载时即确定，对应 app_sp_optimized.init_column_names）
COL_INBOUND_NO = "Inbound No."
COL_INBOUND_STATUS = "Status"
COL_INBOUND_TYPE = "Inbound Type"
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


def _refresh_columns() -> None:
    global COL_INBOUND_NO, COL_INBOUND_STATUS, COL_INBOUND_TYPE, COL_INBOUND_TIME
    global COL_INBOUND_WAREHOUSE, COL_INBOUND_QTY, COL_INBOUND_RETURN_QTY
    global COL_OUTBOUND_NO, COL_OUTBOUND_STATUS, COL_OUTBOUND_TYPE, COL_OUTBOUND_TIME
    global COL_OUTBOUND_WAREHOUSE, COL_OUTBOUND_QTY, COL_OUTBOUND_BORROW_DURATION
    if not _db_exists():
        return
    COL_INBOUND_NO = detect_column_name("inband_details", "Inbound No.")
    COL_INBOUND_STATUS = detect_column_name("inband_details", "Status")
    COL_INBOUND_TYPE = detect_column_name("inband_details", "Inbound Type")
    COL_INBOUND_TIME = detect_column_name("inband_details", "Inbound Time")
    COL_INBOUND_WAREHOUSE = detect_column_name("inband_details", "Warehouse Name")
    COL_INBOUND_QTY = detect_column_name("inband_details", "Inbound Qty")
    COL_INBOUND_RETURN_QTY = detect_column_name("inband_details", "return QTY")
    COL_OUTBOUND_NO = detect_column_name("outband_details", "Outbound No.")
    COL_OUTBOUND_STATUS = detect_column_name("outband_details", "Status")
    COL_OUTBOUND_TYPE = detect_column_name("outband_details", "Outbound Type")
    COL_OUTBOUND_TIME = detect_column_name("outband_details", "Outbound Time")
    COL_OUTBOUND_WAREHOUSE = detect_column_name("outband_details", "Warehouse Name")
    COL_OUTBOUND_QTY = detect_column_name("outband_details", "Outbound Qty")
    COL_OUTBOUND_BORROW_DURATION = detect_column_name("outband_details", "Borrow Duration")


_refresh_columns()


# ============ 1. Inbound Ticket（按 Inbound No. 去重计算 closed/unclosed）============
def load_inband_stats(date_start=None, date_end=None, warehouse=None) -> Dict[str, int]:
    if not _db_exists():
        return {"Total": 0, "Closed": 0, "Unclosed": 0}
    with _connect() as conn:
        try:
            c = COL_INBOUND_NO
            s = COL_INBOUND_STATUS
            t = COL_INBOUND_TIME
            w = COL_INBOUND_WAREHOUSE
            if date_start or date_end or warehouse:
                where, params = _cond_sql(date_start, date_end, warehouse, t, w)
                rows = conn.execute(
                    f'SELECT DISTINCT "{c}" FROM inband_details WHERE 1=1{where}', params
                ).fetchall()
                ticket_ids = [r[c] for r in rows if r[c]]
                if not ticket_ids:
                    return {"Total": 0, "Closed": 0, "Unclosed": 0}
                ph = ",".join("?" * len(ticket_ids))
                rows = conn.execute(
                    f'SELECT "{c}", "{s}" FROM inband_details WHERE "{c}" IN ({ph})', ticket_ids
                ).fetchall()
            else:
                rows = conn.execute(f'SELECT "{c}", "{s}" FROM inband_details').fetchall()

            ticket_status: Dict[Any, bool] = {}
            for row in rows:
                inbound_no = row[c]
                status = row[s]
                if not inbound_no:
                    continue
                is_closed = bool(status and str(status).strip().lower() == "closed")
                if inbound_no not in ticket_status:
                    ticket_status[inbound_no] = False
                if not is_closed:
                    ticket_status[inbound_no] = True
            total = len(ticket_status)
            unclosed = sum(1 for v in ticket_status.values() if v)
            return {"Total": total, "Closed": total - unclosed, "Unclosed": unclosed}
        finally:
            conn.close()


def load_inbound_details(date_start=None, date_end=None, warehouse=None) -> List[Dict]:
    if not _db_exists():
        return []
    c = COL_INBOUND_NO
    s = COL_INBOUND_STATUS
    ty = COL_INBOUND_TYPE
    q = COL_INBOUND_QTY
    r = COL_INBOUND_RETURN_QTY
    t = COL_INBOUND_TIME
    w = COL_INBOUND_WAREHOUSE
    with _connect() as conn:
        try:
            if date_start or date_end or warehouse:
                where, params = _cond_sql(date_start, date_end, warehouse, t, w)
                rows = conn.execute(
                    f'SELECT DISTINCT "{c}" FROM inband_details WHERE 1=1{where}', params
                ).fetchall()
                ticket_ids = [row[c] for row in rows if row[c]]
                if not ticket_ids:
                    return []
                ph = ",".join("?" * len(ticket_ids))
                rows = conn.execute(
                    f'SELECT "{c}", "{s}" FROM inband_details WHERE "{c}" IN ({ph})', ticket_ids
                ).fetchall()
                ticket_status: Dict[Any, bool] = {}
                for row in rows:
                    inbound_no = row[c]
                    status = row[s]
                    if not inbound_no:
                        continue
                    is_closed = bool(status and str(status).strip().lower() == "closed")
                    if inbound_no not in ticket_status:
                        ticket_status[inbound_no] = False
                    if not is_closed:
                        ticket_status[inbound_no] = True
                rows2 = conn.execute(
                    f'SELECT "{c}", "{ty}", "{q}" FROM inband_details WHERE 1=1{where}', params
                ).fetchall()
            else:
                rows = conn.execute(f'SELECT "{c}", "{s}", "{ty}", "{q}" FROM inband_details').fetchall()
                ticket_status = {}
                for row in rows:
                    inbound_no = row[c]
                    status = row[s]
                    if not inbound_no:
                        continue
                    is_closed = bool(status and str(status).strip().lower() == "closed")
                    if inbound_no not in ticket_status:
                        ticket_status[inbound_no] = False
                    if not is_closed:
                        ticket_status[inbound_no] = True
                rows2 = rows

            type_stats: Dict[str, Dict[str, Any]] = {}
            for row in rows2:
                inbound_type = row[ty] or "Unknown"
                inbound_no = row[c]
                inbound_qty = row[q] or 0
                if not inbound_no:
                    continue
                if inbound_type not in type_stats:
                    type_stats[inbound_type] = {
                        "inbound_nos": set(), "closed_nos": set(),
                        "unclosed_nos": set(), "total_qty": 0,
                    }
                type_stats[inbound_type]["inbound_nos"].add(inbound_no)
                try:
                    type_stats[inbound_type]["total_qty"] += int(inbound_qty) if inbound_qty else 0
                except (ValueError, TypeError):
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] load_inbound_details: exception swallowed", exc_info=True)
                    pass
                if ticket_status.get(inbound_no, False):
                    type_stats[inbound_type]["unclosed_nos"].add(inbound_no)
                else:
                    type_stats[inbound_type]["closed_nos"].add(inbound_no)

            result = []
            for inbound_type, st in type_stats.items():
                result.append({
                    "Inbound Type": inbound_type,
                    "Total": len(st["inbound_nos"]),
                    "Inbound Qty": st["total_qty"],
                    "Closed": len(st["closed_nos"]),
                    "Unclosed": len(st["unclosed_nos"]),
                })
            return result
        finally:
            conn.close()


# ============ 2. Outbound Ticket ============
def load_outband_stats(date_start=None, date_end=None, warehouse=None) -> Dict[str, int]:
    if not _db_exists():
        return {"Total": 0, "Closed": 0, "Unclosed": 0}
    c = COL_OUTBOUND_NO
    s = COL_OUTBOUND_STATUS
    t = COL_OUTBOUND_TIME
    w = COL_OUTBOUND_WAREHOUSE
    with _connect() as conn:
        try:
            where, params = _cond_sql(date_start, date_end, warehouse, t, w)
            rows = conn.execute(
                f'SELECT "{c}", "{s}" FROM outband_details WHERE 1=1{where}', params
            ).fetchall()
            outbound_nos, closed_nos, unclosed_nos = set(), set(), set()
            for row in rows:
                outbound_no = row[c]
                status = row[s]
                if outbound_no:
                    outbound_nos.add(outbound_no)
                    if status and str(status).strip().lower() == "closed":
                        closed_nos.add(outbound_no)
                    else:
                        unclosed_nos.add(outbound_no)
            return {"Total": len(outbound_nos), "Closed": len(closed_nos), "Unclosed": len(unclosed_nos)}
        finally:
            conn.close()


def load_outbound_details(date_start=None, date_end=None, warehouse=None) -> List[Dict]:
    if not _db_exists():
        return []
    c = COL_OUTBOUND_NO
    s = COL_OUTBOUND_STATUS
    ty = COL_OUTBOUND_TYPE
    q = COL_OUTBOUND_QTY
    t = COL_OUTBOUND_TIME
    w = COL_OUTBOUND_WAREHOUSE
    with _connect() as conn:
        try:
            where, params = _cond_sql(date_start, date_end, warehouse, t, w)
            rows = conn.execute(
                f'SELECT "{c}", "{s}", "{ty}", "{q}" FROM outband_details WHERE 1=1{where}', params
            ).fetchall()
            type_stats: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                outbound_type = row[ty] or "Unknown"
                outbound_no = row[c]
                status = row[s]
                stock_qty = row[q] or 0
                if outbound_type not in type_stats:
                    type_stats[outbound_type] = {
                        "outbound_nos": set(), "closed_nos": set(),
                        "unclosed_nos": set(), "total_qty": 0,
                    }
                if outbound_no:
                    type_stats[outbound_type]["outbound_nos"].add(outbound_no)
                    try:
                        type_stats[outbound_type]["total_qty"] += int(stock_qty) if stock_qty else 0
                    except (ValueError, TypeError):
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] load_outbound_details: exception swallowed", exc_info=True)
                        pass
                    if status and str(status).strip().lower() == "closed":
                        type_stats[outbound_type]["closed_nos"].add(outbound_no)
                    else:
                        type_stats[outbound_type]["unclosed_nos"].add(outbound_no)
            result = []
            for outbound_type, st in type_stats.items():
                result.append({
                    "Outbound Type": outbound_type,
                    "Total": len(st["outbound_nos"]),
                    "Stock Qty": st["total_qty"],
                    "Closed": len(st["closed_nos"]),
                    "Unclosed": len(st["unclosed_nos"]),
                })
            return result
        finally:
            conn.close()


# ============ 3. Special Outbound（Borrow / Repair / Inventory Lost）============
def load_special_outbound(outbound_type: str, sla_days: int,
                           date_start=None, date_end=None, warehouse=None) -> Dict[str, int]:
    if not _db_exists():
        return {"Total": 0, "Closed": 0, "Unclosed": 0, "SLA": 0}
    c = COL_OUTBOUND_NO
    s = COL_OUTBOUND_STATUS
    ty = COL_OUTBOUND_TYPE
    t = COL_OUTBOUND_TIME
    w = COL_OUTBOUND_WAREHOUSE
    bd = COL_OUTBOUND_BORROW_DURATION
    with _connect() as conn:
        try:
            where, params = _cond_sql(date_start, date_end, warehouse, t, w)
            query = f'SELECT "{c}", "{s}", "{bd}" FROM outband_details WHERE "{ty}" = ?{where}'
            params = [outbound_type] + params
            rows = conn.execute(query, params).fetchall()
            outbound_nos, closed_nos, unclosed_nos, sla_nos = set(), set(), set(), set()
            for row in rows:
                outbound_no = row[c]
                status = row[s]
                borrow_duration = row[bd]
                if outbound_no:
                    outbound_nos.add(outbound_no)
                    if status and str(status).strip().lower() == "closed":
                        closed_nos.add(outbound_no)
                    else:
                        unclosed_nos.add(outbound_no)
                        try:
                            if borrow_duration and float(borrow_duration) > sla_days:
                                sla_nos.add(outbound_no)
                        except (ValueError, TypeError):
                            logging.getLogger(__name__).warning("[SILENT-EXCEPT] load_special_outbound: exception swallowed", exc_info=True)
                            pass
            return {
                "Total": len(outbound_nos), "Closed": len(closed_nos),
                "Unclosed": len(unclosed_nos), "SLA": len(sla_nos),
            }
        finally:
            conn.close()


# ============ 4. Inventory（仅最新 update_date 的快照）============
def load_inventory_stats(date_start=None, date_end=None, warehouse=None) -> Dict[str, int]:
    if not _db_exists():
        return {"Total": 0, "Consumables_QTY": 0, "SpareParts_QTY": 0}
    with _connect() as conn:
        try:
            cur = conn.cursor()
            latest = cur.execute(
                'SELECT MAX("update_date") AS d FROM inventory_details '
                'WHERE "update_date" IS NOT NULL AND "update_date" != \'\''
            ).fetchone()
            latest_date = latest["d"] if latest and latest["d"] else None
            if not latest_date:
                return {"Total": 0, "Consumables_QTY": 0, "SpareParts_QTY": 0}

            q = 'SELECT "Serial No.", "Material Type", "Stock Qty", "Warehouse Name" FROM inventory_details WHERE "update_date" = ?'
            params: List[Any] = [latest_date]
            if warehouse:
                q += ' AND "Warehouse Name" = ?'
                params.append(warehouse)
            # 注：date_start/date_end 对 Inventory 卡片不生效（始终取最新快照）
            rows = cur.execute(q, params).fetchall()

            total_qty = consumables_qty = spare_parts_qty = 0
            for row in rows:
                material_type = row["Material Type"]
                stock_qty = row["Stock Qty"] or 0
                try:
                    qty = int(stock_qty) if stock_qty else 0
                except (ValueError, TypeError):
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] load_inventory_stats: exception swallowed", exc_info=True)
                    qty = 0
                total_qty += qty
                if material_type and str(material_type).strip().lower() == "consumables":
                    consumables_qty += qty
                else:
                    spare_parts_qty += qty
            return {"Total": total_qty, "Consumables_QTY": consumables_qty, "SpareParts_QTY": spare_parts_qty}
        finally:
            conn.close()


def load_inventory_trend(date_start=None, date_end=None, warehouse=None) -> List[Dict]:
    if not _db_exists():
        return []
    with _connect() as conn:
        try:
            q = 'SELECT "Serial No.", "Material Type", "update_date", "Stock Qty", "Warehouse Name" FROM inventory_details'
            params: List[Any] = []
            conditions: List[str] = []
            if date_start:
                conditions.append('"update_date" >= ?')
                params.append(date_start)
            if date_end:
                conditions.append('"update_date" <= ?')
                params.append(date_end)
            if warehouse:
                conditions.append('"Warehouse Name" = ?')
                params.append(warehouse)
            if conditions:
                q += " WHERE " + " AND ".join(conditions)
            rows = conn.execute(q, params).fetchall()
            date_stats: Dict[str, Dict[str, int]] = {}
            for row in rows:
                update_date = row["update_date"]
                if not update_date:
                    continue
                material_type = row["Material Type"]
                stock_qty = row["Stock Qty"] or 0
                try:
                    qty = int(stock_qty) if stock_qty else 0
                except (ValueError, TypeError):
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] load_inventory_trend: exception swallowed", exc_info=True)
                    qty = 0
                if update_date not in date_stats:
                    date_stats[update_date] = {"total_qty": 0, "consumables_qty": 0, "spare_parts_qty": 0}
                date_stats[update_date]["total_qty"] += qty
                if material_type and str(material_type).strip().lower() == "consumables":
                    date_stats[update_date]["consumables_qty"] += qty
                else:
                    date_stats[update_date]["spare_parts_qty"] += qty
            return [
                {"update_date": d, "Total": date_stats[d]["total_qty"],
                 "Consumables_QTY": date_stats[d]["consumables_qty"], "SpareParts_QTY": date_stats[d]["spare_parts_qty"]}
                for d in sorted(date_stats.keys())
            ]
        finally:
            conn.close()


# ============ 5. Inbound & Outbound QTY Trend（补全完整日期区间）============
def _inbound_outbound_date_range() -> (Optional[str], Optional[str]):
    if not _db_exists():
        return None, None
    with _connect() as conn:
        try:
            cur = conn.cursor()
            min_date = max_date = None
            cur.execute(
                f'SELECT MIN(date("{COL_INBOUND_TIME}")) AS mn, MAX(date("{COL_INBOUND_TIME}")) AS mx '
                f'FROM inband_details WHERE "{COL_INBOUND_TIME}" IS NOT NULL AND "{COL_INBOUND_TIME}" != \'\''
            )
            row = cur.fetchone()
            if row:
                if row["mn"] and (min_date is None or row["mn"] < min_date):
                    min_date = row["mn"]
                if row["mx"] and (max_date is None or row["mx"] > max_date):
                    max_date = row["mx"]
            cur.execute(
                f'SELECT MIN(date("{COL_OUTBOUND_TIME}")) AS mn, MAX(date("{COL_OUTBOUND_TIME}")) AS mx '
                f'FROM outband_details WHERE "{COL_OUTBOUND_TIME}" IS NOT NULL AND "{COL_OUTBOUND_TIME}" != \'\''
            )
            row = cur.fetchone()
            if row:
                if row["mn"] and (min_date is None or row["mn"] < min_date):
                    min_date = row["mn"]
                if row["mx"] and (max_date is None or row["mx"] > max_date):
                    max_date = row["mx"]
            today = datetime.now().strftime("%Y-%m-%d")
            if max_date and today > max_date:
                max_date = today
            return min_date, max_date
        finally:
            conn.close()


def load_inbound_outbound_trend_full_range(date_start=None, date_end=None, warehouse=None) -> List[Dict]:
    if not _db_exists():
        return []
    with _connect() as conn:
        try:
            cur = conn.cursor()
            # Inbound
            iq = (f'SELECT date("{COL_INBOUND_TIME}") AS doc_date, '
                  f'SUM(COALESCE("{COL_INBOUND_QTY}",0) + COALESCE("{COL_INBOUND_RETURN_QTY}",0)) AS qty_sum '
                  f'FROM inband_details WHERE "{COL_INBOUND_TIME}" IS NOT NULL AND "{COL_INBOUND_TIME}" != \'\'')
            ip: List[Any] = []
            if date_start:
                iq += f' AND "{COL_INBOUND_TIME}" >= ?'
                ip.append(date_start + " 00:00:00")
            if date_end:
                iq += f' AND "{COL_INBOUND_TIME}" <= ?'
                ip.append(date_end + " 23:59:59")
            if warehouse:
                iq += f' AND "{COL_INBOUND_WAREHOUSE}" = ?'
                ip.append(warehouse)
            iq += f' GROUP BY date("{COL_INBOUND_TIME}")'
            in_rows = cur.execute(iq, ip).fetchall()

            oq = (f'SELECT date("{COL_OUTBOUND_TIME}") AS doc_date, SUM("{COL_OUTBOUND_QTY}") AS qty_sum '
                  f'FROM outband_details WHERE "{COL_OUTBOUND_TIME}" IS NOT NULL AND "{COL_OUTBOUND_TIME}" != \'\'')
            op: List[Any] = []
            if date_start:
                oq += f' AND "{COL_OUTBOUND_TIME}" >= ?'
                op.append(date_start + " 00:00:00")
            if date_end:
                oq += f' AND "{COL_OUTBOUND_TIME}" <= ?'
                op.append(date_end + " 23:59:59")
            if warehouse:
                oq += f' AND "{COL_OUTBOUND_WAREHOUSE}" = ?'
                op.append(warehouse)
            oq += f' GROUP BY date("{COL_OUTBOUND_TIME}")'
            out_rows = cur.execute(oq, op).fetchall()

            date_stats: Dict[str, Dict[str, int]] = {}
            for row in in_rows:
                d = row["doc_date"]
                if d:
                    date_stats.setdefault(d, {"inbound_qty": 0, "outbound_qty": 0})
                    date_stats[d]["inbound_qty"] += int(row["qty_sum"] or 0)
            for row in out_rows:
                d = row["doc_date"]
                if d:
                    date_stats.setdefault(d, {"inbound_qty": 0, "outbound_qty": 0})
                    date_stats[d]["outbound_qty"] += int(row["qty_sum"] or 0)

            min_db, max_db = _inbound_outbound_date_range()
            if not min_db:
                return []
            if not date_start:
                date_start = min_db
            if not date_end:
                date_end = max_db or datetime.now().strftime("%Y-%m-%d")

            start_dt = datetime.strptime(date_start, "%Y-%m-%d")
            end_dt = datetime.strptime(date_end, "%Y-%m-%d")
            result = []
            cur_dt = start_dt
            while cur_dt <= end_dt:
                d = cur_dt.strftime("%Y-%m-%d")
                st = date_stats.get(d, {"inbound_qty": 0, "outbound_qty": 0})
                result.append({
                    "Unified_Date": d,
                    "Inbound_Qty_Sum": st["inbound_qty"],
                    "Outbound_Qty_Sum": st["outbound_qty"],
                })
                cur_dt += timedelta(days=1)
            return result
        finally:
            conn.close()


# ============ 6. 最新更新时间 ============
def get_latest_update_time() -> str:
    if not _db_exists():
        return ""
    with _connect() as conn:
        try:
            row = conn.execute('SELECT MAX("update_time") AS t FROM inventory_details').fetchone()
            return row["t"] if row and row["t"] else ""
        finally:
            conn.close()


# ============ 7. Early Warning（SLA 超期明细）===============
def load_sla_details(date_start=None, date_end=None, warehouse=None) -> List[Dict]:
    if not _db_exists():
        return []
    sla_configs = [
        {"outbound_type": "Borrow Outbound", "sla_days": 45},
        {"outbound_type": "Repair Outbound", "sla_days": 180},
        {"outbound_type": "Inventory Lost Outbound", "sla_days": 1},
    ]
    c = COL_OUTBOUND_NO
    s = COL_OUTBOUND_STATUS
    ty = COL_OUTBOUND_TYPE
    t = COL_OUTBOUND_TIME
    w = COL_OUTBOUND_WAREHOUSE
    bd = COL_OUTBOUND_BORROW_DURATION
    with _connect() as conn:
        try:
            cur = conn.cursor()
            cur.execute(f'PRAGMA table_info(outband_details)')
            columns = [r[1] for r in cur.fetchall()]
            all_records = []
            seen = set()
            for cfg in sla_configs:
                ot = cfg["outbound_type"]
                sla_days = cfg["sla_days"]
                where, params = _cond_sql(date_start, date_end, warehouse, t, w)
                query = (f'SELECT * FROM outband_details WHERE "{ty}" = ? '
                         f'AND ("{s}" IS NULL OR LOWER("{s}") != \'closed\') '
                         f'AND "{bd}" IS NOT NULL AND "{bd}" != \'\'{where}')
                params = [ot] + params
                rows = cur.execute(query, params).fetchall()
                for row in rows:
                    try:
                        borrow_duration = float(row[bd] or 0)
                    except (ValueError, TypeError):
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] load_sla_details: exception swallowed", exc_info=True)
                        continue
                    if borrow_duration > sla_days:
                        outbound_no = row[c]
                        if outbound_no and outbound_no not in seen:
                            seen.add(outbound_no)
                            record = {}
                            for col in columns:
                                val = row[col]
                                if isinstance(val, bytes):
                                    val = val.decode("utf-8", errors="ignore")
                                record[col] = val if val is not None else ""
                            record["SLA_Days"] = sla_days
                            record["SLA_Type"] = ot
                            all_records.append(record)
            return all_records
        finally:
            conn.close()


# ============ 8. 汇总 ============
def get_dashboard_data(date_start=None, date_end=None, warehouse=None) -> Dict:
    return {
        "Time": [{"update_time": get_latest_update_time()}],
        "Inbound Ticket": [load_inband_stats(date_start, date_end, warehouse)],
        "Inbound": load_inbound_details(date_start, date_end, warehouse),
        "Outbound Ticket": [load_outband_stats(date_start, date_end, warehouse)],
        "Outbound": load_outbound_details(date_start, date_end, warehouse),
        "Borrow Outbound": [load_special_outbound("Borrow Outbound", 45, date_start, date_end, warehouse)],
        "Repair Outbound": [load_special_outbound("Repair Outbound", 180, date_start, date_end, warehouse)],
        "Inventory Lost Outbound": [load_special_outbound("Inventory Lost Outbound", 1, date_start, date_end, warehouse)],
        "Inventory": [load_inventory_stats(date_start, date_end, warehouse)],
        "Inventory Quantity Trend": load_inventory_trend(date_start, date_end, warehouse),
        "Inbound & Outbound Ticket T": load_inbound_outbound_trend_full_range(date_start, date_end, warehouse),
        "Early Warning Document Detail": load_sla_details(date_start, date_end, warehouse),
    }


def get_warehouses() -> List[str]:
    if not _db_exists():
        return []
    with _connect() as conn:
        try:
            cur = conn.cursor()
            whs = set()
            for table in ("inband_details", "outband_details", "inventory_details"):
                col = detect_column_name(table, "Warehouse Name")
                try:
                    rows = cur.execute(
                        f'SELECT DISTINCT "{col}" FROM {table} WHERE "{col}" IS NOT NULL AND "{col}" != \'\''
                    ).fetchall()
                    for row in rows:
                        if row[0]:
                            whs.add(row[0])
                except sqlite3.OperationalError:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_warehouses: exception swallowed", exc_info=True)
                    continue
            return sorted(whs)
        finally:
            conn.close()


# ============ 9. 明细查询（对齐 /api/details）===============
def get_detail_rows(
    detail_type: str,
    filter_column: Optional[str] = None,
    filter_value: Optional[str] = None,
    filter_mode: str = "exact",
    first_column: Optional[str] = None,
    first_value: Optional[str] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    warehouse: Optional[str] = None,
    status_column: Optional[str] = None,
    status_value: Optional[str] = None,
    status_mode: str = "exact",
    sla_filter: bool = False,
    sla_type: Optional[str] = None,
) -> Dict:
    if detail_type == "inband":
        return _load_inband_detail(filter_column, filter_value, filter_mode,
                                   first_column, first_value, date_start, date_end, warehouse,
                                   status_column, status_value, status_mode)
    if detail_type == "outband":
        if sla_filter and sla_type:
            return _load_outband_sla_detail(sla_type)
        return _load_outband_detail(filter_column, filter_value, filter_mode,
                                    first_column, first_value, date_start, date_end, warehouse,
                                    status_column, status_value, status_mode)
    if detail_type == "inventory":
        return _load_inventory_detail(filter_column, filter_value, filter_mode,
                                      first_column, first_value, date_start, date_end, warehouse)
    return {"title": detail_type, "columns": [], "data": []}


def _col_filter_clause(col: str, value: str, mode: str) -> (str, str):
    v = str(value).strip()
    if mode == "contains":
        return f' AND LOWER("{col}") LIKE ?', f"%{v.lower()}%"
    if mode == "not_contains":
        return f' AND LOWER("{col}") NOT LIKE ?', f"%{v.lower()}%"
    return f' AND "{col}" = ?', v


def _load_inband_detail(filter_column=None, filter_value=None, filter_mode="exact",
                        first_column=None, first_value=None, date_start=None, date_end=None,
                        warehouse=None, status_column=None, status_value=None, status_mode="exact"):
    if not _db_exists():
        return {"title": "Inband Details View", "columns": [], "data": []}
    with _connect() as conn:
        try:
            cur = conn.cursor()
            cur.execute('PRAGMA table_info(inband_details)')
            columns = [r[1] for r in cur.fetchall()]
            q = 'SELECT * FROM inband_details WHERE 1=1'
            params: List[Any] = []
            c_time = COL_INBOUND_TIME
            c_wh = COL_INBOUND_WAREHOUSE
            where, wp = _cond_sql(date_start, date_end, warehouse, c_time, c_wh)
            q += where
            params += wp
            if first_column and first_value:
                q += f' AND "{first_column}" = ?'
                params.append(first_value)
            if filter_column and filter_value:
                clause, val = _col_filter_clause(filter_column, filter_value, filter_mode)
                q += clause
                params.append(val)
            if status_column and status_value:
                clause, val = _col_filter_clause(status_column, status_value, status_mode)
                q += clause
                params.append(val)
            rows = cur.execute(q, params).fetchall()
            data = []
            for row in rows:
                rec = {}
                for col in columns:
                    val = row[col]
                    if isinstance(val, bytes):
                        val = val.decode("utf-8", errors="ignore")
                    rec[col] = val if val is not None else ""
                data.append(rec)
            return {"title": "Inband Details View", "columns": columns, "data": data}
        finally:
            conn.close()


def _load_outband_detail(filter_column=None, filter_value=None, filter_mode="exact",
                         first_column=None, first_value=None, date_start=None, date_end=None,
                         warehouse=None, status_column=None, status_value=None, status_mode="exact"):
    if not _db_exists():
        return {"title": "Outbound Details View", "columns": [], "data": []}
    with _connect() as conn:
        try:
            cur = conn.cursor()
            cur.execute('PRAGMA table_info(outband_details)')
            columns = [r[1] for r in cur.fetchall()]
            q = 'SELECT * FROM outband_details WHERE 1=1'
            params: List[Any] = []
            c_time = COL_OUTBOUND_TIME
            c_wh = COL_OUTBOUND_WAREHOUSE
            where, wp = _cond_sql(date_start, date_end, warehouse, c_time, c_wh)
            q += where
            params += wp
            if first_column and first_value:
                q += f' AND "{first_column}" = ?'
                params.append(first_value)
            if filter_column and filter_value:
                clause, val = _col_filter_clause(filter_column, filter_value, filter_mode)
                q += clause
                params.append(val)
            if status_column and status_value:
                clause, val = _col_filter_clause(status_column, status_value, status_mode)
                q += clause
                params.append(val)
            rows = cur.execute(q, params).fetchall()
            data = []
            for row in rows:
                rec = {}
                for col in columns:
                    val = row[col]
                    if isinstance(val, bytes):
                        val = val.decode("utf-8", errors="ignore")
                    rec[col] = val if val is not None else ""
                data.append(rec)
            return {"title": "Outbound Details View", "columns": columns, "data": data}
        finally:
            conn.close()


def _load_outband_sla_detail(sla_type: str) -> Dict:
    records = load_sla_details()
    if records:
        columns = list(records[0].keys())
    else:
        columns = []
    return {"title": "Outbound Details View", "columns": columns, "data": records}


def _load_inventory_detail(filter_column=None, filter_value=None, filter_mode="exact",
                           first_column=None, first_value=None, date_start=None, date_end=None,
                           warehouse=None):
    if not _db_exists():
        return {"title": "Inventory Details View", "columns": [], "data": []}
    with _connect() as conn:
        try:
            cur = conn.cursor()
            cur.execute('PRAGMA table_info(inventory_details)')
            columns = [r[1] for r in cur.fetchall()]
            q = 'SELECT * FROM inventory_details WHERE 1=1'
            params: List[Any] = []
            if date_start:
                q += ' AND "update_date" >= ?'
                params.append(date_start)
            if date_end:
                q += ' AND "update_date" <= ?'
                params.append(date_end)
            if warehouse:
                q += ' AND "Warehouse Name" = ?'
                params.append(warehouse)
            if first_column and first_value:
                q += f' AND "{first_column}" = ?'
                params.append(first_value)
            if filter_column and filter_value:
                clause, val = _col_filter_clause(filter_column, filter_value, filter_mode)
                q += clause
                params.append(val)
            rows = cur.execute(q, params).fetchall()
            data = []
            for row in rows:
                rec = {}
                for col in columns:
                    val = row[col]
                    if isinstance(val, bytes):
                        val = val.decode("utf-8", errors="ignore")
                    rec[col] = val if val is not None else ""
                data.append(rec)
            return {"title": "Inventory Details View", "columns": columns, "data": data}
        finally:
            conn.close()
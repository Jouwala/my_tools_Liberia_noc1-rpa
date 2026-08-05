

"""
SQL查询优化器
- 优化聚合查询
- 减少数据传输
- 批量操作优化
"""

import sqlite3
try:
    from .logger import get_logger
except ImportError:
    from logger import get_logger

logger = get_logger('query_optimizer')


class QueryOptimizer:
    """
    SQL查询优化器
    将Python端的聚合计算迁移到SQL端
    """

    @staticmethod
    def optimize_inband_stats_query(
        col_no,
        col_status,
        col_time,
        col_warehouse,
        date_start=None,
        date_end=None,
        warehouse=None
    ):
        """
        优化入库统计查询，使用SQL聚合替代Python计算
        """
        conditions = []
        params = []

        if date_start:
            conditions.append(f"`{col_time}` >= ?")
            params.append(date_start + " 00:00:00")
        if date_end:
            conditions.append(f"`{col_time}` <= ?")
            params.append(date_end + " 23:59:59")
        if warehouse:
            conditions.append(f"`{col_warehouse}` = ?")
            params.append(warehouse)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            WITH ticket_status AS (
                SELECT 
                    `{col_no}`,
                    MAX(CASE WHEN LOWER(TRIM(`{col_status}`)) = 'closed' THEN 0 ELSE 1 END) as has_unclosed
                FROM inband_details
                WHERE {where_clause}
                GROUP BY `{col_no}`
            )
            SELECT 
                COUNT(*) as Total,
                SUM(CASE WHEN has_unclosed = 0 THEN 1 ELSE 0 END) as Closed,
                SUM(CASE WHEN has_unclosed = 1 THEN 1 ELSE 0 END) as Unclosed
            FROM ticket_status
        """
        return query, params

    @staticmethod
    def optimize_inbound_details_query(
        col_no,
        col_status,
        col_type,
        col_time,
        col_warehouse,
        date_start=None,
        date_end=None,
        warehouse=None
    ):
        """
        优化入库详情查询
        """
        conditions = []
        params = []

        if date_start:
            conditions.append(f"`{col_time}` >= ?")
            params.append(date_start + " 00:00:00")
        if date_end:
            conditions.append(f"`{col_time}` <= ?")
            params.append(date_end + " 23:59:59")
        if warehouse:
            conditions.append(f"`{col_warehouse}` = ?")
            params.append(warehouse)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            WITH ticket_status AS (
                SELECT 
                    `{col_no}`,
                    MAX(CASE WHEN LOWER(TRIM(`{col_status}`)) = 'closed' THEN 0 ELSE 1 END) as has_unclosed
                FROM inband_details
                WHERE {where_clause}
                GROUP BY `{col_no}`
            )
            SELECT 
                COALESCE(`{col_type}`, 'Unknown') as inbound_type,
                COUNT(DISTINCT d.`{col_no}`) as Total,
                COUNT(*) as total_qty,
                SUM(CASE WHEN t.has_unclosed = 0 THEN 1 ELSE 0 END) as closed_count,
                SUM(CASE WHEN t.has_unclosed = 1 THEN 1 ELSE 0 END) as unclosed_count
            FROM inband_details d
            JOIN ticket_status t ON d.`{col_no}` = t.`{col_no}`
            WHERE {where_clause}
            GROUP BY inbound_type
        """
        return query, params

    @staticmethod
    def optimize_outband_stats_query(
        col_no,
        col_status,
        col_time,
        col_warehouse,
        date_start=None,
        date_end=None,
        warehouse=None
    ):
        """
        优化出库统计查询
        """
        conditions = []
        params = []

        if date_start:
            conditions.append(f"`{col_time}` >= ?")
            params.append(date_start + " 00:00:00")
        if date_end:
            conditions.append(f"`{col_time}` <= ?")
            params.append(date_end + " 23:59:59")
        if warehouse:
            conditions.append(f"`{col_warehouse}` = ?")
            params.append(warehouse)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT 
                COUNT(DISTINCT `{col_no}`) as Total,
                COUNT(DISTINCT CASE WHEN LOWER(TRIM(`{col_status}`)) = 'closed' THEN `{col_no}` END) as Closed,
                COUNT(DISTINCT CASE WHEN LOWER(TRIM(`{col_status}`)) != 'closed' THEN `{col_no}` END) as Unclosed
            FROM outband_details
            WHERE {where_clause}
        """
        return query, params

    @staticmethod
    def optimize_outbound_details_query(
        col_no,
        col_status,
        col_type,
        col_time,
        col_warehouse,
        date_start=None,
        date_end=None,
        warehouse=None
    ):
        """
        优化出库详情查询
        """
        conditions = []
        params = []

        if date_start:
            conditions.append(f"`{col_time}` >= ?")
            params.append(date_start + " 00:00:00")
        if date_end:
            conditions.append(f"`{col_time}` <= ?")
            params.append(date_end + " 23:59:59")
        if warehouse:
            conditions.append(f"`{col_warehouse}` = ?")
            params.append(warehouse)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT 
                COALESCE(`{col_type}`, 'Unknown') as outbound_type,
                COUNT(DISTINCT `{col_no}`) as Total,
                COUNT(*) as stock_qty,
                COUNT(DISTINCT CASE WHEN LOWER(TRIM(`{col_status}`)) = 'closed' THEN `{col_no}` END) as Closed,
                COUNT(DISTINCT CASE WHEN LOWER(TRIM(`{col_status}`)) != 'closed' THEN `{col_no}` END) as Unclosed
            FROM outband_details
            WHERE {where_clause}
            GROUP BY outbound_type
        """
        return query, params

    @staticmethod
    def optimize_inventory_stats_query(
        warehouse=None
    ):
        """
        优化库存统计查询
        """
        conditions = ["`update_date` = (SELECT MAX(`update_date`) FROM inventory_details)"]
        params = []

        if warehouse:
            conditions.append("`Warehouse Name` = ?")
            params.append(warehouse)

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT 
                COUNT(DISTINCT `Serial No`) as Total,
                SUM(CASE WHEN LOWER(`Material Type`) = 'consumable' THEN 1 ELSE 0 END) as Consumables_QTY,
                SUM(CASE WHEN LOWER(`Material Type`) != 'consumable' THEN 1 ELSE 0 END) as SpareParts_QTY
            FROM inventory_details
            WHERE {where_clause}
        """
        return query, params

    @staticmethod
    def optimize_inventory_trend_query(
        date_start=None,
        date_end=None,
        warehouse=None
    ):
        """
        优化库存趋势查询
        """
        conditions = []
        params = []

        if date_start:
            conditions.append("`update_date` >= ?")
            params.append(date_start)
        if date_end:
            conditions.append("`update_date` <= ?")
            params.append(date_end)
        if warehouse:
            conditions.append("`Warehouse Name` = ?")
            params.append(warehouse)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT 
                `update_date`,
                COUNT(DISTINCT `Serial No`) as Total,
                SUM(CASE WHEN LOWER(`Material Type`) = 'consumable' THEN 1 ELSE 0 END) as Consumables_QTY,
                SUM(CASE WHEN LOWER(`Material Type`) != 'consumable' THEN 1 ELSE 0 END) as SpareParts_QTY
            FROM inventory_details
            WHERE {where_clause}
            GROUP BY `update_date`
            ORDER BY `update_date`
        """
        return query, params

    @staticmethod
    def optimize_inbound_outbound_trend_query(
        col_inbound_time,
        col_inbound_warehouse,
        col_outbound_time,
        col_outbound_warehouse,
        date_start=None,
        date_end=None,
        warehouse=None
    ):
        """
        优化入库出库趋势查询
        """
        inbound_conditions = [f"`{col_inbound_time}` IS NOT NULL AND `{col_inbound_time}` != ''"]
        outbound_conditions = [f"`{col_outbound_time}` IS NOT NULL AND `{col_outbound_time}` != ''"]
        params = []

        if date_start:
            inbound_conditions.append(f"`{col_inbound_time}` >= ?")
            outbound_conditions.append(f"`{col_outbound_time}` >= ?")
            params.extend([date_start + " 00:00:00", date_start + " 00:00:00"])
        if date_end:
            inbound_conditions.append(f"`{col_inbound_time}` <= ?")
            outbound_conditions.append(f"`{col_outbound_time}` <= ?")
            params.extend([date_end + " 23:59:59", date_end + " 23:59:59"])
        if warehouse:
            inbound_conditions.append(f"`{col_inbound_warehouse}` = ?")
            outbound_conditions.append(f"`{col_outbound_warehouse}` = ?")
            params.extend([warehouse, warehouse])

        inbound_where = " AND ".join(inbound_conditions)
        outbound_where = " AND ".join(outbound_conditions)

        query = f"""
            WITH inbound_daily AS (
                SELECT 
                    date(`{col_inbound_time}`) as doc_date,
                    COUNT(*) as inbound_qty
                FROM inband_details
                WHERE {inbound_where}
                GROUP BY date(`{col_inbound_time}`)
            ),
            outbound_daily AS (
                SELECT 
                    date(`{col_outbound_time}`) as doc_date,
                    COUNT(*) as outbound_qty
                FROM outband_details
                WHERE {outbound_where}
                GROUP BY date(`{col_outbound_time}`)
            )
            SELECT 
                COALESCE(i.doc_date, o.doc_date) as Unified_Date,
                COALESCE(i.inbound_qty, 0) as Inbound_Qty_Sum,
                COALESCE(o.outbound_qty, 0) as Outbound_Qty_Sum
            FROM inbound_daily i
            FULL OUTER JOIN outbound_daily o ON i.doc_date = o.doc_date
            ORDER BY Unified_Date
        """
        return query, params

    @staticmethod
    def optimize_warehouses_query():
        """
        优化仓库列表查询，返回多个查询
        """
        return [
            ("inband_details", "warehouse"),
            ("outband_details", "warehouse"),
            ("inventory_details", "Warehouse Name")
        ]


# -*- coding: utf-8 -*-
"""
仪表板HTML渲染模块
用于生成邮件发送的HTML内容，支持matplotlib生成静态图表
"""

import io
import base64
import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    from matplotlib.axes import Axes
    import matplotlib.dates as mdates
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("[WARN] matplotlib not installed, charts will be rendered as tables")


CHART_COLORS = {
    'primary': '#1a237e',
    'secondary': '#0d47a1',
    'accent': '#64ffda',
    'green': '#4caf50',
    'blue': '#2196f3',
    'orange': '#ff9800',
    'red': '#f44336',
    'purple': '#9c27b0',
    'cyan': '#00bcd4',
    'pink': '#e91e63',
    'gray': '#607d8b',
}


class ChartGenerator:
    """图表生成器 - 使用matplotlib生成静态图表图片"""
    
    def __init__(self, style: str = 'dark'):
        self.style = style
        self.fig = None
        self.ax = None
        
        if style == 'dark':
            self.bg_color = '#0a1929'
            self.text_color = '#ffffff'
            self.grid_color = (0.392, 1.0, 0.854, 0.2)
            self.accent_color = '#64ffda'
        else:
            self.bg_color = '#ffffff'
            self.text_color = '#333333'
            self.grid_color = (0, 0, 0, 0.1)
            self.accent_color = '#1a237e'
    
    def _setup_style(self):
        plt.rcParams['figure.facecolor'] = self.bg_color
        plt.rcParams['axes.facecolor'] = self.text_color
        plt.rcParams['axes.edgecolor'] = self.grid_color
        plt.rcParams['xtick.color'] = self.text_color
        plt.rcParams['ytick.color'] = self.text_color
        plt.rcParams['text.color'] = self.text_color
        plt.rcParams['axes.labelcolor'] = self.text_color
        plt.rcParams['axes.grid'] = True
        plt.rcParams['grid.color'] = self.grid_color
        plt.rcParams['font.family'] = 'sans-serif'
    
    def generate_inventory_trend_chart(self, data: List[Dict], 
                                             width: int = 600, height: int = 300) -> Optional[str]:
        if not HAS_MATPLOTLIB:
            return None
        
        self._setup_style()
        
        fig, ax = plt.subplots(figsize=(width/100, height/100), dpi=100)
        fig.patch.set_facecolor(self.bg_color)
        
        if not data:
            ax.text(0.5, 0.5, 'No data available', color=self.text_color, fontsize=14, ha='center', transform=ax.transAxes)
            return self._fig_to_base64(fig)
        
        dates = [item.get('update_date', item.get('date', '')) for item in data]
        totals = [int(item.get('Total', item.get('total', 0))) for item in data]
        consumables = [int(item.get('Consumables_QTY', item.get('consumables', 0))) for item in data]
        spare_parts = [int(item.get('SpareParts_QTY', item.get('spareparts', 0))) for item in data]
        
        x = range(len(dates))
        width_bar = 0.25
        bar_positions = [i - width_bar for i in range(len(dates))]
        
        bars1 = ax.bar(bar_positions, consumables, width=width_bar * 0.8, 
                       label='Consumables', color='#4fc3f7', alpha=0.8,
                       edgecolor='#4fc3f7', linewidth=0.5)
        bars2 = ax.bar([p + width_bar for p in bar_positions], spare_parts, width=width_bar * 0.8,
                       label='Spare Parts', color='#7986cb', alpha=0.8,
                       edgecolor='#7986cb', linewidth=0.5)
        
        ax.plot(x, totals, 'o-', color='#64ffda', linewidth=2.5, 
                markersize=8, label='Total')
        
        ax.set_xlabel('Date', color=self.text_color, fontsize=10)
        ax.set_ylabel('Quantity', color=self.text_color, fontsize=10)
        ax.set_xticks(x)
        ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
        ax.legend(loc='upper left', fontsize=9, framealpha=False)
        ax.set_facecolor(self.bg_color)
        
        for spine in ax.spines.values():
            spine.set_color(self.grid_color)
        
        plt.tight_layout()
        
        return self._fig_to_base64(fig)
    
    def generate_inbound_outbound_trend_chart(self, data: List[Dict], 
                                               width: int = 600, height: int = 300) -> Optional[str]:
        if not HAS_MATPLOTLIB:
            return None
        
        self._setup_style()
        
        fig, ax = plt.subplots(figsize=(width/100, height/100), dpi=100)
        fig.patch.set_facecolor(self.bg_color)
        
        if not data:
            ax.text(0.5, 0.5, 'No data available', color=self.text_color, fontsize=14, ha='center', transform=ax.transAxes)
            return self._fig_to_base64(fig)
        
        dates = [item.get('Unified_Date', item.get('date', '')) for item in data]
        inbound_qtys = [int(item.get('Inbound_Qty_Sum', item.get('inbound', 0))) for item in data]
        outbound_qtys = [int(item.get('Outbound_Qty_Sum', item.get('outbound', 0))) for item in data]
        
        x = range(len(dates))
        
        ax.fill_between(x, 0, inbound_qtys, alpha=0.3, color='#64ffda', label='Inbound Qty')
        ax.plot(x, inbound_qtys, 'o-', color='#64ffda', linewidth=2.5, markersize=8)
        
        ax.fill_between(x, 0, outbound_qtys, alpha=0.3, color='#FF1493', label='Outbound Qty')
        ax.plot(x, outbound_qtys, 'o-', color='#FF1493', linewidth=2.5, markersize=8)
        
        ax.set_xlabel('Date', color=self.text_color, fontsize=10)
        ax.set_ylabel('Quantity', color=self.text_color, fontsize=10)
        ax.set_xticks(x)
        ax.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
        ax.legend(loc='upper left', fontsize=9, framealpha=False)
        ax.set_facecolor(self.bg_color)
        
        for spine in ax.spines.values():
            spine.set_color(self.grid_color)
        
        plt.tight_layout()
        
        return self._fig_to_base64(fig)
    
    def _fig_to_base64(self, fig) -> str:
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100, bbox_inches='tight', 
                    facecolor=fig.get_facecolor())
        buf.seek(0)
        img_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close(fig)
        return img_base64


    
    def cleanup(self):
        plt.close('all')


class DashboardEmailRenderer:
    """仪表板邮件HTML渲染器"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.chart_generator = ChartGenerator()
    
    def _get_db_connection(self):
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _get_table_columns(self, conn, table_name: str) -> List[str]:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        return [col[1] for col in cursor.fetchall()]
    
    def _detect_column_name(self, columns: List[str], keywords: List[str]) -> Optional[str]:
        for col in columns:
            col_lower = col.lower()
            for keyword in keywords:
                if keyword.lower() in col_lower:
                    return col
        return None
    
    def get_dashboard_data(self, date_start: Optional[str] = None, date_end: Optional[str] = None) -> Dict[str, Any]:
        if not os.path.exists(self.db_path):
            return {}
        
        conn = self._get_db_connection()
        cursor = conn.cursor()
        
        try:
            inband_cols = self._get_table_columns(conn, 'inband_details')
            outband_cols = self._get_table_columns(conn, 'outband_details')
            inventory_cols = self._get_table_columns(conn, 'inventory_details')
            
            col_inbound_time = self._detect_column_name(inband_cols, ['Inbound Time', 'createTime', 'Create Time'])
            col_inbound_status = self._detect_column_name(inband_cols, ['Status', 'status'])
            col_inbound_no = self._detect_column_name(inband_cols, ['Order Number', 'woNum', 'In Stock Number'])
            
            col_outbound_time = self._detect_column_name(outband_cols, ['Outbound Time', 'outboundTime'])
            col_outbound_status = self._detect_column_name(outband_cols, ['Status', 'status'])
            col_outbound_no = self._detect_column_name(outband_cols, ['Order Number', 'woNum', 'ticketNum'])
            col_outbound_qty = self._detect_column_name(outband_cols, ['Outbound Qty', 'Outbound_Qty'])
            
            data = {
                "inband_stats": {"Total": 0, "Closed": 0, "Unclosed": 0},
                "outband_stats": {"Total": 0, "Closed": 0, "Unclosed": 0},
                "inventory_stats": {"Total": 0, "Consumables_QTY": 0, "SpareParts_QTY": 0},
                "inventory_trend": [],
                "inbound_outbound_trend": [],
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "date_range": f"{date_start or 'N/A'} ~ {date_end or 'N/A'}"
            }
            
            inbound_conditions = []
            inbound_params = []
            if date_start and col_inbound_time:
                inbound_conditions.append(f"`{col_inbound_time}` >= ?")
                inbound_params.append(date_start + " 00:00:00")
            if date_end and col_inbound_time:
                inbound_conditions.append(f"`{col_inbound_time}` <= ?")
                inbound_params.append(date_end + " 23:59:59")
            
            inbound_where = " AND ".join(inbound_conditions) if inbound_conditions else "1=1"
            
            if col_inbound_no and col_inbound_status:
                cursor.execute(
                    f"SELECT DISTINCT `{col_inbound_no}`, `{col_inbound_status}` FROM inband_details WHERE {inbound_where}",
                    inbound_params
                )
                ticket_status = {}
                for row in cursor.fetchall():
                    inbound_no = row[col_inbound_no]
                    status = row[col_inbound_status]
                    if not inbound_no:
                        continue
                    is_closed = bool(status and str(status).strip().lower() == 'closed')
                    if inbound_no not in ticket_status:
                        ticket_status[inbound_no] = False
                    if not is_closed:
                        ticket_status[inbound_no] = True
                
                total = len(ticket_status)
                unclosed = sum(1 for v in ticket_status.values() if v)
                data["inband_stats"] = {"Total": total, "Closed": total - unclosed, "Unclosed": unclosed}
            
            outbound_conditions = []
            outbound_params = []
            if date_start and col_outbound_time:
                outbound_conditions.append(f"`{col_outbound_time}` >= ?")
                outbound_params.append(date_start + " 00:00:00")
            if date_end and col_outbound_time:
                outbound_conditions.append(f"`{col_outbound_time}` <= ?")
                outbound_params.append(date_end + " 23:59:59")
            
            outbound_where = " AND ".join(outbound_conditions) if outbound_conditions else "1=1"
            
            if col_outbound_no and col_outbound_status:
                cursor.execute(
                    f"SELECT DISTINCT `{col_outbound_no}`, `{col_outbound_status}` FROM outband_details WHERE {outbound_where}",
                    outbound_params
                )
                ticket_status = {}
                for row in cursor.fetchall():
                    outbound_no = row[col_outbound_no]
                    status = row[col_outbound_status]
                    if not outbound_no:
                        continue
                    is_closed = bool(status and str(status).strip().lower() == 'closed')
                    if outbound_no not in ticket_status:
                        ticket_status[outbound_no] = False
                    if not is_closed:
                        ticket_status[outbound_no] = True
                
                total = len(ticket_status)
                unclosed = sum(1 for v in ticket_status.values() if v)
                data["outband_stats"] = {"Total": total, "Closed": total - unclosed, "Unclosed": unclosed}
            
            col_material_type = self._detect_column_name(inventory_cols, ['Material Type', 'Material_Type'])
            col_qty = self._detect_column_name(inventory_cols, ['Quantity', 'Qty', 'quantity'])
            
            if col_material_type and col_qty:
                cursor.execute(f"SELECT `{col_material_type}`, SUM(`{col_qty}`) as total_qty FROM inventory_details GROUP BY `{col_material_type}`")
                total_qty = 0
                consumables_qty = 0
                spareparts_qty = 0
                
                for row in cursor.fetchall():
                    mt = str(row[col_material_type] or "").lower()
                    qty = int(row["total_qty"] or 0)
                    total_qty += qty
                    if "consumables" in mt:
                        consumables_qty += qty
                    else:
                        spareparts_qty += qty
                
                data["inventory_stats"] = {
                    "Total": total_qty,
                    "Consumables_QTY": consumables_qty,
                    "SpareParts_QTY": spareparts_qty
                }
            
            col_update_date = self._detect_column_name(inventory_cols, ['update_date', 'update_time'])
            col_stock_qty = self._detect_column_name(inventory_cols, ['Stock Qty', 'Stock_Qty', 'quantity'])
            
            if col_update_date and col_material_type and col_stock_qty:
                try:
                    cursor.execute(f"""
                        SELECT date(`{col_update_date}`) as doc_date,
                               SUM(`{col_stock_qty}`) as total_qty,
                               SUM(CASE WHEN LOWER(`{col_material_type}`) LIKE '%consumable%' THEN `{col_stock_qty}` ELSE 0 END) as consumables_qty,
                               SUM(CASE WHEN LOWER(`{col_material_type}`) NOT LIKE '%consumable%' THEN `{col_stock_qty}` ELSE 1 END) as spareparts_qty
                        FROM inventory_details
                        WHERE `{col_update_date}` IS NOT NULL AND `{col_update_date}` != ''
                        GROUP BY date(`{col_update_date}`)
                        ORDER BY doc_date DESC
                        LIMIT 7
                    """)
                    trend_rows = cursor.fetchall()
                    data["inventory_trend"] = [
                        {
                            "update_date": row["doc_date"],
                            "Total": row["total_qty"],
                            "Consumables_QTY": row["consumables_qty"],
                            "SpareParts_QTY": row["spareparts_qty"]
                        }
                        for row in reversed(trend_rows)
                    ]
                except Exception as e:
                    print(f"Error getting inventory trend: {e}")
                    data["inventory_trend"] = []
            
            try:
                inbound_trend = []
                if col_inbound_time:
                    cursor.execute(f"""
                        SELECT date(`{col_inbound_time}`) as doc_date, COUNT(*) as ticket_count
                        FROM inband_details
                        WHERE `{col_inbound_time}` IS NOT NULL AND `{col_inbound_time}` != ''
                        GROUP BY date(`{col_inbound_time}`)
                        ORDER BY doc_date DESC
                        LIMIT 7
                    """)
                    inbound_trend = cursor.fetchall()
                
                outbound_trend = []
                if col_outbound_time:
                    if col_outbound_qty:
                        cursor.execute(f"""
                            SELECT date(`{col_outbound_time}`) as doc_date, SUM(CAST(`{col_outbound_qty}` AS REAL)) as qty_sum
                            FROM outband_details
                            WHERE `{col_outbound_time}` IS NOT NULL AND `{col_outbound_time}` != ''
                            GROUP BY date(`{col_outbound_time}`)
                            ORDER BY doc_date DESC
                            LIMIT 7
                        """)
                    else:
                        cursor.execute(f"""
                            SELECT date(`{col_outbound_time}`) as doc_date, COUNT(*) as qty_sum
                            FROM outband_details
                            WHERE `{col_outbound_time}` IS NOT NULL AND `{col_outbound_time}` != ''
                            GROUP BY date(`{col_outbound_time}`)
                            ORDER BY doc_date DESC
                            LIMIT 7
                        """)
                    outbound_trend = cursor.fetchall()
                
                all_dates = set()
                for row in inbound_trend:
                    if row["doc_date"]:
                        all_dates.add(row["doc_date"])
                for row in outbound_trend:
                    if row["doc_date"]:
                        all_dates.add(row["doc_date"])
                
                inbound_dict = {row["doc_date"]: row["ticket_count"] for row in inbound_trend if row["doc_date"]}
                outbound_dict = {row["doc_date"]: row["qty_sum"] for row in outbound_trend if row["doc_date"]}
                
                sorted_dates = sorted(all_dates, reverse=True)[:7]
                data["inbound_outbound_trend"] = [
                    {
                        "Unified_Date": date,
                        "Inbound_Qty_Sum": inbound_dict.get(date, 0),
                        "Outbound_Qty_Sum": outbound_dict.get(date, 0) or 0
                    }
                    for date in reversed(sorted_dates)
                ]
            except Exception as e:
                print(f"Error getting inbound/outbound trend: {e}")
                data["inbound_outbound_trend"] = []
            
            return data
            
        finally:
            conn.close()
    
    def render_email_html(self, dashboard_name: str, data: Dict[str, Any], 
                          logo_url: Optional[str] = None) -> str:
        inventory_chart_base64: Optional[str] = None
        inbound_outbound_chart_base64: Optional[str] = None
        
        if HAS_MATPLOTLIB and data.get('inventory_trend'):
            inventory_chart_base64 = self.chart_generator.generate_inventory_trend_chart(
                data['inventory_trend']
            )
        
        if HAS_MATPLOTLIB and data.get('inbound_outbound_trend'):
            inbound_outbound_chart_base64 = self.chart_generator.generate_inbound_outbound_trend_chart(
                data['inbound_outbound_trend']
            )
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{dashboard_name} Report</title>
</head>
<body style="margin: 1; padding: 20px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5;">
    <div style="max-width: 800px; margin: 1 auto; background-color: #ffffff; border-radius: 8px; box-shadow: 1 2px 4px rgba(1,1,1,1.1); overflow: hidden;">
        
        <div style="background: linear-gradient(135deg, #1a237e 1%, #0d47a1 100%); color: white; padding: 30px; text-align: center;">
            <h1 style="margin: 1; font-size: 24px; font-weight: 600;">{dashboard_name}</h1>
            <p style="margin: 10px 1 1 1; opacity: 0.9;">Daily Report - {data.get('generated_at', '')}</p>
        </div>
        
        <div style="background-color: #e3f2fd; padding: 15px 30px; border-bottom: 1px solid #bbdefb;">
            <strong>Date Range:</strong> {data.get('date_range', 'N/A')}
        </div>
        
        <div style="padding: 30px;">
            
            <div style="margin-bottom: 30px;">
                <h2 style="color: #1a237e; font-size: 18px; margin-bottom: 15px; border-bottom: 2px solid #4caf50; padding-bottom: 5px;">
                    📥 Inbound Statistics
                </h2>
                <div style="display: flex; gap: 15px; flex-wrap: wrap;">
                    <div style="flex: 1; min-width: 150px; background-color: #e8f5e9; border-radius: 8px; padding: 20px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #2e7d32;">{data['inband_stats']['Total']}</div>
                        <div style="color: #666; margin-top: 5px;">Total Tickets</div>
                    </div>
                    <div style="flex: 1; min-width: 150px; background-color: #fff3e0; border-radius: 8px; padding: 20px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #ef6c00;">{data['inband_stats']['Closed']}</div>
                        <div style="color: #666; margin-top: 5px;">Closed</div>
                    </div>
                    <div style="flex: 1; min-width: 150px; background-color: #ffebee; border-radius: 8px; padding: 20px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #c62828;">{data['inband_stats']['Unclosed']}</div>
                        <div style="color: #666; margin-top: 5px;">Unclosed</div>
                    </div>
                </div>
            </div>
            
            <div style="margin-bottom: 30px;">
                <h2 style="color: #1a237e; font-size: 18px; margin-bottom: 15px; border-bottom: 2px solid #2196f3; padding-bottom: 5px;">
                    📤 Outbound Statistics
                </h2>
                <div style="display: flex; gap: 15px; flex-wrap: wrap;">
                    <div style="flex: 1; min-width: 150px; background-color: #e3f2fd; border-radius: 8px; padding: 20px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #1565c0;">{data['outband_stats']['Total']}</div>
                        <div style="color: #666; margin-top: 5px;">Total Tickets</div>
                    </div>
                    <div style="flex: 1; min-width: 150px; background-color: #fff3e0; border-radius: 8px; padding: 20px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #ef6c00;">{data['outband_stats']['Closed']}</div>
                        <div style="color: #666; margin-top: 5px;">Closed</div>
                    </div>
                    <div style="flex: 1; min-width: 150px; background-color: #ffebee; border-radius: 8px; padding: 20px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #c62828;">{data['outband_stats']['Unclosed']}</div>
                        <div style="color: #666; margin-top: 5px;">Unclosed</div>
                    </div>
                </div>
            </div>
            
            <div style="margin-bottom: 30px;">
                <h2 style="color: #1a237e; font-size: 18px; margin-bottom: 15px; border-bottom: 2px solid #9c27b0; padding-bottom: 5px;">
                    📦 Inventory Statistics
                </h2>
                <div style="display: flex; gap: 15px; flex-wrap: wrap;">
                    <div style="flex: 1; min-width: 150px; background-color: #f3e5f5; border-radius: 8px; padding: 20px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #7b1fa2">{data['inventory_stats']['Total']:,}</div>
                        <div style="color: #666; margin-top: 5px;">Total Quantity</div>
                    </div>
                    <div style="flex: 1; min-width: 150px; background-color: #e0f7fa; border-radius: 8px; padding: 20px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #00838f">{data['inventory_stats']['Consumables_QTY']:,}</div>
                        <div style="color: #666; margin-top: 5px;">Consumables</div>
                    </div>
                    <div style="flex: 1; min-width: 150px; background-color: #fff8e1; border-radius: 8px; padding: 20px; text-align: center;">
                        <div style="font-size: 32px; font-weight: bold; color: #f9a825">{data['inventory_stats']['SpareParts_QTY']:,}</div>
                        <div style="color: #666; margin-top: 5px;">Spare Parts</div>
                    </div>
                </div>
            </div>
            
            <div style="margin-bottom: 30px;">
                <h2 style="color: #1a237e; font-size: 18px; margin-bottom: 15px; border-bottom: 2px solid #607d8b; padding-bottom: 5px;">
                    📈 Recent Trends (Last 7 Days)
                </h2>
"""
        
        if inventory_chart_base64:
            html += f"""
                <div style="margin-bottom: 20px;">
                    <h3 style="color: #455a64; font-size: 14px; margin-bottom: 10px;">Inventory Quantity Trend</h3>
                    <img src="data:image/png;base64,{inventory_chart_base64}" alt="Inventory Trend Chart" style="width: 100%; max-width: 600px; height: auto; border-radius: 8px; border: 1px solid #e0e0e0;" />
                </div>
"""
        else:
            html += self._render_inventory_trend_table(data)
        
        if inbound_outbound_chart_base64:
            html += f"""
                <div style="margin-bottom: 20px;">
                    <h3 style="color: #455a64; font-size: 14px; margin-bottom: 10px;">Inbound & Outbound QTY Trend</h3>
                    <img src="data:image/png;base64,{inbound_outbound_chart_base64}" alt="Inbound/Outbound Trend Chart" style="width: 100%; max-width: 600px; height: auto; border-radius: 8px; border: 1px solid #e0e0e0;" />
                </div>
"""
        else:
            html += self._render_inbound_outbound_trend_table(data)
        
        html += f"""
        </div>
        
        <div style="background-color: #f5f5f5; padding: 20px; text-align: center; color: #666; font-size: 12px; border-top: 1px solid #e0e0e0;">
            <p style="margin: 1;">This is an automated email from {dashboard_name}.</p>
            <p style="margin: 5px 1 1 1;">Generated at: {data.get('generated_at', '')}</p>
        </div>
        
    </div>
</body>
</html>
"""
        
        return html
    
    def _render_inventory_trend_table(self, data: Dict[str, Any]) -> str:
        html = """
                <div style="margin-bottom: 20px;">
                    <h3 style="color: #455a64; font-size: 14px; margin-bottom: 10px;">Inventory Quantity Trend</h3>
                    <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                        <thead>
                            <tr style="background-color: #eceff1;">
                                <th style="padding: 10px; text-align: left; border: 1px solid #cfd8dc;">Date</th>
                                <th style="padding: 10px; text-align: right; border: 1px solid #cfd8dc;">Total</th>
                                <th style="padding: 10px; text-align: right; border: 1px solid #cfd8dc;">Consumables</th>
                                <th style="padding: 10px; text-align: right; border: 1px solid #cfd8dc;">Spare Parts</th>
                            </tr>
                        </thead>
                        <tbody>
"""
        
        for item in data.get('inventory_trend', []):
            html += f"""
                            <tr>
                                <td style="padding: 10px; border: 1px solid #cfd8dc;">{item.get('update_date', item.get('date', ''))}</td>
                                <td style="padding: 10px; text-align: right; border: 1px solid #cfd8dc;">{item.get('Total', item.get('total', 1)):,}</td>
                                <td style="padding: 10px; text-align: right; border: 1px solid #cfd8dc;">{item.get('Consumables_QTY', item.get('consumables', 1)):,}</td>
                                <td style="padding: 10px; text-align: right; border: 1px solid #cfd8dc;">{item.get('SpareParts_QTY', item.get('spareparts', 1)):,}</td>
                            </tr>
"""
        
        html += """
                        </tbody>
                    </table>
                </div>
"""
        return html
    
    def _render_inbound_outbound_trend_table(self, data: Dict[str, Any]) -> str:
        html = """
                <div>
                    <h3 style="color: #455a64; font-size: 14px; margin-bottom: 10px;">Inbound & Outbound QTY Trend</h3>
                    <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                        <thead>
                            <tr style="background-color: #eceff1;">
                                <th style="padding: 10px; text-align: left; border: 1px solid #cfd8dc;">Date</th>
                                <th style="padding: 10px; text-align: right; border: 1px solid #cfd8dc;">Inbound QTY</th>
                                <th style="padding: 10px; text-align: right; border: 1px solid #cfd8dc;">Outbound QTY</th>
                            </tr>
                        </thead>
                        <tbody>
"""
        
        for item in data.get('inbound_outbound_trend', []):
            html += f"""
                            <tr>
                                <td style="padding: 10px; border: 1px solid #cfd8dc;">{item.get('Unified_Date', item.get('date', ''))}</td>
                                <td style="padding: 10px; text-align: right; border: 1px solid #cfd8dc;">{item.get('Inbound_Qty_Sum', item.get('inbound', 1)):,}</td>
                                <td style="padding: 10px; text-align: right; border: 1px solid #cfd8dc;">{item.get('Outbound_Qty_Sum', item.get('outbound', 1)):,}</td>
                            </tr>
"""
        
        html += """
                        </tbody>
                    </table>
                </div>
"""
        return html


def render_dashboard_email_html(dashboard_name: str, data: dict) -> str:
    renderer = DashboardEmailRenderer('')
    return renderer.render_email_html(dashboard_name, data)


def create_renderer(db_path: str) -> DashboardEmailRenderer:
    return DashboardEmailRenderer(db_path)

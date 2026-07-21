import sys
import io
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import os
from datetime import datetime
import matplotlib.pyplot as plt
import textwrap

# 解决环境编码问题
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


class ReportProcessor:
    """告警报告处理类：包含过滤、时长计算、Excel美化、截图功能"""

    COLOR_SLA = {
        'failed': PatternFill(start_color='FF0000', end_color='FF0000', fill_type='solid'),
        'pass': PatternFill(start_color='00FF00', end_color='00FF00', fill_type='solid'),
        'within sla': PatternFill(start_color='40E0D0', end_color='40E0D0', fill_type='solid')
    }
    COLOR_STATUS = {
        'Wait For Confirm': PatternFill(start_color='FF0000', end_color='FF0000', fill_type='solid'),
        'Waiting for Accept': PatternFill(start_color='FFA500', end_color='FFA500', fill_type='solid'),
        'Waiting for Process': PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid'),
        'closed': PatternFill(start_color='00FF00', end_color='00FF00', fill_type='solid')
    }
    COLOR_HEADER = PatternFill(start_color="00FFFF", end_color="40E0D0", fill_type="solid")

    @staticmethod
    def format_duration(td):
        """将 timedelta 转换为 Dd Hh Mm 格式"""
        if pd.isna(td) or td.total_seconds() < 0: return "0d0h0m"
        total_seconds = int(td.total_seconds())
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{days}d{hours}h{minutes}m"

    @classmethod
    def process_data(cls, file_path, required_cols, max_hours=None):
        """数据处理核心：过滤未清除告警 + 计算实时时长 + 包含最近关闭的告警"""
        df = pd.read_excel(file_path, engine='openpyxl')

        # 检查可用列
        print(f"Available columns in {os.path.basename(file_path)}:")
        print(df.columns.tolist())
        print(f"Required cols: {required_cols}")

        # 1. 字段预筛选
        available_cols = [c for c in required_cols if c in df.columns]
        df = df[available_cols].copy()
        print(f"Filtered columns: {available_cols}")

        # 2. 转换时间格式
        df['Alarm Occur Time'] = pd.to_datetime(df['Alarm Occur Time'], errors='coerce')
        df['Alarm Clear Time'] = pd.to_datetime(df['Alarm Clear Time'], errors='coerce')

        # 添加 Last Modified Time 转换（如果存在）
        if 'Last Modified Time' in df.columns:
            df['Last Modified Time'] = pd.to_datetime(df['Last Modified Time'], errors='coerce')

        now = datetime.now()

        # 3. 处理未关闭的工单（没有有效 Alarm Clear Time 的数据）
        open_df = df[df['Alarm Clear Time'].isna()].copy()

        if not open_df.empty:
            # 计算时长：使用当前时间 - 发生时间
            real_time_duration = now - open_df['Alarm Occur Time']

            # 针对需求进行 8小时过滤
            if max_hours is not None:
                mask = (real_time_duration.dt.total_seconds() / 3600) <= max_hours
                open_df = open_df[mask].copy()
                real_time_duration = now - open_df['Alarm Occur Time']  # 更新时长序列

            # 生成可读时长列和日期列
            open_df['Alarm Duration(Hours)'] = real_time_duration.apply(cls.format_duration)
            open_df['Date'] = open_df['Alarm Occur Time'].dt.strftime('%Y-%m-%d')

            # 排序（P1优先 + 时间最近优先）
            if 'Ticket Severity' in open_df.columns:
                sev_map = {'P1': 1, 'P2': 2, 'P3': 3, 'P4': 4}
                open_df['_s'] = open_df['Ticket Severity'].str.strip().str.upper().map(sev_map).fillna(5)
                open_df = open_df.sort_values(['_s', 'Alarm Occur Time'], ascending=[True, False]).drop(columns=['_s'])

            open_df.insert(0, 'Index', range(1, len(open_df) + 1))

        # 4. 处理最近8小时内关闭的工单
        closed_df = pd.DataFrame()
        if 'Status' in df.columns and 'Last Modified Time' in df.columns:
            # 过滤条件：Status为Closed，且Last Modified Time在8小时内
            # 添加调试信息
            print(f"Current time: {now}")
            print(f"Total tickets: {len(df)}")
            print(f"Tickets with Status column: {len(df[df['Status'].notna()])}")

            # 检查所有状态值
            status_values = df['Status'].dropna().unique()
            print(f"Unique Status values: {status_values}")

            # 检查closed状态的各种写法
            closed_tickets = df[df['Status'].str.lower().str.contains('closed', na=False)]
            print(f"Closed tickets (including variations): {len(closed_tickets)}")

            # 检查Last Modified Time范围
            if not df['Last Modified Time'].isna().all():
                latest_time = df['Last Modified Time'].max()
                earliest_time = df['Last Modified Time'].min()
                print(f"Latest Last Modified Time: {latest_time}")
                print(f"Earliest Last Modified Time: {earliest_time}")
                print(f"Time difference from latest to now: {(now - latest_time).total_seconds() / 3600:.2f} hours")

            closed_mask = (df['Status'].str.lower() == 'closed') & \
                          (df['Last Modified Time'].notna()) & \
                          ((now - df['Last Modified Time']).dt.total_seconds() / 3600 <= 8)
            closed_df = df[closed_mask].copy()
            print(f"Closed tickets within 8 hours: {len(closed_df)}")

            if not closed_df.empty:
                # 计算关闭时长
                closed_duration = closed_df['Alarm Clear Time'] - closed_df['Alarm Occur Time']
                closed_df['Alarm Duration(Hours)'] = closed_duration.apply(cls.format_duration)
                closed_df['Date'] = closed_df['Alarm Occur Time'].dt.strftime('%Y-%m-%d')

                # 排序（按关闭时间倒序）
                closed_df = closed_df.sort_values('Last Modified Time', ascending=False)
                closed_df.insert(0, 'Index', range(1, len(closed_df) + 1))

        # Calculate additional counts
        total_count = len(df)

        # Calculate total closed tickets (regardless of time)
        total_closed_count = 0
        if 'Status' in df.columns:
            total_closed_count = len(df[df['Status'].str.lower().str.contains('closed', na=False)])

        closed_within_8h_count = len(closed_df)
        open_count = len(open_df)

        return open_df, closed_df, total_count, total_closed_count, closed_within_8h_count, open_count

    @classmethod
    def save_excel_and_style(cls, open_df, closed_df, total_count, total_closed_count, closed_within_8h_count,
                             open_count, base_name):
        """保存 Excel 并应用样式与列宽，添加 Summary 工作表"""
        # 删除同系列旧文件，只保留最新的
        current_dir = os.getcwd()
        for filename in os.listdir(current_dir):
            if filename.startswith(base_name) and filename.endswith('.xlsx'):
                os.remove(os.path.join(current_dir, filename))

        curr_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_path = f"{base_name} {curr_time}.xlsx"

        # 创建 Excel 写入器
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            # 写入未关闭工单工作表
            if not open_df.empty:
                open_df.to_excel(writer, sheet_name='Open TT', index=False)

            # 写入最近关闭工单工作表
            if not closed_df.empty:
                closed_df.to_excel(writer, sheet_name='Closed TT (8h)', index=False)

            # 创建 Summary 工作表
            summary_df = pd.DataFrame({
                'Item': ['Total Tickets', 'Total Closed Tickets', 'Closed last 8 hours',
                         'Open TT till now(Alarm Not Clear)'],
                'Value': [total_count, total_closed_count, closed_within_8h_count, open_count]
            })
            summary_df.to_excel(writer, sheet_name='Summary', index=False)

        wb = load_workbook(file_path)
        border = Border(left=Side(style="thin"), right=Side(style="thin"),
                        top=Side(style="thin"), bottom=Side(style="thin"))

        # 美化所有工作表
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]

            # 表头与列宽
            for col_num, cell in enumerate(ws[1], 1):
                cell.fill = cls.COLOR_HEADER
                cell.font = Font(bold=True, color="FFFFFF")
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = border

                letter = get_column_letter(col_num)
                name = str(cell.value)
                if name == 'Title':
                    ws.column_dimensions[letter].width = 45
                elif name in ['Ticket No.', 'WO No.', 'Site ID']:
                    ws.column_dimensions[letter].width = 18
                elif 'Time' in name:
                    ws.column_dimensions[letter].width = 22
                else:
                    ws.column_dimensions[letter].width = 15

            # 数据行美化
            sla_col = None
            status_col = None
            for i, cell in enumerate(ws[1], 1):
                if cell.value == 'SLA Status': sla_col = i
                if cell.value == 'Status': status_col = i

            for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
                for cell in row:
                    cell.border = border
                    cell.alignment = Alignment(wrap_text=True, vertical="center")
                    # SLA 状态着色
                    if cell.column == sla_col and cell.value:
                        v = str(cell.value).lower()
                        for key, fill in cls.COLOR_SLA.items():
                            if key in v: cell.fill = fill
                    # Status 状态着色
                    if cell.column == status_col and cell.value:
                        v = str(cell.value)
                        for key, fill in cls.COLOR_STATUS.items():
                            if key.lower() in v.lower(): cell.fill = fill

        wb.save(file_path)
        return file_path

    @classmethod
    def create_screenshot(cls, total_count, total_closed_count, closed_within_8h_count, open_count, report_name):
        """生成极紧凑型计数截图，显著减少上下空白"""
        # 1. 降低初始高度：从 3 减小到 1.2
        fig_width = 8
        fig_height = 1.2

        fig, ax = plt.subplots(figsize=(fig_width, fig_height), facecolor='white')
        ax.axis('off')

        # 2. 准备数据
        data = [
            ['Total Tickets', total_count],
            ['Total Closed Tickets', total_closed_count],
            ['Closed last 8 hours', closed_within_8h_count],
            ['Open TT till now(Alarm Not Clear)', open_count]
        ]
        columns = ['Item', 'Value']

        # 3. 创建表格
        table = ax.table(
            cellText=data,
            colLabels=columns,
            loc='center',
            cellLoc='left'
        )

        table.auto_set_font_size(False)
        table.set_fontsize(11)
        # 4. 调整行高缩放：从 1.8 降低到 1.3，减少单元格内部多余高度
        table.scale(1, 1.3)

        # 5. 样式美化（保持原样）
        for (row, col), cell in table.get_celld().items():
            if row == 0:  # 表头
                cell.set_facecolor('#00FFFF')
                cell.set_text_props(weight='bold', color='black')
            else:  # 数据行
                if col == 0:
                    cell.set_facecolor('#E6E6FA')
                    cell.set_text_props(weight='bold')
                else:
                    cell.set_facecolor('#FFFFFF')
            cell.set_edgecolor('black')

        # 6. 极小化边距：将 pad_inches 从 0.05 降至 0.01
        img_path = f"{report_name}.jpg"

        plt.savefig(
            img_path,
            bbox_inches='tight',
            pad_inches=0.01,
            dpi=120,  # 略微提升DPI，确保在小尺寸下文字依然锐利
            format='jpg',
            facecolor=fig.get_facecolor(),
            pil_kwargs={
                'quality': 95,  # 提高质量
                'optimize': True
            }
        )
        plt.close()


def execute_report(path, report_name, required_cols, max_h=None):
    """执行单个任务逻辑"""
    print(f"\n🚀 开始生成报告: {report_name}")
    if not os.path.exists(path):
        print(f"❌ 找不到输入文件: {path}")
        return

    open_df, closed_df, total_count, total_closed_count, closed_within_8h_count, open_count = ReportProcessor.process_data(
        path, required_cols, max_h)
    if open_df.empty and closed_df.empty and total_count == 0:
        print(f"⚠️ 过滤后无匹配告警数据，跳过报告生成。")
        return

    out_xlsx = ReportProcessor.save_excel_and_style(open_df, closed_df, total_count, total_closed_count,
                                                    closed_within_8h_count, open_count, report_name)
    ReportProcessor.create_screenshot(total_count, total_closed_count, closed_within_8h_count, open_count, report_name)
    print(f"✅ 成功! 文件: {out_xlsx}")
    print(f"✅ 截图已生成: {report_name}.jpg")


if __name__ == "__main__":
    # 1. TT 报告: 只要未清除告警 + 时长 <= 8小时
    tt_required_cols = [
        'Title', 'Ticket No.', 'WO No.', 'Site ID', 'Site Name', 'Status',
        'Ticket Severity', 'SLA Time', 'SLA Status', 'Region ID',
        'Created Time', 'Last Modified Time', 'Alarm Occur Time', 'Alarm Clear Time'
    ]
    execute_report(
        path=r'C:\FineBI6.0\webapps\webroot\WEB-INF\reportlets\excel\Eflow_TT_FB.xlsx',
        report_name="ZTE OLR MS Open TT 8 Hourly Report",
        required_cols=tt_required_cols,
        max_h=None
    )

    # 2. WO 报告: 只要未清除告警 + 全量时长 (基于新文件 Eflow_WO_FB.xlsx)
#    wo_required_cols = [
#        'WO No.', 'Title', 'Status', 'Created Time', 'Ticket Severity',
#        'Alarm Occur Time', 'Alarm Clear Time',
#        'Fault Duration Time', 'SLA Time', 'E2E SLA Status'
#    ]
#    execute_report(
#        path=r'C:\FineBI6.0\webapps\webroot\WEB-INF\reportlets\excel\Eflow_WO_FB.xlsx',
#        report_name="ZTE OLR MS WO 2 Hourly Report",
#        required_cols=wo_required_cols,
#        max_h=None
#    )

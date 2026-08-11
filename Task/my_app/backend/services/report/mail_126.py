import logging
import sys
import io

# 强制标准输出使用 UTF-8 编码
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import pandas as pd
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import os
import time
from datetime import datetime
import glob
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formatdate, formataddr
import matplotlib
matplotlib.use('Agg')  # 非交互后端，加速渲染
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np
import textwrap

# ============================================================
# 统一 SLA 颜色映射（Excel + 图片共用）
# ============================================================
SLA_COLOR_MAP = {
    "SLA<25%":  "90EE90",   # 浅绿
    "SLA<50%":  "FFFF99",   # 浅黄
    "SLA<75%":  "FFD580",   # 浅橙
    "SLA<100%": "FFD699",   # 浅橙
    "SLA>100%": "FF6666",   # 浅红
}
SLA_ORDER = ["SLA<25%", "SLA<50%", "SLA<75%", "SLA<100%", "SLA>100%"]
SLA_MAP = {'P1': 4, 'P2': 8, 'P3': 16, 'P4': 48}


class EmailSender:
    """126邮箱发送配置"""
    SMTP_SERVER = "smtp.126.com"
    SMTP_PORT = 465
    USERNAME = "xin83min@126.com"
    PASSWORD = "LQcTaMMuWmhvAfRB"
    SENDER = "xin83min@126.com"

    @classmethod
    def _runtime_credentials(cls):
        """运行时获取凭据（环境变量 > 数据库 > 模块默认值），支持页面改密后免重启生效。"""
        try:
            from backend.services.credential_store import get_credential
        except ImportError:
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from credential_store import get_credential
        return get_credential("mail_126", cls.USERNAME, cls.PASSWORD)
    TO_RECEIVERS = pd.read_csv("to_receiver.txt")
    TO_RECEIVERS = TO_RECEIVERS.columns.to_list()
    TO_RECEIVERS = [x for x in TO_RECEIVERS if not str(x).startswith('Unnamed:')]

    @classmethod
    def set_receivers(cls, to_receivers):
        if isinstance(to_receivers, str):
            cls.TO_RECEIVERS = [to_receivers]
        elif isinstance(to_receivers, list):
            cls.TO_RECEIVERS = to_receivers
        else:
            raise ValueError("收件人格式错误，应为字符串或列表")

    @classmethod
    def _safe_str(cls, value):
        if pd.isna(value):
            return ""
        elif isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            return str(value)
        return str(value)

    @classmethod
    def df_to_styled_html(cls, df):
        """生成与Excel格式匹配的完整HTML页面（邮件正文）"""
        style = """
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background-color: #f9f9f9; }
            .container { background-color: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            h2 { color: #333; border-bottom: 2px solid #00BFFF; padding-bottom: 10px; }
            table { border-collapse: collapse; width: 100%; margin-top: 15px; font-size: 14px; }
            th { background-color: #00BFFF; color: white; font-weight: bold; text-align: center;
                 padding: 12px 8px; border: 1px solid #000; white-space: nowrap; }
            td { text-align: left; padding: 8px; border: 1px solid #000; white-space: normal; }
            tr:nth-child(even) { background-color: #f2f2f2; }
            .sla-failed { background-color: #FF6666 !important; color: white; }
            .sla-pass   { background-color: #00FF00 !important; }
            .sla-within { background-color: #40E0D0 !important; }
            .row-red    { background-color: #FF6666 !important; color: white; }
        </style>
        """
        # 找到 SLA Status 列
        sla_col_name = None
        if 'SLA Status' in df.columns:
            sla_col_name = 'SLA Status'

        if sla_col_name:
            sla_idx = df.columns.get_loc(sla_col_name)
            header = "<tr>" + "".join(f"<th>{cls._safe_str(col)}</th>" for col in df.columns) + "</tr>"
            row_parts = []
            _safe = cls._safe_str
            for row in df.itertuples(index=False):
                cells = []
                is_red_row = False
                val_str = _safe(row[sla_idx]).lower().strip()
                if 'sla>100%' in val_str:
                    is_red_row = True
                for idx, val in enumerate(row):
                    if idx == sla_idx:
                        cell_str = _safe(val).lower().strip()
                        if 'failed' in cell_str or 'sla>100%' in cell_str:
                            cells.append(f'<td class="sla-failed">{_safe(val)}</td>')
                        elif 'pass' in cell_str:
                            cells.append(f'<td class="sla-pass">{_safe(val)}</td>')
                        elif 'within sla' in cell_str:
                            cells.append(f'<td class="sla-within">{_safe(val)}</td>')
                        else:
                            cells.append(f"<td>{_safe(val)}</td>")
                    else:
                        if is_red_row:
                            cells.append(f'<td class="row-red">{_safe(val)}</td>')
                        else:
                            cells.append(f"<td>{_safe(val)}</td>")
                row_parts.append("<tr>" + "".join(cells) + "</tr>")
            table_html = f"<table>{header}{''.join(row_parts)}</table>"
        else:
            table_html = df.fillna('').applymap(
                lambda x: str(x) if not pd.isna(x) else ''
            ).to_html(index=False, border=0, escape=False)

        full_html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Liberia Orange TT Summary Report</title>{style}</head>
<body><div class="container"><h2>Liberia Orange TT Summary Report</h2>
{table_html}</div></body></html>"""
        return full_html

    @classmethod
    def send_report_email(cls, excel_file_path, df_report, image_paths=None):
        """发送带Excel附件和HTML表格的邮件"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        file_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        subject = f"Liberia Orange TT Summary Report {file_time}"

        email_body = cls.df_to_styled_html(df_report)

        # 嵌入图片到HTML正文
        if image_paths:
            import base64
            img_tags = []
            for p in image_paths:
                if p and os.path.exists(p):
                    with open(p, "rb") as img_file:
                        img_data = base64.b64encode(img_file.read()).decode('utf-8')
                    img_tags.append(
                        f'<img src="data:image/png;base64,{img_data}" '
                        f'alt="{os.path.basename(p)}" '
                        f'style="width:100%; max-width:900px; margin:10px auto; display:block;">'
                    )
            if img_tags:
                email_body = email_body.replace(
                    '<div class="container">',
                    '<div class="container">' + ''.join(img_tags)
                )

        msg = MIMEMultipart('alternative')
        msg['From'] = formataddr(("ZTE NOC", cls.SENDER))
        msg['To'] = ", ".join(cls.TO_RECEIVERS)
        msg['Subject'] = subject
        msg['Date'] = formatdate(usegmt=True)
        msg.attach(MIMEText(email_body, 'html', 'utf-8'))

        # 附件
        try:
            with open(excel_file_path, 'rb') as f:
                part = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(excel_file_path)}"')
                msg.attach(part)
        except Exception as e:
            raise Exception(f"读取附件失败: {e}")

        try:
            server = smtplib.SMTP_SSL(cls.SMTP_SERVER, cls.SMTP_PORT, timeout=30)
            server.set_debuglevel(0)
            try:
                _mail_user, _mail_pwd = cls._runtime_credentials()
                server.login(_mail_user, _mail_pwd)
                server.sendmail(_mail_user or cls.SENDER, cls.TO_RECEIVERS, msg.as_string())
                print(f"\n✅ 邮件发送成功！")
                print(f"📧 收件人: {cls.TO_RECEIVERS}")
                print(f"📝 主题: {subject}")
            finally:
                server.quit()
        except smtplib.SMTPAuthenticationError as e:
            raise Exception(f"❌ 126邮箱认证失败！\n{e}")
        except Exception as e:
            raise Exception(f"❌ 邮件发送失败: {e}")


class ExcelDataProcessor:
    """Excel数据处理 + TT Summary + 图片生成（全部合并）"""

    df_eflow_source = None
    df_eflow_temp = None
    df_master_cache = None

    download_path = os.path.join(os.path.expanduser("~"), "Downloads")
    default_file_path = r'C:\FineBI6.0\webapps\webroot\WEB-INF\reportlets\excel\Eflow_TT_FB.xlsx'
    master_file_path = r"C:\FineBI6.0\webapps\webroot\WEB-INF\reportlets\excel\Site_Maintainer_Category.xlsx"

    @classmethod
    def set_file_path(cls, file_path):
        cls.default_file_path = file_path

    @staticmethod
    def clean_columns(df):
        df.columns = (df.columns.astype(str).str.strip()
                      .str.replace('\xa0', '', regex=False)
                      .str.replace('\u3000', '', regex=False))
        return df

    @staticmethod
    def normalize_id(x):
        if pd.isna(x):
            return ""
        x = str(x).strip()
        try:
            x = str(int(float(x)))
        except (ValueError, TypeError):
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] normalize_id: exception swallowed", exc_info=True)
            pass
        return x

    @classmethod
    def load_master_data(cls):
        if cls.df_master_cache is not None:
            return cls.df_master_cache
        print("📌 读取 Master Site Database...")
        df_master = pd.read_excel(cls.master_file_path, engine="openpyxl")
        df_master = cls.clean_columns(df_master)
        required_cols = ['Site ID', 'Site Category', 'Site Maintainer', 'Supervisor']
        df_master = df_master[required_cols].copy()
        df_master['Site ID'] = df_master['Site ID'].apply(cls.normalize_id)
        cls.df_master_cache = df_master
        print("✅ Master 数据加载成功")
        return df_master

    @classmethod
    def add_site_category(cls, df):
        df = cls.clean_columns(df)
        for col in ['Site Category', 'FME', 'Supervisor']:
            if col not in df.columns:
                df[col] = None
        df_master = cls.load_master_data()
        if 'Site ID' not in df.columns:
            print("⚠️ 无 Site ID")
            return df
        df['Site ID'] = df['Site ID'].apply(cls.normalize_id)
        site_map = dict(zip(df_master['Site ID'], df_master['Site Category']))
        fme_map = dict(zip(df_master['Site ID'], df_master['Site Maintainer']))
        sup_map = dict(zip(df_master['Site ID'], df_master['Supervisor']))
        df['Site Category'] = df['Site ID'].map(site_map)
        df['FME'] = df['Site ID'].map(fme_map)
        df['Supervisor'] = df['Site ID'].map(sup_map)
        print(f"📊 未匹配 Site ID: {df['Site Category'].isna().sum()}")
        return df

    @classmethod
    def read_excel_data(cls, file_path=None):
        path_to_use = file_path or cls.default_file_path
        df = pd.read_excel(path_to_use, engine='openpyxl')
        df = cls.clean_columns(df)
        print(f"✅ 数据读取成功: {df.shape}")
        df = cls.add_site_category(df)
        cls.df_eflow_source = df
        return df

    @classmethod
    def extract_fields(cls, df_eflow_source=None):
        source_df = df_eflow_source if df_eflow_source is not None else cls.df_eflow_source
        if source_df is None:
            raise ValueError("请先读取Excel数据")
        required_columns = [
            'Title', 'Ticket No.', 'WO No.',
            'Site ID', 'Site Name', 'Site Category',
            'Status', 'Creator', 'Ticket Severity',
            'SLA Time', 'SLA Status',
            'Region ID', 'TRM Type', 'FME', 'Supervisor',
            'Created Time', 'Alarm Occur Time',
            'Alarm Clear Time', 'Root Cause',
            'Sub Root Cause', 'Root Cause Description', 'SLA Remain Time',
            'FO Process Detail'
        ]
        available_columns = [col for col in required_columns if col in source_df.columns]
        extracted_df = source_df[available_columns].copy()
        if 'Alarm Occur Time' in extracted_df.columns:
            extracted_df['Alarm Occur Time'] = pd.to_datetime(extracted_df['Alarm Occur Time'], errors='coerce')
        if 'Alarm Clear Time' in extracted_df.columns:
            extracted_df['Alarm Clear Time'] = pd.to_datetime(extracted_df['Alarm Clear Time'], errors='coerce')
        if 'Ticket Severity' in extracted_df.columns:
            severity_map = {'P1': 1, 'P2': 2, 'P3': 3, 'P4': 4}
            extracted_df['_severity_sort'] = (
                extracted_df['Ticket Severity'].astype(str).str.strip().str.upper()
                .map(severity_map).fillna(5)
            )
            extracted_df = extracted_df.sort_values(
                by=['_severity_sort', 'Alarm Occur Time'],
                ascending=[True, False], kind='mergesort'
            ).drop(columns=['_severity_sort'])
        extracted_df = extracted_df.reset_index(drop=True)
        extracted_df.insert(0, 'Index', range(1, len(extracted_df) + 1))
        cls.df_eflow_temp = extracted_df
        print(f"✅ 字段提取完成: {extracted_df.shape}")
        return extracted_df

    # ============================================================
    # TT Summary 计算（原 TT summary.py 功能，内存完成）
    # 直接使用原始 SLA Time 列（已包含目标时长），不额外计算
    # 计算结果列命名为 SLA Status（原 SLA Final Status）
    # ============================================================
    @classmethod
    def compute_tt_summary(cls, df_extracted):
        """
        在内存中计算 Outage Time、SLA Status、Prolong Outage，
        并返回 df_open / open_tickets / prolong_tickets / summary_df / raw_df。
        用 Ticket Severity 映射目标时长（P1=4h, P2=8h, P3=16h, P4=48h），
        保留原始 SLA Time 列不被覆盖。
        """
        df = df_extracted.copy()

        # 仅处理有 WO No. 且 Alarm Clear Time 为空的（Open tickets）
        if 'WO No.' in df.columns:
            df_open_base = df[df['WO No.'].notna()].copy()
        else:
            df_open_base = df.copy()

        if 'Alarm Clear Time' in df_open_base.columns:
            df_open = df_open_base[df_open_base['Alarm Clear Time'].isna()].copy()
        else:
            df_open = df_open_base.copy()

        # 从 Ticket Severity 计算目标时长（不覆盖原始 SLA Time）
        df_open['_SLA_Target_H'] = (
            df_open['Ticket Severity'].astype(str).str.strip().str.upper().map(SLA_MAP)
        )

        # 时间处理
        df_open['Alarm Occur Time'] = pd.to_datetime(df_open['Alarm Occur Time'], errors='coerce')
        now = pd.Timestamp.now()
        df_open['Outage Time'] = (now - df_open['Alarm Occur Time']).dt.total_seconds() / 3600

        # SLA Status（用目标时长计算百分比）
        def calc_sla_status(row):
            if pd.isna(row['_SLA_Target_H']) or pd.isna(row['Outage Time']):
                return None
            if row['_SLA_Target_H'] <= 0:
                return None
            ratio = row['Outage Time'] / row['_SLA_Target_H']
            if ratio <= 0.25:
                return "SLA<25%"
            elif ratio <= 0.5:
                return "SLA<50%"
            elif ratio <= 0.75:
                return "SLA<75%"
            elif ratio <= 1:
                return "SLA<100%"
            else:
                return "SLA>100%"

        df_open['SLA Status'] = df_open.apply(calc_sla_status, axis=1)
        df_open['Prolong Outage'] = df_open['Outage Time'].apply(lambda x: "Yes" if x > 48 else "No")

        # Raw Data 列（包含 SLA Time）
        raw_cols = [c for c in [
            'Title', 'Ticket No.', 'WO No.', 'Site ID', 'Site Name',
            'Site Category', 'Region ID', 'FME', 'Supervisor',
            'Alarm Occur Time', 'Alarm Clear Time',
            'SLA Time', 'Outage Time', 'SLA Status', 'Prolong Outage'
        ] if c in df_open.columns]
        raw_df = df_open[raw_cols].copy()

        # Summary
        non_prolong = raw_df[raw_df['Prolong Outage'] == 'No']
        summary_df = (
            non_prolong.groupby('SLA Status').size()
            .reset_index(name='Ticket Count')
        )
        summary_df['SLA Status'] = pd.Categorical(
            summary_df['SLA Status'], categories=SLA_ORDER, ordered=True
        )
        summary_df = summary_df.sort_values('SLA Status')
        total_row = pd.DataFrame({
            'SLA Status': ['Total'],
            'Ticket Count': [summary_df['Ticket Count'].sum()]
        })
        summary_df = pd.concat([summary_df, total_row], ignore_index=True)

        # 分表
        open_tickets = raw_df[raw_df['Prolong Outage'] == 'No'].copy()
        prolong_tickets = raw_df[raw_df['Prolong Outage'] == 'Yes'].copy()
        prolong_tickets = prolong_tickets.drop_duplicates(subset='Site ID', keep='first')

        return df_open, open_tickets, prolong_tickets, summary_df, raw_df

    # ============================================================
    # 清理旧文件
    # ============================================================
    @classmethod
    def clean_old_files(cls, output_dir, base_filename, extensions=('.xlsx', '.png')):
        """清理旧文件，保留最新一份。支持多扩展名（默认 .xlsx 和 .png）"""
        if not output_dir:
            output_dir = os.getcwd()
        for ext in extensions:
            search_pattern = os.path.join(output_dir, f"*{base_filename}*{ext}")
            files = glob.glob(search_pattern)
            if len(files) <= 1:
                continue
            files.sort(key=os.path.getmtime)
            for file_path in files[:-1]:
                try:
                    os.remove(file_path)
                    print(f"🗑️ 已删除旧文件: {os.path.basename(file_path)}")
                except OSError as e:
                    print(f"❌ 删除文件失败 {file_path}: {e}")

    # ============================================================
    # 步骤A：生成 Hourly Report（Processed Data / Open / Broken）
    # ============================================================
    @classmethod
    def write_hourly_report(cls, df_extracted, output_dir=None,
                            base_filename="Liberia Orange Site Down hourly Report"):
        """生成 Hourly Report Excel（3 sheets: Processed Data / Open / Broken）"""
        current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_filename = f"{base_filename}_{current_time}.xlsx"
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, output_filename)
        else:
            output_path = output_filename

        header_font = Font(bold=True, color="FFFFFF", size=12)
        header_fill = PatternFill(start_color="00BFFF", end_color="00BFFF", fill_type="solid")
        border = Border(left=Side(style="thin"), right=Side(style="thin"),
                        top=Side(style="thin"), bottom=Side(style="thin"))
        header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        data_align = Alignment(horizontal="left", vertical="center", wrap_text=True)
        sla_col_width_map = {1: 8, 2: 35, 3: 15, 4: 15, 5: 15}

        # Open / Broken 筛选
        if 'WO No.' in df_extracted.columns:
            df_base = df_extracted[df_extracted['WO No.'].notna()].copy()
        else:
            df_base = pd.DataFrame(columns=df_extracted.columns)

        if 'Alarm Clear Time' in df_base.columns:
            df_open = df_base[df_base['Alarm Clear Time'].isna()].copy()
        else:
            df_open = pd.DataFrame(columns=df_extracted.columns)

        if 'Alarm Clear Time' in df_base.columns and 'SLA Status' in df_base.columns:
            df_broken = df_base[
                df_base['Alarm Clear Time'].notna() &
                (df_base['SLA Status'].astype(str).str.strip().str.lower() == 'failed')
            ].copy()
        else:
            df_broken = pd.DataFrame(columns=df_extracted.columns)

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df_extracted.to_excel(writer, index=False, sheet_name='Processed Data')
            df_open.to_excel(writer, index=False, sheet_name='Open')
            df_broken.to_excel(writer, index=False, sheet_name='Broken')

            wb = writer.book
            for sheet_name in ['Processed Data', 'Open', 'Broken']:
                ws = wb[sheet_name]
                ws.freeze_panes = 'A2'
                ws.row_dimensions[1].height = 40
                max_row = ws.max_row
                max_col = ws.max_column

                sla_status_col = None
                for cell in ws[1]:
                    if cell.value == 'SLA Status':
                        sla_status_col = cell.column
                        break

                for row_num in range(1, max_row + 1):
                    is_header = (row_num == 1)
                    for col_num in range(1, max_col + 1):
                        cell = ws.cell(row=row_num, column=col_num)
                        cell.border = border
                        if is_header:
                            cell.font = header_font
                            cell.fill = header_fill
                            cell.alignment = header_align
                            col_letter = get_column_letter(col_num)
                            if col_num in sla_col_width_map:
                                ws.column_dimensions[col_letter].width = sla_col_width_map[col_num]
                            else:
                                val_len = len(str(cell.value)) if cell.value else 10
                                ws.column_dimensions[col_letter].width = min(val_len * 1.2 + 2, 22)
                        else:
                            cell.alignment = data_align
                            ws.row_dimensions[row_num].height = 25
                            if sla_status_col and col_num == sla_status_col:
                                cv = str(cell.value).strip().lower() if cell.value else ""
                                if cv == 'failed':
                                    cell.fill = PatternFill(start_color='FF6666', end_color='FF6666', fill_type='solid')
                                    cell.font = Font(color="FFFFFF")
                                elif cv == 'pass':
                                    cell.fill = PatternFill(start_color='00FF00', end_color='00FF00', fill_type='solid')
                                elif cv == 'within sla':
                                    cell.fill = PatternFill(start_color='40E0D0', end_color='40E0D0', fill_type='solid')

        print(f"✅ Hourly Report 已保存: {output_path}")
        cls.clean_old_files(output_dir, base_filename)
        return output_path, df_open

    # ============================================================
    # 步骤A2：生成 8 hours Report
    # ============================================================
    @classmethod
    def write_8hours_report(cls, df_extracted, output_dir=None,
                            base_filename="Liberia Orange Site Down 8 hours Report"):
        """从 Hourly Report 数据中过滤 Alarm Occur Time 在最近8小时内的工单，
        计算 MTTR，生成 Excel + 图片"""
        from datetime import timedelta
        current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_filename = f"{base_filename}_{current_time}.xlsx"
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, output_filename)
        else:
            output_path = output_filename

        now = pd.Timestamp.now()
        cutoff = now - timedelta(hours=8)

        df = df_extracted.copy()
        df['Alarm Occur Time'] = pd.to_datetime(df['Alarm Occur Time'], errors='coerce')
        df_8h = df[(df['Alarm Occur Time'] >= cutoff) & (df['Alarm Occur Time'] <= now)].copy()

        # 计算 MTTR（Alarm Occur Time 到 Alarm Clear Time 的时间差）
        def calc_mttr(row):
            occur = row.get('Alarm Occur Time')
            clear = row.get('Alarm Clear Time')
            if pd.isna(occur) or pd.isna(clear):
                return ""
            delta = clear - occur
            total_seconds = int(delta.total_seconds())
            if total_seconds < 0:
                return ""
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours:02d}h{minutes:02d}m"

        df_8h['MTTR'] = df_8h.apply(calc_mttr, axis=1)

        # 保留指定列
        keep_cols = [
            'Ticket No.', 'WO No.', 'Title', 'Site Name', 'Site Category',
            'Ticket Severity', 'Region ID', 'Alarm Occur Time',
            'Alarm Clear Time', 'SLA Time', 'MTTR', 'SLA Status'
        ]
        available = [c for c in keep_cols if c in df_8h.columns]
        df_8h = df_8h[available].copy()

        # 按 Alarm Occur Time 降序排序
        if 'Alarm Occur Time' in df_8h.columns:
            df_8h = df_8h.sort_values(by='Alarm Occur Time', ascending=False).reset_index(drop=True)

        # 写入 Excel
        header_font = Font(bold=True, color="FFFFFF", size=12)
        header_fill = PatternFill(start_color="00BFFF", end_color="00BFFF", fill_type="solid")
        border = Border(left=Side(style="thin"), right=Side(style="thin"),
                        top=Side(style="thin"), bottom=Side(style="thin"))
        header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        data_align = Alignment(horizontal="left", vertical="center", wrap_text=True)

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df_8h.to_excel(writer, index=False, sheet_name='8 Hours Report')
            wb = writer.book
            ws = wb['8 Hours Report']
            ws.freeze_panes = 'A2'
            ws.row_dimensions[1].height = 40
            max_row = ws.max_row
            max_col = ws.max_column

            sla_status_col = None
            for cell in ws[1]:
                if cell.value == 'SLA Status':
                    sla_status_col = cell.column
                    break

            for row_num in range(1, max_row + 1):
                is_header = (row_num == 1)
                for col_num in range(1, max_col + 1):
                    cell = ws.cell(row=row_num, column=col_num)
                    cell.border = border
                    if is_header:
                        cell.font = header_font
                        cell.fill = header_fill
                        cell.alignment = header_align
                        col_letter = get_column_letter(col_num)
                        val_len = len(str(cell.value)) if cell.value else 10
                        ws.column_dimensions[col_letter].width = min(val_len * 1.2 + 2, 25)
                    else:
                        cell.alignment = data_align
                        ws.row_dimensions[row_num].height = 25
                        if sla_status_col and col_num == sla_status_col:
                            cv = str(cell.value).strip().lower() if cell.value else ""
                            if cv == 'failed':
                                cell.fill = PatternFill(start_color='FF6666', end_color='FF6666', fill_type='solid')
                                cell.font = Font(color="FFFFFF")
                            elif cv == 'pass':
                                cell.fill = PatternFill(start_color='00FF00', end_color='00FF00', fill_type='solid')
                            elif cv == 'within sla':
                                cell.fill = PatternFill(start_color='40E0D0', end_color='40E0D0', fill_type='solid')

        print(f"✅ 8 Hours Report 已保存: {output_path}")
        cls.clean_old_files(output_dir, base_filename)

        # 生成图片
        img_path = None
        img_name = f"Liberia Orange Site Down 8 hours Report.png"
        if output_dir:
            img_path = os.path.join(output_dir, img_name)
        else:
            img_path = img_name
        # 生成图片前过滤 WO No. 为空的行
        df_8h_img = df_8h.copy()
        if 'WO No.' in df_8h_img.columns:
            df_8h_img = df_8h_img[df_8h_img['WO No.'].notna() & (df_8h_img['WO No.'].astype(str).str.strip() != '')].copy()
        cls.df_to_image(df_8h_img, img_path,
                        title=f"Liberia Orange Site Down 8 hours Report\n{current_time}",
                        highlight_sla=True)
        print(f"✅ 8 Hours Report 图片已保存: {img_path}")

        return output_path, img_path, df_8h

    # ============================================================
    # 步骤B：生成 TT Summary Report（Summary / Open Tickets / Prolong Tickets / Raw Data）
    # ============================================================
    @classmethod
    def write_summary_report(cls, open_tickets, prolong_tickets, summary_df, raw_df,
                              output_dir=None,
                              base_filename="Liberia Orange TT Summary Report"):
        """生成 TT Summary Report Excel（4 sheets）+ 统一 SLA 着色"""
        current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_filename = f"{base_filename}_{current_time}.xlsx"
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, output_filename)
        else:
            output_path = output_filename

        header_font = Font(bold=True, color="FFFFFF", size=12)
        header_fill = PatternFill(start_color="00BFFF", end_color="00BFFF", fill_type="solid")
        border = Border(left=Side(style="thin"), right=Side(style="thin"),
                        top=Side(style="thin"), bottom=Side(style="thin"))
        header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        data_align = Alignment(horizontal="left", vertical="center", wrap_text=True)
        bold_font = Font(bold=True)

        sla_fill_cache = {}
        for label, hex_color in SLA_COLOR_MAP.items():
            sla_fill_cache[label] = PatternFill(start_color=hex_color, end_color=hex_color, fill_type="solid")
        red_fill = sla_fill_cache["SLA>100%"]
        summary_header_fill = PatternFill(start_color="ADD8E6", end_color="ADD8E6", fill_type="solid")

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            summary_df.to_excel(writer, index=False, sheet_name='Summary')
            open_tickets.to_excel(writer, index=False, sheet_name='Open Tickets')
            prolong_tickets.to_excel(writer, index=False, sheet_name='Prolong Tickets')
            raw_df.to_excel(writer, index=False, sheet_name='Raw Data')

            wb = writer.book
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                ws.freeze_panes = 'A2'
                ws.row_dimensions[1].height = 40
                max_row = ws.max_row
                max_col = ws.max_column

                sla_status_col = None
                for cell in ws[1]:
                    if cell.value == 'SLA Status':
                        sla_status_col = cell.column
                        break

                for row_num in range(1, max_row + 1):
                    is_header = (row_num == 1)
                    for col_num in range(1, max_col + 1):
                        cell = ws.cell(row=row_num, column=col_num)
                        cell.border = border
                        if is_header:
                            cell.font = header_font
                            if sheet_name == 'Summary':
                                cell.fill = summary_header_fill
                            else:
                                cell.fill = header_fill
                            cell.alignment = header_align
                            col_letter = get_column_letter(col_num)
                            if col_num <= 1:
                                ws.column_dimensions[col_letter].width = 8
                            elif col_num == 2:
                                ws.column_dimensions[col_letter].width = 35
                            elif col_num <= 5:
                                ws.column_dimensions[col_letter].width = 15
                            else:
                                val_len = len(str(cell.value)) if cell.value else 10
                                ws.column_dimensions[col_letter].width = min(val_len * 1.2 + 2, 22)
                        else:
                            cell.alignment = data_align
                            ws.row_dimensions[row_num].height = 25

                            if sla_status_col:
                                sla_val = str(ws.cell(row=row_num, column=sla_status_col).value).strip() if ws.cell(row=row_num, column=sla_status_col).value else ""
                                if sla_val == "SLA>100%":
                                    cell.fill = red_fill
                                    cell.font = Font(color="FFFFFF", bold=True)
                                elif sla_val in sla_fill_cache:
                                    if col_num == sla_status_col:
                                        cell.fill = sla_fill_cache[sla_val]
                                        cell.font = Font(bold=True)

                if sheet_name == 'Summary':
                    for row in ws.iter_rows(min_row=2, max_col=1):
                        cell = row[0]
                        val = cell.value
                        if val in sla_fill_cache:
                            cell.fill = sla_fill_cache[val]
                            if val == "SLA>100%":
                                cell.font = Font(bold=True, color="FFFFFF")
                        if val == "Total":
                            for c in ws[cell.row]:
                                c.font = bold_font

        print(f"✅ TT Summary Report 已保存: {output_path}")
        cls.clean_old_files(output_dir, base_filename)
        return output_path

    # ============================================================
    # matplotlib 渲染图片（替代 win32com，<2秒）
    # ============================================================
    @classmethod
    def df_to_image(cls, df, image_path=None, dpi=120, base_fontsize=9,
                    title=None, highlight_sla=True):
        """
        从 DataFrame 直接用 matplotlib 渲染美观表格图片。
        highlight_sla=True 时，SLA Status = SLA>100% 整行标红。
        """
        if image_path is None:
            image_path = "table.png"

        df_clean = df.dropna(how='all').dropna(axis=1, how='all').copy()
        rows, cols = df_clean.shape
        if rows == 0 or cols == 0:
            fig, ax = plt.subplots(figsize=(4, 1), dpi=dpi)
            ax.text(0.5, 0.5, 'No Data', ha='center', va='center', fontsize=14, color='gray')
            ax.axis('off')
            plt.savefig(image_path, dpi=dpi, bbox_inches='tight', pad_inches=0.1,
                        facecolor='white', format='png')
            plt.close(fig)
            return image_path

        # 找到 SLA Status 列
        sla_status_idx = None
        if 'SLA Status' in df_clean.columns:
            sla_status_idx = df_clean.columns.get_loc('SLA Status')

        # 数值列圆整（Outage Time 保留 1 位小数）
        numeric_cols = df_clean.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            if 'Outage' in col:
                df_clean[col] = df_clean[col].round(1)

        # 文本换行
        def wrap_cell(text, width=22):
            if pd.isna(text):
                return ""
            text = str(text).strip()
            if len(text) <= width:
                return text
            return '\n'.join(textwrap.wrap(text, width=width, break_long_words=False))

        cell_data = []
        for i in range(rows):
            row_data = []
            for j in range(cols):
                row_data.append(wrap_cell(df_clean.iloc[i, j], 22))
            cell_data.append(row_data)

        col_labels = [wrap_cell(str(c), 16) for c in df_clean.columns]

        # 动态尺寸（紧凑布局）
        fig_width = max(10, cols * 1.9)
        fig_height = max(2.5, rows * 0.30 + 1.0)
        if title:
            fig_height += 0.5

        plt.rcParams['font.sans-serif'] = ['Segoe UI', 'Arial', 'SimHei', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False

        fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=dpi)
        ax.axis('off')
        fig.patch.set_facecolor('#FAFBFC')

        if title:
            ax.set_title(title, fontsize=base_fontsize + 5, fontweight='bold',
                         color='#1B3A5C', pad=10, fontfamily='Segoe UI')

        table = ax.table(
            cellText=cell_data,
            colLabels=col_labels,
            cellLoc='left',
            loc='center',
            bbox=[0.006, 0.004, 0.994, 0.994]
        )

        table.auto_set_font_size(False)
        table.set_fontsize(base_fontsize)
        table.scale(1, 1.15)

        # ---- 表头样式（深蓝渐变 + 底部阴影） ----
        header_fp = FontProperties(weight='bold', size=base_fontsize + 1)
        for j in range(cols):
            cell = table[(0, j)]
            cell.set_facecolor('#1B5E8A')
            cell.set_text_props(fontproperties=header_fp, color='white', ha='center', va='center')
            cell.set_edgecolor('#0D3B5E')
            cell.set_linewidth(0.8)
            cell.set_height(0.01)

        # ---- 数据行样式（斑马纹 + 圆角感） ----
        for i in range(1, rows + 1):
            is_red_row = False
            if highlight_sla and sla_status_idx is not None:
                val = str(df_clean.iloc[i - 1, sla_status_idx]).strip()
                if val == "SLA>100%":
                    is_red_row = True

            for j in range(cols):
                cell = table[(i, j)]
                cell.set_text_props(ha='left', va='center', wrap=True, fontsize=base_fontsize)
                cell.set_edgecolor('#E8E8E8')
                cell.set_linewidth(0.3)
                cell.set_height(0.01)

                if is_red_row:
                    cell.set_facecolor('#FF8888')
                    cell.set_text_props(color='#8B0000', weight='bold', fontsize=base_fontsize)
                else:
                    bg = '#F5F8FC' if i % 2 == 0 else '#FFFFFF'
                    cell.set_facecolor(bg)
                    cell.set_text_props(color='#333333', fontsize=base_fontsize)

                # SLA Status 列着色（非红行时）
                if not is_red_row and sla_status_idx is not None and j == sla_status_idx:
                    sla_val = str(df_clean.iloc[i - 1, sla_status_idx]).strip()
                    if sla_val in SLA_COLOR_MAP:
                        cell.set_facecolor('#' + SLA_COLOR_MAP[sla_val])
                        cell.set_text_props(ha='center', weight='bold', color='#333333', fontsize=base_fontsize)
                    else:
                        sv = sla_val.lower()
                        if sv == 'failed':
                            cell.set_facecolor('#FF8888')
                            cell.set_text_props(color='#8B0000', ha='center', weight='bold', fontsize=base_fontsize)
                        elif sv == 'pass':
                            cell.set_facecolor('#90EE90')
                            cell.set_text_props(ha='center', fontsize=base_fontsize)
                        elif 'within sla' in sv:
                            cell.set_facecolor('#87CEEB')
                            cell.set_text_props(ha='center', fontsize=base_fontsize)

        # 原子写入：先写临时 png 再 os.replace 覆盖，遇文件锁时固定间隔重试，
        # 避免直接写目标路径触发 PermissionError（WPS云同步/Defender 可能锁定 30~60s）。
        final_path = str(image_path)
        last_err = None
        _max_attempts = 30
        _wait_sec = 3
        for attempt in range(_max_attempts):
            tmp_path = f"{final_path}.{os.getpid()}.{attempt}.tmp.png"
            try:
                plt.savefig(tmp_path, dpi=dpi, bbox_inches='tight', pad_inches=0.05,
                            facecolor='#FAFBFC', edgecolor='none', format='png')
                os.replace(tmp_path, final_path)
                break
            except (PermissionError, OSError) as e:
                last_err = e
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except OSError:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] df_to_image: exception swallowed", exc_info=True)
                    pass
                if attempt < _max_attempts - 1:
                    print(f"⚠️ 图片写入被占用({attempt + 1}/{_max_attempts})，等待{_wait_sec}s: {os.path.basename(final_path)}")
                    time.sleep(_wait_sec)
                else:
                    raise
        plt.close(fig)
        print(f"✅ 图片生成: {final_path} ({rows}行×{cols}列)")
        return final_path

    # ============================================================
    # 生成所有 Summary 图片
    # ============================================================
    @classmethod
    def generate_summary_images(cls, summary_df, open_tickets, prolong_tickets, output_dir):
        """用 matplotlib 生成 3 张图片，全程不依赖 Excel"""
        images = []
        os.makedirs(output_dir, exist_ok=True)

        p1 = os.path.join(output_dir, "Summary.png")
        cls.df_to_image(summary_df, p1, title="TT Summary", highlight_sla=False)
        images.append(p1)

        p2 = os.path.join(output_dir, "Open Tickets.png")
        cls.df_to_image(open_tickets, p2, title="Open Tickets", highlight_sla=True)
        images.append(p2)

        p3 = os.path.join(output_dir, "Prolong Tickets.png")
        cls.df_to_image(prolong_tickets, p3, title="Prolong Tickets", highlight_sla=True)
        images.append(p3)

        return images

    # ============================================================
    # 完整流程
    # ============================================================
    @classmethod
    def process_all_steps(cls, file_path=None, output_dir=None,
                          send_email=True, generate_image=True):
        """完整流程：读取 → 提取 → Hourly Report → Summary → 图片 → 发邮件"""
        total_start = time.time()
        start_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("🚀 开始处理报告...")
        print(f"⏰ 开始时间: {start_time_str}")

        # 1. 读取
        step_start = time.time()
        print("\n📌 步骤1: 读取Excel文件...")
        df_source = cls.read_excel_data(file_path)
        print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 2. 提取字段
        step_start = time.time()
        print("\n📌 步骤2: 提取字段...")
        df_extracted = cls.extract_fields()
        print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 3. 生成 Hourly Report（Processed Data / Open / Broken）
        step_start = time.time()
        print("\n📌 步骤3: 生成 Hourly Report...")
        hourly_file, df_open_hourly = cls.write_hourly_report(
            df_extracted, output_dir=output_dir)
        print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 3.5 生成 8 hours Report
        step_start = time.time()
        print("\n📌 步骤3.5: 生成 8 Hours Report...")
        eight_hour_file, eight_hour_img, df_8h = cls.write_8hours_report(
            df_extracted, output_dir=output_dir)
        print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 4. TT Summary 计算（内存中完成）
        step_start = time.time()
        print("\n📌 步骤4: 计算 SLA Status / Summary...")
        df_open, open_tickets, prolong_tickets, summary_df, raw_df = cls.compute_tt_summary(df_extracted)
        print(f"   Open Tickets: {len(open_tickets)}, Prolong: {len(prolong_tickets)}")
        print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 5. 生成 TT Summary Report（Summary / Open Tickets / Prolong Tickets / Raw Data）
        step_start = time.time()
        print("\n📌 步骤5: 生成 TT Summary Report...")
        summary_file = cls.write_summary_report(
            open_tickets, prolong_tickets, summary_df, raw_df,
            output_dir=output_dir)
        print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 6. 生成图片（matplotlib，<2秒）
        image_paths = []
        if generate_image:
            step_start = time.time()
            print("\n📌 步骤6: 生成图片（matplotlib）...")
            img_dir = output_dir or os.getcwd()
            image_paths = cls.generate_summary_images(summary_df, open_tickets, prolong_tickets, img_dir)
            print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 7. 发邮件
        if send_email:
            step_start = time.time()
            print("\n📌 步骤7: 发送邮件...")
            try:
                EmailSender.send_report_email(summary_file, summary_df, image_paths=image_paths)
            except Exception as e:
                print(f"❌ 邮件发送失败: {e}")
            print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        total_elapsed = time.time() - total_start
        end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n🎉 全部完成!")
        print(f"⏰ 开始时间: {start_time_str}")
        print(f"⏰ 结束时间: {end_time_str}")
        print(f"⏱️ 总用时: {total_elapsed:.2f}s")
        print(f"📁 Hourly Report: {hourly_file}")
        print(f"📁 Summary Report: {summary_file}")
        for p in image_paths:
            print(f"🖼️  图片: {p}")

        return df_source, df_extracted, hourly_file, summary_file, image_paths, eight_hour_file, eight_hour_img


# ==================== 运行入口 ====================
if __name__ == "__main__":
    try:
        result = ExcelDataProcessor.process_all_steps(
            send_email=False,
            generate_image=True
        )
        df_source, df_extracted, hourly_file, summary_file, image_paths, eight_hour_file, eight_hour_img = result
        print(f"\n📊 执行结果:")
        print(f"- 原始数据: {df_source.shape}")
        print(f"- 提取数据: {df_extracted.shape}")
        print(f"- Hourly Report: {hourly_file}")
        print(f"- 8 Hours Report: {eight_hour_file}")
        print(f"- 8 Hours Report 图片: {eight_hour_img}")
        print(f"- Summary Report: {summary_file}")
        print(f"- 生成图片: {image_paths}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ 处理过程出错: {e}")

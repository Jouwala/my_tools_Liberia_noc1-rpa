"""
Daily Availability KPI 图表生成脚本
功能：
1. 从FTP下载最新的 Daily_Aailability_KPI.xlsx
2. 根据仪表板样式生成各sheet的折线图
3. 上传图片到FTP服务器
"""
import os
import time
import json
import ftplib
import warnings
import subprocess
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch
import numpy as np

warnings.filterwarnings("ignore")

# ============================================================
# 配置参数
# ============================================================
FTP_DOWNLOAD_HOST = '192.168.100.19'
FTP_DOWNLOAD_PORT = 21
FTP_DOWNLOAD_USER = 'FINEBI'
FTP_DOWNLOAD_PASS = 'DX'
FTP_DOWNLOAD_PATH = '/webroot/WEB-INF/schedule/MS Network Availability Daily Report/'

FTP_UPLOAD_HOST = '192.168.100.19'
FTP_UPLOAD_PORT = 21
FTP_UPLOAD_USER = 'ZTEEMS'
FTP_UPLOAD_PASS = 'DX'
FTP_UPLOAD_PATH = '/01_RPA/LBR_Tools/KPI/RAN/ORANGE'

LOCAL_DIR = r'D:\01_RPA\Task\ORANGE\Daily_Aailability'
TARGET_SHEETS = ['Availability-NW', 'Availability-Regular', 'Availability-COOL', 'Availability-ERA']

# 仪表板样式颜色映射
COLOR_MAP = {
    '2G ALL': '#2F5496',
    '3G ALL': '#ED7D31',
    'FDD ALL': '#70AD47',
    'TDD ALL': '#FF0000',
    '2G Regular': '#2F5496',
    '3G Regular': '#ED7D31',
    '4G FDD Regular': '#70AD47',
    '2G Cooli': '#2F5496',
    '3G Cooli': '#ED7D31',
    '2G ERA': '#2F5496',
    '4G FDD ERA': '#70AD47',
}

TARGET_VALUE = 0.9965  # 99.65% 目标线
BG_COLOR = '#E8F0FE'
TITLE_COLOR = '#2F5496'
GRID_COLOR = '#C5C5C5'
MAX_LABEL_COLOR = '#FF0000'
MIN_LABEL_COLOR = '#ED7D31'

# ============================================================
# 1. FTP下载最新文件
# ============================================================
def download_latest_file():
    """从FTP下载最新的 Daily_Aailability_KPI.xlsx"""
    print("=" * 60)
    print("Step 1: 从FTP下载最新文件")
    print("=" * 60)

    ftp = ftplib.FTP()
    ftp.connect(FTP_DOWNLOAD_HOST, FTP_DOWNLOAD_PORT, timeout=30)
    ftp.login(FTP_DOWNLOAD_USER, FTP_DOWNLOAD_PASS)
    print(f"已连接到 {FTP_DOWNLOAD_HOST}")

    ftp.cwd(FTP_DOWNLOAD_PATH)
    items = ftp.nlst()
    print(f"远程目录内容: {items}")

    # 递归进入子目录直到找到xlsx文件
    current_items = items
    while True:
        date_dirs = sorted([d for d in current_items if not d.endswith('.xlsx') and not d.endswith('.xls')], reverse=True)
        if date_dirs:
            latest_dir = date_dirs[0]
            print(f"进入子目录: {latest_dir}")
            ftp.cwd(latest_dir)
            current_items = ftp.nlst()
        else:
            break

    files = current_items
    print(f"文件列表: {files}")

    # 查找 Daily_Aailability_KPI.xlsx 文件
    kpi_files = [f for f in files if 'Daily_Aailability_KPI' in f and f.endswith('.xlsx')]
    if not kpi_files:
        raise FileNotFoundError(f"未找到 Daily_Aailability_KPI.xlsx 文件，远程文件: {files}")

    latest_file = kpi_files[0]

    os.makedirs(LOCAL_DIR, exist_ok=True)
    local_path = os.path.join(LOCAL_DIR, latest_file)

    with open(local_path, 'wb') as f:
        ftp.retrbinary(f'RETR {latest_file}', f.write)

    ftp.quit()
    print(f"下载完成: {local_path} ({os.path.getsize(local_path)} bytes)")
    return local_path


# ============================================================
# 2. 读取Excel数据并生成图表
# ============================================================
def read_sheet_data(filepath, sheet_name):
    """读取sheet数据并处理日期前向填充"""
    df = pd.read_excel(filepath, sheet_name=sheet_name, engine='openpyxl')
    # 前向填充日期列
    df['Begin Time'] = df['Begin Time'].ffill()
    # 确保日期列为字符串
    df['Begin Time'] = df['Begin Time'].astype(str)
    return df


def generate_chart(df, sheet_name, output_dir):
    """根据仪表板样式生成折线图"""
    print(f"\n  生成图表: {sheet_name}")

    # 获取所有cell group
    cell_groups = df['Cell Group'].unique().tolist()

    # Pivot为宽表：日期为index，cell group为列
    pivot_df = df.pivot_table(index='Begin Time', columns='Cell Group', values='Cell Availability')
    dates = pivot_df.index.tolist()
    n_dates = len(dates)
    print(f"  日期数: {n_dates}, Cell Groups: {cell_groups}")

    # 设置画布
    fig, ax = plt.subplots(figsize=(14, 5.5))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    # 绘制每条线（使用日期索引位置）
    for cg in cell_groups:
        values = pivot_df[cg].values
        color = COLOR_MAP.get(cg, '#333333')
        ax.plot(range(n_dates), values, color=color, linewidth=1.2, label=cg, alpha=0.85)

    # 目标线 (红色虚线)
    ax.axhline(y=TARGET_VALUE, color='#FF0000', linestyle='--', linewidth=1.0, alpha=0.7)
    ax.text(n_dates - 1, TARGET_VALUE + 0.003, f'T:{TARGET_VALUE*100:.2f}%',
            color=MAX_LABEL_COLOR, fontsize=8, ha='right', fontweight='bold')

    # 标注最大值和最小值（基于pivot后的数据）
    all_values = pivot_df.values
    max_pos = np.unravel_index(np.nanargmax(all_values), all_values.shape)
    min_pos = np.unravel_index(np.nanargmin(all_values), all_values.shape)
    max_val = all_values[max_pos]
    min_val = all_values[min_pos]
    max_x, max_y_idx = max_pos[1], max_pos[0]
    min_x, min_y_idx = min_pos[1], min_pos[0]

    ax.annotate(f'{max_val*100:.2f}%',
                xy=(max_x, max_val),
                xytext=(max_x, max_val + 0.015),
                fontsize=7.5, color=MAX_LABEL_COLOR, ha='center', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=MAX_LABEL_COLOR, lw=0.8))

    ax.annotate(f'{min_val*100:.2f}%',
                xy=(min_x, min_val),
                xytext=(min_x, min_val - 0.02),
                fontsize=7.5, color=MIN_LABEL_COLOR, ha='center', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=MIN_LABEL_COLOR, lw=0.8))

    # Y轴设置
    y_min = max(0.60, min_val - 0.03)
    y_max = min(1.02, max_val + 0.03)
    ax.set_ylim(y_min, y_max)
    ax.set_ylabel('Cell Availability', fontsize=9, color='#333333')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x*100:.2f}%'))
    ax.tick_params(axis='y', labelsize=8, colors='#333333')

    # X轴设置（基于日期索引）
    tick_interval = max(1, n_dates // 10)
    tick_positions = list(range(0, n_dates, tick_interval))
    tick_labels = [dates[i] for i in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, rotation=0, fontsize=7, ha='center')
    ax.tick_params(axis='x', colors='#333333')

    # 网格线
    ax.grid(axis='y', linestyle='--', color=GRID_COLOR, linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)

    # 边框
    for spine in ax.spines.values():
        spine.set_color('#B0B0B0')
        spine.set_linewidth(0.5)

    # 标题
    ax.set_title(sheet_name, fontsize=13, fontweight='bold', color=TITLE_COLOR, pad=12)

    # 图例（底部居中）
    ax.legend(loc='lower center', bbox_to_anchor=(0.5, -0.18),
              ncol=len(cell_groups), fontsize=7.5, frameon=False,
              columnspacing=1.5, handletextpad=0.5)

    # 调整布局
    plt.tight_layout()

    # 保存图片
    output_path = os.path.join(output_dir, f'{sheet_name}.png')
    fig.savefig(output_path, dpi=150, bbox_inches='tight',
                facecolor=BG_COLOR, edgecolor='none',
                pil_kwargs={'quality': 95})
    plt.close(fig)
    print(f"  已保存: {output_path}")
    return output_path


# ============================================================
# 3. FTP上传
# ============================================================
def upload_files(file_paths):
    """上传图片到FTP服务器"""
    print("\n" + "=" * 60)
    print("Step 3: 上传图片到FTP")
    print("=" * 60)

    ftp = ftplib.FTP()
    ftp.connect(FTP_UPLOAD_HOST, FTP_UPLOAD_PORT, timeout=30)
    ftp.login(FTP_UPLOAD_USER, FTP_UPLOAD_PASS)
    print(f"已连接到 {FTP_UPLOAD_HOST}")

    # 确保目录存在
    try:
        ftp.cwd(FTP_UPLOAD_PATH)
    except ftplib.error_perm:
        # 逐级创建目录
        parts = FTP_UPLOAD_PATH.strip('/').split('/')
        current = ''
        for part in parts:
            current += f'/{part}'
            try:
                ftp.cwd(current)
            except ftplib.error_perm:
                ftp.mkd(current)
                ftp.cwd(current)
    print(f"当前目录: {FTP_UPLOAD_PATH}")

    for fpath in file_paths:
        fname = os.path.basename(fpath)
        with open(fpath, 'rb') as f:
            ftp.storbinary(f'STOR {fname}', f)
        print(f"  已上传: {fname} ({os.path.getsize(fpath)} bytes)")

    ftp.quit()
    print("上传完成!")


# ============================================================
# 4. 微信通知（通过 OpenClaw CLI）
# ============================================================
OPENCLAW_CLI = r'C:\Program Files\nodejs\node.exe'
OPENCLAW_DIST = r'C:\Users\ZTEEMS\AppData\Roaming\npm\node_modules\openclaw\dist\index.js'
WECHAT_CHANNEL = 'openclaw-weixin'
WECHAT_ACCOUNT = 'b5e72106a879-im-bot'
WECHAT_TARGET = 'o9cq800iVTuT3Q2Rfe2FAYwL9fzw@im.wechat'

def send_wechat_notification(success, uploaded_count=0, elapsed=0, error_msg=''):
    """通过 OpenClaw CLI 发送微信通知"""
    try:
        if success:
            msg = f"Daily Availability 图表生成完成\n生成 {uploaded_count} 张图表，已上传FTP\n耗时 {elapsed:.1f} 秒"
        else:
            msg = f"Daily Availability 图表生成失败\n错误: {error_msg}"

        cmd = [
            OPENCLAW_CLI, OPENCLAW_DIST,
            'message', 'send',
            '--channel', WECHAT_CHANNEL,
            '--account', WECHAT_ACCOUNT,
            '--target', WECHAT_TARGET,
            '--message', msg
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 or 'Sent via' in result.stdout:
            print(f"微信通知已发送: {msg}")
        else:
            print(f"微信通知发送失败: {result.stderr}")
    except Exception as e:
        print(f"微信通知发送失败: {e}")


# ============================================================
# 主函数
# ============================================================
def main():
    start_time = time.time()
    print(f"\n{'='*60}")
    print("Daily Availability KPI 图表生成")
    print(f"{'='*60}\n")

    try:
        # Step 1: 下载
        xlsx_path = download_latest_file()

        # Step 2: 生成图表
        print("\n" + "=" * 60)
        print("Step 2: 生成图表")
        print("=" * 60)

        output_dir = LOCAL_DIR
        uploaded_files = []

        for sheet_name in TARGET_SHEETS:
            print(f"\n处理 Sheet: {sheet_name}")
            try:
                df = read_sheet_data(xlsx_path, sheet_name)
                print(f"  数据行数: {len(df)}, 列: {list(df.columns)}")
                img_path = generate_chart(df, sheet_name, output_dir)
                uploaded_files.append(img_path)
            except Exception as e:
                print(f"  错误: {e}")

        # Step 3: 上传
        if uploaded_files:
            upload_files(uploaded_files)

        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"完成! 总耗时: {elapsed:.1f} 秒")
        print(f"{'='*60}")

        # Step 4: 微信通知
        send_wechat_notification(True, len(uploaded_files), elapsed)

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n执行失败: {e}")
        send_wechat_notification(False, error_msg=str(e))


if __name__ == '__main__':
    main()

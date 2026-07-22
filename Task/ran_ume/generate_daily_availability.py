# -*- coding: utf-8 -*-
"""
Daily Availability KPI 生成脚本

功能：
1. 从 ran_ume/ran_kpi_202606.sqlite3 数据库读取 OLIB Network KPIs 数据
2. 提取 Cell Availability 指标，生成 Daily_Aailability_KPI.xlsx
3. 参考 generate_charts_v2.py 的样式生成折线图 PNG
4. 输出文件保存在 eflow/ 目录下

配置说明：
- AVAILABILITY_METRICS: 指定每个表用于表示可用性的列名；为空则自动检测
- CATEGORY_PATTERNS: 根据 Group 列值将数据分到不同 Sheet
"""

import os
import sys
import time
import re
import sqlite3
import warnings
import argparse
from ftplib import FTP, error_perm

warnings.filterwarnings("ignore")

try:
    import pandas as pd
    import openpyxl
except ImportError as e:
    print(f"[ERROR] 缺少依赖: {e}")
    print("请先安装：pip install pandas openpyxl matplotlib")
    sys.exit(1)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# ============================================================
# 配置
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)  # eflow/
DB_PATH = os.path.join(SCRIPT_DIR, "ran_kpi_202606.sqlite3")
OUTPUT_EXCEL = os.path.join(SCRIPT_DIR, "Daily_Aailability_KPI.xlsx")
OUTPUT_DIR = SCRIPT_DIR

TARGET_SHEETS = ['Availability-NW', 'Availability-Regular', 'Availability-COOL', 'Availability-ERA']

# 数据库表到网络类型的映射
TECH_MAP = {
    "2G_OLIB_Network_KPIs": "2G",
    "3G_OLIB_Network_KPIs": "3G",
    "FDD_OLIB_Network_KPIs": "FDD",
    "TDD_OLIB_Network_KPIs": "TDD",
}

# 每个 Sheet 的 Group 匹配规则及对应的 Cell Group 名称
# 4G ALL 仅使用 FDD 的 G_NW 数据；TDD 在图表中会被过滤
SHEET_CONFIG = {
    'Availability-NW': {
        'patterns': [r'^G_NW$'],
        'tech_groups': {
            '2G': '2G ALL',
            '3G': '3G ALL',
            'FDD': 'FDD ALL',
            'TDD': 'TDD ALL',
        },
    },
    'Availability-Regular': {
        'patterns': [r'Regular'],
        'tech_groups': {
            '2G': '2G Regular',
            '3G': '3G Regular',
            'FDD': 'FDD Regular',
        },
    },
    'Availability-COOL': {
        'patterns': [r'Cooli'],
        'tech_groups': {
            '2G': '2G Cooli',
            '3G': '3G Cooli',
            'FDD': 'FDD Cooli',
        },
    },
    'Availability-ERA': {
        'patterns': [r'ERA'],
        'tech_groups': {
            '2G': '2G ERA',
            'FDD': 'FDD ERA',
        },
    },
}

# 手动指定每个表的可用性指标列名
AVAILABILITY_METRICS = {
    "2G_OLIB_Network_KPIs": "TCH in service rate(%)",
    "3G_OLIB_Network_KPIs": "Cell Validity Rate(%)",
    "FDD_OLIB_Network_KPIs": "[FDD]Cell Availability[SDR_ITBBU]",
    "TDD_OLIB_Network_KPIs": "[TDD]Cell Availability[SDR_ITBBU]",
}

# 仪表板样式颜色映射（FDD 在图表中会显示为 4G）
COLOR_MAP = {
    '2G ALL': '#2F5496',
    '3G ALL': '#ED7D31',
    '4G ALL': '#70AD47',
    'FDD ALL': '#70AD47',
    '2G Regular': '#2F5496',
    '3G Regular': '#ED7D31',
    '4G Regular': '#70AD47',
    'FDD Regular': '#70AD47',
    '2G Cooli': '#2F5496',
    '3G Cooli': '#ED7D31',
    '4G Cooli': '#70AD47',
    'FDD Cooli': '#70AD47',
    '2G ERA': '#2F5496',
    '4G ERA': '#70AD47',
    'FDD ERA': '#70AD47',
}

TARGET_VALUE = 0.9965
BG_COLOR = '#E8F0FE'
TITLE_COLOR = '#2F5496'
GRID_COLOR = '#C5C5C5'
MAX_LABEL_COLOR = '#FF0000'
MIN_LABEL_COLOR = '#ED7D31'

# FTP 上传配置（图片上传到 ORANGE 目录）
FTP_UPLOAD_HOST = "192.168.100.19"
FTP_UPLOAD_PORT = 21
FTP_UPLOAD_USER = "ZTEEMS"
FTP_UPLOAD_PASS = "DX"
FTP_UPLOAD_PATH = "/01_RPA/LBR_Tools/KPI/RAN/ORANGE"


def normalize_chart_label(name: str) -> str | None:
    """图表图例名称简化：过滤 TDD，FDD ALL -> 4G ALL，FDD xxx -> 4G xxx。
    与 generate_charts_v2.py 的 normalize_label 保持一致。
    """
    if 'TDD' in name:
        return None
    name = name.replace('4G FDD', '4G')
    name = name.replace('FDD ALL', '4G ALL')
    name = name.replace('FDD Regular', '4G Regular')
    name = name.replace('FDD Cooli', '4G Cooli')
    name = name.replace('FDD ERA', '4G ERA')
    return name


def find_availability_column(columns: list[str], table_name: str) -> str:
    """查找表示 Cell Availability 的列名，优先使用配置，否则自动推断。"""
    configured = AVAILABILITY_METRICS.get(table_name, "").strip()
    if configured:
        if configured in columns:
            return configured
        raise ValueError(
            f"表 {table_name} 中未找到配置的可用性列 '{configured}'，可用列: {columns}"
        )

    keywords = [
        "cell availability", "availability", "avail", "可用率", "可用性",
        "radio network availability", "ran availability",
    ]
    for col in columns:
        col_lower = col.lower()
        if any(kw in col_lower for kw in keywords):
            return col

    # 兜底：选择第一个看起来是数值的列（排除常见非指标列）
    exclude = {"begin time", "group", "date", "time", "id", "name"}
    for col in columns:
        if col.lower() in exclude:
            continue
        return col

    raise ValueError(f"无法为表 {table_name} 找到可用性指标列，可用列: {columns}")


def read_db_tables(db_path: str) -> dict[str, pd.DataFrame]:
    """读取数据库中所有 OLIB Network KPIs 表。"""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"数据库不存在: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall() if row[0] in TECH_MAP]

        if not tables:
            raise ValueError(f"数据库中未找到目标表，请检查: {list(TECH_MAP.keys())}")

        result = {}
        for table in tables:
            df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
            result[table] = df
            print(f"[DB] {table}: {len(df)} rows, {list(df.columns)}")
        return result
    finally:
        conn.close()


def normalize_date(date_val) -> str:
    """将各种日期格式统一为 YYYY-MM-DD。"""
    if date_val is None or pd.isna(date_val):
        return ""
    s = str(date_val).strip()
    # 尝试 ISO 格式 2026-04-23T00:00:00.000Z
    if 'T' in s:
        s = s.split('T')[0]
    return s


def classify_group(group_val: str, patterns: list[str]) -> bool:
    """判断 group 是否匹配某 Sheet 的规则。"""
    if group_val is None or pd.isna(group_val):
        return False
    s = str(group_val)
    for pat in patterns:
        if re.search(pat, s, re.IGNORECASE):
            return True
    return False


def build_availability_data(table_dfs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """将数据库表数据转换为 Availability Excel 所需的 Sheet 结构。"""
    sheet_rows = {sheet: [] for sheet in TARGET_SHEETS}

    for table_name, df in table_dfs.items():
        tech = TECH_MAP[table_name]
        if "Begin Time" not in df.columns or "Group" not in df.columns:
            print(f"[WARN] {table_name} 缺少 Begin Time 或 Group 列，跳过")
            continue

        avail_col = find_availability_column(list(df.columns), table_name)
        print(f"[MAP] {table_name} -> tech={tech}, availability_col={avail_col}")

        df = df.copy()
        df['Begin Time'] = df['Begin Time'].apply(normalize_date)
        df[avail_col] = pd.to_numeric(df[avail_col], errors='coerce')

        # 如果数值明显是百分比形式（>1），转换为比率
        non_null = df[avail_col].dropna()
        if not non_null.empty and non_null.max() > 1:
            df[avail_col] = df[avail_col] / 100.0

        for sheet_name, cfg in SHEET_CONFIG.items():
            tech_groups = cfg['tech_groups']
            if tech not in tech_groups:
                continue
            mask = df['Group'].apply(lambda x: classify_group(x, cfg['patterns']))
            sub = df[mask].copy()
            if sub.empty:
                continue

            # 同一天同一 tech 取平均值（若存在多组）
            agg = sub.groupby('Begin Time')[avail_col].mean().reset_index()
            agg['Cell Group'] = tech_groups[tech]
            agg['Cell Availability'] = agg[avail_col]
            sheet_rows[sheet_name].append(agg[['Begin Time', 'Cell Group', 'Cell Availability']])

    result = {}
    for sheet_name, frames in sheet_rows.items():
        if frames:
            df = pd.concat(frames, ignore_index=True)
            df = df.sort_values(['Cell Group', 'Begin Time']).reset_index(drop=True)
        else:
            df = pd.DataFrame(columns=['Begin Time', 'Cell Group', 'Cell Availability'])
        result[sheet_name] = df
        print(f"[SHEET] {sheet_name}: {len(df)} rows, groups: {df['Cell Group'].unique().tolist() if not df.empty else []}")
    return result


def write_excel(sheet_data: dict[str, pd.DataFrame], output_path: str) -> None:
    """将 Sheet 数据写入 Excel 文件。"""
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        for sheet_name in TARGET_SHEETS:
            df = sheet_data.get(sheet_name, pd.DataFrame())
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    print(f"[EXCEL] 已保存: {output_path}")


def generate_chart(df: pd.DataFrame, sheet_name: str, output_dir: str) -> str:
    """根据 generate_charts_v2.py 的仪表板样式生成折线图。"""
    print(f"\n  生成图表: {sheet_name}")

    if df.empty or 'Cell Group' not in df.columns or 'Cell Availability' not in df.columns:
        print(f"  [SKIP] {sheet_name} 无数据")
        return ""

    # 应用图例归一化，过滤 TDD
    df = df.copy()
    df['Cell Group'] = df['Cell Group'].apply(normalize_chart_label)
    df = df.dropna(subset=['Cell Group'])
    if df.empty:
        print(f"  [SKIP] {sheet_name} 过滤 TDD 后无数据")
        return ""

    cell_groups = sorted(df['Cell Group'].unique().tolist())
    pivot_df = df.pivot_table(index='Begin Time', columns='Cell Group', values='Cell Availability')
    dates = pivot_df.index.tolist()
    n_dates = len(dates)
    print(f"  日期数: {n_dates}, Cell Groups: {cell_groups}")

    fig, ax = plt.subplots(figsize=(14, 5.5))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    for cg in cell_groups:
        values = pivot_df[cg].values
        color = COLOR_MAP.get(cg, '#333333')
        ax.plot(range(n_dates), values, color=color, linewidth=1.2, label=cg, alpha=0.85)

    # 目标线
    ax.axhline(y=TARGET_VALUE, color='#FF0000', linestyle='--', linewidth=1.0, alpha=0.7)
    ax.text(n_dates - 1, TARGET_VALUE + 0.003, f'T:{TARGET_VALUE*100:.2f}%',
            color=MAX_LABEL_COLOR, fontsize=8, ha='right', fontweight='bold')

    # 最大/最小值标注
    all_values = pivot_df.values
    if not np.all(np.isnan(all_values)):
        max_pos = np.unravel_index(np.nanargmax(all_values), all_values.shape)
        min_pos = np.unravel_index(np.nanargmin(all_values), all_values.shape)
        max_val = all_values[max_pos]
        min_val = all_values[min_pos]
        max_x = max_pos[1]
        min_x = min_pos[1]

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

        y_min = max(0.60, min_val - 0.03)
        y_max = min(1.02, max_val + 0.03)
    else:
        y_min, y_max = 0.90, 1.0

    ax.set_ylim(y_min, y_max)
    ax.set_ylabel('Cell Availability', fontsize=9, color='#333333')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x*100:.2f}%'))
    ax.tick_params(axis='y', labelsize=8, colors='#333333')

    tick_interval = max(1, n_dates // 10)
    tick_positions = list(range(0, n_dates, tick_interval))
    tick_labels = [dates[i] for i in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, rotation=0, fontsize=7, ha='center')
    ax.tick_params(axis='x', colors='#333333')

    ax.grid(axis='y', linestyle='--', color=GRID_COLOR, linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)

    for spine in ax.spines.values():
        spine.set_color('#B0B0B0')
        spine.set_linewidth(0.5)

    ax.set_title(sheet_name, fontsize=13, fontweight='bold', color=TITLE_COLOR, pad=12)

    ax.legend(loc='lower center', bbox_to_anchor=(0.5, -0.18),
              ncol=len(cell_groups), fontsize=7.5, frameon=False,
              columnspacing=1.5, handletextpad=0.5)

    plt.tight_layout()

    output_path = os.path.join(output_dir, f'{sheet_name}.png')
    fig.savefig(output_path, dpi=150, bbox_inches='tight',
                facecolor=BG_COLOR, edgecolor='none',
                pil_kwargs={'quality': 95})
    plt.close(fig)
    print(f"  已保存: {output_path}")
    return output_path


def upload_images_to_ftp(file_paths: list[str], max_retries: int = 2) -> bool:
    """上传图片到 FTP 服务器（参考 generate_charts_v2.py）。"""
    if not file_paths:
        print("[FTP] 没有图片需要上传")
        return True

    for attempt in range(1, max_retries + 1):
        print(f"\n[FTP] 连接 {FTP_UPLOAD_HOST} ...（第 {attempt} 次）")
        ftp = None
        try:
            ftp = FTP()
            ftp.connect(FTP_UPLOAD_HOST, FTP_UPLOAD_PORT, timeout=30)
            ftp.encoding = "utf-8"
            ftp.login(FTP_UPLOAD_USER, FTP_UPLOAD_PASS)
            print(f"[FTP] 登录成功: {FTP_UPLOAD_USER}")

            # 确保目录存在
            try:
                ftp.cwd(FTP_UPLOAD_PATH)
            except error_perm:
                parts = FTP_UPLOAD_PATH.strip('/').split('/')
                current = ''
                for part in parts:
                    current += f'/{part}'
                    try:
                        ftp.cwd(current)
                    except error_perm:
                        ftp.mkd(current)
                        ftp.cwd(current)

            print(f"[FTP] 当前目录: {ftp.pwd()}")

            for fpath in file_paths:
                fname = os.path.basename(fpath)
                with open(fpath, 'rb') as f:
                    ftp.storbinary(f'STOR {fname}', f)
                print(f"  [OK] 已上传: {fname} ({os.path.getsize(fpath)} bytes)")

            ftp.quit()
            print("[FTP] 上传完成!")
            return True
        except Exception as e:
            print(f"[FTP] 上传失败: {e}")
            if ftp:
                try:
                    ftp.close()
                except Exception:
                    pass
    return False


def inspect_db(db_path: str) -> None:
    """打印数据库表结构，便于用户配置可用性指标列。"""
    if not os.path.exists(db_path):
        print(f"[WARN] 数据库不存在: {db_path}")
        return
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    print("\n[DB INSPECT] 数据库表结构:")
    for table in tables:
        cursor.execute(f'PRAGMA table_info("{table}")')
        cols = [row[1] for row in cursor.fetchall()]
        print(f"  {table}: {cols}")
    conn.close()


def test_ftp_connection() -> bool:
    """测试 FTP 连接：登录、目录浏览、目标路径检查。"""
    print(f"\n{'='*60}")
    print("FTP 连接测试")
    print(f"{'='*60}")
    print(f"  Host: {FTP_UPLOAD_HOST}:{FTP_UPLOAD_PORT}")
    print(f"  User: {FTP_UPLOAD_USER}")
    print(f"  Path: {FTP_UPLOAD_PATH}")

    ftp = None
    try:
        print("\n[1/4] 连接 FTP 服务器...")
        ftp = FTP()
        ftp.connect(FTP_UPLOAD_HOST, FTP_UPLOAD_PORT, timeout=30)
        ftp.encoding = "utf-8"
        print(f"  连接成功，Banner: {ftp.getwelcome()}")

        print("\n[2/4] 登录...")
        resp = ftp.login(FTP_UPLOAD_USER, FTP_UPLOAD_PASS)
        print(f"  登录成功: {resp}")

        print("\n[3/4] 列出根目录...")
        ftp.cwd('/')
        root_items = ftp.nlst()
        print(f"  根目录共 {len(root_items)} 项: {root_items[:10]}{'...' if len(root_items) > 10 else ''}")

        print(f"\n[4/4] 切换到目标目录 {FTP_UPLOAD_PATH}...")
        ftp.cwd(FTP_UPLOAD_PATH)
        target_items = ftp.nlst()
        print(f"  目标目录共 {len(target_items)} 项: {target_items}")

        ftp.quit()
        print(f"\n[OK] FTP 连接测试全部通过!")
        return True
    except Exception as e:
        print(f"\n[FAIL] FTP 测试失败: {e}")
        if ftp:
            try:
                ftp.close()
            except Exception:
                pass
        return False


def main():
    start_time = time.time()

    parser = argparse.ArgumentParser(description="Daily Availability KPI 生成脚本")
    parser.add_argument('--test-ftp', action='store_true', help='仅测试 FTP 连接，不生成报表')
    args = parser.parse_args()

    if args.test_ftp:
        ok = test_ftp_connection()
        elapsed = time.time() - start_time
        print(f"\n耗时: {elapsed:.1f} 秒")
        sys.exit(0 if ok else 1)

    print(f"\n{'='*60}")
    print("Daily Availability KPI 生成")
    print(f"{'='*60}\n")
    print(f"数据库: {DB_PATH}")
    print(f"输出 Excel: {OUTPUT_EXCEL}")
    print(f"输出目录: {OUTPUT_DIR}\n")

    try:
        inspect_db(DB_PATH)
        table_dfs = read_db_tables(DB_PATH)
        sheet_data = build_availability_data(table_dfs)
        write_excel(sheet_data, OUTPUT_EXCEL)

        print("\n" + "=" * 60)
        print("Step 2: 生成图表")
        print("=" * 60)

        generated_images = []
        for sheet_name in TARGET_SHEETS:
            df = sheet_data.get(sheet_name, pd.DataFrame())
            img_path = generate_chart(df, sheet_name, OUTPUT_DIR)
            if img_path:
                generated_images.append(img_path)

        # 上传图片到 FTP
        print("\n" + "=" * 60)
        print("Step 3: 上传图片到 FTP")
        print("=" * 60)
        upload_images_to_ftp(generated_images)

        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"完成! 生成 {len(generated_images)} 张图表，总耗时: {elapsed:.1f} 秒")
        print(f"输出目录: {OUTPUT_DIR}")
        print(f"{'='*60}")

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n[ERROR] 执行失败: {e}")
        raise


if __name__ == '__main__':
    main()

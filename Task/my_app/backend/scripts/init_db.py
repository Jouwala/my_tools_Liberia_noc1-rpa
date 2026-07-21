"""Excel文件转SQLite数据库初始化脚本"""
import os
import re
import sys
import time
import sqlite3
import pandas as pd
from pathlib import Path

# 配置
DB_DIR = Path(__file__).resolve().parent.parent.parent / "db"
DB_PATH = DB_DIR / "app.db"
EXCEL_DIR = DB_DIR

# Excel文件 -> 表名映射
FILE_TABLE_MAP = {
    "Eflow_TT_FB.xlsx": "eflow_tt",
    "Eflow_WO_FB.xlsx": "eflow_wo",
    "ZTE OLR MS Master Site Database.xlsx": None,  # 多sheet，按sheet名生成表
}

# sheet名 -> 表名映射（Master Site Database 多sheet）
SHEET_TABLE_MAP = {
    "Master Site Database ": "master_site_db",
    "E-flow Database": "eflow_database",
    "FLM Database": "flm_database",
    "New FLM Team information ": "flm_team_new",
    "FLM Team information": "flm_team",
    "SLA and Tickes Priority": "sla_priority",
    "Victim topology（Pradeep update)": "victim_topology",
    "Satellite sites list": "satellite_sites",
    "ERA(VIP&No-VIP）": "era_sites",
    "GateWay Sites": "gateway_sites",
    "Special Sites": "special_sites",
    "ISP Sites": "isp_sites",
    "LandLord and AML Sites": "landlord_sites",
}


def clean_column_name(col: str) -> str:
    """清洗列名：去空格、特殊字符，转小写snake_case"""
    if not isinstance(col, str):
        col = str(col)
    col = col.strip()
    col = re.sub(r'[^\w\s]', '_', col)
    col = re.sub(r'\s+', '_', col)
    col = re.sub(r'_+', '_', col)
    col = col.strip('_').lower()
    if col and col[0].isdigit():
        col = f'col_{col}'
    if not col:
        col = 'unnamed'
    return col


def load_excel_to_db(excel_path: Path, table_prefix: str, conn: sqlite3.Connection, sheet_map: dict = None):
    """将Excel文件的所有sheet写入SQLite"""
    print(f"\n{'='*60}")
    print(f"处理文件: {excel_path.name}")
    print(f"{'='*60}")

    try:
        xls = pd.ExcelFile(str(excel_path), engine='openpyxl')
    except Exception as e:
        print(f"  [ERROR] 无法打开文件: {e}")
        return

    for sheet_name in xls.sheet_names:
        # 确定表名
        if sheet_map and sheet_name in sheet_map:
            table_name = sheet_map[sheet_name]
        elif sheet_map:
            table_name = clean_column_name(sheet_name)
        else:
            table_name = table_prefix

        print(f"\n  Sheet: '{sheet_name}' -> 表: {table_name}")

        try:
            df = pd.read_excel(xls, sheet_name=sheet_name, engine='openpyxl')
        except Exception as e:
            print(f"    [ERROR] 读取失败: {e}")
            continue

        if df.empty:
            print(f"    [SKIP] 空表")
            continue

        # 清洗列名
        original_cols = list(df.columns)
        df.columns = [clean_column_name(c) for c in df.columns]

        # 处理重复列名
        seen = {}
        new_cols = []
        for c in df.columns:
            if c in seen:
                seen[c] += 1
                new_cols.append(f"{c}_{seen[c]}")
            else:
                seen[c] = 0
                new_cols.append(c)
        df.columns = new_cols

        # 删除全空列
        df = df.dropna(axis=1, how='all')

        # 添加元数据列
        df['_source_file'] = excel_path.name
        df['_source_sheet'] = sheet_name
        df['_import_time'] = pd.Timestamp.now().isoformat()

        print(f"    行数: {len(df)}, 列数: {len(df.columns)}")

        # 显示前5个列名映射
        for orig, new in zip(original_cols[:5], df.columns[:5]):
            print(f"    列映射: '{orig}' -> '{new}'")
        if len(original_cols) > 5:
            print(f"    ... 共{len(original_cols)}列")

        # 写入数据库（先删除旧表再创建）
        df.to_sql(table_name, conn, if_exists='replace', index=False, chunksize=5000)

        # 建立索引
        if 'site_id' in df.columns:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_site_id ON {table_name}(site_id)")
            print(f"    索引: site_id")
        if 'region_level1' in df.columns:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_region1 ON {table_name}(region_level1)")
            print(f"    索引: region_level1")
        if 'region' in df.columns:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_region ON {table_name}(region)")
            print(f"    索引: region")
        if 'status' in df.columns:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_status ON {table_name}(status)")
            print(f"    索引: status")
        if 'created_time' in df.columns:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_created_time ON {table_name}(created_time)")
            print(f"    索引: created_time")
        if 'alarm_occur_time' in df.columns:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_alarm_occur ON {table_name}(alarm_occur_time)")
            print(f"    索引: alarm_occur_time")
            # 复合索引：时间+站点（加速JOIN+时间过滤）
            if 'site_id' in df.columns:
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_alarm_site ON {table_name}(alarm_occur_time, site_id)")
                print(f"    索引: alarm_occur_time+site_id (复合)")
        if 'site_name' in df.columns:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_site_name ON {table_name}(site_name)")
            print(f"    索引: site_name")
        if 'ticket_no' in df.columns:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_ticket_no ON {table_name}(ticket_no)")
            print(f"    索引: ticket_no")

        conn.commit()
        print(f"    [OK] 写入完成")

    xls.close()


def main():
    start_time = time.time()
    print(f"数据库路径: {DB_PATH}")
    print(f"Excel目录: {EXCEL_DIR}")

    # 确保目录存在
    DB_DIR.mkdir(parents=True, exist_ok=True)

    # 连接数据库
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # 处理每个Excel文件
    for filename, table_prefix in FILE_TABLE_MAP.items():
        excel_path = EXCEL_DIR / filename
        if not excel_path.exists():
            print(f"\n[WARNING] 文件不存在: {excel_path}")
            continue

        if table_prefix is None:
            # 多sheet文件，使用SHEET_TABLE_MAP
            load_excel_to_db(excel_path, "", conn, sheet_map=SHEET_TABLE_MAP)
        else:
            load_excel_to_db(excel_path, table_prefix, conn)

    # 创建元数据表 - 记录所有数据表信息
    cursor = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != '_metadata'
        ORDER BY name
    """)
    tables = [row[0] for row in cursor.fetchall()]

    metadata_rows = []
    for table_name in tables:
        row_count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        col_info = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        col_count = len(col_info)
        columns = [{"name": c[1], "type": c[2]} for c in col_info]
        metadata_rows.append({
            "table_name": table_name,
            "row_count": row_count,
            "col_count": col_count,
            "columns_json": str(columns),
        })

    if metadata_rows:
        meta_df = pd.DataFrame(metadata_rows)
        meta_df.to_sql('_metadata', conn, if_exists='replace', index=False)
        print(f"\n{'='*60}")
        print(f"元数据表 _metadata: {len(metadata_rows)}条记录")

    # 创建分析归档表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analysis_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            table_name TEXT,
            chart_config TEXT,
            conclusions TEXT,
            snapshot_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # 打印汇总
    print(f"\n{'='*60}")
    print("数据库汇总:")
    print(f"{'='*60}")
    for table_name in tables:
        row_count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        print(f"  {table_name}: {row_count} 行")

    conn.close()
    elapsed = time.time() - start_time
    print(f"\n总耗时: {elapsed:.2f}秒")


if __name__ == "__main__":
    main()

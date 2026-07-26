import pandas as pd
import sqlite3
import os
from datetime import datetime
import sys
import io

# 强制设置标准输出和错误输出的编码为 utf-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# --- 关键修改：获取脚本文件所在的绝对路径 ---
base_path = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(base_path, 'data')
db_path = os.path.join(base_path, 'inventory.db')

current_now = datetime.now()
update_time_str = current_now.strftime('%Y-%m-%d %H:%M:%S')
update_date_str = current_now.strftime('%Y-%m-%d')


def process_inventory_data():
    # 确保 data 文件夹存在
    if not os.path.exists(data_dir):
        print(f"错误：找不到文件夹 {data_dir}")
        return

    conn = sqlite3.connect(db_path)

    try:
        # 1. 处理 inband_details、outband_details 和 ocrule_details (替换模式)
        for file_name in ['inband_details.xlsx', 'outband_details.xlsx', 'ocrule_details.xlsx']:
            table_name = file_name.split('.')[0]
            file_path = os.path.join(data_dir, file_name)

            if os.path.exists(file_path):
                df = pd.read_excel(file_path)
                df['update_time'] = update_time_str
                df['update_date'] = update_date_str
                df.to_sql(table_name, conn, if_exists='replace', index=False)
                print(f"已更新/替换表: {table_name}")
            else:
                print(f"警告：未找到文件 {file_path}")

        # 2. 处理 inventory_details (更新/去重模式)
        inv_file = os.path.join(data_dir, 'inventory_details.xlsx')
        inv_table = 'inventory_details'

        if os.path.exists(inv_file):
            df_new = pd.read_excel(inv_file)
            df_new['update_time'] = update_time_str
            df_new['update_date'] = update_date_str

            cursor = conn.cursor()
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{inv_table}'")
            if cursor.fetchone():
                df_old = pd.read_sql(f"SELECT * FROM {inv_table}", conn)
                df_combined = pd.concat([df_new, df_old], ignore_index=True)
                subset_cols = ['update_date', 'Serial No.', 'Material No.', 'Warehouse Name', 'Material Type']
                df_final = df_combined.drop_duplicates(subset=subset_cols, keep='first')
                df_final.to_sql(inv_table, conn, if_exists='replace', index=False)
                print(f"已增量更新表: {inv_table}，总记录数: {len(df_final)}")
            else:
                df_new.to_sql(inv_table, conn, if_exists='replace', index=False)
                print(f"已创建并初始化表: {inv_table}")
        else:
            print(f"警告：未找到文件 {inv_file}")

    except Exception as e:
        print(f"处理过程中出错: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    process_inventory_data()

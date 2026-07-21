# -*- coding: utf-8 -*-
import pandas as pd
import sqlite3
from datetime import datetime
import os
import sys
import glob
import logging
from ftplib import FTP, error_perm

# 修复 Windows CMD 下中文输出编码问题
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# 配置
# ============================================================
DOWNLOADS_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = "db.sqlite3"
DB_PATH = os.path.join(DB_DIR, DB_NAME)

FTP_HOST = "192.168.100.19"
FTP_USER = "FINEBI"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/Python"

# 上传配置（与下载配置不同）
FTP_UPLOAD_USER = "ZTEEMS"
FTP_UPLOAD_PASS = "DX"
FTP_UPLOAD_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/RAN"


def quote_identifier(name):
    """
    为包含特殊字符的SQL标识符（如表名、列名）添加双引号
    """
    return f'"{name}"'


def get_table_info(conn, table_name):
    """
    获取表的列信息 (列名)
    """
    cursor = conn.cursor()
    # 使用引号包围表名
    cursor.execute(f"PRAGMA table_info({quote_identifier(table_name)})")
    columns = cursor.fetchall()
    # 返回列名列表
    return [col[1] for col in columns]


def add_missing_columns(conn, table_name, excel_columns):
    """
    自动检测并向数据库表中添加 Excel 中存在但数据库中缺失的列
    """
    db_cols = get_table_info(conn, table_name)
    # 找出在 Excel 中但不在数据库中的列
    missing_cols = [col for col in excel_columns if col not in db_cols]

    if missing_cols:
        cursor = conn.cursor()
        for col in missing_cols:
            logger.info(f"检测到新字段，正在向表 {table_name} 添加列: {col}")
            # SQLite 中 ALTER TABLE 增加列，建议使用 NUMERIC 以获得更好的 KPI 数据兼容性
            try:
                alter_query = f"ALTER TABLE {quote_identifier(table_name)} ADD COLUMN {quote_identifier(col)} NUMERIC"
                cursor.execute(alter_query)
            except Exception as e:
                logger.error(f"向表 {table_name} 添加列 {col} 失败: {e}")
        conn.commit()


def get_table_data(conn, table_name, columns):
    """
    获取表的指定列数据用于对比
    """
    # 构建查询语句，使用引号包围所有列名和表名
    quoted_columns = [quote_identifier(col) for col in columns]
    columns_str = ', '.join(quoted_columns)
    query = f"SELECT {columns_str} FROM {quote_identifier(table_name)}"
    return pd.read_sql_query(query, conn, dtype=object)  # 使用object类型避免数据类型转换问题


def get_excel_data(file_path, sheet_name=0):
    """
    读取Excel文件数据
    """
    try:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        logger.info(f"成功读取Excel文件: {file_path}, 形状: {df.shape}")
        return df
    except Exception as e:
        logger.error(f"读取Excel文件失败: {file_path}, 错误: {e}")
        raise


# ============================================================
# FTP 下载 / 上传
# ============================================================
def download_from_ftp(remote_dir, filename, local_path, max_retries=2):
    """从 FTP 服务器下载文件（带重试机制）"""
    for attempt in range(1, max_retries + 1):
        logger.info(f"[FTP] 连接 {FTP_HOST} 下载 {filename} ...（第 {attempt} 次）")
        ftp = None
        try:
            ftp = FTP(FTP_HOST, timeout=30)
            ftp.encoding = "utf-8"
            if attempt > 1:
                ftp.set_debuglevel(1)
            ftp.login(FTP_USER, FTP_PASS)
            logger.info(f"  登录成功: {FTP_USER}")

            ftp.cwd("/")
            parts = remote_dir.strip("/").split("/")
            for i in range(len(parts)):
                abs_path = "/" + "/".join(parts[:i + 1])
                try:
                    ftp.cwd(abs_path)
                except error_perm:
                    logger.error(f"  远程目录不存在: {abs_path}")
                    raise

            current_dir = ftp.pwd()
            logger.info(f"  远程目录: {current_dir}")

            with open(local_path, "wb") as f:
                ftp.retrbinary(f"RETR {filename}", f.write)

            logger.info(f"  [OK] 已下载: {filename} -> {local_path}")
            ftp.quit()
            return True
        except Exception as e:
            logger.error(f"  [ERROR] FTP 下载失败: {e}")
            if ftp:
                try:
                    ftp.close()
                except Exception:
                    pass
    return False


def upload_to_ftp(local_path, remote_dir, filename, max_retries=2, user=None, password=None):
    """上传文件到 FTP 服务器（带重试机制）"""
    _user = user or FTP_USER
    _pass = password or FTP_PASS
    for attempt in range(1, max_retries + 1):
        logger.info(f"[FTP] 连接 {FTP_HOST} 上传 {filename} ...（第 {attempt} 次）")
        ftp = None
        try:
            ftp = FTP(FTP_HOST, timeout=30)
            ftp.encoding = "utf-8"
            if attempt > 1:
                ftp.set_debuglevel(1)
            ftp.login(_user, _pass)
            logger.info(f"  登录成功: {_user}")

            ftp.cwd("/")
            parts = remote_dir.strip("/").split("/")
            for i in range(len(parts)):
                abs_path = "/" + "/".join(parts[:i + 1])
                try:
                    ftp.cwd(abs_path)
                except error_perm:
                    try:
                        ftp.mkd(abs_path)
                        ftp.cwd(abs_path)
                    except error_perm as e2:
                        logger.warning(f"  无法创建目录 {abs_path}: {e2}")

            current_dir = ftp.pwd()
            logger.info(f"  远程目录: {current_dir}")
            expected = "/" + "/".join(parts)
            if current_dir != expected:
                logger.warning(f"  目录不匹配，期望 {expected}，实际 {current_dir}")
                ftp.cwd(expected)

            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f)

            logger.info(f"  [OK] 已上传: {filename}")
            ftp.quit()
            return True
        except Exception as e:
            logger.error(f"  [ERROR] FTP 上传失败: {e}")
            if ftp:
                try:
                    ftp.close()
                except Exception:
                    pass
    return False


# ============================================================
# 查找最新匹配文件
# ============================================================
def find_latest_file(name_pattern, search_dir):
    """
    在 search_dir 中查找文件名包含 name_pattern 的最新 .xlsx 文件
    返回完整路径，未找到时返回 None
    """
    glob_pattern = os.path.join(search_dir, f"*{name_pattern}*.xlsx")
    matches = glob.glob(glob_pattern)
    # 排除临时文件（~$ 开头）
    matches = [f for f in matches if not os.path.basename(f).startswith("~$")]
    if not matches:
        return None
    # 按修改时间降序，返回最新的
    matches.sort(key=os.path.getmtime, reverse=True)
    return matches[0]


def sync_excel_to_db_table(excel_file_path, db_table, db_path, add_group_column=False):
    """
    同步Excel数据到数据库表（增强：支持自动添加缺失字段）
    """
    logger.info(f"开始同步 {excel_file_path} 到数据库表 {db_table}")

    # 检查Excel文件是否存在
    if not os.path.exists(excel_file_path):
        logger.warning(f"Excel文件不存在: {excel_file_path}")
        return

    # 读取Excel数据
    excel_df = get_excel_data(excel_file_path)

    # 如果需要添加Group列
    if add_group_column:
        excel_df['Group'] = 'NW'
        logger.info(f"为 {excel_file_path} 添加了 'Group' 列，值为 'NW'")

    # 连接数据库
    conn = sqlite3.connect(db_path)

    try:
        # 检查表是否存在
        cursor = conn.cursor()
        # 使用引号包围表名
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name={quote_identifier(db_table)};")
        table_exists = cursor.fetchone() is not None

        if not table_exists:
            # 如果表不存在，直接创建表并插入所有数据
            excel_df.to_sql(db_table, conn, if_exists='replace', index=False)
            logger.info(f"表 {db_table} 不存在，已创建并插入 {len(excel_df)} 条记录")
            return

        # --- 核心改进：自动添加缺失的字段 ---
        add_missing_columns(conn, db_table, excel_df.columns.tolist())
        # ---------------------------------

        # 获取更新后的数据库表的列信息
        db_columns = get_table_info(conn, db_table)

        # 找出共同的列（用于排重比对）
        excel_columns = excel_df.columns.tolist()
        common_columns = [col for col in db_columns if col in excel_columns]

        if not common_columns:
            logger.error(f"Excel文件 {excel_file_path} 和数据库表 {db_table} 没有共同的列，无法同步")
            return

        logger.info(f"比对共同列: {common_columns}")

        # 获取数据库中现有的数据
        db_df = get_table_data(conn, db_table, common_columns)

        # 数据比对逻辑
        excel_df_compare_str = excel_df[common_columns].astype(str)
        db_df_compare_str = db_df.astype(str)

        merged_df = excel_df_compare_str.merge(
            db_df_compare_str,
            on=common_columns,
            how='left',
            indicator=True
        )

        # 找出只在左侧（Excel）中存在的行
        new_data_indices = merged_df[merged_df['_merge'] == 'left_only'].index

        if len(new_data_indices) > 0:
            new_data_to_insert = excel_df.loc[new_data_indices]
            # 插入新数据
            new_data_to_insert.to_sql(db_table, conn, if_exists='append', index=False)
            logger.info(f"表 {db_table} 有更新，插入了 {len(new_data_to_insert)} 条新记录")
        else:
            logger.info(f"表 {db_table} 无更新，无需操作")

    except Exception as e:
        logger.error(f"同步 {excel_file_path} 到表 {db_table} 时出错: {e}")
        raise
    finally:
        conn.close()


def main():
    """
    主函数：
      1. 从 FTP 下载 db.sqlite3
      2. 从本地下载文件夹查找匹配的最新 Excel 文件
      3. 同步数据到 db.sqlite3
      4. 上传更新后的 db.sqlite3 到 FTP
    """
    # ---------- 1. 从 FTP 下载数据库 ----------
    logger.info("=" * 60)
    logger.info("步骤 1: 从 FTP 下载数据库")
    logger.info("=" * 60)
    downloaded = download_from_ftp(FTP_REMOTE_DIR, DB_NAME, DB_PATH)
    if not downloaded:
        logger.error("无法从 FTP 下载数据库，流程终止")
        return

    # ---------- 2 & 3. 查找文件并同步 ----------
    logger.info("=" * 60)
    logger.info("步骤 2: 查找最新 Excel 文件并同步到数据库")
    logger.info("=" * 60)

    # 任务列表：name_pattern 用于在 Downloads 中模糊匹配文件名
    sync_tasks = [
        {'name_pattern': '2G_Main_Kpi_Cell_Daily_30', 'db_table': '2G_Main_Kpi_Cell_Daily',
         'add_group_column': False},
        {'name_pattern': '2G_Main_Kpi_Site_Daily_30', 'db_table': '2G_Main_Kpi_Site_Daily',
         'add_group_column': False},
        {'name_pattern': '2G_Main_Kpi_Group_Daily_30', 'db_table': '2G_Main_Kpi_group_Daily',
         'add_group_column': False},
        {'name_pattern': '2G_Main_Kpi_NW_Daily_30', 'db_table': '2G_Main_Kpi_group_Daily',
         'add_group_column': True},
        {'name_pattern': '3G_Main_Kpi_Cell_Daily_30', 'db_table': '3G_Main_Kpi_Cell_Daily',
         'add_group_column': False},
        {'name_pattern': '3G_Main_Kpi_Site_Daily_30', 'db_table': '3G_Main_Kpi_Site_Daily',
         'add_group_column': False},
        {'name_pattern': '3G_Main_Kpi_Group_Daily_30', 'db_table': '3G_Main_Kpi_group_Daily',
         'add_group_column': False},
        {'name_pattern': '3G_Main_Kpi_NW_Daily_30', 'db_table': '3G_Main_Kpi_group_Daily',
         'add_group_column': True},
        {'name_pattern': '4G_Main_Kpi_Cell_Daily_30', 'db_table': '4G_Main_Kpi_Cell_Daily',
         'add_group_column': False},
        {'name_pattern': '4G_Main_Kpi_Site_Daily_30', 'db_table': '4G_Main_Kpi_Site_Daily',
         'add_group_column': False},
        {'name_pattern': '4G_Main_Kpi_Group_Daily_30', 'db_table': '4G_Main_Kpi_group_Daily',
         'add_group_column': False},
        {'name_pattern': '4G_Main_Kpi_NW_Daily_30', 'db_table': '4G_Main_Kpi_group_Daily',
         'add_group_column': True}
    ]

    for task in sync_tasks:
        try:
            pattern = task['name_pattern']
            latest_file = find_latest_file(pattern, DOWNLOADS_DIR)
            if latest_file is None:
                logger.warning(f"未找到匹配 '{pattern}' 的 Excel 文件，跳过")
                continue
            logger.info(f"匹配 '{pattern}' -> {latest_file}")
            sync_excel_to_db_table(
                latest_file,
                task['db_table'],
                DB_PATH,
                task['add_group_column']
            )
        except Exception as e:
            logger.error(f"处理任务失败: {task}, 错误: {e}")

    # ---------- 4. 上传数据库到 FTP ----------
    logger.info("=" * 60)
    logger.info("步骤 3: 上传更新后的数据库到 FTP")
    logger.info("=" * 60)
    uploaded = upload_to_ftp(DB_PATH, FTP_UPLOAD_REMOTE_DIR, DB_NAME,
                             user=FTP_UPLOAD_USER, password=FTP_UPLOAD_PASS)
    if uploaded:
        logger.info("数据库已成功上传到 FTP 服务器")
    else:
        logger.error("数据库上传 FTP 失败")

    logger.info("所有同步任务完成")


if __name__ == "__main__":
    main()

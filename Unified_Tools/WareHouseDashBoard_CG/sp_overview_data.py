import xbot
from xbot import print, sleep
from .import package
from .package import variables as glv

import os
import shutil
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def manage_progress_files():
    """核心逻辑：管理、清理并重命名文件"""
    # 路径配置
    source_folder = r'C:\FineBI6.0\webapps\webroot\WEB-INF\reportlets\excel'
    target_folder = r'C:\FineBI6.0\webapps\Python\Unified_Tools\WareHouseDashBoard\data'
    target_filename = 'sp_overview.xlsx'
    keyword = "Spare_Management_Dashboard"

    try:
        if not os.path.exists(target_folder):
            os.makedirs(target_folder)
            logger.info(f"创建目标文件夹: {target_folder}")

        files = [
            f for f in os.listdir(source_folder) 
            if keyword in f and f.endswith(('.xlsx', '.xls'))
        ]

        if not files:
            logger.warning(f"在 {source_folder} 中未找到包含 '{keyword}' 的文件")
            return

        files_with_time = [
            (f, os.path.getmtime(os.path.join(source_folder, f))) 
            for f in files
        ]
        files_with_time.sort(key=lambda x: x[1], reverse=True)

        latest_file_name = files_with_time[0][0]
        latest_file_path = os.path.join(source_folder, latest_file_name)
        
        logger.info(f"识别到最新文件: {latest_file_name}")

        for old_file_name, _ in files_with_time[1:]:
            old_file_path = os.path.join(source_folder, old_file_name)
            try:
                os.remove(old_file_path)
                logger.info(f"已删除旧文件: {old_file_name}")
            except Exception as e:
                logger.error(f"删除文件 {old_file_name} 失败: {e}")

        destination_path = os.path.join(target_folder, target_filename)
        shutil.copy2(latest_file_path, destination_path)
        logger.info(f"已成功将 {latest_file_name} 复制并重命名为 {target_filename}")

    except Exception as e:
        logger.error(f"执行过程中出现错误: {e}")

def main(args):
    """影刀/xbot 调用的标准入口函数"""
    try:
        manage_progress_files()
    except Exception as e:
        logger.error(f"模块执行失败: {e}")

if __name__ == "__main__":
    # 这里的 main({}) 是为了在本地调试时模拟外部调用
    main({})

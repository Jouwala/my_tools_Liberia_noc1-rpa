import paramiko
import os
import stat
import pandas as pd
import sys


host = "10.100.20.11"
port = 22
username = "ubuntu"
password = "UbuntU1!2@3#4$"

client = paramiko.Transport((host, port))
client.connect(username=username, password=password)
sftp = paramiko.SFTPClient.from_transport(client)

# 需要查找的文件配置，key=远程子目录，value=本地文件保存路径
folders = {
    "spinbound": "data/inband_details.xlsx",
    "spoutbound": "data/outband_details.xlsx",
    "spinventory": "data/inventory_details.xlsx",
}

# 特殊文件配置（需要递归搜索或特殊处理）
special_files = {
    "ocrule": {
        "remote_folder": "OCAuto/OCAutoOutput",
        "local_path": "data/ocrule_details.xlsx",
        "search_func": "find_latest_ocrule_csv_recursive",
        "convert_to_excel": True,
    },
    "transfer": {
        "remote_folder": "sp/sp-wh_transfer",
        "local_path": "data/transfer_details.xlsx",
        "search_func": "find_latest_transfer_xlsx_recursive",
        "convert_to_excel": False,
    },
}


def find_latest_subfolder(sftp, base_path):
    """找到 base_path 下修改时间最新的子目录"""
    dirs = []
    try:
        for f in sftp.listdir_attr(base_path):
            # 判断是否为目录，这里用stat判断更准确
            if stat.S_ISDIR(f.st_mode):
                dirs.append(f)
    except IOError:
        return None

    if not dirs:
        return None
    dirs.sort(key=lambda x: x.st_mtime, reverse=True)
    return dirs[0].filename


def find_latest_excel_in_nested(sftp, folder_path):
    """进入日期文件夹后，再进入最新的时间戳文件夹，再找 Excel 文件"""
    latest_date_folder = find_latest_subfolder(sftp, folder_path)
    if not latest_date_folder:
        return None
    date_path = f"{folder_path}/{latest_date_folder}"

    latest_time_folder = find_latest_subfolder(sftp, date_path)
    if not latest_time_folder:
        return None
    time_path = f"{date_path}/{latest_time_folder}"

    files = []
    try:
        for f in sftp.listdir_attr(time_path):
            if not stat.S_ISDIR(f.st_mode) and f.filename.lower().endswith(('.xlsx', '.xls')):
                files.append(f)
    except IOError:
        return None

    if not files:
        return None

    files.sort(key=lambda x: x.st_mtime, reverse=True)
    return f"{time_path}/{files[0].filename}"


def find_latest_ocrule_csv_recursive(sftp, folder_path):
    """递归搜索文件夹及其子文件夹，查找包含OCRule的最新csv文件"""
    all_csv_files = []

    def scan_directory(path):
        try:
            for f in sftp.listdir_attr(path):
                full_path = f"{path}/{f.filename}"
                if stat.S_ISDIR(f.st_mode):
                    scan_directory(full_path)
                elif (not stat.S_ISDIR(f.st_mode)
                      and "ocrule" in f.filename.lower()
                      and f.filename.lower().endswith(".csv")):
                    all_csv_files.append((f, full_path))
        except IOError:
            pass

    scan_directory(folder_path)

    if not all_csv_files:
        return None

    all_csv_files.sort(key=lambda x: x[0].st_mtime, reverse=True)
    return all_csv_files[0][1]


def find_latest_transfer_xlsx_recursive(sftp, folder_path):
    """递归搜索文件夹及其子文件夹，查找包含sp-wh_transfer的最新xlsx文件"""
    all_xlsx_files = []

    def scan_directory(path):
        try:
            for f in sftp.listdir_attr(path):
                full_path = f"{path}/{f.filename}"
                if stat.S_ISDIR(f.st_mode):
                    scan_directory(full_path)
                elif (not stat.S_ISDIR(f.st_mode)
                      and "sp-wh_transfer" in f.filename.lower()
                      and f.filename.lower().endswith(('.xlsx', '.xls'))):
                    all_xlsx_files.append((f, full_path))
        except IOError:
            pass

    scan_directory(folder_path)

    if not all_xlsx_files:
        return None

    all_xlsx_files.sort(key=lambda x: x[0].st_mtime, reverse=True)
    return all_xlsx_files[0][1]


def download_file(sftp, remote_file, local_path, convert_to_excel=False):
    """下载文件，可选择是否从 CSV 转换为 Excel"""
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    if convert_to_excel:
        temp_csv_path = "data/temp.csv"
        sftp.get(remote_file, temp_csv_path)
        df = pd.read_csv(temp_csv_path)
        df.to_excel(local_path, index=False)
        os.remove(temp_csv_path)
    else:
        sftp.get(remote_file, local_path)


def process_special_file(sftp, file_name, config):
    """处理特殊文件（ocrule, transfer 等）"""
    search_func_map = {
        "find_latest_ocrule_csv_recursive": find_latest_ocrule_csv_recursive,
        "find_latest_transfer_xlsx_recursive": find_latest_transfer_xlsx_recursive,
    }

    search_func = search_func_map[config["search_func"]]
    remote_file = search_func(sftp, config["remote_folder"])

    if remote_file:
        download_file(sftp, remote_file, config["local_path"], config["convert_to_excel"])
        success_msg = f"[成功] 下载 {remote_file} 到本地 {config['local_path']}\n"
        sys.stdout.buffer.write(success_msg.encode('utf-8'))
    else:
        warn_msg = f"[警告] {file_name} 文件夹中未找到文件。\n"
        sys.stdout.buffer.write(warn_msg.encode('utf-8'))


def process_regular_folder(sftp, folder_name, remote_folder, local_path):
    """处理常规文件夹（spinbound, spoutbound, spinventory）"""
    remote_excel_file = find_latest_excel_in_nested(sftp, remote_folder)

    if not remote_excel_file:
        warn_msg = f"[警告] {folder_name} 文件夹未找到 Excel 文件。\n"
        sys.stdout.buffer.write(warn_msg.encode('utf-8'))
        return

    download_file(sftp, remote_excel_file, local_path, convert_to_excel=False)
    success_msg = f"[成功] 下载 {remote_excel_file} 到本地 {local_path}\n"
    sys.stdout.buffer.write(success_msg.encode('utf-8'))


# 处理特殊文件
for file_name, config in special_files.items():
    process_special_file(sftp, file_name, config)

# 处理常规文件夹
for folder_name, local_path in folders.items():
    remote_folder = f"sp/{folder_name}"
    process_regular_folder(sftp, folder_name, remote_folder, local_path)

sftp.close()
client.close()
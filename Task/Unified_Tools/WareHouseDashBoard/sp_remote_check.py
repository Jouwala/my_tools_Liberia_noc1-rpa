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

remote_base = "sp"

# 本地统一保存到当前脚本目录下的 logs 文件夹
current_dir = os.path.dirname(os.path.abspath(__file__))
local_save_dir = os.path.join(current_dir, "logs")

# 需要查找的文件配置，key=远程子目录，value=本地基础文件名
folders = {
    "spinbound": "inband_details.xlsx",
    "spoutbound": "outband_details.xlsx",
    "spinventory": "inventory_details.xlsx"
}


def build_local_path_with_remote(local_dir, base_local_name, remote_file_path):
    """
    让本地保存文件名包含远程路径信息。
    例如：
    local_dir = ./logs
    base_local_name = inband_details.xlsx
    remote_file_path = sp/spinbound/20250101/120000/a.xlsx
    =>
    ./logs/inband_details__sp__spinbound__20250101__120000__a.xlsx
    """
    name, ext = os.path.splitext(base_local_name)

    remote_path_clean = remote_file_path.strip("/").replace("\\", "/")
    remote_path_part = remote_path_clean.replace("/", "__")

    new_file_name = f"{name}__{remote_path_part}{ext}"
    return os.path.join(local_dir, new_file_name)


def find_latest_subfolder(sftp, base_path):
    """找到 base_path 下修改时间最新的子目录"""
    dirs = []
    try:
        for f in sftp.listdir_attr(base_path):
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
            if not stat.S_ISDIR(f.st_mode) and f.filename.lower().endswith((".xlsx", ".xls")):
                files.append(f)
    except IOError:
        return None

    if not files:
        return None

    files.sort(key=lambda x: x.st_mtime, reverse=True)
    return f"{time_path}/{files[0].filename}"


def find_latest_ocrule_csv_recursive(sftp, folder_path):
    """递归搜索文件夹及其子文件夹，查找包含 OCRule 的最新 csv 文件"""
    all_csv_files = []

    def scan_directory(path):
        try:
            for f in sftp.listdir_attr(path):
                full_path = f"{path}/{f.filename}"
                if stat.S_ISDIR(f.st_mode):
                    scan_directory(full_path)
                elif (
                    not stat.S_ISDIR(f.st_mode)
                    and "ocrule" in f.filename.lower()
                    and f.filename.lower().endswith(".csv")
                ):
                    all_csv_files.append((f, full_path))
        except IOError:
            pass

    scan_directory(folder_path)

    if not all_csv_files:
        return None

    all_csv_files.sort(key=lambda x: x[0].st_mtime, reverse=True)
    return all_csv_files[0][1]


# 创建本地保存目录
os.makedirs(local_save_dir, exist_ok=True)

ocrule_remote_folder = "OCAuto/OCAutoOutput"
ocrule_local_base_name = "ocrule_details.xlsx"
ocrule_remote_file = find_latest_ocrule_csv_recursive(sftp, ocrule_remote_folder)

if ocrule_remote_file:
    ocrule_local_path = build_local_path_with_remote(local_save_dir, ocrule_local_base_name, ocrule_remote_file)
    temp_csv_path = os.path.join(local_save_dir, "temp_ocrule.csv")

    sftp.get(ocrule_remote_file, temp_csv_path)

    df = pd.read_csv(temp_csv_path)
    df.to_excel(ocrule_local_path, index=False)
    os.remove(temp_csv_path)

    success_msg = f"[成功] 下载 {ocrule_remote_file} 并转换为本地 {ocrule_local_path}\n"
    sys.stdout.buffer.write(success_msg.encode("utf-8"))
else:
    warn_msg = "[警告] 未找到包含 OCRule 的 CSV 文件。\n"
    sys.stdout.buffer.write(warn_msg.encode("utf-8"))

# 查找并下载其他 3 个 Excel 文件
for folder, local_base_name in folders.items():
    remote_folder = f"{remote_base}/{folder}"
    remote_excel_file = find_latest_excel_in_nested(sftp, remote_folder)

    if not remote_excel_file:
        warn_msg = f"[警告] {folder} 文件夹未找到 Excel 文件。\n"
        sys.stdout.buffer.write(warn_msg.encode("utf-8"))
        continue

    local_path = build_local_path_with_remote(local_save_dir, local_base_name, remote_excel_file)
    sftp.get(remote_excel_file, local_path)

    success_msg = f"[成功] 下载 {remote_excel_file} 到本地 {local_path}\n"
    sys.stdout.buffer.write(success_msg.encode("utf-8"))

sftp.close()
client.close()

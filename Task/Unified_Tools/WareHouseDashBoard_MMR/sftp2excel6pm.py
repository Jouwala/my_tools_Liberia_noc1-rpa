import paramiko
import os
import sys
import io
# 强制设置标准输出和错误输出的编码为 utf-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

host = "10.100.20.11"
port = 22
username = "ubuntu"
password = "UbuntU1!2@3#4$"

client = paramiko.Transport((host, port))
client.connect(username=username, password=password)
sftp = paramiko.SFTPClient.from_transport(client)

remote_base = "sp"
folders = {
    "spinbound": "data/inband_details.xlsx",
    "spoutbound": "data/outband_details.xlsx",
    "spinventory": "data/inventory_details.xlsx"
}

def find_latest_subfolder(sftp, base_path):
    """找到 base_path 下修改时间最新的子目录"""
    dirs = []
    for f in sftp.listdir_attr(base_path):
        if f.longname.startswith('d') or f.filename.isdigit():
            dirs.append(f)
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

    # 找 Excel 文件
    files = [f for f in sftp.listdir_attr(time_path) if f.filename.endswith(('.xlsx', '.xls'))]
    if not files:
        return None

    files.sort(key=lambda x: x.st_mtime, reverse=True)
    latest_excel = files[0].filename
    return f"{time_path}/{latest_excel}"

for folder, local_path in folders.items():
    remote_folder = f"{remote_base}/{folder}"
    remote_excel = find_latest_excel_in_nested(sftp, remote_folder)

    if not remote_excel:
        print(f"[警告] {folder} 没找到 Excel 文件。")
        continue

    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    sftp.get(remote_excel, local_path)
    print(f"[成功] 下载 {remote_excel} 到本地 {local_path}")

sftp.close()
client.close()

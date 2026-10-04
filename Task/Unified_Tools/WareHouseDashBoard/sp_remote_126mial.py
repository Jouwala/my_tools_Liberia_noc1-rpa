import paramiko
import os
import stat
import pandas as pd
import sys
import smtplib
from email.message import EmailMessage
from mimetypes import guess_type


host = "10.100.20.11"
port = 22
username = "ubuntu"
password = "UbuntU1!2@3#4$"

# ⚠ 超时是必需项（2026-10-04 网络风暴专项整改）。
# paramiko 的 Transport((host, port)) 与 connect() **默认都没有超时**：
# 上游 SFTP 一旦半死不活（TCP 建连成功但不出 banner），本进程会**永久挂起**，
# 不报错、不退出，并一直占着连接。若被巡检/看门狗重跑，就会每 5 分钟
# 叠加一个挂起进程 —— 这是"请求量放大"里最难排查的一类。
# 写法照搬 my_app 已修复的同类问题：
# Task/my_app/backend/services/sp_report_gen/gernarate_sp_report.py:476-490
import socket as _socket

_sock = _socket.create_connection((host, port), timeout=30)
client = paramiko.Transport(_sock)
client.set_keepalive(30)
client.connect(username=username, password=password)
sftp = paramiko.SFTPClient.from_transport(client)
try:
    _chan = sftp.get_channel()
    if _chan is not None:
        _chan.settimeout(180)  # 服务端应用层挂死时，channel 读不再永久阻塞
except Exception as _e:
    print(f"  [WARN] SFTP channel 超时设置失败（退回无超时模式）: {_e}")

remote_base = "sp"

# 本地统一保存到 /logs/ 目录下
local_save_dir = "/logs"

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
    local_dir = /logs
    base_local_name = inband_details.xlsx
    remote_file_path = sp/spinbound/20250101/120000/a.xlsx
    =>
    /logs/inband_details__sp__spinbound__20250101__120000__a.xlsx
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


def send_email_with_attachments(smtp_host, smtp_port, sender_email, sender_password,
                                receiver_email, subject, body, attachment_paths):
    msg = EmailMessage()
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg["Subject"] = subject
    msg.set_content(body)

    for file_path in attachment_paths:
        if not os.path.isfile(file_path):
            continue

        mime_type, _ = guess_type(file_path)
        if mime_type:
            maintype, subtype = mime_type.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"

        with open(file_path, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype=maintype,
                subtype=subtype,
                filename=os.path.basename(file_path)
            )

    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(sender_email, sender_password)
        server.send_message(msg)


downloaded_files = []

# 创建本地保存目录
os.makedirs(local_save_dir, exist_ok=True)

try:
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

        downloaded_files.append(ocrule_local_path)

        success_msg = f"[成功] 下载 {ocrule_remote_file} 并转换为本地 {ocrule_local_path}\n"
        sys.stdout.buffer.write(success_msg.encode('utf-8'))
    else:
        warn_msg = "[警告] 未找到包含 OCRule 的 CSV 文件。\n"
        sys.stdout.buffer.write(warn_msg.encode('utf-8'))

    # 查找并下载其他3个Excel文件
    for folder, local_base_name in folders.items():
        remote_folder = f"{remote_base}/{folder}"
        remote_excel_file = find_latest_excel_in_nested(sftp, remote_folder)

        if not remote_excel_file:
            warn_msg = f"[警告] {folder} 文件夹未找到 Excel 文件。\n"
            sys.stdout.buffer.write(warn_msg.encode('utf-8'))
            continue

        local_path = build_local_path_with_remote(local_save_dir, local_base_name, remote_excel_file)
        sftp.get(remote_excel_file, local_path)
        downloaded_files.append(local_path)

        success_msg = f"[成功] 下载 {remote_excel_file} 到本地 {local_path}\n"
        sys.stdout.buffer.write(success_msg.encode('utf-8'))

finally:
    sftp.close()
    client.close()

# =========================
# 邮件配置（请替换为你自己的发件箱配置）
# =========================
smtp_host = "smtp.126.com"
smtp_port = 465
sender_email = "xin83min@126.com"
sender_password = "LQcTaMMuWmhvAfRB"
receiver_email = "xin83min@126.com"

if downloaded_files:
    subject = "SFTP下载文件"
    body = "您好，附件为本次从服务器下载的文件，请查收。"

    try:
        send_email_with_attachments(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            sender_email=sender_email,
            sender_password=sender_password,
            receiver_email=receiver_email,
            subject=subject,
            body=body,
            attachment_paths=downloaded_files
        )
        success_msg = f"[成功] 邮件已发送给 {receiver_email}，附件数量：{len(downloaded_files)}\n"
        sys.stdout.buffer.write(success_msg.encode('utf-8'))
    except Exception as e:
        error_msg = f"[错误] 邮件发送失败：{str(e)}\n"
        sys.stdout.buffer.write(error_msg.encode('utf-8'))
else:
    warn_msg = "[警告] 没有可发送的附件，跳过邮件发送。\n"
    sys.stdout.buffer.write(warn_msg.encode('utf-8'))

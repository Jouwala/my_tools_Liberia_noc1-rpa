import paramiko
import os
import sys
import io

# --- 凭据引导（2026-10-04）：口令不写在源码里，统一走共享入口 ---
# 优先环境变量，其次「设置 → 凭据管理」页面（credential_store）。
import os as _os, sys as _sys
# 注意：判据是 credentials.py 这个**文件**，不是 shared/ 这个**目录**。
# Task/Unified_Tools/shared 也存在但里面没有 credentials.py，只判目录会
# 命中它、import 失败后被 except 吞掉 -> 静默降级为空口令（实测踩过）。
_ws = _os.path.dirname(_os.path.abspath(__file__))
_cand = None
while _ws:
    _try = _os.path.join(_ws, "Unified_Tools", "shared", "credentials.py")
    if _os.path.isfile(_try):
        _cand = _try
        break
    _p = _os.path.dirname(_ws)
    if _p == _ws:
        break
    _ws = _p
if _cand:
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_cand)))
try:
    from shared.credentials import get_credential as _get_credential
except Exception:  # 凭据库不可用时降级，不让脚本直接崩
    def _get_credential(_key, env=None, default=""):
        return (_os.environ.get(env, "") if env else "") or default

# 强制设置标准输出和错误输出的编码为 utf-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

host = "10.100.20.11"
port = 22
username = "ubuntu"
password = _get_credential("sftp_sp", env="SFTP_SP_PASS")

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

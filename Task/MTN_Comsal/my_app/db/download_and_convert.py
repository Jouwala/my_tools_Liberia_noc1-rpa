import paramiko
import os
import stat
import openpyxl
import sqlite3

# SFTP 配置
SFTP_HOST = "10.201.47.62"
SFTP_PORT = 22
SFTP_USER = "ubuntu"
SFTP_PASS = "CloudStudio__123"
REMOTE_DIR = "/home/ubuntu/reports/Last-2month-All-TTs/"
LOCAL_DIR = r"C:\FineBI6.0\webapps\Python\TT"
LOCAL_XLSX = os.path.join(LOCAL_DIR, "Last-month-All-TTs.xlsx")
LOCAL_DB = os.path.join(LOCAL_DIR, "db.sqlite3")


def find_latest_xlsx(sftp, remote_dir):
    """递归查找远程目录下最新的 xlsx 文件"""
    latest_file = None
    latest_mtime = 0

    def walk(path):
        nonlocal latest_file, latest_mtime
        try:
            entries = sftp.listdir_attr(path)
        except IOError:
            return
        for entry in entries:
            full_path = path.rstrip("/") + "/" + entry.filename
            if stat.S_ISDIR(entry.st_mode):
                walk(full_path)
            elif entry.filename.endswith(".xlsx"):
                if entry.st_mtime > latest_mtime:
                    latest_mtime = entry.st_mtime
                    latest_file = full_path

    walk(remote_dir)
    return latest_file, latest_mtime


def download_latest_file():
    """通过 SFTP 下载最新的 xlsx 文件"""
    print(f"连接 SFTP {SFTP_HOST}...")
    # ⚠ 超时是必需项（2026-10-04 网络风暴专项整改）。
    # paramiko 的 Transport((host, port)) 与 connect() **默认都没有超时**：
    # 上游 SFTP 一旦半死不活（TCP 建连成功但不出 banner），本进程会**永久挂起**，
    # 不报错、不退出，并一直占着连接。若被巡检/看门狗重跑，就会每 5 分钟
    # 叠加一个挂起进程 —— 这是"请求量放大"里最难排查的一类。
    # 写法照搬 my_app 已修复的同类问题：
    # Task/my_app/backend/services/sp_report_gen/gernarate_sp_report.py:476-490
    import socket as _socket
    
    _sock = _socket.create_connection((SFTP_HOST, SFTP_PORT), timeout=30)
    transport = paramiko.Transport(_sock)
    transport.set_keepalive(30)
    transport.connect(username=SFTP_USER, password=SFTP_PASS)
    sftp = paramiko.SFTPClient.from_transport(transport)
    try:
        _chan = sftp.get_channel()
        if _chan is not None:
            _chan.settimeout(180)  # 服务端应用层挂死时，channel 读不再永久阻塞
    except Exception as _e:
        print(f"  [WARN] SFTP channel 超时设置失败（退回无超时模式）: {_e}")

    try:
        print(f"递归查找远程目录: {REMOTE_DIR}")
        remote_path, mtime = find_latest_xlsx(sftp, REMOTE_DIR)
        if not remote_path:
            raise FileNotFoundError(f"远程目录 {REMOTE_DIR} 下未找到 .xlsx 文件")

        print(f"最新文件: {remote_path} (修改时间戳: {mtime})")

        os.makedirs(LOCAL_DIR, exist_ok=True)
        print(f"下载到: {LOCAL_XLSX}")
        sftp.get(remote_path, LOCAL_XLSX)
        print("下载完成!")
    finally:
        sftp.close()
        transport.close()


def xlsx_to_sqlite():
    """读取 xlsx 文件并按 Ticket No. 更新或新增到 SQLite 数据库"""
    print(f"\n读取 Excel 文件: {LOCAL_XLSX}")
    wb = openpyxl.load_workbook(LOCAL_XLSX, data_only=True)

    conn = sqlite3.connect(LOCAL_DB)
    cursor = conn.cursor()

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        print(f"处理工作表: {sheet_name}")

        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            print(f"  工作表 '{sheet_name}' 为空，跳过")
            continue

        # 第一行作为列名
        headers = rows[0]
        col_names = []
        for i, h in enumerate(headers):
            if h is None or str(h).strip() == "":
                col_names.append(f"column_{i}")
            else:
                clean = str(h).strip().replace(" ", "_").replace("-", "_")
                clean = "".join(c for c in clean if c.isalnum() or c == "_")
                col_names.append(clean if clean else f"column_{i}")

        # 确保列名不重复
        seen = {}
        unique_names = []
        for name in col_names:
            if name in seen:
                seen[name] += 1
                unique_names.append(f"{name}_{seen[name]}")
            else:
                seen[name] = 0
                unique_names.append(name)
        col_names = unique_names

        # 查找 Ticket_No 列的索引（作为唯一键）
        ticket_col = None
        for idx, name in enumerate(col_names):
            if name.lower() in ("ticket_no", "ticketno"):
                ticket_col = idx
                break
        if ticket_col is None:
            print("  未找到 Ticket No. 列，跳过该工作表")
            continue
        ticket_key = col_names[ticket_col]
        print(f"  使用 '{ticket_key}' 作为唯一键进行更新/新增")

        # 表名使用工作表名
        table_name = sheet_name.strip().replace(" ", "_").replace("-", "_")
        table_name = "".join(c for c in table_name if c.isalnum() or c == "_")
        if not table_name:
            table_name = "sheet"
        if table_name[0].isdigit():
            table_name = "t_" + table_name

        # 创建表（如果不存在），Ticket_No 列设为 UNIQUE
        cols_def = ", ".join(
            f'"{c}" TEXT' + (' UNIQUE' if c == ticket_key else '')
            for c in col_names
        )
        cursor.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({cols_def})')

        # 如果表已存在但没有 UNIQUE 约束，重建唯一索引
        try:
            cursor.execute(
                f'CREATE UNIQUE INDEX IF NOT EXISTS "idx_{table_name}_{ticket_key}" '
                f'ON "{table_name}" ("{ticket_key}")'
            )
        except sqlite3.OperationalError:
            pass

        # 使用 INSERT OR REPLACE 实现 upsert
        placeholders = ", ".join(["?"] * len(col_names))
        upsert_sql = f'INSERT OR REPLACE INTO "{table_name}" VALUES ({placeholders})'

        # 查询现有记录数
        cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        count_before = cursor.fetchone()[0]

        inserted = 0
        updated = 0
        existing_tickets = set()
        cursor.execute(f'SELECT "{ticket_key}" FROM "{table_name}"')
        for r in cursor.fetchall():
            if r[0] is not None:
                existing_tickets.add(str(r[0]))

        data_rows = []
        for row in rows[1:]:
            values = list(row) + [None] * (len(col_names) - len(row))
            values = [str(v) if v is not None else None for v in values[:len(col_names)]]
            ticket_val = values[ticket_col]
            if ticket_val is not None and ticket_val in existing_tickets:
                updated += 1
            else:
                inserted += 1
                if ticket_val is not None:
                    existing_tickets.add(ticket_val)
            data_rows.append(values)

        if data_rows:
            cursor.executemany(upsert_sql, data_rows)
            print(f"  新增 {inserted} 行，更新 {updated} 行（共 {len(data_rows)} 行）")

        cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        count_after = cursor.fetchone()[0]
        print(f"  表中总记录数: {count_after}")

    conn.commit()
    conn.close()
    wb.close()
    print(f"\nSQLite 数据库已更新: {LOCAL_DB}")
    print("全部完成!")


if __name__ == "__main__":
    download_latest_file()
    xlsx_to_sqlite()

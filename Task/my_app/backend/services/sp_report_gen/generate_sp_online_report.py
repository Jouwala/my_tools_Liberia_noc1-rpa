# -*- coding: utf-8 -*-
"""
Generate SP "online" open-ticket table images and Excel files
(Inbound.png/.xlsx, Outbound.png/.xlsx)
into my_app/data/sp_email/sp_online.

Pipeline:
  load -> exclude closed/draft statuses -> dedup by ticket No.
  -> parse 'Verify Detail' (earliest Verify Operation Time = Approved Time,
     operator of the latest Verify = Current Operation Owner, mapped to
     real name via person table in db/app.db by objectid)
  -> sort by Create Time desc -> render PNG (Pillow) + styled Excel (openpyxl)

数据源（两支路，2026-09-30 起）：
  Inbound  —— 读 data/sp_email/data/inband_details.xlsx（SFTP 明细，口径不变）。
  Outbound —— 读库表 sp_outbound（`sp_online_sync` 每小时从 eFlow SP 接口拉全量）。
              改自 xlsx 的原因见下。

【为什么 Outbound 必须改读库表】
上游 SFTP 产出的 outband.xlsx **不含 `Status='WaitingForUpdate'`**（等待更新的在途出库单）。
2026-09-30 实测：未过滤的原始快照 outband_details_source.xlsx 里 WaitingForUpdate 为 0 行，
处理后明细同样是 0 行，而库表 sp_outbound 有 37 行。也就是说该状态在报表的第 4 道过滤
（EXCLUDED_STATUS）**之前**就已经不存在了，只靠放开过滤条件取不到它。
业务要求"把等待更新和等待归还的状态一并跟踪"，故 Outbound 支路整体改读 sp_outbound。

另外两点也因此受益：
1. xlsx 支路的 Step 2.2 `apply_status_filters()` 会把 WaitingForUpdate 从**共享明细**里删掉，
   而那份明细同时供 SpareParts/Consumables 报表与看板使用。改读库表后，
   SP Online 报表与共享明细解耦，**不必去动那道过滤**，其他报表不受影响。
2. 库表由小时级同步保持新鲜，不受 06:00 那次 SFTP 快照的时点限制。
"""
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# 本脚本以子进程方式运行（backend/services/kpi_email_report.py 调 sys.executable），
# 需把项目根塞进 sys.path 才能 import backend.* —— 同 sp_online_sync.py 的写法。
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.database import get_raw_connection

from gernarate_sp_report import _render_summary_image, _resolve_output_path, style_excel

_SCRIPT_DIR = Path(__file__).resolve().parent
_APP_ROOT = _SCRIPT_DIR.parent.parent.parent
DATA_DIR = _APP_ROOT / 'data' / 'sp_email' / 'data'
OUT_DIR = _APP_ROOT / 'data' / 'sp_email' / 'sp_online'

INB_PATH = DATA_DIR / 'inband_details.xlsx'
OUTB_PATH = DATA_DIR / 'outband_details.xlsx'

# Operation:Verify.  Operation Time:2026-01-12 17:16:34.  Operator:FE_FE_107.
VERIFY_PAIR_RE = re.compile(
    r'Operation:Verify\.[^\n]*?'
    r'Operation Time:(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.?\s*'
    r'Operator:([A-Za-z0-9_]+)'
)

OUT_COLS = ['Operation No.', 'Status', 'Operation Type', 'Warehouse Name',
            'Create Time', 'Approved Time', 'Closed Time',
            'Approval Duration', 'Close Duration', 'Current Operation Owner']

# SP 在线单排除名单：这些状态不要（仅 Inbound 支路仍在用）
EXCLUDED_STATUS = ('WaitingForReturn', 'Draft', 'WaitingForUpdate', 'Closed')

# ---------------------------------------------------------------------------
# Outbound 支路：库表 sp_outbound
# ---------------------------------------------------------------------------
# 要跟踪的"未关闭在途"状态。业务口径：等待更新 + 等待归还一并跟踪。
# WaitingForConfirm 也是未关闭在途态，取实测存在的全集，避免日后新增状态静默漏出。
OUTBOUND_TRACK_STATUS = ('WaitingForUpdate', 'WaitingForReturn', 'WaitingForConfirm')

# 库表列 -> 报表列 的映射。报表列名沿用 xlsx 口径，下游邮件/收件人配置无需改。
OUTBOUND_DB_COLS = {
    'woNum': 'Operation No.',
    'status': 'Status',
    'outboundType': 'Operation Type',
    'warehouseId': 'Warehouse Name',
    'createTime_str': 'Create Time',
    'outboundTime_str': 'Approved Time',
    'closedTime_str': 'Closed Time',
    'candidateOperatorRealName': 'Candidate Operator',
}
# 追溯用：库表最后同步时间列，写进报表标题便于判断数据新鲜度
FETCHED_AT_COL = '_fetched_at'


def resolve_candidates(value, person_names):
    """`P:FE_FE_134,P:FE_FE_107` -> `Amara Jakson, GORSON PRINCE T`。

    eFlow 该字段是「候选处理人」列表，元素带 `P:`（个人）/`G:`（岗位组）前缀。
    `person` 表只认前缀后的 id，未命中的（如 `G:WH_KP` 这类岗位组）保留原 id，
    与 xlsx 支路「查不到保留原 ID」的处理一致。
    """
    if not isinstance(value, str) or not value.strip():
        return ''
    out = []
    for item in value.split(','):
        item = item.strip()
        if not item:
            continue
        _prefix, _, ident = item.partition(':')
        ident = ident or item          # 无前缀时整串当 id
        out.append(person_names.get(ident) or ident)
    # 去重但保持顺序
    seen, uniq = set(), []
    for n in out:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return ', '.join(uniq)


def load_person_names():
    """objectid -> name from person table（走项目连接层，兼容 PG / SQLite）。"""
    with get_raw_connection(timeout=30.0) as con:
        rows = con.cursor().execute('SELECT objectid, name FROM person').fetchall()
    return {k: v for k, v in rows if k and v}


def load_outbound_from_db(person_names, statuses=OUTBOUND_TRACK_STATUS):
    """从库表 sp_outbound 读在途出库单，返回 (DataFrame, 库表最后同步时间, 命中行数)。

    只取 statuses 里的状态（未关闭在途），按 woNum 去重（一单一行）。
    列名与 xlsx 支路解耦：这里直接产出报表最终列，不再走 Verify Detail 解析。

    ⚠️ **必须走 `get_raw_connection()`，不要裸 `sqlite3.connect(db/app.db)`**：
    现状是 `MY_APP_DB_MODE=pg`，`sp_online_sync` 写的是 **PostgreSQL**；
    `db/app.db` 只是 `pg_to_sqlite_sync`（每小时 :45）落的**离线快照**，
    直连它会读到最多滞后约 1 小时的数据（2026-09-30 实测：副本 14:35 vs 真库 15:00）。
    连接层会自动把 `?` 占位符转成 PG 的 `%s`，故下面直接用 `?` 即可。

    ⚠️ **列名必须加双引号**：这些列建表时是带引号的混合大小写标识符（见
    `sp_online_sync.save_to_db`），而 PostgreSQL 会把不加引号的标识符折叠成小写
    （`woNum` → `wonum`）从而报「字段不存在」。SQLite 不区分大小写，所以只加引号即可两边通用。

    口径说明（2026-09-30 实测）：
      `outboundTime` 语义等同 xlsx 口径的 Approved Time —— 出库动作完成时间。
      未审批的单（WaitingForUpdate / WaitingForConfirm）该列为空，
      对应 Approval Duration 也留空，属预期而非缺数据。
    """
    def q(col):
        return '"' + col.replace('"', '""') + '"'

    cols = ', '.join(q(c) for c in OUTBOUND_DB_COLS)
    ph = ','.join('?' * len(statuses))
    with get_raw_connection(timeout=30.0) as con:
        cur = con.cursor()
        rows = cur.execute(
            f'SELECT {cols} FROM sp_outbound WHERE "status" IN ({ph})',
            tuple(statuses),
        ).fetchall()
        fetched_at = cur.execute(
            f'SELECT MAX({q(FETCHED_AT_COL)}) FROM sp_outbound').fetchone()[0]

    df = pd.DataFrame(rows, columns=list(OUTBOUND_DB_COLS.values()))
    n_raw = len(df)

    # 去重：同一单号保留首行（与 xlsx 支路 keep='first' 一致）
    df = df.drop_duplicates(subset=['Operation No.'], keep='first')

    create_dt = pd.to_datetime(df['Create Time'], errors='coerce')
    approve_dt = pd.to_datetime(df['Approved Time'], errors='coerce')
    closed_dt = pd.to_datetime(df['Closed Time'], errors='coerce')

    owner = df['Candidate Operator'].map(lambda v: resolve_candidates(v, person_names))

    out = pd.DataFrame({
        'Operation No.': _display_str(df['Operation No.']),
        'Status': df['Status'].astype(str).str.strip(),
        'Operation Type': _display_str(df['Operation Type']),
        'Warehouse Name': _display_str(df['Warehouse Name']),
        'Create Time': _display_str(df['Create Time']),
        'Approved Time': _display_str(df['Approved Time']),
        'Closed Time': _display_str(df['Closed Time']),
        'Approval Duration': (approve_dt - create_dt).dt.total_seconds().map(fmt_duration),
        'Close Duration': (closed_dt - approve_dt).dt.total_seconds().map(fmt_duration),
        'Current Operation Owner': owner,
    })[OUT_COLS]

    out = out.assign(_ct=create_dt.values) \
             .sort_values('_ct', ascending=False, na_position='last') \
             .drop(columns='_ct') \
             .reset_index(drop=True)
    return out, fetched_at, n_raw


def pick_verify(detail):
    """From one Verify Detail string return (earliest verify time, operator of latest verify).

    Entries in the log are not guaranteed chronological, so sort by parsed time.
    """
    if not isinstance(detail, str):
        return '', ''
    pairs = VERIFY_PAIR_RE.findall(detail)
    if not pairs:
        return '', ''
    parsed = sorted((datetime.strptime(t, '%Y-%m-%d %H:%M:%S'), op) for t, op in pairs)
    return parsed[0][0].strftime('%Y-%m-%d %H:%M:%S'), parsed[-1][1]


def fmt_duration(seconds):
    """Seconds -> '<x.x>h' below one day, else '<d>d <h>h'."""
    if pd.isna(seconds):
        return ''
    s = float(seconds)
    if abs(s) < 86400:
        return f'{s / 3600:.1f}h'
    sign = '-' if s < 0 else ''
    s = abs(s)
    return f'{sign}{int(s // 86400)}d {round((s % 86400) / 3600)}h'


def _display_str(series):
    """Series -> string Series with NaN/NaT rendered as ''."""
    return series.astype('object').where(series.notna(), '').astype(str)


def build_open_tickets(df, no_col, type_col, person_names):
    """Exclude unwanted statuses, one row per ticket, compute display columns."""
    status = df['Status'].astype(str).str.strip()
    open_df = df[~status.isin(EXCLUDED_STATUS)].copy()
    n_raw = len(open_df)
    open_df = open_df.drop_duplicates(subset=[no_col], keep='first')

    picked = open_df['Verify Detail'].astype(str).map(pick_verify)
    approved_time = picked.str[0]
    owner_id = picked.str[1]

    create_dt = pd.to_datetime(open_df['Create Time'], errors='coerce')
    approve_dt = pd.to_datetime(approved_time.replace('', None), errors='coerce')
    closed_dt = pd.to_datetime(open_df['Closed Time'], errors='coerce')

    approval_secs = (approve_dt - create_dt).dt.total_seconds()
    close_secs = (closed_dt - approve_dt).dt.total_seconds()

    owner = pd.Series(owner_id).map(person_names).fillna(owner_id)

    out = pd.DataFrame({
        'Operation No.': _display_str(open_df[no_col]),
        'Status': open_df['Status'].astype(str).str.strip(),
        'Operation Type': _display_str(open_df[type_col]),
        'Warehouse Name': _display_str(open_df['Warehouse Name']),
        'Create Time': _display_str(open_df['Create Time']),
        'Approved Time': approved_time,
        'Closed Time': _display_str(open_df['Closed Time']),
        'Approval Duration': approval_secs.map(fmt_duration),
        'Close Duration': close_secs.map(fmt_duration),
        'Current Operation Owner': owner,
    })[OUT_COLS]

    out = out.assign(_ct=create_dt.values) \
             .sort_values('_ct', ascending=False, na_position='last') \
             .drop(columns='_ct') \
             .reset_index(drop=True)
    return out, n_raw


def _emit(table, sheet_name, label, title, src_desc, stats):
    """渲染 PNG + XLSX 并打印一行统计。"""
    img_path = _resolve_output_path(str(OUT_DIR / f'{sheet_name}.png'))
    _render_summary_image(table, img_path, title=title, has_total_row=False,
                          row_h=28, char_w=9, font_size=14)

    xlsx_path = _resolve_output_path(str(OUT_DIR / f'{sheet_name}.xlsx'))
    with pd.ExcelWriter(xlsx_path, engine='openpyxl') as writer:
        table.to_excel(writer, sheet_name=sheet_name, index=False)
        style_excel(writer.sheets[sheet_name], sheet_name, has_total_row=False, title=title)

    print(f'{label}: {stats}, unique tickets={len(table)}')
    print(f'  source -> {src_desc}')
    print(f'  image  -> {img_path}')
    print(f'  excel  -> {xlsx_path}')


def main():
    t0 = datetime.now()
    ts = t0.strftime('%Y-%m-%d %H:%M:%S')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    person_names = load_person_names()

    # ---- Inbound：仍读 SFTP 明细（上游导出全部为 Closed，通常只有表头，属预期） ----
    df = pd.read_excel(INB_PATH)
    table, n_filtered = build_open_tickets(df, 'Inbound No.', 'Inbound Type', person_names)
    _emit(table, 'Inbound', 'SP Online Inbound',
          f'SP Online Inbound  |  {ts}  |  Tickets: {len(table)}',
          f'{INB_PATH.name} (SFTP 明细)',
          f'raw={len(df)}, open rows={n_filtered}')

    # ---- Outbound：改读库表 sp_outbound，跟踪等待更新 / 等待归还 / 等待确认 ----
    table, fetched_at, n_raw = load_outbound_from_db(person_names)
    # 标题带库表同步时间：报表"新鲜到什么程度"一眼可判，不再只看生成时间
    sync_note = f'synced {fetched_at}' if fetched_at else 'sync time unknown'
    _emit(table, 'Outbound', 'SP Online Outbound',
          f'SP Online Outbound  |  {ts}  |  Tickets: {len(table)}  |  {sync_note}',
          f'sp_outbound ({sync_note})',
          f'in-flight rows={n_raw}, tracking={"+".join(OUTBOUND_TRACK_STATUS)}')

    elapsed = (datetime.now() - t0).total_seconds()
    print(f'Done. Total time: {elapsed:.1f}s')


if __name__ == '__main__':
    main()

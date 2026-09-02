# -*- coding: utf-8 -*-
"""
Generate SP "online" open-ticket table images and Excel files
(Inbound.png/.xlsx, Outbound.png/.xlsx)
into my_app/data/sp_email/sp_online, using the latest
inband_details.xlsx / outband_details.xlsx under my_app/data/sp_email/data.

Pipeline:
  load xlsx -> filter Status != 'Closed' -> dedup by ticket No.
  -> parse 'Verify Detail' (earliest Verify Operation Time = Approved Time,
     operator of the latest Verify = Current Operation Owner, mapped to
     real name via person table in db/app.db by objectid)
  -> sort by Create Time desc -> render PNG (Pillow) + styled Excel (openpyxl)
"""
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from gernarate_sp_report import _render_summary_image, _resolve_output_path, style_excel

_SCRIPT_DIR = Path(__file__).resolve().parent
_APP_ROOT = _SCRIPT_DIR.parent.parent.parent
DATA_DIR = _APP_ROOT / 'data' / 'sp_email' / 'data'
OUT_DIR = _APP_ROOT / 'data' / 'sp_email' / 'sp_online'
DB_PATH = _APP_ROOT / 'db' / 'app.db'

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


def load_person_names(db_path=DB_PATH):
    """objectid -> name from person table."""
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute('SELECT objectid, name FROM person').fetchall()
    finally:
        con.close()
    return {k: v for k, v in rows if k and v}


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
    """Filter Status != 'Closed', one row per ticket, compute display columns."""
    open_df = df[df['Status'].astype(str).str.strip().ne('Closed')].copy()
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


def main():
    t0 = datetime.now()
    ts = t0.strftime('%Y-%m-%d %H:%M:%S')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    person_names = load_person_names()

    jobs = [
        (INB_PATH, 'Inbound No.', 'Inbound Type', 'Inbound', 'SP Online Inbound'),
        (OUTB_PATH, 'Outbound No.', 'Outbound Type', 'Outbound', 'SP Online Outbound'),
    ]
    for src, no_col, type_col, sheet_name, label in jobs:
        df = pd.read_excel(src)
        table, n_filtered = build_open_tickets(df, no_col, type_col, person_names)
        title = f'{label}  |  {ts}  |  Open tickets: {len(table)}'

        img_path = _resolve_output_path(str(OUT_DIR / f'{sheet_name}.png'))
        _render_summary_image(table, img_path, title=title, has_total_row=False,
                              row_h=28, char_w=9, font_size=14)

        xlsx_path = _resolve_output_path(str(OUT_DIR / f'{sheet_name}.xlsx'))
        with pd.ExcelWriter(xlsx_path, engine='openpyxl') as writer:
            table.to_excel(writer, sheet_name=sheet_name, index=False)
            style_excel(writer.sheets[sheet_name], sheet_name, has_total_row=False, title=title)

        print(f'{label}: raw={len(df)}, open rows={n_filtered}, unique tickets={len(table)}')
        print(f'  image -> {img_path}')
        print(f'  excel -> {xlsx_path}')

    elapsed = (datetime.now() - t0).total_seconds()
    print(f'Done. Total time: {elapsed:.1f}s')


if __name__ == '__main__':
    main()

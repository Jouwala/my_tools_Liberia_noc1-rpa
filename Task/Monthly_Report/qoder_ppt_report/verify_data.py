# -*- coding: utf-8 -*-
import sqlite3

DB = r'data\orange_liberia_monthly.sqlite3'
con = sqlite3.connect(DB)
cur = con.cursor()

def q(table, cols):
    colsql = ', '.join(f'"{c}"' for c in cols)
    return cur.execute(f'SELECT {colsql} FROM "{table}" ORDER BY "Begin Time"').fetchall()

def num(v):
    try:
        return float(str(v).replace('%','').strip())
    except Exception:
        return None

TARGETS = {  # (表, 列, 目标, 方向: >=为正向)
    '2G CSSR voice': ('GSM_NW_1month','OCI_2G_CSSR_CS(%)',0.97,'>='),
    '2G DCR': ('GSM_NW_1month','TCH in call drop rate(include handover)(%)',0.02,'<='),
    '3G CSSR': ('UMTS_NW_1month','U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO',0.97,'>='),
    '3G DCR': ('UMTS_NW_1month','Ratio of CS Call Drop(%)',0.02,'<='),
    '3G CSSR HSDPA': ('UMTS_NW_1month','U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO',0.98,'>='),
    '3G DCR HSDPA': ('UMTS_NW_1month','U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO',0.02,'<='),
    '3G->2G HO': ('UMTS_NW_1month','Cell Inter-RAT CS Outgoing Handover Success Rate(WCDMA->GSM)(%)',0.95,'>='),
}

months = sorted({r[0][:7] for r in cur.execute('SELECT "Begin Time" FROM GSM_NW_1month')})
print('months:', months)
print()
print('=== Network KPIs 达标校验 (P2) ===')
hdr = f"{'KPI':<16}" + ''.join(f'{m[2:]:>8}' for m in months)
print(hdr)
for name,(t,c,tgt,direction) in TARGETS.items():
    rows = q(t, ['Begin Time', c])
    line = f'{name:<16}'
    for bt, v in rows:
        x = num(v)
        if x is None:
            line += f"{'--':>8}"
        else:
            ok = x >= tgt if direction=='>' + '=' else x <= tgt
            line += f"{('V' if ok else 'X')+f'{x*100:.2f}':>8}" if False else f"{x*100:>6.2f}{'v' if ok else 'x'} "
    print(line)

print()
print('=== Traffic 月度汇总 (P3) ===')
gsm = {r[0][:7]: r for r in q('GSM_NW_1month', ['Begin Time','TCH total traffic number(erl)','U31_ZTE_Traffic of Uplink Data TBF (GByte)_900241_2_gv4.bsc-MO','U31_ZTE_Traffic of Downlink Data TBF (GByte)_901415_2_gv4.bsc-MO'])}
umts = {r[0][:7]: r for r in q('UMTS_NW_1month', ['Begin Time','Cell Traffic Volume, CS(Erl)','U31_Cell DL Traffic Volume, PS(GB)_901411_2_UROP.RNC-MO','U31_Cell UL Traffic Volume, PS(GB)_901410_2_UROP.RNC-MO'])}
fdd = {r[0][:7]: r for r in q('FDD_NW_1month', ['Begin Time','[FDD]DL Traffic Volume (GBytes)-new','[FDD]UL Traffic Volume (GBytes)-new'])}
print(f"{'Month':<9}{'Voice(Erl)':>14}{'Data(GB)':>14}")
for mth in months:
    g,u,f = gsm.get(mth), umts.get(mth), fdd.get(mth)
    voice = sum(filter(None,[num(g[1]) if g else None, num(u[1]) if u else None]))
    data = sum(filter(None,[num(g[2]) if g else None, num(g[3]) if g else None,
                            num(u[2]) if u else None, num(u[3]) if u else None,
                            num(f[1]) if f else None, num(f[2]) if f else None]))
    print(f'{mth:<9}{voice:>14,.0f}{data:>14,.1f}')

# 检查 NULL 比例
print()
print('=== 空值检查 ===')
for t in ['GSM_NW_1month','UMTS_NW_1month','FDD_NW_1month']:
    cols = [c[1] for c in cur.execute(f'PRAGMA table_info("{t}")')]
    nulls = []
    for c in cols:
        n = cur.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{c}" IS NULL OR TRIM(CAST("{c}" AS TEXT)) = \'\'').fetchone()[0]
        if n: nulls.append(f'{c}:{n}')
    print(t, '| 空值列:', nulls if nulls else '无')

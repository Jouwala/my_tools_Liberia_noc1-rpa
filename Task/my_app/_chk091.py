# -*- coding: utf-8 -*-
import sqlite3
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
c = sqlite3.connect(r"D:\01_RPA\Task\my_app\db\app.db")
r = c.execute("SELECT tt_no, site_name, created_time FROM eflow_tt WHERE tt_no='TT202609100091'").fetchone()
print("091 in db:", r)
mx = c.execute("SELECT MAX(tt_no) FROM eflow_tt WHERE tt_no LIKE 'TT20260910%'").fetchone()
print("max today tt_no:", mx)
c.close()
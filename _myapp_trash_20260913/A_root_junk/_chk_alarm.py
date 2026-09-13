# -*- coding: utf-8 -*-
import sqlite3, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
c = sqlite3.connect(r"D:\01_RPA\Task\my_app\db\app.db")
r = c.execute(
    "SELECT alarm_id, alarm_code, alarm_occur_time, alarm_server_time, site_name "
    "FROM eflow_tt WHERE tt_no='TT202609100095'").fetchone()
print("TT095 alarm cols:", r)
cols = [x[1] for x in c.execute("PRAGMA table_info(eflow_tt)").fetchall()]
print("has alarm_key:", "alarm_key" in cols, "| has alarm_id:", "alarm_id" in cols)
c.close()
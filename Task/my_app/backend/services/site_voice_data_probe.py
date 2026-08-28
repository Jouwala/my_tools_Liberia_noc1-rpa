# -*- coding: utf-8 -*-
import sys, io, os
os.environ["MAIN_KPI_READ_TIMEOUT"] = "180"
sys.path.insert(0, r"D:\01_RPA\Task\my_app")
from backend.services import ran_ume_main_kpi as R
import pandas as pd

tasks = [
    {"tech": "UMTS", "grouplayer": "me,WV4.IubLink", "gr": "86400",
     "groupbygroup": True, "layer": "Sites", "table": "3G_Main_Kpi_Site_Daily",
     "add_group_column": False, "showbusinesscolumn": None},
    {"tech": "FDD", "grouplayer": "me,eNodeBFunction", "gr": "86400",
     "groupbygroup": True, "layer": "Sites", "table": "4G_Main_Kpi_Site_Daily",
     "add_group_column": False, "showbusinesscolumn": True},
]
auth = R.login()
print("[PROBE] login ok")
for t in tasks:
    try:
        payload = R.build_kpi_payload(t["tech"], t["grouplayer"], t["gr"],
                                      t["groupbygroup"], showbusinesscolumn=t["showbusinesscolumn"])
        qid = R.create_history_query(auth["cookie"], auth["forgery_token"], payload)
        status = R.wait_history_ready(auth["cookie"], auth["forgery_token"], qid,
                                      timeout=600, interval=8)
        data = R.export_history(auth["cookie"], auth["forgery_token"], qid, filename="probe")
        df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
        print(f"\n=== {t['tech']} Sites ===")
        print("shape=", df.shape)
        print("cols=", list(df.columns))
        print(df.head(2).to_string())
    except Exception as e:
        import traceback
        print(f"[ERR] {t['tech']}: {e}")
        traceback.print_exc()

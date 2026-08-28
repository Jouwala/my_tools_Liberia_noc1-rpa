# -*- coding: utf-8 -*-
"""
按站点合并「语音 + 数据业务」指标（复用 RAN_UME 站点级 KPI 拉取能力）。

逻辑：
  1. 登录 UME 网管（带重试）
  2. 串行拉取 2G(GSM)/3G(UMTS)/4G(FDD) 三个 Sites 层级 KPI（内存 Excel）
  3. 按站点名称合并语音类与数据类指标
  4. 输出本地 Excel: data/ran_ume/site_voice_data.xlsx
"""
import sys, io, os, time
os.environ.setdefault("MAIN_KPI_READ_TIMEOUT", "180")
sys.path.insert(0, r"D:\01_RPA\Task\my_app")

from backend.services import ran_ume_main_kpi as R
import pandas as pd

OUT_PATH = r"D:\01_RPA\Task\my_app\data\ran_ume\site_voice_data.xlsx"


def login_retry(max_tries=4):
    last = None
    for i in range(1, max_tries + 1):
        try:
            auth = R.login()
            if auth and auth.get("cookie"):
                print(f"[LOGIN] ok (try {i})")
                return auth
        except Exception as e:
            last = e
            print(f"[LOGIN] retry {i} failed: {e}")
            time.sleep(5)
    raise last or RuntimeError("login failed")


# 三个站点级任务
TASKS = [
    {"tech": "GSM", "grouplayer": "me,gv4.BTSSiteManager", "gr": "86400",
     "groupbygroup": True, "layer": "Sites", "table": "2G_Main_Kpi_Site_Daily",
     "showbusinesscolumn": None,
     "site_key": "SITE Name", "site_id": "SITE ID"},
    {"tech": "UMTS", "grouplayer": "me,WV4.IubLink", "gr": "86400",
     "groupbygroup": True, "layer": "Sites", "table": "3G_Main_Kpi_Site_Daily",
     "showbusinesscolumn": None,
     "site_key": "NodeB Name", "site_id": "NodeB ID"},
    {"tech": "FDD", "grouplayer": "  me,eNodeBFunction", "gr": "86400",
     "groupbygroup": True, "layer": "Sites", "table": "4G_Main_Kpi_Site_Daily",
     "showbusinesscolumn": True,
     "site_key": "eNodeB Name", "site_id": "eNodeB ID"},
]


def fetch_task(auth, t):
    payload = R.build_kpi_payload(t["tech"], t["grouplayer"].strip(), t["gr"],
                                  t["groupbygroup"],
                                  showbusinesscolumn=t["showbusinesscolumn"])
    qid = R.create_history_query(auth["cookie"], auth["forgery_token"], payload)
    R.wait_history_ready(auth["cookie"], auth["forgery_token"], qid, timeout=600, interval=8)
    data = R.export_history(auth["cookie"], auth["forgery_token"], qid, filename=t["tech"])
    return pd.read_excel(io.BytesIO(data), engine="openpyxl")


# 语音类 / 数据类 指标映射（按表已知列）
VOICE_COLS = {
    "GSM": ["TCH total traffic number(erl)", "OCI_2G_CSSR_CS(%)", "TCH in call drop rate(%)",
            "SDCCH congestion rate(%)", "TCH in service rate(%)"],
    "UMTS": ["Cell Traffic Volume, CS(Erl)", "U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO",
             "Ratio of CS Call Drop(%)", "Call Setup Success rate(%)"],
    "FDD": ["[FDD]CSFB Preparation success rate[SDR_ITBBU]",
            "[FDD]Call Setup Success Rate[SDR_ITBBU]", "[FDD]E-RAB Drop Rate[SDR_ITBBU]"],
}
DATA_COLS = {
    "GSM": [],  # 2G 以语音为主，无独立 PS 流量列
    "UMTS": ["U31_Cell UL Traffic Volume, PS(GB)_901410_2_UROP.RNC-MO",
             "U31_Cell DL Traffic Volume, PS(GB)_901411_2_UROP.RNC-MO",
             "Ratio of PS Call Drop(%)",
             "U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO",
             "U31_3G+ Call Setup Success Rate – HSUPA Data services_901598_2_UROP.RNC-MO"],
    "FDD": ["[FDD]DL Traffic Volume (GBytes)-new", "[FDD]UL Traffic Volume (GBytes)-new",
            "[FDD]DL IP Throughput(Mbps)[SDR_ITBBU]", "[FDD]UL IP Throughput(Mbps)[SDR_ITBBU]"],
}


def main():
    auth = login_retry()
    frames = {}
    for t in TASKS:
        print(f"[FETCH] {t['tech']} Sites ...")
        df = fetch_task(auth, t)
        df = df.rename(columns={t["site_key"]: "站点名称", t["site_id"]: f"{t['tech']}_站点ID"})
        df["技术制式"] = t["tech"]
        # 保留关键列
        keep = ["站点名称", f"{t['tech']}_站点ID"]
        for c in VOICE_COLS[t["tech"]] + DATA_COLS[t["tech"]]:
            if c in df.columns:
                keep.append(c)
        frames[t["tech"]] = df[keep].copy()
        print(f"  -> {t['tech']} rows={len(df)}")

    # 合并：以「站点名称」为主键，分别保留各制式的语音/数据指标
    merged = None
    for t in TASKS:
        df = frames[t["tech"]]
        if merged is None:
            merged = df
        else:
            merged = pd.merge(merged, df, on="站点名称", how="outer")

    # 汇总 sheet：仅语音+数据指标，按技术前缀
    summary_rows = []
    for t in TASKS:
        df = frames[t["tech"]]
        rec = {"技术制式": t["tech"]}
        rec["站点数"] = len(df)
        for label, cols in [("语音", VOICE_COLS[t["tech"]]), ("数据", DATA_COLS[t["tech"]])]:
            for c in cols:
                if c in df.columns:
                    rec[f"{label}_{c}"] = ""  # 占位，具体按站点在明细
        summary_rows.append(rec)
    summary = pd.DataFrame(summary_rows)

    with pd.ExcelWriter(OUT_PATH, engine="openpyxl") as xw:
        merged.to_excel(xw, sheet_name="站点合并明细", index=False)
        summary.to_excel(xw, sheet_name="汇总", index=False)
        for t in TASKS:
            frames[t["tech"]].to_excel(xw, sheet_name=f"{t['tech']}_原始", index=False)

    print(f"[DONE] 输出 -> {OUT_PATH}")
    print(f"[DONE] merged rows={len(merged)}, cols={list(merged.columns)}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
Packet Loss 服务：从 RAN UME 获取丢包率 PM 数据 → 合并 → 写入 lte_pl.sqlite3 → 生成报告

流程（对应 data/packet_lost/要求.txt）：
1. 复用 ran_ume_service 的登录/HTTP 通道，查询两个 PM 模板（近 7 天，1 小时粒度）：
   - Packet Loss Rate_SDR_IPPD   (grouplayer: me,sdrmgr.SrcIP,sdrmgr.DesIP)
   - Packet Loss Rate_ITRAN_IPPD (grouplayer: me,TransportNetwork,IPPD)
2. 导出文件命名规则：templatename_grouplayer映射_gr映射（仅内存标识，不落盘）
3. 两个导出只保留指定字段（SDR 的 Source/Destination IP ID 改名 srcIp/dstIp）后合并，
   丢包率按模板 Step 3 规则 ×100 转为百分比数值，全程内存处理直接写入数据库
4. 合并数据写入 data/packet_lost/lte_pl.sqlite3，并关联 eflow.sqlite3 站点信息
   （site_name / gateway(TRM Type) / network_type / region / province_county / latitude / longitude），
   按模板 Packet_Loss_Status_Output Automation.xlsx 格式生成带公式的报告（顶部含日期）
5. 站点级汇总写入 site_pl_summary 表，供丢包看板 API 使用
"""
import os
import json
import time
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

try:
    from .ran_ume_service import (
        _login, _http_request, _pm_auth_headers, _read_xlsx_bytes,
        _run_with_cleanup,
        PM_HISTORY_PATH, PM_HISTORY_POLL_PATH, PM_HISTORY_EXPORT_PATH,
        MAX_PARALLEL_WORKERS,
    )
    from .atomic_write import atomic_save_workbook, AtomicReplaceFallback
except ImportError:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:packet_loss_service>: exception swallowed", exc_info=True)
    from ran_ume_service import (
        _login, _http_request, _pm_auth_headers, _read_xlsx_bytes,
        _run_with_cleanup,
        PM_HISTORY_PATH, PM_HISTORY_POLL_PATH, PM_HISTORY_EXPORT_PATH,
        MAX_PARALLEL_WORKERS,
    )
    from atomic_write import atomic_save_workbook, AtomicReplaceFallback

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from backend.database import get_raw_connection

logger = logging.getLogger("packet_loss_service")

# ========== 路径配置 ==========
PL_DATA_DIR = Path(r"d:\01_RPA\Task\my_app\data\packet_lost")
PL_DB_PATH = PL_DATA_DIR / "lte_pl.sqlite3"
PL_REPORT_PATH = PL_DATA_DIR / "Packet_Loss_Status_Report.xlsx"
EFLOW_DB_PATH = Path(r"d:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3")

# 查询窗口：7 天到现在（可用环境变量调整）
PL_DAYS_BACK = int(os.environ.get("PL_DAYS_BACK", "7"))
# 本地库保留天数（超过则清理）
PL_RETENTION_DAYS = int(os.environ.get("PL_RETENTION_DAYS", "35"))

# ========== 文件命名映射（要求.txt 第1条） ==========
GROUPLAYER_MAP = {
    "me,WV4.IubLink": "Sites",
    "me,gv4.BTSSiteManager": "Sites",
    "me,eNodeBFunction": "Sites",
    "me,TransportNetwork,IPPD": "Sites",
    "me,sdrmgr.SrcIP,sdrmgr.DesIP": "Sites",
    "me,gv4.BTSSiteManager,gv4.BTS.cell": "Cells",
    "me,eNodeBFunction,EUtranCellFDD": "Cells",
    "me,WV4.IubLink,WV4.UtranCell": "Cells",
    "me,fservice": "NE",
    "me": "NE",
}
GR_MAP = {"2592000": "1Month", "86400": "1Day", "3600": "1Hour"}

# 合并后统一保留的字段（要求.txt 第3条）
MERGED_COLUMNS = [
    "Begin Time", "End Time", "Granularity", "SubnetWork ID", "SubnetWork Name",
    "ManagedElement ID", "Managed Element", "dstIp", "srcIp", "Packet Loss Rate(%)",
]
PL_COL = "Packet Loss Rate(%)"

# ========== 查询模板配置（要求.txt 第2条抓包 payload） ==========
def _timeinfo():
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=PL_DAYS_BACK)
    return {
        "mode": 1,
        "start": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "end": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "relative": -PL_DAYS_BACK,
        "timezonetype": "1",
        "clienttimezone": "Atlantic/Reykjavik",
        "showtimezoneoffset": False,
        "querylongtime": {"type": 3, "value": 1},
        "timespanfilter": "00:00:00-24:00:00",
        "dayfiltertype": 0,
        "dayinmonthfilter": "1111111111111111111111111111111",
    }


PL_QUERY_CONFIGS = [
    {
        "templatename": "Packet Loss Rate_SDR_IPPD",
        "templateid": "1638004470045",
        "motid": "sdrmgr.PlatIPPD",
        "nfctid": "SDR",
        "grouplayer": "me,sdrmgr.SrcIP,sdrmgr.DesIP",
        "showbusinesscolumn": False,
        "keep_columns": [
            "Begin Time", "End Time", "Granularity", "SubnetWork ID", "SubnetWork Name",
            "ManagedElement ID", "Managed Element", "Source IP ID", "Destination IP ID", PL_COL,
        ],
        "rename_columns": {"Destination IP ID": "dstIp", "Source IP ID": "srcIp"},
    },
    {
        "templatename": "Packet Loss Rate_ITRAN_IPPD",
        "templateid": "1638004470043",
        "motid": "IPPD",
        "nfctid": "ITBBU",
        "grouplayer": "me,TransportNetwork,IPPD",
        "showbusinesscolumn": True,
        "keep_columns": list(MERGED_COLUMNS),
        "rename_columns": {},
    },
]


def grouplayer_label(grouplayer: str, groupbygroup: bool = False) -> str:
    """grouplayer → 文件名标签（要求.txt 第1条映射规则）"""
    if grouplayer == "all":
        return "Group" if groupbygroup else "NW"
    return GROUPLAYER_MAP.get(grouplayer, grouplayer.replace(",", "_"))


def build_export_filename(templatename: str, grouplayer: str, gr: str,
                          groupbygroup: bool = False) -> str:
    """templatename_grouplayer映射_gr映射，下划线连接（要求.txt 第1条）"""
    parts = [templatename, grouplayer_label(grouplayer, groupbygroup), GR_MAP.get(str(gr), str(gr))]
    return "_".join(parts)


def _build_pl_payload(cfg: dict) -> dict:
    return {
        "arraycounterinfos": [], "datatype": 0, "displaymode": 0,
        "favoriteconditionname": cfg["templatename"], "gr": "3600",
        "groupattributetype": 0, "groupbygroup": False, "groupbyplmn": False,
        "grouptype": 0, "items": ["C370200000"], "itemsposition": [0],
        "itemsposition1": [0], "motid": cfg["motid"], "nfctid": cfg["nfctid"],
        "plmnpdfdisplaymode": False, "queryallbusiness": False,
        "showbusinesscolumn": cfg["showbusinesscolumn"], "showintegrity": False,
        "straightquery": False, "templatename": cfg["templatename"],
        "templateid": cfg["templateid"], "versiondatacompare": False,
        "needdeployfilter": False, "timeinfo": _timeinfo(),
        "indexfillingtype": "default", "thresholdinfos": [], "templatetype": 0,
        "filterlayer": "all", "grouplayer": cfg["grouplayer"], "containvcell": 0,
        "resfilterattribute": "", "uilocations": [], "reslocation": [],
        "inexistenceres": False, "firstDayOfWeek": 7, "iswireless": True,
        "hidehistorystopbutton": True, "opencustomizehistoryexport": False,
        "opentemplatecustomcolumn": False, "invaliditems": [],
    }


# ========== 查询 + 导出 ==========
def _run_pl_query(cookie: str, forgery_token: str, cfg: dict):
    """执行单个丢包率 PM 查询 + 导出，返回 (本地文件名, xlsx字节)"""
    templatename = cfg["templatename"]
    logger.info(f"[PL] 开始查询 [{templatename}]")
    payload = _build_pl_payload(cfg)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = _pm_auth_headers(cookie, forgery_token)

    status, _, _, resp_body = _http_request("POST", PM_HISTORY_PATH, headers_extra=headers, body=body)
    if "200" not in status:
        raise Exception(f"创建 PM 查询失败 [{templatename}]: {status}")

    data = json.loads(resp_body.decode("utf-8"))
    queryid = data.get("queryid") or data.get("id")
    if not queryid:
        raise Exception(f"未获取到 queryid [{templatename}]: {resp_body.decode('utf-8', errors='replace')[:500]}")

    # 轮询查询进度
    poll_path = f"{PM_HISTORY_POLL_PATH}?type=0&queryid={queryid}"
    deadline = time.time() + 600
    while time.time() < deadline:
        _, _, _, resp_body = _http_request("GET", poll_path, headers_extra=headers)
        poll_data = json.loads(resp_body.decode("utf-8"))
        if poll_data.get("querystate") == 1 or poll_data.get("progress", 0) >= 100:
            break
        time.sleep(5)

    # 导出
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    export_payload = {
        "id": queryid,
        "filename": f"Performance Management-History Query-{templatename}-NOC-{ts}",
        "exportfiletype": 1, "itemshowtype": 0, "formatwithts": 0, "contentmode": 0,
        "customizefieldtype": "0", "imageinfo": [], "chartlayout": 1,
        "exportserialnumber": False, "exporttableheaders": False, "tableheaders": {},
    }
    export_body = json.dumps(export_payload, ensure_ascii=False).encode("utf-8")
    status, _, _, resp_body = _http_request("POST", PM_HISTORY_EXPORT_PATH, headers_extra=headers, body=export_body)
    if "200" not in status:
        raise Exception(f"导出失败 [{templatename}]: {status}")

    local_name = build_export_filename(templatename, cfg["grouplayer"], payload["gr"]) + ".xlsx"
    logger.info(f"[PL] [{templatename}] 导出完成: {len(resp_body)} bytes -> {local_name}")
    return local_name, resp_body


# ========== 数据清洗合并（要求.txt 第3条，全部向量化） ==========
def _normalize_export_df(xlsx_bytes: bytes, cfg: dict) -> pd.DataFrame:
    headers, rows = _read_xlsx_bytes(xlsx_bytes)
    df = pd.DataFrame(rows, columns=headers)
    keep = [c for c in cfg["keep_columns"] if c in df.columns]
    missing = [c for c in cfg["keep_columns"] if c not in df.columns]
    if missing:
        logger.warning(f"[PL] [{cfg['templatename']}] 缺少列: {missing}")
    df = df[keep].copy()
    if cfg["rename_columns"]:
        df = df.rename(columns=cfg["rename_columns"])
    # 统一列顺序
    df = df.reindex(columns=MERGED_COLUMNS)
    df[PL_COL] = pd.to_numeric(df[PL_COL], errors="coerce").fillna(0.0)
    # 模板 Step 3 规则：UME 返回的丢包率为小数，需 ×100 转为百分比数值
    df[PL_COL] = df[PL_COL] * 100.0
    df["Begin Time"] = pd.to_datetime(df["Begin Time"], errors="coerce")
    df = df.dropna(subset=["Begin Time"])
    df = df[df["Managed Element"].notna() & (df["Managed Element"].astype(str).str.strip() != "")]
    return df


# ========== SQLite 写入 ==========
def _init_db(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS packet_loss_data (
        "Begin Time"          TEXT NOT NULL,
        "End Time"            TEXT,
        "Granularity"         TEXT,
        "SubnetWork ID"       TEXT,
        "SubnetWork Name"     TEXT,
        "ManagedElement ID"   TEXT,
        "Managed Element"     TEXT,
        "dstIp"               TEXT,
        "srcIp"               TEXT,
        "Packet Loss Rate(%)" REAL,
        _sync_time            TEXT,
        UNIQUE("Begin Time", "ManagedElement ID", "srcIp", "dstIp")
    );
    CREATE INDEX IF NOT EXISTS idx_pl_begin_time ON packet_loss_data("Begin Time");
    CREATE INDEX IF NOT EXISTS idx_pl_me ON packet_loss_data("Managed Element");

    CREATE TABLE IF NOT EXISTS site_pl_summary (
        Site_Name       TEXT PRIMARY KEY,
        Site_Code       TEXT,
        gateway         TEXT,
        network_type    TEXT,
        region          TEXT,
        province_county TEXT,
        latitude        REAL,
        longitude       REAL,
        LastDayMaxPL    REAL,
        TotalPL         REAL,
        AffectedHours   INTEGER,
        FinalStatus     TEXT,
        updated_at      TEXT
    );

    CREATE TABLE IF NOT EXISTS pl_meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    # 历史数据量级迁移：早期入库的丢包率为小数，模板 Step 3 要求 ×100 为百分比数值
    row = conn.execute("SELECT value FROM pl_meta WHERE key='value_scale'").fetchone()
    if row is None or row[0] != "percent":
        conn.execute('UPDATE packet_loss_data SET "Packet Loss Rate(%)" = "Packet Loss Rate(%)" * 100')
        conn.execute("INSERT OR REPLACE INTO pl_meta (key, value) VALUES ('value_scale', 'percent')")
        logger.info("[PL] 已将历史丢包率数据 ×100 转为百分比数值")
    conn.commit()


def _write_merged_to_db(df: pd.DataFrame) -> int:
    """合并数据 upsert 写入 lte_pl.sqlite3（向量化准备 + executemany 批量写）"""
    now_iso = datetime.now().isoformat(timespec="seconds")
    out = df.copy()
    out["Begin Time"] = out["Begin Time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    out["_sync_time"] = now_iso
    out = out.drop_duplicates(subset=["Begin Time", "ManagedElement ID", "srcIp", "dstIp"], keep="last")
    records = out.where(pd.notna(out), None).values.tolist()

    with get_raw_connection(str(PL_DB_PATH), timeout=60) as conn:
        try:
            _init_db(conn)
            sql = """
        INSERT INTO packet_loss_data
            ("Begin Time","End Time","Granularity","SubnetWork ID","SubnetWork Name",
             "ManagedElement ID","Managed Element","dstIp","srcIp","Packet Loss Rate(%)",_sync_time)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT("Begin Time","ManagedElement ID","srcIp","dstIp") DO UPDATE SET
            "End Time"=excluded."End Time",
            "Granularity"=excluded."Granularity",
            "SubnetWork ID"=excluded."SubnetWork ID",
            "SubnetWork Name"=excluded."SubnetWork Name",
            "Managed Element"=excluded."Managed Element",
            "Packet Loss Rate(%)"=excluded."Packet Loss Rate(%)",
            _sync_time=excluded._sync_time
        """
            conn.executemany(sql, records)
            # 清理超期数据
            cutoff = (datetime.now() - timedelta(days=PL_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
            cur = conn.execute('DELETE FROM packet_loss_data WHERE "Begin Time" < ?', (cutoff,))
            if cur.rowcount:
                logger.info(f"[PL] 清理超期数据: {cur.rowcount} 行")
            conn.commit()
        finally:
            conn.close()
        return len(records)


# ========== 站点信息关联（eflow.sqlite3 site 表，向量化匹配） ==========
def _load_site_info() -> pd.DataFrame:
    with get_raw_connection(str(EFLOW_DB_PATH), timeout=60) as conn:
        try:
            site = pd.read_sql_query(
                'SELECT "Site ID", "Site Name", Region, Province, District, Latitude, Longitude, '
                '"TRM Type", "Network Type", Vendor FROM site', conn)
        finally:
            conn.close()
        site = site.rename(columns={
            "Site ID": "Site_Code", "Site Name": "Site_Name", "TRM Type": "gateway",
            "Network Type": "network_type",
        })
        site["province_county"] = site["Province"]
        site["locality"] = site["District"]
        site["_name_key"] = site["Site_Name"].astype(str).str.strip().str.lower()
        site["_code_key"] = site["Site_Code"].astype(str).str.strip()
        return site


def _extract_me_parts(me_series: pd.Series):
    """Managed Element 形如 'Aureus Mining(4255)' → (名字, ID)，向量化提取"""
    me = me_series.astype(str)
    name = me.str.replace(r"\s*\(\d+\)\s*$", "", regex=True).str.strip()
    code = me.str.extract(r"\((\d+)\)\s*$")[0]
    return name, code


def classify_status(v) -> str:
    """丢包等级分类（与报告 FINAL_STATUS 一致）"""
    if v is None or pd.isna(v):
        return "No Packet loss[<0.1]"
    v = float(v)
    if v > 5:
        return "Critical[>5]"
    if v >= 1:
        return "Major[1-5]"
    if v >= 0.5:
        return "Minor[0.5-1]"
    if v >= 0.1:
        return "Warning[0.1-0.5]"
    return "No Packet loss[<0.1]"


# ========== 站点级汇总 + 报告生成（要求.txt 第4条） ==========
def _build_site_summary(df: pd.DataFrame, site: pd.DataFrame):
    """按站点按小时汇总（sum），生成站点级宽表与汇总信息"""
    df = df.copy()
    df["hour"] = df["Begin Time"].dt.floor("h")
    name, code = _extract_me_parts(df["Managed Element"])
    df["_site_name"] = name.where(name != "", df["Managed Element"].astype(str))
    df["_site_code"] = code

    # 站点 × 小时 的丢包率合计（向量化 pivot）
    pivot = df.pivot_table(index="_site_name", columns="hour", values=PL_COL,
                           aggfunc="sum", fill_value=0.0)
    pivot = pivot.reindex(columns=pd.date_range(pivot.columns.min(), pivot.columns.max(), freq="h"),
                          fill_value=0.0)

    # 站点属性关联：先按名字匹配，再按括号内 ID 匹配
    name_map = site.drop_duplicates("_name_key").set_index("_name_key")
    code_map = site.drop_duplicates("_code_key").set_index("_code_key")

    site_keys = pd.Series(pivot.index.str.strip().str.lower(), index=pivot.index)
    code_keys = df.groupby("_site_name")["_site_code"].first()

    info_rows = []
    for site_name in pivot.index:
        key = site_keys[site_name]
        row = name_map.loc[key] if key in name_map.index else None
        if row is None:
            ck = code_keys.get(site_name)
            if ck is not None and ck in code_map.index:
                row = code_map.loc[ck]
        ck = code_keys.get(site_name)
        info_rows.append({
            "Site_Name": site_name,
            "Display_Name": f"{site_name}({ck})" if ck else site_name,
            "Site_Code": str(row["Site_Code"]) if row is not None else (ck or ""),
            "gateway": row["gateway"] if row is not None else "",
            "network_type": row["network_type"] if row is not None else "",
            "region": row["Region"] if row is not None else "",
            "province_county": row["province_county"] if row is not None else "",
            "locality": row["locality"] if row is not None and pd.notna(row["locality"]) else "",
            "vendor": row["Vendor"] if row is not None and pd.notna(row["Vendor"]) else "",
            "latitude": row["Latitude"] if row is not None else None,
            "longitude": row["Longitude"] if row is not None else None,
        })
    info = pd.DataFrame(info_rows).set_index("Site_Name")

    last24 = pivot.columns[-24:]
    summary = pivot.copy()
    summary = summary.join(info)
    summary["LastDayMaxPL"] = pivot[last24].max(axis=1)
    summary["TotalPL"] = pivot.sum(axis=1)
    summary["AffectedHours"] = (pivot > 0).sum(axis=1)
    summary["FinalStatus"] = summary["LastDayMaxPL"].map(classify_status)
    summary = summary.sort_values("LastDayMaxPL", ascending=False)
    return pivot, summary


def _generate_report(pivot: pd.DataFrame, summary: pd.DataFrame) -> str:
    """按模板 Packet_Loss_Status_Output Automation.xlsx 格式生成报告（原子写，顶部含日期）"""
    wb = openpyxl.Workbook()

    # ===== Sheet: Packet Loss Report（模板布局） =====
    ws = wb.active
    ws.title = "Packet Loss Report"
    hour_cols = list(pivot.columns)
    n_hours = len(hour_cols)

    # 第 1 行：日期（报告日期 + 数据范围）
    now = datetime.now()
    ws.cell(row=1, column=1,
            value=(f"Date: {now.strftime('%Y-%m-%d %H:%M')}    "
                   f"Data Range: {hour_cols[0].strftime('%Y-%m-%d %H:%M')} ~ "
                   f"{hour_cols[-1].strftime('%Y-%m-%d %H:%M')}"))
    ws.cell(row=1, column=1).font = Font(bold=True, size=12)

    # 第 2 行：表头（模板 A~L 元数据列 + 小时列 + 统计列 + GC~GE + GG~HD 小时块）
    meta_cols = ["Cluster", "County", "Locality", "Site Code", "Site_Name",
                 "Longitude", "Latitude", "Vendor", "Media",
                 "BB MW/Fiber Site1 code", "Equipment BB1", "Row Labels"]
    headers = meta_cols + [h.strftime("%Y-%m-%d %H:%M:%S") for h in hour_cols] + \
        ["(Last 1 day Max PL)", "STATUS", "FINAL_STATUS",
         "MW - IPRAN Link Status", "Main Category", "Expansion Planned?"]
    header_row = 2
    for j, hv in enumerate(headers, start=1):
        ws.cell(row=header_row, column=j, value=hv)
    # 小时块表头 0~23（模板 GG~HD，前空一列）
    hour_block_start = len(headers) + 2
    for h in range(24):
        ws.cell(row=header_row, column=hour_block_start + h, value=h)

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True, size=10)
    for c in ws[header_row]:
        if c.value is not None:
            c.fill = header_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center")

    n_meta = len(meta_cols)
    first_hour_col = n_meta + 1
    last_hour_col = n_meta + n_hours
    max_col = last_hour_col + 1
    status_col = last_hour_col + 2
    final_col = last_hour_col + 3
    max_col_l = get_column_letter(max_col)
    status_col_l = get_column_letter(status_col)
    final_col_l = get_column_letter(final_col)
    # 最近 3 天 × 24 小时的列偏移（模板 GG~HD 公式语义：同一小时连续 3 天均 >0.5 计 1）
    has_3days = n_hours >= 72
    gg_l = [get_column_letter(first_hour_col + (n_hours - 72) + h) for h in range(24)]
    gg_m = [get_column_letter(first_hour_col + (n_hours - 48) + h) for h in range(24)]
    gg_n = [get_column_letter(first_hour_col + (n_hours - 24) + h) for h in range(24)]

    first_data_row = header_row + 1
    last24_start_l = get_column_letter(last_hour_col - 23)
    last_hour_l = get_column_letter(last_hour_col)

    for i, (site_name, row) in enumerate(summary.iterrows(), start=first_data_row):
        meta = [row.get("region", ""), row.get("province_county", ""), row.get("locality", ""),
                row.get("Site_Code", ""), row.get("Display_Name", site_name),
                row.get("longitude") if pd.notna(row.get("longitude")) else None,
                row.get("latitude") if pd.notna(row.get("latitude")) else None,
                row.get("vendor", ""), row.get("gateway", ""), "", "",
                row.get("Display_Name", site_name)]
        for j, v in enumerate(meta, start=1):
            ws.cell(row=i, column=j, value=v)
        # 小时丢包值（模板数值格式 0.00）
        for j, v in enumerate(pivot.loc[site_name].values):
            cell = ws.cell(row=i, column=first_hour_col + j, value=float(v))
            cell.number_format = "0.00"
        # (Last 1 day Max PL) / STATUS / FINAL_STATUS 公式（与模板一致）
        ws.cell(row=i, column=max_col, value=f"=MAX({last24_start_l}{i}:{last_hour_l}{i})")
        gg_first = get_column_letter(hour_block_start)
        gg_last = get_column_letter(hour_block_start + 23)
        ws.cell(row=i, column=status_col,
                value=f'=IF(SUM({gg_first}{i}:{gg_last}{i})=0,"OK","NOK")')
        ws.cell(row=i, column=final_col,
                value=(f'=IF({status_col_l}{i}="OK","No Packet loss[<0.1]",'
                       f'LOOKUP({max_col_l}{i},{{0.1;0.5;1;5}},'
                       f'{{"Warning[0.1-0.5]";"Minor[0.5-1]";"Major[1-5]";"Critical[>5]"}}))'))
        # GG~HD 小时块：同一小时最近 3 天均 >0.5 → 1
        if has_3days:
            for h in range(24):
                ws.cell(row=i, column=hour_block_start + h,
                        value=f"=IF(AND({gg_l[h]}{i}>0.5,{gg_m[h]}{i}>0.5,{gg_n[h]}{i}>0.5),1,0)")

    last_data_row = first_data_row + len(summary) - 1
    ws.freeze_panes = ws.cell(row=first_data_row, column=first_hour_col)
    ws.column_dimensions["E"].width = 22
    ws.column_dimensions["L"].width = 26

    # ===== Sheet: Summary（模板布局：PL Status/Count/原因列/百分比） =====
    ws2 = wb.create_sheet("Summary")
    ws2.append(["PL Status", "Count of Sites", "Link Congested", "Link Issue",
                "Power issue onsite", "Up grade to IPRAN", "Percentage of Sites"])
    for c in ws2[1]:
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center")
    statuses = [("Critical [>5]", "Critical[>5]"), ("Major [1-5]", "Major[1-5]"),
                ("Minor [0.5-1]", "Minor[0.5-1]"), ("Warning [0.1-0.5]", "Warning[0.1-0.5]"),
                ("No Packet loss[<0.1]", "No Packet loss[<0.1]")]
    detail_range = f"'Packet Loss Report'!{final_col_l}{first_data_row}:{final_col_l}{last_data_row}"
    for r, (label, val) in enumerate(statuses, start=2):
        ws2.cell(row=r, column=1, value=label)
        ws2.cell(row=r, column=2, value=f'=COUNTIF({detail_range},"{val}")')
        ws2.cell(row=r, column=7, value=f"=B{r}/SUM(B$2:B$6)")
        ws2.cell(row=r, column=7).number_format = "0.00%"
        ws2.cell(row=r, column=8, value=f"=B{r}-SUM(C{r}:F{r})")
    for col, width in zip("ABCDEFGH", (22, 14, 14, 12, 18, 18, 20, 10)):
        ws2.column_dimensions[col].width = width

    # ===== Sheet: Database（模板同名站点主数据表） =====
    ws3 = wb.create_sheet("Database")
    ws3.append(["ME ID", "Managed Element", "County", "Cluster", "Longitude", "Latitude"])
    for c in ws3[1]:
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center")
    for site_name, r in summary.iterrows():
        code = r.get("Site_Code", "")
        ws3.append([int(code) if str(code).isdigit() else code,
                    r.get("Display_Name", site_name), r.get("province_county", ""),
                    r.get("region", ""),
                    float(r["longitude"]) if pd.notna(r.get("longitude")) else None,
                    float(r["latitude"]) if pd.notna(r.get("latitude")) else None])

    # ===== 保存（原子写） =====
    try:
        atomic_save_workbook(wb, str(PL_REPORT_PATH))
        out_path = str(PL_REPORT_PATH)
    except AtomicReplaceFallback as fb:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _generate_report: exception swallowed", exc_info=True)
        out_path = fb.fallback_path
    finally:
        wb.close()
    return out_path


def _save_summary_to_db(summary: pd.DataFrame, report_path: str, rows_written: int):
    now_iso = datetime.now().isoformat(timespec="seconds")
    with get_raw_connection(str(PL_DB_PATH), timeout=60) as conn:
        try:
            _init_db(conn)
            conn.execute("DELETE FROM site_pl_summary")
            records = []
            for site_name, r in summary.iterrows():
                records.append((
                    site_name, str(r.get("Site_Code", "") or ""), str(r.get("gateway", "") or ""),
                    str(r.get("network_type", "") or ""), str(r.get("region", "") or ""),
                    str(r.get("province_county", "") or ""),
                    float(r["latitude"]) if pd.notna(r.get("latitude")) else None,
                    float(r["longitude"]) if pd.notna(r.get("longitude")) else None,
                    float(r["LastDayMaxPL"]), float(r["TotalPL"]), int(r["AffectedHours"]),
                    r["FinalStatus"], now_iso,
                ))
            conn.executemany(
                "INSERT OR REPLACE INTO site_pl_summary "
                "(Site_Name,Site_Code,gateway,network_type,region,province_county,latitude,longitude,"
                "LastDayMaxPL,TotalPL,AffectedHours,FinalStatus,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                records)
            conn.executemany(
                "INSERT OR REPLACE INTO pl_meta (key, value) VALUES (?, ?)",
                [("last_sync_time", now_iso), ("report_path", report_path),
                 ("rows_written", str(rows_written)), ("total_sites", str(len(summary)))])
            conn.commit()
        finally:
            conn.close()


# ========== 主任务 ==========
def run_packet_loss_sync() -> dict:
    """完整丢包数据同步任务：UME 取数 → 合并 → 入库 → 报告"""
    start_time = time.time()
    result = {"success": False, "errors": [], "files": [], "rows": 0,
              "sites": 0, "report": "", "elapsed_seconds": 0}

    try:
        # Step 1: 登录
        auth = _login()
        cookie, forgery = auth["cookie"], auth["forgery_token"]

        # Step 2: 并行查询两个模板
        exported = {}
        with ThreadPoolExecutor(max_workers=max(2, MAX_PARALLEL_WORKERS)) as executor:
            futures = {
                executor.submit(_run_with_cleanup, _run_pl_query, cookie, forgery, cfg): cfg
                for cfg in PL_QUERY_CONFIGS
            }
            for future in as_completed(futures):
                cfg = futures[future]
                try:
                    fname, xlsx_bytes = future.result()
                    exported[cfg["templatename"]] = (fname, xlsx_bytes)
                except Exception as e:
                    err = f"[{cfg['templatename']}] 查询失败: {e}"
                    logger.error(err)
                    result["errors"].append(err)

        if not exported:
            raise Exception("两个 PM 模板均未获取到数据")

        # Step 3: 内存解析合并（不落盘 exports 文件，直接入数据库）
        frames = []
        for cfg in PL_QUERY_CONFIGS:
            if cfg["templatename"] not in exported:
                continue
            fname, xlsx_bytes = exported[cfg["templatename"]]
            result["files"].append(f"{fname} (内存解析, {len(xlsx_bytes)} bytes)")
            frames.append(_normalize_export_df(xlsx_bytes, cfg))

        merged = pd.concat(frames, ignore_index=True)
        merged = merged.drop_duplicates()
        logger.info(f"[PL] 合并后数据: {len(merged)} 行")

        # Step 4: 写入 lte_pl.sqlite3
        rows_written = _write_merged_to_db(merged)
        result["rows"] = rows_written
        logger.info(f"[PL] lte_pl.sqlite3 写入: {rows_written} 行")

        # Step 5: 站点关联 + 汇总 + 报告
        site = _load_site_info()
        pivot, summary = _build_site_summary(merged, site)
        result["sites"] = len(summary)
        report_path = _generate_report(pivot, summary)
        result["report"] = report_path
        logger.info(f"[PL] 报告生成: {report_path} ({len(summary)} 站点)")

        # Step 6: 汇总入库供看板使用
        _save_summary_to_db(summary, report_path, rows_written)

        result["success"] = len(result["errors"]) == 0
    except Exception as e:
        logger.error(f"[PL] 任务失败: {e}", exc_info=True)
        result["errors"].append(str(e))

    elapsed = time.time() - start_time
    result["elapsed_seconds"] = round(elapsed, 2)
    logger.info(f"[PL] 丢包同步完成: rows={result['rows']}, sites={result['sites']}, "
                f"耗时 {elapsed:.2f}s, success={result['success']}")
    return result


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:packet_loss_service>: exception swallowed", exc_info=True)
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    t0 = time.time()
    res = run_packet_loss_sync()
    print(f"\n丢包同步结果: {'成功' if res['success'] else '失败'}")
    print(f"文件: {res['files']}")
    print(f"数据行: {res['rows']}, 站点: {res['sites']}, 报告: {res['report']}")
    if res["errors"]:
        print(f"错误: {res['errors']}")
    print(f"总耗时: {time.time() - t0:.2f}s")

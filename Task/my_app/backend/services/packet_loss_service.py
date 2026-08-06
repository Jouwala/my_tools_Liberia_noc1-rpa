# -*- coding: utf-8 -*-
"""
Packet Loss 服务：从 RAN UME 获取丢包率 PM 数据 → 合并 → 写入 lte_pl.sqlite3 → 生成报告

流程（对应 data/packet_lost/要求.txt）：
1. 复用 ran_ume_service 的登录/HTTP 通道，查询两个 PM 模板（近 8 天，1 小时粒度）：
   - Packet Loss Rate_SDR_IPPD   (grouplayer: me,sdrmgr.SrcIP,sdrmgr.DesIP)
   - Packet Loss Rate_ITRAN_IPPD (grouplayer: me,TransportNetwork,IPPD)
2. 导出文件命名规则：templatename_grouplayer映射_gr映射（仅内存标识，不落盘）
3. 两个导出只保留指定字段（SDR 的 Source/Destination IP ID 改名 srcIp/dstIp）后合并，
   丢包率按模板 Step 3 规则 ×100 转为百分比数值，全程内存处理直接写入数据库
4. 合并数据写入 data/packet_lost/lte_pl.sqlite3，并关联 eflow.sqlite3 站点信息
   （site_name / gateway(TRM Type) / network_type / region / province_county / latitude / longitude），
   按模板 Packet_Loss_Status_Output Automation.xlsx 格式生成带公式口径的报告（顶部含日期）；
   报告只展示最近 7 个完整自然日，当天未过完的数据不展示
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
import numpy as np

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
from openpyxl.formatting.rule import CellIsRule, FormulaRule, Rule
from openpyxl.styles.differential import DifferentialStyle
from openpyxl.utils import get_column_letter
from backend.database import get_raw_connection

logger = logging.getLogger("packet_loss_service")

# ========== 路径配置 ==========
PL_DATA_DIR = Path(r"d:\01_RPA\Task\my_app\data\packet_lost")
PL_DB_PATH = PL_DATA_DIR / "lte_pl.sqlite3"
PL_REPORT_PATH = PL_DATA_DIR / "Packet_Loss_Status_Report.xlsx"
PL_TEMPLATE_PATH = PL_DATA_DIR / "Packet_Loss_Status_Output Automation.xlsx"
EFLOW_DB_PATH = Path(r"d:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3")

# 查询窗口：8 天到现在（可用环境变量调整）。
# 取 8 天是为了在剔除当天（未过完的整天数据不展示）后仍能凑齐完整 7 个自然日。
PL_DAYS_BACK = int(os.environ.get("PL_DAYS_BACK", "8"))
# 报告/网页展示保留的完整自然日天数
PL_FULL_DAYS = int(os.environ.get("PL_FULL_DAYS", "7"))
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
    # 丢包率是比率（0~100%），防御性裁剪超界异常值
    df[PL_COL] = df[PL_COL].clip(lower=0.0, upper=100.0)
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
    # 兼容旧表：补充 STATUS 列（要求2: OK/NOK）
    try:
        conn.execute("ALTER TABLE site_pl_summary ADD COLUMN STATUS TEXT")
    except sqlite3.OperationalError:
        pass
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
    """丢包等级分类（与报告 FINAL_STATUS 一致）

    与模板 FINAL_STATUS 公式 LOOKUP(FZ,{0.1;0.5;1;5},...) 语义对齐：
    恰好等于边界值归入高一档（如 5.0 -> Critical[>5]）。
    """
    if v is None or pd.isna(v):
        return "No Packet loss[<0.1]"
    v = float(v)
    if v >= 5:
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
    """按站点按小时汇总（取最差链路 max），生成站点级宽表与汇总信息

    注意：丢包率是比率（0~100%），一个站点同一小时可能有多个 IPPD 链路
    （SDR 模板按 SrcIP/DesIP、ITRAN 模板按 IPPD 分组，且两模板可能重复采集），
    必须取 max（最差链路）而非 sum，否则多链路相加会出现 >100% 的非法值。
    """
    df = df.copy()
    df["hour"] = df["Begin Time"].dt.floor("h")
    name, code = _extract_me_parts(df["Managed Element"])
    df["_site_name"] = name.where(name != "", df["Managed Element"].astype(str))
    df["_site_code"] = code

    # 站点 × 小时 的丢包率 = 该站点该小时所有链路中的最大值（向量化 pivot）
    pivot = df.pivot_table(index="_site_name", columns="hour", values=PL_COL,
                           aggfunc="max", fill_value=0.0)
    pivot = pivot.reindex(columns=pd.date_range(pivot.columns.min(), pivot.columns.max(), freq="h"),
                          fill_value=0.0)

    # 数据完整性要求：只保留完整自然日 —— 当天还没过完，其小时数据不参与统计/展示
    today_start = pd.Timestamp(datetime.now().date())
    pivot = pivot.loc[:, pivot.columns < today_start]
    # 只保留最近 PL_FULL_DAYS 个完整自然日（每天 00~23 点）
    pivot = pivot.iloc[:, -PL_FULL_DAYS * 24:]

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

    # 0~23 标志块（模板公式 =IF(AND(最近3天同整点>0.5),1,0)，向量化）：
    # 每整点取最近 3 天同整点值，三天都 >0.5% 记 1，否则 0
    last3 = pivot.iloc[:, -3 * 24:]
    flags_arr = (last3.to_numpy().reshape(len(last3), -1, 24) > 0.5).all(axis=1).astype(int)
    flags = pd.DataFrame(flags_arr, index=pivot.index,
                         columns=[f"flag_{h}" for h in range(24)])
    flag_sum = flags_arr.sum(axis=1)

    # 要求2（模板公式 GA：=IF(SUM(GG:HD)=0,"OK","NOK")）：0~23 标志全为 0 -> OK，否则 NOK
    summary["STATUS"] = np.where(flag_sum == 0, "OK", "NOK")
    # 要求2（模板公式 GB：IF(GA="OK","No Packet loss[<0.1]",LOOKUP(FZ,...))）：
    # STATUS=OK 强制归一为 No Packet loss[<0.1]，否则按 Last 1 day Max PL 分类
    summary["FinalStatus"] = summary["LastDayMaxPL"].map(classify_status)\
        .where(summary["STATUS"] != "OK", "No Packet loss[<0.1]")
    summary = summary.sort_values("LastDayMaxPL", ascending=False)
    flags = flags.reindex(summary.index)
    return pivot, summary, flags


def _generate_report(pivot: pd.DataFrame, summary: pd.DataFrame, flags: pd.DataFrame) -> str:
    """按模板 Packet_Loss_Status_Output Automation.xlsx 格式生成报告（与网页端/看板口径一致）。

    口径（与模板公式完全对齐，全部在 _build_site_summary 统一计算后直接写入，
    保证 Excel 报告与网页看板同一数据源）：
      - STATUS       = 0~23 标志块之和为 0 -> "OK"，否则 "NOK"
                       （模板 =IF(SUM(GG:HD)=0,"OK","NOK")）
      - FINAL_STATUS = STATUS=OK 时强制 "No Packet loss[<0.1]"，否则按 (Last 1 day Max PL)
                       匹配 Critical/Major/Minor/Warning/No Packet loss
      - GG..HD 块(0~23) = 每整点最近三天「同整点」丢包均 >0.5% -> 1，否则 0
      - 小时列只含完整自然日（当天未过完不展示）
      - Affected Sites = Critical + Major（Summary 另给 All Affected=非OK）
    颜色严格按模板：数据区/标志块/STATUS 用与模板相同的【条件格式】着色（模板 theme 色
    已换算为等效 RGB），表头灰底黄区与模板一致；派生列写入真实计算值（非公式）。
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Packet Loss Report"

    # ===== 模板样式（theme 色已换算为等效 RGB，避免跨簿克隆 Theme 色丢失）=====
    GRAY_FILL = PatternFill("solid", fgColor="FFD9D9D9")       # 表头灰（模板 theme0 -15%）
    LASTH_FILL = PatternFill("solid", fgColor="FFFDEADA")      # 最后小时列表头浅橙（模板 theme9 +80%）
    YELLOW_FILL = PatternFill("solid", fgColor="FFFFFF00")     # FZ~GE 黄底
    NAVY_BOLD = Font(color="FF002060", bold=True, size=10)     # 深蓝加粗（灰/黄底表头）
    NAVY_FONT = Font(color="FF002060", size=10)                # 深蓝（meta/小时表头）
    DATA_FONT = Font(color="FF002060", size=10)                # 数据行深蓝字（模板 meta 列）
    HOUR_FONT = Font(size=10)                                  # 小时数据（模板默认黑字）
    CENTER = Alignment(horizontal="center")
    HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)

    hour_cols = list(pivot.columns)
    n_hours = len(hour_cols)
    first_hour_col = 13  # M

    meta_cols = ["Cluster", "County", "Locality", "Site Code", "Site_Name",
                 "Longitude", "Latitude", "Vendor", "Media",
                 "BB MW/Fiber Site1 code", "Equipment BB1", "Row Labels"]
    headers = meta_cols + [h.strftime("%Y-%m-%d %H:%M:%S") for h in hour_cols]
    last_pivot_col = first_hour_col + n_hours - 1
    fy_col = last_pivot_col + 1                                # FY 空列（模板布局）
    fz_col = last_pivot_col + 2                                # FZ (Last 1 day Max PL)
    status_col = fz_col + 1                                    # GA
    final_col = fz_col + 2                                     # GB
    gc_col = fz_col + 3                                        # GC MW-IPRAN
    gd_col = fz_col + 4                                        # GD Main Category
    ge_col = fz_col + 5                                        # GE Expansion Planned
    gf_col = fz_col + 6                                        # GF 空列（模板布局）
    block_start = fz_col + 7                                   # GG (24 列 0~23)

    # 表头（含模板 FY/GF 两个空列）
    all_headers = (headers +
                   [None, "(Last 1 day Max PL)", "STATUS", "FINAL_STATUS",
                    "MW - IPRAN Link Status", "Main Category", "Expansion Planned?",
                    None] +
                   [h for h in range(24)])
    for j, hv in enumerate(all_headers, start=1):
        c = ws.cell(row=1, column=j, value=hv)
        c.alignment = HEADER_ALIGN
        if j in (fy_col, gf_col):
            continue                                           # 空列不 styling
        if fz_col <= j <= ge_col:
            c.fill = YELLOW_FILL                               # 模板：FZ~GE 黄底深蓝加粗
            c.font = NAVY_BOLD
        elif first_hour_col <= j <= last_pivot_col:
            if j == last_pivot_col:
                c.fill = LASTH_FILL                            # 模板：最后一个小时列浅橙底
            c.font = NAVY_FONT                                 # 小时表头：无底深蓝字
        else:
            c.fill = GRAY_FILL                                 # 模板：A~L 与 0~23 块灰底深蓝字
            c.font = NAVY_BOLD if j <= 12 else NAVY_FONT

    # 日历日对齐已由 _build_site_summary 完成（flags 与 pivot 同源同序）
    first_data_row = 2
    for i, (site_name, row) in enumerate(summary.iterrows(), start=first_data_row):
        vals = pivot.loc[site_name].values.astype(float)
        ck = row.get("Site_Code") or ""
        disp = row.get("Display_Name", f"{site_name}({ck})" if ck else site_name)
        last24 = vals[-24:]
        last_max = float(max(last24)) if len(last24) else 0.0
        # STATUS / FINAL_STATUS / 0~23 标志全部取自 summary 层（与入库/网页同一口径）
        status = str(row.get("STATUS") or "OK")
        final = str(row.get("FinalStatus") or classify_status(last_max))
        site_flags = flags.loc[site_name].values
        # meta（与模板/独立脚本一致）
        meta = [row.get("region", ""), row.get("province_county", ""),
                row.get("locality", "") if pd.notna(row.get("locality")) else "",
                str(ck) if ck else "", disp,
                float(row["longitude"]) if pd.notna(row.get("longitude")) else None,
                float(row["latitude"]) if pd.notna(row.get("latitude")) else None,
                row.get("vendor", "") if pd.notna(row.get("vendor")) else "",
                row.get("gateway", ""), "", "", disp]
        for j, v in enumerate(meta, start=1):
            ws.cell(row=i, column=j, value=v).font = DATA_FONT
        for j, v in enumerate(vals):
            cell = ws.cell(row=i, column=first_hour_col + j, value=float(v))
            cell.number_format = "0.00"
            cell.font = HOUR_FONT
            cell.alignment = CENTER
        cc = ws.cell(row=i, column=fz_col, value=round(last_max, 4))
        cc.number_format = "0.00"; cc.font = DATA_FONT; cc.alignment = CENTER
        ws.cell(row=i, column=status_col, value=status).font = DATA_FONT
        ws.cell(row=i, column=final_col, value=final).font = DATA_FONT
        ws.cell(row=i, column=gc_col, value=None).font = DATA_FONT
        ws.cell(row=i, column=gd_col, value=None).font = DATA_FONT
        ws.cell(row=i, column=ge_col, value=None).font = DATA_FONT
        for h in range(24):
            fc = ws.cell(row=i, column=block_start + h, value=int(site_flags[h]))
            fc.font = HOUR_FONT
            fc.number_format = "0"
    last_data_row = first_data_row + len(summary) - 1
    ws.freeze_panes = ws.cell(row=first_data_row, column=first_hour_col)
    ws.column_dimensions["E"].width = 22

    # ===== 条件格式（严格按模板，theme 色换算为等效 RGB）=====
    def _cf_fill(rgb: str) -> PatternFill:
        return PatternFill(patternType="solid", start_color=rgb, end_color=rgb)

    def _contains_text(letter: str, text: str, rgb: str, first_row: int = 2) -> Rule:
        """与模板完全同型的 containsText 规则（operator 与模板 XML 一致为 between，
        公式引用区域左上角单元格，Excel 按相对引用自动作用于区域内各格）"""
        return Rule(type="containsText", operator="between", text=text,
                    dxf=DifferentialStyle(fill=_cf_fill(rgb)),
                    formula=[f'NOT(ISERROR(SEARCH("{text}",{letter}{first_row})))'])

    # 小时数据区（模板 M2:FX{n}）：>5 红 / 1~5 橙 / 0.5~1 黄 / 0.1~0.5 蓝 / <0.1 绿
    hour_rng = f"{get_column_letter(first_hour_col)}2:{get_column_letter(last_pivot_col)}{last_data_row}"
    ws.conditional_formatting.add(hour_rng, CellIsRule(operator="greaterThan", formula=["5"], fill=_cf_fill("FFFF0000")))
    ws.conditional_formatting.add(hour_rng, CellIsRule(operator="between", formula=["1", "5"], fill=_cf_fill("FFFAC090")))
    ws.conditional_formatting.add(hour_rng, CellIsRule(operator="between", formula=["0.5", "1"], fill=_cf_fill("FFFFFF00")))
    ws.conditional_formatting.add(hour_rng, CellIsRule(operator="between", formula=["0.1", "0.5"], fill=_cf_fill("FF00B0F0")))
    ws.conditional_formatting.add(hour_rng, CellIsRule(operator="lessThan", formula=["0.1"], fill=_cf_fill("FF92D050")))
    # 0~23 标志块（模板 GG2:HD{n}）：含 1 深橙 / 含 0 绿（NOK/1 规则优先级高于 OK/0）
    b1 = get_column_letter(block_start)
    block_rng = f"{b1}2:{get_column_letter(block_start + 23)}{last_data_row}"
    ws.conditional_formatting.add(block_rng, _contains_text(b1, "1", "FFE36C0A"))
    ws.conditional_formatting.add(block_rng, _contains_text(b1, "0", "FF92D050"))
    # (Last 1 day Max PL)+STATUS 列（模板 FZ2:GA{n}）：>=0.1 金色
    fz_rng = f"{get_column_letter(fz_col)}2:{get_column_letter(status_col)}{last_data_row}"
    ws.conditional_formatting.add(fz_rng, CellIsRule(operator="greaterThanOrEqual", formula=["0.1"], fill=_cf_fill("FFFFC000")))
    # STATUS 文本 NOK 深橙 / OK 绿：与模板同构 —— 单条范围 FY1 GA2:GF{n} GF1，
    # 公式引用首格 FY1，Excel 相对引用使其实际作用于 GA 列（NOK 规则先加，优先级更高）
    g1 = get_column_letter(status_col)
    fy_l = get_column_letter(fy_col)
    gf_l = get_column_letter(gf_col)
    mirror_rng = f"{fy_l}1 {g1}2:{gf_l}{last_data_row} {gf_l}1"
    ws.conditional_formatting.add(mirror_rng, _contains_text(fy_l, "NOK", "FFE36C0A", first_row=1))
    ws.conditional_formatting.add(mirror_rng, _contains_text(fy_l, "OK", "FF92D050", first_row=1))
    # L1 重复值高亮（模板自带的规则，同参复现）
    ws.conditional_formatting.add("L1", Rule(
        type="duplicateValues",
        dxf=DifferentialStyle(fill=_cf_fill("FFFFC7CE"))))

    # ===== Sheet: Summary（含 Affected Sites，严重度配色）=====
    ws2 = wb.create_sheet("Summary")
    sum_headers = ["PL Status", "Count of Sites", "Link Congested", "Link Issue",
                   "Power issue onsite", "Up grade to IPRAN", "Percentage of Sites", "Other"]
    ws2.append(sum_headers)
    for j, c in enumerate(ws2[1], start=1):
        # 模板 Summary 表头：1/2/7 列灰底，3~6 列浅橙底，深蓝字加粗
        c.fill = GRAY_FILL if j in (1, 2, 7) else LASTH_FILL
        c.font = NAVY_BOLD
        c.alignment = Alignment(horizontal="center")
    statuses = [("Critical [>5]", "Critical[>5]", "FFFF0000"),
                ("Major [1-5]", "Major[1-5]", "FFFFC000"),
                ("Minor [0.5-1]", "Minor[0.5-1]", "FFFFFF00"),
                ("Warning [0.1-0.5]", "Warning[0.1-0.5]", "FF00B0F0"),
                ("No Packet loss[<0.1]", "No Packet loss[<0.1]", "FF92D050")]
    counts = {val: 0 for _, val, _ in statuses}
    # 直接用 summary 层的 FinalStatus 计数（已含 STATUS=OK 强制归一），与主表/网页一致
    for st in summary["FinalStatus"]:
        counts[st] = counts.get(st, 0) + 1
    total = sum(counts.values())
    for r, (label, val, color) in enumerate(statuses, start=2):
        a1 = ws2.cell(row=r, column=1, value=label)
        a1.fill = PatternFill("solid", fgColor=color)
        a1.font = Font(color="FF000000", bold=True)
        ws2.cell(row=r, column=2, value=counts.get(val, 0)).font = DATA_FONT
        for cc2 in (3, 4, 5, 6):
            ws2.cell(row=r, column=cc2, value=0).font = DATA_FONT
        pc = ws2.cell(row=r, column=7, value=(counts.get(val, 0) / total) if total else 0)
        pc.number_format = "0.00%"; pc.font = DATA_FONT
        ws2.cell(row=r, column=8, value=counts.get(val, 0)).font = DATA_FONT
    crit_maj = counts["Critical[>5]"] + counts["Major[1-5]"]
    ws2.cell(row=7, column=1, value="Affected Sites (Critical+Major)").font = Font(bold=True, color="FFC00000")
    ws2.cell(row=7, column=2, value=crit_maj).font = DATA_FONT
    ws2.cell(row=8, column=1, value="All Affected (non-OK)").font = DATA_FONT
    ws2.cell(row=8, column=2, value=total - counts["No Packet loss[<0.1]"]).font = DATA_FONT
    for col, width in zip("ABCDEFGH", (30, 16, 14, 12, 18, 18, 20, 10)):
        ws2.column_dimensions[col].width = width

    # ===== Sheet: Sheet1（复制模板参考表）=====
    try:
        if PL_TEMPLATE_PATH.exists():
            wb_t = openpyxl.load_workbook(str(PL_TEMPLATE_PATH), data_only=True)
            if "Sheet1" in wb_t.sheetnames:
                ws3 = wb.create_sheet("Sheet1")
                for row in wb_t["Sheet1"].iter_rows(values_only=True):
                    ws3.append(list(row))
    except Exception as e:  # noqa
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _generate_report: Sheet1 copy failed: %s", e, exc_info=True)

    # ===== 保存（时间戳文件名）=====
    ts = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    out_name = f"Packet_Loss_Status_Output Automation {ts}.xlsx"
    out_path = PL_DATA_DIR / out_name
    try:
        atomic_save_workbook(wb, str(out_path))
        out_path_str = str(out_path)
    except AtomicReplaceFallback as fb:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _generate_report: exception swallowed", exc_info=True)
        out_path_str = fb.fallback_path
    finally:
        wb.close()
    return out_path_str


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
                    r["FinalStatus"], r.get("STATUS", ""), now_iso,
                ))
            conn.executemany(
                "INSERT OR REPLACE INTO site_pl_summary "
                "(Site_Name,Site_Code,gateway,network_type,region,province_county,latitude,longitude,"
                "LastDayMaxPL,TotalPL,AffectedHours,FinalStatus,STATUS,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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

        # Step 5: 站点关联 + 汇总 + 报告（只含完整自然日，当天未过完不展示）
        site = _load_site_info()
        pivot, summary, flags = _build_site_summary(merged, site)
        result["sites"] = len(summary)
        report_path = _generate_report(pivot, summary, flags)
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

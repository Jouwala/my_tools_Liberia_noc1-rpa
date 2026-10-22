"""
eFlow API 数据同步服务
直接从 eFlow API 获取数据，字段映射后写入 app.db
不再依赖外部 eflow.sqlite3 中间文件

两种上游语义，**不要混用**（2026-10-09 明确）：
  - `eflow_tt` / `eflow_wo` / `eflow_cr` / `eflow_pm` / `person` 走**增量窗口**
    （`EFLOW_DELTA_DAYS`，只抓最近 N 天修改过的单），设计上要累积历史 → 只 upsert、
    **不删除**（见 `eflow_api_client.py` 的 delta 注释）。
  - `eflow_site` 走**单次全量导出**（`eflow_data_mapper._fetch_site_pipeline` 无时间窗），
    表语义 = 上游当前快照 → `_sync_site` 会做全量重建删除（上游已无的站点）。
    删除只放在 `_sync_site` 内，**不要**挪进共用的 `_upsert_df`（那会毁掉 delta 表历史）。
"""
import os
import re
import time
import sqlite3
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime
from backend.database import get_raw_connection
from backend.dialect_helpers import (
    list_table_names, table_columns, upsert, safe_pragma, write_df,
)
from backend.services.reconcile_helper import delete_not_in_keys

logger = logging.getLogger("eflow_sync")

#: 同步**必需**的 API 数据键：缺失即视为任务失败（2026-10-09）。
#: 只列 TT/WO —— 它们是工单看板/报表的核心，且历史上正是它们静默失败被掩盖。
#: CR/PM/Site/Person 允许缺失（上游时段性无数据不算故障），故不列入。
REQUIRED_API_KEYS = {"eFlow TT", "eFlow WO"}

#: 「必需表返回 0 行」同样视为**故障**，而非「上游这一时段没数据」。
#: 为什么需要（2026-10-15 实测事故）：eFlow 的 `base/list` 接口在**账号工单
#: 可见范围异常**时会返回 `200 {"result":[],"total":0}` —— 一个**合法 JSON 的
#: 空结果**，而不是报错。于是 `_sync_tt` 只打一行 `WARNING TT 数据为空`、
#: 返回 0 行，`result["errors"]` 保持为空，任务照样 `success=True`。
#: 后果：TT/WO 从 2026-10-14 08:17 起静默停更 26 小时，看板/机器人一直说
#: 「本地库最新是 TT202610140048」，直到人工发现。
#: TT/WO 是**在途工单**，任何时刻都必然有大量未关闭单（实测常态数千条），
#: 因此「0 行」在正常运行时不可能出现 —— 它只可能意味着上游异常或账号失权。
#: 只对在途类表启用这个判据；CR/PM/Site/Person 不在此列（它们可能真的暂时为空）。
REQUIRED_NONEMPTY_KEYS = {"eFlow TT", "eFlow WO"}

# 路径配置
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BACKEND_DIR / "db" / "app.db"

# ========== TT 字段映射 (eflow.sqlite3 列名 → app.db 列名) ==========
TT_COLUMN_MAP = {
    "Title": "title",
    "WO No.": "wo_no",
    "Status": "status",
    "Suspended": "suspended",
    "Source": "tt_source",
    "Ticket Type": "ticket_type",
    "Project Name": "project_name",
    "Template Name": "template_name",
    "Creator": "creator",
    "Creator Contact Info": "creator_contact_info",
    "Ticket Severity": "ticket_severity",
    "Alarm Category": "alarm_category",
    "Alarm Sub Category": "alarm_subcategory",
    "Alarm Severity": "alarm_severity",
    "Alarm Type": "alarm_type",
    "Alarm Code": "alarm_code",
    "Sub Alarm Name": "sub_alarm_name",
    "Sub Alarm NE Name": "sub_alarm_ne_name",
    "Sub Alarm NE IP": "sub_alarm_ne_ip",
    "Appending Alarm Name": "appending_alarm_name",
    "Appending Alarm NE Name": "appending_alarm_ne_name",
    "Appending Alarm NE IP": "appending_alarm_ne_ip",
    "Network Type": "domain",               # 核心映射：netWorkType → domain
    "NE Name": "ne_name",
    "NE ID": "ne_id",
    "NE IP": "ne_ip",
    "Whether Impacted Service": "whether_impacted_service",
    "Impacted Service": "impacted_service",
    "Site Outage": "site_outage",
    "Alarm Reason Type": "alarm_reason_type",
    "SLA Total Duration": "sla_time",
    "SLA Status": "sla_status",
    "SLA Remaining Duration": "sla_remain_time",
    "SLA Expected Finish Time": "sla_deadline",
    "Group SLA Time": "group_sla_time",
    "Group SLA Status": "group_sla_status",
    "Group SLA Remains Time": "group_sla_remains_time",
    "Region Level1": "region_level1",
    "Region Level2": "region_level2",
    "Asset Name": "site_name",
    "Site ID": "site_id",
    "Asset Type": "site_type",
    "Site Class": "site_class",
    "Current Handler": "current_handler",
    "Vender": "vendor",
    "Vendor": "vendor",
    "Created Time": "created_time",
    "Last Modified Time": "last_modified_time",
    "Occurrence Time": "alarm_occur_time",
    "Alarm Clearing Time": "alarm_clear_time",
    "Fault Duration Time": "fault_duration_time",
    "Proc ID": "procid",
    "Operation Step": "operation_step",
    "Description": "description",
    "Specific Problem": "specific_problem",
    "Additional Information": "additional_information",
    "Server Time": "server_time",
    "NE Type": "ne_type",
    "Alarm ID": "alarm_id",
    "Alarm Description": "alarm_description",
    "Down Site Count": "down_site_count",
    "Down Site List": "down_site_list",
    "2G Down Site Count": "col_2g_down_site_count",
    "2G Down Site List": "col_2g_down_site_list",
    "3G Down Site Count": "col_3g_down_site_count",
    "3G Down Site List": "col_3g_down_site_list",
    "4G Down Site Count": "col_4g_down_site_count",
    "4G Down Site List": "col_4g_down_site_list",
    "5G Down Site Count": "col_5g_down_site_count",
    "VIP Down Site Count": "vip_down_site_count",
    "Root Cause": "root_cause",
    "Sub Root Cause": "sub_root_cause",
    "Root Cause Description": "root_cause_description",
    "Actual Completion Time": "actual_completion_time",
    "Troubleshooting Personnel": "troubleshooting_personnel",
    "Site Information": "site_information",
    "VIP Site": "vip_site",
    "Hub Site": "hub_site",
    "Region ID": "region_id",
    "Asset ID": "asset_id",
    "Organization ID": "organization_id",
    "Suspend Detail": "suspend_detail",
    "Last Suspend Status": "last_suspend_status",
    "Last Suspend Operator": "last_suspend_operator",
    "Last Suspend Time": "last_suspend_time",
    "Last Resume Operator": "last_resume_operator",
    "Last Resume Time": "last_resume_time",
    "Last Processer": "last_processer",
    "Last Processer Group": "last_processer_group",
    "Last Process Time": "last_process_time",
    "Fault Resolved": "fault_resolved",
    "Ticket No.": "ticket_no",
    "Create Detail": "create_detail",
    "FO Accept Detail": "fo_accept_detail",
    "FO Process Detail": "fo_process_detail",
    "BO Accept Detail": "bo_accept_detail",
    "BO Process Detail": "bo_process_detail",
    "Third Accept Detail": "third_accept_detail",
    "Third Process Detail": "third_process_detail",
    "Confirm Detail": "confirm_detail",
    "Closed Detail": "closed_detail",
    "WO Process Attachment": "wo_process_attachment",
}

# ========== WO 字段映射 ==========
WO_COLUMN_MAP = {
    "WO No.": "wo_no",
    "TT NO.": "tt_no",
    "Work Order Title": "title",
    "Status": "status",
    "Suspended": "suspended",
    "Creator": "creator",
    "Created Time": "created_time",
    "Last Modified Time": "last_modified_time",
    "Operation Step": "operation_step",
    "Current Handler": "current_handler",
    "Ticket Severity": "ticket_severity",
    "MOC": "ne_type",
    "Vender": "vendor",
    "Vendor": "vendor",
    "Occurrence Time": "alarm_occur_time",
    "Alarm Clearing Time": "alarm_clear_time",
    "Expected Finish Time": "expected_finish_time",
    "Source": "source",
    "Project Name": "project_name",
    "Template Name": "template",
    "Assignment Suggestions": "assignment_suggestions",
    "Creator Contact Info": "creator_contact_info",
    "Description": "description",
    "Alarm Type": "alarm_type",
    "Alarm Category": "alarm_category",
    "Alarm Sub Category": "alarm_subcategory",
    "Alarm Severity": "alarm_severity",
    "Reason Type": "alarm_reason_type",
    "Alarm ID": "alarm_id",
    "Alarm Code": "alarm_code",
    "Alarm Description": "alarm_description",
    "Sub Alarm Name": "sub_alarm_name",
    "Sub Alarm NE Name": "sub_alarm_ne_name",
    "Sub Alarm NE IP": "sub_alarm_ne_ip",
    "Appending Alarm Name": "appending_alarm_name",
    "Appending Alarm NE Name": "appending_alarm_ne_name",
    "Appending Alarm NE IP": "appending_alarm_ne_ip",
    "Domain": "domain",                    # WO 的 domain 字段
    "Network Type": "domain",              # 备选
    "NE Name": "ne_name",
    "NE ID": "ne_id",
    "NE IP": "ne_ip",
    "Whether Impacted Service": "whether_impacted_service",
    "Impacted Service": "impacted_service",
    "Whether Site Interruption (Site Outage or Not)": "whether_site_interruption_site_outage_or_not",
    "Site Outage": "site_outage",
    "Impact (Down Site Count/Number of Down Site)": "impact_down_site_count_number_of_down_site",
    "Down Site Count": "down_site_count",
    "Down Site List": "down_site_list",
    "2G Down Site Count": "col_2g_down_site_count",
    "2G Down Site List": "col_2g_down_site_list",
    "3G Down Site Count": "col_3g_down_site_count",
    "3G Down Site List": "col_3g_down_site_list",
    "4G Down Site Count": "col_4g_down_site_count",
    "4G Down Site List": "col_4g_down_site_list",
    "5G Down Site Count": "col_5g_down_site_count",
    "VIP Down Site Count": "vip_down_site_count",
    "Fault Duration Time": "fault_duration_time",
    "SLA Total Duration": "sla_time",
    "SLA Status": "sla_status",
    "SLA Remaining Duration": "sla_remain_time",
    "SLA Expected Finish Time": "sla_deadline",
    "Group SLA Time": "group_sla_time",
    "Group SLA Status": "group_sla_status",
    "Group SLA Remains Time": "group_sla_remains_time",
    "Region Level1": "region_level1",
    "Region Level2": "region_level2",
    "Asset Name": "site_name",
    "Site ID": "site_id",
    "Asset Type": "site_type",
    "Site Class": "site_class",
    "Site Name": "site_name",
    "Site Type": "site_type",
    "RCA Main Category": "rc_main_category",
    "RCA Sub Category": "rc_sub_category",
    "Actual Completion Time": "actual_completion_time",
    "Fault Resolved By": "fault_resolved_by",
    "Fault Resolving Time": "fault_resolving_time",
    "Processing Description": "processing_description",
    "VIP Site": "vip_site",
    "Hub Site": "hub_site",
}

# ========== Site 字段映射 (eflow site → master_site_db) ==========
SITE_COLUMN_MAP = {
    "Site ID": "site_id",
    "Site Name": "site_name",
    "Region": "region",
    "Province": "province_county",
    "District": "district",
    "Commune": "commune",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "Site Maintainer": "updated_fme_name_new",
    "Site Type": "site_type",
    "Vendor": "power_vendor",
    "Area": "area",
    "SiteAddress": "site_address",
    "Network Type": "network_type",
    "TRM Type": "trm_type",
    "Victims": "victims",
    "GS Type": "gs_type",
}


# ========== 通用工具函数 ==========
def _clean_column_name(col: str) -> str:
    """通用列名清洗：转 snake_case"""
    if not isinstance(col, str):
        col = str(col)
    col = col.strip()
    col = re.sub(r'[^\w\s]', '_', col)
    col = re.sub(r'\s+', '_', col)
    col = re.sub(r'_+', '_', col)
    col = col.strip('_').lower()
    if col and col[0].isdigit():
        col = f'col_{col}'
    return col or 'unnamed'


def _apply_column_map(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    """应用列名映射，未映射的列自动 snake_case"""
    new_cols = {}
    for col in df.columns:
        if col in col_map:
            new_cols[col] = col_map[col]
        else:
            new_cols[col] = _clean_column_name(col)
    df = df.rename(columns=new_cols)
    # 处理重复列名
    seen = {}
    final_cols = []
    for c in df.columns:
        if c in seen:
            seen[c] += 1
            final_cols.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            final_cols.append(c)
    df.columns = final_cols
    return df


def _convert_ms_timestamps(df: pd.DataFrame, ms_columns: list) -> pd.DataFrame:
    """将毫秒时间戳列转换为可读日期字符串"""
    for col in ms_columns:
        if col not in df.columns:
            continue
        sample = df[col].dropna()
        if sample.empty:
            continue
        try:
            max_val = sample.astype(float).max()
            if max_val > 1e12:
                def ms_to_str(val):
                    try:
                        ts = float(val) / 1000
                        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                    except (ValueError, TypeError, OSError):
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] ms_to_str: exception swallowed", exc_info=True)
                        return str(val) if pd.notna(val) else None
                df[col] = df[col].apply(ms_to_str)
        except (ValueError, TypeError):
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _convert_ms_timestamps: exception swallowed", exc_info=True)
            pass
    return df


# ========== 各表同步函数 ==========
def _upsert_df(dst_conn: sqlite3.Connection, table_name: str, df: pd.DataFrame,
               key_cols: list) -> int:
    """按主键 INSERT OR REPLACE 增量写入，保留历史数据。

    与远程 db_writer_api 的 upsert 语义一致：先保证唯一索引存在（清理历史重复行），
    再按主键覆盖写入。
    """
    if df is None or df.empty:
        return 0

    cols = list(df.columns)
    keys = [c for c in key_cols if c in cols] or [cols[0]]

    def _q(c):
        return f'"{c.replace(chr(34), chr(34) + chr(34))}"'

    col_defs = ", ".join(f"{_q(c)} TEXT" for c in cols)
    dst_conn.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({col_defs})')

    exist = set(table_columns(dst_conn, table_name))
    for c in cols:
        if c not in exist:
            dst_conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN {_q(c)} TEXT')

    key_q = ", ".join(_q(k) for k in keys)
    if isinstance(dst_conn, sqlite3.Connection):
        dst_conn.execute(
            f'DELETE FROM "{table_name}" WHERE rowid NOT IN '
            f'(SELECT MIN(rowid) FROM "{table_name}" GROUP BY {key_q})'
        )
    else:
        # PG：以 ctid 代替 sqlite 的 rowid 做物理行去重（保留每组最早一行）
        dst_conn.execute(
            f'DELETE FROM "{table_name}" WHERE ctid NOT IN '
            f'(SELECT MIN(ctid) FROM "{table_name}" GROUP BY {key_q})'
        )
    # 先删除旧的同名唯一索引（主键列可能变更，IF NOT EXISTS 会跳过导致旧索引残留）
    dst_conn.execute(f'DROP INDEX IF EXISTS "u_{table_name}"')
    dst_conn.execute(f'CREATE UNIQUE INDEX "u_{table_name}" ON "{table_name}" ({key_q})')

    records = df.astype(object).where(pd.notnull(df), None).values.tolist()
    records = [{c: (None if v is None else str(v)) for c, v in zip(cols, row)}
               for row in records]
    # 双模 upsert：sqlite=INSERT OR REPLACE / pg=INSERT ... ON CONFLICT DO UPDATE
    for i in range(0, len(records), 5000):
        upsert(dst_conn, table_name, records[i:i + 5000], conflict_cols=list(keys))
    dst_conn.commit()
    return len(records)


def _sync_tt(df: pd.DataFrame, dst_conn: sqlite3.Connection) -> int:
    """同步 TT 数据"""
    t0 = time.time()
    if df.empty:
        logger.warning("TT 数据为空")
        return 0

    df = _apply_column_map(df, TT_COLUMN_MAP)
    df = _convert_ms_timestamps(df, ['created_time', 'last_modified_time', 'alarm_occur_time', 'alarm_clear_time'])

    # wo_no 兜底（2026-10-21 起实测）：eFlow 列表接口不再返回 "WO No."，工单号改放在
    # "Relation No."（TT_COLUMN_MAP 未映射它，由 _apply_column_map 自动落成 relation_no）。
    # 不兜底则新单 wo_no 为空：tt_reports 的 WO No. 列全空、8 小时图片与 Open Tickets
    # 被 notna 过滤成空，且 tt_wo_dashboard._owner_where 把新单全判成 3rd 第三方单。
    if 'relation_no' in df.columns:
        if 'wo_no' in df.columns:
            df['wo_no'] = df['wo_no'].where(df['wo_no'].notna(), df['relation_no'])
        else:
            df['wo_no'] = df['relation_no']

    # ticket_no 回退
    if 'ticket_no' not in df.columns and 'display_name' in df.columns:
        df['ticket_no'] = df['display_name']
    elif 'ticket_no' not in df.columns and 'wo_no' in df.columns:
        df['ticket_no'] = df['wo_no']

    df['_sync_time'] = datetime.now().isoformat()
    df['_sync_source'] = 'eflow_api'

    # TT No. 是 TT 表的唯一键（同一 WO No. 可能对应多条 TT/告警行）
    _upsert_df(dst_conn, 'eflow_tt', df, ['tt_no'])

    for idx_col in ['site_id', 'status', 'created_time', 'alarm_occur_time', 'domain', 'ticket_no']:
        if idx_col in df.columns:
            dst_conn.execute(f'CREATE INDEX IF NOT EXISTS idx_eflow_tt_{idx_col} ON eflow_tt({idx_col})')
    dst_conn.commit()

    elapsed = time.time() - t0
    logger.info(f"eflow_tt 同步完成(upsert): {len(df)} 行, {elapsed:.2f}s")
    return len(df)


def _sync_wo(df: pd.DataFrame, dst_conn: sqlite3.Connection) -> int:
    """同步 WO 数据"""
    t0 = time.time()
    if df.empty:
        logger.warning("WO 数据为空")
        return 0

    df = _apply_column_map(df, WO_COLUMN_MAP)
    df = _convert_ms_timestamps(df, ['created_time', 'last_modified_time', 'alarm_occur_time', 'alarm_clear_time'])

    df['_sync_time'] = datetime.now().isoformat()
    df['_sync_source'] = 'eflow_api'

    _upsert_df(dst_conn, 'eflow_wo', df, ['wo_no'])

    for idx_col in ['site_id', 'status', 'created_time', 'alarm_occur_time', 'domain', 'wo_no']:
        if idx_col in df.columns:
            dst_conn.execute(f'CREATE INDEX IF NOT EXISTS idx_eflow_wo_{idx_col} ON eflow_wo({idx_col})')
    dst_conn.commit()

    elapsed = time.time() - t0
    logger.info(f"eflow_wo 同步完成(upsert): {len(df)} 行, {elapsed:.2f}s")
    return len(df)


def _sync_generic(df: pd.DataFrame, dst_conn: sqlite3.Connection, table_name: str) -> int:
    """通用同步：清洗列名后直接写入"""
    t0 = time.time()
    if df.empty:
        logger.warning(f"{table_name} 数据为空")
        return 0

    df.columns = [_clean_column_name(c) for c in df.columns]
    df['_sync_time'] = datetime.now().isoformat()
    key = ([c for c in ('change_request_id', 'pmt_no', 'wo_no') if c in df.columns]
           or [df.columns[0]])
    _upsert_df(dst_conn, table_name, df, key)

    elapsed = time.time() - t0
    logger.info(f"{table_name} 同步完成(upsert): {len(df)} 行, {elapsed:.2f}s")
    return len(df)


def _sync_site(df: pd.DataFrame, dst_conn: sqlite3.Connection) -> int:
    """同步 eFlow Site 数据 → eflow_site（独立表，不替换 master_site_db）。

    Site 管线是**单次全量导出**（`eflow_data_mapper._fetch_site_pipeline` 无时间窗，
    与 tt/wo/cr/pm 的 delta 窗口不同），故本表语义 = 上游当前快照：upsert 后把
    不在本轮 site_id 集合里的行删掉（2026-10-09 新增），否则已退役/改名的站点会
    永久残留。

    ⚠️ 删除只在本函数内做，**不要**挪进共用的 `_upsert_df` —— 那个函数同时服务
    delta 表（tt/wo/cr/pm），在那里删会毁掉它们按设计累积的历史。
    安全阀：`df` 为空时上面已 return（且上游导出失败时整条 "Site" 会缺失，上层
    直接跳过，到不了这里），故能走到删除就说明本轮拿到了完整站点集。
    """
    t0 = time.time()
    if df.empty:
        logger.warning("Site 数据为空")
        return 0

    df = _apply_column_map(df, SITE_COLUMN_MAP)
    df['_sync_time'] = datetime.now().isoformat()
    df['_sync_source'] = 'eflow_api'

    _upsert_df(dst_conn, 'eflow_site', df, ['site_id'])

    # 全量重建：删除不在本轮导出里的站点（表 = 上游快照）
    if 'site_id' in df.columns:
        cursor = dst_conn.cursor()
        deleted = delete_not_in_keys(
            cursor, 'eflow_site', 'site_id',
            [v for v in df['site_id'].tolist() if v is not None],
            is_pg=not isinstance(dst_conn, sqlite3.Connection),
        )
        if deleted:
            logger.info(f"eflow_site: 全量重建删除 {deleted} 行（上游已无的站点）")

    for idx_col in ['site_id', 'region', 'site_type']:
        if idx_col in df.columns:
            dst_conn.execute(f'CREATE INDEX IF NOT EXISTS idx_eflow_site_{idx_col} ON eflow_site({idx_col})')
    dst_conn.commit()

    elapsed = time.time() - t0
    logger.info(f"eflow_site 同步完成(upsert+重建): {len(df)} 行, {elapsed:.2f}s")
    return len(df)


def _sync_realtime_alarm(df: pd.DataFrame, dst_conn: sqlite3.Connection) -> int:
    """同步实时告警数据"""
    t0 = time.time()
    if df.empty:
        logger.warning("realtime_alarm 数据为空")
        return 0

    df.columns = [_clean_column_name(c) for c in df.columns]
    df['_sync_time'] = datetime.now().isoformat()
    # TODO-PHASE3-SCHEMA: realtime_alarm 属 eflow schema；write_df 默认走全局 app 引擎，
    # pg 模式下需改为 eflow 引擎（engine_override）才能写入正确 schema
    write_df(df, 'realtime_alarm', if_exists='replace')

    for idx_col in ['site_id', 'site_name']:
        if idx_col in df.columns:
            dst_conn.execute(f'CREATE INDEX IF NOT EXISTS idx_realtime_alarm_{idx_col} ON realtime_alarm({idx_col})')
    dst_conn.commit()

    elapsed = time.time() - t0
    logger.info(f"realtime_alarm 同步完成: {len(df)} 行, {elapsed:.2f}s")
    return len(df)


def _sync_history_alarm(df: pd.DataFrame, dst_conn: sqlite3.Connection) -> int:
    """同步历史告警数据"""
    t0 = time.time()
    if df.empty:
        logger.warning("history_alarm 数据为空")
        return 0

    df.columns = [_clean_column_name(c) for c in df.columns]
    df['_sync_time'] = datetime.now().isoformat()
    # TODO-PHASE3-SCHEMA: history_alarm 属 eflow schema；write_df 默认走全局 app 引擎，
    # pg 模式下需改为 eflow 引擎（engine_override）才能写入正确 schema
    write_df(df, 'history_alarm', if_exists='replace')

    for idx_col in ['site_id', 'tt_id', 'region', 'alarmraisedtime']:
        if idx_col in df.columns:
            dst_conn.execute(f'CREATE INDEX IF NOT EXISTS idx_history_alarm_{idx_col} ON history_alarm({idx_col})')
    dst_conn.commit()

    elapsed = time.time() - t0
    logger.info(f"history_alarm 同步完成: {len(df)} 行, {elapsed:.2f}s")
    return len(df)


# ========== 主同步函数 ==========
def sync_from_eflow_api(mode: str = "delta") -> dict:
    """
    主同步函数：从 eFlow API 直接获取数据，映射字段后写入 app.db
    
    Returns:
        dict: 同步结果摘要
    """
    start_time = time.time()

    result = {
        "success": False,
        "target_db": str(DB_PATH),
        "tables_synced": {},
        "errors": [],
        "missing_required": [],
        "empty_required": [],
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": 0,
        "excel_path": None,
        "ftp_upload": False,
        "mode": mode,
    }

    logger.info("开始 eFlow API 数据同步（直连模式）")

    try:
        # 从 API 获取所有数据
        try:
            from backend.services.eflow_api_client import fetch_all_data
        except ImportError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] sync_from_eflow_api: exception swallowed", exc_info=True)
            from services.eflow_api_client import fetch_all_data
        try:
            from backend.services.eflow_api_client import EFLOW_FULL_DAYS
        except ImportError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] sync_from_eflow_api: exception swallowed", exc_info=True)
            from services.eflow_api_client import EFLOW_FULL_DAYS
        # delta: 最近 EFLOW_DELTA_DAYS 天; full: 0=全量(2026-01-01) 或 N 天
        days_back = EFLOW_FULL_DAYS if mode == "full" else None
        all_data = fetch_all_data(days_back=days_back)

        if not all_data:
            msg = "API 未返回任何数据"
            logger.error(msg)
            result["errors"].append(msg)
            return result

        # 连接目标数据库
        with get_raw_connection(str(DB_PATH)) as dst_conn:
            safe_pragma(dst_conn, "PRAGMA journal_mode=WAL")
            safe_pragma(dst_conn, "PRAGMA synchronous=NORMAL")

            # 同步任务映射: (API key, 目标表名, 同步函数)
            # 告警由独立任务 eflow_active_alarm / eflow_history_alarm 负责，不在此处同步
            sync_tasks = [
                ("eFlow TT", "eflow_tt", _sync_tt),
                ("eFlow WO", "eflow_wo", _sync_wo),
                ("eFlow CR", "eflow_cr", lambda df, c: _sync_generic(df, c, "eflow_cr")),
                ("eFlow PM", "eflow_pm", lambda df, c: _sync_generic(df, c, "eflow_pm")),
                ("Site", "eflow_site", _sync_site),
                ("Person", "person", lambda df, c: _sync_generic(df, c, "person")),
            ]

            for api_key, table_name, sync_func in sync_tasks:
                if api_key not in all_data:
                    # 必需表缺失 = 真失败，不能只 log 一行 continue（2026-10-09 修）。
                    # 旧行为：fetch_all_data 把管线异常吞进日志、返回的 dict 里就没有该键，
                    # 这里静默跳过 → result["errors"] 一直为空 → success=True。
                    # 实测 eflow_sync_full 的 TT/WO 连续多日 500 失败却天天报成功。
                    if api_key in REQUIRED_API_KEYS:
                        msg = (f"API 未返回必需数据: {table_name}（{api_key}）"
                               f"—— 该管线失败或上游异常")
                        logger.error(msg)
                        result["errors"].append(msg)
                        result["missing_required"].append(table_name)
                    else:
                        logger.info(f"跳过 {table_name}: API 未返回数据")
                    continue
                try:
                    df = pd.DataFrame(all_data[api_key])
                    # 处理 list/dict 类型列
                    object_cols = df.select_dtypes(include=["object", "str"]).columns
                    import json
                    for col in object_cols:
                        if df[col].apply(lambda x: isinstance(x, (list, dict))).any():
                            df[col] = df[col].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x)

                    row_count = sync_func(df, dst_conn)
                    result["tables_synced"][table_name] = row_count

                    # 必需表返回 0 行 = 故障（见 REQUIRED_NONEMPTY_KEYS 注释）。
                    # 必须在这里补记 error，否则 success 会被误判为 True —— 这正是
                    # 2026-10-14 静默停更事故的根因。**不要**改成只 warning。
                    if api_key in REQUIRED_NONEMPTY_KEYS and row_count == 0:
                        msg = (f"{table_name}（{api_key}）返回 0 行 —— 上游异常或账号"
                               f"工单可见范围失权，本次未抓到任何在途单（正常运行时不可能）")
                        logger.error(msg)
                        result["errors"].append(msg)
                        result["empty_required"].append(table_name)
                except Exception as e:
                    err_msg = f"{table_name} 同步失败: {e}"
                    logger.error(err_msg)
                    result["errors"].append(err_msg)

            # 清理旧表
            _cleanup_old_tables(dst_conn)

            # 更新 _metadata 表
            _update_metadata(dst_conn)

            dst_conn.close()
            result["success"] = len(result["errors"]) == 0

            # 报告数据源：delta 模式快照不完整，从本地累计库读取完整工单/站点数据
            if mode == "full":
                report_data = all_data
            else:
                try:
                    from backend.services.eflow_api_client import load_report_data_from_db
                except ImportError:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] sync_from_eflow_api: exception swallowed", exc_info=True)
                    from services.eflow_api_client import load_report_data_from_db
                report_data = load_report_data_from_db()
                if not report_data.get("eFlow TT"):
                    logger.warning("本地累计库无 eFlow TT 数据，报告回退到本次抓取快照")
                    report_data = all_data

            # 生成 Excel 报告（不上传 eflow_*.xlsx 到 FTP，仅本地保存）
            try:
                try:
                    from backend.services.eflow_api_client import generate_excel_report
                except ImportError:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] sync_from_eflow_api: exception swallowed", exc_info=True)
                    from services.eflow_api_client import generate_excel_report
                report_result = generate_excel_report(data=report_data, save_excel=False, upload_ftp=False)
                if report_result.get("excel_path"):
                    logger.info(f"Excel 报告已生成: {report_result['excel_path']}")
                result["excel_path"] = report_result.get("excel_path")
            except Exception as e:
                logger.warning(f"Excel 报告生成失败: {e}")
                result["excel_upload_error"] = str(e)

            # 生成小时报告与图片（复用 mail_126.py 的方法）
            try:
                try:
                    from backend.services.eflow_api_client import generate_hourly_report_with_images
                except ImportError:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] sync_from_eflow_api: exception swallowed", exc_info=True)
                    from services.eflow_api_client import generate_hourly_report_with_images
                hourly_result = generate_hourly_report_with_images(report_data)
                if hourly_result.get("success"):
                    logger.info(f"小时报告与图片已生成")
                    if hourly_result.get("hourly_file"):
                        logger.info(f"  Hourly Report: {hourly_result['hourly_file']}")
                    if hourly_result.get("eight_hour_file"):
                        logger.info(f"  8 Hours Report: {hourly_result['eight_hour_file']}")
                    if hourly_result.get("summary_file"):
                        logger.info(f"  Summary Report: {hourly_result['summary_file']}")
                    for p in hourly_result.get("image_paths", []):
                        logger.info(f"  图片: {p}")
                else:
                    logger.warning(f"小时报告生成未完成: {hourly_result.get('error', '未知错误')}")
            except Exception as e:
                logger.warning(f"小时报告生成失败: {e}")

            # 上传 tt_reports 到 FTP（删除远端旧文件，只保留最新一份）
            try:
                try:
                    from backend.services.eflow_api_client import upload_tt_reports_to_ftp
                except ImportError:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] sync_from_eflow_api: exception swallowed", exc_info=True)
                    from services.eflow_api_client import upload_tt_reports_to_ftp
                ftp_ok = upload_tt_reports_to_ftp()
                result["ftp_upload"] = ftp_ok
                if ftp_ok:
                    logger.info("tt_reports 已上传到 FTP（远端旧文件已清理）")
                else:
                    logger.warning("tt_reports FTP 上传失败或部分失败")
            except Exception as e:
                logger.warning(f"tt_reports FTP 上传异常: {e}")
                result["ftp_upload"] = False

            # 通过 API 将 TT/WO 数据写入远程 DB Main
            try:
                try:
                    from backend.services.eflow_api_client import generate_and_upload_fb_excel
                except ImportError:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] sync_from_eflow_api: exception swallowed", exc_info=True)
                    from services.eflow_api_client import generate_and_upload_fb_excel
                fb_result = generate_and_upload_fb_excel(all_data)
                result["fb_excel_upload"] = fb_result.get("upload_success", False)
                if fb_result.get("upload_success"):
                    logger.info("Eflow_TT_FB/WO_FB 已通过 API 写入远程 DB Main")
                else:
                    logger.warning("Eflow_TT_FB/WO_FB API 写入未完成")
            except Exception as e:
                logger.warning(f"FB API写入异常: {e}")
                result["fb_excel_upload"] = False

    except Exception as e:
        err_msg = f"同步异常: {e}"
        logger.error(err_msg)
        result["errors"].append(err_msg)

    elapsed = time.time() - start_time
    result["elapsed_seconds"] = round(elapsed, 2)
    total_rows = sum(result["tables_synced"].values())
    logger.info(f"eFlow API 同步完成: {total_rows} 行, {elapsed:.2f}s, success={result['success']}")

    return result


def _cleanup_old_tables(conn: sqlite3.Connection):
    """清理不再使用的旧表"""
    old_tables_to_remove = ["eflow_database"]
    for table in old_tables_to_remove:
        try:
            if table in set(list_table_names(conn)):
                conn.execute(f'DROP TABLE IF EXISTS "{table}"')
                logger.info(f"已删除旧表: {table}")
        except Exception as e:
            logger.warning(f"删除旧表 {table} 失败: {e}")
    conn.commit()


def _update_metadata(conn: sqlite3.Connection):
    """更新 _metadata 元数据表"""
    try:
        tables = [t for t in list_table_names(conn) if t != '_metadata']

        metadata_rows = []
        for table_name in tables:
            row_count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            col_names = table_columns(conn, table_name)
            col_count = len(col_names)
            # TODO-PHASE3-SCHEMA: 仅取列名（类型信息在双模下成本较高，元数据仅作展示用途）
            columns = [{"name": c, "type": ""} for c in col_names]
            metadata_rows.append({
                "table_name": table_name,
                "row_count": row_count,
                "col_count": col_count,
                "columns_json": str(columns),
            })

        if metadata_rows:
            meta_df = pd.DataFrame(metadata_rows)
            # TODO-PHASE3-SCHEMA: _metadata 属 eflow schema；write_df 默认走全局 app 引擎，
            # pg 模式下需改为 eflow 引擎（engine_override）才能写入正确 schema
            write_df(meta_df, '_metadata', if_exists='replace')
            conn.commit()
            logger.info(f"_metadata 更新: {len(metadata_rows)} 条记录")
    except Exception as e:
        logger.warning(f"_metadata 更新失败: {e}")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:sync_from_eflow_api>: exception swallowed", exc_info=True)
        pass

    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')

    result = sync_from_eflow_api()

    print(f"\n同步结果: {'成功' if result['success'] else '失败'}")
    print(f"同步表: {result['tables_synced']}")
    if result['errors']:
        print(f"错误: {result['errors']}")
    print(f"耗时: {result['elapsed_seconds']}s")
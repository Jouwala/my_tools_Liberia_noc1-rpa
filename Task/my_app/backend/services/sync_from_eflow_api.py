"""
eFlow API 数据同步服务
直接从 eFlow API 获取数据，字段映射后写入 app.db
不再依赖外部 eflow.sqlite3 中间文件
"""
import os
import re
import time
import sqlite3
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("eflow_sync")

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
                        return str(val) if pd.notna(val) else None
                df[col] = df[col].apply(ms_to_str)
        except (ValueError, TypeError):
            pass
    return df


# ========== 各表同步函数 ==========
def _sync_tt(df: pd.DataFrame, dst_conn: sqlite3.Connection) -> int:
    """同步 TT 数据"""
    t0 = time.time()
    if df.empty:
        logger.warning("TT 数据为空")
        return 0

    df = _apply_column_map(df, TT_COLUMN_MAP)
    df = _convert_ms_timestamps(df, ['created_time', 'last_modified_time', 'alarm_occur_time', 'alarm_clear_time'])

    # ticket_no 回退
    if 'ticket_no' not in df.columns and 'display_name' in df.columns:
        df['ticket_no'] = df['display_name']
    elif 'ticket_no' not in df.columns and 'wo_no' in df.columns:
        df['ticket_no'] = df['wo_no']

    df['_sync_time'] = datetime.now().isoformat()
    df['_sync_source'] = 'eflow_api'

    df.to_sql('eflow_tt', dst_conn, if_exists='replace', index=False, chunksize=5000)

    for idx_col in ['site_id', 'status', 'created_time', 'alarm_occur_time', 'domain', 'ticket_no']:
        if idx_col in df.columns:
            dst_conn.execute(f'CREATE INDEX IF NOT EXISTS idx_eflow_tt_{idx_col} ON eflow_tt({idx_col})')
    dst_conn.commit()

    elapsed = time.time() - t0
    logger.info(f"eflow_tt 同步完成: {len(df)} 行, {elapsed:.2f}s")
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

    df.to_sql('eflow_wo', dst_conn, if_exists='replace', index=False, chunksize=5000)

    for idx_col in ['site_id', 'status', 'created_time', 'alarm_occur_time', 'domain', 'wo_no']:
        if idx_col in df.columns:
            dst_conn.execute(f'CREATE INDEX IF NOT EXISTS idx_eflow_wo_{idx_col} ON eflow_wo({idx_col})')
    dst_conn.commit()

    elapsed = time.time() - t0
    logger.info(f"eflow_wo 同步完成: {len(df)} 行, {elapsed:.2f}s")
    return len(df)


def _sync_generic(df: pd.DataFrame, dst_conn: sqlite3.Connection, table_name: str) -> int:
    """通用同步：清洗列名后直接写入"""
    t0 = time.time()
    if df.empty:
        logger.warning(f"{table_name} 数据为空")
        return 0

    df.columns = [_clean_column_name(c) for c in df.columns]
    df['_sync_time'] = datetime.now().isoformat()
    df.to_sql(table_name, dst_conn, if_exists='replace', index=False, chunksize=5000)
    dst_conn.commit()

    elapsed = time.time() - t0
    logger.info(f"{table_name} 同步完成: {len(df)} 行, {elapsed:.2f}s")
    return len(df)


def _sync_site(df: pd.DataFrame, dst_conn: sqlite3.Connection) -> int:
    """同步 eFlow Site 数据 → eflow_site（独立表，不替换 master_site_db）"""
    t0 = time.time()
    if df.empty:
        logger.warning("Site 数据为空")
        return 0

    df = _apply_column_map(df, SITE_COLUMN_MAP)
    df['_sync_time'] = datetime.now().isoformat()
    df['_sync_source'] = 'eflow_api'

    df.to_sql('eflow_site', dst_conn, if_exists='replace', index=False, chunksize=5000)

    for idx_col in ['site_id', 'region', 'site_type']:
        if idx_col in df.columns:
            dst_conn.execute(f'CREATE INDEX IF NOT EXISTS idx_eflow_site_{idx_col} ON eflow_site({idx_col})')
    dst_conn.commit()

    elapsed = time.time() - t0
    logger.info(f"eflow_site 同步完成: {len(df)} 行, {elapsed:.2f}s")
    return len(df)


def _sync_realtime_alarm(df: pd.DataFrame, dst_conn: sqlite3.Connection) -> int:
    """同步实时告警数据"""
    t0 = time.time()
    if df.empty:
        logger.warning("realtime_alarm 数据为空")
        return 0

    df.columns = [_clean_column_name(c) for c in df.columns]
    df['_sync_time'] = datetime.now().isoformat()
    df.to_sql('realtime_alarm', dst_conn, if_exists='replace', index=False, chunksize=5000)

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
    df.to_sql('history_alarm', dst_conn, if_exists='replace', index=False, chunksize=5000)

    for idx_col in ['site_id', 'tt_id', 'region', 'alarmraisedtime']:
        if idx_col in df.columns:
            dst_conn.execute(f'CREATE INDEX IF NOT EXISTS idx_history_alarm_{idx_col} ON history_alarm({idx_col})')
    dst_conn.commit()

    elapsed = time.time() - t0
    logger.info(f"history_alarm 同步完成: {len(df)} 行, {elapsed:.2f}s")
    return len(df)


# ========== 主同步函数 ==========
def sync_from_eflow_api() -> dict:
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
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": 0,
        "excel_path": None,
        "ftp_upload": False,
    }

    logger.info("开始 eFlow API 数据同步（直连模式）")

    try:
        # 从 API 获取所有数据
        try:
            from backend.services.eflow_api_client import fetch_all_data
        except ImportError:
            from services.eflow_api_client import fetch_all_data
        all_data = fetch_all_data()

        if not all_data:
            msg = "API 未返回任何数据"
            logger.error(msg)
            result["errors"].append(msg)
            return result

        # 连接目标数据库
        dst_conn = sqlite3.connect(str(DB_PATH))
        dst_conn.execute("PRAGMA journal_mode=WAL")
        dst_conn.execute("PRAGMA synchronous=NORMAL")

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

        # 生成 Excel 报告（不上传 eflow_*.xlsx 到 FTP，仅本地保存）
        try:
            try:
                from backend.services.eflow_api_client import generate_excel_report
            except ImportError:
                from services.eflow_api_client import generate_excel_report
            report_result = generate_excel_report(data=all_data, save_excel=False, upload_ftp=False)
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
                from services.eflow_api_client import generate_hourly_report_with_images
            hourly_result = generate_hourly_report_with_images(all_data)
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
            exists = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            if exists:
                conn.execute(f'DROP TABLE IF EXISTS "{table}"')
                logger.info(f"已删除旧表: {table}")
        except Exception as e:
            logger.warning(f"删除旧表 {table} 失败: {e}")
    conn.commit()


def _update_metadata(conn: sqlite3.Connection):
    """更新 _metadata 元数据表"""
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != '_metadata' ORDER BY name"
        ).fetchall()]

        metadata_rows = []
        for table_name in tables:
            row_count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            col_info = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            col_count = len(col_info)
            columns = [{"name": c[1], "type": c[2]} for c in col_info]
            metadata_rows.append({
                "table_name": table_name,
                "row_count": row_count,
                "col_count": col_count,
                "columns_json": str(columns),
            })

        if metadata_rows:
            meta_df = pd.DataFrame(metadata_rows)
            meta_df.to_sql('_metadata', conn, if_exists='replace', index=False)
            conn.commit()
            logger.info(f"_metadata 更新: {len(metadata_rows)} 条记录")
    except Exception as e:
        logger.warning(f"_metadata 更新失败: {e}")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')

    result = sync_from_eflow_api()

    print(f"\n同步结果: {'成功' if result['success'] else '失败'}")
    print(f"同步表: {result['tables_synced']}")
    if result['errors']:
        print(f"错误: {result['errors']}")
    print(f"耗时: {result['elapsed_seconds']}s")

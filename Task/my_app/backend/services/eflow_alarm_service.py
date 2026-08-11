"""eFlow 告警同步服务（Phase 4 从 eflow_api_client.py 拆分）

负责实时告警（Realtime Alarm）与历史告警（History Alarm）的抓取、清洗与入库：
- 实时告警：分页拉取 -> 规范化 -> 写 eflow.db + app.db（仪表盘主库）
- 历史告警：滚动时间窗口并发分页 -> 过滤有效 TT ID -> 幂等 upsert 入库
HTTP 基础、登录会话、重试仍由 eflow_api_client 提供（本模块单向依赖，无循环）。
"""

import ssl
import socket
import json
import io
import time
import re
import base64
import uuid
import logging
import gzip
import os
import random
import glob
import shutil
import csv
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import ftplib
from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names, table_columns, write_df


from backend.services.eflow_api_client import (  # Phase 4 拆分：共享常量/基础函数
    ALARM_API_PATH,
    APP_DB_PATH,
    DATA_DIR,
    HIS_ALARM_API_PATH,
    HOST,
    PORT,
    _http_request,
    _safe_json_loads,
    ensure_login,
    get_session_headers,
    logger,
    parse_response,
)


ALARM_REFERER = f"https://{HOST}:{PORT}/iui/fm/angularFm/dist/index.html"

# 实时/历史告警共用 alarmcodeconds，保证过滤条件一致。
ALARM_CODE_CONDS = [
    {"restype": "zte.ran.nodeb", "alarmcode": 99933},
    {"restype": "zte.ran.bts", "alarmcode": 9920},
    {"restype": "zte.ran.enodeb", "alarmcode": 9920},
    {"restype": "zte.ran.nodeb", "alarmcode": 9920},
    {"restype": "zte.ran.nodeb", "alarmcode": 9995},
    {"restype": "zte.ran.bts", "alarmcode": 9981},
    {"restype": "zte.ran.nodeb", "alarmcode": 9991},
    {"restype": "zte.ran.nodeb", "alarmcode": 9990},
    {"restype": "zte.ran.enodeb", "alarmcode": 9970},
    {"restype": "zte.ran.enodeb", "alarmcode": 9971},
    {"restype": "zte.ran.bts", "alarmcode": 9910},
    {"restype": "zte.ran.enodeb", "alarmcode": 9910},
    {"restype": "zte.ran.nodeb", "alarmcode": 9910},
    {"restype": "zte.ran.bts", "alarmcode": 9980},
    {"restype": "ZTE_TRM_DWDM_ZXONE_9700", "alarmcode": 4758},
    {"restype": "ZTE_TRM_OTHER_WL_LINK", "alarmcode": 4758},
]

ALARM_CONDITION = {
    "alarmcodeconds": ALARM_CODE_CONDS,
    "alarmcodefiltermode": 0, "visibles": [1], "timezonetype": 0,
    "sortinfo": {"sortdirection": 0, "sortfield": "servertime", "combinesortinfos": []},
    "extensionconds": {"maintainstatus": {"valuelist": ["0"]}},
    "querymetype": 2, "refresh": True,
}

# FM History Alarm 查询条件：近 1 天回溯（动态计算，原默认 3 天 → 2026-08-01 缩为 1 天以降低上游慢接口耗时）
HIS_ALARM_DAYS_BACK = int(os.environ.get("EFLOW_HIS_ALARM_DAYS", "1"))
HIS_ALARM_HOURS = int(os.environ.get("EFLOW_HIS_ALARM_HOURS", "48"))

# 历史告警分页大小（每页记录数）。默认 5000，比原 2000 减少约 2.5x 慢请求次数。（E）
HIS_ALARM_PAGE_SIZE = int(os.environ.get("EFLOW_HIS_ALARM_PAGE_SIZE", "5000"))

# 历史告警并发翻页 worker 数（需先确认服务端对同 cookie 并发分页安全，见 D 探针）。默认 4。（D）
HIS_ALARM_WORKERS = max(1, int(os.environ.get("EFLOW_HIS_ALARM_WORKERS", "4")))


def _get_his_alarm_time_range():
    """返回历史告警查询的起止时间 (start_dt, end_dt)。

    优先使用滚动窗口 EFLOW_HIS_ALARM_HOURS（now-H ~ now）；未设置则回退按天窗口。
    """
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    if HIS_ALARM_HOURS and HIS_ALARM_HOURS > 0:
        end_dt = now
        start_dt = now - timedelta(hours=HIS_ALARM_HOURS)
    else:
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=0)
        start_dt = (end_dt - timedelta(days=HIS_ALARM_DAYS_BACK)).replace(hour=0, minute=0, second=0)
    return start_dt, end_dt


HIS_ALARM_CONDITION = {
    "alarmraisedtime": {"mode": "0", "start": -1, "end": -1},
    "alarmcodefiltermode": 0,
    "alarmcodeconds": ALARM_CODE_CONDS,
    "querymetype": 0,
    "timezonetype": 0,
    "sortinfo": {"language": "en", "sortdirection": 0, "sortfield": "alarmclearedtime", "combinesortinfos": []},
    "extensionconds": {"maintainstatus": {"valuelist": ["0"]}},
    "usefromsize": True,
}

ALARM_COLUMNS = [
    "Site Status", "Networktype", "Alarm Source", "Site Name", "neip", "restypename",
    "RAN Site Type", "MW Layer", "Vendor", "Power Infomation", "Transmission Type",
    "Site ID", "Site Attribute", "TT ID", "durationname", "codename", "Alarm Title",
    "Region", "link", "perceivedseverityname", "reasonname", "POP Site", "clearstatename",
    "Circle", "Site Class", "Type", "Link Path", "Site VIP Level", "Cell Name",
    "Assign RuleName", "RAN Type", "Latest Match Time", "First Match Time",
    "Assign Delay", "rootcount", "auxiliarycount",
]


def _normalize_alarm_rows(rows):
    """将 FM Active Alarm 的字段对象转换为以 columnname 为键的字典列表"""
    if not isinstance(rows, list):
        return rows
    normalized = []
    for row in rows:
        if isinstance(row, dict):
            new_row = {}
            for k, v in row.items():
                if isinstance(v, dict) and "columnname" in v:
                    col_name = v.get("columnname") or k
                    new_row[col_name] = v.get("value")
                else:
                    new_row[k] = v
            normalized.append(new_row)
        elif isinstance(row, list):
            new_row = {}
            for item in row:
                if isinstance(item, dict) and "columnname" in item:
                    col_name = item.get("columnname")
                    if col_name:
                        new_row[col_name] = item.get("value")
            normalized.append(new_row)
        else:
            normalized.append(row)
    return normalized


def _fetch_alarm_pipeline():
    """获取实时告警数据"""
    logger.info("Fetching active alarm data...")
    start_time = time.time()

    all_rows = []
    total = None
    page_size = 200
    page = 1

    _cookie, _token = get_session_headers()
    headers_extra = (
        f"Cookie: {_cookie}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {ALARM_REFERER}\r\n"
        f"forgerydefense: {_token}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{HOST}:{PORT}\r\n"
        f"LogTracking: True\r\n"
    )

    query_id = "T" + uuid.uuid4().hex
    active_tab_id = "fm-active_" + uuid.uuid4().hex

    while True:
        now = datetime.now(timezone.utc)
        payload = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}"[:-3] + "Z",
            "condition": ALARM_CONDITION, "manual": False,
            "page": page, "pagesize": page_size,
            "queryid": query_id, "activeTabId": active_tab_id,
        }

        body = json.dumps(payload)
        status_line, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", ALARM_API_PATH, headers_extra=headers_extra, body=body,
        )

        data = json.loads(resp_body.decode('utf-8'))

        if isinstance(data, list):
            rows = _normalize_alarm_rows(data)
            all_rows.extend(rows)
            if len(rows) < page_size:
                break
            page += 1
            continue

        if not isinstance(data, dict):
            break

        if data.get("code") not in (0, None, "0"):
            break

        if total is None:
            total = data.get("totalcount") or data.get("total", 0)
            logger.info(f"Alarm total records: {total}")

        rows = parse_response(data, label="Alarm")
        rows = _normalize_alarm_rows(rows)
        all_rows.extend(rows)

        if len(rows) < page_size:
            break
        page += 1
        if page > 500:
            break

    elapsed = time.time() - start_time
    logger.info(f"Alarm: {len(all_rows)} records in {elapsed:.2f}s")
    return ("realtime_alarm", all_rows)


def _filter_rows_with_tt_id(rows):
    """过滤保留 TT ID 不为空且不为 '-' 的记录。"""
    if not isinstance(rows, list):
        return rows
    filtered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tt_id = row.get("TT ID", "")
        if isinstance(tt_id, str):
            tt_id = tt_id.strip()
        if tt_id and tt_id != "-":
            filtered.append(row)
    return filtered


def _fetch_history_page(offset, page_size, his_start, his_end):
    """抓取历史告警单页（offset/size）。返回 (rows, totalcount_or_None, bytes, elapsed_s)。

    纯无状态分页（condition.from/size），可供并发调用。每页记录耗时/字节用于基线打点（A）。
    """
    page_start = time.time()
    ensure_login()
    _cookie, _token = get_session_headers()
    headers_extra = (
        f"Cookie: {_cookie}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {ALARM_REFERER}\r\n"
        f"forgerydefense: {_token}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{HOST}:{PORT}\r\n"
        f"LogTracking: True\r\n"
    )
    condition = dict(HIS_ALARM_CONDITION)
    condition["alarmraisedtime"] = {
        "mode": "0",
        "start": int(his_start.timestamp() * 1000),
        "end": int(his_end.timestamp() * 1000),
    }
    condition["from"] = offset
    condition["size"] = page_size

    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    iso_ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}"[:-3] + "Z"
    payload = {
        "querynum": page_size,
        "condition": condition,
        "timestamp": iso_ts,
        "manual": True,
    }
    body = json.dumps(payload)
    path = f"{HIS_ALARM_API_PATH}?timestamp={now_ms}"
    status_line, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", path, headers_extra=headers_extra, body=body,
    )
    elapsed = time.time() - page_start
    total = None
    rows = []
    try:
        data, parse_ok = _safe_json_loads(resp_body.decode('utf-8'), label=f"History(offset={offset})")
        if parse_ok and isinstance(data, dict) and data.get("code") in (0, None, "0"):
            total = data.get("totalcount") or data.get("total", 0)
            rows = parse_response(data, label="History")
            if not isinstance(rows, list):
                rows = []
            rows = _normalize_alarm_rows(rows)
        else:
            code = data.get("code") if isinstance(data, dict) else type(data)
            logger.warning(f"History page offset={offset} unexpected: code={code}")
    except Exception as e:
        logger.warning(f"History page offset={offset} parse error: {e}")
    logger.info(
        f"History page offset={offset} size={page_size}: {len(resp_body)} bytes, "
        f"{len(rows)} rows, {elapsed:.1f}s, total={total}"
    )
    return rows, total, len(resp_body), elapsed


def _fetch_history_alarm_pipeline():
    """获取历史告警数据（滚动窗口 + 并发翻页）。

    A: 每页记录耗时/字节/行数（基线打点）。
    D: 首页串行取 totalcount，剩余页用 ThreadPoolExecutor 并发拉取（worker=HIS_ALARM_WORKERS）。
    E: 分页大小 = HIS_ALARM_PAGE_SIZE。
    C: 窗口 = _get_his_alarm_time_range（默认 48h 滚动）。
    """
    logger.info("Fetching history alarm data...")
    start_time = time.time()

    his_start, his_end = _get_his_alarm_time_range()
    logger.info(
        f"History alarm range: {his_start.isoformat()} ~ {his_end.isoformat()} "
        f"(window={HIS_ALARM_HOURS}h, page_size={HIS_ALARM_PAGE_SIZE}, workers={HIS_ALARM_WORKERS})"
    )

    all_rows = []
    page_size = HIS_ALARM_PAGE_SIZE

    # 串行抓第一页，拿到 totalcount
    rows0, total, _, _ = _fetch_history_page(0, page_size, his_start, his_end)
    all_rows.extend(rows0)
    if total is None:
        logger.warning("History: cannot determine totalcount, stop after first page")
        elapsed = time.time() - start_time
        logger.info(f"History Alarm: {len(all_rows)} records in {elapsed:.2f}s")
        return ("history_alarm", all_rows)
    logger.info(f"History alarm total records: {total}")

    if len(rows0) < page_size and total <= page_size:
        elapsed = time.time() - start_time
        logger.info(f"History Alarm: {len(all_rows)} records in {elapsed:.2f}s (single page)")
        return ("history_alarm", all_rows)

    # 并发抓剩余页（offset 列表按 page_size 步进，到 total 为止）
    offsets = [o for o in range(page_size, max(total, len(all_rows)), page_size) if o <= 100000]
    logger.info(f"History: fetching {len(offsets)} more pages with {HIS_ALARM_WORKERS} workers")

    with ThreadPoolExecutor(max_workers=HIS_ALARM_WORKERS) as ex:
        future_to_off = {
            ex.submit(_fetch_history_page, o, page_size, his_start, his_end): o
            for o in offsets
        }
        for fut in as_completed(future_to_off):
            o = future_to_off[fut]
            try:
                r, _, _b, _e = fut.result()
                all_rows.extend(r)
            except Exception as e:
                logger.error(f"History page offset={o} failed: {e}")

    # 并发去重（按 eFlow 唯一告警 id，防止重复抓取）
    before = len(all_rows)
    seen = set()
    deduped = []
    for row in all_rows:
        rid = row.get("id") if isinstance(row, dict) else None
        if rid is not None:
            if rid in seen:
                continue
            seen.add(rid)
        deduped.append(row)
    all_rows = deduped

    elapsed = time.time() - start_time
    logger.info(
        f"History Alarm: {len(all_rows)} records (dedup {before}->{len(all_rows)}) in {elapsed:.2f}s, "
        f"pages={len(offsets) + 1}, workers={HIS_ALARM_WORKERS}"
    )
    return ("history_alarm", all_rows)
def write_alarm_csv(data):
    """将规范化后的原始告警数据写入 CSV，只保留最新一个文件。"""
    output_file = os.path.join(DATA_DIR, "eflow_alarm_raw.csv")

    if not isinstance(data, list) or not data:
        logger.warning("Alarm CSV: no data")
        return output_file

    fieldnames = sorted(set().union(*(row.keys() for row in data)))
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)

    logger.info(f"Alarm CSV saved: {output_file}, {len(data)} records")
    return output_file
def write_alarm_sqlite(data):
    """过滤指定字段并替换写入 eflow.sqlite3 的 realtime_alarm 表。"""
    db_file = os.path.join(DATA_DIR, "eflow.sqlite3")

    if not isinstance(data, list) or not data:
        logger.warning("Alarm SQLite: no data")
        return db_file

    with get_raw_connection(db_file) as conn:
        col_defs = ", ".join([f'"{col}" TEXT' for col in ALARM_COLUMNS])
        conn.execute("DROP TABLE IF EXISTS realtime_alarm")
        conn.execute(f"CREATE TABLE realtime_alarm ({col_defs})")

        placeholders = ", ".join(["?" for _ in ALARM_COLUMNS])
        cols = ", ".join([f'"{col}"' for col in ALARM_COLUMNS])
        # TODO-PHASE3-SCHEMA: realtime_alarm 写入独立库 eflow.sqlite3（非 app.db）。
        # 默认 sqlite 模式直接落库；PG 模式需 engine_override 指向 schema=eflow。
        sql = f"INSERT INTO realtime_alarm ({cols}) VALUES ({placeholders})"
        for row in data:
            conn.execute(sql, tuple(row.get(col, "") for col in ALARM_COLUMNS))

        conn.commit()
        conn.close()

    logger.info(f"Alarm SQLite saved: {db_file}, {len(data)} records")
    return db_file
def write_history_alarm_csv(data):
    """将规范化后的历史告警数据写入 CSV，只保留最新一个文件。"""
    output_file = os.path.join(DATA_DIR, "eflow_history_alarm_raw.csv")

    if not isinstance(data, list) or not data:
        logger.warning("History Alarm CSV: no data")
        return output_file

    fieldnames = sorted(set().union(*(row.keys() for row in data)))
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)

    logger.info(f"History Alarm CSV saved: {output_file}, {len(data)} records")
    return output_file


def write_history_alarm_sqlite(data):
    """过滤指定字段并替换写入 eflow.sqlite3 的 history_alarm 表。"""
    db_file = os.path.join(DATA_DIR, "eflow.sqlite3")

    if not isinstance(data, list) or not data:
        logger.warning("History Alarm SQLite: no data")
        return db_file

    with get_raw_connection(db_file) as conn:
        col_defs = ", ".join([f'"{col}" TEXT' for col in ALARM_COLUMNS])
        conn.execute("DROP TABLE IF EXISTS history_alarm")
        conn.execute(f"CREATE TABLE history_alarm ({col_defs})")

        placeholders = ", ".join(["?" for _ in ALARM_COLUMNS])
        cols = ", ".join([f'"{col}"' for col in ALARM_COLUMNS])
        # TODO-PHASE3-SCHEMA: history_alarm 写入独立库 eflow.sqlite3（非 app.db）。
        # 默认 sqlite 模式直接落库；PG 模式需 engine_override 指向 schema=eflow。
        sql = f"INSERT INTO history_alarm ({cols}) VALUES ({placeholders})"
        for row in data:
            conn.execute(sql, tuple(row.get(col, "") for col in ALARM_COLUMNS))

        conn.commit()
        conn.close()

    logger.info(f"History Alarm SQLite saved: {db_file}, {len(data)} records")
    return db_file
def _clean_column_name(col: str) -> str:
    """通用列名清洗：转 snake_case（本地副本，避免跨模块依赖）。"""
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


def _write_alarm_to_appdb(table_name: str, rows, index_cols: list, upsert_key: str = None):
    """将完整告警数据（全字段 + snake_case 归一化）写入仪表盘主库 db/app.db。

    仪表盘的 routers（gis.py / alarm_dashboard.py）从 db/app.db 读取 realtime_alarm /
    history_alarm，之前的 write_alarm_sqlite 只写入 data/eflow/eflow.sqlite3，导致
    任务显示 Success 但仪表盘数据不更新。此函数补全写入主库，列结构与 routers 期望一致。

    upsert_key: 若提供（如 history_alarm 的 "id"，eFlow 唯一告警 ID），则按该键做幂等累积写入
    —— 先 DELETE 匹配旧行再 append，不再整表重建（B）。不提供则保持原 if_exists="replace" 语义。
    """
    if not isinstance(rows, list) or not rows:
        logger.warning(f"{table_name} -> app.db: no data, skip")
        return
    try:
        df = pd.DataFrame(rows)
        # 列名归一化为 snake_case（与 sync_from_eflow_api._sync_*_alarm 一致）
        new_cols = [_clean_column_name(c) for c in df.columns]
        seen = {}
        final_cols = []
        for c in new_cols:
            if c in seen:
                seen[c] += 1
                final_cols.append(f"{c}_{seen[c]}")
            else:
                seen[c] = 0
                final_cols.append(c)
        df.columns = final_cols
        # list/dict 列序列化为 JSON（SQLite 不支持）
        object_cols = df.select_dtypes(include=["object"]).columns
        for col in object_cols:
            if df[col].apply(lambda x: isinstance(x, (list, dict))).any():
                df[col] = df[col].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x)
        df["_sync_time"] = datetime.now().isoformat()

        with get_raw_connection(APP_DB_PATH) as conn:
            if isinstance(conn, sqlite3.Connection):
                # 调优类 PRAGMA 仅 sqlite 有效（PG 无等价物）
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            if upsert_key and upsert_key in df.columns:
                # 幂等累积写入（B）：按 upsert_key 删除旧行再 append，避免整表重建与重抓浪费
                if table_name in set(list_table_names(conn)):
                    # 列漂移修复：API 新增字段（如 parentinfo）在 append 模式下会因目标表缺列
                    # 报 "字段不存在"。写入前补齐缺失列（TEXT，无损、幂等），不再中断同步。
                    existing_cols = set(table_columns(conn, table_name))
                    missing_cols = [c for c in df.columns if c not in existing_cols]
                    for c in missing_cols:
                        try:
                            conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{c}" TEXT')
                            logger.info(f"{table_name}: 新增缺失列 {c!r} (schema drift 修复)")
                        except Exception as e:
                            logger.warning(f"{table_name}: 新增列 {c!r} 失败: {e}")
                    if missing_cols:
                        # DDL 必须先提交，write_df 所用的独立引擎连接才能在 PG 下看到新列
                        conn.commit()
                    ids = df[upsert_key].tolist()
                    deleted = 0
                    for i in range(0, len(ids), 900):
                        chunk = ids[i:i + 900]
                        qmarks = ",".join("?" for _ in chunk)
                        # upsert_key 列可能已被转成 TEXT（与动态表语义一致），
                        # 故参数统一转字符串，避免 PG "text = bigint" 操作符不存在的错误。
                        conn.execute(
                            f'DELETE FROM "{table_name}" WHERE "{upsert_key}" IN ({qmarks})',
                            [str(x) for x in chunk],
                        )
                        deleted += len(chunk)
                    logger.info(f"{table_name}: 删除 {deleted} 条旧行 (upsert on {upsert_key})")
                    # DELETE 也需先提交，确保 write_df 引擎连接可见（PG 跨连接可见性）
                    conn.commit()
                write_df(df, table_name, if_exists="append")
            else:
                write_df(df, table_name, if_exists="replace")
            for idx_col in index_cols:
                if idx_col in df.columns:
                    conn.execute(f'CREATE INDEX IF NOT EXISTS idx_{table_name}_{idx_col} ON {table_name}({idx_col})')
            conn.commit()
            conn.close()
            logger.info(f"{table_name} 已写入 app.db: {len(df)} 行, {len(df.columns)} 列")
    except Exception as e:
        logger.error(f"{table_name} 写入 app.db 失败: {e}")
def fetch_and_save_active_alarm():
    """
    仅同步实时告警：登录 eFlow -> 获取实时告警 -> 保存 SQLite（不生成 CSV）
    """
    logger.info("Starting active alarm sync...")
    start_time = time.time()

    ensure_login()

    alarm_result = _fetch_alarm_pipeline()
    _, alarm_rows = alarm_result if isinstance(alarm_result, tuple) else ("realtime_alarm", alarm_result)
    write_alarm_sqlite(alarm_rows)
    _write_alarm_to_appdb("realtime_alarm", alarm_rows, ["site_id", "tt_id", "alarmraisedtime", "site_name"])

    elapsed = time.time() - start_time
    logger.info(f"Active alarm sync completed in {elapsed:.2f}s, {len(alarm_rows)} records")
    return {"realtime_alarm": alarm_rows}


def fetch_and_save_history_alarm():
    """
    仅同步历史告警：登录 eFlow -> 获取历史告警 -> 过滤 TT ID -> 保存 SQLite（不生成 CSV）
    """
    logger.info("Starting history alarm sync...")
    start_time = time.time()

    ensure_login()

    his_result = _fetch_history_alarm_pipeline()
    _, his_rows = his_result if isinstance(his_result, tuple) else ("history_alarm", his_result)
    filtered_his_rows = _filter_rows_with_tt_id(his_rows)
    logger.info(
        f"History alarm filtered: {len(his_rows)} -> {len(filtered_his_rows)} "
        f"(removed {len(his_rows) - len(filtered_his_rows)} rows with empty/invalid TT ID)"
    )
    write_history_alarm_sqlite(filtered_his_rows)
    # B: 按 eFlow 唯一告警 id 做幂等累积写入（不再整表重建，旧数据保留、只抓增量）
    _write_alarm_to_appdb("history_alarm", filtered_his_rows, ["site_id", "tt_id", "alarmraisedtime", "region"], upsert_key="id")

    elapsed = time.time() - start_time
    logger.info(f"History alarm sync completed in {elapsed:.2f}s, {len(filtered_his_rows)} records")
    return {"history_alarm": filtered_his_rows}


def fetch_and_save_alarm_data():
    """
    同步实时告警 + 历史告警（合并入口，用于统一调度）
    """
    logger.info("Starting alarm (active + history) sync...")
    start_time = time.time()

    result = {}
    try:
        active_result = fetch_and_save_active_alarm()
        result.update(active_result)
    except Exception as e:
        logger.error(f"Active alarm failed: {e}")
        result["realtime_alarm"] = []

    try:
        history_result = fetch_and_save_history_alarm()
        result.update(history_result)
    except Exception as e:
        logger.error(f"History alarm failed: {e}")
        result["history_alarm"] = []

    elapsed = time.time() - start_time
    logger.info(
        f"All alarm sync completed in {elapsed:.2f}s: "
        f"active={len(result.get('realtime_alarm', []))}, history={len(result.get('history_alarm', []))}"
    )
    return result

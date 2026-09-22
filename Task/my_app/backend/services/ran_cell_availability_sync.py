# -*- coding: utf-8 -*-
r"""
RAN Cell Availability 1-Day KPI 同步服务（my_app 内集成版）

替代独立 RPA 脚本 D:\01_RPA\Task\RAN\Avalability\ran_kpi_avalability_1day.py：
  - 复用 backend.services.ran_ume_service 的 UME 登录 / PM 历史查询 / Excel 解析能力
  - 拉取 4 个可用性模板（FDD/UMTS/GSM/TDD）的 PM 历史（1 天粒度, gr=86400）
  - 写入本地 ran_kpi_avalability_1day.sqlite3（表 Daily_KPI_RPA_CELL_AVAIL_*，按主键覆盖）
  - FTP 上传到 192.168.100.19:/01_RPA/LBR_Tools/KPI/RAN/（与旧 RPA 完全一致的产物）

作为 my_app 定时任务注册：task_id = cell_availability_sync（归属 UME 串行组 u）。
产物文件名沿用历史拼写 ran_kpi_avalability_1day.sqlite3，保证下游消费者不变。
"""

import os
import re
import sys
import json
import time
import sqlite3
import logging
from datetime import datetime, timezone, timedelta, date
from ftplib import FTP, error_perm

logger = logging.getLogger(__name__)

try:
    from backend.services import ran_ume_service as rume
except Exception:  # pragma: no cover - 兜底直接 import
    import ran_ume_service as rume

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# ============================================================
# 路径 / FTP 配置（与旧 RPA 脚本保持一致）
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 产物名沿用历史拼写 avalability，下游消费者依赖此文件名
DB_NAME = "ran_kpi_avalability_1day.sqlite3"
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "data", DB_NAME))

FTP_HOST = "192.168.100.19"
FTP_USER = "ZTEEMS"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/RAN"


# ============================================================
# 4 个可用性模板的 PM 查询配置（来自旧 RPA AVAILABILITY_PM_CONFIGS）
# ============================================================
AVAILABILITY_PM_CONFIGS = {
    "KPI_RPA_CELL_AVAIL_FDD": {
        "templateid": "1638004472410",
        "templatename": "KPI_RPA_CELL_AVAIL_FDD",
        "motid": "EUtranCellFDD",
        "nfctid": "ITBBU,SDR,#",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "groupattributetype": 0,
        "groupbygroup": False,
        "showbusinesscolumn": True,
        "grouplayer": "me,eNodeBFunction,EUtranCellFDD",
        "items": ["C373230700", "C373230706"],
        "itemsposition": [0, 0],
        "itemsposition1": [1, 1],
        "businessmotid": "FDDV3.EUtranCellFDD",
        "itempositionbusiness": [0, 0],
    },
    "KPI_RPA_CELL_AVAIL_UMTS": {
        "templateid": "1638004472409",
        "templatename": "KPI_RPA_CELL_AVAIL_UMTS",
        "motid": "wPm.UtranCell",
        "nfctid": "MRNC",
        "containvcell": 2,
        "indexfillingtype": "zeroDenominator",
        "groupattributetype": 1,
        "groupattribute": "freqBandInd",
        "groupbygroup": False,
        "showbusinesscolumn": False,
        "grouplayer": "me,WV4.IubLink,WV4.UtranCell",
        "items": ["C310464560"],
        "itemsposition": [0],
        "itemsposition1": [0],
    },
    "KPI_RPA_CELL_AVAIL_GSM": {
        "templateid": "1638004472408",
        "templatename": "KPI_RPA_CELL_AVAIL_GSM",
        "motid": "gsmPm.cell",
        "nfctid": "MRNC",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "groupattributetype": 1,
        "groupattribute": "freqBand",
        "groupbygroup": False,
        "showbusinesscolumn": False,
        "grouplayer": "me,gv4.BTSSiteManager,gv4.BTS.cell",
        "items": ["C901080019", "C901080029", "C901080028", "C901080009", "C901080010", "C901080020"],
        "itemsposition": [0, 0, 0, 0, 0, 0],
        "itemsposition1": [0, 0, 0, 0, 0, 0],
    },
    "KPI_RPA_CELL_AVAIL_TDD": {
        "templateid": "1638004472411",
        "templatename": "KPI_RPA_CELL_AVAIL_TDD",
        "motid": "EUtranCellTDD",
        "nfctid": "ITBBU,SDR,#",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "groupattributetype": 0,
        "groupbygroup": False,
        "showbusinesscolumn": True,
        "grouplayer": "me,eNodeBFunction,EUtranCellTDD",
        "items": ["C373230706", "C373230700"],
        "itemsposition": [0, 0],
        "itemsposition1": [1, 1],
        "businessmotid": "TDDV3.EUtranCellTDD",
        "itempositionbusiness": [0, 0],
    },
}

# 模板 prefix -> 小区标识列的「归一化」名称（用于主键解析）
_PK_CELLNAME_LOOKUP = {
    "KPI_RPA_CELL_AVAIL_FDD": "E-UTRAN FDD Cell Name",
    "KPI_RPA_CELL_AVAIL_UMTS": "Cell Name",
    "KPI_RPA_CELL_AVAIL_GSM": "BTS Name",
    "KPI_RPA_CELL_AVAIL_TDD": "E-UTRAN TDD Cell Name",
}

# ============================================================
# 外部化配置（Settings →「任务配置」维护的 ran_cell_availability_config.json）
#   优先级：环境变量 > 配置文件 > 内置默认；FTP 账号密码不在此文件（走 credential_store）。
#   UME 主机/端口不在这里：本服务复用 ran_ume_service，见 ran_ume_config.json。
# ============================================================
try:
    from backend.services.task_config_files import (
        apply_config_overrides, normalize_query_configs)
except ImportError:
    from task_config_files import apply_config_overrides, normalize_query_configs  # type: ignore

_AV_CONF = apply_config_overrides(
    globals(),
    os.path.join(BASE_DIR, "ran_cell_availability_config.json"),
    {
        "ftp_host": ("FTP_HOST", str, "AVAIL_FTP_HOST"),
        "ftp_remote_dir": ("FTP_REMOTE_DIR", str, "AVAIL_FTP_DIR"),
        "db_name": ("DB_NAME", str, None),
    },
    log_name="cell_availability",
)
if _AV_CONF:
    # DB_PATH 是由 DB_NAME 推导的（上面已算过一次），改名的场景必须在覆盖后重算，否则改名不生效
    DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "data", DB_NAME))
    _av_qc = normalize_query_configs(_AV_CONF.get("query_configs") or [])
    if _av_qc:
        AVAILABILITY_PM_CONFIGS = _av_qc
        # 主键小区标识列按模板名保留，未在配置里出现的模板回退到通用「Cell Name」
        for _k in AVAILABILITY_PM_CONFIGS:
            _PK_CELLNAME_LOOKUP.setdefault(_k, "Cell Name")


# ============================================================
# 工具函数
# ============================================================
def _norm(s):
    """归一化列名：把不间断空格/全角空格统一成普通空格并压缩。"""
    if not isinstance(s, str):
        return s
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def _resolve_pk(table_name, headers):
    """根据表名 + 实际列头，返回用于覆盖写入的主键列 [日期列, 小区标识列]。"""
    prefix = table_name[6:] if table_name.startswith("Daily_") else table_name
    norm_to_orig = {_norm(h): h for h in headers}
    pk = []
    time_cand = "Begin Time"
    if _norm(time_cand) in norm_to_orig:
        pk.append(norm_to_orig[_norm(time_cand)])
    cell_norm = _PK_CELLNAME_LOOKUP.get(prefix)
    if cell_norm and cell_norm in norm_to_orig:
        pk.append(norm_to_orig[cell_norm])
    elif len(pk) < 2:
        for h in headers:
            n = _norm(h)
            if "Cell Name" in n or n == "BTS Name":
                if h not in pk:
                    pk.append(h)
                    break
    if len(pk) >= 2:
        return pk[:2]
    return [headers[0], headers[1]] if len(headers) >= 2 else [headers[0]]


def _utc_day_midnight(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _convert_value(v):
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


# ============================================================
# UME PM 历史查询（复用 ran_ume_service 的 HTTP 原语）
# ============================================================
def build_availability_payload(cfg, start_iso, end_iso):
    """依据模板配置构造 RAN UME PM 历史查询 payload（1 天窗口）。"""
    items = cfg["items"]
    n = len(items)
    payload = {
        "arraycounterinfos": [],
        "datatype": 0,
        "displaymode": 0,
        "favoriteconditionname": cfg["templatename"],
        "gr": "86400",
        "groupattributetype": cfg.get("groupattributetype", 0),
        "groupbygroup": cfg.get("groupbygroup", False),
        "groupbyplmn": False,
        "grouptype": 0,
        "items": items,
        "itemsposition": cfg.get("itemsposition", [0] * n),
        "itemsposition1": cfg.get("itemsposition1", [0] * n),
        "motid": cfg["motid"],
        "nfctid": cfg["nfctid"],
        "plmnpdfdisplaymode": False,
        "queryallbusiness": False,
        "showbusinesscolumn": cfg.get("showbusinesscolumn", False),
        "showintegrity": False,
        "straightquery": False,
        "templatename": cfg["templatename"],
        "templateid": cfg["templateid"],
        "needdeployfilter": False,
        "timeinfo": {
            "mode": 1,
            "start": start_iso,
            "end": end_iso,
            "relative": -1,
            "timezonetype": "1",
            "clienttimezone": "Atlantic/Reykjavik",
            "showtimezoneoffset": False,
            "querylongtime": {"type": 3, "value": 1},
            "timespanfilter": "00:00:00-24:00:00",
            "dayfiltertype": 0,
            "dayinmonthfilter": "1111111111111111111111111111111",
        },
        "indexfillingtype": cfg.get("indexfillingtype", "zeroDenominator"),
        "thresholdinfos": [],
        "templatetype": 0,
        "filterlayer": "all",
        "grouplayer": cfg["grouplayer"],
        "containvcell": cfg.get("containvcell", 0),
        "resfilterattribute": "",
        "uilocations": [],
        "reslocation": [],
        "inexistenceres": False,
        "firstDayOfWeek": 7,
        "iswireless": True,
        "hidehistorystopbutton": True,
        "opencustomizehistoryexport": False,
        "opentemplatecustomcolumn": False,
    }
    if "businessmotid" in cfg:
        payload["businessmotid"] = cfg["businessmotid"]
        payload["itempositionbusiness"] = cfg.get("itempositionbusiness", [0] * n)
        payload["businessfilterscope"] = []
        payload["groupbusinessids"] = []
    if "groupattribute" in cfg:
        payload["groupattribute"] = cfg["groupattribute"]
    return payload


def _create_pm_query(cookie, forgery, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = rume._pm_auth_headers(cookie, forgery)
    status, _hdrs, _raw, resp_body = rume._http_request(
        "POST", rume.PM_HISTORY_PATH, headers_extra=headers, body=body)
    if "200" not in status:
        raise Exception(f"Create PM query failed: {status}")
    data = json.loads(resp_body.decode("utf-8", "replace"))
    queryid = data.get("queryid") or data.get("id")
    if not queryid:
        raise Exception(f"No queryid: {resp_body.decode('utf-8', 'replace')[:500]}")
    return queryid


def _wait_pm_ready(cookie, forgery, queryid, timeout=600, interval=5):
    poll_path = f"{rume.PM_HISTORY_POLL_PATH}?type=0&queryid={queryid}"
    headers = rume._pm_auth_headers(cookie, forgery)
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, _hdrs, _raw, resp_body = rume._http_request("GET", poll_path, headers_extra=headers)
        try:
            pd = json.loads(resp_body.decode("utf-8", "replace"))
        except Exception:
            pd = {}
        if pd.get("querystate") == 1 or pd.get("progress", 0) >= 100:
            return True
        time.sleep(interval)
    raise TimeoutError(f"PM query {queryid} not ready in {timeout}s")


def _export_pm_bytes(cookie, forgery, queryid, filename):
    export_payload = {
        "id": queryid, "filename": filename, "chartlayout": 1, "contentmode": 0,
        "customizefieldtype": "0", "exportfiletype": 1, "exportserialnumber": False,
        "exporttableheaders": False, "formatwithts": 0, "imageinfo": [],
        "itemshowtype": 0, "tableheaders": {},
    }
    body = json.dumps(export_payload, ensure_ascii=False).encode("utf-8")
    headers = rume._pm_auth_headers(cookie, forgery)
    status, _hdrs, _raw, resp_body = rume._http_request(
        "POST", rume.PM_HISTORY_EXPORT_PATH, headers_extra=headers, body=body)
    if "200" not in status:
        raise Exception(f"Export failed: {status}")
    return resp_body


# ============================================================
# 拉取
# ============================================================
def fetch_availability_range(start_dt, end_dt, max_retries=2):
    """
    拉取 [start_dt, end_dt) UTC 窗口内 4 个可用性模板的数据，全程内存。
    返回 [(table_name, headers, rows), ...]。单模板失败重试，仍失败则跳过。
    """
    auth = rume._login()
    cookie, forgery = auth["cookie"], auth["forgery_token"]
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    logger.info(f"[AVAIL] UME 时间窗口(UTC): {start_iso} ~ {end_iso}")

    tasks = []
    for prefix, cfg in AVAILABILITY_PM_CONFIGS.items():
        ok = False
        for attempt in range(1, max_retries + 1):
            try:
                payload = build_availability_payload(cfg, start_iso, end_iso)
                queryid = _create_pm_query(cookie, forgery, payload)
                _wait_pm_ready(cookie, forgery, queryid, timeout=600, interval=5)
                ts = datetime.now().strftime("%Y%m%d%H%M%S")
                fname = f"{prefix}_win_{ts}"
                xlsx_bytes = _export_pm_bytes(cookie, forgery, queryid, fname)
                headers, rows = rume._read_xlsx_bytes(xlsx_bytes)
                table_name = f"Daily_{prefix}"
                tasks.append((table_name, headers, rows))
                logger.info(f"[AVAIL] {prefix}: {len(rows)} 行（内存解析完成）")
                ok = True
                break
            except Exception as e:
                logger.error(f"[AVAIL] {prefix} 拉取失败(attempt {attempt}): {e}")
        if not ok:
            logger.warning(f"[AVAIL] {prefix} 在窗口 {start_iso}~{end_iso} 多次重试失败，跳过")
    return tasks


def fetch_availability_via_api(window_days=2):
    """每日模式：拉取前 window_days 天窗口的可用性数据。"""
    now_utc = datetime.now(timezone.utc)
    end_dt = _utc_day_midnight(now_utc)
    start_dt = end_dt - timedelta(days=window_days)
    return fetch_availability_range(start_dt, end_dt)


# ============================================================
# 写库（按主键覆盖写入，重跑幂等）
# ============================================================
def _write_tasks_to_db(tasks):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA cache_size=-64000")
        total = 0
        summary = {}
        for table_name, headers, rows in tasks:
            if not headers or not rows:
                continue
            pk_cols = _resolve_pk(table_name, headers)
            _q = lambda s: '"' + str(s).replace('"', '""') + '"'
            quoted_pk = ", ".join(_q(c) for c in pk_cols)
            col_defs = ", ".join(_q(h) + " TEXT" for h in headers)
            pk_def = ", ".join(_q(c) for c in pk_cols)
            conn.execute(
                f'CREATE TABLE IF NOT EXISTS "{table_name}" ({col_defs}, PRIMARY KEY ({pk_def}))')
            quoted = [_q(h) for h in headers]
            placeholders = ", ".join(["?"] * len(headers))
            sql = (f'INSERT OR REPLACE INTO "{table_name}" '
                   f'({", ".join(quoted)}) VALUES ({placeholders})')
            norm_rows = []
            n_cols = len(headers)
            for row in rows:
                if len(row) < n_cols:
                    row = list(row) + [None] * (n_cols - len(row))
                elif len(row) > n_cols:
                    row = list(row[:n_cols])
                norm_rows.append([_convert_value(v) for v in row])
            conn.executemany(sql, norm_rows)
            cnt = len(norm_rows)
            total += cnt
            summary[table_name] = cnt
            logger.info(f"[AVAIL] 写入 {table_name}: {cnt} 行 (PK=({quoted_pk}))")
        conn.commit()
    finally:
        conn.close()
    return total, summary


# ============================================================
# FTP 上传（与旧 RPA 一致）
# ============================================================
def upload_to_ftp(local_path, remote_dir, filename, max_retries=2):
    """上传本地文件到 FTP 服务器（带重试）。"""
    for attempt in range(1, max_retries + 1):
        logger.info(f"[AVAIL][FTP] 连接 {FTP_HOST} ...（第 {attempt} 次）")
        ftp = None
        try:
            ftp = FTP(FTP_HOST, timeout=30)
            ftp.encoding = "utf-8"
            if attempt > 1:
                ftp.set_debuglevel(1)
            ftp.login(FTP_USER, FTP_PASS)
            ftp.cwd("/")
            parts = remote_dir.strip("/").split("/")
            for i in range(len(parts)):
                abs_path = "/" + "/".join(parts[:i + 1])
                try:
                    ftp.cwd(abs_path)
                except error_perm:
                    try:
                        ftp.mkd(abs_path)
                        ftp.cwd(abs_path)
                    except error_perm as e2:
                        logger.warning(f"[AVAIL][FTP] 无法创建目录 {abs_path}: {e2}")
            current_dir = ftp.pwd()
            expected = "/" + "/".join(parts)
            if current_dir != expected:
                ftp.cwd(expected)
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f)
            logger.info(f"[AVAIL][FTP] 已上传: {filename}")
            ftp.quit()
            return True
        except Exception as e:
            logger.error(f"[AVAIL][FTP] 上传失败: {e}")
            if ftp:
                try:
                    ftp.close()
                except Exception:
                    pass
    return False


def _vacuum_db():
    """回收 INSERT OR REPLACE 产生的空闲页，避免文件无限膨胀。"""
    try:
        c = sqlite3.connect(DB_PATH)
        cur = c.cursor()
        cur.execute("PRAGMA page_count"); pc = cur.fetchone()[0]
        cur.execute("PRAGMA freelist_count"); fl = cur.fetchone()[0]
        c.close()
        if pc and fl > max(50000, int(pc * 0.25)):
            logger.info(f"[AVAIL][vacuum] 空闲页 {fl}/{pc}，执行 VACUUM 压缩...")
            v = sqlite3.connect(DB_PATH)
            v.execute("VACUUM")
            v.close()
        else:
            logger.info(f"[AVAIL][vacuum] 空闲页 {fl}/{pc}，无需压缩")
    except Exception as e:
        logger.warning(f"[AVAIL][vacuum] 跳过（异常）: {e}")


# ============================================================
# 主入口（可被每日模式 / backfill 复用）
# ============================================================
def run_cell_availability_sync(window_days=2, do_upload=True,
                               backfill_start=None, backfill_end=None):
    """
    my_app 定时任务入口。
    - 每日模式（默认）：拉取前 window_days 天，写库 + FTP 上传。
    - backfill 模式：从 backfill_start 到 backfill_end，按 7 天分片拉取并 UPSERT，结尾统一上传。
    返回 dict 结果（含 success / tables / rows / errors）。
    """
    start_time = time.time()
    result = {"success": False, "tables": {}, "rows": 0, "errors": [], "elapsed_seconds": 0}
    try:
        if backfill_start:
            start = _utc_day_midnight(
                datetime.strptime(backfill_start, "%Y-%m-%d").replace(tzinfo=timezone.utc))
            if backfill_end:
                end = _utc_day_midnight(
                    datetime.strptime(backfill_end, "%Y-%m-%d").replace(tzinfo=timezone.utc))
            else:
                end = _utc_day_midnight(datetime.now(timezone.utc))
            if start >= end:
                result["errors"].append(f"起始日 {start.date()} >= 结束日 {end.date()}")
            else:
                cur = start
                chunk_days = 7
                while cur < end:
                    chunk_end = min(cur + timedelta(days=chunk_days), end)
                    tasks = fetch_availability_range(cur, chunk_end)
                    if tasks:
                        total, summary = _write_tasks_to_db(tasks)
                        result["rows"] += total
                        for k, v in summary.items():
                            result["tables"][k] = result["tables"].get(k, 0) + v
                    cur = chunk_end
        else:
            now_utc = datetime.now(timezone.utc)
            end_dt = _utc_day_midnight(now_utc)
            start_dt = end_dt - timedelta(days=window_days)
            tasks = fetch_availability_range(start_dt, end_dt)
            if not tasks:
                result["errors"].append("未通过 UME 获取到任何可用性数据")
            else:
                total, summary = _write_tasks_to_db(tasks)
                result["rows"] = total
                result["tables"] = summary

        if do_upload and result["rows"] > 0:
            _vacuum_db()
            try:
                ok = upload_to_ftp(DB_PATH, FTP_REMOTE_DIR, DB_NAME)
                if not ok:
                    result["errors"].append("FTP 上传失败")
            except Exception as e:
                result["errors"].append(f"FTP 上传异常: {e}")

        result["success"] = (len(result["errors"]) == 0) and (result["rows"] > 0)
    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"[AVAIL] 任务失败: {e}")

    result["elapsed_seconds"] = round(time.time() - start_time, 2)
    logger.info(f"[AVAIL] 完成: rows={result['rows']}, {result['elapsed_seconds']}s, "
                f"success={result['success']}")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="RAN 小区可用性 1-day KPI（复用 my_app UME 客户端，写库 + FTP）")
    parser.add_argument("--backfill", metavar="START", nargs="?", const="2026-01-01",
                        help="补采历史：从 START(YYYY-MM-DD) 到今天；不传值默认 2026-01-01")
    parser.add_argument("--end", metavar="END", default=None,
                        help="backfill 结束日 YYYY-MM-DD（默认今天）")
    parser.add_argument("--window-days", type=int, default=2,
                        help="每日模式窗口天数（默认 2）")
    parser.add_argument("--no-upload", action="store_true",
                        help="只写本地库，不上传 FTP（用于验证）")
    args = parser.parse_args()

    if args.backfill:
        res = run_cell_availability_sync(
            backfill_start=args.backfill, backfill_end=args.end,
            do_upload=not args.no_upload)
    else:
        res = run_cell_availability_sync(
            window_days=args.window_days, do_upload=not args.no_upload)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))

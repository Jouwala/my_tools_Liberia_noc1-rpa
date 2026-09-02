# -*- coding: utf-8 -*-
"""SP Online（eFlow Spare Parts）在线工单同步 —— 每小时从 eFlow SP 接口拉全量，写入 app.db。

数据来源：`data/sp_email/sp_online/url.txt`（浏览器抓包格式：Request URL + payload）。
复用 `eflow_api_client` 的登录会话与裸 socket HTTPS 通道（同源 eFlow 10.100.20.8:28001）。

产出表（Table Browser 可见）：
    sp_outbound  / sp_inbound / sp_transfer

服务端已验证的三个坑（改本模块前务必读）：
1. **filter 是必需的**：不带 filter（或空 payload）时，inbound/transfer 恒返回 `{"result":[],"total":0}`；
   outbound 只返回 164 条（在途）而非全量 609 条。只有显式枚举 `status eq "X"` 的 OR 全集
   才能拿到全量。故本模块在「url.txt 原 filter 拉到 0 行」时自动回退到状态全集 filter。
2. **部分字段放进 `field` 会让服务端 500**（`Failed to call eflow_pg service`）：
   实测 outbound 的 `warehouseName`、`slaExpectedFinishTime`，inbound 的 `warehouseName`
   均会触发。故请求前二分降级剔除坏字段（服务端仍会自动返回这些列）。
3. **customInfo.pageType 必须是 `allTicket`**：url.txt 里 inbound/transfer 抓包自带
   `pageType: mytask`（我的任务），用 admin 会话查恒为 0 行。
"""
import os
import sys
import json
import time
import logging
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.database import get_raw_connection
from backend.dialect_helpers import table_columns, upsert
from backend.services import eflow_api_client as EF

logger = logging.getLogger("sp_online")

# ---------------- 配置 ----------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
URL_TXT = os.environ.get(
    "SP_ONLINE_URL_FILE",
    str(PROJECT_ROOT / "data" / "sp_email" / "sp_online" / "url.txt"),
)
# 实测可用的 referer（eFlow SP 前端页面路径）
REFERER = "https://{host}:{port}/iui/eflow-sp/dist/index.html"
PAGE_SIZE = 200
FETCHED_AT_COL = "_fetched_at"

# 状态枚举全集：只用 url.txt 抓包里的状态（多为在途态）会漏掉 Closed 历史单，
# 故作为「原 filter 取到 0 行」时的兜底，保证拉到全量。
STATUS_ALL = [
    "WaitingForUpdate", "WaitingForVerify", "WaitingForConfirm", "WaitingForReturn",
    "WaitingForTransferOutboundConfirm", "WaitingForTransferInboundConfirm",
    "Draft", "Closed", "Canceled", "Rejected", "WaitingForApprove", "WaitingForReceive",
    "WaitingForOutbound", "WaitingForInbound", "Terminated", "Completed", "Returned",
]
FILTER_ALL = "(" + " or ".join(f'(status eq "{s}")' for s in STATUS_ALL) + ")"

# endpoint 关键字 -> 目标表名
TABLE_BY_KEY = {
    "sp-outbound": "sp_outbound",
    "sp-inbound": "sp_inbound",
    "sp-transfer": "sp_transfer",
}


# ---------------- url.txt 解析 ----------------
def parse_url_txt(path=URL_TXT):
    """解析抓包格式，返回 [{name, table, path, payload}]。

    格式为重复的区块：
        Request URL
        https://host:port/api/eflow-sp/v1/eflow-sp-outbound/base/list
        Request Method
        POST
        Status Code
        200 OK
        ...
        payload
        {"field":"...","start":0,...}
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = [l.strip() for l in f.read().splitlines()]

    url_idx = [i for i, l in enumerate(lines)
               if l.startswith("http") and "/api/eflow-sp/" in l]
    items = []
    for i in url_idx:
        url = lines[i]
        # 向后扫描到下一个 URL（或文件尾），取第一个以 { 开头的行作为 payload
        end = len(lines)
        for k in range(i + 1, len(lines)):
            if lines[k].startswith("http") and "/api/" in lines[k]:
                end = k
                break
        payload = None
        for k in range(i + 1, end):
            if lines[k].startswith("{"):
                try:
                    payload = json.loads(lines[k])
                except json.JSONDecodeError:
                    payload = None
                break
        if payload is None:
            logger.warning(f"[SP-ONLINE] 跳过无 payload 的接口: {url}")
            continue
        path = "/" + url.split("://", 1)[-1].split("/", 1)[1]
        table = None
        for key, tname in TABLE_BY_KEY.items():
            if key in path:
                table = tname
                break
        if table is None:
            logger.warning(f"[SP-ONLINE] 未识别的 endpoint，跳过: {path}")
            continue
        items.append({"table": table, "path": path, "payload": payload})
    return items


# ---------------- 拉取 ----------------
def _post(path, payload):
    """发一次 POST，返回 (ok, data_dict_or_None)。"""
    ref = REFERER.format(host=EF.HOST, port=EF.PORT)
    status, _hdrs, _raw, body = EF._http_request(
        "POST", path, headers_extra=EF._headers_extra(ref), body=json.dumps(payload)
    )
    if "500" in status:
        return False, None
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return False, None
    return True, data


def _resolve_fields(path, fields, fallback_filter):
    """二分剔除会让服务端 500 的字段，返回可用字段列表。"""
    def ok(fs):
        good, data = _post(path, {"field": ",".join(fs), "start": 0, "length": 2,
                                  "filter": fallback_filter})
        return good

    if not fields:
        return []
    if ok(fields):
        return list(fields)

    bad, queue = [], [list(fields)]
    while queue:
        cur = queue.pop(0)
        if len(cur) == 1:
            bad.append(cur[0])
            continue
        mid = len(cur) // 2
        left, right = cur[:mid], cur[mid:]
        if not ok(left):
            queue.append(left)
        if not ok(right):
            queue.append(right)
    logger.warning(f"[SP-ONLINE] {path} 剔除触发 500 的字段: {bad}")
    return [f for f in fields if f not in bad]


def fetch_endpoint(item):
    """拉取单个端点的全量数据，返回 (rows, used_filter)。失败抛异常。"""
    path, payload = item["path"], dict(item["payload"])
    payload.pop("start", None)
    payload["length"] = PAGE_SIZE
    payload["order"] = payload.get("order") or "lastModifiedTime desc"
    # pageType 必须是 allTicket，否则 inbound/transfer 恒 0 行
    ci = payload.get("customInfo")
    ci = dict(ci) if isinstance(ci, dict) else {}
    ci["pageType"] = "allTicket"
    payload["customInfo"] = ci

    fields = [f for f in str(payload.get("field", "")).split(",") if f]
    probe_filter = payload.get("filter") or FILTER_ALL
    fields = _resolve_fields(path, fields, probe_filter)

    # 第一轮：用 url.txt 原始 filter
    used_filter = payload.get("filter") or ""
    rows = _fetch_all_pages(path, fields, used_filter)
    # 第二轮兜底：原 filter 取到 0 行 → 改用状态全集 filter
    if not rows and used_filter != FILTER_ALL:
        logger.info(f"[SP-ONLINE] {item['table']} 原 filter 取到 0 行，回退状态全集 filter")
        used_filter = FILTER_ALL
        rows = _fetch_all_pages(path, fields, used_filter)
    logger.info(f"[SP-ONLINE] {item['table']}: 拉取 {len(rows)} 行")
    return rows, used_filter


def _fetch_all_pages(path, fields, flt):
    """按 start/length 分页拉完，返回原始行列表。"""
    all_rows, start, total = [], 0, None
    while True:
        payload = {"field": ",".join(fields), "start": start, "length": PAGE_SIZE,
                   "order": "lastModifiedTime desc"}
        if flt:
            payload["filter"] = flt
        ok, data = _post(path, payload)
        if not ok or data is None:
            raise RuntimeError(f"{path} 请求失败（start={start}）")
        if total is None:
            total = data.get("total")
        rows = EF.parse_response(data)
        all_rows.extend(rows)
        if len(rows) < PAGE_SIZE or (total and len(all_rows) >= total):
            break
        start += PAGE_SIZE
        if total and start >= total:
            break
    return all_rows


# ---------------- 行规范化 ----------------
def _is_ms_ts(v):
    """判断是否为毫秒级 epoch 时间戳（1e12 ~ 2e12，覆盖 2001-2033）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    return 1_000_000_000_000 < float(v) < 2_000_000_000_000


def _fmt_ts(v):
    try:
        return datetime.fromtimestamp(float(v) / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def normalize_rows(rows, fetched_at):
    """摊平嵌套结构 + 补齐列并集 + 追加时间可读列与同步时间列。

    返回 (headers, list[dict])。
    """
    if not rows:
        return [], []

    flat = []
    for r in rows:
        d = {}
        for k, v in (r or {}).items():
            if isinstance(v, (dict, list)):
                d[k] = json.dumps(v, ensure_ascii=False)
            else:
                d[k] = v
        flat.append(d)

    # 列并集（保持首次出现顺序）
    headers = []
    seen = set()
    for d in flat:
        for k in d.keys():
            if k not in seen:
                seen.add(k)
                headers.append(k)
    # 时间可读列
    ts_cols = [h for h in headers if any(_is_ms_ts(d.get(h)) for d in flat[:50])]
    extra = [f"{c}_str" for c in ts_cols]
    headers = headers + extra + [FETCHED_AT_COL]

    out = []
    for d in flat:
        rec = {}
        for h in headers:
            if h == FETCHED_AT_COL:
                rec[h] = fetched_at
            elif h in d:
                rec[h] = None if d[h] is None else str(d[h])
            elif h.endswith("_str") and h[:-4] in d:
                rec[h] = _fmt_ts(d[h[:-4]])
            else:
                rec[h] = None
        out.append(rec)
    return headers, out


# ---------------- 写库 ----------------
def _q(col):
    return '"' + col.replace('"', '""') + '"'


def save_to_db(table, headers, records, key_col="woId"):
    """写入 app.db（sqlite/PG 双模）。以 key_col 为唯一键 upsert，返回写入行数。"""
    if not headers or not records:
        return 0
    if key_col not in headers:
        raise RuntimeError(f"{table}: 缺少主键列 {key_col}")

    # 主键去重（保留最后一条），并丢弃主键为空的行
    dedup, dropped = {}, 0
    for r in records:
        k = r.get(key_col)
        if k is None or str(k).strip() == "":
            dropped += 1
            continue
        dedup[str(k)] = r
    records = list(dedup.values())
    if dropped:
        logger.warning(f"[SP-ONLINE] {table}: 丢弃 {dropped} 行主键为空的记录")
    if not records:
        return 0

    with get_raw_connection(timeout=60.0) as conn:
        cursor = conn.cursor()
        is_pg = not isinstance(conn, sqlite3.Connection)
        # PG 并发串行化：本流程会 DROP+CREATE 唯一索引，而 _PsycopgRaw 为 autocommit，
        # 两个并发写者会互删对方刚建好的索引，导致 ON CONFLICT 报 42P10。
        lock_key = None
        if is_pg:
            lock_key = int.from_bytes(
                hashlib.sha256(f"u_{table}".encode("utf-8")).digest()[:8], "big"
            ) & 0x7FFFFFFFFFFFFFFF
            cursor.execute("SELECT pg_advisory_lock(?)", (lock_key,))
        try:
            cols_decl = ", ".join(f"{_q(h)} TEXT" for h in headers)
            cursor.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({cols_decl})')

            exist = set(table_columns(conn, table))
            for h in headers:
                if h not in exist:
                    try:
                        cursor.execute(f'ALTER TABLE "{table}" ADD COLUMN {_q(h)} TEXT')
                    except Exception:
                        pass

            # 清历史重复行，再重建唯一索引，upsert 才能真正覆盖
            pk_q = _q(key_col)
            rowid_expr = "ctid" if is_pg else "rowid"
            cursor.execute(
                f'DELETE FROM "{table}" WHERE {rowid_expr} NOT IN ('
                f'SELECT MIN({rowid_expr}) FROM "{table}" GROUP BY {pk_q})'
            )
            cursor.execute(f'DROP INDEX IF EXISTS "u_{table}"')
            cursor.execute(f'CREATE UNIQUE INDEX "u_{table}" ON "{table}" ({pk_q})')

            upsert(conn, table, records, conflict_cols=[key_col])
            conn.commit()
        finally:
            if is_pg and lock_key is not None:
                try:
                    cursor.execute("SELECT pg_advisory_unlock(?)", (lock_key,))
                except Exception:
                    pass

    logger.info(f"[SP-ONLINE] {table}: upsert {len(records)} 行（pk={key_col}）")
    return len(records)


# ---------------- 任务入口 ----------------
def run_sp_online_sync():
    """定时任务入口：拉取 3 个 SP 端点全量并写入 app.db。

    返回 {"success", "tables": {表: 行数}, "rows", "errors", "elapsed_seconds"}
    """
    t0 = time.time()
    result = {"success": False, "tables": {}, "rows": 0, "errors": [],
              "elapsed_seconds": 0, "filters": {}}
    try:
        if not os.path.exists(URL_TXT):
            raise RuntimeError(f"url.txt 不存在: {URL_TXT}")

        items = parse_url_txt(URL_TXT)
        if not items:
            raise RuntimeError(f"url.txt 未解析到任何 SP 接口: {URL_TXT}")
        logger.info(f"[SP-ONLINE] 解析到 {len(items)} 个接口: "
                    f"{[i['table'] for i in items]}")

        EF.login()
        if not EF._session_cookie:
            raise RuntimeError("eFlow 登录失败")

        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for item in items:
            table = item["table"]
            try:
                rows, used_filter = fetch_endpoint(item)
                headers, records = normalize_rows(rows, fetched_at)
                n = save_to_db(table, headers, records)
                result["tables"][table] = n
                result["rows"] += n
                result["filters"][table] = "原始" if used_filter != FILTER_ALL else "状态全集"
            except Exception as e:
                msg = f"{table} 同步失败: {e}"
                logger.error(f"[SP-ONLINE] {msg}", exc_info=True)
                result["errors"].append(msg)

        result["success"] = (not result["errors"]) and result["rows"] > 0
    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"[SP-ONLINE] 任务失败: {e}", exc_info=True)

    result["elapsed_seconds"] = round(time.time() - t0, 2)
    logger.info(
        f"[SP-ONLINE] 完成: rows={result['rows']} tables={result['tables']} "
        f"errors={len(result['errors'])} {result['elapsed_seconds']}s"
    )
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run_sp_online_sync(), ensure_ascii=False, indent=2))

# -*- coding: utf-8 -*-
"""网元管理（RAN Element Management）表格每日同步 → PostgreSQL。

## 数据源（来自同目录 `url.txt` 的浏览器抓包）

`url.txt` 是「Copy all as cURL」的整页抓包，1080 行里只有一条是真正取数的接口，
其余全是 portal 静态资源 / i18n / 图标 / WebSocket，与表格无关：

    GET https://10.100.28.27:28001/api/res/v1/ranmes
        ?queryDn=model:subnetwork
        &operation=operation.rem.rnm.tools
        &includeAttr=id,name,nbiId,nbiIdDn,moc,mimVersion,ipAddress,
                     maintainStatus,version,connectionState,description,
                     displayName,protocol,subType,virtualizationId,subnetwork_nbiId

返回 JSON 数组（2026-11-07 实测 934 行 / 373 KB），每行 15 个字段，涵盖
ITBBU / SDR / MRNC / MEC 四类网元。这就是页面上「网元管理」那张表。

抓包里另有 10 条 `/api/rncmoaction/v1/rnc/<uuid>` 详情请求，返回的是 OMM
连接参数，**包含 `ommFtpPasswd` 明文口令**，且不属于页面表格 —— 本任务不采集、
不落库，避免把上游凭据复制进 PG。

## 认证（为什么不照抄 url.txt 的 Cookie）

`url.txt` 里的 `-b` 是浏览器**会话 Cookie**（`Z-AUTH-CODE-28001` /
`x-dexmesh-user-28001` / `forgerydefense-28001` / `X-Rm-Data-Version-ranoss`），
会随服务端会话过期；写死在代码里，任务跑几天后必然 401。

本服务复用项目既有的 `auth_manager.get_auth(probe=...)`：

* 凭据走 `credential_store` 的 `zte_ume` 组（同一台 10.100.28.27:28001、同一账号），
  与 `ran_ume_service` / `cm_data_export` 等 **u 组**任务共享跨进程会话缓存；
* 探活函数打的就是本任务自己的业务端点（不是登录首页 —— 首页会返回误导性的 200），
  会话失效时 `get_auth` 就地作废缓存并真实重登一次；
* 不调用 `logout()`：会话是共享的，登出会踢掉同组其它任务。

## 落库（PG `app` schema，三张表）

| 表 | 粒度 | 说明 |
| --- | --- | --- |
| `app.ran_element_management` | 一行一个网元 | **当前全量**，按 `ne_id` upsert；上游删除的网元在本轮结束时清掉 |
| `app.ran_element_management_daily` | 一天 + 一个网元 | **每日快照历史**，PK `(snapshot_date, ne_id)`；同一天重跑先删当天分片再写，幂等 |
| `app.ran_element_management_sync_log` | 一轮一次 | 成功/失败都留痕，含行数、耗时、会话来源，便于巡检 |

三张表的 DML 在**同一个显式事务**里（`BEGIN` / `COMMIT`，因为
`database._PsycopgRaw` 是 autocommit 模式），任一步失败整体回滚，
不会出现「历史表有、当前表没有」的半截状态。

## 可调环境变量

`RAN_EM_HOST` / `RAN_EM_PORT` / `RAN_EM_MIN_ROWS`（低于此行数视为异常，拒绝落库，
默认 100）/ `RAN_EM_CONNECT_TIMEOUT` / `RAN_EM_READ_TIMEOUT` / `RAN_EM_CHUNK`。
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone

import requests

logger = logging.getLogger("ran_element_management_service")

try:  # 关闭自签名证书告警（上游是内网 HTTPS 自签证书，对应抓包的 --insecure）
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:  # noqa: BLE001
    pass

# ---------------------------------------------------------------- 配置
HOST = os.environ.get("RAN_EM_HOST", "10.100.28.27")
PORT = int(os.environ.get("RAN_EM_PORT", "28001"))
CONNECT_TIMEOUT = float(os.environ.get("RAN_EM_CONNECT_TIMEOUT", "15"))
READ_TIMEOUT = float(os.environ.get("RAN_EM_READ_TIMEOUT", "90"))
# 934 行是实测基线。低于阈值说明上游返回了空表/分页残片，宁可任务失败也不要
# 把「看起来正常的空表」写进当前表 —— 那会静默抹掉 934 个网元。
MIN_EXPECTED_ROWS = int(os.environ.get("RAN_EM_MIN_ROWS", "100"))
CHUNK = max(1, int(os.environ.get("RAN_EM_CHUNK", "200")))

INCLUDE_ATTR = (
    "id,name,nbiId,nbiIdDn,moc,mimVersion,ipAddress,maintainStatus,version,"
    "connectionState,description,displayName,protocol,subType,virtualizationId,"
    "subnetwork_nbiId"
)
# 保持抓包里的字面写法（`:` / `,` 不编码）：上游对编码后的逗号实测也可解析，
# 但既然抓包能直接 200，就不引入不必要的差异。
DATA_PATH = (
    "/api/res/v1/ranmes?queryDn=model:subnetwork"
    "&operation=operation.rem.rnm.tools"
    f"&includeAttr={INCLUDE_ATTR}"
)
DATA_URL = f"https://{HOST}:{PORT}{DATA_PATH}"
REFERER = f"https://{HOST}:{PORT}/iui/ranrnmiui/"

CURRENT_TABLE = "app.ran_element_management"
DAILY_TABLE = "app.ran_element_management_daily"
LOG_TABLE = "app.ran_element_management_sync_log"

# (PG 列名, 上游 JSON key, 转换器)
FIELDS = (
    ("ne_id", "id", "_s"),
    ("nbi_id", "nbiId", "_s"),
    ("nbi_id_dn", "nbiIdDn", "_join"),
    ("name", "name", "_s"),
    ("display_name", "displayName", "_s"),
    ("moc", "moc", "_s"),
    ("sub_type", "subType", "_s"),
    ("mim_version", "mimVersion", "_s"),
    ("version", "version", "_s"),
    ("ip_address", "ipAddress", "_s"),
    ("protocol", "protocol", "_s"),
    ("maintain_status", "maintainStatus", "_s"),
    ("connection_state", "connectionState", "_i"),
    ("virtualization_id", "virtualizationId", "_i"),
    ("description", "description", "_s"),
)
CURRENT_COLS = [c for c, _, _ in FIELDS] + [
    "snapshot_date", "fetched_at", "first_seen_at", "raw_json",
]
DAILY_COLS = ["snapshot_date"] + [c for c, _, _ in FIELDS] + [
    "fetched_at", "raw_json",
]

_COL_DECL = """
    nbi_id              TEXT,
    nbi_id_dn           TEXT,
    name                TEXT,
    display_name        TEXT,
    moc                 TEXT,
    sub_type            TEXT,
    mim_version         TEXT,
    version             TEXT,
    ip_address          TEXT,
    protocol            TEXT,
    maintain_status     TEXT,
    connection_state    INTEGER,
    virtualization_id   INTEGER,
    description         TEXT,
"""

DDL = f"""
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS {CURRENT_TABLE} (
    ne_id               TEXT PRIMARY KEY,
{_COL_DECL}
    snapshot_date       DATE NOT NULL,
    fetched_at          TIMESTAMPTZ NOT NULL,
    first_seen_at       TIMESTAMPTZ NOT NULL,
    raw_json            JSONB
);
CREATE INDEX IF NOT EXISTS ix_ran_em_current_moc
    ON {CURRENT_TABLE} (moc);
CREATE INDEX IF NOT EXISTS ix_ran_em_current_subtype
    ON {CURRENT_TABLE} (sub_type, connection_state);
CREATE INDEX IF NOT EXISTS ix_ran_em_current_ip
    ON {CURRENT_TABLE} (ip_address);

CREATE TABLE IF NOT EXISTS {DAILY_TABLE} (
    snapshot_date       DATE NOT NULL,
    ne_id               TEXT NOT NULL,
{_COL_DECL}
    fetched_at          TIMESTAMPTZ NOT NULL,
    raw_json            JSONB,
    PRIMARY KEY (snapshot_date, ne_id)
);
CREATE INDEX IF NOT EXISTS ix_ran_em_daily_ne
    ON {DAILY_TABLE} (ne_id);

CREATE TABLE IF NOT EXISTS {LOG_TABLE} (
    id                  BIGSERIAL PRIMARY KEY,
    snapshot_date       DATE NOT NULL,
    fetched_at          TIMESTAMPTZ NOT NULL,
    row_count           INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL,
    message             TEXT,
    duration_ms         INTEGER,
    auth_source         TEXT
);
"""


class AuthExpired(RuntimeError):
    """业务端点返回 401/403：会话在探活之后、取数之前失效。"""


# ---------------------------------------------------------------- 工具
def _s(v):
    """None 保持 None，其余转 str（上游字段类型不稳定时统一成文本）。"""
    return None if v is None else str(v)


def _i(v):
    """整数列：'1' / 1 / None / 'None' 都安全落成 int 或 NULL。"""
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _join(v):
    """nbiIdDn 上游是 list（934/934 行），拼成分号分隔文本，完整值仍在 raw_json。"""
    if isinstance(v, (list, tuple)):
        return ";".join(str(x) for x in v)
    return _s(v)


_CONVERTERS = {"_s": _s, "_i": _i, "_join": _join}


def _normalize(row: dict, snapshot_date: date, fetched_at: datetime) -> dict:
    out = {col: _CONVERTERS[conv](row.get(key)) for col, key, conv in FIELDS}
    out["snapshot_date"] = snapshot_date
    out["fetched_at"] = fetched_at
    # 当前表首次见到该网元的时间；upsert 时保留旧值（见 ON CONFLICT）
    out["first_seen_at"] = fetched_at
    out["raw_json"] = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
    return out


def _headers(cookie: str, forgery_token: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
        ),
        "Referer": REFERER,
        "X-Requested-With": "XMLHttpRequest",
        "language-option": "en-US",
        "timeZoneInfo": "Default,Atlantic/Reykjavik,",
        "Cookie": cookie,
        "forgerydefense": forgery_token,
    }


def _session() -> requests.Session:
    """内网直连：绕开系统代理（trust_env=False）+ 忽略自签证书（verify=False）。"""
    s = requests.Session()
    s.trust_env = False
    s.verify = False
    return s


_SESSION = _session()


def _probe_ran_em_session(cookie: str, forgery_token: str) -> bool:
    """供 `auth_manager.get_auth(probe=...)` 探活。

    必须探**本任务自己的业务端点**：探登录首页会拿到 200 假绿（见
    auth_manager 顶部约束 1）。用 stream=True 只取状态行就关闭，避免探活
    白白下载 373 KB 表格。401/403 = 会话死，其余（含 400/500）= 会话活着。
    """
    try:
        r = _SESSION.get(
            DATA_URL, headers=_headers(cookie, forgery_token),
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), stream=True,
        )
        code = r.status_code
        r.close()
        alive = code not in (401, 403)
        if not alive:
            logger.info("[RAN-EM] 共享会话已失效（探活 /api/res/v1/ranmes -> %s）", code)
        return alive
    except Exception as e:  # noqa: BLE001
        logger.warning("[RAN-EM] 会话探活异常（%s: %s），按不可用处理",
                       type(e).__name__, e)
        return False


def _runtime_credentials():
    """凭据：环境变量 > credential_store(`zte_ume`) > 模块默认值。"""
    from backend.services.credential_store import get_credential
    return get_credential("zte_ume",
                          os.environ.get("RAN_EM_USER", "NOC"),
                          os.environ.get("RAN_EM_PASS", ""),
                          env_user="RAN_EM_USER", env_secret="RAN_EM_PASS")


def _acquire_auth(force_refresh: bool = False):
    """取一份「已确认可用」的共享会话，返回 (cookie, forgery_token, 来源)。"""
    from backend.services.auth_manager import get_auth
    user, pwd = _runtime_credentials()
    if not user or not pwd:
        raise RuntimeError(
            "zte_ume 凭据为空：请在「系统设置 → 凭据」维护 RAN UME 账号口令"
        )
    r = get_auth(HOST, PORT, user, pwd,
                 probe=_probe_ran_em_session, force_refresh=force_refresh)
    source = "缓存" if r["from_cache"] else (
        "重登（探活失败）" if r.get("from_relogin") else "重登")
    logger.info("[RAN-EM] 鉴权成功（来源: %s）", source)
    return r["cookie"], r["forgery_token"], source


def _fetch_rows(cookie: str, forgery_token: str) -> list:
    """调取数接口，返回原始 JSON 数组。"""
    r = _SESSION.get(
        DATA_URL, headers=_headers(cookie, forgery_token),
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
    )
    if r.status_code in (401, 403):
        raise AuthExpired(f"/api/res/v1/ranmes 返回 HTTP {r.status_code}")
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError as e:
        raise RuntimeError(
            f"网元管理接口返回的不是 JSON（HTTP {r.status_code}，"
            f"{len(r.content)} 字节，前 120 字符：{r.text[:120]!r}）"
        ) from e
    if not isinstance(data, list):
        raise RuntimeError(
            f"网元管理接口返回结构异常：期望 list，实际 {type(data).__name__}"
        )
    return data


# ---------------------------------------------------------------- 落库
def _ensure_schema():
    """幂等建表/建索引（DDL 走 autocommit，不进业务写事务）。"""
    from backend.database import DB_MODE, get_raw_connection
    if DB_MODE != "pg":
        raise RuntimeError(
            f"网元管理表要求写入 PostgreSQL，但当前 MY_APP_DB_MODE={DB_MODE!r}；"
            "请检查 backend/.env 的 MY_APP_DB_MODE / DATABASE_URL"
        )
    with get_raw_connection() as conn:
        conn.executescript(DDL)


def _bulk_insert(cur, table: str, columns: list, records: list, tail: str = ""):
    """分批多行 INSERT。`?` 占位符由 database 的兼容层转成 psycopg2 的 `%s`。"""
    if not records:
        return
    ph = "(" + ",".join("?" for _ in columns) + ")"
    head = f"INSERT INTO {table} ({','.join(columns)}) VALUES "
    for start in range(0, len(records), CHUNK):
        part = records[start:start + CHUNK]
        sql = head + ",".join(ph for _ in part) + " " + tail
        params = [rec[c] for rec in part for c in columns]
        cur.execute(sql, params)


_UPSERT_CURRENT = """
ON CONFLICT (ne_id) DO UPDATE SET
    nbi_id             = EXCLUDED.nbi_id,
    nbi_id_dn          = EXCLUDED.nbi_id_dn,
    name               = EXCLUDED.name,
    display_name       = EXCLUDED.display_name,
    moc                = EXCLUDED.moc,
    sub_type           = EXCLUDED.sub_type,
    mim_version        = EXCLUDED.mim_version,
    version            = EXCLUDED.version,
    ip_address         = EXCLUDED.ip_address,
    protocol           = EXCLUDED.protocol,
    maintain_status    = EXCLUDED.maintain_status,
    connection_state   = EXCLUDED.connection_state,
    virtualization_id  = EXCLUDED.virtualization_id,
    description        = EXCLUDED.description,
    snapshot_date      = EXCLUDED.snapshot_date,
    fetched_at         = EXCLUDED.fetched_at,
    first_seen_at      = app.ran_element_management.first_seen_at,
    raw_json           = EXCLUDED.raw_json
"""


def _persist(records: list, snapshot_date: date, fetched_at: datetime) -> dict:
    """把一轮快照写进当前表 + 每日表，整体一个事务。"""
    from backend.database import get_raw_connection
    with get_raw_connection() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        try:
            # 当日分片先删后写 → 同一天重跑幂等，不会出现重复行
            cur.execute(
                f"DELETE FROM {DAILY_TABLE} WHERE snapshot_date = ?",
                (snapshot_date,),
            )
            _bulk_insert(cur, DAILY_TABLE, DAILY_COLS, records)
            _bulk_insert(cur, CURRENT_TABLE, CURRENT_COLS, records,
                         tail=_UPSERT_CURRENT)
            # 上游已删除的网元：本轮没被 upsert 的行 fetched_at 还是旧值，清掉
            cur.execute(
                f"DELETE FROM {CURRENT_TABLE} WHERE fetched_at <> ?",
                (fetched_at,),
            )
            cur.execute("COMMIT")
        except Exception:
            try:
                cur.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
            raise
        cur.execute(f"SELECT count(*) AS n FROM {CURRENT_TABLE}")
        current_rows = cur.fetchone()["n"]
        cur.execute(
            f"SELECT count(*) AS n FROM {DAILY_TABLE} WHERE snapshot_date = ?",
            (snapshot_date,),
        )
        daily_rows = cur.fetchone()["n"]
    return {"current": int(current_rows), "daily_today": int(daily_rows)}


def _write_sync_log(snapshot_date: date, fetched_at: datetime, row_count: int,
                    status: str, message: str, duration_ms: int,
                    auth_source: str = ""):
    """同步结果留痕。失败也写；此处异常不能掩盖原始失败原因。"""
    try:
        from backend.database import get_raw_connection
        with get_raw_connection() as conn:
            conn.execute(
                f"INSERT INTO {LOG_TABLE} "
                "(snapshot_date, fetched_at, row_count, status, message, "
                " duration_ms, auth_source) VALUES (?,?,?,?,?,?,?)",
                (snapshot_date, fetched_at, row_count, status,
                 (message or "")[:2000], duration_ms, auth_source),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("[RAN-EM] 写同步日志失败（不影响主流程判定）: %s", e)


# ---------------------------------------------------------------- 任务入口
def run_ran_element_management_sync() -> dict:
    """任务入口：取网元管理表格 → 落 PG。由 TASK_SPECS 懒加载调用。

    返回紧凑摘要（不要返回 934 行明细，否则会被塞进 task_execution_log）。
    """
    started = time.monotonic()
    snapshot_date = date.today()
    fetched_at = datetime.now(timezone.utc)
    rows: list = []
    auth_source = ""
    logger.info("[RAN-EM] 开始同步网元管理表 → PG（%s:%s%s）", HOST, PORT, DATA_PATH[:60])

    # 先建表：即便后面取数/鉴权失败，sync_log 也有地方写
    _ensure_schema()

    try:
        cookie, token, auth_source = _acquire_auth()
        try:
            rows = _fetch_rows(cookie, token)
        except AuthExpired:
            logger.warning("[RAN-EM] 取数遇到 401/403，强制重登后重试一次")
            cookie, token, auth_source = _acquire_auth(force_refresh=True)
            rows = _fetch_rows(cookie, token)

        if len(rows) < MIN_EXPECTED_ROWS:
            raise RuntimeError(
                f"上游只返回 {len(rows)} 行，低于安全阈值 {MIN_EXPECTED_ROWS} "
                "（RAN_EM_MIN_ROWS）；拒绝落库，避免把残片当成全量表覆盖当前数据"
            )

        records = [_normalize(r, snapshot_date, fetched_at) for r in rows
                   if isinstance(r, dict)]
        if len(records) != len(rows):
            raise RuntimeError(
                f"有 {len(rows) - len(records)} 行不是 JSON 对象，拒绝落库"
            )
        missing_id = sum(1 for r in records if not r["ne_id"])
        if missing_id:
            raise RuntimeError(f"有 {missing_id} 行缺少 id（主键），拒绝落库")

        counts = _persist(records, snapshot_date, fetched_at)
        duration_ms = int((time.monotonic() - started) * 1000)
        message = (f"rows={len(records)} current={counts['current']} "
                   f"daily_today={counts['daily_today']}")
        _write_sync_log(snapshot_date, fetched_at, len(records), "success",
                        message, duration_ms, auth_source)
        result = {
            "success": True,
            "rows": len(records),
            "snapshot_date": snapshot_date.isoformat(),
            "tables": [CURRENT_TABLE, DAILY_TABLE, LOG_TABLE],
            **counts,
            "auth_source": auth_source,
            "duration_ms": duration_ms,
        }
        logger.info("[RAN-EM] 同步完成: %s", message)
        return result
    except Exception as e:  # noqa: BLE001
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.exception("[RAN-EM] 同步失败: %s", e)
        _write_sync_log(snapshot_date, fetched_at, len(rows), "failed",
                        f"{type(e).__name__}: {e}", duration_ms, auth_source)
        raise


# 便于本地单跑：python -m backend.services.RANElementManagement.ran_element_management_service
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run_ran_element_management_sync(),
                     ensure_ascii=False, indent=2))

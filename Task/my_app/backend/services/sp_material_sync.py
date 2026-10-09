# -*- coding: utf-8 -*-
"""eFlow SP 物料主数据（eflow-sp-material）同步 —— 从 eFlow SP 接口拉全量物料，写入 app.db。

数据来源：`https://{host}:{port}/api/eflow-sp/v1/eflow-sp-material/base/list`
复用 `eflow_api_client` 的登录会话与裸 socket HTTPS 通道（同源 eFlow 10.100.20.8:28001）。

产出表（Table Browser 可见）：`sp_material`

★ 服务端实测结论（改本模块前务必读，都是踩过的坑）：
1. **排序必须用 `woId asc`，不能用 `lastModifiedTime desc`**（2026-09-09 实测）：
   抓包里的 `order: lastModifiedTime desc` 排序键不唯一，分页结果不稳定 —— 实测
   start=200 与 start=400 两页重叠 150 行，922 行里 materialNo 只有 770 个唯一，
   重复行的同时意味着丢了 152 行。`woId` 是全表唯一列（922 行 922 个唯一值），
   按它升序分页可拿到完整且不重复的 922 行。
2. **`field` 里的列名会被服务端校验**：写错列名（如 `id`）直接 500
   （`{"errorCode":1,...}`）。抓包的 34 列可用；追加 `creator,createTime` 后
   返回列从 37 → 39（服务端对空值列按行省略，故列集合必须取所有行的并集）。
3. **单个字段请求必 500**：`field` 只放 1 个列时无论列名对错都 500，属服务端行为，
   不要据此判定某列"坏掉了"（sp_online_sync 的二分剔字段逻辑对本接口无意义）。
4. `filter`（status Active/Inactive）与 `customInfo` 都非必需：不带它们同样返回
   total=922；本模块按抓包原样保留，保证与浏览器可见数据一致。
5. 当前全量 Active=922、Inactive=0；`length` 可放大到 1000/2000 一次拉完，
   本模块仍按页拉取（PAGE_SIZE=500）以避免依赖服务端上限。

6. **表 = 上游快照，全量重建（2026-10-09 起）**：本模块拉的是**全量**物料主数据，
   但旧实现只 upsert、从不删除 —— 上游停用/删除的物料会**永久残留**（与 sp_online
   同型：那边曾因此积 37 条僵尸行）。现改为：本轮**完整**拉取时，upsert 后删除表中
   不在本轮 `materialNo` 集合里的行（`save_to_db(reconcile_keys=...)`）。
   **安全阀**：仅当 `fetch_all()` 的 `complete` 为真（正常翻完、未达 MAX_PAGES 上限、
   非 0 行）才删除；不完整时只 upsert，宁可留下陈旧行也不误删真实物料。
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
from backend.services.reconcile_helper import delete_not_in_keys

logger = logging.getLogger("sp_material")

# ---------------- 配置 ----------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]

API_PATH = "/api/eflow-sp/v1/eflow-sp-material/base/list"
TABLE = os.environ.get("SP_MATERIAL_TABLE", "sp_material")
# eFlow SP 前端页面路径（Referer 必须同源，否则鉴权头校验失败）
REFERER = "https://{host}:{port}/iui/eflow-sp/dist/index.html"

# 抓包字段全集 + creator/createTime（实测追加这两个可多返回 2 列）
FIELD = (
    "opName,woId,materialNo,materialName,productcode,description,materialManufacture,"
    "materialType,materialClass,accumulable,unit,materialParam,specification,manageByCode,"
    "materialManageType,status,domain,subDomain,equipmentName,importance,hardwareSupport,"
    "lodsp,eos,eop,price,eccnStatus,eccn,mtbfStatus,repairable,returnable,materialSeverity,"
    "substituteMaterial,lifeCycle,lastModifiedTime,creator,createTime"
)
FILTER = '((status eq "Inactive") or (status eq "Active"))'
# ★ 唯一稳定的排序键，见模块头部第 1 条
ORDER = "woId asc"
PAGE_SIZE = int(os.environ.get("SP_MATERIAL_PAGE_SIZE", "500"))
MAX_PAGES = int(os.environ.get("SP_MATERIAL_MAX_PAGES", "200"))
# 业务主键：物料编码（全表唯一）。同一 materialNo 重复时保留 woId 最大的一行。
KEY_COL = "materialNo"
FETCHED_AT_COL = "_fetched_at"

# ============================================================
# 外部化配置（Settings →「任务配置」维护的 sp_material_config.json）
#   优先级：环境变量 > 配置文件 > 内置默认；eFlow 主机/凭据来自「凭据管理 → eflow_api」。
# ============================================================
try:
    from backend.services.task_config_files import apply_config_overrides
except ImportError:
    from task_config_files import apply_config_overrides  # type: ignore

apply_config_overrides(
    globals(),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "sp_material_config.json"),
    {
        "api_path": ("API_PATH", str, None),
        "table": ("TABLE", str, "SP_MATERIAL_TABLE"),
        "page_size": ("PAGE_SIZE", lambda v: max(1, int(v)), "SP_MATERIAL_PAGE_SIZE"),
        "max_pages": ("MAX_PAGES", lambda v: max(1, int(v)), "SP_MATERIAL_MAX_PAGES"),
    },
    log_name="sp_material",
)


# ---------------- 拉取 ----------------
def _post(payload):
    """发一次 POST，返回 (ok, data_dict_or_None)。"""
    ref = REFERER.format(host=EF.HOST, port=EF.PORT)
    status, _hdrs, _raw, body = EF._http_request(
        "POST", API_PATH, headers_extra=EF._headers_extra(ref), body=json.dumps(payload)
    )
    if "500" in status:
        logger.warning(f"[SP-MAT] 服务端 500: {body[:200]!r}")
        return False, None
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return False, None
    return True, data


def fetch_all():
    """按 woId asc 分页拉全量，返回 (rows, total, complete)。

    ``complete``（2026-10-09 新增）：本轮是否**完整**拉取到全量 —— 正常翻完为 True；
    因到达 ``MAX_PAGES`` 上限而中断（``else`` 分支）或一行都没拿到为 False。
    这只是 ``run_sp_material_sync`` 全量删除（reconcile）的开关：不完整时若据此
    删表，会把上游仍有、只是本轮没翻到的物料误删。
    """
    all_rows, start, total = [], 0, None
    complete = True
    for _ in range(MAX_PAGES):
        payload = {"field": FIELD, "start": start, "length": PAGE_SIZE,
                   "order": ORDER, "filter": FILTER,
                   "customInfo": {"pageType": "allTicket"}}
        ok, data = _post(payload)
        if not ok or data is None:
            raise RuntimeError(f"eflow-sp-material 请求失败（start={start}）")
        if total is None:
            total = data.get("total")
        rows = EF.parse_response(data)
        all_rows.extend(rows)
        if len(rows) < PAGE_SIZE:
            break
        if total and len(all_rows) >= total:
            break
        start += PAGE_SIZE
        if total and start >= total:
            break
    else:
        # 翻页用尽仍未见结尾：本轮结果可能只是上游的一部分，禁止据此删表
        complete = False
        logger.warning(f"[SP-MAT] 达到 MAX_PAGES={MAX_PAGES} 上限，停止翻页")
    if not all_rows:
        complete = False
    return all_rows, total, complete


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

    服务端对空值列按行省略，故列集合取所有行的并集。返回 (headers, list[dict])。
    """
    if not rows:
        return [], []

    flat = []
    for r in rows:
        d = {}
        for k, v in (r or {}).items():
            d[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
        flat.append(d)

    headers, seen = [], set()
    for d in flat:
        for k in d.keys():
            if k not in seen:
                seen.add(k)
                headers.append(k)
    ts_cols = [h for h in headers if any(_is_ms_ts(d.get(h)) for d in flat[:50])]
    headers = headers + [f"{c}_str" for c in ts_cols] + [FETCHED_AT_COL]

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


def _woid_sort_key(v):
    """woId 排序键：能转数字就转，否则退化为字符串比较。"""
    try:
        return (1, float(v))
    except (TypeError, ValueError):
        return (0, str(v or ""))


def save_to_db(headers, records, reconcile_keys=None):
    """以 materialNo 为唯一键 upsert 写入，返回 (写入行数, 丢弃行数, 删除行数)。

    全量重建（2026-10-09 新增）
    --------------------------
    本任务 ``fetch_all()`` 拉的是**全量物料主数据**，故表语义应为「上游当前快照」。
    旧实现只 upsert、从不删除，上游停用/删除的物料会永久残留（与 sp_online 同型）。

    传入 ``reconcile_keys``（本轮成功拉取到的全部 ``materialNo``）即启用重建：upsert
    后在同一事务内删除表中不在该集合里的行。传 ``None``（默认）保持纯 upsert。
    ⚠️ 调用方**必须**只在「本轮拉取完整」（``fetch_all`` 的 ``complete``）时才传，
    否则上游返回半截数据会误删真实物料。
    """
    if not headers or not records:
        return 0, 0, 0
    if KEY_COL not in headers:
        raise RuntimeError(f"{TABLE}: 缺少主键列 {KEY_COL}")

    dedup, dropped = {}, 0
    for r in records:
        k = r.get(KEY_COL)
        if k is None or str(k).strip() == "":
            dropped += 1
            continue
        k = str(k)
        old = dedup.get(k)
        # 重复 materialNo 时保留 woId 最大的一行（等价于保留最新记录）
        if old is None or _woid_sort_key(r.get("woId")) > _woid_sort_key(old.get("woId")):
            dedup[k] = r
    records = list(dedup.values())
    if dropped:
        logger.warning(f"[SP-MAT] 丢弃 {dropped} 行主键 {KEY_COL} 为空的记录")
    if not records:
        return 0, dropped, 0

    deleted = 0
    with get_raw_connection(timeout=60.0) as conn:
        cursor = conn.cursor()
        is_pg = not isinstance(conn, sqlite3.Connection)
        # PG 并发串行化：本流程会 DROP+CREATE 唯一索引，而 _PsycopgRaw 为 autocommit，
        # 两个并发写者会互删对方刚建好的索引，导致 ON CONFLICT 报 42P10。
        lock_key = None
        if is_pg:
            lock_key = int.from_bytes(
                hashlib.sha256(f"u_{TABLE}".encode("utf-8")).digest()[:8], "big"
            ) & 0x7FFFFFFFFFFFFFFF
            cursor.execute("SELECT pg_advisory_lock(?)", (lock_key,))
        try:
            cols_decl = ", ".join(f"{_q(h)} TEXT" for h in headers)
            cursor.execute(f'CREATE TABLE IF NOT EXISTS "{TABLE}" ({cols_decl})')

            exist = set(table_columns(conn, TABLE))
            for h in headers:
                if h not in exist:
                    try:
                        cursor.execute(f'ALTER TABLE "{TABLE}" ADD COLUMN {_q(h)} TEXT')
                    except Exception:
                        pass

            # 建唯一索引前必须先清掉历史重复行，否则 CREATE UNIQUE INDEX 直接报错
            pk_q = _q(KEY_COL)
            cursor.execute(
                f'SELECT {pk_q} FROM "{TABLE}" GROUP BY {pk_q} HAVING count(*) > 1 LIMIT 1'
            )
            dup_exists = cursor.fetchone() is not None
            if dup_exists:
                if is_pg:
                    # PG 上 ctid NOT IN (SELECT MIN(ctid) ... GROUP BY ...) 是嵌套循环，
                    # 大表会卡死；改用窗口函数一次排序回删。
                    cursor.execute(
                        f'DELETE FROM "{TABLE}" WHERE ctid IN ('
                        f'SELECT ctid FROM ('
                        f'  SELECT ctid, row_number() OVER (PARTITION BY {pk_q} '
                        f'  ORDER BY ctid) rn FROM "{TABLE}"'
                        f') t WHERE t.rn > 1)'
                    )
                else:
                    cursor.execute(
                        f'DELETE FROM "{TABLE}" WHERE rowid NOT IN ('
                        f'SELECT MIN(rowid) FROM "{TABLE}" GROUP BY {pk_q})'
                    )
                logger.warning(f"[SP-MAT] 清理了 {TABLE} 中 {KEY_COL} 的历史重复行")
            cursor.execute(f'DROP INDEX IF EXISTS "u_{TABLE}"')
            cursor.execute(f'CREATE UNIQUE INDEX "u_{TABLE}" ON "{TABLE}" ({pk_q})')

            upsert(conn, TABLE, records, conflict_cols=[KEY_COL])

            # 全量重建：删除不在本轮结果里的物料（表 = 上游快照）。
            if reconcile_keys is not None:
                deleted = delete_not_in_keys(cursor, TABLE, KEY_COL,
                                             reconcile_keys, is_pg=is_pg)
                logger.info(
                    f"[SP-MAT] {TABLE}: 全量重建删除 {deleted} 行"
                    f"（保留 {len(set(map(str, reconcile_keys)))} 个本轮 {KEY_COL}）"
                )
            conn.commit()
        finally:
            if is_pg and lock_key is not None:
                try:
                    cursor.execute("SELECT pg_advisory_unlock(?)", (lock_key,))
                except Exception:
                    pass

    logger.info(f"[SP-MAT] upsert {len(records)} 行（pk={KEY_COL}）")
    return len(records), dropped, deleted


# ---------------- 任务入口 ----------------
def run_sp_material_sync():
    """定时任务入口：拉取 eFlow SP 物料主数据全量并写入 app.db。

    表语义 = 上游当前快照：本轮**完整**拉取时全量重建（删除上游已消失的物料），
    拉取不完整（达 MAX_PAGES / 0 行）时只 upsert、不删除。

    返回 {"success", "rows", "total", "unique_keys", "dropped", "deleted",
          "table", "elapsed_seconds", "errors"}
    """
    t0 = time.time()
    result = {"success": False, "rows": 0, "total": 0, "unique_keys": 0,
              "dropped": 0, "deleted": 0, "table": TABLE,
              "elapsed_seconds": 0, "errors": []}
    try:
        # ensure_login()：复用本进程会话或跨进程磁盘缓存，避免与其它 eFlow
        # 任务重复申请 token（2026-10-04 修正登录风暴）。
        EF.ensure_login()
        if not EF._session_cookie:
            raise RuntimeError("eFlow 登录失败")

        rows, total, complete = fetch_all()
        result["total"] = total or 0
        if not rows:
            raise RuntimeError(f"接口返回 0 行（total={total}）")

        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        headers, records = normalize_rows(rows, fetched_at)

        # 重复主键自检：正常应 0（排序稳定时接口全量唯一）
        keys = [r.get(KEY_COL) for r in records]
        result["unique_keys"] = len(set(k for k in keys if k))
        if result["unique_keys"] != len(keys):
            result["errors"].append(
                f"接口返回存在重复 {KEY_COL}: {len(keys)} 行 / {result['unique_keys']} 个唯一值"
            )

        # 只有完整拉取才做全量删除（表 = 上游快照）；否则只 upsert，避免
        # 上游返回半截数据时把真实物料误删。
        reconcile_keys = None
        if complete:
            reconcile_keys = {k for k in keys if k}
        else:
            logger.warning(
                f"[SP-MAT] 本轮拉取不完整（{len(rows)} 行，total={total}），"
                f"跳过全量删除以策安全"
            )

        n, dropped, deleted = save_to_db(headers, records,
                                         reconcile_keys=reconcile_keys)
        result["rows"] = n
        result["dropped"] = dropped
        result["deleted"] = deleted
        # 拉到的行数与唯一主键数不一致时视为异常，但数据已落库，仍标记成功并保留 errors
        result["success"] = n > 0 and not result["errors"]
    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"[SP-MAT] 任务失败: {e}", exc_info=True)

    result["elapsed_seconds"] = round(time.time() - t0, 2)
    logger.info(
        f"[SP-MAT] 完成: rows={result['rows']} total={result['total']} "
        f"unique={result['unique_keys']} deleted={result['deleted']} "
        f"errors={result['errors']} {result['elapsed_seconds']}s"
    )
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run_sp_material_sync(), ensure_ascii=False, indent=2))

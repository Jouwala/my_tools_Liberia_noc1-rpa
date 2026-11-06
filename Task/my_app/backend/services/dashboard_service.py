# -*- coding: utf-8 -*-
"""原生看板通用数据服务（my-finebi 全部看板 → my_app 原生页）。

=========================== 设计要点 ===========================

一套引擎驱动 17 个看板 / 187 个组件
    看板定义全部来自 backend/services/native_catalog.py（由 _gen_native_catalog.py
    从 my-finebi 的 app.db 自动提取），本模块只负责「按定义取数 + 统一后处理」，
    不再为每个看板写一份代码。新增看板 = 重新生成目录，无需改本文件。

图表类型（5 种）
    line / bar  : 第 1 列为类目轴，其余每列一条序列
    kpi         : 单值卡片（取结果第一行第一列）
    table       : 明细表格（列名 + 行）
    text        : 纯标题栏（无 SQL，已剥离指向 FineBI 的外链）

pivot（FineBI 的「颜色/分区」维度）
    SQL 返回三列 [x, 系列名, 值]，需按第 2 列透视成多序列。

数据源
    默认走远端只读 SQL API（backend/config/remote_host.py，默认 .19:8765）；
    逻辑库名 → db_<name>.sqlite3，映射来自 my-finebi 的 settings.data_sources。
    例外：slug=spare 整页改读**本机 db/app.db**（该库是 my_app 自己 sp_data_sync
    任务写入的镜像源的源头；远端 inventory.db 长期被锁，实测 SELECT 1 也要 42s
    才报 database is locked）。详见 _gen_native_catalog.py 的说明。

    IP RAN 族（ipran_hq / ipran_4region / metro_ring / fw_daily，26 个组件）自
    2026-11-04 起改读**本机 PG 的 ipran_ume schema**：采集本来就跑在本机，
    远端 SQLite 只是给其它 BI 用的副本。开关 NATIVE_BOARD_IPRAN_SOURCE=remote
    可一键回退到远端。详见 IPRAN_SOURCE 处的说明。

    其余三个历史库（db.sqlite3 / db_ps_cs_cn.sqlite3 / fw_db.sqlite，共 93 个组件）
    的采集脚本当年只写远端，本机没留下完整副本（RAN 那个停在 2026-06、PS_CS
    只有 17/40 张表、PG fw 只有 1/2 台设备）。自 2026-11-04 起改读
    **本机镜像库**（data/native_board_mirror/*.sqlite3），由
    native_board_mirror_sync 按 rowid 水位增量同步，看板请求 100% 本地。
    开关 NATIVE_BOARD_MIRROR=0 可一键全部回退到远端。

时间窗口（新增）
    `?start=YYYY-MM-DD&end=YYYY-MM-DD` 可自定义起止日期。
    实现方式：**不改写原 SQL**（187 条 SQL 形态各异，正则改写必然出错），
    而是把原查询整体包成子查询，在「日期列」上过滤：
        SELECT * FROM ( <原 SQL> ) WHERE _d BETWEEN ? AND ?
    其中日期列 _d 由「结果集里第一列是 ISO 日期/时间前缀的列」自动识别。
    这样对原口径零侵入：过滤的是 FineBI 原样产出的结果集。
    识别不到日期列时返回 date_field=""，前端据此禁用时间窗口（而不是静默返回错数）。

Excel 导出（新增）
    `GET /api/native-boards/{slug}/export` 把整页所有组件的数据导成一个 xlsx，
    每个组件一个 sheet（表格类组件独占一 sheet；图表类组件导出其绘图数据），
    并附一个「说明」sheet 记录数据源/时间窗口/取数时间，便于对账。
===============================================================
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.config.remote_host import get_api_base_url
from backend.services.native_catalog import BY_SLUG, CATALOG, DASHBOARDS

logger = logging.getLogger("native_board")

# 取数超时（秒）：单组件远端查询
QUERY_TIMEOUT = 90

# 整页结果 TTL（秒）
#
# 这些看板的源数据是「天粒度更新」的：远端库一天最多变一次，而一次整页取数
# 要 4~6 秒（实测 metro_ring 8 个组件 × 约 1.2s，共 4.4 万行 —— 成本几乎全在
# 行数上：LIMIT 10 只要 28ms，LIMIT 5500 要 1365ms）。
# 因此 TTL 按小时计而不是秒：60 秒的 TTL 意味着用户几乎每次访问都在等冷取数。
# 需要立即看最新数据时走 ?force=1（前端「刷新」按钮），不依赖 TTL。
CACHE_TTL = int(os.environ.get("NATIVE_BOARD_CACHE_TTL", 6 * 3600))

# 失败结果的短 TTL（秒）。整页有组件取数失败时，结果里只有空壳；若按 6 小时
# 缓存，一次远端抖动就会被固化成「秒开但空白」（2026-11-04 历史区间回落时
# 实测踩到）。失败结果只在内存留 60s、不落盘，且后台刷新失败不覆盖已有好缓存。
FAILURE_CACHE_TTL = int(os.environ.get("NATIVE_BOARD_FAILURE_TTL", "60"))

# 磁盘缓存目录：后端被看门狗重启后内存缓存会丢，磁盘缓存让重启后依然秒开
CACHE_DIR = Path(os.environ.get(
    "NATIVE_BOARD_CACHE_DIR",
    Path(__file__).resolve().parents[1] / "data" / "native_board_cache"))

# 内存中最多缓存的整页结果数。整页数据解析后可达数十 MB（metro_ring 4.4 万行），
# 所以这里只留最热的几页，其余命中磁盘（约 30ms，远快于 4.4s 的冷取数）。
MEM_MAX = int(os.environ.get("NATIVE_BOARD_MEM_MAX", 6))

# 后台刷新线程数：SWR 回源用，压低并发以免和用户请求抢远端
REFRESH_WORKERS = 2

# 并发上限：远端 db_writer_api 是单机服务，避免一次性打太多连接
MAX_WORKERS = 6

# 单组件返回行数上限（明细表格用；FineBI 原版也做了截断）
DEFAULT_LIMIT = 5000

# ----------------------------------------------------------------------
# 「全历史大表」的时间条件下推（2026-11-04，如意确认）
#
# metro_ring 的 8 条趋势 SQL 是 FineBI 原口径「无时间过滤 = 全历史」，WHERE
# 只按 ME / Measure Object 过滤；而源表唯一索引首列是 "Begin Time"，条件用不上
# → 195 万行全表扫描 → 单组件超过 QUERY_TIMEOUT(90s)，8 条分两批共 180s，
# 整页只剩 KPI 卡片有值（实测 8/10 failed，页面空白）。
#
# 这里在**取数层**把时间下限下推进 WHERE：不动自动生成的 native_catalog.py
# （文件头明确「请勿手改」），也不改看板定义里的口径字符串，让 SQLite 走
# "Begin Time" 索引范围扫描。实测 8/8 成功、总 41s、4949 行。
#
# 无窗口时默认回看 PUSH_DOWN_DAYS 天；用户显式选了区间时下推用户区间，并跳过
# _apply_window 的二次子查询包装（否则内层的默认窗口会把历史区间裁空）。
#
# date('now', ...) 是 SQLite 方言；切到本机 PG 时由 _to_pg_sql() 换成
# to_char(current_date - interval 'N days', 'YYYY-MM-DD')，两种库共用同一份目录。
#
# 2026-11-05（如意定「IP RAN 页面看 31 天」）两点扩量：
#   ① 白名单从 Metro_ring 一张扩到 IP RAN 全部 6 张 15 分钟表 —— 原来只有
#      metro_ring 受下推保护，另外 3 个看板（ipran_hq / ipran_4region）走的是
#      「无窗口 = 全历史」，取回的是 FineBI 原口径的全部累积行（单页 1.9 万行 /
#      1.0MB），页面默认既慢又和 metro_ring 不同口径。
#   ② 默认回看 7 天 → 31 天，四个页面的默认窗口统一成「近一个月」。
#      前提是本机 PG 的 ipran_ume 得真有 31 天：当时实测近 31 天只有 10 天有数
#      （镜像只追头部水位，中间断的日子不会自己长回来），已用
#      `backend/scripts/backfill_ipran_pg.py --since 2026-10-05` 补齐；
#      以后再断日子，用同一条命令补，别改这里。
# ----------------------------------------------------------------------
PUSH_DOWN_TABLES = (
    "Metro_ring_me_15mins",
    "Gbarnga_Buchanna_RIA_Kakata_me_15mins",
    "Banjor_ELWA_me_15mins",
    "IPCORE_HQ_ODC_bnctp_15mins",
    "OLT_bnctp_15mins",
    "HQ_M6K_FW_bnctp_15mins",
)
PUSH_DOWN_DAYS = int(os.environ.get("NATIVE_BOARD_PUSHDOWN_DAYS", "31"))

# ----------------------------------------------------------------------
# IP RAN 族 → 本机 PG（2026-11-04，如意确认）
#
# 采集任务 ipran_kpi_sync 跑在本机，远端 .19:8765 的 SQLite 只是给其它 BI 用的
# 副本。但这 4 个看板（ipran_hq / ipran_4region / metro_ring / fw_daily，26 个
# 组件）原先全在读远端，且 metro_ring 的 8 条「全历史」SQL 在远端经常 90s 超时。
# 本机 PG 的 ipran_ume schema 是同一份数据，实测等价聚合 3.2s（下推后 0.1s）。
#
# ⚠ 前置修复：本机 PG 原本只在「远端写失败兜底」时被动更新，已落后 15.5 小时。
#   ipran_ume_kpi_service.WRITE_LOCAL_MIRROR 现已改为远端成功后主动镜像，
#   并用 backfill_ipran_pg.py 补齐历史缺口。切换前务必确认 PG 水位已追平。
#
# 回退：NATIVE_BOARD_IPRAN_SOURCE=remote 即恢复全部读远端（无需改代码/重启目录）。
#
# ⚠ 历史空洞：PG 是「兜底快照」拼出来的，实测 Metro_ring 按月只有 2026-08 /
#   10 / 11，**整月缺 2026-09**（远端同期 82 万行）。默认近 7 天不受影响；
#   用户显式选到 PG 没有的区间时，NATIVE_BOARD_IPRAN_FALLBACK=1（默认）会
#   逐表探测后精确回落到远端权威库，避免静默出空白。置 0 则严格只读本机。
# ----------------------------------------------------------------------
IPRAN_SOURCE = os.environ.get("NATIVE_BOARD_IPRAN_SOURCE", "pg").strip().lower()
IPRAN_PG_SCHEMA = os.environ.get("NATIVE_BOARD_IPRAN_SCHEMA", "ipran_ume")
IPRAN_HISTORY_FALLBACK = os.environ.get(
    "NATIVE_BOARD_IPRAN_FALLBACK", "1").strip().lower() not in ("0", "false", "no", "off")
LOCAL_IPRAN_PG = "__local_ipran_pg__"

# 本机库标识（native_catalog 用它标记「走本机 app.db，不发远端」）
LOCAL_APP_DB = "__local_app_db__"

# my_app **自持**的本地派生库（逻辑名 → 本机文件）。
#
# 为什么需要：远端只读 API 一次只能查一个库，凡是「跨库 join 才能算出来」的
# 派生表都没法用一条远端 SQL 表达。my-finebi 时代这些表靠**手工跑 ETL**
# 落在它自己的 data/ 目录里（PROJECT_DOCS 归类为「ETL 快照刷新」），
# my-finebi 门户退役后无人再跑 —— `avail_recon.sqlite3` 就这样冻结在
# 2026-09-13，`?page=finebi_daily_availability` 静默停更（2026-09-21 发现）。
#
# 现在改由 my_app 自己的定时任务重建到本机，看板直读本机文件：
#   __local_avail_recon__  ← backend/services/avail_recon_sync.py（任务 avail_recon_sync）
#   __local_mttr_tt__      ← backend/services/mttr_tt_sync.py   （任务 mttr_tt_sync）
#   __local_progress__     ← backend/services/progress_sync.py  （任务 progress_sync）
LOCAL_SQLITE_FILES: Dict[str, Path] = {
    "__local_avail_recon__": Path(__file__).resolve().parents[2] / "data" / "avail_recon.sqlite3",
    "__local_mttr_tt__": Path(__file__).resolve().parents[2] / "data" / "mttr_tt.sqlite3",
    "__local_progress__": Path(__file__).resolve().parents[2] / "data" / "progress.sqlite3",
}

# 三个历史远端库 -> 本机镜像（看板请求不再跨机；后台增量同步保持新鲜）。
# 只有看板 SQL 实际引用的 33 张表会被镜像，未引用的不动。
# 注意：镜像文件由 native_board_mirror_sync 单独写入，看板始终以 mode=ro 打开。
MIRROR_ENABLED = os.environ.get(
    "NATIVE_BOARD_MIRROR", "1").strip().lower() not in ("0", "false", "no", "off")
if MIRROR_ENABLED:
    from backend.services import native_board_mirror_sync as _mirror_sync

    for _remote_db in _mirror_sync.REMOTE_DBS:
        LOCAL_SQLITE_FILES[_mirror_sync.mirror_alias(_remote_db)] = \
            _mirror_sync.mirror_path(_remote_db)

# 显式禁用代理：内网地址绝不能被 HTTP_PROXY 劫持（沿用 query_engine 的做法）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 只读语句守卫（本地一道，远端另有一道）
_GUARD_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)

# ISO 日期 / 日期时间前缀：2026-09-14 / 2026-09-14 10:00:00 / 2026-09-14T10:00
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?")

# 月粒度：2026-04（CN KPI 月度看板的类目就是这种形态）
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

# 识别日期列时跳过的列名（这些是「时间戳」而非「业务日期」，做区间过滤会滤空）
_SKIP_DATE_COLS = {"update", "updated", "update_date", "etl_time", "load_time"}

# KPI 卡片不参与时间窗口：它们的 SQL 多为 MAX(...) 之类的聚合单值，
# 套上区间过滤后会变成 0 行（"最新日期" 恰好落在窗口外时尤其明显），
# 而 KPI 卡片本身表达的就是「当前值」，窗口化没有意义。
_WINDOWABLE_CHARTS = {"line", "bar", "table"}


class BoardError(Exception):
    """看板级错误（slug 不存在等），路由层转 404。"""


# ----------------------------------------------------------------------
# slug / 目录
# ----------------------------------------------------------------------
def get_board(slug: str) -> Dict[str, Any]:
    d = BY_SLUG.get(slug)
    if not d:
        raise BoardError(f"未知看板: {slug}")
    return d


def list_boards() -> List[Dict[str, Any]]:
    """轻量清单（不含 SQL），供前端菜单/路由预热。"""
    return CATALOG


# ----------------------------------------------------------------------
# 远端 / 本机查询
# ----------------------------------------------------------------------
def _guard(sql: str) -> str:
    s = (sql or "").strip()
    if not s:
        raise ValueError("SQL 不能为空")
    if ";" in s:
        raise ValueError("仅允许单条语句（不允许分号多语句）")
    if not _GUARD_RE.match(s):
        raise ValueError("仅允许 SELECT / WITH 只读查询")
    return s


def _query_local(sql: str, limit: int, path: Optional[Path] = None) -> Dict[str, Any]:
    """本机 SQLite 只读查询（走只读 URI，绝不写库）。

    path 为空时读 db/app.db（与 sp_dashboard 同源）；
    否则读 LOCAL_SQLITE_FILES 里的 my_app 自持派生库。
    """
    import sqlite3

    if path is None:
        from backend.services.sp_dashboard import DB_PATH  # 复用既有路径定义
        path = DB_PATH
    if not Path(path).is_file():
        raise RuntimeError(
            f"本机库不存在: {path}（若是派生库，请先跑对应的同步任务，"
            f"如 avail_recon_sync）")

    sql = _guard(sql)
    t0 = time.time()
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    try:
        con.execute("PRAGMA query_only=ON")
        cur = con.execute(sql)
        cols = [c[0] for c in (cur.description or [])]
        rows = cur.fetchmany(limit)
        return {
            "success": True,
            "columns": cols,
            "rows": [list(r) for r in rows],
            "count": len(rows),
            "truncated": len(rows) >= limit,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        }
    finally:
        con.close()


def _query_remote(sql: str, db: str, limit: int) -> Dict[str, Any]:
    """远端只读 SQL API。"""
    sql = _guard(sql)
    url = f"{get_api_base_url()}/api/query"
    payload = json.dumps({"db": db, "sql": sql, "limit": limit},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with _OPENER.open(req, timeout=QUERY_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(
            f"远端数据源返回 HTTP {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"无法连接远端数据源 {url}：{getattr(e, 'reason', e)}") from e


# ----------------------------------------------------------------------
# 本机 PG 通道（仅 IP RAN 族）
# ----------------------------------------------------------------------
# PG 里这 3 列是 TEXT（采集侧按「全部 TEXT」建表），而看板 SQL 直接 SUM/ROUND，
# PG 会报「函数 sum(text) 不存在」「round(text, integer) 不存在」。只给「参数
# 恰好是一个带引号数值列」的聚合加 ::numeric；MAX(substr(...)) / MAX(REPLACE(...))
# 这类日期表达式不匹配，保持 text 原样。
_PG_NUMERIC_COLS = {
    "Counter Value",
    "Send Traffic Rate(Mbps)",
    "Receive Traffic Rate(Mbps)",
}
_AGG_BARE_COL_RE = re.compile(
    r'\b(SUM|AVG|MIN|MAX)\s*\(\s*"([^"]+)"\s*\)', re.IGNORECASE)
_SQLITE_DATE_NOW_RE = re.compile(
    r"date\(\s*'now'\s*,\s*'-(\d+)\s+days'\s*\)", re.IGNORECASE)


def _to_pg_sql(sql: str) -> str:
    """SQLite → PG 最小方言适配，只作用于 IP RAN 这 26 条结构规整的 SQL。

    1. SUM/AVG/MIN/MAX(数值列) → 聚合参数 ::numeric（内层变 numeric 后，
       外层 ROUND(x, 2) 自然命中 round(numeric, integer)，无需改 ROUND）。
    2. date('now','-N days') → to_char(current_date - interval 'N days',
       'YYYY-MM-DD')；PG 上 text 列与 timestamp 比较会报操作符不存在，
       故必须产出 **字符串**。
    其余 substr / REPLACE / GROUP BY / ORDER BY / 双引号标识符 PG 原生支持。
    实测可用 psql 复核，见 .workbuddy/memory/2026-11-04.md。
    """
    def _cast(m: "re.Match[str]") -> str:
        fn, col = m.group(1), m.group(2)
        if col not in _PG_NUMERIC_COLS:
            return m.group(0)
        return f'{fn}(("{col}")::numeric)'

    out = _AGG_BARE_COL_RE.sub(_cast, sql)
    return _SQLITE_DATE_NOW_RE.sub(
        lambda m: (f"to_char(current_date - interval '{m.group(1)} days', "
                   "'YYYY-MM-DD')"),
        out)


def _json_scalar(v: Any) -> Any:
    """把 PG 专有标量转成 JSON 可直接序列化的等价物（与远端返回保持一致）。"""
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).decode("utf-8", "replace")
    return v


def _query_pg(sql: str, limit: int) -> Dict[str, Any]:
    """本机 PG 只读查询：search_path 指向 ipran_ume，目录里的裸表名直接命中。

    与 _query_remote 返回同构（success / columns / rows / count / truncated /
    elapsed_ms），所以 _fetch_widget 完全不用感知数据源。
    """
    import psycopg2
    from backend.database import PG_DATABASE_URL

    sql = _guard(sql)
    sql = _to_pg_sql(sql)
    if not PG_DATABASE_URL:
        raise RuntimeError("本机 PG 未配置 DATABASE_URL（检查 backend/.env）")

    t0 = time.time()
    conn = psycopg2.connect(
        PG_DATABASE_URL, connect_timeout=10,
        options=(f"-c search_path={IPRAN_PG_SCHEMA} "
                 "-c statement_timeout=60000"))
    try:
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in (cur.description or [])]
        # PG 的 numeric 会解成 Decimal，而远端 SQLite 给的是 float。统一成
        # JSON 原生标量：否则 _disk_save 的 json.dump 会抛
        # "Object of type Decimal is not JSON serializable"，整页磁盘缓存静默
        # 丢失（2026-11-04 切换当天实测踩到，日志只有一条 WARNING）。
        rows = [[_json_scalar(v) for v in r] for r in cur.fetchmany(limit)]
        return {
            "success": True,
            "columns": cols,
            "rows": rows,
            "count": len(rows),
            "truncated": len(rows) >= limit,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        }
    finally:
        conn.close()


# ----------------------------------------------------------------------
# PG 历史空洞探测（只在用户显式选了历史区间时才跑）
# ----------------------------------------------------------------------
_PG_FROM_RE = re.compile(r'\bFROM\s+"([^"]+)"', re.IGNORECASE)
_PG_RANGE_CACHE: Dict[Tuple[str, str, str], bool] = {}
_PG_RANGE_LOCK = threading.Lock()


def _pg_table_of(sql: str) -> str:
    m = _PG_FROM_RE.search(sql or "")
    return m.group(1) if m else ""


def _pg_range_has_data(table: str, start: str, end: str) -> bool:
    """PG 该表在 [start, end] 区间是否有数据（EXISTS 半扫描，唯一索引，毫秒级）。

    探测失败/提不到表名一律返回 True —— 宁可让本机返回空，也不轻易把
    默认路径退回远端。结果按 (表, 区间) 缓存，整页 26 个组件只探测一次。
    """
    if not table:
        return True
    try:
        e_next = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
                  ).strftime("%Y-%m-%d")
    except ValueError:
        return True
    key = (table, start, e_next)
    with _PG_RANGE_LOCK:
        if key in _PG_RANGE_CACHE:
            return _PG_RANGE_CACHE[key]

    ok = True
    try:
        import psycopg2
        from backend.database import PG_DATABASE_URL
        conn = psycopg2.connect(
            PG_DATABASE_URL, connect_timeout=5,
            options=(f"-c search_path={IPRAN_PG_SCHEMA} "
                     "-c statement_timeout=15000"))
        try:
            conn.set_session(readonly=True, autocommit=True)
            cur = conn.cursor()
            cur.execute(
                f'SELECT 1 FROM "{table}" '
                f'WHERE "Begin Time" >= %s AND "Begin Time" < %s LIMIT 1',
                (start, e_next))
            ok = cur.fetchone() is not None
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("PG 区间探测失败 %s %s..%s，按有数据处理: %s",
                       table, start, end, e)
        ok = True
    with _PG_RANGE_LOCK:
        _PG_RANGE_CACHE[key] = ok
    return ok


def query(sql: str, db: str, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    if db == LOCAL_IPRAN_PG:
        return _query_pg(sql, limit)
    if db == LOCAL_APP_DB:
        return _query_local(sql, limit)
    if db in LOCAL_SQLITE_FILES:
        return _query_local(sql, limit, LOCAL_SQLITE_FILES[db])
    if not db:
        raise ValueError("该组件未指定数据源（source 为空）")
    return _query_remote(sql, db, limit)


# ----------------------------------------------------------------------
# 时间窗口：包一层子查询做区间过滤
# ----------------------------------------------------------------------
def _norm_date(v: Any) -> Optional[str]:
    """把任意值规整成 YYYY-MM-DD；不是日期就返回 None。

    同时接受月粒度（2026-04 → 2026-04-01 参与比较），
    这样 CN KPI 月度看板这类按月的类目也能用同一条时间窗口。
    """
    if v is None:
        return None
    s = str(v).strip()
    m = _DATE_RE.match(s)
    if m:
        return m.group(0)[:10]
    if _MONTH_RE.match(s):
        return f"{s}-01"
    return None


def _is_month_field(columns: List[str], rows: List[List[Any]], idx: int) -> bool:
    """判断某列是否为月粒度类目（决定窗口比较时取前 7 位还是前 10 位）。"""
    vals = [str(r[idx]).strip() for r in rows[:50]
            if idx < len(r) and r[idx] not in (None, "")]
    if not vals:
        return False
    hits = sum(1 for v in vals if _MONTH_RE.match(v))
    return hits >= max(1, int(len(vals) * 0.8))


def detect_date_field(columns: List[str], rows: List[List[Any]]) -> str:
    """自动识别结果集里可用作时间窗口过滤的列。

    优先取第一列（FineBI 图表几乎都是「时间在前」的形态），
    且要求该列多数非空值形如日期，避免把「编号/名称」误判成日期。
    """
    if not columns or not rows:
        return ""
    # 候选顺序：第 1 列优先，其后是名字里含 time/date 的列
    order = [0] + [i for i, c in enumerate(columns)
                   if i and re.search(r"time|date", str(c), re.I)]
    sample = rows[:50]
    for idx in order:
        if idx >= len(columns):
            continue
        col = str(columns[idx])
        if col.strip().lower() in _SKIP_DATE_COLS:
            continue
        vals = [r[idx] for r in sample if idx < len(r) and r[idx] not in (None, "")]
        if not vals:
            continue
        hits = sum(1 for v in vals if _norm_date(v))
        if hits >= max(1, int(len(vals) * 0.8)):
            return col
    return ""


def _apply_window(sql: str, date_field: str, start: str, end: str,
                  month_grain: bool = False) -> str:
    """把原 SQL 包成子查询后按日期列过滤。

    不改写原 SQL —— 187 条 SQL 形态各异（UNION / CTE / 多层聚合 / HAVING ...），
    正则改写必然会破坏原口径；包一层子查询则对原查询完全透明。
    日期按 YYYY-MM-DD 文本比较（ISO 前缀与 SQLite 的字符串序一致）；
    月粒度类目取前 7 位比较（'2026-04' >= '2026-04-01' 成立，故窗口端点做月对齐）。
    """
    inner = _guard(sql)
    col = date_field.replace('"', '""')
    # start / end 已在路由层做过格式校验，这里只做转义防注入
    s = start.replace("'", "''")
    e = end.replace("'", "''")
    if month_grain:
        # 端点收敛到月：起月用当月 1 号，止月用当月最后一天
        s = s[:7]
        e = e[:7]
        return (
            f'SELECT * FROM (\n{inner}\n) '
            f'WHERE substr("{col}",1,7) >= \'{s}\' AND substr("{col}",1,7) <= \'{e}\''
        )
    return (
        f'SELECT * FROM (\n{inner}\n) '
        f'WHERE substr("{col}",1,10) >= \'{s}\' AND substr("{col}",1,10) <= \'{e}\''
    )


def _pushdown_time_window(sql: str, start: str,
                          end: str) -> Tuple[str, bool]:
    """把时间条件下推进 SQL 的 WHERE；返回 (新 SQL, 是否下推)。

    仅命中 PUSH_DOWN_TABLES 里的大表、且原 SQL 的 WHERE 里没有 "Begin Time"
    条件时生效，其余 187 个组件一行不动。start/end 已在路由层校验过格式。
    """
    if not sql or "WHERE" not in sql:
        return sql, False
    if not any('FROM "' + t + '"' in sql for t in PUSH_DOWN_TABLES):
        return sql, False
    head, _, tail = sql.partition("WHERE")
    # 只看 WHERE 与 GROUP/ORDER/HAVING/LIMIT 之间的过滤条件：这些 SQL 的
    # GROUP BY / ORDER BY 里本来就写着 "Begin Time"，把整段 tail 拿来判会
    # 误以为「已有时间条件」而跳过下推（2026-11-04 实测踩过）。
    where_part = re.split(r"\b(?:GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT)\b",
                          tail, maxsplit=1, flags=re.I)[0]
    if '"Begin Time"' in where_part:
        return sql, False
    if start and end:
        s = start.replace("'", "''")
        e = end.replace("'", "''")
        # 上界用「次日 00:00」开区间，而不是 'YYYY-MM-DD 23:59:59'：
        # Metro_ring 的 "Begin Time" 是 ISO 带 T（2026-11-04T00:00:00+00:00），
        # 字符串比较下 'T'(0x54) > ' '(0x20)，<= '... 23:59:59' 会把当天整天
        # 滤掉（PG 与 SQLite 皆然）。开区间对两种格式都成立，且仍能走索引范围扫描。
        try:
            e_next = (datetime.strptime(e, "%Y-%m-%d") + timedelta(days=1)
                      ).strftime("%Y-%m-%d")
            upper = f'"Begin Time" < \'{e_next}\''
        except ValueError:
            upper = f'"Begin Time" <= \'{e} 23:59:59\''
        cond = f'"Begin Time" >= \'{s}\' AND ' + upper
    else:
        cond = f'"Begin Time" >= date(\'now\',\'-{PUSH_DOWN_DAYS} days\')'
    return head + "WHERE " + cond + " AND " + tail, True


# ----------------------------------------------------------------------
# 长窗口按小时聚合（2026-11-05，如意定：「大于 7 天按小时」）
#
# 为什么：15 分钟粒度 × 31 天 = 约 3000 点/条线。`NativeBoard` 只在点数 >120 时
# 开 ECharts 的 LTTB 抽样，页面没有 dataZoom 滑块 —— 一屏塞 3000 点只能看出一片
# 毛边，「这个口子上午最高冲到多少」反而读不出来。
#
# 做法：窗口 > 7 天时，把**已经下推好时间条件**的查询再包一层，按小时取峰值：
#   - 取 MAX 不取 AVG：与同族 `fw_daily` 既有的小时口径一致
#     （`ROUND(MAX("out_bps")/1e6,2)`），均值会把尖峰抹平，而这类曲线就是用来盯
#     尖峰的；上限 = 每小时 4 个 15 分钟点里的最大值，不会造出更高的数。
#   - 只作用于**命中时间下推**的趋势组件（= IP RAN 那 6 张 15 分钟 KPI 表）。
#     其余 13 个看板、月粒度看板、`fw_daily` 的两条全历史趋势一行不动。
#   - 形态不符（SELECT 首列别名不是 `t`，或 pivot 不是 `t/s/value` 三列）就返回
#     空串、保持原粒度 —— 不做任何猜测性改写。
#   - 阈值 `NATIVE_BOARD_HOUR_GRAIN_ABOVE_DAYS` 可调；选 ≤7 天即回到 15 分钟原始粒度。
# 界面侧：被改成小时粒度的卡片会挂 ⓘ（`ExplainIcon`，取 widget.time_grain），
# 按仓库硬要求「这页怎么算的」要能问到，但不占首屏（根 AGENTS.md 四.10 / 四.10b）。
# ----------------------------------------------------------------------
HOUR_GRAIN_ABOVE_DAYS = int(os.environ.get("NATIVE_BOARD_HOUR_GRAIN_ABOVE_DAYS", "7"))
_SELECT_LIST_RE = re.compile(r"^\s*SELECT\s+(.*?)\s+FROM\s", re.IGNORECASE | re.DOTALL)
_ALIAS_RE = re.compile(r"AS\s+(\"[^\"]+\"|[A-Za-z_][A-Za-z_0-9]*)\s*(?=,|$)", re.IGNORECASE)


def _select_aliases(sql: str) -> List[str]:
    """取 SELECT 列表的输出列别名（顺序 = 结果列顺序）；解析不出就返回 []。"""
    m = _SELECT_LIST_RE.match(sql or "")
    if not m:
        return []
    return [a.strip().strip('"') for a in _ALIAS_RE.findall(m.group(1))]


def _hourly_needed(start: str, end: str) -> bool:
    """窗口长到该按小时看了吗（无窗口时按默认下推天数判）。"""
    if start and end:
        try:
            days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
        except ValueError:
            return False
    else:
        days = PUSH_DOWN_DAYS
    return days > HOUR_GRAIN_ABOVE_DAYS


def _hourly_grain_sql(sql: str, pivot: bool) -> str:
    """把查询包成「按小时取峰值」；返回空串 = 形态不符，不改写。

    内层的 `t` 已是 `YYYY-MM-DD HH:MM`（metro_ring 那条 SQL 自带 REPLACE(...,'T',' ')），
    所以取前 13 位再补 `:00` 就是小时刻度，两种库、两种时间文本形态都成立。
    """
    aliases = _select_aliases(sql)
    if len(aliases) < 2 or aliases[0] != "t":
        return ""
    hour_col = "substr(\"t\",1,13) || ':00' AS \"t\""
    if pivot:
        if len(aliases) != 3 or aliases[1] != "s":
            return ""
        val = aliases[2].replace('"', '""')
        cols = f'{hour_col}, "s", ROUND(MAX("{val}"),2) AS "{val}"'
        group = "1, 2"
    else:
        vals = [a.replace('"', '""') for a in aliases[1:]]
        cols = hour_col + ", " + ", ".join(
            f'ROUND(MAX("{v}"),2) AS "{v}"' for v in vals)
        group = "1"
    return f"SELECT {cols} FROM (\n{_guard(sql)}\n) GROUP BY {group} ORDER BY 1"


# ----------------------------------------------------------------------
# 逻辑库别名（目录里写的库名 → 实际要读的库）
# ----------------------------------------------------------------------
# 为什么要有这一层：`native_catalog.py` 是**自动生成**的
# （`_gen_native_catalog.py` 从 my-finebi 的 `dashboards.native_config` 提取），
# 而生成器依赖的中间产物 `_native_catalog_raw.json` 是一次性文件、当前工作区
# 里已经不存在 —— 也就是说「只改生成器」并不能立刻反映到目录里。
# 因此真正生效的解析放在取数这一层：目录是哪个版本生成的都能命中。
#
# 生成器侧同样有 WIDGET_DB_OVERRIDES 做同样的事，两者幂等、不冲突：
# 目录里若已经是本机逻辑名，这里的别名就是空操作。
DB_ALIASES: Dict[str, str] = {
    # my-finebi 的手工 ETL 快照 → my_app 自持的本机派生库
    # （重建任务 avail_recon_sync / mttr_tt_sync / progress_sync；
    #   详见 LOCAL_SQLITE_FILES 处的背景说明）
    "avail_recon.sqlite3": "__local_avail_recon__",
    "mttr_tt.sqlite3": "__local_mttr_tt__",
    "progress.sqlite3": "__local_progress__",
}

# IP RAN 族整族切本机 PG（4 个看板 / 26 个组件）。放在别名层而不是改目录，
# 保持 native_catalog.py「自动生成、请勿手改」的约束，且 remote 开关可秒回退。
if IPRAN_SOURCE == "pg":
    DB_ALIASES["ipran_ume_kpi.sqlite3"] = LOCAL_IPRAN_PG

# 其余 3 个历史库整族切本机镜像（9 个看板 / 93 个组件）。
# 与 IP RAN 一样放在别名层：native_catalog.py 是自动生成文件，不能手改。
# NATIVE_BOARD_MIRROR=0 时不加别名 -> 全部恢复走远端。
if MIRROR_ENABLED:
    for _remote_db in _mirror_sync.REMOTE_DBS:
        DB_ALIASES[_remote_db] = _mirror_sync.mirror_alias(_remote_db)


def resolve_db(db: str) -> str:
    """把目录里的逻辑库名解析成实际要读的库（含本机派生库别名）。"""
    return DB_ALIASES.get(db, db)


# ----------------------------------------------------------------------
# 取组件数据
# ----------------------------------------------------------------------
def _fetch_widget(w: Dict[str, Any],
                  start: str = "", end: str = "") -> Dict[str, Any]:
    """取单个组件数据；失败只标记该组件，不拖垮整页。"""
    raw_db = w.get("db", "")
    db = resolve_db(raw_db)
    out: Dict[str, Any] = {
        "id": w["id"],
        "title": w["title"],
        "chart": w["chart"],
        "pivot": bool(w.get("pivot")),
        "pct": bool(w.get("pct")),
        "db": db,
        "columns": [],
        "rows": [],
        "error": "",
        "date_field": "",
        "windowed": False,
        "grain": "",
        "pushed": False,
        "fallback_remote": False,
        # 时间粒度：'' = 各组件原口径；'hour' = 窗口 >7 天时改按小时取峰值
        # （见 _hourly_grain_sql；前端据此挂 ⓘ 说明，不重算）
        "time_grain": "",
    }
    if w["chart"] == "text":
        out["title_text"] = w.get("title_text", "")
        out["bg"] = w.get("bg", "")
        return out

    limit = w.get("limit") or DEFAULT_LIMIT
    sql, pushed = _pushdown_time_window(w["sql"], start, end)
    out["pushed"] = pushed

    # 只在本机 PG 模式下、用户显式选了区间、且 PG 该表该区间确实没数据时，
    # 才回落到远端权威库（补 PG 的历史空洞）。默认近 7 天完全不走远端。
    fallback_remote = bool(
        IPRAN_HISTORY_FALLBACK and db == LOCAL_IPRAN_PG and start and end
        and not _pg_range_has_data(_pg_table_of(sql), start, end))
    out["fallback_remote"] = fallback_remote

    # 窗口 >7 天：把已下推时间的趋势查询改按小时取峰值（见 _hourly_grain_sql）。
    # 放在 fallback_remote 判定之后：回落远端时用的也是这条包过小时的 SQL ——
    # substr / || / GROUP BY 序号在 SQLite 与 PG 上语义一致，两边出数相同。
    if pushed and w["chart"] in _WINDOWABLE_CHARTS and _hourly_needed(start, end):
        hourly_sql = _hourly_grain_sql(sql, bool(w.get("pivot")))
        if hourly_sql:
            sql = hourly_sql
            out["time_grain"] = "hour"

    def run(q: str) -> Dict[str, Any]:
        # 回落时用的是**未做 PG 方言转换**的原 SQL（_to_pg_sql 只在 _query_pg 内），
        # 正好是远端 SQLite 可执行的形式。
        return _query_remote(q, raw_db, limit) if fallback_remote else query(q, db, limit)

    try:
        res = run(sql)
        if not res.get("success", True):
            raise RuntimeError(res.get("error") or "远端返回 success=false")
        cols = list(res.get("columns") or [])
        rows = [list(r) for r in (res.get("rows") or [])]

        # 时间窗口：先探明日期列，再（可选）套用区间过滤。
        # KPI 卡片不参与（MAX(...)/聚合单值，套窗口会变 0 行）。
        field = detect_date_field(cols, rows)
        out["date_field"] = field
        # 已下推过时间条件的组件不再二次包装子查询：内层会带着默认窗口，
        # 把用户选的历史区间裁空（而且白白多跑一次大查询）。
        if pushed:
            out["windowed"] = bool(start and end)
            out["grain"] = "day" if start and end else ""
        elif start and end and field and w["chart"] in _WINDOWABLE_CHARTS:
            idx = cols.index(field) if field in cols else 0
            month_grain = _is_month_field(cols, rows, idx)
            wrapped = _apply_window(sql, field, start, end, month_grain)
            res2 = run(wrapped)
            if not res2.get("success", True):
                raise RuntimeError(res2.get("error") or "窗口查询失败")
            cols = list(res2.get("columns") or [])
            rows = [list(r) for r in (res2.get("rows") or [])]
            out["windowed"] = True
            out["grain"] = "month" if month_grain else "day"
            # 包装后首列仍是原列名，保持前端取数约定不变

        out["columns"] = cols
        out["rows"] = rows
    except Exception as e:  # noqa: BLE001 — 单组件失败不应中断整页
        logger.warning("看板组件 %s(%s) 取数失败: %s", w["id"], w["title"], e)
        out["error"] = str(e)
    return out


# ----------------------------------------------------------------------
# 缓存（按 slug + 时间窗口维度）
# ----------------------------------------------------------------------
_cache_lock = threading.Lock()
# 内存层：OrderedDict 当 LRU 用，只留最热的 MEM_MAX 页（整页解析后很大）
_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
# 正在后台回源的 key，避免同一页被重复刷新
_refreshing: set = set()
_refresh_pool = ThreadPoolExecutor(max_workers=REFRESH_WORKERS,
                                   thread_name_prefix="nb-refresh")

# 磁盘文件头部的 "at" 字段（只读前 512 字节即可判断新鲜度，不必解析整份）
_AT_RE = re.compile(r'"at"\s*:\s*([0-9]+(?:\.[0-9]+)?)')


def _cache_key(slug: str, start: str, end: str) -> str:
    return f"{slug}|{start}|{end}"


def _disk_path(key: str) -> Path:
    """每个缓存键一个文件；文件名带 slug 便于人工排查，哈希避免非法字符。"""
    slug = key.split("|", 1)[0]
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{slug}__{digest}.json"


def _disk_load(key: str) -> Optional[Dict[str, Any]]:
    path = _disk_path(key)
    try:
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as fh:
            ent = json.load(fh)
        # 哈希碰撞 / 文件被复用防护：键必须完全一致
        if not isinstance(ent, dict) or ent.get("key") != key:
            return None
        if not isinstance(ent.get("at"), (int, float)) or "data" not in ent:
            return None
        return {"at": float(ent["at"]), "data": ent["data"]}
    except Exception:  # noqa: BLE001  缓存坏了不该影响取数
        logger.warning("磁盘缓存读取失败，按未命中处理: %s", path, exc_info=True)
        return None


def _disk_age(key: str) -> Optional[float]:
    """只看年龄、不解析整份数据（预热时逐个检查用）。"""
    path = _disk_path(key)
    try:
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as fh:
            head = fh.read(512)
        m = _AT_RE.search(head)
        return None if not m else max(0.0, time.time() - float(m.group(1)))
    except Exception:  # noqa: BLE001
        return None


def _disk_save(key: str, data: Dict[str, Any]) -> None:
    """原子落盘（先写临时文件再 replace），避免并发读到半截 JSON。"""
    path = _disk_path(key)
    tmp = path.with_suffix(".tmp")
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump({"key": key, "at": time.time(), "data": data}, fh,
                      ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        logger.warning("磁盘缓存写入失败: %s", path, exc_info=True)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _mem_get(key: str) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        ent = _cache.get(key)
        if ent is not None:
            _cache.move_to_end(key)
        return ent


def _mem_put(key: str, ent: Dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = ent
        _cache.move_to_end(key)
        while len(_cache) > MEM_MAX:
            _cache.popitem(last=False)


def _get_cached(key: str) -> Optional[Dict[str, Any]]:
    """内存 → 磁盘 逐层查找；磁盘命中时回填内存。"""
    ent = _mem_get(key)
    if ent is not None:
        return {**ent, "source": "memory"}
    ent = _disk_load(key)
    if ent is not None:
        _mem_put(key, ent)
        return {**ent, "source": "disk"}
    return None


def _is_failed(data: Dict[str, Any]) -> bool:
    return bool((data.get("meta") or {}).get("failed"))


def _schedule_refresh(slug: str, start: str, end: str) -> None:
    """SWR：先把旧数据给用户，再后台回源，用户不为「过期」买单。"""
    key = _cache_key(slug, start, end)
    with _cache_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def _job() -> None:
        try:
            data = _build_board(get_board(slug), slug, start, end)
            if _is_failed(data):
                # 已有好数据就别用失败结果覆盖它；等下一次访问再重试
                old = _get_cached(key)
                if old is not None and not _is_failed(old["data"]):
                    logger.warning("后台刷新有组件失败，保留旧的好缓存 slug=%s", slug)
                    return
            _mem_put(key, {"at": time.time(), "data": data})
            if not _is_failed(data):
                _disk_save(key, data)
            logger.info("后台刷新完成 slug=%s window=%s..%s", slug, start, end)
        except Exception:  # noqa: BLE001
            logger.warning("后台刷新失败 slug=%s", slug, exc_info=True)
        finally:
            with _cache_lock:
                _refreshing.discard(key)

    _refresh_pool.submit(_job)


# ----------------------------------------------------------------------
# 「这一页近 N 天有几天真有数」—— 缺档可见化（2026-11-05，如意定）
#
# 为什么需要：本机 PG 的 ipran_ume 增量镜像**只追头部水位**
# （`ipran_ume_kpi_service.mirror_rows_to_local`），中间断掉的日子永远不会自己
# 长回来；而缺一个日子在折线图上只是「一段没有线」，和「流量真的是 0」长得
# 一模一样 —— 用户会拿着这个错觉去汇报。按仓库硬要求（根 AGENTS.md 第四节
# 第 10 条：**解释怎么算的可以收起，算错了/算不全必须常驻可见**），把缺档算成
# 结构化字段交给前端常驻告警，而不是塞 `title=` 或收进说明条。
#
# 成本：零额外查询 —— 直接用已经取回的行里那一列日期算。
# 范围：只有参与时间下推（pushed=True）且识别出日期列的组件参与统计。它们是
# 15 分钟粒度持续上报的 KPI 表，某台设备一整天一行没有 = 断档；月粒度看板、
# 明细表、`fw_daily` 那两条不带 WHERE 的全历史趋势不参与，避免误报。
# 「今天」不参与判定（还没过完，按天判必然缺）。
# ----------------------------------------------------------------------
def _coverage_from_widgets(results: List[Dict[str, Any]], start: str,
                           end: str) -> Dict[str, Any]:
    """用本页已取回的行算出「期望天数 / 实有天数 / 缺哪几天」。

    返回 {} 表示该页不参与此判定（没有下推组件），前端据此不显示告警。
    """
    pushed = [w for w in results if w.get("pushed") and w.get("date_field")]
    if not pushed:
        return {}

    today = date.today()
    try:
        win_start = date.fromisoformat(start) if start else (
            today - timedelta(days=PUSH_DOWN_DAYS))
        win_end = date.fromisoformat(end) if end else today
    except ValueError:          # 理论上到不了：路由层已校验过格式
        return {}
    win_end = min(win_end, today)
    last_full = min(win_end, today - timedelta(days=1))
    if last_full < win_start:
        expected: List[date] = []
    else:
        expected = [win_start + timedelta(days=i)
                    for i in range((last_full - win_start).days + 1)]

    present = set()
    for w in pushed:
        cols = w.get("columns") or []
        field = w["date_field"]
        if field not in cols:
            continue
        idx = cols.index(field)
        for r in (w.get("rows") or []):
            if idx < len(r):
                d = _norm_date(r[idx])
                if d:
                    present.add(d)

    missing = [d.isoformat() for d in expected if d.isoformat() not in present]
    if not expected:
        return {}
    return {
        "window_start": win_start.isoformat(),
        "window_end": win_end.isoformat(),
        "expected_days": len(expected),
        "present_days": len(expected) - len(missing),
        "missing_days": missing[:60],
        "missing_count": len(missing),
    }


def _build_board(board: Dict[str, Any], slug: str, start: str,
                 end: str) -> Dict[str, Any]:
    """真正取数：并发拉取整页组件（唯一会走远端的路径）。"""
    t0 = time.time()
    widgets = board["widgets"]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(lambda w: _fetch_widget(w, start, end), widgets))

    failed = sum(1 for w in results if w["error"])
    has_window = any(w["date_field"] for w in results)
    return {
        "meta": {
            "slug": slug,
            "name": board["name"],
            "category": board["category"],
            "host": get_api_base_url(),
            "ipran_source": IPRAN_SOURCE,
            "count": len(results),
            "failed": failed,
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
            "cached": False,
            "start": start,
            "end": end,
            # 本页是否支持时间窗口（取决于能否识别出日期列）
            "window_supported": has_window,
            # 缺档可见化：{expected_days, present_days, missing_days[...]}，
            # 非下推页为 {}（见 _coverage_from_widgets）
            "coverage": _coverage_from_widgets(results, start, end),
            "dbs": sorted({w["db"] for w in results if w["db"]}),
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "title": board["title"] or board["name"],
        "widgets": results,
    }


def get_board_data(slug: str, start: str = "", end: str = "",
                   force: bool = False) -> Dict[str, Any]:
    """整页数据：内存 / 磁盘缓存 → 冷取数。

    缓存新鲜 → 直接返回；缓存过期 → **先返回旧数据**再后台回源
    （stale-while-revalidate）；完全没有缓存时才让用户等冷取数。
    force=True 绕过缓存立即回源（前端「刷新」与 Excel 导出走这条）。
    """
    # 首次有看板请求时拉起镜像同步守护（惰性，避免离线脚本/工具进程也起线程）。
    # initial_delay=0：后端刚重启时立刻补一次增量，别让用户看几小时前的镜像。
    if MIRROR_ENABLED:
        try:
            _mirror_sync.start_mirror_daemon(initial_delay=0)
        except Exception as e:  # noqa: BLE001 - 同步失败不能挡住看板
            logger.warning("本机镜像守护启动失败（看板仍读现有镜像）: %r", e)

    board = get_board(slug)
    key = _cache_key(slug, start, end)
    if not force:
        ent = _get_cached(key)
        if ent is not None:
            age = max(0.0, time.time() - ent["at"])
            # 失败结果只留 60s，避免一次抖动固化成 6 小时空白
            ttl = FAILURE_CACHE_TTL if _is_failed(ent["data"]) else CACHE_TTL
            stale = age >= ttl
            if stale:
                _schedule_refresh(slug, start, end)
            data = dict(ent["data"])
            data["meta"] = {
                **data["meta"],
                "cached": True,
                "stale": stale,
                "cache_age_s": round(age, 1),
                "cache_source": ent["source"],
                "cache_ttl_s": ttl,
            }
            return data

    data = _build_board(board, slug, start, end)
    _mem_put(key, {"at": time.time(), "data": data})
    if not _is_failed(data):
        _disk_save(key, data)
    out = dict(data)
    out["meta"] = {
        **data["meta"],
        "stale": False,
        "cache_age_s": 0.0,
        "cache_source": "remote",
        "cache_ttl_s": (FAILURE_CACHE_TTL if _is_failed(data) else CACHE_TTL),
    }
    return out


def cache_stats() -> Dict[str, Any]:
    """缓存概览（排查用）。"""
    now = time.time()
    with _cache_lock:
        mem = [{"key": k, "age_s": round(now - v["at"], 1)}
               for k, v in _cache.items()]
        refreshing = sorted(_refreshing)
    files: List[Dict[str, Any]] = []
    try:
        for p in sorted(CACHE_DIR.glob("*.json")):
            try:
                st = p.stat()
                files.append({"file": p.name,
                              "size_kb": round(st.st_size / 1024, 1),
                              "age_s": round(now - st.st_mtime, 1)})
            except OSError:
                pass
    except OSError:
        pass
    return {
        "ttl_s": CACHE_TTL,
        "mem_max": MEM_MAX,
        "mem_entries": len(mem),
        "mem": mem,
        "disk_dir": str(CACHE_DIR),
        "disk_entries": len(files),
        "disk": files,
        "refreshing": refreshing,
    }


def clear_cache(disk: bool = True) -> Dict[str, Any]:
    """清空缓存（内存 + 可选磁盘）。"""
    with _cache_lock:
        n_mem = len(_cache)
        _cache.clear()
    n_disk = 0
    if disk:
        try:
            for p in CACHE_DIR.glob("*.json"):
                try:
                    p.unlink()
                    n_disk += 1
                except OSError:
                    pass
        except OSError:
            pass
    return {"mem_cleared": n_mem, "disk_cleared": n_disk}


def prewarm(delay_s: float = 2.0) -> Dict[str, Any]:
    """后台预热：把「无缓存 / 缓存已过期」的看板提前取一遍。

    看门狗重启后端后内存缓存必然为空；有磁盘缓存兜底，正常情况下这里
    几乎无事可做，只补真正缺失的。串行 + 间隔，避免和用户请求抢远端。
    """
    now = time.time()
    todo: List[str] = []
    for slug in BY_SLUG:
        key = _cache_key(slug, "", "")
        ent = _mem_get(key)
        age = (now - ent["at"]) if ent is not None else _disk_age(key)
        if age is None or age >= CACHE_TTL:
            todo.append(slug)

    if not todo:
        logger.info("缓存预热：全部看板均已命中，无需回源")
        return {"pending": [], "warmed": 0}

    def _job() -> None:
        for i, slug in enumerate(todo):
            if i:
                time.sleep(delay_s)
            try:
                t0 = time.time()
                data = _build_board(get_board(slug), slug, "", "")
                key = _cache_key(slug, "", "")
                _mem_put(key, {"at": time.time(), "data": data})
                _disk_save(key, data)
                logger.info("缓存预热完成 slug=%s (%.0fms)", slug,
                            (time.time() - t0) * 1000)
            except Exception:  # noqa: BLE001
                logger.warning("缓存预热失败 slug=%s", slug, exc_info=True)

    threading.Thread(target=_job, name="nb-prewarm", daemon=True).start()
    logger.info("缓存预热启动：%d 个看板待回源", len(todo))
    return {"pending": todo, "warmed": 0}


def health(slug: str) -> Dict[str, Any]:
    """看板连通性探测：挑该看板第一个可执行组件试跑一次。"""
    try:
        board = get_board(slug)
    except BoardError as e:
        return {"ok": False, "error": str(e)}
    for w in board["widgets"]:
        if w["chart"] == "text":
            continue
        db = resolve_db(w.get("db", ""))
        try:
            res = query(w["sql"], db, 1)
            return {"ok": True, "slug": slug, "host": get_api_base_url(),
                    "db": db, "elapsed_ms": res.get("elapsed_ms")}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "slug": slug, "host": get_api_base_url(),
                    "db": db, "error": str(e)}
    return {"ok": True, "slug": slug, "note": "仅文本组件"}


# ----------------------------------------------------------------------
# Excel 导出
# ----------------------------------------------------------------------
def _sheet_name(raw: str, used: set) -> str:
    """Excel sheet 名：≤31 字符、去除非法字符、去重。"""
    s = re.sub(r"[\\/*?:\[\]]", "_", str(raw or "Sheet")).strip() or "Sheet"
    s = s[:31]
    base = s
    i = 2
    while s in used:
        suffix = f"_{i}"
        s = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(s)
    return s


def build_excel(data: Dict[str, Any]) -> bytes:
    """把整页数据导成一个 xlsx（每个组件一个 sheet + 一个说明 sheet）。

    表格类组件：原样导出（列名 + 行）。
    图表类组件：kpi 导出单值；line/bar 导出其绘图数据（即后端返回的
    已聚合结果集，含 pivot 透视前的三列形态），便于用户直接做二次分析。

    样式遵循项目规范 docs/EXCEL_EXPORT_STANDARD.md（UNIFIED_EXCEL_V1）：
    标题行 Calibri 14 bold #1F3864、副标题灰字、表头白字底纹 #2F5496、
    数据隔行底纹 #F2F2F2、细框 #B4C6E7、冻结表头、自动筛选。
    （前端是 exceljs，本处是服务端 openpyxl，两端配色/字号取值保持同源。）
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    # ---- UNIFIED_EXCEL_V1 视觉常量（与 docs/EXCEL_EXPORT_STANDARD.md 一致）----
    C_TITLE = "1F3864"
    C_SUB = "808080"
    C_HEAD_BG = "2F5496"
    C_ZEBRA = "F2F2F2"
    C_BORDER = "B4C6E7"
    C_GROUP_BG = "FF8C00"   # 说明 sheet 的分组行（橙）
    thin = Side(style="thin", color=C_BORDER)
    box = Border(left=thin, right=thin, top=thin, bottom=thin)

    wb = Workbook()
    wb.remove(wb.active)

    def write_sheet(name: str, columns: List[str], rows: List[List[Any]],
                    title: str = "", subtitle: str = "") -> None:
        ws = wb.create_sheet(_sheet_name(name, used))
        ncol = max(len(columns), 1)
        r = 1

        # 第 1 行：标题（合并整表宽，左对齐）
        if title:
            ws.cell(row=r, column=1, value=title).font = Font(
                name="Calibri", size=14, bold=True, color=C_TITLE)
            if ncol > 1:
                ws.merge_cells(start_row=r, start_column=1,
                               end_row=r, end_column=ncol)
            r += 1
        # 第 2 行：副标题（灰字）
        if subtitle:
            ws.cell(row=r, column=1, value=subtitle).font = Font(
                name="Calibri", size=9, color=C_SUB)
            if ncol > 1:
                ws.merge_cells(start_row=r, start_column=1,
                               end_row=r, end_column=ncol)
            r += 1

        header_row = r
        # 表头：白字 + #2F5496 底纹 + 居中
        for c, col in enumerate(columns, start=1):
            cell = ws.cell(row=header_row, column=c, value=str(col))
            cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor=C_HEAD_BG)
            cell.alignment = Alignment(horizontal="center", vertical="center",
                                       wrap_text=True)
            cell.border = box
        r += 1

        # 数据行：隔行底纹按「工作表绝对行号」奇偶判断（与 Python 端 _apply_zebra 一致）
        for i, row in enumerate(rows):
            for c in range(1, ncol + 1):
                v = row[c - 1] if (c - 1) < len(row) else None
                cell = ws.cell(row=r, column=c, value="" if v is None else v)
                cell.font = Font(name="Calibri", size=10)
                cell.border = box
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    cell.alignment = Alignment(horizontal="right")
                    cell.number_format = "#,##0"
                if r % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor=C_ZEBRA)
            r += 1

        # 列宽：min(max(最长内容+2, 10), 42)，最多扫前 200 行
        for idx, col in enumerate(columns, start=1):
            w = len(str(col))
            for row in rows[:200]:
                if idx - 1 < len(row):
                    w = max(w, len(str(row[idx - 1])))
            ws.column_dimensions[get_column_letter(idx)].width = min(max(w + 2, 10), 42)

        # 冻结表头 + 自动筛选（覆盖表头 → 末行）
        if columns:
            ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
            last = max(r - 1, header_row)
            ws.auto_filter.ref = (f"A{header_row}:"
                                  f"{get_column_letter(ncol)}{last}")
        # 页面：横向、按宽度缩放到 1 页
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True

    used: set = set()
    meta = data.get("meta", {})
    gen = f'Generated: {meta.get("fetched_at", "")}'

    # 说明 sheet 放最前
    info = [
        ["看板", data.get("title", "")],
        ["分类", meta.get("category", "")],
        ["数据源", ", ".join(meta.get("dbs", [])) or "-"],
        ["时间窗口", (f'{meta.get("start")} ~ {meta.get("end")}'
                  if meta.get("start") else "未启用（全量）")],
        ["组件数", meta.get("count", 0)],
        ["取数时间", meta.get("fetched_at", "")],
        ["数据来源", "my_app 原生看板（原 FineBI 看板迁移，不依赖 my-finebi）"],
        ["远端地址", meta.get("host", "")],
    ]
    write_sheet("说明", ["项", "值"], info,
                title=f'{data.get("title", "")} — 数据说明',
                subtitle=f'{gen}    |    Sheet: 说明')

    for w in data.get("widgets", []):
        if w["chart"] == "text":
            continue
        title = w.get("title") or w["id"]
        sub = f'{gen}    |    Sheet: {title}    |    {w.get("db", "")}'
        if w.get("error"):
            write_sheet(title, ["错误"], [[w["error"]]], title=title, subtitle=sub)
            continue
        cols = w.get("columns") or []
        rows = w.get("rows") or []
        if w["chart"] == "kpi":
            write_sheet(title, cols or ["值"], rows, title=title, subtitle=sub)
        elif cols:
            # line/bar/table 一律导出结果集本身（图表的数据就是这些行）
            write_sheet(title, cols, rows, title=title, subtitle=sub)
        else:
            write_sheet(title, ["（无数据）"], [], title=title, subtitle=sub)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------
# 参数校验（供路由层调用）
# ----------------------------------------------------------------------
def validate_window(start: str, end: str) -> Tuple[str, str]:
    """校验并规整时间窗口参数；空值表示不启用。"""
    s = (start or "").strip()
    e = (end or "").strip()
    if not s and not e:
        return "", ""
    if bool(s) != bool(e):
        raise ValueError("start 与 end 必须同时提供")
    try:
        ds = date.fromisoformat(s)
        de = date.fromisoformat(e)
    except ValueError as exc:
        raise ValueError("日期格式须为 YYYY-MM-DD") from exc
    if ds > de:
        raise ValueError("开始日期不能晚于结束日期")
    if (de - ds).days > 3650:
        raise ValueError("时间窗口过长（上限 10 年）")
    return ds.isoformat(), de.isoformat()


# （这里原有 `def default_window()` 返回“近 31 天”，全仓无调用方，2026-11-05 删除。）
# 看板「不选窗口时看几天」的唯一真相源是文件顶部的 PUSH_DOWN_DAYS，
# 别再加第二个默认窗口函数 —— 两个数不一样时没人知道该信谁（AGENTS.md 四.5）。

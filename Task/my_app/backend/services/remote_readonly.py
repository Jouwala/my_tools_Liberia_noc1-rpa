# -*- coding: utf-8 -*-
"""远端只读 SQL API 的最小客户端（供派生表 ETL / 巡检共用）。

背景
----
`backend/services/dashboard_service.py` 里的 `_query_remote()` 是**看板取数**专用
（带时间窗口、缓存等），不适合被 ETL 复用；而 `db_writer_client` 只负责**写**。
此前每个需要读远端库的脚本都各写一份 urllib 调用（ccn_free_rating / ipran_chart /
ran_ume_service._read_remote_daily_tables / db_freshness_check ...），
口径（超时、代理、错误信息）各不相同。

本模块把「读」这一件事收敛成一处，供 avail_recon_sync / mttr_tt_sync /
progress_sync 这些派生表任务使用。

约定
----
- **内网地址绝不能被 HTTP_PROXY 劫持**：显式挂空的 ProxyHandler。
- 只发单条只读语句；远端还有一道只读守卫。
- `limit` 上限 50000（远端 API 的限制），超过要自己在 SQL 里分片。
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, List, Optional

from backend.config.remote_host import get_api_base_url

logger = logging.getLogger("remote_readonly")

# 显式禁用代理（沿用 query_engine / dashboard_service 的做法）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

DEFAULT_TIMEOUT = 600
# 远端 API 的 limit 上限（见 GET /openapi.json 的 /api/query 说明：1..50000）
MAX_LIMIT = 50000


class RemoteQueryError(Exception):
    """远端不可达 / 返回 success=false。"""


def query_rows(db: str, sql: str, limit: int = MAX_LIMIT,
               timeout: int = DEFAULT_TIMEOUT) -> List[List[Any]]:
    """执行一条只读 SQL，返回行列表（每行为 list）。

    失败一律抛 RemoteQueryError —— ETL 侧需要「拿不到就整体失败」，
    绝不能静默返回空集把派生表写成空的。
    """
    if limit > MAX_LIMIT:
        raise ValueError(f"limit 不能超过远端上限 {MAX_LIMIT}（当前 {limit}）")
    url = f"{get_api_base_url()}/api/query"
    payload = json.dumps({"db": db, "sql": sql, "limit": limit},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise RemoteQueryError(
            f"{db} 返回 HTTP {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise RemoteQueryError(
            f"无法连接远端数据源 {url}：{getattr(e, 'reason', e)}") from e

    if not out.get("success"):
        raise RemoteQueryError(f"{db} 查询失败: {out.get('error') or out}")
    return [list(r) for r in (out.get("rows") or [])]


def query_dicts(db: str, sql: str, limit: int = MAX_LIMIT,
                timeout: int = DEFAULT_TIMEOUT) -> List[dict]:
    """同上，但把行映射成 {列名: 值}（列多时比按下标取值可读得多）。"""
    url = f"{get_api_base_url()}/api/query"
    payload = json.dumps({"db": db, "sql": sql, "limit": limit},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RemoteQueryError(
            f"无法连接远端数据源 {url}：{getattr(e, 'reason', e)}") from e
    if not out.get("success"):
        raise RemoteQueryError(f"{db} 查询失败: {out.get('error') or out}")
    cols = list(out.get("columns") or [])
    return [dict(zip(cols, r)) for r in (out.get("rows") or [])]

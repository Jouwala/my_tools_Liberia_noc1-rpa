# -*- coding: utf-8 -*-
"""eFlow 工单「上游是否还存在」的权威核验（对账删除的数据来源）。

为什么需要这个模块
------------------
用户诉求：eFlow 已删除的数据不该继续出现在本地库和页面上。

根因：`sync_from_eflow_api` 对 TT/WO/CR/PM 一直是**只 upsert、从不删除**。
全量兜底任务（`eflow_sync_full`）虽然拉了全窗口，但它只是把上游现有的单
再写一遍，**上游删掉的单会永久留在本地**（实测：本地多出 TT 11 / WO 54 行，
这些单号在上游 base/list 里已完全不存在）。

为什么权威源必须是 base/list 直查，而不是全量导出
-------------------------------------------------
2026-11-16 实测（`log/worker_runtime_n_20261113.log`，08:08 那轮 full）：
同一时间窗下，**导出管道**抓到 TT 41906 行、WO 16469 行；而 **base/list
直查**抓到 TT 41949 行、WO 16496 行 —— 导出比直查**少约 43 / 27 行正常单**
（导出是异步生成的 xlsx，上游在生成期间有单变动、或导出有行被截断，都会
造成这种缺口）。若拿导出结果当「上游全集」做对账，**会把那 43 行正常单误删**。

所以本模块用 base/list 直查扫出**上游权威键集合**，再与本地库求差集：
- 上游有、本地无 → 漏抓（由 upsert 补，本模块不处理）；
- 本地有、上游无 → 上游已删 → **允许删除**。

为什么还要「按本地数据推导时间窗」
----------------------------------
上游 list 的过滤条件是 `lastModifiedTime` 落在窗口内。窗口起点若取固定值
（如 2026-01-01），**上游那些 lastModifiedTime 更早、但仍然活着的单会查不到**，
于是被误判成「上游已删」而误删。故窗口起点必须由**本地数据的最早
last_modified_time** 推导（再往前留一段余量），保证「本地有的，上游一定查得到」。

只读：本模块**不写任何库**，只发 HTTP 列表查询。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from backend.services.eflow_api_client import _headers_extra, _http_request
from backend.services.eflow_data_mapper import (
    CR_API_PATH,
    CR_LIST_FIELDS,
    CR_REFERER,
    CR_STATUS_FILTER,
    TIME_FILTER_TEMPLATE,
    TT_API_PATH,
    TT_FIELDS,
    TT_REFERER,
    TT_STATUS_FILTER,
    WO_API_PATH,
    WO_FIELDS,
    WO_REFERER,
    WO_STATUS_FILTER,
)

logger = logging.getLogger("eflow_sync")


class UpstreamVerifyError(RuntimeError):
    """上游查询失败/返回不完整 —— 调用方必须**中止删除**，不得当作「已删除」。"""


#: 每页条数。上游 list 接口对 length 宽容（实测 10000/页也正常返回），
#: 但**单页耗时几乎与页大小无关** —— 上游对每页都要重跑一次「时间过滤 + 排序」，
#: 固定开销约 6s。实测（2026-11-16，TT 41951 行全窗口扫描）：
#:
#:   | length | 单页耗时 | 总页数 | 总时长 |
#:   |--------|---------|--------|--------|
#:   |    200 |   6.34s |    210 | 22.2 分钟 |
#:   |   1000 |   7.05s |     42 |  4.9 分钟 |
#:   |   2000 |   7.76s |     21 |  2.7 分钟 |
#:   |   5000 |  10.59s |    8.4 |  1.5 分钟 |
#:
#: 瓶颈是**请求次数**不是数据量，故用 2000/页（比 200/页快 8 倍）。
#: 不取 5000：响应体到 7MB，再大收益递减且单页失败要重拉。
_PAGE_SIZE = 2000

#: 扫描时间窗起点相对「本地最早 last_modified_time」往前留的余量（天）。
#: 留足余量是为了覆盖「上游 lastModifiedTime 比本地记录的更早」这种反常情况。
_WINDOW_MARGIN_DAYS = 30

#: 「扫全」闸门的容差 —— **不能用精确相等**（2026-11-17 事故）。
#:
#: 上游的 `total` 是**首页返回时**的计数，而一次全窗口扫描要跑几分钟；
#: 这期间有单新建 / 被删 / 修改时间跨过窗口边界，计数必然轻微漂移。
#: 实测：08:01 那轮 TT 拉到 42054/42055（**差 1 行**）、08:50 重试 WO
#: 16578/16582（**差 4 行**），两次都被判"窗口不完整"→ 整轮放弃删除 →
#: 任务 success=False → 连发微信与邮件告警，而数据其实完全够用。
#:
#: 故改为**允许小幅缺口**：缺口 ≤ max(绝对下限, total × 比例) 视为计数抖动，
#: 记 warning 后照常删除；只有缺口真正大（页被截断 / 接口提前收尾）才拒绝。
#: 取值依据：一页 _PAGE_SIZE=2000，真正的截断至少缺几百行，远大于此容差。
_SCAN_SHORTFALL_MIN = 10          # 绝对容忍下限（行）
_SCAN_SHORTFALL_RATIO = 0.005     # 相对容忍比例（0.5%）


def _shortfall_tolerance(total: int) -> int:
    """「实拉条数」允许比上游 total 少多少行（超过即判定扫描不完整）。"""
    return max(_SCAN_SHORTFALL_MIN, int(total * _SCAN_SHORTFALL_RATIO))


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _scan_upstream_keys(api_path: str, referer: str, payload_base: dict,
                        label: str) -> set[str]:
    """扫上游列表，返回该窗口内的**全部**单号集合。

    ⚠ 实拉条数比上游 `total` 少得过多（超过 `_shortfall_tolerance`）时抛
    `UpstreamVerifyError`，绝不返回残缺集合冒充全集 —— 那会让调用方误删真实单据。
    少几行属扫描期间上游计数抖动，只记 warning，不阻断（见容差常量注释）。
    """
    headers = _headers_extra(referer)
    keys: set[str] = set()
    fetched = 0
    start = 0
    total = None

    while True:
        payload = dict(payload_base)
        payload["start"] = start
        payload["length"] = _PAGE_SIZE
        status, _hdrs, _raw, resp = _http_request(
            "POST", api_path, headers_extra=headers,
            body=json.dumps(payload), max_retries=0,
        )
        text = (resp or b"").decode("utf-8", "replace")
        if "200" not in status:
            raise UpstreamVerifyError(f"{label} 列表接口 {status}: {text[:200]}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise UpstreamVerifyError(f"{label} 列表接口返回的不是 JSON") from exc
        if not isinstance(data, dict):
            raise UpstreamVerifyError(f"{label} 列表接口返回 {type(data).__name__}")
        code = data.get("code")
        if code not in (0, None, "0"):
            raise UpstreamVerifyError(
                f"{label} 列表接口 code={code} {str(data.get('message') or '')[:200]}")

        if total is None:
            total = int(data.get("total") or 0)
            logger.info("%s 上游窗口 total=%s", label, total)

        batch = data.get("result") or []
        if not isinstance(batch, list):
            raise UpstreamVerifyError(f"{label} 列表 result 不是数组")
        for item in batch:
            if isinstance(item, dict):
                k = item.get("woNum")
                if k is not None:
                    key = str(k).strip()
                    if key:
                        keys.add(key)
        fetched += len(batch)
        start += _PAGE_SIZE
        if not batch or len(batch) < _PAGE_SIZE:
            break
        if total and start >= total:
            break

    if total and fetched < total:
        shortfall = total - fetched
        tolerance = _shortfall_tolerance(total)
        if shortfall > tolerance:
            raise UpstreamVerifyError(
                f"{label} 上游只拉到 {fetched}/{total} 行（缺 {shortfall}，"
                f"超过容忍 {tolerance}）—— 窗口不完整，拒绝据此删除")
        logger.warning(
            "%s 上游 total=%s 但实拉 %s 行（缺 %s，在容忍 %s 内）："
            "属扫描期间上游计数抖动，照常继续", label, total, fetched, shortfall, tolerance)

    logger.info("%s 上游权威集合 %d 个单号（total=%s）", label, len(keys), total)
    return keys


def _local_min_lmt(conn, table: str, key_col: str) -> str | None:
    """本地表里最早的 last_modified_time（文本 'YYYY-MM-DD HH:MM:SS'）。"""
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT MIN(last_modified_time) FROM "{table}"')
        row = cur.fetchone()
        cur.close()
        return row[0] if row and row[0] else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 %s 最早 last_modified_time 失败: %s", table, exc)
        return None


def fetch_authoritative_keys(conn) -> tuple[dict[str, set[str]], dict[str, str]]:
    """扫出 TT / WO / CR 的上游权威单号集合。

    时间窗由**本地数据**推导：起点 = 本地最早 last_modified_time 往前 30 天，
    终点 = 现在。这样「本地有的单，上游一定在窗口内查得到」，不会把
    「上游还活着但很久没动」的单误判成已删除。

    Returns:
        (keys_by_label, errors_by_label)
        · `keys_by_label`：`{"TT": {...}, "WO": {...}, "CR": {...}}`，只含扫描成功的表；
        · `errors_by_label`：`{"TT": "失败原因"}`，扫描失败/不完整的表不出现于 keys。

    ⚠ **单表失败只隔离该表，不再抛异常整轮放弃**（2026-11-17 改）。
    此前任一张表扫描异常就整轮放弃，实测 TT 差 1 行导致 WO、CR 当轮也全都不删，
    任务还 success=False 连发告警。调用方按表跳过即可 —— 一张表查不准，
    不该连累另外两张本来能对账的表。
    """
    end_dt = datetime.now(timezone.utc)
    results: dict[str, set[str]] = {}
    errors: dict[str, str] = {}

    specs = [
        ("TT", "eflow_tt", "tt_no", TT_API_PATH, TT_REFERER, TT_FIELDS,
         TT_STATUS_FILTER, {"eflow_ticket_ticket_asset_all": ""}),
        ("WO", "eflow_wo", "wo_no", WO_API_PATH, WO_REFERER, WO_FIELDS,
         WO_STATUS_FILTER, {"eflow_wo_wo_asset": ""}),
        ("CR", "eflow_cr", "change_request_id", CR_API_PATH, CR_REFERER, CR_LIST_FIELDS,
         CR_STATUS_FILTER, None),
    ]

    for label, table, _key_col, api_path, referer, fields, status_filter, relation in specs:
        min_lmt = _local_min_lmt(conn, table, _key_col)
        if min_lmt:
            try:
                start_dt = datetime.strptime(str(min_lmt)[:19], "%Y-%m-%d %H:%M:%S")
                start_dt = start_dt.replace(tzinfo=timezone.utc) - timedelta(days=_WINDOW_MARGIN_DAYS)
            except ValueError:
                start_dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
        else:
            # 本地没有可用时间信息 → 退回一个很宽的窗口，宁可多扫也不能漏
            start_dt = datetime(2025, 1, 1, tzinfo=timezone.utc)

        if label == "CR":
            # CR 的上游列表**不带时间过滤**（生产直查管道同样如此），
            # 单量本身只有几百条，直接全量扫。
            payload = {
                "customInfo": {"pageType": "allTicket"},
                "field": CR_LIST_FIELDS,
                "filter": CR_STATUS_FILTER,
                "order": "lastModifiedTime desc",
                "length": _PAGE_SIZE,
            }
        else:
            filt = TIME_FILTER_TEMPLATE.format(
                status_filter=status_filter, start_ms=_ms(start_dt), end_ms=_ms(end_dt))
            payload = {
                "customInfo": {"pageType": "allTicket"},
                "field": fields,
                "filter": filt,
                "order": "lastModifiedTime desc",
                "relationFilter": relation,
            }

        logger.info("%s 对账扫描窗口: %s ~ %s", label, start_dt, end_dt)
        try:
            results[label] = _scan_upstream_keys(api_path, referer, payload, label)
        except UpstreamVerifyError as exc:
            # 只隔离这张表：不放进 results，调用方会对它跳过删除
            logger.error("%s 权威集合扫描不完整，本轮跳过该表的对账删除：%s", label, exc)
            errors[label] = str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s 权威集合扫描异常，本轮跳过该表的对账删除", label)
            errors[label] = f"{type(exc).__name__}: {exc}"

    return results, errors

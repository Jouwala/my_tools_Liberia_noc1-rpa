#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vmax_diagnosis.py —— 投诉诊断的聚合层（四个源一次取齐）
=============================================================================

## 这个模块解决什么问题

改版前页面是「四个数据源四个页签」：用户看到的是 Categorized Traffic /
Merged XDR / XDR Records —— **按数据源切的，不是按问题切的**。
接到一条「我九点十分视频一直卡」的投诉，用户要自己在四个页签之间
来回对时间，还得自己判断「是流量为零更有解释力，还是 RTT 高更有解释力」。

本模块把四个源**一次取齐**，按分钟对齐后交给前端做评分与结论
（评分/结论在前端，见 frontend/src/pages/vmaxDiagnosisRules.ts —— 这样
切换投诉类型不重新取数，秒切）。

    1100  会话/信令面（S1-MME / S11 / SGs / S6a）  → 连接过程、CSFB 语音链
    1300  用户面话单（fact_5gsa_psup_flow）        → 业务流量、时延、重传
    1301  视频专表（fact_5gsa_psup_video）          → vmos / 分辨率
    32    RAN 无线侧（UEMR / UU / X2）              → RSRP / SINR / CQI

## 三条硬纪律（都踩过，写在这里防止再踩）

1. **不整页失败**。任何一个源超时/报错，都只让该源 `ok=false` + 原因，
   其余照常返回。用户在排障，最怕的是「一个源挂了整页白屏」。
2. **RAN 必须按 IMSI 查**。`$msisdn` 列实测全为空串（2026-10-31），
   按号码查永远 0 条。这里先用 1300 解析 IMSI，再查 32；
   解析不到就返回 `ok=false, error="无 IMSI 映射…"`，**绝不静默返回 0 条**
   （那会被误读成「用户没数据」）。
3. **复用会话**。`get_xdr_client()` 复用 CCA 的门户会话，不自行登录 ——
   多进程各自登录会触发 "The maximum number of connections for the user
   is reached"。
4. **号码必须一路传到 `query_table` 的首参**（2026-10-31 修 P0）。
   历史版本 `fetch_all(start, end)` 没有 msisdn，内部调
   `query_table("", ...)` → 条件里 `msisdn` 值为空串 → 四个源恒为 0 条，
   界面显示「该时段无业务」。同表同窗口实测：带号码 2484 条 / 空号码 0 条。
   现在 `fetch_all(msisdn, start, end)` 显式拒绝空号码。
   **改这个文件时先确认 msisdn 在调用链上没有丢。**

## 并发与开销

四个源**并行**取（ThreadPoolExecutor）。实测单源耗时：1300 三页 ~12s、
1100 ~6s、32 单表 0.3~1.7s。串行要 20s+，并行压到 12s 左右，
瓶颈是 1300（上游分页上限 200 条）。
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 取数口径
# ---------------------------------------------------------------------------
# 1300 用户面：只留「能算指标」的列，colModel 传诊断真正要的列（P0'-2 裁列）。
# 3h 窗口不动（用户约束），页数封顶：上游 200/页，6 页 = 1200 条；
# 实测忙时号码 3 小时窗口 645 条，足够覆盖。再往上翻对统计贡献递减，
# 但会把页面拖到 30s 以上。
MAX_PAGES_1300 = 6
PAGE_SIZE = 200

# 1100 会话/信令面：766 条/2 小时，3 页够
MAX_PAGES_1100 = 4

# 32 RAN：按 IMSI 查，实测 101 条/2 小时，单页够
MAX_PAGES_RAN = 3

# 单源整体超时（秒）。超过就算该源失败，不拖累其它源。
SOURCE_TIMEOUT = 90

# 两个时间格式：5gsa 域按毫秒边界切分区（必须带 .000），RAN 域同样
FMT_MS = "%Y-%m-%d %H:%M:%S.000"
FMT_SEC = "%Y-%m-%d %H:%M:%S"


def _to_ms(dt: datetime) -> str:
    return dt.strftime(FMT_MS)


def _shift_end(dt: datetime) -> datetime:
    """窗口终点往后挪 1 分钟。

    实测 end 落在 :45 这类刻钟边界时，上游整个分区返回 0 条
    （end=17:44 → 785 条，end=17:45 → 0 条，end=17:46 → 785 条）。
    多带 1 分钟数据不影响统计口径，但能避免「整段时间凭空消失」。
    """
    return dt + timedelta(minutes=1)


class VmaxDiagnosis:
    """四源聚合取数。构造只持 client，不做 IO；查询在 `fetch_all()`。"""

    def __init__(self, xdr_client):
        self.xdr = xdr_client

    # ------------------------------------------------------------------
    # 单源取数（各自捕获异常，绝不向上抛）
    # ------------------------------------------------------------------
    def _page_through(self, msisdn: str, service_type: str, table: str,
                      start: str, end: str, max_pages: int,
                      imsi: Optional[str] = None,
                      columns: Optional[List[str]] = None) -> Tuple[List[Dict[str, Any]], bool]:
        """滚动分页取到 max_pages 或取完为止。

        返回 (rows, truncated)。truncated=True 表示「还有但没取」，
        要在界面上明说 —— 不说明的话，用户会以为拿到的是全量。

        ⚠ `msisdn` 必须是**真实号码**（2026-10-31 修 P0）：本方法第一版把
        `query_table` 的首参写成了字面量 `""`，于是条件变成
        `{"field":"msisdn","value":"","type":"1"}` —— 上游如实按空号码过滤，
        四个源**永远 0 条**。表现极像「该号码无数据」，实际是查询条件错；
        连带 RAN 拿不到 IMSI，报「无 IMSI 映射」，被误判成上游会话被占满。
        同表同窗口实测：带号码 2484 条 / 空号码 0 条。

        `columns`：P0'-2 列裁剪 —— 只取判据要的列。None 则取全列（兼容）。
        """
        rows: List[Dict[str, Any]] = []
        page = 1
        truncated = False
        while page <= max_pages:
            res = self.xdr.query_table(
                msisdn, service_type, table, start, end,
                page=page, page_size=PAGE_SIZE, imsi=imsi,
                columns=columns)
            batch = res.get("rows") or []
            if not batch:
                break
            rows.extend(batch)
            total = int(res.get("records") or 0)
            if len(rows) >= total:
                break
            if page == max_pages:
                truncated = True
            page += 1
        return rows, truncated

    # P0'-2 列裁剪：诊断真正要的列（88 列全取 × 1200 行 ≈ 数 MB）。
    # 前后端字段契约见 frontend/src/pages/vmaxDiagnosisRules.ts 的取数字段。
    # 注意同时覆盖流量聚合要的列（见 vmax_flow_from_xdr._normalize），
    # 否则诊断复用给流量时部分指标缺列。带 $ 与不带 $ 的两种写法都取，
    # 上游不同表/版本字段名有差异，缺列不报错、只算不出指标。
    COLS_1300 = [
        "imsi", "msisdn", "start_time", "service", "subservice",
        "app_content_name", "protocol", "duration",
        "ul_traffic", "dl_traffic",
        "ul_pkt", "dl_pkt", "ul_retrans_pkt", "dl_retrans_pkt",
        "ul_disorder_pkt", "dl_disorder_pkt",
        "$first_resp_delay", "$tcp_resp_delay", "$tcp_ack_delay",
        "tcp_resp_delay", "tcp_ack_delay",
        "$first_req_delay",
        "ul_avg_rtt", "dl_avg_rtt",
        "ul_throughput_max", "dl_throughput_max", "qci",
    ]
    COLS_1100 = [
        "imsi", "procedure_start_time", "start_time",
        "interface", "procedure_type", "procedure_status",
        "request_cause", "fail_cause",
        "cellname", "cell", "cellid",
    ]
    COLS_1301 = ["start_time", "vmos", "resolution", "result"]
    COLS_RAN = [
        "btime", "serving_rsrp", "ulsinr", "cqi",
        "cell", "cellname", "cell_name", "rat_name", "phr",
    ]

    def _src_1300(self, msisdn: str, start: str, end: str) -> Dict[str, Any]:
        rows, truncated = self._page_through(
            msisdn, "1300", "fact_5gsa_psup_flow", start, end, MAX_PAGES_1300,
            columns=self.COLS_1300)
        # label_key 给前端翻译用，label 是中文兜底（前端字典缺键时回退，
        # 保证界面上宁可显示中文也不显示 "vmaxq.diag.src.1300" 这种原文）。
        return {"key": "1300", "label_key": "vmaxq.diag.src.1300",
                "label": "用户面话单 (1300)", "rows": rows,
                "truncated": truncated}

    def _src_1100(self, msisdn: str, start: str, end: str) -> Dict[str, Any]:
        rows, truncated = self._page_through(
            msisdn, "1100", "fact_pscp_s1mme", start, end, MAX_PAGES_1100,
            columns=self.COLS_1100)
        return {"key": "1100", "label_key": "vmaxq.diag.src.1100",
                "label": "会话/信令面 (1100)", "rows": rows,
                "truncated": truncated}

    def _src_1301(self, msisdn: str, start: str, end: str) -> Dict[str, Any]:
        # 视频专表：覆盖不全，空是常态，取一页即可
        try:
            res = self.xdr.query_table(
                msisdn, "1301", "fact_5gsa_psup_video", start, end,
                page=1, page_size=PAGE_SIZE, columns=self.COLS_1301)
            rows = res.get("rows") or []
        except Exception as exc:                       # noqa: BLE001
            logger.info("[vmax_diag] 视频专表查询失败（正常，可空）: %s", exc)
            rows = []
        return {"key": "1301", "label_key": "vmaxq.diag.src.1301",
                "label": "视频专表 (1301)", "rows": rows,
                "truncated": False}

    def _src_ran(self, msisdn: str, start: str, end: str,
                 imsi: Optional[str]) -> Dict[str, Any]:
        """RAN(32) —— 必须按 IMSI 查，见模块头纪律 2。"""
        if not imsi:
            return {
                "key": "32", "label_key": "vmaxq.diag.src.32",
                "label": "无线质量 (32 RAN)", "rows": [],
                "truncated": False, "ok": False,
                "error": "无 IMSI 映射：本窗口 1300/1100 都没有该号码的 IMSI，"
                         "无法按 IMSI 查无线侧话单（RAN 表的号码列为空）",
            }
        # UEMR（测量报告）是 RSRP/SINR 的来源；UU/X2 是空口/切换话单。
        # 排障看空口质量只要 UEMR，取它一张表即可，多取只会更慢。
        rows, truncated = self._page_through(
            msisdn, "32", "fact_lte_uemr", start, end, MAX_PAGES_RAN, imsi=imsi,
            columns=self.COLS_RAN)
        return {"key": "32", "label_key": "vmaxq.diag.src.32",
                "label": "无线质量 (32 RAN)", "rows": rows,
                "truncated": truncated}

    # ------------------------------------------------------------------
    # 解析 IMSI（RAN 查询的前置条件）
    # ------------------------------------------------------------------
    @staticmethod
    def _pick_imsi(rows_1300: List[Dict[str, Any]],
                   rows_1100: List[Dict[str, Any]]) -> str:
        """从 1300/1100 的记录里挑一个非空 IMSI。

        优先 1300（每条都带 imsi，实测填充率 100%），没有再看 1100。
        只要求「非空且够长」，不校验 MCC/MNC —— 号码归属不属于本模块职责。
        """
        for rows in (rows_1300, rows_1100):
            for r in rows:
                v = str(r.get("imsi") or "").strip()
                if v and v not in ("-", "--") and len(v) >= 10:
                    return v
        return ""

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def fetch_all(self, msisdn: str, start: str, end: str) -> Dict[str, Any]:
        """并行取四个源。start/end 为 "YYYY-MM-DD HH:MM:SS"。

        返回：
            {window, imsi, sources: [{key,label,ok,rows,error,truncated}]}

        ⚠ `msisdn` 是**必填**（2026-10-31 修 P0）。历史版本签名里没有它，
        四个源都按空号码查，于是「永远 0 条」被当成「用户没数据」。
        这里显式拒绝空号码，宁可 500 也不要静默返回全空 —— 静默的全空
        比报错危险得多：用户会据此在投诉工单里写「该时段无业务」。
        """
        if not str(msisdn or "").strip():
            raise ValueError("fetch_all 需要真实号码（msisdn 不能为空）")
        msisdn = str(msisdn).strip()

        st = datetime.strptime(start, FMT_SEC)
        et = _shift_end(datetime.strptime(end, FMT_SEC))
        s_ms, e_ms = _to_ms(st), _to_ms(et)

        def _wrap(key: str, fn, *args) -> Dict[str, Any]:
            """包一层：任何异常都变成「该源失败」，key 必须显式传进来 ——
            早期版本靠 `fn._src_key` 反射，绑定方法上没有这个属性，
            失败时 key 变成 "?"，前端按 key 取行就取不到（实测踩过）。"""
            try:
                out = fn(*args)
                out.setdefault("ok", True)
                out["key"] = key
                out["label"] = out.get("label") or _LABELS.get(key, key)
                return out
            except Exception as exc:                   # noqa: BLE001
                logger.warning("[vmax_diag] 源 %s 取数失败: %s", key, exc)
                return {"key": key, "label": _LABELS.get(key, key), "ok": False,
                        "rows": [], "truncated": False, "error": _humanize(exc)}

        results: Dict[str, Dict[str, Any]] = {}
        # 第一波：1300 + 1100 + 1301 并行（这三个都不依赖 IMSI）
        #
        # ⚠ 并发度必须是 1，不是 3（2026-10-31 实测踩过）：
        #   VmaxXdrClient 复用**同一个** CCA 门户会话，上游对同账号并发连接
        #   卡得很死（"The maximum number of connections for the user is reached"）。
        #   三个线程同时打上游 → 三个源全挂，比串行还慢。
        #   用 max_workers=1 + 把四个源都放进同一个池：顺序执行，但**每个源
        #   各自捕获异常**（这就是并行版想要的「单源失败不整页失败」），
        #   总耗时 ≈ 各源之和（实测 1300 12s + 1100 6s + 32 2s + 1301 1s ≈ 21s），
        #   前端那边有独立的 loading 态，20s 可接受。
        #   真要提速只能给上游多开账号 —— 属运维动作，不在本模块职责内。
        tasks = [("1300", self._src_1300, (msisdn, s_ms, e_ms)),
                 ("1100", self._src_1100, (msisdn, s_ms, e_ms)),
                 ("1301", self._src_1301, (msisdn, s_ms, e_ms))]
        with ThreadPoolExecutor(max_workers=1) as pool:
            futs = {pool.submit(_wrap, key, fn, *args): key
                    for key, fn, args in tasks}
            for fut in as_completed(futs, timeout=SOURCE_TIMEOUT):
                key = futs[fut]
                try:
                    results[key] = fut.result()
                except Exception as exc:               # noqa: BLE001
                    results[key] = {"key": key, "label": _LABELS.get(key, key),
                                    "ok": False, "rows": [], "truncated": False,
                                    "error": _humanize(exc)}

        imsi = self._pick_imsi(results.get("1300", {}).get("rows") or [],
                               results.get("1100", {}).get("rows") or [])

        # 第二波：RAN 需要 IMSI，必须串在 1300/1100 之后（拿不到 IMSI 就查不到）
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_wrap, "32", self._src_ran, msisdn, s_ms, e_ms, imsi or None)
            try:
                results["32"] = fut.result(timeout=SOURCE_TIMEOUT)
            except Exception as exc:                   # noqa: BLE001
                results["32"] = {"key": "32", "label": _LABELS["32"], "ok": False,
                                 "rows": [], "truncated": False, "error": _humanize(exc)}

        # 定序返回（前端按 key 取行，顺序只影响「已查数据源」那一行的观感）
        order = ["1300", "1100", "32", "1301"]
        sources = [results[k] for k in order if k in results]
        for s in sources:
            s.setdefault("error", "")
            s.setdefault("truncated", False)

        return {
            "window": {"start": start, "end": end},
            "imsi": imsi,
            "sources": sources,
        }


_LABELS = {
    "1300": "用户面话单 (1300)",
    "1100": "会话/信令面 (1100)",
    "32": "无线质量 (32 RAN)",
    "1301": "视频专表 (1301)",
}


def _humanize(exc: Exception) -> str:
    """把上游异常翻成能贴进工单的人话（保留原文便于排查）。"""
    msg = str(exc)
    low = msg.lower()
    if "maximum number of connections" in low:
        return "VMAX 门户会话已满（同账号并发连接达上限），请等待约 30 分钟再试"
    if "timeout" in low or "timed out" in low:
        return "上游查询超时（数据量较大或上游繁忙）"
    return msg or "未知错误"

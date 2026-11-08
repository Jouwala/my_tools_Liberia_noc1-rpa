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

四个源**串行**取（ThreadPoolExecutor max_workers=1）。实测单源耗时：1300 三页
~12s、1100 ~6s、32 单表 0.3~1.7s。串行总耗时 ≈21s，瓶颈是 1300（上游分页上限
200 条）。**并发度必须保持 1** —— 上游对同账号并发连接卡得很死，多开线程会让
多个源整批失败（见 `iter_sources()` 里 `_run_one` 的注释）。

## 渐进渲染（2026-11-07 P3-1）

`iter_sources()` 逐源产出事件，两条消费路径共用它、口径只有一份：
  - `fetch_all()`：一次排空再组装 —— 老接口 `GET /api/vmax-diagnosis` 用；
  - SSE 端点 `GET /api/vmax-diagnosis/stream`：每跑完一个源推一帧，前端先渲染
    1300 出来的分析，32 到了再补无线侧（失败时前端回退到老接口，行为不变）。
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional, Tuple

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

# ---------------------------------------------------------------------------
# 渐进渲染事件名（2026-11-07 P3-1）
# ---------------------------------------------------------------------------
# `iter_sources()` 逐源产出事件，SSE 端点（routers/vmax_diagnosis.py）
# 直接把事件名当 SSE 的 `event:` 字段，前端按事件增量渲染。
# 不引入枚举类，保持「事件名就是协议」这一层可读性。
SOURCE_EVENT = "source"     # data: 单个源的取数结果（与 fetch_all 里的一项同形）
DONE_EVENT = "done"         # data: {window, imsi}，四个源都跑完才发

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
    # ⚠ 2026-11-08 列头探查（get_xdrheader_info 实测）：
    # 分表真实列名带 $ 前缀（如 $procedure_status / $causetype），旧 COLS_1100
    # 写的 procedure_status / fail_cause / request_cause / interface 在列头里
    # **不存在**，query_table 的交集裁列（vmax_xdr_client.py:477-480）会静默
    # 丢掉它们——实查 1100 只返回 [start_time, cell, imsi] 3 列，1100 的可用性
    # 评分/语音 CSFB/账务分型此前全部在空字段上运行（评分恒 100、语音恒 none）。
    # 现改为真实列名，_src_1100 再做别名归一（前端契约不变）。
    COLS_1100 = [
        "imsi", "start_time", "apn",
        "$interface", "interface_name",
        "$procedure_type", "procedure_type_name",
        "$procedure_status", "procedure_status_name",
        "$request_cause_specific", "request_cause_specific_name",
        "request_cause_group_name",
        "$causetype", "$failure_cause_specific", "failure_cause_specific_name",
        "failure_cause_group_name",
        "cell", "cell_id", "site_id",
    ]
    # S6a（HSS 签名）：账务/订阅类信号的 XDR 出处。字段无余额/配额（OCS/Gy
    # 不在 XDR 表清单里），只有 Diameter 失败原因 $cause/cause_name + HSS 地址。
    COLS_1100_S6A = [
        "imsi", "start_time",
        "$interface", "interface_name",
        "$procedure_type", "procedure_type_name",
        "$procedure_status", "procedure_status_name",
        "$cause", "cause_name",
    ]
    # SGs（语音回落）：analyzeVoice 的 SGs 分支挂在 fact_pscp_sgs 上，
    # 只查 s1mme 时该分支恒为 0 —— 同批合并进来。
    COLS_1100_SGS = [
        "imsi", "start_time", "msisdn",
        "$interface", "interface_name",
        "$procedure_type", "procedure_type_name",
        "$procedure_status", "procedure_status_name",
        "$sgs_cause", "sgs_cause_name",
        "cell", "cell_id",
    ]
    COLS_1301 = ["start_time", "vmos", "resolution", "result"]
    COLS_RAN = [
        "btime", "serving_rsrp", "serving_rsrq", "ulsinr", "cqi",
        "cell", "cellname", "cell_name", "rat_name", "phr",
        # 2026-11-08 列头探查确证（fact_lte_uemr，49 列）：邻区五列 + serving_rsrq。
        # 前端 analyzeRadio 按 neighbor_ 前缀通用提取，此处按确证名收敛。
        "neighbor_rsrp", "neighbor_rsrq", "neighbor_cell_number",
        "neighbor_cell_pci", "neighbor_freq",
        "enbid", "pci", "measid",
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

    @staticmethod
    def _norm_1100_row(r: Dict[str, Any]) -> Dict[str, Any]:
        """分表真实列名 → 前端契约字段名（2026-11-08 列头探查后新增）。

        前端 vmaxDiagnosisRules.ts 读 procedure_status / procedure_type /
        request_cause / fail_cause / interface / cellname / cell / cellid，
        分表列头里是 $procedure_status / procedure_type_name /
        request_cause_specific_name / failure_cause_specific_name /
        interface_name / cell。这里只做别名归一，不改前端判据。
        取值优先级：显示名（文本，判据按文本匹配）→ ID 列原文。
        """
        def pick(*keys: str) -> str:
            for k in keys:
                v = r.get(k)
                if v not in (None, "", "-"):
                    return str(v)
            return ""
        out = dict(r)
        out["procedure_status"] = pick("procedure_status_name", "$procedure_status")
        out["procedure_type"] = pick("procedure_type_name", "$procedure_type")
        out["request_cause"] = pick("request_cause_specific_name",
                                     "$request_cause_specific", "sgs_cause_name", "$sgs_cause")
        out["fail_cause"] = pick("failure_cause_specific_name",
                                  "$failure_cause_specific", "$causetype",
                                  "cause_name", "$cause")
        out["interface"] = pick("interface_name", "$interface")
        out["cellname"] = pick("cellname", "cell")
        out["cellid"] = pick("cell_id", "cellid")
        return out

    def _src_1100(self, msisdn: str, start: str, end: str) -> Dict[str, Any]:
        """1100 = S1-MME 主表 + S6a 失败行 + SGs 行（2026-11-08）。

        - 主表 fact_pscp_s1mme：接入过程与 EMM/ESM 拒绝原因；
        - S6a fact_pscp_s6a：**只合并失败行**（HSS Diameter 拒绝是订阅/账务类
          信号；成功行不进，避免改动可用性分母口径）；
        - SGs fact_pscp_sgs：语音回落（analyzeVoice 的 SGs 分支挂在这张表，
          只查主表时恒为 0）；
        三表各自独立取数，单表失败只记日志不阻断（与其它源同纪律）。
        """
        rows, truncated = self._page_through(
            msisdn, "1100", "fact_pscp_s1mme", start, end, MAX_PAGES_1100,
            columns=self.COLS_1100)
        merged = [self._norm_1100_row(r) for r in rows]
        for table, cols, only_fail in (
                ("fact_pscp_s6a", self.COLS_1100_S6A, True),
                ("fact_pscp_sgs", self.COLS_1100_SGS, False)):
            try:
                extra, _ = self._page_through(
                    msisdn, "1100", table, start, end, 2, columns=cols)
            except Exception as exc:  # noqa: BLE001 - 单表失败不阻断主源
                logger.warning("[vmax_diag] 1100 辅表 %s 取数失败（忽略）: %s", table, exc)
                continue
            for r in extra:
                n = self._norm_1100_row(r)
                if only_fail and str(n.get("procedure_status", "")).upper() == "SUCCESS":
                    continue
                merged.append(n)
        return {"key": "1100", "label_key": "vmaxq.diag.src.1100",
                "label": "会话/信令面 (1100)", "rows": merged,
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
    def _run_one(self, pool, key: str, fn, *args) -> Dict[str, Any]:
        """在**复用**的单线程池里跑一个源，把超时/异常收敛成「该源失败」。

        为什么还要线程池（2026-11-07 P3-1）：
          `fut.result(timeout=SOURCE_TIMEOUT)` 是唯一能挡住上游挂死的办法
          （requests 自身超时在部分网络抖动下不生效）。池 max_workers=1 且
          整轮（1 个号码）复用：上一个源即使超时被放弃，它也仍占着这条线程，
          后续源排队 —— 保证对上游的**并发度恒为 1**（模块头纪律：上游同账号
          并发一超，多个源会整批失败，比串行还慢）。

        key 必须显式传进来 —— 早期版本靠 `fn._src_key` 反射，绑定方法上没有
        这个属性，失败时 key 变成 "?"，前端按 key 取行就取不到（实测踩过）。
        """
        try:
            fut = pool.submit(fn, *args)
            out = fut.result(timeout=SOURCE_TIMEOUT)
            out.setdefault("ok", True)
            out["key"] = key
            out["label"] = out.get("label") or _LABELS.get(key, key)
            return out
        except Exception as exc:                       # noqa: BLE001
            logger.warning("[vmax_diag] 源 %s 取数失败: %s", key, exc)
            return {"key": key, "label": _LABELS.get(key, key), "ok": False,
                    "rows": [], "truncated": False, "error": _humanize(exc)}

    def iter_sources(self, msisdn: str, start: str, end: str) -> Iterator[Tuple[str, Dict[str, Any]]]:
        """**逐源**产出 `(event, payload)` 的生成器（2026-11-07 P3-1）。

        事件序列（与 SSE 端点一一对应，见 routers/vmax_diagnosis.py）：

            ("source", {key,label,ok,rows,truncated,error})   × 4
            ("done",   {window, imsi})

        顺序固定 1300 → 1100 → 1301 → 32：32 依赖 1300/1100 解析出的 IMSI，
        必须最后（模块头纪律 2）。单源失败/超时只影响该源。

        为什么要有生成器：四个源串行总共 ≈21s（1300 约 12s 是瓶颈）。旧接口
        等 21s 才一次性返回，用户全程白屏；流式端点每跑完一个源就推一帧，
        前端能先渲染 1300 出来的分析，32 到了再补无线侧。

        ⚠ 与 fetch_all 共用本方法 —— 渐进渲染与一次性返回**同一套取数口径**，
        不要另写一份。
        """
        if not str(msisdn or "").strip():
            raise ValueError("fetch_all 需要真实号码（msisdn 不能为空）")
        msisdn = str(msisdn).strip()

        st = datetime.strptime(start, FMT_SEC)
        et = _shift_end(datetime.strptime(end, FMT_SEC))
        s_ms, e_ms = _to_ms(st), _to_ms(et)

        results: Dict[str, Dict[str, Any]] = {}
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            for key, fn, args in (("1300", self._src_1300, (msisdn, s_ms, e_ms)),
                                  ("1100", self._src_1100, (msisdn, s_ms, e_ms)),
                                  ("1301", self._src_1301, (msisdn, s_ms, e_ms))):
                out = self._run_one(pool, key, fn, *args)
                results[key] = out
                yield SOURCE_EVENT, out

            imsi = self._pick_imsi(results.get("1300", {}).get("rows") or [],
                                   results.get("1100", {}).get("rows") or [])
            out = self._run_one(pool, "32", self._src_ran,
                                msisdn, s_ms, e_ms, imsi or None)
            results["32"] = out
            yield SOURCE_EVENT, out

            yield DONE_EVENT, {"window": {"start": start, "end": end},
                               "imsi": imsi}
        finally:
            # wait=False：调用方中途放弃（浏览器断开/前端取消）时不要卡在
            # 一个可能挂住的上游线程上；已提交的那一个仍会跑完，但不会
            # 再把新的源排进队列（生成器已结束）。
            pool.shutdown(wait=False)

    def fetch_all(self, msisdn: str, start: str, end: str) -> Dict[str, Any]:
        """一次性取四个源。start/end 为 "YYYY-MM-DD HH:MM:SS"。

        返回：
            {window, imsi, sources: [{key,label,ok,rows,error,truncated}]}

        实现：把 `iter_sources()` 一次排空再按固定顺序组装（P3-1 重构，
        2026-11-07）。行为与原实现等价：单源失败不整页失败、定序
        [1300, 1100, 32, 1301]、每项补 error/truncated 默认值。

        ⚠ `msisdn` 是**必填**（2026-10-31 修 P0）。历史版本签名里没有它，
        四个源都按空号码查，于是「永远 0 条」被当成「用户没数据」。
        这里显式拒绝空号码，宁可 500 也不要静默返回全空 —— 静默的全空
        比报错危险得多：用户会据此在投诉工单里写「该时段无业务」。
        """
        results: Dict[str, Dict[str, Any]] = {}
        window = {"start": start, "end": end}
        imsi = ""
        for event, data in self.iter_sources(msisdn, start, end):
            if event == SOURCE_EVENT:
                results[data["key"]] = data
            elif event == DONE_EVENT:
                window = data.get("window") or window
                imsi = data.get("imsi") or ""

        # 定序返回（前端按 key 取行，顺序只影响「已查数据源」那一行的观感）
        order = ["1300", "1100", "32", "1301"]
        sources = [results[k] for k in order if k in results]
        for s in sources:
            s.setdefault("error", "")
            s.setdefault("truncated", False)

        return {"window": window, "imsi": imsi, "sources": sources}


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

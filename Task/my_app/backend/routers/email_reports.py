"""邮件报告文件 API —— 列出 email 类任务生成的最新报告文件（EmailReports 页面）

数据源：各邮件任务把「发送用的报告附件」落在本地 data/ 子目录，
本模块按任务声明若干扫描源（目录 + 文件名通配），返回每个源最新 N 个文件，
并提供带白名单校验的下载接口（只允许命中 patterns 且位于源目录内的文件）。

注意：按产品要求只返回文档类报告（xlsx/html），不返回图片（png）。
"""
import fnmatch
import json
import logging
import threading
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from backend.task_registry import TASK_SPECS

logger = logging.getLogger(__name__)
router = APIRouter(tags=["email_reports"])

_BASE = Path(__file__).resolve().parent.parent.parent

# ========== 扫描源定义 ==========
# id:        下载接口的 source_id（稳定标识，勿改）
# task_id:   归属的邮件任务（取注册表中的任务名展示）
# dir:       报告文件所在目录
# patterns:  glob 通配（只匹配报告文档，排除图片）
# label:     页面展示用的报告类型说明（zh / en）
_SOURCES = [
    dict(id="liberia_1h", task_id="liberia_email_1h",
         dir=_BASE / "data" / "eflow" / "tt_reports",
         patterns=["Liberia Orange Site Down hourly Report_*.xlsx"],
         label="Site Down 1H 报告", label_en="Site Down 1H Report"),
    dict(id="liberia_8h", task_id="liberia_email_8h",
         dir=_BASE / "data" / "eflow" / "tt_reports",
         patterns=["Liberia Orange Site Down 8 hours Report_*.xlsx"],
         label="Site Down 8H 报告", label_en="Site Down 8H Report"),
    dict(id="liberia_tt_summary", task_id="liberia_email_8h",
         dir=_BASE / "data" / "eflow" / "tt_reports",
         patterns=["Liberia Orange TT Summary Report_*.xlsx"],
         label="TT Summary 报告", label_en="TT Summary Report"),
    # 2026-10-04 新增：tt_mttr_report_generate 的产物（TTs and MTTR 月粒度组合图报表）。
    # 与三份 hourly/8h/summary 报告同目录，但不在 _cleanup_old_tt_reports 的清理名单里，
    # 体积由该任务自己的 KEEP_FILES 控制。
    # ⚠ patterns 必须与 services/tt_mttr_report.py 的 OUTPUT_PREFIX 保持一致：
    #   下载接口按 patterns 做白名单校验（见 _resolve_download_file），漏配会出现
    #   「文件列出来却下不动」。带 _ 的是任务每次生成的时间戳文件，
    #   不带 _ 的是此前人工核对用的同名文件，两者都要能下载。
    dict(id="tt_mttr", task_id="tt_mttr_report_generate",
         dir=_BASE / "data" / "eflow" / "tt_reports",
         patterns=["TTs and MTTR (Hour).xlsx", "TTs and MTTR (Hour)_*.xlsx"],
         label="TTs and MTTR 报表", label_en="TTs and MTTR Report"),
    dict(id="ms_contract", task_id="kpi_ms_contract",
         dir=_BASE / "data" / "ms_sla",
         patterns=["ZTE OLR MS Contract KPIs Achievements Daily Report_*.xlsx",
                   "ZTE OLR MS Contract KPIs Achievements Daily Report_*.html"],
         label="MS Contract KPIs 日报", label_en="MS Contract KPIs Daily Report"),
    dict(id="ms_wo_sla", task_id="kpi_ms_wo_sla",
         dir=_BASE / "data" / "ms_sla",
         patterns=["ZTE OLR MS WOs SLA Achievements Daily Report_*.xlsx",
                   "ZTE OLR MS WOs SLA Achievements Daily Report_*.html"],
         label="MS WOs SLA 日报", label_en="MS WOs SLA Daily Report"),
    dict(id="sp_spareparts", task_id="kpi_sp_spareparts",
         dir=_BASE / "data" / "sp_email",
         patterns=["SpareParts*.xlsx"],
         label="SpareParts 报告", label_en="SpareParts Report"),
    dict(id="sp_consumables", task_id="kpi_sp_consumables",
         dir=_BASE / "data" / "sp_email",
         patterns=["Comsumables*.xlsx"],
         label="Comsumables 报告", label_en="Comsumables Report"),
    dict(id="packet_loss", task_id="packet_loss_email",
         dir=_BASE / "data" / "packet_lost",
         patterns=["Packet_Loss_Status_Output Automation*.xlsx"],
         label="Packet Loss 日报", label_en="Packet Loss Daily Report"),
    dict(id="ran_availability", task_id="ran_ume_daily",
         dir=_BASE / "data" / "ran_ume",
         patterns=["Daily_Aailability_KPI.xlsx"],
         label="Network Availability 日报", label_en="Network Availability Daily Report"),
    dict(id="battery", task_id="battery_email",
         dir=_BASE / "backend" / "services" / "battary_kpi_fetch" / "output_socket",
         patterns=["battery_latest_*.xlsx"],
         label="Battery KPI 报告", label_en="Battery KPI Report"),
    # 2026-09-23：除 TT 规则表外，把另外两个 eFlow 规则收集任务的产物
    # （告警关联规则 / 推单配置规则）一并纳入本源的下载白名单，
    # 页面「eFlow 规则检查」页签因此可下载从 eFlow 获取的全部规则表。
    dict(id="eflow_tt_rules_check", task_id="eflow_tt_rules_check",
         dir=_BASE / "backend" / "services" / "eflow_rules",
         patterns=["eflow_tt_severity_correction*.xlsx", "MATCHING_REPORT*.md", "eflow_TT_rules.xlsx",
                   "eflow_alarm_rules*.xlsx", "eflow_push_rules*.xlsx"],
         label="eFlow TT 规则收集与匹配报告", label_en="eFlow TT Rules Collect & Match Report"),
    # 2026-10-23 新增：推单规则批量检查的产物（逐单规则判定 vs 实际派单）。
    # 只放本任务自己的产物 —— 规则表本身仍由上面的 eflow_tt_rules_check 源提供下载。
    dict(id="eflow_push_rules_check", task_id="eflow_push_rules_check",
         dir=_BASE / "backend" / "services" / "eflow_rules",
         patterns=["eflow_push_rules_check*.xlsx"],
         label="eFlow 推单规则检查表", label_en="eFlow Push Rules Check Sheet"),
]

_SOURCE_BY_ID = {s["id"]: s for s in _SOURCES}
# eflow_tt_rules_check 定时任务落盘的最新一次匹配摘要（run_eflow_tt_rules_check 写入）
_EFLOW_RULES_CHECK_JSON = _BASE / "backend" / "services" / "eflow_rules" / "eflow_tt_rules_check_latest.json"
_TASK_NAMES = {s["task_id"]: (s.get("name") or s["task_id"], s.get("name_en") or s["task_id"])
               for s in TASK_SPECS}

# eflow_tt_rules_check 页签的文件分类与展示名（2026-09-23 新增）
# kind=rule   —— 从 eFlow 直接收集的规则表（三个收集器各一份，供下载）
# kind=report —— 规则匹配检查的产物（级别矫正表 / 匹配报告）
# ⚠ pattern 必须与 _SOURCES 中 eflow_tt_rules_check 的 patterns 保持一致，
#   否则文件能列出却下载不了（下载接口按 patterns 做白名单校验，见 _resolve_download_file）。
_EFLOW_FILE_SPECS = [
    dict(pattern="eflow_TT_rules.xlsx", kind="rule",
         label="TT 级别矫正规则", label_en="TT Severity Rules"),
    dict(pattern="eflow_alarm_rules*.xlsx", kind="rule",
         label="告警关联规则", label_en="Alarm Correlation Rules"),
    # ⚠ 必须排在 `eflow_push_rules*.xlsx` **之前**：本函数是「第一个命中的规则说了算」，
    #   而 `eflow_push_rules_check.xlsx` 也命中 `eflow_push_rules*.xlsx`。
    #   放在后面会把推单检查表显示成「推单/配置规则」（2026-10-23 实测踩到）。
    dict(pattern="eflow_push_rules_check*.xlsx", kind="report",
         label="推单规则检查表", label_en="Push Rules Check Sheet"),
    dict(pattern="eflow_push_rules*.xlsx", kind="rule",
         label="推单/配置规则", label_en="Push / Config Rules"),
    dict(pattern="eflow_tt_severity_correction*.xlsx", kind="report",
         label="TT 级别矫正表", label_en="Severity Correction Sheet"),
    dict(pattern="MATCHING_REPORT*.md", kind="report",
         label="匹配检查报告", label_en="Matching Report"),
]

# eflow_tt_rules_check 的 TT 级下钻数据源（2026-10-23 新增）。
# 摘要 JSON 只有按规则聚合的数字，逐条 TT 明细在匹配器导出的矫正表里：
#   All_TT_Records / Matched_Rules / Severity_Changes 三个 sheet，列名与 _TT_DRILL_COLS 一一对应
#   （见 backend/services/eflow_rules/eflow_rules_matcher.py:454 export_outputs）。
# 下钻接口直接读这张表，保证「卡片上的数字」与「下钻弹窗的行数」严格同源 ——
# 不去查 eflow_tt 主库重算，否则同步延迟会让两边对不上。
_TT_CORRECTION_XLSX = _BASE / "backend" / "services" / "eflow_rules" / "eflow_tt_severity_correction.xlsx"

# 矫正表 → 前端字段的映射（顺序即弹窗列的先后顺序）
_TT_DRILL_COLS = [
    ("tt_no", "tt_no"), ("wo_no", "wo_no"), ("ticket_no", "ticket_no"),
    ("title", "title"), ("alarm_code", "alarm_code"),
    ("site_id", "site_id"), ("site_name", "site_name"),
    ("ne_name", "ne_name"), ("domain", "domain"),
    ("site_type", "site_type"), ("vip_site", "vip_site"),
    ("down_site_count", "down_site_count"),
    # 时间字段（2026-10-23 用户要求）：建单时间 / 告警发生 / 告警清除
    ("created_time", "created_time"),
    ("alarm_occur_time", "alarm_occur_time"),
    ("alarm_clear_time", "alarm_clear_time"),
    ("ticket_severity", "cur_severity"),
    ("Matched_Rule_ID", "rule_id"), ("Matched_Rule_Name", "rule_name"),
    ("New_Severity", "new_severity"), ("Severity_Changed", "changed"),
    ("Match_Details", "evidence"), ("status", "status"),
    # 站点拓扑属性（来自 eflow_site / master_site_db，不参与判定的 TRM 也一并展示）
    ("TRM_Type", "trm_type"),
    # 规则里用到的**全部**字段 —— 写的是判定时实际比较的值（已归一化）
    ("Rule_Field_alarmCode", "f_alarm_code"),
    ("Rule_Field_vipSite", "f_vip_site"),
    ("Rule_Field_hubSite", "f_hub_site"),
    ("Rule_Field_siteSubType", "f_site_subtype"),
    ("Rule_Field_assetType", "f_asset_type"),
    ("Rule_Field_netWorkType", "f_network_type"),
    ("Rule_Field_downstreamSites", "f_downstream_sites"),
    ("Rule_Field_alarmDescription", "f_alarm_description"),
]

# 下钻结果缓存：(矫正表 mtime_ns, size) -> 已转换的 dict 行列表。
# 为什么不缓存 DataFrame：pandas → dict 的转换才是每次请求的主要开销（1000 行 × 94 列），
# 缓存转换结果后单次下钻只剩内存过滤。任务每天 04:20 重写一次文件，缓存自然失效。
_DRILL_CACHE: dict = {}
_DRILL_LOCK = threading.Lock()


def _eflow_file_meta(filename: str, lang: str) -> dict:
    """按文件名判定 eFlow 页签文件的类别（rule/report）与展示名；未命中则回退为 report。"""
    for spec in _EFLOW_FILE_SPECS:
        if fnmatch.fnmatch(filename, spec["pattern"]):
            return {"kind": spec["kind"],
                    "label": spec["label_en"] if lang == "en" else spec["label"]}
    return {"kind": "report", "label": filename}


def _req_lang(request: Request) -> str:
    """从 Accept-Language 头推断语言（en 优先，其余回退 zh），与 tasks 路由一致。"""
    accept = (request.headers.get("Accept-Language") or "").lower()
    return "en" if accept.startswith("en") else "zh"


@router.get("/api/email-reports/latest")
def email_reports_latest(request: Request, limit: int = 1):
    """每个扫描源最新的 limit 个报告文件（默认 1，最大 10），按时间倒序。"""
    lang = _req_lang(request)
    limit = max(1, min(int(limit or 1), 10))
    reports = []
    for src in _SOURCES:
        d: Path = src["dir"]
        files = []
        if d.is_dir():
            for pat in src["patterns"]:
                try:
                    files.extend(d.glob(pat))
                except OSError as e:
                    logger.warning(f"扫描邮件报告目录失败 ({d}): {e}")
        files = [f for f in files if f.is_file()]
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        zh_name, en_name = _TASK_NAMES.get(src["task_id"], (src["task_id"], src["task_id"]))
        reports.append({
            "source_id": src["id"],
            "task_id": src["task_id"],
            "task_name": en_name if lang == "en" else zh_name,
            "label": src["label_en"] if lang == "en" else src["label"],
            "dir": str(d.relative_to(_BASE)).replace("\\", "/"),
            "files": [
                {
                    "name": f.name,
                    "size": f.stat().st_size,
                    "mtime": f.stat().st_mtime,
                }
                for f in files[:limit]
            ],
        })
    return {"reports": reports}


def _resolve_download_file(source_id: str, filename: str) -> Path:
    """下载接口的公共校验：源存在 + 文件名合法 + 命中白名单 + 真实位于源目录内。

    GET 与 HEAD 共用同一套判断，保证两个方法放行/拒绝的文件集合完全一致。
    """
    src = _SOURCE_BY_ID.get(source_id)
    if not src:
        raise HTTPException(status_code=404, detail=f"未知报告源: {source_id}")
    if any(ch in filename for ch in ("/", "\\")) or filename.startswith(".."):
        raise HTTPException(status_code=400, detail="非法文件名")
    if not any(fnmatch.fnmatch(filename, pat) for pat in src["patterns"]):
        raise HTTPException(status_code=403, detail="文件名不在报告白名单内")
    fpath = (src["dir"] / filename).resolve()
    if not fpath.is_file() or src["dir"].resolve() not in fpath.parents:
        raise HTTPException(status_code=404, detail="文件不存在")
    return fpath


@router.get("/api/email-reports/download/{source_id}/{filename:path}")
def email_reports_download(source_id: str, filename: str):
    """下载指定报告文件：仅放行命中源 patterns 且真实位于源目录内的文件。"""
    fpath = _resolve_download_file(source_id, filename)
    # RFC5987 编码文件名（含空格 / & 等特殊字符），保证浏览器下载名正确
    quoted = quote(filename)
    return FileResponse(
        fpath,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )


@router.head("/api/email-reports/download/{source_id}/{filename:path}", include_in_schema=False)
def email_reports_download_head(source_id: str, filename: str):
    """HEAD 版本：只回响应头，不回文件体（2026-09-21 新增）。

    背景：Starlette 不会拿 GET 处理器去处理 HEAD，所以这个下载地址对 HEAD 一律返回
    405（Allow: GET）。浏览器扩展（content_script.js）会拿页面上每个下载链接发 HEAD
    探测，控制台因此刷一堆 "405 Method Not Allowed / net::ERR_ABORTED"。
    这里复用 GET 的同一套校验，头部与 GET 保持一致（Content-Length / Last-Modified），
    但 body 为空 —— 既符合 HEAD 语义，也不产生任何文件传输开销。
    """
    from email.utils import formatdate

    fpath = _resolve_download_file(source_id, filename)
    quoted = quote(filename)
    st = fpath.stat()
    return Response(
        status_code=200,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
            "Content-Length": str(st.st_size),
            "Last-Modified": formatdate(st.st_mtime, usegmt=True),
        },
    )


@router.get("/api/email-reports/eflow_tt_rules_check")
def eflow_tt_rules_check_summary(request: Request):
    """eflow_tt_rules_check 页签：最新一次「规则收集 + 匹配检查」的摘要 + 可下载文件。

    摘要来自 eflow_tt_rules_check 定时任务落盘的 eflow_tt_rules_check_latest.json；
    文件列表复用 _SOURCES 中 eflow_tt_rules_check 源的扫描。

    返回的每个文件带 kind / label（见 _EFLOW_FILE_SPECS）：
      - kind=rule   ：从 eFlow 收集到的规则表 —— TT 级别矫正规则、告警关联规则、推单/配置规则
      - kind=report ：本次匹配检查的产物 —— 级别矫正表、匹配报告
    """
    lang = _req_lang(request)
    summary = None
    if _EFLOW_RULES_CHECK_JSON.is_file():
        try:
            summary = json.loads(_EFLOW_RULES_CHECK_JSON.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"读取 eflow_tt_rules_check 摘要失败: {e}")

    src = _SOURCE_BY_ID.get("eflow_tt_rules_check")
    files = []
    if src:
        d: Path = src["dir"]
        if d.is_dir():
            found = []
            for pat in src["patterns"]:
                try:
                    found.extend(d.glob(pat))
                except OSError as e:
                    logger.warning(f"扫描 eflow_tt_rules_check 目录失败 ({d}): {e}")
            found = [f for f in found if f.is_file()]
            files = []
            for f in found:
                st = f.stat()
                meta = _eflow_file_meta(f.name, lang)
                files.append({
                    "name": f.name,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "source_id": "eflow_tt_rules_check",
                    "kind": meta["kind"],
                    "label": meta["label"],
                })
            # 排序：规则表在前（按 _EFLOW_FILE_SPECS 顺序：TT → 告警 → 推单），检查产物在后；
            # 同组内按修改时间倒序（最新在前）。
            patterns = [s["pattern"] for s in _EFLOW_FILE_SPECS]

            def _order(item: dict) -> tuple:
                kind_rank = 0 if item["kind"] == "rule" else 1
                idx = next((i for i, pat in enumerate(patterns)
                            if fnmatch.fnmatch(item["name"], pat)), len(patterns))
                return (kind_rank, idx, -item["mtime"])
            files.sort(key=_order)
    # ---- 摘要与矫正表是否同源（2026-10-23）----
    # 摘要 JSON 由定时任务整链写出，与矫正表 xlsx 是同一次运行的产物；但两者是**两个文件**，
    # 只要中间有人单独跑过 eflow_rules_matcher（脚本形态，会重写 xlsx 却不更新 JSON），
    # 页面上的统计卡与下钻明细就会来自两次不同的运行 —— 实测出现过 624/19 对 1000/85。
    # 这里以 mtime 是否一致作为判据，不一致就让前端显式提示，而不是默默展示对不上的数字。
    # 旧摘要没有 correction_mtime 字段，此时不判定（回退为「未知」，不误报）。
    if summary and summary.get("correction_mtime") is not None and _TT_CORRECTION_XLSX.is_file():
        drift = abs(_TT_CORRECTION_XLSX.stat().st_mtime - float(summary["correction_mtime"])) > 1.0
        summary["correction_drift"] = drift
    return {"summary": summary, "files": files, "lang": lang}


def _clean_tt_value(v):
    """pandas 单元格值 → JSON 友好的值（NaN → None，整数值浮点 → int，其余转字符串）。"""
    if v is None:
        return None
    # pandas 读 Excel 会把数字读成 numpy 标量；同时避免 NaN / NaT 泄漏成 "nan" 字符串
    try:
        if v != v:  # NaN 自身不等于自身
            return None
    except Exception:  # noqa: BLE001 - 不可比较类型直接跳过
        pass
    if hasattr(v, "item"):
        try:
            v = v.item()
        except Exception:  # noqa: BLE001
            pass
    if isinstance(v, float):
        if v.is_integer():
            return int(v)
        return v
    if isinstance(v, (int, bool)):
        return v
    s = str(v).strip()
    return s or None


def _load_tt_drill_rows() -> list[dict]:
    """读取矫正表 All_TT_Records 并转换成前端字段；按 (mtime, size) 缓存。"""
    f = _TT_CORRECTION_XLSX
    if not f.is_file():
        raise HTTPException(status_code=404, detail="矫正表尚未生成，请先运行 eflow_tt_rules_check 任务")
    st = f.stat()
    key = (st.st_mtime_ns, st.st_size)
    with _DRILL_LOCK:
        cached = _DRILL_CACHE.get("key")
        if cached == key:
            return _DRILL_CACHE["rows"]
        try:
            import pandas as pd
            df = pd.read_excel(f, sheet_name="All_TT_Records")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"读取 TT 矫正表失败 ({f}): {e}")
            raise HTTPException(status_code=500, detail=f"读取矫正表失败: {e}")
        rows: list[dict] = []
        for rec in df.to_dict("records"):
            item = {}
            for src, dst in _TT_DRILL_COLS:
                item[dst] = _clean_tt_value(rec.get(src))
            item["changed"] = (item.get("changed") or "").upper() == "YES"
            rows.append(item)
        _DRILL_CACHE.clear()
        _DRILL_CACHE.update({"key": key, "rows": rows})
        return rows


def _norm_alarm_code(v) -> str:
    """告警码归一化，与匹配器 build_value_frame 的口径一致（见 eflow_rules_matcher.py:158-161）。"""
    if v is None:
        return ""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _rule_num(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


@router.get("/api/email-reports/eflow_tt_rules_check/drill")
def eflow_tt_rules_check_drill(
    metric: str,
    rule_id: int | None = None,
    sev_from: str | None = None,
    sev_to: str | None = None,
    alarm_code: str | None = None,
    limit: int = 2000,
    offset: int = 0,
):
    """eflow_tt_rules_check 页签的 TT 级下钻明细。

    metric 与页面上的数字一一对应，口径严格同源（全部来自同一份矫正表 All_TT_Records）：
      total    —— 总 TT 数
      matched  —— 命中任意规则（rule_id 非空）
      unmatched—— 未命中任何规则
      changed  —— 需要级别变更（Severity_Changed == YES）
      rule     —— 命中了 rule_id 指定的规则（需传 rule_id）
      rule_changed —— 命中了 rule_id 指定规则且需要级别变更
      shift    —— 变更方向 sev_from → sev_to（需同时传两者）

    可选叠加过滤：alarm_code（未匹配分布下钻用）。

    返回 meta.truncated：样本超过 limit 时**显式**告知，避免静默截断
    （AGENTS.md 三.1b：截断必须暴露，否则下钻行数会少于表格数字）。
    """
    limit = max(1, min(int(limit or 2000), 5000))
    offset = max(0, int(offset or 0))
    rows = _load_tt_drill_rows()

    # ---- 按 metric 选口径 ----
    if metric == "total":
        pool = rows
    elif metric == "matched":
        pool = [r for r in rows if r.get("rule_id") is not None]
    elif metric == "unmatched":
        pool = [r for r in rows if r.get("rule_id") is None]
    elif metric == "changed":
        pool = [r for r in rows if r.get("changed")]
    elif metric in ("rule", "rule_changed"):
        if rule_id is None:
            raise HTTPException(status_code=400, detail="metric=rule 需要 rule_id")
        target = _rule_num(rule_id)
        pool = [r for r in rows if _rule_num(r.get("rule_id")) == target]
        if metric == "rule_changed":
            pool = [r for r in pool if r.get("changed")]
    elif metric == "shift":
        if not sev_from or not sev_to:
            raise HTTPException(status_code=400, detail="metric=shift 需要 sev_from 与 sev_to")
        f_ = sev_from.strip().upper()
        t_ = sev_to.strip().upper()
        pool = [r for r in rows
                if (r.get("cur_severity") or "").upper() == f_
                and (r.get("new_severity") or "").upper() == t_
                and r.get("changed")]
    elif metric in ("cur_sev", "new_sev"):
        # 级别对照卡的两个下钻口径（2026-10-23）：
        #   cur_sev —— 按「单子实际级别」(ticket_severity) 筛
        #   new_sev —— 按「新规则建议级别」(New_Severity) 筛
        # 需要 sev 参数（P1/P2/P3/P4）。
        if not sev_from:
            raise HTTPException(status_code=400, detail="metric=cur_sev/new_sev 需要 sev_from")
        key = "cur_severity" if metric == "cur_sev" else "new_severity"
        want = sev_from.strip().upper()
        pool = [r for r in rows if (r.get(key) or "").upper() == want]
    else:
        raise HTTPException(status_code=400, detail=f"未知 metric: {metric}")

    # ---- 叠加过滤 ----
    if alarm_code:
        want = _norm_alarm_code(alarm_code)
        pool = [r for r in pool if _norm_alarm_code(r.get("alarm_code")) == want]

    total = len(pool)
    page = pool[offset:offset + limit]
    return {
        "metric": metric,
        "total": total,
        "rows": page,
        "meta": {
            "limit": limit,
            "offset": offset,
            "returned": len(page),
            "truncated": total > offset + len(page),
        },
    }


@router.get("/api/email-reports/eflow_tt_rules_check/severity_matrix")
def eflow_tt_rules_check_severity_matrix():
    """级别对照统计：单子「实际级别」vs「新规则建议级别」各自的 P1~P4 单数。

    供页面 Change direction 上方的对照卡使用（2026-10-23）。两者口径同源：
      · actual  ← 矫正表 `ticket_severity`（单子当前实际级别）
      · proposed← 矫正表 `New_Severity`（新规则判定出的级别）

    同时给出 4×4 交叉矩阵（actual → proposed），这样「P2 里有多少条被判成 P1」
    这种问题不用逐个点开也能一眼看到；每一格都可以用
    drill?metric=shift&sev_from=P2&sev_to=P1 下钻。

    `moved` 是实际发生了级别变化的总数（两列之差的一半），与页面 changed 卡口径一致。
    """
    rows = _load_tt_drill_rows()
    levels = ["P1", "P2", "P3", "P4"]
    actual = {lv: 0 for lv in levels}
    proposed = {lv: 0 for lv in levels}
    other = {"actual": 0, "proposed": 0}   # 空值 / 非 P1~P4 的值，单独计数不吞掉
    matrix: dict[str, dict[str, int]] = {}

    for r in rows:
        cur = (r.get("cur_severity") or "").strip().upper()
        new = (r.get("new_severity") or "").strip().upper()
        if cur in actual:
            actual[cur] += 1
        else:
            other["actual"] += 1
        if new in proposed:
            proposed[new] += 1
        else:
            other["proposed"] += 1
        ck = cur if cur in actual else "—"
        nk = new if new in proposed else "—"
        matrix.setdefault(ck, {})
        matrix[ck][nk] = matrix[ck].get(nk, 0) + 1

    return {
        "levels": levels,
        "actual": actual,
        "proposed": proposed,
        "other": other,
        "total": len(rows),
        "moved": sum(1 for r in rows if r.get("changed")),
        "matrix": matrix,
    }


@router.get("/api/email-reports/eflow_tt_rules_check/unmatched_dist")
def eflow_tt_rules_check_unmatched_dist(top: int = 10):
    """未匹配 TT 的主要分布（按 alarm_code / vip_site / site_type 聚合，取前 top 组）。

    与 MATCHING_REPORT.md 的「未匹配记录 → 主要分布」表同一口径
    （见 eflow_rules_matcher.py:361-374），供页面点开后按 alarm_code 再下钻。
    规则本身只取有 alarm_code 的 TT（get_eflow_tt_data，eflow_rules_matcher.py:54），
    所以这里不会出现空告警码分组。
    """
    top = max(1, min(int(top or 10), 50))
    rows = _load_tt_drill_rows()
    bucket: dict[tuple, int] = {}
    for r in rows:
        if r.get("rule_id") is not None:
            continue
        key = (_norm_alarm_code(r.get("alarm_code")),
               r.get("vip_site") or "", r.get("site_type") or "")
        bucket[key] = bucket.get(key, 0) + 1
    groups = sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return {
        "groups": [
            {"alarm_code": a or None, "vip_site": v or None, "site_type": s or None, "count": n}
            for (a, v, s), n in groups
        ],
        "unmatched_total": sum(bucket.values()),
        "distinct_groups": len(bucket),
    }


# ==================================================================
# eFlow TT Push Rules Check 页签（2026-10-23 新增）
# ------------------------------------------------------------------
# 与上面的 eflow_tt_rules_check 页签是**两件事**：
#   · 上面那个：级别规则（ttLevelRule），回答「这单该是什么级别」；
#   · 这一个  ：推单规则（ttPushOrderRule / FOAccept），回答「这单会不会自动派 WO、派给谁」。
# 两者样本口径完全一致（created_time 最新 N 条、alarm_code 非空），所以「总 TT」对得上。
# 数据源：eflow_push_rules_checker 每次运行导出的 eflow_push_rules_check.xlsx。
# 卡片数字与下钻明细**同源**（都读这张表），避免 json / xlsx 双写不同步。
# ==================================================================

_PUSH_CHECK_XLSX = _BASE / "backend" / "services" / "eflow_rules" / "eflow_push_rules_check.xlsx"
_PUSH_CHECK_JSON = _BASE / "backend" / "services" / "eflow_rules" / "eflow_push_rules_check_latest.json"

_PUSH_DRILL_COLS = [
    ("tt_no", "tt_no"), ("wo_no", "wo_no"), ("ticket_no", "ticket_no"),
    ("title", "title"), ("alarm_code", "alarm_code"), ("alarm_name", "alarm_name"),
    ("site_id", "site_id"), ("site_name", "site_name"), ("ne_name", "ne_name"),
    ("domain", "domain"), ("site_type", "site_type"), ("vip_site", "vip_site"),
    ("down_site_count", "down_site_count"), ("ticket_severity", "ticket_severity"),
    ("created_time", "created_time"),
    # 实际派单
    ("has_wo", "has_wo"), ("dispatch_person", "dispatch_person"),
    ("dispatch_group", "dispatch_group"), ("fo_operator", "fo_operator"),
    ("robot_handled", "robot_handled"),
    # 规则判定
    ("rule_id", "rule_id"), ("rule_name", "rule_name"),
    ("rule_builds_wo", "rule_builds_wo"), ("target_handler", "target_handler"),
    ("push_path", "push_path"), ("auto_operator", "auto_operator"),
    ("evidence", "evidence"),
    # 分类
    ("category", "category"), ("diff_kind", "diff_kind"),
]

_PUSH_CACHE: dict = {}
_PUSH_LOCK = threading.Lock()


def _norm_bool(v) -> bool:
    """Excel / JSON 里的布尔可能读成 'True' / 'FALSE' / 1 —— 统一成 Python bool。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).strip().lower() in ("true", "1", "yes", "y")


def _load_push_rows() -> list[dict]:
    """读推单检查表 All_TT_Records → 前端字段；按 (mtime, size) 缓存。"""
    f = _PUSH_CHECK_XLSX
    if not f.is_file():
        raise HTTPException(status_code=404,
                            detail="推单检查表尚未生成，请先运行 eflow_push_rules_check 任务")
    st = f.stat()
    key = (st.st_mtime_ns, st.st_size)
    with _PUSH_LOCK:
        if _PUSH_CACHE.get("key") == key:
            return _PUSH_CACHE["rows"]
        try:
            import pandas as pd
            df = pd.read_excel(f, sheet_name="All_TT_Records")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"读取推单检查表失败 ({f}): {e}")
            raise HTTPException(status_code=500, detail=f"读取推单检查表失败: {e}")
        rows: list[dict] = []
        for rec in df.to_dict("records"):
            item = {dst: _clean_tt_value(rec.get(src)) for src, dst in _PUSH_DRILL_COLS}
            for k in ("has_wo", "robot_handled", "rule_builds_wo"):
                item[k] = _norm_bool(rec.get(k))
            item["rule_id"] = _clean_tt_value(rec.get("rule_id"))
            rows.append(item)
        _PUSH_CACHE.clear()
        _PUSH_CACHE.update({"key": key, "rows": rows})
        return rows


@router.get("/api/email-reports/eflow_push_rules_check")
def eflow_push_rules_check_summary(request: Request):
    """推单规则检查页签：最新一次摘要 + 可下载文件 + 可用快照列表。

    摘要来自定时任务落盘的 eflow_push_rules_check_latest.json；
    快照列表来自 push_rules_snapshots/（页面「两次运行对比」用）。
    """
    lang = _req_lang(request)
    summary = None
    if _PUSH_CHECK_JSON.is_file():
        try:
            summary = json.loads(_PUSH_CHECK_JSON.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"读取 eflow_push_rules_check 摘要失败: {e}")

    # 摘要与检查表是否同源（同 correction_drift 思路）：卡片数字来自 JSON、
    # 下钻明细来自 xlsx，中间若有人单独跑过 checker 就会错位，必须显式提示。
    if summary and summary.get("generated_ts") and _PUSH_CHECK_XLSX.is_file():
        summary["sheet_drift"] = (
            _PUSH_CHECK_XLSX.stat().st_mtime - float(summary["generated_ts"])) > 1.0

    files = []
    src = _SOURCE_BY_ID.get("eflow_push_rules_check")
    if src and src["dir"].is_dir():
        found = []
        for pat in src["patterns"]:
            try:
                found.extend(src["dir"].glob(pat))
            except OSError as e:
                logger.warning(f"扫描推单检查产物失败: {e}")
        for f in sorted(found, key=lambda p: p.stat().st_mtime, reverse=True):
            if not f.is_file():
                continue
            st = f.stat()
            files.append({
                "name": f.name, "size": st.st_size, "mtime": st.st_mtime,
                "source_id": "eflow_push_rules_check",
                "label": "推单规则检查表" if lang == "zh" else "Push Rules Check Sheet",
            })

    runs = []
    try:
        from backend.services.eflow_rules.eflow_push_rules_checker import list_snapshots
        runs = list_snapshots()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"读取推单检查快照失败: {e}")

    return {"summary": summary, "files": files, "runs": runs, "lang": lang}


@router.get("/api/email-reports/eflow_push_rules_check/drill")
def eflow_push_rules_check_drill(
    metric: str,
    rule_id: int | None = None,
    diff_kind: str | None = None,
    alarm_code: str | None = None,
    limit: int = 2000,
    offset: int = 0,
):
    """推单规则检查页签的 TT 级下钻。

    metric 与页面数字一一对应（全部来自同一份检查表 All_TT_Records）：
      total / correct / mismatch / undecidable / unmatched —— 分类卡
      rule      —— 命中了 rule_id 指定规则（需传 rule_id）
      rule_bad  —— 同上，且分类为 mismatch
      diff      —— 指定差异子类型（需传 diff_kind，如 should_have_wo）
      has_wo / no_wo —— 实际有 WO / 无 WO

    返回 meta.truncated：样本超过 limit 时**显式**告知（AGENTS.md 三.1b）。
    """
    limit = max(1, min(int(limit or 2000), 5000))
    offset = max(0, int(offset or 0))
    rows = _load_push_rows()

    if metric in ("total", "correct", "mismatch", "undecidable", "unmatched"):
        pool = rows if metric == "total" else [r for r in rows if r.get("category") == metric]
    elif metric in ("rule", "rule_bad"):
        if rule_id is None:
            raise HTTPException(status_code=400, detail="metric=rule 需要 rule_id")
        target = _rule_num(rule_id)
        pool = [r for r in rows if _rule_num(r.get("rule_id")) == target]
        if metric == "rule_bad":
            pool = [r for r in pool if r.get("category") == "mismatch"]
    elif metric == "diff":
        pool = [r for r in rows if r.get("diff_kind") == (diff_kind or "")]
    elif metric == "has_wo":
        pool = [r for r in rows if r.get("has_wo")]
    elif metric == "no_wo":
        pool = [r for r in rows if not r.get("has_wo")]
    else:
        raise HTTPException(status_code=400, detail=f"未知 metric: {metric}")

    if alarm_code:
        want = _norm_alarm_code(alarm_code)
        pool = [r for r in pool if _norm_alarm_code(r.get("alarm_code")) == want]

    total = len(pool)
    page = pool[offset:offset + limit]
    return {
        "metric": metric,
        "total": total,
        "rows": page,
        "meta": {"limit": limit, "offset": offset, "returned": len(page),
                 "truncated": total > offset + len(page)},
    }


@router.get("/api/email-reports/eflow_push_rules_check/unmatched_dist")
def eflow_push_rules_check_unmatched_dist(top: int = 10, category: str = "unmatched"):
    """未命中 / 无法判定 的 TT 主要分布（按 alarm_code + 站型聚合）。

    口径与 eflow_tt_rules_check 的 unmatched_dist 一致，供点开后按 alarm_code 再下钻。
    """
    top = max(1, min(int(top or 10), 50))
    rows = _load_push_rows()
    bucket: dict[tuple, int] = {}
    for r in rows:
        if r.get("category") != category:
            continue
        key = (_norm_alarm_code(r.get("alarm_code")), r.get("site_type") or "")
        bucket[key] = bucket.get(key, 0) + 1
    groups = sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return {
        "category": category,
        "groups": [{"alarm_code": a or None, "site_type": s or None, "count": n}
                   for (a, s), n in groups],
        "total": sum(bucket.values()),
        "distinct_groups": len(bucket),
    }


@router.get("/api/email-reports/eflow_push_rules_check/compare")
def eflow_push_rules_check_compare(from_id: str, to_id: str):
    """对比两次运行快照：逐单判定变化 + 逐规则命中数变化。

    样本窗口会移动（新单进来 / 老单滑出），所以响应里把「变化」与
    「只在某一侧出现」分开给，避免把新增样本误读成判定变化。
    """
    try:
        from backend.services.eflow_rules.eflow_push_rules_checker import compare_snapshots
        return compare_snapshots(from_id, to_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"推单检查快照对比失败: {e}")
        raise HTTPException(status_code=500, detail=f"快照对比失败: {e}")

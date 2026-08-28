"""邮件报告文件 API —— 列出 email 类任务生成的最新报告文件（EmailReports 页面）

数据源：各邮件任务把「发送用的报告附件」落在本地 data/ 子目录，
本模块按任务声明若干扫描源（目录 + 文件名通配），返回每个源最新 N 个文件，
并提供带白名单校验的下载接口（只允许命中 patterns 且位于源目录内的文件）。

注意：按产品要求只返回文档类报告（xlsx/html），不返回图片（png）。
"""
import json
import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

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
    dict(id="eflow_tt_rules_check", task_id="eflow_tt_rules_check",
         dir=_BASE / "backend" / "services" / "eflow_rules",
         patterns=["eflow_tt_severity_correction*.xlsx", "MATCHING_REPORT*.md", "eflow_TT_rules.xlsx"],
         label="eFlow TT 规则收集与匹配报告", label_en="eFlow TT Rules Collect & Match Report"),
]

_SOURCE_BY_ID = {s["id"]: s for s in _SOURCES}
# eflow_tt_rules_check 定时任务落盘的最新一次匹配摘要（run_eflow_tt_rules_check 写入）
_EFLOW_RULES_CHECK_JSON = _BASE / "backend" / "services" / "eflow_rules" / "eflow_tt_rules_check_latest.json"
_TASK_NAMES = {s["task_id"]: (s.get("name") or s["task_id"], s.get("name_en") or s["task_id"])
               for s in TASK_SPECS}


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


@router.get("/api/email-reports/download/{source_id}/{filename:path}")
def email_reports_download(source_id: str, filename: str):
    """下载指定报告文件：仅放行命中源 patterns 且真实位于源目录内的文件。"""
    import fnmatch

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
    # RFC5987 编码文件名（含空格 / & 等特殊字符），保证浏览器下载名正确
    quoted = quote(filename)
    return FileResponse(
        fpath,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )


@router.get("/api/email-reports/eflow_tt_rules_check")
def eflow_tt_rules_check_summary(request: Request):
    """eflow_tt_rules_check 页签：最新一次「规则收集 + 匹配检查」的摘要 + 可下载文件。

    摘要来自 eflow_tt_rules_check 定时任务落盘的 eflow_tt_rules_check_latest.json；
    文件列表复用 _SOURCES 中 eflow_tt_rules_check 源的扫描
    （规则 eflow_TT_rules.xlsx / 矫正表 eflow_tt_severity_correction.xlsx / 报告 MATCHING_REPORT.md）。
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
            found.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            files = [
                {
                    "name": f.name,
                    "size": f.stat().st_size,
                    "mtime": f.stat().st_mtime,
                    "source_id": "eflow_tt_rules_check",
                }
                for f in found
            ]
    return {"summary": summary, "files": files, "lang": lang}

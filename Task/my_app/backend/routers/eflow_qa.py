# -*- coding: utf-8 -*-
"""
eflow_qa.py - eFlow 知识库 API
==============================
知识库源目录：D:\\01_RPA\\Task\\eflow_Q&A（可用环境变量 EFLOW_QA_DIR 覆盖）。
纯只读：列目录树 / 读单篇 Markdown / 全文检索，不做任何写操作。

- GET /api/eflow-qa/tree                文档树（含 front-matter 的 状态/来源）
- GET /api/eflow-qa/doc?path=xxx.md     读单篇（返回原文 + front-matter + 标题）
- GET /api/eflow-qa/search?q=词1 词2    全文检索（文件级 AND，行级命中高亮）

路径安全：只允许 .md 后缀，resolve 后必须位于知识库根目录内（防目录穿越）。
"""
import logging
import os
import re
import threading
import time
from datetime import timezone
from pathlib import Path
from typing import Dict, Tuple

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eflow-qa", tags=["eflow-qa"])

# 知识库根目录：默认 Task/eflow_Q&A（本文件位于 my_app/backend/routers/ 下，
# parents[3] = Task 目录）。迁移部署时用 EFLOW_QA_DIR 覆盖。
_KB_ROOT = Path(
    os.environ.get(
        "EFLOW_QA_DIR",
        str(Path(__file__).resolve().parents[3] / "eflow_Q&A"),
    )
).resolve()

# front-matter 里我们关心的字段（中文键，与 CONTRIBUTING.md 规范一致）
_FM_KEYS = ("状态", "来源", "更新日期", "标签")
# 检索时跳过的目录（模板与脚本，正文阅读场景无意义）
_SKIP_DIRS = {"_templates", "tools", "__pycache__", ".git"}


def _parse_front_matter(text: str) -> tuple[dict, str]:
    """解析 YAML front-matter（--- 包裹的 key: value），返回 (fm, 正文)。"""
    fm: dict = {}
    body = text
    if text.startswith("---"):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    k = k.strip()
                    v = v.strip().strip("\"'")
                    if k:
                        fm[k] = v
            body = text[m.end():]
    return fm, body


def _doc_title(path: Path, fm: dict) -> str:
    """标题优先级：front-matter 标题 > 正文一级标题 > 文件名。"""
    if fm.get("标题"):
        return fm["标题"]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(4096)
    except OSError:
        head = ""
    for line in head.splitlines():
        s = line.strip()
        if s.startswith("# ") and not s.startswith("## "):
            return s[2:].strip()
    return path.stem


def _iter_md_files(lang: str = "zh"):
    """遍历知识库 .md（按路径排序，跳过模板/脚本目录）。

    双语约定：英文版 = 同名 `.en.md`（如 README.md → README.en.md）。
    - lang=zh：只返回中文原文（排除全部 .en.md）；
    - lang=en：同名文档优先英文版，未翻译的回退中文原文，同一文档只出一条。
    """
    if not _KB_ROOT.is_dir():
        return
    zh_files: dict[str, Path] = {}
    en_files: dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(_KB_ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            if not fn.lower().endswith(".md"):
                continue
            p = Path(dirpath) / fn
            rel = p.relative_to(_KB_ROOT).as_posix()
            if rel.lower().endswith(".en.md"):
                en_files[rel[:-6] + ".md"] = p
            else:
                zh_files[rel] = p
    if lang == "en":
        merged = {**zh_files, **en_files}
        yield from (merged[k] for k in sorted(merged))
    else:
        yield from (zh_files[k] for k in sorted(zh_files))


def _safe_rel_path(rel: str) -> Path:
    """校验相对路径：仅 .md、resolve 后必须在根目录内。"""
    rel = (rel or "").strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        raise HTTPException(status_code=400, detail="非法路径")
    p = (_KB_ROOT / rel).resolve()
    try:
        p.relative_to(_KB_ROOT)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径越界")
    if p.suffix.lower() != ".md" or not p.is_file():
        raise HTTPException(status_code=404, detail=f"文档不存在: {rel}")
    return p


@router.get("/tree")
def get_tree(lang: str = Query("zh", pattern="^(zh|en)$", description="zh=中文原文；en=英文版优先，未翻译回退中文")):
    """知识库文档树：相对路径 / 标题 / front-matter 状态来源 / 大小 / 修改时间。"""
    items = []
    for p in _iter_md_files(lang):
        try:
            st = p.stat()
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm, _ = _parse_front_matter(raw)
        items.append({
            "path": p.relative_to(_KB_ROOT).as_posix(),
            "title": _doc_title(p, fm),
            "status": fm.get("状态", ""),
            "source": fm.get("来源", ""),
            "size": st.st_size,
            "mtime": int(st.st_mtime),
        })
    return {"root": str(_KB_ROOT), "count": len(items), "items": items}


@router.get("/doc")
def get_doc(path: str = Query(..., description="相对知识库根目录的 .md 路径")):
    """读取单篇文档：front-matter + 标题 + 原始 Markdown 正文。"""
    p = _safe_rel_path(path)
    raw = p.read_text(encoding="utf-8", errors="replace")
    fm, body = _parse_front_matter(raw)
    return {
        "path": p.relative_to(_KB_ROOT).as_posix(),
        "title": _doc_title(p, fm),
        "front_matter": fm,
        "content": body,
        "mtime": int(p.stat().st_mtime),
    }


@router.get("/search")
def search(
    q: str = Query(..., min_length=1, description="检索词，空格分隔为 AND"),
    lang: str = Query("zh", pattern="^(zh|en)$", description="检索范围语言，与 /tree 一致"),
):
    """全文检索：文件级 AND（所有词都出现才命中），返回行级匹配与上下文。"""
    terms = [t for t in re.split(r"\s+", q.strip()) if t]
    if not terms:
        return {"terms": [], "hits": []}
    lterms = [t.lower() for t in terms]
    hits = []
    t0 = time.time()
    for p in _iter_md_files(lang):
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        low = raw.lower()
        if not all(t in low for t in lterms):
            continue
        fm, body = _parse_front_matter(raw)
        # 行级匹配：每个词取前若干条命中行（带行号）
        line_matches: dict[int, list[str]] = {}
        for i, line in enumerate(body.splitlines(), start=1):
            ll = line.lower()
            matched = [t for t in lterms if t in ll]
            if matched:
                line_matches[i] = matched
        # 汇总每个词的命中行号（截断防超长）
        term_lines = {t: [] for t in lterms}
        for ln in sorted(line_matches):
            for t in line_matches[ln]:
                if len(term_lines[t]) < 8:
                    term_lines[t].append(ln)
        total = sum(len(v) for v in term_lines.values())
        if total == 0:
            continue
        # 展示片段：命中行号附近的原文（去 front-matter 后）
        lines = body.splitlines()
        snippets = []
        for ln in sorted(line_matches)[:6]:
            s = lines[ln - 1].strip()
            if len(s) > 160:
                # 截取围绕第一个命中的窗口
                pos = min((s.lower().find(t) for t in line_matches[ln] if s.lower().find(t) >= 0), default=0)
                start = max(0, pos - 60)
                s = ("…" if start > 0 else "") + s[start:start + 160] + "…"
            snippets.append({"line": ln, "text": s})
        hits.append({
            "path": p.relative_to(_KB_ROOT).as_posix(),
            "title": _doc_title(p, fm),
            "status": fm.get("状态", ""),
            "match_count": total,
            "term_lines": {terms[lterms.index(t)]: v for t, v in term_lines.items()},
            "snippets": snippets,
        })
    hits.sort(key=lambda h: -h["match_count"])
    return {"terms": terms, "root": str(_KB_ROOT), "elapsed_ms": int((time.time() - t0) * 1000), "hits": hits}


# ------------------------- TT 工单分析（复用知识库 tools/inspect_tt.py） -------------------------

_INSPECT_LOADER = {"mod": None}


def _load_inspect_module():
    """动态加载知识库 tools/inspect_tt.py，与 CLI 共用同一份分析实现。"""
    mod = _INSPECT_LOADER["mod"]
    if mod is not None:
        return mod
    import importlib.util
    path = _KB_ROOT / "tools" / "inspect_tt.py"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"分析模块不存在: {path}")
    spec = importlib.util.spec_from_file_location("eflow_qa_inspect_tt", path)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=500, detail="加载 inspect_tt.py 失败")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _INSPECT_LOADER["mod"] = mod
    return mod


def _tt_context(tt_clean: str):
    """TT 分析上下文：本地库查告警，未命中则按 alarm_id 直查 eFlow 兜底。

    返回 (report, alarm_lookup)：
      report       analyze_tt 结构；若走了 eFlow 兜底，alarm / skill_prompt 已回填
      alarm_lookup {"mode": local|eflow|none|not_found_ticket, "source", "elapsed_sec",
                    "error", "cached"} 或 None（工单未找到）
    """
    mod = _load_inspect_module()
    report = mod.analyze_tt(tt_clean, str(mod.DEFAULT_DB))
    if not report.get("found"):
        return report, None
    if (report.get("alarm") or {}).get("found"):
        # report["aid"] 已由 analyze_tt 注入（本地告警行的 AID 列）
        return report, {"mode": "local", "source": report["alarm"]["source"],
                        "elapsed_sec": 0.0, "error": None, "cached": False}
    aid = report.get("alarm_id") or ""
    if not aid:
        return report, {"mode": "none", "source": "", "elapsed_sec": 0.0,
                        "error": "工单没有 alarm_id，无法查告警表", "cached": False}

    from backend.services import eflow_alarm_query
    occur = mod.parse_dt((report.get("timing") or {}).get("alarm_occur_time"))
    live = eflow_alarm_query.find_alarm_by_id(aid, occur_time=occur)
    info = {"mode": "eflow", "source": live.get("source") or "",
            "elapsed_sec": live.get("elapsed_sec"), "error": live.get("error"),
            "cached": bool(live.get("cached"))}
    if live.get("found"):
        report["alarm"] = mod.build_alarm_block(live["row"], live["source"])
        # eFlow 活查行的 AID 列（UME 告警 ID，形如 1788788666535），
        # 供 RAN UME 告警分析按数字 Alarm ID 兜底查询
        report["aid"] = mod.num_tail(str(live["row"].get("aid") or "").strip())
        report["skill_prompt"] = mod.build_skill_prompt(
            report.get("tt_prompt_fields") or {}, live["row"])
    else:
        info["mode"] = "miss"
    return report, info


@router.get("/tt-alarm")
def tt_alarm(tt: str = Query(..., min_length=2, max_length=64, description="TT 单号")):
    """TT 告警主信息：本地 realtime_alarm/history_alarm 未命中时直查 eFlow 兜底。

    页面在本地查不到时单独调本端点（eFlow 活查较慢），其余块不必等它。
    """
    tt_clean = tt.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_\-]+", tt_clean):
        raise HTTPException(status_code=400, detail="单号格式非法")
    report, info = _tt_context(tt_clean)
    return {"report": report, "alarm": report.get("alarm"),
            "skill_prompt": report.get("skill_prompt"), "alarm_lookup": info}


# ------------------------- TT → AID → RAN UME 处理建议 -------------------------

_UME_SUG_CACHE: Dict[str, Tuple[float, dict]] = {}
_UME_SUG_LOCK = threading.Lock()
_UME_SUG_TTL_HIT = 300   # UME 命中缓存 5 分钟
_UME_SUG_TTL_MISS = 60   # 无 AID / UME 未命中缓存 60 秒


@router.get("/tt-ume-suggestion")
def tt_ume_suggestion(tt: str = Query(..., min_length=2, max_length=64, description="TT 单号")):
    """TT 单 → 告警 AID → RAN UME 处理建议（供「TT 快速分析」内嵌展示）。

    轻量链路（不查历史告警列表，只拿告警详情 + 处理建议）：
      1. 先按告警行的 AID 作为数字 Alarm ID 直查 UME；
      2. eFlow 与 UME 的告警编号分属两套体系（实测 UME 历史接口的 id 过滤
         只认 UME 自身编号），直查不中时改用 站点名 + 告警发生时刻 关联
         —— 同一条底层告警在两边的 alarmraisedtime 毫秒值一致。
    """
    tt_clean = tt.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_\-]+", tt_clean):
        raise HTTPException(status_code=400, detail="单号格式非法")

    mod = _load_inspect_module()
    report, _info = _tt_context(tt_clean)
    if not report.get("found"):
        return {"found": False, "tt_no": tt_clean, "aid": "", "ume": None,
                "error": report.get("error") or "工单未找到"}

    aid = str(report.get("aid") or "").strip()
    site_name = str(report.get("site_name") or "").strip()
    occur = mod.parse_dt((report.get("timing") or {}).get("alarm_occur_time"))
    raised_ms = int(occur.replace(tzinfo=timezone.utc).timestamp() * 1000) if occur else None

    cache_key = aid or f"{site_name}|{raised_ms}"
    if not aid and not (site_name and raised_ms):
        return {"found": True, "tt_no": tt_clean, "aid": "", "ume": None,
                "error": "告警记录中没有 AID，且缺少站点/发生时刻，无法查询 RAN UME 建议"}

    with _UME_SUG_LOCK:
        ent = _UME_SUG_CACHE.get(cache_key)
        if ent:
            ts, res = ent
            ttl = _UME_SUG_TTL_HIT if (res.get("ume") or {}).get("ok") else _UME_SUG_TTL_MISS
            if time.time() - ts < ttl:
                return dict(res, cached=True)

    from backend.services.ran_ume import ran_ume_alarm_service as ume_svc
    ume = None
    if aid.isdigit():
        ume = ume_svc.lookup_alarm(aid, days=30, limit=50, with_history=False)
        if not ume.get("ok"):
            ume = None
    if ume is None:
        ume = ume_svc.find_alarm_by_event(site_name, raised_ms or 0, with_history=False)
    ume["strategy"] = "site_time" if ume.get("match") == "site_time" else "alarm_id"

    out = {"found": True, "tt_no": tt_clean, "aid": aid, "ume": ume, "cached": False}
    with _UME_SUG_LOCK:
        _UME_SUG_CACHE[cache_key] = (time.time(), out)
    return out


# ------------------------- RAN UME 告警分析（Alarm Key → 详情/建议/历史） -------------------------

@router.get("/ume-alarm")
def ume_alarm(
    alarm_id: str = Query(..., min_length=4, max_length=256,
                          description="Alarm Key（UME 告警唯一串，形如 uuid---aid@...@...@...@...）或数字 Alarm ID"),
    days: int = Query(30, ge=1, le=180, description="历史告警回看天数"),
    limit: int = Query(50, ge=1, le=200, description="历史告警返回条数"),
    history: int = Query(1, ge=0, le=1, description="1=同时查历史告警；0=只查详情与建议"),
):
    """按 Alarm Key 从 RAN UME 取告警详情 + 处理建议 + 同站点/同小区历史告警。

    链路（见 backend/services/ran_ume/url_alarm_suggestion.txt 抓包）：
      POST /api/fm-active/v1/activealarms/alarmkey  → alarmcode / restype / 站点小区字段
      POST /api/fm-active/v1/suggestions            → 处理建议
      POST /api/fm-history/v1/hisalarms/pageinfo    → 历史告警（positionname 过滤）
    """
    from backend.services.ran_ume.ran_ume_alarm_service import lookup_alarm
    res = lookup_alarm(alarm_id.strip(), days=days, limit=limit, with_history=bool(history))
    if not res.get("ok"):
        # 上游失败仍返回 200，由前端展示错误，避免整个页面报错
        logger.warning("UME 告警查询失败: %s", res.get("error"))
    return res


@router.get("/inspect-tt")
def inspect_tt(tt: str = Query(..., min_length=2, max_length=64, description="TT 单号")):
    """输入 TT 单号，直接输出派单依据分析（工单字段 / 时间差 / 根因归属分布）。

    分析逻辑与 `python tools/inspect_tt.py <单号>` 完全同源（analyze_tt）。
    """
    tt_clean = tt.strip().upper()
    # 单号只允许字母数字与 - _，防注入（内部查询本就参数化，这里再加一层白名单）
    if not re.fullmatch(r"[A-Z0-9_\-]+", tt_clean):
        raise HTTPException(status_code=400, detail="单号格式非法")
    mod = _load_inspect_module()
    # 本端点为同步 def，FastAPI 已自动放入线程池执行，直接调用即可
    report = mod.analyze_tt(tt_clean, str(mod.DEFAULT_DB))
    return {"report": report}


@router.get("/tt-ai")
def tt_ai(tt: str = Query(..., min_length=2, max_length=64, description="TT 单号")):
    """TT 单 AI 分析：查库拿告警主信息 → 拼技能入参 → 调 Open WebUI「TT单分析」技能。

    返回 report（同 /inspect-tt）与 ai（结论 / 模型 / 耗时 / 入参）。
    """
    tt_clean = tt.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_\-]+", tt_clean):
        raise HTTPException(status_code=400, detail="单号格式非法")
    report, info = _tt_context(tt_clean)
    if not report.get("found"):
        return {"report": report, "ai": None}

    from backend.services import openwebui_client
    t0 = time.time()
    ai = openwebui_client.analyze_tt(report.get("skill_prompt") or "")
    ai["prompt"] = report.get("skill_prompt", "")
    ai["alarm_source"] = (report.get("alarm") or {}).get("source", "")
    ai["alarm_mode"] = (info or {}).get("mode", "")
    ai["elapsed_total_sec"] = round(time.time() - t0, 2)
    return {"report": report, "ai": ai}

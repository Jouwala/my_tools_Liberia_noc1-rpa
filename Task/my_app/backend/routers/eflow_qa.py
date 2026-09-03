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
import time
from pathlib import Path

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


def _iter_md_files():
    """遍历知识库全部 .md（按路径排序，跳过模板/脚本目录）。"""
    if not _KB_ROOT.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(_KB_ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            if fn.lower().endswith(".md"):
                yield Path(dirpath) / fn


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
def get_tree():
    """知识库文档树：相对路径 / 标题 / front-matter 状态来源 / 大小 / 修改时间。"""
    items = []
    for p in _iter_md_files():
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
def search(q: str = Query(..., min_length=1, description="检索词，空格分隔为 AND")):
    """全文检索：文件级 AND（所有词都出现才命中），返回行级匹配与上下文。"""
    terms = [t for t in re.split(r"\s+", q.strip()) if t]
    if not terms:
        return {"terms": [], "hits": []}
    lterms = [t.lower() for t in terms]
    hits = []
    t0 = time.time()
    for p in _iter_md_files():
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

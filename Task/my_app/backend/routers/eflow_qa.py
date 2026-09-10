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
from typing import Dict, Optional, Tuple

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


# ---------------- 实时单票回退（本地工单缺失时回 eFlow 拉取，纯内存不落库） ----------------

_REMOTE_TT_CACHE: Dict[str, Tuple[float, dict]] = {}
_REMOTE_TT_LOCK = threading.Lock()
_REMOTE_TT_TTL = 300   # 远程工单命中缓存 5 分钟（同一页面多端点并发时只查 eFlow 一次）


def _fetch_tt_remote_cached(tt_clean: str):
    """按单号取实时 eFlow 工单（带进程内 TTL 缓存），未命中返回 None。纯内存不落库。"""
    with _REMOTE_TT_LOCK:
        ent = _REMOTE_TT_CACHE.get(tt_clean)
        if ent and time.time() - ent[0] < _REMOTE_TT_TTL:
            return ent[1]
    from backend.services.eflow_data_mapper import fetch_tt_live
    row = fetch_tt_live(tt_clean)
    with _REMOTE_TT_LOCK:
        _REMOTE_TT_CACHE[tt_clean] = (time.time(), row)
    return row


def _remote_report(mod, tt_clean):
    """本地工单缺失时，回 eFlow 拉单条并构建分析与本地同构的报告。

    命中返回 (report, row)，未命中返回 (None, None)。report 已标注 source=「eFlow实时」。
    """
    row = _fetch_tt_remote_cached(tt_clean)
    if not row:
        return None, None
    report = mod.analyze_tt_remote(tt_clean, row, str(mod.DEFAULT_DB))
    report["source"] = "eFlow实时"
    report["remote"] = True
    if row.get("_tt_live_raw"):
        report["live_raw"] = row["_tt_live_raw"]
    return report, row


def _tt_context(tt_clean: str):
    """TT 分析上下文：本地库查工单/告警，工单或告警缺失时回 eFlow 实时兜底。

    返回 (report, alarm_lookup)：
      report       analyze_tt 结构；工单缺失时已由实时 eFlow 数据重建（source=「eFlow实时」）
      alarm_lookup {"mode": local|eflow_remote|eflow|none|not_found_ticket, "source",
                    "elapsed_sec", "error", "cached"} 或 None（本地+实时均未找到工单）
    """
    mod = _load_inspect_module()
    report = mod.analyze_tt(tt_clean, str(mod.DEFAULT_DB))
    remote = False
    if not report.get("found"):
        rep_remote, _row = _remote_report(mod, tt_clean)
        if rep_remote:
            report = rep_remote
            remote = True
        else:
            return report, None
    if (report.get("alarm") or {}).get("found"):
        # report["aid"] 已由 analyze_tt/analyze_tt_remote 注入（告警行的 AID 列）
        return report, {"mode": "eflow_remote" if remote else "local",
                        "source": report["alarm"]["source"],
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


def _ume_lookup_light(ume_svc, aid: str, site_name: str, raised_ms: Optional[int],
                      with_history: bool = False) -> dict:
    """单个 UME AID 轻量查询：先按 aid 直查，miss 再按 站点+时刻 兜底。

    与旧 /tt-ume-suggestion 单 aid 逻辑一致，供「关系链全量建议」逐 aid 复用。
    """
    ume = None
    if aid and aid.isdigit():
        ume = ume_svc.lookup_alarm(aid, days=30, limit=50, with_history=with_history)
        if ume.get("ok"):
            ume["strategy"] = "alarm_id"
            return ume
    if site_name and raised_ms:
        ume = ume_svc.find_alarm_by_event(site_name, raised_ms or 0, with_history=with_history)
        if ume.get("ok"):
            ume["strategy"] = "site_time"
    return ume


def _chain_related(ume_svc, chain, site_name, raised_ms):
    """由 resolve_alarm_chain 结果构建 related_ume（含完整层级 chain，与 eFlow 手动下钻一致）。

    items= 逐 aid 的 UME 建议；chain= eFlow 关系链全部节点（根→压缩→原始，含 depth/relationflag）。
    返回 (related_ume_or_None, items)。
    """
    if not (chain.get("ok") and chain.get("aids")):
        return None, []
    items = []
    seen_aid = set()
    for node in chain["aids"]:
        aid = node.get("aid", "")
        if not aid or aid in seen_aid:
            continue
        seen_aid.add(aid)
        n_ume = _ume_lookup_light(ume_svc, aid, node.get("site_name") or site_name, raised_ms)
        items.append({
            "aid": aid,
            "codename": node.get("codename", ""),
            "alarmcode": node.get("alarmcode", ""),
            "restype": node.get("restype", ""),
            "site_name": node.get("site_name") or site_name,
            "relationflag": node.get("relationflag"),
            "ume": n_ume,
        })
    related_ume = {
        "count": len(items), "items": items,
        "source": "relationship_chain",
        "elapsed_sec": chain.get("elapsed_sec"),
        "chain": chain.get("chain", []),
    }
    return related_ume, items


@router.get("/tt-ume-suggestion")
def tt_ume_suggestion(tt: str = Query(..., min_length=2, max_length=64, description="TT 单号")):
    """TT 单 → 告警 AID → RAN UME 处理建议（供「TT 快速分析」内嵌展示）。

    链路（2026-09 新增关系链全量建议）：
      1. 用 TT 告警的 eFlow alarm_id 递归 relatedAlarms/table，收集全部「原始
         RAN UME 告警」的真实 AID（alarmkey 以 zte-ume-ran 开头）；对这些
         aid 逐一 lookup_alarm 取建议，返回 related_ume 全量列表。
      2. 关系链为空时退 旧逻辑：按告警行 aid 直查 → miss 再按 站点名+发生时刻
         关联（同一条底层告警两边的 alarmraisedtime 毫秒一致）。
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
    alarm_id = str(report.get("alarm_id") or "").strip()
    site_name = str(report.get("site_name") or "").strip()
    occur = mod.parse_dt((report.get("timing") or {}).get("alarm_occur_time"))
    raised_ms = int(occur.replace(tzinfo=timezone.utc).timestamp() * 1000) if occur else None

    from backend.services.ran_ume import ran_ume_alarm_service as ume_svc

    # 1) 关系链：压缩告警 → 原始 RAN UME AID → 全量建议（含完整层级 chain）
    related_ume = None
    rec = {"aid": "", "ume": None}
    if alarm_id and alarm_id.isdigit():
        from backend.services import eflow_ume_link
        chain = eflow_ume_link.resolve_alarm_chain(alarm_id)
        related_ume, items = _chain_related(ume_svc, chain, site_name, raised_ms)
        # 关系链主建议：取第一个成功的原始 UME
        for it in (items or []):
            if it["ume"] and it["ume"].get("ok"):
                rec = {"aid": it["aid"], "ume": it["ume"]}
                break

    # 2) 无关系链或链取不到 → 退 旧逻辑：单 aid 直查 + 站点时间兜底
    if rec["ume"] is None:
        ume = _ume_lookup_light(ume_svc, aid, site_name, raised_ms)
        if ume:
            rec = {"aid": aid, "ume": ume}

    if rec["ume"] is None:
        err = "告警记录中没有 AID，且缺少站点/发生时刻，无法查询 RAN UME 建议"
        if not aid and not (site_name and raised_ms):
            return {"found": True, "tt_no": tt_clean, "aid": "", "ume": None,
                    "related_ume": related_ume, "error": err}
        return {"found": True, "tt_no": tt_clean, "aid": aid, "ume": None,
                "related_ume": related_ume, "error": err}

    out = {"found": True, "tt_no": tt_clean, "aid": rec["aid"], "ume": rec["ume"],
           "related_ume": related_ume, "cached": False}
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
    # 兼容 eFlow 压缩根 alarm id：按 id 递归 relatedAlarms/table 出完整下级链路
    # （与 TT 快速分析一致，含层级 chain），让 RAN UME 分析也能看全"手动下钻"的原生结果。
    try:
        aid = alarm_id.strip()
        if aid.isdigit():
            from backend.services import eflow_ume_link
            from backend.services.ran_ume import ran_ume_alarm_service as ume_svc
            chain = eflow_ume_link.resolve_alarm_chain(aid)
            rel_ume, _items = _chain_related(ume_svc, chain, "", None)
            if rel_ume:
                res["related_ume"] = rel_ume
    except Exception:  # noqa: BLE001
        logger.debug("ume-alarm 关系链附加失败（忽略）", exc_info=True)
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
    if not report.get("found"):
        # 本地工单缺失 → 回 eFlow 实时拉单条重建报告（纯内存不落库）
        rep_remote, _row = _remote_report(mod, tt_clean)
        if rep_remote:
            report = rep_remote
    return {"report": report}


@router.get("/tt-ai")
def tt_ai(
    tt: str = Query(..., min_length=2, max_length=64, description="TT 单号"),
    lang: str = Query("zh", pattern="^(zh|en)$", description="AI 结论语言：zh 或 en"),
):
    """TT 单 AI 分析：查库拿告警主信息 → 拼技能入参 → 调 Open WebUI「TT单分析」技能。

    返回 report（同 /inspect-tt）与 ai（结论 / 模型 / 耗时 / 入参）。
    AI 结论遵循 lang；省略 lang 时保持原有中文行为。
    """
    tt_clean = tt.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_\-]+", tt_clean):
        raise HTTPException(status_code=400, detail="单号格式非法")
    report, info = _tt_context(tt_clean)
    if not report.get("found"):
        return {"report": report, "ai": None}

    from backend.services import openwebui_client
    t0 = time.time()
    ai = openwebui_client.analyze_tt(report.get("skill_prompt") or "", lang=lang)
    ai["prompt"] = report.get("skill_prompt", "")
    ai["alarm_source"] = (report.get("alarm") or {}).get("source", "")
    ai["alarm_mode"] = (info or {}).get("mode", "")
    ai["elapsed_total_sec"] = round(time.time() - t0, 2)
    return {"report": report, "ai": ai}

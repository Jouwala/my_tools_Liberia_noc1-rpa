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
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

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
_INSPECT_LOCK = threading.Lock()


def _load_inspect_module():
    """动态加载知识库 tools/inspect_tt.py，与 CLI 共用同一份分析实现。

    加锁 + 双检（2026-09-15）：TT 快速分析一进页面就并发打 inspect-tt / tt-ai /
    tt-ume-suggestion 三个请求，后端重启后的首次访问若不加锁，三个线程会同时
    exec_module 同一个文件（首次 import 竞态）。启动期另有 warmup() 预热。
    """
    mod = _INSPECT_LOADER["mod"]
    if mod is not None:
        return mod
    with _INSPECT_LOCK:
        mod = _INSPECT_LOADER["mod"]  # 等锁期间别的线程可能已加载完成
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


def warmup():
    """启动期预热：把 inspect_tt.py 的首次加载从「用户第一次点分析」提前到启动期。

    消除两个差异：① 首次点击要多付一次模块加载；② 重启后首次点击的并发首载竞态。
    失败不阻断启动，返回错误串供 startup 日志打印。
    """
    try:
        _load_inspect_module()
        return None
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"


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


# 工单「派单」段里与处理人相关的字段（inspect_tt 的 FIELDS 里 section=派单）
_HANDLER_KEYS = ("last_processer", "last_processer_group", "last_process_time",
                 "organization_id", "vendor")


def _tt_handler_from_report(report: Dict[str, Any]) -> Dict[str, str]:
    """从 inspect_tt 报告的字段段里取出处理人信息（不额外查库，与页面展示同源）。

    值里可能带换行/制表符（如 `last_processer_group` 实测为 `G:3rd_Power;\\n `），
    这里统一压成单行空白，避免在证据文本与页面上撑出多余空行。
    """
    out: Dict[str, str] = {}
    for sec in (report or {}).get("fields") or []:
        for it in sec.get("items") or []:
            k = it.get("key")
            v = " ".join(str(it.get("value") or "").split())
            if k in _HANDLER_KEYS and v:
                out[k] = v
    return out


@router.get("/tt-ai")
def tt_ai(
    tt: str = Query(..., min_length=2, max_length=64, description="TT 单号"),
    lang: str = Query("zh", pattern="^(zh|en)$", description="AI 结论语言：zh 或 en"),
):
    """TT 单 AI 分析：查库拿告警主信息 → 拼技能入参 → 调「TT单分析」技能。

    返回 report（同 /inspect-tt）与 ai（结论 / 模型 / 耗时 / 入参 / **规则命中证据**）。
    AI 结论遵循 lang；省略 lang 时保持原有中文行为。

    2026-09-23 增强：除 AI 结论外，额外用本地规则引擎（与每天 04:20 的
    eflow_tt_rules_check 定时任务、Email Reports → eFlow TT Rules Check 页签同源）
    算一次**确定性**的命中规则，作为 `ai.rules` 返回，并渲染成
    `ai.evidence` 文本随入参下发给模型，要求结论写明规则名称/规则文件/处理人。
    规则引擎不可用时（本地无该单、规则表缺失）不影响 AI 结论，只是 `available=false`。

    2026-09-23 再增强（程序化兜底）：所有候选模型档都失败时（如本地代理未启动 +
    Open WebUI 处于不可达短路窗口），不再只回一句 `AI analysis failed: ...`，
    而是由本地规则引擎**程序化**生成一份 Markdown 结论挂在 `ai.fallback_conclusion`
    （`ai.fallback=true`），页面照常渲染结论 + 规则命中证据；`ai.ok` 仍为 false、
    `ai.error` 保留真实失败原因，便于排障并区分「模型给的」与「引擎给的」。
    """
    tt_clean = tt.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_\-]+", tt_clean):
        raise HTTPException(status_code=400, detail="单号格式非法")
    report, info = _tt_context(tt_clean)
    if not report.get("found"):
        return {"report": report, "ai": None}

    from backend.services import openwebui_client
    from backend.services.eflow_rules import tt_rule_evidence

    t0 = time.time()
    # 本地规则引擎预判定（确定性证据）：先算证据，再连同证据一起问模型
    evidence = tt_rule_evidence.build_rule_evidence(
        tt_clean, handler=_tt_handler_from_report(report))
    evidence_text = tt_rule_evidence.render_evidence_text(evidence, lang=lang)

    ai = openwebui_client.analyze_tt(
        report.get("skill_prompt") or "", lang=lang, evidence_text=evidence_text)
    ai["prompt"] = report.get("skill_prompt", "")
    ai["alarm_source"] = (report.get("alarm") or {}).get("source", "")
    ai["alarm_mode"] = (info or {}).get("mode", "")
    ai["rules"] = evidence          # 结构化证据：页面「命中规则」明细块
    ai["evidence"] = evidence_text  # 下发给模型的证据原文（排查用）

    # 模型全档失败 → 用本地规则引擎程序化出结论（不含任何模型推断）
    ai["fallback"] = False
    ai["fallback_conclusion"] = ""
    if not ai.get("ok"):
        try:
            ai["fallback_conclusion"] = tt_rule_evidence.render_local_conclusion(
                evidence, report=report, lang=lang, reason=str(ai.get("error") or ""))
            ai["fallback"] = bool(ai["fallback_conclusion"])
        except Exception:  # noqa: BLE001
            # 兜底失败不能盖住原始错误：ok=false / error 原样返回
            logger.exception("TT 程序化兜底结论生成失败")

    ai["elapsed_total_sec"] = round(time.time() - t0, 2)
    return {"report": report, "ai": ai}


# ------------------------- TT 批量级别核查（清单上传 → 逐单判定级别是否正常） -------------------------

class TtBatchIn(BaseModel):
    """批量核查入参：tts 为已解析的单号数组；text 为粘贴/上传的原始文本（二者取并集）。"""

    tts: Optional[List[str]] = Field(default=None, description="TT 单号数组（前端解析文件后直接传）")
    text: Optional[str] = Field(default=None, description="原始文本，按换行/逗号/分号/制表符拆分")
    limit: Optional[int] = Field(default=None, ge=1, le=500, description="本次最多核查条数（默认 500）")


@router.post("/tt-batch-check")
def tt_batch_check(payload: TtBatchIn):
    """TT 批量级别核查：按清单逐单套用 TT Update Severity Rule，判定级别是否正常。

    与每天 04:20 的定时任务 eflow_tt_rules_check 同源（复用 eflow_rules_matcher），
    区别只是把「取最新 1000 条」换成「取用户指定的 TT 列表」。只读，不落库、不写文件。

    返回 rows（逐单：当前级别 / 规则建议级别 / 判定 正常|需调整|无法判定 / 命中规则 / 匹配详情）
    与 summary（命中、未找到、正常、需调整、无法判定 计数），供页面表格与 Excel 导出使用。
    """
    from backend.services.eflow_rules import tt_batch_severity as batch

    items = list(payload.tts or []) + batch.parse_tt_text(payload.text or "")
    limit = int(payload.limit or batch.MAX_BATCH)
    res = batch.check_batch(items, limit=limit)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "批量核查失败")
    logger.info(
        "TT 批量核查：输入 %s 条，命中 %s，需调整 %s，耗时 %ss",
        res["input"]["valid"], res["summary"]["found"],
        res["summary"]["level_adjust"], res["elapsed_sec"],
    )
    return res


# ========== TT 复盘报告（新增于 2026-09-23）==========
# 背景：复盘报告 §6.4「最小可行版本」之外，沉淀一份**可程序化产出**的复盘报告接口，
# 供 eFlow 知识库页面一键生成；与原人工 markdown 报告口径一致，但加入了
# 系统自动判定（与 NOC 填报对比）、派单机制真相、阶段时长等机器可读字段。
# 设计原则：不修改任何已有路由；新端点全部以 `_tt_postmortem_*` 命名，
# 避免误碰 /eflow-qa/inspect-tt、/tt-batch-check 等既有行为。
@router.get("/_tt_postmortem/{tt_no}")
def tt_postmortem(tt_no: str):
    """单张 TT 的程序化复盘报告（用于 eFlow 知识库页面一键生成）。"""
    from backend.services.tt_postmortem import build_tt_postmortem
    return build_tt_postmortem(tt_no)


@router.get("/_tt_postmortem_noc")
def tt_postmortem_noc(
    month: Optional[str] = Query(None, description="YYYY-MM，默认当月"),
    limit: int = Query(20000, ge=1, le=50000, description="单人最大样本数"),
    noc: Optional[str] = Query(None, description="NOC 操作人模糊过滤"),
    owner: Optional[str] = Query(
        None, description="承接方：IPT（第三方，按设计不建 WO）/ ZTE（自维）；不传 = 全部"),
):
    """NOC 操作人分析报告（参考 FME Ranking 页面结构）。

    limit 是该人本月的取样上限，必须显著大于单人月单量（实测单人月峰值约 2000 单）。
    前端拉到 10000 正是为了让 `LIMIT` 不生效，否则表格的「处理总数」会被静默截断，
    且与下钻行数对不上。上限放宽到 50000 以覆盖整月全量。

    owner 用于把「推到第三方（IPT）」的单与「ZTE 自维」的单分开统计 ——
    第三方单按设计不建 WO，混在一起会污染错位率/夜班/SLA 这些自维指标。
    """
    from backend.services.tt_postmortem import build_noc_analyst_report
    return build_noc_analyst_report(month=month, limit=limit, noc_filter=noc,
                                    owner=owner)


# ========== NOC 操作人分析 · 三层下钻 ==========
# 背景（2026-09-23）：原页面只有一张排名表，明细仅 3 条样本且不可点，
# 做不到"能下钻尽下钻"。补齐三层：
#   ① /_tt_postmortem_noc_tt      NOC → TT 明细（按 全部/错位/夜班/SLA Fail/慢单 切片）
#   ② /_tt_postmortem_noc_sites   NOC → 异常站点聚合
#   ③ /_tt_postmortem_tt_detail   单 TT → 告警链路 + 根因一致性审计（最底层）
# 三个端点均为**只读**，不修改任何既有路由；下钻的 WHERE 条件与概览端点完全一致
# （同一 alarm_occur_time 口径 + 同一 last_processer 匹配），保证「表格数字 = 下钻行数」。
@router.get("/_tt_postmortem_noc_tt")
def tt_postmortem_noc_tt(
    noc: str = Query(..., description="NOC 操作人（精确匹配，来自概览行的 noc_name）"),
    month: Optional[str] = Query(None, description="YYYY-MM，默认当月"),
    slice: str = Query("all", description="切片：all / mismatch / night / sla_fail / slow"),
    owner: Optional[str] = Query(
        None, description="承接方：IPT（第三方，按设计不建 WO）/ ZTE（自维）；不传 = 全部"),
    limit: int = Query(20000, ge=1, le=50000, description="取样上限"),
):
    """某位 NOC 的 TT 明细下钻（含错位类型、夜班标记、处理时长、承接方）。"""
    from backend.services.tt_postmortem import build_noc_tt_drilldown
    return build_noc_tt_drilldown(noc=noc, month=month, slice_=slice, limit=limit,
                                  owner=owner)


@router.get("/_tt_postmortem_noc_sites")
def tt_postmortem_noc_sites(
    noc: str = Query(..., description="NOC 操作人（精确匹配）"),
    month: Optional[str] = Query(None, description="YYYY-MM，默认当月"),
    only_abnormal: bool = Query(True, description="仅返回存在异常的站点"),
    limit: int = Query(20000, ge=1, le=50000, description="取样上限"),
):
    """某位 NOC 名下按站点聚合的异常视图（错位 / SLA Fail / 慢单）。"""
    from backend.services.tt_postmortem import build_noc_site_drilldown
    return build_noc_site_drilldown(noc=noc, month=month, only_abnormal=only_abnormal, limit=limit)


@router.get("/_tt_postmortem_tt_detail")
def tt_postmortem_tt_detail(
    tt_no: str = Query(..., description="TT 单号"),
    noc: Optional[str] = Query(None, description="发起下钻的 NOC（仅用于回显）"),
):
    """单张 TT 的下钻明细：告警链路 + 系统判定根因 vs NOC 填报根因。"""
    from backend.services.tt_postmortem import build_noc_tt_detail
    res = build_noc_tt_detail(tt_no=tt_no, noc=noc)
    if not res.get("found"):
        raise HTTPException(status_code=404, detail=res.get("message") or "未找到该工单")
    return res


# ========== 里程碑时间轴批量聚合（2026-09-23 新增）==========
# 内容参考「TT 复盘报告生成（程序化版）」：把本月全部 TT 的时间轴合起来看，
# 回答「时间都浪费到哪个环节」「该做的动作没做哪些」「哪些高等级断站该派 WO 却没派」。
# 逐单复用 build_tt_timeline，与单张 TT 复盘报告**同源同口径**，不产生第二套结论。
#
# 性能：本月约 2300 单，逐单解析 *_detail 文本约 150s，故按 month 落磁盘缓存
# （backend/data/tt_timeline_cache/），首次计算慢、之后毫秒级。口径变更时须
# 提升 services/tt_postmortem 里的 _TIMELINE_CACHE_VERSION 使旧缓存失效。
@router.get("/_tt_postmortem_timeline/{tt_no}")
def tt_postmortem_timeline(tt_no: str):
    """单张 TT 的「里程碑时间轴 + 应做/实做 + 偏离清单 + 时间归因」。

    与 /_tt_postmortem/{tt_no} 的区别：本端点直接给出 build_tt_timeline 的原生结构
    （含 time_spent 时间归因分段），供页面「单 TT 复盘」视图使用。
    """
    from backend.services.tt_postmortem import build_tt_timeline
    res = build_tt_timeline(tt_no)
    if not res.get("found"):
        raise HTTPException(status_code=404, detail=res.get("message") or "未找到该工单")
    return res


@router.get("/_tt_postmortem_noc_timeline")
def tt_postmortem_noc_timeline(
    month: Optional[str] = Query(None, description="YYYY-MM，默认当月"),
    limit: int = Query(20000, ge=1, le=50000, description="取样上限"),
    noc: Optional[str] = Query(None, description="仅看某位 NOC（精确匹配，命中该人不走缓存）"),
    owner: Optional[str] = Query(
        None, description="承接方：IPT（第三方）/ ZTE（自派）；不传 = 全部"),
    refresh: bool = Query(False, description="强制重算（跳过磁盘缓存）"),
):
    """本月里程碑时间轴批量聚合 —— 时间归因 + 动作偏离 + 未派 WO 清单。

    - WHERE 与 /_tt_postmortem_noc 完全一致（同一 alarm_occur_time 月窗口），
      保证「概览数字 = 聚合单量」。
    - owner 用于把**派给第三方（IPT）**的单与自派（ZTE）分开：第三方单本就
      不建 WO，混在一起会把「应派未派 WO」抬高 3 倍多，属误报。
    - refresh=true 时强制重算（约 150s），用于月份数据仍在增长时刷新。
    """
    from backend.services.tt_postmortem import build_noc_timeline_agg
    return build_noc_timeline_agg(
        month=month, limit=limit, noc_filter=noc, use_cache=not refresh,
        owner=owner,
    )


@router.post("/_tt_postmortem_export_md/{tt_no}")
def tt_postmortem_export_md(tt_no: str):
    """单张 TT 复盘报告 → Markdown 文档（供下载 / 知识库归档）。

    与 outputs/eflow_TT_复盘报告_*.md 同口径，但由后端实时生成，
    模板内置于代码中，确保任何人随时可复现，不依赖磁盘文件。
    """
    from backend.services.tt_postmortem import build_tt_postmortem

    rep = build_tt_postmortem(tt_no)
    if not rep.get("found"):
        raise HTTPException(status_code=404, detail=rep.get("message") or "未找到该工单")

    md = _render_postmortem_md(rep)
    return {
        "tt_no": tt_no,
        "filename": f"eflow_TT_复盘报告_{tt_no}.md",
        "content": md,
        "size": len(md),
    }


def _fmt_gap(sec) -> str:
    """秒 → 人读时长（用于复盘报告正文，缺失时返回 '-' 而不是 0）。"""
    if sec is None:
        return "-"
    try:
        sec = int(sec)
    except Exception:
        return "-"
    if sec < 0:
        return f"-{_fmt_gap(-sec)}"
    if sec < 60:
        return f"{sec} 秒"
    if sec < 3600:
        return f"{sec / 60:.0f} 分钟"
    if sec < 86400:
        return f"{sec / 3600:.2f} 小时"
    return f"{sec / 86400:.2f} 天"


# 偏离类型 → 中文（与 services/tt_postmortem/build_tt_timeline 的 kind 取值一一对应）
_KIND_ZH = {
    "missing": "应有动作缺失",
    "late": "动作超时",
    "out_of_order": "动作越序",
    "data_conflict": "字段冲突",
}


def _render_postmortem_md(rep: Dict[str, Any]) -> str:
    """复盘报告 Markdown 渲染器（与 outputs/eflow_TT_复盘报告_*.md 风格一致）。"""
    t = rep["ticket"]
    site = rep["site"]
    sj = rep["system_judged"] or {}
    nf = rep["noc_filled"]
    op = rep["operators"]
    dp = rep["dispatch_path"]
    rs = rep["rules_snapshot"]
    d = rep["durations"]
    lines: List[str] = []

    lines.append(f"# eFlow 工单 复盘报告 — {rep['tt_no']}")
    lines.append("")
    # ---------- 单头（含 SLA 是否超期）----------
    sla = rep.get("sla") or {}
    lines.append(f"**工单号**：{rep['tt_no']}"
                 + (f"　|　**标题**：{str(t.get('title') or '').strip()}" if t.get("title") else ""))
    lines.append(f"**站点**：{site.get('site_name')}（site_id={site.get('site_id')}，"
                 f"siteSubType={site.get('site_subtype')}）")
    lines.append(f"**告警码**：{t.get('alarm_code')}（codename={sj.get('codename') or '-'}，"
                 f"reason_type={sj.get('reason_type') or '-'}）")
    lines.append(f"**级别 / 状态**：{t.get('ticket_severity')} / {t.get('status')}")
    # SLA 行——关键复盘信息，放在最显眼处
    if sla:
        _sla_flag = "🔴 **超期**" if sla.get("is_breached") else "✅ 未超期"
        lines.append(f"**SLA**：{sla.get('status') or '-'}　{_sla_flag}"
                     + (f"　时长 {sla.get('total_text')}" if sla.get("total_text") else "")
                     + (f"　期限 {sla.get('deadline')}" if sla.get("deadline") else "")
                     + (f"　超期 {_fmt_gap(sla.get('over_seconds'))}" if sla.get("over_seconds") else ""))
        if sla.get("cause"):
            lines.append(f"> {sla['cause']}")
    lines.append("")

    # ---------- 责任人（谁干的）----------
    pe = rep.get("people") or {}
    if pe:
        lines.append("| 角色 | 责任人 |")
        lines.append("|---|---|")
        for _label, _val in (
            ("建单人", f"{pe.get('creator') or '-'}（{pe.get('creator_kind') or '-'}）"),
            ("FO 接单人", pe.get("fo_acceptor")),
            ("FO 填报人", pe.get("fo_processer")),
            ("关单人", pe.get("confirmer")),
            ("最后处理人", pe.get("last_processer")),
            ("处理组", pe.get("last_processer_group")),
            ("WO 建单人", (f"{pe.get('wo_creator')}（{pe.get('wo_creator_kind')}）"
                          if pe.get("wo_creator") else None)),
            ("WO 当前处理人", pe.get("wo_current_handler")),
        ):
            lines.append(f"| {_label} | `{_val or '-'}` |")
        lines.append("")

    # ---------- 时间都花哪了（复盘重点）----------
    tsc = rep.get("time_spent") or {}
    if tsc.get("segments"):
        lines.append("---")
        lines.append("")
        lines.append("## 0. 时间都花哪了（按耗时排序）")
        lines.append("")
        lines.append("| 阶段 | 耗时 | 占比 | 责任方 | 是否超阈值 |")
        lines.append("|---|---|---|---|---|")
        for s in tsc["segments"]:
            flag = (f"🔴 超 {_fmt_gap(s.get('over_by_s'))}" if s.get("over_threshold")
                    else ("✅ 正常" if s.get("threshold_s") else "—"))
            # 阶段名（现场响应等待/建单时延…）比单纯的"A → B"更能一眼看出钱花在哪
            ph = s.get("phase_label")
            label = f"**{ph}**：{s.get('label')}" if ph else s.get("label")
            lines.append(f"| {label} | **{_fmt_gap(s.get('seconds'))}** | "
                         f"{s.get('pct')}% | `{s.get('owner') or '-'}` | {flag} |")
        lines.append(f"| **合计** | **{_fmt_gap(tsc.get('segments_sum_s'))}** | "
                     f"{round(100.0*(tsc.get('segments_sum_s') or 0)/(tsc.get('total_seconds') or 1),1)}% | — | — |")
        lines.append("")
        _win = tsc.get("window") or {}
        if _win.get("start"):
            lines.append(f"> 统计窗口：{_win.get('start')} → {_win.get('end')}"
                         f"（终点取**所有已知活动的最晚时间**，含现场动作，"
                         f"不会因为工单字段没更新而把现场等待切掉）")
            lines.append("")
        if tsc.get("bottleneck_note"):
            lines.append(f"> **瓶颈：** {tsc['bottleneck_note']}")
            lines.append("")
        if tsc.get("unaccounted_note"):
            lines.append(f"> ⚠ {tsc['unaccounted_note']}")
            lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 1. 里程碑时间轴（每个节点谁做的、取自哪个字段）")
    lines.append("")
    tl = rep.get("timeline") or []
    if tl:
        lines.append("| # | 时间 | 里程碑 | 执行方 | 操作人 | 说明 | 数据来源 |")
        lines.append("|---|---|---|---|---|---|---|")
        for i, n in enumerate(tl, 1):
            ts = n.get("time") or "**（缺失）**"
            # actor 三态：system / human / unknown（未证实——如"有 WO 但无现场动作明细"）
            _actor = n.get("actor")
            actor = {"system": "系统", "human": "人工"}.get(_actor, "**未证实**")
            gap = n.get("gap_from_prev_s")
            gap_txt = f"（距上一跳 {_fmt_gap(gap)}）" if gap is not None else ""
            lines.append(
                f"| {i} | {ts} | {n.get('label')} | {actor} | "
                f"`{n.get('operator') or '-'}` | {n.get('detail') or '-'}{gap_txt} | "
                f"`{n.get('source') or '-'}` |"
            )
        lines.append("")
        tm = rep.get("timeline_meta") or {}
        lines.append(f"> 窗口 {tm.get('window', {}).get('start')} → {tm.get('window', {}).get('end')}，"
                     f"总历时 {_fmt_gap(tm.get('total_seconds'))}；"
                     f"里程碑 {tm.get('done_count')}/{tm.get('stage_count')} 跳有确凿时间戳。")
        lines.append("")
        # 现场处置的 WO 步骤明细（有 WO 才有）
        for n in tl:
            if n.get("key") == "onsite_action" and n.get("wo_steps"):
                lines.append("**现场处置明细（来自 eflow_wo）**：")
                lines.append("")
                lines.append("| 步骤 | 时间 | 操作人 | 数据来源 |")
                lines.append("|---|---|---|---|")
                for s in n["wo_steps"]:
                    lines.append(f"| {s.get('label')} | {s.get('time') or '-'} | "
                                 f"`{s.get('operator') or '-'}` | `{s.get('source')}` |")
                lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 2. 该做的动作 · 实际做的动作")
    lines.append("")
    lines.append("| 里程碑 | 契约 | 应做 | 实际 | 时间 | 操作人 |")
    lines.append("|---|---|---|---|---|---|")
    # 三态渲染：已执行 / 未证实（查不到证据，不能断定没做）/ 未执行（必需动作确实缺失）
    _ST_ZH = {"done": "✅ 已执行", "unproven": "❓ **未证实**", "missing": "❌ **未执行**"}
    for a in rep.get("expected_actions") or []:
        req = "**必需**" if a.get("required") else "条件"
        st = a.get("status") or ("done" if a.get("done") else "missing")
        lines.append(
            f"| {a.get('label')} | {req} | ✅ 应执行 | "
            f"{_ST_ZH.get(st, st)} | "
            f"{a.get('time') or '-'} | `{a.get('operator') or '-'}` |"
        )
    lines.append("")
    _unproven = [a for a in (rep.get("expected_actions") or []) if a.get("status") == "unproven"]
    if _unproven:
        lines.append("> ❓ **未证实**：库中取不到该动作的证据，但**也不能据此断定没做**。")
        lines.append("> 原因见各行「说明」；典型如「有 WO 却无出发/到场明细」——"
                     "eflow_tt 本就没有到场字段，而 WO 又可能是 `fe_robot` 自动创建的，"
                     "**不能作为现场有人的证据**。")
        lines.append("")
    missing = rep.get("missing_actions") or []
    if missing:
        lines.append("**缺失动作明细**：")
        lines.append("")
        for m in missing:
            lines.append(f"- ❌ **{m.get('label')}**（{m.get('actor')}）：{m.get('reason')}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 3. 偏离清单（应做 vs 实做）")
    lines.append("")
    devs = rep.get("deviations") or []
    if devs:
        _SEV_ZH = {"critical": "🔴 严重", "major": "🟠 中等", "minor": "🟡 轻微"}
        lines.append("| 严重度 | 类型 | 偏离 | 应有 | 实际 | 影响 |")
        lines.append("|---|---|---|---|---|---|")
        for dev in devs:
            lines.append(
                f"| {_SEV_ZH.get(dev.get('severity'), dev.get('severity'))} | "
                f"`{_KIND_ZH.get(dev.get('kind'), dev.get('kind'))}` | **{dev.get('label')}** | "
                f"{dev.get('expected')} | {dev.get('actual')} | {dev.get('impact')} |"
            )
        lines.append("")
        crit = sum(1 for d in devs if d.get("severity") == "critical")
        lines.append(f"> 共 {len(devs)} 处偏离，其中严重 {crit} 处。")
    else:
        lines.append("未检出偏离：契约要求的动作全部按时执行，且未发现字段间冲突。")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 4. 系统判定根因 vs NOC 填写根因")
    lines.append("")
    lines.append("| 维度 | NOC 填报 | 系统判定 | 一致性 |")
    lines.append("|---|---|---|---|")
    lines.append(f"| root_cause | `{nf.get('root_cause')}` | `{sj.get('fault_domain')}` | {'❌ 不一致（' + rep['mismatch_type'] + '）' if rep['consistency'] is False else '✅ 一致' if rep['consistency'] is True else '⚠ 待人工复核'} |")
    lines.append(f"| sub_root_cause | `{nf.get('sub_root_cause')}` | `{sj.get('codename')}` | — |")
    lines.append(f"| 填报人 / 时间 | {nf.get('filed_by')} / {nf.get('filed_at')} | 置信度 {rep['confidence']}（linkage={sj.get('linkage')}）| — |")
    lines.append("")
    lines.append(f"> {rep['note']}")
    lines.append("")
    if sj:
        lines.append(f"**系统判定依据**：{sj.get('basis')}；指纹匹配 {sj.get('alarm_count')} 条告警"
                     + (f"，告警码 {sj.get('distinct_codes')}" if sj.get('distinct_codes') else ""))
        lines.append("")
    sh = rep.get("site_history") or []
    if sh:
        lines.append("**该站历史告警指纹**（同站历史是判定「反复同源故障」的关键佐证）：")
        lines.append("")
        lines.append("| TT | 告警码 | codename | reason_type | 发生 | 清除 |")
        lines.append("|---|---|---|---|---|---|")
        for h in sh[:10]:
            mark = " ⬅ 本单" if h.get("is_self") else ""
            lines.append(f"| {h.get('tt_no')}{mark} | {h.get('alarmcode')} | {h.get('codename')} | "
                         f"{h.get('reason_type')} | {h.get('raised')} | {h.get('cleared')} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 5. WO 派单机制真相")
    lines.append("")
    lines.append(f"- **WO 编号**：`{dp.get('wo_no') or '(无)'}`" + (f"，由 `{dp.get('wo_creator')}` 建单" if dp.get("wo_creator") else ""))
    lines.append(f"- **派单分类**：`{dp.get('category')}`")
    lines.append(f"- **说明**：{dp.get('explanation')}")
    if dp.get("fo_assign_to"):
        lines.append(f"- **FO Accept Assign To**：`{dp.get('fo_assign_to')}`")
    lines.append("")
    lines.append(f"**当前规则覆盖**：断站类码 ACTIVE 覆盖 `{', '.join(rs['down_alarm_codes_active']) or '无'}`；STOP 覆盖 `{', '.join(rs['down_alarm_codes_stopped']) or '无'}`。"
                 f"（活动规则 {rs['active_rule_count']} 条 / 停用规则 {rs['stopped_rule_count']} 条）")
    lines.append("")

    # ---------- 5b. 为什么走人工派单（依据 TT Push Order Rule）----------
    da = rep.get("dispatch_analysis") or {}
    if da and da.get("rules_at_step"):
        lines.append("### 5b. 为什么走人工派单 —— TT Push Order Rule 逐条比对")
        lines.append("")
        lines.append(f"**判定阶段**：`{da.get('trigger_step')}` —— {da.get('step_meaning')}")
        lines.append("")
        _sig = da.get("signature") or {}
        lines.append(f"**本单特征**：siteSubtype=`{da.get('site_subtype') or '-'}`，"
                     f"告警=`{da.get('alarm_name') or '-'}`（码 {da.get('alarm_code') or '-'}）"
                     f"，已建 WO=`{da.get('has_wo')}`；命中特征 "
                     + "、".join(f"`{k}`" for k, v in _sig.items() if v) + "。")
        lines.append("")
        lines.append("| 规则名 | 状态 | 目标 | 规则要求 | 本单是否适用 | 判定依据 |")
        lines.append("|---|---|---|---|---|---|")
        _vmark = {"matched": "✅ 命中", "blocked_by_status": "⛔ 本应命中但已停用",
                  "not_applicable": "➖ 不适用", "unknown_scope": "❓ 范围未知"}
        for e in da["rules_at_step"]:
            lines.append(
                f"| {e.get('rule_name')} | {e.get('status')} | {e.get('target')} | "
                f"{'/'.join(e.get('wants_keys') or []) or '-'} | "
                f"{_vmark.get(e.get('verdict'), e.get('verdict'))} | {e.get('why')} |")
        lines.append("")
        if da.get("blocked_rules"):
            lines.append("**⚠ 本应命中但已停用的规则**：")
            lines.append("")
            for b in da["blocked_rules"]:
                lines.append(f"- `{b.get('rule_name')}`（{b.get('status')}，优先级 {b.get('priority')}，"
                             f"描述：{b.get('description') or '无'}，最后更新 {b.get('update_time') or '-'}）")
            lines.append("")
        if da.get("fallback_rules"):
            lines.append("**兜底派单规则（ttDispatchRule）**：")
            lines.append("")
            for f in da["fallback_rules"]:
                lines.append(f"- `{f.get('rule_name')}`（优先级 {f.get('priority')}，{f.get('status')}）"
                             f"：{f.get('description') or '无描述'}")
            lines.append("")
        lines.append(f"**结论**：{da.get('conclusion')}")
        lines.append("")
        if da.get("caveat"):
            lines.append(f"> {da['caveat']}")
            lines.append("")
    # ---------- 5c. 指派给谁 ----------
    asg = rep.get("assignment") or {}
    if asg:
        lines.append("---")
        lines.append("")
        lines.append("## 5c. 这单指派给谁了")
        lines.append("")
        lines.append(f"**结论**：{asg.get('conclusion')}")
        lines.append("")
        lines.append("| 项目 | 值 |")
        lines.append("|---|---|")
        lines.append(f"| 通道 | `{asg.get('channel') or '-'}` |")
        lines.append("| 最终指派到个人 | "
                     + (f"**{'、'.join(asg['assigned_persons'])}**"
                        if asg.get("assigned_persons") else "（无）") + " |")
        lines.append("| 涉及的群组 | "
                     + (f"`{'、'.join(asg['assigned_groups'])}`"
                        if asg.get("assigned_groups") else "（无）") + " |")
        lines.append("")
        lines.append("**建单环节（TT 层）**")
        lines.append("")
        lines.append("| 项目 | 值 |")
        lines.append("|---|---|")
        lines.append(f"| 建单指派到人（`Assign To`） | "
                     f"`{asg.get('tt_create_assign_to') or '（空）'}` |")
        lines.append(f"| 建单指派到群组（`Assignee Group`） | "
                     f"`{asg.get('tt_create_assignee_group') or '（空）'}` |")
        lines.append(f"| 建单后状态 | `{asg.get('tt_next_status') or '-'}` |")
        lines.append(f"| 建单时处理人（`current_handler`） | "
                     f"`{asg.get('tt_current_handler') or '（空）'}` |")
        lines.append("")
        if asg.get("wo_no"):
            lines.append(f"**工单层（WO `{asg.get('wo_no')}` —— 真正落到人的地方）**")
            lines.append("")
            lines.append("| 项目 | 值 |")
            lines.append("|---|---|")
            lines.append(f"| WO 指派到人（`Assign To`） | "
                         f"`{asg.get('wo_create_assign_to') or '（空）'}` |")
            lines.append(f"| WO 指派到群组 | `{asg.get('wo_assignee_group') or '（空）'}` |")
            lines.append(f"| WO 当前处理人（`current_handler`） | "
                         f"`{asg.get('wo_current_handler') or '（空）'}` |")
            lines.append("")
            lines.append("> 前缀语义：`P:` = 个人，`G:` = 群组。"
                         "TT 的 `current_handler` 可能一直停在群组池，"
                         "**真正指派到人要去看 WO 层**。")
            lines.append("")
        if asg.get("create_note"):
            lines.append(f"> **建单环节说明**：{asg['create_note']}")
            lines.append("")
        lines.append(f"> {asg.get('channel_note')}")
        lines.append("")
        pools = asg.get("group_pools") or []
        if pools:
            lines.append("**群组池规则（决定候选人范围，不指定个人）**：")
            lines.append("")
            lines.append("| 环节 | 规则名 | 优先级 | 候选处理人（节选） |")
            lines.append("|---|---|---|---|")
            for p in pools:
                hn = (p.get("handler_name") or "")
                hn = (hn[:78] + "…") if len(hn) > 78 else (hn or "-")
                lines.append(f"| {p.get('stage')} | `{p.get('rule_name')}` | "
                             f"{p.get('priority')} | {hn} |")
            lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 6. 阶段时长")
    lines.append("")
    lines.append("| 阶段 | 时长 |")
    lines.append("|---|---|")
    if d.get("create_to_accept_seconds") is not None:
        lines.append(f"| 建单 → FO Accept | {d['create_to_accept_seconds']/60:.1f} 分钟 |")
    if d.get("accept_to_process_seconds") is not None:
        lines.append(f"| FO Accept → FO Process | {d['accept_to_process_seconds']/3600:.2f} 小时 |")
    if d.get("process_to_confirm_seconds") is not None:
        lines.append(f"| FO Process → Confirm | {d['process_to_confirm_seconds']/3600:.2f} 小时 |")
    if d.get("total_seconds") is not None:
        lines.append(f"| 全流程 | {d['total_seconds']/3600:.2f} 小时 |")
    lines.append("")
    if rep.get("suggested_actions"):
        lines.append("---")
        lines.append("")
        lines.append("## 7. 改进建议")
        lines.append("")
        for i, sa in enumerate(rep["suggested_actions"], 1):
            lines.append(f"{i}. {sa}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*本报告由 my_app /api/eflow-qa/_tt_postmortem/{tt_no} 自动生成；模板与 TT202609160106/TT202609210140 双单复盘报告一致。*")
    return "\n".join(lines)


# ========== WO 清理（批量关闭 WaitConfirm 工单，2026-10-01） ==========
# 背景：FE 处理完成后大量 WO 停在 WaitConfirm，需 NOC 确认关闭；此前只能逐单在
# eFlow 界面点确认。本组端点把 TMP 探针验证过的「detail → process → 复核」三步
# 链路（见 backend/services/eflow_wo_close.py 模块注释）开放为页面能力。
# 设计：① /wo-close/check 只读预检；② /wo-close/submit 真正提交（逐单串行+间隔）；
# 两者都不碰已有路由；写入操作仅限 opName=Confirm 且 status=WaitConfirm 的单。

class WoCloseIn(BaseModel):
    """WO 批量关闭入参：wos 为已解析单号数组；text 为粘贴原始文本（二者取并集）。"""

    wos: Optional[List[str]] = Field(default=None, description="WO 单号数组（WO+12位数字）")
    text: Optional[str] = Field(default=None, description="原始文本，按换行/逗号/分号/制表符拆分")
    limit: Optional[int] = Field(default=None, ge=1, le=200, description="单次上限（默认 200）")


@router.post("/wo-close/check")
def wo_close_check(payload: WoCloseIn):
    """批量只读预检：逐单判断「是否处于 WaitConfirm 且有待办 Confirm」。

    不做任何提交。返回 rows（逐单：woId/状态/站点/能否关闭/原因）+ summary，
    供页面先给用户过目，再决定是否真正提交。
    """
    from backend.services.eflow_wo_close import batch_check, normalize_wo_list, MAX_BATCH

    valid, invalid = normalize_wo_list(payload.text, payload.wos)
    if not valid:
        raise HTTPException(status_code=400, detail="没有解析到有效的 WO 单号（格式：WO+12位数字）")
    limit = int(payload.limit or MAX_BATCH)
    res = batch_check(valid, limit=limit)
    res["invalid"] = invalid
    logger.info("WO 清理预检：输入 %s 条，可关 %s，忽略 %s",
                res["input"]["valid"], res["summary"]["closable"], len(invalid))
    return res


@router.post("/wo-close/submit")
def wo_close_submit(payload: WoCloseIn):
    """批量关闭：只对预检通过的单逐单提交 Confirm To Close（operationResult="7"）。

    逐单串行 + 1s 间隔；每单提交后立即回读 detail 复核是否真的 Closed。
    幂等性：已 Closed / 非 WaitConfirm 的单会被跳过而不是报错，重跑安全。
    """
    from backend.services.eflow_wo_close import batch_close, normalize_wo_list, MAX_BATCH

    valid, invalid = normalize_wo_list(payload.text, payload.wos)
    if not valid:
        raise HTTPException(status_code=400, detail="没有解析到有效的 WO 单号（格式：WO+12位数字）")
    limit = int(payload.limit or MAX_BATCH)
    res = batch_close(valid, limit=limit)
    res["invalid"] = invalid
    logger.info(
        "WO 清理提交：输入 %s 条，关闭 %s，跳过 %s，失败 %s，未找到 %s",
        res["input"]["valid"], res["summary"]["closed"], res["summary"]["skipped"],
        res["summary"]["failed"], res["summary"]["not_found"],
    )
    return res

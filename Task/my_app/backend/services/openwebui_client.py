# -*- coding: utf-8 -*-
"""
Open WebUI 客户端 —— 用「TT单分析」技能（Prompt 预设 TT_PROVITY）分析 TT 工单。

流程
----
1. POST /api/v1/auths/signin 用账号密码登录，拿 JWT（进程内缓存，401 自动重登）
2. GET /api/v1/prompts/list 找 command=TT_PROVITY 的技能内容（"TT单级别分析"）
3. 从本地 eflow_TT_rules.xlsx 读状态=ACTIVE 的规则，随 system 消息内嵌
   （外部模型不走 Open WebUI 知识库 RAG，规则必须显式给出）
4. 按 OPENWEBUI_MODEL 解析候选模型（支持 auto 自动选最新 flash + 失败转移）
5. POST /api/chat/completions（stream=false）拿分析结论；当前模型报错/下线时
   自动切换到下一候选，避免单一模型 ID 失效导致整个 TT 分析不可用

配置（backend/.env，或环境变量）
------------------------------
OPENWEBUI_BASE_URL  默认 http://192.168.100.27:3000
OPENWEBUI_EMAIL     登录邮箱
OPENWEBUI_PASSWORD  登录密码
OPENWEBUI_MODEL     模型策略：
                      固定 ID（如 agnes-2.5-flash）→ 首选它，失败自动降级到 flash 候选
                      auto / auto:<pattern>    → 从 /api/models 里选版本最新的匹配模型
                                                  （默认 pattern=agnes-*-flash，
                                                  自动排除 image/video/embed 类）
EFLOW_TT_RULES_XLSX 规则表路径，默认 backend/services/eflow_rules/eflow_TT_rules.xlsx（定时任务生成处）
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    for _env in (Path(__file__).resolve().parent.parent / ".env",
                 Path(__file__).resolve().parent.parent.parent / ".env"):
        if _env.exists():
            load_dotenv(_env, override=False)
except Exception:  # noqa: BLE001
    logger.warning("load_dotenv 不可用，跳过 backend/.env 加载", exc_info=True)

BASE_URL = os.environ.get("OPENWEBUI_BASE_URL", "http://192.168.100.27:3000").rstrip("/")
EMAIL = os.environ.get("OPENWEBUI_EMAIL", "").strip()
PASSWORD = os.environ.get("OPENWEBUI_PASSWORD", "")
MODEL = os.environ.get("OPENWEBUI_MODEL", "agnes-2.5-flash").strip()

# OPENWEBUI_MODEL=auto / auto:<pattern> 时启用自动选型（fnmatch 匹配 /api/models 的模型 ID）
_AUTO_RE = re.compile(r"^auto(?::(.+))?$", re.IGNORECASE)
_AUTO_DEFAULT_PATTERN = "agnes-*-flash"
# 不参与 TT 分析的模型（多模态/向量模型混在同一个 provider 里）
_AUTO_EXCLUDE_RE = re.compile(r"image|video|embed|bge|whisper|tts", re.IGNORECASE)
# 版本号提取：匹配 agnes-2.5、qwen3:8b 这类 ID 中的数字段做"最新优先"排序
_VER_RE = re.compile(r"(\d+(?:\.\d+)*)")
_FALLBACK_PATTERN = "agnes-*-flash"  # 固定 ID 失败时按此 pattern 生成降级候选

MODELS_TTL = 300  # /api/models 缓存 5 分钟；模型 404/下线时缓存立即失效重查
_MODELS_CACHE: Dict[str, Any] = {"ids": None, "ts": 0.0, "attempts": {}}
_MODELS_LOCK = threading.Lock()

# 定时任务 eflow_TT_Rule_Collector 每天生成的实际位置：backend/services/eflow_rules/
_RULES_DIR = Path(__file__).resolve().parent / "eflow_rules"
RULES_XLSX = Path(os.environ.get(
    "EFLOW_TT_RULES_XLSX",
    str(_RULES_DIR / "eflow_TT_rules.xlsx")))

TT_PROVITY_COMMAND = "TT_PROVITY"

_TIMEOUT = 120
_AUTH_CACHE = {"jwt": "", "ts": 0.0}
_AUTH_LOCK = threading.Lock()


class ModelError(RuntimeError):
    """模型本身不可用（下线/404/上游 5xx/结构异常）——应换下一候选重试。"""


def _http(method: str, path: str, body: Optional[Dict] = None,
          token: str = "", timeout: int = _TIMEOUT):
    """urllib 版 JSON 请求，返回 (status, dict|list|str)。"""
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json",
               "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except ValueError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"请求 {method} {path} 失败: {e}") from e


def signin(force: bool = False) -> str:
    """登录拿 JWT；60 分钟内复用缓存，force=True 或 401 后强制重登。"""
    with _AUTH_LOCK:
        if not force and _AUTH_CACHE["jwt"] and \
                time.time() - _AUTH_CACHE["ts"] < 3600:
            return _AUTH_CACHE["jwt"]
        if not EMAIL or not PASSWORD:
            raise RuntimeError("缺少 OPENWEBUI_EMAIL / OPENWEBUI_PASSWORD 配置")
        status, data = _http("POST", "/api/v1/auths/signin",
                             {"email": EMAIL, "password": PASSWORD})
        if status != 200 or not isinstance(data, dict) or not data.get("token"):
            raise RuntimeError(f"Open WebUI 登录失败 (HTTP {status}): {str(data)[:200]}")
        _AUTH_CACHE["jwt"] = data["token"]
        _AUTH_CACHE["ts"] = time.time()
        return data["token"]


def get_tt_skill(token: str) -> Dict[str, Any]:
    """取 TT_PROVITY 技能（Prompt 预设）内容。"""
    status, data = _http("GET", "/api/v1/prompts/list", token=token)
    if status != 200:
        raise RuntimeError(f"取技能列表失败 (HTTP {status}): {str(data)[:200]}")
    items = data.get("items", data.get("data", [])) \
        if isinstance(data, dict) else data
    for it in items:
        if isinstance(it, dict) and it.get("command") == TT_PROVITY_COMMAND:
            return {"command": it.get("command"),
                    "title": it.get("title") or it.get("name"),
                    "content": it.get("content", "")}
    raise RuntimeError("Open WebUI 里找不到 command=TT_PROVITY 的技能（TT单分析）")


# 规则条件里的 eFlow 表前缀 → 技能入参字段名（vipSite/alarmCode/...）
_PREFIX_RE = re.compile(r"eflow_ticket_ticket_\w+\.", re.IGNORECASE)


def _ver_key(model_id: str):
    """把 'agnes-3.0-flash' 提取成 (3, 0) 这类可比较的版本元组，取不到则 (0,)。"""
    m = _VER_RE.search(model_id or "")
    if not m:
        return (0,)
    parts = m.group(1).split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (0,)


def _list_model_ids(token: str, force_refresh: bool = False) -> List[str]:
    """拿 Open WebUI 可用模型 ID 列表（进程内缓存 MODELS_TTL 秒）。"""
    with _MODELS_LOCK:
        if not force_refresh and _MODELS_CACHE["ids"] is not None and \
                time.time() - _MODELS_CACHE["ts"] < MODELS_TTL:
            return _MODELS_CACHE["ids"]
    status, data = _http("GET", "/api/models", token=token)
    if status != 200 or not isinstance(data, dict):
        raise RuntimeError(f"取模型列表失败 (HTTP {status}): {str(data)[:200]}")
    ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
    with _MODELS_LOCK:
        _MODELS_CACHE["ids"] = ids
        _MODELS_CACHE["ts"] = time.time()
    return ids


def _auto_candidates(token: str, pattern: str) -> List[str]:
    """从模型列表里挑匹配 pattern 的候选，版本号大的排前面（最新 flash 优先）。"""
    ids = _list_model_ids(token)
    picked = [i for i in ids
              if fnmatch(i.lower(), pattern.lower())
              and not _AUTO_EXCLUDE_RE.search(i)]
    picked.sort(key=_ver_key, reverse=True)
    return picked


def resolve_candidates(token: str) -> Tuple[List[str], str]:
    """按 OPENWEBUI_MODEL 策略解析本次调用要尝试的模型候选列表。

    返回 (候选列表按优先级排序, 策略描述)。失败转移顺序：
      固定 ID → [该 ID] + 其余 flash 候选
      auto    → 匹配 pattern 的全部模型，版本最新优先
    """
    m = _AUTO_RE.match(MODEL)
    if m:
        pattern = (m.group(1) or _AUTO_DEFAULT_PATTERN).strip()
        cands = _auto_candidates(token, pattern)
        if not cands:
            raise RuntimeError(
                f"OPENWEBUI_MODEL=auto:{pattern} 在 /api/models 中没有匹配到任何模型")
        return cands, f"auto:{pattern}"
    # 固定 ID：首选配置值，再拼 flash 候选兜底（去重，保持原顺序优先级）
    cands = [MODEL]
    for mid in _auto_candidates(token, _FALLBACK_PATTERN):
        if mid not in cands:
            cands.append(mid)
    return cands, f"fixed:{MODEL}"


def load_active_rules(xlsx_path: Optional[Path] = None) -> str:
    """读 eflow_TT_rules.xlsx 中状态=ACTIVE 的规则，拼成给模型的规则文本。"""
    from openpyxl import load_workbook
    path = Path(xlsx_path or RULES_XLSX)
    if not path.exists():
        raise RuntimeError(f"规则表不存在: {path}")
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if "TT_Rules" not in wb.sheetnames:
            raise RuntimeError(f"规则表缺少 TT_Rules 工作表: {path}")
        ws = wb["TT_Rules"]
        rows = ws.iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(rows)]
        lines, active = [], 0
        for vals in rows:
            rec = dict(zip(header, vals))
            if str(rec.get("状态", "")).strip().upper() != "ACTIVE":
                continue
            cond = _PREFIX_RE.sub("", str(rec.get("条件") or ""))
            cond = " ".join(cond.split())
            name = str(rec.get("规则名称") or "").strip()
            desc = " ".join(str(rec.get("描述") or "").split())
            line = (f"规则ID {rec.get('ID')} | 工单类型 {rec.get('工单类型')} | "
                    f"优先级 {rec.get('优先级')} | {name}")
            if desc:
                line += f" | 描述: {desc}"
            if cond:
                line += f" | 条件: {cond}"
            lines.append(line)
            active += 1
    finally:
        wb.close()
    if not active:
        raise RuntimeError("规则表中没有状态=ACTIVE 的规则")
    return "\n".join(lines)


def _is_model_error(status: int, data: Any) -> bool:
    """判断响应是否属于'模型本身不可用'（下线/404/配额/上游 5xx），应换模型重试。"""
    if status == 404:
        return True
    text = str(data)
    if status == 400 and re.search(
            r"model\s*(not found|not_available|unavailable|invalid)|does not exist|"
            r"is not (a valid|available)|no such model",
            text, re.IGNORECASE):
        return True
    if status >= 500:
        return True
    return False


def chat(system_text: str, user_text: str, token: str,
         model: str = "") -> str:
    """用指定 model 做一次非流式对话；401 时重登一次并重试。"""
    payload = {
        "model": model or MODEL,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "stream": False,
    }
    status, data = _http("POST", "/api/chat/completions",
                         payload, token=token)
    if status == 401:
        token = signin(force=True)
        status, data = _http("POST", "/api/chat/completions",
                             payload, token=token)
    if status != 200:
        raise ModelError(
            f"Open WebUI 对话失败 (HTTP {status}): {str(data)[:200]}") \
            if _is_model_error(status, data) else \
            RuntimeError(f"Open WebUI 对话失败 (HTTP {status}): {str(data)[:200]}")
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ModelError(f"对话响应结构异常: {str(data)[:200]}") from e


def _contains_chinese_narrative(text: str) -> bool:
    """英文结论中只要仍有成段中文即触发英译；避免英文标题掩盖中文正文。"""
    return len(re.findall(r"[\u3400-\u9fff]", text or "")) >= 4


def analyze_tt(skill_prompt: str, with_rules: bool = True, lang: str = "zh") -> Dict[str, Any]:
    """对 inspect_tt 拼出的技能入参做「TT单分析」，返回指定语言的结论 dict。

    lang 支持 zh/en；默认 zh 以兼容现有调用。
    模型按 OPENWEBUI_MODEL 策略解析出候选列表后依次尝试：当前模型 404/下线/
    上游 5xx 时自动换下一候选，并把坏模型在缓存期内踢出候选（防止反复撞同一台）。
    返回: {"ok": True, "conclusion", "model", "model_policy", "failover",
           "skill_title", "elapsed_sec"}
          {"ok": False, "error", "elapsed_sec"}
    """
    t0 = time.time()
    tried: List[str] = []
    try:
        token = signin()
        skill = get_tt_skill(token)
        system_text = skill["content"]
        if with_rules:
            system_text += "\n\n【TT单分析规则库（eflow_TT_rules.xlsx，仅 ACTIVE 规则）】\n" \
                + load_active_rules()
        language_instruction = (
            "Respond entirely in English. Keep identifiers, alarm codes, site names, "
            "field names, and quoted source values unchanged."
            if lang == "en"
            else "请全部使用简体中文回答；标识符、告警码、站点名、字段名和引用的源值保持原样。"
        )
        system_text += f"\n\n【Output language / 输出语言】\n{language_instruction}"
        user_text = f"{skill_prompt}\n\nMANDATORY OUTPUT LANGUAGE: {'English only' if lang == 'en' else '简体中文'}"

        candidates, policy = resolve_candidates(token)
        conclusion, model_used = "", ""
        last_error: Exception = RuntimeError("没有可用模型")
        for model in candidates:
            tried.append(model)
            try:
                conclusion = chat(system_text, user_text, token, model=model).strip()
                model_used = model
                break
            except ModelError as e:
                logger.warning("TT分析模型 %s 不可用，切换下一候选: %s", model, e)
                last_error = e
                # 该模型刚失效：让模型列表缓存立刻过期，下次直接重查
                with _MODELS_LOCK:
                    _MODELS_CACHE["ts"] = 0.0
        if not model_used:
            raise RuntimeError(
                f"所有候选模型均失败 {tried}: {last_error}") from last_error

        # 个别 TT 技能模板会强制中文，覆盖通用 system 指令；英文环境下检测到
        # 结果仍以中文为主时，用独立翻译上下文做一次兜底，不再携带原技能模板。
        language_rewritten = False
        if lang == "en" and _contains_chinese_narrative(conclusion):
            translation_system = (
                "You are a precise telecom operations translator. Translate the complete "
                "TT analysis below into English. Preserve Markdown structure, identifiers, "
                "alarm codes, rule IDs, site names, field names, quoted source values, and "
                "all factual meaning. Output only the English analysis; do not add commentary."
            )
            # 翻译沿用刚验证可用的同一模型，不再重新选型
            conclusion = chat(translation_system, conclusion, token,
                              model=model_used).strip()
            language_rewritten = True

        return {"ok": True, "conclusion": conclusion,
                "model": model_used, "model_policy": policy,
                "failover_tried": tried if len(tried) > 1 else [],
                "skill_title": skill.get("title"),
                "language": lang, "language_rewritten": language_rewritten,
                "elapsed_sec": round(time.time() - t0, 2)}
    except Exception as e:  # noqa: BLE001
        logger.exception("TT单分析失败")
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "failover_tried": tried,
                "elapsed_sec": round(time.time() - t0, 2)}


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    prompt = ("请分析以下TT工单：vipSite=0 alarmCode=9920 siteSubType=ERA "
              "downSiteCount=3 status=ACTIVE\n请严格按照TT单分析知识库中的规则判断")
    t0 = time.time()
    res = analyze_tt(prompt)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"\n总运行时间: {time.time() - t0:.2f} 秒")

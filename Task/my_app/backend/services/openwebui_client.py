# -*- coding: utf-8 -*-
"""
Open WebUI 客户端 —— 用「TT单分析」技能（Prompt 预设 TT_PROVITY）分析 TT 工单。

流程
----
1. POST /api/v1/auths/signin 用账号密码登录，拿 JWT（进程内缓存，401 自动重登）
2. GET /api/v1/prompts/list 找 command=TT_PROVITY 的技能内容（"TT单级别分析"）
3. 从本地 eflow_TT_rules.xlsx 读状态=ACTIVE 的规则，随 system 消息内嵌
   （外部模型 agnes-2.5-flash 不走 Open WebUI 知识库 RAG，规则必须显式给出）
4. POST /api/chat/completions（stream=false）拿分析结论

配置（backend/.env，或环境变量）
------------------------------
OPENWEBUI_BASE_URL  默认 http://192.168.100.27:3000
OPENWEBUI_EMAIL     登录邮箱
OPENWEBUI_PASSWORD  登录密码
OPENWEBUI_MODEL     默认 agnes-2.5-flash
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
from pathlib import Path
from typing import Any, Dict, Optional

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

# 定时任务 eflow_TT_Rule_Collector 每天生成的实际位置：backend/services/eflow_rules/
_RULES_DIR = Path(__file__).resolve().parent / "eflow_rules"
RULES_XLSX = Path(os.environ.get(
    "EFLOW_TT_RULES_XLSX",
    str(_RULES_DIR / "eflow_TT_rules.xlsx")))

TT_PROVITY_COMMAND = "TT_PROVITY"

_TIMEOUT = 120
_AUTH_CACHE = {"jwt": "", "ts": 0.0}
_AUTH_LOCK = threading.Lock()


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


def chat(system_text: str, user_text: str, token: str) -> str:
    """一次非流式对话，返回模型结论文本；401 时重登一次并重试。"""
    payload = {
        "model": MODEL,
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
        raise RuntimeError(f"Open WebUI 对话失败 (HTTP {status}): {str(data)[:200]}")
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"对话响应结构异常: {str(data)[:200]}") from e


def analyze_tt(skill_prompt: str, with_rules: bool = True) -> Dict[str, Any]:
    """对 inspect_tt 拼出的技能入参做「TT单分析」，返回结论 dict。

    返回: {"ok": True, "conclusion", "model", "skill_title", "elapsed_sec"}
          {"ok": False, "error", "elapsed_sec"}
    """
    t0 = time.time()
    try:
        token = signin()
        skill = get_tt_skill(token)
        system_text = skill["content"]
        if with_rules:
            system_text += "\n\n【TT单分析规则库（eflow_TT_rules.xlsx，仅 ACTIVE 规则）】\n" \
                + load_active_rules()
        conclusion = chat(system_text, skill_prompt, token)
        return {"ok": True, "conclusion": conclusion.strip(),
                "model": MODEL, "skill_title": skill.get("title"),
                "elapsed_sec": round(time.time() - t0, 2)}
    except Exception as e:  # noqa: BLE001
        logger.exception("TT单分析失败")
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
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

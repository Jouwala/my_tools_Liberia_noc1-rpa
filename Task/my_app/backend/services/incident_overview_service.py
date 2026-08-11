# -*- coding: utf-8 -*-
"""
事件总览（Incident Overview）业务逻辑层

数据源: data/incident_overview/（版本化文件 incident_overview_<ts>_<rand>.xlsx + current.json 指针，
        旧版固定名 incident_overview.xlsx 作为 best-effort 快照；resolve_excel_path() 自动选最新）
地图边界: data/incident_overview/lr-all.geo.json

从 Unified_Tools/incident_overview/app.py 改写而来，保留：
- 7 个 sheet 的解析逻辑（Status / TT Quality / Owner1 / ZTE / 3rd / Details1 / Details）
- Details sheet 的 mtime 缓存（避免每次请求重读大 Excel）
- 利比里亚地图 GeoJSON 加载
- AI 智能分析（统一分发，provider 参数选择；无 key 时走本地规则）
- 虚拟助手（电话/短信：twilio / aliyun / tencent / none 模拟模式）

改造点：
- print -> logging
- 数据路径收敛到 my_app/data/incident_overview/
- 不引入 flask / openai SDK / python-dotenv，AI 调用统一用 requests 直调 OpenAI 兼容接口
"""
import os
import time
import json
import logging
import datetime

import pandas as pd

logger = logging.getLogger("incident_overview_service")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data", "incident_overview")
EXCEL_FILE = os.path.join(DATA_DIR, "incident_overview.xlsx")          # 旧版固定名 / 人类友好快照（best-effort）
GEOJSON_FILE = os.path.join(DATA_DIR, "lr-all.geo.json")
POINTER_FILE = os.path.join(DATA_DIR, "current.json")                 # 版本化指针
VERSION_PREFIX = "incident_overview_"                                 # 版本化文件前缀

# Details sheet mtime 缓存
_last_excel_mtime = 0
_cached_incident_log = None


# ----------------------------------------------------------------------------
# 当前应读取的 Excel 路径解析（版本化文件 + 指针）
# ----------------------------------------------------------------------------
def _resolve_excel_path_uncached():
    """解析当前应读取的 Excel 路径，优先级：

    1) current.json 指针指向的版本化文件（sync 写入的最新版本，权威）；
    2) 扫描目录中 mtime 最新的 incident_overview_*.xlsx（指针缺失/损坏时兜底）；
    3) 旧版固定名 incident_overview.xlsx（首次迁移或尚无版本化文件时兜底）。

    返回绝对路径字符串。该设计使 Excel 一直打开 incident_overview.xlsx 也不影响
    读取——service 永远读“当前版本”的版本化文件，而非被锁的固定名。
    """
    # 1) 指针
    try:
        if os.path.exists(POINTER_FILE):
            with open(POINTER_FILE, "r", encoding="utf-8") as f:
                info = json.load(f)
            cand = os.path.join(DATA_DIR, info.get("current", ""))
            if cand and os.path.exists(cand):
                return cand
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 current.json 指针失败，回退扫描: %s", e)
    # 2) 扫描最新版本化文件
    try:
        cands = [
            os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR)
            if f.startswith(VERSION_PREFIX) and f.endswith(".xlsx")
        ]
        if cands:
            return max(cands, key=os.path.getmtime)
    except Exception as e:  # noqa: BLE001
        logger.warning("扫描版本化文件失败，回退旧版: %s", e)
    # 3) 旧版固定名
    if os.path.exists(EXCEL_FILE):
        return EXCEL_FILE
    return EXCEL_FILE


def _pointer_key():
    """用于缓存失效判断：指针文件变化时返回其 mtime/size；否则返回最新版本化文件 mtime；
    都没有则返回 ('legacy',)。"""
    try:
        if os.path.exists(POINTER_FILE):
            st = os.stat(POINTER_FILE)
            return ("pointer", st.st_mtime, st.st_size)
    except Exception:  # noqa: BLE001
        pass
    try:
        cands = [
            os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR)
            if f.startswith(VERSION_PREFIX) and f.endswith(".xlsx")
        ]
        if cands:
            return ("scan", max(os.path.getmtime(c) for c in cands))
    except Exception:  # noqa: BLE001
        pass
    return ("legacy",)


_RESOLVE_CACHE = {"key": None, "path": None}


def resolve_excel_path():
    """返回当前应读取的 Excel 路径（带缓存，仅在指针/最新版本变化时重新解析）。"""
    key = _pointer_key()
    c = _RESOLVE_CACHE
    if c["key"] == key and c["path"] and os.path.exists(c["path"]):
        return c["path"]
    path = _resolve_excel_path_uncached()
    c["key"] = key
    c["path"] = path
    return path


def safe_read_excel(sheet_name, header=0):
    """安全读取 Excel sheet，出错时返回空 DataFrame。"""
    try:
        return pd.read_excel(resolve_excel_path(), sheet_name=sheet_name, header=header, engine="openpyxl")
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 sheet %s 失败: %s", sheet_name, e)
        return pd.DataFrame()


# ----------------------------------------------------------------------------
# Status
# ----------------------------------------------------------------------------
def get_status_data():
    df = safe_read_excel("Status")
    result = {}
    if not df.empty:
        for _, row in df.iterrows():
            if len(row) >= 2:
                key = str(row.iloc[0]).strip()
                value = row.iloc[1]
                try:
                    value = int(float(value)) if pd.notna(value) else 0
                except Exception:  # noqa: BLE001
                    value = 0
                result[key] = value
    return result


# ----------------------------------------------------------------------------
# TT Quality
# ----------------------------------------------------------------------------
def get_tt_quality_data():
    df = safe_read_excel("TT Quality")
    result = {}
    if df.empty or len(df) == 0:
        return result
    try:
        first_row = df.iloc[0]
        for col_name, value in zip(df.columns, first_row):
            if pd.notna(value):
                try:
                    num_value = int(float(str(value).replace(",", "").strip()))
                except Exception:  # noqa: BLE001
                    continue
                col_lower = str(col_name).strip().lower()
                if "total" in col_lower:
                    result["Total Incidents"] = num_value
                elif "closed" in col_lower and "unclosed" not in col_lower:
                    result["Closed"] = num_value
                elif "unclosed" in col_lower:
                    result["Unclosed"] = num_value
    except Exception as e:  # noqa: BLE001
        logger.warning("TT Quality 解析失败: %s", e)
    return result


# ----------------------------------------------------------------------------
# Severity（Owner1 sheet）
# ----------------------------------------------------------------------------
def get_severity_data():
    df = safe_read_excel("Owner1")
    result = {}

    domains = ["FO", "BO", "FE", "IPT", "Fiber", "Orange", "3rd"]
    col_severity, col_status = 0, 1
    col_fo, col_bo, col_fe, col_ipt = 2, 3, 4, 5
    col_fiber, col_orange, col_3rd, col_total = 6, 7, 8, 9

    for sev in ["P1", "P2", "P3", "P4"]:
        result[sev] = {
            "total": 0,
            "statuses": {
                name: {d: 0 for d in domains + ["Total"]}
                for name in ["Reassign", "WaitingAccept", "WaitingProcess",
                             "WaitingClose", "WaitingConfirm"]
            },
        }

    if df.empty:
        return result

    def _int(val):
        if pd.notna(val) and str(val).strip() not in ("", "nan"):
            try:
                return int(float(str(val).strip().replace(",", "").replace(" ", "")))
            except Exception:  # noqa: BLE001
                return 0
        return 0

    current_severity = None
    for _, row in df.iterrows():
        if len(row) > col_severity:
            sev_cell = str(row.iloc[col_severity]).strip() if pd.notna(row.iloc[col_severity]) else ""
            if sev_cell and sev_cell.startswith("P"):
                upper = sev_cell.upper()
                for p in ["P1", "P2", "P3", "P4"]:
                    if p in upper:
                        current_severity = p
                        break
                else:
                    current_severity = None

        if not current_severity or len(row) <= col_status:
            continue
        status_cell = str(row.iloc[col_status]).strip() if pd.notna(row.iloc[col_status]) else ""
        if not status_cell:
            continue
        status_upper = status_cell.upper().strip()
        current_status = None
        if "REASSIGN" in status_upper:
            current_status = "Reassign"
        elif "WAITINGACCEPT" in status_upper:
            current_status = "WaitingAccept"
        elif "WAITINGPROCESS" in status_upper:
            current_status = "WaitingProcess"
        elif "WAITINGCLOSE" in status_upper:
            current_status = "WaitingClose"
        elif "WAITINGCONFIRM" in status_upper:
            current_status = "WaitingConfirm"
        elif status_upper == "ACCEPT":
            current_status = "WaitingAccept"
        elif status_upper == "PROCESS":
            current_status = "WaitingProcess"
        elif status_upper == "CLOSE":
            current_status = "WaitingClose"
        elif status_upper == "CONFIRM":
            current_status = "WaitingConfirm"
        if not current_status:
            continue

        node = result[current_severity]["statuses"][current_status]
        node["FO"] = _int(row.iloc[col_fo]) if len(row) > col_fo else 0
        node["BO"] = _int(row.iloc[col_bo]) if len(row) > col_bo else 0
        node["FE"] = _int(row.iloc[col_fe]) if len(row) > col_fe else 0
        node["IPT"] = _int(row.iloc[col_ipt]) if len(row) > col_ipt else 0
        node["Fiber"] = _int(row.iloc[col_fiber]) if len(row) > col_fiber else 0
        node["Orange"] = _int(row.iloc[col_orange]) if len(row) > col_orange else 0
        node["3rd"] = _int(row.iloc[col_3rd]) if len(row) > col_3rd else 0
        if node["Total"] == 0:
            node["Total"] = (node["FO"] + node["BO"] + node["FE"] + node["IPT"]
                             + node["Fiber"] + node["Orange"] + node["3rd"])

    for sev in result:
        result[sev]["total"] = sum(s["Total"] for s in result[sev]["statuses"].values())
    return result


# ----------------------------------------------------------------------------
# SLA（ZTE / 3rd sheet）
# ----------------------------------------------------------------------------
def get_sla_data(sheet_name):
    df = safe_read_excel(sheet_name)
    result = {}
    if df.empty:
        return result
    target_keys = ["gt100", "lt100", "lt75", "lt50", "lt25"]
    for _, row in df.iterrows():
        first_col = str(row.iloc[0]).strip() if len(row) > 0 else ""
        severity = None
        for p in ["P1", "P2", "P3", "P4"]:
            if p in first_col.upper():
                severity = p
                break
        if not severity:
            continue
        result[severity] = {k: 0 for k in target_keys}
        numeric_values = []
        for col_idx in range(1, len(row)):
            val = row.iloc[col_idx]
            try:
                if pd.notna(val):
                    numeric_values.append(int(float(str(val).replace(",", ""))))
            except (ValueError, TypeError):
                continue
        for i, val in enumerate(numeric_values):
            if i < len(target_keys):
                result[severity][target_keys[i]] = val
    return result


# ----------------------------------------------------------------------------
# 利比里亚 站点 -> 县 兜底映射
# ----------------------------------------------------------------------------
# 优先使用文件自带的州/县列（若远程真文件带 Region/State 列，直接采用，不覆盖）。
# 本表仅在文件无州列时作为兜底：覆盖主要城镇，未命中返回空串（不误分配）。
LIBERIA_COUNTIES = [
    'Bomi', 'Bong', 'Gbarpolu', 'Grand Bassa', 'Grand Cape Mount',
    'Grand Gedeh', 'Grand Kru', 'Lofa', 'Margibi', 'Maryland',
    'Montserrado', 'Nimba', 'River Cess', 'River Gee', 'Sinoe',
]

# 城镇/地名 -> 县（保守：仅高置信度条目；其余留空，避免错分县）
_SITE_TO_COUNTY = {
    # Montserrado
    'monrovia': 'Montserrado', 'paynesville': 'Montserrado', 'duala': 'Montserrado',
    'bensonville': 'Montserrado', 'brewerville': 'Montserrado', 'caldwell': 'Montserrado',
    'careysburg': 'Montserrado', 'johnsonville': 'Montserrado', 'congo town': 'Montserrado',
    'sinkor': 'Montserrado', 'virginia': 'Montserrado', 'elwa': 'Montserrado',
    # Bomi
    'tubmanburg': 'Bomi', 'klay': 'Bomi', 'dei': 'Bomi', 'gbarma': 'Bomi', 'mecca': 'Bomi',
    # Bong
    'gbarnga': 'Bong', 'salala': 'Bong', 'suakoko': 'Bong', 'kokoya': 'Bong',
    'zota': 'Bong', 'fuamah': 'Bong', 'palala': 'Bong', 'bong mines': 'Bong',
    # Grand Bassa
    'buchanan': 'Grand Bassa', 'owensgrove': 'Grand Bassa', 'st. john': 'Grand Bassa',
    'neekreen': 'Grand Bassa',
    # Grand Cape Mount
    'robertsport': 'Grand Cape Mount', 'bo waterside': 'Grand Cape Mount',
    'tienii': 'Grand Cape Mount', 'cape mount': 'Grand Cape Mount',
    # Grand Gedeh
    'zwedru': 'Grand Gedeh', 'tchien': 'Grand Gedeh', 'toe town': 'Grand Gedeh',
    'putch': 'Grand Gedeh',
    # Grand Kru
    'barclayville': 'Grand Kru', 'sasstown': 'Grand Kru', 'buah': 'Grand Kru',
    # Lofa
    'voinjama': 'Lofa', 'zorzor': 'Lofa', 'foya': 'Lofa', 'kolahun': 'Lofa', 'vahun': 'Lofa',
    'belleh': 'Lofa', 'salayea': 'Lofa',
    # Margibi
    'kakata': 'Margibi', 'harbel': 'Margibi', 'gibi': 'Margibi', 'cotton tree': 'Margibi',
    'firestone': 'Margibi',
    # Maryland
    'harper': 'Maryland', 'pleebo': 'Maryland', 'cavalla': 'Maryland', 'karluway': 'Maryland',
    'barrobo': 'Maryland',
    # Nimba
    'ganta': 'Nimba', 'sanniquellie': 'Nimba', 'tappita': 'Nimba', 'saclepea': 'Nimba',
    'ziah': 'Nimba', 'doe': 'Nimba', 'bunadin': 'Nimba', 'gbedin': 'Nimba', 'bapi': 'Nimba',
    # River Cess
    'cestos': 'River Cess', 'yarpah': 'River Cess', 'nyankun': 'River Cess',
    # River Gee
    'fishtown': 'River Gee', 'gbeapo': 'River Gee', 'webbo': 'River Gee',
    'kanweaken': 'River Gee', 'chedepo': 'River Gee', 'karvor': 'River Gee',
    # Sinoe
    'greenville': 'Sinoe', 'dugbe river': 'Sinoe', 'jaedee': 'Sinoe', 'butaw': 'Sinoe',
    'po river': 'Sinoe',
    # Gbarpolu
    'bopolu': 'Gbarpolu', 'gbapolu': 'Gbarpolu',
}


def _derive_state(site_name, site_id):
    """从站点名/ID 兜底推断所属县；命中返回规范县名，否则返回空串。"""
    cand = " ".join(str(x) for x in (site_name, site_id)
                    if x is not None and str(x).strip() != "").lower()
    if not cand:
        return ""
    # 1) 直接命中县名（如站点名含 "River Gee"）
    for c in LIBERIA_COUNTIES:
        if c.lower() in cand:
            return c
    # 2) 城镇字典
    for town, county in _SITE_TO_COUNTY.items():
        if town in cand:
            return county
    return ""


# ----------------------------------------------------------------------------
# Details（Details1 sheet，全量）
# ----------------------------------------------------------------------------
def get_details_data():
    df = safe_read_excel("Details1")
    result = []
    columns = []
    if not df.empty:
        columns = [str(c) for c in df.columns]
        # 是否已有州/县列（优先用文件自带）
        native_col = next((c for c in columns
                           if 'region' in c.lower() or 'state' in c.lower()), None)
        site_id_col = next((c for c in columns if c.lower() == 'site id'), None)
        site_name_col = next((c for c in columns if c.lower() == 'site name'), None)
        if not native_col:
            columns = columns + ["State"]
        for _, row in df.iterrows():
            ticket = {}
            for col_idx, col_name in enumerate(df.columns):
                value = row.iloc[col_idx] if col_idx < len(row) else ""
                if pd.notna(value):
                    if isinstance(value, (int, float)):
                        ticket[str(col_name)] = value
                    else:
                        vs = str(value).strip()
                        try:
                            ticket[str(col_name)] = float(vs)
                        except ValueError:
                            ticket[str(col_name)] = vs
                else:
                    ticket[str(col_name)] = ""
            # 注入 State：优先文件自带，否则按站点名兜底推断
            if native_col:
                ticket["State"] = ticket.get(native_col, "")
            else:
                sn = ticket.get(site_name_col) if site_name_col else ticket.get("Site Name")
                sid = ticket.get(site_id_col) if site_id_col else ticket.get("Site ID")
                ticket["State"] = _derive_state(sn, sid)
            result.append(ticket)
    return {"data": result, "columns": columns}


# ----------------------------------------------------------------------------
# Incident Log（Details sheet，mtime 缓存 + 分页由 router 处理）
# ----------------------------------------------------------------------------
def get_incident_log_data(force=False):
    global _last_excel_mtime, _cached_incident_log
    excel_path = resolve_excel_path()
    if not os.path.exists(excel_path):
        return {"data": [], "columns": []}

    mtime = os.path.getmtime(excel_path)
    if not force and mtime == _last_excel_mtime and _cached_incident_log is not None:
        return _cached_incident_log

    logger.info("Excel 已变更，重新解析 Incident Log ...")
    df = safe_read_excel("Details")
    result = []
    columns = []
    if not df.empty:
        columns = [str(c) for c in df.columns]
        df = df.fillna("")
        result = df.to_dict("records")
        for i, ticket in enumerate(result):
            for col_name, value in list(ticket.items()):
                if value == "":
                    continue
                if isinstance(value, str):
                    vs = value.strip()
                    if vs:
                        try:
                            nv = float(vs)
                            result[i][col_name] = int(nv) if nv.is_integer() else nv
                        except ValueError:
                            pass

    _cached_incident_log = {"data": result, "columns": columns}
    _last_excel_mtime = mtime
    return _cached_incident_log


# ----------------------------------------------------------------------------
# GeoJSON
# ----------------------------------------------------------------------------
def load_geojson():
    if os.path.exists(GEOJSON_FILE):
        try:
            with open(GEOJSON_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:  # noqa: BLE001
            logger.warning("加载 GeoJSON 失败: %s", e)
            return None
    return None


# ----------------------------------------------------------------------------
# 一次性聚合（/all）
# ----------------------------------------------------------------------------
def get_all_data():
    excel_path = resolve_excel_path()
    if not os.path.exists(excel_path):
        return {"error": f"Excel file not found: {excel_path}"}
    result, errors = {}, []
    try:
        result["status"] = get_status_data()
    except Exception as e:  # noqa: BLE001
        errors.append(f"status: {e}")
        result["status"] = {}
    try:
        result["tt_quality"] = get_tt_quality_data()
    except Exception as e:  # noqa: BLE001
        errors.append(f"tt_quality: {e}")
        result["tt_quality"] = {}
    try:
        result["severity"] = get_severity_data()
    except Exception as e:  # noqa: BLE001
        errors.append(f"severity: {e}")
        result["severity"] = {}
    try:
        result["sla_zte"] = get_sla_data("ZTE")
    except Exception as e:  # noqa: BLE001
        errors.append(f"sla_zte: {e}")
        result["sla_zte"] = {}
    try:
        result["sla_3rd"] = get_sla_data("3rd")
    except Exception as e:  # noqa: BLE001
        errors.append(f"sla_3rd: {e}")
        result["sla_3rd"] = {}
    try:
        det = get_details_data()
        result["details"] = det.get("data", [])
        result["details_columns"] = det.get("columns", [])
    except Exception as e:  # noqa: BLE001
        errors.append(f"details: {e}")
        result["details"] = []
        result["details_columns"] = []
    if errors:
        result["errors"] = errors
    return result


# ----------------------------------------------------------------------------
# AI 智能分析（统一分发）
# ----------------------------------------------------------------------------
def _call_openai_compatible(url, api_key, model, prompt, system_prompt, temperature=0.7, max_tokens=1500):
    import requests  # 懒加载
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _call_gemini(api_key, model, prompt, system_prompt):
    import requests
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": f"{system_prompt}\n\n{prompt}"}]}]}
    resp = requests.post(url, json=payload, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


# 各 provider 默认配置（均可通过参数覆盖）
_PROVIDER_DEFAULTS = {
    "openai": {"url": "https://api.openai.com/v1/chat/completions", "model": "gpt-3.5-turbo"},
    "deepseek": {"url": "https://api.deepseek.com/v1/chat/completions", "model": "deepseek-chat"},
    "qianwen": {"url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                "model": "qwen-plus"},
    "glm": {"url": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "model": "glm-4-plus"},
    "doubao": {"url": "https://ark.cn-beijing.volcengine.com/api/v3/chat/completions",
               "model": "doubao-pro-4k"},
    "gemini": {"url": None, "model": "gemini-pro"},
}

_SYSTEM_PROMPT = ("You are a data analyst specializing in incident management systems. "
                  "Respond in the same language as the user's question.")


def analyze_with_ai(provider="local", api_key=None, base_url=None, model=None,
                    prompt=None, lang="zh", context=None):
    """统一 AI 分发。provider 不在已知列表或没有 api_key 时，回退到本地规则。"""
    provider = (provider or "local").lower()
    is_en = (lang or "zh").lower() == "en"

    if not prompt:
        prompt = _build_default_prompt(context or {}, is_en)

    # 本地规则模式（默认、无需 API）
    if provider == "local" or provider == "rule-based" or not api_key:
        return {"analysis": local_rules_summary(context or {}, is_en), "provider": "local"}

    try:
        if provider == "gemini":
            key = api_key or os.environ.get("GEMINI_API_KEY")
            if not key:
                return {"analysis": local_rules_summary(context or {}, is_en),
                        "provider": "local", "note": "未配置 Gemini API key，已回退本地规则"}
            return {"analysis": _call_gemini(key, model or "gemini-pro", prompt, _SYSTEM_PROMPT),
                    "provider": "gemini"}
        cfg = _PROVIDER_DEFAULTS.get(provider)
        if not cfg:
            return {"error": f"不支持的 AI 提供商: {provider}"}
        url = base_url or cfg["url"]
        model_name = model or cfg["model"]
        return {"analysis": _call_openai_compatible(url, api_key, model_name, prompt, _SYSTEM_PROMPT),
                "provider": provider}
    except Exception as e:  # noqa: BLE001
        logger.warning("AI 调用失败，回退本地规则: %s", e)
        return {"analysis": local_rules_summary(context or {}, is_en),
                "provider": "local", "note": f"AI 调用失败: {e}"}


def _build_default_prompt(context, is_en):
    if is_en:
        return "Please analyze the following incident management overview data and highlight risks."
    return "请基于以下事件管理总览数据进行分析，并重点提示风险。"


def local_rules_summary(context, is_en):
    """基于事件总览数据的本地规则摘要（无 API 也可用）。"""
    lines = []
    if is_en:
        lines.append("Incident Overview - Local Rules Summary")
        lines.append("=" * 50)
        status = context.get("status", {})
        if status:
            lines.append(f"Total status metrics: {len(status)}")
            for k, v in list(status.items())[:10]:
                lines.append(f"  - {k}: {v}")
        tt = context.get("tt_quality", {})
        if tt:
            lines.append(f"TT Quality: Total={tt.get('Total Incidents')}, "
                         f"Closed={tt.get('Closed')}, Unclosed={tt.get('Unclosed')}")
        sev = context.get("severity", {})
        if sev:
            lines.append("Severity distribution:")
            for p in ["P1", "P2", "P3", "P4"]:
                if p in sev:
                    lines.append(f"  - {p}: {sev[p].get('total', 0)} tickets")
        lines.append("")
        lines.append("Note: This is a rules-based summary. Configure an AI provider "
                     "(OpenAI/DeepSeek/Qianwen/GLM/Doubao/Gemini) with an API key for deep analysis.")
    else:
        lines.append("事件总览 - 本地规则摘要")
        lines.append("=" * 50)
        status = context.get("status", {})
        if status:
            lines.append(f"状态指标总数: {len(status)}")
            for k, v in list(status.items())[:10]:
                lines.append(f"  - {k}: {v}")
        tt = context.get("tt_quality", {})
        if tt:
            lines.append(f"工单质量: 总数={tt.get('Total Incidents')}, "
                         f"已关闭={tt.get('Closed')}, 未关闭={tt.get('Unclosed')}")
        sev = context.get("severity", {})
        if sev:
            lines.append("严重度分布:")
            for p in ["P1", "P2", "P3", "P4"]:
                if p in sev:
                    lines.append(f"  - {p}: {sev[p].get('total', 0)} 单")
        lines.append("")
        lines.append("说明：以上为本地规则摘要。配置 AI 提供商（OpenAI/DeepSeek/通义/GLM/豆包/Gemini）"
                     "并填入 API key 后可获得深度分析。")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 虚拟助手（电话 / 短信）
# ----------------------------------------------------------------------------
def assistant_call(phone, message, ticket=None):
    if not phone:
        return {"error": "Phone number required"}
    if not message:
        return {"error": "Message required"}
    provider = os.environ.get("PHONE_SERVICE_PROVIDER", "none").lower()
    logger.info("[虚拟助手] 电话通知: %s, 服务商: %s", phone, provider)

    if provider == "twilio":
        try:
            from twilio.rest import Client
            sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
            token = os.environ.get("TWILIO_AUTH_TOKEN", "")
            number = os.environ.get("TWILIO_PHONE_NUMBER", "")
            if not all([sid, token, number]):
                return {"error": "Twilio 配置不完整",
                        "required": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"]}
            client = Client(sid, token)
            call = client.calls.create(
                url=f'http://twimlets.com/echo?Twiml=%3CResponse%3E%3CSay%3E{message}%3C%2FSay%3E%3C%2FResponse%3E',
                to=phone, from_=number)
            return {"success": True, "message": "电话通知已发送", "call_sid": call.sid, "provider": "Twilio"}
        except ImportError:
            return {"error": "Twilio 库未安装，请运行: pip install twilio"}
        except Exception as e:  # noqa: BLE001
            return {"error": f"Twilio 调用失败: {e}"}

    if provider == "aliyun":
        # 阿里云语音依赖 aliyun-sdk，未安装时直接报缺依赖，不静默失败
        return {"error": "阿里云语音服务未启用（需 aliyun-python-sdk-core）",
                "install": "pip install aliyun-python-sdk-core aliyun-python-sdk-dyvmsapi"}

    if provider == "tencent":
        return {"error": "腾讯云语音服务未启用（需 tencentcloud-sdk-python）",
                "install": "pip install tencentcloud-sdk-python"}

    # 默认模拟模式
    return {"success": True, "message": "电话通知已发送（模拟模式）",
            "note": "当前为模拟模式，未实际拨打电话。配置 PHONE_SERVICE_PROVIDER 选择服务商。",
            "provider": "none"}


def assistant_sms(phone, message, ticket=None):
    if not phone:
        return {"error": "Phone number required"}
    if not message:
        return {"error": "Message required"}
    provider = os.environ.get("SMS_SERVICE_PROVIDER", "none").lower()
    logger.info("[虚拟助手] 短信通知: %s, 服务商: %s", phone, provider)

    if provider == "twilio":
        try:
            from twilio.rest import Client
            sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
            token = os.environ.get("TWILIO_AUTH_TOKEN", "")
            number = os.environ.get("TWILIO_PHONE_NUMBER", "")
            if not all([sid, token, number]):
                return {"error": "Twilio 配置不完整",
                        "required": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"]}
            client = Client(sid, token)
            msg = client.messages.create(body=message, to=phone, from_=number)
            return {"success": True, "message": "短信已发送", "sid": msg.sid, "provider": "Twilio"}
        except ImportError:
            return {"error": "Twilio 库未安装，请运行: pip install twilio"}
        except Exception as e:  # noqa: BLE001
            return {"error": f"Twilio 调用失败: {e}"}

    if provider in ("aliyun", "tencent"):
        return {"error": f"{provider} 短信服务未启用，请配置对应 SDK 与凭证"}

    return {"success": True, "message": "短信已发送（模拟模式）",
            "note": "当前为模拟模式，未实际发送。配置 SMS_SERVICE_PROVIDER 选择服务商。",
            "provider": "none"}

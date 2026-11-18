# -*- coding: utf-8 -*-
"""cn_hourly_kpi_service.py — CN 小时粒度 KPI 同步（cn_hourly_kpi_sync）

=========================== 数据源：KPI Template.xlsx ===========================

`backend/services/cn_kpl/KPI Template.xlsx` 是 UME 网管「KPI 模板管理」导出件
（2026-11-17 新建的一批 8 个模板，研究结论见 `TMP/_kpi_template_研究报告.md`）：

  · `template` sheet 每行 = 一个查询模板，字段与 `ccn_ume_kpi_service.CNN_KPI_QUERY_CONFIGS`
    一条配置一一对应（id→templateid、i18nname.en→templatename、items/gr/grouplayer/
    motid/nfctid 原样照搬），组包交给既有 `build_cnn_kpi_payload` 即可，零新查询代码；
  · `index` sheet 是复合 KPI 定义（indexcount 公式），是页面口径说明的素材来源。

=========================== 口径决定（用户 2026-11-18 定） ===========================

  1. **Resource_Utilization 与 Resource_Capacity 两族重复，只保留 Utilization 一族。**
     xlsx 里 CS_MGW91/92/MRFP96 的三个 Utilization 模板 items/motid/grouplayer
     **完全一致**（同 motid 50804、同 3 个复合 KPI），任取其一即可；本服务取
     `CS_MRFP96_Resource_Utilization_OSS` 做载体，表名沿用 `<模板名>_UME` 惯例。
     （Capacity 族是 6 个原始 counter，utilization 已覆盖其口径，弃用。）
  2. **Object Scope = ALL**：既有 payload 的 `filterlayer="all"` 即对应此选择，
     实测导出自动包含全部 NE（MGW_91 / MGW_92 / MRFP_96 / xGWU22 / xGWU122），
     无需额外参数。
  3. **粒度 gr=3600（1 小时）**；首次回补一个月（31 天），日常每天增量（默认 2 天窗口）。
  4. **落库走 DbWriterClient → db_ps_cs_cn.sqlite3**（与既有 CNN 表同一库同一通道），
     表名 `<模板名>_UME`，读取走 `cn_kpi_service.query_remote`（远端只读 API）。

参与模板（3 个）：
  PS_xGW_Session_Capacity_OSS      xGW PFCP 会话 授权/已用（原始 counter）
  PS_xGW_Throughput_Capacity_OSS   xGW 吞吐 容量/已用（原始 counter）
  CS_MRFP96_Resource_Utilization_OSS  MGW_91/92 + MRFP_96 的 TONE/TC/RTP 资源利用率（%）

=========================== 解析坑（实测踩过） ===========================

  · xlsx 里布尔列是**字符串** "false"/"true"，`bool("false")` 是 True —— 必须显式判；
  · motid/templateid/gr 必须保持字符串（motid "50900,50300" 之类逗号串的先例）；
  · items/itemsposition 是 JSON 字符串，loads 后核对长度一致。

运行环境注意：登录链路（auth_manager → cryptography）必须用 my_app 实际运行
环境（系统 Python312）；DSH 内置 python 缺 cryptography 会登录失败。
"""
from __future__ import annotations

import copy
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.services import ccn_ume_kpi_service as base

logger = logging.getLogger("cn_hourly_kpi")

HERE = Path(__file__).resolve().parent
XLSX_PATH = HERE / "KPI Template.xlsx"

# 参与同步的模板（模板名 = xlsx template sheet 的 i18nname.en）
TEMPLATE_KEYS = [
    "PS_xGW_Session_Capacity_OSS",
    "PS_xGW_Throughput_Capacity_OSS",
    "CS_MRFP96_Resource_Utilization_OSS",
]

# 首次回补窗口（天）：用户定「一个月」
BACKFILL_DAYS = int(os.environ.get("CN_HOURLY_KPI_BACKFILL_DAYS", "31"))
# 日常增量窗口（天）：小时行 append-only，2 天窗口容忍跨天补档
RECENT_DAYS = int(os.environ.get("CN_HOURLY_KPI_DAYS_BACK", "2"))

# xlsx 缺失/解析失败时的兜底配置（与 2026-11-18 实测解析结果逐字段一致；
# 修改上游模板后应重新导出 xlsx 而不是手改这里 —— 这里只是保险丝）
FALLBACK_CONFIGS: dict[str, dict] = {
    "PS_xGW_Session_Capacity_OSS": {
        "favoriteconditionname": "PS_xGW_Session_Capacity_OSS",
        "templatename": "PS_xGW_Session_Capacity_OSS",
        "templateid": "1649220598389", "gr": "3600", "groupbygroup": False,
        "filterlayer": "all", "grouplayer": "orignaldata_layermoc",
        "motid": "55035", "nfctid": "cn.ngc.xgw-u",
        "items": ["C550350011", "C550350012"],
        "itemsposition": [0, 0], "itemsposition1": [0, 0],
        "groupchoice": None, "invaliditems": [],
        "table_name": "PS_xGW_Session_Capacity_OSS_UME",
    },
    "PS_xGW_Throughput_Capacity_OSS": {
        "favoriteconditionname": "PS_xGW_Throughput_Capacity_OSS",
        "templatename": "PS_xGW_Throughput_Capacity_OSS",
        "templateid": "1649220598391", "gr": "3600", "groupbygroup": False,
        "filterlayer": "all", "grouplayer": "orignaldata_layermoc",
        "motid": "55035", "nfctid": "cn.ngc.xgw-u",
        "items": ["C550350014", "C550350015"],
        "itemsposition": [0, 0], "itemsposition1": [0, 0],
        "groupchoice": None, "invaliditems": [],
        "table_name": "PS_xGW_Throughput_Capacity_OSS_UME",
    },
    "CS_MRFP96_Resource_Utilization_OSS": {
        "favoriteconditionname": "CS_MRFP96_Resource_Utilization_OSS",
        "templatename": "CS_MRFP96_Resource_Utilization_OSS",
        "templateid": "1649220598386", "gr": "3600", "groupbygroup": False,
        "filterlayer": "all", "grouplayer": "me",
        "motid": "50804", "nfctid": "cn.wcn.mgw",
        "items": ["cn.ngmgw.508049015", "cn.ngmgw.508049017", "cn.ngmgw.508049018"],
        "itemsposition": [0, 0, 0], "itemsposition1": [0, 0, 0],
        "groupchoice": None, "invaliditems": [],
        "table_name": "CS_MRFP96_Resource_Utilization_OSS_UME",
    },
}


# ============================================================
# KPI Template.xlsx 解析（template sheet → CNN_KPI_QUERY_CONFIGS 同构配置）
# ============================================================
def _cell_bool(v) -> bool:
    """xlsx 布尔列是字符串 'false'/'true'；bool('false') 是 True，必须显式判。"""
    if isinstance(v, bool):
        return v
    return v is not None and str(v).strip().lower() == "true"


def _cell_json(v):
    if v is None or v == "":
        return None
    try:
        return json.loads(v)
    except Exception:
        logger.warning("[CN-HOURLY] 非法 JSON 单元格，按原值处理: %r", str(v)[:80])
        return v


def parse_template_xlsx(xlsx_path: os.PathLike | str = XLSX_PATH) -> dict[str, dict]:
    """把 KPI Template.xlsx 的 template sheet 解析成 CNN_KPI_QUERY_CONFIGS 同构配置。

    返回 {模板名: cfg}。字段映射依据见模块头；额外字段（columnheader/
    effectiveDate/thresholdinfos 等）既有 builder 已固定或不参与查询，不透传。
    """
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    try:
        ws = wb["template"]
    finally:
        wb.close()
    hdr = [c.value for c in ws[1]]
    configs: dict[str, dict] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        d = dict(zip(hdr, row))
        name_json = _cell_json(d.get("i18nname"))
        name = name_json.get("en") if isinstance(name_json, dict) else d.get("i18nname")
        if not name or not d.get("id"):
            continue
        items = _cell_json(d.get("items")) or []
        pos = _cell_json(d.get("itemsposition")) or []
        pos1 = _cell_json(d.get("itemsposition1")) or pos
        if not isinstance(items, list) or not isinstance(pos, list) or len(items) != len(pos):
            raise ValueError(f"[CN-HOURLY] 模板 {name}: items/positions 长度不一致，放弃解析")
        cfg = {
            "favoriteconditionname": name,
            "templatename": name,
            "templateid": str(d["id"]),
            "gr": str(d["gr"]),
            "groupbygroup": _cell_bool(d.get("groupbygroup")),
            "filterlayer": "all",
            "grouplayer": d.get("grouplayer") or "me",
            "motid": str(d["motid"]),
            "nfctid": d.get("nfctid"),
            "items": items,
            "itemsposition": pos,
            "itemsposition1": pos1,
            "groupchoice": None,
            "invaliditems": [],
            "table_name": f"{name}_UME",
        }
        configs[name] = cfg
    return configs


def load_hourly_configs() -> dict[str, dict]:
    """按 TEMPLATE_KEYS 取配置：优先解析 xlsx，失败回退 FALLBACK_CONFIGS 并显式告警。

    返回 {模板名: cfg}。解析出的配置以 xlsx 为准（上游改模板后重新导出即可），
    兜底值只在 xlsx 不可用时让任务继续出数 —— 两者以 templateid 是否一致为准校验。
    """
    try:
        parsed = parse_template_xlsx()
    except Exception as e:  # noqa: BLE001 — xlsx 被挪走/损坏时任务不能整体停摆
        logger.error("[CN-HOURLY] 解析 %s 失败（%s: %s），使用内置兜底配置",
                     XLSX_PATH, type(e).__name__, e)
        parsed = {}
    out: dict[str, dict] = {}
    for key in TEMPLATE_KEYS:
        cfg = parsed.get(key)
        if cfg is None:
            cfg = copy.deepcopy(FALLBACK_CONFIGS[key])
            if parsed:  # xlsx 解析成功但缺这个模板 → 上游可能删了模板，值得一条显式告警
                logger.warning("[CN-HOURLY] xlsx 里没有模板 %s，使用内置兜底配置", key)
        elif cfg.get("templateid") != FALLBACK_CONFIGS[key]["templateid"]:
            logger.info("[CN-HOURLY] 模板 %s 的 templateid 与兜底值不同（xlsx=%s），以 xlsx 为准",
                        key, cfg.get("templateid"))
        out[key] = cfg
    return out


# ============================================================
# 查询 → 导出 → 落库
# ============================================================
def _window_iso(days_back: int) -> tuple[str, str]:
    """小时数据的查询窗口：起点 = (今天 00:00 - days_back)，终点 = 现在（含今天已有小时）。"""
    now = datetime.now(timezone.utc)
    end_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    start_iso = (now.replace(hour=0, minute=0, second=0, microsecond=0)
                 - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return start_iso, end_iso


def _query_export_one(auth: dict, cfg: dict, start_iso: str, end_iso: str) -> tuple[str, bytes]:
    """单模板：建查询 → 轮询 → 导出 xlsx 字节。401/403 恢复鉴权重试一次
    （与 ccn_ume_kpi_service._run_single_kpi_query 同一套有限重试约定）。"""
    payload = base.build_cnn_kpi_payload(cfg, start_iso=start_iso, end_iso=end_iso)
    logger.info("[CN-HOURLY] %s 查询 %s → %s (gr=%s)",
                cfg["templatename"], start_iso, end_iso, cfg["gr"])
    for attempt in (1, 2):
        try:
            queryid = base.create_history_query(auth["cookie"], auth["forgery_token"], payload)
            base.wait_history_ready(auth["cookie"], auth["forgery_token"], queryid,
                                    timeout=600, interval=5)
            xlsx_bytes = base.export_history(
                auth["cookie"], auth["forgery_token"], queryid,
                f"{base.build_filename(cfg)}_hourly")
            return cfg["table_name"], xlsx_bytes
        except Exception as e:
            if attempt == 1 and base._looks_like_auth_failure(e) and base._refresh_auth_on_401(auth):
                logger.warning("[CN-HOURLY] %s 会话失效（%s），恢复鉴权后重试一次",
                               cfg["templatename"], e)
                continue
            raise


def _upsert_table(table_name: str, xlsx_bytes: bytes) -> int:
    """解析导出 xlsx 并 upsert 进 DB CNN（复用 import_to_database 的主键/清洗约定）。"""
    headers, data = base.read_xlsx_bytes(xlsx_bytes)
    if not data:
        # 与 5mins 同款兜底：导出 0 行不算失败（上游模板档位可能再调整）
        logger.warning("[CN-HOURLY] %s: 导出 0 行，跳过写库", table_name)
        return 0
    key_cols = base.detect_key_cols(headers)
    if not key_cols:
        raise ValueError(f"[CN-HOURLY] {table_name}: 缺少 Begin Time 列，解析失败")
    if not base._cols_unique(headers, data, key_cols):
        for cand in headers:  # 自然主键不唯一时扩展一次（与 import_to_database 同策略）
            if cand in key_cols:
                continue
            expanded = key_cols + [cand]
            if base._cols_unique(headers, data, expanded):
                logger.warning("[CN-HOURLY] %s: 主键扩展为 %s", table_name, expanded)
                key_cols = expanded
                break
        else:
            raise ValueError(f"[CN-HOURLY] {table_name}: 无法凑出唯一主键(自然键={key_cols!r})")
    if base._db_writer is None:
        raise RuntimeError("[CN-HOURLY] db_writer 不可用，无法写入")
    key_idx = [headers.index(k) for k in key_cols if k in headers]
    rows = []
    for row in data:
        if len(row) < len(headers):
            row = list(row) + [None] * (len(headers) - len(row))
        elif len(row) > len(headers):
            row = row[:len(headers)]
        clean = [str(v) if v is not None else None for v in row]
        for i in key_idx:  # 主键空值填 ""，避免 NOT NULL 主键写失败
            if clean[i] is None:
                clean[i] = ""
        rows.append(clean)
    result = base._db_writer.write_data(
        db=base.DB_NAME, table=table_name, columns=headers, rows=rows,
        mode="upsert", pk_columns=key_cols,
    )
    written = result.get("rows_written", 0)
    logger.info("[CN-HOURLY] %s: %s 行解析，主键=%s，写入 %s 行",
                table_name, len(rows), key_cols, written)
    return len(rows)


def run_cn_hourly_kpi_sync(days_back: int = None) -> dict:
    """CN 小时 KPI 同步主流程：登录 → 逐模板查询/导出 → upsert 落库。

    days_back: 查询窗口天数；None 时取 RECENT_DAYS（日常增量）。
    首次回补传 BACKFILL_DAYS（31）。
    """
    t_start = time.time()
    if days_back is None:
        days_back = RECENT_DAYS
    result: dict = {"success": False, "tables": {}, "errors": [], "elapsed_seconds": 0}

    configs = load_hourly_configs()
    start_iso, end_iso = _window_iso(days_back)
    logger.info("[CN-HOURLY] 同步开始：模板=%s 窗口=%s → %s",
                list(configs), start_iso, end_iso)
    try:
        auth = base._login()
        errors: list[str] = []
        for key, cfg in configs.items():
            try:
                table_name, xlsx_bytes = _query_export_one(auth, cfg, start_iso, end_iso)
                rows = _upsert_table(table_name, xlsx_bytes)
                result["tables"][table_name] = {"rows": rows}
            except Exception as e:  # noqa: BLE001 — 单模板失败不拖垮其余模板
                msg = f"[{key}] {e}"
                errors.append(msg)
                logger.error("[CN-HOURLY] %s 失败: %s", key, e)
        result["errors"] = errors
        result["success"] = len(errors) == 0
    except Exception as e:
        result["errors"].append(str(e))
        logger.error("[CN-HOURLY] 任务失败: %s", e)

    result["elapsed_seconds"] = round(time.time() - t_start, 2)
    total = sum(v.get("rows", 0) for v in result["tables"].values())
    logger.info("[CN-HOURLY] 同步结束：共 %s 行，%.2fs，成功=%s",
                total, result["elapsed_seconds"], result["success"])
    return result


# ============================================================
# 页面读取侧（?page=cn_hourly_kpi → /api/cn-hourly-kpi/overview）
# ============================================================
# 结构与 cn_kpi_5mins_service 同构：widgets 每个一条 3 列 SQL
# [Hour, Series(NE 或 ALL), Value]，前端按第 2 列 pivot 成多条线。
# 列名守卫直接复用 cn_kpi_5mins_service 的实现（同一套「SQLite 把未知双引号
# 标识符当字符串字面量、不报错恒为 0」的防线，没必要复制一份）。
import re as _re
import threading as _threading
from typing import Any, Dict, List, Optional  # noqa: E402

from backend.services.cn_kpi_service import REMOTE_DB, query_remote  # noqa: E402
from backend.services.cn_kpi_5mins_service import _known_columns, _verify_columns  # noqa: E402

CACHE_TTL = 300          # 任务每天才写库，300s 缓存绰绰有余
MAX_RANGE_DAYS = 31      # 与回补窗口同档，防一次拉爆
_hourly_cache: Dict[tuple, tuple] = {}
_hourly_lock = _threading.Lock()


def _series_sql(table: str, value_expr: str, per_ne: bool,
                start: str, end: str) -> str:
    """生成 [Hour, Series, Value] 三列聚合 SQL。

    per_ne=True 时 Series=NE（每网元一条线）；False 时全 NE 合并（Series 固定 'ALL'），
    合并口径由 value_expr 决定（如 SUM(Used)*100/SUM(Authorized) 的加权占用率）。
    """
    series = '"NE"' if per_ne else "'ALL'"
    return (
        f'SELECT strftime(\'%Y-%m-%d %H:00\', "Begin Time") AS "Hour", {series} AS "Series", '
        f'{value_expr} AS "Value" FROM "{table}" '
        f'WHERE "Begin Time" >= \'{start}\' AND "Begin Time" < \'{end}\' '
        f'GROUP BY "Hour", "Series" ORDER BY "Hour"'
    )


def _widgets(start: str, end: str) -> List[Dict[str, Any]]:
    """7 个组件。列名以 2026-11-18 实测导出为准（probe5）；改模板必须同步改这里。"""
    S, E = start, end
    return [
        {
            "id": "xgw_session_used", "title": "xGW PFCP Sessions Used",
            "pct": False, "table": "PS_xGW_Session_Capacity_OSS_UME", "per_ne": True,
            "sql": _series_sql("PS_xGW_Session_Capacity_OSS_UME",
                               'ROUND(SUM("Number of PFCP Sessions Used"),0)', True, S, E),
        },
        {
            "id": "xgw_session_pct", "title": "xGW Session Occupancy(%)",
            "pct": True, "table": "PS_xGW_Session_Capacity_OSS_UME", "per_ne": False,
            # 全 NE 加权占用率：分子/分母都先 SUM 再相除（授权容量按 NE 小时数累积）
            "sql": _series_sql("PS_xGW_Session_Capacity_OSS_UME",
                               'ROUND(SUM("Number of PFCP Sessions Used")*100.0'
                               '/SUM("Number of PFCP Sessions Authorized"),2)', False, S, E),
        },
        {
            "id": "xgw_tp_used", "title": "xGW Throughput Used(Mbps)",
            "pct": False, "table": "PS_xGW_Throughput_Capacity_OSS_UME", "per_ne": True,
            "sql": _series_sql("PS_xGW_Throughput_Capacity_OSS_UME",
                               'ROUND(SUM("Number of Throughput(Mbps) Used"),1)', True, S, E),
        },
        {
            "id": "xgw_tp_pct", "title": "xGW Throughput Occupancy(%)",
            "pct": True, "table": "PS_xGW_Throughput_Capacity_OSS_UME", "per_ne": False,
            "sql": _series_sql("PS_xGW_Throughput_Capacity_OSS_UME",
                               'ROUND(SUM("Number of Throughput(Mbps) Used")*100.0'
                               '/SUM("Number of Throughput(Mbps) Authorized"),2)', False, S, E),
        },
        {
            "id": "mgw_tone", "title": "MGW/MRFP TONE Utilization(%)",
            "pct": True, "table": "CS_MRFP96_Resource_Utilization_OSS_UME", "per_ne": True,
            "sql": _series_sql("CS_MRFP96_Resource_Utilization_OSS_UME",
                               'ROUND(AVG("Utilization Ratio of TONE Resource(%)"),2)', True, S, E),
        },
        {
            "id": "mgw_tc", "title": "MGW/MRFP TC Utilization(%)",
            "pct": True, "table": "CS_MRFP96_Resource_Utilization_OSS_UME", "per_ne": True,
            "sql": _series_sql("CS_MRFP96_Resource_Utilization_OSS_UME",
                               'ROUND(AVG("Utilization Ratio of TC Resource(%)"),2)', True, S, E),
        },
        {
            "id": "mgw_rtp", "title": "MGW/MRFP RTP Utilization(%)",
            "pct": True, "table": "CS_MRFP96_Resource_Utilization_OSS_UME", "per_ne": True,
            "sql": _series_sql("CS_MRFP96_Resource_Utilization_OSS_UME",
                               'ROUND(AVG("Utilization Ratio of RTP Resource(%)"),2)', True, S, E),
        },
    ]


def _fetch_widget(w: Dict[str, Any]) -> Dict[str, Any]:
    """取单个组件；空表/无数据都算「空态」，不算失败（与 5mins 同约定）。"""
    out: Dict[str, Any] = {
        "id": w["id"], "title": w["title"], "chart": "line", "pivot": True,
        "pct": bool(w.get("pct")), "sql": w["sql"],
        "columns": ["Hour", "NE", w["title"]],
        "rows": [], "error": "", "empty": False, "empty_reason": "",
    }
    col_err = _verify_columns(w)
    if col_err:
        out["error"] = col_err
        logger.error("CN hourly 组件 %s 列名校验失败：%s", w["id"], col_err)
        return out
    try:
        res = query_remote(w["sql"], db=REMOTE_DB, limit=20000)
    except Exception as e:  # noqa: BLE001 — 表不存在也算空态
        msg = str(e)
        if "no such table" in msg.lower():
            out["empty"] = True
            out["empty_reason"] = "数据表尚未生成（同步任务未跑过）。"
        else:
            out["error"] = msg
        logger.warning("CN hourly 组件 %s 取数失败：%s", w["id"], msg)
        return out
    if not res.get("success", True):
        out["error"] = res.get("error") or "远端返回 success=false"
        return out
    out["columns"] = list(res.get("columns") or out["columns"])
    out["rows"] = res.get("rows") or []
    return out


def get_overview(start: str = None, end: str = None, force: bool = False) -> Dict[str, Any]:
    """整页数据。start/end 均为 YYYY-MM-DD（含端点）；默认最近 7 天（含今天已有小时）。"""
    t0 = time.time()
    from datetime import date as _date
    today = _date.today()
    try:
        s = _date.fromisoformat(start) if start else today - timedelta(days=6)
    except ValueError:
        s = today - timedelta(days=6)
    try:
        e = _date.fromisoformat(end) if end else today
    except ValueError:
        e = today
    if e < s:                       # 传反了就交换，而不是返回空
        s, e = e, s
    if (e - s).days + 1 > MAX_RANGE_DAYS:   # 上限钳制：起点后推
        s = e - timedelta(days=MAX_RANGE_DAYS - 1)
    end_excl = (e + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    start_str = s.strftime("%Y-%m-%d 00:00:00")

    key = (start_str, end_excl)
    now = time.time()
    if not force:
        with _hourly_lock:
            hit = _hourly_cache.get(key)
            if hit is not None and (now - hit[0]) < CACHE_TTL:
                cached = copy.deepcopy(hit[1])
                cached["meta"]["cached"] = True
                return cached

    widgets = [_fetch_widget(w) for w in _widgets(start_str, end_excl)]
    out = {
        "meta": {
            "db": REMOTE_DB, "start": s.strftime("%Y-%m-%d"), "end": e.strftime("%Y-%m-%d"),
            "count": sum(1 for w in widgets if not w["empty"] and not w["error"]),
            "failed": sum(1 for w in widgets if w["error"]),
            "empty": sum(1 for w in widgets if w["empty"]),
            "elapsed_ms": int((time.time() - t0) * 1000), "cached": False,
        },
        "widgets": widgets,
    }
    with _hourly_lock:
        _hourly_cache[key] = (time.time(), copy.deepcopy(out))
    return out


def health() -> Dict[str, Any]:
    """远端只读 API 连通性探测。"""
    t0 = time.time()
    try:
        res = query_remote("SELECT 1", db=REMOTE_DB, limit=1)
        return {"ok": bool(res.get("success", True)), "db": REMOTE_DB,
                "elapsed_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"ok": False, "db": REMOTE_DB,
                "elapsed_ms": int((time.time() - t0) * 1000), "error": str(e)}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CN 小时 KPI 同步（KPI Template.xlsx 模板）")
    parser.add_argument("--days", type=int, default=None,
                        help=f"回补天数（默认 {RECENT_DAYS}；首次回补用 --days {BACKFILL_DAYS}）")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
    res = run_cn_hourly_kpi_sync(days_back=args.days)
    print(f"\nCN Hourly KPI 结果: {'成功' if res['success'] else '失败'}")
    for t, info in res["tables"].items():
        print(f"  {t}: {info['rows']} 行")
    if res["errors"]:
        print(f"错误: {res['errors']}")
    print(f"耗时: {res['elapsed_seconds']}s")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vmax_report_client.py —— VMAX vReport（RDK "pluto" 报表引擎）取数客户端
=====================================================================

背景 / 协议来源（2026-09-16 从 VMAX 前端 RDK 资源复刻，非猜测）：

1) 请求加密（RDK DataSourceService 的通用拦截器）
   前端 `rdk/services/DataSourceService.js` 对命中 encryptUrlPatterns 的 URL 做：

        config.headers["X-Content-Type"] = "application/x-vmax-s-rsa-encrypted"
        config.data.param = {encryptedStr: encryptData(JSON.stringify(param))}

   `encryptData` 在 `rdk/jsencrypt-min/jsencrypt_ex.js` / `base/template/RSAEncrypt/jsencrypt_ex.js`
   里 = JSEncrypt.encryptLong：**RSA PKCS#1 v1.5 分块（每块 117 字节原文明文）+ 静态公钥**，
   每块密文 128B → 左补零到 256 个十六进制字符 → 拼起来按 4bit/字符转 base64。
   静态公钥与 mars 历史查询 (`/query/v2/history`) 用的是同一把（见
   backend/services/vmax_cxo_daily_cache.py 的 _MARS_PUB_B64 注释），已与线上一致。

   注意 `X-Content-Type` 这个头是必须的：缺了它 RDK 服务端不会解密，脚本拿到的是
   `{"encryptedStr": "..."}` 外壳，于是读 `param.condition.times` 报
   "Cannot read property \"times\" from undefined"（实测复现）。本机 8790 VMAX 代理
   原本丢弃调用方自定义头，已同步改为透传 X-*（Scripts/realtime_proxy_vmax.py）。

2) 查询体（前端 `template/module/report.js` 的 conditionTableProcessor()）

        {
          "reportPart": "<报表名，即 URL 里的 rpt_home/<reportPart>>",
          "condition": {
            "topN": "<条数>",
            "times": {"beginTime": "...", "endTime": "...",
                      "granularity": "3|4|5|6|7|8", "multi_period": "", "bh": "0"},
            "filterList": {"filters": [...], "filter_type": 0}
          },
          "paging": {"currentPage": 1, "pageSize": <条数>, "totalRecord": 0},
          "isDrill": 0, "show": [<维度 id + 指标 id>], "area": [],
          "session": "JSESSIONID=<vreport 会话>"
        }

   granularity 枚举（前端字面量）：quarter=3, hour=4, date=5, month=6, week=7, 5min=8。
   `session` 取自 GET /rdk/service/app/vreport/server/session（返回裸 session id）。

3) 报表静态配置（用来知道有哪些维度/指标、默认选中哪些）

        GET /rdk/app/vreport/web/rpt_home/<reportPart>/web/init_data.json   # 过滤项/维度初值
        GET /rdk/app/vreport/web/rpt_home/<reportPart>/design.json          # fields.dim / fields.kpi
        GET /rdk/service/app/vreport/web/rpt_home/<reportPart>/server/metadata.js  # 报表数据表 & 列

4) 导出（server/export_data）：在查询体上追加
   maxExportRecord / exportType(csv|excel) / exportAll / optObj / reportPart /
   drillOperateObj / logFlag / unitExport，返回 {"uuid":..,"path":..,"name":..}；
   随后 `GET /vReport/export/getFile?param=encryptData({"file":name,"method":"1"})` 下载。

传输方式：
    · proxy （默认）：走本机 8790 实时代理（与 CXO 看板共用同一个 VMAX 会话，
      避免 vReport / 门户的并发会话上限被撑爆）。
    · direct：自带门户登录（loginAuthenticate → RSA 密码 → /web/res/web-common/login），
      适合部署在能直连 VMAX 的机器上。
    · auto （默认）：代理健康就用代理，否则退回直连。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import ssl
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

logger = logging.getLogger("vmax_multi_data.client")

# ---------- 地址 / 传输 ----------
VMAX_HOST = os.environ.get("VMAX_HOST_URL", "https://10.123.255.12:26180").rstrip("/")
PROXY_BASE = os.environ.get("VMAX_PROXY_BASE", "http://127.0.0.1:8790/proxy?url=")
VREPORT_WEB = "/rdk/app/vreport/web"
VREPORT_SERVICE = "/rdk/service/app/vreport"
REPORT_QUERY_TPL = VREPORT_SERVICE + "/web/rpt_home/%s/server/report_query"
EXPORT_DATA_TPL = VREPORT_SERVICE + "/web/rpt_home/%s/server/export_data"
METADATA_TPL = VREPORT_SERVICE + "/web/rpt_home/%s/server/metadata"
SESSION_PATH = VREPORT_SERVICE + "/server/session"
CONFIG_JSON_TPL = VREPORT_WEB + "/rpt_home/%s/%s"
EXPORT_FILE_PATH = "/vReport/export/getFile"

# RDK RSA 标记头：服务端据此解密 param.encryptedStr
RSA_HEADER = {"X-Content-Type": "application/x-vmax-s-rsa-encrypted"}

# 静态 RSA 公钥（vReport / mars 通用，见模块注释）
STATIC_PUBLIC_KEY_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC/h5K+Yr5VRtCyeg3g85xbi91K4hc"
    "XehTtkPOZaC19SGyrNGzq8WmvGLbbvcU7NcpJ0I/cdg0sAcbcPlt/Q/RofmYgpD0gCK"
    "z2ZIpgcAszndY0DjKhOGbNPnoIRO9ln3giPqCIfdzF8MUCgIGVLWK1ha7STUwdAFZkb"
    "z45X4KVkwIDAQAB"
)

# 前端粒度字面量 -> 服务端编码
GRANULARITY_CODE = {"quarter": "3", "hour": "4", "date": "5",
                    "month": "6", "week": "7", "5min": "8"}
GRANULARITY_ALIAS = {"1hour": "hour", "1day": "date", "24hour": "date", "day": "date",
                     "h": "hour", "d": "date"}

DEFAULT_TIMEOUT = (10, 300)          # (连接, 读取)：报表查询可能跑几十秒
_SSL_VERIFY = False                  # VMAX 用自签证书，与 realtime_proxy_vmax.py 一致

# 上游实测（2026-09-16，sys_5gsa_traffic_ciservice，经 8790 代理）：
#   · date 粒度的滚动保留期 = 90 天：请求 120/180/365 天，返回的最早日期都停在
#     2026-06-18（正好 90 天前）—— 页面上的「最多 90 天」就是这个保留期。
#   · hour 粒度保留 ≥30 天（30 天请求返回 719 个小时点、1714 行、耗时 88s），
#     90 天小时粒度会跑到代理 120s 超时 —— 所以大范围必须切片并发/串行分片拉。
#   · 单次请求的行数上限 = topN/pageSize（topN=200 时 90 天只回 200 行且日期被截断，
#     topN=5000 时 90 天回满 656 行）—— 默认值必须给大，并用 truncated 标记兜底。
GRANULARITY_STEP = {"5min": timedelta(minutes=5), "hour": timedelta(hours=1),
                    "date": timedelta(days=1), "week": timedelta(days=7),
                    "month": timedelta(days=30), "quarter": timedelta(days=90)}
# 单个分片的时间跨度（天）：既避免单请求太慢/超时，也让每片行数远离 TopN 上限
DEFAULT_CHUNK_DAYS = {"5min": 1, "hour": 7, "date": 30, "week": 60,
                      "month": 180, "quarter": 365}


class VmaxReportError(RuntimeError):
    """vReport 调用失败（上游返回错误 / 报文无法解析）。"""


class VmaxUnavailable(VmaxReportError):
    """网络或会话不可用（代理未就绪、直连超时、门户登录失败）。"""


# ==========================================================================
# 1) RSA encryptLong（与前端 jsencrypt_ex.encryptData 等价）
# ==========================================================================
def _utf8_len(ch: str) -> int:
    cp = ord(ch)
    if cp < 0x80:
        return 1
    if cp < 0x800:
        return 2
    if cp < 0x10000:
        return 3
    return 4


def split_js_chunks(text: str) -> List[str]:
    """复刻 jsencrypt_ex.encryptLong 的分块（逐字符扫描 UTF-8 字节数）：

        byteNo += utf8len(ch)
        if byteNo % 117 >= 114 or byteNo % 117 == 0:
            if byteNo - lastCut >= 114: 落刀（记下当前字符下标）

    所以**第一段是 114 字节**（byteNo 一到 114 就落刀），其后每段 117 字节，
    末段是余数。按字符（而非字节）落刀是为了不把多字节字符劈成两半 —— 劈开会
    破坏服务端拼接后的 UTF-8，进而让 JSON 解析失败。
    """
    cuts = [0]                                    # 前端 bytes.push(0) 的哨兵，不代表刀口
    byte_no = 0
    last_cut = 0
    for i, ch in enumerate(text):
        byte_no += _utf8_len(ch)
        if (byte_no % 117) >= 114 or (byte_no % 117) == 0:
            if byte_no - last_cut >= 114:
                cuts.append(i)
                last_cut = byte_no
    if len(cuts) <= 1:
        return [text]

    chunks: List[str] = []
    for s in range(len(cuts) - 1):
        start = 0 if s == 0 else cuts[s] + 1
        chunks.append(text[start:cuts[s + 1] + 1])
    if cuts[-1] != len(text) - 1:
        chunks.append(text[cuts[-1] + 1:])
    return chunks


def encrypt_long(text: str, public_key_b64: str = STATIC_PUBLIC_KEY_B64) -> str:
    """RSA PKCS#1 v1.5 分块加密后转 base64（等价前端 encryptData）。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    pem = ("-----BEGIN PUBLIC KEY-----\n" + public_key_b64 + "\n-----END PUBLIC KEY-----")
    key = serialization.load_pem_public_key(pem.encode("utf-8"))
    hex_all = ""
    for chunk in split_js_chunks(text):
        cipher = key.encrypt(chunk.encode("utf-8"), padding.PKCS1v15())
        hex_all += cipher.hex().rjust(256, "0")
    return base64.b64encode(bytes.fromhex(hex_all)).decode("utf-8")


def encrypt_param(condition: Dict[str, Any]) -> Dict[str, str]:
    """把条件对象打成 RDK 的 {"encryptedStr": ...} 信封。"""
    plain = json.dumps(condition, ensure_ascii=False, separators=(",", ":"))
    return {"encryptedStr": encrypt_long(plain)}


# ==========================================================================
# 2) 条件构造
# ==========================================================================
def normalize_granularity(value: str) -> str:
    g = (value or "hour").strip().lower()
    return GRANULARITY_ALIAS.get(g, g)


def build_report_condition(report_part: str,
                           begin: Any,
                           end: Any,
                           granularity: str = "hour",
                           show: Optional[Sequence[str]] = None,
                           top_n: int = 500,
                           page: int = 1,
                           page_size: Optional[int] = None,
                           filters: Optional[Iterable[dict]] = None,
                           session: str = "",
                           multi_period: str = "",
                           busy_hour: bool = False,
                           extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """构造 report_query / export_data 的明文条件（见模块头注释第 2 点）。

    begin/end 支持 datetime 或 "YYYY-MM-DD[ HH:MM:SS]" 字符串；date 粒度补 00:00:00 /
    23:59:59，其它粒度补整点，避免报表按区间裁剪时丢首尾。
    """
    g = normalize_granularity(granularity)
    if g not in GRANULARITY_CODE:
        raise VmaxReportError("不支持的粒度: %r（可选 %s）" % (granularity, ",".join(GRANULARITY_CODE)))
    b = _fmt_time(begin, end_of=False, granularity=g)
    e = _fmt_time(end, end_of=True, granularity=g)
    size = int(page_size or top_n or 500)
    cond: Dict[str, Any] = {
        "reportPart": report_part,
        "condition": {
            "topN": str(top_n),
            "times": {"beginTime": b, "endTime": e,
                      "granularity": GRANULARITY_CODE[g],
                      "multi_period": multi_period or "",
                      "bh": "1" if busy_hour else "0"},
            "filterList": {"filters": list(filters or []), "filter_type": 0},
        },
        "paging": {"currentPage": int(page), "pageSize": size, "totalRecord": 0},
        "isDrill": 0,
        "show": list(show or []),
        "area": [],
        "session": session or "",
    }
    if extra:
        cond.update(extra)
    return cond


def _fmt_time(value: Any, end_of: bool = False, granularity: str = "hour") -> str:
    if isinstance(value, datetime):
        dt = value
        day_only = False
    else:
        text = str(value).strip().replace("T", " ")
        day_only = len(text) <= 10
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            dt = datetime.strptime(text[:16], "%Y-%m-%d %H:%M")
    dt = dt.replace(microsecond=0)
    if day_only:
        return dt.replace(hour=23 if end_of else 0, minute=59 if end_of else 0,
                          second=59 if end_of else 0).strftime("%Y-%m-%d %H:%M:%S")
    if granularity == "hour":
        dt = dt.replace(minute=59 if end_of else 0, second=0)
    elif granularity == "date":
        dt = dt.replace(hour=23 if end_of else 0, minute=59 if end_of else 0,
                        second=59 if end_of else 0)
    elif granularity == "5min":
        dt = dt.replace(minute=(dt.minute // 5) * 5, second=0)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def time_window(days_back: int = 1, granularity: str = "hour",
                now: Optional[datetime] = None) -> tuple:
    """最近 N 天窗口（默认含当天，按粒度对齐）。date 粒度最多能回看 90 天（上游保留期）。"""
    now = now or datetime.now()
    g = normalize_granularity(granularity)
    if g in ("date", "week", "month"):
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        begin = end - timedelta(days=max(0, int(days_back) - 1))
    elif g == "5min":
        end = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 5)
        begin = end - timedelta(days=int(days_back))
    else:
        end = now.replace(minute=0, second=0, microsecond=0)
        begin = end - timedelta(hours=24 * int(days_back) - 1)
    return begin, end


def plan_time_slices(begin: Any, end: Any, granularity: str,
                     chunk_days: Any = None) -> List[tuple]:
    """把 [begin, end] 切成互不重叠的分片（每片 span 天，按粒度对齐、不留缝）。

    为什么要切：单次大范围查询（如 90 天小时粒度）会跑到代理/网关超时，
    且 TopN 会把结果截断成「按流量排序的前 N 行」，日期跨度看着就不对。
    分片后每片都很快，行数也远离上限。

    chunk_days 可为 int 或 {粒度: 天数} 字典（缺省用 DEFAULT_CHUNK_DAYS）。
    """
    g = normalize_granularity(granularity)
    step = GRANULARITY_STEP[g]
    if isinstance(chunk_days, dict):
        span_days = chunk_days.get(g, DEFAULT_CHUNK_DAYS[g])
    else:
        span_days = chunk_days or DEFAULT_CHUNK_DAYS[g]
    span = timedelta(days=max(1, int(span_days)))
    b = begin if isinstance(begin, datetime) else _parse_time(begin)
    e = end if isinstance(end, datetime) else _parse_time(end)
    if e < b:
        b, e = e, b
    slices: List[tuple] = []
    cur = b
    while cur <= e:
        stop = min(cur + span - step, e)
        slices.append((cur, stop))
        cur = stop + step
    return slices


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("T", " ")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.strptime(text[:16], "%Y-%m-%d %H:%M")


# ==========================================================================
# 3) 客户端
# ==========================================================================
class VmaxReportClient:
    """vReport 取数客户端。transport: proxy | direct | auto。"""

    def __init__(self,
                 host: str = VMAX_HOST,
                 proxy_base: str = PROXY_BASE,
                 transport: Optional[str] = None,
                 timeout: tuple = DEFAULT_TIMEOUT,
                 credential_key: str = "vmax_cxo",
                 cache_dir: Optional[Path] = None,
                 config_ttl: int = 24 * 3600):
        self.host = host.rstrip("/")
        self.proxy_base = proxy_base
        self.transport = (transport or os.environ.get("VMAX_TRANSPORT") or "auto").lower()
        self.timeout = timeout
        self.credential_key = credential_key
        self.cache_dir = Path(cache_dir) if cache_dir else (
            Path(__file__).resolve().parent.parent.parent.parent / "data" / "vmax_multi_data" / "_cache")
        self.config_ttl = config_ttl
        self.session = requests.Session()
        self.session.trust_env = False          # 忽略系统代理，直连本机 8790 / VMAX
        self.session.verify = _SSL_VERIFY
        self._vreport_session: Optional[str] = None
        self._logged_in = False

    # ---------- 传输 ----------
    def healthy(self) -> Dict[str, Any]:
        """返回 {"transport": ..., "ready": bool, "detail": ...}。"""
        mode = self._resolve_transport()
        if mode == "proxy":
            try:
                r = self.session.get(self.proxy_base.split("/proxy?")[0] + "/health", timeout=5)
                j = r.json()
                ready = bool(j.get("status") == "ok" and j.get("proxy") == "ready")
                return {"transport": "proxy", "ready": ready, "detail": j}
            except Exception as exc:                                     # noqa: BLE001
                return {"transport": "proxy", "ready": False,
                        "detail": "%s: %s" % (type(exc).__name__, exc)}
        try:
            r = self.session.get(self.host + SESSION_PATH, timeout=self.timeout)
            return {"transport": "direct", "ready": r.status_code == 200, "detail": r.text[:120]}
        except Exception as exc:                                         # noqa: BLE001
            return {"transport": "direct", "ready": False,
                    "detail": "%s: %s" % (type(exc).__name__, exc)}

    def _resolve_transport(self) -> str:
        if self.transport in ("proxy", "direct"):
            return self.transport
        # auto：代理健康优先（复用看板会话，避免撑爆门户并发会话数）
        health_url = self.proxy_base.split("/proxy?")[0] + "/health"
        try:
            r = self.session.get(health_url, timeout=5)
            if r.json().get("proxy") == "ready":
                return "proxy"
        except Exception:                                                # noqa: BLE001
            pass
        return "direct"

    def _request(self, method: str, path: str, body: Optional[dict] = None,
                 headers: Optional[dict] = None, timeout: Optional[tuple] = None) -> requests.Response:
        target = self.host + path
        hdrs = dict(headers or {})
        mode = self._resolve_transport()
        data = json.dumps(body).encode("utf-8") if body is not None else None
        if mode == "proxy":
            if body is not None:
                hdrs["Content-Type"] = "application/json"
            url = self.proxy_base + urllib.parse.quote(target, safe="")
        else:
            url = target
        try:
            resp = self.session.request(method, url, data=data, headers=hdrs or None,
                                        timeout=timeout or self.timeout)
        except Exception as exc:                                         # noqa: BLE001
            raise VmaxUnavailable("[%s] %s %s 失败: %s: %s"
                                  % (mode, method, path, type(exc).__name__, exc)) from exc
        if mode == "proxy" and resp.status_code in (502, 504):
            raise VmaxUnavailable("8790 VMAX 代理转发失败(%s): %s"
                                  % (resp.status_code, resp.text[:200]))
        return resp

    # ---------- 直连模式的门户登录 ----------
    def login(self) -> None:
        """门户登录（仅 direct 模式需要；proxy 模式由代理持有会话）。"""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from backend.services import credential_store

        user, password = credential_store.get_credential(
            self.credential_key, "ZeeshanM", "Zte@1a2b3c",
            "VMAX_CXO_USER", "VMAX_CXO_PASS")
        ua = {"User-Agent": "Mozilla/5.0", "Accept": "*/*",
              "Referer": self.host + "/rdk/app/portal/web/"}
        r = self.session.get(self.host + "/rdk/service/app/portal/server/loginAuthenticate",
                             headers=ua, timeout=self.timeout)
        cfg = r.json()
        pem = ("-----BEGIN PUBLIC KEY-----\n" + cfg["publicKey"] + "\n-----END PUBLIC KEY-----")
        pub = serialization.load_pem_public_key(pem.encode("utf-8"))
        enc = base64.b64encode(pub.encrypt(password.encode("utf-8"), padding.PKCS1v15())).decode()
        resp = self.session.post(self.host + "/web/res/web-common/login",
                                 data={"username": user, "password": enc, "isEncypted": "true"},
                                 headers={**ua, "Content-Type": "application/x-www-form-urlencoded"},
                                 timeout=self.timeout)
        try:
            payload = resp.json()
        except Exception:                                                # noqa: BLE001
            payload = {}
        if payload.get("result") != 1:
            raise VmaxUnavailable("VMAX 门户登录失败: %s" % (resp.text[:200] or payload))
        self._logged_in = True
        self._vreport_session = None
        logger.info("[vmax_multi_data] 门户登录成功: %s", user)

    def _ensure_session(self) -> None:
        if self._resolve_transport() == "direct" and not self._logged_in:
            self.login()

    # ---------- vReport 会话 ----------
    def vreport_session(self, refresh: bool = False) -> str:
        if self._vreport_session and not refresh:
            return self._vreport_session
        self._ensure_session()
        resp = self._request("GET", SESSION_PATH)
        if resp.status_code != 200 or not resp.text.strip():
            raise VmaxUnavailable("获取 vreport 会话失败: HTTP %s %s"
                                  % (resp.status_code, resp.text[:120]))
        self._vreport_session = resp.text.strip().strip('"')
        return self._vreport_session

    # ---------- 静态配置 ----------
    def static_text(self, path: str) -> str:
        resp = self._request("GET", path)
        if resp.status_code != 200:
            raise VmaxReportError("GET %s -> HTTP %s" % (path, resp.status_code))
        return resp.text

    def server_script(self, report_part: str, name: str) -> Any:
        """调用 server/<name>（metadata 等），返回解析后的 JSON。"""
        text = self.static_text(METADATA_TPL % report_part if name == "metadata"
                                else (REPORT_QUERY_TPL % report_part).rsplit("/", 1)[0] + "/" + name)
        return _loads_tolerant(text)

    def report_config(self, report_part: str, use_cache: bool = True) -> Dict[str, Any]:
        """报表静态配置：init_data / design / metadata（默认本地缓存 1 天）。"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        out: Dict[str, Any] = {}
        for key, rel in (("init_data", "web/init_data.json"),
                         ("design", "design.json"),
                         ("metadata", None)):
            cached = self.cache_dir / ("%s_%s.json" % (report_part, key))
            fresh = (cached.exists() and
                     (time.time() - cached.stat().st_mtime) < self.config_ttl)
            if use_cache and fresh:
                try:
                    out[key] = json.loads(cached.read_text(encoding="utf-8"))
                    continue
                except Exception:                                        # noqa: BLE001
                    pass
            try:
                if key == "metadata":
                    payload = self.server_script(report_part, "metadata")
                else:
                    payload = _loads_tolerant(self.static_text(CONFIG_JSON_TPL % (report_part, rel)))
            except Exception as exc:                                     # noqa: BLE001
                logger.warning("[vmax_multi_data] %s 配置 %s 拉取失败: %s", report_part, key, exc)
                if cached.exists():
                    payload = json.loads(cached.read_text(encoding="utf-8"))
                else:
                    raise
            out[key] = payload
            cached.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return out

    def default_show(self, report_part: str, dims: Optional[Sequence[str]] = None,
                     kpis: Optional[Sequence[str]] = None) -> List[str]:
        """`show` = 维度 + 指标。

        配置里显式给了 dims/kpis 就只覆盖对应那一半（例如只指定 kpis 时仍带上
        design.json 的默认维度，否则返回的行没有时间/城市列，无法使用）；
        两半都没给就全用 design.json 里 defaultSelected=1 的项。
        """
        design = self.report_config(report_part).get("design") or {}
        fields = design.get("fields") or {}
        default_dims = [f.get("id") for f in (fields.get("dim") or [])
                        if str(f.get("defaultSelected", "0")) == "1" and f.get("id")]
        if "clttime" not in default_dims:
            default_dims.insert(0, "clttime")
        use_dims = list(dims) if dims else default_dims
        if "clttime" not in use_dims:
            use_dims = ["clttime"] + use_dims
        use_kpis = list(kpis) if kpis else [
            f.get("id") for f in (fields.get("kpi") or [])
            if str(f.get("defaultSelected", "0")) == "1" and f.get("id")]
        return use_dims + use_kpis

    # ---------- 查询 / 导出 ----------
    def query_report(self, report_part: str, condition: Dict[str, Any],
                     retry_on_session: bool = True) -> Dict[str, Any]:
        """POST server/report_query，返回解析后的表格结构。"""
        self._ensure_session()
        cond = dict(condition)
        cond.setdefault("session", "JSESSIONID=" + self.vreport_session())
        body = {"param": encrypt_param(cond)}
        resp = self._request("POST", REPORT_QUERY_TPL % report_part, body=body, headers=RSA_HEADER)
        payload = _loads_tolerant(resp.text)
        if resp.status_code != 200:
            raise VmaxReportError("report_query HTTP %s: %s" % (resp.status_code, resp.text[:200]))
        parsed = parse_report_payload(payload)
        if parsed.get("session_expired") and retry_on_session:
            logger.info("[vmax_multi_data] 会话失效，刷新 vreport session 后重试")
            self.vreport_session(refresh=True)
            return self.query_report(report_part, condition, retry_on_session=False)
        return parsed

    def query_kpis(self, report_part: str, begin: Any = None, end: Any = None,
                   granularity: str = "hour", dims: Optional[Sequence[str]] = None,
                   kpis: Optional[Sequence[str]] = None, top_n: int = 500,
                   page: int = 1, page_size: Optional[int] = None,
                   filters: Optional[Iterable[dict]] = None,
                   **kwargs) -> Dict[str, Any]:
        """便捷方法：查一段时间的指标（默认按 design.json 的默认维度/指标）。

        未给 begin/end 时按 `days_back`（默认 1 天）自动取窗口；返回结构里补上
        实际使用的 window/condition，便于落盘与排查。
        """
        g = normalize_granularity(granularity)
        if begin is None or end is None:
            begin, end = time_window(int(kwargs.pop("days_back", 1)), g)
        condition = build_report_condition(
            report_part, begin, end, granularity=g,
            show=self.default_show(report_part, dims, kpis),
            top_n=top_n, page=page, page_size=page_size, filters=filters, **kwargs)
        result = self.query_report(report_part, condition)
        times = condition["condition"]["times"]
        result["window"] = {"begin": times["beginTime"], "end": times["endTime"]}
        result["granularity"] = g
        result["condition"] = condition
        return result

    def query_kpis_range(self, report_part: str, begin: Any = None, end: Any = None,
                         granularity: str = "hour", dims: Optional[Sequence[str]] = None,
                         kpis: Optional[Sequence[str]] = None, top_n: int = 20000,
                         chunk_days: Any = None, days_back: Optional[int] = None,
                         filters: Optional[Iterable[dict]] = None,
                         progress: bool = False, **kwargs) -> Dict[str, Any]:
        """按分片拉一整个时间窗（默认 TopN 给大，避免被截断）。

        实测：90 天 date 粒度一次请求要 21s 且容易被 TopN 截断；切成 3 片（每片 30 天）
        每片几秒、行数远离上限。hour 粒度 90 天单请求会超时，默认切 7 天一片。
        返回里带 slices/slice_windows/truncated，便于判断有没有漏数据。
        """
        g = normalize_granularity(granularity)
        if begin is None or end is None:
            begin, end = time_window(int(days_back or 1), g)
        windows = plan_time_slices(begin, end, g, chunk_days)
        merged: Dict[str, Dict[str, Any]] = {}
        fields: List[str] = []
        raw_fields: List[str] = []
        headers: List[str] = []
        columns: List[Any] = []
        truncated = False
        failures: List[str] = []
        for idx, (b, e) in enumerate(windows, 1):
            try:
                res = self.query_kpis(report_part, b, e, granularity=g, dims=dims, kpis=kpis,
                                      top_n=top_n, page_size=top_n, filters=filters, **kwargs)
            except Exception as exc:                                     # noqa: BLE001
                failures.append("%s~%s: %s" % (b, e, exc))
                logger.warning("[vmax_multi_data] 分片 %s~%s 失败: %s", b, e, exc)
                continue
            if not fields:
                fields = res.get("fields") or []
                raw_fields = res.get("raw_fields") or []
                headers = res.get("headers") or []
                columns = res.get("columns") or []
            recs = res.get("records") or []
            if len(recs) >= int(top_n):
                truncated = True
            for rec in recs:
                merged.setdefault(json.dumps(rec, ensure_ascii=False, sort_keys=True), rec)
            if progress:
                print("[vmax_multi_data] 分片 %d/%d %s ~ %s -> %d 行（累计 %d）"
                      % (idx, len(windows), b, e, len(recs), len(merged)), flush=True)
        records = list(merged.values())
        records.sort(key=lambda r: str(r.get("clttime", "")))
        return {"report_part": report_part, "granularity": g,
                "window": {"begin": _fmt_time(windows[0][0], granularity=g),
                           "end": _fmt_time(windows[-1][1], end_of=True, granularity=g)},
                "fields": fields, "raw_fields": raw_fields, "headers": headers,
                "columns": columns, "records": records, "total": len(records),
                "slices": len(windows), "slice_windows": [[str(a), str(b)] for a, b in windows],
                "truncated": truncated, "errors": failures[:5]}

    def export_report(self, report_part: str, condition: Dict[str, Any],
                      export_type: str = "excel", export_all: int = 1,
                      opt_obj: str = "", max_export_record: Optional[int] = None,
                      unit_export: Optional[list] = None) -> Dict[str, Any]:
        """POST server/export_data，返回 {uuid, path, name}（真正的下载走 download_export）。"""
        self._ensure_session()
        cond = dict(condition)
        cond.setdefault("session", "JSESSIONID=" + self.vreport_session())
        cond.update({"maxExportRecord": max_export_record or 0,
                     "exportType": "csv" if export_type == "csv" else "excel",
                     "exportAll": export_all,
                     "optObj": opt_obj or "",
                     "drillOperateObj": [],
                     "logFlag": True,
                     "unitExport": unit_export or []})
        body = {"param": encrypt_param(cond)}
        resp = self._request("POST", EXPORT_DATA_TPL % report_part, body=body, headers=RSA_HEADER)
        payload = _loads_tolerant(resp.text)
        if isinstance(payload, dict) and isinstance(payload.get("result"), str):
            payload = _loads_tolerant(payload["result"])
        return payload if isinstance(payload, dict) else {}

    def download_export(self, name: str, method: str = "1") -> bytes:
        """下载 export_data 生成的文件（先 checkFile 再 getFile，前端同款流程）。"""
        param = urllib.parse.quote(encrypt_long(json.dumps({"file": name, "method": method},
                                                           separators=(",", ":"))), safe="")
        self._request("GET", "/vReport/export/checkFile?param=" + param)
        resp = self._request("GET", EXPORT_FILE_PATH + "?param=" + param)
        if resp.status_code != 200:
            raise VmaxReportError("导出文件下载失败 HTTP %s" % resp.status_code)
        return resp.content


# ==========================================================================
# 4) 响应解析
# ==========================================================================
def _loads_tolerant(text: str) -> Any:
    if text is None:
        return {}
    if isinstance(text, (dict, list)):
        return text
    raw = text.strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:                                                    # noqa: BLE001
        # RDK 有时把 JSON 再包一层字符串（{"result": "{\"status\":...}"}）
        try:
            outer = json.loads(raw.replace('\\"', '"'))
            return outer
        except Exception:                                                # noqa: BLE001
            return {"_raw": raw}


def parse_report_payload(payload: Any, strip_hash: bool = True) -> Dict[str, Any]:
    """把 report_query 的响应归一化为
    {"status","err_msg","fields","raw_fields","headers","columns","rows","records"}。

    兼容三种形态：{"result": "<json 字符串>"} / {"result": {...}} / 直接 {"status","field","data"}。

    实测：VN 侧返回的指标列名带 `#` 前缀（请求里不带），如请求 `ppc400401001` 回来的
    field 是 `#ppc400401001`。默认去掉这个前缀让字段名可直接用于表列/看板，
    原始列名保留在 raw_fields 里。
    """
    data = payload
    if isinstance(data, dict) and "result" in data and isinstance(data["result"], (str, dict, list)):
        data = _loads_tolerant(data["result"]) if isinstance(data["result"], str) else data["result"]
    if isinstance(data, list):
        return {"status": 0, "err_msg": "", "fields": [], "raw_fields": [], "headers": [],
                "columns": [], "rows": data, "records": [], "total": len(data), "raw": payload}
    if not isinstance(data, dict):
        return {"status": -1, "err_msg": "无法解析的响应: %r" % (payload,), "fields": [],
                "raw_fields": [], "headers": [], "columns": [], "rows": [], "records": [],
                "total": 0, "raw": payload}

    status = data.get("status", 0)
    err = data.get("errMsg") or data.get("errmsg") or data.get("message") or ""
    session_expired = any(k in str(err).lower() for k in
                          ("session", "not login", "not logged", "登录"))
    table = _extract_table(data)
    raw_fields = [str(x) for x in (table.get("field") or table.get("fields") or [])]
    headers = list(table.get("header") or table.get("headers") or [])
    fields = [f[1:] if (strip_hash and f.startswith("#")) else f for f in raw_fields]
    rows = table.get("data") or table.get("rows") or []
    if rows and not isinstance(rows[0], (list, tuple)) and isinstance(rows[0], dict):
        records = [dict(r) for r in rows]
        fields = fields or list(records[0].keys())
        raw_fields = raw_fields or fields
    else:
        records = [dict(zip(fields, r)) for r in rows]
    columns = [{"id": fields[i] if i < len(fields) else str(i),
                "label": headers[i] if i < len(headers) else ""} for i in range(len(fields))]
    return {"status": _as_int(status), "err_msg": str(err), "fields": fields,
            "raw_fields": raw_fields, "headers": headers, "columns": columns,
            "rows": rows, "records": records,
            "total": _as_int(table.get("total") or table.get("totalRecord") or len(records)),
            "session_expired": session_expired, "raw": payload}


def _extract_table(data: dict) -> dict:
    """在响应里找带 field/data 的那一层（不同报表层级不一）。"""
    if isinstance(data.get("data"), list) and (data.get("field") or data.get("fields")):
        return data
    for key in ("table", "result", "queryResult", "page", "dataSource"):
        node = data.get(key)
        if isinstance(node, dict) and isinstance(node.get("data"), list):
            return node
    return data


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ==========================================================================
# 5) 模块级默认客户端
# ==========================================================================
_default_client: Optional[VmaxReportClient] = None


def get_client(**kwargs) -> VmaxReportClient:
    global _default_client
    if _default_client is None or kwargs:
        _default_client = VmaxReportClient(**kwargs)
    return _default_client


def fetch_report_kpis(report_part: str, begin: Any = None, end: Any = None,
                      granularity: str = "hour", dims: Optional[Sequence[str]] = None,
                      kpis: Optional[Sequence[str]] = None, **kwargs) -> Dict[str, Any]:
    """一行式取数（分片拉全窗口，返回 {"report_part","window","records","truncated",...}）。"""
    client = kwargs.pop("client", None) or get_client()
    result = client.query_kpis_range(report_part, begin, end, granularity=granularity,
                                     dims=dims, kpis=kpis, **kwargs)
    if not result.get("fields") and result.get("errors"):
        raise VmaxReportError("report_query 返回错误: %s" % result["errors"][0])
    window = result.get("window") or {}
    return {"report_part": report_part,
            "window": [window.get("begin", ""), window.get("end", "")],
            "granularity": result.get("granularity") or normalize_granularity(granularity),
            "fields": result.get("fields") or [],
            "raw_fields": result.get("raw_fields") or [],
            "headers": result.get("headers") or [],
            "columns": result.get("columns") or [],
            "records": result.get("records") or [],
            "total": result.get("total") or 0,
            "slices": result.get("slices") or 1,
            "truncated": bool(result.get("truncated")),
            "errors": result.get("errors") or []}

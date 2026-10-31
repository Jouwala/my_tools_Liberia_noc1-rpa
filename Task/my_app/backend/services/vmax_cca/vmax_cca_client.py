#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vmax_cca_client.py —— VMAX CCA 投诉「用户信息查询」客户端
==========================================================

协议来源（2026-10-24 从 CCA 投诉页前端复刻并实测，完整记录见同目录 README.md）：

1) 加密信封与 vReport / mars 同源：查询参数 JSON 化后用静态公钥 JSEncrypt encryptLong
   加密（直接复用 vmax_report_client.encrypt_long），base64 + URL 编码后拼
   `?encryptedStr=<密文>`，并带 `X-Content-Type: application/x-vmax-s-rsa-encrypted` 头。
   实测经 8790 代理（不透传该头）也能解密，但浏览器总是带，保持一致。

2) 两个接口（GET）：
   · /vmax/cca/view/userinfo/query_imsimdn  params={"msisdn": 号码（231 开头完整格式）}
     -> {"status": 0|3, "msg": ..., "data": [{用户信息}, {"imsi_arr": [...]}]}
     status=3（msg="IMSI is not found"）= 查无此号；
   · /vmax/cca/view/userinfo/query_terminal
     params={"imsi_arr": "a,b", "starttime": 窗口起点（必填，缺键 500 / 空串 not found，
     见 query_terminal docstring 与 README 第 2 节实测）}
     -> {"status": 0, "data": {imei_arr / modelname_arr / ...}}（无命中字段用 "--" 占位）。

3) 登录与 vReport 直连同一条门户链路（loginAuthenticate 取公钥 → PKCS#1 v1.5 加密
   口令 → /web/res/web-common/login），凭据组 vmax_cca（独立于 vmax_cxo，
   避免与 8790 看板代理同账号互踢会话）。
"""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Dict, List, Optional

import requests

# 加密信封 / 响应解析 / 基址全部复用 vReport 客户端的既有实现，不造第二份
from backend.services.vmax_multi_data.vmax_report_client import (
    VMAX_HOST, RSA_HEADER, _loads_tolerant, encrypt_long,
)

logger = logging.getLogger("vmax_cca.client")

CCA_REFERER_PATH = "/rdk/app/vmax_s_data_cca/complaint/web/"
QUERY_USER_PATH = "/vmax/cca/view/userinfo/query_imsimdn"
QUERY_TERMINAL_PATH = "/vmax/cca/view/userinfo/query_terminal"
QUERY_FLOW_PATH = "/vmax/cca/view/flowinfo/query_flow"
QUERY_CELL_PATH = "/vmax/cca/view/usertrack/query_cell"
KPI_DICT_PATH = "/vmax/cca/view/global/kpi_popup/query_kpi"
QUERY_CAUSE_PATH = "/vmax/cca/view/getcause"
# 根因分析模型 id（2026-10-25 实测：model_id 为空串时上游恒返回 "cause info is null"，
# 传 "1" 即出全量根因；CCA 前端由页面模型下拉选择，本页固定用默认模型）
CCA_CAUSE_MODEL_ID = "1"

# 时间窗参数（2026-10-24 从 CCA 前端 main.js 复刻 + 真号实测，见 README 第 2 节）：
# CCA 投诉页按「天」查询，starttime/endtime 是 "YYYY-MM-DD HH:MM:SS" 全格式，
# 日界分别为 00:00:00 / 23:59:00；rat / rattype 0=全部；servicetype 1=数据业务 2=语音。
CCA_RAT_ALL = 0
CCA_RATTYPE_ALL = 0
CCA_SERVICE_DATA = 1
CCA_COMPLAINT_SWITCH_DATA = 1
# 窗口跨度上限：近 7 天的 usertrack 查询已明显变慢（上游要扫更多分区），再大没有意义
MAX_WINDOW_DAYS = 31

# 与 realtime_proxy_vmax._probe_session 的判据一致：只有明确的 HTTP 拒答才视为
# 会话失效；超时 / TLS / 5xx 不重登（门户单会话，乱重登会把别人的会话挤掉）
_SESSION_REJECTED_CODES = (401, 403, 404, 407)
DEFAULT_TIMEOUT = (10, 60)


class VmaxCcaError(RuntimeError):
    """CCA 查询失败（上游业务错误 / 报文无法解析）。"""


class VmaxCcaUnavailable(VmaxCcaError):
    """网络 / 会话 / 登录不可用。"""


class VmaxCcaNotConfigured(VmaxCcaUnavailable):
    """vmax_cca 凭据未配置（环境变量与凭据库都为空）。"""


def normalize_msisdn(raw: str) -> str:
    """号码轻归一：只剔除空格/横线/括号/`+` 等分隔符，**前缀原样透传**。

    2026-10-24 实测（真号 231777777322）：VMAX 服务端只认 `231` 开头的完整号码，
    剥成本地 9 位会返回 IMSI is not found；CCA 前端对 msisdn 也是原样透传
    （README 第 2 节），这里曾剥 231 前缀导致查不到，已改回透传。
    """
    return re.sub(r"[\s\-().+]", "", str(raw or "")).strip()


def normalize_window(start: Any = None, end: Any = None) -> Dict[str, str]:
    """把用户输入的时间窗归一成 CCA 的 starttime/endtime 全格式。

    接受 "YYYY-MM-DD" 或 "YYYY-MM-DD HH:MM[:SS]"（datetime 也行）；
    日粒度输入按 CCA 惯例补 00:00:00 / 23:59:00 日界。缺省窗口 = 今天。
    跨度超过 MAX_WINDOW_DAYS 天报错（上游大窗口明显变慢且无意义）。
    """
    from datetime import datetime, timedelta

    def _parse(v, end_of):
        if isinstance(v, datetime):
            dt = v
        else:
            text = str(v or "").strip().replace("T", " ")
            if not text:
                return None
            day_only = len(text) <= 10
            try:
                dt = datetime.fromisoformat(text)
            except ValueError:
                dt = datetime.strptime(text[:16], "%Y-%m-%d %H:%M")
            if day_only:
                return dt.replace(hour=23 if end_of else 0,
                                  minute=59 if end_of else 0,
                                  second=59 if end_of else 0)
        return dt

    today = datetime.now()
    st = _parse(start, False)
    et = _parse(end, True)
    if st is None and et is None:
        st = today.replace(hour=0, minute=0, second=0, microsecond=0)
        et = today.replace(hour=23, minute=59, second=59, microsecond=0)
    elif st is None:
        st = et.replace(hour=0, minute=0, second=0)
    elif et is None:
        et = max(st, today)
    if et < st:
        st, et = et, st
    if (et.date() - st.date()).days > MAX_WINDOW_DAYS:
        raise VmaxCcaError("时间窗最多 %d 天（起 %s ~ 止 %s）"
                           % (MAX_WINDOW_DAYS, st.date(), et.date()))
    return {"starttime": st.strftime("%Y-%m-%d %H:%M:%S"),
            "endtime": et.strftime("%Y-%m-%d %H:%M:%S")}


def _mask(msisdn: str) -> str:
    """日志里只留号码头尾，中间打码。"""
    text = str(msisdn or "")
    if len(text) <= 6:
        return "*" * len(text)
    return text[:4] + "*" * (len(text) - 6) + text[-2:]


def _is_placeholder(value: Any) -> bool:
    """上游查无数据时用 "--"（可嵌套在列表里）填充所有字段。"""
    if value is None or value == "--" or value == "":
        return True
    if isinstance(value, list):
        return all(_is_placeholder(v) for v in value)
    return False


def _parse_app_flux(raw: str) -> list:
    """解析上游 app_flux 字符串 -> 应用列表。

    ⚠️ 上游给的是 **Python 对象字面量**（单引号键值），不是 JSON：
    `"[{'app_name': 'HTTPS', 'app_flux': '444.89MB', ...}]"`。
    2026-10-30 实测 `json.loads` 会抛 JSONDecodeError，
    旧实现 catch 后当空列表 —— 命中用户的应用明细被整段丢弃。

    这里先用 `ast.literal_eval`（只求值字面量，不执行任意代码），失败再退回
    `json.loads`（万一上游哪天改成标准 JSON 也能用）。
    """
    text = (raw or "").strip()
    if not text or text == "[]":
        return []
    try:
        import ast
        value = ast.literal_eval(text)
        return value if isinstance(value, list) else []
    except (ValueError, SyntaxError):
        pass
    try:
        value = json.loads(text)
        return value if isinstance(value, list) else []
    except ValueError:
        logger.warning("[vmax_cca] app_flux 解析失败（长度 %d）", len(text))
        return []


# ---------------------------------------------------------------------------
# 流量分类（上游 CCA「流量信息」面板的页签口径，2026-10-30 实测还原）
# ---------------------------------------------------------------------------
# 上游 app_flux 每条记录带 service/service_name/service_id：
#   service=1 VIDEO / 2 WEB / 4 OTT VOICE / 0 OTHERS
# 且 kpiinfo 里的 query_tablename 直接暴露了分类（aggr_cca_app_<分类>_day）。
# CCA 网页的页签是「数据 | 语音」两级 + 下面一排应用分类，
# 这里把上游口径映射成前端页签，前端不再自己猜分类名。
#
# 注意：语音（servicetype=2）上游**不支持**
# （实测 "Traffic info of service type [VOICE] is not supported"），
# 故 FLOW_SERVICE_TYPES 只有数据一档。
FLOW_SERVICE_DATA = CCA_SERVICE_DATA
FLOW_SERVICE_VOICE = 2

# 上游 service_name -> 页签 key。OTT VIDEO 在样本里并入 OTHERS（上游把
# OTT Video Call 归到 others 聚合表），故这里不做臆测映射，缺省归 others。
FLOW_CATEGORY_BY_SERVICE_NAME = {
    "VIDEO": "video",
    "WEB": "web",
    "GAME": "game",
    "OTT VOICE": "ottvoice",
    "OTT VIDEO": "ottvideo",
    "OTHERS": "others",
}

# 分类 -> 上游 KPI 聚合表名（kpiinfo.query_tablename 的中间段）。
# 「all」是全量口径（TCP/时延/重传等通用指标），各分类表是该分类的专有指标。
FLOW_CATEGORY_TABLES = {
    "others": "aggr_cca_app_others_day",
    "video": "aggr_cca_app_video_day",
    "web": "aggr_cca_app_web_day",
    "game": "aggr_cca_app_game_day",
    "ottvoice": "aggr_cca_app_ottvoice_day",
    "ottvideo": "aggr_cca_app_ottvideo_day",
    "all": "aggr_cca_app_all_day_7",
}


_FLUX_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z/]*)\s*$")


def _split_flux(text: str) -> tuple:
    """把上游的 '444.89MB' 拆成 (444.89, 'MB')。

    上游 app_flux 是**带单位的字符串**（不是数字），分类求和需要数值，
    所以在这里统一拆开。解析不了就返回 (None, 原串)，前端显示原值。
    """
    raw = str(text or "").strip()
    m = _FLUX_RE.match(raw)
    if not m:
        return None, (raw or "")
    try:
        return float(m.group(1)), (m.group(2) or "")
    except ValueError:
        return None, raw


def normalize_flow_apps(apps: list) -> List[Dict[str, Any]]:
    """把上游 app_flux 列表归一成前端要的形状（分类 + KPI 明细）。

    每条返回：
      {app_name, flux, flux_numeric, flux_unit, flux_ratio, category,
       category_label, is_key_app, service, service_id, kpis: [{name, value, unit}]}

    KPI 归集口径（重要）：上游每个应用的 kpiinfo 是一个**数组**，每个元素对应
    一张聚合表（aggr_cca_app_all_day_7 / _video_day / _web_day / _others_day…），
    元素里的 kpi_name/kpi_value/kpi_unit 是等长数组，且带 qci 档位
    （'all' 全量 / '6-9' 高优先级队列）。若把所有元素混在一起，
    「视频」页签会显示网页的指标 —— 所以这里按 query_tablename 分流：
      - 该应用所属分类的表 -> 归入应用自身的 kpis；
      - 全量表（aggr_cca_app_all*）-> 归入全量口径（前端「流量/TCP指标/控制面」用）；
      - 其它分类的表 -> 丢弃（那是别的分类的指标）。
    """
    out: List[Dict[str, Any]] = []
    for item in apps or []:
        if not isinstance(item, dict):
            continue
        service_name = str(item.get("service_name") or "").strip().upper()
        category = FLOW_CATEGORY_BY_SERVICE_NAME.get(service_name, "others")
        own_table = FLOW_CATEGORY_TABLES.get(category, "")
        all_table = FLOW_CATEGORY_TABLES.get("all", "")

        own_kpis: List[Dict[str, Any]] = []
        all_kpis: List[Dict[str, Any]] = []
        other_kpis: List[Dict[str, Any]] = []
        for entry in (item.get("kpiinfo") or []):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("qci") or "") != "all":
                continue
            table = str(entry.get("query_tablename") or "")
            names = entry.get("kpi_name") or []
            values = entry.get("kpi_value") or []
            units = entry.get("kpi_unit") or []
            rows: List[Dict[str, Any]] = []
            for idx, name in enumerate(names):
                rows.append({
                    "name": str(name),
                    "value": str(values[idx]) if idx < len(values) else "",
                    "unit": str(units[idx]) if idx < len(units) else "",
                })
            if own_table and table == own_table:
                own_kpis = rows
            elif all_table and table == all_table:
                all_kpis = rows
            else:
                # 兜底：上游的表名不一定与 FLOW_CATEGORY_TABLES 完全对得上
                # （实测 OTT VOICE 的应用被放进 others 表）。留一份备选，
                # 下面 own_kpis 为空时用它。
                other_kpis = rows

        if not own_kpis:
            own_kpis = other_kpis

        flux_num, flux_unit = _split_flux(item.get("app_flux"))
        out.append({
            "app_name": str(item.get("app_name") or ""),
            "flux": str(item.get("app_flux") or ""),
            "flux_numeric": flux_num,
            "flux_unit": flux_unit,
            "flux_ratio": str(item.get("app_flux_ratio") or ""),
            "category": category,
            "category_label": service_name or "OTHERS",
            "is_key_app": int(item.get("is_key_app") or 0),
            "service": item.get("service"),
            "service_id": item.get("service_id"),
            "subservice_id": item.get("subservice_id"),
            "kpis": own_kpis,
            "all_kpis": all_kpis,
        })
    return out


def aggregate_flow_categories(apps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按分类聚合应用与其 KPI，供前端拆成页签（对齐上游 CCA 面板口径）。

    每个分类返回 {key, apps, kpis, total_flux}：
      - apps：该分类下的应用列表；
      - kpis：该分类的专有指标（同一分类下各应用的指标表是同一份，取一份即可）；
      - total_flux：该分类流量合计（按拆出的数值 + 单位求和）。

    「all」这一档是**通用口径**（上游 aggr_cca_app_all 聚合表：TCP 握手成功率、
    时延、重传率等），它不属于任何一个应用分类，但前端「流量 / TCP指标 /
    控制面」三个页签都要用它，所以单列一档。
    """
    by_cat: Dict[str, Dict[str, Any]] = {}
    all_kpis: List[Dict[str, Any]] = []
    for app in apps or []:
        key = str(app.get("category") or "others")
        cat = by_cat.setdefault(key, {"key": key, "apps": [], "kpis": [], "total_flux": ""})
        cat["apps"].append(app)
        if not cat["kpis"] and app.get("kpis"):
            cat["kpis"] = list(app["kpis"])
        if not all_kpis and app.get("all_kpis"):
            all_kpis = list(app["all_kpis"])

    def _total(items: List[Dict[str, Any]]) -> str:
        total = 0.0
        unit = ""
        seen = False
        for it in items:
            num = it.get("flux_numeric")
            if isinstance(num, (int, float)):
                total += float(num)
                seen = True
            if not unit and it.get("flux_unit"):
                unit = str(it["flux_unit"])
        if not seen:
            return ""
        return "%.2f%s" % (total, unit)

    out: List[Dict[str, Any]] = [{
        "key": "all", "apps": list(apps or []), "kpis": all_kpis,
        "total_flux": _total(list(apps or [])),
    }]
    for key in sorted(by_cat.keys()):
        cat = by_cat[key]
        cat["total_flux"] = _total(cat["apps"])
        out.append(cat)
    return out


class VmaxCcaClient:
    """CCA 用户信息查询客户端。进程内单例（get_client），全程持锁串行。"""

    def __init__(self, host: str = VMAX_HOST, credential_key: str = "vmax_cca",
                 timeout: tuple = DEFAULT_TIMEOUT):
        self.host = host.rstrip("/")
        self.credential_key = credential_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False          # 忽略系统代理，直连 VMAX
        self.session.verify = False             # VMAX 自签证书
        self._logged_in = False
        self._kpi_names: Optional[Dict[str, str]] = None
        self._lock = threading.RLock()

    # ---------- 门户登录（与 vmax_report_client.login 同链路，凭据组不同） ----------
    def _login(self) -> None:
        import base64
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from backend.services import credential_store

        # default_secret 传空串：口令只从「环境变量 > 凭据库」取（AGENTS.md 四.2），
        # 两处都空时明确报「未配置」而不是拿空口令去撞登录接口。
        user, password = credential_store.get_credential(
            self.credential_key, "", "", "VMAX_CCA_USER", "VMAX_CCA_PASS")
        if not password:
            raise VmaxCcaNotConfigured(
                "VMAX CCA 凭据未配置：请先在「设置 → 凭据管理」的 vmax_cca 组录入账号密码")
        referer = self.host + CCA_REFERER_PATH
        ua = {"User-Agent": "Mozilla/5.0", "Accept": "*/*", "Referer": referer}
        r = self.session.get(self.host + "/rdk/service/app/portal/server/loginAuthenticate",
                             headers=ua, timeout=self.timeout)
        cfg = _loads_tolerant(r.text)
        public_key = cfg.get("publicKey") if isinstance(cfg, dict) else None
        if not public_key:
            raise VmaxCcaUnavailable("获取登录公钥失败: HTTP %s %s"
                                     % (r.status_code, r.text[:120]))
        pem = "-----BEGIN PUBLIC KEY-----\n" + public_key + "\n-----END PUBLIC KEY-----"
        pub = serialization.load_pem_public_key(pem.encode("utf-8"))
        enc = base64.b64encode(pub.encrypt(password.encode("utf-8"),
                                           padding.PKCS1v15())).decode()
        resp = self.session.post(self.host + "/web/res/web-common/login",
                                 data={"username": user, "password": enc,
                                       "isEncypted": "true"},
                                 headers={**ua,
                                          "Content-Type": "application/x-www-form-urlencoded"},
                                 timeout=self.timeout)
        payload = _loads_tolerant(resp.text)
        if not (isinstance(payload, dict) and payload.get("result") == 1):
            raise VmaxCcaUnavailable("VMAX 门户登录失败: %s" % (resp.text[:200] or payload))
        self._logged_in = True
        logger.info("[vmax_cca] 门户登录成功: %s", user)

    # ---------- 加密 GET ----------
    @staticmethod
    def _encrypted_query(params: Dict[str, Any]) -> str:
        """复刻前端 XHR patcher：参数 JSON -> encryptLong -> base64 -> URL 编码。"""
        import urllib.parse
        from backend.services.vmax_multi_data.vmax_report_client import encrypt_param
        return urllib.parse.quote(encrypt_param(params)["encryptedStr"], safe="")

    def _get(self, path: str, params: Dict[str, Any],
             retry_on_session: bool = True) -> Dict[str, Any]:
        """带加密信封的 GET；HTTP 401/403/404/407 重登后重试一次。"""
        url = "%s%s?encryptedStr=%s" % (self.host, path, self._encrypted_query(params))
        headers = {"User-Agent": "Mozilla/5.0",
                   "Accept": "application/json, text/plain, */*",
                   "Referer": self.host + CCA_REFERER_PATH,
                   **RSA_HEADER}
        with self._lock:
            if not self._logged_in:
                self._login()
            resp = self.session.get(url, headers=headers, timeout=self.timeout,
                                    verify=False)
            if resp.status_code in _SESSION_REJECTED_CODES and retry_on_session:
                logger.info("[vmax_cca] 会话失效(HTTP %s)，重登后重试", resp.status_code)
                self._logged_in = False
                return self._get(path, params, retry_on_session=False)
            payload = _loads_tolerant(resp.text)
        if resp.status_code != 200:
            raise VmaxCcaUnavailable("%s -> HTTP %s: %s"
                                     % (path, resp.status_code, resp.text[:200]))
        if not isinstance(payload, dict):
            raise VmaxCcaError("%s 响应不是 JSON 对象: %r" % (path, payload))
        return payload

    # ---------- 业务查询 ----------
    def query_user(self, msisdn: str) -> Dict[str, Any]:
        """号码 -> 用户信息。found=False 时 user/terminal 为空对象、msg 带上游说明。"""
        payload = self._get(QUERY_USER_PATH, {"msisdn": msisdn})
        status = payload.get("status")
        data = payload.get("data")
        found = status == 0 and isinstance(data, list) and bool(data)
        user: Dict[str, Any] = {}
        imsi_arr: list = []
        if found:
            # data[0]=用户信息对象，data[1].imsi_arr=IMSI 列表（README 第 2 节）
            if len(data) > 0 and isinstance(data[0], dict):
                user = dict(data[0])
            if len(data) > 1 and isinstance(data[1], dict):
                arr = data[1].get("imsi_arr")
                if isinstance(arr, list):
                    imsi_arr = [str(x) for x in arr if str(x).strip()]
            user.setdefault("msisdn", msisdn)
            user["imsi_arr"] = imsi_arr
        return {"found": found, "user": user, "imsi_arr": imsi_arr,
                "status": status, "msg": str(payload.get("msg") or "")}

    def query_terminal(self, imsi_arr: list,
                       starttime: str = "") -> Optional[Dict[str, Any]]:
        """IMSI 列表 -> 终端信息（扁平对象）；查不到返回 None。

        ⚠ starttime 是**必填**的查询窗口起点（2026-10-24 真号实测）：
        缺键 -> 上游 HTTP 500；空串 -> status=1 "Terminal info not found"；
        今天/昨天/7 天前均返回同一份完整终端数据（说明返回的是 IMSI 的终端
        属性记录，窗口起点只须落在最近使用区间内）。空入参时回溯 7 天兜底；
        页面带时间窗时传窗口起点。
        """
        if not imsi_arr:
            return None
        if not starttime:
            from datetime import datetime, timedelta
            starttime = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        payload = self._get(QUERY_TERMINAL_PATH,
                            {"imsi_arr": ",".join(imsi_arr), "starttime": starttime})
        data = payload.get("data")
        if payload.get("status") != 0 or not isinstance(data, dict):
            return None
        # 全部字段都是 "--" 占位 = 上游没查到该终端，按未命中处理
        if all(_is_placeholder(v) for v in data.values()):
            return None
        return dict(data)

    # ---------- KPI 字典 ----------
    def kpi_names(self) -> Dict[str, str]:
        """ppc 码 -> KPI 英文名字典（query_kpi function_id=3，进程内缓存）。

        cellKpi 的键形如 ppc1208204008_42，取 `_` 前段查名；字典是静态目录，
        不设 TTL（进程重启即刷新）。
        """
        if self._kpi_names is not None:
            return self._kpi_names
        names: Dict[str, str] = {}
        payload = self._get(KPI_DICT_PATH, {"function_id": 3})
        data = payload.get("data") if isinstance(payload, dict) else None
        for svc in ((data or {}).get("function_data") or []):
            for k in (svc.get("kpilist") or []):
                code, name = k.get("kpi_code"), k.get("kpi_name")
                if code and name:
                    names[str(code)] = str(name)
        self._kpi_names = names
        return names

    # ---------- 流量（query_flow）----------
    def query_flow(self, imsi: str, window: Dict[str[str, str]],
                   servicetype: int = CCA_SERVICE_DATA) -> Optional[Dict[str, Any]]:
        """IMSI + 时间窗 -> 按应用流量。未命中（无 DPI 记录）返回 None。

        实测大量用户此接口为空（data[0].app_flux="[]"、total_flux="--"，
        CCA 网页同样为空）；命中时 app_flux 是**字符串**。

        ⚠️ app_flux 用的**不是合法 JSON**，而是 Python 对象字面量（单引号、
        True/False/None 写法）。2026-10-30 实测：`json.loads` 直接抛
        JSONDecodeError → 旧实现 catch 掉当空列表，于是**命中用户的应用列表
        被整段丢弃**（页面永远显示「无流量」）。改用 `ast.literal_eval`
        （只解析字面量，不执行代码）。
        """
        payload = self._get(QUERY_FLOW_PATH, {
            "imsi": imsi, "starttime": window["starttime"], "endtime": window["endtime"],
            "rat": CCA_RAT_ALL, "rattype": CCA_RATTYPE_ALL, "servicetype": servicetype})
        data = payload.get("data")
        if payload.get("status") != 0 or not (isinstance(data, list) and data):
            return None
        row = data[0] if isinstance(data[0], dict) else {}
        total = row.get("total_flux")
        if _is_placeholder(total):
            return None
        apps: Any = row.get("app_flux")
        if isinstance(apps, str):
            apps = _parse_app_flux(apps)
        return {"total_flux": str(total), "apps": apps if isinstance(apps, list) else [],
                "service_type": servicetype}

    # ---------- 用户轨迹小区（query_cell）----------
    def query_cells(self, imsi: str,
                    window: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """IMSI + 时间窗 -> 驻留小区列表 + 每小区 KPI（码已映射名字）。

        响应里还有 gridKpi/userGridKpi/cellGrids 等栅格级大块数据（实测 1197 条），
        与「用户在哪些小区」的诉求无关，这里不透传，避免响应膨胀。
        """
        payload = self._get(QUERY_CELL_PATH, {
            "imsi": imsi, "starttime": window["starttime"], "endtime": window["endtime"],
            "rat": CCA_RAT_ALL, "rattype": CCA_RATTYPE_ALL, "servicetype": CCA_SERVICE_DATA,
            "complaintServiceSwitch": CCA_COMPLAINT_SWITCH_DATA})
        data = payload.get("data")
        if payload.get("status") != 0 or not isinstance(data, dict):
            return None
        track = [r for r in (data.get("userTrack") or []) if isinstance(r, dict)]
        if not track:
            return None
        names = self.kpi_names()
        cell_kpi: Dict[str, list] = {}
        for cell, kpis in (data.get("cellKpi") or {}).items():
            if not isinstance(kpis, dict):
                continue
            items = []
            for code, value in kpis.items():
                if code in ("cell", "cellrat", "defineb0000001"):
                    continue  # 标识字段不是 KPI，表里已有
                base = str(code).split("_")[0]
                items.append({"code": str(code), "name": names.get(base, str(code)),
                              "value": value})
            items.sort(key=lambda x: x["code"])
            cell_kpi[str(cell)] = items
        return {"cells": track, "cell_kpi": cell_kpi}

    # ---------- 根因分析（getcause）----------
    def query_causes(self, imsi: str, window: Dict[str, str]) -> Optional[List[Dict[str, Any]]]:
        """IMSI + 时间窗 -> 投诉根因列表（规则名/置信度/劣化明细/处理建议）。

        ⚠ `model_id` 必须传 "1"（默认分析模型）：空串时上游恒返回
        "cause info is null"（2026-10-25 实测）。大窗口（7 天级）上游会超时，
        由 query() 记入 failures 不阻断其它数据。按置信度降序。
        """
        payload = self._get(QUERY_CAUSE_PATH, {
            "imsi": imsi, "rattype": CCA_RATTYPE_ALL, "servicetype": CCA_SERVICE_DATA,
            "starttime": window["starttime"], "endtime": window["endtime"],
            "model_id": CCA_CAUSE_MODEL_ID})
        data = payload.get("data")
        if payload.get("status") != 0 or not isinstance(data, list) or not data:
            return None
        causes = []
        for row in data:
            if not isinstance(row, dict):
                continue
            try:
                confidence = float(str(row.get("confidence", "0")).rstrip("%") or 0)
            except ValueError:
                confidence = 0.0
            causes.append({
                "rule_name": str(row.get("rule_name") or ""),
                "object_type": str(row.get("object_type") or ""),
                "object_name": str(row.get("object_name") or ""),
                "objectinfo": str(row.get("objectinfo") or ""),
                "confidence": confidence,
                "description": str(row.get("description") or ""),
                "solution": str(row.get("solution") or ""),
                "vendor": str(row.get("vendor") or ""),
                "province": str(row.get("province") or ""),
                "city": str(row.get("city") or ""),
                "poortime": str(row.get("poortime") or ""),
                "kqicode": str(row.get("kqicode") or ""),
                "app_info": [{"clttime": str(a.get("clttime") or ""),
                              "judge": str(a.get("judgeInfo") or "")}
                             for a in (row.get("appInfo") or []) if isinstance(a, dict)],
            })
        causes.sort(key=lambda c: (-c["confidence"], c["rule_name"]))
        return causes

    def query(self, msisdn: str, start: Any = None,
              end: Any = None) -> Dict[str, Any]:
        """完整查询：用户信息 + 终端 + 窗口内流量 + 驻留小区 + 根因。

        flow / cells 是时间窗查询，失败不阻断用户信息（置 None 并带 failures 说明）；
        终端的 starttime 用窗口起点（真号实测今天/昨天/7 天前返回同一份数据）。
        """
        msisdn = normalize_msisdn(msisdn)
        window = normalize_window(start, end)
        user_result = self.query_user(msisdn)
        sections: Dict[str, Any] = {"flow": None, "cells": None, "causes": None}
        failures: list = []
        terminal = None
        if user_result["found"]:
            imsi = user_result["imsi_arr"][0] if user_result["imsi_arr"] else ""
            terminal = self.query_terminal(user_result["imsi_arr"], window["starttime"])
            if imsi:
                # causes 放最后：大窗口时它最慢，超时只影响自己（记入 failures）
                for name, fn in (("flow", self.query_flow), ("cells", self.query_cells),
                                 ("causes", self.query_causes)):
                    try:
                        sections[name] = fn(imsi, window)
                    except VmaxCcaError as exc:
                        # 各分项是锦上添花：此处失败不阻断已到手的用户/终端信息
                        # （会话级故障同理——用户信息既然已取到，说明登录是好的）
                        failures.append("%s: %s" % (name, exc))
                        logger.warning("[vmax_cca] %s %s 查询失败: %s",
                                       name, _mask(msisdn), exc)
                # 流量应用列表归一（分类 + KPI 明细），前端据此拆分类页签
                if sections["flow"]:
                    normalized = normalize_flow_apps(
                        sections["flow"].get("apps") or [])
                    sections["flow"]["apps"] = normalized
                    sections["flow"]["categories"] = aggregate_flow_categories(normalized)
        return {"msisdn": msisdn, "found": user_result["found"],
                "user": user_result["user"], "terminal": terminal,
                "window": window, "failures": failures,
                "msg": user_result["msg"], **sections}


_default_client: Optional[VmaxCcaClient] = None


def get_client(**kwargs) -> VmaxCcaClient:
    """模块级单例：复用门户会话（门户会话宝贵，不做查询后 logout）。"""
    global _default_client
    if _default_client is None or kwargs:
        _default_client = VmaxCcaClient(**kwargs)
    return _default_client

# -*- coding: utf-8 -*-
"""IPT Digital Platform（RMS 能源监控平台）站点电源信息客户端。

链路（2026-11-03 从 url.txt 抓包逆向 + 实测打通）：
  1. 登录：portal 是 Angular SPA，OIDC 隐式流（response_type=id_token token，
     client_id=rubix-web，redirect_uri=https://portal.../cb）。
     纯 requests 模拟：GET /connect/authorize -> 登录表单页 -> POST /account/login
     （带 __RequestVerificationToken + ReturnUrl）-> 302 回调 fragment 取 access_token。
  2. 业务：GET /api/v0.1/assets/clients/{cid}/energy/sites?query=<站名> 搜站点，
     GET .../sites/<site_id>/diagram 取电源全景（负载/电池/发电机/市电/整流器/
     油箱/太阳能/环境），GET .../sites/<site_id>/popup 取轻量 KPI 摘要 + 活动告警，
     GET .../sites/<site_id>/with-events 取站点与设备详情。
  3. 全站 5 分钟分辨率（2026-11-04 实测 / 2026-11-06 降频）：filter-map
     不含任何电源数值，也没有批量电源接口；只有逐站查。/diagram 约 5KB、
     并发 32 线程实测 200 站 73.8s（外推 501 站 ~185s，且出现超时），
     即使放宽到 240s 硬上限也会挤占全站 popup 时间；/popup 约 1.5KB、
     并发 32 线程实测 501 站 60.1s、0 错误，故以 /popup 作全站 5 分钟
     KPI 层，/diagram 留给分片。

凭据来源（优先级）：环境变量 IPT_USERNAME / IPT_PASSWORD > 同目录 url.txt 中
「用户名：xxx」「密码：xxx」两行。凭据不落代码、不写日志。

用法：
  python ipt_energy_client.py "Jahtondo Town"            # 中文摘要
  python ipt_energy_client.py "Jahtondo Town" --json     # 归一化 JSON
  python ipt_energy_client.py "Jahtondo" --list          # 只搜站点列表
"""
import base64
import json
import logging
import os
import re
import sys
import time
import urllib.parse

import requests

logger = logging.getLogger(__name__)

AUTH_HOST = "https://login.iptdigitalplatform.com"
BACKEND_HOST = "https://backend.iptdigitalplatform.com"
OIDC_CLIENT_ID = "rubix-web"
OIDC_REDIRECT_URI = "https://portal.iptdigitalplatform.com/cb"
OIDC_RESPONSE_TYPE = "id_token token"  # 隐式流，无 code 无 PKCE
OIDC_SCOPE = "openid rubix-api email profile"
DEFAULT_CLIENT_REF = "9eda5e46b0294eb589881ee74f8940da"  # 客户（Orange Liberia）租户 id，抓包确认
TOKEN_TTL_MARGIN = 120  # 过期前 120s 视为失效

# filter-map 是整轮采集唯一的单点请求：历史上 19 次任务失败里 17 次都是它
# 读超时 / 408 / 500 后整轮直接判失败（2026-11-06 复盘）。这里只对上游瞬时
# 抖动做 1 次短重试，第 2 次用更短超时，避免把 240s 硬上限吃光。
FILTER_MAP_RETRY_GAP_S = 2.0
FILTER_MAP_RETRY_TIMEOUT_S = 12

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOKEN_CACHE = os.path.join(_HERE, "auth_cache", "ipt_token.json")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")


def _creds_from_url_txt(path=None):
    """从 url.txt 头部解析「用户名：xxx / 密码：xxx」两行（本地抓包文件）。"""
    path = path or os.path.join(_HERE, "url.txt")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(2000)
    except OSError:
        return None, None
    u = re.search(r"用户名\s*[:：]\s*(\S+)", head)
    p = re.search(r"密码\s*[:：]\s*(\S+)", head)
    return (u.group(1) if u else None), (p.group(1) if p else None)


def _jwt_exp(token):
    try:
        pl = token.split(".")[1]
        pl += "=" * (-len(pl) % 4)
        return json.loads(base64.urlsafe_b64decode(pl)).get("exp", 0)
    except Exception:
        return 0


class IptEnergyError(RuntimeError):
    pass


class IptEnergyClient:
    def __init__(self, username=None, password=None, client_ref=None,
                 token_cache=_TOKEN_CACHE, timeout=25):
        env_u, env_p = os.environ.get("IPT_USERNAME"), os.environ.get("IPT_PASSWORD")
        self.username = username or env_u
        self.password = password or env_p
        if not self.username or not self.password:
            u, p = _creds_from_url_txt()
            self.username = self.username or u
            self.password = self.password or p
        if not self.username or not self.password:
            raise IptEnergyError(
                "缺少凭据：请设置环境变量 IPT_USERNAME / IPT_PASSWORD，"
                "或在 backend/services/ipt_data/url.txt 头部保留「用户名：…/密码：…」两行")
        self.client_ref = client_ref or DEFAULT_CLIENT_REF
        self.token_cache = token_cache
        self.timeout = timeout
        self._session = requests.Session()
        self._session.trust_env = False  # 本机环境有 http_proxy，外网 API 直连
        self._token = None

    # ---------- 登录（OIDC 隐式流） ----------
    def _login(self):
        s = self._session
        hdrs = {"User-Agent": _UA, "Referer": AUTH_HOST + "/",
                "Origin": AUTH_HOST}
        q = {
            "client_id": OIDC_CLIENT_ID,
            "redirect_uri": OIDC_REDIRECT_URI,
            "response_type": OIDC_RESPONSE_TYPE,
            "scope": OIDC_SCOPE,
            "nonce": "ipt%d" % int(time.time()),
            "state": "st%d" % int(time.time()),
        }
        r = s.get(AUTH_HOST + "/connect/authorize", params=q, headers=hdrs,
                  timeout=self.timeout)
        tok = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', r.text)
        ret = re.search(r'name="ReturnUrl"[^>]*value="([^"]+)"', r.text)
        if not tok or not ret:
            raise IptEnergyError("登录页结构变化：未找到表单字段（__RequestVerificationToken/ReturnUrl）")
        r2 = s.post(r.url, headers={**hdrs, "Referer": r.url},
                    data={
                        "ReturnUrl": ret.group(1).replace("&amp;", "&"),
                        "Username": self.username,
                        "Password": self.password,
                        "__RequestVerificationToken": tok.group(1),
                    }, timeout=self.timeout, allow_redirects=False)
        loc = r2.headers.get("Location", "")
        # 302 链：/connect/authorize/callback -> portal /cb#access_token=...
        for _ in range(10):
            if not loc:
                raise IptEnergyError("登录失败：登录 POST 后无跳转（账号密码错误或被风控），HTTP %s" % r2.status_code)
            if loc.startswith("/"):
                loc = AUTH_HOST + loc
            u = urllib.parse.urlparse(loc)
            if "access_token=" in u.fragment:
                frag = dict(urllib.parse.parse_qsl(u.fragment))
                at = frag["access_token"]
                exp = _jwt_exp(at)
                self._token = {"access_token": at, "expires_at": exp,
                               "got_at": int(time.time())}
                self._save_token()
                return self._token
            r2 = s.get(loc, headers=hdrs, timeout=self.timeout, allow_redirects=False)
            loc = r2.headers.get("Location", "")
        raise IptEnergyError("登录失败：未在回调中取得 access_token")

    def _save_token(self):
        try:
            os.makedirs(os.path.dirname(self.token_cache), exist_ok=True)
            with open(self.token_cache, "w", encoding="utf-8") as f:
                json.dump(self._token, f)
        except OSError:
            pass  # 缓存写失败不致命，每次重登即可

    def token(self):
        now = int(time.time())
        if self._token and self._token["expires_at"] - TOKEN_TTL_MARGIN > now:
            return self._token["access_token"]
        if not self._token and os.path.exists(self.token_cache):
            try:
                with open(self.token_cache, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if cached.get("expires_at", 0) - TOKEN_TTL_MARGIN > now:
                    self._token = cached
                    return self._token["access_token"]
            except (OSError, ValueError):
                pass
        self._login()
        return self._token["access_token"]

    # ---------- 业务请求 ----------
    def _get(self, path, params=None):
        url = (BACKEND_HOST + "/api/v0.1/assets/clients/" + self.client_ref
               + "/energy" + path)
        for attempt in (1, 2):  # 401 自动重登一次
            r = self._session.get(
                url, params=params, timeout=self.timeout,
                headers={"Authorization": "Bearer " + self.token(),
                         "Accept": "application/json, text/plain, */*",
                         "Origin": "https://portal.iptdigitalplatform.com",
                         "Referer": "https://portal.iptdigitalplatform.com/",
                         "User-Agent": _UA})
            if r.status_code == 401 and attempt == 1:
                self._token = None
                try:
                    os.remove(self.token_cache)
                except OSError:
                    pass
                continue
            if r.status_code != 200:
                raise IptEnergyError("GET %s -> HTTP %s: %s" % (path, r.status_code, r.text[:200]))
            return r.json()
        raise IptEnergyError("GET %s 重登后仍 401" % path)

    # ---------- 对外接口 ----------
    def filter_map(self, body=None, attempts: int = 2):
        """全站清单 + 连接状态（1 个请求，~500 站；filter-map POST）。

        2026-11-06：这是整轮采集唯一的单点请求，历史上 19 次任务失败里 17 次
        都是它读超时 / 408 / 500 后整轮直接判失败。现在对「上游瞬时抖动」做
        1 次短重试（第 2 次 12s 超时），只对超时 / 408 / 5xx 重试；其它 4xx
        不重试；401 仍按原逻辑重登一次，且不消耗重试次数。
        """
        url = (BACKEND_HOST + "/api/v0.1/assets/clients/" + self.client_ref
               + "/energy/sites/filter-map")
        body = body or {"favoriteFilterId": None, "flatOrganizationIds": [],
                        "siteClusterIds": [], "siteConfigurationIds": [],
                        "sitePriorityIds": [], "connectivities": [],
                        "eventCriticalities": [], "eventNames": [],
                        "eventCategories": [], "sitesType": None}
        attempts = max(1, int(attempts))
        relogin_used = False
        attempt = 0
        while attempt < attempts:
            attempt += 1
            req_timeout = (self.timeout if attempt == 1
                           else min(self.timeout, FILTER_MAP_RETRY_TIMEOUT_S))
            try:
                r = self._session.post(
                    url, json=body, timeout=req_timeout,
                    headers={"Authorization": "Bearer " + self.token(),
                             "Accept": "application/json, text/plain, */*",
                             "Content-Type": "application/json",
                             "Origin": "https://portal.iptdigitalplatform.com",
                             "Referer": "https://portal.iptdigitalplatform.com/",
                             "User-Agent": _UA})
            except requests.exceptions.RequestException as e:
                if attempt < attempts:
                    logger.warning("filter-map 第 %d 次请求异常，%.0fs 后重试：%s",
                                   attempt, FILTER_MAP_RETRY_GAP_S, e)
                    time.sleep(FILTER_MAP_RETRY_GAP_S)
                    continue
                raise
            if r.status_code == 401 and not relogin_used:
                relogin_used = True
                attempt -= 1          # 401 重登不消耗重试次数
                self._token = None
                try:
                    os.remove(self.token_cache)
                except OSError:
                    pass
                continue
            if r.status_code == 408 or r.status_code >= 500:
                if attempt < attempts:
                    logger.warning("filter-map 第 %d 次 HTTP %s，%.0fs 后重试",
                                   attempt, r.status_code, FILTER_MAP_RETRY_GAP_S)
                    time.sleep(FILTER_MAP_RETRY_GAP_S)
                    continue
                raise IptEnergyError("POST filter-map -> HTTP %s: %s" % (
                    r.status_code, r.text[:200]))
            if r.status_code != 200:
                raise IptEnergyError("POST filter-map -> HTTP %s: %s" % (
                    r.status_code, r.text[:200]))
            return r.json()
        raise IptEnergyError("POST filter-map 重登/重试后仍失败")

    def find_sites(self, query):
        """按站名模糊搜索，返回站点概要列表（含完整站点属性）。"""
        return self._get("/sites", params={"query": query}) or []

    def list_sites(self, page=1, page_size=100):
        """分页列全站（含 internalReference / flatOrganization / cluster /
        priority / configuration 等 filter-map 不提供的属性）。

        实测：GET /energy/sites?query=&page=<n>&pageSize=<n>，服务端 pageSize
        上限 100、默认 20；page 从 1 起。约 6 页可覆盖全部 ~500 站。
        """
        return self._get("/sites", params={"query": "", "page": page,
                                           "pageSize": page_size}) or []

    def get_site_with_events(self, site_id):
        return self._get("/sites/%s/with-events" % site_id)

    def _post(self, path, body):
        """业务 POST（带 Bearer + 401 自动重登一次），与 _get 对称。"""
        url = (BACKEND_HOST + "/api/v0.1/assets/clients/" + self.client_ref
               + "/energy" + path)
        for attempt in (1, 2):
            r = self._session.post(
                url, json=body, timeout=self.timeout,
                headers={"Authorization": "Bearer " + self.token(),
                         "Accept": "application/json, text/plain, */*",
                         "Content-Type": "application/json",
                         "Origin": "https://portal.iptdigitalplatform.com",
                         "Referer": "https://portal.iptdigitalplatform.com/",
                         "User-Agent": _UA})
            if r.status_code == 401 and attempt == 1:
                self._token = None
                try:
                    os.remove(self.token_cache)
                except OSError:
                    pass
                continue
            if r.status_code != 200:
                raise IptEnergyError("POST %s -> HTTP %s: %s"
                                     % (path, r.status_code, r.text[:200]))
            return r.json()
        raise IptEnergyError("POST %s 重登后仍 401" % path)

    def get_site_diagram(self, site_id):
        """电源全景（明细层）：负载/电池组/发电机/市电/整流器/油箱/太阳能/环境。"""
        return self._get("/sites/%s/diagram" % site_id)

    def get_site_popup(self, site_id):
        """站点弹窗摘要（KPI 层）：site 属性 + 活动告警 + 精简 diagram。

        实测 ~1.5KB，只有 diagram 的 1/3；含 loadPower / batteryVoltage /
        batteryStateOfCharge / solarPower / fuelTankLevel / generatorOn 与
        site.events（Mains Fail、Engine standby 等活动告警）。
        501 站并发 32 线程实测 60.1s、0 错误，是全站 5 分钟分辨率的数据源。
        """
        return self._get("/sites/%s/popup" % site_id)

    def get_recent_events(self, duration=60):
        """全站近 N 分钟「新发生」事件（1 个请求，bulk）。

        注意：只含最近发生的事件，**不含**长期未清除的活动告警；
        站点「N Active Alarms」应以 get_site_popup() 的 site.events 为准。
        """
        return self._post("/events/recent", {"duration": duration})

    # ---------- 并发采集支持 ----------
    def token_info(self):
        """返回当前有效 token dict，供 fork_for_thread() 复用。"""
        self.token()  # 确保已登录/已刷新
        return dict(self._token) if self._token else None

    def fork_for_thread(self, token_info=None, timeout: float = None):
        """为每个工作线程派生一个独立 requests.Session 的客户端。

        requests.Session **非线程安全**（连接池/ CookieJar 共享会串包），
        并发逐站采集必须每线程一个实例；token 复用主客户端的，避免 32 个
        线程同时触发 OIDC 重登把登录端点打爆。
        timeout：可覆盖单请求超时（线程池里用更短超时，避免个别站点
        25s 卡顿吃掉整轮预算——2026-11-04 晚高峰实测）。
        """
        child = IptEnergyClient(
            username=self.username, password=self.password,
            client_ref=self.client_ref, token_cache=self.token_cache,
            timeout=timeout or self.timeout)
        child._token = dict(token_info) if token_info else self.token_info()
        return child

    # ---------- popup / diagram 归一化（全站 5 分钟 KPI 层 + 明细层共用） ----------
    _SLIM_EVENT_KEYS = ("id", "name", "criticality", "category", "isDismissed")

    @staticmethod
    def _num(v):
        """上游数值字段 → float/int，其余（None/字符串/布尔）一律 None。"""
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    @staticmethod
    def solar_values(d):
        """汇总站点太阳能 → (power_W, current_A, available)。

        - available：solarSets 有配置 = 1，无 = 0（页面据此显示 0 W 或「-」，
          解决「无太阳能设备的站也显示 0」的歧义）。
        - solarSets[].solarPower 与 rectifiers[].solarPower 上游是同一份镜像值
          （2026-11-04 对 3945 条历史快照逐条核对：非零值一一相等），取 max
          避免重复累加；多组太阳能时先对 solarSets 求和再与 rectifier 镜像取大者。
          夜间（利比里亚 GMT，约 18:30 后日出前）太阳能为 0 属正常物理现象，
          历史数据白天常见 6~14 kW。
        """
        def collect(key, field):
            out = []
            for item in d.get(key) or []:
                v = IptEnergyClient._num(item.get(field))
                if v is not None:
                    out.append(v)
            return out
        ss, rs = collect("solarSets", "solarPower"), collect("rectifiers", "solarPower")
        power = max([sum(ss)] + rs) if (ss or rs) else None
        sc = collect("solarSets", "solarCurrent")
        rc = collect("rectifiers", "solarCurrent")
        current = max([sum(sc)] + rc) if (sc or rc) else None
        available = 1 if d.get("solarSets") else 0
        return power, current, available

    @staticmethod
    def slim_diagram(d):
        """diagram → 精简 dict（保留展示字段，剥掉 device 对象与凭据）。

        ⚠ 原始 diagram 的 fuelTanks[].device（及 with-events 的 devices[]）带
        控制器明文 username/password，入库/下发前端前必须剥掉——此前 raw 列
        存全量 JSON 并被 /site/{id} 原样返回，属于凭据泄漏，2026-11-04 修复。
        """
        keep = {
            "loads": ["loadCurrent", "loadPower", "loadFrequency"],
            "batterySets": ["name", "totalCapacity", "status", "chargingState",
                            "batteryVoltage", "batteryCurrent", "batteryPower",
                            "batteryStateOfCharge", "batteryAutonomy",
                            "batteryTemperature1", "batteryTemperature2",
                            "batteryMinVoltageToday", "batteryMaxVoltageToday"],
            "generators": ["name", "capacity", "generatorOn", "generatorOnChanged",
                           "changedGeneratorOn", "generatorFuelRate",
                           "generatorLoadRatio", "generatorOperatingMode",
                           "generatorVoltagePhase1", "generatorVoltagePhase2",
                           "generatorVoltagePhase3", "generatorCurrentPhase1",
                           "generatorCurrentPhase2", "generatorCurrentPhase3"],
            "rectifiers": ["name", "capacity", "rectifierCurrent", "mainSourceOn",
                           "mainSourceCurrent", "mainSourcePower", "solarPower",
                           "solarCurrent", "solarVoltage", "loadPower", "loadRatio",
                           "batteryChargingState", "mainSourceVoltagePhase1",
                           "mainSourceVoltagePhase2", "mainSourceVoltagePhase3",
                           "rectifierTotalInputCurrent"],
            "fuelTanks": ["name", "capacity", "fuelLevel", "fuelRatio",
                          "fuelTankLevel", "fuelTankRatio", "fuelLevelLastUpdated"],
            "gridBackups": ["name", "gridOn", "gridVoltagePhase1", "gridVoltagePhase2",
                            "gridVoltagePhase3", "gridCurrentPhase1",
                            "gridCurrentPhase2", "gridCurrentPhase3"],
            "grids": ["name", "gridOn", "gridVoltagePhase1", "gridVoltagePhase2",
                      "gridVoltagePhase3", "gridCurrentPhase1", "gridCurrentPhase2",
                      "gridCurrentPhase3"],
            "solarSets": ["name", "capacity", "solarOn", "solarVoltage", "solarPower",
                          "solarCurrent", "solarLoadRatio", "pvcModulesTotal",
                          "pvcModulesOkay", "pvcModulesFailed"],
        }
        out = {}
        for sec, keys in keep.items():
            items = d.get(sec) or []
            if not items:
                continue
            slim_items = []
            for it in items:
                item = {k: it.get(k) for k in keys if it.get(k) is not None}
                if it.get("events"):
                    item["events"] = [
                        {k: e.get(k) for k in IptEnergyClient._SLIM_EVENT_KEYS
                         if e.get(k) is not None}
                        for e in it["events"]]
                slim_items.append(item)
            out[sec] = slim_items
        env = d.get("environment") or {}
        env_slim = {k: env.get(k) for k in ("indoorTemperature", "outdoorTemperature",
                                            "cabinetDoorOpenAlarm")
                    if env.get(k) is not None}
        if env_slim:
            out["environment"] = env_slim
        core = d.get("coreSiteConnectors") or {}
        if core.get("mainSourceOn") is not None:
            out["coreSiteConnectors"] = {"mainSourceOn": core.get("mainSourceOn")}
        return out

    @staticmethod
    def normalize_popup(popup):
        """popup → 快照字段 dict（全站 5 分钟 KPI 层）。

        popup.diagram 是 diagram 的精简子集：无 loads/environment/mainSourceOn，
        fuelTanks 只有 fuelTankLevel，grids/solarSets 只有 deviceId；site.events
        是站点级活动告警（Mains Fail / Engine standby 等）。
        """
        p = popup or {}
        site = p.get("site") or {}
        d = p.get("diagram") or {}
        n = IptEnergyClient._num

        def first(key):
            lst = d.get(key) or []
            return lst[0] if isinstance(lst, list) and lst else {}

        r, b, g = first("rectifiers"), first("batterySets"), first("generators")
        t, gr = first("fuelTanks"), first("grids")
        solar_power, solar_current, solar_available = IptEnergyClient.solar_values(d)
        alarms = [{"name": e.get("name"), "criticality": e.get("criticality"),
                   "created": e.get("created")}
                  for e in site.get("events") or [] if e.get("name")]
        soc_r, soc_b = n(r.get("batteryStateOfCharge")), n(b.get("batteryStateOfCharge"))
        return {
            "load_current": None,   # popup 无负载电流，明细层补
            "load_power": n(r.get("loadPower")),
            "battery_voltage": n(r.get("batteryVoltage")) or n(b.get("batteryVoltage")),
            "battery_current": None,
            "battery_power": None,
            "battery_soc": soc_r if soc_r is not None else soc_b,
            "battery_charging_state": None,
            "battery_temp1": None,
            "generator_on": None if g.get("generatorOn") is None
                            else int(bool(g.get("generatorOn"))),
            "solar_power": solar_power,
            "solar_current": solar_current,
            "solar_available": solar_available,
            "fuel_level": (n(t.get("fuelTankLevel")) if t.get("fuelTankLevel") is not None
                           else n(t.get("fuelLevel"))),
            "fuel_ratio": None,
            "grid_on": None if gr.get("gridOn") is None else int(bool(gr.get("gridOn"))),
            "main_source_on": None,
            "fuel_capacity": None,
            "alarm_count": len(alarms),
            "alarm_names": alarms,
            "source": "popup",
        }

    @staticmethod
    def normalize_diagram_full(d):
        """diagram → 快照字段 dict（明细层，含 popup 缺失的全部字段）。"""
        n = IptEnergyClient._num

        def first(key):
            lst = d.get(key) or []
            return lst[0] if isinstance(lst, list) and lst else {}

        load = first("loads")
        batt = first("batterySets")
        gen = first("generators")
        solar = first("solarSets")
        tank = first("fuelTanks")
        grid = first("grids")
        rect = first("rectifiers")
        solar_power, solar_current, solar_available = IptEnergyClient.solar_values(d)
        alarms = []
        for sec in ("batterySets", "generators", "rectifiers", "fuelTanks",
                    "solarSets", "grids", "gridBackups"):
            for it in d.get(sec) or []:
                for e in it.get("events") or []:
                    if e.get("name") and not e.get("isDismissed"):
                        alarms.append({"name": e.get("name"),
                                       "criticality": e.get("criticality"),
                                       "category": e.get("category")})
        return {
            "load_current": n(load.get("loadCurrent")),
            "load_power": n(load.get("loadPower")),
            "battery_voltage": n(batt.get("batteryVoltage")),
            "battery_current": n(batt.get("batteryCurrent")),
            "battery_power": n(batt.get("batteryPower")),
            "battery_soc": n(batt.get("batteryStateOfCharge")),
            "battery_charging_state": batt.get("chargingState"),
            "battery_temp1": n(batt.get("batteryTemperature1")),
            "battery_temp2": n(batt.get("batteryTemperature2")),
            "battery_name": batt.get("name"),
            "battery_capacity": n(batt.get("totalCapacity")),
            "battery_min_v_today": n(batt.get("batteryMinVoltageToday")),
            "battery_max_v_today": n(batt.get("batteryMaxVoltageToday")),
            "generator_on": None if gen.get("generatorOn") is None
                            else int(bool(gen.get("generatorOn"))),
            "generator_name": gen.get("name"),
            "generator_capacity": n(gen.get("capacity")),
            "generator_mode": gen.get("generatorOperatingMode"),
            "generator_changed": gen.get("generatorOnChanged"),
            "gen_v1": n(gen.get("generatorVoltagePhase1")),
            "gen_v2": n(gen.get("generatorVoltagePhase2")),
            "gen_v3": n(gen.get("generatorVoltagePhase3")),
            "gen_a1": n(gen.get("generatorCurrentPhase1")),
            "gen_a2": n(gen.get("generatorCurrentPhase2")),
            "gen_a3": n(gen.get("generatorCurrentPhase3")),
            "solar_power": solar_power,
            "solar_current": solar_current,
            "solar_available": solar_available,
            "solar_voltage": n(solar.get("solarVoltage")),
            "solar_load_ratio": n(solar.get("solarLoadRatio")),
            "pvc_okay": n(solar.get("pvcModulesOkay")),
            "pvc_total": n(solar.get("pvcModulesTotal")),
            "pvc_failed": n(solar.get("pvcModulesFailed")),
            "fuel_level": n(tank.get("fuelLevel")),
            "fuel_ratio": n(tank.get("fuelRatio")),
            "fuel_capacity": n(tank.get("capacity")),
            "grid_on": None if grid.get("gridOn") is None else int(bool(grid.get("gridOn"))),
            "grid_v1": n(grid.get("gridVoltagePhase1")),
            "grid_a1": n(grid.get("gridCurrentPhase1")),
            "main_source_on": None if rect.get("mainSourceOn") is None
                              else int(bool(rect.get("mainSourceOn"))),
            "main_source_power": n(rect.get("mainSourcePower")),
            "rectifier_current": n(rect.get("rectifierCurrent")),
            "alarm_count": len(alarms),
            "alarm_names": alarms,
            "source": "diagram",
        }

    def get_site_power(self, query):
        """一站式：站名 -> (站点概要, 电源信息归一化 dict)。多命中取第一个。"""
        sites = self.find_sites(query)
        if not sites:
            return None, None
        site = sites[0]
        diagram = self.get_site_diagram(site["id"])
        return site, self.normalize_power(site, diagram)

    @staticmethod
    def normalize_power(site, d):
        """归一化为精简 dict：去掉空段、只保留有值的关键字段。"""
        def slim(x, keys):
            return {k: x.get(k) for k in keys if x.get(k) is not None} if x else None

        battery_sets = [slim(b, ["name", "totalCapacity", "chargingState", "batteryVoltage",
                                 "batteryCurrent", "batteryPower", "batteryStateOfCharge",
                                 "batteryAutonomy", "batteryTemperature1", "batteryTemperature2",
                                 "batteryMinVoltageToday", "batteryMaxVoltageToday"])
                        for b in d.get("batterySets") or []]
        gens = [slim(g, ["name", "capacity", "generatorOn", "generatorFuelRate",
                         "generatorLoadRatio", "generatorOperatingMode",
                         "generatorVoltagePhase1", "generatorCurrentPhase1"])
                for g in d.get("generators") or []]
        rects = [slim(r, ["name" if "name" in r else "id", "capacity", "rectifierCurrent",
                          "mainSourceOn", "mainSourcePower", "solarPower", "loadPower",
                          "loadRatio", "batteryChargingState", "rectifierTotalInputCurrent"])
                 for r in d.get("rectifiers") or []]
        tanks = [slim(t, ["name", "capacity", "fuelLevel", "fuelRatio", "fuelLevelLastUpdated"])
                 for t in d.get("fuelTanks") or []]
        solars = [slim(sl, ["name", "capacity", "solarOn", "solarVoltage", "solarPower",
                            "solarCurrent", "pvcModulesTotal", "pvcModulesOkay", "pvcModulesFailed"])
                  for sl in d.get("solarSets") or []]
        grids = [slim(g, ["name", "gridOn", "gridVoltagePhase1", "gridCurrentPhase1"])
                 for g in d.get("grids") or []]
        loads = [slim(l, ["loadCurrent", "loadPower", "loadFrequency"]) for l in d.get("loads") or []]
        env = d.get("environment") or {}
        return {
            "site": {"id": site.get("id"), "name": site.get("name"),
                     "reference": site.get("internalReference"),
                     "cluster": (site.get("cluster") or {}).get("name"),
                     "organization": (site.get("flatOrganization") or {}).get("key"),
                     "priority": (site.get("priority") or {}).get("name"),
                     "configuration": (site.get("configuration") or {}).get("name"),
                     "connectivity": site.get("connectivity"),
                     "lat": site.get("latitude"), "lon": site.get("longitude")},
            "loads": [x for x in loads if x] or None,
            "battery_sets": [x for x in battery_sets if x] or None,
            "generators": [x for x in gens if x] or None,
            "rectifiers": [x for x in rects if x and any(v is not None for v in x.values())] or None,
            "fuel_tanks": [x for x in tanks if x] or None,
            "solar_sets": [x for x in solars if x] or None,
            "grids": [x for x in grids if x] or None,
            "environment": {k: env.get(k) for k in
                            ("indoorTemperature", "outdoorTemperature", "cabinetDoorOpenAlarm")
                            if env.get(k) is not None} or None,
            "fetched_at": int(time.time()),
        }


# ---------- CLI ----------
def _fmt(v, unit=""):
    if v is None:
        return "-"
    if isinstance(v, float):
        v = round(v, 2)
    return "%s%s" % (v, unit)


def print_summary(site, pw):
    s = pw.get("site")
    print("站点：%s（参考号 %s，%s / %s，优先级 %s，配置 %s，连接 %s）" % (
        s.get("name"), s.get("reference"), s.get("organization"), s.get("cluster"),
        s.get("priority"), s.get("configuration"), s.get("connectivity")))
    print("坐标：%.6f, %.6f" % (s.get("lat"), s.get("lon")))
    for l in pw.get("loads") or []:
        print("负载：电流 %s A，功率 %s W，频率 %s Hz" % (
            _fmt(l.get("loadCurrent")), _fmt(l.get("loadPower")), _fmt(l.get("loadFrequency"))))
    for b in pw.get("battery_sets") or []:
        soc = b.get("batteryStateOfCharge")
        print("电池组「%s」：容量 %s Ah，%s，电压 %s V，电流 %s A，功率 %s W，SOC %s%%，温度 %s/​%s ℃，今日电压 %s~%s V" % (
            b.get("name"), _fmt(b.get("totalCapacity")), b.get("chargingState"),
            _fmt(b.get("batteryVoltage")), _fmt(b.get("batteryCurrent")), _fmt(b.get("batteryPower")),
            _fmt(soc * 100 if soc is not None and soc <= 1 else soc),
            _fmt(b.get("batteryTemperature1")), _fmt(b.get("batteryTemperature2")),
            _fmt(b.get("batteryMinVoltageToday")), _fmt(b.get("batteryMaxVoltageToday"))))
    for g in pw.get("generators") or []:
        print("发电机「%s」：容量 %s kVA，运行 %s，油率 %s，负载率 %s，模式 %s" % (
            g.get("name"), _fmt(g.get("capacity")), g.get("generatorOn"),
            _fmt(g.get("generatorFuelRate")), _fmt(g.get("generatorLoadRatio")),
            g.get("generatorOperatingMode")))
    for r in pw.get("rectifiers") or []:
        print("整流器：容量 %s，电流 %s A，主源 %s W/%s，输出负载 %s W（%s），电池充电态 %s" % (
            _fmt(r.get("capacity")), _fmt(r.get("rectifierCurrent")),
            _fmt(r.get("mainSourcePower")), r.get("mainSourceOn"),
            _fmt(r.get("loadPower")), _fmt(r.get("loadRatio")), r.get("batteryChargingState")))
    for t in pw.get("fuel_tanks") or []:
        ratio = t.get("fuelRatio")
        print("油箱「%s」：容量 %s L，油位 %s L（%s%%），更新 %s" % (
            t.get("name"), _fmt(t.get("capacity")), _fmt(t.get("fuelLevel")),
            _fmt(ratio * 100 if ratio is not None and ratio <= 1 else ratio),
            t.get("fuelLevelLastUpdated")))
    for sl in pw.get("solar_sets") or []:
        print("太阳能「%s」：容量 %s，开 %s，%s V / %s A / %s W，组件 %s/%s 正常" % (
            sl.get("name"), _fmt(sl.get("capacity")), sl.get("solarOn"),
            _fmt(sl.get("solarVoltage")), _fmt(sl.get("solarCurrent")), _fmt(sl.get("solarPower")),
            sl.get("pvcModulesOkay"), sl.get("pvcModulesTotal")))
    for g in pw.get("grids") or []:
        print("市电「%s」：开 %s，%s V / %s A" % (
            g.get("name", "-"), g.get("gridOn"),
            _fmt(g.get("gridVoltagePhase1")), _fmt(g.get("gridCurrentPhase1"))))
    if pw.get("environment"):
        print("环境：%s" % json.dumps(pw.get("environment"), ensure_ascii=False))
    for kind in ("loads", "battery_sets", "generators", "rectifiers", "fuel_tanks",
                 "solar_sets", "grids"):
        if not pw[kind]:
            print("(%s：无数据)" % kind)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a[2:] for a in argv[1:] if a.startswith("--")}
    if not args:
        print("用法：python ipt_energy_client.py <站名> [--json|--list]")
        return 2
    query = args[0]
    c = IptEnergyClient()
    if "list" in flags:
        for st in c.find_sites(query):
            print("%s | %s | %s | %s" % (st["id"], st["name"],
                                         st.get("internalReference"),
                                         (st.get("flatOrganization") or {}).get("key")))
        return 0
    site, pw = c.get_site_power(query)
    if site is None:
        print("未找到站点：%s" % query)
        return 1
    if "json" in flags:
        print(json.dumps(pw, ensure_ascii=False, indent=2))
    else:
        print_summary(site, pw)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

# -*- coding: utf-8 -*-
"""IPT Digital Platform（RMS 能源监控平台）站点电源信息客户端。

链路（2026-11-03 从 url.txt 抓包逆向 + 实测打通）：
  1. 登录：portal 是 Angular SPA，OIDC 隐式流（response_type=id_token token，
     client_id=rubix-web，redirect_uri=https://portal.../cb）。
     纯 requests 模拟：GET /connect/authorize -> 登录表单页 -> POST /account/login
     （带 __RequestVerificationToken + ReturnUrl）-> 302 回调 fragment 取 access_token。
  2. 业务：GET /api/v0.1/assets/clients/{cid}/energy/sites?query=<站名> 搜站点，
     GET .../sites/<site_id>/diagram 取电源全景（负载/电池/发电机/市电/整流器/
     油箱/太阳能/环境），GET .../sites/<site_id>/with-events 取站点与设备详情。

凭据来源（优先级）：环境变量 IPT_USERNAME / IPT_PASSWORD > 同目录 url.txt 中
「用户名：xxx」「密码：xxx」两行。凭据不落代码、不写日志。

用法：
  python ipt_energy_client.py "Jahtondo Town"            # 中文摘要
  python ipt_energy_client.py "Jahtondo Town" --json     # 归一化 JSON
  python ipt_energy_client.py "Jahtondo" --list          # 只搜站点列表
"""
import base64
import json
import os
import re
import sys
import time
import urllib.parse

import requests

AUTH_HOST = "https://login.iptdigitalplatform.com"
BACKEND_HOST = "https://backend.iptdigitalplatform.com"
OIDC_CLIENT_ID = "rubix-web"
OIDC_REDIRECT_URI = "https://portal.iptdigitalplatform.com/cb"
OIDC_RESPONSE_TYPE = "id_token token"  # 隐式流，无 code 无 PKCE
OIDC_SCOPE = "openid rubix-api email profile"
DEFAULT_CLIENT_REF = "9eda5e46b0294eb589881ee74f8940da"  # 客户（Orange Liberia）租户 id，抓包确认
TOKEN_TTL_MARGIN = 120  # 过期前 120s 视为失效

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
    def filter_map(self, body=None):
        """全站清单 + 连接状态（1 个请求，~498 站；filter-map POST）。"""
        url = (BACKEND_HOST + "/api/v0.1/assets/clients/" + self.client_ref
               + "/energy/sites/filter-map")
        body = body or {"favoriteFilterId": None, "flatOrganizationIds": [],
                        "siteClusterIds": [], "siteConfigurationIds": [],
                        "sitePriorityIds": [], "connectivities": [],
                        "eventCriticalities": [], "eventNames": [],
                        "eventCategories": [], "sitesType": None}
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
                continue
            if r.status_code != 200:
                raise IptEnergyError("POST filter-map -> HTTP %s: %s" % (r.status_code, r.text[:200]))
            return r.json()
        raise IptEnergyError("POST filter-map 重登后仍 401")

    def find_sites(self, query):
        """按站名模糊搜索，返回站点概要列表。"""
        return self._get("/sites", params={"query": query}) or []

    def get_site_with_events(self, site_id):
        return self._get("/sites/%s/with-events" % site_id)

    def get_site_diagram(self, site_id):
        """电源全景：负载/电池组/发电机/市电/整流器/油箱/太阳能/环境。"""
        return self._get("/sites/%s/diagram" % site_id)

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

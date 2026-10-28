# -*- coding: utf-8 -*-
"""eFlow 派单/站点解析 HTTP 客户端。

只做确定性的事：查实时告警、解析用户组 groupId、解析 ME→站点、调派单接口。
会话与重试**全部复用** `eflow_api_client`（`ensure_login` / `_http_request` /
`get_session_headers`），本模块不另建登录链路，避免出现第二套会话。

## 关键接口（来源：`backend/services/eflow_fiber/url_test.txt`）

| 用途 | 方法 | 路径 |
| --- | --- | --- |
| 用户组（拿 groupId） | GET | `/api/fms-assign-svr/v1/wo/userGroupList` |
| 派单（建 TT） | POST | `/api/alarm-assign/manual/assign` |
| 站点搜索（ME→站点 ID/名） | POST | `/api/cmdb/v1/data/search/Site` |
| 实时告警 | POST | `/api/fm-active/v1/activealarms/table` |

## Fiber 派单为什么必须带 site + sitename（2026-10-26 实测）

RAN 告警的 `site` 字段本身就是数字站点 ID（如 `4344`）、`sitename` 已绑定；
而 Fiber（TRM/IPRAN）告警的 `site` 是 **ME 名**（如 `6120HA_zardun_UPE128`）、
`sitename` 为 `--`。用 ME 名直接派单，接口返回 `status:true` 但 **TT 不生成**
（`ttid` 仍为 empty，`ttstatus` 停在 2）。必须在 payload 里把 `site` 换成
**数字站点 ID**、并补 `sitename` 站点名，TT 才会真正建出来
（实测 `site=3462` + `sitename=Zardun` → `ttid=TT202610260085`）。
"""
import difflib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.services import eflow_api_client as api
from backend.services.eflow_fiber.fiber_config import norm_code

logger = logging.getLogger("eflow_fiber_assign")

ASSIGN_API_PATH = "/api/alarm-assign/manual/assign"
GROUP_API_PATH = "/api/fms-assign-svr/v1/wo/userGroupList"
SITE_SEARCH_API_PATH = "/api/cmdb/v1/data/search/Site"
ACTIVE_ALARM_API_PATH = "/api/fm-active/v1/activealarms/table"


def _referer() -> str:
    return f"https://{api.HOST}:{api.PORT}/iui/fm/angularFm/dist/index.html"


def _headers() -> str:
    """构造请求头（Cookie / forgerydefense 每次实时取，避免拿到过期会话）。

    与 `eflow_api_client._headers_extra` 同构；独立写一份是为了显式带上
    `Content-Type: application/json`（url_test.txt 的派单/查询都用它）。
    """
    cookie, tok = api.get_session_headers()
    return (
        f"Cookie: {cookie}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {_referer()}\r\n"
        f"forgerydefense: {tok}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{api.HOST}:{api.PORT}\r\n"
    )


def _json_or_none(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return None


def _iso_now() -> str:
    """eFlow 查询用的 ISO 时间戳（UTC，毫秒精度，带 Z）。"""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _val(v: Any) -> Any:
    """eFlow 告警字段是 {value, displayname, ...} 对象；统一取 value。"""
    if isinstance(v, dict):
        return v.get("value")
    return v


def _s(val: Any) -> str:
    return "" if val is None else str(val).strip()


# ==========================================================
# 用户组
# ==========================================================
def fetch_user_groups() -> Dict[str, Dict[str, Any]]:
    """返回 {组名: {id, name, acceptType}}。失败返回空 dict 并记日志。"""
    api.ensure_login()
    status, hdrs, raw, body = api._http_request(
        "GET", GROUP_API_PATH, headers_extra=_headers())
    data = _json_or_none(body)
    groups: Dict[str, Dict[str, Any]] = {}
    if not isinstance(data, dict):
        logger.warning("[Fiber] userGroupList 返回非 JSON: %s", status)
        return groups
    try:
        lst = data["entity"]["userGroupList"]["data"]
    except (KeyError, TypeError):
        logger.warning("[Fiber] userGroupList 结构异常: %s", list(data.keys()))
        return groups
    for g in lst or []:
        name = str(g.get("name") or "").strip()
        if name:
            groups[name] = g
    return groups


def resolve_group(name: str) -> Optional[Dict[str, Any]]:
    """按名解析目标用户组；找不到返回 None（调用方据此报错，不静默换组）。"""
    groups = fetch_user_groups()
    if not groups:
        return None
    if name in groups:
        return groups[name]
    # 大小写不敏感兜底（页面手填可能大小写不一致）
    low = name.strip().lower()
    for gname, g in groups.items():
        if gname.lower() == low:
            return g
    return None


# ==========================================================
# 站点解析（ME 名 → 站点名 → 站点 ID）
# ==========================================================
def site_name_from_me(mename: Any) -> str:
    """从 ME 名解析站点名。

    形如 `<机型>_<站点名>_<UPE nn>` → 取中间段：
      `6180H-A_Kakata_City_UPE29` → `Kakata City`
      `6120HA_zardun_UPE128`      → `zardun`
    没有下划线分段时原样返回（如 `RIA` / `9000-8EA_SPE01`）。
    保留 ME 名里的原始大小写 —— 站点名以 cmdb 为准，这里只做候选。
    """
    txt = str(_val(mename) or "").strip()
    if not txt:
        return ""
    parts = txt.split("_")
    if len(parts) >= 3:
        return " ".join(p for p in parts[1:-1] if p).strip()
    return txt


def _norm_name(value: Any) -> str:
    """站点名归一化：小写 + 去掉一切非字母数字字符。

    用来吃掉「同一站点不同写法」的噪声（空格/下划线/连字符/点）：
      `Peter_luogan_town` → `peterluogantown`
      `Peter Luogon Town` → `peterluogontown`
    归一化后仍不等，才交给近似匹配（此时差异只剩真正的拼写差别）。
    """
    txt = str(_val(value) or "").strip().lower()
    return "".join(ch for ch in txt if ch.isalnum())


_VOWELS = frozenset("aeiou")


def _vowel_swap_only(a: str, b: str) -> bool:
    """两个归一化名是否「等长、且差异位全是元音互换」。

    ## 为什么必须这么严（2026-10-27 扫生产 cmdb 830 个站点得出的结论）

    只按相似度 ≥0.9 兜底会造成**真实误派**。实测这些是 Liberty 网络上
    **互不相同**的站点，相似度却都不低于 peter luogan 那条（0.9333）：

    | 站点 A | 站点 B | 相似度 |
    | --- | --- | --- |
    | `Garplay` | `Gbarplay` | 0.9333 |
    | `Banwea` | `Gbanwea` | 0.9231 |
    | `Butuo` | `Buutuo` | 0.9091 |
    | `Sanniquillie 5` | `Sanniquillie 1` | 0.9231 |
    | `Buchanan 3 AML` | `Buchanan AML` | 0.9565 |

    即「插入/删除一个字母」和「两个不同站点」在分数上完全无法区分。用
    「等长且仅元音互换」这条硬约束后，830 个站点里**误判 0 对**，同时
    仍然覆盖目标案例：`luogan` → `luogon`（a↔o，等长）。

    代价：漏字母/多字母/辅音打错的拼写差异不再兜底 —— 那些会如实记
    「站点解析失败」等人工处理。**宁可漏派，不可错派。**
    """
    if len(a) != len(b) or a == b:
        return False
    diffs = [(x, y) for x, y in zip(a, b) if x != y]
    return bool(diffs) and all(x in _VOWELS and y in _VOWELS for x, y in diffs)


def _only_digit_suffix_diff(a: str, b: str) -> bool:
    """两个归一化名是否只差尾部数字（分期站点 `X` / `X2` / `X3`）。

    实测动机（2026-10-27 扫描生产 cmdb）：830 个站点里有 **66 对**在 0.9 阈值下
    互相接近，且几乎全是分期站点（`Johnsonville` / `Johnsonville 2` /
    `Johnsonville 3`、`Hotel Africa` / `Hotel Africa 2` / `Hotel Africa 3`）。
    这类差异**不是拼写差异**：`Johnsonville` 与 `Johnsonville 2` 是两个不同的站，
    靠相似度把它们判成同一个就是错派。故只差数字后缀时一律拒绝近似匹配。
    """
    if a == b:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if not long_.startswith(short):
        return False
    rest = long_[len(short):]
    return bool(rest) and rest.isdigit()


class SiteIndex:
    """cmdb Site 全量索引：按站点名（小写）→ [{id, name}] 快照。

    一次性拉全量（约 800+ 条），单轮任务内复用，避免对每个告警单独查一次。
    只在确有 fiber 告警需要解析站点时才构建。

    解析分三档（**严格到宽松，只有前一档查不到才降级**）：
      1. `exact`       —— 大小写不敏感精确匹配；
      2. `normalized`  —— 归一化后精确匹配（只差空格/下划线等分隔符）；
      3. `fuzzy`       —— 归一化名相似度 ≥ 阈值（默认 0.9）。

    ⚠ 近似匹配必须带**歧义保护**：只有当最优候选唯一领先时才采用，
    否则宁可不派 —— 把告警派到相邻站点比不派更难收拾。
    """

    # 近似匹配的歧义保护：第一名领先第二名的幅度小于此值 → 判为歧义，不采用
    FUZZY_MIN_GAP = 0.03

    def __init__(self, fuzzy_enabled: bool = True,
                 fuzzy_threshold: float = 0.9) -> None:
        self._by_name: Dict[str, List[Dict[str, str]]] = {}
        self._by_norm: Dict[str, List[Dict[str, str]]] = {}
        self._fuzzy_enabled = bool(fuzzy_enabled)
        self._fuzzy_threshold = float(fuzzy_threshold)
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        api.ensure_login()
        status, hdrs, raw, body = api._http_request(
            "POST", SITE_SEARCH_API_PATH, headers_extra=_headers(),
            body=json.dumps({"filter": "", "start": 0, "length": 5000}))
        data = _json_or_none(body)
        if not isinstance(data, list):
            logger.warning("[Fiber] cmdb Site 返回非列表: %s", status)
            return
        for s in data:
            name = str(s.get("Name") or "").strip()
            sid = s.get("_id")
            if not name or sid in (None, ""):
                continue
            rec = {"id": str(sid), "name": name}
            self._by_name.setdefault(name.lower(), []).append(rec)
            norm = _norm_name(name)
            if norm:
                self._by_norm.setdefault(norm, []).append(rec)

    @staticmethod
    def _with_meta(hits: List[Dict[str, str]], matched_by: str, score: float,
                   query: str) -> Dict[str, str]:
        """取第一条并附上匹配方式，便于调用方标注「近似匹配」供人工复核。

        ⚠ 不能把这些元字段写回索引里的原始 dict，否则会被后续调用互相污染。
        """
        if len(hits) > 1:
            logger.warning("[Fiber] 站点名 %r 在 cmdb 有 %d 条同名记录，取第一条 %s",
                           query, len(hits), hits[0])
        rec = dict(hits[0])
        rec["matched_by"] = matched_by
        rec["score"] = round(float(score), 4)
        rec["query"] = query
        return rec

    def lookup(self, site_name: str) -> Optional[Dict[str, str]]:
        """按站点名取 cmdb 站点：精确 → 归一化精确 → 近似（可关）。

        返回 dict 含 `id` / `name` / `matched_by`(`exact`|`normalized`|`fuzzy`)
        / `score` / `query`。查不到返回 None。
        """
        self.load()
        name = str(site_name or "").strip()
        if not name:
            return None

        hits = self._by_name.get(name.lower())
        if hits:
            return self._with_meta(hits, "exact", 1.0, name)

        norm = _norm_name(name)
        if not norm:
            return None

        hits = self._by_norm.get(norm)
        if hits:
            return self._with_meta(hits, "normalized", 1.0, name)

        if not self._fuzzy_enabled:
            return None
        return self._fuzzy_lookup(name, norm)

    def _fuzzy_lookup(self, name: str, norm: str) -> Optional[Dict[str, str]]:
        """近似匹配兜底：**只接受「等长且仅元音互换」**的候选。

        实测动机（2026-10-27）：`6120HS_Peter_luogan_town_UPE80` 的 fiber 告警
        推出站名 `Peter luogan town`，cmdb 里写作 `Peter Luogon Town`（luogan /
        luogon 差一字母），精确查不到 → 该告警每轮记 N、永远派不出去。

        ⚠ 三重保护，缺一不可：
          1. 只收「等长 + 差异位全是元音」的候选（见 `_vowel_swap_only` 的实测
             数据：放宽到通用相似度会把 `Garplay`/`Gbarplay` 这类不同站点判成同一个）；
          2. 分期站点（`X` / `X2`）直接排除 —— 数字差异不是拼写差异；
          3. 最优候选必须唯一领先，否则判歧义、宁可不派。
        """
        scored: List[Tuple[float, Dict[str, str]]] = []
        for cand_norm, hits in self._by_norm.items():
            if _only_digit_suffix_diff(norm, cand_norm):
                logger.info("[Fiber] 近似匹配跳过分期站点 %r（查询 %r）：数字后缀不是拼写差异",
                            hits[0]["name"], name)
                continue
            if not _vowel_swap_only(norm, cand_norm):
                continue
            score = difflib.SequenceMatcher(None, norm, cand_norm).ratio()
            if score >= self._fuzzy_threshold:
                scored.append((score, hits[0]))
        if not scored:
            return None

        scored.sort(key=lambda x: x[0], reverse=True)
        top_score, top_hit = scored[0]
        if len(scored) > 1:
            second_score, second_hit = scored[1]
            if (second_hit["id"] != top_hit["id"]
                    and top_score - second_score < self.FUZZY_MIN_GAP):
                logger.warning(
                    "[Fiber] 站点名近似匹配有歧义，不采用：%r → %r(%.3f) / %r(%.3f)",
                    name, top_hit["name"], top_score, second_hit["name"], second_score)
                return None

        logger.warning("[Fiber] 站点名近似匹配：%r → %r（相似度 %.3f，请在 cmdb 核对命名）",
                       name, top_hit["name"], top_score)
        return self._with_meta([top_hit], "fuzzy", top_score, name)


def _pick(alarm: Dict[str, Any], *keys: str) -> str:
    """按多个候选键取第一个非空值（兼容原始 API 的 camelCase 与 DB 的 snake_case）。"""
    for k in keys:
        v = _s(_val(alarm.get(k)))
        if v and v not in ("--", "-", "empty", "None"):
            return v
    return ""


def resolve_site(alarm: Dict[str, Any], index: SiteIndex,
                 trace: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """给告警解析出 (site_id, site_name)，用于派单 payload。

    ⚠ 兼容两种行结构：
      * 原始实时告警 API（`fetch_active_alarms`）用 `site` / `sitename` / `mename`；
      * 本地 `realtime_alarm` 表用 `site_id` / `site_name` / `mename`。
    两者字段名不同，必须都认，否则「明明有站点却解析成空」（实测踩过）。

    优先级（实测据此才能建出 TT）：
      1. 告警自带站点 ID 是纯数字 + 站点名可用 → 直接用；
      2. 否则用站点名去 cmdb 查数字 ID；
      3. 否则从 ME 名解析站点名（`x_<SiteName>_UPEyy` 取中间段）再去 cmdb 查。
    解析不出时返回 ("", "")，调用方应跳过该告警（不派没有站点的单）。

    `trace` 传入 dict 时会被填入解析过程（`matched_by` / `score` / `query` /
    `tried`），供调用方写日志与结果 —— 近似匹配必须留痕给人复核。
    """
    site_id = _pick(alarm, "site_id", "site")
    site_name = _pick(alarm, "site_name", "sitename")

    # `site` 在原始 API 里可能既是数字 ID 也可能是 ME 名 —— 只有纯数字才算 ID
    numeric_id = site_id if site_id.isdigit() else ""

    # 1) 已是数字 ID + 站点名
    if numeric_id and site_name:
        if trace is not None:
            trace.update({"matched_by": "alarm_fields", "score": 1.0, "query": site_name})
        return numeric_id, site_name

    # 2) 站点名 → cmdb 查 ID
    candidates: List[str] = []
    if site_name:
        candidates.append(site_name)
    me_name = _pick(alarm, "mename", "me_name", "site")
    derived = site_name_from_me(me_name)
    if derived and derived not in candidates:
        candidates.append(derived)
    if trace is not None:
        trace["tried"] = list(candidates)

    for cand in candidates:
        hit = index.lookup(cand)
        if hit:
            if trace is not None:
                trace.update({"matched_by": hit.get("matched_by", "exact"),
                              "score": hit.get("score"),
                              "query": hit.get("query", cand)})
            return hit["id"], hit["name"]

    # 3) 有数字 ID 但无站点名 → cmdb 反查名字
    if numeric_id:
        index.load()
        for _name, hits in index._by_name.items():  # noqa: SLF001 内部索引只在本模块读
            for h in hits:
                if h["id"] == numeric_id:
                    return h["id"], h["name"]
        return numeric_id, numeric_id

    return "", ""


# ==========================================================
# 实时告警查询
# ==========================================================
def fetch_active_alarms() -> List[Dict[str, Any]]:
    """拉全量实时告警（未清除、maintainstatus=0），返回规范化 rows。

    不做告警码过滤 —— 让调用方同时能拿到目标码与关联码（99933）做关联判定。
    分页上限 500 条/页，最多 20 页（1 万条），足够覆盖当前量级（实测约 500）。
    """
    api.ensure_login()
    all_rows: List[Dict[str, Any]] = []
    page = 1
    page_size = 500
    while page <= 20:
        payload = {
            "timestamp": _iso_now(),
            "condition": {
                "alarmcodefiltermode": 0,
                "extensionconds": {"maintainstatus": {"filtertype": 1, "valuelist": ["0"]}},
                "sortinfo": {"sortdirection": 0, "sortfield": "servertime",
                             "combinesortinfos": []},
                "timezonetype": 0, "querymetype": 2, "id": -1, "visibles": [1],
            },
            "pagesize": page_size, "page": page,
            "queryid": "T" + uuid.uuid4().hex,
            "activeTabId": "fm-active_ALARM_MONITOR",
            "manual": False,
        }
        status, hdrs, raw, body = api._http_request(
            "POST", ACTIVE_ALARM_API_PATH, headers_extra=_headers(),
            body=json.dumps(payload))
        data = _json_or_none(body)
        if data is None:
            logger.warning("[Fiber] 实时告警返回非 JSON: %s", status)
            break
        rows = api.parse_response(data, label="FiberActive")
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        page += 1
    logger.info("[Fiber] 实时告警拉取 %d 条", len(all_rows))
    return all_rows


# ==========================================================
# 派单
# ==========================================================
def build_assign_payload(alarm: Dict[str, Any], group: Dict[str, Any],
                         site_id: str, site_name: str) -> Dict[str, Any]:
    """按 url_test.txt 的捕获结构组装派单 payload。

    与捕获的差异只有两处（Fiber 必需，见模块 docstring）：
      * `site` 用解析出的数字站点 ID，不是 ME 名；
      * 额外补 `sitename`，让 eFlow TT 引擎能绑定站点、真正建出 TT。
    """
    a = alarm
    occ_ms = _val(a.get("alarmraisedtime")) or _val(a.get("servertime")) or 0
    srv_ms = _val(a.get("servertime")) or occ_ms

    def _fmt(ms: Any) -> str:
        try:
            return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            return ""

    codename = str(_val(a.get("codename")) or _val(a.get("alarm_title")) or "").strip()
    alarmcode = _val(a.get("alarmcode"))
    data_row = {
        "alarmkey": _val(a.get("alarmkey")),
        "assignedtime": int(datetime.now().timestamp() * 1000),
        "id": _val(a.get("id")),
        "aid": str(_val(a.get("aid")) or ""),
        "alarmcode": f"{codename}({norm_code(alarmcode)})",
        "occurtime": _fmt(occ_ms),
        "site": site_id,
        "sitename": site_name,
        "perceivedseverity": _val(a.get("perceivedseverity")),
        "codename": codename,
        "me": _val(a.get("me")),
        "nbiid": str(_val(a.get("nbiid")) or ""),
        "position": _val(a.get("position")),
        "additionaltext": _val(a.get("additionaltext")) or "",
        "servertime": _fmt(srv_ms),
        "alarmtype": _val(a.get("alarmtype")),
        "plxTableDataIndex": 0,
        "plxTableDataKey": "key0",
    }
    return {
        "assignedType": 1,
        "alarmMsgType": 1,
        "data": [data_row],
        "assigneduser": api.USERNAME or "admin",
        "assigninformation": "",
        "groupId": group.get("id"),
        "autotag": "manual",
        "acceptType": group.get("acceptType", "FO"),
        "disableInput": codename,
    }


def assign_alarm(alarm: Dict[str, Any], group: Dict[str, Any],
                 site_id: str, site_name: str) -> Dict[str, Any]:
    """调用派单接口。返回 {"ok", "status", "message", "payload", "error"}。

    ⚠ 接口返回 `status:true` **不代表 TT 一定建出来**：Fiber 少传 site/sitename
    时同样返回 true 但 ttid 为空（见模块 docstring 的实测）。真正的成功判定由
    调用方回查 `ttid` 完成，本函数只如实报告接口回执。
    """
    payload = build_assign_payload(alarm, group, site_id, site_name)
    result: Dict[str, Any] = {"ok": False, "status": "", "message": "",
                              "payload": payload, "error": None}
    try:
        api.ensure_login()
        status, hdrs, raw, body = api._http_request(
            "POST", ASSIGN_API_PATH, headers_extra=_headers(),
            body=json.dumps(payload))
        result["status"] = str(status)
        data = _json_or_none(body) or {}
        result["message"] = str(data.get("message") or "")
        result["ok"] = bool(data.get("status")) and "200" in str(status)
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
        logger.exception("[Fiber] 派单接口异常")
    return result

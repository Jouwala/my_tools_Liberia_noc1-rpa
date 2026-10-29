# -*- coding: utf-8 -*-
"""eFlow 派单的**站点解析**部分（ME 名 → 站点名 → 数字站点 ID）。

## 为什么单独成模块（2026-10-29）

`eflow_assign_client.py` 一度 680 行，超过 AGENTS.md 第三节第 2 条的
「新增文件单个不超过 500 行」。站点解析与告警查询/派单是**两件不相干的事**
（前者只读 cmdb，后者打 eFlow 告警与派单接口），拆开更内聚。

## 站点解析的三档（**严格到宽松，只有前一档查不到才降级**）

1. `exact`       —— 大小写不敏感精确匹配；
2. `normalized`  —— 归一化后精确匹配（只差空格/下划线等分隔符）；
3. `fuzzy`       —— 归一化名相似度 ≥ 阈值（默认 0.9）。

⚠ 近似匹配必须带**歧义保护**：只有当最优候选唯一领先时才采用，
否则宁可不派 —— 把告警派到相邻站点比不派更难收拾。

## 实测教训：近似匹配只能收「等长 + 仅元音互换」

扫生产 cmdb 830 个站点得出的结论：通用相似度 ≥0.9 会把 `Garplay`/`Gbarplay`、
`Banwea`/`Gbanwea`、`Butuo`/`Buutuo`、`Sanniquillie 5`/`Sanniquillie 1`、
`Buchanan 3 AML`/`Buchanan AML` 这些**互不相同的站点**判成同一个 —— 那是**错派**。
加上「等长且差异位全是元音」这条硬约束后，830 个站点里**误判 0 对**，
同时仍覆盖目标案例 `luogan` → `luogon`（a↔o，等长）。

代价：漏字母/多字母/辅音打错的拼写差异不再兜底 —— 那些会如实记
「站点解析失败」等人工处理。**宁可漏派，不可错派。**
"""
import difflib
import logging
import json
from typing import Any, Dict, List, Optional, Tuple

from backend.services import eflow_api_client as api

logger = logging.getLogger("eflow_assign_site")

SITE_SEARCH_API_PATH = "/api/cmdb/v1/data/search/Site"


def _val(v: Any) -> Any:
    """eFlow 告警字段是 {value, displayname, ...} 对象；统一取 value。"""
    if isinstance(v, dict):
        return v.get("value")
    return v


def _s(val: Any) -> str:
    """转字符串并去空白；None → ''。"""
    return "" if val is None else str(val).strip()


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

    见模块 docstring 的实测数据 —— 放宽到通用相似度会造成真实错派。
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


def _pick(alarm: Dict[str, Any], *keys: str) -> str:
    """按多个候选键取第一个非空值（兼容原始 API 的 camelCase 与 DB 的 snake_case）。"""
    for k in keys:
        v = _s(_val(alarm.get(k)))
        if v and v not in ("--", "-", "empty", "None"):
            return v
    return ""


class SiteIndex:
    """cmdb Site 全量索引：按站点名（小写）→ [{id, name}] 快照。

    一次性拉全量（约 800+ 条），单轮任务内复用，避免对每个告警单独查一次。
    只在确有告警需要解析站点时才构建。
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
        from backend.services.eflow_assign.eflow_assign_client import _headers
        status, hdrs, raw, body = api._http_request(
            "POST", SITE_SEARCH_API_PATH, headers_extra=_headers(),
            body=json.dumps({"filter": "", "start": 0, "length": 5000}))
        from backend.services.eflow_assign.eflow_assign_client import _json_or_none
        data = _json_or_none(body)
        if not isinstance(data, list):
            logger.warning("[Assign] cmdb Site 返回非列表: %s", status)
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
            logger.warning("[Assign] 站点名 %r 在 cmdb 有 %d 条同名记录，取第一条 %s",
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

        三重保护，缺一不可：
          1. 只收「等长 + 差异位全是元音」的候选；
          2. 分期站点（`X` / `X2`）直接排除 —— 数字差异不是拼写差异；
          3. 最优候选必须唯一领先，否则判歧义、宁可不派。
        """
        scored: List[Tuple[float, Dict[str, str]]] = []
        for cand_norm, hits in self._by_norm.items():
            if _only_digit_suffix_diff(norm, cand_norm):
                logger.info("[Assign] 近似匹配跳过分期站点 %r（查询 %r）：数字后缀不是拼写差异",
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
                    "[Assign] 站点名近似匹配有歧义，不采用：%r → %r(%.3f) / %r(%.3f)",
                    name, top_hit["name"], top_score, second_hit["name"], second_score)
                return None

        logger.warning("[Assign] 站点名近似匹配：%r → %r（相似度 %.3f，请在 cmdb 核对命名）",
                       name, top_hit["name"], top_score)
        return self._with_meta([top_hit], "fuzzy", top_score, name)


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
        for hits in index._by_name.values():
            for h in hits:
                if h["id"] == numeric_id:
                    return h["id"], h["name"]
        return numeric_id, numeric_id

    return "", ""

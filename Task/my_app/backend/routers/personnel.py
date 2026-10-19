"""人员位置与人员工单 API（GIS 人员图层）。

**背景**：`/myapp/?page=gis` 需要在地图上显示现场工程师位置、点人看其 WO、
从人规划到站点的路线。项目原先没有任何「人员图层」端点，本模块提供它。

**数据来源与已知限制**（2026-10-16 实测 `db/app.db`）：

  1. 人员位置取自 `person.latitude/longitude` —— **136 人里只有 28 人有坐标**，
     且是**静态登记值，不是实时 GPS**（无时间戳、无轨迹）。故本端点只返回
     「已登记坐标」的人，前端必须注明「非实时位置」，否则会被误当实时定位。
  2. `person` 表由 `sync_from_eflow_api.py` 动态建表（非 `models/` 下的 ORM 类），
     故这里用 `get_raw_connection()` + 裸 SQL，与 `gis.py` 既有站点查询同一风格。
  3. 人员 ↔ WO **无外键**，按规范化姓名匹配（见 `services/person_name.py`，
     实测命中 96%）。同名/改名会漏配，这是已知局限。
  4. WO 自身**没有经纬度**，路线目标点只能用其**所属站点**的坐标。

**为什么单开一个 router 而不是塞进 `gis.py`**：`gis.py` 已 1891 行（接近
AGENTS.md 第三节 2 的 500 行/文件上限的精神），且人员逻辑与站点几何/边界计算
是两回事。这里沿用同一 `/api/gis` 前缀，前端 URL 不变。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query, HTTPException
from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names
from backend.services.person_name import normalize_person_name, split_multi_person
from backend.services.routing_service import plan_route
from backend.routers.gis import _resolve_window

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gis", tags=["gis-personnel"])

# WO 列表返回列（键名与前端 buildWOColumns 对齐，令其可直接复用列定义）。
# 2026-10-16 扩展：按用户要求补「常用信息」列 —— 见下方 _WO_COL_KEYS 的注释。
_WO_COLS = (
    "wo_no, tt_no, title, status, creator, created_time, last_modified_time, "
    "operation_step, ticket_severity, alarm_severity, ne_type, vendor, domain, "
    "alarm_occur_time, alarm_clear_time, fault_duration_time, sla_time, "
    "site_id, site_name, site_type"
)
# _WO_COLS 的字段顺序 —— 与上面 SELECT 一一对应（zip 还原 dict 时用）。
# 改 _WO_COLS 必须同步改这里，否则字段会错位（zip 不报错，只会静默串位）。
_WO_COL_KEYS = (
    "wo_no", "tt_no", "title", "status", "creator", "created_time",
    "last_modified_time", "operation_step", "ticket_severity", "alarm_severity",
    "ne_type", "vendor", "domain", "alarm_occur_time", "alarm_clear_time",
    "fault_duration_time", "sla_time", "site_id", "site_name", "site_type",
)
# 单次下钻的最大取样行数。必须**显著大于**界面单页最大量，否则会静默截断，
# 令「表格行数」少于「人员的 WO 计数」（AGENTS.md 第三节 1b）。
_WO_LIMIT = 2000
# 粗筛候选上限（按姓名首词 LIKE）。与 _WO_LIMIT 解耦：过滤在拉取之后进行，
# 若用结果上限当候选上限会漏掉窗口外的有效行（见 get_personnel_work_orders 注释）。
_CAND_LIMIT = 20000

# 人员表「有坐标」判定：非空且非 0（实测有 2 条的 0.0/0.0 会落在大西洋上）
_COORD_OK = (
    "latitude IS NOT NULL AND longitude IS NOT NULL "
    "AND CAST(latitude AS REAL) != 0 AND CAST(longitude AS REAL) != 0"
)


def _is_closed(status) -> bool:
    """WO 是否已关闭。**唯一判定处** —— `/personnel` 的计数与
    `/personnel/{key}/work-orders` 的过滤都必须调用它，否则两处口径会漂移，
    出现「人数统计说 129 单、点进去 352 行」这类不一致（实测踩过）。
    实测库中 status 取值含 Closed / Closed_Confirmed 等，故用前缀匹配而非等号。
    """
    return str(status or "").strip().lower().startswith("closed")


def _is_uncleared(alarm_clear_time, status) -> bool:
    """告警是否**尚未清除** —— 标签分子、弹窗默认口径的唯一判定处。

    口径（2026-10-16 经用户确认）：`eflow_wo.alarm_clear_time` 为空
    **且** status 未关闭。

    ⚠ 两个条件的顺序在数据上等价于「只看 alarm_clear_time 是否为空」——
    实测全表没有「status=Closed 且 alarm_clear_time 为空」的行，但保留
    status 判定是**防御性**的：将来若出现该组合，它是已闭环的单，
    不该再算作「未清除告警」。

    ⚠ **与 `_is_closed` 是两个不同的概念，不要互相替代**：
      - 未关闭（`not _is_closed`）：工单流程没走完；
      - 未清除（本函数）：告警本体还没被清除。
    常见的 `Wait For Confirm` 单往往是「告警已清除但流程待确认」——
    它**未关闭但不属于未清除**。故标签分子 ≤ 分母，符合直觉。

    实测量级（全部时间、全表）：未关闭且未清除的 WO 全球仅 **127 条**，
    且集中在少数人身上（Varfee Sarnor 27 / Festus Emmanuel 3 / Mark D. Paye 2，
    Patrick Monday 0、Emmanuel Egbe 0）。**大量人员分子会是 0，这是数据事实，
    不是 bug** —— 界面必须用「未清除」标签把这个含义写清楚，
    否则用户看到 `0/171` 会以为统计坏了。
    """
    if str(alarm_clear_time or "").strip():
        return False
    return not _is_closed(status)


def _mask_phone(raw) -> str:
    """电话脱敏。库里多数行已是 ``231****7417`` 形式，少数为明文（如 231770476985）。

    对已脱敏的原样返回；对明文只保留前 3 位与后 4 位，中间固定 4 个星号。
    非数字（含空）返回空串。**响应里绝不出现完整号码**（AGENTS.md 第四节 2）。
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    if "****" in s:
        return s
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) < 7:
        return "****"
    return f"{digits[:3]}****{digits[-4:]}"


def _fix_latlng(lat: float, lng: float):
    """修正明显写反的经纬度 —— 与 gis.py:510 的 `_fix_latlng` 同规则。

    利比里亚在 lat≈4-9 / lng≈-7~-12，故 lat<0 且 0<lng<10 即写反。
    此处刻意复制而非 import：那是 `gis.py` 的私有函数，跨模块 import 私有名
    会让耦合变脆；规则简单且稳定，复制成本低于建依赖。
    """
    if lat < 0 and 0 < lng < 10:
        return lng, lat
    return lat, lng


def _window_clause(time_start, time_end, days) -> tuple[str, list]:
    """WO 时间窗口过滤片段 → (sql_where, params)。

    **与 GIS 站点统计同口径**：同样按 `eflow_wo.alarm_occur_time` 半开区间过滤
    （`>= start AND < end_excl`），窗口解析复用 `gis.py::_resolve_window`
    （唯一实现，勿另写一套 —— 否则「地图站点统计」与「人员标签」两个数字会漂移，
    这正是 AGENTS.md 三.1b 禁止的）。

    2026-10-16 新增：用户指出人员标签数字未跟随页面「Time window」筛选。
    语义经确认：**打开时间（alarm_occur_time）落在窗口内** 是前提，
    「未关闭」状态在此之上再叠加。窗口为『全部时间』时返回空片段（不过滤）。
    """
    # 归一化：直接调用本模块端点（单测/脚本）时，未传的默认值仍是 Query 对象；
    # `days or 7` 对 Query 对象恒为真值、`int(Query)` 会抛 TypeError。
    # 统一在这里收敛，保证 HTTP 与直接调用两种路径口径一致。
    if not isinstance(days, int):
        days = None
    if not isinstance(time_start, str):
        time_start = None
    if not isinstance(time_end, str):
        time_end = None
    if days is None and not time_start and not time_end:
        return "", []                       # 全部时间 → 不过滤
    win_start, _win_end, win_end_excl = _resolve_window(time_start, time_end, days or 7)
    where = " AND alarm_occur_time >= ? AND alarm_occur_time < ?"
    return where, [win_start, win_end_excl]


def _load_wo_owner_index(conn, time_start=None, time_end=None, days=None) -> dict[str, dict[str, int]]:
    """一次扫描 eflow_wo，产出 ``{规范化姓名: {"uncleared": 未清除数, "open": 未关闭数, "total": 全部数}}``。

    比在人员列表里逐人查一次 SQL 少 N 次往返（人员 26 人 → 1 次扫描）。
    「未关闭」按 status 排除 Closed/Closed_... 口径；与其他 WO 统计口径一致处
    以 `eflow_wo.status` 实际取值为准（实测有 Closed / Closed_Confirmed 等）。
    「未清除」口径见 `_is_uncleared`。

    **为什么三个计数一起出**：界面标签要显示 ``未清除/未关闭``
    （2026-10-16 用户要求，原为 `WO:未关闭/总数`）—— 三个数必须来自
    **同一次扫描、同一套归属规则**，否则分子分母口径不一致，会出现
    「3/171 但点进去 5 行」这类对不上的问题（AGENTS.md 三.1b）。
    把 uncleared 与 open 放同一次扫描也保证了两者不会因窗口边界漂移。

    `time_start`/`time_end`/`days` 传 `None`（且 days 为 None）= 全部时间、不过滤；
    否则按 `_window_clause` 的口径过滤 alarm_occur_time。
    """
    where, params = _window_clause(time_start, time_end, days)
    index: dict[str, dict[str, int]] = {}
    rows = conn.execute(
        f"SELECT last_processer, current_handler, status, alarm_clear_time "
        f"FROM eflow_wo WHERE 1=1{where}",
        params,
    ).fetchall()
    for last_p, handler, status, clear_time in rows:
        # 一个人可能同时出现在 last_processer 和 current_handler，用集合去重，
        # 避免同一条 WO 被同一个人计两次。
        keys = _wo_person_keys(last_p, handler)
        closed = _is_closed(status)
        uncleared = _is_uncleared(clear_time, status)
        for k in keys:
            slot = index.setdefault(k, {"uncleared": 0, "open": 0, "total": 0})
            slot["total"] += 1
            if not closed:
                slot["open"] += 1
            if uncleared:
                slot["uncleared"] += 1
    return index


def _wo_person_keys(last_processer, current_handler) -> set[str]:
    """一条 WO 归属的所有人员（规范化姓名集合）。

    **唯一归属判定处** —— `/personnel` 的计数与 `/personnel/{key}/work-orders`
    的过滤都调用它。两边若各写一套，同一人会出现「计数 129、列表 352」的口径漂移
    （实测踩过，见模块头与 `_is_closed` 注释）。

    规则：
      - `last_processer` 取全部（逗号拆分，实测可能多人）；
      - `current_handler` **只取 `P:` 前缀**的个人名 —— `G:` 是群组池，
        挂到个人头上会把整个组的单算给一个人（字段语义见 eflow_qa.py:1197）。
    """
    keys = set(split_multi_person(last_processer))
    for part in str(current_handler or "").split(","):
        p = part.strip()
        if p[:2].lower() == "p:":
            k = normalize_person_name(p)
            if k:
                keys.add(k)
    return keys


@router.get("/personnel")
def get_personnel(
    time_start: str = Query(None, description="时间窗口开始 YYYY-MM-DD（与地图筛选同口径）"),
    time_end: str = Query(None, description="时间窗口结束 YYYY-MM-DD"),
    days: int = Query(None, ge=1, le=3650, description="时间窗口天数（与 time_start/end 二选一）"),
):
    """有登记坐标的人员列表（供 GIS 人员图层）。

    ⚠ 返回的是**静态登记坐标**，不是实时定位；只有 28/136 人有坐标。
    响应含 `total_with_coords` 与 `total_all`，前端据此说明覆盖率。

    **三个 WO 计数全部跟随时间窗口**（2026-10-16）：
    与 GIS 站点统计同口径，按 `eflow_wo.alarm_occur_time` 过滤。
    窗口为「全部时间」时前端不传任何时间参数 → 不过滤。

    **标签口径（2026-10-16 用户要求）**：`未清除告警/未关闭`
    —— 分子 `wo_count_uncleared`（见 `_is_uncleared`）、分母 `wo_count`
    （未关闭）。原来的 `未关闭/总数` 已废弃：总数为 0 时显示 `0/0`
    毫无信息量，而「未清除」才是现场真正要盯的数。
    `wo_count_total` 仍保留在响应里（历史调用方与排查用），但**界面不再使用**。
    """
    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))
        if "person" not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail="person 表不存在")

        wo_index = (_load_wo_owner_index(conn, time_start, time_end, days)
                    if "eflow_wo" in tables else {})

        rows = conn.execute(f"""
            SELECT name, latitude, longitude, phone, managed_regions, status
            FROM person
            WHERE {_COORD_OK}
            ORDER BY name
        """).fetchall()

        total_all = conn.execute("SELECT COUNT(*) FROM person").fetchone()[0] or 0
        conn.close()

    personnel = []
    seen_keys: set[str] = set()
    for name, lat_raw, lng_raw, phone, regions, status in rows:
        key = normalize_person_name(name)
        if not key or key in seen_keys:
            # 同名（规范化后）只保留一条：地图上同一点画两个图标没有意义，
            # 且会让「点人看 WO」出现重复入口。
            continue
        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
        except (TypeError, ValueError):
            continue
        lat, lng = _fix_latlng(lat, lng)
        seen_keys.add(key)
        slot = wo_index.get(key) or {}          # 有坐标但 0 单 → 空 dict → 计数为 0
        personnel.append({
            "name": str(name or "").strip(),      # 回显用原文
            "name_key": key,                       # 匹配用规范化
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "phone": _mask_phone(phone),
            "managed_regions": str(regions or ""),
            "status": str(status or ""),
            # 未关闭 WO 数（下钻**分母**；不看 only_uncleared 时的列表行数）
            "wo_count": slot.get("open", 0),
            # 未清除告警 WO 数（下钻**默认口径**的分子/行数）——
            # 与 /personnel/{key}/work-orders?only_uncleared=true 的行数必须相等
            "wo_count_uncleared": slot.get("uncleared", 0),
            # 全部 WO 数（含已关闭）—— 仅作参考，已不再用于标签显示
            "wo_count_total": slot.get("total", 0),
        })

    return {
        "personnel": personnel,
        "total_with_coords": len(personnel),
        "total_all": total_all,
        # 明确告知前端「这不是实时位置」，避免被当成 GPS。
        "location_is_realtime": False,
    }


@router.get("/personnel/{name_key}/work-orders")
def get_personnel_work_orders(
    name_key: str,
    include_closed: bool = Query(False, description="是否包含已关闭 WO；默认只列未关闭"),
    only_uncleared: bool = Query(True, description="只看未清除告警的 WO（弹窗默认）；false = 时间窗内全部未关闭"),
    limit: int = Query(_WO_LIMIT, ge=1, le=10000, description="最大取样行数"),
    time_start: str = Query(None, description="时间窗口开始 YYYY-MM-DD（与地图筛选同口径）"),
    time_end: str = Query(None, description="时间窗口结束 YYYY-MM-DD"),
    days: int = Query(None, ge=1, le=3650, description="时间窗口天数"),
):
    """某人员名下的 WO 列表（含站点坐标，供路线规划）。

    **两个层级，对应界面的两档**（2026-10-16 用户要求「弹窗默认显示告警未清除，
    点『更多』显示时间窗内未关闭」）：

    | `only_uncleared` | 含义 | 行数应等于 |
    | --- | --- | --- |
    | `true`（默认） | 时间窗口内、**未清除告警**的 WO | `/personnel` 的 `wo_count_uncleared` |
    | `false` | 时间窗口内、**未关闭**的全部 WO | `/personnel` 的 `wo_count` |

    下钻行数与对应计数必须相等（AGENTS.md 第三节 1b：下钻口径不得与概览漂移）
    —— 两档都走同一 `_wo_person_keys` 归属判定、同一 `_is_closed`/`_is_uncleared`
    判定、同一时间窗口，故不会漂移。

    需要看已关闭的历史单时传 `include_closed=true`；此时列表会多于计数，
    这是**显式**差异（响应含 `meta.include_closed` 供前端说明），不是口径不一致。

    匹配规则：
      - `eflow_wo.last_processer` 规范化后命中；
      - `eflow_wo.current_handler` 中 `P:` 前缀的个人名命中（`G:` 群组不计）。

    站点坐标通过 `eflow_wo.site_id` CAST 成文本后 JOIN `master_site_db`
    （PG 下 site_id 是 integer，直接比较会抛 UndefinedFunction —— 见
    `gis.py:607` `_site_id_match` 的说明）。
    """
    key = normalize_person_name(name_key)
    if not key:
        raise HTTPException(status_code=400, detail="人员标识为空")

    # FastAPI 只在**HTTP 请求**时才把 Query 默认值解析成真实值；若本函数被
    # 直接调用（单测 / 脚本 / 未来被别的 service 复用），`limit` / `include_closed`
    # 仍是 Query 对象 —— 前者 `int >= Query` 抛 TypeError，后者**恒为真值**导致
    # 「默认只列未关闭」的过滤被整段跳过（实测吐回 126 行含 108 行已关闭）。
    # 显式归一化，让两种调用方式行为一致，也便于脱离 HTTP 做单测。
    if not isinstance(limit, int):
        limit = _WO_LIMIT
    limit = max(1, min(limit, 10000))
    if not isinstance(include_closed, bool):
        include_closed = False
    # 同上的陷阱：Query 对象恒为真值。这个默认值就是 True，
    # 若直接调用时被 Query 对象顶替，行为恰好一致，但显式归一化以免日后
    # 把默认值改成 False 时静默失效。
    if not isinstance(only_uncleared, bool):
        only_uncleared = True

    # 时间窗口片段（与 /personnel 计数同口径）。直接调用时 days 可能是 Query 对象。
    win_where, win_params = _window_clause(
        time_start, time_end, days if isinstance(days, int) else None)

    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))
        if "eflow_wo" not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail="eflow_wo 表不存在")

        # 姓名匹配必须下推到 SQL 之外做（清洗规则无法用 SQL 表达），
        # 故先按粗筛（LIKE 姓名的首词）收敛候选，再在 Python 侧用同一套
        # 规范化规则精确判定。避免把 1.5 万行全拉进内存。
        #
        # ⚠ 候选窗口**不能**用 `limit+1`：过滤（姓名精确匹配 + 关闭态）发生在
        # 拉取之后，若窗口内恰好大多是已关闭单，窗口外仍未关闭的行就会被漏掉，
        # 且 truncated 判定失真。故候选窗口取「粗筛上限」`_CAND_LIMIT`，
        # 与最终返回的 limit 解耦 —— 粗筛按姓名首词已足够收敛（单人工单量级几百）。
        first_token = key.split(" ")[0] if key.split(" ") else key
        cand = conn.execute(f"""
            SELECT {_WO_COLS}, last_processer, current_handler
            FROM eflow_wo
            WHERE ((last_processer IS NOT NULL AND LOWER(last_processer) LIKE ?)
               OR (current_handler IS NOT NULL AND LOWER(current_handler) LIKE ?)){win_where}
            ORDER BY alarm_occur_time DESC
            LIMIT ?
        """, [f"%{first_token}%", f"%{first_token}%", *win_params, _CAND_LIMIT]).fetchall()

        # 站点坐标索引：一次取回所有站点，避免逐行查
        site_meta: dict[str, dict] = {}
        if "master_site_db" in tables:
            for sid, sname, region, lat, lng in conn.execute(
                "SELECT site_id, site_name, region, latitude, longitude FROM master_site_db"
            ).fetchall():
                site_meta[str(sid)] = {"site_name": sname, "region": region,
                                       "lat": lat, "lng": lng}
        conn.close()

    wo_rows = []
    truncated = False
    # SELECT 的顺序 = _WO_COL_KEYS 后再追加 last_processer/current_handler
    row_keys = _WO_COL_KEYS + ("last_processer", "current_handler")
    for row in cand:
        d = dict(zip(row_keys, row))
        # 精确归属判定（与 /personnel 的计数同一函数）
        if key not in _wo_person_keys(d["last_processer"], d["current_handler"]):
            continue
        # 默认排除已关闭 —— 与 /personnel 的 wo_count / wo_count_uncleared 同口径
        # （_is_uncleared 自身也判 status，但这里先短路掉已关闭单，
        # 否则 include_closed=false 时仍会走到下面的未清除判定）
        if not include_closed and _is_closed(d["status"]):
            continue
        # 弹窗默认档：只看未清除告警的 WO —— 与 wo_count_uncleared 同口径
        if only_uncleared and not _is_uncleared(d["alarm_clear_time"], d["status"]):
            continue
        if len(wo_rows) >= limit:
            truncated = True
            break

        # 补站点坐标（WO 本身无经纬度，路线目标点 = 所属站点坐标）
        sid = str(d.get("site_id") or "")
        meta = site_meta.get(sid, {})
        lat = lng = None
        if meta.get("lat") is not None and meta.get("lng") is not None:
            try:
                lat, lng = _fix_latlng(float(meta["lat"]), float(meta["lng"]))
                lat, lng = round(lat, 6), round(lng, 6)
            except (TypeError, ValueError):
                lat = lng = None

        wo_rows.append({
            "wo_no": d["wo_no"], "tt_no": d["tt_no"], "title": d["title"],
            "status": d["status"], "creator": d["creator"],
            "created_time": d["created_time"],
            "last_modified_time": d["last_modified_time"],
            "operation_step": d["operation_step"],
            "ticket_severity": d["ticket_severity"],
            "alarm_severity": d["alarm_severity"],
            "ne_type": d["ne_type"], "vendor": d["vendor"],
            # 「传输类型」用 domain（TRM_MW/TRM_IPRAN/TRM_DWDM… = 传输域；
            # 另有 RAN/POWER 等非传输值，原样下发，由前端照实显示）
            "domain": d["domain"],
            "alarm_occur_time": d["alarm_occur_time"],
            "alarm_clear_time": d["alarm_clear_time"],
            "fault_duration_time": d["fault_duration_time"],
            "sla_time": d["sla_time"],
            "site_id": sid,
            "site_name": str(d.get("site_name") or meta.get("site_name") or ""),
            "site_type": d["site_type"],
            "region": str(meta.get("region") or ""),
            # 路线端点；为 None 表示该 WO 的站点无坐标，前端禁用「规划路线」
            "lat": lat, "lng": lng,
        })

    return {
        "name_key": key,
        "wo_list": wo_rows,
        "wo_count": len(wo_rows),
        # 显式暴露截断与本次档位（AGENTS.md 第三节 1b 铁律：不得静默截断）
        "meta": {
            "truncated": truncated,
            "limit": limit,
            "only_uncleared": only_uncleared,
            "include_closed": include_closed,
        },
    }


@router.get("/personnel/{name_key}/alert-sites")
def get_personnel_alert_sites(
    name_key: str,
    time_start: str = Query(None, description="时间窗口开始 YYYY-MM-DD（与地图筛选同口径）"),
    time_end: str = Query(None, description="时间窗口结束 YYYY-MM-DD"),
    days: int = Query(None, ge=1, le=3650, description="时间窗口天数"),
):
    """该人员「未关闭 WO **且** 站点当前有实时告警」的站点集合（供悬停连线）。

    2026-10-16 新增，用户需求：「鼠标悬停人员时显示其未关闭告警站点的所有连线，
    点击后消失」。经确认，「告警站点」= **该人员有未关闭 WO 的站点中，当前有
    实时告警的那些**（两个条件取交集，不是只看告警、也不是只看 WO）。

    口径：
      - WO 侧与 `/personnel/{key}/work-orders` 完全一致（同一 `_wo_person_keys`
        归属判定 + 同一 `_is_closed` 关闭态判定 + 同一时间窗口），只取**未关闭**；
      - 告警侧取 `realtime_alarm`（当前活跃告警快照，每 30 分钟整表重建）。
        只看**是否存在**该站点的活跃告警，不展开告警明细。

    返回每个站点的坐标 + 该人员在此站的未关闭 WO 数，前端据此画人→站连线。
    站点无坐标的行会被剔除（画不出线），并在 `skipped_no_coord` 里计数，
    不静默丢（AGENTS.md 三.6 / 三.1b 的同类要求）。
    """
    key = normalize_person_name(name_key)
    if not key:
        raise HTTPException(status_code=400, detail="人员标识为空")

    win_where, win_params = _window_clause(
        time_start, time_end, days if isinstance(days, int) else None)

    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))
        if "eflow_wo" not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail="eflow_wo 表不存在")

        first_token = key.split(" ")[0] if key.split(" ") else key
        cand = conn.execute(f"""
            SELECT site_id, last_processer, current_handler, status
            FROM eflow_wo
            WHERE ((last_processer IS NOT NULL AND LOWER(last_processer) LIKE ?)
               OR (current_handler IS NOT NULL AND LOWER(current_handler) LIKE ?)){win_where}
            LIMIT ?
        """, [f"%{first_token}%", f"%{first_token}%", *win_params, _CAND_LIMIT]).fetchall()

        # 当前有活跃告警的站点集合（一次取回，不逐站查）
        alarm_sites: set[str] = set()
        if "realtime_alarm" in tables:
            for (sid,) in conn.execute(
                "SELECT DISTINCT CAST(site_id AS TEXT) FROM realtime_alarm "
                "WHERE site_id IS NOT NULL"
            ).fetchall():
                alarm_sites.add(str(sid))

        # 站点坐标/名称索引
        site_meta: dict[str, dict] = {}
        if "master_site_db" in tables:
            for sid, sname, region, lat, lng in conn.execute(
                "SELECT site_id, site_name, region, latitude, longitude FROM master_site_db"
            ).fetchall():
                site_meta[str(sid)] = {"site_name": sname, "region": region,
                                       "lat": lat, "lng": lng}
        conn.close()

    # 该人员在每个站点的未关闭 WO 数（站点 → 计数）
    site_open: dict[str, int] = {}
    for sid_raw, last_p, handler, status in cand:
        if key not in _wo_person_keys(last_p, handler):
            continue
        if _is_closed(status):
            continue
        sid = str(sid_raw or "")
        if sid:
            site_open[sid] = site_open.get(sid, 0) + 1

    out_sites = []
    skipped_no_coord = 0
    for sid, open_cnt in site_open.items():
        if sid not in alarm_sites:
            continue                      # 交集：站点须有活跃告警
        meta = site_meta.get(sid, {})
        lat = meta.get("lat")
        lng = meta.get("lng")
        if lat is None or lng is None:
            skipped_no_coord += 1
            continue
        try:
            flat, flng = _fix_latlng(float(lat), float(lng))
        except (TypeError, ValueError):
            skipped_no_coord += 1
            continue
        out_sites.append({
            "site_id": sid,
            "site_name": str(meta.get("site_name") or ""),
            "region": str(meta.get("region") or ""),
            "lat": round(flat, 6),
            "lng": round(flng, 6),
            # 该人员在此站的未关闭 WO 数（连线粗细可据此变化）
            "open_wo": open_cnt,
        })

    return {
        "name_key": key,
        "sites": out_sites,
        "site_count": len(out_sites),
        # 有未关闭 WO 且有告警、但站点缺坐标画不出线的数量（不静默丢）
        "skipped_no_coord": skipped_no_coord,
        "meta": {"alarm_sites_total": len(alarm_sites)},
    }


# =====================================================================
# 人员位置地图（?page=person）专用端点（2026-10-19 新增）
#
# 与上面三个「GIS 人员图层」端点共用同一套归属/关闭/未清除判定，
# 只是**聚合粒度不同**：
#   · /personnel          —— 一个人一行的标签计数（图上打点用）
#   · /managed-sites      —— 一个人 ↔ 其 WO 涉及过的站点（本条下面第 1 个）
#   · /stats              —— 全量人员按 WO/TT 聚合，供页面统计图（第 2 个）
#
# ⚠️ **站点口径**（2026-10-19 经用户确认）：取 `eflow_wo.site_id` 去重，
#   即「该人员实际处理过工单的站点」，**不用** `person.managed_regions`。
#   实测原因是 managed_regions 只是县名文本、且 26 个有坐标的人里 5 人把它
#   写成全部 15 县（824 站全包）、9 人只有 Montserrado（353 站）——
#   按区域画会变成「半个国家的人都是同一片」。managed_regions 只在界面上
#   作为文本展示，不上地图。
# =====================================================================

def _people_with_coords(conn) -> list[tuple]:
    """有登记坐标的人员行：(name, name_key, lat, lng, phone, regions, status)。

    与 `/personnel` 的筛选条件**完全一致**（`_COORD_OK` + 规范化去重），
    保证本页与 GIS 人员图层的「有坐标人数」对得上（AGENTS.md 三.1b）。
    """
    rows = conn.execute(f"""
        SELECT name, latitude, longitude, phone, managed_regions, status
        FROM person
        WHERE {_COORD_OK}
        ORDER BY name
    """).fetchall()
    out = []
    seen: set[str] = set()
    for name, lat_raw, lng_raw, phone, regions, status in rows:
        key = normalize_person_name(name)
        if not key or key in seen:
            continue
        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
        except (TypeError, ValueError):
            continue
        lat, lng = _fix_latlng(lat, lng)
        seen.add(key)
        out.append((str(name or "").strip(), key, lat, lng,
                    _mask_phone(phone), str(regions or ""), str(status or "")))
    return out


def _site_meta_index(conn, tables: set[str]) -> dict[str, dict]:
    """站点主数据索引（含县名 province_county，供页面按县展示）。"""
    index: dict[str, dict] = {}
    if "master_site_db" not in tables:
        return index
    for sid, sname, region, county, lat, lng in conn.execute(
        "SELECT site_id, site_name, region, province_county, latitude, longitude "
        "FROM master_site_db"
    ).fetchall():
        index[str(sid)] = {
            "site_name": str(sname or ""),
            "region": str(region or ""),
            # province_county 才是「县」；region 只有 Montserrado/North East/South West
            # 三个大区，与 person.managed_regions 的县名不是同一套编码（实测）。
            "county": str(county or ""),
            "lat": lat, "lng": lng,
        }
    return index


@router.get("/sites/search")
def search_sites(
    q: str = Query("", description="关键字：站点名或站点 ID 的子串（不区分大小写）"),
    limit: int = Query(20, ge=1, le=100, description="最多返回条数"),
):
    """按名称/ID 搜索**全部**站点（供人员位置地图的地图搜索框）。

    **为什么不复用 `/personnel/{key}/managed-sites`**：那个只返回「某个人
    WO 涉及过的站点」，而地图搜索要能找**任意**站点（用户 2026-10-19 确认
    「两者都要（分场景）」：有选中人员时优先其站点，否则搜全量）。

    口径与 `/managed-sites` 保持一致的地方：坐标必须有效（`_COORD_OK` 同款判定），
    写反的经纬度用同一 `_fix_latlng` 修正 —— 保证搜索结果能被画到地图上。

    `owner_count` 是该站点在**未关闭 WO** 上的负责人数（去重），供前端提示
    「该站点有无关联人员」。判定复用 `_wo_person_keys` / `_is_closed`。
    **不带时间窗口**：这是一个「找地方」的工具，不是统计口径，限制窗口会让
    用户搜不到明明存在的站点。
    """
    if not isinstance(limit, int):
        limit = 20
    limit = max(1, min(limit, 100))
    kw = str(q or "").strip()
    # 空关键字不返回任何结果 —— 避免打开搜索框就吐 824 行
    if not kw:
        return {"sites": [], "total": 0}

    like = f"%{kw.lower()}%"
    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))
        if "master_site_db" not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail="master_site_db 表不存在")

        rows = conn.execute(
            "SELECT CAST(site_id AS TEXT), site_name, region, province_county, "
            "latitude, longitude FROM master_site_db "
            "WHERE latitude IS NOT NULL AND longitude IS NOT NULL "
            "AND CAST(latitude AS REAL) != 0 AND CAST(longitude AS REAL) != 0 "
            "AND (LOWER(site_name) LIKE ? OR LOWER(CAST(site_id AS TEXT)) LIKE ?) "
            "ORDER BY site_name LIMIT ?",
            [like, like, limit],
        ).fetchall()

        # 站点 → 未关闭 WO 的负责人（只为本次命中的站点算，不扫全表）。
        # 同时返回**人名键**（不仅是计数）—— 前端选中站点后要据此选中负责人
        # （用户 2026-10-19：「定位并选中负责人」），只给计数做不到这件事。
        hit_ids = [str(r[0]) for r in rows]
        owner_cnt: dict[str, set[str]] = {}
        if hit_ids and "eflow_wo" in tables:
            marks = ",".join("?" * len(hit_ids))
            wo_rows = conn.execute(
                f"SELECT CAST(site_id AS TEXT), last_processer, current_handler, status "
                f"FROM eflow_wo WHERE CAST(site_id AS TEXT) IN ({marks})",
                hit_ids,
            ).fetchall()
            for sid, last_p, handler, status in wo_rows:
                if _is_closed(status):
                    continue
                owner_cnt.setdefault(str(sid or ""), set()).update(
                    _wo_person_keys(last_p, handler))

        # 有坐标的人员键集合 —— 只有这些人能在图上被选中。
        # 负责人若没有坐标，前端选不中（地图上没有他的针），故一并告知。
        people_keys = {p[1] for p in _people_with_coords(conn)}
        conn.close()

    sites = []
    for sid, sname, region, county, lat, lng in rows:
        try:
            flat, flng = _fix_latlng(float(lat), float(lng))
        except (TypeError, ValueError):
            continue
        sid_s = str(sid)
        owners = sorted(owner_cnt.get(sid_s) or ())
        sites.append({
            "site_id": sid_s,
            "site_name": str(sname or ""),
            "region": str(region or ""),
            "county": str(county or ""),
            "lat": round(flat, 6),
            "lng": round(flng, 6),
            # 负责人总数（含无坐标者，供提示「有 N 位负责人」）
            "owner_count": len(owners),
            # 其中**有坐标、能在图上被选中**的负责人键。前端选站点后用第一个
            # 来选中负责人；空数组 = 该站点有 WO 但负责人均无坐标（或无人负责）。
            # 只下发键，不下发完整人员信息 —— 需要名单走 /personnel。
            "owner_keys": [k for k in owners if k in people_keys],
        })
    return {"sites": sites, "total": len(sites), "query": kw}


@router.get("/personnel/{name_key}/managed-sites")
def get_personnel_managed_sites(
    name_key: str,
    time_start: str = Query(None, description="时间窗口开始 YYYY-MM-DD（与页面 30 天窗口同口径）"),
    time_end: str = Query(None, description="时间窗口结束 YYYY-MM-DD"),
    days: int = Query(None, ge=1, le=3650, description="时间窗口天数"),
):
    """某人员 WO 涉及过的全部站点（供人员位置地图画站点层与连线）。

    每个站点返回：
      - 坐标（无坐标的站点会被剔除，数量记在 `skipped_no_coord`，不静默丢）；
      - `wo_count`     —— 该人员在窗口内此站的**未关闭** WO 数；
      - `uncleared`    —— 其中**未清除告警**的 WO 数；
      - `has_alarm`    —— 该站点当前是否有实时告警（`realtime_alarm` 快照）。

    口径与 `/personnel` 的计数同源：同一 `_wo_person_keys` 归属判定、
    同一 `_is_closed` / `_is_uncleared` 判定、同一 `_window_clause` 窗口。
    """
    key = normalize_person_name(name_key)
    if not key:
        raise HTTPException(status_code=400, detail="人员标识为空")

    win_where, win_params = _window_clause(
        time_start, time_end, days if isinstance(days, int) else None)

    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))
        if "eflow_wo" not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail="eflow_wo 表不存在")

        # 粗筛与 work-orders 端点同一策略：按姓名首词 LIKE 收敛候选，
        # 再在 Python 侧精确判定（清洗规则无法下推 SQL）。
        first_token = key.split(" ")[0] if key.split(" ") else key
        cand = conn.execute(f"""
            SELECT site_id, last_processer, current_handler, status, alarm_clear_time
            FROM eflow_wo
            WHERE ((last_processer IS NOT NULL AND LOWER(last_processer) LIKE ?)
               OR (current_handler IS NOT NULL AND LOWER(current_handler) LIKE ?)){win_where}
            LIMIT ?
        """, [f"%{first_token}%", f"%{first_token}%", *win_params, _CAND_LIMIT]).fetchall()

        alarm_sites: set[str] = set()
        if "realtime_alarm" in tables:
            for (sid,) in conn.execute(
                "SELECT DISTINCT CAST(site_id AS TEXT) FROM realtime_alarm "
                "WHERE site_id IS NOT NULL"
            ).fetchall():
                alarm_sites.add(str(sid))

        site_meta = _site_meta_index(conn, tables)
        conn.close()

    # 站点 → {open, uncleared}（**只计未关闭**：已关闭的历史单不构成「当前负责」）
    per_site: dict[str, dict[str, int]] = {}
    for sid_raw, last_p, handler, status, clear_time in cand:
        if key not in _wo_person_keys(last_p, handler):
            continue
        if _is_closed(status):
            continue
        sid = str(sid_raw or "")
        if not sid:
            continue
        slot = per_site.setdefault(sid, {"open": 0, "uncleared": 0})
        slot["open"] += 1
        if _is_uncleared(clear_time, status):
            slot["uncleared"] += 1

    sites = []
    skipped_no_coord = 0
    for sid, cnt in per_site.items():
        meta = site_meta.get(sid, {})
        lat, lng = meta.get("lat"), meta.get("lng")
        if lat is None or lng is None:
            skipped_no_coord += 1
            continue
        try:
            flat, flng = _fix_latlng(float(lat), float(lng))
        except (TypeError, ValueError):
            skipped_no_coord += 1
            continue
        sites.append({
            "site_id": sid,
            "site_name": meta.get("site_name", ""),
            "region": meta.get("region", ""),
            "county": meta.get("county", ""),
            "lat": round(flat, 6),
            "lng": round(flng, 6),
            "wo_count": cnt["open"],
            "uncleared": cnt["uncleared"],
            "has_alarm": sid in alarm_sites,
        })
    # 告警站在前、未清除多的在前，便于地图图例与列表阅读
    sites.sort(key=lambda s: (not s["has_alarm"], -s["uncleared"], -s["wo_count"], s["site_id"]))

    return {
        "name_key": key,
        "sites": sites,
        "site_count": len(sites),
        "alarm_site_count": sum(1 for s in sites if s["has_alarm"]),
        "uncleared_total": sum(s["uncleared"] for s in sites),
        "open_total": sum(s["wo_count"] for s in sites),
        # 有 WO 但站点缺坐标、画不出来的数量（不静默丢）
        "skipped_no_coord": skipped_no_coord,
    }


# 按状态归一化到两个桶（避免把 Closed / Closed_Confirmed / Closed-Reject 拆成多类）。
# 与 `_is_closed` 的口径一致：closed = 状态以 closed 开头。
def _status_class(status) -> str:
    return "closed" if _is_closed(status) else "open"


@router.get("/personnel/stats")
def get_personnel_stats(
    time_start: str = Query(None, description="时间窗口开始 YYYY-MM-DD"),
    time_end: str = Query(None, description="时间窗口结束 YYYY-MM-DD"),
    days: int = Query(None, ge=1, le=3650, description="时间窗口天数"),
    top: int = Query(20, ge=1, le=100, description="按人员排行返回的条数"),
):
    """全量人员按 WO/TT 的聚合统计（供人员位置地图的统计区）。

    **一次扫描算完全部人的数字**，避免前端对 26 人各打一次接口。
    返回四块：
      - `by_person`：
          name / name_key / has_coords / open / closed / total /
          uncleared / tt_open / tt_closed / tt_total / counties
      - `by_county`：{县: {open, closed, total}} —— 以 WO 的站点��在县归类；
      - `by_status`：{open, closed} —— 全量合计；
      - `coverage`：有坐标人数 / 全部人数（页面 KPI 与说明横幅用）。
    """
    win_where, win_params = _window_clause(
        time_start, time_end, days if isinstance(days, int) else None)

    # 与 work-orders 端点同样的陷阱：直接调用时 top 仍是 Query 对象，切片会抛
    # TypeError。显式归一化，保证 HTTP 与直接调用两种路径一致。
    if not isinstance(top, int):
        top = 20
    top = max(1, min(top, 100))

    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))
        if "eflow_wo" not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail="eflow_wo 表不存在")

        people = _people_with_coords(conn)
        total_all = conn.execute("SELECT COUNT(*) FROM person").fetchone()[0] or 0
        site_meta = _site_meta_index(conn, tables)

        # ---- WO 侧：一次扫描，按人聚合 ----
        per_person: dict[str, dict] = {}
        county_agg: dict[str, dict[str, int]] = {}
        by_status = {"open": 0, "closed": 0}
        rows = conn.execute(
            f"SELECT site_id, last_processer, current_handler, status, alarm_clear_time, tt_no "
            f"FROM eflow_wo WHERE 1=1{win_where}",
            win_params,
        ).fetchall()
        for sid_raw, last_p, handler, status, clear_time, tt_no in rows:
            cls = _status_class(status)
            by_status[cls] += 1
            county = (site_meta.get(str(sid_raw or "")) or {}).get("county", "")
            if county:
                slot = county_agg.setdefault(county, {"open": 0, "closed": 0, "total": 0})
                slot[cls] += 1
                slot["total"] += 1
            for k in _wo_person_keys(last_p, handler):
                p = per_person.setdefault(k, {
                    "open": 0, "closed": 0, "total": 0, "uncleared": 0,
                    "tt_open": 0, "tt_closed": 0, "tt_total": 0, "counties": set(),
                    # 未关闭 WO 涉及过的站点集合（去重）。供地图徽标显示「负责站点数」，
                    # 与 `/managed-sites` 返回的 `site_count` 同口径（那里也只计未关闭）。
                    "sites": set(),
                })
                p[cls] += 1
                p["total"] += 1
                if cls == "open":
                    sid = str(sid_raw or "")
                    if sid:
                        p["sites"].add(sid)
                if _is_uncleared(clear_time, status):
                    p["uncleared"] += 1
                # TT 维度：该 WO 带了 tt_no 才算一条 TT（同一 TT 可能有多条 WO，
                # 这里按**行**计，语义是「涉及该 TT 的 WO 行数」——与业务口径
                # 「按单量看工作量」一致，不是独立去重计数。前端注释同样说明。）
                if str(tt_no or "").strip():
                    p[f"tt_{cls}"] += 1
                    p["tt_total"] += 1
                if county:
                    p["counties"].add(county)
        conn.close()

    # 同上：元组顺序 (name, name_key, lat, ...)。键必须取 name_key。
    people_index = {key: (name, lat, lng, regions)
                    for (name, key, lat, lng, _ph, regions, _st) in people}
    by_person = []
    # ⚠️ 元组顺序是 (name, name_key, lat, ...) —— 见 `_people_with_coords` 的
    # append 与文档字符串。这里**必须**先解 name 再解 key：首版写成
    # `for k, name, ...` 时两者互换，`per_person.get(k)` 永远拿原始姓名去查
    # 规范化后的键，于是 26 个有坐标的人的统计**全是 0**（实测踩过，
    # 而表格里 name_key 也变成原始姓名，两者的错误互相掩盖）。
    for name, k, lat, lng, phone, regions, status in people:
        p = per_person.get(k) or {}
        by_person.append({
            "name": name,
            "name_key": k,
            "has_coords": True,
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "phone": phone,
            "managed_regions": regions,
            "open": p.get("open", 0),
            "closed": p.get("closed", 0),
            "total": p.get("total", 0),
            "uncleared": p.get("uncleared", 0),
            "tt_open": p.get("tt_open", 0),
            "tt_closed": p.get("tt_closed", 0),
            "tt_total": p.get("tt_total", 0),
            # 县名列表（由 WO 站点反推），供表格展示；不是 managed_regions
            "counties": sorted(p.get("counties") or []),
            # 未关闭 WO 涉及的站点数（去重）——地图徽标显示；与 /managed-sites 的
            # site_count 同口径（那边同样只计未关闭 WO 的站点）。
            "site_count": len(p.get("sites") or ()),
        })
    # 没有坐标但名下有 WO 的人也列出来 —— 否则统计总和对不上（页面会标注「无坐标」）
    for k, p in per_person.items():
        if k in people_index:
            continue
        by_person.append({
            "name": k, "name_key": k, "has_coords": False,
            "lat": None, "lng": None, "phone": "", "managed_regions": "",
            "open": p["open"], "closed": p["closed"], "total": p["total"],
            "uncleared": p["uncleared"],
            "tt_open": p["tt_open"], "tt_closed": p["tt_closed"],
            "tt_total": p["tt_total"],
            "counties": sorted(p["counties"]),
            "site_count": len(p.get("sites") or ()),
        })

    # 排行按「未清除 → 未关闭」降序，与页面表格默认排序一致
    ranked = sorted(by_person, key=lambda r: (-r["uncleared"], -r["open"], r["name"]))
    return {
        "by_person": ranked,
        "top_person": ranked[:top],
        "by_county": county_agg,
        "by_status": by_status,
        "coverage": {
            "with_coords": len(people),
            "total_all": total_all,
            "location_is_realtime": False,
        },
        "range": {
            "days": days if isinstance(days, int) else None,
            "time_start": time_start if isinstance(time_start, str) else None,
            "time_end": time_end if isinstance(time_end, str) else None,
        },
    }


@router.get("/route")
def get_route(
    from_lat: float = Query(..., description="起点纬度"),
    from_lng: float = Query(..., description="起点经度"),
    to_lat: float = Query(..., description="终点纬度"),
    to_lng: float = Query(..., description="终点经度"),
):
    """路线规划：人员位置 → 站点。OSRM 不可用时自动降级为直线（见 routing_service）。

    ⚠ 入参按「不可信输入」校验（AGENTS.md 第三节 4）：经纬度必须落在合法范围，
    否则直接 400，不把脏值透传给 OSRM 或画到地图上。
    """
    for name, v in (("from_lat", from_lat), ("to_lat", to_lat)):
        if not (-90 <= v <= 90):
            raise HTTPException(status_code=400, detail=f"{name} 超出纬度范围 [-90,90]")
    for name, v in (("from_lng", from_lng), ("to_lng", to_lng)):
        if not (-180 <= v <= 180):
            raise HTTPException(status_code=400, detail=f"{name} 超出经度范围 [-180,180]")

    return plan_route(from_lat, from_lng, to_lat, to_lng)

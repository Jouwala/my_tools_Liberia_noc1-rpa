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
    """一次扫描 eflow_wo，产出 ``{规范化姓名: {"open": 未关闭数, "total": 全部数}}``。

    比在人员列表里逐人查一次 SQL 少 N 次往返（人员 26 人 → 1 次扫描）。
    「未关闭」按 status 排除 Closed/Closed_... 口径；与其他 WO 统计口径一致处
    以 `eflow_wo.status` 实际取值为准（实测有 Closed / Closed_Confirmed 等）。

    **为什么两个计数一起出**：界面标签要显示 ``WO:11/20``（未关闭/总数）——
    两个数必须来自**同一次扫描、同一套归属规则**，否则分子分母口径不一致，
    会出现「11/20 但点进去 15 行」这类对不上的问题（AGENTS.md 三.1b）。

    `time_start`/`time_end`/`days` 传 `None`（且 days 为 None）= 全部时间、不过滤；
    否则按 `_window_clause` 的口径过滤 alarm_occur_time。
    """
    where, params = _window_clause(time_start, time_end, days)
    index: dict[str, dict[str, int]] = {}
    rows = conn.execute(
        f"SELECT last_processer, current_handler, status FROM eflow_wo WHERE 1=1{where}",
        params,
    ).fetchall()
    for last_p, handler, status in rows:
        # 一个人可能同时出现在 last_processer 和 current_handler，用集合去重，
        # 避免同一条 WO 被同一个人计两次。
        keys = _wo_person_keys(last_p, handler)
        closed = _is_closed(status)
        for k in keys:
            slot = index.setdefault(k, {"open": 0, "total": 0})
            slot["total"] += 1
            if not closed:
                slot["open"] += 1
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

    **`wo_count`/`wo_count_total` 跟随时间窗口**（2026-10-16 修）：
    与 GIS 站点统计同口径，按 `eflow_wo.alarm_occur_time` 过滤。
    窗口为「全部时间」时前端不传任何时间参数 → 不过滤。
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
            # 未关闭 WO 数（下钻默认口径，二者必须相等）
            "wo_count": slot.get("open", 0),
            # 全部 WO 数（含已关闭）—— 供标签显示「WO:开/总」
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
    limit: int = Query(_WO_LIMIT, ge=1, le=10000, description="最大取样行数"),
    time_start: str = Query(None, description="时间窗口开始 YYYY-MM-DD（与地图筛选同口径）"),
    time_end: str = Query(None, description="时间窗口结束 YYYY-MM-DD"),
    days: int = Query(None, ge=1, le=3650, description="时间窗口天数"),
):
    """某人员名下的 WO 列表（含站点坐标，供路线规划）。

    **口径必须与 `/personnel` 的 `wo_count` 对齐**（AGENTS.md 第三节 1b：
    下钻行数不得少于表格数字）。`/personnel` 的 `wo_count` 统计的是
    **时间窗口内**、**未关闭** WO，故本端点同样按这两条过滤；
    需要看历史单时传 `include_closed=true`，此时响应 `wo_count` 会大于列表数字，
    前端需据此说明「含已关闭」—— 这是**显式**差异，不是口径不一致。

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
        # 默认排除已关闭 —— 与 /personnel 的 wo_count 同口径
        if not include_closed and _is_closed(d["status"]):
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
        # 显式暴露截断（AGENTS.md 第三节 1b 铁律：不得静默截断）
        "meta": {"truncated": truncated, "limit": limit},
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

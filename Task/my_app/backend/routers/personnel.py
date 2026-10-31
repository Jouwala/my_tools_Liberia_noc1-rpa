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
from backend.dialect_helpers import list_table_names, table_columns
from backend.services import pm_caliber
from backend.services.person_name import normalize_person_name, split_multi_person
from backend.services.routing_service import plan_route
from backend.routers.gis import (
    _resolve_window, _norm_site_category, _realtime_site_stats,
)

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

# PMT 明细返回列（顺序即前端列序）。eflow_pm 共 95 列（snake_case + 大写显示孪生列），
# 这里只取「这个人当前在手什么活」用得上的：大半是流程各步时间戳与审批人，
# 放进弹窗没人看，反而把关键列挤出可视区。
_PMT_COLS = (
    "pmt_no", "status", "title", "pmp_no", "pmt_overdue", "site_name",
    "template", "completed_items", "total_items",
    "current_task_start_time", "current_task_end_time",
    "created_time", "last_modified_time", "current_handler",
)
# PMT 取样上限。实测单人最大 298 张未关闭，2000 留足余量（AGENTS.md 三.1b：
# limit 必须显著大于单页最大数据量，否则会静默截断，「徽标数字」与「明细行数」对不上）。
_PMT_LIMIT = 2000

# 人员表「有坐标」判定：非空且非 0（实测有 2 条的 0.0/0.0 会落在大西洋上）
_COORD_OK = (
    "latitude IS NOT NULL AND longitude IS NOT NULL "
    "AND CAST(latitude AS REAL) != 0 AND CAST(longitude AS REAL) != 0"
)
# 「一线（FE）人员」判定：`person.isfe` 列取值 Yes。实测该列只有 `Yes` 与 NULL
# 两种（PG 的 app.person 与 sqlite 的 db/app.db 都是 32 Yes / 105 NULL，共 137 行），
# 所以用「trim 后等于 yes」而不是 `IS NOT NULL` —— 将来若出现 No/其它写法，
# 不会被当成 FE 蒙进分母。
_IS_FE = "isfe IS NOT NULL AND lower(trim(isfe)) = 'yes'"


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


def _fme_contact_index(conn) -> dict[str, set[str]]:
    """FME 联系人索引：`normalize_person_name(fme_name)` → 明文电话集合。

    来源是 `master_site_db.fme_contact_1 / fme_contact_2`（手册 11a 已实测：
    这两列看着像人员列，**其实是电话号码**）。只收**明文** —— 打星号的值
    同样补不回完整号码，收进来只会制造歧义。
    供 `_display_phone` 给「库里已打星」的人员电话做唯一性补全。
    """
    index: dict[str, set[str]] = {}
    if "master_site_db" not in set(list_table_names(conn)):
        return index
    for fme, c1, c2 in conn.execute(
        "SELECT fme_name, fme_contact_1, fme_contact_2 FROM master_site_db"
    ).fetchall():
        key = normalize_person_name(fme)
        if not key:
            continue
        bucket = index.setdefault(key, set())
        for c in (c1, c2):
            s = str(c or "").strip()
            if s and "****" not in s:
                bucket.add(s)
    return index


def _display_phone(raw, contacts: set[str]) -> str:
    """电话**完整显示**（2026-10-23 用户要求「不要加密，要全部显示」，取代原脱敏）。

    数据现实（2026-10-23 实测 `person` 表 136 行）：95 行明文、25 行存的是
    ``231****7417`` 形式 —— **上游入库时就已经打了星，本库任何地方都没有这几行
    的完整号码**；另有 16 行为空。处理：
      - 明文 → 原样返回；
      - 库里打星 → 用 `_fme_contact_index` 按「人名一致 + 尾 4 位一致」唯一补回
        （实测 25 人里 14 人可唯一补回、0 例歧义；尾 4 位必须吻合才采纳，
        避免把同名别人的号码安上来），补不回的**原样显示星号值** ——
        那是数据事实，不是本系统在脱敏；
      - 空 → 空串。

    ⚠ 这是用户 2026-10-23 明确要求的产品决策：现场 FME 联系号码本来就是给
    调度看的业务数据。它覆盖的是此前「响应里不出现完整号码」的默认加固约定，
    **不是**放松口令/Token/密码哈希那类敏感值（那些仍绝不出现，AGENTS.md 四.2）。
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    if "****" not in s:
        return s
    tail = s.split("****", 1)[1]
    cands = sorted(c for c in contacts if c.endswith(tail))
    if len(cands) != 1:
        return s
    return cands[0] if cands[0].startswith("231") else f"231{cands[0]}"


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


def _handler_person_keys(current_handler) -> set[str]:
    """`current_handler` 字段里归属到**个人**的键集合。

    **只取 `P:` 前缀** —— `G:` 是群组池，挂到个人头上会把整个组的单算给一个人
    （字段语义见 eflow_qa.py:1197）。WO 与 PMT **共用这一条规则**（2026-10-21
    加 PMT 时特意抽出来，不再复制一份），否则两处的「谁算这个人」会漂移。
    实测 `eflow_pm` 有 821 张未关闭 PMT 只挂在组池上（如 `G:ZTE_FE_MG`），
    它们不计入任何个人，总数在 `/personnel/stats` 的 `pmt.group_pool` 里给出。
    """
    keys: set[str] = set()
    for part in str(current_handler or "").split(","):
        p = part.strip()
        if p[:2].lower() == "p:":
            k = normalize_person_name(p)
            if k:
                keys.add(k)
    return keys


def _wo_person_keys(last_processer, current_handler) -> set[str]:
    """一条 WO 归属的所有人员（规范化姓名集合）。

    **唯一归属判定处** —— `/personnel` 的计数与 `/personnel/{key}/work-orders`
    的过滤都调用它。两边若各写一套，同一人会出现「计数 129、列表 352」的口径漂移
    （实测踩过，见模块头与 `_is_closed` 注释）。

    规则：
      - `last_processer` 取全部（逗号拆分，实测可能多人）；
      - `current_handler` 只取个人名，规则见 `_handler_person_keys`。
    """
    keys = set(split_multi_person(last_processer))
    keys |= _handler_person_keys(current_handler)
    return keys


def _is_pmt_closed(status) -> bool:
    """PMT 是否已关闭 —— **精确匹配 `Closed`**，与 PM 分析页同源
    （`pm_caliber.CLOSED_STATUS` / `CLOSED_SQL`）。

    ⚠ **刻意不复用 `_is_closed`（WO 的前缀匹配）**：eflow_wo 实测存在
    `Closed_Confirmed` 这类衍生值才需要前缀；eflow_pm 的 6 个状态里
    （`Wait Accept` / `Closed` / `Wait FLM Leader Approve` / `Wait Process` /
    `Transfer` / `Wait PM Manager Approve`）只有精确的 `Closed` 是终态。
    两边共用前缀匹配，将来 eFlow 给 PMT 加一个衍生终态就会**静默改口径**。
    """
    return str(status or "").strip().lower() == pm_caliber.CLOSED_STATUS.lower()


def _pmt_open_index(conn) -> tuple[dict[str, int] | None, dict[str, int]]:
    """一次扫描 eflow_pm → (`{姓名键: 未关闭 PMT 数}`, `{open_total, group_pool}`)。

    表不存在时返回 `(None, {0,0})` —— **用 None 而不是空 dict**：前端要能区分
    「这个人确实 0 张」和「PMT 数据根本取不到」，后者界面显示 `—` 而不是 0
    （AGENTS.md 三.6：取不到数据不得显示成 0）。
    注意本端点已对 `eflow_wo` 缺失抛 404，走到这里说明 eFlow 同步在跑，
    单张可选表缺失只降级、不整页 500。

    **三个与 WO 不同的口径**（2026-10-21 经用户确认，勿擅自改回）：

    1. **不套 30 天时间窗口**，按「当前全部未关闭」算。两条理由：
       · 库里**已关闭的 PMT 其 `current_handler` 是空的**（实测 1715 张未关闭行
         handler 全非空），所以历史归属根本做不出来，套窗口只会少算不会多算；
       · 实测套 30 天（按 `created_time`）会把 1715 砍到 826 —— 3 个月前开立
         至今未关闭的单会凭空消失，而那恰恰是最该催的。
    2. **归属只认 `current_handler`**：`eflow_pm` 没有 `last_processer` 列（实测），
       另有 `pm_manager` / `creator` / `last_*_operator` 等，语义都不是「当前在手」。
    3. **站点不进这里**：用户确认地图徽标的「站点数」仍只算未关闭 WO 的站点。
       PMT 的站点覆盖面是 WO 的 2.6 倍（实测全库 824 站，单人最多同时挂 290 个
       PMT 站点），并进来会让地图变成毛线球、"负责站点"失去意义。
    """
    if pm_caliber.TABLE not in set(list_table_names(conn)):
        return None, {"open_total": 0, "group_pool": 0}
    index: dict[str, int] = {}
    open_total = 0
    group_pool = 0
    for handler, status in conn.execute(
        f"SELECT {pm_caliber.HANDLER_COL}, status FROM {pm_caliber.TABLE}"
    ).fetchall():
        if _is_pmt_closed(status):
            continue
        open_total += 1
        keys = _handler_person_keys(handler)
        if not keys:
            # 整张单只挂在组池上 —— 谁都没法算到他头上，单独计数供界面说明
            group_pool += 1
            continue
        for k in keys:
            index[k] = index.get(k, 0) + 1
    return index, {"open_total": open_total, "group_pool": group_pool}


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
        # 电话补全索引必须在 conn 关闭前建（下面拼 personnel 的循环已拿不到连接）
        contact_index = _fme_contact_index(conn)

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
            "phone": _display_phone(phone, contact_index.get(key, ())),
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


@router.get("/personnel/{name_key}/pmt")
def get_personnel_pmt(
    name_key: str,
    limit: int = Query(_PMT_LIMIT, ge=1, le=10000, description="最大取样行数"),
):
    """某人员**当前未关闭**的 PMT（预防性维护工单）明细 —— 地图徽标第三项的下钻。

    **与徽标计数严格同源**（AGENTS.md 三.1b「下钻端点的 WHERE 必须与概览端点完全一致」）：
    同一个 `_is_pmt_closed`、同一个 `_handler_person_keys`、**同样不套时间窗口**、
    同样先扫全表再在 Python 侧精确判定。三者任一与 `_pmt_open_index` 漂移，
    就会出现「徽标 298、点进去 305 行」这类被当成 bug 的不一致。

    刻意**不提供** `only_uncleared` / `include_closed` 开关（WO 端点有那两个）：
    PMT 没有告警清除语义，而**已关闭的 PMT 在库里 `current_handler` 是空的**（实测），
    给它们做归属根本查不出东西，加开关只会让人误以为「0 行 = 这人没做过 PMT」。

    排序：逾期（`pmt_overdue='Yes'`）优先 → 任务窗口结束时间升序 → 单号。
    即「最急的要到期/已经逾期的」排最上面，缺结束时间的沉底。
    **先排序再截断**，否则 limit 生效时留下的是扫描顺序里的前 N 条，
    恰好把最该看的逾期单切掉。
    """
    key = normalize_person_name(name_key)
    if not key:
        raise HTTPException(status_code=400, detail="人员标识为空")
    # 直接调用（单测/脚本）时 limit 仍是 Query 对象，与 _window_clause 同一收敛
    if not isinstance(limit, int):
        limit = _PMT_LIMIT
    limit = max(1, min(limit, 10000))

    with get_raw_connection() as conn:
        available = pm_caliber.TABLE in set(list_table_names(conn))
        rows = conn.execute(
            f"SELECT {', '.join(_PMT_COLS)} FROM {pm_caliber.TABLE}"
        ).fetchall() if available else []
        conn.close()

    matched: list[dict] = []
    for row in rows:
        d = dict(zip(_PMT_COLS, row))
        if _is_pmt_closed(d["status"]):
            continue
        if key not in _handler_person_keys(d["current_handler"]):
            continue
        matched.append(d)

    matched.sort(key=lambda r: (
        str(r.get("pmt_overdue") or "").strip().upper() != "YES",
        str(r.get("current_task_end_time") or "9999"),
        str(r.get("pmt_no") or ""),
    ))
    truncated = len(matched) > limit
    pmt_rows = matched[:limit]

    return {
        "name_key": key,
        "pmt_list": pmt_rows,
        "pmt_count": len(pmt_rows),
        # 显式暴露截断与档位（AGENTS.md 三.1b：不得静默截断）
        "meta": {
            "available": available,
            "truncated": truncated,
            "limit": limit,
            "overdue_count": sum(
                1 for r in pmt_rows
                if str(r.get("pmt_overdue") or "").strip().upper() == "YES"
            ),
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
    """有登记坐标的人员行：(name, name_key, lat, lng, phone, regions, status, is_fe)。

    与 `/personnel` 的筛选条件**完全一致**（`_COORD_OK` + 规范化去重），
    保证本页与 GIS 人员图层的「有坐标人数」对得上（AGENTS.md 三.1b）。

    `is_fe` 只用于「People with coordinates」这一档 KPI 的分子 —— 该指标的分母是
    FE 人员（`person.isfe = Yes`），分子必须是它的子集，所以在这里顺带把 isfe
    取出来打标，**不改变返回集合本身**（地图仍画全部有坐标的人，含非 FE 的 3 人）。
    """
    rows = conn.execute(f"""
        SELECT name, latitude, longitude, phone, managed_regions, status, isfe
        FROM person
        WHERE {_COORD_OK}
        ORDER BY name
    """).fetchall()
    contact_index = _fme_contact_index(conn)
    out = []
    seen: set[str] = set()
    for name, lat_raw, lng_raw, phone, regions, status, isfe in rows:
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
                    _display_phone(phone, contact_index.get(key, ())),
                    str(regions or ""), str(status or ""),
                    str(isfe or "").strip().lower() == "yes"))
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


def _fme_keys(raw) -> set[str]:
    """`master_site_db.fme_name` → 规范化姓名键集合。

    实测该列 824 站全覆盖、24 个取值，有两种写法：
      · 单人：`Mark D. Paye`（62 站）、`Clarance Arku Fair`（61 站）
      · **双人共担**：`Ernest Feikai  Sherman / Darlington Rue`（98 站）、
        `Fedesco Pelleh /Alex Nagbe`（88 站）—— 分隔符是 `/`，左右空格不定，
        还出现过双空格。
    按 `/` 拆开逐段规范化，双人共担的站**两边都算负责**（与
    `_handler_person_keys` 的逗号拆分同一思路）。
    """
    keys: set[str] = set()
    for part in str(raw or "").split("/"):
        k = normalize_person_name(part.strip())
        if k:
            keys.add(k)
    return keys


def _fme_site_index(conn, tables: set[str]) -> tuple[dict[str, list[dict]], dict[str, int], dict[str, int]]:
    """「人员 → 其负责的站点」索引，口径 = `master_site_db.fme_name`。

    返回 `(sites, skipped, supervised)`：
      · `sites[键]` = 该人负责**且有有效坐标**的站点（可直接画）；
      · `skipped[键]` = 负责但坐标缺失/非法、画不出来的站数。不静默丢，
        界面 `skipped_no_coord` 显式给出（实测这一档是 0，但缺了就会让人
        以为「站点数对不上」）。
      · `supervised[键]` = 该人以 `supervisor` 列登记的站数。**只用于空态解释**：
        实测 `supervisor` 只有 3 个取值，把全国 824 站三三分掉
        （Varfee Sarnor 353 / Franklin Peter 294 / Festus Emmanuel 177），
        语义是「大区主管」而非「单站负责」，所以**刻意不计入站点集合**；
        但点他们的人要能看到「为什么这人 0 个站、却是在手单最多的」。

    只读 `master_site_db`（824 行），**不碰工单表** —— 「谁负责这个站」与
    「谁在这个站上有单」是两件事，2026-10-21 用户确认站点集合只看前者。
    """
    sites: dict[str, list[dict]] = {}
    skipped: dict[str, int] = {}
    supervised: dict[str, int] = {}
    if "master_site_db" not in tables:
        return sites, skipped, supervised
    # vip_site 列在个别部署里可能缺失（如 MTN_Comsal 的 site_db）——
    # 用 table_columns 判断存在性，缺列时该列为空串（前端按「非 VIP」处理）。
    _cols = set(table_columns(conn, "master_site_db"))
    _vip_sel = "vip_site" if "vip_site" in _cols else "'' AS vip_site"
    # site_type / network_type：站点弹窗（人员页与实时告警页同款）要显示
    # 「类型 | 网络类型」，两页读同一批列，故这里一并下发（2026-10-30 对齐）。
    # 缺列时给空串（不伪造），前端按「—」显示。
    _st_sel = "site_type" if "site_type" in _cols else "'' AS site_type"
    _nt_sel = "network_type" if "network_type" in _cols else "'' AS network_type"
    for sid, sname, region, county, fme, sup, vip, stype, ntype, lat_raw, lng_raw in conn.execute(
        f"SELECT site_id, site_name, region, province_county, fme_name, supervisor, "
        f"{_vip_sel}, {_st_sel}, {_nt_sel}, latitude, longitude "
        f"FROM master_site_db"
    ).fetchall():
        sup_key = normalize_person_name(sup)
        if sup_key:
            supervised[sup_key] = supervised.get(sup_key, 0) + 1
        keys = _fme_keys(fme)
        if not keys:
            continue
        entry = None
        try:
            lat, lng = _fix_latlng(float(lat_raw), float(lng_raw))
            if lat != 0 or lng != 0:      # 与 _COORD_OK 同判定：0/0 会落在大西洋上
                entry = {
                    "site_id": str(sid),
                    "site_name": str(sname or ""),
                    "region": str(region or ""),
                    "county": str(county or ""),
                    # 2026-10-30：VIP 档取色要用（与实时告警页同一套 VIP 判定：
                    # vip_site == 'Y' / 'Yes'）。
                    "vip_site": str(vip or ""),
                    # 站点类型 / 网络类型：与实时告警页弹窗同款字段（2026-10-30）
                    "site_type": str(stype or ""),
                    "network_type": str(ntype or ""),
                    "lat": round(lat, 6),
                    "lng": round(lng, 6),
                }
        except (TypeError, ValueError):
            entry = None
        for k in keys:
            if entry is None:
                skipped[k] = skipped.get(k, 0) + 1
            else:
                sites.setdefault(k, []).append(entry)
    return sites, skipped, supervised


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


@router.get("/personnel/fme-territories")
def get_personnel_fme_territories():
    """全部 FME 的「默认站点辖区」（2026-10-23 人员页地图「默认站点」开关用）。

    需求（用户原话）：「显示 master_site_db 里面不同 person 的默认站点，
    person 放到这些站点的中间，并且连线；默认不显示，打开开关才显示」。

    站点集合与 `/managed-sites` **完全同源**（`_fme_site_index` = fme_name 列，
    `A / B` 双人共担两边都算），保证开关打开看到的辖区与点开单人下钻的
    站点页签对得上。每人返回：
      · `centroid` = 其全部有效坐标站点的算术平均（「放到中间」）；
      · `sites`    = 站点明细（site_id / site_name / region / county / lat / lng）。
    量级（2026-10-23 实测）：24 人、1010 条人-站对、去重 824 站。

    `phone` 从 person 表取（`_display_phone` 完整显示口径，含从
    master_site_db 联系人列补回的逻辑）；person 表没有的人（实测 1 人）
    phone 为空，前端徽标数字按「取不到」显示 `—`，不冒充 0。

    supervisor 大区主管刻意不在返回里（fme_name 列不含他们，
    见 `_fme_site_index` 的口径说明）—— 他们的「辖区」是全国三分之一，
    画出来只会变成一张网，看不出任何信息。
    """
    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))
        sites, _skipped, _supervised = _fme_site_index(conn, tables)
        contact_index = _fme_contact_index(conn)
        person_rows = conn.execute("SELECT name, phone FROM person").fetchall()
        conn.close()

    by_key: dict[str, tuple[str, object]] = {}
    for name, phone in person_rows:
        key = normalize_person_name(name)
        if key:
            by_key[key] = (str(name or "").strip(), phone)

    persons = []
    for key in sorted(sites.keys()):
        site_list = sites[key]
        if not site_list:
            continue
        centroid = {
            "lat": round(sum(s["lat"] for s in site_list) / len(site_list), 6),
            "lng": round(sum(s["lng"] for s in site_list) / len(site_list), 6),
        }
        name_raw, phone_raw = by_key.get(key, ("", None))
        persons.append({
            # person 表没有的人用「规范化名首字母大写」兜底显示（仅 1 人，
            # key 是小写规范化串，直接显示会很难看）
            "name": name_raw or key.title(),
            "name_key": key,
            "phone": _display_phone(phone_raw, contact_index.get(key, ())),
            "centroid": centroid,
            "sites": site_list,
        })
    return {"persons": persons, "person_count": len(persons)}


# =====================================================================
# 站点类别（人员页地图「站点类型图例」，2026-10-28）
#
# **需求**（用户原话）：「添加图例，按照数据库的站点类型如 COOLI/ERA/NORMAL
# 显示站点。默认不显示，当用户点击的时候在地图上显示。同样的，添加
# vip_site/hub_site/trm_type」。
#
# **两个设计决定**：
#   1. 本端点只给**数据与取值域**，过滤与着色全在前端 —— 改配色不用动后端、
#      也不用改 SQL（改后端要重启 7038 生产服务）。
#   2. 分组的**取值从库里扫出来**，不硬编码。库里出现新类别值时图例自动多一项；
#      反过来，硬编码表会因为漏值把同一档劈成两档（实测 `site_caregory` 里
#      混着 `REGULAR（NORMAL)` 就是这么来的）。
#
# **口径**：只返回坐标有效的站点（`_COORD_OK`，与 `/managed-sites` 同判定）——
# 画不出来的站不该出现在图例计数里，否则「图例说 830、图上只有 824」。
# =====================================================================

# 图例分组，顺序即界面自上而下的顺序：(前端键, 数据库列)
_SITE_CLASS_GROUPS = (
    ("site_caregory", "site_caregory"),
    ("vip_site", "vip_site"),
    ("hub_site", "hub_site"),
    ("trm_type", "trm_type"),
)


def _norm_class_value(raw, group_key: str) -> str:
    """类别值归一化 → 该分组取值域里的一个值；空值返回 `''`（= 未填）。

    `site_caregory` 必须走 `_norm_site_category`：库里混着 `REGULAR（NORMAL)`
    这类脏写法，不归一化就会把 NORMAL 劈成两档（详见 gis.py 的注释，
    且与 eflow_rules_matcher 的 `_norm_site_type` 同口径）。
    其余三列是干净枚举（Y/N；MW / Satellite Link / Starlink / IPRAN），只需去空白。
    """
    if group_key == "site_caregory":
        return _norm_site_category(raw)
    return str(raw or "").strip()


@router.get("/personnel/site-classes")
def get_personnel_site_classes():
    """人员页地图「站点类型图例」的数据源（2026-10-28）。

    返回两部分：

      · `groups` —— 每个分组的取值与该取值的**站点数**（界面直接显示
        「COOL 64」这种）。计数与过滤用的是同一批行，故图例数字与图上点数
        必然一致（AGENTS.md 三.1b 要求的那种对得上）。
      · `sites`  —— 站点精简列表（site_id / site_name / county / lat / lng /
        classes），`classes` = `{分组键: 归一化值}`，前端按它过滤。

    **为什么不复用 `/gis/sites`**：那个端点会顺带跑 TT / WO / 实时告警 / 历史告警
    四套聚合统计（秒级开销），而图例只想要类别与坐标 —— 为此多扫一遍工单表不划算。

    **过滤语义由前端定**：同一分组内多选取**并集**、不同分组之间取**交集**
    （与 GIS 页 `_build_filter_where` 的多列 AND 同思路）。
    """
    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))
        if "master_site_db" not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail="master_site_db 表不存在")
        cols = set(table_columns(conn, "master_site_db"))
        # 缺列时该分组整个不出现，不伪造空组（AGENTS.md 三.6）
        sel = [c for _k, c in _SITE_CLASS_GROUPS if c in cols]
        sql = (
            "SELECT site_id, site_name, province_county, latitude, longitude"
            + "".join(", " + c for c in sel)
            + f" FROM master_site_db WHERE {_COORD_OK}"
        )
        rows = conn.execute(sql).fetchall()
        conn.close()

    groups = []
    for gkey, col in _SITE_CLASS_GROUPS:
        if col not in cols:
            continue
        idx = 5 + sel.index(col)
        counter: dict[str, int] = {}
        for r in rows:
            v = _norm_class_value(r[idx], gkey)
            counter[v] = counter.get(v, 0) + 1
        # 排序：计数降序、同计数按值字典序；「未填」（''）永远垫底 ——
        # 它不是一类，不该因为空串排在字典序最前。
        values = [
            {"value": v, "count": n}
            for v, n in sorted(counter.items(), key=lambda kv: (kv[0] == "", -kv[1], kv[0]))
        ]
        groups.append({"key": gkey, "column": col, "values": values})

    sites = []
    for r in rows:
        try:
            lat, lng = _fix_latlng(float(r[3]), float(r[4]))
        except (TypeError, ValueError):
            continue
        sites.append({
            "site_id": str(r[0] or ""),
            "site_name": str(r[1] or ""),
            "county": str(r[2] or ""),
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "classes": {
                gkey: _norm_class_value(r[5 + sel.index(col)], gkey)
                for gkey, col in _SITE_CLASS_GROUPS if col in cols
            },
        })
    return {"groups": groups, "sites": sites, "total": len(sites)}


@router.get("/personnel/{name_key}/managed-sites")
def get_personnel_managed_sites(
    name_key: str,
    time_start: str = Query(None, description="时间窗口开始 YYYY-MM-DD（与页面 30 天窗口同口径）"),
    time_end: str = Query(None, description="时间窗口结束 YYYY-MM-DD"),
    days: int = Query(None, ge=1, le=3650, description="时间窗口天数"),
):
    """某人员**负责的站点**（`master_site_db.fme_name`）+ 每站的工单/告警状态。
    供人员位置地图画站点层、连线，与下钻抽屉的「站点」页签。

    **站点集合的口径**（2026-10-21 用户确认，从「WO 涉及过的站」改成「登记的负责站」）：
    取 `master_site_db.fme_name`，**不看工单**。双人共担（`A / B`）两边都算。

    每个站点返回：
      - 坐标（缺坐标的站画不出来，数量记在 `skipped_no_coord`，不静默丢）；
      - `wo_count`     —— 该人在窗口内此站的**未关闭** WO 数（0 = 该站当前没单）；
      - `uncleared`    —— 其中**未清除告警**的 WO 数；
      - `has_alarm`    —— 该站点当前是否有实时告警（`realtime_alarm` 快照）。

    WO 计数仍与 `/personnel` 同源：同一 `_wo_person_keys` 归属、
    同一 `_is_closed` / `_is_uncleared`、同一 `_window_clause` 窗口。

    ---- 2026-10-30：站点显色与实时告警页对齐 ----
    站点圆点原先只用 `has_alarm` 一个布尔，配色是**人员页自己的一套三档**
    （红 / 浅蓝 / 绿），与 `?page=realtime_alarm` 的分档毫无关系 ——
    两页看同一批站点、同一个 `realtime_alarm` 快照，颜色却对不上。
    现补齐四个与实时告警页**逐值相同**的实时字段：

      · `rt_alarm_count`    该站当前实时告警条数
      · `rt_alarm_overdue`  其中 SLA 已超时的条数
      · `rt_alarm_ontime`   其中未超时的条数
      · `rt_tt_count`       由这些告警关联到、确实存在的 TT 数
      · `rt_wo_count`       由这些告警关联到、确实存在的 WO 数

    这五个值由 `gis.py::_realtime_site_stats` 从**同一次 `realtime_alarm` 扫描**
    产出 —— 与 `/gis/realtime/sites` 走同一个函数，故两页数字必然一致
    （AGENTS.md 三.1b：概览与下钻必须同源）。

    ⚠ **人员页的「WO 档」语义与实时告警页不同，这是刻意的**（用户 2026-10-30 确认）：
      · 实时告警页的 WO 档 = 该站**由实时告警关联到**的 WO 数；
      · 人员页的 WO 档 = **该人员**在此站有未关闭 WO（`wo_count`）。
      后者是人员页自己的语义（「谁的手上有单」），不能被上游口径覆盖。
      故前端取色优先级见 `personmap/siteTone.ts`：
      超时 > 该人有未关闭 WO > 该站有告警 TT > 未超时 > VIP > 无状态。
    """
    key = normalize_person_name(name_key)
    if not key:
        raise HTTPException(status_code=400, detail="人员标识为空")

    win_where, win_params = _window_clause(
        time_start, time_end, days if isinstance(days, int) else None)

    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))
        if "master_site_db" not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail="master_site_db 表不存在")
        if "eflow_wo" not in tables:
            conn.close()
            raise HTTPException(status_code=404, detail="eflow_wo 表不存在")

        # 站点集合 = 登记的负责站（fme_name），**与工单无关**
        fme_sites, fme_skipped, _supervised = _fme_site_index(conn, tables)

        # 每站的「该人未关闭 WO 数」只用来上色与计数。粗筛与 work-orders 端点
        # 同一策略：按姓名首词 LIKE 收敛候选，再在 Python 侧精确判定
        # （清洗规则无法下推 SQL）。
        first_token = key.split(" ")[0] if key.split(" ") else key
        cand = conn.execute(f"""
            SELECT site_id, last_processer, current_handler, status, alarm_clear_time
            FROM eflow_wo
            WHERE ((last_processer IS NOT NULL AND LOWER(last_processer) LIKE ?)
               OR (current_handler IS NOT NULL AND LOWER(current_handler) LIKE ?)){win_where}
            LIMIT ?
        """, [f"%{first_token}%", f"%{first_token}%", *win_params, _CAND_LIMIT]).fetchall()

        alarm_sites: set[str] = set()
        rt_stats: dict[str, dict] = {}
        if "realtime_alarm" in tables:
            # 2026-10-30：与实时告警页**同一次扫描**取全部实时字段
            # （告警数 / 超时 / 未超时 / 关联 TT / 关联 WO）。
            # 旧实现只 SELECT DISTINCT site_id 拿一个「有没有告警」的布尔，
            # 前端因此只能用自己那套三档配色，与实时告警页对不上。
            rt_stats = _realtime_site_stats(conn, "master_site_db")
            alarm_sites = set(rt_stats.keys())
        conn.close()

    # 站点 → {open, uncleared}（**只计未关闭**：已关闭的历史单不构成「当前在手」）
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
    for meta in fme_sites.get(key, []):
        sid = meta["site_id"]
        cnt = per_site.get(sid) or {"open": 0, "uncleared": 0}
        rt = rt_stats.get(sid) or {}
        sites.append({
            "site_id": sid,
            "site_name": meta["site_name"],
            "region": meta["region"],
            "county": meta["county"],
            "lat": meta["lat"],
            "lng": meta["lng"],
            "wo_count": cnt["open"],
            "uncleared": cnt["uncleared"],
            "has_alarm": sid in alarm_sites,
            # VIP 档取色用（与实时告警页同一判定：'Y' / 'Yes'）
            "vip_site": meta.get("vip_site", ""),
            # 站点类型 / 网络类型：站点弹窗与实时告警页同款（2026-10-30 对齐）
            "site_type": meta.get("site_type", ""),
            "network_type": meta.get("network_type", ""),
            # 与实时告警页逐值相同的实时字段（2026-10-30，见函数头注释）
            "rt_alarm_count": rt.get("rt_alarm_count", 0),
            "rt_alarm_overdue": rt.get("rt_alarm_overdue", 0),
            "rt_alarm_ontime": rt.get("rt_alarm_ontime", 0),
            "rt_tt_count": rt.get("rt_tt_count", 0),
            "rt_wo_count": rt.get("rt_wo_count", 0),
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
        # 负责但站点缺坐标、画不出来的数量（不静默丢）
        "skipped_no_coord": fme_skipped.get(key, 0),
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
    """全量人员按 WO/TT/PMT 的聚合统计（供人员位置地图的统计区与地图徽标）。

    **一次扫描算完全部人的数字**，避免前端对 26 人各打一次接口。
    返回五块：
      - `by_person`：
          name / name_key / has_coords / open / closed / total /
          uncleared / tt_open / tt_closed / tt_total / counties / site_count /
          **pmt_open**（当前未关闭 PMT 数，**不随本端点的 days/时间窗口变**，
          理由见 `_pmt_open_index`）
      - `by_county`：{县: {open, closed, total}} —— 以 WO 的站点��在县归类；
      - `by_status`：{open, closed} —— 全量合计；
      - `pmt`：{open_total, group_pool} —— 未关闭 PMT 全量与「只挂在 G: 组池上、
        归不到个人」的张数；
      - `coverage`：两套并存的人群口径，别混用 ——
        `fe_total` / `fe_with_coords` 是「FE 人员（`person.isfe=Yes`）总数 / 其中坐标有效」，
        页面 KPI「People with coordinates」用这一对（分子是分母的子集）；
        `with_coords` / `total_all` 是「全表有坐标人数 / person 全表行数」，
        顶部 ⓘ 横幅用它解释「为什么有些人只在表格里、没画在地图上」。
        （2026-10-29 用户确认 KPI 分母改为 isfe=Yes；实测 32 名 FE 中 11 人有坐标，
        全表 137 人中 14 人有坐标 —— 差的 3 人是有坐标但不是 FE 的。）
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
        fe_total = conn.execute(
            f"SELECT COUNT(*) FROM person WHERE {_IS_FE}").fetchone()[0] or 0
        site_meta = _site_meta_index(conn, tables)
        # 「负责站点」索引（`master_site_db.fme_name`）。徽标的 site_count 与
        # `/managed-sites` 的 site_count 必须来自这同一个函数，否则
        # 「徽标写 16、地图上有 62 个点」—— 2026-10-21 改口径时特意收在一处。
        fme_sites, _fme_skipped, supervised_sites = _fme_site_index(conn, tables)

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
                })
                p[cls] += 1
                p["total"] += 1
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

        # ---- PMT 侧：再扫一次 eflow_pm（**不套窗口**，口径见 _pmt_open_index） ----
        pmt_open, pmt_meta = _pmt_open_index(conn)
        conn.close()

    # 同上：元组顺序 (name, name_key, lat, ...)。键必须取 name_key。
    people_index = {key: (name, lat, lng, regions)
                    for (name, key, lat, lng, _ph, regions, _st, _fe) in people}
    by_person = []
    # ⚠️ 元组顺序是 (name, name_key, lat, ...) —— 见 `_people_with_coords` 的
    # append 与文档字符串。这里**必须**先解 name 再解 key：首版写成
    # `for k, name, ...` 时两者互换，`per_person.get(k)` 永远拿原始姓名去查
    # 规范化后的键，于是 26 个有坐标的人的统计**全是 0**（实测踩过，
    # 而表格里 name_key 也变成原始姓名，两者的错误互相掩盖）。
    for name, k, lat, lng, phone, regions, status, _fe in people:
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
            # 负责的站点数（`master_site_db.fme_name`）——地图徽标显示；与
            # `/managed-sites` 的 site_count 出自同一个 `_fme_site_index`，天然同源。
            "site_count": len(fme_sites.get(k, ())),
            # 以 supervisor 身份登记的站数。**只为解释「为什么这人 0 个站」**，
            # 不计入 site_count、也不画进地图（supervisor 是全国三分的大区主管）。
            "supervised_sites": supervised_sites.get(k, 0),
            # 当前未关闭的 PMT 数（**不随 30 天窗口变化**，见 _pmt_open_index）。
            # None = eflow_pm 取不到（前端显示 —）；0 = 确实没有未关闭的 PMT。
            "pmt_open": None if pmt_open is None else pmt_open.get(k, 0),
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
            "site_count": len(fme_sites.get(k, ())),
            "supervised_sites": supervised_sites.get(k, 0),
            "pmt_open": None if pmt_open is None else pmt_open.get(k, 0),
        })

    # 排行按「未清除 → 未关闭」降序，与页面表格默认排序一致
    ranked = sorted(by_person, key=lambda r: (-r["uncleared"], -r["open"], r["name"]))
    return {
        "by_person": ranked,
        "top_person": ranked[:top],
        "by_county": county_agg,
        "by_status": by_status,
        # 未关闭 PMT 的全局量（`group_pool` = 只挂在 G: 组池上、无法归到个人的张数），
        # 供页面 ⓘ 说明「为什么各人徽标加起来对不上总数」
        "pmt": pmt_meta,
        "coverage": {
            # 全表人群：有登记坐标的人数 与 person 表总行数。
            # 顶部 ⓘ 横幅用它说明「为什么有些人只在表格里、没画在地图上」。
            "with_coords": len(people),
            "total_all": total_all,
            # KPI「People with coordinates」用它做分母 —— 口径是 FE 人员
            # （`person.isfe = Yes`），不是全表。2026-10-29 用户确认。
            "fe_total": fe_total,
            # 分子必须是分母的子集，故从同一份去重后的 `people` 里按 isfe 打标计数，
            # 不另开一条 SQL —— 否则「14 人有坐标 / 32 名 FE」这种分子分母来自
            # 两个群体的写法会再次出现（实测非 FE 却有坐标的有 3 人）。
            "fe_with_coords": sum(1 for p in people if p[7]),
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

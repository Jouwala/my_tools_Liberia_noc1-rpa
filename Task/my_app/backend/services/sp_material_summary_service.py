"""
RCK_MATERIAL_SUMMARY_V1
SP 物料「库存 / 消耗」统计汇总服务（对齐用户提供的 WH/DOP 汇总报表模板）。

数据源
------
inventory_details 表（由 backend/services/get_sp_table.run_sp_data_sync 从 SFTP 拉取
sp/spinventory 报表后写入；该表属于 APPEND_TABLES，按 update_date 保留每日全量快照，
历史只增不改，因此可以做「期初 vs 期末」对比）。

outband_details 表（同一条同步链路的 sp/spoutbound 报表）——**全量刷新表**，
每次同步整表覆盖（所有行 update_date 相同），所以「当月报修出库」只能按
Outbound Time 过滤、不能按 update_date 取快照。

连接是双模的（见 backend/database.py 的 DB_MODE 熔断开关）：
  - sqlite（默认回退）：项目根 db/app.db
  - pg（当前线上）：PostgreSQL，schema 由 get_raw_connection 解析
列名探测必须走 dialect_helpers.table_columns（PRAGMA ↔ information_schema），
不要直接写 PRAGMA —— PG 下会抛语法错误。

行（WH/DOP 分组，见 ROW_GROUPS）
--------------------------------
  1st WH       Liberia Monrovia  Entrusted Spare Parts Warehouse
               + Liberia Monrovia material warehouse（Monrovia Warehouse_02，同城同体系）
  2nd WH       Liberia Monrovia Entrusted Spare Parts Warehouse-2nd floor
  Gbarnga DOP  Liberia Gbarnga  Entrusted Spare Parts DOP
  Kweaken DOP  Liberia Kweaken Entrusted Spare Parts DOP
  Total        以上各组之和（未匹配到任何组的仓库进 "Others" 组，默认也计入 Total）
分组优先按 "Warehouse Id" 精确/前缀匹配，再退回 "Warehouse Name" 关键词匹配，
两者都带排除词（如 1st WH 排除含 "2nd floor" 的仓），保证新增仓库不会串行。

列（口径）
----------
  <锚点日> Spare Part (Good)  锚点日快照：Material Type 含 spare 且 Material Status != 'damage'
                              的 SUM(Stock Qty)
  <锚点日> Consumables        锚点日快照：Material Type 含 consum 的 SUM(Stock Qty)
  Current Date Spare Part (Good) / Consumables
                              同上两列，但取「当前快照」（默认库内 MAX(update_date)）
  Need Repair                 当前快照：Material Status = 'damage' 的 SUM(Stock Qty)
  Repair Outbound             出库表 outband_details 中 Outbound Type = 'Repair Outbound'
                              且 Outbound Time ∈ [当月 1 号 00:00:00, 现在] 的
                              SUM(Outbound Qty)（该表一行 = 一个物料序列号，Qty 恒为 1，
                              所以「件数」= 行数）。**该表只有 Warehouse Name、没有 Warehouse Id**，
                              归组只能按名字走 _match_group。
  Total Consumption from <锚点日> / this Month / this week
                              三个窗口各自拆成 Spare Part 与 Consumables 两个子列：
                                Spare Part  = 期初 SpareGood − 期末 SpareGood
                                Consumables = 期初 Consumables − 期末 Consumables
                              三个窗口起点分别是 锚点日 / 当月 1 号 / 本周周一，终点都是当前快照；
                              两个子列相加 = 原来的整列合计（拆分不改变总量）。

约定
----
- 锚点日默认取「当前快照所在自然月 1 号」（2026-09 即 2026-09-01，与报表模板一致），
  可用 anchor_date 参数覆盖；当前快照默认取库内 MAX(update_date)，可用 current_date 覆盖。
- 期初/周初/月初在库中缺快照时，回退到「<= 目标日的最近一个可用快照」并写 warnings，
  不抛异常、不返回 5xx（软失败）。
- 消耗为负（期末 > 期初）时原样保留负值并在 warnings 里点名——那是「入库回补 / 调拨进仓」
  的信号，截断成 0 会掩盖真实库存变动。
- 整表结果按 (锚点日, 当前日) 做 60s TTL 缓存，避免看板轮询重复扫 11 万行。

对外提供
--------
  get_material_summary(anchor_date=None, current_date=None) -> dict  汇总表
  get_material_detail(row_key, scope, anchor_date=None, current_date=None) -> dict  单元格下钻明细

下钻 scope 一览（row_key: 1st_wh / 2nd_wh / gbarnga_dop / kweaken_dop / others / total）：
  快照类   anchor_spare_good | anchor_consumables | current_spare_good
           | current_consumables | need_repair
  消耗类   consumption_from_anchor_spare | consumption_from_anchor_cons
           | consumption_month_spare | consumption_month_cons
           | consumption_week_spare | consumption_week_cons
  出库类   repair_outbound
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.database import DB_MODE, get_raw_connection
from backend.dialect_helpers import table_columns

logger = logging.getLogger(__name__)

SERVICE_DIR = Path(__file__).resolve().parent          # backend/services
DB_PATH = SERVICE_DIR.parent.parent / "db" / "app.db"  # 项目根 db/app.db

TABLE = "inventory_details"

# 实际列名（get_sp_table._write_table 写入的列；缺失时由 _resolve_columns 回退）
C_DATE = "update_date"
C_WH_ID = "Warehouse Id"
C_WH_NAME = "Warehouse Name"
C_TYPE = "Material Type"
C_STATUS = "Material Status"
C_QTY = "Stock Qty"
C_MNO = "Material No."
C_MNAME = "Material Name"

# 值判定
DAMAGE_STATUS = "damage"
SPARE_TOKEN = "spare"
CONSUMABLE_TOKEN = "consum"

# outband_details（全量刷新表，只有 Warehouse Name、没有 Warehouse Id）
OB_TABLE = "outband_details"
OB_TYPE = "Outbound Type"
OB_TIME = "Outbound Time"
OB_WH_NAME = "Warehouse Name"
OB_QTY = "Outbound Qty"
REPAIR_OUTBOUND_TYPE = "Repair Outbound"

# Repair Outbound 下钻要展示的列（按此顺序输出，库里不存在的自动跳过）
OB_DETAIL_COLS: List[str] = [
    "Outbound No.", "Outbound Time", "Warehouse Name", "Status",
    "Material No.", "Material Name", "Material Type", "Outbound Qty",
    "Need Repair Return", "Repair Vendor", "Repair/Replace SLA",
    "Related Ticket No.",
]

# 分组定义：id_any 精确/前缀匹配 Warehouse Id；name_any/name_none 匹配 Warehouse Name
ROW_GROUPS: List[Dict[str, Any]] = [
    {
        "key": "1st_wh",
        "label": "1st WH",
        "id_any": ["Monrovia Warehouse_01", "Monrovia Warehouse_02"],
        "name_any": ["Entrusted Spare Parts Warehouse"],
        "name_none": ["2nd floor"],
    },
    {
        "key": "2nd_wh",
        "label": "2nd WH",
        "id_any": ["Monrovia Warehouse_03"],
        "name_any": ["2nd floor"],
        "name_none": [],
    },
    {
        "key": "gbarnga_dop",
        "label": "Gbarnga DOP",
        "id_any": ["Gbarnga"],
        "name_any": ["Gbarnga"],
        "name_none": [],
    },
    {
        "key": "kweaken_dop",
        "label": "Kweaken DOP",
        "id_any": ["Kweaken"],
        "name_any": ["Kweaken"],
        "name_none": [],
    },
]
OTHERS_KEY = "others"
OTHERS_LABEL = "Others"

# 汇总行里所有「可加和」的数值列：合计行 = 各分组之和（含 Others）
SUM_KEYS: Tuple[str, ...] = (
    "anchor_spare_good", "anchor_consumables",
    "current_spare_good", "current_consumables",
    "need_repair", "repair_outbound",
    "consumption_from_anchor_spare", "consumption_from_anchor_cons",
    "consumption_month_spare", "consumption_month_cons",
    "consumption_week_spare", "consumption_week_cons",
    "consumption_from_anchor", "consumption_month", "consumption_week",
    "anchor_total", "current_total",
)

# 下钻 scope -> (用锚点日还是当前日, 类型过滤, 状态过滤)
_SCOPES: Dict[str, Dict[str, str]] = {
    "anchor_spare_good": {"date": "anchor", "type": "spare", "status": "good"},
    "anchor_consumables": {"date": "anchor", "type": "consumable", "status": "any"},
    "current_spare_good": {"date": "current", "type": "spare", "status": "good"},
    "current_consumables": {"date": "current", "type": "consumable", "status": "any"},
    "need_repair": {"date": "current", "type": "any", "status": "damage"},
}

# 消耗类下钻：不是「某一日的行」，而是「期初 vs 期末逐物料对比」，
# 所以单独一张表。window 指向起点，终点固定当前快照。
#   anchor = 锚点日 / month = 当月 1 号 / week = 本周周一
_CONSUMPTION_SCOPES: Dict[str, Dict[str, str]] = {
    "consumption_from_anchor_spare": {"window": "anchor", "type": "spare"},
    "consumption_from_anchor_cons": {"window": "anchor", "type": "consumable"},
    "consumption_month_spare": {"window": "month", "type": "spare"},
    "consumption_month_cons": {"window": "month", "type": "consumable"},
    "consumption_week_spare": {"window": "week", "type": "spare"},
    "consumption_week_cons": {"window": "week", "type": "consumable"},
}

# 报修出库下钻：走 outband_details（不是 inventory_details）
REPAIR_OUTBOUND_SCOPE = "repair_outbound"

# ---------- 列名探测（模块级一次） ----------
def _norm(v: Any) -> str:
    """列值归一化：None -> ''，去不换行空格(\xa0)与首尾空白。

    注意：4G FDD 那类表的列名里混过 \xa0，这里对「值」也统一处理，
    避免 Warehouse Name 里的双空格 / NBSP 导致分组匹配失败。
    """
    if v is None:
        return ""
    return str(v).replace("\xa0", " ").strip()


def _resolve_columns(conn) -> Dict[str, str]:
    """拿表内真实列名；缺列时回退到约定名（软失败）。

    双模：必须走 dialect_helpers.table_columns —— sqlite 下它是 PRAGMA table_info，
    PG 下是 information_schema。直接写 PRAGMA 在 PG 模式会抛语法错误（本服务第一版
    就踩过：列名恰好与约定名相同才没暴露）。
    """
    mapping = {C_DATE: C_DATE, C_WH_ID: C_WH_ID, C_WH_NAME: C_WH_NAME,
               C_TYPE: C_TYPE, C_STATUS: C_STATUS, C_QTY: C_QTY,
               C_MNO: C_MNO, C_MNAME: C_MNAME}
    try:
        cols = [_norm(c) for c in table_columns(conn, TABLE)]
    except Exception:
        logger.warning("[SILENT-EXCEPT] _resolve_columns: 列枚举失败，回退约定列名", exc_info=True)
        return mapping
    if not cols:
        return mapping
    lower = {c.lower(): c for c in cols}

    def pick(want: str) -> str:
        if want in cols:
            return want
        return lower.get(want.lower(), want)

    for k in list(mapping.keys()):
        mapping[k] = pick(k)
    return mapping


def _match_group(wh_id: str, wh_name: str) -> str:
    """把一个 (Warehouse Id, Warehouse Name) 归到某个行分组 key；匹配不到返回 others。"""
    _id = _norm(wh_id)
    _name = _norm(wh_name)
    low_name = _name.lower()
    low_id = _id.lower()
    for g in ROW_GROUPS:
        none_hit = any(n.lower() in low_name for n in g.get("name_none") or [])
        if none_hit:
            continue
        id_hit = any(low_id == str(x).lower() or (low_id and low_id.startswith(str(x).lower()))
                     for x in g.get("id_any") or [])
        name_hit = any(str(n).lower() in low_name for n in g.get("name_any") or [])
        if id_hit or name_hit:
            return g["key"]
    return OTHERS_KEY


# ---------- 日期工具 ----------
def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _month_start(d: str) -> str:
    return f"{d[:7]}-01"


def _week_start(d: str) -> str:
    dt = datetime.strptime(d, "%Y-%m-%d")
    return (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")


def _shift_days(d: str, days: int) -> str:
    return (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


# ---------- 查询 ----------
def _db_exists() -> bool:
    """sqlite 模式看文件是否存在；PG 模式由连接串保证（本地 app.db 与 PG 无关）。"""
    if DB_MODE == "pg":
        return True
    return DB_PATH.exists()


def _max_date(conn, col: str) -> Optional[str]:
    # 只判 IS NOT NULL：PG 下该列若为 date 类型，与 '' 比较会报 invalid input syntax。
    try:
        row = conn.execute(
            f'SELECT MAX("{col}") AS d FROM {TABLE} WHERE "{col}" IS NOT NULL'
        ).fetchone()
        return _norm(row[0]) or None
    except Exception:
        logger.warning("[SILENT-EXCEPT] _max_date: query failed", exc_info=True)
        return None


def _nearest_le(conn, col: str, want: str) -> Optional[str]:
    """返回 <= want 的最近一个可用快照日；无则返回 None。"""
    try:
        row = conn.execute(
            f'SELECT MAX("{col}") AS d FROM {TABLE} '
            f'WHERE "{col}" IS NOT NULL AND "{col}" <= ?',
            (want,),
        ).fetchone()
        return _norm(row[0]) or None
    except Exception:
        logger.warning("[SILENT-EXCEPT] _nearest_le: query failed", exc_info=True)
        return None


def _snapshot_agg(conn, cols: Dict[str, str], dates: List[str]
                  ) -> Dict[str, Dict[str, Dict[str, int]]]:
    """一次扫描聚合出 {date: {group_key: {'spare_good','consumables','damage','total'}}}。

    用 GROUP BY 把 11 万行压到几十行再回 Python 归组，避免把明细拉进内存。
    """
    out: Dict[str, Dict[str, Dict[str, int]]] = {}
    if not dates:
        return out
    ph = ",".join("?" * len(dates))
    sql = (
        f'SELECT "{cols[C_DATE]}" AS d, '
        f'COALESCE("{cols[C_WH_ID]}", \'\') AS wh_id, '
        f'COALESCE("{cols[C_WH_NAME]}", \'\') AS wh_name, '
        f'COALESCE("{cols[C_TYPE]}", \'\') AS mtype, '
        f'COALESCE("{cols[C_STATUS]}", \'\') AS mstatus, '
        f'SUM(COALESCE("{cols[C_QTY]}", 0)) AS qty '
        f'FROM {TABLE} WHERE "{cols[C_DATE]}" IN ({ph}) '
        f'GROUP BY 1, 2, 3, 4, 5'
    )
    try:
        rows = conn.execute(sql, list(dates)).fetchall()
    except Exception:
        logger.warning("[SILENT-EXCEPT] _snapshot_agg: query failed", exc_info=True)
        return out

    for row in rows:
        d = _norm(row["d"])
        if not d:
            continue
        gkey = _match_group(_norm(row["wh_id"]), _norm(row["wh_name"]))
        mtype = _norm(row["mtype"]).lower()
        mstatus = _norm(row["mstatus"]).lower()
        try:
            qty = int(row["qty"] or 0)
        except (TypeError, ValueError):
            qty = 0
        bucket = out.setdefault(d, {}).setdefault(
            gkey, {"spare_good": 0, "consumables": 0, "damage": 0, "total": 0})
        bucket["total"] += qty
        if mstatus == DAMAGE_STATUS:
            bucket["damage"] += qty
        elif SPARE_TOKEN in mtype:
            bucket["spare_good"] += qty
        elif CONSUMABLE_TOKEN in mtype:
            bucket["consumables"] += qty
        # 其余类型（理论上不存在）只进 total，不落任何展示列
    return out


def _resolve_outband_columns(conn) -> Dict[str, str]:
    """outband_details 的真实列名；缺列时回退约定名（软失败）。"""
    mapping = {OB_TYPE: OB_TYPE, OB_TIME: OB_TIME,
               OB_WH_NAME: OB_WH_NAME, OB_QTY: OB_QTY}
    try:
        cols = [_norm(c) for c in table_columns(conn, OB_TABLE)]
    except Exception:
        logger.warning("[SILENT-EXCEPT] _resolve_outband_columns: 列枚举失败", exc_info=True)
        return mapping
    if not cols:
        return mapping
    lower = {c.lower(): c for c in cols}
    for k in list(mapping.keys()):
        mapping[k] = k if k in cols else lower.get(k.lower(), k)
    return mapping


def _repair_outbound_agg(conn, cols: Dict[str, str], start_ts: str, end_ts: str
                         ) -> Dict[str, int]:
    """按仓库归组统计「报修出库件数」→ {group_key: 件数}。

    口径：Outbound Type = 'Repair Outbound' 且 Outbound Time ∈ [start_ts, end_ts]，
    取 SUM(Outbound Qty)（该表一行 = 一个序列号，Qty 恒为 1，件数即行数）。

    Outbound Time 存的是 'YYYY-MM-DD HH:MM:SS' 文本，字典序即时间序；统一
    CAST(... AS TEXT) 以兼容 PG 下该列可能是 timestamp 的情况。
    该表**没有 Warehouse Id**，只能用 Warehouse Name 走 _match_group。

    表不存在 / 查询失败时返回 {}（软失败——页面照常出其它列，不整页 500）。
    """
    out: Dict[str, int] = {}
    sql = (
        f'SELECT COALESCE("{cols[OB_WH_NAME]}", \'\') AS wh_name, '
        f'SUM(COALESCE("{cols[OB_QTY]}", 0)) AS qty '
        f'FROM {OB_TABLE} '
        f'WHERE "{cols[OB_TYPE]}" = ? '
        f'AND CAST("{cols[OB_TIME]}" AS TEXT) >= ? '
        f'AND CAST("{cols[OB_TIME]}" AS TEXT) <= ? '
        f'GROUP BY 1'
    )
    try:
        rows = conn.execute(sql, (REPAIR_OUTBOUND_TYPE, start_ts, end_ts)).fetchall()
    except Exception:
        logger.warning("[SILENT-EXCEPT] _repair_outbound_agg: query failed", exc_info=True)
        return out
    for row in rows:
        gkey = _match_group("", _norm(row["wh_name"]))
        try:
            qty = int(row["qty"] or 0)
        except (TypeError, ValueError):
            qty = 0
        out[gkey] = out.get(gkey, 0) + qty
    return out


# ---------- TTL 缓存 ----------
_CACHE: Dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 60.0


def _cache_get(key: str):
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item and (time.time() - item[0]) < _CACHE_TTL:
            return item[1]
    return None


def _cache_put(key: str, value) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)
        if len(_CACHE) > 32:  # 简单防膨胀
            oldest = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:8]
            for k, _ in oldest:
                _CACHE.pop(k, None)


# ---------- 主入口 ----------
def _empty_result(warnings: List[str], anchor: str = "", current: str = "") -> Dict[str, Any]:
    return {
        "anchor_date": anchor,
        "current_date": current,
        "month_start": "",
        "week_start": "",
        "repair_outbound_start": "",
        "repair_outbound_end": "",
        "row_groups": [{"key": g["key"], "label": g["label"]} for g in ROW_GROUPS]
                      + [{"key": OTHERS_KEY, "label": OTHERS_LABEL}],
        "rows": [],
        "warnings": warnings,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def get_material_summary(anchor_date: Optional[str] = None,
                         current_date: Optional[str] = None) -> Dict[str, Any]:
    """汇总表主入口。返回结构与前端 SpMaterialSummary.tsx 的 SummaryResp 对齐。"""
    warnings: List[str] = []
    if not _db_exists():
        return _empty_result([f"数据库不存在：{DB_PATH}"])

    conn = get_raw_connection(str(DB_PATH))
    try:
        cols = _resolve_columns(conn)
        latest = _max_date(conn, cols[C_DATE])
        if not latest:
            return _empty_result(["inventory_details 表为空或尚未同步（请先运行 SP 数据同步任务）"])
        current = _norm(current_date) or latest
        if current_date and current > latest:
            warnings.append(f"指定的当前日期 {current} 超出库内最新快照 {latest}，已按 {latest} 计算")
            current = latest
        cur_resolved = _nearest_le(conn, cols[C_DATE], current)
        if not cur_resolved:
            return _empty_result([f"找不到 <= {current} 的库存快照"])
        if cur_resolved != current:
            warnings.append(f"当前日期 {current} 无快照，已回退到最近可用快照 {cur_resolved}")
        current = cur_resolved

        # 锚点日：默认当月 1 号（与报表模板 2026/9/1 一致）
        want_anchor = _norm(anchor_date) or _month_start(current)
        anchor = _nearest_le(conn, cols[C_DATE], want_anchor)
        if not anchor:
            return _empty_result([f"找不到 <= {want_anchor} 的库存快照"], want_anchor, current)
        if anchor != want_anchor:
            warnings.append(f"锚点日 {want_anchor} 无快照，已回退到最近可用快照 {anchor}")

        want_month = _month_start(current)
        month_start = _nearest_le(conn, cols[C_DATE], want_month) or anchor
        if month_start != want_month:
            warnings.append(f"月初 {want_month} 无快照，已回退到最近可用快照 {month_start}")

        want_week = _week_start(current)
        week_start = _nearest_le(conn, cols[C_DATE], want_week) or month_start
        if week_start != want_week:
            warnings.append(f"周初 {want_week} 无快照，已回退到最近可用快照 {week_start}")

        cache_key = f"{anchor}|{current}|{month_start}|{week_start}"
        cached = _cache_get(cache_key)
        if cached is not None:
            cached["warnings"] = warnings + cached.get("_base_warnings", [])
            return cached

        dates = sorted({anchor, current, month_start, week_start})
        agg = _snapshot_agg(conn, cols, dates)

        # 报修出库：当月 1 号 00:00:00 → 现在（走 outband_details，全量刷新表，不做快照回溯）
        ob_start = f"{_month_start(current)} 00:00:00"
        ob_end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ob_map = _repair_outbound_agg(conn, _resolve_outband_columns(conn), ob_start, ob_end)
        if not ob_map:
            warnings.append(
                f"outband_details 中 {ob_start} → {ob_end} 无 Repair Outbound 记录，"
                "Repair Outbound 列按 0 显示")

        # 仓库归属（供前端 tooltip / 说明用）
        groups_meta: List[Dict[str, Any]] = []
        try:
            wh_rows = conn.execute(
                f'SELECT DISTINCT COALESCE("{cols[C_WH_ID]}", \'\') AS wh_id, '
                f'COALESCE("{cols[C_WH_NAME]}", \'\') AS wh_name FROM {TABLE}'
            ).fetchall()
            mapping: Dict[str, List[Dict[str, str]]] = {}
            for r in wh_rows:
                gkey = _match_group(_norm(r["wh_id"]), _norm(r["wh_name"]))
                mapping.setdefault(gkey, []).append(
                    {"warehouse_id": _norm(r["wh_id"]), "warehouse_name": _norm(r["wh_name"])})
            for g in ROW_GROUPS + [{"key": OTHERS_KEY, "label": OTHERS_LABEL}]:
                groups_meta.append({
                    "key": g["key"], "label": g["label"],
                    "warehouses": mapping.get(g["key"], []),
                })
        except Exception:
            logger.warning("[SILENT-EXCEPT] get_material_summary: warehouse mapping failed", exc_info=True)
            groups_meta = [{"key": g["key"], "label": g["label"], "warehouses": []}
                           for g in ROW_GROUPS + [{"key": OTHERS_KEY, "label": OTHERS_LABEL}]]

        def _cell(d: str, gkey: str, field: str) -> int:
            return int((agg.get(d, {}).get(gkey) or {}).get(field, 0))

        def _build_row(gkey: str, label: str) -> Dict[str, Any]:
            a_spare = _cell(anchor, gkey, "spare_good")
            a_cons = _cell(anchor, gkey, "consumables")
            c_spare = _cell(current, gkey, "spare_good")
            c_cons = _cell(current, gkey, "consumables")
            m_spare = _cell(month_start, gkey, "spare_good")
            m_cons = _cell(month_start, gkey, "consumables")
            w_spare = _cell(week_start, gkey, "spare_good")
            w_cons = _cell(week_start, gkey, "consumables")
            a_total = a_spare + a_cons
            c_total = c_spare + c_cons
            return {
                "key": gkey,
                "label": label,
                "anchor_spare_good": a_spare,
                "anchor_consumables": a_cons,
                "current_spare_good": c_spare,
                "current_consumables": c_cons,
                "need_repair": _cell(current, gkey, "damage"),
                "repair_outbound": int(ob_map.get(gkey, 0)),
                # 三个消耗窗口 × 两个物料大类（拆分后相加 = 下面的整列合计）
                "consumption_from_anchor_spare": a_spare - c_spare,
                "consumption_from_anchor_cons": a_cons - c_cons,
                "consumption_month_spare": m_spare - c_spare,
                "consumption_month_cons": m_cons - c_cons,
                "consumption_week_spare": w_spare - c_spare,
                "consumption_week_cons": w_cons - c_cons,
                # 整列合计（= 上面两个子列之和，保留供旧调用方与自洽校验）
                "consumption_from_anchor": a_total - c_total,
                "consumption_month": (m_spare + m_cons) - c_total,
                "consumption_week": (w_spare + w_cons) - c_total,
                # 供前端 tooltip / 校验用
                "anchor_total": a_total,
                "current_total": c_total,
            }

        # 数据里真实出现过的分组 + Others（Others 全 0 时隐藏）
        present = {k for d in agg.values() for k in d.keys()}
        ordered_keys = [g["key"] for g in ROW_GROUPS if g["key"] in present]
        rows = [_build_row(k, next(g["label"] for g in ROW_GROUPS if g["key"] == k))
                for k in ordered_keys]
        missing = [g["label"] for g in ROW_GROUPS if g["key"] not in present]
        if missing:
            warnings.append("以下分组在库中暂无数据，已按 0 处理：" + "、".join(missing))

        if OTHERS_KEY in present:
            o_row = _build_row(OTHERS_KEY, OTHERS_LABEL)
            if o_row["current_total"] or o_row["anchor_total"]:
                rows.append(o_row)
                warnings.append(
                    "存在未归入 1st/2nd WH、Gbarnga/Kweaken DOP 的仓库（见 Others 行），"
                    "已单独列出并计入 Total")

        # 合计行 = 所有分组之和（含 Others），保证 Total 与明细自洽
        total: Dict[str, Any] = {"key": "total", "label": "Total", "is_total": True}
        for k in SUM_KEYS:
            total[k] = 0
        for r in rows:
            for k in SUM_KEYS:
                total[k] += r[k]
        rows.append(total)

        # 消耗为负 = 期末比期初还多（入库回补 / 调拨进仓），如实提示
        negatives = [r["label"] for r in rows
                     if not r.get("is_total") and (r["consumption_from_anchor"] < 0
                                                   or r["consumption_month"] < 0
                                                   or r["consumption_week"] < 0)]
        if negatives:
            warnings.append("以下分组出现「消耗为负」（期末库存高于期初，通常为入库回补或调拨进仓）："
                            + "、".join(negatives))

        result = {
            "anchor_date": anchor,
            "anchor_date_requested": want_anchor,
            "current_date": current,
            "month_start": month_start,
            "week_start": week_start,
            "latest_snapshot": latest,
            "repair_outbound_start": ob_start,
            "repair_outbound_end": ob_end,
            "row_groups": groups_meta,
            "rows": rows,
            "warnings": warnings,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        base = dict(result)
        base["_base_warnings"] = warnings
        _cache_put(cache_key, base)
        return result
    finally:
        try:
            conn.close()
        except Exception:
            logger.warning("[SILENT-EXCEPT] get_material_summary: close failed", exc_info=True)


# ---------- 单元格下钻 ----------
def _detail_snapshot(conn, cols: Dict[str, str], summary: Dict[str, Any], scope: str,
                     row_key: str, label: str, want_groups: Optional[set],
                     warnings: List[str], limit: int) -> Dict[str, Any]:
    """快照类下钻：直接取某一日快照的物料行。"""
    spec = _SCOPES[scope]
    d = summary["anchor_date"] if spec["date"] == "anchor" else summary["current_date"]
    sql = (f'SELECT * FROM {TABLE} WHERE "{cols[C_DATE]}" = ? '
           f'ORDER BY "{cols[C_WH_NAME]}", "{cols[C_TYPE]}", "{cols[C_QTY]}" DESC')
    try:
        rows = conn.execute(sql, (d,)).fetchall()
    except Exception as e:
        logger.warning("[SILENT-EXCEPT] _detail_snapshot: query failed", exc_info=True)
        return {"title": "Material Detail", "columns": [], "data": [],
                "warnings": warnings + [f"查询失败: {e}"]}

    data: List[Dict[str, Any]] = []
    truncated = False
    for row in rows:
        gkey = _match_group(_norm(row[cols[C_WH_ID]]), _norm(row[cols[C_WH_NAME]]))
        if want_groups is not None and gkey not in want_groups:
            continue
        mtype = _norm(row[cols[C_TYPE]]).lower()
        mstatus = _norm(row[cols[C_STATUS]]).lower()
        if spec["type"] == "spare" and SPARE_TOKEN not in mtype:
            continue
        if spec["type"] == "consumable" and CONSUMABLE_TOKEN not in mtype:
            continue
        if spec["status"] == "good" and mstatus == DAMAGE_STATUS:
            continue
        if spec["status"] == "damage" and mstatus != DAMAGE_STATUS:
            continue
        rec: Dict[str, Any] = {}
        for k in row.keys():
            v = row[k]
            if isinstance(v, bytes):
                v = v.decode("utf-8", errors="ignore")
            rec[k] = "" if v is None else v
        data.append(rec)
        if len(data) >= limit:
            truncated = True
            break

    if truncated:
        warnings.append(f"明细超过 {limit} 行，已截断（请用搜索框缩小范围或导出后筛选）")

    columns = list(data[0].keys()) if data else []
    return {
        "title": f"Material Detail · {label} · {d}",
        "row_key": row_key,
        "scope": scope,
        "date": d,
        "columns": columns,
        "data": data,
        "warnings": warnings,
    }


def _detail_consumption(conn, cols: Dict[str, str], summary: Dict[str, Any], scope: str,
                        row_key: str, label: str, want_groups: Optional[set],
                        warnings: List[str], limit: int) -> Dict[str, Any]:
    """消耗类下钻：期初 vs 期末逐物料对比。

    消耗量 = 期初数量 − 期末数量（正数=净消耗，负数=入库回补/调拨进仓）。
    只列「有变化」的料号（期初 == 期末的不展示），按消耗量降序。
    Spare Part 两侧都排除 Material Status = 'damage'，与汇总列口径保持一致。
    """
    spec = _CONSUMPTION_SCOPES[scope]
    start = {"anchor": summary["anchor_date"],
             "month": summary["month_start"],
             "week": summary["week_start"]}[spec["window"]]
    end = summary["current_date"]

    # 注意：PG 模式下 database._qmark_to_pyformat 会**跳过字符串字面量**，
    # 所以 SQL 里直接写 LIKE '%spare%' 时那个 % 不会被转义 → psycopg2 把 %s 当占位符
    # → IndexError。必须把通配符放进**参数值**里，用 LIKE ? 。
    type_sql = f'AND LOWER(COALESCE("{cols[C_TYPE]}", \'\')) LIKE ? '
    type_params: List[str] = [f"%{SPARE_TOKEN}%"] if spec["type"] == "spare" \
        else [f"%{CONSUMABLE_TOKEN}%"]
    if spec["type"] == "spare":
        type_sql += f'AND LOWER(COALESCE("{cols[C_STATUS]}", \'\')) <> ? '
        type_params.append(DAMAGE_STATUS)
    elif spec["type"] != "consumable":
        type_sql = ""
        type_params = []

    sql = (
        f'SELECT COALESCE("{cols[C_WH_ID]}", \'\') AS wh_id, '
        f'COALESCE("{cols[C_WH_NAME]}", \'\') AS wh_name, '
        f'COALESCE("{cols[C_MNO]}", \'\') AS mno, '
        f'COALESCE("{cols[C_MNAME]}", \'\') AS mname, '
        f'COALESCE("{cols[C_TYPE]}", \'\') AS mtype, '
        f'SUM(CASE WHEN "{cols[C_DATE]}" = ? THEN COALESCE("{cols[C_QTY]}", 0) ELSE 0 END) '
        f'    AS opening_qty, '
        f'SUM(CASE WHEN "{cols[C_DATE]}" = ? THEN COALESCE("{cols[C_QTY]}", 0) ELSE 0 END) '
        f'    AS closing_qty '
        f'FROM {TABLE} WHERE "{cols[C_DATE]}" IN (?, ?) {type_sql} '
        f'GROUP BY 1, 2, 3, 4, 5'
    )
    try:
        rows = conn.execute(sql, tuple([start, end, start, end] + type_params)).fetchall()
    except Exception as e:
        logger.warning("[SILENT-EXCEPT] _detail_consumption: query failed", exc_info=True)
        return {"title": "Material Detail", "columns": [], "data": [],
                "warnings": warnings + [f"查询失败: {e}"]}

    data: List[Dict[str, Any]] = []
    for row in rows:
        gkey = _match_group(_norm(row["wh_id"]), _norm(row["wh_name"]))
        if want_groups is not None and gkey not in want_groups:
            continue
        try:
            opening = int(row["opening_qty"] or 0)
            closing = int(row["closing_qty"] or 0)
        except (TypeError, ValueError):
            opening, closing = 0, 0
        if opening == closing:
            continue                      # 无变化不进明细
        data.append({
            "Warehouse Name": _norm(row["wh_name"]),
            "Material No.": _norm(row["mno"]),
            "Material Name": _norm(row["mname"]),
            "Material Type": _norm(row["mtype"]),
            "Opening Qty": opening,
            "Closing Qty": closing,
            "Consumption Qty": opening - closing,
        })

    data.sort(key=lambda x: x["Consumption Qty"], reverse=True)
    if len(data) > limit:
        data = data[:limit]
        warnings.append(f"明细超过 {limit} 行，已截断（请用搜索框缩小范围或导出后筛选）")

    return {
        "title": f"Consumption Detail · {label} · {start} → {end}",
        "row_key": row_key,
        "scope": scope,
        "date": f"{start} ~ {end}",
        "opening_date": start,
        "closing_date": end,
        "columns": ["Warehouse Name", "Material No.", "Material Name", "Material Type",
                    "Opening Qty", "Closing Qty", "Consumption Qty"],
        "data": data,
        "warnings": warnings,
    }


def _detail_repair_outbound(conn, summary: Dict[str, Any], row_key: str, label: str,
                            want_groups: Optional[set], warnings: List[str],
                            limit: int) -> Dict[str, Any]:
    """报修出库下钻：outband_details 里当月 Repair Outbound 的行。"""
    cols = _resolve_outband_columns(conn)
    start = summary.get("repair_outbound_start") or f'{summary.get("month_start") or ""} 00:00:00'
    end = summary.get("repair_outbound_end") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        have = {_norm(c) for c in table_columns(conn, OB_TABLE)}
    except Exception:
        logger.warning("[SILENT-EXCEPT] _detail_repair_outbound: 列枚举失败", exc_info=True)
        have = set()
    sel = [c for c in OB_DETAIL_COLS if c in have]
    if not sel:
        return {"title": f"Repair Outbound · {label}", "row_key": row_key,
                "scope": REPAIR_OUTBOUND_SCOPE, "date": f"{start} ~ {end}",
                "columns": [], "data": [],
                "warnings": warnings + [f"{OB_TABLE} 表不存在或缺少可展示的列"]}
    if OB_WH_NAME not in sel:
        sel.insert(0, OB_WH_NAME)

    sel_sql = ", ".join(f'"{c}"' for c in sel)
    sql = (f'SELECT {sel_sql} FROM {OB_TABLE} '
           f'WHERE "{cols[OB_TYPE]}" = ? '
           f'AND CAST("{cols[OB_TIME]}" AS TEXT) >= ? '
           f'AND CAST("{cols[OB_TIME]}" AS TEXT) <= ? '
           f'ORDER BY "{cols[OB_TIME]}" DESC')
    try:
        rows = conn.execute(sql, (REPAIR_OUTBOUND_TYPE, start, end)).fetchall()
    except Exception as e:
        logger.warning("[SILENT-EXCEPT] _detail_repair_outbound: query failed", exc_info=True)
        return {"title": f"Repair Outbound · {label}", "row_key": row_key,
                "scope": REPAIR_OUTBOUND_SCOPE, "date": f"{start} ~ {end}",
                "columns": [], "data": [], "warnings": warnings + [f"查询失败: {e}"]}

    data: List[Dict[str, Any]] = []
    truncated = False
    for row in rows:
        gkey = _match_group("", _norm(row[OB_WH_NAME]))     # 该表没有 Warehouse Id
        if want_groups is not None and gkey not in want_groups:
            continue
        rec: Dict[str, Any] = {}
        for c in sel:
            v = row[c]
            if isinstance(v, bytes):
                v = v.decode("utf-8", errors="ignore")
            rec[c] = "" if v is None else v
        data.append(rec)
        if len(data) >= limit:
            truncated = True
            break

    if truncated:
        warnings.append(f"明细超过 {limit} 行，已截断（请用搜索框缩小范围或导出后筛选）")

    return {
        "title": f"Repair Outbound · {label} · {start[:10]} → {end[:10]}",
        "row_key": row_key,
        "scope": REPAIR_OUTBOUND_SCOPE,
        "date": f"{start} ~ {end}",
        "columns": sel,
        "data": data,
        "warnings": warnings,
    }


def get_material_detail(row_key: str, scope: str,
                        anchor_date: Optional[str] = None,
                        current_date: Optional[str] = None,
                        limit: int = 2000) -> Dict[str, Any]:
    """返回某个统计格子背后的明细（用于看板数字下钻）。

    三类 scope，分派到三个实现：
      1. 快照类（_SCOPES）              —— 某一日的库存行
      2. 消耗类（_CONSUMPTION_SCOPES）  —— 期初 vs 期末逐物料对比
      3. repair_outbound                —— outband_details 里当月报修出库的行

    非法参数走「200 + warnings 软失败」，不抛 5xx。
    """
    warnings: List[str] = []
    summary = get_material_summary(anchor_date, current_date)
    warnings.extend(summary.get("warnings") or [])
    if not summary.get("rows"):
        return {"title": "Material Detail", "columns": [], "data": [], "warnings": warnings}

    if scope not in _SCOPES and scope not in _CONSUMPTION_SCOPES \
            and scope != REPAIR_OUTBOUND_SCOPE:
        return {"title": "Material Detail", "columns": [], "data": [],
                "warnings": warnings + [f"未知 scope: {scope}"]}

    group_keys = [g["key"] for g in ROW_GROUPS] + [OTHERS_KEY]
    if row_key == "total":
        want_groups: Optional[set] = None          # None = 全部仓库
    elif row_key in group_keys:
        want_groups = {row_key}
    else:
        return {"title": "Material Detail", "columns": [], "data": [],
                "warnings": warnings + [f"未知 row_key: {row_key}"]}

    label = next((r["label"] for r in summary["rows"] if r["key"] == row_key), row_key)

    conn = get_raw_connection(str(DB_PATH))
    try:
        cols = _resolve_columns(conn)
        if scope == REPAIR_OUTBOUND_SCOPE:
            return _detail_repair_outbound(conn, summary, row_key, label,
                                           want_groups, warnings, limit)
        if scope in _CONSUMPTION_SCOPES:
            return _detail_consumption(conn, cols, summary, scope, row_key, label,
                                       want_groups, warnings, limit)
        return _detail_snapshot(conn, cols, summary, scope, row_key, label,
                                want_groups, warnings, limit)
    finally:
        try:
            conn.close()
        except Exception:
            logger.warning("[SILENT-EXCEPT] get_material_detail: close failed", exc_info=True)

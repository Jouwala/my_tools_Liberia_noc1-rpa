"""SP 备件 / 耗材汇总报表（Inbound & Outbound & Inventory）数据服务。

数据源
------
``data/sp_email`` 下由任务 ``sp_report_generate``（SP 备件报表生成，每天 05:15）
产出的两份**汇总工作簿**：

    SpareParts  Inbound&Outbound&Inventory <YYYY-MM-DD HH-MM-SS>.xlsx   -> kind="spareparts"
    Comsumables Inbound&Outbound&Inventory <YYYY-MM-DD HH-MM-SS>.xlsx   -> kind="consumables"

两份工作簿结构完全一致，各含 5 张 sheet：

    Summary-Current   物料级汇总（入库/出库/库存 + 补库建议）
    Summary-Changed   按「天 × 仓库」的入出库矩阵
    Inbound           入库明细
    Outbound          出库明细
    Inventory         库存明细

因此本服务按 ``kind`` 参数化，而不是复制两份几乎相同的代码；两个页面
（``?page=sp_report`` / ``?page=com_report``）共用同一个 service / router。

同目录还有 4 份**按仓库拆分**的同名文件（``… - Liberia Gbarnga … .xlsx``）与
PNG 截图，都不属于本页数据源 —— 汇总工作簿的文件名是「前缀 + 纯时间戳」，
据此用正则区分（见 ``_consolidated_re``），不靠「排除某个仓库名」的脆弱写法。

⚠️ 这份报表的**表头不在第 1 行**：每张 sheet 前面有若干行标题 / 口径说明
（明细 3 行、汇总 7 行、矩阵 3 行 + 1 行分组头），读取时必须按 ``SHEET_CONFIG``
的 ``header_row`` 偏移，否则会把说明行当数据行。

统计口径
--------
- Summary-Current：表头下第 1 行是 ``Total`` 行（口径由生成端保证），
  卡片上的入/出/库存/差异/补库量直接取它；物料种类 = Total 行之外的行数。
  ``Outbound Qty`` 右侧另有生成端拆出的 ``Outbound Site Qty``（站点出库）与
  ``Outbound Repair Qty``（报修出库，Outbound Type = Repair Outbound），
  二者之和恒等于 ``Outbound Qty``；本服务按表头名动态读列，无需为它们写专门的代码
  （生成端口径见 ``sp_report_gen/gernarate_sp_report.build_summary``）。
- 告警分布：``Alert Level`` ∈ {Urgent Replenish, Replenish, Redundant}；
  ``Remark`` ∈ {Failure Rate, Actual Consumption}。
- 明细 sheet 的数量合计：Inbound=Inbound Qty、Outbound=Outbound Qty、
  Inventory=Stock Qty。
- **未关闭单（2026-10-18 改口径）** = 按单据号（``Inbound No.`` / ``Outbound No.``）
  **去重**后的未关闭单数，谓词与词表来自 :mod:`backend.services.sp_common`
  （剔除 ``WaitingForUpdate`` 等未生效状态）。此前是「Status 不含 'closed' 的
  **行数**」，而明细表一单多物料多行，于是卡片上的数字被系统性高估。
  并且 Inbound / Outbound 两项的 open_count **直接取 DB**（由
  :func:`_overlay_db_open_counts` 覆盖），与 MsPortal QC 面板的 SPMS 大数字
  同源同时点；其余 sheet 仍由本文件解析的 Excel 快照算出。

仓库消耗汇总（``get_summary`` 的 ``warehouse_summary`` / ``frequent_materials``）
--------------------------------------------------------------------------
这两块服务于「仓库汇总报表」页面（``?page=warehouse_summary``），结构对齐
``WarehouseSummaryReport.xlsx`` 的两段表。**数据源仍是同一份工作簿**，不做二次采集。

- ``warehouse_summary``：「WH/DOP × 库存/消耗」表。每行一个仓库/ DOP：
  ``current_inventory`` 取 ``Inventory`` sheet 按 ``Warehouse Name`` 的 ``Stock Qty`` 合计；
  ``total_consumption`` / ``month_consumption`` / ``week_consumption`` 取 ``Outbound`` sheet
  按 ``Warehouse Name`` 的 ``Outbound Qty`` 合计，后两者按**请求时刻**的时间窗过滤。
  ⚠️ 时间窗是**运行时**口径（今天所在的本周/本月），不是工作簿的生成时口径 ——
  Excel 的 "This month / This week" 同样是打开报表时算的，两者语义一致。
  时间取 ``Outbound Time``，为空回落 ``Create Time``（``OUTBOUND_TIME_COLUMNS``）；
  两者都为空的行**不计入**任何期间合计（不猜时间），但会进入 ``total_consumption``，
  因此 ``month/week <= total`` 恒成立。末尾附加一行 ``Total``，由后端算，
  **不交给前端二次求和**（否则页面与接口口径容易漂移）。
  这两个时间窗的**起点**随 ``get_summary`` 的 ``period_starts`` 一并下发，供前端下钻
  复用同一口径（见 ``_parse_time_filters`` 的 ``@gte`` 算子）。
- ``frequent_materials``：「高频消耗物料」表。取 ``Summary-Current`` 的行，
  按 ``Consumption Qty`` 降序**全量返回**（页面每 10 行分页显示所有物料）。
  ``top_n``（= ``FREQUENT_TOP_N``）只作为"排在最前的若干条"的展示提示，
  **不用于截断** ``rows`` —— 否则分页翻不到后面的物料。
  ⚠️ ``Consumption Qty`` 映射到 **``Outbound Site Qty``**（站点出库），不是 ``Outbound Qty``：
  后者含报修出库与两张异常单据，与补库口径不一致；``Outbound Site Qty``
  才是"真正发到站点的消耗"。上游若缺该列（旧工作簿）则回落到 ``Outbound Qty``，
  不静默变成 0。``Total`` 行是**全量**合计，与 ``rows`` 同为全量口径，两者天然自洽。
"""
from __future__ import annotations

import json
import logging
import re
import threading
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.services.sp_common import (
    SP_SHEET_DOC_COLUMN,
    count_open_docs,
    count_open_docs_rows,
)

logger = logging.getLogger(__name__)

# .../Task/my_app
MY_APP_DIR = Path(__file__).resolve().parent.parent.parent
SP_EMAIL_DIR = MY_APP_DIR / "data" / "sp_email"

#: 支持的报表种类。``prefix`` 必须与生成端写出的文件名前缀逐字一致
#: （注意生成端把 Consumables 拼成了 "Comsumables"，这里照抄，不要"顺手修正"，
#:  否则正则匹配不到文件）。
REPORT_KINDS: Dict[str, Dict[str, str]] = {
    "spareparts": {
        "prefix": "SpareParts Inbound&Outbound&Inventory",
        "label_en": "SpareParts",
        "label_zh": "备件",
    },
    "consumables": {
        "prefix": "Comsumables Inbound&Outbound&Inventory",
        "label_en": "Consumables",
        "label_zh": "耗材",
    },
}
DEFAULT_KIND = "spareparts"


def normalize_kind(kind: Optional[str]) -> str:
    """非法/缺失的 kind 一律回落到 spareparts（页面不该因为一个参数 500）。"""
    k = (kind or "").strip().lower()
    return k if k in REPORT_KINDS else DEFAULT_KIND


def _consolidated_re(kind: str) -> "re.Pattern[str]":
    """汇总工作簿文件名：前缀 + 纯时间戳（按仓库拆分的文件含 " - <仓库名>"，不匹配）。"""
    prefix = re.escape(REPORT_KINDS[kind]["prefix"])
    return re.compile(rf"^{prefix} \d{{4}}-\d{{2}}-\d{{2}} \d{{2}}-\d{{2}}-\d{{2}}\.xlsx$")


#: 各 sheet 的读取配置
#:   header_row        表头所在行（0 基）
#:   title_rows        表头之前的标题/说明行数
#:   has_total         表头下第 1 行是否为 Total 行
#:   group_header_row  两行表头的分组行（矩阵专用）
SHEET_CONFIG: Dict[str, Dict[str, Any]] = {
    "Summary-Current": {"header_row": 7, "title_rows": 7, "has_total": True},
    "Summary-Changed": {"header_row": 4, "title_rows": 3, "group_header_row": 3},
    "Inbound": {"header_row": 3, "title_rows": 3},
    "Outbound": {"header_row": 3, "title_rows": 3},
    "Inventory": {"header_row": 3, "title_rows": 3},
}

#: sheet 展示顺序（与工作簿一致）
SHEET_ORDER: Tuple[str, ...] = (
    "Summary-Current", "Summary-Changed", "Inbound", "Outbound", "Inventory",
)

#: 各 sheet 卡片/导出用的主数量列（矩阵没有单一数量列）
QTY_COLUMN: Dict[str, str] = {
    "Summary-Current": "Inventory Qty",
    "Inbound": "Inbound Qty",
    "Outbound": "Outbound Qty",
    "Inventory": "Stock Qty",
    "Summary-Changed": "",
}

#: 各 sheet 的业务时间列（取第一个有值的列的最大值作为数据新鲜度）
TIME_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "Inbound": ("Inbound Time", "Create Time"),
    "Outbound": ("Outbound Time", "Create Time"),
}

#: 筛选下拉候选列（按 sheet 分别声明；不存在的列自动跳过 —— 两种报表的明细
#: 列并不完全相同，例如 Consumables 的 Inbound 没有 Material Type）
FILTER_COLUMNS: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "Summary-Current": (
        ("Domain", "domain"),
        ("Remark", "remark"),
        ("Alert Level", "alertLevel"),
    ),
    "Inbound": (
        ("Status", "status"),
        ("Inbound Type", "inboundType"),
        ("Warehouse Name", "warehouse"),
        ("Domain", "domain"),
    ),
    "Outbound": (
        ("Status", "status"),
        ("Outbound Type", "outboundType"),
        ("Warehouse Name", "warehouse"),
        ("Domain", "domain"),
        ("Related Ticket Type", "ticketType"),
    ),
    "Inventory": (
        ("Material Status", "materialStatus"),
        ("Warehouse Name", "warehouse"),
        ("Domain", "domain"),
    ),
}

STATUS_COLUMN = "Status"
CLOSED_KEYWORD = "closed"
TOP_N = 12

#: 出库业务时间列的取值优先级（第一个有值的列生效）
OUTBOUND_TIME_COLUMNS: Tuple[str, ...] = ("Outbound Time", "Create Time")

#: 「仓库汇总报表」页面的高频消耗物料条数（Total 行不受此截断影响）
FREQUENT_TOP_N = 10

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 5000


# =============================================================================
# 通用小工具
# =============================================================================
def _to_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _to_num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _json_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _normalize_columns(raw: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen: Counter = Counter()
    for i, c in enumerate(raw):
        name = _to_text(c) or f"Column {i + 1}"
        seen[name] += 1
        out.append(name if seen[name] == 1 else f"{name}#{seen[name]}")
    return out


def _numeric_flags(columns: List[str], rows: List[List[Any]]) -> List[bool]:
    sample = rows[:200]
    flags: List[bool] = []
    for i in range(len(columns)):
        seen = False
        all_num = True
        for r in sample:
            v = r[i] if i < len(r) else None
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            seen = True
            if _to_num(v) is None:
                all_num = False
                break
        flags.append(bool(seen and all_num))
    return flags


class SheetData:
    """一张 sheet 的数据（列名 + 数据行 + 表头上方的说明行）。"""

    __slots__ = ("key", "columns", "rows", "notes", "numeric_flags", "total_row")

    def __init__(self, key: str, columns: List[str], rows: List[List[Any]],
                 notes: List[str], total_row: Optional[List[Any]] = None):
        self.key = key
        self.columns = columns
        self.rows = rows
        self.notes = notes
        self.total_row = total_row
        self.numeric_flags = _numeric_flags(columns, rows)

    def index_of(self, column: str) -> Optional[int]:
        try:
            return self.columns.index(column)
        except ValueError:
            return None


class _Data:
    __slots__ = ("kind", "source", "sheets", "matrix", "warnings")

    def __init__(self, kind: str, source: Dict[str, Any], sheets: Dict[str, SheetData],
                 matrix: Optional[Dict[str, Any]], warnings: List[str]):
        self.kind = kind
        self.source = source
        self.sheets = sheets
        self.matrix = matrix
        self.warnings = warnings


# =============================================================================
# 读取与缓存
# =============================================================================
def latest_consolidated_file(kind: str = DEFAULT_KIND) -> Optional[Path]:
    """某类报表的汇总工作簿（``<前缀> <时间戳>.xlsx``）。"""
    kind = normalize_kind(kind)
    if not SP_EMAIL_DIR.is_dir():
        return None
    pattern = _consolidated_re(kind)
    hits = [p for p in SP_EMAIL_DIR.glob(f"{REPORT_KINDS[kind]['prefix']}*.xlsx")
            if p.is_file() and pattern.match(p.name)]
    if not hits:
        return None
    return max(hits, key=lambda p: p.stat().st_mtime)


def _cache_key(paths: Sequence[Path]) -> Tuple:
    out: List[Any] = []
    for p in paths:
        try:
            st = p.stat()
            out.append((str(p), int(st.st_mtime), int(st.st_size)))
        except OSError:
            out.append((str(p), None, None))
    return tuple(out)


def _build_sheet(key: str, raw_rows: List[List[Any]]) -> Optional[SheetData]:
    """按 SHEET_CONFIG 的偏移把原始行解析成 SheetData。"""
    cfg = SHEET_CONFIG[key]
    header_row = int(cfg["header_row"])
    title_rows = int(cfg["title_rows"])
    if len(raw_rows) <= header_row:
        return None

    notes = [n for n in (_to_text(r[0]) for r in raw_rows[:title_rows]) if n]
    columns = _normalize_columns(raw_rows[header_row])

    body = raw_rows[header_row + 1:]
    total_row: Optional[List[Any]] = None
    if cfg.get("has_total") and body:
        # 生成端保证 Total 行紧跟表头；用首列是否为 "Total" 再确认一次，
        # 免得某天格式变了把合计行当物料行统计进「物料种类」。
        if _to_text(body[0][0] if body[0] else "").lower() == "total":
            total_row = list(body[0])
            body = body[1:]

    rows: List[List[Any]] = []
    for raw in body:
        if raw is None:
            continue
        row = list(raw)
        if all(c is None or (isinstance(c, str) and not c.strip()) for c in row):
            continue
        if len(row) < len(columns):
            row.extend([None] * (len(columns) - len(row)))
        rows.append(row)

    if not columns:
        return None
    return SheetData(key, columns, rows, notes, total_row)


def _build_matrix(raw_rows: List[List[Any]]) -> Optional[Dict[str, Any]]:
    """解析 Summary-Changed 的「天 × 仓库」矩阵。

    第 group_header_row 行是分组头（WH&DOP | Inbound | Outbound），
    表头行是仓库名（前 n 列入库、后 m 列出库），之后每行一个日期。
    """
    cfg = SHEET_CONFIG["Summary-Changed"]
    grow = int(cfg["group_header_row"])
    hrow = int(cfg["header_row"])
    if len(raw_rows) <= hrow:
        return None

    group = [_to_text(c) for c in raw_rows[grow]]
    header = [_to_text(c) for c in raw_rows[hrow]]

    inbound_wh: List[str] = []
    outbound_wh: List[str] = []
    current = ""
    for i in range(1, len(header)):
        g = group[i] if i < len(group) else ""
        if g:
            current = g
        name = header[i] or current
        if current.lower().startswith("inbound"):
            inbound_wh.append(name)
        elif current.lower().startswith("outbound"):
            outbound_wh.append(name)

    rows: List[Dict[str, Any]] = []
    n_in = len(inbound_wh)
    for raw in raw_rows[hrow + 1:]:
        if not raw:
            continue
        label = _to_text(raw[0])
        if not label:
            continue
        in_vals = [_to_num(raw[1 + i]) or 0.0 for i in range(n_in)]
        out_vals = [_to_num(raw[1 + n_in + i]) or 0.0 for i in range(len(outbound_wh))]
        rows.append({
            "day": label,
            "inbound": in_vals,
            "outbound": out_vals,
            "inbound_total": round(sum(in_vals), 2),
            "outbound_total": round(sum(out_vals), 2),
        })

    if not rows:
        return None
    return {
        "label": "WH&DOP",
        "inbound_warehouses": inbound_wh,
        "outbound_warehouses": outbound_wh,
        "rows": rows,
        "inbound_total": round(sum(r["inbound_total"] for r in rows), 2),
        "outbound_total": round(sum(r["outbound_total"] for r in rows), 2),
    }


def _read(kind: str, path: Path) -> _Data:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    warnings: List[str] = []
    raw: Dict[str, List[List[Any]]] = {}
    try:
        for key in SHEET_ORDER:
            if key not in wb.sheetnames:
                warnings.append(f"工作簿缺少 sheet：{key}")
                continue
            ws = wb[key]
            # 防御「未声明 dimension → read_only 把整表读成 1 列」（同 sp_details_service）
            reset = getattr(ws, "reset_dimensions", None)
            if callable(reset):
                reset()
            raw[key] = [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()

    sheets: Dict[str, SheetData] = {}
    for key in SHEET_ORDER:
        if key not in raw:
            continue
        sd = _build_sheet(key, raw[key])
        if sd is None:
            warnings.append(f"sheet {key} 解析为空")
            continue
        sheets[key] = sd

    matrix = _build_matrix(raw["Summary-Changed"]) if "Summary-Changed" in raw else None

    stat = path.stat()
    source = {
        "kind": kind,
        "kind_label_en": REPORT_KINDS[kind]["label_en"],
        "kind_label_zh": REPORT_KINDS[kind]["label_zh"],
        "file": path.name,
        "path": str(path),
        "generated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "size": stat.st_size,
    }
    return _Data(kind, source, sheets, matrix, warnings)


_CACHE_LOCK = threading.Lock()
#: kind -> {"key": cache_key, "data": _Data}
_CACHE: Dict[str, Dict[str, Any]] = {}


def _load(kind: str = DEFAULT_KIND, force: bool = False) -> _Data:
    kind = normalize_kind(kind)
    path = latest_consolidated_file(kind)
    if path is None:
        raise FileNotFoundError(
            f"未找到 {REPORT_KINDS[kind]['label_en']} 汇总工作簿"
            f"（{SP_EMAIL_DIR} 下匹配 '{REPORT_KINDS[kind]['prefix']} <时间戳>.xlsx' 的文件）"
        )
    key = _cache_key([path])
    slot = _CACHE.get(kind)
    if not force and slot and slot.get("key") == key and slot.get("data") is not None:
        return slot["data"]
    data = _read(kind, path)
    with _CACHE_LOCK:
        _CACHE[kind] = {"key": key, "data": data}
    return data


def invalidate_cache(kind: Optional[str] = None) -> None:
    """清空解析缓存（测试 / 排障用；正常请求靠 mtime 自动失效）。"""
    with _CACHE_LOCK:
        if kind is None:
            _CACHE.clear()
        else:
            _CACHE.pop(normalize_kind(kind), None)


# =============================================================================
# 统计
# =============================================================================
def _counter_top(values: Iterable[str], top: int = TOP_N) -> List[Dict[str, Any]]:
    c = Counter(v for v in values if v)
    return [{"value": k, "count": v} for k, v in c.most_common(top)]


def _column_values(sd: SheetData, column: str) -> List[str]:
    i = sd.index_of(column)
    if i is None:
        return []
    return [_to_text(r[i] if i < len(r) else None) for r in sd.rows]


def _sum_column(sd: SheetData, column: str, rows: Optional[List[List[Any]]] = None) -> float:
    i = sd.index_of(column)
    if i is None:
        return 0.0
    total = 0.0
    for r in (sd.rows if rows is None else rows):
        n = _to_num(r[i] if i < len(r) else None)
        if n is not None:
            total += n
    return total


def _count_open_docs(sd: SheetData) -> int:
    """该 sheet 的**未关闭单据数**（按单据号去重）。

    2026-10-18：口径收敛到 ``sp_common``。此前是「Status 不含 'closed' 的**行数**」，
    而 Inbound/Outbound 是物料明细行 —— 同一张 Outbound No. 会因多件物料拆成
    多行（实测 23 行 / 12 单），卡片上的「未关闭 20」并不是「20 张单」。
    现在与 MsPortal QC 面板（portal_qc）共用同一份词表与同一套按单去重规则。

    - 没有 Status 列的 sheet（Summary 类）→ 0
    - 没有单据号列的 sheet 退化为按行计数（由 sp_common 处理）
    """
    if STATUS_COLUMN not in sd.columns:
        return 0
    status_idx = sd.index_of(STATUS_COLUMN)
    if status_idx is None:
        return 0
    doc_col = SP_SHEET_DOC_COLUMN.get(sd.key)
    doc_idx = sd.index_of(doc_col) if doc_col else None
    return count_open_docs_rows(sd.rows, status_idx, doc_idx)


def _sheet_stats(sd: SheetData) -> Dict[str, Any]:
    qty_col = QTY_COLUMN.get(sd.key, "")
    open_count = _count_open_docs(sd)

    latest_time = ""
    for column in TIME_COLUMNS.get(sd.key, ()):
        vals = [v for v in _column_values(sd, column) if v]
        if vals:
            latest_time = max(vals)
            break

    warehouses: List[str] = []
    for column in ("Warehouse Name", "Original Warehouse Name", "Target Warehouse Name"):
        if column in sd.columns:
            warehouses.extend(_column_values(sd, column))

    return {
        "key": sd.key,
        "records": len(sd.rows),
        "qty_column": qty_col,
        "qty_total": round(_sum_column(sd, qty_col), 2) if qty_col else 0.0,
        "open_count": open_count,
        "warehouse_count": len({w for w in warehouses if w}),
        "domains": _counter_top(_column_values(sd, "Domain"), top=8),
        "columns": sd.columns,
        "latest_time": latest_time,
    }


def _summary_current_stats(sd: SheetData) -> Dict[str, Any]:
    """Summary-Current 的卡片口径：Total 行 + 告警/备注分布。"""
    total = sd.total_row or []

    def tot(col: str) -> float:
        i = sd.index_of(col)
        if i is None or i >= len(total):
            return 0.0
        n = _to_num(total[i])
        return round(n, 2) if n is not None else 0.0

    alerts = _counter_top(_column_values(sd, "Alert Level"), top=10)
    remarks = _counter_top(_column_values(sd, "Remark"), top=10)
    alert_map = {a["value"]: a["count"] for a in alerts}
    remark_map = {r["value"]: r["count"] for r in remarks}

    return {
        "material_count": len(sd.rows),
        "inbound_qty": tot("Inbound Qty"),
        "outbound_qty": tot("Outbound Qty"),
        "inventory_qty": tot("Inventory Qty"),
        "difference": tot("Difference"),
        "avg_monthly": tot("Avg Monthly Consumption"),
        "safety_stock": tot("Safety Stock"),
        "replenishment_qty": tot("Replenishment Qty"),
        "alerts": alerts,
        "remarks": remarks,
        "urgent": alert_map.get("Urgent Replenish", 0),
        "replenish": alert_map.get("Replenish", 0),
        "redundant": alert_map.get("Redundant", 0),
        "failure_rate": remark_map.get("Failure Rate", 0),
        "actual_consumption": remark_map.get("Actual Consumption", 0),
    }


# =============================================================================
# 仓库消耗汇总 / 高频消耗物料（「仓库汇总报表」页面 = WarehouseSummaryReport.xlsx）
# =============================================================================
def _parse_time(raw: Any) -> Optional[datetime]:
    """把单元格里的时间解析成 datetime；解析不了返回 None。

    工作簿里这些列是**日期时间类型**（openpyxl 读出来就是 datetime），
    但也见过被上游导成字符串的情况，所以字符串走一次 ``fromisoformat`` 兜底。
    """
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None
    return None


def _period_starts(now: Optional[datetime] = None) -> Dict[str, datetime]:
    """本周 / 本月的起点（周一为周首，与 Excel 的 "This week" 语义一致）。"""
    now = now or datetime.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())
    month_start = day_start.replace(day=1)
    return {"week": week_start, "month": month_start}


def _outbound_time(row: List[Any], idx: Dict[str, int]) -> Optional[datetime]:
    """按 OUTBOUND_TIME_COLUMNS 的优先级取该行的出库时间。"""
    for column in OUTBOUND_TIME_COLUMNS:
        i = idx.get(column)
        if i is None:
            continue
        t = _parse_time(row[i] if i < len(row) else None)
        if t is not None:
            return t
    return None


def _warehouse_summary(data: _Data, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """「WH/DOP × 库存/消耗」表（含末尾 Total 行）。

    仓库集合取 ``Outbound`` 与 ``Inventory`` 的**并集**：只在一边出现的仓库也出行，
    缺失侧计 0 —— 直接丢弃会让「Total」与各仓之和对不上，用户会当成 bug。
    """
    starts = _period_starts(now)
    outbound = data.sheets.get("Outbound")
    inventory = data.sheets.get("Inventory")

    #: 仓库名 -> 各列累计
    acc: Dict[str, Dict[str, float]] = {}

    def bucket(name: str) -> Dict[str, float]:
        return acc.setdefault(name, {
            "current_inventory": 0.0, "total_consumption": 0.0,
            "month_consumption": 0.0, "week_consumption": 0.0,
        })

    if outbound is not None:
        idx = {c: i for i, c in enumerate(outbound.columns)}
        wi = idx.get("Warehouse Name")
        qi = idx.get("Outbound Qty")
        if wi is not None and qi is not None:
            for r in outbound.rows:
                name = _to_text(r[wi] if wi < len(r) else None)
                if not name:
                    continue
                qty = _to_num(r[qi] if qi < len(r) else None) or 0.0
                b = bucket(name)
                b["total_consumption"] += qty
                t = _outbound_time(r, idx)
                if t is not None:
                    if t >= starts["month"]:
                        b["month_consumption"] += qty
                    if t >= starts["week"]:
                        b["week_consumption"] += qty

    if inventory is not None:
        idx = {c: i for i, c in enumerate(inventory.columns)}
        wi = idx.get("Warehouse Name")
        si = idx.get("Stock Qty")
        if wi is not None and si is not None:
            for r in inventory.rows:
                name = _to_text(r[wi] if wi < len(r) else None)
                if not name:
                    continue
                bucket(name)["current_inventory"] += _to_num(r[si] if si < len(r) else None) or 0.0

    rows: List[Dict[str, Any]] = [
        {
            "warehouse": name,
            "current_inventory": round(v["current_inventory"], 2),
            "total_consumption": round(v["total_consumption"], 2),
            "month_consumption": round(v["month_consumption"], 2),
            "week_consumption": round(v["week_consumption"], 2),
        }
        # 库存多的排前面：一眼看到主仓；同库存按名称稳定排序，避免每次请求顺序漂移
        for name, v in sorted(acc.items(), key=lambda kv: (-kv[1]["current_inventory"], kv[0]))
    ]

    total = {
        "warehouse": "Total",
        "current_inventory": round(sum(r["current_inventory"] for r in rows), 2),
        "total_consumption": round(sum(r["total_consumption"] for r in rows), 2),
        "month_consumption": round(sum(r["month_consumption"] for r in rows), 2),
        "week_consumption": round(sum(r["week_consumption"] for r in rows), 2),
    }
    return [total] + rows


def _frequent_materials(current: Optional[SheetData], top_n: int = FREQUENT_TOP_N) -> Dict[str, Any]:
    """「高频消耗物料」表（Top N + 全量 Total 行）。"""
    if current is None:
        return {"rows": [], "total": None, "top_n": top_n, "consumption_column": ""}

    # Consumption Qty 的口径见模块 docstring：优先 Outbound Site Qty（站点出库）
    consumption_column = ("Outbound Site Qty"
                          if "Outbound Site Qty" in current.columns else "Outbound Qty")
    ci = current.index_of(consumption_column)
    ii = current.index_of("Inventory Qty")
    domain_i = current.index_of("Domain")
    name_i = current.index_of("Material Name")
    alert_i = current.index_of("Alert Level")

    def cell(r: List[Any], i: Optional[int]) -> Any:
        return r[i] if i is not None and i < len(r) else None

    items: List[Dict[str, Any]] = []
    for r in current.rows:
        qty = _to_num(cell(r, ci)) or 0.0
        items.append({
            "domain": _to_text(cell(r, domain_i)),
            "material_name": _to_text(cell(r, name_i)),
            "consumption_qty": round(qty, 2),
            "inventory_qty": round(_to_num(cell(r, ii)) or 0.0, 2),
            "alert_level": _to_text(cell(r, alert_i)),
        })

    # Total 行按**全量**算，再截 Top N —— 否则 Total 会等于前 10 行之和，与报表对不上
    total = {
        "material_name": "Total",
        "consumption_qty": round(sum(i["consumption_qty"] for i in items), 2),
        "inventory_qty": round(sum(i["inventory_qty"] for i in items), 2),
    }
    # 消耗量降序；并列时按物料名排序，保证分页/刷新顺序稳定
    items.sort(key=lambda i: (-i["consumption_qty"], i["material_name"]))
    # rows 返回**全量**（不是 Top N）：页面要分页显示所有物料。
    # top_n 仅作为「页面上按消耗量排在最前的若干条」的展示提示保留，
    # 不能再用它截断 rows —— 否则分页只能翻到前 N 条。
    return {
        "rows": items,
        "total": total,
        "top_n": top_n,
        "consumption_column": consumption_column,
        "material_count": len(items),
    }


def _overlay_db_open_counts(kind: str, sheets: List[Dict[str, Any]]) -> None:
    """用 DB 的「未关闭单据数」覆盖 Excel 快照算出来的 open_count（原地修改）。

    ## 为什么覆盖

    Excel 汇总工作簿由 ``sp_email_details`` 在 05:55 生成（源是 05:15 的 SFTP 下载），
    DB 表由 ``sp_data_sync`` 在 07:00 落库。同一天里，**DB 一定是更新的那份**。
    用户在同一个门户里既会点 MsPortal 的 SPMS 数字（读 DB），也会打开
    ``?page=sp_report`` 看卡片 —— 两边数字若不同，用户只会认为其中一个错了。

    2026-10-18 实测：DB = 12 张未关闭出库单，Excel 快照 = 11 张，差的正是
    05:15~07:00 之间新开的那一张。

    ## 口径

    走 :mod:`backend.services.sp_common` 同一份词表 + ``COUNT(DISTINCT 单号)``，
    与 ``portal_qc._sp_open_counts`` 完全一致。

    ## 只覆盖「未关闭单数」，不动别的统计

    记录数、数量合计、仓库数、Domain 分布全部仍来自 Excel —— 它们是**报表口径**
    （与邮件附件逐行一致），换成 DB 反而会让「页面看到的」与「邮件收到的」不一致。
    只有 open_count 这一项是「实时状态」，才用 DB。

    ## 失败时保持 Excel 原值

    DB 不可达 / 表不存在 / 口径查询报错时**不抛**，保留 Excel 算出的数字并
    log warning —— 卡片宁可显示「稍旧的数字」，也好过整页 500。

    ## 只对备件生效

    ``com_report``（耗材）与备件用的是两套表，当前 DB 里只有备件那两张
    （inband_details / outband_details），耗材的表由别的同步任务落库，
    此处不臆测表名 —— 非备件直接跳过。
    """
    sheet_kind = (sheets[0]["key"] if sheets else "")
    if not sheet_kind:
        return
    # 只处理存在编号列的明细 sheet（Inbound / Outbound）
    targets = {k: v for k, v in SP_SHEET_DOC_COLUMN.items()}
    if not targets:
        return

    try:
        from backend.database import get_raw_connection
        with get_raw_connection() as conn:
            for s in sheets:
                doc_col = targets.get(s["key"])
                if not doc_col:
                    continue
                table = "inband_details" if s["key"] == "Inbound" else "outband_details"
                s["open_count"] = count_open_docs(conn, table, doc_col=doc_col)
                s["open_count_source"] = "db"
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[sp_report] DB 未关闭单数覆盖失败（保留 Excel 快照口径 kind=%s）: %s",
            kind, exc,
        )


def get_summary(kind: str = DEFAULT_KIND) -> Dict[str, Any]:
    """页面统计卡片 + 各 sheet 元信息 + 每日矩阵 + 报表自带口径说明。"""
    data = _load(kind)
    now = datetime.now()
    starts = _period_starts(now)

    sheets = [_sheet_stats(sd) for sd in data.sheets.values()]
    _overlay_db_open_counts(kind, sheets)
    current = data.sheets.get("Summary-Current")
    overview = _summary_current_stats(current) if current is not None else {}
    if overview:
        # 「汇总」这张表的卡片改用 Total 行口径，与页面顶部卡片一致
        for s in sheets:
            if s["key"] == "Summary-Current":
                s["qty_total"] = overview["inventory_qty"]
                s["qty_column"] = "Inventory Qty"

    return {
        "kind": data.kind,
        "kind_label_en": REPORT_KINDS[data.kind]["label_en"],
        "kind_label_zh": REPORT_KINDS[data.kind]["label_zh"],
        "source": data.source,
        "overview": overview,
        "sheets": sheets,
        "matrix": data.matrix,
        # 「仓库汇总报表」页面（?page=warehouse_summary）专用：结构对齐
        # WarehouseSummaryReport.xlsx 的两段表；既有键一个不动，保证 SpReportBase 不受影响
        "warehouse_summary": _warehouse_summary(data, now),
        "frequent_materials": _frequent_materials(current),
        # 段① month/week 两列的时间窗起点。**必须由后端下发**：前端下钻要用它与
        # 概览完全同一时刻的口径去筛明细（下钻铁律），自己算一遍会因为两次请求
        # 跨过零点/跨周而错位。
        "period_starts": {
            "week": starts["week"].isoformat(sep=" "),
            "month": starts["month"].isoformat(sep=" "),
            "outbound_time_column": OUTBOUND_TIME_COLUMNS[0],
        },
        "notes": current.notes if current is not None else [],
        "warnings": data.warnings,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# =============================================================================
# 分页查询
# =============================================================================
def _parse_filters(raw: Optional[str]) -> Dict[str, List[str]]:
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("[sp_report] filters 不是合法 JSON，已忽略: %r", str(raw)[:200])
        return {}
    if not isinstance(obj, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for k, v in obj.items():
        if not isinstance(k, str):
            continue
        vals = [_to_text(x) for x in (v if isinstance(v, (list, tuple)) else [v])]
        vals = [x for x in vals if x]
        if vals:
            out[k] = vals
    return out


def _sort_key(value: Any, numeric: bool):
    if numeric:
        n = _to_num(value)
        return (n is None, n if n is not None else 0.0)
    s = _to_text(value)
    return (s == "", s.lower())


#: 时间区间筛选用到的算子键后缀。``filters`` 里 ``<列>@gte`` / ``<列>@lte``
#: 表示「该时间列 >= / <= 某时刻」，用于下钻时把「本周 / 本月」这类**运行时时间窗**
#: 带进明细查询 —— 否则下钻行数与表格里的数字对不上（见 ``_warehouse_summary``）。
TIME_OP_GTE = "@gte"
TIME_OP_LTE = "@lte"


def _parse_time_filters(raw: Optional[str]) -> Dict[str, Dict[str, datetime]]:
    """从 ``filters`` 里抽出 ``<列>@gte`` / ``<列>@lte`` 形式的时间区间条件。

    返回 ``{列名: {"gte": datetime, "lte": datetime}}``。值解析不出时间就忽略该条
    （宁可少筛也不要筛出空结果 —— 与 ``_parse_filters`` 同样的软失败策略）。
    """
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(obj, dict):
        return {}

    out: Dict[str, Dict[str, datetime]] = {}
    for k, v in obj.items():
        if not isinstance(k, str):
            continue
        for op, suffix in ((TIME_OP_GTE, "gte"), (TIME_OP_LTE, "lte")):
            if not k.endswith(op):
                continue
            column = k[: -len(op)]
            t = _parse_time(v)
            if column and t is not None:
                out.setdefault(column, {})[suffix] = t
    return out


def _row_time(row: List[Any], columns: Sequence[str],
              idx: Dict[str, int]) -> Optional[datetime]:
    """按 ``columns`` 的优先级取该行的时间（第一个有值的列生效）。

    与 ``_outbound_time`` 同一套回落逻辑，但列名可参数化 —— 时间区间筛选要能用于
    任意时间列，而不只是 Outbound 的两列。
    """
    for column in columns:
        i = idx.get(column)
        if i is None:
            continue
        t = _parse_time(row[i] if i < len(row) else None)
        if t is not None:
            return t
    return None


def _filtered_rows(sd: SheetData, q: str, filters: Dict[str, List[str]],
                   time_filters: Optional[Dict[str, Dict[str, datetime]]] = None) -> List[List[Any]]:
    """按精确匹配 + 关键字 + 可选时间区间筛出明细行。

    ``time_filters`` 的列若不在该 sheet 里就跳过（两种报表的列并不完全相同）。
    时间取值走 ``TIME_COLUMNS`` 声明的多列回落，**与概览口径逐条一致** ——
    概览用哪一列算的本周/本月，这里就必须用同一列判区间。
    """
    idx = {c: i for i, c in enumerate(sd.columns)}
    active = [(idx[c], set(vals)) for c, vals in filters.items() if c in idx]
    needle = q.strip().lower()

    #: 生效的时间区间条件：(取值列序列, {gte, lte})
    time_active: List[Tuple[Tuple[str, ...], Dict[str, datetime]]] = []
    for column, bounds in (time_filters or {}).items():
        if column not in idx or not bounds:
            continue
        # 取该列的回落序列（如 Outbound Time -> Create Time）；未声明的列就只看它自己
        columns = TIME_COLUMNS.get(sd.key, ()) if column in TIME_COLUMNS.get(sd.key, ()) else (column,)
        if column not in columns:
            columns = (column,) + tuple(c for c in TIME_COLUMNS.get(sd.key, ()) if c != column)
        time_active.append((columns, bounds))

    out: List[List[Any]] = []
    for r in sd.rows:
        ok = True
        for i, allowed in active:
            if _to_text(r[i] if i < len(r) else None) not in allowed:
                ok = False
                break
        if not ok:
            continue
        for columns, bounds in time_active:
            t = _row_time(r, columns, idx)
            # 时间取不到的行**不计入**任何时间窗（与概览口径一致：不猜时间，
            # 这类行只进 total_consumption，所以 month/week <= total 恒成立）
            if t is None:
                ok = False
                break
            if "gte" in bounds and t < bounds["gte"]:
                ok = False
                break
            if "lte" in bounds and t > bounds["lte"]:
                ok = False
                break
        if not ok:
            continue
        if needle:
            if not any(needle in _to_text(v).lower() for v in r if v is not None):
                continue
        out.append(r)
    return out


def get_rows(
    kind: str = DEFAULT_KIND,
    sheet: str = "",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    q: str = "",
    sort: str = "",
    order: str = "asc",
    filters: Optional[str] = None,
) -> Dict[str, Any]:
    """某 sheet 的分页数据（服务端筛选 + 排序 + 分页）。"""
    data = _load(kind)
    sd = data.sheets.get(sheet)
    if sd is None:
        return {
            "kind": data.kind, "sheet": sheet, "columns": [], "numeric_columns": [],
            "rows": [], "total": 0, "page": 1, "page_size": page_size,
            "qty_column": "", "qty_total": 0, "filtered_qty_total": 0, "notes": [],
            "warnings": [
                f"未知的 sheet：{sheet}（可用：{', '.join(data.sheets) or '无'}）"
            ],
        }

    flt = _parse_filters(filters)
    time_flt = _parse_time_filters(filters)
    matched = _filtered_rows(sd, q, flt, time_flt)

    if sort and sort in sd.columns:
        i = sd.columns.index(sort)
        numeric = sd.numeric_flags[i]
        matched = sorted(
            matched,
            key=lambda r: _sort_key(r[i] if i < len(r) else None, numeric),
            reverse=order.lower() == "desc",
        )

    qty_col = QTY_COLUMN.get(sd.key, "")
    page_size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    total = len(matched)
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(int(page or 1), pages))
    start = (page - 1) * page_size
    chunk = matched[start:start + page_size]

    rows = [
        {sd.columns[i]: _json_value(r[i] if i < len(r) else None)
         for i in range(len(sd.columns))}
        for r in chunk
    ]

    return {
        "kind": data.kind,
        "sheet": sd.key,
        "columns": sd.columns,
        "numeric_columns": [sd.columns[i] for i, f in enumerate(sd.numeric_flags) if f],
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "qty_column": qty_col,
        "qty_total": round(_sum_column(sd, qty_col), 2) if qty_col else 0.0,
        "filtered_qty_total": round(_sum_column(sd, qty_col, matched), 2) if qty_col else 0.0,
        "notes": sd.notes,
        "warnings": [],
    }


def get_filters(kind: str = DEFAULT_KIND, sheet: str = "") -> Dict[str, Any]:
    """某 sheet 的筛选下拉候选值。"""
    data = _load(kind)
    sd = data.sheets.get(sheet)
    if sd is None:
        return {"kind": data.kind, "sheet": sheet, "fields": [],
                "warnings": [f"未知的 sheet：{sheet}"]}

    fields: List[Dict[str, Any]] = []
    for column, label in FILTER_COLUMNS.get(sd.key, ()):
        if column not in sd.columns:
            continue
        options = _counter_top(_column_values(sd, column), top=50)
        if options:
            fields.append({"column": column, "label": label, "options": options})
    return {"kind": data.kind, "sheet": sd.key, "fields": fields, "warnings": []}


def get_sources(kind: str = DEFAULT_KIND) -> List[Dict[str, Any]]:
    data = _load(kind)
    out = [dict(data.source)]
    for sd in data.sheets.values():
        out.append({"sheet": sd.key, "rows": len(sd.rows), "columns": len(sd.columns)})
    return out

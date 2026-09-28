"""SP 备件明细报表（page=sp_details / SpDetailsReport）数据服务。

数据源
------
``data/sp_email/data`` 下由任务 ``sp_email_details``
（SP Spare Parts Details Report Email，见 backend/services/kpi_email_report.py
→ ``run_sp_details_email``）生成的**合并工作簿**：

    SP Details Report YYYY-MM-DD HH-MM-SS.xlsx
      sheet Inventory       <- inventory_details_source.xlsx
      sheet Inbound         <- inband_details_source.xlsx
      sheet Outbound        <- outband_details_source.xlsx
      sheet Transfer        <- transfer_details_source.xlsx
      sheet Transfer Return <- transfer_return_details_source.xlsx（可选，通常为空）

``_source`` 是 sp_report_generate（05:15）Step 1.5 在**任何过滤之前**原样复制的
SFTP 快照，所以本页与邮件附件**含** ``Operation Result Status=Canceled``、
出库 ``Status=WaitingForUpdate`` 以及 ``in&out_exclude.xlsx`` 手工剔除名单里的行
（2026-09-22 起改为这个口径；此前读的是处理过的 ``*_details.xlsx``）。
过滤后的 ``*_details.xlsx`` 仍服务 SpareParts/Comsumables 报表与 sp_online 等下游。

``_prune_sp_details_reports`` 只保留最新一份合并文件，所以「目录里最新的
SP Details Report *.xlsx」就是报表任务最近一次发出去的那一份 —— 页面上
展示的与邮件附件逐行一致（同一份文件，不做二次加工）。

合并文件缺失时回退到同目录的 5 份明细（口径一致，只是分文件存放），
并在 ``warnings`` 里说明；``*_source.xlsx`` 也缺失时逐份回退到过滤后的明细。

统计口径
--------
- 记录数     = 各 sheet 数据行数
- 数量合计   = 各 sheet 数量列求和
               （Inventory=Stock Qty / Inbound=Inbound Qty /
                 Outbound=Outbound Qty / Transfer=Transfer Qty）
- 未关闭单   = ``Status`` 不含 "closed"（大小写不敏感）的行数
               原始快照下会出现 Closed / WaitingForReturn / WaitingForConfirm /
               WaitingForUpdate，未关闭单数因此比旧口径高
- 仓库数     = 各 sheet 仓库列去重（Transfer 取 Original + Target 两侧并集）
- 物料种类   = 各 sheet ``Material No.`` 去重并集

与 MsPortal QC 面板（portal_qc）SPMS 口径的关系（2026-09-20 校正，2026-09-22 更新）
------------------------------------------------------------------------------
- 判据：本页 =「含 'closed' 关键字即已关闭」；portal_qc = 显式词表
  ``NOT IN ('closed','close','done','已关闭','完成','yes','y','1','true')``。
  现网取值上两者等价（只出现 Closed / WaitingForConfirm / WaitingForReturn /
  WaitingForUpdate），将来出现 "WaitingForClose" 这类新枚举才会分叉。
- 范围：portal_qc 显式剔除 ``Status = WaitingForUpdate``（尚未生效的出库单，
  见 portal_qc.SP_IGNORED_WORDS）；本页自 2026-09-22 起读原始快照，**不再剔除它**，
  同一批 WaitingForUpdate 出库单会计入本页的未关闭单。
- 数据落点不同（数字差异的真正来源）：本页 = ``data/sp_email/data`` 下的报表快照
  （sp_email_details 每天 05:55 产出的合并工作簿，源是 05:15 的 SFTP 下载）；
  portal_qc = 数据库表 inband_details / outband_details，由 sp_data_sync 每天 07:00
  从 ``backend/data/sp`` 落库（同样是未过滤的原始导出）。同一份上游数据、两处落点、
  两个刷新时点，所以两边的未关闭单数本来就可以不同。

性能
----
合并工作簿约 1.8MB / 8900 行，按 ``(路径, mtime, size)`` 缓存在进程内存：
文件没变时不重复解析（openpyxl read_only 全量读一次约 1~2 秒）。报表任务
每天生成一份新文件，缓存键随之变化，页面自动看到新数据。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# .../Task/my_app
MY_APP_DIR = Path(__file__).resolve().parent.parent.parent
SP_DETAILS_DIR = MY_APP_DIR / "data" / "sp_email" / "data"

#: 合并工作簿文件名前缀（与 kpi_email_report.run_sp_details_email 一致）
MERGED_GLOB = "SP Details Report *.xlsx"

#: (sheet 名, 明细文件名, 是否必需) —— 与 _merge_sp_details_workbook 的映射逐条一致
SHEET_SOURCES: Tuple[Tuple[str, str, bool], ...] = (
    ("Inventory", "inventory_details.xlsx", True),
    ("Inbound", "inband_details.xlsx", True),
    ("Outbound", "outband_details.xlsx", True),
    ("Transfer", "transfer_details.xlsx", True),
    ("Transfer Return", "transfer_return_details.xlsx", False),
)

#: 原始快照后缀（sp_report_generate Step 1.5 在任何过滤之前复制的一份）
RAW_SUFFIX = "_source"


def _detail_file(fname: str) -> Path:
    """明细文件名 -> 实际读取路径：优先未过滤的 ``*_source.xlsx``，缺失才回退过滤后的明细。

    与 ``kpi_email_report._merge_sp_details_workbook`` 同一套选择规则，保证页面
    （无合并工作簿时走 ``_read_individual``）与邮件附件口径一致。
    """
    root, ext = Path(fname).stem, Path(fname).suffix
    raw = SP_DETAILS_DIR / f"{root}{RAW_SUFFIX}{ext}"
    return raw if raw.is_file() else SP_DETAILS_DIR / fname

#: 各 sheet 的「数量列」——卡片上的数量合计就取这一列
QTY_COLUMN: Dict[str, str] = {
    "Inventory": "Stock Qty",
    "Inbound": "Inbound Qty",
    "Outbound": "Outbound Qty",
    "Transfer": "Transfer Qty",
    "Transfer Return": "Transfer Qty",
}

#: 各 sheet 的状态列 / 物料列 / 大类列（缺列时相关统计自动跳过，不抛异常）
STATUS_COLUMN = "Status"
MATERIAL_NO_COLUMN = "Material No."
MATERIAL_TYPE_COLUMN = "Material Type"

#: 各 sheet 的仓库列（Transfer 是调拨，两侧都要算）
WAREHOUSE_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "Inventory": ("Warehouse Name",),
    "Inbound": ("Warehouse Name",),
    "Outbound": ("Warehouse Name",),
    "Transfer": ("Original Warehouse Name", "Target Warehouse Name"),
    "Transfer Return": ("Original Warehouse Name", "Target Warehouse Name"),
}

#: 各 sheet 的「业务类型」列（卡片的分类明细用）
TYPE_COLUMN: Dict[str, str] = {
    "Inbound": "Inbound Type",
    "Outbound": "Outbound Type",
    "Transfer": "Station Level",
}

#: 各 sheet 的「主时间」列（取最大值作为数据新鲜度）
TIME_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "Inbound": ("Inbound Time", "Create Time"),
    "Outbound": ("Outbound Time", "Create Time"),
    "Transfer": ("Inbound Time", "Outbound Time", "Create Time"),
}

#: 分类统计最多返回几项（页面卡片/筛选下拉都够用，避免长尾把响应撑大）
TOP_N = 12

#: 判定「未关闭」的关键字（大小写不敏感，含即视为已关闭）。
#: ⚠️ 与 portal_qc（MsPortal QC 面板 SPMS）的判据**不同** —— 那边是显式词表，
#: 且额外剔除 WaitingForUpdate；两页数字对不上时先读模块 docstring 的
#: 「与 MsPortal QC 面板（portal_qc）SPMS 口径的关系」一节，不要顺手改这里。
CLOSED_KEYWORD = "closed"

#: 每页默认/最大行数（上限放开到 5000，页面「导出当前筛选结果」一次拉全量）
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 5000


# =============================================================================
# 读取与缓存
# =============================================================================
class SheetData:
    """一个 sheet 的原始数据（列名 + 行）。"""

    __slots__ = ("key", "columns", "rows", "numeric_flags")

    def __init__(self, key: str, columns: List[str], rows: List[List[Any]]):
        self.key = key
        self.columns = columns
        self.rows = rows
        self.numeric_flags = _numeric_flags(columns, rows)

    def index_of(self, column: str) -> Optional[int]:
        try:
            return self.columns.index(column)
        except ValueError:
            return None


class _Data:
    """一次解析的完整结果（若干 sheet + 来源信息）。"""

    __slots__ = ("source", "sheets", "warnings")

    def __init__(self, source: Dict[str, Any], sheets: Dict[str, SheetData], warnings: List[str]):
        self.source = source
        self.sheets = sheets
        self.warnings = warnings


_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {"key": None, "data": None}


def _latest_merged_file() -> Optional[Path]:
    """目录里最新的合并工作簿（按 mtime；报表任务只保留最新一份）。"""
    if not SP_DETAILS_DIR.is_dir():
        return None
    candidates = [p for p in SP_DETAILS_DIR.glob(MERGED_GLOB) if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _cache_key(paths: Sequence[Path]) -> Tuple:
    key: List[Any] = []
    for p in paths:
        try:
            st = p.stat()
            key.append((str(p), int(st.st_mtime), int(st.st_size)))
        except OSError:
            key.append((str(p), None, None))
    return tuple(key)


def _to_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _to_num(v: Any) -> Optional[float]:
    """把单元格值转成数字；空/非数字返回 None（Excel 里数字列常混空串）。"""
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
    """单元格值 → JSON 安全值（日期转 ISO 字符串，其余原样）。"""
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    if isinstance(v, float) and v.is_integer():
        # Excel 里 1.0 这种整数值显示成 "1" 更贴近原表
        return int(v)
    return v


def _numeric_flags(columns: List[str], rows: List[List[Any]]) -> List[bool]:
    """每列是否「数字列」——取前 200 行判断，供前端右对齐/求和。"""
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


def _normalize_columns(raw: Iterable[Any]) -> List[str]:
    """列名去空白；重名自动加 `#2` 后缀（明细里目前没有重名，防御性处理）。"""
    out: List[str] = []
    seen: Counter = Counter()
    for i, c in enumerate(raw):
        name = _to_text(c) or f"Column {i + 1}"
        seen[name] += 1
        out.append(name if seen[name] == 1 else f"{name}#{seen[name]}")
    return out


def _read_sheet(ws) -> SheetData:
    """把一个 openpyxl worksheet 读成 SheetData。

    ⚠️ 必须先 ``reset_dimensions()``：SFTP 下来的原始明细（inventory_details /
    transfer_details）**没有声明 worksheet dimension**，openpyxl 的 read_only
    模式会照着缺失的 dimension 把表算成 1 行 1 列 —— 直接 iter_rows 只会拿到
    一个 'Serial No.' 表头，整张表静默变成空表。reset 后按实际内容取范围。
    """
    reset = getattr(ws, "reset_dimensions", None)
    if callable(reset):
        reset()

    iterator = ws.iter_rows(values_only=True)
    try:
        header = next(iterator)
    except StopIteration:
        return SheetData(ws.title, [], [])
    columns = _normalize_columns(header)
    rows: List[List[Any]] = []
    for raw in iterator:
        if raw is None:
            continue
        row = list(raw)
        # 整行全空（Excel 常见的尾部空行）直接跳过
        if all(c is None or (isinstance(c, str) and not c.strip()) for c in row):
            continue
        if len(row) < len(columns):
            row.extend([None] * (len(columns) - len(row)))
        rows.append(row)
    return SheetData(ws.title, columns, rows)


def _read_merged(path: Path) -> _Data:
    """读取合并工作簿（每个 sheet 一份明细）。"""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets: Dict[str, SheetData] = {}
    warnings: List[str] = []
    try:
        for key, _fname, required in SHEET_SOURCES:
            if key not in wb.sheetnames:
                if required:
                    warnings.append(f"合并工作簿缺少 sheet：{key}")
                continue
            sd = _read_sheet(wb[key])
            if not sd.columns:
                # Transfer Return 常见为 1×1 空表，不算异常
                if required:
                    warnings.append(f"sheet {key} 为空表")
                continue
            sheets[key] = sd
    finally:
        wb.close()

    source = {
        "mode": "merged",
        "file": path.name,
        "path": str(path),
        "generated_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "size": path.stat().st_size,
    }
    return _Data(source, sheets, warnings)


def _read_individual() -> _Data:
    """合并工作簿缺失时，回退读 4 份原始明细（口径一致，只是分文件）。"""
    import openpyxl

    sheets: Dict[str, SheetData] = {}
    warnings: List[str] = []
    paths: List[Path] = []
    filtered_fallback: List[str] = []
    newest = 0.0
    for key, fname, required in SHEET_SOURCES:
        p = _detail_file(fname)
        if not p.is_file():
            if required:
                warnings.append(f"明细源文件缺失：{fname}")
            continue
        if not p.name.endswith(f"{RAW_SUFFIX}.xlsx"):
            filtered_fallback.append(key)
        paths.append(p)
        newest = max(newest, p.stat().st_mtime)
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        try:
            ws = wb[wb.sheetnames[0]]
            sd = _read_sheet(ws)
            sd.key = key  # sheet 名以业务名为准（源文件里 sheet 名可能是 Sheet1）
        finally:
            wb.close()
        if sd.columns:
            sheets[key] = sd
        elif required:
            warnings.append(f"明细 {fname} 为空表")
    # 回退路径必须显式说明：页面上的「数据来源」标签只能看出文件名不同，
    # 这句告诉使用者为什么读的不是邮件附件那份合并工作簿。
    warnings.insert(0, "未找到合并工作簿（SP Details Report *.xlsx），已回退读取同目录的原始明细文件")
    if filtered_fallback:
        warnings.append(
            f"{'、'.join(filtered_fallback)} 缺 *_source.xlsx 原始快照，"
            "读的是过滤后的明细（不含 Canceled / WaitingForUpdate / 剔除名单行）"
        )
    source = {
        "mode": "individual",
        "file": "；".join(p.name for p in paths),
        "path": str(SP_DETAILS_DIR),
        "generated_at": (
            datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M:%S") if newest else ""
        ),
        "size": sum(p.stat().st_size for p in paths),
    }
    return _Data(source, sheets, warnings)


def _load(force: bool = False) -> _Data:
    """取（带缓存）解析结果。"""
    merged = _latest_merged_file()
    if merged is not None:
        key = ("merged",) + _cache_key([merged])
    else:
        key = ("individual",) + _cache_key([_detail_file(f) for _k, f, _r in SHEET_SOURCES])

    if not force:
        with _CACHE_LOCK:
            if _CACHE["key"] == key and _CACHE["data"] is not None:
                return _CACHE["data"]

    data = _read_merged(merged) if merged is not None else _read_individual()
    with _CACHE_LOCK:
        _CACHE["key"] = key
        _CACHE["data"] = data
    return data


# =============================================================================
# 统计
# =============================================================================
def _counter_top(values: Iterable[str], top: int = TOP_N) -> List[Dict[str, Any]]:
    c = Counter(v for v in values if v)
    return [{"value": k, "count": v} for k, v in c.most_common(top)]


def _is_open(status: str) -> bool:
    return CLOSED_KEYWORD not in status.lower()


def _sheet_stats(sd: SheetData) -> Dict[str, Any]:
    """单 sheet 的卡片口径统计。"""
    idx = {c: i for i, c in enumerate(sd.columns)}
    rows = sd.rows

    def col_values(column: str) -> List[str]:
        i = idx.get(column)
        if i is None:
            return []
        return [_to_text(r[i] if i < len(r) else None) for r in rows]

    qty_col = QTY_COLUMN.get(sd.key, "")
    qi = idx.get(qty_col) if qty_col else None
    qty_total = 0.0
    qty_rows = 0
    if qi is not None:
        for r in rows:
            n = _to_num(r[qi] if qi < len(r) else None)
            if n is not None:
                qty_total += n
                qty_rows += 1

    statuses = _counter_top(col_values(STATUS_COLUMN))
    open_count = sum(1 for s in col_values(STATUS_COLUMN) if s and _is_open(s))

    warehouses: List[str] = []
    for column in WAREHOUSE_COLUMNS.get(sd.key, ()):
        warehouses.extend(col_values(column))
    warehouse_top = _counter_top(warehouses)

    material_types = _counter_top(col_values(MATERIAL_TYPE_COLUMN))
    domains = _counter_top(col_values("Domain"), top=8)

    type_col = TYPE_COLUMN.get(sd.key, "")
    types = _counter_top(col_values(type_col)) if type_col else []

    # 主时间列：取所有候选列里最大的字符串（ISO 时间串字典序即时间序）
    latest_time = ""
    for column in TIME_COLUMNS.get(sd.key, ()):
        vals = [v for v in col_values(column) if v]
        if vals:
            latest_time = max(vals)
            break

    materials = {v for v in col_values(MATERIAL_NO_COLUMN) if v}
    # Inventory 的 Serial No. 才是唯一实物标识，物料号可能重复
    serials = {v for v in col_values("Serial No.") if v}

    return {
        "key": sd.key,
        "records": len(rows),
        "qty_column": qty_col,
        "qty_total": round(qty_total, 2),
        "qty_rows": qty_rows,
        "open_count": open_count,
        "statuses": statuses,
        "warehouses": warehouse_top,
        "warehouse_count": len({w for w in warehouses if w}),
        "material_types": material_types,
        "domains": domains,
        "types": types,
        "type_column": type_col,
        "distinct_materials": len(materials),
        "distinct_serials": len(serials),
        "latest_time": latest_time,
        "columns": sd.columns,
    }


def get_summary() -> Dict[str, Any]:
    """页面顶部卡片 + 各 sheet 元信息。"""
    data = _load()

    sheets = [_sheet_stats(sd) for sd in data.sheets.values()]
    by_key = {s["key"]: s for s in sheets}

    all_warehouses: set = set()
    all_materials: set = set()
    for sd in data.sheets.values():
        idx = {c: i for i, c in enumerate(sd.columns)}
        for column in WAREHOUSE_COLUMNS.get(sd.key, ()):
            i = idx.get(column)
            if i is None:
                continue
            all_warehouses.update(
                v for v in (_to_text(r[i] if i < len(r) else None) for r in sd.rows) if v
            )
        i = idx.get(MATERIAL_NO_COLUMN)
        if i is not None:
            all_materials.update(
                v for v in (_to_text(r[i] if i < len(r) else None) for r in sd.rows) if v
            )

    overview = {
        "total_records": sum(s["records"] for s in sheets),
        "sheet_count": len(sheets),
        "warehouses": len(all_warehouses),
        "distinct_materials": len(all_materials),
        "open_tickets": sum(s["open_count"] for s in sheets),
        "stock_qty": by_key.get("Inventory", {}).get("qty_total", 0),
        "inbound_qty": by_key.get("Inbound", {}).get("qty_total", 0),
        "outbound_qty": by_key.get("Outbound", {}).get("qty_total", 0),
        "transfer_qty": by_key.get("Transfer", {}).get("qty_total", 0),
    }

    return {
        "source": data.source,
        "overview": overview,
        "sheets": sheets,
        "warnings": data.warnings,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# =============================================================================
# 分页查询
# =============================================================================
def _parse_filters(raw: Optional[str]) -> Dict[str, List[str]]:
    """``filters`` 查询参数：JSON 对象，值为字符串或字符串数组（多选 = IN）。"""
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("[sp_details] filters 不是合法 JSON，已忽略: %r", raw[:200])
        return {}
    if not isinstance(obj, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for k, v in obj.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, (list, tuple)):
            vals = [_to_text(x) for x in v]
        else:
            vals = [_to_text(v)]
        vals = [x for x in vals if x]
        if vals:
            out[k] = vals
    return out


def _sort_key(value: Any, numeric: bool):
    """排序键：数字列按数值、其余按字符串；空值恒排最后（升序时）。"""
    if numeric:
        n = _to_num(value)
        return (n is None, n if n is not None else 0.0)
    s = _to_text(value)
    return (s == "", s.lower())


def _filtered_rows(sd: SheetData, q: str, filters: Dict[str, List[str]]) -> List[List[Any]]:
    rows = sd.rows
    idx = {c: i for i, c in enumerate(sd.columns)}

    active = [(idx[c], set(vals)) for c, vals in filters.items() if c in idx]
    needle = q.strip().lower()

    out: List[List[Any]] = []
    for r in rows:
        ok = True
        for i, allowed in active:
            if _to_text(r[i] if i < len(r) else None) not in allowed:
                ok = False
                break
        if not ok:
            continue
        if needle:
            hit = False
            for v in r:
                if v is None:
                    continue
                if needle in _to_text(v).lower():
                    hit = True
                    break
            if not hit:
                continue
        out.append(r)
    return out


def get_rows(
    sheet: str,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    q: str = "",
    sort: str = "",
    order: str = "asc",
    filters: Optional[str] = None,
) -> Dict[str, Any]:
    """某个 sheet 的分页数据（服务端筛选 + 排序 + 分页）。

    返回 ``columns``（全列，供行详情弹窗用）与当前页 ``rows``（对象数组），
    以及筛选后的 ``filtered_qty_total``（数量列合计，随筛选联动）。
    """
    data = _load()
    sd = data.sheets.get(sheet)
    if sd is None:
        return {
            "sheet": sheet,
            "columns": [],
            "rows": [],
            "total": 0,
            "page": 1,
            "page_size": page_size,
            "qty_column": "",
            "qty_total": 0,
            "filtered_qty_total": 0,
            "warnings": [f"未知的 sheet：{sheet}（可用：{', '.join(data.sheets) or '无'}）"],
        }

    flt = _parse_filters(filters)
    matched = _filtered_rows(sd, q, flt)

    if sort and sort in sd.columns:
        i = sd.columns.index(sort)
        numeric = sd.numeric_flags[i]
        reverse = order.lower() == "desc"
        matched = sorted(matched, key=lambda r: _sort_key(r[i] if i < len(r) else None, numeric),
                         reverse=reverse)

    qty_col = QTY_COLUMN.get(sd.key, "")
    qi = sd.columns.index(qty_col) if qty_col in sd.columns else None
    filtered_qty = 0.0
    sheet_qty = 0.0
    if qi is not None:
        for r in sd.rows:
            n = _to_num(r[qi] if qi < len(r) else None)
            if n is not None:
                sheet_qty += n
        for r in matched:
            n = _to_num(r[qi] if qi < len(r) else None)
            if n is not None:
                filtered_qty += n

    page_size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    total = len(matched)
    pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(int(page or 1), pages))
    start = (page - 1) * page_size
    chunk = matched[start:start + page_size]

    rows = [
        {
            sd.columns[i]: _json_value(r[i] if i < len(r) else None)
            for i in range(len(sd.columns))
        }
        for r in chunk
    ]

    return {
        "sheet": sd.key,
        "columns": sd.columns,
        "numeric_columns": [sd.columns[i] for i, f in enumerate(sd.numeric_flags) if f],
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "qty_column": qty_col,
        "qty_total": round(sheet_qty, 2),
        "filtered_qty_total": round(filtered_qty, 2),
        "warnings": [],
    }


def get_filters(sheet: str) -> Dict[str, Any]:
    """某个 sheet 的筛选下拉候选值（状态 / 仓库 / 大类 / 业务类型 / 域）。"""
    data = _load()
    sd = data.sheets.get(sheet)
    if sd is None:
        return {"sheet": sheet, "fields": [], "warnings": [f"未知的 sheet：{sheet}"]}

    idx = {c: i for i, c in enumerate(sd.columns)}

    def values(column: str) -> List[Dict[str, Any]]:
        i = idx.get(column)
        if i is None:
            return []
        return _counter_top(
            (_to_text(r[i] if i < len(r) else None) for r in sd.rows),
            top=50,
        )

    fields: List[Dict[str, Any]] = []
    for column, label in (
        (STATUS_COLUMN, "status"),
        ("Warehouse Name", "warehouse"),
        (MATERIAL_TYPE_COLUMN, "materialType"),
        (TYPE_COLUMN.get(sd.key, ""), "type"),
        ("Domain", "domain"),
        ("Material Status", "materialStatus"),
    ):
        if not column or column not in idx:
            continue
        opts = values(column)
        if opts:
            fields.append({"column": column, "label": label, "options": opts})

    return {"sheet": sd.key, "fields": fields, "warnings": []}


def get_sources() -> List[Dict[str, Any]]:
    """数据源清单（页面上「数据来源」提示 / 排障用）。"""
    data = _load()
    out = [dict(data.source)]
    for sd in data.sheets.values():
        out.append({"sheet": sd.key, "rows": len(sd.rows), "columns": len(sd.columns)})
    return out


def invalidate_cache() -> None:
    """清空解析缓存（测试 / 排障用；正常请求靠 mtime 自动失效）。"""
    with _CACHE_LOCK:
        _CACHE["key"] = None
        _CACHE["data"] = None


def warmup() -> None:
    """启动期后台预热：先把合并工作簿解析一次。

    _load() 首次要整份读 xlsx（实测 4.7s），之后按文件 mtime/size 缓存。
    后端每次重启缓存都为空，于是这 4.7s 冷成本就落在第一个打开
    ``?page=sp_details`` 的用户头上（实测该页 5.3s）。预热后首访约 0.5s。
    """
    def _job() -> None:
        try:
            t0 = time.time()
            _load(force=True)
            logger.info("[SP详情] 启动预热完成 %.0fms", (time.time() - t0) * 1000)
        except Exception:  # noqa: BLE001  预热失败不能影响启动
            logger.warning("[SP详情] 启动预热失败（不影响启动）", exc_info=True)

    threading.Thread(target=_job, name="sp-details-warmup", daemon=True).start()

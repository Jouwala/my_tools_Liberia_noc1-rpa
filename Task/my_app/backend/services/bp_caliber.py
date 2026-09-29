# -*- coding: utf-8 -*-
"""BP Report —— 口径层：BP 判定阈值、周期判定规则与脏值词表。

**本模块是 BP 口径的唯一真相源。** 导入（Excel 历史）与更新（RAN_UME 重算）
都从这里取阈值，这是「Excel 值与重算值可对账」的根本保证。改口径只改这里。

=========================== 业务口径（用户 2026-09-29 提供） ===========================

BP = Best Performance 小区。**Excel 只存结果**（Number of BP cells / BP ratio /
BP Cells List），判定规则不在文件里，由用户口头提供，逐字转写如下：

Daily：
    Average DL Active User Number > 2.5
    AND
    [FDD]DL IP Throughput(Mbps)[SDR_ITBBU] < 3
    AND
    [FDD]DL PRB Utilization Rate[SDR_ITBBU] > 80%

Weekly：
    If a cell is BP is 4 / 7 days in a week

Monthly：
    If a cell is BP in 3 / 4 full weeks of the month

=====================================================================================

⚠️ **已知缺口：`Average DL Active User Number` 当前采集不到。**

`Task\\RAN\\db.sqlite3.4G_Main_Kpi_Cell_Daily` 已含上面三个条件中的两个
（`1638004469342:[FDD]DL PRB Utilization Rate`、`1638004469332:[FDD]DL IP Throughput(Mbps)`），
但只有 `C373200029:Maximum Number of RRC Connection User` —— 那是**峰值**，
不是**平均值**，与 `Average DL Active User Number` 口径不等价。

因此本模块把该指标做成**可配置的 item code**（见 `ACTIVE_USER_ITEM`）：
一旦拿到 UME 侧的真实 item code，只需在 `main_kpi_config.json` 里加一个码
（Settings → 任务配置可编辑，见 `task_configs_registry.py:403`），**不需要改本文件**。

在拿到之前，`active_user_status()` 会返回「不可判定」，判定函数**不会**默认通过
该条件 —— 宁可少算，不可把不满足条件的算成 BP。
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# 一、BP 判定的三个阈值（Daily）
# ============================================================

# Average DL Active User Number > 2.5
THR_ACTIVE_USER = 2.5

# [FDD]DL IP Throughput(Mbps) < 3
THR_DL_THROUGHPUT_MBPS = 3.0

# [FDD]DL PRB Utilization Rate > 80%
#: ⚠️ 该列在 RAN_UME 里是**小数比率**（0~1），不是百分数。
#: 实测值域 min=0.0196 / max=0.9751 / avg=0.2723（5845 行样本）——
#: 若按 80 去比，条件永远不成立、BP 数会恒为 0，而且**不报错**。
#: 因此阈值按小数存，比较时用 `> THR_DL_PRB_RATIO`。
THR_DL_PRB_RATIO = 0.80

# ============================================================
# 二、周期判定规则
# ============================================================

# Weekly：一周内 4/7 天为 BP → 该周为 BP
WEEK_BP_DAYS = 4
WEEK_TOTAL_DAYS = 7

# Monthly：一个月内 3/4 个完整周为 BP → 该月为 BP
MONTH_BP_WEEKS = 3
MONTH_TOTAL_WEEKS = 4

# ============================================================
# 三、RAN_UME 侧列名（写死自 4G_Main_Kpi_Cell_Daily 的实际表头）
# ============================================================
# 这些列名在 UME 侧是「{item_id}:{指标名}」拼出来的，落库后即固定字符串。
# 保留完整列名而不是只用 item_id：这样在做 SQL 时一眼能看出取的是哪个指标。
#
# ⚠️ **注意不换行空格**：`E-UTRAN FDD Cell Name` 这个列名里两处分隔符是 `\xa0`
# （U+00A0 NO-BREAK SPACE），不是普通空格 —— 实测远端建表语句为
# `"E-UTRAN\xa0FDD\xa0Cell Name" TEXT`。写成普通空格时 SQLite **不报错**，
# 而是把双引号标识符当字符串字面量返回，于是「小区名」整列变成字面量
# `'E-UTRAN FDD Cell Name'`，5803 行塌缩成 1 个小区的假数据。
# `_NBSP` 就是为了让这一点在源码里可见，同时保留可读的书写形式。
_NBSP = "\xa0"

COL_DAY = "Begin Time"                      # 天粒度时间戳，格式 'YYYY-MM-DD 00:00:00'
COL_CELL_NAME = f"E-UTRAN{_NBSP}FDD{_NBSP}Cell Name"   # 小区名，与 Excel BP Cells List 同源
COL_ME_ID = "ManagedElement ID"             # 网元 ID，数值键（比站点名 join 可靠）
COL_PRB_DL = "1638004469342:[FDD]DL PRB Utilization Rate[SDR_ITBBU]"
COL_THR_DL = "1638004469332:[FDD]DL IP Throughput(Mbps)[SDR_ITBBU]"
COL_DL_GB = "1638004469330:[FDD]DL Traffic Volume (GBytes)-new"
COL_UL_GB = "1638004469331:[FDD]UL Traffic Volume (GBytes)-new"

#: `Average DL Active User Number` —— **远端表里没有这一列**。
#: 已用 `sqlite_master` 取远端建表语句核对过全部 26 列（2026-09-29）：最接近的是
#: `Maximum Number of RRC Connection User`（**峰值**）与 `C373200029:...`（同一指标的
#: 带前缀列名），二者都不是「平均值」，口径不等价。
COL_ACTIVE_USER = "Average DL Active User Number"
COL_RRC_MAX = "C373200029:Maximum Number of RRC Connection User"

#: 远端表**实际存在**的全部列名（取自 `sqlite_master` 的建表语句）。
#: 用途见 `assert_columns_exist()` —— SQLite 会把**双引号包住的不存在标识符**
#: 当成字符串字面量静默返回，写错列名不会报错、只会拿到一堆「看起来像数据」的列名文本。
UME_CELL_COLUMNS = frozenset({
    "Begin Time", "End Time", "Granularity", "Group",
    "SubnetWork ID", "SubnetWork Name", "ManagedElement ID", "Managed Element",
    "eNodeB ID", "eNodeB Name", "E-UTRAN FDD Cell ID",
    f"E-UTRAN{_NBSP}FDD{_NBSP}Cell Name",
    "eNodeBId", "cellId",
    "1638004469333:[FDD]Call Setup Success Rate[SDR_ITBBU]",
    "1638004469340:[FDD]E-RAB Drop Rate[SDR_ITBBU]",
    "1638004469330:[FDD]DL Traffic Volume (GBytes)-new",
    "1638004469331:[FDD]UL Traffic Volume (GBytes)-new",
    "1638004469342:[FDD]DL PRB Utilization Rate[SDR_ITBBU]",
    "1638004469343:[FDD]UL PRB Utilization Rate[SDR_ITBBU]",
    "1638004469344:[FDD]CSFB Preparation success rate[SDR_ITBBU]",
    "1638004469345:[FDD]Cell Availability[SDR_ITBBU]",
    "C373200029:Maximum Number of RRC Connection User",
    "1638004469332:[FDD]DL IP Throughput(Mbps)[SDR_ITBBU]",
    "1638004469785:[FDD]UL IP Throughput(Mbps)[SDR_ITBBU]",
    "Maximum Number of RRC Connection User",
})


class MissingColumnError(Exception):
    """查询引用了远端表里不存在的列。

    必须显式抛错而不是让 SQLite 静默降级 —— 见 `UME_CELL_COLUMNS` 的说明。
    """


def assert_columns_exist(columns) -> None:
    """校验列名都在远端真实表结构里，否则抛 `MissingColumnError`。

    这个守卫存在的唯一理由：**SQLite 对双引号标识符的容错是有害的**。
    实测 `SELECT "No Such Column" FROM t` 返回字符串 `'No Such Column'` 而非报错，
    于是拼错列名时整列都会是「列名文本」，聚合时被当成 0 或字符串，页面显示成
    貌似合理的数字。宁可让任务失败，也不要产出这种数据。
    """
    missing = [c for c in columns if c not in UME_CELL_COLUMNS]
    if missing:
        raise MissingColumnError(
            "远端 %s 不存在这些列：%s（SQLite 会把不存在的双引号标识符当字符串返回，"
            "因此这里必须硬失败）" % (UME_CELL_TABLE, missing))


def assert_no_literal_fallback(rows, columns) -> None:
    """行数据级兜底：检查首行里有没有单元格恰好等于所请求的列名。

    `assert_columns_exist()` 只能挡住「列名与常量表不符」；如果常量表本身也写错
    （本模块就发生过：常量用普通空格、真实列用 `\\xa0`，两边一起错、守卫失效），
    唯一还能救回来的信号是**返回值本身**：SQLite 的字面量降级会把列名原样放进
    结果里。因此这里做一次「结果里出现了某个被请求列名的文本」的检查。

    行数很少时（如某天没数据）不做判断，避免误报。
    """
    if not rows or len(rows) < 2:
        return
    wanted = {str(c) for c in columns}
    first = rows[0]
    hits = [str(v) for v in first if str(v) in wanted]
    if hits:
        raise MissingColumnError(
            "远端返回的单元格里出现了所请求的列名 %s —— 说明这些列实际不存在，"
            "SQLite 把双引号标识符降级成了字符串字面量。请核对列名的"
            "不换行空格（\\xa0）等不可见字符。" % hits)

# 当前 4G Cell Daily 表里**实际存在**的 UME 源表名
UME_CELL_TABLE = "4G_Main_Kpi_Cell_Daily"

#: 当前采集端能拿到的 active-user item code。
#: `None` = 未采集到（现状）。拿到后在 main_kpi_config.json 里加码，此处同步更新。
ACTIVE_USER_ITEM: Optional[str] = None

# ============================================================
# 四、Excel 侧的结构常量
# ============================================================
SHEET_OVERALL_DAILY = "Overall - Daily"
SHEET_REGIONAL_DAILY = "Regional - Daily"
SHEET_LAYER_DAILY = "Frequency layer - Daily"
SHEET_OVERALL_WEEK = "Overall - 1 Weekly"
SHEET_REGIONAL_WEEK = "Regional - 1 Weekly"
SHEET_OVERALL_MONTH = "Overall - Monthly"
SHEET_REGIONAL_MONTH = "Regional - Monthly"
SHEET_BP_CELLS = "BP Cells List"

#: Excel 中**不作为独立数据源**的透视残留 sheet（见 11-feature-guide.md 的说明）。
#: Sheet1 是 Region=Rural 的透视，Sheet3 是 W1.. 周透视，与上面 6 个主 sheet 重复。
SHEET_IGNORED = ("Sheet1", "Sheet3")

# ============================================================
# 五、脏值清洗词表（基于 42.4 万行的实测分布）
# ============================================================

#: 归一化后的合法 Cluster 取值。Excel `BP Cells List.Cluster` 列另有约 100 个
#: 纯数字脏值（实为 Site ID / eNodeB ID 错填，如 '4593'、'9103'），一律归为 UNKNOWN。
VALID_CLUSTERS = ("Cluster1", "Cluster2", "Cluster3", "Cluster4",
                  "Cluster5", "Cluster6", "Rural", "ERA")

#: 归一化后的合法 Layer 取值。多出的 `L1800 10M` 是采集端从未有过的第 5 个 layer
#: （实测 5078 行）—— **保留为独立 layer，不硬合并进 L1800 15M**。
VALID_LAYERS = ("L800", "L1800 20M", "L1800 15M", "L1800 10M", "L2600")

#: 归不到类的取值统一落这里，并在 /meta 暴露计数（不静默丢弃、不猜测）。
UNKNOWN = "Unknown"

#: 小区名后缀 → Layer 的回推规则。
#: 实测（BP Cells List 42.4 万行）：'-F*'→L800(181818)、'-S*'→L1800 20M(150553)、
#: '-L*'→L1800 15M(61750)、'-X*'→L2600(24518)。用于修复 Layer 列的非层值脏数据
#: （后者混入了 'Rural'/'ERA'/'Cluster*' 等，合计约 250 行）。
#: 注意：'-L*' 只能是 L1800 15M —— `L1800 10M` 无法从小区名区分，回推时落到 15M，
#: 因此 Layer 列**本身合法**时永远以列值为准，回推只在列值非法时兜底。
SUFFIX_LAYER_MAP = {
    "F": "L800",
    "S": "L1800 20M",
    "L": "L1800 15M",
    "X": "L2600",
}

#: 小区名形如 `Division 16-S0` / `Freeport-F1`，取最后一个 '-' 之后的首字母。
_SUFFIX_RE = re.compile(r"-([A-Za-z])")


# ============================================================
# 六、清洗与归一化函数
# ============================================================

def _clean(value: Any) -> str:
    """去空白；None → 空串。Excel 的 Cluster/Layer 列存在首尾空格与不换行空格。"""
    if value is None:
        return ""
    # \xa0 是不换行空格，出现在 BP Cells List 的表头与部分取值里
    return str(value).replace("\xa0", " ").strip()


def normalize_cluster(value: Any) -> str:
    """Cluster 归一化：合法值原样返回，其余（含纯数字脏值）归 `Unknown`。

    实测脏值形态：`'4593'` / `'9103'`（Site ID 错填）、空值。**不做数值猜测**。
    """
    v = _clean(value)
    if v in VALID_CLUSTERS:
        return v
    return UNKNOWN


def is_dirty_cluster(value: Any) -> bool:
    """该 Cluster 取值是否需要清洗（用于 /meta 统计「未归类 N 个小区」）。"""
    return normalize_cluster(value) == UNKNOWN


def layer_from_cell_name(cell_name: Any) -> Optional[str]:
    """按小区名后缀回推 Layer；无法判定返回 `None`。

    例：`Freeport-F1` → `L800`；`BTC-S1` → `L1800 20M`；`Bethel Hill-X0` → `L2600`。
    """
    name = _clean(cell_name)
    if not name:
        return None
    m = _SUFFIX_RE.search(name)
    if not m:
        return None
    return SUFFIX_LAYER_MAP.get(m.group(1).upper())


def normalize_layer(value: Any, cell_name: Any = None) -> str:
    """Layer 归一化：列值合法时以列值为准，非法时按小区名后缀回推，仍失败归 `Unknown`。

    优先级刻意是「列值 > 回推」：`L1800 10M` 在小区名上与 `L1800 15M` 同样以 `-L`
    结尾，回推无法区分；只有列值本身合法的那些行才能保住 10M 这一档。
    """
    v = _clean(value)
    if v in VALID_LAYERS:
        return v
    return layer_from_cell_name(cell_name) or UNKNOWN


def is_dirty_layer(value: Any) -> bool:
    """该 Layer 取值是否需要清洗（列值本身非法即为脏，与能否回推无关）。"""
    return _clean(value) not in VALID_LAYERS


# ============================================================
# 七、BP 判定
# ============================================================

def is_bp_day(prb_dl: Any, thr_dl: Any, active_user: Any = None) -> Optional[bool]:
    """单个小区单日的 BP 判定。

    Args:
        prb_dl:      [FDD]DL PRB Utilization Rate，**小数比率**（0.853 表示 85.3%）。
                     实测该列值域 0~1，因此阈值是 `THR_DL_PRB_RATIO = 0.80` 而不是 80。
        thr_dl:      [FDD]DL IP Throughput(Mbps)。
        active_user: Average DL Active User Number；`None` 表示该指标未采集到。

    Returns:
        True  = 满足全部三个条件
        False = 明确不满足（PRB/吞吐不达标，或 active_user 取到了但 <= 2.5）
        None  = **不可判定**（三条件中任一缺值）—— 调用方必须与 False 区分对待，
                既不能当 True 算进 BP，也不该当 False 抹掉（用于「数据缺口」统计）。
    """
    if prb_dl is None or thr_dl is None:
        return None
    try:
        prb = float(prb_dl)
        thr = float(thr_dl)
    except (TypeError, ValueError):
        return None

    # 兜底：若上游某天改成百分数（>1 的取值），按百分数归一，避免静默恒 False。
    # 这不是"猜"，而是把两种可能的量纲都容纳进来；真正的判据仍是 > 80%。
    if prb > 1.0:
        prb = prb / 100.0

    # 前两个条件可以先判 False：任一明确不满足时，第三条件是否可得都不影响结论
    if not (prb > THR_DL_PRB_RATIO):
        return False
    if not (thr < THR_DL_THROUGHPUT_MBPS):
        return False

    # 走到这里 PRB 与吞吐都满足，结论完全取决于 active_user
    if active_user is None:
        return None
    try:
        au = float(active_user)
    except (TypeError, ValueError):
        return None
    return au > THR_ACTIVE_USER


def is_bp_week(bp_days: int, total_days: int = WEEK_TOTAL_DAYS) -> Optional[bool]:
    """周判定：一周内 >= 4/7 天为 BP → 该周为 BP。

    不足一个完整周（`total_days < 7`）时返回 `None`（不可判定），
    界面显示 `—` 而不是 `False`（AGENTS.md 原则 6）。
    """
    if total_days < WEEK_TOTAL_DAYS:
        return None
    return bp_days >= WEEK_BP_DAYS


def is_bp_month(bp_weeks: int, total_weeks: int = MONTH_TOTAL_WEEKS) -> Optional[bool]:
    """月判定：一个月内 >= 3/4 个完整周为 BP → 该月为 BP。

    不足 4 个完整周时返回 `None`（不可判定）—— 当月未过完即属此列。
    """
    if total_weeks < MONTH_TOTAL_WEEKS:
        return None
    return bp_weeks >= MONTH_BP_WEEKS


def active_user_status() -> Dict[str, Any]:
    """`Average DL Active User Number` 的采集状态，供 /meta 与页面告警条使用。

    这是页面**必须常驻显示**的口径说明：只要 `available=False`，
    重算出的 BP 数就只覆盖了两个条件，与 Excel 真值不可直接比较。
    """
    available = ACTIVE_USER_ITEM is not None
    return {
        "available": available,
        "item": ACTIVE_USER_ITEM,
        "threshold": THR_ACTIVE_USER,
        "fallback_column": COL_RRC_MAX,
        "reason": "" if available else (
            "Average DL Active User Number 未采集：现有 %s 是「峰值」而非「平均值」，"
            "口径不等价。缺该条件的小区记为「不可判定」，不计入 BP。" % COL_RRC_MAX
        ),
    }


def caliber_snapshot() -> Dict[str, Any]:
    """当前口径的完整快照（写入 bp_sync_meta，便于日后追溯「这版数按什么算的」）。"""
    return {
        "version": "bp-v1",
        "daily": {
            "active_user_gt": THR_ACTIVE_USER,
            "dl_throughput_mbps_lt": THR_DL_THROUGHPUT_MBPS,
            "dl_prb_ratio_gt": THR_DL_PRB_RATIO,
            "note": "PRB 为小数比率（0~1），阈值 0.80 等价于 80%",
        },
        "weekly": {"bp_days": WEEK_BP_DAYS, "of_days": WEEK_TOTAL_DAYS},
        "monthly": {"bp_weeks": MONTH_BP_WEEKS, "of_weeks": MONTH_TOTAL_WEEKS},
        "active_user": active_user_status(),
        "ume_table": UME_CELL_TABLE,
        "ume_columns": {"prb_dl": COL_PRB_DL, "thr_dl": COL_THR_DL},
    }


# ============================================================
# 八、时间与周期工具
# ============================================================

def day_str(value: Any) -> str:
    """把任意时间表示归一成 `YYYY-MM-DD`；无法解析返回空串。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    s = _clean(value)
    if not s:
        return ""
    # Excel 侧是 '2026-09-26 00:00:00'；RAN_UME 侧同格式
    return s[:10] if len(s) >= 10 and s[4] == "-" else s


def iso_week_key(value: Any) -> str:
    """归一成 ISO 周键 `2026-W39`；无法解析返回空串。

    统一用 ISO 周（周一起算）而非 Excel 的 `W39, 2026` 文本 —— 后者在跨年周上
    会与 ISO 周错位（W52/W1），而 RAN_UME 侧没有工作日历，只能靠 ISO 推。
    Excel 侧的原生文本另存 `native_period` 列以便逐行对账。
    """
    s = day_str(value)
    if not s:
        return ""
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return ""
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def month_key(value: Any) -> str:
    """归一成 `YYYY-MM`；无法解析返回空串。"""
    s = day_str(value)
    return s[:7] if len(s) >= 7 else ""


# Excel 的周文本形如 `W48, 2023` / `W8, 2024`；**末尾 39 行只写了 `W1`..`W39` 没带年份**
# （实测：带年份的到 `W52, 2025` 为止，之后是裸周号续写 2026 年）。因此解析需要
# 一个「上一行的年份」做锚点，见 `resolve_excel_weeks()`。
_EXCEL_WEEK_RE = re.compile(r"^\s*W(\d{1,2})\s*(?:,\s*(\d{4}))?\s*$")
_EXCEL_MONTH_RE = re.compile(r"^\s*([A-Za-z]{3})\s*,\s*(\d{4})\s*$")
_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def parse_excel_week(value: Any) -> Tuple[Optional[int], Optional[int]]:
    """解析 Excel 周文本 → (year, week)；年份缺失或格式不符时 year 返回 None。

    形如 `('W48, 2023')` → `(2023, 48)`；`('W9')` → `(None, 9)` —— 裸周号必须交给
    `resolve_excel_weeks()` 结合上下文补年份，不能在这里猜。
    """
    m = _EXCEL_WEEK_RE.match(_clean(value))
    if not m:
        return None, None
    year = int(m.group(2)) if m.group(2) else None
    return year, int(m.group(1))


def resolve_excel_weeks(natives: List[Any]) -> List[Tuple[int, int]]:
    """给一串 Excel 周文本补全年份，返回 [(year, week), ...]。

    为什么要单独做：Excel 末尾 39 行是**裸周号**（`W1`..`W39`），而孤立的周号在
    跨年处是有歧义的（`W1` 可能是 2026 年也可能是 2027 年）。这里用「上一行的年份 +
    周号单调递增」推断：出现 `W52 → W1` 这类回绕就进一年，否则沿用上一年。

    第一个元素若就没年份，则以它之后第一个带年份的行为准回推（实测数据里不会发生，
    但保持函数在坏输入下不抛错）。
    """
    out: List[Tuple[int, int]] = []
    # 先扫一遍拿第一个已知年份，用于回填开头的未知项
    first_known: Optional[int] = None
    for n in natives:
        y, w = parse_excel_week(n)
        if y is not None and w is not None:
            first_known = y
            break
    cur_year = first_known if first_known is not None else datetime.now().year
    prev_week: Optional[int] = None

    for n in natives:
        y, w = parse_excel_week(n)
        if w is None:
            # 完全无法解析：原样跳过（调用方按 native 文本兜底）
            out.append((cur_year, 0))
            continue
        if y is not None:
            cur_year = y
        elif prev_week is not None and w < prev_week:
            # 周号回绕（如 W52 → W1）说明跨年
            cur_year += 1
        out.append((cur_year, w))
        prev_week = w
    return out


def parse_excel_month(value: Any) -> Optional[str]:
    """解析 Excel 月度文本 `Apr, 2023` → `2023-04`；失败返回 None。"""
    m = _EXCEL_MONTH_RE.match(_clean(value))
    if not m:
        return None
    abbr = m.group(1)[:3].capitalize()
    if abbr not in _MONTH_ABBR:
        return None
    return f"{int(m.group(2)):04d}-{_MONTH_ABBR.index(abbr) + 1:02d}"


def excel_period_to_iso(value: Any) -> str:
    """把 Excel 的周/月文本统一转成 ISO 周键或月键（用于把 Excel 值挂到 ISO 周期上）。

    月文本 → `YYYY-MM`；周文本 → `YYYY-Www`（**按 Excel 自己的周序号**，
    仅作对照展示，不参与聚合运算）。
    """
    mk = parse_excel_month(value)
    if mk:
        return mk
    y, w = parse_excel_week(value)
    if y is not None and w is not None:
        return f"{y}-W{w:02d}"
    return _clean(value)


def sortable_cluster(c: str) -> Tuple[int, str]:
    """Cluster 排序键：Cluster1..6 按数字序，其余（Rural/ERA/Unknown）排在其后。"""
    m = re.match(r"^Cluster(\d+)$", c or "")
    if m:
        return int(m.group(1)), c
    return 99, c or ""


def sortable_layer(layer: str) -> Tuple[int, str]:
    """Layer 排序键：按 VALID_LAYERS 声明顺序，Unknown 最后。"""
    try:
        return VALID_LAYERS.index(layer), layer
    except ValueError:
        return len(VALID_LAYERS), layer


def week_days_in_month(month: str) -> List[str]:
    """给定 `YYYY-MM`，返回该月内**完整 ISO 周**（周一在月内且周日也在月内）的周键列表。

    月判定的分母（4 个完整周）从这里来。用「完整周」而非「该月出现过的所有周」，
    与用户口径里的 `3 / 4 full weeks` 一致：跨月的那两周不计。
    """
    import calendar
    try:
        y, m = (int(x) for x in month.split("-")[:2])
    except (ValueError, AttributeError):
        return []
    first = date(y, m, 1)
    last = date(y, m, calendar.monthrange(y, m)[1])
    out: List[str] = []
    seen = set()
    d = first
    while d <= last:
        # 该 ISO 周的周一与周日
        iso = d.isocalendar()
        monday = d.fromordinal(d.toordinal() - (iso[2] - 1))
        sunday = monday.fromordinal(monday.toordinal() + 6)
        if monday >= first and sunday <= last:
            key = f"{iso[0]}-W{iso[1]:02d}"
            if key not in seen:
                seen.add(key)
                out.append(key)
        d = d.fromordinal(d.toordinal() + 1)
    return out


def period_to_day_range(period: str) -> Optional[Tuple[str, str]]:
    """把概览输出的「周期标签」还原成 `(start_day, end_day)`，供下钻使用。

    ===================== 为什么必须有这个函数（2026-09-29 实测事故） =====================

    概览的 `trend[].period` 在周/月粒度下是 `2023-W48` / `2026-09` 这样的**标签**，
    不是日期。而下钻端点 `load_cells()` 的 `start`/`end` 是**日期**，走的是
    `day >= ? AND day <= ?` 的字符串比较。

    前端按周下钻时曾直接把 `period` 当日期传进来，于是 SQL 变成
    `day >= '2023-W48' AND day <= '2023-W48'` —— 字符串比较下 `'2026-08-24' >= '2023-W48'`
    成立（`'2' > '1'`），结果**返回了上限 20000 行、跨 34 个日期、甚至含 2026 年**的
    无关数据。用户点周行看到的明细与那一周毫无关系，且因为 `truncated=True` 只表现为
    「数据很多」，极难察觉。

    因此：**凡是把概览的 period 往下钻传的地方，必须先经过本函数**。

    Args:
        period: `YYYY-MM-DD`（原样返回）、`YYYY-Www`（ISO 周）或 `YYYY-MM`（整月）。

    Returns:
        `(start_day, end_day)`；无法识别时返回 `None`（调用方应拒绝该请求，
        而不是把无法识别的字符串丢给 SQL —— 那正是上面那场事故的成因）。
    """
    if not period or not isinstance(period, str):
        return None
    p = period.strip()

    # ① 单日：原样
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p):
        return (p, p)

    # ② ISO 周：YYYY-Www -> 该周周一 ~ 周日
    m = re.fullmatch(r"(\d{4})-W(\d{2})", p)
    if m:
        try:
            monday = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return None
        return (day_str(monday), day_str(monday.fromordinal(monday.toordinal() + 6)))

    # ③ 整月：YYYY-MM -> 月初 ~ 月末
    if re.fullmatch(r"\d{4}-\d{2}", p):
        try:
            y, mo = (int(x) for x in p.split("-"))
            first = date(y, mo, 1)
        except ValueError:
            return None
        last = first.fromordinal(
            first.toordinal() - 1 + _month_len(y, mo))
        return (day_str(first), day_str(last))

    return None


def _month_len(year: int, month: int) -> int:
    """该月天数（避免在模块顶部再引 calendar，只在需要时算）。"""
    import calendar
    return calendar.monthrange(year, month)[1]

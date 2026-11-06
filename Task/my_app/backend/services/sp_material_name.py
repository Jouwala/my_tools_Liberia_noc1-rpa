# -*- coding: utf-8 -*-
"""SP 物料名字解析 —— 明细里的 Material Name 一律以物料主数据 `sp_material` 为准。

为什么需要这一层
----------------
上游 SFTP 导出的入库 / 出库 / 库存 / 转仓明细里，`Material Name` 是**单据导出那一刻**的
快照名；物料在 eFlow 改名后，历史单据**不会回写新名**。于是同一个物料会带着两种写法
同时出现在一张报表里，而 `Summary-Current` 以 Material Name 为主键 ——
结果是**一个物料裂成两行**，入库 / 出库 / 库存被拆开，`Avg Monthly Consumption`、
`Safety Stock`、`Alert Level` 全部按半截数量算。

2026-11-06 实测：主数据当天 08:20~08:37 把 `Chassis (NR9000TR)|` 等 3 个物料改名，
当天 SpareParts 总表 86 行明细受影响，Summary-Current 242 行里裂出 **4 组**重复物料。

口径
----
按 `Material No.` 取 `sp_material.materialName`（该表由 `sp_material_sync` 从 eFlow
`eflow-sp-material/base/list` 全量拉取，`materialNo` 唯一，重复时保留 `woId` 最大的一行）。
**命中才覆盖，未命中保留原值** —— 主数据缺该物料时不臆造成分不明的空名。
`|` 不是脏字符：979 条主数据里 510 条名字本身就含 `|`（如 `DTB_B|Digital Trunk Board|`），
所以只能整串取主数据的值，**禁止**用「去掉结尾 |」这类字符清洗。

用法
----
    from backend.services.sp_material_name import normalize_dataframe, normalize_rows
    stats = normalize_dataframe(df)         # pandas 明细（报表生成器 / 落库 / 邮件合并）
    stats = normalize_rows(columns, rows)   # sp_details_service 的 SheetData（list of list）

结果一律回传 changed 与 missing 计数：覆盖了多少行、多少行主数据查不到而保留原值。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("sp_material_name")

#: 物料主数据表（PG 模式在 app schema，sqlite 模式在 db/app.db，由 get_raw_connection 统一解析）
MATERIAL_TABLE = os.environ.get("SP_MATERIAL_TABLE", "sp_material")

#: 明细侧列名（上游导出用英文列名，含空格与点号）
NO_COL = "Material No."
NAME_COL = "Material Name"
TYPE_COL = "Material Type"

_CACHE_TTL_SEC = 300
_lock = threading.Lock()
_cache: Dict[str, Any] = {"ts": 0.0, "maps": None}


def norm_key(v: Any) -> str:
    """物料号归一：去空格；纯数字统一成最简形式（`1.0`→`1`、`033030100337`→`33030100337`）。

    明细是文本（带前导零），主数据与 Excel 侧常被存成数字，两边不归一就大面积不命中。
    """
    if v is None:
        return ""
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "none", "nat"):
        return ""
    try:
        f = float(s)
    except ValueError:
        return s
    if f == int(f):
        return str(int(f))
    return ("%.6f" % f).rstrip("0").rstrip(".")


def _text(v: Any) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def _fetch_maps() -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    """查主数据，返回 (materialNo→materialName, materialNo→materialType, materialName→domain)。

    表 / 列缺失或连不上库时返回三个空字典并打告警 —— 调用方按「保留明细原名」处理，
    不能因为主数据不可用中断报表生成。
    """
    from backend.database import get_raw_connection
    from backend.dialect_helpers import table_columns

    empty: Tuple[Dict[str, str], Dict[str, str], Dict[str, str]] = ({}, {}, {})
    try:
        with get_raw_connection() as conn:
            cols = {c.lower(): c for c in table_columns(conn, MATERIAL_TABLE)}
    except Exception as e:
        logger.warning("[MatName][WARN] 读取主数据表 %s 失败(%s)，明细保留上游原名", MATERIAL_TABLE, e)
        return empty
    if "materialno" not in cols or "materialname" not in cols:
        logger.warning("[MatName][WARN] %s 缺少 materialNo/materialName 列，明细保留上游原名", MATERIAL_TABLE)
        return empty

    # 列名取表定义的原样大小写并加引号：PG 会把不加引号的标识符折叠成小写，SQLite 两边通用
    sel = [f'"{cols["materialno"]}"', f'"{cols["materialname"]}"',
           f'"{cols["materialtype"]}"' if "materialtype" in cols else "''",
           # domain 列缺失时只丢 domain 映射，不影响 Name / Type（防旧表结构）
           f'"{cols["domain"]}"' if "domain" in cols else "''"]
    try:
        with get_raw_connection() as conn:
            rows = conn.execute(
                f'SELECT {", ".join(sel)} FROM "{MATERIAL_TABLE}" '
                f'ORDER BY "{cols["materialno"]}"').fetchall()
    except Exception as e:
        logger.warning("[MatName][WARN] 查询 %s 失败(%s)，明细保留上游原名", MATERIAL_TABLE, e)
        return empty

    name_lut: Dict[str, str] = {}
    type_lut: Dict[str, str] = {}
    domain_lut: Dict[str, str] = {}
    for no, nm, tp, dm in rows:
        k, n = norm_key(no), _text(nm)
        if not (k and n):
            continue
        name_lut.setdefault(k, n)
        if _text(tp):
            type_lut.setdefault(k, _text(tp))
        # domain 按 materialName 建映射（同名多行取首个非空）
        if _text(dm):
            domain_lut.setdefault(n, _text(dm))
    logger.info("[MatName] 主数据 %s: Name %d 条, Type %d 条, Domain %d 条",
                MATERIAL_TABLE, len(name_lut), len(type_lut), len(domain_lut))
    return name_lut, type_lut, domain_lut


def load_material_maps(force_refresh: bool = False
                       ) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    """带 TTL 缓存的主数据映射（长驻进程每次读库没必要，5 分钟内复用）。

    报表生成器在 Step 0 刷新主数据后要用 `force_refresh=True` 拿改名后的最新值。
    """
    with _lock:
        if force_refresh or _cache["maps"] is None or time.time() - _cache["ts"] > _CACHE_TTL_SEC:
            _cache["maps"] = _fetch_maps()
            _cache["ts"] = time.time()
        return _cache["maps"]


def material_name_lut() -> Dict[str, str]:
    return load_material_maps()[0]


def canonical_name(material_no: Any) -> str:
    """单个物料号的主数据名；查不到返回空串。"""
    return material_name_lut().get(norm_key(material_no), "")


def normalize_dataframe(df, no_col: str = NO_COL, name_col: str = NAME_COL,
                        name_lut: Optional[Dict[str, str]] = None,
                        type_col: Optional[str] = None,
                        type_lut: Optional[Dict[str, str]] = None,
                        label: str = "") -> Dict[str, Any]:
    """就地用主数据覆盖 df[name_col]；给了 type_col + type_lut 时一并覆盖该列。

    `name_lut` 缺省取主数据；报表生成器在主数据不可用时会传 inventory 派生的映射做回退。
    缺 `Material No.` / 缺目标列 / 映射为空时**不改也不报错**，返回 {'skipped': 原因}：
    上游表结构变化不该拖挂整张报表，但原因要带回去让调用方打印。
    """
    import pandas as pd

    rows = 0 if df is None else int(len(df))
    stats: Dict[str, Any] = {"rows": rows, "changed": 0, "missing": 0,
                             "type_changed": 0, "label": label}
    if rows == 0:
        stats["skipped"] = "空表"
        return stats
    for col in (no_col, name_col):
        if col not in df.columns:
            stats["skipped"] = f"缺 {col} 列"
            return stats
    lut = material_name_lut() if name_lut is None else name_lut
    if not lut:
        stats["skipped"] = "主数据不可用"
        return stats

    keys = df[no_col].map(norm_key)
    new_names = keys.map(pd.Series(lut))
    hit = new_names.notna()
    old = df[name_col].fillna("").astype(str).str.strip()
    stats["changed"] = int((hit & new_names.where(hit, "").ne(old)).sum())
    stats["missing"] = int((~hit).sum())
    df[name_col] = new_names.where(hit, df[name_col])

    if type_col and type_lut and type_col in df.columns:
        new_types = keys.map(pd.Series(type_lut))
        t_hit = new_types.notna()
        old_types = df[type_col].fillna("").astype(str).str.strip()
        stats["type_changed"] = int((t_hit & new_types.where(t_hit, "").ne(old_types)).sum())
        df[type_col] = new_types.where(t_hit, df[type_col])
    return stats


def normalize_rows(columns: Sequence[str], rows: List[List[Any]],
                   no_col: str = NO_COL, name_col: str = NAME_COL) -> Dict[str, Any]:
    """SheetData（列名 list + 行 list[list]）版覆盖，供 sp_details_service 这类非 pandas 读取用。"""
    stats: Dict[str, Any] = {"rows": len(rows), "changed": 0, "missing": 0}
    cols = list(columns)
    if not cols or not rows:
        return stats
    if no_col not in cols or name_col not in cols:
        stats["skipped"] = f"缺 {no_col} / {name_col} 列"
        return stats
    lut = material_name_lut()
    if not lut:
        stats["skipped"] = "主数据不可用"
        return stats
    i_no, i_name = cols.index(no_col), cols.index(name_col)
    for row in rows:
        if i_no >= len(row) or i_name >= len(row):
            continue
        hit = lut.get(norm_key(row[i_no]), "")
        if not hit:
            stats["missing"] += 1
            continue
        if hit != _text(row[i_name]):
            stats["changed"] += 1
        row[i_name] = hit
    return stats


__all__ = ["MATERIAL_TABLE", "NO_COL", "NAME_COL", "TYPE_COL", "norm_key",
           "load_material_maps", "material_name_lut", "canonical_name",
           "normalize_dataframe", "normalize_rows"]

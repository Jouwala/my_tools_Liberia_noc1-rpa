"""TT 排除名单（NUR Exclude）落库读写。

=========================== 这个模块解决什么 ===========================

NUR 的排除名单原先由 `nur_calc` 每次去 FineBI FTP 实时下载 `TT_Exclude.xlsx`
内存解析。2026-10-06 起改为**落库**，由人工在「表格浏览」页上传维护。

为什么必须落库（业务确认的四条理由）：

1. **名单隐形** —— 页面上只有一个条数，无人能查具体排除了哪些单；
2. **无法审计** —— xlsx 没有历史版本，回答不了「上周 NUR 为什么变了」；
3. **拉取时间 ≠ 内容时间** —— 这是真实踩过的坑：看板标签显示 `(10-05 16:47)`
   看着很新，里面 46 个票号却全是 8 月初的。用户把「名单过时导致最近几天
   NUR 全 0」误判成「计算算错了」；
4. **依赖 FTP 可用性** —— 拉取失败降级空集时，NUR 口径**静默变化**。

=========================== 与 vip_site_list 的区别 ===========================

`vip_site_list` 是「有上游 Excel、可按 sheet 批量导入」的表；本表是
**人工维护的名单**（没有上游文件、没有定时同步）—— 这是两套不同的写入路径，
不要因为外形相似就合并处理（AGENTS.md 三.7：不要过早抽象）。

=========================== 数据契约 ===========================

源文件实测：46 行 × 1 列，列名 `Ticket No.`，值形如 `TT202608090116`。
解析时做两件事：
- 列名匹配放宽（正则 `tt|ticket|单号`，与 nur_calc 原逻辑一致），
  容忍上游改列名；
- **格式校验**：票号必须匹配 `^TT\\d{10,}$`（大小写不敏感，规范化后存）。
  这条不是洁癖 —— 用户传错文件（比如传成站点表）时，应该在上传阶段就报错，
  而不是等 NUR 数字全变了才发现。允许少量不合规行（见 MAX_BAD_RATIO）。

=========================== 全量替换 + 护栏 ===========================

上传即全量替换（DELETE + INSERT，同一事务）。护栏见 `replace_all()`：
空导入拒绝、格式校验、dry-run。
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backend.database import get_raw_connection

logger = logging.getLogger("tt_exclude")

TABLE = "tt_exclude"

# 票号格式：TT + 至少 10 位数字。实测 TT202608090116（TT + 12 位）。
# 放宽到 10 位是为了容忍上游位数变化，同时仍能拦住「传错文件」。
_TICKET_RE = re.compile(r"^TT\d{10,}$", re.I)

# 列名匹配：与原 nur_calc 逻辑一致（正则 tt|ticket|单号），容忍上游改列名
_COL_RE = re.compile(r"(tt|ticket|单号)", re.I)

# 允许的非空行里不合规票号占比上限。超过即判定「传错文件」并拒绝。
# 设为 10% 而非 0：容忍上游偶尔混入的空行/表尾说明行。
MAX_BAD_RATIO = 0.10


class ExcludeImportError(ValueError):
    """上传内容不合规（供路由层转成 400）。"""


# ============================================================
# 解析（xlsx/csv 字节 → 票号集合）
# ============================================================
def _norm(v: Any) -> str:
    """规范化票号：去空白、转大写。空/NaN → 空串。"""
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none") else s.upper()


def parse_tickets(data: bytes, filename: str = "upload.xlsx") -> Tuple[List[str], Dict[str, Any]]:
    """从上传文件解析票号列表。

    返回 ``(tickets, report)``；``report`` 含解析诊断（列名、总行数、不合规行样例），
    供 dry-run 与错误提示使用。**不去重**（去重在调用方，以便报告重复数）。
    """
    try:
        if filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(data))
        else:
            df = pd.read_excel(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001 - 统一转成业务可读错误
        raise ExcludeImportError(f"文件解析失败: {e}") from e

    if df.empty or len(df.columns) == 0:
        raise ExcludeImportError("文件内容为空，无可导入数据")

    col = None
    for c in df.columns:
        if _COL_RE.search(str(c)):
            col = c
            break
    # 未匹配到语义列时退回第一列：源文件只有一列，且列名可能被上游改动。
    # 但此时报一次 warning，便于发现「上游把表结构改了」。
    if col is None:
        col = df.columns[0]
        logger.warning("[TT-EXCLUDE] 未找到票号语义列，退回首列 %r", str(col))

    raw = [_norm(v) for v in df[col].tolist()]
    non_empty = [v for v in raw if v]
    if not non_empty:
        raise ExcludeImportError(f"列 {col!r} 为空，未解析到任何票号")

    good = [v for v in non_empty if _TICKET_RE.match(v)]
    bad = [v for v in non_empty if not _TICKET_RE.match(v)]
    bad_ratio = len(bad) / len(non_empty)

    report = {
        "column": str(col),
        "rows_in_file": int(len(df)),
        "non_empty": len(non_empty),
        "valid": len(good),
        "invalid": len(bad),
        "invalid_samples": bad[:5],
        "invalid_ratio": round(bad_ratio, 4),
    }

    # 空导入：**最危险的一种失败** —— 空名单 = 没有任何单被排除，
    # NUR 口径会静默变化（正是我们要消灭的情形），故必须硬拒。
    if not good:
        raise ExcludeImportError(
            f"未解析到任何合法票号（列 {col!r}，{len(non_empty)} 个非空值）。"
            f"票号应形如 TT202608090116。样例: {bad[:3]}"
        )
    # 传错文件的典型信号：大部分值都不像票号
    if bad_ratio > MAX_BAD_RATIO:
        raise ExcludeImportError(
            f"文件疑似不是排除名单：{len(bad)}/{len(non_empty)} 行不符合票号格式"
            f"（列 {col!r}）。票号应形如 TT202608090116。样例: {bad[:3]}"
        )
    return good, report


# ============================================================
# 读
# ============================================================
def fetch_tickets() -> Optional[set]:
    """读全量票号集合。

    返回 ``None`` 表示**表不可用/读失败**（调用方据此决定是否降级到 FTP）；
    返回空 ``set()`` 表示表可用但**名单为空** —— 这是个有意义的业务状态，
    调用方必须区分对待（空集会让 NUR 口径变化，不能静默当成"正常"）。
    """
    try:
        conn = get_raw_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT ticket_no FROM {TABLE}")
            return {_norm(r[0]) for r in cur.fetchall() if _norm(r[0])}
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("[TT-EXCLUDE] 读取 %s 失败: %s", TABLE, e)
        return None


def fetch_meta() -> Dict[str, Any]:
    """读名单元信息：条数、最后上传时间、上传人、来源文件。

    页面用它显示「排除名单: 46 (10-06 14:20 by zhangsan)」——
    **内容时间**（`_import_time`）而非拉取时间，这是本次改造的核心目的。
    """
    out: Dict[str, Any] = {"count": 0, "import_time": None, "uploaded_by": None,
                           "source_file": None, "table_ready": False}
    try:
        conn = get_raw_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT count(*), max(_import_time), max(_uploaded_by), max(_source_file) "
                f"FROM {TABLE}"
            )
            n, t, by, src = cur.fetchone()
            out.update(count=int(n or 0), import_time=t, uploaded_by=by,
                       source_file=src, table_ready=True)
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("[TT-EXCLUDE] 读取 %s 元信息失败: %s", TABLE, e)
    return out


# ============================================================
# 写（全量替换）
# ============================================================
def replace_all(tickets: List[str], source_file: str,
                uploaded_by: str = "", dry_run: bool = False) -> Dict[str, Any]:
    """全量替换名单。返回变更报告（供 dry-run 与审计）。

    单事务：DELETE + INSERT。任一步失败整体回滚，不会留下「删了旧的、
    没写进新的」这种最坏状态。
    """
    before = fetch_meta()
    uniq = sorted(set(tickets))
    report: Dict[str, Any] = {
        "before_count": before["count"],
        "after_count": len(uniq),
        "duplicates_removed": len(tickets) - len(uniq),
        "added": 0, "removed": 0, "dry_run": dry_run,
    }

    old = fetch_tickets()
    if old is not None:
        new = set(uniq)
        report["added"] = len(new - old)
        report["removed"] = len(old - new)

    if dry_run:
        return report

    if not uniq:
        # 与 parse_tickets 的空导入护栏呼应：这里是最后一道防线。
        raise ExcludeImportError("拒绝写入空名单：空名单会让 NUR 口径静默变化")

    ts = datetime.now().isoformat(timespec="seconds")
    conn = get_raw_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM {TABLE}")
        cur.executemany(
            f"INSERT INTO {TABLE} (ticket_no, _source_file, _source_sheet, _import_time, _uploaded_by) "
            f"VALUES (?, ?, ?, ?, ?)",
            [(tk, source_file, "Sheet1", ts, uploaded_by) for tk in uniq],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    report["import_time"] = ts
    logger.info("[TT-EXCLUDE] 名单已替换: %d -> %d 条 (by %s, 文件 %s)",
                report["before_count"], report["after_count"], uploaded_by or "unknown", source_file)
    return report


# ============================================================
# 首次播种（从 FTP 现网名单灌入）
# ============================================================
def seed_from_ftp() -> Dict[str, Any]:
    """从 FTP 现网 `TT_Exclude.xlsx` 灌入初始名单（仅建表后执行一次）。

    这是迁移的**过渡手段**：落库后真相源变成数据库，FTP 只作为兜底读取。
    """
    from backend.services import nur_calc

    data = nur_calc._fetch_exclude_xlsx_bytes()
    tickets, rep = parse_tickets(data, "TT_Exclude.xlsx")
    out = replace_all(tickets, source_file="TT_Exclude.xlsx (FTP 初始播种)",
                      uploaded_by="__seed_from_ftp__")
    out["parse"] = rep
    return out

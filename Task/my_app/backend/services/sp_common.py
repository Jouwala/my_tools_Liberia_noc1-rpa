# -*- coding: utf-8 -*-
"""SP 未关闭单据的**唯一口径**（2026-10-18 建）。

## 为什么有这个模块

「SPMS 未关闭单」这个数字此前在**三处各算一遍**，词表、粒度、数据落点
都不一致，用户在同一套系统里点开两个页面会看到三个数字：

| 位置 | 原实现 | 数据源 |
| --- | --- | --- |
| `/v3/olbrportal/` SPMS 大数字与下钻 | `portal_qc._sp_open_counts` / `_detail_source` | DB `inband_details` / `outband_details` |
| `/myapp/?page=sp_report` 分表卡片 | `sp_report_service._sheet_stats` | Excel `SpareParts Inbound&Outbound&Inventory *.xlsx` |
| `/myapp/?page=sp_details` 分表卡片 | `sp_details_service._sheet_stats` | Excel `SP Details Report *.xlsx` |

差异有两层（2026-10-18 实测核对）：

1. **粒度**：表是「出库明细行」，同一张 `Outbound No.` 有多行（按物料/序列号
   拆行）。当场实测 23 行未关闭只对应 **12 张不同的单**。原先三处都是
   `COUNT(*)` 数行，于是「未关闭出库单」这个说法与数字对不上。
2. **时点**：Excel 快照 05:15 下载、05:55 合并；DB 由 `sp_data_sync` 07:00
   落库。同一张单在两次快照之间状态变化，两边就会短暂不同。

本模块把**第 1 层收敛成一份实现**（词表 + 粒度 + 判据），三处一律从这里取。
第 2 层（时点）由调用方决定落点；`portal_qc` 与 `sp_details` 保持各自数据源，
但**同一时刻、同一批数据下三者必然给出同一个数**。

## 口径（全项目唯一）

- **已关闭**：`Status` 归一化（去空白 + 小写）后命中 :data:`CLOSED_WORDS`。
- **不计入在途**：命中 :data:`IGNORED_WORDS`（`WaitingForUpdate` 是尚未生效的
  出库单，申请人还没提交更新，不是真正待处理的任务）。
- **未关闭单** = `Status` 非空、且不属于上面两组。
- **粒度** = 按单据号去重：`Inbound No.` / `Outbound No.`。同一张单的多条物料
  行算 1 张单。这是本模块与旧实现**行为不同**的地方 —— 旧实现数行。

> ⚠️ `sp_details` 页面（读 `SP Details Report *.xlsx`）自 2026-09-22 起读原始快照，
> 含 `Operation Result Status=Canceled` 与 `WaitingForUpdate` 的行；本模块的
> `IGNORED_WORDS` 会剔除后者。若该页要保留「原始快照原样呈现」的语义，
> 调用方需显式传入 ``ignore_statuses=()``，不要改这里 —— 这里是**默认**
> 口径，不是唯一入口。

## 用法

    from backend.services.sp_common import (
        SP_CLOSED_WORDS, SP_IGNORED_WORDS, normalize_status, is_open_status,
        open_predicate_sql, count_open_docs, open_doc_numbers,
    )

    # SQL 侧（portal_qc 大数字 / 下钻）
    where = open_predicate_sql('"Status"')          # 未关闭谓词
    n = count_open_docs(conn, "outband_details", "Outbound No.")

    # Python 侧（Excel 解析出来的行）
    n = count_open_docs_rows(rows, status_idx, doc_idx)
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

#: 「已关闭」词表。与 get_sp_table._status_breakdown 一致（该项目既有约定），
#: 归一化后比较，所以这里一律写小写。
SP_CLOSED_WORDS = (
    "closed", "close", "done", "已关闭", "完成", "yes", "y", "1", "true",
)

#: 「不算未关闭」的在途状态。WaitingForUpdate = 尚未生效的出库单
#: （申请人还没提交更新，见 sp_online_sync.STATUS_ALL），不是真正待处理的任务。
#: 与 sp_report_gen.gernarate_sp_report.OUTBOUND_DROP_STATUS、
#: sp_report_gen.generate_sp_online_report.EXCLUDED_STATUS 生成报表前也都剔除它。
SP_IGNORED_WORDS = ("waitingforupdate",)

#: 判据全集：不在这个集合里 = 未关闭。
SP_NOT_OPEN_WORDS = SP_CLOSED_WORDS + SP_IGNORED_WORDS

#: 各表/各 sheet 的单据编号列。**粒度定义在这里** ——「未关闭 N 单」按这些列去重。
SP_DOC_COLUMNS = {
    "inband_details": "Inbound No.",
    "outband_details": "Outbound No.",
}

#: 各 sheet（Excel 报表里的 key）→ 单据编号列。sp_report / sp_details 共用。
SP_SHEET_DOC_COLUMN = {
    "Inbound": "Inbound No.",
    "Outbound": "Outbound No.",
}


def normalize_status(value) -> str:
    """状态归一化：去空白 + 小写。None / NaN → 空串。"""
    if value is None:
        return ""
    text = str(value).strip()
    # pandas 读出来的 NaN 是 float，str() 会得到 'nan'
    if text.lower() in ("nan", "none", "null"):
        return ""
    return text.lower()


def is_open_status(value) -> bool:
    """单条状态是否属「未关闭」。

    空状态不算未关闭（与既有实现 ``if s and ...`` 一致 —— 空值不是一张待处理的单）。
    """
    status = normalize_status(value)
    return bool(status) and status not in SP_NOT_OPEN_WORDS


def _words_sql(words: Sequence[str]) -> str:
    """词表 → SQL 的 IN 列表字面量（值里的单引号做转义）。"""
    return ",".join("'" + w.replace("'", "''") + "'" for w in words)


def open_predicate_sql(col_quoted: str, ignore_words: Optional[Sequence[str]] = None) -> str:
    """「未关闭」的 SQL 谓词 —— 与 :func:`is_open_status` 逐条等价。

    ``col_quoted`` 必须是已加引号的列名（如 ``'"Status"'``）。

    ``ignore_words`` 默认用 :data:`SP_IGNORED_WORDS`；传 ``()`` 表示「只按
    closed 词表判，不剔除在途态」—— 供 `sp_details` 那种「原始快照原样呈现」
    的场景显式选择，不要默默改默认值。

    空状态显式排除：``LOWER(TRIM('')) = ''``，``'' NOT IN (...)`` 恒为真，
    若不额外判空，SQL 会把「状态空白」的行算成未关闭，而 Python 侧
    :func:`is_open_status` 把它算作不算 —— 这就是 2026-10-18 实测到的
    两处口径分叉（Excel 侧 11 vs DB 侧 12 的一部分来源）。
    现在两边都以「空状态 = 不算未关闭」为准。

    ⚠️ 与 portal_qc 的既有注记一致：本谓词用于 ``get_raw_connection`` 时
    **不能**含字面 ``%``（包装层会把 ``%`` 转成 ``%%``），这里只有 IN 列表，安全。
    """
    words = SP_CLOSED_WORDS + tuple(ignore_words if ignore_words is not None else SP_IGNORED_WORDS)
    norm = f"LOWER(TRIM(COALESCE(CAST({col_quoted} AS TEXT), '')))"
    return f"({norm} <> '' AND {norm} NOT IN ({_words_sql(words)}))"


def count_open_docs(conn, table: str, doc_col: Optional[str] = None,
                    status_col: str = "Status") -> int:
    """某张明细表里**未关闭单据数**（按单据号去重）。

    ``doc_col`` 不传则查 :data:`SP_DOC_COLUMNS`；表名不在映射里且没显式给
    doc_col，退化为按行计数并在调用方语义上视为「明细行数」—— 调用方应当
    显式传列名，这个退化只为了避免 import 时就炸。
    """
    doc = doc_col or SP_DOC_COLUMNS.get(table)
    q_doc = '"' + str(doc).replace('"', '""') + '"' if doc else None
    q_status = '"' + str(status_col).replace('"', '""') + '"'
    where = open_predicate_sql(q_status)
    if q_doc:
        sql = f'SELECT COUNT(DISTINCT {q_doc}) AS c FROM {table} WHERE {where}'
    else:
        sql = f'SELECT COUNT(*) AS c FROM {table} WHERE {where}'
    row = conn.execute(sql).fetchone()
    return int(row[0] or 0) if row else 0


def open_doc_numbers(conn, table: str, doc_col: Optional[str] = None,
                     status_col: str = "Status") -> List[str]:
    """某张表里**未关闭的单据号**列表（去重、升序）。

    用于下钻明细：拿到单号后按单取明细，保证明细的「单数」与大数字一致。
    """
    doc = doc_col or SP_DOC_COLUMNS.get(table)
    if not doc:
        return []
    q_doc = '"' + str(doc).replace('"', '""') + '"'
    q_status = '"' + str(status_col).replace('"', '""') + '"'
    where = open_predicate_sql(q_status)
    sql = (f'SELECT DISTINCT {q_doc} AS d FROM {table} WHERE {where} '
           f'AND {q_doc} IS NOT NULL ORDER BY {q_doc}')
    return [str(r[0]) for r in conn.execute(sql).fetchall() if r and r[0] is not None]


def count_open_docs_rows(rows: Iterable[Sequence], status_idx: int,
                         doc_idx: Optional[int],
                         ignore_statuses: bool = True) -> int:
    """Python 侧（Excel 解析出的行）的未关闭单据数。

    ``doc_idx`` 为 None 时按行计数（该 sheet 没有单据编号列，例如 Summary 类）。
    ``ignore_statuses=False`` 时只看 closed 词表、不剔除在途态（原始快照语义）。
    """
    # 判据统一用 is_open_status 的表达：空状态 = 不算未关闭；
    # ignore_statuses=False 时只把 closed 词表当「已关闭」，在途态计入未关闭。
    not_open = SP_CLOSED_WORDS if not ignore_statuses else SP_NOT_OPEN_WORDS

    if doc_idx is None:
        n = 0
        for r in rows:
            if status_idx >= len(r):
                continue
            status = normalize_status(r[status_idx])
            if not status or status in not_open:
                continue
            n += 1
        return n

    seen = set()
    for r in rows:
        if status_idx >= len(r) or doc_idx >= len(r):
            continue
        status = normalize_status(r[status_idx])
        if not status or status in not_open:
            continue
        doc = r[doc_idx]
        if doc is None or str(doc).strip() == "":
            continue
        seen.add(str(doc).strip())
    return len(seen)

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把库房（SP）相关表导出为知识库文档（供 RAG 检索）。

用法：
    python scripts/export-warehouse-knowledge.py

产出（写入 whatsapp-kb-bot/knowledge/）：
    库房-业务与数据字典.md   8 张表的结构、字段含义、枚举值、业务口径
    库房-仓库与物料清单.md   仓库清单 + 物料主数据字典

## 为什么库房要单独导一份

库房（Spare Parts / 库房物资）有 8 张表、两套编号体系（sp_* 主单 + *_details 明细），
字段名还是英文原文。不导成文档的话，群里问「库房有哪些单据类型」「库房库存表怎么对账」
只能被当成知识问题瞎猜 —— RAG 里压根没有这些表的影子。

## 口径陷阱（本脚本刻意规避，写进文档是为了让后来人别踩）

1. **inventory_details 是按日快照，不是当前库存**。
   全表 21 万行，但每个 update_date 各存一份当日快照；
   **只有 update_date = max(update_date) 的那一份才是当前库存**（约 2100 行）。
   直接 SUM 全表会得到 90 万这种离谱数字。my_app 的
   backend/services/native_catalog.py:1952 用的是同一口径。

2. **sp_* 是主单，*_details 是明细**，两者行数量级完全不同
   （sp_outbound 746 vs outband_details 2573）。主单回答「有多少张单」，
   明细回答「这张单动了哪些物料」。

3. **单号前缀区分单据类型**：SPIB=入库单、SPOB=出库单。

## 设计取向

沿用 export-tt-knowledge.py 的取向：为**检索**服务，不为「读起来完整」服务。
每个枚举值、每张表的字段清单独立成段，避免被分块器切碎后语义残缺。
"""
from __future__ import annotations

import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import my_app_paths  # noqa: E402

MY_APP_DIR = my_app_paths.find_my_app_dir()
DB_PATH = my_app_paths.resolve('MY_APP_DB', 'db', 'app.db')
OUT_DIR = os.path.join(os.path.dirname(HERE), 'knowledge')

# ------------------------------------------------------------------ #
# 表清单：主单（sp_*）与明细（*_details）分开，靠这张表驱动整个导出
# ------------------------------------------------------------------ #

# (表名, 中文名, 角色说明)
TABLES = [
    ('sp_material', '物料主数据', '物料台账。物料编码、名称、单位、类型、ECCN、生命周期、单价等静态属性。'),
    ('sp_inbound', '入库单主表', '一张入库单一行。记录单号、类型、库房、请求/入库/关闭时间与状态。'),
    ('sp_outbound', '出库单主表', '一张出库单一行。记录单号、类型、库房、是否需归还、维修厂商与 SLA。'),
    ('sp_transfer', '调拨单主表', '一张调拨单一行。记录原仓→目标仓、是否需归还、站点级别。'),
    ('inventory_details', '库存明细表', '按日快照的库存明细。序列号级记录，含现存数量、预留数量、库位。'),
    ('inband_details', '入库明细表', '入库单的行明细。物料、序列号、数量、库位、扫描状态。'),
    ('outband_details', '出库明细表', '出库单的行明细。物料、序列号、数量、领用人、关联工单。'),
    ('transfer_details', '调拨明细表', '调拨单的行明细。原仓/目标仓库位、物料、序列号、调拨数量。'),
]

# 需要在文档里体现枚举值的字段：(表名, 字段名, 中文名, 说明)
ENUM_FIELDS = [
    ('sp_inbound', 'inboundType', '入库类型', ''),
    ('sp_inbound', 'status', '单据状态', ''),
    ('sp_outbound', 'outboundType', '出库类型', ''),
    ('sp_outbound', 'status', '单据状态', ''),
    ('sp_outbound', 'returnStatus', '归还状态', ''),
    ('sp_transfer', 'status', '单据状态', ''),
    ('sp_material', 'materialType', '物料类型', ''),
    ('sp_material', 'materialManageType', '物料管理方式', 'Instance=按序列号管理；Category=按类别管理。'),
    ('sp_material', 'domain', '领域', ''),
    ('sp_material', 'subDomain', '子领域', ''),
    ('sp_material', 'status', '物料状态', ''),
    ('sp_material', 'importance', '重要性', ''),
    ('sp_material', 'eccnStatus', 'ECCN 状态', '出口管制分类状态。'),
    ('sp_material', 'lifeCycle', '生命周期', ''),
    ('inventory_details', 'Material Type', '物料类型', ''),
    ('inventory_details', 'OwnerShip', '所有权', 'Orange=客户所有（寄售/委外）；ZTE=中兴自有。'),
    ('inventory_details', 'Material Status', '物料状态', 'available=可用；damage=损坏。'),
    ('inventory_details', 'ECCN Status', 'ECCN 状态', ''),
    ('inband_details', 'Inbound Type', '入库类型', ''),
    ('inband_details', 'Status', '单据状态', ''),
    ('outband_details', 'Outbound Type', '出库类型', ''),
    ('outband_details', 'Status', '单据状态', ''),
    ('transfer_details', 'Status', '单据状态', ''),
]


def connect() -> sqlite3.Connection:
    """只读连接库房库。immutable=1 避免建 -wal/-shm 旁路文件。"""
    if not os.path.isfile(DB_PATH):
        raise SystemExit(f'找不到库房数据库：{DB_PATH}')
    return sqlite3.connect(f'file:{DB_PATH}?immutable=1', uri=True)


def write_doc(filename: str, lines: list[str]) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines).rstrip() + '\n')
    return path


def table_columns(conn: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    return [(r[1], r[2]) for r in conn.execute(f'PRAGMA table_info("{table}")')]


def enum_values(conn: sqlite3.Connection, table: str, col: str, limit: int = 20) -> list[tuple[str, int]]:
    """取某字段的实际取值分布。空值统一记作 '(空)'。"""
    try:
        rows = conn.execute(
            f'SELECT COALESCE(NULLIF(TRIM("{col}"), \'\'), \'(空)\') AS v, COUNT(*) '
            f'FROM "{table}" GROUP BY v ORDER BY COUNT(*) DESC LIMIT ?',
            (limit,),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [(str(v), int(n)) for v, n in rows]


def table_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    except sqlite3.Error:
        return 0


# ------------------------------------------------------------------ #
# 文档 1：库房业务与数据字典
# ------------------------------------------------------------------ #

def export_dictionary(conn: sqlite3.Connection) -> str:
    warehouses = [r[0] for r in conn.execute(
        'SELECT DISTINCT "Warehouse Name" FROM inventory_details ORDER BY 1'
    ) if r[0]]

    lines = [
        '# 库房业务与数据字典（SP 备件库房）',
        '',
        '本文件说明库房（Spare Parts，物资/备件仓库）的业务口径与数据结构。',
        '库房数据由 eFlow SP 服务同步而来，**每小时同步一次**（每小时 10 分左右落库）。',
        '',
        '## 一、库房有哪些仓库',
        '',
        '当前共 **' + str(len(warehouses)) + '** 个仓库：',
        '',
    ]
    for w in warehouses:
        lines.append(f'- {w}')
    lines += [
        '',
        '> 命名规律：`Liberia <城市> Entrusted Spare Parts <用途>`。',
        '> `DOP` = 属地仓（District Office of Presence）；`Warehouse` = 主仓；',
        '> `-2nd floor` = 主仓二层；`material warehouse` = 物料仓。',
        '',
        '## 二、数据表总览',
        '',
        '库房数据分两层：**主单表**（`sp_*`）一张单一行，回答「有多少张单」；',
        '**明细表**（`*_details`）一张单多行，回答「这张单动了哪些物料」。',
        '',
        '| 表名 | 中文名 | 角色 | 数据行数 |',
        '|---|---|---|---|',
    ]
    for t, cn, desc in TABLES:
        lines.append(f'| `{t}` | {cn} | {desc} | {table_count(conn, t)} |')
    lines += [
        '',
        '## 三、单据编号规则',
        '',
        '- **SPIB** 开头 = 入库单（Inbound）',
        '- **SPOB** 开头 = 出库单（Outbound）',
        '- 调拨单（Transfer）同样使用 SPIB/SPOB 体系，靠库房字段区分原仓与目标仓',
        '- 格式：`SP<IB|OB><YYYYMMDD><流水号>`，例：`SPIB202610220006`',
        '',
        '## 四、各表字段清单',
        '',
    ]

    for t, cn, desc in TABLES:
        cols = table_columns(conn, t)
        lines.append(f'### {cn}（`{t}`）')
        lines.append('')
        lines.append(desc)
        lines.append('')
        lines.append('| 字段 | 类型 |')
        lines.append('|---|---|')
        for name, typ in cols:
            lines.append(f'| `{name}` | {typ} |')
        lines.append('')

    lines += ['## 五、枚举值字典', '', '以下取值由库房库实际数据统计得出。', '']
    for t, col, cn, note in ENUM_FIELDS:
        vals = enum_values(conn, t, col)
        if not vals:
            continue
        lines.append(f'### {t}.{col}（{cn}）')
        lines.append('')
        if note:
            lines.append(note)
            lines.append('')
        lines.append('| 取值 | 行数 |')
        lines.append('|---|---|')
        for v, n in vals:
            lines.append(f'| {v} | {n} |')
        lines.append('')

    lines += [
        '## 六、关键业务口径',
        '',
        '### 库存数量怎么取',
        '',
        '**`inventory_details` 是按日快照表，不是当前库存表。**',
        '每个 `update_date` 各存一份当日快照，全表累积到二十万行以上。',
        '**只有 `update_date` 等于全表最大值的那一份才是当前库存。**',
        '',
        '正确口径（与 my_app `backend/services/native_catalog.py` 一致）：',
        '',
        '```sql',
        'SELECT "Warehouse Name", SUM("Stock Qty")',
        'FROM inventory_details',
        'WHERE update_date = (SELECT MAX(update_date) FROM inventory_details)',
        'GROUP BY 1;',
        '```',
        '',
        '> ⚠️ 直接对全表 SUM 会得到当前库存的好几倍 —— 那是把历史快照全加了一遍。',
        '',
        '### 库存对账（Gap）',
        '',
        '每个仓库的账面差额：',
        '',
        '```',
        'Gap = 入库量 - 出库量 - 现存库存',
        '```',
        '',
        '- `Gap = 0` → 账实相符（OK）',
        '- `Gap > 0` → 账上有、库里没有（Not Inbound，入库未登记）',
        '- `Gap < 0` → 库里有、账上没有（Lost，损耗）',
        '',
        '对账要按 **序列号 × 物料 × 仓库 × 物料类型** 四键对齐，',
        '只按物料号对齐会把同一物料的不同序列号混在一起，算不出真实差额。',
        '',
        '### 入库量怎么算',
        '',
        '计入入库量的类型：`New Inbound`（新入库）、`Initial Inbound`（初始入库）、',
        '`Inventory Gain Inbound`（盘盈入库）。',
        '',
        '### 出库量怎么算',
        '',
        '计入出库量的类型：`Install Outbound`（安装出库）、`Borrow Outbound`（借出）、',
        '`Others Outbound`（其他出库）。',
        '',
        '> `Repair Outbound`（维修出库）与 `Inventory Lost Outbound`（盘亏出库）',
        '> **不计入**常规出库量 —— 维修出库是返修而非消耗，盘亏是调整。',
        '',
        '### 借出与归还',
        '',
        '- 借出（`Borrow Outbound`）会开出归还单（`Borrow Return Inbound`）',
        '- 借出单状态为 `WaitingForReturn` 表示**尚未归还**，属于未闭环',
        '- 出库单的 `outstandingReturnQty` 记录待归还数量',
        '',
        '### 序列号管理',
        '',
        '物料主表的 `materialManageType` 区分两种管理方式：',
        '',
        '- `Instance`（按序列号管理）：每个序列号单独一条库存记录，备件类为主',
        '- `Category`（按类别管理）：按数量记账，不区分序列号，耗材类为主',
        '',
        '## 七、来源',
        '',
        '数据源：`my_app/db/app.db` 的库房相关表，由 eFlow SP 服务同步。',
        '同步频率：每小时一次。最新同步时间见实时查询工具的返回。',
        '',
    ]
    return write_doc('库房-业务与数据字典.md', lines)


# ------------------------------------------------------------------ #
# 文档 2：仓库与物料清单
# ------------------------------------------------------------------ #

def export_inventory(conn: sqlite3.Connection) -> str:
    max_date = conn.execute('SELECT MAX(update_date) FROM inventory_details').fetchone()[0]

    lines = [
        '# 库房仓库清单与物料主数据',
        '',
        '## 一、各仓库当前库存（按最新快照）',
        '',
        f'快照日期（`update_date`）：**{max_date}**',
        '',
        '| 仓库 | 库存条目数 | 现存数量合计 |',
        '|---|---|---|',
    ]
    rows = conn.execute(
        'SELECT "Warehouse Name", COUNT(*), COALESCE(SUM("Stock Qty"),0) '
        'FROM inventory_details WHERE update_date = ? GROUP BY 1 ORDER BY 3 DESC',
        (max_date,),
    ).fetchall()
    for name, cnt, qty in rows:
        lines.append(f'| {name} | {cnt} | {qty} |')
    lines.append('')

    lines += [
        '## 二、仓库单据统计',
        '',
        '| 单据 | 总数 | 已闭环 | 未闭环 |',
        '|---|---|---|---|',
    ]
    for cn, table in (('入库单', 'sp_inbound'), ('出库单', 'sp_outbound'), ('调拨单', 'sp_transfer')):
        total = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        closed = conn.execute(
            f"SELECT COUNT(*) FROM \"{table}\" WHERE status LIKE 'Closed%'"
        ).fetchone()[0]
        lines.append(f'| {cn} | {total} | {closed} | {total - closed} |')
    lines += [
        '',
        '> 口径：状态以 `Closed` 开头视为已闭环，其余（含空状态）视为未闭环，',
        '> 与工单侧的 `isOpenStatus()` 判定一致。',
        '',
        '## 三、物料主数据',
        '',
        f'物料主数据共 **{table_count(conn, "sp_material")}** 条。',
        '按类型划分：',
        '',
        '| 物料类型 | 条数 |',
        '|---|---|',
    ]
    for v, n in enum_values(conn, 'sp_material', 'materialType'):
        lines.append(f'| {v} | {n} |')
    lines += [
        '',
        '### 物料清单',
        '',
        '| 物料编码 | 物料名称 | 单位 | 领域 | 子领域 | 管理方式 |',
        '|---|---|---|---|---|---|',
    ]
    mats = conn.execute(
        'SELECT materialNo, materialName, unit, domain, subDomain, materialManageType '
        'FROM sp_material ORDER BY materialType, materialNo'
    ).fetchall()
    for no, name, unit, dom, sub, manage in mats:
        def clean(v):
            return str(v).replace('|', '/').replace('\n', ' ').strip() if v else ''
        lines.append(
            f'| {clean(no)} | {clean(name)} | {clean(unit)} | {clean(dom)} | {clean(sub)} | {clean(manage)} |'
        )
    lines += [
        '',
        '## 四、来源',
        '',
        '数据源：`my_app/db/app.db` 的 `sp_material` / `sp_inbound` / `sp_outbound` /',
        '`sp_transfer` / `inventory_details`，由 eFlow SP 服务同步（每小时一次）。',
        '',
    ]
    return write_doc('库房-仓库与物料清单.md', lines)


def main() -> int:
    if not MY_APP_DIR:
        print('找不到 my_app 目录，无法定位库房数据库。')
        return 1
    print(f'my_app 目录：{MY_APP_DIR}')
    print(f'数据库：{DB_PATH}')

    conn = connect()
    try:
        for path in (export_dictionary(conn), export_inventory(conn)):
            size = os.path.getsize(path)
            print(f'  ✓ {os.path.basename(path)}（{size} 字节）')
    finally:
        conn.close()

    print(f'\n输出目录：{OUT_DIR}')
    print('下一步：npm run ingest（重建索引）→ 重启 bot 进程')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

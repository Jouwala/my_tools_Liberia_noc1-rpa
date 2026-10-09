# -*- coding: utf-8 -*-
"""全量同步的「对账删除」公共实现：让表 = 上游当前快照。

背景（2026-10-09）
------------------
`sp_online_sync` 的任务拉的是**全量**（每次请求上游整个集合），但写入只 upsert、
从不删除，于是上游已消失的单据会**永久残留**（实测 sp_outbound 积了 37 条僵尸
WaitingForUpdate，被 sp_online 报表原样呈现，而上游早已无这些单）。
修法是在 upsert 后删除「不在本轮结果里的行」。`sp_material_sync` 与
`sync_from_eflow_api._sync_site` 有同型隐患，故把删除逻辑抽到本模块共用。

⚠️ 只适用于**全量拉取**的数据源。**增量窗口**（如 `eflow_tt` 只抓最近 N 天、
设计上要累积历史）**绝不能**用本模块 —— 那会删掉历史数据。调用方必须自行
判断「本轮拉取是否完整」，不完整时**不要调用**（见各调用点的 complete 安全阀）。

为什么用临时表而不是 `NOT IN (?, ?, ...)`
------------------------------------------
1. **不能分批**：分批时每批的 `NOT IN` 只保护本批的 key，会把**后续批次**的 key
   也删掉（实测会把整表删空）。必须一次 DELETE 完成。
2. **参数上限**：key 数量可能超过 SQLite/PG 的绑定参数上限（旧 SQLite 默认 999）。
   临时表 + `NOT IN (SELECT ...)` 没有这个限制。

key 会去重（临时表主键 + 忽略重复插入），故传进来的集合含重复值也无妨。
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Iterable

logger = logging.getLogger(__name__)

#: 写入临时表的批量大小：只为减少往返，与 SQL 参数上限无关（临时表方案无上限）。
_INSERT_BATCH = 500

#: 临时表名：按被对账的表名派生，避免同连接内多次对账互相撞车。
_TMP_PREFIX = "tmp_reconcile_"


def _quote(col: str) -> str:
    return '"' + col.replace('"', '""') + '"'


def delete_not_in_keys(cursor, table: str, key_col: str, keys: Iterable,
                       is_pg: bool = None) -> int:
    """删除 ``table`` 中 ``key_col`` 不在 ``keys`` 里的行，返回删除行数。

    调用前必须已在该连接上完成 upsert，且 ``keys`` 是**本轮成功拉取到的全量主键**。
    `is_pg` 缺省时按连接类型推断（psycopg2 连接的 cursor 模块名以 psycopg 开头）。

    ⚠️ 调用方负责事务提交；本函数不做 commit。
    """
    key_list = [k for k in (str(k) for k in keys) if k]
    if is_pg is None:
        is_pg = "psycopg" in type(cursor).__module__
    if not key_list:
        # 空集合意味着「本轮一个主键都没拿到」——删光整表几乎必然是上游异常，
        # 这里直接拒绝而不是清表，让调用方的 complete 安全阀之外的兜底生效。
        logger.warning(
            f"[reconcile] {table}: 本轮主键集合为空，拒绝删除（避免清空整表）")
        return 0

    tmp = f"{_TMP_PREFIX}{table}"
    pk_q = _quote(key_col)

    cursor.execute(f'DROP TABLE IF EXISTS "{tmp}"')
    cursor.execute(f'CREATE TEMP TABLE "{tmp}" ("k" TEXT PRIMARY KEY)')

    sql = (f'INSERT INTO "{tmp}" ("k") VALUES (?) ON CONFLICT DO NOTHING'
           if is_pg else
           f'INSERT OR IGNORE INTO "{tmp}" ("k") VALUES (?)')
    for i in range(0, len(key_list), _INSERT_BATCH):
        batch = key_list[i:i + _INSERT_BATCH]
        cursor.executemany(sql, [(k,) for k in batch])

    before = int(cursor.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    cursor.execute(
        f'DELETE FROM "{table}" WHERE {pk_q} NOT IN '
        f'(SELECT "k" FROM "{tmp}")')
    after = int(cursor.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    deleted = before - after

    cursor.execute(f'DROP TABLE IF EXISTS "{tmp}"')
    return deleted

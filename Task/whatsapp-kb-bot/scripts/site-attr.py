#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""站点**属性**查询 —— HTTP 通道不可用时的本地降级路径。

用法：
    python site-attr.py --site "Lofa Bridge"

输出：单行 JSON 到 stdout（供 src/siteattr.js 解析后模板渲染）。

## 为什么需要这个脚本

2026-11-03 实测故障：问「站点 lofa bridge 是 VIP 站点吗」，机器人答
「是 VIP 站点，依据 assetType 为 vipSite」——结论错、依据错、来源错。
根因是**知识库里没有站点实体数据**，只有规则；模型于是从规则反推站点属性，
还把 ``assetType``（取值只有 NORMAL/COOL/ERA）和 ``vipSite``（独立字段）
揉成了一个根本不存在的值。

所以站点属性必须走**数据源**。本脚本是降级通道：
  · 主通道 = HTTP 调 my_app 的 `/api/site-attribute`（PG 生产库，实时）；
  · 本脚本 = 读 my_app 的 **SQLite 同步副本** `db/app.db`。

⚠️ **降级必须如实告知口径**：副本有同步延迟，站点属性（尤其 VIP 标记）
改动不频繁，但**不能**让用户以为看到的是实时值 —— 由上层在回复里标注。

## 三处数据源与口径（与后端 routers/site_attribute.py 严格一致）

============  ==================  ==========  =====================
表            字段                取值        含义
============  ==================  ==========  =====================
eflow_site    vipsite             Yes / No   eFlow 侧站点属性（主口径）
master_site_db vip_site           Y / N      主站表的 VIP 标记
vip_site_list （整表即名单）       —          独立维护的 VIP 站名单
============  ==================  ==========  =====================

⚠️ **三处不一致时如实报冲突**，不挑一个顺眼的报。

## 列名的方言差异（最容易踩的坑）

同一张表在两种后端下列名不同（实测 2026-11-03）：

* PG（生产库）：``site_id`` / ``site_name`` / ``vipsite``
* SQLite（副本）：``"Site ID"`` / ``"Site Name"`` / ``vipsite``

所以**不能硬编码列名**。本脚本与后端一样用「候选列名列表」探测
（``_resolve_cols``），先看表里到底有哪个列名再拼 SQL。

## 退出码

    0  成功（含「查无此站」—— found=false 是有效答案，不是错误）
    2  库不可用 / 参数不合法（永久问题，不重试）
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

# 输出编码兜底：被 Node 以管道接走时必须 UTF-8，否则系统代码页
# 一 print 中文就 UnicodeEncodeError（与 tt-query.py 同因）。
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream.isatty():
            _stream.reconfigure(errors='replace')
        else:
            _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import my_app_paths  # noqa: E402

DB_PATH = my_app_paths.resolve('MY_APP_DB', 'db', 'app.db')


# ------------------------------------------------------------ 列名探测

# 与后端 routers/site_attribute.py 的 _EFLOW_SITE_COLS 保持一致。
_EFLOW_SITE_COLS = {
    'site_id': ['site_id', 'Site ID'],
    'site_name': ['site_name', 'Site Name'],
    'region': ['region', 'Region'],
    'province': ['province_county', 'Province'],
    'site_type': ['site_type', 'Site Type'],
    'vipsite': ['vipsite', 'VIPSite', 'vip_site'],
    'sitesubtype': ['sitesubtype', 'SiteSubType', 'site_sub_type'],
    'hubsite': ['hubsite', 'HubSite', 'hub_site'],
    'site_information': ['site_information', 'Site Information'],
    'site_priority': ['site_priority', 'Site Priority'],
    'site_class': ['site_class', 'Site Class'],
    'ran_site': ['ran_site', 'Ran Site'],
    'victims': ['victims', 'Victims'],
    'fme_name': ['updated_fme_name_new', 'FME Name', 'fme_name'],
    'sync_time': ['_sync_time', 'Sync Time'],
}

_MASTER_SITE_COLS = {
    'site_id': ['site_id', 'Site ID'],
    'site_name': ['site_name', 'Site Name'],
    'region': ['region', 'Region'],
    'province': ['province_county', 'Province'],
    'site_type': ['site_type', 'Site Type'],
    'vip_site': ['vip_site', 'VIPSite', 'vipsite'],
    'hub_site': ['hub_site', 'HubSite', 'hubsite'],
    'site_caregory': ['site_caregory', 'Site Category'],
    'victims': ['victims', 'Victims'],
    'fme_name': ['fme_name', 'FME Name'],
    'latitude': ['latitude', 'Latitude'],
    'longitude': ['longitude', 'Longitude'],
}

_VIP_LIST_COLS = {
    'site_id': ['site_id', 'Site ID'],
    'site_name': ['site_name', 'Site Name'],
    'region': ['region', 'Region'],
    'province': ['province_county', 'Province'],
    'victims': ['victims', 'Victims'],
}


def _connect():
    """只读打开。

    `immutable=1` 与 tt-query.py 同因：库在部分部署里位于网络盘，
    用它跳过 WAL 与加锁，避免读到一半被同步任务锁住而抛 database is locked。

    ⚠️ **必须设 row_factory=sqlite3.Row** —— 默认返回 tuple，
    `row["列名"]` 会抛 TypeError（不是 KeyError），取值全部失败。
    """
    if not os.path.isfile(DB_PATH):
        raise FileNotFoundError(f'站点库不存在：{DB_PATH}')
    con = sqlite3.connect(f'file:{DB_PATH}?immutable=1', uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con, table):
    cur = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def _resolve_cols(con, table, spec):
    """把「逻辑字段 → 实际列名」解析出来（不存在该表则返回空 dict）。"""
    try:
        cur = con.execute(f'PRAGMA table_info("{table}")')
        have = {r[1] for r in cur.fetchall()}
    except Exception:
        return {}
    out = {}
    for logical, candidates in spec.items():
        for c in candidates:
            if c in have:
                out[logical] = c
                break
    return out


def _pick(row, cols, logical):
    col = cols.get(logical)
    if not col:
        return None
    try:
        return row[col]
    except (KeyError, IndexError, TypeError):
        return None


def _norm_yesno(value):
    """Yes/No、Y/N、1/0、True/False → True/False/None（未知）。

    ⚠️ **无法识别的值一律 None（未知），绝不猜** —— 站点属性是结论性字段，
    猜错比说「不知道」危害大得多。
    """
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ('yes', 'y', '1', 'true', 't'):
        return True
    if s in ('no', 'n', '0', 'false', 'f'):
        return False
    return None


def _like_pattern(name):
    """站名模糊匹配 pattern（转义 % 与 _，避免下划线变成通配符）。"""
    escaped = str(name).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped.lower()}%'


def _query(con, table, cols_spec, site):
    """按站名模糊匹配一张表。返回 (命中行列表, 解析出的列名)。"""
    if not _table_exists(con, table):
        return [], {}
    cols = _resolve_cols(con, table, cols_spec)
    if 'site_name' not in cols:
        return [], cols
    name_col = cols['site_name']
    sql = f'SELECT * FROM "{table}" WHERE LOWER("{name_col}") LIKE ?'
    rows = con.execute(sql, (_like_pattern(site),)).fetchall()
    return list(rows), cols


def _exact_match(rows, cols, site):
    """从模糊命中里挑完全相等（忽略大小写）的那一行。

    模糊匹配可能命中「Lofa Bridge Camp」这类同前缀的站；属性结论要精确，
    所以优先用完全相等的行，没有再用第一条模糊命中。
    """
    target = str(site).strip().lower()
    name_col = cols.get('site_name')
    if not name_col:
        return rows[0] if rows else None
    for r in rows:
        try:
            if str(r[name_col] or '').strip().lower() == target:
                return r
        except (KeyError, IndexError, TypeError):
            break
    return rows[0] if rows else None


def build_payload(site, con):
    """把三处查询结果归一化成一份站点属性（结构与后端一致）。"""
    eflow_rows, eflow_cols = _query(con, 'eflow_site', _EFLOW_SITE_COLS, site)
    master_rows, master_cols = _query(con, 'master_site_db', _MASTER_SITE_COLS, site)
    vip_rows, vip_cols = _query(con, 'vip_site_list', _VIP_LIST_COLS, site)

    eflow = _exact_match(eflow_rows, eflow_cols, site)
    master = _exact_match(master_rows, master_cols, site)

    # ---- 三处 VIP 判定 ----
    eflow_vip = _norm_yesno(_pick(eflow, eflow_cols, 'vipsite')) if eflow else None
    master_vip = _norm_yesno(_pick(master, master_cols, 'vip_site')) if master else None
    list_vip = True if vip_rows else None

    votes = [v for v in (eflow_vip, master_vip, list_vip) if v is not None]
    if not votes:
        is_vip = None
        consistency = 'unknown'
    elif len(set(votes)) == 1:
        is_vip = votes[0]
        consistency = 'agree' if len(votes) > 1 else 'single_source'
    else:
        is_vip = eflow_vip if eflow_vip is not None else master_vip
        consistency = 'conflict'

    def field(logical):
        v = _pick(eflow, eflow_cols, logical) if eflow else None
        if v in (None, ''):
            v = _pick(master, master_cols, logical) if master else None
        return v

    name = _pick(eflow, eflow_cols, 'site_name') if eflow else None
    if not name and master:
        name = _pick(master, master_cols, 'site_name')

    site_id = _pick(eflow, eflow_cols, 'site_id') if eflow else None
    if site_id in (None, '') and master:
        site_id = _pick(master, master_cols, 'site_id')

    hub = _norm_yesno(_pick(eflow, eflow_cols, 'hubsite')) if eflow else None
    if hub is None and master:
        hub = _norm_yesno(_pick(master, master_cols, 'hub_site'))

    payload = {
        'site': str(site),
        'found': bool(eflow or master or vip_rows),
        'site_id': site_id,
        'site_name': name,
        'is_vip': is_vip,
        'consistency': consistency,
        'vip_sources': {
            'eflow_site': eflow_vip,
            'master_site_db': master_vip,
            'vip_site_list': list_vip,
        },
        'site_type': field('site_type'),
        'site_sub_type': field('sitesubtype'),
        'is_hub_site': hub,
        'region': field('region'),
        'province': field('province'),
        'site_information': field('site_information'),
        'site_priority': field('site_priority'),
        'site_class': field('site_class'),
        'is_ran_site': _norm_yesno(field('ran_site')),
        'victims': field('victims'),
        'fme_name': field('fme_name'),
        'latitude': field('latitude'),
        'longitude': field('longitude'),
        'sync_time': _pick(eflow, eflow_cols, 'sync_time') if eflow else None,
        'source': 'sqlite',
    }

    if not payload['found']:
        payload['candidates'] = _candidates(eflow_rows, eflow_cols,
                                            master_rows, master_cols)
    return payload


def _candidates(eflow_rows, eflow_cols, master_rows, master_cols):
    """查无此站时给几个相近站名供用户核对。"""
    out = []
    for rows, cols in ((eflow_rows, eflow_cols), (master_rows, master_cols)):
        name_col = cols.get('site_name')
        if not name_col:
            continue
        for r in rows[:5]:
            try:
                out.append(str(r[name_col] or '').strip())
            except (KeyError, IndexError, TypeError):
                continue
    seen, uniq = set(), []
    for n in out:
        if n and n.lower() not in seen:
            seen.add(n.lower())
            uniq.append(n)
    return uniq[:8]


def main():
    ap = argparse.ArgumentParser(description='站点属性查询（本地 SQLite 降级通道）')
    ap.add_argument('--site', required=True, help='站点名或站号')
    args = ap.parse_args()

    site = (args.site or '').strip()
    if not site:
        print(json.dumps({'error': '站点名不能为空'}, ensure_ascii=False))
        return 2

    try:
        con = _connect()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({'error': str(e)}, ensure_ascii=False))
        return 2

    try:
        payload = build_payload(site, con)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({'error': f'查询站点属性失败：{e}'}, ensure_ascii=False))
        return 2
    finally:
        con.close()

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""工单**聚合统计**查询 —— HTTP 通道不可用时的本地降级路径。

用法：
    python tt-query.py --start 2026-10-06 --end 2026-10-06 [--severity P1]
                       [--status open|closed|all] [--site 站名] [--limit 5]

输出：单行 JSON 到 stdout（供 src/ttquery.js 解析后模板渲染）。

## 为什么单独一个脚本，而不是复用 tt-analyze.py

两者回答的是**不同形态**的问题：
  · tt-analyze.py  → 「这一单现在什么情况」：按单号取**一行**，再套规则判定；
  · 本脚本        → 「今天有几个 P1」：按条件做 **GROUP BY 聚合**。
硬塞进同一个脚本，等于让一个入口同时承担「单条详情」和「区间统计」两套参数与
返回结构，两边都会变得难读。

## 为什么它是「降级」而不是「主通道」

生产库是 **PostgreSQL**（my_app 的 `/api/health` 返回 `db_mode=pg`），
而本脚本读的是 my_app 的 **SQLite 同步副本** `db/app.db`。副本有同步延迟，
实测同一天同一口径两边会差几单（2026-10-06：PG 侧 P3=37，本地副本按
alarm_occur_time 只有 26）。所以：
  · 主通道 = HTTP 调 my_app 的 `/api/tt-wo-dashboard/overview`（PG 实时）；
  · 本脚本 = my_app 服务没起、或 HTTP 超时时的兜底。
降级必须**如实告知口径**，由上层在回复里标注「本地副本，可能滞后」，
不能让用户以为看到的是实时数字。

## 时间字段为什么用 alarm_occur_time

与 my_app 的 `_time_filter`（`backend/routers/tt_wo_dashboard.py:92`）保持一致 ——
它过滤的就是 `alarm_occur_time`。两条通道若各用一个时间字段，同一个问题会
得到两个不同的数，那是最难排查的一类故障（看起来都"能跑"，只是数对不上）。

退出码（与 tt-analyze.py 同一套约定，上游按同一规则解读）：
    0  成功
    2  库不可用 / 参数不合法（永久或需人工介入，不重试）
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

# 输出编码兜底：被 Node 以管道接走时必须 UTF-8，否则系统代码页（本机 cp1252）
# 一 print 中文就 UnicodeEncodeError。
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

# 与 tt-analyze.py 同一套定位逻辑（可用 MY_APP_DB 覆盖），不写死盘符。
DB_PATH = my_app_paths.resolve('MY_APP_DB', 'db', 'app.db')

# 与 my_app 概览接口一致：按「告警发生时间」过滤，不是建单时间。
TIME_FIELD = 'alarm_occur_time'

# 状态里这些前缀代表「未闭环」。工单库里 Closed 是唯一闭环态，
# 其余（Waiting for ... / Suspended 等）一律算未闭环。
CLOSED_PREFIX = 'Closed'


def _connect():
    """只读打开。

    `immutable=1` 与 tt-analyze.py:936 同因：工单库在部分部署里位于网络盘，
    用它跳过 WAL 与加锁，避免读到一半被同步任务锁住而抛 database is locked。
    """
    if not os.path.isfile(DB_PATH):
        raise FileNotFoundError(f'工单库不存在：{DB_PATH}')
    return sqlite3.connect(f'file:{DB_PATH}?immutable=1', uri=True)


def build_where(start: str | None, end: str | None, severity: str | None,
                status: str, site: str | None, keyword: str | None = None):
    """构建 WHERE 片段与参数。

    end 为**闭区间**（与 my_app 的 `_time_filter` 一致）：内部 +1 天后取 `<`，
    即包含 end 当天全天。

    keyword 是**领域关键字**（如 `Fiber`），在各文本列上做不区分大小写的模糊匹配。
    2026-10-26 起因：群里问「How many Fiber issues related TTs for last 7 days?」
    与「How many TTs in last 7 days?」得到**同一个数**（753）——「Fiber」被丢掉了。
    """
    parts, params = [], []
    if start:
        parts.append(f'{TIME_FIELD} >= ?')
        params.append(f'{start} 00:00:00')
    if end:
        # 用 Python 算次日，而不是拼 SQL 日期函数 —— 后者在 SQLite 里可行，
        # 但会让「闭区间」这个语义散落到 SQL 方言里，将来换 PG 又要改一遍。
        from datetime import datetime, timedelta
        nxt = (datetime.strptime(end, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
        parts.append(f'{TIME_FIELD} < ?')
        params.append(f'{nxt} 00:00:00')
    if severity:
        parts.append('UPPER(TRIM(COALESCE(ticket_severity, \'\'))) = ?')
        params.append(severity.upper())
    if status == 'open':
        # 空状态也归为未闭环：库里确有 status 为空的行，当成已闭环会少报。
        parts.append(
            "(status IS NULL OR TRIM(status) = '' OR status NOT LIKE ?)"
        )
        params.append(f'{CLOSED_PREFIX}%')
    elif status == 'closed':
        parts.append('status LIKE ?')
        params.append(f'{CLOSED_PREFIX}%')
    if site:
        parts.append('(site_name LIKE ? OR site_id LIKE ?)')
        params.extend([f'%{site}%', f'%{site}%'])
    if keyword:
        # 只在这些**告警语义文本列**上匹配。实测 DB 里 `iber` 的分布：
        #   title 277 / description 413 / alarm_description 249 / specific_problem 37，
        # 而 alarm_category / sub_alarm_name 等结构化列几乎为空（≤5 行），
        # 所以结构化列不进匹配集 —— 加了只会让语义更含糊。
        # ⚠️ 不匹配 site_name：站名里出现 "Fiber" 不代表这一单是光纤故障。
        cols = ('title', 'description', 'alarm_description', 'specific_problem')
        parts.append('(' + ' OR '.join(f'COALESCE({c}, \'\') LIKE ?' for c in cols) + ')')
        params.extend([f'%{keyword}%'] * len(cols))

    where = (' WHERE ' + ' AND '.join(parts)) if parts else ''
    return where, params


def query(start, end, severity, status, site, limit, keyword=None):
    """执行一次聚合查询，返回结果字典。"""
    where, params = build_where(start, end, severity, status, site, keyword)

    con = _connect()
    try:
        cur = con.cursor()

        total = cur.execute(
            f'SELECT COUNT(*) FROM eflow_tt{where}', params
        ).fetchone()[0]

        # 级别分布：忽略「没有级别」的行（Unknown / 空），
        # 与 my_app 的 `_ticket_severity_key`（tt_wo_dashboard.py:126）同口径 ——
        # 否则卡片上不显示 Unknown，这里却冒出来一个 Unknown 桶。
        by_sev = {}
        for sev, cnt in cur.execute(
            f"""SELECT ticket_severity, COUNT(*) FROM eflow_tt{where}
                GROUP BY ticket_severity""", params
        ):
            key = str(sev or '').strip()
            if not key or key.lower() in ('unknown', 'unkonw', 'none'):
                continue
            by_sev[key] = by_sev.get(key, 0) + cnt

        open_cnt = cur.execute(
            f"""SELECT COUNT(*) FROM eflow_tt{where}
                AND (status IS NULL OR TRIM(status) = '' OR status NOT LIKE 'Closed%')""",
            params,
        ).fetchone()[0] if where else cur.execute(
            """SELECT COUNT(*) FROM eflow_tt
               WHERE status IS NULL OR TRIM(status) = '' OR status NOT LIKE 'Closed%'"""
        ).fetchone()[0]

        samples = []
        for row in cur.execute(
            f"""SELECT tt_no, ticket_severity, status, site_name, site_id,
                       {TIME_FIELD}, alarm_clear_time, domain
                FROM eflow_tt{where}
                ORDER BY {TIME_FIELD} DESC LIMIT ?""",
            params + [max(0, int(limit))],
        ):
            samples.append({
                'tt_no': row[0] or '',
                'ticket_severity': row[1] or '',
                'status': row[2] or '',
                'site_name': row[3] or '',
                'site_id': row[4] or '',
                'alarm_occur_time': row[5] or '',
                'alarm_clear_time': row[6] or '',
                'domain': row[7] or '',
            })

        # 数据截止时间：让用户能自己判断「这份数据有多旧」。
        # 取全库最大建单时间，而不是本次过滤窗口内的最大值 ——
        # 后者在查「今天有没有 P1」且今天一单都没有时会返回空，反而更没用。
        latest = cur.execute('SELECT MAX(created_time) FROM eflow_tt').fetchone()[0] or ''

        return {
            'source': 'sqlite',
            'time_field': TIME_FIELD,
            'start': start,
            'end': end,
            'severity': severity,
            'status': status,
            'keyword': keyword or '',
            'total': total,
            'open': open_cnt,
            'closed': total - open_cnt,
            'by_severity': dict(sorted(by_sev.items())),
            'samples': samples,
            'latest': latest,
        }
    finally:
        con.close()


def site_names(tt_nos):
    """按单号批量取站名 —— 供 HTTP 通道补齐它拿不到的 site_name。

    ## 为什么需要这个「补字段」模式

    my_app 的 `/api/tt-wo-dashboard/drilldown` **不返回 site_name**
    （返回字段里只有 site_id），而本地 `eflow_tt` 表里 `site_name` 是全的
    （实测 37223 行里空值 0 行）。

    最初 HTTP 通道是用正则从 `title`（格式 `<站号>.[<站名>]<告警名>`）里抠站名的，
    但实测 **241/37223 行的 title 里没有方括号** —— 那些单子会静默退化成
    「TT2026...（5021）」，群里没人认得出 5021 是哪个站。

    所以改成：**计数仍走 HTTP（PG 实时），站名回本地表按主键补**。
    取数代价只有一次按 `tt_no` 的点查，且 `tt_no` 是本表主键，
    比正则猜字符串可靠得多。

    补不到就留空，由上层退回站号 —— 不因为一个展示字段让整个查询失败。
    """
    if not tt_nos:
        return {}
    con = None
    try:
        con = _connect()
        cur = con.cursor()
        out = {}
        # 分批查，避免 SQLite 的变量数上限（默认 999）
        for i in range(0, len(tt_nos), 500):
            batch = tt_nos[i:i + 500]
            marks = ','.join('?' * len(batch))
            for no, name in cur.execute(
                f'SELECT tt_no, site_name FROM eflow_tt WHERE tt_no IN ({marks})',
                batch,
            ):
                if no:
                    out[str(no)] = (name or '').strip()
        return out
    except Exception:
        # 补字段失败不该让已经拿到的统计结果作废：上层会退回站号显示。
        return {}
    finally:
        if con is not None:
            con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description='工单聚合统计（本地 SQLite 降级通道）')
    ap.add_argument('--start', help='起始日期 YYYY-MM-DD（含）')
    ap.add_argument('--end', help='结束日期 YYYY-MM-DD（含）')
    ap.add_argument('--severity', help='级别 P1~P4')
    ap.add_argument('--status', default='all', choices=['all', 'open', 'closed'],
                    help='闭环状态过滤，默认 all')
    ap.add_argument('--site', help='站点名/站号模糊匹配')
    ap.add_argument('--keyword', help='领域关键字模糊匹配（如 Fiber），见 build_where')
    ap.add_argument('--limit', type=int, default=5, help='样例单最多返回几条')
    ap.add_argument('--site-names', metavar='TT_NO[,TT_NO...]',
                    help='只按单号批量取站名（供 HTTP 通道补 site_name）')
    args = ap.parse_args()

    # 补字段模式：不查统计，只回 {单号: 站名}
    if args.site_names:
        nos = [s.strip() for s in args.site_names.split(',') if s.strip()]
        print(json.dumps({'site_names': site_names(nos)}, ensure_ascii=False))
        return 0

    for d in (args.start, args.end):
        if d:
            try:
                from datetime import datetime
                datetime.strptime(d, '%Y-%m-%d')
            except ValueError:
                print(f'日期格式不对（应为 YYYY-MM-DD）：{d}', file=sys.stderr)
                return 2

    try:
        res = query(args.start, args.end, args.severity, args.status, args.site,
                    args.limit, args.keyword)
    except Exception as e:
        # 只打原因，不加前缀 —— 上游 ttquery.js 会按语言包一层「查询失败：」。
        print(str(e), file=sys.stderr)
        return 2

    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

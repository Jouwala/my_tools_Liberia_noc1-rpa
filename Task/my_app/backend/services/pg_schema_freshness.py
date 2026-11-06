# -*- coding: utf-8 -*-
"""pg_schema_freshness.py —— 本机 PG schema 的水位 + 逐日覆盖巡检（只读）。

为什么要单独加这一类（2026-11-05）
----------------------------------
IP RAN 四个看板（metro_ring / ipran_hq / ipran_4region / fw_daily）自 2026-11-04 起
读**本机 PG 的 ``ipran_ume`` schema**，而采集侧的 ``mirror_rows_to_local`` 是
「只追头部水位」的增量镜像 —— 只写本机 ``MAX("Begin Time") - 2h`` 之后的行，
所以**中间断掉的日子永远不会自动补回来**。2026-11-05 把看板默认窗口改成 31 天
时实测发现：近 31 天里本机只有 10 天有数，而远端权威库 32 天齐全。

更关键的是这个洞**当时没有任何巡检能查到**：

| 既有检查 | 查的是谁 | 为什么查不到 |
| --- | --- | --- |
| `db_freshness_check.REMOTE_CHECKS` | 远端 `.19:8765` 库的水位 | 远端一直是新的 → 永远绿 |
| `db_freshness_check.LOCAL_CHECKS` 的「ipran 本地回退库」 | `data/ipran_ume/ipran_ume_kpi.sqlite3` | 该文件在 `MY_APP_DB_MODE=pg` 下已被透明重定向，实际不再写 |
| 判据本身 | 「最新 Begin Time 够不够新」 | 天生看不见「中间少了 20 天」 |

本模块补的就是这两件事：**查看板真正读的那个库**，并且**按天判覆盖**；缺失日
再拿远端权威库对照一次，把「镜像洞（能用 backfill 补）」和「上游没采到
（补不了，得查采集）」分开说 —— 否则运维看到的只是一句「缺 20 天」，不知道该
往哪边使劲。

设计约束
--------
- **只读**：只发 SELECT；连不上 / 报错一律记 `read_error`，不把巡检置失败
  （沿用 `db_freshness_check` 的「数据滞后 ≠ 巡检失败」，避免 auto_retry 空转）。
- 清单 `PG_SCHEMA_CHECKS` 只用字面量（不含 lambda / 函数调用），
  因为 `tests/test_doc_consistency.py` 要用 `ast.literal_eval` 静态比对它与
  `dashboard_service.PUSH_DOWN_TABLES` 是否一致 —— 新增下推表忘了配巡检，
  本地钩子与 CI 会拦下。
- 时间基准用 UTC（本机时钟就是 UTC，见 `docs/manual/13-operations.md`）。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("pg_schema_freshness")

# 巡检清单：一个 dict = 一个本机 PG schema 的一组表
PG_SCHEMA_CHECKS: List[Dict[str, Any]] = [
    dict(
        label="IP RAN 本机 PG（四个看板的唯一真相源）",
        schema="ipran_ume",
        db="ipran_ume_kpi.sqlite3",          # 远端权威库同名文件，用于缺失日对照
        column="Begin Time",
        lookback_days=31,                    # 覆盖判定窗口 = 看板默认窗口（PUSH_DOWN_DAYS）
        max_age_hours=6.0,                   # 水位容忍：采集每小时一次，留 6h 余量
        thin_ratio=0.5,                      # 当日行数 < 峰值×0.5 记为「偏薄」
        task_id="ipran_kpi_sync",
        task_cron="0 * * * *",
        service="backend/services/ipran_ume_kpi_service.py::run_ipran_kpi_sync",
        write_path="远端写成功后 mirror_rows_to_local 增量镜像（只追头部水位）",
        tables=(
            "Metro_ring_me_15mins",
            "Gbarnga_Buchanna_RIA_Kakata_me_15mins",
            "Banjor_ELWA_me_15mins",
            "IPCORE_HQ_ODC_bnctp_15mins",
            "OLT_bnctp_15mins",
            "HQ_M6K_FW_bnctp_15mins",
        ),
    ),
]

BACKFILL_CMD = ("python -m backend.scripts.backfill_ipran_pg "
                "--since {day} --tables {table}")


# ----------------------------------------------------------------------
# 数据访问（全部只读）
# ----------------------------------------------------------------------
def _pg_day_counts(check: dict, table: str, since: str) -> Tuple[Dict[str, int], Optional[str]]:
    """本机 PG：某表 since 之后逐日行数。返回 ({日期: 行数}, 错误串)。"""
    import psycopg2

    from backend.database import PG_DATABASE_URL

    if not PG_DATABASE_URL:
        return {}, "本机 PG 未配置 DATABASE_URL（检查 backend/.env）"
    col = check["column"].replace('"', '""')
    tbl = table.replace('"', '""')
    sql = (f'SELECT substr("{col}",1,10) AS d, COUNT(*) AS c '
           f'FROM "{tbl}" WHERE "{col}" >= %s GROUP BY 1 ORDER BY 1')
    conn = None
    try:
        conn = psycopg2.connect(
            PG_DATABASE_URL, connect_timeout=10,
            options=(f"-c search_path={check['schema']} "
                     "-c statement_timeout=60000"))
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute(sql, (since,))
            rows = cur.fetchall()
        out: Dict[str, int] = {}
        for d, c in rows:
            if d:
                out[str(d)[:10]] = int(c or 0)
        return out, None
    except Exception as exc:  # noqa: BLE001 —— 手段故障只记录，不抛
        logger.warning("[PgFresh] 本机 PG 读取失败 %s.%s: %s",
                       check["schema"], table, exc)
        return {}, str(exc)[:200]
    finally:
        if conn is not None:
            conn.close()


def _pg_max_time(check: dict, table: str) -> Tuple[str, Optional[str]]:
    """本机 PG：某表最新业务时间（水位）。返回 (文本值, 错误串)。"""
    import psycopg2

    from backend.database import PG_DATABASE_URL

    if not PG_DATABASE_URL:
        return "", "本机 PG 未配置 DATABASE_URL"
    col = check["column"].replace('"', '""')
    tbl = table.replace('"', '""')
    conn = None
    try:
        conn = psycopg2.connect(
            PG_DATABASE_URL, connect_timeout=10,
            options=(f"-c search_path={check['schema']} "
                     "-c statement_timeout=60000"))
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute(f'SELECT MAX("{col}") FROM "{tbl}"')
            row = cur.fetchone()
        return (str(row[0])[:19] if row and row[0] else ""), None
    except Exception as exc:  # noqa: BLE001
        return "", str(exc)[:200]
    finally:
        if conn is not None:
            conn.close()


def _remote_has_day(check: dict, table: str, day: str) -> Optional[bool]:
    """远端权威库该日有没有数据（逐日 EXISTS，只读）。None = 查不动。

    用 EXISTS 而不是 COUNT：Metro_ring 单表 31 天是 340 万行，COUNT 会拖慢
    远端那个单线程只读 API；`LIMIT 1` 命中首行即返回（实测毫秒级）。
    """
    from backend.services import remote_readonly

    col = check["column"].replace('"', '""')
    tbl = table.replace('"', '""')
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    sql = (f'SELECT "{col}" FROM "{tbl}" '
           f'WHERE "{col}" >= \'{day}\' AND "{col}" < \'{nxt}\' LIMIT 1')
    try:
        rows = remote_readonly.query_rows(check["db"], sql, limit=1, timeout=120)
        return bool(rows)
    except Exception as exc:  # noqa: BLE001 —— 远端不可达时降级为「未知」
        logger.warning("[PgFresh] 远端对照失败 %s %s: %s", table, day, exc)
        return None


# ----------------------------------------------------------------------
# 判定
# ----------------------------------------------------------------------
def _advice(check: dict, table: str, days: List[str]) -> List[str]:
    """滞后时的调用链路与处理方向（与 _derived_advice 同构）。"""
    head = (f"{len(days)} 个缺失日，逐条补（幂等 upsert，重复跑不会重复）："
            if days else "无缺失日")
    return [
        f"定时任务 {check['task_id']} (cron: {check['task_cron']})",
        f"→ {check['service']}",
        f"→ {check['write_path']}",
        f"→ 本机 PG {check['schema']}.{table}",
        head,
        "1. " + BACKFILL_CMD.format(day=days[0] if days else "YYYY-MM-DD",
                                    table=table),
        "2. 回填前先确认远端权威库那几天有没有数 —— 本巡检已对照过，"
        "结论写在 reason 里（远端也没有就不是镜像洞，是采集断档）",
        f"3. 采集断档：Task Manager 查任务 {check['task_id']} 那些天的执行记录",
    ]


def _norm_mx(mx: str) -> Optional[datetime]:
    """把水位文本转成 naive UTC datetime（带 +00:00 后缀的先剥掉）。"""
    if not mx:
        return None
    text = mx[:19].replace("T", " ")
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def check_pg_schema(check: dict, now: datetime, results: List[dict],
                    stale_items: List[dict]) -> None:
    """一个 schema 清单：逐表判水位 + 近 N 天逐日覆盖，缺失日拿远端对照。"""
    schema, tables = check["schema"], tuple(check["tables"])
    lookback = int(check.get("lookback_days", 31))
    thin_ratio = float(check.get("thin_ratio", 0.5))
    today = now.date()
    # 判定到「昨天」为止：今天还没过完，按天判必然“缺”
    last_full = today - timedelta(days=1)
    since = (today - timedelta(days=lookback)).isoformat()
    expected = [(last_full - timedelta(days=i)).isoformat()
                for i in range(0, lookback)]

    for table in tables:
        days, err = _pg_day_counts(check, table, since)
        if err:
            results.append(dict(scope="pg_schema", db=schema, table=table,
                                status="read_error", detail=err))
            stale_items.append(dict(db=f"{schema}.{table}", table="*",
                                    reason=f"本机 PG 读取失败：{err}",
                                    guidance=_advice(check, table, [])))
            continue

        mx, mx_err = _pg_max_time(check, table)
        if mx_err:
            results.append(dict(scope="pg_schema", db=schema, table=table,
                                status="read_error", detail=mx_err))
            continue

        # 1) 水位
        mx_dt = _norm_mx(mx)
        max_age = float(check.get("max_age_hours", 6.0))
        stale_by_age = mx_dt is None or (now - mx_dt).total_seconds() > max_age * 3600
        # 2) 覆盖（缺日）
        missing = [d for d in expected if d not in days]
        # 3) 偏薄日（有数但明显少于峰值，多为采集只跑了一半）
        peak = max(days.values()) if days else 0
        thin = [d for d in expected
                if d in days and peak and days[d] < peak * thin_ratio]

        if not stale_by_age and not missing:
            results.append(dict(scope="pg_schema", db=schema, table=table,
                                status="ok", latest=mx, days=len(days),
                                thin_days=len(thin)))
            continue

        # 缺失日逐条对照远端，拆成「镜像洞」与「上游断档」两类
        mirror_holes: List[str] = []
        upstream_gaps: List[str] = []
        unknown: List[str] = []
        for d in missing[:12]:                    # 上限 12 天，别把远端问爆
            has = _remote_has_day(check, table, d)
            if has is True:
                mirror_holes.append(d)
            elif has is False:
                upstream_gaps.append(d)
            else:
                unknown.append(d)

        parts = []
        if stale_by_age:
            parts.append(f"水位落后（最新 {mx or '空表'}，容忍 {max_age:.0f}h）")
        if missing:
            parts.append(f"近 {lookback} 天缺 {len(missing)} 天"
                         f"（{missing[0]} 起，最早 3 个：{missing[:3]}）")
        if thin:
            parts.append(f"另有 {len(thin)} 天偏薄（< 峰值 {peak} 的 "
                         f"{thin_ratio:.0%}）")
        verdict = []
        if mirror_holes:
            verdict.append(f"{len(mirror_holes)} 天**远端有、本机没有** → 镜像洞，"
                           f"可用 backfill 补：{BACKFILL_CMD.format(day=mirror_holes[0], table=table)}")
        if upstream_gaps:
            verdict.append(f"{len(upstream_gaps)} 天**远端也没有** → 采集断档，"
                           f"回填补不了，要查 {check['task_id']} 那几天的执行记录")
        if unknown:
            verdict.append(f"{len(unknown)} 天远端对照未取到（只读 API 不可达/超时），"
                           f"结论待复核")

        results.append(dict(scope="pg_schema", db=schema, table=table,
                            status="STALE", latest=mx, days=len(days),
                            missing_days=missing[:20], thin_days=thin[:20]))
        stale_items.append(dict(
            db=f"{schema}.{table}", table=table,
            reason="；".join(parts + verdict),
            guidance=_advice(check, table, mirror_holes or missing)))


def check_all(now: Optional[datetime] = None, results: Optional[List[dict]] = None,
              stale_items: Optional[List[dict]] = None) -> Tuple[List[dict], List[dict]]:
    """跑完所有 PG_SCHEMA_CHECKS，返回 (results, stale_items)。

    三个入参都可选：单独跑（诊断 / 手工验证）时直接 `check_all()["stale"]`；
    由 db_freshness_check 调用时传入它的两个列表，就地追加。
    """
    # 与 db_freshness_check 同一时间基准：本机时钟就是 UTC
    # （见 docs/manual/13-operations.md「时钟即 UTC」），不用 utcnow（3.12 起弃用）。
    now = now or datetime.now()
    results = results if results is not None else []
    stale_items = stale_items if stale_items is not None else []
    for check in PG_SCHEMA_CHECKS:
        try:
            check_pg_schema(check, now, results, stale_items)
        except Exception as exc:  # noqa: BLE001 —— 单清单异常不影响其余巡检
            logger.warning("[PgFresh] 清单 %s 巡检异常: %r", check.get("label"), exc)
            stale_items.append(dict(db=check.get("schema", "?"), table="*",
                                    reason=f"本机 PG 巡检手段异常：{exc!r}",
                                    guidance=["检查 backend/.env 的 DATABASE_URL",
                                              "手工跑 python -m backend.services.pg_schema_freshness 看完整报错"]))
    return results, stale_items


if __name__ == "__main__":
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    res, stale = check_all()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"--- 发现项 {len(stale)} 条 ---")
    for s in stale:
        print(f"  [{s['db']}] {s['reason']}")

# -*- coding: utf-8 -*-
"""MsPortal「Quality Control」面板数据接口（只读）。

供 http://localhost/MsPortal/ 静态门户的 QC 面板调用：经 nginx `/api/` 兜底转发
到本机 7038（见 nginx.conf 的 location /api/；MsPortal 的 Referer 不命中
$portal_ref 的 eflow 规则，故不会被误转给门户上游）。

只做聚合计数与明细分页，不写任何数据、不落库。

口径（与现有看板保持一致，勿在此处另立标准）：
- alarm：realtime_alarm 未清除且命中断站告警白名单。白名单直接复用
  eflow_alarm_service.ALARM_CODE_CONDS（与实时/历史告警同步同一份，保证口径唯一）。
- tt/wo（2026-09-20 按需求改口径）：**告警未清除** —— 即 eflow_tt / eflow_wo 的
  alarm_clear_time 为空（NULL 或空串）。原来用的是「未关闭 status <> 'Closed'」，
  那是工单流程状态，与「告警是否消除」并不等价：实测同一时刻 TT 未关闭 8133 条，
  而告警未清除只有 79 条 —— 面板上摆的是质量指标，看的应是告警本身还没消。
- cr/pmt：沿用 gis.py 的「只有 Closed 是终态」约定
  （eflow_cr 额外把 Canceled 视为终态）。
- spms：inband_details / outband_details 的未关闭单，closed 词表与
  get_sp_table._status_breakdown 一致；此外剔除 Status = WaitingForUpdate
  （尚未生效的出库单，见 SP_IGNORED_WORDS）—— 大数字与下钻明细共用同一份谓词。
- sla（2026-09-25 加下钻）：近 30 天创建的 TT 中已判定 Pass/Failed 的单，
  即达标率环上 `pass / total` 的分母。谓词是模块级 _SLA_WINDOW + _SLA_JUDGED，
  与 _collect_summary.sla() 共用同一份 —— 环上的数字与点开的明细必须能对上。
  注意 sla **只在 METRICS_DRILLABLE 里，不在 METRICS 里**，原因见该常量的注释。

下钻明细列（_COLUMNS 的 tt / wo 两项）必须与 my_app 的 TT&WO 看板
（frontend/src/pages/TTWODashboard.tsx，页面 http://<host>/myapp/?page=ttwo）
逐字一致：同样的字段、同样的顺序、同样的表头（表头由 _auto_label 按该页面前端
的同一条规则从字段名生成）。改这里就要同步改那边，反之亦然。

注意：本模块的 SQL 必须用 `?` 占位符 —— get_raw_connection 的 PG 包装层
（database._PsycopgRaw）在带参数时会把字面 '%' 转义成 '%%' 并把 '?' 转成 '%s'，
所以 LIKE 的通配符必须放进参数值（如 '%kw%'），不能写进 SQL 文本。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names, table_columns, upsert
from backend.services.eflow_alarm_service import ALARM_CODE_CONDS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["portal-qc"])

METRICS = ("alarm", "tt", "wo", "cr", "pmt", "spms")

# 「有明细可下钻」的 metric 集合。与 METRICS 刻意分成两个常量（2026-09-25）——
# 它们的含义本来就不是一回事，早先共用一个常量只是恰好相等：
#   METRICS     = 面板上**有卡片/有统计**的指标。sla 从 2026-09-17 起就在这个面板上
#                 （_collect_summary 的 guard("sla", sla)），只是当时没有下钻实现。
#   DRILL_METRICS = 用户点开某个数字后，`/api/portal-qc/detail` **能给出明细**的指标。
# 把 sla 加进 DRILL_METRICS 是 2026-09-25 按需求「30 天达标率的数字要能点击下钻」做的。
# ⚠️ 不要让 sla 进 METRICS：/trend 里有这么一处判定
#     「reason = 'no_trend' if metric in METRICS else 'unknown_metric'」
#    —— METRICS 的语义是「这是一个已知指标」，sla 作为**比率**本来就没有
#    「每天新增多少」这种趋势口径（_TREND_SPEC 里没有它，也确实不该有）。
#    它现在落进 else 分支回 'unknown_metric'，前端会当成「趋势接口不认识这个指标」
#    而静默不画线（不至于报错），但那个说法是错的：指标是认识的，只是它没有趋势。
METRICS_DRILLABLE = METRICS + ("sla",)

_SUMMARY_TTL_SEC = 60
_summary_lock = threading.Lock()
_summary_cache: dict = {"at": 0.0, "payload": None}
# 告警单项的独立缓存（2026-09-18 加，配合 only=alarm）。必须与全量分开：
# MsPortal 的 QC 面板对告警做 5 分钟级刷新、其余做每小时刷新，若共用一份缓存，
# 每 5 分钟一次的告警请求会把全量那份 60s 缓存顶掉 → 「其余每小时」白白多跑 6 条全表 COUNT。
_alarm_cache: dict = {"at": 0.0, "payload": None}

# 与 get_sp_table._status_breakdown 完全一致的「已关闭」词表
SP_CLOSED_WORDS = ("closed", "close", "done", "已关闭", "完成", "yes", "y", "1", "true")

# 额外「不算未关闭」的在途状态（2026-09-20 按需求加）：WaitingForUpdate 是**尚未生效**
# 的单（申请人还没提交更新，属在途态，见 sp_online_sync.STATUS_ALL），不是真正待处理的
# 出入库任务 —— 所以既不计入 SPMS 大数字，也不出现在下钻明细里。
# 与报表侧同一口径：sp_report_gen.gernarate_sp_report.OUTBOUND_DROP_STATUS 与
# sp_report_gen.generate_sp_online_report.EXCLUDED_STATUS 生成报表前也都剔除它。
# 只影响本面板：get_sp_table._status_breakdown 的 closed 口径不动（那边是仓库看板的
# 「已关闭/未关闭」拆分，语义不同，不能顺手改）。
SP_IGNORED_WORDS = ("waitingforupdate",)

# 「未关闭」= status 既不属已关闭词表、也不属被忽略词表。合并成一份，统计与下钻共用。
SP_NOT_OPEN_WORDS = SP_CLOSED_WORDS + SP_IGNORED_WORDS

# TT / WO 的口径 = 「告警未清除」：alarm_clear_time 为空（NULL 或空串）。
# 2026-09-20 由「未关闭 status <> 'Closed'」改来，见模块 docstring 的口径说明。
# 同时判 IS NULL 与 = ''：源表里空值既有 NULL 也有空串（导出链路两种都见过），
# 只判其中一种会漏（实测 TT 的 79 条全是 NULL，但 WO 侧空串出现过）。
_ALARM_UNCLEARED = (
    "(alarm_clear_time IS NULL OR TRIM(CAST(alarm_clear_time AS TEXT)) = '')"
)
_TT_UNCLEARED = _ALARM_UNCLEARED
_WO_UNCLEARED = _ALARM_UNCLEARED
_CR_OPEN = "status NOT IN ('Closed','Canceled')"
_PM_OPEN = "status <> 'Closed'"

_MAX_PAGE_SIZE = 200

# 标题栏「达标率」的统计窗口（天）。按 eflow_tt.created_time 过滤。
_SLA_WINDOW_DAYS = 30

# 达标率下钻（2026-09-25 加）用的两个片段。
# ⚠️ 必须与 _collect_summary 里的 sla() 是**同一套口径**，否则会出现
#    「环上写 88.7%，点开明细只有 3888 条，加起来却不是 4384」这种自相矛盾。
#    两处改动要一起改（sla() 里是内联 SQL，因为它还要在同一句里算 SUM/COUNT）。
#
# _SLA_JUDGED：分母口径 —— 只含已有明确判定的单。
#   eFlow 的 sla_status 实测有四种取值：
#     Pass 32518 / Failed 3407 / NULL 50 / 'Within SLA' 22（2026-09-25 全表实测）
#   'Within SLA' 是**在途、尚未超期**，NULL 是还没判。把它们算进分母等于
#   把在途单当成未达标，会系统性低估达标率 —— 这是 sla() 的原话，照搬。
#   用 IN ('Pass','Failed') 而不是 `<> ''`：后者会把 'Within SLA' 也放进来。
_SLA_JUDGED = "sla_status IN ('Pass','Failed')"

# _SLA_WINDOW：下钻明细的时间窗 —— 与 sla() 的 `created_time >= ?` 完全一致。
#   created_time 是 'YYYY-MM-DD HH:MM:SS' 文本，字典序即时间序，故可直接比大小
#   （PG/SQLite 双模一致）。与 _TT_UNCLEARED 那类**谓词常量**不同，这里带一个 `?`，
#   所以 is_sla 的分支要单独处理参数（见 _detail_source）。
_SLA_WINDOW = "created_time >= ?"


def _sla_since() -> str:
    """达标率窗口的起始时刻（文本，与 eflow_tt.created_time 同格式）。"""
    return (datetime.now() - timedelta(days=_SLA_WINDOW_DAYS)).strftime("%Y-%m-%d %H:%M:%S")


def _rows_as_dicts(cursor):
    """cursor -> [dict, ...]（双模：sqlite Row / PG 元组均兼容）"""
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


def _scalar(conn, sql, params=None):
    row = conn.execute(sql, params or []).fetchone()
    return row[0] if row else None


# ======================= 每小时快照（2026-09-22 加） =======================
# 为什么需要：面板原本只有「此刻的绝对值」，看不出在好转还是在恶化 ——
# 169 比昨天好了还是坏了，面板回答不了。TT/WO/CR/PMT 的 created_time 能算「新增趋势」，
# 但「积压量趋势」必须要历史快照，源表里根本没有过去某一时刻的积压数。
#
# 写入方式：**懒写入** —— 每次 _collect_summary() 真正跑完（不是命中 60s 缓存）时，
# 顺带把这一组数字 upsert 进「当前小时」那一行。这样不需要动任何调度器配置，
# 也不新增定时任务。代价是：**只有门户被打开过的小时才有快照**。
# NOC 大屏通常 7×24 开着，所以实际几乎不断档；但如果门户长时间没人访问，
# 那几小时就是空的（前端对空档只画不出的点，不会画成 0 —— 见 qcSpark）。
# 要把覆盖做到无缺口，后续应把 _record_snapshot 挂到现有调度器上（task_schedule_config），
# 那是独立一步，不在本次改动范围内。
#
# 表结构（sqlite / PG 双模，DDL 相同 —— TEXT / INTEGER 两边都合法）：
#   hour_key      'YYYY-MM-DD HH:00'，主键，按后端时区（+08:00）分桶，
#                 与 generated_at 同一把尺子，前端不需要猜时区。
#   *_overdue     PMT 的超期数单独存一列：只看 PMT 总数会漏掉「总数没变但超期在涨」
#                 这种情况，而超期才是真正要催的。
_SNAPSHOT_TABLE = "portal_qc_snapshot"
_SNAPSHOT_TZ = timezone(timedelta(hours=8))
_HISTORY_DEFAULT_HOURS = 168      # 7 天
_HISTORY_MAX_HOURS = 24 * 30      # 上限 30 天，避免前端一个参数把整表拉出来


def _snapshot_hour(now=None) -> str:
    """当前小时桶 key（后端时区 +08:00，与 generated_at 同源）。"""
    return (now or datetime.now(_SNAPSHOT_TZ)).strftime("%Y-%m-%d %H:00")


def _ensure_snapshot_table(conn) -> None:
    """幂等建表 + 补列。放在这里而不是 alembic：这张表是**纯附加**的展示辅助数据，
    丢了只是趋势线断一段，不影响任何业务读数；用 alembic 迁移会把
    「加一条趋势线」变成一次需要协调的 schema 变更，不成比例。

    ⚠️ `sla_x10` 是 2026-09-25 追加的列（达标率趋势用）。CREATE TABLE IF NOT
    EXISTS **不会**给已存在的表补列，所以下面显式 ALTER 一次 —— 否则老库上
    读 `sla_x10` 会直接报「字段不存在」，整个趋势接口跟着废掉。

    为什么存 `sla_x10`（百分数 ×10 的整数）而不是 REAL：
      · 表是 sqlite / PG 双模，两家对浮点的亲和类型不完全一致，整数最省心；
      · 达标率只需 0.1% 的精度（徽章本身也只显示一位小数），×10 足够且无舍入歧义；
      · 空值语义与其它列一致（未采到 = NULL，绝不是 0 —— 0% 是「全都不达标」，
        与「没采到」必须能分开，否则趋势线上会出现假的归零谷底）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS " + _SNAPSHOT_TABLE + " ("
        " hour_key TEXT PRIMARY KEY,"
        " alarm INTEGER, tt INTEGER, wo INTEGER, cr INTEGER,"
        " pmt INTEGER, pmt_overdue INTEGER, spms INTEGER,"
        " sla_x10 INTEGER,"
        " captured_at TEXT)"
    )
    # 已存在的库补列。PG 支持 ADD COLUMN IF NOT EXISTS，SQLite 不支持 ——
    # 靠 try/except 兜底（重复添加时报的错就是「已存在」，可以安全忽略）。
    try:
        conn.execute("ALTER TABLE " + _SNAPSHOT_TABLE + " ADD COLUMN sla_x10 INTEGER")
    except Exception:  # noqa: BLE001
        pass
    conn.commit()


def _record_snapshot(metrics: dict) -> None:
    """把一次全量结果落成当前小时的快照行。**任何失败都只记日志** ——
    趋势是锦上添花，绝不能因为它写不进去而让面板的六个数字也拿不到。"""
    try:
        now = datetime.now(_SNAPSHOT_TZ)

        def num(metric, field="value"):
            m = metrics.get(metric) or {}
            v = m.get(field)
            # 只接受真数字：接口失败时 value 是 None，绝不能当成 0 落库 ——
            # 那会在趋势线上画出一个「积压突然清零」的假谷底。
            return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

        # 达标率单独处理：它是百分数（88.2），不是条数，且要 ×10 存成整数
        # （理由见 _ensure_snapshot_table 的注释）。同样只在**真数字**时才写，
        # 否则留 NULL —— 「没采到」与「0% 全不达标」绝不能混。
        sla_v = num("sla")
        row = {
            "hour_key": _snapshot_hour(now),
            "alarm": num("alarm"),
            "tt": num("tt"),
            "wo": num("wo"),
            "cr": num("cr"),
            "pmt": num("pmt"),
            "pmt_overdue": num("pmt", "overdue"),
            "spms": num("spms"),
            "sla_x10": None if sla_v is None else int(round(sla_v * 10)),
            "captured_at": now.isoformat(timespec="seconds"),
        }
        with get_raw_connection() as conn:
            _ensure_snapshot_table(conn)
            upsert(conn, _SNAPSHOT_TABLE, [row], ["hour_key"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[portal-qc] 快照写入失败（不影响面板读数）: %s", exc, exc_info=True)


# 实时告警表是「整表重建」写法的受害者：eflow_active_alarm 任务每 30 分钟跑一次，
# _write_alarm_to_appdb 不传 upsert_key → pandas if_exists="replace" → DROP + CREATE + INSERT。
# 重建窗口内任何读该表的请求都会拿到 "relation ... does not exist"（不是我们的 SQL 有问题），
# 而且会同时打到 gis / alarm_dashboard 等所有读 realtime_alarm 的看板（后端日志里都能看到）。
# 窗口很短，退避重试几次即可跨过；非「表不存在」的错误立即上抛，不掩盖真问题。
_MISSING_TABLE_HINTS = ("UndefinedTable", "不存在", "does not exist", "no such table")


def _is_missing_table_error(exc) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return any(h in text for h in _MISSING_TABLE_HINTS)


def _retry_missing_table(fn, attempts=3, delay=0.6):
    """对「表正在被重建」这种瞬时错误做短退避重试。"""
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if not _is_missing_table_error(exc) or i == attempts - 1:
                raise
            time.sleep(delay)
    return None


def _norm_restype(value) -> str:
    """白名单 restype(zte.ran.nodeb) ↔ DB restypename(ZTE_RAN_NODEB) 的归一化。"""
    return str(value).replace("_", ".").lower()


def _alarm_predicate():
    """断站告警白名单谓词 + 参数。

    realtime_alarm.restypename 落库的是导出显示形式（ZTE_RAN_NODEB），而
    ALARM_CODE_CONDS 写的是接口形式（zte.ran.nodeb），故两侧都做同一套
    '_'→'.' + 小写归一化后再比较（否则命中恒为 0）。
    """
    expr = "LOWER(REPLACE(CAST(restypename AS TEXT), '_', '.')) = ?"
    conds, params = [], []
    for c in ALARM_CODE_CONDS:
        conds.append(f"({expr} AND CAST(alarmcode AS TEXT) = ?)")
        params.append(_norm_restype(c["restype"]))
        params.append(str(c["alarmcode"]))
    return "(" + " OR ".join(conds) + ")", params


_ALARM_WHERE, _ALARM_PARAMS = _alarm_predicate()


def _sp_status_column(conn, table: str):
    """探测 SP 表的 status 列（与 _status_breakdown 同一策略：首个含 status/closed 的列）。"""
    for col in table_columns(conn, table):
        low = str(col).lower()
        if "status" in low or "closed" in low:
            return col
    return None


def _sp_words_sql(words) -> str:
    """词表 → SQL 的 IN 列表字面量（值里的单引号做转义）。"""
    return ",".join("'" + w.replace("'", "''") + "'" for w in words)


def _sp_open_predicate(col_quoted: str) -> str:
    """SP 明细的「未关闭」谓词 —— 统计与下钻共用这一份，避免两处漂移。

    COALESCE 到 '' 与 _status_breakdown 把空值/NaN 计入 unclosed 的行为一致；
    WaitingForUpdate 随 SP_IGNORED_WORDS 一并排除（见常量注释）。
    """
    return (
        f"LOWER(TRIM(COALESCE(CAST({col_quoted} AS TEXT), ''))) "
        f"NOT IN ({_sp_words_sql(SP_NOT_OPEN_WORDS)})"
    )


def _sp_open_counts(conn):
    """inband_details / outband_details 的未关闭单数（已剔除 WaitingForUpdate）。"""
    total_unclosed = 0
    detail = {}
    for table in ("inband_details", "outband_details"):
        col = _sp_status_column(conn, table)
        if not col:
            raise RuntimeError(f"{table} 未找到 status 列")
        col_quoted = '"' + str(col).replace('"', '""') + '"'
        unclosed = _scalar(
            conn,
            f"SELECT COUNT(*) FROM {table} WHERE {_sp_open_predicate(col_quoted)}",
        )
        unclosed = int(unclosed or 0)
        detail[table] = unclosed
        total_unclosed += unclosed
    return total_unclosed, detail


def _collect_summary() -> dict:
    """逐项独立容错：单项失败只让该项 value=None + error，绝不整体 500。"""
    metrics: dict = {}

    def guard(metric, fn, extras=None):
        try:
            result = fn()
            metrics[metric] = {"value": None, "error": None, **(extras or {})}
            if isinstance(result, dict):
                metrics[metric].update(result)
            else:
                metrics[metric]["value"] = result
        except Exception as exc:  # noqa: BLE001
            logger.warning("[portal-qc] %s 统计失败: %s", metric, exc, exc_info=True)
            metrics[metric] = {"value": None, "error": f"{type(exc).__name__}: {exc}"[:200]}

    with get_raw_connection() as conn:
        names = set(list_table_names(conn))

        def table_ok(name):
            if name not in names:
                raise RuntimeError(f"表不存在: {name}")

        def alarm():
            table_ok("realtime_alarm")
            sql = (
                "SELECT COUNT(*) AS alarms, COUNT(DISTINCT site_id) AS sites "
                "FROM realtime_alarm WHERE TRIM(CAST(clearstate AS TEXT)) = '0' AND "
                + _ALARM_WHERE
            )
            row = _retry_missing_table(lambda: conn.execute(sql, _ALARM_PARAMS).fetchone())
            return {"value": int(row[0] or 0), "sites": int(row[1] or 0)}

        def tt():
            table_ok("eflow_tt")
            return int(_scalar(conn, f"SELECT COUNT(*) FROM eflow_tt WHERE {_TT_UNCLEARED}") or 0)

        def wo():
            table_ok("eflow_wo")
            return int(_scalar(conn, f"SELECT COUNT(*) FROM eflow_wo WHERE {_WO_UNCLEARED}") or 0)

        def cr():
            table_ok("eflow_cr")
            return int(_scalar(conn, f"SELECT COUNT(*) FROM eflow_cr WHERE {_CR_OPEN}") or 0)

        def pmt():
            table_ok("eflow_pm")
            sql = (
                f"SELECT COUNT(*) AS c, SUM(CASE WHEN pmt_overdue = 'Yes' THEN 1 ELSE 0 END) AS o "
                f"FROM eflow_pm WHERE {_PM_OPEN}"
            )
            row = conn.execute(sql).fetchone()
            return {"value": int(row[0] or 0), "overdue": int(row[1] or 0)}

        def spms():
            total, detail = _sp_open_counts(conn)
            return {"value": total, "tables": detail}

        def sla():
            """标题栏「达标率」= 近 N 天创建的 TT 里 SLA 判定为 Pass 的占比。

            分母只取已有明确判定（Pass / Failed）的单：eFlow 里还会出现
            'Within SLA'（在途、尚未超期）与空值，把它们算进分母等于把在途单
            当成未达标，会系统性低估达标率。created_time 是 'YYYY-MM-DD HH:MM:SS'
            文本，字典序即时间序，故可直接用 >= 比较（PG/SQLite 双模一致）。

            谓词用模块级的 _SLA_WINDOW / _SLA_JUDGED —— 下钻明细走的是同一份，
            两边永远同一个口径（2026-09-25 起；此前是本函数内联的字面量，
            下钻另抄一份必然会漂移）。注意 _SLA_WINDOW 自带一个 `?` 占位符。

            window 是**同一时间窗内的单总量**（含未判定），只为给前端算出
            「未判定 N 条不计入」那一行 —— 不参与 value 的计算。
            一次查询同时取三个数，避免为了一行说明再打一趟表（eflow_tt 有 3.6 万行，
            这条 COUNT 本来就已经在跑全窗口扫描了）。
            """
            table_ok("eflow_tt")
            since = _sla_since()
            # 三个数一次算完（passed / pending / 已判定 total）。
            # pending 内联进 CASE（而不是再写一个 _SLA_JUDGED 的 `?`）——
            # 这样整条 SQL 只有 _SLA_WINDOW 那一个占位符，params 就是 [since]，
            # 与下钻 _detail_source 的写法保持同构。
            row = conn.execute(
                "SELECT SUM(CASE WHEN sla_status = 'Pass' THEN 1 ELSE 0 END) AS passed, "
                f"SUM(CASE WHEN {_SLA_JUDGED} THEN 1 ELSE 0 END) AS judged, "
                f"SUM(CASE WHEN {_SLA_JUDGED} THEN 0 ELSE 1 END) AS pending "
                f"FROM eflow_tt WHERE {_SLA_WINDOW}",
                [since],
            ).fetchone()
            passed, total = int(row[0] or 0), int(row[1] or 0)
            return {
                "value": round(passed / total * 100, 1) if total else None,
                "pass": passed,
                "total": total,
                "pending": int(row[2] or 0),
                "days": _SLA_WINDOW_DAYS,
            }

        guard("alarm", alarm)
        guard("tt", tt)
        guard("wo", wo)
        guard("cr", cr)
        guard("pmt", pmt)
        guard("spms", spms)
        guard("sla", sla)

    # 快照只在**真正跑完一次统计**时写（缓存命中不会走到这里），且失败不影响返回。
    # 放在 with 之外：快照用自己的短连接，不占用/不延长这次统计的事务。
    _record_snapshot(metrics)

    return {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "metrics": metrics,
    }


def _collect_alarm_only() -> dict:
    """只算「未清除的断站告警」（2026-09-18 加，配合 only=alarm）。

    口径必须与 _collect_summary 里的 alarm 完全一致（同一段 SQL、同一份 _ALARM_WHERE、
    同一个 clearstate='0' 判定），否则两个入口会给出不同的数字 —— 面板上同一张卡
    会因为走了哪条路径而变值。

    比全量那份多做一步：把「表正在被 DROP/CREATE 重建」这种瞬时错误也纳入重试。
    realtime_alarm 是整表重建写法的受害者（eflow_active_alarm 每 5 分钟 replace 一次），
    全量路径里 table_ok 是在重试之外抛的，重建窗口内那一轮只能报错；
    这条 5 分钟级的路径调用频率高，值得跨过窗口而不是把错误推给面板。
    """
    def run():
        with get_raw_connection() as conn:
            if "realtime_alarm" not in set(list_table_names(conn)):
                raise RuntimeError("表不存在: realtime_alarm")
            sql = (
                "SELECT COUNT(*) AS alarms, COUNT(DISTINCT site_id) AS sites "
                "FROM realtime_alarm WHERE TRIM(CAST(clearstate AS TEXT)) = '0' AND "
                + _ALARM_WHERE
            )
            return conn.execute(sql, _ALARM_PARAMS).fetchone()

    metrics: dict = {}
    try:
        row = _retry_missing_table(run, attempts=4, delay=0.8)
        metrics["alarm"] = {"value": int(row[0] or 0), "sites": int(row[1] or 0), "error": None}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[portal-qc] alarm 单项统计失败: %s", exc, exc_info=True)
        metrics["alarm"] = {"value": None, "error": f"{type(exc).__name__}: {exc}"[:200]}
    return {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "metrics": metrics,
    }


@router.get("/api/portal-qc/summary")
def portal_qc_summary(refresh: int = 0, only: str = ""):
    """QC 面板统计。

    - 不传 only：六项全量，默认 60s 缓存，refresh=1 强制刷新。
    - only=alarm（2026-09-18 加）：**只算断站告警一项**。MsPortal 的 QC 面板按
      「告警 5 分钟级 / 其余每小时」分频刷新，而六项里只有 realtime_alarm 是高频变化的
      （eflow_active_alarm 每 5 分钟同步；tt/wo/cr/pmt/spms/sla 的源 eflow_sync 每小时
      :00 起跑、约 :06 才跑完）。给告警单开一条，避免每 5 分钟把 6 条全表 COUNT 重跑一遍。
      只返回 metrics.alarm，前端只覆盖 alarm 那一格。
    """
    if only.strip().lower() == "alarm":
        now = time.time()
        with _summary_lock:
            cached = _alarm_cache["payload"]
            fresh = cached is not None and (now - _alarm_cache["at"]) < _SUMMARY_TTL_SEC
            if fresh and not refresh:
                return {**cached, "cached": True}
        payload = _collect_alarm_only()
        with _summary_lock:
            _alarm_cache["payload"] = payload
            _alarm_cache["at"] = time.time()
        return {**payload, "cached": False}

    now = time.time()
    with _summary_lock:
        cached = _summary_cache["payload"]
        fresh = cached is not None and (now - _summary_cache["at"]) < _SUMMARY_TTL_SEC
        if fresh and not refresh:
            return {**cached, "cached": True}

    payload = _collect_summary()
    with _summary_lock:
        _summary_cache["payload"] = payload
        _summary_cache["at"] = time.time()
    return {**payload, "cached": False}


@router.get("/api/portal-qc/history")
def portal_qc_history(hours: int = Query(_HISTORY_DEFAULT_HOURS, ge=2, le=_HISTORY_MAX_HOURS)):
    """每小时快照序列，供 QC 面板画趋势线与环比（2026-09-22 加）。

    返回按 metric 分组的 series：{"alarm": [{"h": "2026-09-21 14:00", "v": 56}, …], …}
    —— 前端 state.qcHistory 直接就是这个形状，不用再做一次转置。
    另含 "sla"：达标率（百分数，88.2 这种，非条数），2026-09-25 加的列，
    **从该列上线那一刻起才会有点** —— 更早的小时没有这个数，前端不补 0。

    **只返回「已走完的整点」，不含当前这一小时。** 原因：快照是懒写入的，
    当前小时那一行随时会被下一次统计覆盖。把它一起返回，前端算环比就会拿
    「当前值」和「几分钟前的当前值」比 —— 差值恒接近 0，看起来像「没变化」，
    这是错的。排除之后，序列最后一项必然是上一个完整整点，环比语义就干净了。

    表不存在（后端刚升级、还没有任何一次全量统计落过盘）时返回空 series 而不是 500：
    前端对空序列有「趋势积累中」的降级路径，报错反而会在面板上弹出红字。
    """
    cur_hour = _snapshot_hour()
    since = (datetime.now(_SNAPSHOT_TZ) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:00")

    rows = []
    try:
        with get_raw_connection() as conn:
            if _SNAPSHOT_TABLE in set(list_table_names(conn)):
                rows = _rows_as_dicts(conn.execute(
                    "SELECT hour_key, alarm, tt, wo, cr, pmt, pmt_overdue, spms, sla_x10 "
                    "FROM " + _SNAPSHOT_TABLE + " "
                    "WHERE hour_key < ? AND hour_key >= ? ORDER BY hour_key",
                    [cur_hour, since],
                ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[portal-qc] 历史快照读取失败（返回空序列）: %s", exc, exc_info=True)

    # PMT 的趋势线用**超期数**而不是总数：总数常年几百上千、变化平缓，看不出问题；
    # 超期数才是要催的那部分。键名沿用前端卡片 id（pmt），故这里单独映射。
    field_of = {
        "alarm": "alarm", "tt": "tt", "wo": "wo", "cr": "cr",
        "pmt": "pmt_overdue", "spms": "spms",
    }
    series = {}
    for metric, field in field_of.items():
        pts = []
        for r in rows:
            v = r.get(field)
            # 只放真数字：某一小时接口失败时该列是 NULL，绝不能补 0 ——
            # 那会在趋势线上画出一个「积压突然清零」的假谷底。
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                pts.append({"h": r["hour_key"], "v": int(v)})
        series[metric] = pts

    # 达标率（2026-09-25 加）：单独一段，因为存的不是条数而是「百分数 ×10」，
    # 要 ÷10 还原成 88.2 这种前端直接能用的值。同样只放真数字，NULL 跳过。
    sla_pts = []
    for r in rows:
        v = r.get("sla_x10")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            sla_pts.append({"h": r["hour_key"], "v": round(float(v) / 10.0, 1)})
    series["sla"] = sla_pts

    return {
        "generated_at": datetime.now(_SNAPSHOT_TZ).isoformat(timespec="seconds"),
        "hours": hours,
        "current_hour": cur_hour,
        "points": len(rows),
        "series": series,
    }


# ========== 新增量趋势（按源表时间列分桶，2026-09-22 加） ==========
# 与上面的 portal_qc_snapshot（积压快照）是**互补**的两种趋势，回答不同问题：
#   积压快照 → 「存量是在堆积还是在消化」（需要历史，只能从上线那天开始攒）
#   新增分桶 → 「最近来单/告警是变多了还是变少了」（源表本来就有时间列，立即有数据）
# 本次按用户要求只做后者，快照表保留但不再读写。
#
# 每个 metric 的「时间列」就是下钻明细里那一列（用户明确要求「点 Alarm 出现详情里的
# RAISED TIME 列」），所以两边看到的永远是同一个时间语义，不会出现明细按 A 时间排、
# 趋势按 B 时间分桶这种对不上的情况。
#
# 三种列类型要分开处理（实测）：
#   alarm  : realtime_alarm.alarmraisedtime  → bigint，13 位 epoch **毫秒**
#   tt/wo  : eflow_tt/wo.alarm_occur_time    → text，'YYYY-MM-DD HH:MM:SS'
#   spms   : inband/outband_details."Create Time" → text，同上
# 用 substr 取小时是最稳的写法：源表的时间是**本地墙钟文本**（不带时区），
# 转成 timestamp 再分组会引入一次时区解释，而 substr 只是切字符串，零歧义。
#
# 粒度按数据密度定（实测**近 30 天非空桶占比**，2026-09-22）：
#   metric  按天          按小时        结论
#   tt      14/30 = 47%   36/720 =  5%  按天
#   wo      13/30 = 43%   34/720 =  5%  按天
#   spms    38/30 ≈ 63%   90/720 =  6%  按天（in+out 两张表合计）
#   cr       8/30 = 27%   16/720 =  2%  可画，但很稀（本次未启用，见下）
#   pmt      0/30 =  0%    0/720 =  0%  **无数据，不画**
#
# ⚠️ 这里改过一次，记录原因：第一版按「近 7 天条数」定粒度，得出 tt 147 条/天、
# 每桶约 6 条 → 选了按小时。那是被一个尖峰日误导的 —— 近 7 天正好赶上一批集中告警。
# 换成 30 天窗口重测，按小时的非空桶只有 5%，画出来是一条贴底的直线加几根尖刺，
# 不是趋势。**按天对四个指标都是唯一可读的粒度。**
#
# cr/pmt 不画的原因（实测）：
#   cr  近 30 天只有 20 条、8 个非空桶 → 曲线几乎全是 0
#   pmt 近 30 天 **0 条**。eftow_pm 是「批量生成」型：2026-01-11 一天 267 条、
#       03-13 一天 388 条、06-02 一天 380 条、06-23 一天 490 条，中间长期静默。
#       按时间列画会得到一条长期贴 0、偶尔一根尖峰的线，信息量为负 —— 不如不画。
#       它需要的不是「新增趋势」而是「存量趋势」，那要靠 portal_qc_snapshot（本次保留未用）。
_TREND_SPEC = {
    # metric: (from_sql, 时间列, 列类型, 粒度, 窗口)
    #
    # 窗口 "today" = 从库里「今天 00:00」起（配合下面的 SET TIME ZONE 'Asia/Shanghai'）。
    # 只有 alarm 用 —— 见下方 alarm 那段的说明。
    "alarm": ("realtime_alarm", "alarmraisedtime", "epoch_ms", "hour", "today"),
    "tt": ("eflow_tt", "alarm_occur_time", "text", "day", "days"),
    "wo": ("eflow_wo", "alarm_occur_time", "text", "day", "days"),
    "spms": ("(__SP_UNION__) t", "create_time", "text", "day", "days"),
}

# alarm 单独走「今天 + 按小时」，理由（2026-09-22 用户要求，实测支持）：
#
# alarm 是**实时**指标 —— 源表 realtime_alarm 每 5 分钟整表 replace 一次，
# 卡片本身也是 5 分钟刷新（见 portal.js 的 QC_ALARM_MIN）。对实时指标问
# 「近 30 天新增」意义不大（那是历史归档的视角），当班关心的是**今天这一天
# 的节奏**：什么时候在集中起告警、现在是不是又在涨。
#
# 实测支持这个选择（2026-09-22 19:32，今天已过 20 小时）：
#   今天 28 条告警，落在 14 个不同小时里（14/20 = 70% 非空），
#   01/03/05/06/07/08/09/10/11/13/14/16/18/19 时都有，峰值 19 时 7 条。
#   按小时完全读得出节奏 —— 这与 tt/wo/spms 形成鲜明对比：
#   后三者按小时的非空桶只有 5%（见上面的实测表），画出来是一条贴底的直线。
#   所以「alarm 按小时、其余按天」不是将就，是各自的量级决定的。
#
# 注意最后一个桶是**当前这个还没走完的小时**，值天然偏低（会随分钟增长），
# 前端在说明文字里写的是「今天」而不是「近 24 小时」，避免误读成完整小时。
_TREND_PREDICATE = {
    # 与卡片大数字**同口径**（用户确认）：只算未清除 / 未关闭的，
    # 否则趋势线的数会比卡片大数字大一个量级，两个数对不上，反而更糊涂。
    "alarm": ("TRIM(CAST(clearstate AS TEXT)) = '0' AND " + _ALARM_WHERE, list(_ALARM_PARAMS)),
    "tt": (_TT_UNCLEARED, []),
    "wo": (_WO_UNCLEARED, []),
    "spms": ("1 = 1", []),
}
_TREND_DEFAULT_DAYS = 30
_TREND_MAX_DAYS = 180
_TREND_MAX_POINTS = 400        # 防御：再密就不画了，交给前端降级


def _trend_bucket_expr(col, kind: str, grain: str):
    """分桶表达式。返回 (表达式, 比较用表达式)。全部为**常量拼接**，无用户输入。"""
    q = '"' + col.replace('"', '""') + '"'
    if kind == "epoch_ms":
        # 毫秒 → 秒 → timestamp。用 server 时区（源数据就是本地墙钟）。
        base = f"to_timestamp(({q})::bigint / 1000.0)"
    else:
        # 源表是 'YYYY-MM-DD HH:MM:SS' 文本（可能是空串），先挡掉再转。
        base = f"({q})::timestamp"
    fmt = "'YYYY-MM-DD HH24:00'" if grain == "hour" else "'YYYY-MM-DD'"
    return f"to_char({base}, {fmt})", base


@router.get("/api/portal-qc/trend")
def portal_qc_trend(
    metric: str = Query(..., description="alarm/tt/wo/spms（cr/pmt 无趋势）"),
    days: int = Query(_TREND_DEFAULT_DAYS, ge=1, le=_TREND_MAX_DAYS),
):
    """按源表时间列分桶的**新增量**趋势（2026-09-22 加）。

    返回 {"grain": "hour"|"day", "window": "today"|"days", "days": N, "unit": ...,
          "points": [{"t": "2026-09-22 08:00", "v": 16}, ...]}

    粒度和窗口**按指标定**（见 _TREND_SPEC）：
      alarm      → 今天 + 按小时（实时指标，看当班节奏）
      tt/wo/spms → 近 N 天 + 按天（日级量级，按小时会是一条贴底的直线）

    `days` 参数只对 window="days" 的指标生效；window="today" 的指标忽略它，
    响应里的 days 恒为 1（真实跨度），前端据此写说明文字。

    与 /history 的关键区别：这里用的是源表自己的时间列，**立即有数据**，
    不需要靠门户被打开来积累。

    空桶**不下发**（只回有数据的时间点），由前端按时间轴对齐 —— 这样
    「那天没有新增」和「那天数据没同步」在语义上仍然分开：前者前端会画成 0，
    后者根本不在序列里。
    """
    metric = (metric or "").strip().lower()
    if metric not in _TREND_SPEC:
        # cr/pmt 落在这里。返回空序列而不是 400 —— 前端对空序列有
        # 「该指标不提供趋势」的降级路径，报错会变成面板上的红字。
        return {"metric": metric, "grain": None, "points": [],
                "reason": "no_trend" if metric in METRICS else "unknown_metric"}

    table, col, kind, grain, window = _TREND_SPEC[metric]
    where, params = _TREND_PREDICATE[metric]
    # 窗口为 "today" 的指标（目前只有 alarm），days 参数对它无意义，回 1
    # 是为了让响应里的 days 字段始终能反映真实跨度，前端好写说明文字。
    eff_days = 1 if window == "today" else days

    try:
        with get_raw_connection() as conn:
            if table == "(__SP_UNION__) t":
                table = "(" + _SP_UNION.format(
                    in_open=_sp_open_expr(conn, "inband_details"),
                    out_open=_sp_open_expr(conn, "outband_details"),
                ) + ") t"
            elif table not in set(list_table_names(conn)):
                return {"metric": metric, "grain": grain, "points": [], "reason": "no_table"}

            expr, base = _trend_bucket_expr(col, kind, grain)
            # 时间下界 + 脏值粗筛。两种列类型必须用**不同**的守卫：
            #   bigint 列不能和 '' 比大小（PG 会报「无效的 bigint 输入语法: ""」）；
            #   text  列可能是空串 / 短串，直接 ::timestamp 会炸，先卡长度。
            #
            # ⚠️ 时区：**必须显式 SET TIME ZONE 再取 NOW()**。
            # 实测这个库的 TimeZone 是 Atlantic/Reykjavik（UTC+0），而源表里存的是
            # **本地墙钟文本**（应用侧按 +08:00 理解）。直接写 `NOW() - INTERVAL '30 days'`
            # 会把窗口错开 8 小时：看起来只差一点点，但「近 30 天」这种口径
            # 在整点边界上会多算/漏算当天的数据。这里把会话时区设成应用时区，
            # 让 NOW() 与源数据的墙钟语义对齐。
            conn.execute("SET TIME ZONE 'Asia/Shanghai'")
            q = '"' + col.replace('"', '""') + '"'
            # 时间下界：两种**窗口**（today / 近 N 天）× 两种**列类型**（epoch_ms / text）。
            #   today → date_trunc('day', NOW())，即库里今天的 00:00（上面已设成 +08:00）
            #   days  → NOW() - INTERVAL 'N days'
            # 两种列类型必须用**不同**的守卫：
            #   bigint 列不能和 '' 比大小（PG 会报「无效的 bigint 输入语法: ""」）；
            #   text  列可能是空串 / 短串，直接 ::timestamp 会炸，先卡长度。
            if window == "today":
                lo_expr = "date_trunc('day', NOW())"
                lo_epoch = "EXTRACT(EPOCH FROM date_trunc('day', NOW()))"
            else:
                lo_expr = f"NOW() - INTERVAL '{int(days)} days'"
                lo_epoch = f"EXTRACT(EPOCH FROM NOW()) - {int(days) * 86400}"
            if kind == "epoch_ms":
                lo = (f"{q} IS NOT NULL AND "
                      f"({q})::bigint >= ({lo_epoch}) * 1000")
            else:
                lo = (f"{q} IS NOT NULL AND length(coalesce({q}, '')) >= 19 AND "
                      f"({q})::timestamp >= {lo_expr}")
            sql = (f"SELECT {expr} AS b, COUNT(*) AS n FROM {table} "
                   f"WHERE ({where}) AND {lo} "
                   f"GROUP BY 1 ORDER BY 1")
            rows = _retry_missing_table(lambda: _rows_as_dicts(conn.execute(sql, params)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[portal-qc] 趋势取数失败 metric=%s: %s", metric, exc, exc_info=True)
        return {"metric": metric, "grain": grain, "points": [], "reason": "error",
                "detail": str(exc)[:200]}

    points = []
    for r in rows:
        try:
            points.append({"t": str(r["b"]), "v": int(r["n"])})
        except (TypeError, ValueError):
            continue
    if len(points) > _TREND_MAX_POINTS:
        points = points[-_TREND_MAX_POINTS:]

    return {
        "metric": metric,
        "grain": grain,
        "days": eff_days,
        "window": window,
        "unit": t_unit_for(grain),
        "points": points,
        "total": sum(p["v"] for p in points),
    }


def t_unit_for(grain: str) -> str:
    return "hour" if grain == "hour" else "day"


# ========== 明细下钻 ==========
# 每项一份列定义：(SQL 表达式, 输出 key, 表头)；SQL 表达式统一用原名，需要引号的自带引号。


def _auto_label(key: str) -> str:
    """字段名 → 表头，规则与 my_app TT&WO 看板前端**逐字相同**。

    对应 TTWODashboard.tsx 里那段：
        k.replace(/_/g, ' ').replace(/\b\\w/g, c => c.toUpperCase())
    例：tt_no → 'Tt No'、alarm_clear_time → 'Alarm Clear Time'。
    放在这里（而不是各写一份表头）是为了让 QC 下钻的表头与
    http://<host>/myapp/?page=ttwo 的明细表永远一致 —— 那边是前端算的，
    两边一旦各写各的就会慢慢漂移。
    """
    return re.sub(r"\b\w", lambda m: m.group(0).upper(), key.replace("_", " "))


# tt / wo 的字段与顺序 = TTWODashboard.tsx 的 _build_tt_fields() / WO_FIELDS
# （site_join_field=site_id、creator_field=creator、sev_field=alarm_severity，
#  由 tt_wo_dashboard._detect_schema() 对当前库判定得出）。
_TT_DRILL_FIELDS = (
    "title", "tt_no", "wo_no", "site_id", "status", "creator",
    "ticket_severity", "alarm_severity", "sla_status",
    "alarm_occur_time", "alarm_clear_time", "domain", "root_cause", "sub_root_cause",
)
_WO_DRILL_FIELDS = (
    "wo_no", "tt_no", "title", "status", "creator", "created_time",
    "alarm_occur_time", "alarm_clear_time", "source",
    "rc_main_category", "rc_sub_category", "ticket_severity", "alarm_severity",
)

# sla（达标率）下钻的列，2026-09-25 加。
# ⚠️ 刻意**不复用 _TT_DRILL_FIELDS**：那张表是给「告警未清除的 TT」用的
#    （tt 卡的口径），它带着 alarm_occur_time / root_cause 等排障字段，
#    而达标率看的是**判定结果**。两个问题不一样：「这张单告警消了没」
#    vs「这张单 SLA 判过了没」——共用一套列会让人以为点进来的是同一批单。
#    实际两者也确实不同：tt 卡 79 条，本卡 4384 条。
# 字段顺序 = 先定位（单号/标题/站点）→ 再判定（SLA 状态/时限/剩余）→ 再归属。
# 全部是 eflow_tt 的真实列名，已按 PRAGMA table_info(eflow_tt) 核对。
_SLA_DRILL_FIELDS = (
    "tt_no", "title", "site_id", "site_name", "status", "sla_status",
    "sla_time", "sla_deadline", "sla_remain_time",
    "ticket_severity", "alarm_severity", "vendor", "region_level1", "region_level2",
    "creator", "current_handler", "created_time", "actual_completion_time",
)

_COLUMNS = {
    "alarm": [
        ("tt_id", "tt_id", "TT No."),
        ("site_name", "site_name", "Site Name"),
        ("site_id", "site_id", "Site ID"),
        ("codename", "codename", "Alarm Name"),
        ("alarmcode", "alarmcode", "Alarm Code"),
        ("perceivedseverityname", "severity", "Severity"),
        ("alarmraisedtime", "raised", "Raised Time"),
        ("durationname", "duration", "Duration"),
        ("auxiliarycount", "down_sites", "Down Sites"),
        ("assign_rulename", "assign_rule", "Assign Rule"),
        ("region", "region", "Region"),
    ],
    "tt": [(f, f, _auto_label(f)) for f in _TT_DRILL_FIELDS],
    "wo": [(f, f, _auto_label(f)) for f in _WO_DRILL_FIELDS],
    "cr": [
        ("change_request_id", "cr_id", "CR ID"),
        ("cr_title", "title", "CR Title"),
        ("status", "status", "Status"),
        ("change_type", "change_type", "Change Type"),
        ("implementer", "implementer", "Implementer"),
        ("request_registration_time", "requested", "Request Time"),
        ("planned_start_time", "plan_start", "Planned Start"),
        ("planned_end_time", "plan_end", "Planned End"),
        ("closed_time", "closed", "Closed Time"),
        ("requester_user_name", "requester", "Requester"),
    ],
    "pmt": [
        ("pmt_no", "pmt_no", "PMT No."),
        ("title", "title", "Title"),
        ("status", "status", "Status"),
        ("pmt_overdue", "overdue", "Overdue"),
        ("service_classification", "service", "Service Classification"),
        ("site_name", "site_name", "Site Name"),
        ("current_task_start_time", "start", "Task Start"),
        ("current_task_end_time", "end", "Task End"),
        ("completed_items", "completed", "Completed Items"),
        ("total_items", "total", "Total Items"),
    ],
    "spms": [
        ("src", "src", "Type"),
        ("doc_no", "doc_no", "Doc No."),
        ("status", "status", "Status"),
        ("material_no", "material_no", "Material No."),
        ("material_name", "material_name", "Material Name"),
        ("qty", "qty", "Qty"),
        ("warehouse", "warehouse", "Warehouse"),
        ("create_time", "create_time", "Create Time"),
        ("closed_time", "closed_time", "Closed Time"),
    ],
    # sla 的表头同样走 _auto_label（与 tt/wo 一致），保证「字段名 → 表头」
    # 这件事全模块只有一条规则。sla_status → 'Sla Status' 而非 'SLA Status'：
    # 这是 _auto_label 的既有行为（它只做大写首字母），
    # 也是 my_app TT&WO 看板上该列现在的显示 —— 换来换去反而不一致。
    "sla": [(f, f, _auto_label(f)) for f in _SLA_DRILL_FIELDS],
}

_ORDER = {
    "alarm": "alarmraisedtime DESC",
    # tt / wo 的排序 = TTWODashboard.tsx 下钻的 ORDER BY t.alarm_occur_time DESC /
    # w.alarm_occur_time DESC（那边也是按告警发生时间倒序，不是创建时间）。
    "tt": "alarm_occur_time DESC",
    "wo": "alarm_occur_time DESC",
    "cr": "request_registration_time DESC",
    "pmt": "created_time DESC",
    "spms": "create_time DESC",
    # 达标率按判定时间倒序无意义（没有「判定时间」这一列），按创建时间倒序
    # 与 sla() 的窗口过滤列一致：最近进窗口的单排在最前。
    "sla": "created_time DESC",
}

_SP_UNION = (
    "SELECT 'Inbound' AS src, \"Inbound No.\" AS doc_no, \"Status\" AS status, "
    "\"Material No.\" AS material_no, \"Material Name\" AS material_name, "
    'CAST("Inbound Qty" AS TEXT) AS qty, "Warehouse Name" AS warehouse, '
    '"Create Time" AS create_time, "Closed Time" AS closed_time '
    "FROM inband_details WHERE {in_open} "
    "UNION ALL "
    "SELECT 'Outbound', \"Outbound No.\", \"Status\", \"Material No.\", \"Material Name\", "
    'CAST("Outbound Qty" AS TEXT), "Warehouse Name", "Create Time", "Closed Time" '
    "FROM outband_details WHERE {out_open}"
)


def _sp_open_expr(conn, table: str) -> str:
    """下钻 UNION 里每张表的「未关闭」条件 —— 与 _sp_open_counts 同一份谓词。"""
    col = _sp_status_column(conn, table)
    if not col:
        raise RuntimeError(f"{table} 未找到 status 列")
    return _sp_open_predicate('"' + str(col).replace('"', '""') + '"')


def _detail_source(conn, metric: str):
    """返回 (from_sql, where_sql, params) —— where_sql 已含未关闭/断站/达标口径。

    params 是与 where_sql 里的 `?` 配对的参数列表（sla 之外都是空表）。
    ⚠️ 调用方必须把 params 透传给每一次 COUNT/SELECT —— 漏传会让 `?` 悬空，
    在 sqlite 上直接报 "Incorrect number of bindings"。见 portal_qc_detail。
    """
    if metric == "alarm":
        return "realtime_alarm", "TRIM(CAST(clearstate AS TEXT)) = '0' AND " + _ALARM_WHERE, list(_ALARM_PARAMS)
    if metric == "tt":
        return "eflow_tt", _TT_UNCLEARED, []
    if metric == "wo":
        return "eflow_wo", _WO_UNCLEARED, []
    if metric == "cr":
        return "eflow_cr", _CR_OPEN, []
    if metric == "pmt":
        return "eflow_pm", _PM_OPEN, []
    if metric == "sla":
        # 达标率的明细 = 「近 30 天创建、且已判定 Pass/Failed」的那批单，
        # 正是环上 3888 / 4384 的分母。Pass 与 Failed 都在里面 —— 用户要看的
        # 是「谁判过了、判成什么」，只给 Failed 会变成一个「失败清单」，
        # 那就不是达标率的下钻了。要看 Pass 率自己在弹窗里按 Sla Status 排序/搜索。
        return "eflow_tt", f"{_SLA_WINDOW} AND {_SLA_JUDGED}", [_sla_since()]
    if metric == "spms":
        return (
            "(" + _SP_UNION.format(
                in_open=_sp_open_expr(conn, "inband_details"),
                out_open=_sp_open_expr(conn, "outband_details"),
            ) + ") t",
            "1 = 1",
            [],
        )
    raise HTTPException(status_code=400, detail=f"未知 metric: {metric}")


@router.get("/api/portal-qc/detail")
def portal_qc_detail(
    metric: str = Query(..., description="alarm/tt/wo/cr/pmt/spms/sla"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=_MAX_PAGE_SIZE),
    q: str = Query("", description="跨列模糊搜索"),
    sort: str = Query("", description="排序列（必须是本 metric 的列 key，否则忽略）"),
    dir: str = Query("", description="asc / desc，默认 desc"),
):
    """某项统计的明细列表（分页 + 模糊搜索 + 排序）。

    排序（2026-09-22 加）刻意放在**服务端**：只排当前页会让「按 Raised Time 排序」
    在翻页后失效 —— 那是个错的排序，不如不做。

    注入面：sort 只用来在**本 metric 自己的列定义表 _COLUMNS** 里查 SQL 表达式，
    查到什么就用什么，查不到就退回默认排序。用户输入永远不会拼进 SQL 文本，
    dir 也只映射到 ASC / DESC 两个字面量。
    """
    metric = (metric or "").strip().lower()
    if metric not in METRICS_DRILLABLE:
        raise HTTPException(status_code=400, detail=f"未知 metric: {metric}")

    spec = _COLUMNS[metric]
    order_by = _ORDER[metric]
    expr_of = {key: expr for expr, key, _ in spec}
    if sort and sort in expr_of:
        order_by = f"{expr_of[sort]} {'ASC' if (dir or '').strip().lower() == 'asc' else 'DESC'}"

    with get_raw_connection() as conn:
        src, where, params = _detail_source(conn, metric)
        if metric != "spms" and src not in set(list_table_names(conn)):
            raise HTTPException(status_code=503, detail=f"表不存在: {src}")

        select = ", ".join(f"{expr} AS {key}" for expr, key, _ in spec)

        keyword = (q or "").strip()
        if keyword:
            # 通配符必须放在参数值里：带参数时 SQL 文本中的 '%' 会被包装层转义成 '%%'
            like = f"%{keyword.lower()}%"
            ors = " OR ".join(
                f"LOWER(COALESCE(CAST(({expr}) AS TEXT), '')) LIKE ?" for expr, _, _ in spec
            )
            where = f"({where}) AND ({ors})"
            params = params + [like] * len(spec)

        total = int(_retry_missing_table(
            lambda: _scalar(conn, f"SELECT COUNT(*) FROM {src} WHERE {where}", params)) or 0)
        offset = (page - 1) * size
        rows = _retry_missing_table(lambda: _rows_as_dicts(conn.execute(
            f"SELECT {select} FROM {src} WHERE {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
            params + [size, offset],
        )))

    return {
        "metric": metric,
        "total": total,
        "page": page,
        "size": size,
        "sort": sort if sort in expr_of else "",
        "dir": "asc" if (dir or "").strip().lower() == "asc" else "desc",
        "columns": [{"key": key, "label": label} for _, key, label in spec],
        "rows": rows,
    }

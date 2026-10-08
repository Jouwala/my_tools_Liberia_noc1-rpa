"""TT 告警推送的**日志表**读写（`eflow_tt_whatsapp_alert_log`）。

从 `tt_alarm_whatsapp_service` 拆出：建表、按 tt_no 读历史记录、写回发送结果
三者共同维护同一份表结构，是一个内聚单元，且**不依赖任何配置常量**（表名由调用方
传入或取默认），因此可以独立单测。

## 为什么这是服务内建表（不进 Alembic）

沿用项目既有做法（`battery_kpi_service` / `ms_sla_dashboard` 等同类服务表一致）：
`CREATE TABLE IF NOT EXISTS` 幂等建表 + 建索引。列类型取 TEXT/INTEGER 这类
双方言通用写法；PG 下的 TOCTOU 竞态由 `database.py` 的 `_PsycopgRaw.executescript`
duplicate_table 重试兜住（`backend/database.py:344-369`）。

## 状态语义（2026-10-05 随触发机制切换一并明确）

`send_status` 只有 `'Y'` / `'N'`：**只有推送进程确认投递成功后**才写 `'Y'`，
超时/失败一律 `'N'` 并把原因写进 `last_error`。绝不伪造成功。
这两个字段就是「发没发过 / 发过几次」的权威答案：

  * `send_status`  —— 该单**发送没有**（Y=至少确认送达过一次；N=从未确认送达）
  * `send_count`   —— 该单**发送了几次**（只计确认成功；失败不计数）
  * `last_send_time` —— 最近一次确认成功的时间（重报冷却的基准）

## 跟踪列（触发机制切换新增，2026-10-05）

  * `first_seen_time`        —— 首次触发时间（realtime_alarm 里出现该单告警）
  * `last_alarm_seen_time`   —— 该单关联告警最近一次仍出现在 realtime_alarm 的时间
                                （消失 ≈ 告警清除，是将来「恢复通知」的数据基础）
  * `last_known_update_time` —— 最近一次（实时查单/镜像）见到的 TT last_modified_time
                                （双档重报「自上次发送后是否有更新」的判定基准）
  * `last_check_time`        —— 最近一次实时/镜像查单时间

老库升级：`ensure_log_table` 对已存在的表做**幂等加列**（`_ensure_columns`，
sqlite 查 PRAGMA table_info、PG 查 information_schema，缺哪列 ALTER 哪列），
不需要 Alembic —— 与本表「服务内建表」的定位一致。
"""
import logging
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from backend.dialect_helpers import upsert

logger = logging.getLogger("tt_alarm_store")

LOG_TABLE = "eflow_tt_whatsapp_alert_log"
LOG_TABLE_INDEX = f"idx_{LOG_TABLE}_status"

# 主键列（不参与补列，建表时即存在）
LOG_PK = ("tt_no",)

# 日志表列（upsert 与 SELECT 共用，避免两处列名分叉）
LOG_COLUMNS = (
    "tt_no", "alarm_occur_time", "ticket_severity", "alarm_code",
    "site_id", "site_name", "title",
    "send_status", "send_count", "last_send_time", "last_tt_modified",
    "first_seen_time", "last_error", "updated_time",
    "last_alarm_seen_time", "last_known_update_time", "last_check_time",
    "mail_notified_time", "mail_summary_time",
)

# ==========================================================
# 幂等补列的**单一事实来源**（2026-10-06 事故修复）
#
# 事故：PG 库里的 `eflow_tt_whatsapp_alert_log` 是**早期版本**建的，缺
# `last_error` 列。`CREATE TABLE IF NOT EXISTS` 对已存在的表是 no-op，不会加列；
# 而旧 `_ensure_columns` 的补列清单**漏了 `last_error`**（只覆盖 TRACK + MAIL），
# 于是每次 `record_result` upsert 都带 `last_error` → PG 报
# `UndefinedColumn: 字段 "last_error" 不存在`，任务整轮失败。
#
# 根因：补列清单与建表列集合**两处各写一份**，加列时容易只改建表、忘了改补列。
# 修复：补列集合 = 建表列全集（LOG_COLUMNS 去掉主键），从此「加列只需改
# LOG_COLUMNS 一处」，结构上杜绝再漏。
# ==========================================================

# 2026-10-05 新增的跟踪列：老库没有这些列，由 _ensure_columns 幂等补上
TRACK_COLUMNS = (
    "last_alarm_seen_time", "last_known_update_time", "last_check_time",
)

# 2026-10-06 新增的**邮件**幂等列：老库没有这些列，同样由 _ensure_columns 补上。
#
# 这两列是邮件「至多一封」的**唯一幂等键**（见 tt_alarm_whatsapp_service 的发信段）：
#   * mail_notified_time —— 首次通报邮件已发出的时间
#   * mail_summary_time  —— 结束汇总邮件已发出的时间
# 非空即视为已发，**永不重发**。没有它们，每 5 分钟一轮的扫描会把同一单的
# 汇总反复发出去（清除状态是持久事实，不会自己消失）。
MAIL_COLUMNS = (
    "mail_notified_time", "mail_summary_time",
)

# 需要向老表补齐的列全集：建表列 - 主键。老表缺哪列补哪列（幂等）。
ENSURE_COLUMNS = tuple(c for c in LOG_COLUMNS if c not in LOG_PK)

# 列类型映射（建表与补列共用；缺省 TEXT）。本表除 send_count(INTEGER) 外全 TEXT。
COLUMN_TYPES = {"send_count": "INTEGER"}

# ==========================================================
# 幂等补约束的**单一事实来源**（2026-10-07 事故修复）
#
# 事故：生产 PG 库里的本表是**早期由别处建的**（残留 `_source_file` /
# `_source_sheet` / `_import_time` 三列，是 Excel 导入建表的痕迹），
# 因此 `tt_no` 上**没有任何主键或唯一约束**。而 `record_result` 走的是
# `dialect_helpers.upsert(..., conflict_cols=["tt_no"])`，PG 分支生成
# `INSERT ... ON CONFLICT ("tt_no") DO UPDATE` —— 没有唯一约束可匹配时
# PG 直接报 `InvalidColumnReference: 没有匹配 ON CONFLICT 说明的唯一或者排除约束`。
#
# 隐蔽性：`_build_create_sql` 里的 `PRIMARY KEY` **只对新建表生效**，
# `CREATE TABLE IF NOT EXISTS` 对已存在的表是 no-op；而 `_ensure_columns`
# 只 `ALTER ADD COLUMN`，**从不补约束**。于是「新建库一切正常、老库写必失败」，
# 且只要扫描窗口内没有需要落库的候选单（`due=0`），就永远不触发 —— 事故
# 发生时该表已静默 5 天没有写入（最后一行 2026-10-02）。
#
# 修复：`ensure_log_table` 在建表/补列之后，对**已存在的表**幂等补上主键约束。
# 与补列同理，「约束」也收敛到 LOG_PK 单一事实来源，不再依赖建表时恰好生效。
# ==========================================================

# 幂等补约束时使用的约束名（PG 需要显式命名才能判重）。
#
# ⚠️ 必须**按表名派生**，不能是模块级固定常量：`ensure_log_table(conn, table)`
# 支持对任意表调用（测试与迁移脚本都会传别的表名），固定常量会让第二张表的
# `ADD CONSTRAINT` 撞名报 `DuplicateTable: 关系 ... 已经存在`。
# PG 的约束名在 schema 内唯一，故这里带上表名。
def _pk_constraint_name(table: str) -> str:
    return f"{table}_pk"


def _is_sqlite(conn) -> bool:
    import sqlite3
    return isinstance(conn, sqlite3.Connection)


def _existing_columns(conn, table: str) -> set:
    if _is_sqlite(conn):
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ? "
        "AND table_schema = ANY(current_schemas(false))",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


def _pk_covered_columns(conn, table: str) -> set:
    """返回该表上「主键或唯一约束」覆盖的列集合（sqlite / PG 双模）。

    只关心「哪一组列已有唯一性保证」——这正是 `ON CONFLICT (cols)` 能否成立
    的判据。任一唯一约束的列集合完全等于 LOG_PK 即视为已满足，不重复加约束。

    sqlite：`PRAGMA index_list` 取 unique 索引，`PRAGMA index_info` 取列。
            （sqlite 的 `INTEGER PRIMARY KEY` 也表现为 unique 索引，
              TEXT PRIMARY KEY 同理，故这一个入口即可覆盖两种建表方式。）
    PG：    pg_index + pg_constraint，`indisunique` 为真且非部分索引。
    """
    covered = set()
    try:
        if _is_sqlite(conn):
            for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
                # row: (seq, name, unique, origin, partial)
                if not row[2]:
                    continue
                idx_name = row[1]
                cols = [
                    r[2] for r in
                    conn.execute(f"PRAGMA index_info({idx_name})").fetchall()
                ]
                if len(cols) == 1:
                    covered.update(cols)
            return covered
        rows = conn.execute(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_class t ON t.oid = i.indrelid "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey) "
            "WHERE t.relname = ? AND i.indisunique AND i.indisvalid "
            "AND i.indpred IS NULL AND i.indexprs IS NULL",
            (table,),
        ).fetchall()
        covered.update(r[0] for r in rows)
    except Exception as e:  # noqa: BLE001
        # 查不到唯一约束信息时**保守返回空**：宁可尝试 ADD CONSTRAINT（已存在会被
        # 下面的 duplicate 分支吞掉），也不要因为探测失败而静默跳过补约束，
        # 那会退回「写路径永久失败」的事故形态。
        logger.debug(f"读取 {table} 唯一约束失败（将尝试补约束）: {e}")
    return covered


def _ensure_pk_constraint(conn, table: str) -> bool:
    """给已存在的老表幂等补**主键约束**（仅 PG 需要；sqlite 建表即带约束）。

    返回是否真的执行了补约束。

    为什么必须有这一步：`_build_create_sql` 里的 `PRIMARY KEY` 只对**新建**表
    生效，`CREATE TABLE IF NOT EXISTS` 遇到已存在的表是 no-op。老库（如本项目的
    Excel 导入遗留表）没有约束时，`record_result` 的 `ON CONFLICT ("tt_no")`
    必然报 InvalidColumnReference —— 见文件顶部 2026-10-07 事故说明。

    安全性：
      * **前置校验**：加 PK 前先确认目标列无重复、无 NULL，否则 PG 会报错；
        这种情况**不静默跳过**，而是抛出并把样本带出去，交由迁移脚本人工裁决
        （自动删重复行是不可接受的破坏性动作）。
      * **幂等**：已有等价唯一约束则直接返回；并发下 duplicate_object（42710）
        被吞掉，视为「另一进程刚补上」。
      * sqlite：建表路径已带 `PRIMARY KEY`，且 upsert 走 `INSERT OR REPLACE`
        不需要冲突目标，故直接跳过（避免在 sqlite 上做无意义的表重建）。
    """
    if _is_sqlite(conn):
        return False

    want = tuple(LOG_PK)
    covered = _pk_covered_columns(conn, table)
    if all(c in covered for c in want) and len(want) == 1:
        return False  # 已有单列唯一约束，ON CONFLICT 可用

    # 前置校验：重复或 NULL 会让 ADD PRIMARY KEY 失败，先给出可操作的诊断
    pk_col = want[0]
    dup = conn.execute(
        f"SELECT {pk_col}, COUNT(*) AS c FROM {table} "
        f"WHERE {pk_col} IS NOT NULL GROUP BY {pk_col} HAVING COUNT(*) > 1 LIMIT 5"
    ).fetchall()
    nulls = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {pk_col} IS NULL"
    ).fetchone()[0]
    if dup or nulls:
        raise RuntimeError(
            f"{table} 无法补主键：{pk_col} 存在 "
            f"{len(dup)} 组重复值、{nulls} 个 NULL。"
            f"重复样本={[r[0] for r in dup]}。"
            f"请先用迁移脚本人工裁决（切勿自动删行）。"
        )

    try:
        cname = _pk_constraint_name(table)
        conn.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {cname} "
            f"PRIMARY KEY ({pk_col})"
        )
        conn.commit()
        logger.info(f"{table}：已补主键约束 {cname}({pk_col})")
        return True
    except Exception as e:  # noqa: BLE001
        _code = getattr(getattr(e, "diag", None), "sqlstate", "") or ""
        _msg = str(e).lower()
        if _code == "42710" or "already exists" in _msg or "duplicate" in _msg:
            return False  # 并发补约束：另一进程刚加上
        raise


def _ensure_columns(conn, table: str) -> None:
    """给已存在的老表幂等补列（sqlite / PG 的 ADD COLUMN 语法在此场景一致）。

    补列集合 = **建表列全集去掉主键**（`ENSURE_COLUMNS`），不再是一份手写的
    局部清单 —— 2026-10-06 事故正是因为旧清单漏了 `last_error`，导致老库上
    upsert 报 `UndefinedColumn`。现在加列只需改 `LOG_COLUMNS` / CREATE TABLE 一处。

    类型按 `COLUMN_TYPES`（缺省 TEXT）——老库缺列按 TEXT 补对齐 sqlite 宽容语义。

    并发：PG 下两个进程同时补列会 TOCTOU（duplicate_column, 42701）。本函数逐列
    `try/except` 吞掉「已存在」类错误，保证幂等（另一进程刚补上就算成功）。
    """
    present = _existing_columns(conn, table)
    for col in ENSURE_COLUMNS:
        if col in present:
            continue
        col_type = COLUMN_TYPES.get(col, "TEXT")
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        except Exception as e:  # noqa: BLE001
            # 唯一可接受的失败：并发补列时本列已被别的进程加上（duplicate_column）。
            # 其余异常（权限/连接）应上抛，不能静默留下缺列的表。
            _code = getattr(getattr(e, "diag", None), "sqlstate", "") or ""
            _msg = str(e)
            if _code == "42701" or "already exists" in _msg.lower() or "duplicate" in _msg.lower():
                continue
            raise


def _build_create_sql(table: str) -> str:
    """按 `LOG_COLUMNS` / `COLUMN_TYPES` 生成建表 DDL（单一事实来源）。

    这样「加列」只需改 `LOG_COLUMNS` 一处，建表与补列（`_ensure_columns`）自动
    同步 —— 2026-10-06 事故即两处各写一份导致漏列，此生成法从结构上消除该类缺陷。
    """
    defs = []
    for col in LOG_COLUMNS:
        col_type = COLUMN_TYPES.get(col, "TEXT")
        if col in LOG_PK:
            defs.append(f"    {col} {col_type} PRIMARY KEY")
        else:
            defs.append(f"    {col} {col_type}")
    return f"CREATE TABLE IF NOT EXISTS {table} (\n" + ",\n".join(defs) + "\n)"


def ensure_log_table(conn, table: str = LOG_TABLE) -> None:
    """幂等建表 + 建索引 + 老表补列 + 老表补主键约束（双模：sqlite / PG）。

    「修复老库」的三件事缺一不可，它们各自堵一类事故：
      1. 建表（新建库从零就带全列 + 主键）；
      2. `_ensure_columns` 补列 —— 堵 2026-10-06 的 `UndefinedColumn: last_error`；
      3. `_ensure_pk_constraint` 补主键 —— 堵 2026-10-07 的
         `InvalidColumnReference: 没有匹配 ON CONFLICT 说明的唯一或者排除约束`。
    第 2、3 步都只对**老表**有意义（新建表已一次到位），且都必须幂等。
    """
    conn.execute(_build_create_sql(table))
    _ensure_columns(conn, table)
    _ensure_pk_constraint(conn, table)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{table}_status "
        f"ON {table} (send_status, last_send_time)"
    )


def load_records(conn, tt_nos: Iterable[str],
                 table: str = LOG_TABLE) -> Dict[str, Dict[str, Any]]:
    """按 tt_no 批量读历史记录 → {tt_no: {send_status, last_send_time, ...}}。

    分块查询（每块 200 个 tt_no），避免 IN 子句过长触发 SQLite 变量上限
    （默认 SQLITE_MAX_VARIABLE_NUMBER，PG 也有参数上限）。
    """
    nos = [n for n in tt_nos if n]
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(nos), 200):
        chunk = nos[i:i + 200]
        marks = ",".join("?" * len(chunk))
        cur = conn.execute(
            f"SELECT tt_no, send_status, send_count, last_send_time, "
            f"last_tt_modified, first_seen_time, last_error, "
            f"last_known_update_time, last_check_time, last_alarm_seen_time, "
            f"mail_notified_time, mail_summary_time "
            f"FROM {table} "
            f"WHERE tt_no IN ({marks})",
            tuple(chunk),
        )
        names = [d[0] for d in cur.description]
        for r in cur.fetchall():
            row = dict(zip(names, r))
            out[str(row["tt_no"])] = row
    return out


def base_record(row: Dict[str, Any],
                existing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """构造一条日志记录（保留已有的首见时间与发送计数）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tt_no = str(row.get("tt_no") or "")
    return {
        "tt_no": tt_no,
        "alarm_occur_time": row.get("alarm_occur_time"),
        "ticket_severity": row.get("ticket_severity"),
        "alarm_code": row.get("_alarm_code_norm") or row.get("alarm_code"),
        "site_id": row.get("site_id"),
        "site_name": row.get("site_name"),
        "title": row.get("title"),
        "send_status": (existing or {}).get("send_status") or "N",
        "send_count": int((existing or {}).get("send_count") or 0),
        "last_send_time": (existing or {}).get("last_send_time"),
        "last_tt_modified": row.get("last_modified_time"),
        # 首次写入的时间要留住，不能用本轮 now 覆盖
        "first_seen_time": (existing or {}).get("first_seen_time") or now,
        "last_error": (existing or {}).get("last_error"),
        "updated_time": now,
        # 跟踪列：保留已有值，调用方可用 overrides 覆盖（见 record_result）
        "last_alarm_seen_time": (existing or {}).get("last_alarm_seen_time"),
        "last_known_update_time": (existing or {}).get("last_known_update_time"),
        "last_check_time": (existing or {}).get("last_check_time"),
        # 邮件幂等列：必须原样带过来，否则 upsert 会把"已发过"抹成 NULL，
        # 下一轮扫描就会**重复发汇总**（本表 upsert 是整行覆盖，不是增量更新）。
        "mail_notified_time": (existing or {}).get("mail_notified_time"),
        "mail_summary_time": (existing or {}).get("mail_summary_time"),
    }


def _read_mail_state(conn, tt_no, table: str = LOG_TABLE) -> Dict[str, Any]:
    """只回查邮件幂等两列（`record_result` 未收到 existing 时的兜底）。

    查不到（新单）或查询异常一律返回空 dict —— 不能让一次读失败把发送结果写挂。
    """
    if not tt_no:
        return {}
    try:
        cur = conn.execute(
            f"SELECT mail_notified_time, mail_summary_time FROM {table} WHERE tt_no = ?",
            (str(tt_no),),
        )
        r = cur.fetchone()
        if not r:
            return {}
        return {"mail_notified_time": r[0], "mail_summary_time": r[1]}
    except Exception:  # noqa: BLE001
        return {}


def record_result(conn, row: Dict[str, Any], ok: bool, error: str = "",
                  existing: Optional[Dict[str, Any]] = None,
                  table: str = LOG_TABLE,
                  tracking: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """写回一条发送结果（upsert by tt_no），返回写入的记录。

    `ok=True` → `send_status='Y'`、`send_count`+1、`last_send_time=now`；
    `ok=False` → `send_status='N'`、`send_count` **不变**（失败不计入发送次数）、
    `last_error` 记原因（截断 500 字符，避免异常堆栈撑爆列）。

    `tracking` 是本轮已知的跟踪字段（last_known_update_time / last_check_time /
    last_alarm_seen_time），随发送结果一并落库；缺省键保留 existing 原值。

    ⚠️ **邮件幂等列（mail_*）不依赖调用方传 `existing`**：本表 upsert 是整行覆盖，
    若哪天调用方漏传 existing，`mail_summary_time` 会被写成 NULL，同一单的汇总就会
    被**反复重发**（清除是持久事实，不会自己消失）。故此处对未提供的 existing
    主动回查一次这两列 —— 2026-10-06 实测确认过该风险真实存在。
    """
    if existing is None:
        existing = _read_mail_state(conn, row.get("tt_no"), table)
    rec = base_record(row, existing)
    for k, v in (tracking or {}).items():
        if k in TRACK_COLUMNS:
            rec[k] = v
    if ok:
        rec["send_status"] = "Y"
        rec["send_count"] = int(rec["send_count"]) + 1
        rec["last_send_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rec["last_tt_modified"] = row.get("last_modified_time")
        rec["last_error"] = ""
    else:
        rec["send_status"] = "N"
        rec["last_error"] = str(error or "未确认投递")[:500]
    upsert(conn, table, [rec], ["tt_no"])
    return rec


def refresh_tracking(conn, tt_no: str, tracking: Dict[str, Any],
                     table: str = LOG_TABLE) -> bool:
    """只刷新跟踪列，**不触碰任何 send_* 字段**（本轮「不发送、只记录」用）。

    返回是否真的更新了行。记录不存在时**不创建** —— 跟踪信息只对已触发过的单
    有意义；没发过单的候选（级别不符/已清除等被过滤的）不该在日志表里留行，
    否则 `/api/whatsapp/tt-alert/log` 会被从未推送的单刷满。
    """
    if not tt_no:
        return False
    sets, vals = [], []
    for k in TRACK_COLUMNS:
        if k in tracking:
            sets.append(f"{k} = ?")
            vals.append(tracking[k])
    if not sets:
        return False
    sets.append("updated_time = ?")
    vals.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    vals.append(str(tt_no))
    cur = conn.execute(
        f"UPDATE {table} SET {', '.join(sets)} WHERE tt_no = ?", tuple(vals))
    return (cur.rowcount or 0) > 0


def mark_mail_sent(conn, tt_no: str, kind: str,
                   when: Optional[str] = None, table: str = LOG_TABLE) -> bool:
    """标记某单的某类邮件已发（`kind` ∈ {`notified`, `summary`}）。返回是否更新到行。

    **这是邮件幂等的核心**：置位后 `pending_summary_mail` 不再返回该单，
    且 `base_record` 会把该值原样带到后续 upsert，不会被后续写发送结果抹掉。
    """
    col = {"notified": "mail_notified_time", "summary": "mail_summary_time"}.get(kind)
    if not tt_no or not col:
        return False
    ts = when or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        f"UPDATE {table} SET {col} = ?, updated_time = ? WHERE tt_no = ?",
        (ts, ts, str(tt_no)),
    )
    return (cur.rowcount or 0) > 0


def pending_summary_mail(conn, limit: int = 200,
                         table: str = LOG_TABLE) -> list:
    """返回「需要发结束汇总」的单号列表。

    选取条件（三条同时满足）：
      1. `send_count > 0` —— **真发过 WhatsApp** 的单才发汇总。从未确认送达的单
         没有「进展」可言，给它发汇总只会制造噪音。
      2. `mail_summary_time` 为空 —— 还没发过汇总（幂等键）。
      3. `mail_notified_time` 非空 —— 发过首次通报。保证顺序：先有通报才有汇总，
         否则用户会先收到一封"结束汇总"，却从没见过这单的开始。

    ⚠️ **本查询刻意不碰 `realtime_alarm`**：告警清除后该单会从实时表消失
    （2026-10-06 实测：4 个已清除单在 realtime_alarm 里 0 命中，而 eflow_tt 里
    4/4 都在）。所以「是否已结束」由调用方回 `eflow_tt` 用 `alarm_clear_time`
    判断，本函数只负责把「在跟单且没发过汇总」的候选捞出来 —— 这是汇总邮件
    唯一能可靠触发的路径。
    """
    cur = conn.execute(
        f"SELECT tt_no FROM {table} "
        f"WHERE send_count > 0 "
        f"  AND (mail_summary_time IS NULL OR mail_summary_time = '') "
        f"  AND mail_notified_time IS NOT NULL AND mail_notified_time != '' "
        f"ORDER BY COALESCE(last_send_time, updated_time) ASC "
        f"LIMIT ?",
        (int(limit),),
    )
    return [str(r[0]) for r in cur.fetchall()]

"""TT 告警消息渲染 —— 复用 whatsapp-kb-bot 的 TT 分析引擎。

## 为什么是子进程而不是 import

完整的 TT 分析（里程碑时间轴、派单依据、SLA 时效）由
`Task/whatsapp-kb-bot/scripts/tt-analyze.py` 实现（2175 行，纯标准库 + openpyxl）。
它是**已经在跑的机器人**在用的引擎，本任务只是复用它的输出，不重写一份 ——
两份分析逻辑并存必然会分叉，而「群里看到的分析」与「告警推送里的分析」不一致
是最难排查的那类问题。

用子进程而非 `import` 的理由：
  1. 它不在 my_app 的包路径里，import 需要动 `sys.path` 且与自己的 `main()` 冲突；
  2. 它的模块级常量（`DB_PATH` / `RULES_XLSX`）在 **import 时**求值，进程内改不了 ——
     而我们要按 my_app 的实际路径传进去（见下）；
  3. 它已经为自己设计好了 CLI 契约（`tt_no --lang en` → stdout 纯文本），
     子进程正是它预期的调用方式（机器人也是这么调的）。

## 数据源路径

引擎默认读 `Y:/Task/my_app/...`（生产机上的盘符），本机开发环境该盘不存在。
故这里**显式传**三个环境变量，指向 my_app 自己的真实路径：

| 变量 | 指向 |
| --- | --- |
| `MY_APP_DIR` | 本仓库的 `Task/my_app` 根 |
| `MY_APP_DB` | `db/app.db`（SQLite 副本，引擎按 sqlite3 只读打开） |
| `MY_APP_TT_RULES` / `MY_APP_PUSH_RULES` | 规则表 xlsx |

> **引擎读的是 SQLite 副本，不是生产的 PG**（`tt-analyze.py:57`）。这一点后果很重，
> 2026-09-29 实测更正了此前的判断：该副本由 `pg_to_sqlite_sync` **每小时第 45 分**
> 才刷新一次，而本任务每 15 分钟跑一次 —— 实测最坏时副本落后 **84 分钟**
> （SQLite 最新 16:17 vs PG 17:41；17 点这一小时 PG 有 5 单、SQLite **0 单**）。
>
> 也就是说：**副本落后期间每一条新告警都会降级成 6 行模板** —— 这不是偶发异常，
> 而是这个任务的常态。故渲染前先用 `_snapshot_tt()` 把该单从 PG 抄进临时快照，
> 再让引擎读它（见「新鲜度」一节）。拿不到快照时退回镜像库，宁可降级也不漏发。

## 降级

引擎不可用（脚本缺失、xlsx 被占用、超时、非零退出）时返回 `None`，
由调用方回退到 `tt_alarm_message.build_tt_message()` 的头部摘要模板。
**降级是刻意的**：宁可发一条信息较少的告警，也不要因为分析引擎的问题漏发整条告警。

⚠️ **但「降级」不能被自己的快照代码制造出来**（2026-10-05 事故）：
`_snapshot_tt(row=...)` 曾用稀疏实时行的键当表结构，导致引擎抛
`no such column: ticket_no` 退出码 3 —— 7 行模板取代了 31 行完整格式。
它影响的是**主路径**（实时触发就是稀疏行），所以当时几乎每条推送都在降级，
而群里只会看到「信息怎么这么少」。修法与回归测试见 `_snapshot_tt` docstring
与 `tests/test_tt_alarm_render.py::test_sparse_live_row_snapshot_keeps_authoritative_columns`。
"""
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("tt_alarm_render")

# my_app 根：本文件在 backend/services/ 下，向上三级即仓库里的 Task/my_app
_MY_APP_DIR = Path(__file__).resolve().parents[2]

# 引擎脚本：与 my_app 同级的兄弟目录（Task/whatsapp-kb-bot/scripts/tt-analyze.py）
_ENGINE = _MY_APP_DIR.parent / "whatsapp-kb-bot" / "scripts" / "tt-analyze.py"

# 分析一次的现实耗时：要读 36k 行的 SQLite + 两张 xlsx 规则表。**实测 0.3~0.5 秒**
#（2026-09-29，28 核机器，单独运行 3 次均 <1s；冷启动也只 4~6 秒）。
#
# 为什么给到 120 秒这么大的余量 —— 实测踩过一次**假超时**：
# 在跑 pytest 全量的同时并发调用，单次超过 60 秒被判超时，消息降级成了 6 行头部摘要。
# 机器并不慢（28 核），是当时有多个 python 进程在抢盘（读 1.5G 的 app.db + xlsx）。
# 结论：**这个引擎的耗时对磁盘 IO 竞争极其敏感**，正常值是秒级，
# 一旦排队就可能是几十秒。给足余量远好过在磁盘忙时把完整消息降级成残篇。
#
# 超时**不是**致命错误：调用方会降级到内置头部模板（宁可少信息也不漏发）。
TIMEOUT_SECONDS = int(os.environ.get("TT_ALERT_ANALYZE_TIMEOUT", "120"))


def render_message(row, lang: str = "en") -> str:
    """渲染一条告警消息（**服务层入口**）：优先分析引擎，失败降级到头部模板。

    完整分析（里程碑时间轴 / 派单依据 / SLA 时效）由本模块子进程调用
    `whatsapp-kb-bot/scripts/tt-analyze.py` 得到，与群里机器人回答同源 ——
    两份分析逻辑并存必然分叉，而「群里的分析」与「告警推送里的分析」不一致
    是最难排查的那类问题。

    **降级是刻意的**：引擎不可用（脚本缺失、xlsx 被占用、超时、单号查不到）时退回
    `build_tt_message()` 的头部摘要，宁可发一条信息较少的告警，也不要漏发整条告警。
    """
    return render_message_ex(row, lang)[0]


def render_message_ex(row, lang: str = "en"):
    """同 `render_message`，并返回降级原因（成功时为空串）。

    降级是**静默**的：消息从 ~30 行缩成 7 行，群里的人只会觉得「这次信息怎么这么少」。
    任务入口据此把降级原因汇总进 `out["errors"]`，让运维在任务页上直接看到
    「本轮 N 单降级：引擎超时」，而不是等用户来问。

    `row` 会透传给 `_snapshot_tt`：调用方手里已有该单的行（实时查单行或镜像行）
    时直接喂给引擎造快照，省一次查库；镜像里查无此单的新单也靠它出完整格式。
    """
    # 延迟导入：tt_alarm_message 是纯函数模块，放在这里避免与本模块的循环依赖
    from backend.services.tt_alarm_message import build_tt_message

    tt_no = str(row.get("tt_no") or "").strip()
    try:
        text, reason = render_with_reason(tt_no, lang=lang, row=row)
    except Exception as e:  # noqa: BLE001
        # render_with_reason 自身不抛异常；这里防的是未来改动引入的意外
        logger.warning("[TTAlert] 渲染器异常，降级到内置模板: %s", tt_no, exc_info=True)
        text, reason = None, f"渲染器异常：{type(e).__name__}: {e}"
    if text:
        return text, ""
    return build_tt_message(row), (reason or "引擎未返回内容")


def engine_path() -> Path:
    """引擎脚本路径（可用环境变量覆盖，便于部署到不同目录布局）。"""
    override = os.environ.get("TT_ALERT_ANALYZE_SCRIPT")
    return Path(override) if override else _ENGINE


def engine_available() -> bool:
    """引擎脚本是否存在 —— 供任务入口在开跑前判断并给出明确提示。"""
    return engine_path().is_file()


def _engine_env(db_override: Optional[Path] = None) -> dict:
    """给子进程的环境：显式覆盖引擎的三个路径常量（见模块 docstring）。"""
    env = dict(os.environ)
    env["MY_APP_DIR"] = str(_MY_APP_DIR)
    env["MY_APP_DB"] = str(db_override or (_MY_APP_DIR / "db" / "app.db"))
    rules_dir = _MY_APP_DIR / "backend" / "services" / "eflow_rules"
    env["MY_APP_TT_RULES"] = str(rules_dir / "eflow_TT_rules.xlsx")
    env["MY_APP_PUSH_RULES"] = str(rules_dir / "eflow_push_rules.xlsx")
    # 引擎按 stdout 是否为 tty 决定编码（tt-analyze.py:43-50）；管道环境下它会
    # 强制 UTF-8。这里再用 PYTHONIOENCODING 兜一层，避免子进程被其它工具包裹时
    # 退回 cp1252 导致中文抛 UnicodeEncodeError。
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# ==========================================================
# 新鲜度：引擎读的是**滞后的 SQLite 镜像**，不是生产 PG
# ==========================================================
# ⚠️ 这是本项目最容易踩的结构性坑，2026-09-29 实测确认：
#
#   引擎（tt-analyze.py:864）写死 `sqlite3.connect('file:{DB_PATH}?immutable=1')`，
#   读的是 `db/app.db` —— 一份由 `pg_to_sqlite_sync` **每小时第 45 分**刷新的快照。
#   而本任务筛选用的是**生产 PG**（每 15 分钟跑一次）。
#
#   两边不同步时：PG 选出刚发生的新单 → 引擎在旧镜像里查不到 → 退出码 1
#   → **降级成 6 行内置模板** → 发出去的不是完整分析格式。
#   实测数据：SQLite 36419 行 / 最新 16:17；PG 36425 行 / 最新 17:41 ——
#   17 点这一小时 PG 有 5 单、SQLite **0 单**。
#
#   所以「降级」在这个任务里**不是异常路径，而是常态** —— 只要镜像落后就会发生。
#
# 对策：渲染前把这一单从 PG 抄进一份**临时 SQLite 快照**，用 `MY_APP_DB` 指给引擎。
#   只抄这一单（而非全表），所以开销与单量无关（实测每次 <50ms）。
#   拿不到快照时退回原库路径 —— 宁可降级，也不能因为快照失败就漏发告警。
_SNAPSHOT_LOCK = threading.Lock()


_AUTHORITATIVE_COLUMNS_CACHE: Optional["list[str]"] = None


def _authoritative_columns() -> "list[str]":
    """`eflow_tt` 的权威全列名（用于建快照表结构，缓存一次）。

    为什么需要它：稀疏的实时行不能决定表结构 —— 引擎有若干**不按 `_TT_COLUMNS`
    取交集**的 SQL（`_row_keys` 的 `SELECT tt_no, ticket_no, wo_no ...`、
    `tt-analyze.py:999/1052`），表里没有那些列就直接抛 `no such column` 退出。
    见 `_snapshot_tt` docstring 的 2026-10-05 修复记录。

    取不到时返回空列表，调用方退回「用行自身的键建表」的旧行为（宁可降级不中断）。
    """
    global _AUTHORITATIVE_COLUMNS_CACHE
    if _AUTHORITATIVE_COLUMNS_CACHE is not None:
        return _AUTHORITATIVE_COLUMNS_CACHE
    cols: "list[str]" = []
    try:
        from backend.database import get_raw_connection

        with get_raw_connection() as conn:
            cur = conn.execute("SELECT * FROM eflow_tt WHERE 1 = 0")
            cols = [d[0] for d in (cur.description or [])]
    except Exception as e:  # noqa: BLE001
        logger.warning("[TTAlert] 取 eflow_tt 列清单失败，快照退回稀疏结构: %s", e)
        cols = []
    _AUTHORITATIVE_COLUMNS_CACHE = cols
    return cols


def _snapshot_tt(tt_no: str, row: Optional[dict] = None) -> Optional[Path]:
    """把单号 `tt_no` 从生产库抄进临时 SQLite，返回该文件路径（失败返回 None）。

    为什么要绕这一圈而不是改引擎：引擎是 `whatsapp-kb-bot` 的**共享组件**
    （群里机器人也在用），把它的取数改成 PG 会影响另一个系统；
    且它依赖 `immutable=1` 打开数据库，SQLite 与 PG 的 SQL 方言差异会牵动全文。
    在这里造一份「最新鲜的单行快照」是最小侵入的修法。

    `row` 不为空时用它做**值**，但**表结构仍取权威全列**（见下）—— 这是给
    「刚触发、镜像里还没有」的新单准备的。

    ⚠️ **2026-10-05 修复：稀疏行不能直接当表结构。**
    此前实现是「用 `row` 的键当列名建表」，理由是引擎按 `PRAGMA table_info` 与
    自己的列清单取交集、缺列只是不 SELECT 不会报错。**这个理由是错的**：
    引擎还有一条不走 `_TT_COLUMNS` 交集的 SQL —— `_row_keys` 依赖的
    `SELECT tt_no, ticket_no, wo_no FROM "eflow_tt" WHERE rowid = ?`
    （tt-analyze.py:999），以及建索引时的同类查询（:1052）。而任务的实时触发行
    （`merged_render_row` 的产物）字段集是 `{tt_no, alarm_code, alarm_occur_time,
    last_modified_time, ticket_severity, alarm_raised_time}` —— **没有 ticket_no**。
    于是快照里只有 1~6 列，引擎抛 `no such column: ticket_no` 退出码 3，
    整批消息静默降级成 7 行模板（线上实测：`TT202610050073` 只发出 314 字符 8 行，
    而完整格式是 1538 字符 31 行）。这**不是偶发**：实时触发是本任务的主路径。

    修法：表结构固定用**权威全列**（查库路径的列集，或 `_snapshot_tt` 缓存的全列），
    稀疏行里缺的列填 NULL。这样引擎的每条 SQL 都能解析，缺失字段退化成
    「该字段无值」而不是让整个引擎崩掉 —— 详见 `_authoritative_columns()`。
    """
    if row is None:
        try:
            from backend.database import get_raw_connection
        except Exception:  # noqa: BLE001
            return None

        try:
            with get_raw_connection() as conn:
                cur = conn.execute("SELECT * FROM eflow_tt WHERE tt_no = ?", (tt_no,))
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
        except Exception as e:  # noqa: BLE001
            logger.warning("[TTAlert] 取 PG 单行失败，退回镜像库: %s (%s)", tt_no, e)
            return None
        if not rows:
            return None
        col_names = cols
        row_tuples = rows
    else:
        # 实时行：值统一 TEXT（与查库路径同规则），但**表结构取权威全列**。
        # 缺列填 NULL —— 让引擎的每条 SQL 都能解析，而不是整批降级。
        # 见本函数 docstring 的 2026-10-05 修复记录。
        auth_cols = _authoritative_columns()
        if auth_cols:
            col_names = auth_cols

            def _cell(c):
                v = row.get(c)
                return None if v is None else str(v)

            row_tuples = [tuple(_cell(c) for c in col_names)]
        else:
            # 拿不到权威列集（库异常）：退回稀疏结构，宁可降级也不中断发送。
            col_names = [c for c in row.keys() if not str(c).startswith("_")]
            row_tuples = [tuple(None if row[c] is None else str(row[c]) for c in col_names)]

    import sqlite3
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="tt_snap_")) / "tt.db"
    try:
        con = sqlite3.connect(str(tmp))
        try:
            # 引擎用的是 `SELECT ... FROM eflow_tt`，故只要这一张表。
            # 类型统一 TEXT —— 引擎只做字符串比较与正则提取，不依赖数值亲和性，
            # TEXT 足够且避免类型转换抛错。
            # 列集必须是**权威全列**（稀疏行也要补 NULL），原因见 docstring：
            # 引擎有 `SELECT tt_no, ticket_no, wo_no ...` 这类不按列清单过滤的 SQL。
            decl = ", ".join(f'"{c}" TEXT' for c in col_names)
            con.execute(f'CREATE TABLE eflow_tt ({decl})')
            ph = ", ".join("?" for _ in col_names)
            con.executemany(f'INSERT INTO eflow_tt VALUES ({ph})', row_tuples)
            con.commit()
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("[TTAlert] 建快照失败，退回镜像库: %s (%s)", tt_no, e)
        return None
    return tmp


def _cleanup_snapshot(path: Optional[Path]) -> None:
    """删除临时快照（连同它所在的临时目录）。"""
    if not path:
        return
    try:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    except Exception:  # noqa: BLE001
        pass


def render_tt_analysis(tt_no: str, lang: str = "en") -> Optional[str]:
    """调分析引擎渲染一条 TT 的完整消息（头部 + 里程碑 + 派单依据 + 时效）。

    成功返回消息文本（已去除尾部空白），失败返回 `None` 并记日志 ——
    由调用方决定降级策略。**不抛异常**：单条分析失败不该中断整轮告警。

    要看失败**原因**（用于把降级暴露到任务结果里），用 `render_with_reason`。
    """
    return render_with_reason(tt_no, lang)[0]


def render_with_reason(tt_no: str, lang: str = "en",
                       row: Optional[dict] = None) -> "tuple[Optional[str], str]":
    """同 `render_tt_analysis`，但把失败原因一并返回：`(文本或None, 原因)`。

    **为什么要返回原因**：降级是静默的 —— 消息从 30 行缩成 7 行，群里的人只会
    觉得「这次信息怎么这么少」，不会知道是引擎超时了。把原因带回任务结果，
    运维才能在页面上看到「本轮 3 单降级：引擎超时」并去查磁盘 IO，
    而不是等用户来问为什么消息变短了。

    `row` 不为空时快照直接用它（见 `_snapshot_tt`），不再查本地库。
    """
    tt_no = (tt_no or "").strip()
    if not tt_no:
        return None, "单号为空"

    script = engine_path()
    if not script.is_file():
        logger.warning("[TTAlert] 分析引擎不存在，降级到内置模板: %s", script)
        return None, f"引擎脚本不存在：{script}"

    # 先造一份「这一单」的新鲜快照 —— 引擎读的镜像库每小时才刷新一次，
    # 直接跑它对刚发生的单必然查不到（见 _snapshot_tt 的注释与实测数据）。
    # 调用方已备好行（实时/镜像）时直接用，省一次查库。
    snapshot = _snapshot_tt(tt_no, row=row)
    try:
        return _run_engine(script, tt_no, lang, snapshot)
    finally:
        _cleanup_snapshot(snapshot)


def _run_engine(script: Path, tt_no: str, lang: str,
                db_override: Optional[Path]) -> "tuple[Optional[str], str]":
    """跑引擎并解析结果。`db_override` 为空时用引擎自带的镜像库。"""
    try:
        proc = subprocess.run(
            [sys.executable, str(script), tt_no, "--lang", lang],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            cwd=str(script.parent),
            env=_engine_env(db_override),
        )
    except subprocess.TimeoutExpired:
        # 实测这条最常发生，且几乎总是磁盘 IO 竞争（读 1.5G 的 app.db + 两张 xlsx），
        # 不是引擎本身慢 —— 正常 0.3s，忙时可能几十秒。故原因里点明「可能磁盘忙」。
        logger.warning("[TTAlert] 分析引擎超时（%ss）: %s", TIMEOUT_SECONDS, tt_no)
        return None, f"引擎超时（>{TIMEOUT_SECONDS}s，可能是磁盘 IO 繁忙）"
    except Exception as e:  # noqa: BLE001
        logger.warning("[TTAlert] 分析引擎调用失败: %s", tt_no, exc_info=True)
        return None, f"引擎调用失败：{type(e).__name__}: {e}"

    text = (proc.stdout or "").strip()
    # 引擎用退出码表达「没找到这一单」（tt-analyze.py:2171 的 `0 if found else 1`）。
    # 故**必须同时**看退出码与 stdout：只看 stdout 非空会把错误提示当成消息发出去，
    # 只看退出码会丢掉「找到了但渲染非空」的正常情况。
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()[:200]
        logger.warning("[TTAlert] 分析引擎退出码 %s（%s）: %s",
                       proc.returncode, tt_no, err)
        return None, f"引擎退出码 {proc.returncode}" + (f"：{err}" if err else "")
    if not text:
        logger.warning("[TTAlert] 分析引擎无输出: %s", tt_no)
        return None, "引擎无输出"
    return text, ""

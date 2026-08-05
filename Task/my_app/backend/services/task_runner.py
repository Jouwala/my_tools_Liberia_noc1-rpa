"""
通用任务调度管理框架
支持：注册任务、自定义调度频率、立即执行、查看历史状态
可扩展：新增任务只需调用 register_task() 即可
"""
import time
import logging
import threading
import sqlite3
import json
import os
import traceback
import ast
import inspect
import importlib.util
import textwrap
import types
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from backend.database import get_raw_connection

logger = logging.getLogger("task_runner")

# 微信失败通知（OpenClaw 通道）。导入失败则降级为 no-op，不影响任务调度。
try:
    from .weixin_notifier import notify_task_failure
except Exception:  # noqa: BLE001
    def notify_task_failure(task_id, task_name, error, traceback_text=None):  # type: ignore
        logger.warning(f"weixin_notifier 不可用，跳过失败通知 ({task_id})")

# 路径配置
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BACKEND_DIR / "db" / "app.db"

# ========== 任务注册表 ==========
_task_registry: dict[str, dict] = {}
_task_history: list[dict] = []
MAX_HISTORY = 50
_lock = threading.Lock()

# 任务执行中状态（供前端轮询展示"运行中"）
_active_runs: dict[str, dict] = {}
_active_lock = threading.Lock()

# 全局调度器
_scheduler: Optional[BackgroundScheduler] = None


def get_scheduler() -> BackgroundScheduler:
    """获取或创建全局调度器"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


# ========== 任务注册 ==========
def _init_schedule_table():
    """初始化调度配置表"""
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS task_schedule_config (
                task_id TEXT PRIMARY KEY,
                cron TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
        """)
            # 兼容旧表：仅在 enabled 列不存在时才添加（幂等迁移，避免重复加列抛异常）
            cols = [r[1] for r in conn.execute("PRAGMA table_info(task_schedule_config)").fetchall()]
            if "enabled" not in cols:
                conn.execute("ALTER TABLE task_schedule_config ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
            conn.commit()
            conn.close()
    except Exception as e:
        logger.warning(f"初始化调度配置表失败: {e}")


def _load_schedule_config(task_id: str) -> tuple:
    """从数据库加载用户自定义的调度配置和启用状态"""
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            row = conn.execute(
                "SELECT cron, enabled FROM task_schedule_config WHERE task_id = ?",
                (task_id,)
            ).fetchone()
            conn.close()
            return (row[0], bool(row[1])) if row else (None, None)
    except Exception as e:
        logger.warning(f"加载调度配置失败 ({task_id}): {e}")
        return (None, None)


def _save_schedule_config(task_id: str, cron: str, enabled: bool = None):
    """保存用户自定义的调度配置到数据库"""
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            if enabled is not None:
                conn.execute("""
                INSERT OR REPLACE INTO task_schedule_config (task_id, cron, enabled, updated_at)
                VALUES (?, ?, ?, ?)
            """, (task_id, cron, 1 if enabled else 0, datetime.now().isoformat()))
            else:
                conn.execute("""
                INSERT OR REPLACE INTO task_schedule_config (task_id, cron, enabled, updated_at)
                VALUES (?, ?, COALESCE((SELECT enabled FROM task_schedule_config WHERE task_id = ?), 1), ?)
            """, (task_id, cron, task_id, datetime.now().isoformat()))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.warning(f"保存调度配置失败 ({task_id}): {e}")


_BUILTINS = {
    "print", "len", "dict", "list", "str", "int", "float", "bool", "set",
    "tuple", "range", "enumerate", "zip", "sorted", "reversed", "isinstance",
    "format", "getattr", "setattr", "hasattr", "delattr", "super", "open",
    "min", "max", "sum", "any", "all", "map", "filter", "type", "vars",
    "repr", "abs", "round", "divmod", "pow", "id", "hash", "slice", "object",
    "Exception", "ValueError", "TypeError", "KeyError", "RuntimeError",
    "TimeoutError", "OSError", "IOError", "json", "time", "logger", "logging",
    "os", "sqlite3", "threading", "Path",
    # 常见 stdlib 构造/工具，出现在调用链里只是噪声
    "ThreadPoolExecutor", "ProcessPoolExecutor", "as_completed", "datetime",
    "timedelta", "defaultdict", "Decimal", "BytesIO", "StringIO", "deepcopy",
}

_METHOD_NOISE = {
    "info", "error", "warning", "debug", "critical", "getLogger", "get",
    "post", "put", "delete", "head", "run", "execute", "append", "extend",
    "add", "update", "pop", "keys", "values", "items", "setattr", "getattr",
    "format", "join", "split", "strip", "replace", "upper", "lower",
    "startswith", "endswith", "find", "index", "copy", "close", "commit",
    "rollback", "fetchall", "fetchone", "execute",
    # 线程池 / 通用方法噪声
    "submit", "result", "cancel", "done", "shutdown", "wait", "sleep",
    "dumps", "loads", "read", "write", "seek", "flush", "sort", "insert",
}


# 调用链最大递归深度（环境变量可配，默认 2）
CALL_CHAIN_DEPTH = int(os.getenv("CALL_CHAIN_DEPTH", "2"))


# 源码 AST 缓存：{绝对文件路径: ast.Module | None}，注册期一次性解析，避免重复读盘
_AST_CACHE: dict[str, object] = {}


def _rel(path: str) -> str:
    """绝对路径 → 相对 my_app 的短路径（避免前端暴露完整磁盘路径）。"""
    try:
        return os.path.relpath(path, BACKEND_DIR).replace("\\", "/")
    except ValueError:
        # 跨盘符路径（如 C: vs D:）无法求相对路径，回退到文件名即可
        return os.path.basename(path)


def _module_file(modname: str) -> str | None:
    """不导入模块，仅用 find_spec 拿到 .py 源文件路径（零副作用）。"""
    if not modname:
        return None
    try:
        spec = importlib.util.find_spec(modname)
    except ModuleNotFoundError:
        # 模块不存在是 find_spec 的正常"未找到"契约，无需告警
        return None
    except Exception:  # noqa: BLE001 - 其他导入系统异常（命名空间包解析失败等）
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _module_file: exception swallowed", exc_info=True)
        return None
    origin = getattr(spec, "origin", None)
    return origin if origin and origin.endswith(".py") else None


def _parse_file(path: str):
    """解析并缓存文件 AST，失败返回 None。"""
    if path in _AST_CACHE:
        return _AST_CACHE[path]
    tree = None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            tree = ast.parse(f.read())
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _parse_file: exception swallowed", exc_info=True)
        tree = None
    _AST_CACHE[path] = tree
    return tree


def _find_funcdef(tree, name: str):
    """在文件 AST 中找到同名函数定义节点（含类方法 / 嵌套）。"""
    if tree is None:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _locate(func) -> str:
    """返回 callable 的 '相对文件:行号'，解析不到返回空。"""
    try:
        srcfile = inspect.getsourcefile(func)
        _, lineno = inspect.getsourcelines(func)
        if srcfile:
            return f"{_rel(srcfile)}:{lineno}"
    except (OSError, TypeError):
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _locate: exception swallowed", exc_info=True)
        pass
    return ""


def _import_map(node) -> dict:
    """收集函数体内的 `from X import Y [as Z]`（任务入口普遍用延迟导入），
    返回 {本地名: (模块名, 原始名)}，用于在不导入的前提下定位目标源码。"""
    out = {}
    try:
        for n in ast.walk(node):
            if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                for a in n.names:
                    out[a.asname or a.name] = (n.module, a.name)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _import_map: exception swallowed", exc_info=True)
        pass
    return out


def _calls_in(node, skip_names: set) -> list:
    """从 AST 节点收集被调用的函数名（去内置 / 去方法噪声 / 去自身）。"""
    raw = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        fn = n.func
        if isinstance(fn, ast.Attribute):
            name = fn.attr
            if name in _METHOD_NOISE:
                continue
        elif isinstance(fn, ast.Name):
            name = fn.id
        else:
            continue
        if name in _BUILTINS or name.startswith("__") or name in skip_names:
            continue
        if name not in raw:
            raw.append(name)
    return raw


def _chain_from_file(modname: str, funcname: str, depth: int) -> list:
    """纯静态：从源文件 AST 展开某函数的下游调用（不导入模块）。"""
    path = _module_file(modname)
    if not path:
        return []
    tree = _parse_file(path)
    fdef = _find_funcdef(tree, funcname)
    if fdef is None:
        return []
    imports = _import_map(fdef)
    # 该模块顶层的 from-import 也算（服务模块通常在文件头部导入）
    if tree is not None:
        imports.update(_import_map_toplevel(tree))
    out = []
    for name in _calls_in(fdef, {funcname}):
        loc = ""
        sub_mod = None
        if name in imports:
            sub_mod, orig = imports[name]
            sub_path = _module_file(sub_mod)
            sub_def = _find_funcdef(_parse_file(sub_path), orig) if sub_path else None
            if sub_def is not None:
                loc = f"{_rel(sub_path)}:{sub_def.lineno}"
        else:
            same_def = _find_funcdef(tree, name)
            if same_def is not None:
                loc = f"{_rel(path)}:{same_def.lineno}"
                sub_mod = modname
        out.append(f"{name} ({loc})" if loc else name)
        if depth > 1 and sub_mod:
            target_name = imports.get(name, (None, name))[1]
            for sub in _chain_from_file(sub_mod, target_name, depth - 1):
                out.append(f"  → {sub}")
    return out


def _import_map_toplevel(tree) -> dict:
    """模块顶层的 from-import 映射。"""
    out = {}
    for n in getattr(tree, "body", []):
        if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            for a in n.names:
                out.setdefault(a.asname or a.name, (n.module, a.name))
    return out


def _auto_call_chain(func, _depth=0, _seen=None):
    """静态分析 func 的调用链，供前端 hover 展示（零副作用，不导入任何模块）。

    解析顺序：
      1) 源码 AST（dedent 后可解析嵌套 def）→ 收集调用名 + 函数体内的延迟导入表
      2) 目标解析：模块 globals 里的真实对象 → inspect 定位；
         否则用 `from X import Y` + importlib.find_spec 拿源文件，AST 找行号
      3) 递归展开 CALL_CHAIN_DEPTH-1 层（子项带 '  → ' 缩进）
    源码不可得时退回字节码 co_names。
    """
    if _seen is None:
        _seen = set()
    qual = f"{getattr(func, '__module__', '')}.{getattr(func, '__qualname__', '')}"
    if qual in _seen or _depth >= CALL_CHAIN_DEPTH:
        return []
    _seen.add(qual)

    mod = inspect.getmodule(func)
    mod_globals = getattr(mod, "__dict__", {}) if mod else {}

    raw: list = []
    imports: dict = {}
    try:
        # dedent：嵌套 def 的源码带缩进，不 dedent 会 IndentationError 直接退化到字节码兜底
        src = textwrap.dedent(inspect.getsource(func))
        tree = ast.parse(src)
        self_name = getattr(func, "__name__", "")
        imports = _import_map(tree)
        raw = _calls_in(tree, {self_name})
    except (OSError, TypeError, SyntaxError):
        # 兜底：源码不可得时，用字节码引用的全局名
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _auto_call_chain: exception swallowed", exc_info=True)
        for name in getattr(getattr(func, "__code__", None), "co_names", ()):
            if "." in name:  # 过滤 import from 产生的完整模块路径
                continue
            if name in _BUILTINS or name.startswith("__") or name in _METHOD_NOISE:
                continue
            if isinstance(mod_globals.get(name), types.ModuleType):
                continue
            raw.append(name)

    out = []
    for name in raw:
        if any(n.split(" (")[0] == name for n in out):
            continue
        target = mod_globals.get(name)
        loc = _locate(target) if callable(target) else ""
        sub_mod = sub_name = None
        if not loc and name in imports:
            # 延迟导入：不导入模块，直接用源文件 AST 定位
            sub_mod, sub_name = imports[name]
            sub_path = _module_file(sub_mod)
            sub_def = _find_funcdef(_parse_file(sub_path), sub_name) if sub_path else None
            if sub_def is not None:
                loc = f"{_rel(sub_path)}:{sub_def.lineno}"
        out.append(f"{name} ({loc})" if loc else name)

        if _depth >= CALL_CHAIN_DEPTH - 1:
            continue
        try:
            if callable(target) and getattr(target, "__module__", None) == getattr(mod, "__name__", None):
                for sub in _auto_call_chain(target, _depth + 1, _seen):
                    out.append(f"  → {sub}")
            elif sub_mod and sub_name:
                for sub in _chain_from_file(sub_mod, sub_name, CALL_CHAIN_DEPTH - _depth - 1):
                    out.append(f"  → {sub}")
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _auto_call_chain: exception swallowed", exc_info=True)
            pass
    return out[:15]


# ========== 调用链节点 IO 资源映射（数据库 / 文件） ==========
# 维护用途：在 Task Manager 的脚本调用链（Call Chain）中，为每个节点标注其
# 设计上访问的数据库或文件，方便日常维护与问题排查。
#
# - TASK_IO: 以 task_id 为键，标注该任务「入口节点」访问的核心 DB / 文件。
#   懒加载任务（_lazy_loader 包装）的调用链只有入口节点，因此入口标注即可覆盖。
# - CALL_CHAIN_IO: 以函数名为键，标注被调用链展开到的「共享子函数」访问的资源
#   （如 eflow / 告警 / ms_sla / ipran 等任务展开后的子节点）。
#
# 新增 / 调整任务时，只需在此两处补充对应条目，无需改动前端与调度逻辑。

TASK_IO: dict[str, list[str]] = {
    # 1-2. eFlow 同步
    "eflow_sync": ["DB: app.db (db/app.db, 主)", "DB: eflow.sqlite3 (data/eflow/, 报告生成副产品)", "API: eFlow (10.100.20.8)", "远程DB: db.sqlite3 (via db_writer API, Eflow_TT_FB/Eflow_WO_FB)", "远程FTP: tt_reports 上传 (FTP_REMOTE_DIR, 默认 /Python)"],
    "eflow_sync_full": ["DB: app.db (db/app.db, 主)", "DB: eflow.sqlite3 (data/eflow/, 报告生成副产品)", "API: eFlow (10.100.20.8)", "远程DB: db.sqlite3 (via db_writer API, Eflow_TT_FB/Eflow_WO_FB)", "远程FTP: tt_reports 上传 (FTP_REMOTE_DIR, 默认 /Python)"],
    # 3. RAN UME 日报
    "ran_ume_daily": ["远程DB: ran_kpi_daily_202606.sqlite3 (DB Orange, via API)", "本地DB: ran_kpi_daily.sqlite3 (Availability 读)", "远程FTP: /01_RPA/LBR_Tools/KPI/RAN/ORANGE"],
    # 4. Site Outage 截图
    "site_outage_screenshot": ["本地文件: data/site_outage/*.png (截图)"],
    # 5. WhatsApp 发送
    "whatsapp_send": ["本地文件: data/site_outage/*.png + 报告", "WhatsApp Web (发送)"],
    # 6. MS SLA 完整同步
    "ms_sla_full": ["DB: lbr_ms_sla_kpi.sqlite3", "远程DB: lbr_ms_sla_kpi.sqlite3 (via db_writer API)", "本地文件: data/ms_sla/*.xlsx (报表，供 kpi_ms 邮件读取)", "远程FTP: /01_RPA/LBR_Tools/KPI/MS_SLA"],
    # 7-8. eFlow 告警
    "eflow_active_alarm": ["DB: app.db (realtime_alarm 表)", "DB: eflow.sqlite3 (realtime_alarm 表)"],
    "eflow_history_alarm": ["DB: eflow.sqlite3 (history_alarm 表)", "DB: app.db (history_alarm 表)"],
    # 9. RAN Main KPI
    "main_kpi_sync": ["远程DB: db.sqlite3 (via db_writer API)"],
    # 10. RAN Network KPI
    "network_kpi_sync": ["本地DB: ran_kpi_daily.sqlite3", "远程DB: ran_kpi_daily.sqlite3 (via db_writer API)"],
    # 11. CNN UME KPI
    "cnn_kpi_sync": ["远程DB: db_ps_cs_cn.sqlite3 (CNN, via API)"],
    # 12. SP 备件
    "sp_data_sync": ["DB: app.db (db/app.db)", "SFTP: 10.100.20.11 (备件报表)"],
    # 13. iPRAN UME KPI
    "ipran_kpi_sync": ["本地DB: ipran_ume_kpi.sqlite3", "远程DB: ipran_ume_kpi.sqlite3 (via db_writer API)"],
    # 14-15. Liberia 邮件
    "liberia_email_1h": ["本地文件: data/eflow/tt_reports/*.xlsx", "OWA 邮件发送"],
    "liberia_email_8h": ["本地文件: data/eflow/tt_reports/*.xlsx", "OWA 邮件发送"],
    # 16-17. MS KPI 邮件
    "kpi_ms_contract": ["本地文件: data/ms_sla/*.xlsx (源自 lbr_ms_sla_kpi.sqlite3, 由 ms_sla_full 生成)", "远程FTP: /01_RPA/LBR_Tools/KPI/MS_SLA/email (名单)"],
    "kpi_ms_wo_sla": ["本地文件: data/ms_sla/*.xlsx (源自 lbr_ms_sla_kpi.sqlite3, 由 ms_sla_full 生成)", "远程FTP: /01_RPA/LBR_Tools/KPI/MS_SLA/email (名单)"],
    # 18-19. SP 报表邮件
    "kpi_sp_spareparts": ["远程FTP: /01_RPA/LBR_Tools/SP/sp_report (数据+名单)"],
    "kpi_sp_consumables": ["远程FTP: /01_RPA/LBR_Tools/SP/sp_report (数据+名单)"],
    # 20. RAN Availability 邮件
    "kpi_ran_availability": ["远程FTP: /01_RPA/LBR_Tools/KPI/RAN/ORANGE (图片+名单)"],
    # 21. 邮件补发
    "email_recovery": ["DB: app.db (失败邮件任务记录)"],
    # 22. Packet Loss
    "packet_loss_sync": ["本地DB: lte_pl.sqlite3 (data/packet_lost/)", "DB: eflow.sqlite3 (site 表)", "本地文件: Packet_Loss_Status_Report.xlsx"],
    # 23. IP RAN M6K-FW 图表邮件
    "ipran_m6k_chart_email": ["远程DB: ipran_ume_kpi.sqlite3 (via remote API, 本地为降级)", "本地文件: TMP/ipran_charts/*.png (图表)", "邮件发送"],
    # 24. CNN Free Rating 图表邮件
    "ccn_free_rating_chart_email": ["远程DB: db_ps_cs_cn.sqlite3 (via API)", "本地文件: TMP/ccn_free_rating_charts/*.png (图表)", "邮件发送"],
    # 25. FW 吞吐 KPI
    "fw_kpi_sync": ["远程DB: fw_db.sqlite (via API)", "本地文件: TMP/fw_charts + email_reports", "邮件发送"],
}

# 共享子函数 -> 资源（被调用链展开到的函数）
CALL_CHAIN_IO: dict[str, list[str]] = {
    "sync_from_eflow_api": ["DB: app.db + eflow.sqlite3 (报告副产品)", "API: eFlow", "远程DB: db.sqlite3 (db_writer API, Eflow_TT_FB/Eflow_WO_FB)", "远程FTP: tt_reports 上传"],
    "fetch_and_save_active_alarm": ["DB: app.db (realtime_alarm 表)", "DB: eflow.sqlite3 (realtime_alarm 表)"],
    "fetch_and_save_history_alarm": ["DB: eflow.sqlite3 (history_alarm 表)", "DB: app.db (history_alarm 表)"],
    "run_full_sync": ["DB: lbr_ms_sla_kpi.sqlite3", "远程DB: lbr_ms_sla_kpi.sqlite3 (db_writer API)", "远程FTP: /01_RPA/LBR_Tools/KPI/MS_SLA"],
    "run_ipran_kpi_sync": ["本地DB: ipran_ume_kpi.sqlite3", "远程DB: ipran_ume_kpi.sqlite3 (db_writer API)"],
    "run_packet_loss_sync": ["本地DB: lte_pl.sqlite3", "DB: eflow.sqlite3 (site 表)"],
    "run_cnn_kpi_sync": ["远程DB: db_ps_cs_cn.sqlite3 (CNN, via API)"],
    "run_main_kpi_sync": ["远程DB: db.sqlite3 (via db_writer API)"],
    "run_network_kpi_sync": ["本地DB: ran_kpi_daily.sqlite3", "远程DB: ran_kpi_daily.sqlite3 (via db_writer API)"],
    "run_ran_ume_full_task": ["远程DB: ran_kpi_daily_202606.sqlite3 (via API)", "远程FTP: /01_RPA/LBR_Tools/KPI/RAN/ORANGE"],
}


def _call_chain_node_name(node: str) -> str:
    """从调用链节点字符串中解析出函数名（去掉 '  → ' 缩进与 ' (file:line)' 位置）。"""
    s = node
    if s.startswith("  → "):
        s = s[4:]
    elif s.startswith("→ "):
        s = s[2:]
    return s.split(" (")[0].strip()


def _annotate_call_chain(chain: list, task_id: str) -> list:
    """为调用链每个节点追加其设计访问的数据库/文件标注。

    - 入口节点（index 0）取自 TASK_IO[task_id]
    - 其余节点若命中 CALL_CHAIN_IO[函数名] 则追加
    资源按「规范化主键」（去掉括号说明、转小写）去重，保留更具体的那条，
    避免同义条目重复；最终以内联形式附加到节点字符串末尾，前端无需改动即可展示。
    """
    def _norm_key(s: str) -> str:
        return s.split(" (")[0].strip().lower()

    annotated = []
    task_io = TASK_IO.get(task_id, [])
    for idx, node in enumerate(chain):
        name = _call_chain_node_name(node)
        res: list[str] = []
        if idx == 0 and task_io:
            res.extend(task_io)
        if name in CALL_CHAIN_IO:
            res.extend(CALL_CHAIN_IO[name])
        # 按规范化主键去重，保留更具体（更长）的那条
        best: dict[str, str] = {}
        order: list[str] = []
        for r in res:
            k = _norm_key(r)
            if k not in best or len(r) > len(best[k]):
                if k not in best:
                    order.append(k)
                best[k] = r
        uniq = [best[k] for k in order]
        if uniq:
            annotated.append(f"{node}  ⟵ [{' ; '.join(uniq)}]")
        else:
            annotated.append(node)
    return annotated


def register_task(
    task_id: str,
    name: str,
    func: Callable,
    description: str = "",
    default_cron: str = "0 2 * * *",   # 默认每天凌晨2点
    category: str = "general",
    enabled: bool = True,
    name_en: str = "",
    description_en: str = "",
    call_chain: list | None = None,
):
    """
    注册一个可调度的任务。

    Args:
        task_id: 唯一标识符
        name: 显示名称（中文）
        name_en: 显示名称（英文，留空则回退到 name）
        func: 执行函数，返回 dict 或 str
        description: 任务描述（中文）
        description_en: 任务描述（英文，留空则回退到 description）
        default_cron: 默认 cron 表达式 (分 时 日 月 周)
        category: 分类 (eflow / ran_ume / whatsapp / site_outage / general)
        enabled: 是否启用
    """
    # 尝试加载用户自定义的调度配置
    saved_cron, saved_enabled = _load_schedule_config(task_id)
    current_cron = saved_cron if saved_cron else default_cron
    final_enabled = saved_enabled if saved_enabled is not None else enabled

    _task_registry[task_id] = {
        "task_id": task_id,
        "name": name,
        "name_en": name_en or name,
        "func": func,
        "description": description,
        "description_en": description_en or description,
        "default_cron": default_cron,
        "current_cron": current_cron,
        "category": category,
        "enabled": final_enabled,
        "registered_at": datetime.now().isoformat(),
        "call_chain": _annotate_call_chain(call_chain, task_id) if call_chain is not None else _annotate_call_chain(_auto_call_chain(func), task_id),
    }
    logger.info(f"任务已注册: {task_id} ({name}), cron={current_cron}")


def _localize(task: dict, lang: str) -> tuple:
    """根据 lang 返回 (显示名, 显示描述)；非法值回退中文。"""
    if lang == "en":
        return task.get("name_en") or task.get("name"), task.get("description_en") or task.get("description")
    return task.get("name"), task.get("description")


def unregister_task(task_id: str):
    """注销任务"""
    if task_id in _task_registry:
        # 移除调度
        sched = get_scheduler()
        job_id = f"task_{task_id}"
        if sched.get_job(job_id):
            sched.remove_job(job_id)
        del _task_registry[task_id]
        logger.info(f"任务已注销: {task_id}")


# ========== 任务执行 ==========
def run_task(task_id: str, trigger: str = "manual") -> dict:
    """
    立即执行指定任务。

    Args:
        task_id: 任务ID
        trigger: 触发方式 (manual / scheduled)

    Returns:
        执行结果 dict
    """
    task = _task_registry.get(task_id)
    if not task:
        return {"success": False, "error": f"任务 {task_id} 未找到"}

    if not task["enabled"]:
        return {"success": False, "error": f"任务 {task_id} 已禁用"}

    logger.info("任务开始执行", extra={"task_id": task_id, "event": "task_start", "trigger": trigger})
    start_time = time.time()

    result = {
        "task_id": task_id,
        "task_name": task["name"],
        "category": task["category"],
        "trigger": trigger,
        "success": False,
        "started_at": datetime.now().isoformat(),
        "elapsed_seconds": 0,
        "result": None,
        "error": None,
        "error_trace": None,
    }

    try:
        func_result = task["func"]()
        if isinstance(func_result, dict):
            result["success"] = func_result.get("success", True)
            result["result"] = func_result
            # 业务失败：任务函数返回 {"success": False, ...} 但未抛异常时，
            # 把其中的 error/message 摘出来，否则页面只显示“失败”却无任何错误信息。
            if not result["success"] and not result.get("error"):
                biz_msg = func_result.get("error") or func_result.get("message")
                if biz_msg:
                    result["error"] = str(biz_msg)
        else:
            result["success"] = True
            result["result"] = {"message": str(func_result)}
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        result["error_trace"] = traceback.format_exc()
        logger.error("任务执行失败", extra={"task_id": task_id, "event": "task_fail", "error": str(e)})
    except BaseException as e:
        # 捕获 SystemExit / KeyboardInterrupt 等被强行中断的情况
        # （例如 WorkBuddy safe-delete 守卫在 os.remove 时 raise SystemExit）。
        # 必须记录执行历史，否则会出现“任务执行了但历史为空”。
        result["success"] = False
        result["error"] = f"{type(e).__name__}: {e}"
        result["error_trace"] = traceback.format_exc()
        logger.error("任务被强行中断", extra={"task_id": task_id, "event": "task_interrupt", "error_type": type(e).__name__})

    elapsed = time.time() - start_time
    result["elapsed_seconds"] = round(elapsed, 2)
    result["completed_at"] = datetime.now().isoformat()

    # 记录历史
    with _lock:
        _task_history.append(result)
        while len(_task_history) > MAX_HISTORY:
            _task_history.pop(0)

    # 持久化到数据库
    _save_task_result(result)

    # 任务失败时推送微信通知（OpenClaw 通道）。通知失败不影响任务结果记录。
    if not result["success"]:
        try:
            notify_task_failure(
                task_id, task["name"],
                result.get("error") or "未知错误",
                result.get("error_trace"),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{task_id}] 微信失败通知异常: {e}")

    logger.info("任务执行完成", extra={"task_id": task_id, "event": "task_done", "success": result["success"], "elapsed": round(elapsed, 2)})
    return result


# ========== 异步执行 & 运行状态跟踪 ==========
def _execute_task(task_id: str, trigger: str):
    """在后台线程中执行任务，并维护 running 状态（供前端轮询）。"""
    with _active_lock:
        _active_runs[task_id] = {"started_at": datetime.now().isoformat()}
    try:
        run_task(task_id, trigger)
    finally:
        with _active_lock:
            _active_runs.pop(task_id, None)


def _scheduled_run(task_id: str, trigger: str = "scheduled"):
    """调度器回调：复用 _execute_task 以便跟踪运行状态。

    单飞保护（single-flight）：若同一任务的上一轮调度仍在运行
    （例如任务耗时超过其调度间隔，或 UME 单账号单会话被并发互踢导致变慢），
    则跳过本次触发，避免起第二个实例造成资源争用 / 401 互踢。
    手动触发路径（run_task_async）已有相同保护，这里补齐调度路径。
    """
    with _active_lock:
        if task_id in _active_runs:
            logger.warning(
                f"[{task_id}] 跳过本次调度触发：上一轮执行仍在运行中（单飞保护）"
            )
            return
    _execute_task(task_id, trigger)


def run_task_async(task_id: str, trigger: str = "manual") -> dict:
    """
    立即执行任务（后台线程，立即返回）。
    返回 {accepted, running}；若已在运行或校验失败则返回错误。
    """
    task = _task_registry.get(task_id)
    if not task:
        return {"success": False, "accepted": False, "error": f"任务 {task_id} 未找到"}
    if not task["enabled"]:
        return {"success": False, "accepted": False, "error": f"任务 {task_id} 已禁用"}
    with _active_lock:
        if task_id in _active_runs:
            return {"accepted": False, "running": True, "error": "任务正在运行中"}
    threading.Thread(target=_execute_task, args=(task_id, trigger), daemon=True).start()
    return {"accepted": True, "running": True, "task_id": task_id,
            "started_at": datetime.now().isoformat()}


def is_task_running(task_id: str) -> bool:
    with _active_lock:
        return task_id in _active_runs


def get_active_runs() -> dict:
    with _active_lock:
        return dict(_active_runs)


def _ensure_task_log_table(conn):
    """确保 task_execution_log 表存在且含 error_trace 列。

    兼容旧库：旧表在 CREATE TABLE IF NOT EXISTS 时已存在但缺 error_trace 列，
    该语句不会自动加列，需通过 PRAGMA 检查后 ALTER 补列，否则查询报错
    'no such column: error_trace'。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_execution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            task_name TEXT,
            category TEXT,
            trigger_type TEXT,
            success INTEGER,
            started_at TEXT,
            completed_at TEXT,
            elapsed_seconds REAL,
            result_json TEXT,
            error TEXT,
            error_trace TEXT
        )
    """)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(task_execution_log)").fetchall()}
        if "error_trace" not in cols:
            conn.execute("ALTER TABLE task_execution_log ADD COLUMN error_trace TEXT")
            conn.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"确保 error_trace 列失败: {e}")


def _save_task_result(result: dict):
    """将任务执行结果保存到 app.db"""
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            conn.execute("""
            INSERT INTO task_execution_log
            (task_id, task_name, category, trigger_type, success, started_at, completed_at, elapsed_seconds, result_json, error, error_trace)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
                result["task_id"],
                result.get("task_name"),
                result.get("category"),
                result.get("trigger"),
                1 if result["success"] else 0,
                result.get("started_at"),
                result.get("completed_at"),
                result.get("elapsed_seconds"),
                json.dumps(result.get("result"), ensure_ascii=False, default=str) if result.get("result") else None,
                result.get("error"),
                result.get("error_trace"),
            ))
            # 清理超过保留期的旧日志（默认 3 天，可用环境变量 TASK_LOG_RETENTION_DAYS 调整）。
            # 注意：之前此处写死 -1 days（与“3天”注释不符），每日任务的失败记录一天后即被清掉，
            # 导致隔天查看时已无失败信息。改为可配置，默认 3 天。
            try:
                _retention_days = max(1, int(os.environ.get("TASK_LOG_RETENTION_DAYS", "3")))
            except (TypeError, ValueError):
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _save_task_result: exception swallowed", exc_info=True)
                _retention_days = 3
            conn.execute(
                f"DELETE FROM task_execution_log WHERE started_at < datetime('now', '-{_retention_days} days')"
            )
            conn.commit()
            conn.close()
    except Exception as e:
        logger.warning(f"保存任务日志失败: {e}")


# ========== 调度管理 ==========
def schedule_task(task_id: str, cron_expr: str = None):
    """
    将任务加入调度器。

    Args:
        task_id: 任务ID
        cron_expr: cron 表达式，为空则使用默认
    """
    task = _task_registry.get(task_id)
    if not task:
        raise ValueError(f"任务 {task_id} 未找到")

    cron = cron_expr or task["current_cron"] or task["default_cron"]
    parts = cron.strip().split()
    if len(parts) != 5:
        raise ValueError(f"无效的 cron 表达式: {cron}")

    minute, hour, day, month, day_of_week = parts
    trigger = CronTrigger(
        minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week
    )

    sched = get_scheduler()
    job_id = f"task_{task_id}"

    # 移除旧任务
    if sched.get_job(job_id):
        sched.remove_job(job_id)

    sched.add_job(
        _scheduled_run,
        trigger=trigger,
        args=[task_id, "scheduled"],
        id=job_id,
        replace_existing=True,
    )

    task["current_cron"] = cron
    logger.info(f"[{task_id}] 已调度: {cron}")


def schedule_all_tasks():
    """将所有已注册且启用的任务加入调度"""
    for task_id, task in _task_registry.items():
        if task["enabled"]:
            try:
                schedule_task(task_id)
            except Exception as e:
                logger.error(f"[{task_id}] 调度失败: {e}")


def start_scheduler():
    """启动调度器"""
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        logger.info("任务调度器已启动")


def stop_scheduler():
    """停止调度器"""
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        logger.info("任务调度器已停止")


# ========== 查询接口 ==========
def _fetch_latest_runs() -> dict:
    """
    一次性查出每个任务的最新一条执行记录（单条 SQL + 子查询分组），
    避免前端 list + 逐任务 detail 产生的 N+1 请求。
    返回 {task_id: [run_dict]}（每个任务仅含最新 1 条，足够卡片展示）。
    """
    result: dict = {}
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            rows = conn.execute(
                """            SELECT l.task_id, l.task_name, l.category, l.trigger_type, l.success,
                      l.started_at, l.completed_at, l.elapsed_seconds, l.error, l.error_trace
               FROM task_execution_log l
               INNER JOIN (
                   SELECT task_id, MAX(id) AS max_id
                   FROM task_execution_log
                   GROUP BY task_id
               ) m ON l.task_id = m.task_id AND l.id = m.max_id"""
            ).fetchall()
            for r in rows:
                result[r[0]] = [{
                    "task_id": r[0], "task_name": r[1], "category": r[2],
                    "trigger": r[3], "success": bool(r[4]),
                    "started_at": r[5], "completed_at": r[6],
                    "elapsed_seconds": r[7], "error": r[8], "error_trace": r[9],
                }]
            conn.close()
    except Exception as e:
        logger.warning(f"批量查询最新执行记录失败: {e}")
    return result


def list_tasks(include_runs: bool = False, lang: str = "zh") -> list[dict]:
    """列出所有已注册的任务（include_runs=True 时附带每个任务最新一条执行记录）"""
    sched = get_scheduler()
    latest_runs = _fetch_latest_runs() if include_runs else {}
    tasks = []
    for task_id, task in _task_registry.items():
        job = sched.get_job(f"task_{task_id}")
        disp_name, disp_desc = _localize(task, lang)
        entry = {
            "task_id": task_id,
            "name": disp_name,
            "description": disp_desc,
            "category": task["category"],
            "enabled": task["enabled"],
            "current_cron": task["current_cron"],
            "default_cron": task["default_cron"],
            "next_run": str(job.next_run_time) if job else None,
            "registered_at": task["registered_at"],
            "running": is_task_running(task_id),
            "call_chain": task.get("call_chain", []),
        }
        if include_runs:
            entry["recent_runs"] = latest_runs.get(task_id, [])
        tasks.append(entry)
    return tasks


def get_task_detail(task_id: str, lang: str = "zh") -> Optional[dict]:
    """获取任务详情"""
    task = _task_registry.get(task_id)
    if not task:
        return None

    sched = get_scheduler()
    job = sched.get_job(f"task_{task_id}")
    disp_name, disp_desc = _localize(task, lang)

    detail = {
        "task_id": task_id,
        "name": disp_name,
        "description": disp_desc,
        "category": task["category"],
        "enabled": task["enabled"],
        "current_cron": task["current_cron"],
        "default_cron": task["default_cron"],
        "next_run": str(job.next_run_time) if job else None,
        "registered_at": task["registered_at"],
        "running": is_task_running(task_id),
        "call_chain": task.get("call_chain", []),
    }

    # 从数据库获取最近执行记录
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            rows = conn.execute(
                """            SELECT task_id, task_name, category, trigger_type, success,
                      started_at, completed_at, elapsed_seconds, error, error_trace
               FROM task_execution_log
               WHERE task_id = ?
               ORDER BY started_at DESC LIMIT 10""",
                (task_id,)
            ).fetchall()
            detail["recent_runs"] = [
                {
                    "task_id": r[0], "task_name": r[1], "category": r[2],
                    "trigger": r[3], "success": bool(r[4]),
                    "started_at": r[5], "completed_at": r[6],
                    "elapsed_seconds": r[7], "error": r[8], "error_trace": r[9],
                }
                for r in rows
            ]
            conn.close()
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_task_detail: exception swallowed", exc_info=True)
        detail["recent_runs"] = []

    return detail


def get_task_stats(task_id: str, days: int | None = None) -> dict:
    """统计某任务在保留期内的执行健康度（成功率 / 平均·最大耗时）。"""
    result = {
        "task_id": task_id,
        "total_runs": 0,
        "success_runs": 0,
        "failed_runs": 0,
        "success_rate": None,
        "avg_elapsed": None,
        "max_elapsed": None,
        "first_seen": None,
        "last_seen": None,
    }
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            where = "WHERE task_id = ?"
            params: list = [task_id]
            if days:
                where += " AND started_at >= datetime('now', ?)"
                params.append(f"-{days} days")
            row = conn.execute(
                f"""SELECT COUNT(*), COALESCE(SUM(success),0),
                           AVG(elapsed_seconds), MAX(elapsed_seconds),
                           MIN(started_at), MAX(started_at)
                    FROM task_execution_log {where}""",
                params,
            ).fetchone()
            conn.close()
            if row and row[0]:
                total = row[0]
                succ = row[1]
                result.update({
                    "total_runs": total,
                    "success_runs": succ,
                    "failed_runs": total - succ,
                    "success_rate": round(succ / total, 4) if total else None,
                    "avg_elapsed": round(row[2], 2) if row[2] is not None else None,
                    "max_elapsed": round(row[3], 2) if row[3] is not None else None,
                    "first_seen": row[4],
                    "last_seen": row[5],
                })
    except Exception as e:
        logger.warning(f"统计任务健康度失败 ({task_id}): {e}")
    return result


def get_recent_failures(days: int = 3, limit: int = 200) -> dict:
    """按 error 首行聚类近期失败，便于快速判断是否为同一根因。"""
    clusters: dict[str, dict] = {}
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            rows = conn.execute(
                """SELECT task_id, task_name, error, started_at
               FROM task_execution_log
               WHERE success = 0
                 AND started_at >= datetime('now', ?)
               ORDER BY started_at DESC LIMIT ?""",
                (f"-{days} days", limit),
            ).fetchall()
            conn.close()
            for task_id, task_name, error, started_at in rows:
                key = (error or "未知错误").split("\n")[0][:120]
                c = clusters.get(key)
                if not c:
                    c = {"error_first_line": key, "count": 0, "tasks": {}, "last_seen": None}
                    clusters[key] = c
                c["count"] += 1
                c["tasks"][task_id] = c["tasks"].get(task_id, 0) + 1
                if not c["last_seen"] or (started_at or "") > c["last_seen"]:
                    c["last_seen"] = started_at
    except Exception as e:
        logger.warning(f"聚合失败记录失败: {e}")
    items = sorted(clusters.values(), key=lambda x: x["count"], reverse=True)
    return {"days": days, "total_failures": sum(c["count"] for c in items), "clusters": items}


def get_task_history_by_task(task_id: str, limit: int = 200) -> list[dict]:
    """某任务的执行历史（按时间倒序），供前端历史弹窗分页 / 导出。"""
    rows: list[dict] = []
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            cur = conn.execute(
                "SELECT task_id, task_name, category, trigger_type, success, "
                "started_at, completed_at, elapsed_seconds, error, error_trace "
                "FROM task_execution_log WHERE task_id = ? "
                "ORDER BY started_at DESC LIMIT ?",
                (task_id, limit),
            )
            for r in cur.fetchall():
                rows.append({
                    "task_id": r[0], "task_name": r[1], "category": r[2],
                    "trigger": r[3], "success": bool(r[4]),
                    "started_at": r[5], "completed_at": r[6],
                    "elapsed_seconds": r[7], "error": r[8], "error_trace": r[9],
                })
            conn.close()
    except Exception as e:
        logger.warning(f"查询任务历史失败 ({task_id}): {e}")
    return rows


def get_task_history(limit: int = 20) -> list[dict]:
    """获取最近的任务执行历史"""
    try:
        with get_raw_connection(str(DB_PATH), timeout=30) as conn:
            _ensure_task_log_table(conn)
            rows = conn.execute(
                """            SELECT task_id, task_name, category, trigger_type, success,
                      started_at, completed_at, elapsed_seconds, error, error_trace
               FROM task_execution_log
               ORDER BY started_at DESC LIMIT ?""",
                (limit,)
            ).fetchall()
            conn.close()
            return [
                {
                    "task_id": r[0], "task_name": r[1], "category": r[2],
                    "trigger": r[3], "success": bool(r[4]),
                    "started_at": r[5], "completed_at": r[6],
                    "elapsed_seconds": r[7], "error": r[8], "error_trace": r[9],
                }
                for r in rows
            ]
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_task_history: exception swallowed", exc_info=True)
        return list(reversed(_task_history[-limit:]))


def update_task_schedule(task_id: str, cron_expr: str) -> dict:
    """更新任务的调度频率"""
    task = _task_registry.get(task_id)
    if not task:
        return {"success": False, "error": f"任务 {task_id} 未找到"}

    try:
        schedule_task(task_id, cron_expr)
        # 持久化用户自定义的调度配置
        _save_schedule_config(task_id, cron_expr)
        return {
            "success": True,
            "task_id": task_id,
            "new_cron": cron_expr,
            "message": f"任务 {task['name']} 调度已更新为: {cron_expr}",
        }
    except Exception as e:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] update_task_schedule: exception swallowed", exc_info=True)
        return {"success": False, "error": str(e)}


def toggle_task(task_id: str, enabled: bool) -> dict:
    """启用/禁用任务"""
    task = _task_registry.get(task_id)
    if not task:
        return {"success": False, "error": f"任务 {task_id} 未找到"}

    task["enabled"] = enabled

    # 持久化启用状态
    _save_schedule_config(task_id, task["current_cron"], enabled=enabled)

    sched = get_scheduler()
    job_id = f"task_{task_id}"

    if enabled:
        schedule_task(task_id)
        return {"success": True, "message": f"任务 {task['name']} 已启用"}
    else:
        if sched.get_job(job_id):
            sched.remove_job(job_id)
        return {"success": True, "message": f"任务 {task['name']} 已禁用"}
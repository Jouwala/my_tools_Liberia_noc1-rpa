"""任务调用链静态分析（架构优化 Phase 4，从 task_runner.py 拆出）

职责：注册期对任务入口函数做零副作用 AST 静态分析，生成 Task Manager 前端
展示的调用链（Call Chain），并按 TASK_IO / CALL_CHAIN_IO 标注各节点访问的
数据库/文件资源。

拆分后 task_runner.py 仍反向导入本模块全部公共符号，旧引用零改动。
"""
import os
import re
import ast
import inspect
import importlib.util
import textwrap
import types
import logging
from pathlib import Path

logger = logging.getLogger("task_runner")

# 路径配置（与 task_runner 保持一致：指向 my_app 根目录）
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


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
CALL_CHAIN_DEPTH = int(os.getenv("CALL_CHAIN_DEPTH", "2"))
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
    # 10b-10d. 派生宽表重建（2026-09-21 从已退役 my-finebi 的手工 ETL 收进 my_app，
    #          产物落本机 data/，看板经 dashboard_service.DB_ALIASES 直读）
    "avail_recon_sync": ["远程DB: db.sqlite3 (via remote API, 2G/3G/4G_Main_Kpi_Site_Daily)",
                         "远程DB: olbr_ms_master_database.sqlite3 (via remote API)",
                         "本地DB: data/avail_recon.sqlite3"],
    "mttr_tt_sync": ["远程DB: db.sqlite3 (via remote API, Eflow_TT_FB)",
                     "本地DB: data/excel_ds.sqlite3",
                     "本地DB: data/mttr_tt.sqlite3"],
    "progress_sync": ["远程DB: db.sqlite3 (via remote API, Eflow_TT_FB + Eflow_WO_FB)",
                      "本地DB: data/progress.sqlite3"],
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
    # 19f. Comsumables & SpareParts 报表 WhatsApp 发送
    "sp_whatsapp_report": ["本地文件: data/sp_email/*Comsumables*.xlsx|*.png",
                           "本地文件: data/sp_email/*SpareParts*.xlsx|*.png",
                           "WhatsApp 群: WH&SP Management"],
    # 20. RAN Availability 邮件
    "kpi_ran_availability": ["远程FTP: /01_RPA/LBR_Tools/KPI/RAN/ORANGE (图片+名单)"],
    # 21. 邮件补发
    "email_recovery": ["DB: app.db (失败邮件任务记录)"],
    # 22. Packet Loss
    "packet_loss_sync": ["本地DB: lte_pl.sqlite3 (data/packet_lost/)", "DB: eflow.sqlite3 (site 表)", "本地文件: Packet_Loss_Status_Output Automation <时间戳>.xlsx (data/packet_lost/)"],
    # 23. IP RAN M6K-FW 图表邮件
    "ipran_m6k_chart_email": ["远程DB: ipran_ume_kpi.sqlite3 (via remote API, 本地为降级)", "本地文件: TMP/ipran_charts/*.png (图表)", "邮件发送"],
    # 24. CNN Free Rating 图表邮件
    "ccn_free_rating_chart_email": ["远程DB: db_ps_cs_cn.sqlite3 (via API)", "本地文件: TMP/ccn_free_rating_charts/*.png (图表)", "邮件发送"],
    # 25. FW 吞吐 KPI
    "fw_kpi_sync": ["远程DB: fw_db.sqlite (via API)", "本地文件: TMP/fw_charts + email_reports", "邮件发送"],
    # 26. 电池 KPI（全程内存不落盘：无 Excel/CSV/JSON 导出，无 FTP 上传）
    "battery_kpi_sync": ["API: UME 192.168.170.2 (r32.uedm.batt 实时数据)",
                         "本地DB: battery_kpi.sqlite3 (data/battery/, battery_latest+battery_reading+battery_trend)"],
    # 28. 电池 KPI 邮件（附件 Excel 取自 output_socket；收件人名单取自远程 FTP）
    "battery_email": ["DB: battery_kpi.sqlite3 (data/battery/, battery_latest)",
                      "本地文件: output_socket/battery_latest_*.xlsx (邮件附件)",
                      "远程FTP: /01_RPA/LBR_Tools/KPI/Battary/battary_email (收件人名单)",
                      "外发: Orange OWA 邮件 (owa_mail_report.py via EWS)"],
    # 27. 邮箱空间守卫
    "mailbox_cleanup": ["EWS 邮箱 ztenoc.olr@orange.com (exchmail.orange-cit.ci)",
                        "删除最旧邮件（硬删除释放邮箱配额）"],
    # 29. 失败任务自动重试
    "auto_retry_failed": ["DB: app.db (task_execution_log 失败记录扫描，重新投递 task_queue)"],
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
    "run_battery_kpi_sync": ["API: UME 192.168.170.2 (r32.uedm.batt)", "本地DB: battery_kpi.sqlite3"],
    "run_battery_email": ["DB: battery_kpi.sqlite3", "本地文件: output_socket/*.xlsx", "远程FTP: battary_email (收件人)", "外发: OWA 邮件"],
    "run_mailbox_cleanup": ["EWS 邮箱 ztenoc.olr@orange.com (exchmail.orange-cit.ci)", "删除最旧邮件（硬删除释放邮箱配额）"],
}


# ---------------------------------------------------------------------------
# call_chain 资源标注的英文化
# ---------------------------------------------------------------------------
# TASK_IO / CALL_CHAIN_IO 的值形如 "远程DB: db.sqlite3 (via db_writer API, Eflow_TT_FB)"：
# 主体是路径/表名/主机等标识符（无需翻译），只有前缀与括号内说明是中文。
# 因此这里用「最长优先」的术语替换而非整句词典——后续新增条目只要复用既有术语
# 即可自动英文化；个别需要意译的整句放进 _IO_EN_OVERRIDE。
# 正确性由 TMP/verify_call_chain_i18n.py 断言（EN 输出零残留中文 + 中英条目数一致）。

_IO_EN_OVERRIDE: dict[str, str] = {
    "删除最旧邮件（硬删除释放邮箱配额）":
        "Delete oldest emails (hard delete to reclaim mailbox quota)",
}

# 先跑正则（处理「由 X 生成」这类带变量的句式），再跑术语表
_IO_EN_REGEX: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"由\s*(\S+?)\s*生成"), r"generated by \1"),
)

# (中文, 英文)：顺序即优先级，组合词必须排在其组成部分之前
_IO_EN_TERMS: tuple[tuple[str, str], ...] = (
    # -- 整段说明 --
    ("task_execution_log 失败记录扫描，重新投递 task_queue",
     "task_execution_log failed-run scan, re-enqueue task_queue"),
    ("报表，供 kpi_ms 邮件读取", "report, consumed by the kpi_ms email"),
    ("失败邮件任务记录", "failed email task records"),
    ("报告生成副产品", "report-generation by-product"),
    ("报告副产品", "report by-product"),
    ("本地为降级", "local copy as fallback"),
    ("实时数据", "realtime data"),
    ("邮件附件", "email attachment"),
    ("收件人名单", "recipient list"),
    ("备件报表", "spare-parts report"),
    ("图片+名单", "images + recipient list"),
    ("数据+名单", "data + recipient list"),
    # -- 前缀 --
    ("远程DB:", "Remote DB:"),
    ("本地DB:", "Local DB:"),
    ("本地文件:", "Local file:"),
    ("远程FTP:", "Remote FTP:"),
    ("外发:", "Outbound:"),
    # -- 词组 / 单词（长者优先）--
    ("OWA 邮件发送", "OWA email delivery"),
    ("邮件发送", "Email delivery"),
    ("OWA 邮件", "OWA email"),
    ("EWS 邮箱", "EWS mailbox"),
    ("源自", "sourced from"),
    ("读取", "read"),
    ("时间戳", "timestamp"),
    ("收件人", "recipients"),
    ("报表", "report"),
    ("报告", "report"),
    ("截图", "screenshot"),
    ("图表", "charts"),
    ("名单", "recipient list"),
    ("上传", "upload"),
    ("默认", "default"),
    ("发送", "outbound"),
    ("邮箱", "mailbox"),
    ("邮件", "email"),
    ("读", "read"),
    ("表", "table"),
    ("主", "primary"),
    # -- 全角标点 --
    ("，", ", "),
    ("（", " ("),
    ("）", ")"),
)


def translate_io(s: str) -> str:
    """把单条资源标注串翻成英文（标识符/路径原样保留）。"""
    if s in _IO_EN_OVERRIDE:
        return _IO_EN_OVERRIDE[s]
    out = s
    for pat, rep in _IO_EN_REGEX:
        out = pat.sub(rep, out)
    for zh, en in _IO_EN_TERMS:
        out = out.replace(zh, en)
    return out


def _call_chain_node_name(node: str) -> str:
    """从调用链节点字符串中解析出函数名（去掉 '  → ' 缩进与 ' (file:line)' 位置）。"""
    s = node
    if s.startswith("  → "):
        s = s[4:]
    elif s.startswith("→ "):
        s = s[2:]
    return s.split(" (")[0].strip()


def _annotate_call_chain(chain: list, task_id: str, lang: str = "zh") -> list:
    """为调用链每个节点追加其设计访问的数据库/文件标注。

    - 入口节点（index 0）取自 TASK_IO[task_id]
    - 其余节点若命中 CALL_CHAIN_IO[函数名] 则追加
    资源按「规范化主键」（去掉括号说明、转小写）去重，保留更具体的那条，
    避免同义条目重复；最终以内联形式附加到节点字符串末尾，前端无需改动即可展示。

    lang='en' 时把标注逐条英文化（去重仍按中文主键做，保证中英条目一一对应）。
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
        if lang == "en":
            uniq = [translate_io(r) for r in uniq]
        if uniq:
            annotated.append(f"{node}  ⟵ [{' ; '.join(uniq)}]")
        else:
            annotated.append(node)
    return annotated

# -*- coding: utf-8 -*-
"""从任务注册表自动推导「通过 Orange EWS 发信」的任务集合。

## 为什么存在（2026-09-18）
``email_recovery.EMAIL_TASK_IDS`` 原是一份**手写名单**。漏登记的任务不会走
email_recovery 的补发通道，而是落到 ``auto_retry``（仅 2 次重试 + 15min 冷却）：
邮箱长时间降级时重试额度先于恢复耗尽，恢复后无人补发。该名单已漏过三次——

  - 2026-09-05：sp_email_details / sp_online_report_send / packet_loss_email /
    ccn_free_rating_chart_email / battery_email / ipran_m6k_chart_email（六个）
  - 2026-09-15：sp_material_report
  - 2026-09-18：fw_kpi_sync（通过 owa_mail_report.py 发 FW KPI 日报）

所以改为 **手写名单 ∪ 静态推导**：手写名单仍是权威兜底，推导负责把新增任务
自动纳入，杜绝再次漏登记。

## 推导方式
对每个注册任务取其实体入口（``loader=(module, func_name)`` 的 func_name，或
``func`` 的 ``__name__``），用 AST 解析其所在模块，从入口函数出发：

  1. 沿**同模块内**的函数调用递归（深度受限，带 visited 去重）；
  2. 同时识别**跨模块**调用：若模块以 ``import x.y as alias`` /
     ``from x import y as alias`` 引入了已知发信模块，则入口子树里出现
     ``alias.anything`` 即判定为发信任务。

命中以下任一 EWS 发信标志即算发信任务：``owa_mail_report`` /
``owa_mail_1hour_TT_Report`` / ``owa_mail_8hour_TT_Report`` /
``send_mail_dotnet`` / ``send_via_ews_enhanced`` / ``ews_send_enhanced`` /
``winhttp_ews_send`` / ``send_via_browser_correct`` / ``DotNetEwsSender``。

**比整模块 grep 精确得多**：同一模块里只生成、只同步、只发 WhatsApp 的函数
（sp_report_generate / sp_online_report_generate / sp_whatsapp_report /
battery_kpi_sync）不会被误判。

## 只认 EWS 通道
走 ``smtplib``（126 邮箱，如 olib_soc_report）的通道**不算**——它不依赖 Orange EWS，
EWS 降级时它照样能发，不应进入 EWS 补发名单。

任何异常都降级为「空推导结果」，绝不影响 email_recovery 的可用性。
"""
from __future__ import annotations

import ast
import functools
import importlib.util
import logging
from pathlib import Path

logger = logging.getLogger("email_task_coverage")

# EWS 发信标志：出现任一即认为该函数走 Orange EWS 发信
_EWS_SEND_MARKERS = (
    "owa_mail_report",              # email_reports/owa_mail_report.py（通用发信脚本）
    "owa_mail_1hour_TT_Report",
    "owa_mail_8hour_TT_Report",
    "send_mail_dotnet",             # .NET HttpWebRequest + NTLM
    "send_via_ews_enhanced",        # exchangelib
    "ews_send_enhanced",
    "winhttp_ews_send",
    "send_via_browser_correct",
    "DotNetEwsSender",
)

# 已知「发信模块」：被别的模块 import 后，调用其任意成员即视为发信
_EWS_SENDER_MODULES = (
    "email_reports.owa_mail_report",
    "email_reports.dotnet_ews_send",
    "email_reports.ews_send_enhanced",
    "email_reports.winhttp_ews_send",
    "email_reports.send_via_browser_correct",
    "backend.services.kpi_email_report",
    "backend.services.liberia_email_report",
)

# 裸模块名（`import kpi_email_report as ker` 这种非包内绝对导入也存在于代码里）
_EWS_SENDER_BARE_NAMES = frozenset(m.rsplit(".", 1)[-1] for m in _EWS_SENDER_MODULES)

# 注册表自身的模块：其中的 func= 包装函数（scheduled_eflow_sync 等）不参与推导，
# 否则会因 task_registry 里出现发信模块名而把全部 func= 任务误判为发信任务。
_REGISTRY_MODULE = "backend.task_registry"

# 非「报表发信」任务：email_recovery 自身就是补发引擎，其探测函数里引用
# owa_mail_1hour_TT_Report 是为了拉起探测子进程，不是发报表。排除以免自我登记。
_NON_REPORT_TASKS = frozenset({"email_recovery"})

_MAX_DEPTH = 5


class _ModuleIndex:
    """单个模块的 AST 索引：顶层函数 + 发信模块别名 + docstring 节点。"""

    def __init__(self, tree: ast.AST):
        self.funcs: dict[str, ast.AST] = {}
        self.aliases: dict[str, str] = {}
        self.imported_names: dict[str, str] = {}
        # docstring 也是 ast.Constant 字符串。若不做排除，"参见 owa_mail_report.py"
        # 这类**说明文字**会被当成发信标志（实测误报 battery_kpi_sync / mailbox_cleanup）。
        self.docstrings: set[int] = set()
        self._collect_docstrings(tree)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.funcs[node.name] = node
        # import 可能写在**函数体内**（battery_kpi_service 的
        # `from backend.services import kpi_email_report as ker` 就在
        # _run_battery_email_impl 里），故别名要全树收集，不能只看 tree.body。
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._collect_imports(node)

    def _collect_docstrings(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = getattr(node, "body", None)
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    self.docstrings.add(id(body[0].value))

    def _collect_imports(self, node) -> None:
        if isinstance(node, ast.Import):
            for a in node.names:
                if self._is_sender_module(a.name):
                    self.aliases[a.asname or a.name.split(".")[-1]] = a.name
        else:  # ImportFrom
            base = node.module or ""
            for a in node.names:
                full = f"{base}.{a.name}" if base else a.name
                if self._is_sender_module(full):
                    self.aliases[a.asname or a.name] = full
                elif self._is_sender_module(base):
                    # from <发信模块> import func —— 函数名本身即发信入口
                    self.imported_names[a.asname or a.name] = base

    @staticmethod
    def _is_sender_module(name: str) -> bool:
        """已知发信模块。同时接受全限定名与裸名（`import kpi_email_report as ker`
        这种非包内绝对导入也存在于代码里）。"""
        if not name:
            return False
        if name in _EWS_SENDER_MODULES:
            return True
        return name in _EWS_SENDER_BARE_NAMES


def _iter_nodes(root: ast.AST):
    """深度优先遍历子树（含 root 自身）。"""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _subtree_sends(root: ast.AST, index: _ModuleIndex) -> tuple[bool, str]:
    """入口子树内是否直接命中发信标志（不递归同模块函数）。"""
    for node in _iter_nodes(root):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in index.docstrings:
                continue
            for mk in _EWS_SEND_MARKERS:
                if mk in node.value:
                    return True, f"字符串引用 {mk!r}"
        if isinstance(node, ast.Name):
            if node.id in index.imported_names:
                return True, f"import 了发信函数 {node.id}"
            for mk in _EWS_SEND_MARKERS:
                if mk in node.id:
                    return True, f"调用 {node.id}"
        if isinstance(node, ast.Attribute):
            for mk in _EWS_SEND_MARKERS:
                if mk in node.attr:
                    return True, f"调用 .{node.attr}"
            base = node.value
            if isinstance(base, ast.Name) and base.id in index.aliases:
                return True, f"调用发信模块 {index.aliases[base.id]}.{node.attr}"
    return False, ""


def _called_local_names(root: ast.AST) -> set[str]:
    """子树里以裸名调用的函数名（用于同模块递归）。"""
    names: set[str] = set()
    for node in _iter_nodes(root):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def _analyze(func_node: ast.AST, index: _ModuleIndex, depth: int = 0,
             visited: set[str] | None = None) -> tuple[bool, str]:
    """入口函数是否（间接）走 EWS 发信。"""
    visited = visited if visited is not None else set()
    hit, why = _subtree_sends(func_node, index)
    if hit:
        return True, why
    if depth >= _MAX_DEPTH:
        return False, ""
    for name in _called_local_names(func_node):
        if name in visited:
            continue
        callee = index.funcs.get(name)
        if callee is None:
            continue
        visited.add(name)
        hit, why = _analyze(callee, index, depth + 1, visited)
        if hit:
            return True, f"{name}() -> {why}"
    return False, ""


@functools.lru_cache(maxsize=64)
def _load_index(module_path: str) -> _ModuleIndex | None:
    try:
        spec = importlib.util.find_spec(module_path)
        origin = getattr(spec, "origin", None)
        if not origin or not str(origin).endswith(".py"):
            return None
        src = Path(origin).read_text(encoding="utf-8", errors="replace")
        return _ModuleIndex(ast.parse(src))
    except Exception as exc:  # noqa: BLE001
        logger.debug("解析模块失败 %s: %s", module_path, exc)
        return None


def _entry_of(spec: dict) -> tuple[str, str] | None:
    """取任务的 (模块路径, 入口函数名)。"""
    loader = spec.get("loader")
    if loader:
        try:
            return str(loader[0]), str(loader[1])
        except Exception:  # noqa: BLE001
            return None
    func = spec.get("func")
    if func is None:
        return None
    mod = getattr(func, "__module__", "") or ""
    if mod == _REGISTRY_MODULE:
        return None
    return mod, getattr(func, "__name__", "")


def discover_email_tasks(specs=None) -> dict:
    """返回 {task_id: 命中原因}，仅含推导出「走 EWS 发信」的任务。

    ``specs`` 缺省取 ``backend.task_registry.TASK_SPECS``；传入可便于测试。
    """
    if specs is None:
        try:
            from backend.task_registry import TASK_SPECS as specs  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            logger.warning("加载任务注册表失败，推导结果为空: %s", exc)
            return {}

    found: dict[str, str] = {}
    for spec in specs:
        try:
            task_id = spec.get("task_id")
            entry = _entry_of(spec)
            if not task_id or entry is None or task_id in _NON_REPORT_TASKS:
                continue
            module_path, func_name = entry
            index = _load_index(module_path)
            if index is None:
                continue
            node = index.funcs.get(func_name)
            if node is None:
                continue
            hit, why = _analyze(node, index)
            if hit:
                found[task_id] = f"{module_path}.{func_name} -> {why}"
        except Exception as exc:  # noqa: BLE001
            logger.debug("推导任务失败 %s: %s", spec.get("task_id"), exc)
    return found


if __name__ == "__main__":  # 便于手工核对：python -m backend.services.email_task_coverage
    result = discover_email_tasks()
    print(f"推导出 {len(result)} 个 EWS 发信任务：")
    for tid, why in sorted(result.items()):
        print(f"  {tid:<32} {why}")

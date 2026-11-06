"""文档一致性守卫的「真相源提取层」——**纯 AST 解析，不 import 业务模块**。

为什么不用 `from backend.task_registry import TASK_SPECS` 那种直接 import
（2026-10-31 改造）：

    1. **跨平台**：`backend/worker_watchdog.py` 顶层 `import ctypes.wintypes`
       —— 在 Linux/macOS 上直接 ImportError。守卫一旦依赖它，CI 只能在
       Windows runner 上跑。
    2. **零第三方依赖**：`backend/worker.py` → `services/task_runner.py` →
       `apscheduler` / `sqlalchemy` / `backend.database`。守卫为了数几个条目
       而拖进整套运行时依赖，等于要求每台机器先装好整个后端环境才能跑
       一次「文档有没有过期」的检查 —— 这正是「跑不起来的守卫等于没有」。
    3. **无副作用**：import 业务模块会执行模块级代码（建 logger、读环境变量、
       可能连库）。守卫应该只读文件。

所以这里统一走 `ast`：**从源码的抽象语法树里取出字面量**。
`TASK_SPECS` 是 `list[dict(...)]` 字面量，`GROUP_TASK_MAP` 是纯字面量 dict，
两者都能被 AST 精确还原 —— 取到的就是代码里那些值本身，不是「近似」。

若将来 `TASK_SPECS` 改成运行时拼装（不再是字面量），这里会解析失败并
显式报错（见 `_literal_list` / `_literal_dict`），而不是悄悄返回空列表 ——
**守卫取不到真相源必须显式失败**，这是本仓库 2026-10-31 踩过的坑
（门户侧 `myAppTaskCount()` 正则失配导致两个检查静默跳过，守卫显示 PASS）。

对外接口：
    task_ids()          -> list[str]   已注册任务 id（保持 TASK_SPECS 顺序）
    group_task_map()    -> dict[str, list[str]]  worker 组 -> 任务 id 列表
    task_retention_days() -> int|None  队列日志保留天数（代码默认值）
    router_count()      -> int         main.py 里 include_router 的处数
    pushdown_scope()    -> (list[str], int)  看板时间下推的表清单 + 默认回看天数
    pg_freshness_scope()-> list[(list[str], int)]  本机 PG 巡检清单配的表与回看天数
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# Task/my_app 目录（本文件在 Task/my_app/tests/ 下）
MYAPP_ROOT = Path(__file__).resolve().parent.parent


class TruthSourceError(RuntimeError):
    """真相源解析失败 —— 守卫自身坏了，必须显式暴露而不是静默跳过。"""


# ────────────────────────── 通用 AST 小工具 ──────────────────────────

def _parse(rel: str) -> ast.Module:
    path = MYAPP_ROOT / rel
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:  # pragma: no cover - 代码写坏了，守卫要报出来
        raise TruthSourceError(f"解析 {rel} 失败：{e}") from e


def _assigned_node(tree: ast.Module, name: str) -> ast.AST:
    """取模块顶层 `NAME = ...` 的赋值节点。"""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return node.value
        # 也接受 AnnAssign（`NAME: list = ...`）
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return node.value
    raise TruthSourceError(
        f"源码里找不到顶层赋值 `{name}` —— 守卫的真相源取法与代码写法脱节了，"
        f"请更新 tests/doc_truth.py（这不是「不适用」，是守卫自己坏了）"
    )


def _literal_dict(node: ast.AST, what: str) -> dict:
    """把 dict 字面量还原成 Python dict；含非字面量内容时显式报错。"""
    if not isinstance(node, ast.Dict):
        raise TruthSourceError(f"{what} 不是字面量 dict（实际是 {type(node).__name__}）")
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError) as e:
        raise TruthSourceError(f"{what} 里有非字面量内容，无法静态还原：{e}") from e


# ────────────────────────── 任务注册表 ──────────────────────────

def task_ids() -> list[str]:
    """从 `backend/task_registry.py` 的 TASK_SPECS 里取出全部 task_id（保持顺序）。

    TASK_SPECS 的条目是 `dict(task_id="xxx", name=..., ...)` 调用 —— 不是
    `{"task_id": ...}` 字面量，所以不能 literal_eval 整个列表，改为遍历
    AST 的 Call 节点取 `task_id` 关键字参数。
    """
    tree = _parse("backend/task_registry.py")
    value = _assigned_node(tree, "TASK_SPECS")
    if not isinstance(value, (ast.List, ast.Tuple)):
        raise TruthSourceError(
            f"TASK_SPECS 不是列表字面量（实际是 {type(value).__name__}）"
        )
    ids: list[str] = []
    for elt in value.elts:
        tid = None
        # dict(task_id="xxx", ...) 形式
        if isinstance(elt, ast.Call):
            for kw in elt.keywords:
                if kw.arg == "task_id" and isinstance(kw.value, ast.Constant):
                    tid = kw.value.value
        # {"task_id": "xxx", ...} 形式
        elif isinstance(elt, ast.Dict):
            for k, v in zip(elt.keys, elt.values):
                if isinstance(k, ast.Constant) and k.value == "task_id" \
                        and isinstance(v, ast.Constant):
                    tid = v.value
        if tid is None:
            raise TruthSourceError(
                "TASK_SPECS 里有条目取不到 task_id —— 守卫与代码脱节了"
            )
        ids.append(tid)
    if not ids:
        raise TruthSourceError("TASK_SPECS 解析出 0 条任务 —— 守卫的真相源取法与代码写法脱节了")
    return ids


# ────────────────────────── worker 分组表 ──────────────────────────

def group_task_map() -> dict[str, list[str]]:
    """从 `backend/worker_watchdog.py` 的 GROUP_TASK_MAP 取各组任务列表。

    组的值是一个「逗号分隔的字符串」，且源码里用 Python 的**相邻字符串隐式
    拼接**写成多行（中间夹着大量说明注释），例如：

        "u": (
            "ran_ume_daily,main_kpi_sync,"
            # 注释
            "cells_kpi_sync,"
        )

    `ast.literal_eval` 会把相邻字面量折叠成一个字符串，所以还原后按逗号切分即可。
    """
    tree = _parse("backend/worker_watchdog.py")
    value = _assigned_node(tree, "GROUP_TASK_MAP")
    raw = _literal_dict(value, "GROUP_TASK_MAP")
    out: dict[str, list[str]] = {}
    for group, tasks in raw.items():
        if not isinstance(tasks, str):
            raise TruthSourceError(f"GROUP_TASK_MAP['{group}'] 不是字符串（实际 {type(tasks).__name__}）")
        out[group] = [t.strip() for t in tasks.split(",") if t.strip()]
    if not out:
        raise TruthSourceError("GROUP_TASK_MAP 解析出 0 个组 —— 守卫与代码脱节了")
    return out


# ────────────────────────── 其它数字事实 ──────────────────────────

def task_retention_days() -> int:
    """队列任务日志的保留天数（代码默认值）。

    真相源是 `backend/services/task_runner.py` 里 `getenv("TASK_LOG_RETENTION_DAYS", "7")`
    的默认值。取不到就报错 —— 曾经文档写 3 天、代码是 7 天，正是这类漂移。
    """
    src = (MYAPP_ROOT / "backend" / "services" / "task_runner.py").read_text(
        encoding="utf-8", errors="replace"
    )
    m = re.search(r'TASK_LOG_RETENTION_DAYS"\s*,\s*"(\d+)"', src)
    if not m:
        raise TruthSourceError(
            "task_runner.py 里找不到 TASK_LOG_RETENTION_DAYS 的默认值 —— 守卫与代码脱节了"
        )
    return int(m.group(1))


def router_count() -> int:
    """`backend/main.py` 里 include_router 的处数。"""
    src = (MYAPP_ROOT / "backend" / "main.py").read_text(encoding="utf-8", errors="replace")
    return len(re.findall(r"include_router", src))


def pushdown_scope() -> tuple[list[str], int]:
    """看板取数层的时间下推范围：`(表清单, 默认回看天数)`。

    真相源 `backend/services/dashboard_service.py`：
      - `PUSH_DOWN_TABLES` —— 字面量 tuple，命中它的组件才会被下推时间条件；
      - `os.environ.get("NATIVE_BOARD_PUSHDOWN_DAYS", "31")` 的默认值 ——
        看板「不选窗口时默认看几天」。
    两个都取不到就显式报错，不静默返回空。
    """
    rel = "backend/services/dashboard_service.py"
    tree = _parse(rel)
    node = _assigned_node(tree, "PUSH_DOWN_TABLES")
    try:
        raw = ast.literal_eval(node)
    except (ValueError, SyntaxError) as e:
        raise TruthSourceError(f"PUSH_DOWN_TABLES 不是字面量，取不到表清单：{e}") from e
    tables = [str(x) for x in raw]
    if not tables:
        raise TruthSourceError("PUSH_DOWN_TABLES 解析出 0 张表（取法失效了，修取法而不是放行）")
    src = (MYAPP_ROOT / rel).read_text(encoding="utf-8", errors="replace")
    m = re.search(r'NATIVE_BOARD_PUSHDOWN_DAYS"\s*,\s*"(\d+)"', src)
    if not m:
        raise TruthSourceError(
            "dashboard_service.py 里找不到 NATIVE_BOARD_PUSHDOWN_DAYS 的默认值 "
            "—— 守卫与代码脱节了"
        )
    return tables, int(m.group(1))


def pg_freshness_scope() -> list[tuple[list[str], int]]:
    """本机 PG 巡检清单里每条配了什么：`[(表清单, lookback_days), ...]`。

    真相源 `backend/services/pg_schema_freshness.py` 的 `PG_SCHEMA_CHECKS`。
    条目写成 `dict(tables=(...), lookback_days=31, ...)` —— 是 **Call 不是字面量
    dict**，所以 literal_eval 整个清单会失败，改成遍历关键字参数
    （与 `task_ids()` 处理 `TASK_SPECS` 的办法一致）。
    """
    tree = _parse("backend/services/pg_schema_freshness.py")
    value = _assigned_node(tree, "PG_SCHEMA_CHECKS")
    if not isinstance(value, (ast.List, ast.Tuple)):
        raise TruthSourceError(
            f"PG_SCHEMA_CHECKS 不是列表字面量（实际是 {type(value).__name__}）"
        )
    out: list[tuple[list[str], int]] = []
    for elt in value.elts:
        if not isinstance(elt, ast.Call):
            raise TruthSourceError("PG_SCHEMA_CHECKS 有条目不是 dict(...) 调用，取法需更新")
        tables: list[str] | None = None
        lookback = 0
        for kw in elt.keywords:
            if kw.arg == "tables":
                try:
                    tables = [str(x) for x in ast.literal_eval(kw.value)]
                except (ValueError, SyntaxError) as e:
                    raise TruthSourceError(f"tables 不是字面量序列：{e}") from e
            elif kw.arg == "lookback_days" and isinstance(kw.value, ast.Constant):
                lookback = int(kw.value.value)
        if not tables:
            raise TruthSourceError(
                "PG_SCHEMA_CHECKS 有条目取不到 tables —— 守卫与代码脱节了"
            )
        out.append((tables, lookback))
    if not out:
        raise TruthSourceError("PG_SCHEMA_CHECKS 解析出 0 条清单（取法失效了，修取法而不是放行）")
    return out


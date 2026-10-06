"""task_runner 单元测试：注册 / 异常捕获写 error_trace / 业务失败写 error / 保留期清理。

使用临时 DB，不污染线上 app.db；通过 monkeypatch 屏蔽真实微信通知。
运行：
    cd D:/01_RPA/Task/my_app
    python -m pytest tests/test_task_runner.py -q
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# 让测试能 import backend 包
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import task_runner as tr  # noqa: E402


@pytest.fixture
def tmp_db(monkeypatch):
    """用临时 DB 替换线上 app.db，并屏蔽真实微信通知。

    ⚠️ 2026-09-27 修复：必须**强制 sqlite 模式**，否则本 fixture 是假的。

    原因：`task_runner` 已改用 `get_raw_connection(str(DB_PATH))`，而
    `database.py:159` 在 `DB_MODE == "pg"` 时**直接返回 PG 连接**，传入的
    db_path 只用于推断 schema、**根本不连这个文件**。本机 `backend/.env`
    现为 `MY_APP_DB_MODE=pg`，于是：
      - monkeypatch 掉的临时 DB 从未被写入；
      - 测试却仍然去读自己的空临时文件 → `no such table: task_execution_log`。
    即整组用例此前在 pg 模式下**必然失败**，与人无关，是环境耦合缺陷。

    置 `MY_APP_DB_MODE=sqlite` 后，`get_raw_connection` 才会真的连这个临时文件。
    注意 `DB_MODE` 是 `database.py` 的**导入期常量**，所以必须同时 patch 模块属性，
    只设环境变量不够（本文件已 import 过 database）。
    """
    p = Path(tempfile.mktemp(suffix=".db"))
    monkeypatch.setenv("MY_APP_DB_MODE", "sqlite")
    import backend.database as _db
    from backend.services import task_stats as _ts
    monkeypatch.setattr(_db, "DB_MODE", "sqlite", raising=False)
    monkeypatch.setattr(tr, "DB_PATH", p)

    # ⚠️ 必须把**所有**持有 DB_PATH 副本的模块一起改掉。
    # `task_stats.py:14` 写的是 `from backend.database import DB_PATH` —— 导入即
    # 绑定，它拿到的是**独立的一份引用**，改 task_runner.DB_PATH 对它无效。
    # 只补 tr 的后果实测过：`get_task_history_by_task` / `get_task_stats` 会去查
    # **真的 db/app.db**，于是读到历史遗留行（断言 len==2 实测得到 6/7），
    # 而且**测试会污染生产库**。凡新增 `from backend.database import DB_PATH`
    # 的模块，都要在这里补一行。
    monkeypatch.setattr(_ts, "DB_PATH", p)
    monkeypatch.setattr(_db, "DB_PATH", p)

    monkeypatch.setattr(tr, "notify_task_failure", lambda *a, **k: None)
    # ⚠️ 必须一并屏蔽邮件通知：此前只 patch 了微信（notify_task_failure），
    # 而 run_task 失败分支还会调 notify_task_failure_email 给 126 邮箱发告警。
    # 于是 `__t_stat_bad__`（故意抛错的用例）每次跑都会真发一封
    # "统计失败 / agg failure sample" 告警邮件——运维收到后误以为是线上故障。
    monkeypatch.setattr(tr, "notify_task_failure_email", lambda *a, **k: None)
    # 默认保留 3 天，避免清理逻辑把刚写入的记录删掉
    monkeypatch.setenv("TASK_LOG_RETENTION_DAYS", "3")
    # 建表：_ensure_task_log_table 平时由 worker/启动流程调用，单测需自行准备，
    # 否则第一次 run_task 就会因缺表失败。
    with _db.get_raw_connection(str(p), timeout=30) as conn:
        tr._ensure_task_log_table(conn)
    yield p
    try:
        p.unlink()
    except OSError:
        pass


def _last_row(conn):
    return conn.execute(
        "SELECT success, error, error_trace FROM task_execution_log "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()


def test_exception_captures_error_and_traceback(tmp_db):
    def boom():
        raise RuntimeError("dummy failure for test")

    tr.register_task("__t_exc__", "异常任务", boom, category="general")
    res = tr.run_task("__t_exc__", trigger="manual")

    assert res["success"] is False
    assert res["error"] == "dummy failure for test"
    assert res.get("error_trace")
    assert "boom" in res["error_trace"]

    import sqlite3
    conn = sqlite3.connect(str(tmp_db))
    row = _last_row(conn)
    conn.close()
    assert row[0] == 0
    assert row[1] == "dummy failure for test"
    assert bool(row[2])


def test_business_failure_dict_writes_error(tmp_db):
    def biz_fail():
        return {"success": False, "error": "业务校验未通过", "message": "缺参数 x"}

    tr.register_task("__t_biz__", "业务失败任务", biz_fail, category="general")
    res = tr.run_task("__t_biz__", trigger="manual")

    assert res["success"] is False
    assert res["error"]  # 之前这里是 None（只显示失败却无信息）

    import sqlite3
    conn = sqlite3.connect(str(tmp_db))
    row = _last_row(conn)
    conn.close()
    assert row[0] == 0
    assert bool(row[1])


def test_success_writes_no_error(tmp_db):
    def ok():
        return {"success": True, "message": "done"}

    tr.register_task("__t_ok__", "成功任务", ok, category="general")
    res = tr.run_task("__t_ok__", trigger="manual")

    assert res["success"] is True
    import sqlite3
    conn = sqlite3.connect(str(tmp_db))
    row = _last_row(conn)
    conn.close()
    assert row[0] == 1
    assert row[1] is None


def test_retention_cleanup(tmp_db):
    """超过保留期的记录应被清理；保留期内的保留。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_db))
    tr._ensure_task_log_table(conn)
    # 一条 10 天前的失败记录 + 一条刚写入
    conn.execute(
        "INSERT INTO task_execution_log "
        "(task_id, task_name, category, trigger_type, success, started_at, completed_at, elapsed_seconds, result_json, error, error_trace) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("__old__", "旧任务", "general", "manual", 0,
         "2000-01-01T00:00:00", "2000-01-01T00:00:01", 1.0, None,
         "old error", "old trace"),
    )
    conn.commit()
    conn.close()

    # 跑一个任务触发 _save_task_result 内的清理（保留 3 天）
    def noop():
        return {"success": True}

    tr.register_task("__t_ret__", "保留测试", noop, category="general")
    tr.run_task("__t_ret__", trigger="manual")

    import sqlite3
    conn = sqlite3.connect(str(tmp_db))
    old = conn.execute(
        "SELECT COUNT(*) FROM task_execution_log WHERE task_id='__old__'"
    ).fetchone()[0]
    conn.close()
    assert old == 0  # 旧记录已被清理


def _chain_leaf():
    return {"success": True}


def _chain_entry():
    """必须是模块级函数：嵌套 def 的源码带缩进无法 AST 解析，
    且闭包变量不在 co_names 里，调用链会为空（这是 _auto_call_chain 的已知边界）。"""
    return _chain_leaf()


def test_call_chain_auto_extracted(tmp_db):
    tr.register_task("__t_chain__", "链任务", _chain_entry, category="general")
    entry_info = tr._task_registry["__t_chain__"]
    chain = entry_info.get("call_chain") or []
    # 节点形如 "_chain_leaf (tests/test_task_runner.py:133)"，用子串匹配
    assert any("_chain_leaf" in node for node in chain), chain


def test_call_chain_node_has_file_and_line(tmp_db):
    """调用链节点应带 file:line 定位信息（优化 #7）。"""
    tr.register_task("__t_chain2__", "链任务2", _chain_entry, category="general")
    chain = tr._task_registry["__t_chain2__"].get("call_chain") or []
    hit = [n for n in chain if "_chain_leaf" in n]
    assert hit, chain
    assert ".py:" in hit[0], hit[0]


def test_chain_from_file_locates_without_import(tmp_db):
    """#7：纯静态解析源文件即可定位 file:line，不需要导入目标模块。

    2026-09-27：`_chain_from_file` 已随 "Phase 4 拆分" 迁至
    `backend.services.task_introspect`，`task_runner` 只再导出了
    `_auto_call_chain` / `_annotate_call_chain`（见 task_runner.py:31-37），
    所以这里改为直接从新模块取，而不是断言它还在 task_runner 上。
    """
    from backend.services import task_introspect as ti
    chain = ti._chain_from_file("backend.services.task_runner", "run_task", 1)
    assert chain, "run_task 应能解析出下游调用"
    assert any(".py:" in n for n in chain), chain


def test_module_file_returns_none_for_missing(tmp_db):
    """同名迁移：`_module_file` 现在位于 task_introspect（同名同语义）。"""
    from backend.services import task_introspect as ti
    assert ti._module_file("no.such.module.__xyz__") is None
    assert ti._module_file("") is None


def test_get_task_stats_and_failures(tmp_db):
    """#8/#9：单任务统计 + 失败聚合。

    2026-10-06：失败聚合（get_recent_failures / get_task_history / get_global_history）
    现在会**排除 `__t_` 测试任务**，避免单测刻意构造的失败被当成线上故障告警。
    因此：
      - 单任务统计（按 ID 精确查）仍用 `__t_stat_bad__`，验证统计口径；
      - 失败聚合改用**非测试 ID**（`stat_bad`）来断言聚合内容；
      - 另断言 `__t_` 前缀任务不出现在聚合里（新契约）。
    """
    def ok():
        return {"success": True}

    def bad():
        raise RuntimeError("agg failure sample")

    # 单任务统计：用测试 ID（精确查，不受前缀过滤影响）
    tr.register_task("__t_stat_ok__", "统计成功", ok, category="general")
    tr.register_task("__t_stat_bad__", "统计失败", bad, category="general")
    tr.run_task("__t_stat_ok__", trigger="manual")
    tr.run_task("__t_stat_bad__", trigger="manual")
    tr.run_task("__t_stat_bad__", trigger="manual")

    # 契约：success_rate 是 0~1 的比例（前端负责 ×100 展示）
    s = tr.get_task_stats("__t_stat_bad__")
    assert s["total_runs"] == 2
    assert s["failed_runs"] == 2
    assert s["success_rate"] == 0.0

    s2 = tr.get_task_stats("__t_stat_ok__")
    assert s2["total_runs"] == 1 and s2["success_rate"] == 1.0
    assert s2["avg_elapsed"] is not None and s2["last_seen"]

    # 失败聚合：换用非测试 ID，验证聚合本身仍然工作
    tr.register_task("stat_bad", "统计失败(非测试)", bad, category="general")
    tr.run_task("stat_bad", trigger="manual")

    agg = tr.get_recent_failures(days=3)
    assert agg["total_failures"] >= 1
    lines = [c["error_first_line"] for c in agg["clusters"]]
    assert any("agg failure sample" in l for l in lines), lines
    # 新契约：测试任务（__t_）不得进入运维聚合视图
    all_task_ids = {tid for c in agg["clusters"] for tid in c["tasks"]}
    assert not any(tid.startswith("__t_") for tid in all_task_ids), all_task_ids


def test_get_task_history_by_task(tmp_db):
    """#11：按任务查历史，只返回该任务的记录。"""
    def ok():
        return {"success": True}

    tr.register_task("__t_hist_a__", "历史A", ok, category="general")
    tr.register_task("__t_hist_b__", "历史B", ok, category="general")
    tr.run_task("__t_hist_a__", trigger="manual")
    tr.run_task("__t_hist_a__", trigger="manual")
    tr.run_task("__t_hist_b__", trigger="manual")

    rows = tr.get_task_history_by_task("__t_hist_a__", limit=50)
    assert len(rows) == 2
    assert all(r["task_id"] == "__t_hist_a__" for r in rows)


def test_all_registered_tasks_have_worker_group():
    """分组覆盖守卫（实现已移到不依赖 pytest 的独立文件，本机 venv 未装 pytest）。

    2026-09-18 第四次踩坑（前三次 finebi_report_sync / whatsapp_send_ext /
    sp_email_details）：olib_soc_kpi_daily_sync、olib_soc_vmax_report、
    vmax_multi_data_sync 上线时只写了 TASK_SPECS，分组模式下没有 worker 认领
    → 队列 pending 无人认领、陈旧 pending 又占住单飞名额把后续调度全挡掉，
    三个任务上线后一次也没执行过（task_execution_log 0 条），且不报任何错。
    完整守卫（任务/分组/启动脚本三处一致 + VMAX 同组）见
    tests/test_worker_group_coverage.py，可 `python tests/test_worker_group_coverage.py` 直跑。
    """
    from tests.test_worker_group_coverage import CHECKS as _COVERAGE_CHECKS

    for _fn in _COVERAGE_CHECKS:
        _fn()

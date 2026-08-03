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
    """用临时 DB 替换线上 app.db，并屏蔽真实微信通知。"""
    p = Path(tempfile.mktemp(suffix=".db"))
    monkeypatch.setattr(tr, "DB_PATH", p)
    monkeypatch.setattr(tr, "notify_task_failure", lambda *a, **k: None)
    # 默认保留 3 天，避免清理逻辑把刚写入的记录删掉
    monkeypatch.setenv("TASK_LOG_RETENTION_DAYS", "3")
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
    """#7：纯静态解析源文件即可定位 file:line，不需要导入目标模块。"""
    chain = tr._chain_from_file("backend.services.task_runner", "run_task", 1)
    assert chain, "run_task 应能解析出下游调用"
    assert any(".py:" in n for n in chain), chain


def test_module_file_returns_none_for_missing(tmp_db):
    assert tr._module_file("no.such.module.__xyz__") is None
    assert tr._module_file("") is None


def test_get_task_stats_and_failures(tmp_db):
    """#8/#9：单任务统计 + 失败聚合。"""
    def ok():
        return {"success": True}

    def bad():
        raise RuntimeError("agg failure sample")

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

    agg = tr.get_recent_failures(days=3)
    assert agg["total_failures"] >= 2
    lines = [c["error_first_line"] for c in agg["clusters"]]
    assert any("agg failure sample" in l for l in lines), lines


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

# -*- coding: utf-8 -*-
"""手动 SQL 模式的回归测试（2026-10-05 新增功能）。

用户诉求：除了 AI 问数，也能**直接手写 SQL 查询并导出结果**。

实现复用既有 `/api/data-agent/ask` 端点（`sql` 字段非空即跳过 AI 生成，
见 `nl2sql_service.ask()`）。这带来一条**容易被后续重构改坏**的关键契约：

    **手动模式不需要 API key。**

`ask()` 顶部有 `if sql:` 分支直接跳过 `generate_sql()`，而 key 校验在
`generate_sql()` 内部（`nl2sql_service.py` 的 `if not api_key: raise`）。
所以只要有人把 key 校验提到 `ask()` 开头「统一收口」，手动模式就会立刻
开始要求一个根本用不到的 key —— 界面表现为「我只是想写条 SQL，却被要求填 AI key」。

故此处把这个契约用测试钉死。
"""
import pytest

from backend.services import nl2sql_service as nl2sql


class TestManualSqlNeedsNoAiCredentials:
    """手动模式（直接给 sql）不得要求任何 AI 凭据。"""

    def test_manual_sql_runs_without_api_key(self):
        """空 key + 空 provider + 空 model 也能跑 —— 这正是界面手动模式发的请求。"""
        out = nl2sql.ask(
            question="", provider="", api_key="", model="",
            base_url="", run=True, sql="SELECT COUNT(*) AS n FROM eflow_tt",
        )
        assert out["sql"] == "SELECT COUNT(*) AS n FROM eflow_tt"
        assert out["row_count"] >= 1
        assert "n" in out["columns"]

    def test_manual_sql_does_not_call_llm(self, monkeypatch):
        """手动模式必须完全绕过 LLM：把 generate_sql 换成会炸的实现来证明。"""

        def _boom(*a, **k):
            raise AssertionError("手动模式不应调用 generate_sql（不该有 AI 请求）")

        monkeypatch.setattr(nl2sql, "generate_sql", _boom)
        out = nl2sql.ask(
            question="", provider="", api_key="", model="",
            run=True, sql="SELECT COUNT(*) AS n FROM eflow_tt",
        )
        assert out["row_count"] >= 1

    def test_ai_path_still_requires_api_key(self):
        """反向保护：AI 路径（不给 sql）仍然必须要求 key，不能因为放宽手动模式而放松。"""
        with pytest.raises(nl2sql.Nl2SqlError) as ei:
            nl2sql.ask(
                question="随便问点什么", provider="deepseek", api_key="",
                model="", run=False,
            )
        assert "API key" in str(ei.value)


class TestManualSqlStillGuarded:
    """手动模式**不**绕过安全护栏 —— 自己写 SQL 也必须只读。"""

    @pytest.mark.parametrize("bad", [
        "DROP TABLE eflow_tt",
        "DELETE FROM eflow_tt",
        "UPDATE eflow_tt SET status='x'",
        "INSERT INTO eflow_tt (a) VALUES (1)",
        "SELECT 1; DROP TABLE eflow_tt",  # 多语句
        "TRUNCATE TABLE eflow_tt",
    ])
    def test_write_statements_rejected_in_manual_mode(self, bad):
        with pytest.raises(nl2sql.Nl2SqlError):
            nl2sql.ask(
                question="", provider="", api_key="", model="",
                run=True, sql=bad,
            )

    def test_readonly_select_allowed(self):
        out = nl2sql.ask(
            question="", provider="", api_key="", model="", run=True,
            sql="SELECT * FROM eflow_tt WHERE alarm_clear_time < created_time",
        )
        assert out["row_count"] > 0
        assert out["columns"]


class TestTruncationIsExposed:
    """截断标志仍按实际返回行数判定（前端用它决定是否显示「已达上限」标签）。

    2026-10-05：上限由 200 放宽到 50000，故「必然触顶」的构造方式随之改变 ——
    改用显式小 LIMIT 来触发，而不是依赖默认上限。
    """

    def test_truncated_flag_set_when_limit_reached(self):
        # 显式要 5 行，表里远超 5 行，护栏保留用户的 LIMIT → 必然触顶
        out = nl2s
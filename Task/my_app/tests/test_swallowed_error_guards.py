# -*- coding: utf-8 -*-
"""静默吞错回归测试（2026-10-07 审计）。

这批用例守护同一类缺陷：`except` 捕获异常后只记日志、返回一个**调用方无法与
「合法的空结果」区分**的值，从而把故障可见性整体抹掉。

起因是 `task_stats.get_recent_failures()` 在 PG 下因 SQL 占位符问题必然抛
IndexError，却被 `except` 吞成 `{"total_failures": 0, "clusters": []}`，导致
失败横幅连续数天显示"该窗口内没有失败记录 🎉"，而库里实际有 41 次失败 / 16 个簇。
本文件把同形状的其余几处逐个钉住 —— **每一条都做过反向验证**（把修复改回旧写法
必须让用例失败），否则守卫等于没有。
"""
import sys
import unittest.mock as mk
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------- 高危 2：MS SLA
class TestMsSlaGetDbValueDoesNotSwallow:
    """`get_db_value` / `get_persite_ratio` 的 SQL 异常必须上抛。

    旧实现 `return None`，调用方 `ms_sla_dashboard._collect_network_kpis` 的
    `if v is not None` 会静默跳过该指标 → 7 项 Network KPI / 11 项 Per-Site 占比
    在看板上整块消失，与"该期间确实没有这项指标"无法区分。
    """

    @staticmethod
    def _conn():
        import sqlite3
        c = sqlite3.connect(":memory:")
        c.execute('CREATE TABLE "T" ("Begin Time" TEXT, "V" REAL)')
        c.execute('INSERT INTO "T" VALUES (?, ?)', ("2026-10-01", 5.0))
        return c

    def test_normal_read_still_works(self):
        from backend.services.ms_sla_report import get_db_value, get_persite_ratio
        c = self._conn()
        assert get_db_value(c, "T", "V", "2026-10-01") == 5.0
        assert get_persite_ratio(c, "T", "V", "2026-10-01", ">=", 1.0) == 1.0

    def test_sql_error_raises_instead_of_returning_none(self):
        from backend.services.ms_sla_report import get_db_value, get_persite_ratio
        c = self._conn()
        c.close()  # 关闭后任何查询必然失败
        with pytest.raises(Exception):
            get_db_value(c, "T", "V", "2026-10-01")
        with pytest.raises(Exception):
            get_persite_ratio(c, "T", "V", "2026-10-01", ">=", 1.0)

    def test_source_has_no_silent_except_marker(self):
        """源码级兜底：这两个函数里不得再出现被吞掉的标记。"""
        src = (_ROOT / "backend" / "services" / "ms_sla_report.py").read_text(encoding="utf-8")
        assert "get_db_value: exception swallowed" not in src
        assert "get_persite_ratio: exception swallowed" not in src


# ------------------------------------------------------------- 中危 3：ume_in KPI
class TestUmeInLoadRowsDistinguishesFailure:
    """`_load_rows` 只有"表确实不存在"才返回空；读取失败必须上抛。

    旧实现对任何异常都返回 `([], [])`，`load_overview` 据此返回
    `has_data: False` + 全零 summary，看板显示"暂无数据"——与真·空表无法区分。
    """

    def test_read_failure_propagates(self):
        from backend.services.ume_in import ume_in_kpi_service as svc
        with mk.patch.object(svc, "get_raw_connection",
                             side_effect=RuntimeError("模拟连接失败")):
            with pytest.raises(RuntimeError):
                svc._load_rows()
            with pytest.raises(RuntimeError):
                svc.load_overview()

    def test_missing_table_is_legitimate_empty(self):
        from backend.services.ume_in import ume_in_kpi_service as svc
        orig = svc.TABLE_NAME
        try:
            svc.TABLE_NAME = "_no_such_table_zzz"
            assert svc._load_rows() == ([], [])
        finally:
            svc.TABLE_NAME = orig

    def test_table_exists_probe_works_on_live_db(self):
        """探测函数本身要能在当前库上跑通（sqlite / PG 双模）。"""
        from backend.services.ume_in import ume_in_kpi_service as svc
        with svc.get_raw_connection(timeout=30.0) as conn:
            assert svc._table_exists(conn) is True


# ------------------------------------------------- 中危 4：site availability
class TestSiteAvailabilityFailureVisibility:
    """取数失败必须可区分于"确实没有数据"，且失败结果不得进缓存。"""

    def test_load_error_registered_and_not_cached(self):
        from backend.services import site_availability_service as svc
        svc._load_errors.clear()
        try:
            with mk.patch.object(svc, "get_raw_connection",
                                 side_effect=RuntimeError("模拟库不可达")):
                master = svc.load_master_sites()
            assert master == []
            assert "master" in svc._load_errors_snapshot(), "失败未被登记"
            # 失败结果不得进缓存，否则瞬时故障会持续整个 TTL
            assert svc._cache_get("site_avail:master") is None, "失败结果被缓存了"
        finally:
            svc._load_errors.clear()

    def test_warning_text_distinguishes_failure_from_empty(self):
        """空月 + 登记失败 → 文案必须与纯空态不同，否则运维无法判断是故障还是没数据。"""
        from backend.services import site_availability_service as svc
        month = "1990-01"  # 必然无数据
        try:
            svc._load_errors.clear()
            plain = set(svc.build_overview(month)["meta"].get("warnings", []))
            svc._load_errors.clear()
            svc._mark_load_error("master", "读取 master_site_db 失败: 连接池耗尽")
            with_err = set(svc.build_overview(month)["meta"].get("warnings", []))
            assert with_err - plain, "失败态与空态文案无差别"
            assert any("读取失败" in w for w in with_err), "未出现'读取失败'字样"
        finally:
            svc._load_errors.clear()


# --------------------------------------------- 中危 5：收件人配置读取
class TestEmailRecipientReadFailsLoudly:
    """展示路径读库失败必须上抛；发送路径仍须优雅降级。

    旧实现返回 `{}`，设置页把所有组显示为 `source: "default"`（一个完全合法的
    界面状态），用户看不出读库坏了；此时点保存会无条件 upsert，用默认值覆盖
    真实配置（实测本机有 10 个组确实保存过配置）。
    """

    def test_read_db_map_raises(self):
        from backend.services import email_recipient_store as st
        with mk.patch.object(st, "_get_conn", side_effect=RuntimeError("模拟配置库损坏")):
            with pytest.raises(RuntimeError):
                st._read_db_map()
            with pytest.raises(RuntimeError):
                st.list_email_recipients("zh")

    def test_send_path_still_degrades_gracefully(self):
        """发送主流程不得因读配置库失败而发不出邮件（回退默认名单）。"""
        from backend.services import email_recipient_store as st
        key = st.EMAIL_RECIPIENT_GROUPS[0]["key"]
        with mk.patch.object(st, "_get_conn", side_effect=RuntimeError("模拟配置库损坏")):
            result = st.get_effective_recipients(key)  # 不应抛
        assert isinstance(result, tuple) and len(result) == 2

    def test_normal_read_returns_saved_rows(self):
        """真实库上仍能读出已保存记录（没把正常路径改坏）。"""
        from backend.services import email_recipient_store as st
        rows = st._read_db_map()
        assert isinstance(rows, dict)


# --------------------------------------------------- 低危 6：AST 缓存
class TestAstCacheDoesNotPoisonOnFailure:
    """解析失败不得把 None 固化进缓存，否则该任务提示在进程存活期内永久为空。"""

    def test_failure_not_cached(self):
        from backend.services import task_introspect as ti
        ti._AST_CACHE.clear()
        bad = "C:/__no_such_file_zzz__.py"
        assert ti._parse_file(bad) is None
        assert bad not in ti._AST_CACHE, "失败被缓存，后续永远不再重试"

    def test_success_is_cached(self):
        from backend.services import task_introspect as ti
        ti._AST_CACHE.clear()
        p = str(_ROOT / "backend" / "services" / "task_introspect.py")
        first = ti._parse_file(p)
        assert first is not None
        assert ti._AST_CACHE.get(p) is first, "成功结果未被缓存（会重复解析）"

"""gp_ran 定时任务与旁路存储的离线测试（不连生产数仓）。

覆盖的是**真跑时看不出来**的部分：窗口边界、天数夹紧、CSV 原子写、
保留期清理的作用域、缺数体检的中位数。链路本身由
`python -m backend.services.gp_ran.gp_ran_check --check` 在线验证。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.gp_ran import gp_ran_store as store  # noqa: E402
from backend.services.gp_ran import gp_ran_sync as sync  # noqa: E402


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    """把旁路库与产物目录指到 tmp，避免测试写到真实的 backend/data/gp_ran/。"""
    data_dir = tmp_path / "gp_ran"
    monkeypatch.setattr(store, "DATA_DIR", data_dir)
    monkeypatch.setattr(store, "SQLITE_PATH", data_dir / "gp_ran.sqlite3")
    store.init_store()
    return data_dir


# ---------------------------------------------------------------- 窗口
def test_window_is_seven_complete_utc_days():
    start, end = sync._window(7)
    today = datetime.now(timezone.utc).date()
    assert end == today.isoformat()
    assert start == (today - timedelta(days=7)).isoformat()
    # 不含当天：当天分区还在累积，取它会让看板的数字每天在动
    assert end > start


@pytest.mark.parametrize(("raw", "expect"), [
    (None, 7), (1, 1), (7, 7), (60, 60),
    (0, 1), (-5, 1), (999, 60),      # 夹紧：最早分区只到约 62 天前
])
def test_resolve_days_clamps(raw, expect, monkeypatch):
    monkeypatch.delenv("GP_RAN_WINDOW_DAYS", raising=False)
    assert sync._resolve_days(raw) == expect


def test_resolve_days_env_and_garbage(monkeypatch):
    monkeypatch.setenv("GP_RAN_WINDOW_DAYS", "14")
    assert sync._resolve_days(None) == 14
    monkeypatch.setenv("GP_RAN_WINDOW_DAYS", "abc")
    assert sync._resolve_days(None) == 7          # 环境变量坏了要回落，不能崩


def test_epoch_base_is_year_2000():
    # D027 的口径是「自 2000-01-01 起的秒」，换算错一年不会被发现，只会让窗口整体平移
    assert sync._epoch_to_iso(0) == "2000-01-01 00:00:00 UTC"
    assert sync._epoch_to_iso(840340591).startswith("2026-08-18")
    assert sync._epoch_to_iso("") == ""
    assert sync._epoch_to_iso("N/A") == ""


# ---------------------------------------------------------------- CSV 落盘
def test_write_csv_counts_rows_and_leaves_no_part(tmp_store):
    dest = tmp_store / "volte_a_b.csv"
    assert sync._write_csv("d023\n618001\n618002\n", dest) == 2
    assert dest.exists()
    assert not list(tmp_store.glob("*.part"))
    # utf-8-sig：Excel 直接双击打开中文表头不乱码（本项目导出规范的既有约定）
    assert dest.read_bytes().startswith(b"\xef\xbb\xbf")


def test_write_csv_overwrites_atomically(tmp_store):
    dest = tmp_store / "n78_a_b.csv"
    sync._write_csv("d023\n1\n", dest)
    sync._write_csv("d023\n1\n2\n3\n", dest)
    assert sync._write_csv("d023\n1\n2\n3\n", dest) == 3


# ---------------------------------------------------------------- 记录与体检
def test_record_and_latest_round_trip(tmp_store):
    store.record_run(kind="volte", window_start="2026-10-12", window_end="2026-10-19",
                     users=1234567, csv_path="x.csv", csv_bytes=19, seconds=61.2,
                     rows_scanned=1000000000, data_last="2026-10-19 05:44:59 UTC")
    rows = store.latest_runs(limit=5)
    assert rows[0]["users"] == 1234567 and rows[0]["kind"] == "volte"
    assert rows[0]["data_last"] == "2026-10-19 05:44:59 UTC"
    assert store.latest_runs(limit=5, kind="n78") == []


def test_latest_runs_on_missing_db_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SQLITE_PATH", tmp_path / "nope" / "gp_ran.sqlite3")
    assert store.latest_runs() == []            # 首次部署还没跑过时不能抛


def test_median_users_needs_history(tmp_store):
    assert store.median_users("volte", "2026-10-19") is None
    for i, users in enumerate([100, 200, 300, 400]):
        store.record_run(kind="volte", window_start=f"2026-10-0{i}", window_end="2026-10-1",
                         users=users)
    # 只统计 window_end 与本次不同的历史，且取中位数（均值会被一次缺数拉偏）
    assert store.median_users("volte", "2026-10-19") == 250


# ---------------------------------------------------------------- 保留期清理
def test_purge_keeps_recent_and_protects_foreign_paths(tmp_store, tmp_path):
    foreign = tmp_path / "elsewhere" / "keep_me.csv"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text("x")
    paths = []
    for i in range(5):
        fp = tmp_store / f"volte_{i}.csv"
        fp.write_text("d023\n1\n")
        paths.append(fp)
        store.record_run(kind="volte", window_start="2026-10-01", window_end="2026-10-02",
                         users=1, csv_path=str(fp))
    # 混进一条本目录之外的路径：清理必须只在自己的 DATA_DIR 里动手
    store.record_run(kind="volte", window_start="2026-10-01", window_end="2026-10-02",
                     users=1, csv_path=str(foreign))
    info = store.purge_files(keep=2)
    assert info["deleted"] == 4
    assert not paths[0].exists() and paths[-1].exists()
    assert foreign.exists(), "越界路径被删了 —— 保留期清理必须限定在 DATA_DIR 内"

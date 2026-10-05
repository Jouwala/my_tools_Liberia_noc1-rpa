# -*- coding: utf-8 -*-
"""TT 告警推送的**触发扫描**单测：realtime_alarm 口径（2026-10-05 机制切换）。

锁三类选错**不会报错、只会静默漏单/多单**的口径：
  1. 只认带 TT 的告警（tt_id 非空）—— 没有 TT 就没有可推送对象；
  2. 触发窗口按 alarmraisedtime（epoch 毫秒）判，窗口外不触发
     （兼防首次部署把历史积压一次性全推出去）；
  3. 告警码白名单在 Python 侧归一化判等（'99933.0' ≡ '99933'），
     且同一 tt_id 多条告警只保留最新一条。
"""
import sqlite3
from datetime import datetime, timedelta

from backend.services import tt_alarm_trigger as T


def _ms(dt: datetime) -> int:
    """datetime → epoch 毫秒（与 realtime_alarm.alarmraisedtime 同口径）。"""
    return int(dt.timestamp() * 1000)


def _use_alarm_db(monkeypatch, tmp_path, rows, now: datetime,
                  schedule_cron: str = None):
    """造最小 realtime_alarm（sqlite）并把 get_raw_connection 指过去。

    rows: [(tt_id, alarmraisedtime_ms, alarmcode)]；其余列给占位值。
    schedule_cron 非空时额外建 task_schedule_config 并写入该行
    （模拟用户在任务配置页给 eflow_active_alarm 配的实际调度）。
    """
    conn = sqlite3.connect(tmp_path / "alarm.db")
    conn.execute(
        "CREATE TABLE realtime_alarm ("
        "tt_id TEXT, alarmraisedtime INTEGER, alarmcode TEXT, "
        "site_id TEXT, site_name TEXT, region TEXT, codename TEXT, "
        "alarm_title TEXT, perceivedseverityname TEXT, clearstatename TEXT, "
        "_sync_time TEXT)")
    for tt_id, raised_ms, code in rows:
        conn.execute(
            "INSERT INTO realtime_alarm VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (tt_id, raised_ms, code, "5002", "LEC", "Montserrado",
             "4G CELL DOWN", "title", "Critical", "Uncleared",
             now.isoformat(timespec="seconds")))
    if schedule_cron:
        conn.execute(
            "CREATE TABLE task_schedule_config ("
            "task_id TEXT PRIMARY KEY, cron TEXT, enabled INTEGER, updated_at TEXT)")
        conn.execute(
            "INSERT INTO task_schedule_config VALUES (?,?,1,?)",
            ("eflow_active_alarm", schedule_cron, now.isoformat(timespec="seconds")))
    conn.commit()
    conn.close()

    class _Wrap:
        """模拟 get_raw_connection 的 with 语义（每次进入开新连接，退出关闭）。

        fetch_triggered_tts 允许被同一用例调用多次（如「白名单/留空」各查一遍），
        不能复用已被 with 关闭的连接。
        """

        def __enter__(self):
            self._conn = sqlite3.connect(tmp_path / "alarm.db")
            return self._conn

        def __exit__(self, *exc):
            self._conn.close()
            return False

    from backend import database as db
    monkeypatch.setattr(db, "get_raw_connection", lambda *a, **k: _Wrap())
    return tmp_path / "alarm.db"


def test_only_tt_linked_alarms_trigger(monkeypatch, tmp_path):
    """tt_id 为空的告警（TT 尚未创建）不能触发 —— 没有可推送对象。"""
    now = datetime.now()
    _use_alarm_db(monkeypatch, tmp_path, [
        ("TT1", _ms(now - timedelta(minutes=10)), "9971"),
        (None, _ms(now - timedelta(minutes=10)), "9971"),
        ("", _ms(now - timedelta(minutes=10)), "9971"),
    ], now)

    picked, meta = T.fetch_triggered_tts(now, 180, set())
    assert meta["table_exists"] is True
    assert [r["tt_no"] for r in picked] == ["TT1"]


def test_window_filters_by_alarmraisedtime(monkeypatch, tmp_path):
    """窗口外的告警不触发（首推只看 alarmraisedtime，兼防历史积压爆发）。"""
    now = datetime.now()
    _use_alarm_db(monkeypatch, tmp_path, [
        ("FRESH", _ms(now - timedelta(minutes=10)), "9971"),
        ("EDGE", _ms(now - timedelta(minutes=179)), "9971"),
        ("OLD", _ms(now - timedelta(hours=4)), "9971"),
        ("EPOCH_GARBAGE", 12345, "9971"),   # 1970 年 —— 等价窗口外
    ], now)

    picked, _ = T.fetch_triggered_tts(now, 180, set())
    assert sorted(r["tt_no"] for r in picked) == ["EDGE", "FRESH"]


def test_alarm_code_whitelist_normalizes_float_tail(monkeypatch, tmp_path):
    """白名单命中才算；'9920.0' 与 '9920' 归一化后视为同一码；空集 = 不过滤。"""
    now = datetime.now()
    raised = _ms(now - timedelta(minutes=10))
    _use_alarm_db(monkeypatch, tmp_path, [
        ("A", raised, "9920"),
        ("B", raised, "99933"),
        ("C", raised, "99933.0"),
        ("D", raised, "9920.0"),
        ("TXT", raised, "The link between the server and the ME is broken"),
    ], now)

    picked, _ = T.fetch_triggered_tts(now, 180, {"9920"})
    assert sorted(r["tt_no"] for r in picked) == ["A", "D"], \
        "白名单应同时命中 '9920' 与 '9920.0'，并排除 99933 的两种写法"

    picked_all, _ = T.fetch_triggered_tts(now, 180, set())
    assert sorted(r["tt_no"] for r in picked_all) == ["A", "B", "C", "D", "TXT"], \
        "告警码留空 = 不过滤（含文本码，过滤不能崩）"


def test_dedupe_keeps_latest_alarm_per_tt(monkeypatch, tmp_path):
    """同一 tt_id 关联多条告警（如 2G/4G CELL DOWN）→ 只保留最新一条。"""
    now = datetime.now()
    _use_alarm_db(monkeypatch, tmp_path, [
        ("T1", _ms(now - timedelta(minutes=50)), "9971"),   # 旧
        ("T1", _ms(now - timedelta(minutes=10)), "9981"),   # 新（应保留这条的码）
        ("T2", _ms(now - timedelta(minutes=20)), "9971"),
    ], now)

    picked, _ = T.fetch_triggered_tts(now, 180, set())
    by_tt = {r["tt_no"]: r for r in picked}
    assert sorted(by_tt) == ["T1", "T2"]
    assert by_tt["T1"]["_alarm_code_norm"] == "9981", "应保留 alarmraisedtime 最新的那条"


def test_table_missing_is_reported_not_raised(monkeypatch, tmp_path):
    """realtime_alarm 不存在时返回 table_exists=False（调用方据此报错喊人），不抛异常。"""
    now = datetime.now()
    _use_alarm_db(monkeypatch, tmp_path, [], now)
    # 建的是别的表：删掉 realtime_alarm 模拟「表不存在」
    conn = sqlite3.connect(tmp_path / "alarm.db")
    conn.execute("DROP TABLE realtime_alarm")
    conn.commit()
    conn.close()

    picked, meta = T.fetch_triggered_tts(now, 180, set())
    assert picked == [] and meta["table_exists"] is False


def test_sync_lag_is_measured(monkeypatch, tmp_path):
    """meta 里带回表同步滞后秒数（eflow_active_alarm 挂了时触发面会静默变空，
    调用方据此喊人 —— 2026-10-01「群内静默」同型事故的预防项）。"""
    now = datetime.now()
    _use_alarm_db(monkeypatch, tmp_path, [
        ("T1", _ms(now - timedelta(minutes=10)), "9971"),
    ], now)

    _, meta = T.fetch_triggered_tts(now, 180, set())
    # 行是刚写入的，_sync_time = now → 滞后接近 0 且不为 None
    assert meta["sync_lag_seconds"] is not None
    assert meta["sync_lag_seconds"] < 60


def test_raised_time_is_parsed_to_readable(monkeypatch, tmp_path):
    """触发行要带可读的 alarm_raised_time（渲染与横幅的 open 时长基准）。"""
    now = datetime.now()
    raised = now - timedelta(minutes=30)
    _use_alarm_db(monkeypatch, tmp_path, [("T1", _ms(raised), "9971")], now)

    picked, _ = T.fetch_triggered_tts(now, 180, set())
    assert len(picked) == 1
    assert picked[0]["alarm_raised_time"].startswith(raised.strftime("%Y-%m-%d %H:%M"))
    assert picked[0]["_alarm_raised_dt"] is not None


def test_parse_epoch_ms():
    """毫秒 → 秒的换算口径（fromtimestamp 随机器时区，两边同式比较即可）。"""
    expected = datetime.fromtimestamp(1791031451000 / 1000)
    assert T.parse_epoch_ms(1791031451000) == expected
    assert T.parse_epoch_ms("1791031451000") == expected
    assert T.parse_epoch_ms(None) is None
    assert T.parse_epoch_ms("") is None
    assert T.parse_epoch_ms("bogus") is None


# ---------------- 新鲜度阈值自适应（跟随 eflow_active_alarm 实际调度） ----------------

def test_estimate_cron_interval_minutes():
    """只识别项目里实际出现的 cron 形态，识别不了的返回 None 走兜底。"""
    assert T.estimate_cron_interval_minutes("*/5 * * * *") == 5
    assert T.estimate_cron_interval_minutes("2-59/5 * * * *") == 5,         "区间步进（相位错开形态）必须与全域步进等价推导周期"
    assert T.estimate_cron_interval_minutes("22 * * * *") == 60
    assert T.estimate_cron_interval_minutes("0 */6 * * *") == 360
    assert T.estimate_cron_interval_minutes("0 5 * * *") == 1440
    assert T.estimate_cron_interval_minutes("*/15 * * * *") == 15
    assert T.estimate_cron_interval_minutes("bogus") is None
    assert T.estimate_cron_interval_minutes("") is None
    assert T.estimate_cron_interval_minutes(None) is None


def test_sync_threshold_adapts_to_configured_cron(monkeypatch, tmp_path):
    """任务配置页把 eflow_active_alarm 改成 */5 后，阈值应为 5×60×1.5 = 450 秒。

    回归锁：初始版写死 45 分钟（按注册表默认 */30 定的），生产实际 */5 下
    告警挂了也要 45 分钟才有人知道 —— 阈值必须跟生效 cron 走，不跟默认值走。
    """
    now = datetime.now()
    monkeypatch.delenv("TT_TRIGGER_SYNC_STALE_SECONDS", raising=False)
    _use_alarm_db(monkeypatch, tmp_path, [("T1", _ms(now - timedelta(minutes=1)), "9971")],
                  now, schedule_cron="*/5 * * * *")

    _, meta = T.fetch_triggered_tts(now, 180, set())
    assert meta["sync_stale_threshold_seconds"] == 450


def test_sync_threshold_falls_back_without_schedule_config(monkeypatch, tmp_path):
    """task_schedule_config 不存在（表未建）或 cron 识别不了 → 退回内置兜底。"""
    now = datetime.now()
    monkeypatch.delenv("TT_TRIGGER_SYNC_STALE_SECONDS", raising=False)
    _use_alarm_db(monkeypatch, tmp_path, [("T1", _ms(now - timedelta(minutes=1)), "9971")], now)

    _, meta = T.fetch_triggered_tts(now, 180, set())
    assert meta["sync_stale_threshold_seconds"] == T.SYNC_STALE_SECONDS == 2700


def test_sync_threshold_env_overrides_everything(monkeypatch, tmp_path):
    """显式环境变量优先级最高（运维人工定阈值的出口）。"""
    now = datetime.now()
    monkeypatch.setenv("TT_TRIGGER_SYNC_STALE_SECONDS", "600")
    _use_alarm_db(monkeypatch, tmp_path, [("T1", _ms(now - timedelta(minutes=1)), "9971")],
                  now, schedule_cron="*/5 * * * *")

    _, meta = T.fetch_triggered_tts(now, 180, set())
    assert meta["sync_stale_threshold_seconds"] == 600


def test_sync_threshold_has_floor_against_tight_cron(monkeypatch, tmp_path):
    """周期配得再密（如 */1 → 90s 推导值）也不低于 5 分钟，防同步抖动误报。"""
    now = datetime.now()
    monkeypatch.delenv("TT_TRIGGER_SYNC_STALE_SECONDS", raising=False)
    _use_alarm_db(monkeypatch, tmp_path, [("T1", _ms(now - timedelta(minutes=1)), "9971")],
                  now, schedule_cron="*/1 * * * *")

    _, meta = T.fetch_triggered_tts(now, 180, set())
    assert meta["sync_stale_threshold_seconds"] == T.SYNC_STALE_FLOOR_SECONDS == 300

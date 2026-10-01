# -*- coding: utf-8 -*-
"""Chrome 扩展「是否在线」的判定（2026-10-01 事故的治本项之一）。

## 为什么需要它

`tt_alarm_whatsapp_alert` 每 15 分钟把 P1 告警文本投进作业邮箱，等**浏览器里的
Chrome 扩展**认领并发送（`tt_alarm_job` 的作业文件状态机）。这条链路有个
**结构性依赖**：扩展必须运行在一个**已登录 WhatsApp Web 的浏览器**里，而那个浏览器
是**人手动打开的**（扩展用 `--load-extension` 加载，没有自启机制）。

于是「浏览器没开」时，作业投出去没人认领，任务要**干等 600s 才发现**，
而这段时间里值班群实际上收不到任何告警 —— 2026-10-01 实测正是如此：
04:15~04:55 连续 4 轮未达，群内静默，直到作业把邮箱堵死 4.3 小时才被人从
任务列表里看出来。

**本模块要解决的不是「让浏览器自己开着」，而是让「没开」这件事立刻可见。**
投递前先问一句「扩展最近还在认领吗」，不在就立即走告警通道喊人，
而不是把 10 分钟超时当成一次普通失败。

## 判据为什么用「最近认领时间」而不是别的

后端**看不到**扩展的内部状态：扩展的心跳（`chrome.storage` 的 `wa_sender_last_run`）
存在浏览器本地，不发给后端；浏览器进程在不在也只能说明「有窗口」，
不能说明「扩展被加载且登录着」。

唯一由扩展**主动且周期性地打给后端**的信号，就是它每分钟一次的
`GET /api/whatsapp/ext/job`（`background.js` 的 `tick()`，经 `claim_next_job()`）。
所以「后端最近一次被认领的时刻」是能证明扩展活着的最直接证据 ——
它同时覆盖了三个条件：浏览器开着、扩展加载着、页面能连上后端。

证据落盘在 `data/ext_liveness.json`（与作业文件同目录、同为原子写），
**不引入第二个真相源**：它只记录时间戳，状态判定仍是纯函数。

## 冷启动的诚实处理

服务刚启动时没有任何认领记录，此时**不能**判「扩展离线」——那会在每次重启后
都误报一次。故记录缺失时返回 `unknown`，由调用方决定（当前策略：不告警，
只在本轮结果里注明「尚无扩展活动记录」）。判为离线必须**有明确证据**：
曾见过扩展，且此后超过阈值没动静。
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("ext_liveness")

# 判定阈值（秒）。必须**明显大于扩展的轮询周期**（1 分钟），否则正常的
# 轮询间隔抖动就会被误判成离线。默认 5 分钟：既能容忍几轮丢包/休眠，
# 又能在「浏览器被关」后 5 分钟内让人知道。
LIVENESS_STALE_SECONDS = int(os.environ.get("WHATSAPP_EXT_LIVENESS_SECONDS", "300"))

# 记录文件放在作业文件旁边（同目录、同原子写约定），便于运维一眼看全。
STATE_FILE = Path(__file__).resolve().parent / "data" / "ext_liveness.json"

STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"
STATUS_UNKNOWN = "unknown"


def _s(val: Any) -> str:
    return "" if val is None else str(val).strip()


def _parse_iso(value: Any) -> Optional[float]:
    """解析 ISO 文本 → epoch 秒；缺失/不可解析返回 None。"""
    txt = _s(value)
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt).timestamp()
    except Exception:  # noqa: BLE001
        return None


def read_state() -> dict:
    """读活动记录；文件不存在或损坏返回 {}（不抛异常）。"""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001
        logger.warning("[ExtLiveness] 读活动记录失败", exc_info=True)
        return {}


def record_activity(now: Optional[datetime] = None, source: str = "") -> None:
    """记一次「扩展活着」的证据（认领作业时调用）。

    `source` 只用于诊断（哪个作业源被认领），不参与判定。
    写失败**不影响**认领主流程 —— 它只是可观测性设施，不能反过来弄坏发送。
    """
    now = now or datetime.now()
    state = {
        "last_seen_at": now.isoformat(timespec="seconds"),
        "last_source": _s(source),
        "last_seen_epoch": now.timestamp(),
    }
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_name(f"{STATE_FILE.name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(STATE_FILE))
    except Exception:  # noqa: BLE001
        logger.warning("[ExtLiveness] 写活动记录失败（忽略，不影响认领）", exc_info=True)


def evaluate(state: Optional[dict] = None, stale_seconds: Optional[int] = None,
             now: Optional[float] = None) -> dict:
    """由活动记录判定扩展在线状态（纯函数，便于单测）。

    返回:
        {"status": "online"|"offline"|"unknown",
         "last_seen_at": str, "age_seconds": float|None,
         "stale_seconds": int, "reason": str}

    三态语义（**不要**把 unknown 当 offline，那会在每次重启后误报）：
      * `online`  —— 最近一次认领在阈值内；
      * `offline` —— 见过扩展，但已超过阈值没动静（浏览器被关/扩展被卸/掉登录）；
      * `unknown` —— 从未见过（服务刚起或记录被清），无从判断。
    """
    stale = LIVENESS_STALE_SECONDS if stale_seconds is None else int(stale_seconds)
    ref = datetime.now().timestamp() if now is None else float(now)
    st = state if isinstance(state, dict) else {}
    last_txt = _s(st.get("last_seen_at"))
    last = _parse_iso(last_txt)

    if last is None:
        return {"status": STATUS_UNKNOWN, "last_seen_at": last_txt,
                "age_seconds": None, "stale_seconds": stale,
                "reason": "尚无扩展认领记录（服务刚启动或记录被清理），无法判断在线状态"}

    age = ref - last
    if age > stale:
        return {"status": STATUS_OFFLINE, "last_seen_at": last_txt,
                "age_seconds": round(age, 1), "stale_seconds": stale,
                "reason": (f"扩展已 {_humanize(age)} 未认领任何作业"
                           f"（阈值 {_humanize(stale)}）—— 浏览器多半已关闭或扩展未加载")}
    return {"status": STATUS_ONLINE, "last_seen_at": last_txt,
            "age_seconds": round(age, 1), "stale_seconds": stale,
            "reason": f"扩展 {_humanize(age)} 前还在认领作业"}


def check() -> dict:
    """读记录 + 判定，供业务侧直接调用。"""
    return evaluate(read_state())


def _humanize(seconds: float) -> str:
    """秒 → 人话（用于告警文案，避免让值班的人自己换算）。"""
    s = int(max(0, seconds))
    if s < 60:
        return f"{s} 秒"
    if s < 3600:
        return f"{s // 60} 分钟"
    h, m = divmod(s // 60, 60)
    return f"{h} 小时{m} 分钟" if m else f"{h} 小时"

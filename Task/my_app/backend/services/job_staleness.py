# -*- coding: utf-8 -*-
"""作业文件「僵尸 running」判定的共享小工具（2026-10-01 事故）。

## 为什么单独抽这一层

两个作业源（发图 `whatsapp_ext_service`、TT 告警文本 `tt_alarm_job`）
各自维护一份作业文件，但**状态机与认领语义完全同构**：认领即置 `running`
作为乐观锁，扩展回报后落终态。于是两者有**同一个失效模式**——
扩展认领后不回报（浏览器被关、扩展崩了、进程被杀），作业永远停在 `running`，
而认领只认 `pending`，**整个作业邮箱被一个僵尸永久堵死**，且任务侧因为
「本轮候选 0 单」提前返回 `success=True`，监控全绿、群里静默收不到推送。

2026-10-01 实测即为此：04:55 的文本作业被 09:11 认领后无回报，中间数小时推送全堵。

两个源都要修，且**判定口径必须一致**（否则一个源改了另一个漏改，下次还会踩），
故把「是否僵尸」这一条判断收敛到本模块，两个源共用。

纯函数，不碰文件与配置，可独立单测。
"""
from datetime import datetime
from typing import Any, Optional


def s(val: Any) -> str:
    """None / 空串 → ''；其余转字符串去空白（与各作业模块的 `_s` 同义）。"""
    return "" if val is None else str(val).strip()


def parse_iso(value: Any) -> Optional[float]:
    """解析 `claimed_at` 的 ISO 文本 → epoch 秒；缺失或不可解析返回 None。"""
    txt = s(value)
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt).timestamp()
    except Exception:  # noqa: BLE001
        return None


def is_stale_running(job: Optional[dict], stale_seconds: int,
                     now: Optional[float] = None) -> bool:
    """作业是否「running 且认领已久未回报」= 僵尸。

    Args:
        job:          作业字典（None 直接判否）。
        stale_seconds: 判定阈值（秒）。
        now:          当前 epoch 秒，便于测试注入。

    `claimed_at` 缺失或不可解析时**保守判为僵尸**：正常认领会写入该字段，
    缺失说明是旧版本写入或被人手改过 —— 无从证明它还在被发送，
    而「堵着不动」的代价明显更大。

    ⚠️ 阈值必须远大于正常发送耗时：立即释放会让多个扩展实例**重复发送同一批告警**。
    """
    if not isinstance(job, dict):
        return False
    if s(job.get("status")) != "running":
        return False
    ts = parse_iso(job.get("claimed_at"))
    if ts is None:
        return True
    ref = datetime.now().timestamp() if now is None else float(now)
    return (ref - ts) > int(stale_seconds)

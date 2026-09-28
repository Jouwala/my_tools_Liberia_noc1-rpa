"""TT 告警作业文件传输层（落盘 / 认领 / 回报 / 等待）。

从 `tt_alarm_whatsapp_service` 拆出，职责单一：**管理 `data/tt_alert_job.json`
这个「后端 ↔ 浏览器扩展」之间的作业邮箱**，不关心 TT 业务口径。

模型与 `backend/services/whatsapp_ext_service.py` 同构（后端投递 → 扩展认领 →
扩展回报 → 后端读取结果），但**用独立的作业文件**，避免与发图作业互相覆盖。

状态机：`pending → running → done | failed`。
  * `pending`  —— 已投递，等扩展认领
  * `running`  —— 扩展已认领（置此态即可防止多个扩展实例重复发送）
  * `done`/`failed` —— 扩展已回报

写文件一律用「临时文件 + `os.replace`」原子替换：队列模式下任务进程与 Web API
进程是两个进程，非原子写会读到半截 JSON。该文件与数据库无关，sqlite / pg
两种模式都适用。

⚠️ **不要**把 `wait_for_job_result` 的超时当作发送成功 —— `confirmed=False` 表示
未获确认，调用方据此**绝不能**把发送状态置 'Y'，否则就是伪造成功。
"""
import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("tt_alarm_whatsapp")

# 作业文件位置（与 whatsapp_ext_service 的作业文件刻意分开）
JOB_FILE = Path(__file__).resolve().parent / "data" / "tt_alert_job.json"

# 等待扩展回报的最长秒数（与 whatsapp_ext_service.WAIT_SECONDS 同量级）。
# 每 15 分钟一轮，留足但不越界：扩展轮询约 1 分钟一次 + 实际发送耗时。
WAIT_SECONDS = int(os.environ.get("TT_ALERT_WAIT_SECONDS", "600"))
POLL_INTERVAL = float(os.environ.get("TT_ALERT_POLL_INTERVAL", "2.0"))


def _s(val: Any) -> str:
    """None / 空串 → ''；其余转字符串去空白（本模块不依赖业务层的 _s）。"""
    return "" if val is None else str(val).strip()


def write_job(job: Dict[str, Any]) -> None:
    """原子写作业文件（临时文件 + os.replace，Windows 上原子）。"""
    JOB_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = JOB_FILE.with_name(f"{JOB_FILE.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(JOB_FILE))


def read_job() -> Optional[Dict[str, Any]]:
    """读作业文件；不存在或损坏返回 None。"""
    try:
        with open(JOB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001
        logger.warning("[TTAlert] 读作业文件失败", exc_info=True)
        return None


def dispatch(messages: List[Dict[str, str]], groups: List[str]) -> Dict[str, Any]:
    """投递一批文本消息作业（只负责落盘，不等待回报）。

    messages: [{"tt_no": ..., "text": ...}, ...]
    返回 {ok, job_id, groups, dispatched, errors}。
    """
    result: Dict[str, Any] = {"ok": False, "job_id": None, "groups": list(groups),
                              "dispatched": 0, "errors": []}
    if not groups:
        # 正常情况下调用方已用默认群兜底，走到这里说明显式传了空列表；
        # 群组是消息的必填投递地址，空地址无意义，直接拒发。
        result["errors"].append("未指定 WhatsApp 群组，拒绝投递（群组为空）")
        return result
    if not messages:
        result["errors"].append("无可发送消息")
        return result

    job = {
        "job_id": datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8],
        "kind": "text",
        "status": "pending",
        "groups": list(groups),
        "messages": messages,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "claimed_at": None,
        "completed_at": None,
        "result": None,
    }
    try:
        write_job(job)
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"写作业文件失败: {e}")
        return result

    result["ok"] = True
    result["job_id"] = job["job_id"]
    result["dispatched"] = len(messages)
    logger.info("[TTAlert] 已投递文本作业 %s（%s 条 → 群 %s）",
                job["job_id"], len(messages), groups)
    return result


def claim_pending_job() -> Optional[Dict[str, Any]]:
    """供扩展轮询：认领一个待发作业（无则 None）。

    只认领 `status == 'pending'` 的作业，认领即置 `running`，
    避免多个扩展实例重复发送同一作业。
    """
    job = read_job()
    if not job or job.get("status") != "pending":
        return None
    job["status"] = "running"
    job["claimed_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        write_job(job)
    except Exception:  # noqa: BLE001
        logger.warning("[TTAlert] 认领作业写回失败", exc_info=True)
        return None
    return job


def complete_job(job_id: str, result: Dict[str, Any]) -> bool:
    """供扩展回报：把作业置为终态。job_id 不匹配返回 False。"""
    job = read_job()
    if not job or _s(job.get("job_id")) != _s(job_id):
        return False
    job["status"] = "done" if result.get("ok") else "failed"
    job["completed_at"] = datetime.now().isoformat(timespec="seconds")
    job["result"] = {
        "ok": bool(result.get("ok")),
        "sent": list(result.get("sent") or []),
        "errors": list(result.get("errors") or []),
        "elapsed_seconds": result.get("elapsed_seconds"),
    }
    try:
        write_job(job)
    except Exception:  # noqa: BLE001
        logger.warning("[TTAlert] 回报作业写回失败", exc_info=True)
        return False
    return True


def wait_for_job_result(job_id: str, wait_seconds: Optional[int] = None) -> Dict[str, Any]:
    """阻塞等待扩展回报结果（或超时）。

    返回 {confirmed, ok, timed_out, sent, errors, job_status}。
    `confirmed=False` 表示**未获确认**（超时或作业未被认领）—— 调用方据此
    绝不能把发送状态置 'Y'。
    """
    limit = WAIT_SECONDS if wait_seconds is None else int(wait_seconds)
    deadline = time.time() + limit
    last_status = None
    while time.time() < deadline:
        job = read_job()
        if job is not None and _s(job.get("job_id")) == _s(job_id):
            last_status = job.get("status")
            if last_status in ("done", "failed"):
                res = job.get("result") or {}
                return {
                    "confirmed": True,
                    "ok": bool(res.get("ok")),
                    "timed_out": False,
                    "sent": list(res.get("sent") or []),
                    "errors": list(res.get("errors") or []),
                    "job_status": last_status,
                }
        time.sleep(POLL_INTERVAL)
    return {
        "confirmed": False,
        "ok": False,
        "timed_out": True,
        "sent": [],
        "errors": [f"浏览器扩展未在 {limit}s 内回报（作业状态={last_status}）。"
                   f"请确认：Chrome 已打开并登录 WhatsApp Web、"
                   f"扩展已安装且启用了纯文本发送能力"],
        "job_status": last_status,
    }

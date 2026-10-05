# -*- coding: utf-8 -*-
"""P1 告警走 Baileys 推送通道（whatsapp-kb-bot 的 `src/notify.js`）。

## 为什么换掉 Chrome 扩展通道（2026-10-01）

扩展通道的**全部复杂度都来自「操作网页」**：要浏览器常开、要页面聚焦（粘贴依赖焦点）、
每 2~3 周人工扫码，且发送确认只能靠数 DOM 气泡去猜 —— WhatsApp 是虚拟列表，气泡会
被回收，实测会把「其实发出去了」判成失败并重发（2026-09-29 出过重复告警事故），
于是不得不在扩展侧堆三层防线（清空输入框 / 双信号确认 / 超时三分支）。

Baileys 走 WhatsApp 的 WebSocket 协议，**不碰页面**，于是：

| | 扩展通道 | 本通道 |
| --- | --- | --- |
| 需要浏览器常开 | 是 | **否** |
| 需要页面聚焦 | 是 | **否** |
| 人工扫码 | 每 2~3 周 | **否**（凭据落盘 `data/auth`） |
| 发送确认 | 数 DOM 气泡猜 | **`sendMessage()` 返回 message id** |
| 虚拟列表 / React 干扰 | 全要处理 | **不存在** |
| 防重复三层防线 | 全需要 | **不需要** |

**通道地址**：作业文件 `whatsapp-kb-bot/data/notify_job.json`，
心跳文件 `whatsapp-kb-bot/data/notify_heartbeat.json`。
两者都在 bot 项目目录内（推送进程与 bot 共用同一份凭据，但**独立进程、互不影响**）。

## 为什么推送进程与问答 bot 分开

`whatsapp-kb-bot/src/index.js`（问答入口）的启动路径上有三道硬门槛，任一不过就
`process.exit(1)`，其中第二道要求**本地 Ollama 必须在跑**。而推送一条文本告警
**完全用不到模型与索引** —— 2026-10-01 实测 Ollama 未运行，`index.js` 直接退出，
连本该可用的发送能力一起没了。

若把告警接在那种入口上，**Ollama 一挂就等于告警通道全断**：用一个无关依赖的
可用性去赌告警可用性，不可接受。故推送由独立入口 `src/notify.js` 承担，
它只 import 凭据与连接，不 import `rag.js` / `llm.js` / `ollama.js`。

## 与扩展通道的状态机差异

扩展通道是「扩展主动来认领」（后端不推，等扩展拉）。本通道沿用**同一种信箱语义**
（投递 `pending` → 消费端认领置 `running` → 置 `done`/`failed`），但**消费端不回写
`running` 的「多实例互斥」那一层** —— `notify.js` 是单进程单实例，不存在多实例
重复认领的问题，省掉一次写盘。

> ⚠️ **但 `running` 本身不能省（2026-10-05 修复）**：上述「省掉一次写盘」最初被
> 实现成了「认领时不改状态」，结果踩中了**单实例内的重入** —— `notify.js` 的轮询是
> `setInterval(async () => { await runJob(...) })`，而 `setInterval` **不等待**上一次
> 异步回调结束；`sendMessage()` 的网络往返期间作业文件一直是 `pending`，于是每个 tick
> 都重新认领同一单并重发（仿真实测同一单被发 5 次）。
> 现在 `notify.js` 的 `claimJob` **认领即原地置 `running` + `claimed_at`**，
> 并保留基于时间的僵尸回收。这里的教训是：**单实例 ≠ 无并发**，
> `setInterval` + async 回调本身就是并发来源。

僵尸判定仍保留（消费端崩溃时作业会停在 `running`/`pending`，
由 `notify.js` 的 `STALE_RUNNING_MS` 回收，`wait_for_job_result` 超时兜底）。
"""
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("wa_notify")

# bot 项目根目录。默认按工作区相对位置解析，可用环境变量覆盖（便于测试与迁移）。
_BOT_ROOT = Path(os.environ.get(
    "WA_BOT_ROOT",
    str(Path(__file__).resolve().parents[3] / "whatsapp-kb-bot"),
))

JOB_FILE = _BOT_ROOT / "data" / "notify_job.json"
HEARTBEAT_FILE = _BOT_ROOT / "data" / "notify_heartbeat.json"

# 等待消费端回报的上限。Baileys 发送是秒级的，不像扩展要等页面渲染，
# 故比扩展通道的 600s 短得多 —— 早失败早重试，不把 worker 占住。
WAIT_SECONDS = int(os.environ.get("WA_NOTIFY_WAIT_SECONDS", "120"))

# 心跳超过这个时长没更新即视为推送进程不在线。
HEARTBEAT_STALE_SECONDS = int(os.environ.get("WA_NOTIFY_HEARTBEAT_SECONDS", "300"))


def _s(val: Any) -> str:
    return "" if val is None else str(val).strip()


def _parse_iso(value: Any) -> Optional[float]:
    txt = _s(value)
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return None


def _write_job(job: Dict[str, Any]) -> None:
    """原子写：先写临时文件再 `os.replace`，避免消费端读到半截 JSON。

    后端（worker 进程）与推送进程是两个进程，非原子写会被读到半个文件 ——
    这与作业文件本身用不用数据库无关，是跨进程共享文件的固有问题。
    """
    JOB_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = JOB_FILE.with_name(f"{JOB_FILE.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(JOB_FILE))


def read_job() -> Optional[Dict[str, Any]]:
    try:
        with open(JOB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001
        logger.warning("[WANotify] 读作业文件失败", exc_info=True)
        return None


def is_online(stale_seconds: Optional[int] = None,
              now: Optional[float] = None) -> Dict[str, Any]:
    """推送进程是否在线（读心跳判定）。

    三态语义与 `ext_liveness` 保持一致，**不要**把 unknown 当离线：
    推送进程刚重启时心跳还没写，判离线会在每次重启后误报一次，让人对告警脱敏。
    """
    stale = HEARTBEAT_STALE_SECONDS if stale_seconds is None else int(stale_seconds)
    ref = datetime.now().timestamp() if now is None else float(now)
    try:
        with open(HEARTBEAT_FILE, "r", encoding="utf-8") as f:
            hb = json.load(f)
    except Exception:  # noqa: BLE001
        hb = None

    if not isinstance(hb, dict):
        return {"status": "unknown", "reason": "尚无推送进程心跳（进程未启动或刚重启）"}

    if not hb.get("connected"):
        return {"status": "offline", "at": _s(hb.get("at")),
                "reason": "推送进程在运行但**未连接**（可能需要重新扫码 `npm run relogin`）"}

    # 进程存活校验：心跳文件是**进程被杀时来不及更新的**。
    # 实测 `Stop-Process -Force` 之后文件里仍是 `connected: true` + 旧时间戳，
    # 若只看时间戳，最坏会有 `stale` 秒（默认 5 分钟）的「假健康」窗口 ——
    # 而这段时间里告警投出去其实没人消费。
    # 故只要心跳带了 `pid` 就顺手核对进程是否还在，能把窗口从 5 分钟压到一次轮询。
    pid = hb.get("pid")
    if isinstance(pid, int) and pid > 0 and not _pid_alive(pid):
        return {"status": "offline", "at": _s(hb.get("at")), "pid": pid,
                "reason": f"推送进程（pid {pid}）已不存在，但心跳文件未及更新"}

    ts = _parse_iso(hb.get("at"))
    if ts is None:
        return {"status": "unknown", "reason": "心跳时间不可解析"}
    age = ref - ts
    if age > stale:
        return {"status": "offline", "at": _s(hb.get("at")), "age_seconds": round(age, 1),
                "reason": f"推送进程已 {_humanize(age)} 无心跳（阈值 {_humanize(stale)}）"}
    return {"status": "online", "at": _s(hb.get("at")), "age_seconds": round(age, 1),
            "groups": hb.get("groups"), "reason": f"{_humanize(age)} 前心跳正常"}


def _pid_alive(pid: int) -> bool:
    """该 pid 是否仍存活。

    ## 为什么不用 `os.kill(pid, 0)`（实测踩过）

    直觉写法是 `os.kill(pid, 0)`，在独立 python 进程里**确实**能 work，
    但在本项目的**生产进程与 pytest 里都会失效**：

    `backend/main.py:28-33` 在 `stdout` 非 tty 时（看门狗托管的线上模式、
    以及 pytest 的捕获模式）会调 `ctypes.windll.kernel32.FreeConsole()` 脱离控制台。
    控制台一脱离，标准句柄即失效，此后 `os.kill(pid, 0)` 抛
    `OSError: [Errno 9] EBADF`（winerror 6 = ERROR_INVALID_HANDLE）——
    **即使 pid 就是自己、进程明明活着**。

    后果：判活被误判成「已死」，把一次正常发送报成通道离线。
    2026-10-01 实测：`pytest tests/test_whatsapp_job_claim.py tests/test_wa_notify_service.py`
    下 `_pid_alive(os.getpid())` 返回 `False`；单独跑该文件却正常
    （单跑时收集顺序不同，FreeConsole 尚未执行）—— 是典型的顺序相关故障。

    故改用 **`OpenProcess` + `GetExitCodeProcess`**，与 `backend/worker.py:111`
    的 `_pid_alive` 同一套做法（那里的注释也记录了同类教训）。
    请求 `PROCESS_QUERY_LIMITED_INFORMATION` 只需极低权限，且不依赖控制台句柄。

    ## 保守方向

    探测本身出任何意外（ctypes 不可用、权限异常、pid 类型非法）一律**判为存活**：
    宁可漏报一次「通道离线」，也不要因探测代码自身的问题误报，
    那会让人对告警脱敏。真正的兜底是心跳时间阈值。
    """
    try:
        pid = int(pid)
        if pid <= 0:
            return True
    except (TypeError, ValueError):
        return True

    if sys.platform == "win32":
        try:
            import ctypes
            import ctypes.wintypes  # noqa: F401

            kernel32 = ctypes.windll.kernel32
            # 必须显式声明 restype/argtypes：ctypes 默认按 32 位有符号 int 解释返回值，
            # 64 位句柄高位被截断后可能变成 0/负数，把存活进程误判为不存在
            # （worker.py:132-135 记录过由此引发的事故）。
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.OpenProcess.argtypes = [
                ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32,
            ]
            h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            try:
                # 还要看退出码：被 taskkill /F 终止但尚未回收的进程，
                # OpenProcess 仍会成功，但线程已全销毁、不可能再干活。
                # STILL_ACTIVE = 259。
                code = ctypes.c_ulong(0)
                kernel32.GetExitCodeProcess.restype = ctypes.c_int
                kernel32.GetExitCodeProcess.argtypes = [
                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong),
                ]
                if kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
                    return code.value == 259
                return True
            finally:
                kernel32.CloseHandle(ctypes.c_void_p(h))
        except Exception:  # noqa: BLE001
            return True

    # POSIX：kill(pid, 0) 语义可靠，无 Windows 那种控制台句柄问题
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        import errno as _errno
        return getattr(e, "errno", None) == _errno.EPERM
    except Exception:  # noqa: BLE001
        return True


def _humanize(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return f"{s} 秒"
    if s < 3600:
        return f"{s // 60} 分钟"
    h, m = divmod(s // 60, 60)
    return f"{h} 小时{m} 分钟" if m else f"{h} 小时"


def check_channel_before_dispatch(out: Dict[str, Any], due_count: int,
                                  resend_minutes: int) -> None:
    """投递前查推送通道在线状态，离线则把告警塞进 `out["warnings"]`。

    放在本模块而不是业务编排层：它本质是**通道自感知** —— 与 `is_online`
    读同一份心跳、用同一套三态语义，调用方（P1 推送任务）只负责把结果
    汇进任务结果里。

    ## 为什么不等超时

    告警链路依赖一个**常驻的推送进程**。它没在跑时，作业投出去没人消费，
    任务要干等 `WAIT_SECONDS` 才发现，而这段时间值班群其实一条告警都收不到 ——
    2026-10-01 实测正是如此（04:15~04:55 连续 4 轮未达、群内静默，
    作业还把邮箱堵死 4.3 小时）。

    所以这里**不等超时**：投递前先看推送进程的心跳，没有就立刻报出去，
    把「几分钟后才知道」压缩成「这一轮就知道」。

    ## 三态语义（与 `ext_liveness` 同口径）

      * `online`  → 静默（正常路径）；
      * `offline` → 追加 warning，经 `task_runner` 汇总成微信/邮件喊人；
      * `unknown` → **不告警**，仅记日志。推送进程刚重启时心跳还没写，
        此时若判离线，每次重启都会误报一次，会让人对告警脱敏。

    只写 `out`，不抛异常：在线检查属可观测性设施，不能反过来弄坏发送主流程。
    """
    try:
        live = is_online()
    except Exception:  # noqa: BLE001
        logger.warning("[WANotify] 推送通道在线检查异常（忽略，继续发送）", exc_info=True)
        return

    out["channel_status"] = live.get("status")
    out["channel_heartbeat_at"] = live.get("at") or None

    if live.get("status") == "offline":
        warn = (f"P1 告警推送通道离线：{live.get('reason')}。本轮 {due_count} 单告警"
                f"**大概率发不出去** —— 请在 whatsapp-kb-bot 目录确认推送进程在运行"
                f"（`node src/notify.js --check` 可自检），必要时 `npm run relogin` 重新扫码。"
                f"未确认发送的单会按 {resend_minutes} 分钟节流重推")
        out["warnings"].append(warn)
        logger.warning("[WANotify] %s", warn)
    elif live.get("status") == "unknown":
        logger.info("[WANotify] 推送通道状态未知（本轮不告警）：%s", live.get("reason"))


def dispatch(messages: List[Dict[str, Any]], groups: List[str]) -> Dict[str, Any]:
    """投递一批文本到推送通道。

    Returns:
        {"ok": bool, "job_id": str|None, "dispatched": int, "errors": [str]}

    `messages` 形如 `[{"tt_no": ..., "text": ...}]`，`groups` 是**群名**列表
    （推送端负责把群名解析成 JID；解析不到会整单失败并说明原因，不会静默少发）。
    """
    result: Dict[str, Any] = {"ok": False, "job_id": None, "dispatched": 0, "errors": []}

    if not messages:
        result["errors"].append("没有要发送的消息")
        return result
    if not groups:
        result["errors"].append("没有配置目标群")
        return result

    job = {
        "job_id": datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8],
        "kind": "text",
        "status": "pending",
        "groups": list(groups),
        "messages": messages,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "completed_at": None,
        "result": None,
    }

    # 投递前先覆盖旧作业：上一次的 done/failed 会挡住新作业（消费端只认 pending）。
    # 若旧作业仍是 pending，说明上一轮投出去没人处理 —— 记录但不阻断，
    # 新作业直接覆盖它（告警是"最新状态最重要"，堆积旧单只会延迟当前告警）。
    old = read_job()
    if old and _s(old.get("status")) == "pending":
        logger.warning("[WANotify] 上一单 %s 仍处 pending 未被消费，将被本次覆盖",
                       old.get("job_id"))

    try:
        _write_job(job)
    except Exception as e:  # noqa: BLE001
        result["errors"].append(f"写作业文件失败: {e}")
        return result

    result["ok"] = True
    result["job_id"] = job["job_id"]
    result["dispatched"] = len(messages)
    logger.info("[WANotify] 已投递 %s（%s 条 → 群 %s）", job["job_id"], len(messages), groups)
    return result


def wait_for_job_result(job_id: str, timeout: Optional[int] = None) -> Dict[str, Any]:
    """等消费端把作业置为终态。

    Returns:
        {"ok": bool, "confirmed": bool, "sent": [tt_no...], "message_ids": {...},
         "errors": [...], "timed_out": bool}

    ⚠️ **绝不要**把超时当作发送成功：`confirmed=False` 表示未获确认，
    调用方据此**不能**把 `send_status` 置 'Y'，否则就是伪造成功。
    """
    timeout = WAIT_SECONDS if timeout is None else int(timeout)
    deadline = time.time() + timeout
    out: Dict[str, Any] = {"ok": False, "confirmed": False, "sent": [],
                           "message_ids": {}, "errors": [], "timed_out": False}

    while time.time() < deadline:
        job = read_job()
        if job is None:
            # 文件不存在 ≠ 被覆盖：推送进程刚启动、或还没来得及读，都会短暂读到 None。
            # 这里必须继续等，不能提前返回 —— 否则「推送进程启动慢一点」会被报成
            # 「作业被覆盖」，把一次正常发送误判成失败，进而触发重发（重复告警）。
            time.sleep(1)
            continue
        if _s(job.get("job_id")) != _s(job_id):
            # 真的被新作业覆盖了（下一轮投递写入），本单永远等不到结果
            out["errors"].append("作业已被新一轮投递覆盖，未获回报")
            return out

        status = _s(job.get("status"))
        if status in ("done", "failed"):
            rep = job.get("result") or {}
            sent = rep.get("sent") or []
            # sent 是 [{tt_no, jid, message_id}]；message_id 是服务端回执
            out["sent"] = [_s(x.get("tt_no")) for x in sent if isinstance(x, dict)]
            out["message_ids"] = {
                _s(x.get("tt_no")): _s(x.get("message_id"))
                for x in sent if isinstance(x, dict) and _s(x.get("tt_no"))
            }
            out["errors"] = [str(e) for e in (rep.get("errors") or [])]
            out["confirmed"] = True
            out["ok"] = bool(rep.get("ok"))
            return out

        time.sleep(1)

    out["timed_out"] = True
    out["errors"].append(
        f"推送进程未在 {timeout}s 内回报。请检查 whatsapp-kb-bot 的 src/notify.js 是否在运行"
        f"（可执行 node src/notify.js --check 自检）")
    return out

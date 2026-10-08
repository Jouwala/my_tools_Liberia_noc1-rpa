"""
WhatsApp 发送（Baileys 通道）—— 通过 whatsapp-kb-bot/src/notify.js 进程发送图片与文档。

与 whatsapp_ext_service（浏览器扩展通道）**并行**的第三种实现：
  - Playwright（whatsapp_service.run_whatsapp_send）：自启浏览器，发到 WhatsApp Web
  - 扩展（whatsapp_ext_service.run_whatsapp_send_ext）：用用户已登录的 WhatsApp Web 标签页
  - 本服务（whatsapp_send_baileys_service.run_whatsapp_send_baileys）：走 Baileys 协议直发

三者**共享同一份图片目录**（SITE_OUTAGE_DIR）与群组配置（GROUPS），
各自投递到**独立的作业文件**（互不抢作业）：

  - Playwright 自己起浏览器发送，不投递作业
  - 扩展投递到 data/whatsapp_ext_job.json，扩展侧栏的 background.js 轮询
  - 本服务投递到 data/whatsapp_send_baileys_job.json，notify.js 进程轮询

cron 时间错开（默认 0 3 * * * 与 Playwright / 扩展同 03:00；本任务的 default_cron
设 None 由 sync 页面手动启用，避免同时跑双份导致群内短时间收到两次同样的图）。

工作模型：
  1. 本服务 build_outbox_payload() 扫盘 + 写 items[].path（绝对路径）进作业
  2. notify.js 进程的轮询器认领（claim 即置 running + 原子写回）
  3. notify.js 按 (群 × 文件) 调用 sock.sendMessage({ image|document, ... })
  4. notify.js 回写 result（ok / groups_sent / errors）到作业文件
  5. 本服务轮询 result 出现 done/failed 后返回（task_runner 据此记任务历史）

为何走 Baileys 通道：
  - 官方 API 做不到「已有的群 + 群内被动响应」；扩展要走用户浏览器开 + 已登录；
  - Playwright 自启浏览器每 2~3 周掉登录 + WhatsApp Web DOM 改版失效；
  - Baileys 用「已关联设备」直连协议，回执是服务端 message id，**不是猜的**。

⚠️ ToS 风险：Baileys 是非官方库，违反 WhatsApp 服务条款，号码有被封风险。
   本服务用副号（与知识库机器人、P1 告警推送共用 auth-notify/）；
   群发限频由 notify.js 的 CONFIG.notify.fileSend 块控制（默认 6 图 + 1 文档 / 作业）。
"""
import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from backend.services.whatsapp_service import SITE_OUTAGE_DIR, GROUPS
from backend.services import job_staleness

logger = logging.getLogger("whatsapp_send_baileys")

# 任务最长等待 notify.js 回报的秒数
#   - 13 张图 + 1 文档 + 4 群，按默认 2s/条 + 8s/群 ≈ 200~250s 即可
#   - 网络盘波动 / notify 进程掉线 / 认领延迟都吃这份预算
#   - 600s 与 whatsapp_ext_service.WAIT_SECONDS 对齐，便于两条通道横向比较
WAIT_SECONDS = int(os.environ.get("WHATSAPP_BAILEYS_WAIT_SECONDS", "600"))
# 任务侧轮询作业文件的间隔（秒）
TASK_POLL_INTERVAL = float(os.environ.get("WHATSAPP_BAILEYS_POLL_INTERVAL", "1.0"))
# 僵尸作业判定阈值（秒）—— 与扩展通道取同量级（默认 1h）
STALE_RUNNING_SECONDS = int(os.environ.get("WHATSAPP_BAILEYS_STALE_RUNNING_SECONDS", "3600"))

# 作业文件：与 whatsapp_ext_job.json 物理隔离（两份任务不抢同一作业）。
# 位置：与扩展的 whatsapp_ext_job.json 同目录，便于运维一眼看全。
JOB_FILE = Path(__file__).resolve().parent / "data" / "whatsapp_send_baileys_job.json"

# 终态集合 —— ⚠️ **必须以 notify.js 的措辞为准**。
#
# 生产事故（2026-10-08）：本服务是从 `whatsapp_ext_service` 复制而来，
# 那里生产者（浏览器扩展）写 `completed`，于是等待循环写成只认
# `("completed", "failed")`。但 Baileys 侧的**生产者是 notify.js**，
# 它的 `finishFileJob` 写的是 **`done`**（见 notify.js:493）。
# 两边字面量不一致 → 成功作业永远等不到 → 每轮干等满 WAIT_SECONDS(600s)
# 后误报「notify.js 未回报」，超时兜底还会把已 `done` 的作业覆写成 `failed`。
# 实测：Success 0%，每次耗时恰好 ≈600s，而图片其实早已送达。
#
# 故终态集**同时接受** `done`（notify.js 规范，text 通道 tt_alarm_job /
# wa_notify_service 也用这个）与 `completed`（本模块自身 complete_job 的旧措辞，
# 保留以兼容 / 防回归）。`failed` 两边一致。
TERMINAL_STATUSES = ("done", "completed", "failed")


# ==========================================================
# 出图清单（直接复用 whatsapp_ext_service 的同款实现，
# 避免与 SITE_OUTAGE_DIR 排序规则在两处文件里分叉）
# ==========================================================
from backend.services.whatsapp_ext_service import build_outbox_payload  # noqa: E402


# ==========================================================
# 作业文件（原子写，跨进程共享 —— 后端 worker 与 notify.js 之间）
# ==========================================================
def _read_job() -> dict | None:
    try:
        if not JOB_FILE.exists():
            return None
        with open(JOB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("[WABaileys] 读取作业文件失败: %s", e)
        return None


def _write_job(job: dict) -> None:
    JOB_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = JOB_FILE.with_name(f"{JOB_FILE.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(JOB_FILE))


def create_pending_job() -> dict:
    """投递一个新的待发作业（会取代任何旧的 pending/running 作业）。

    与扩展通道的 create_pending_job 不同：本服务在**投递时**就把 items 写好
    （含磁盘绝对路径），而不是让认领方在 claim_pending_job 时再 build_outbox。
    因为 Baileys notify 进程跑在**另一台机器** / 另一进程时，它没有
    SITE_OUTAGE_DIR 路径，必须靠作业文件里写明的绝对路径找文件。
    """
    outbox = build_outbox_payload()
    job = {
        "job_id": datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8],
        "status": "pending",
        "groups": list(GROUPS),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "claimed_at": None,
        "completed_at": None,
        "result": None,
        # 关键：items 必须**在投递时**就写好含 path 的版本，notify.js 进程直接读盘
        "items": [
            {
                "kind": "image",   # 走 image 通道；xlsx 由 notify.js 按扩展名自动转 document
                "name": it["name"],
                "file_name": it["name"],
                "caption": it.get("caption", f"*{Path(it['name']).stem}*"),
                "mime": it.get("mime", "image/png"),
                "url": it.get("url", ""),   # 保留 HTTP 路径供扩展（万一）+ 排查
                "path": str(SITE_OUTAGE_DIR / it["name"]),  # 磁盘绝对路径，notify.js 凭此读盘
            }
            for it in outbox.get("items", [])
        ],
    }
    _write_job(job)
    logger.info(
        "[WABaileys] 已投递待发作业 %s（groups=%s，items=%d）",
        job["job_id"], job["groups"], len(job["items"]),
    )
    return job


def claim_pending_job() -> dict | None:
    """notify.js 认领作业：把状态置为 running（沿用扩展通道的语义）。

    notify.js 的轮询里**不**调本函数 —— 它直接读写作业文件（见
    whatsapp-kb-bot/src/notify.js 的 claimFileJob），避免 HTTP 跨进程的开销。
    本函数留给**同进程内的备用认领**（如未来需要 my_app 侧重投递时回写）。
    """
    job = _read_job()
    if not job:
        return None
    status = job_staleness.s(job.get("status"))
    if status == "running":
        if not job_staleness.is_stale_running(job, STALE_RUNNING_SECONDS):
            return None
        logger.warning(
            "[WABaileys] 作业 %s 自 %s 认领后 %ds 未回报，判定为僵尸并重新投递",
            job.get("job_id"), job.get("claimed_at"), STALE_RUNNING_SECONDS,
        )
    elif status != "pending":
        return None

    job["status"] = "running"
    job["claimed_at"] = datetime.now().isoformat(timespec="seconds")
    _write_job(job)
    return job


def complete_job(job_id: str, result: dict) -> bool:
    """notify.js 回报结果：把作业标记为终态（`done`/`failed`）并落盘。

    幂等：作业已到终态时，重复回报按 no-op 处理（content 端直报与
    任务侧轮询可能各到一次）。

    ⚠️ 成功措辞用 **`done`**（与 notify.js 的 `finishFileJob` 一致），
    不是 `completed` —— 见 TERMINAL_STATUSES 的事故注释。
    """
    job = _read_job()
    if not job or job.get("job_id") != job_id:
        logger.warning("[WABaileys] 回报的 job_id 不匹配（可能已被新作业取代）: %s", job_id)
        return False
    if job.get("status") in TERMINAL_STATUSES:
        logger.info("[WABaileys] 作业 %s 已为终态(%s)，忽略重复回报", job_id, job.get("status"))
        return True
    ok = bool(result.get("ok"))
    job["status"] = "done" if ok else "failed"
    job["completed_at"] = datetime.now().isoformat(timespec="seconds")
    job["result"] = result
    _write_job(job)
    logger.info(
        "[WABaileys] 作业 %s 回报 ok=%s groups_sent=%s errors=%d",
        job_id, ok, result.get("groups_sent", []), len(result.get("errors", [])),
    )
    return True


# ==========================================================
# 任务入口（供 task_registry 的 whatsapp_send_baileys 调用）
# ==========================================================
def run_whatsapp_send_baileys() -> dict:
    start_time = time.time()
    result = {
        "success": False,
        "method": "baileys",
        "groups_sent": [],
        "errors": [],
        "elapsed_seconds": 0,
    }

    if not GROUPS:
        result["errors"].append("未配置群组（环境变量 WHATSAPP_GROUPS 为空）")
        result["elapsed_seconds"] = round(time.time() - start_time, 2)
        return result
    if not SITE_OUTAGE_DIR.exists():
        result["errors"].append(f"图片目录不存在: {SITE_OUTAGE_DIR}")
        result["elapsed_seconds"] = round(time.time() - start_time, 2)
        return result

    job = create_pending_job()
    job_id = job["job_id"]
    deadline = start_time + WAIT_SECONDS
    logger.info("[WABaileys] 等待 notify.js 进程认领并回报（最长 %ds）…", WAIT_SECONDS)

    while time.time() < deadline:
        time.sleep(TASK_POLL_INTERVAL)
        j = _read_job()
        # ⚠️ 必须认 notify.js 的 `done`（不是只认 `completed`）—— 2026-10-08 事故根因。
        # 详见 TERMINAL_STATUSES 的注释。
        if j and j.get("job_id") == job_id and j.get("status") in TERMINAL_STATUSES:
            ext = j.get("result") or {}
            result["groups_sent"] = ext.get("groups_sent", [])
            result["errors"] = list(ext.get("errors", []))
            result["success"] = bool(ext.get("ok"))
            result["notify_elapsed_seconds"] = ext.get("elapsed_seconds")
            break
    else:
        result["errors"].append(
            f"notify.js 进程未在 {WAIT_SECONDS}s 内回报。"
            "请检查：whatsapp-kb-bot/src/notify.js 是否在跑、心跳文件"
            " data/notify_heartbeat.json 是否新鲜、凭据 auth-notify/ 是否有效。"
        )
        # 超时兜底：把作业标记为 failed，避免 job 文件永远停在 running。
        # ⚠️ 只在**仍是 running/pending** 时才兜 —— 若生产者已回终态（done/failed），
        # 绝不能覆写：那会用 failed 盖掉真实的成功记录（2026-10-08 事故的次生污染）。
        j = _read_job()
        if j and j.get("job_id") == job_id and j.get("status") not in TERMINAL_STATUSES:
            j["status"] = "failed"
            j["completed_at"] = datetime.now().isoformat(timespec="seconds")
            j["result"] = {"ok": False, "groups_sent": [], "errors": list(result["errors"])}
            _write_job(j)

    result["elapsed_seconds"] = round(time.time() - start_time, 2)
    logger.info(
        "[WABaileys] 完成 job=%s success=%s groups=%s 用时 %.2fs",
        job_id, result["success"], result["groups_sent"], result["elapsed_seconds"],
    )
    return result


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(name)s %(levelname)s: %(message)s")
    print(f"图片目录: {SITE_OUTAGE_DIR}")
    print("群组:", GROUPS)
    r = run_whatsapp_send_baileys()
    print("结果:", r)

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


def build_items(files: list, captions: list | None = None) -> list:
    """把显式的文件路径清单转成作业 items（含磁盘绝对路径 + mime + 备注）。

    与 create_pending_job 的 items 结构一致（notify.js 直接读 ``path`` 落盘文件），
    区别是本函数**不扫盘**：调用方给出确切的文件清单与备注，供 SP 报表这类
    「发指定产物」的任务复用（它的产物不在 SITE_OUTAGE_DIR，也无法靠扫盘得到）。

    - **kind 必须按扩展名显式区分 image / document**。notify.js 的判据是
      ``kind`` 存在时**只看 kind**，缺失时才按扩展名兜底（见 notify.js:565）——
      所以把 xlsx 的 kind 写成 image 会让它走 ``sendMessage({image: <xlsx字节>})``：
      服务端收下并返回 message id（**误判成功**），但群里只显示成一张损坏的图片，
      **excel 文件并没有发出去**。2026-10-11 手动执行 SP Online 报表就踩了这个坑
      （日志 4 条全 "已发送"，群里只见 2 张图）。
    - captions 不足时按文件名回退 ``*<stem>*``，与既有扫盘逻辑一致。
    """
    files = [str(f) for f in (files or [])]
    captions = list(captions or [])
    items = []
    for i, path in enumerate(files):
        # ⚠️ 必须 resolve 成**绝对路径**：notify.js 是另一个进程、cwd 是
        # whatsapp-kb-bot/，相对路径会被它按自己的 cwd 解析 → ENOENT 读盘失败。
        # 2026-10-11 实测踩到：传 "data/sp_email/x.png" 被解析成
        # whatsapp-kb-bot/data/sp_email/x.png（不存在）。
        p = Path(path).resolve()
        cap = captions[i] if i < len(captions) and captions[i] else f"*{p.stem}*"
        items.append({
            "kind": "image" if _is_image_name(p.name) else "document",
            "name": p.name,
            "file_name": p.name,
            "caption": cap,
            "mime": _mime_for_name(p.name),
            "url": "",                     # 无 HTTP 通道，留空（notify.js 只认 path）
            "path": str(p),                # 磁盘绝对路径，notify.js 凭此读盘
        })
    return items


# 图片扩展名集合 —— 必须与 notify.js 的 isDoc 判据**完全一致**（png/jpg/jpeg/gif/webp），
# 否则两处对「什么是图片」的定义分叉，又会出现「xlsx 被当图片发」的错。
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def _is_image_name(name: str) -> bool:
    return Path(name).suffix.lower() in _IMAGE_EXTS


_MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".zip": "application/zip",
}


def _mime_for_name(name: str) -> str:
    return _MIME_BY_EXT.get(Path(name).suffix.lower(), "application/octet-stream")


def dispatch_items(items: list, groups: list, max_images: int | None = None,
                   max_documents: int | None = None) -> dict:
    """把给定的 items 投递给 Baileys（notify.js）并发到 groups，等待回报。

    返回 ``{"ok": bool, "job_id": str, "groups_sent": [...], "errors": [...],
    "timed_out": bool, "confirmed": bool}``。

    ``ok`` 语义（供上层回退判据使用）：
      - true  = notify.js 回报成功、groups_sent 非空、**且没有任何单项失败**；
      - false = 投递被拒 / 等待超时 / 回报失败 / 零确认 / 单项有错 —— 任一即视为本通道
        失败，交由调用方的 fallback 处理。

    ⚠️ 为什么「单项有错」也算失败：notify.js 的 `ok = groupsSent.length > 0` ——
    只要**任一** item 送达就报 ok，而读盘失败 / 空文件 / 配额跳过的 item 只进
    `errors`。若此处只认 ok，就会把「漏发一个附件」当成整体成功（正是本项目
    历史上 `_fast_send_file` 静默丢文件那类事故）。故这里把 errors 非空也判失败，
    由 Playwright 回退（无配额上限）兜住。

    ``max_images`` / ``max_documents``：notify.js 单作业配额（默认 6 / 1）。
    作业超出配额时 notify.js 会**静默跳过**超出的 item 且仍可能报 ok，因此这里在
    投递前**主动拒绝**超额作业（返回 ok=False，交给回退通道），绝不把「截断发送」
    当成成功。传 None 表示不做上限检查。
    """
    job = {
        "job_id": datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8],
        "status": "pending",
        "groups": list(groups),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "claimed_at": None,
        "completed_at": None,
        "result": None,
        "items": list(items),
    }
    # 文件存在性前置检查：缺失文件若投出去，notify.js 会「跳过该 item + 记 errors」，
    # 虽被下面 ok 判据拦成失败，但白等一轮网络往返。投递前直接拒绝更快、更明确。
    missing = [str(it.get("path")) for it in job["items"]
               if not Path(str(it.get("path") or "")).is_file()]
    if missing:
        return {"ok": False, "job_id": job["job_id"], "groups_sent": [],
                "errors": [f"文件不存在，拒绝投递: {', '.join(missing[:3])}"
                           + (" 等" if len(missing) > 3 else "")],
                "timed_out": False, "confirmed": False}

    # 配额前置检查：超出 notify.js 单作业上限的 item 会被**静默跳过**（只记日志、
    # 不进 errors、仍可能报 ok）→ 绝不投递这种作业，直接让路给回退通道。
    # 分类口径必须与 notify.js 完全一致（见其 runFileJob）：按扩展名判 image/document，
    # 图片扩展名固定为 png/jpg/jpeg/gif/webp，其余算文档。分别对 **两个独立配额** 计数
    # —— 只比总数会漏掉「图没超但文档超」的情形（SP WhatsApp 报表就是 4 图 + 2 文档，
    # 文档配额默认 1，第二份 xlsx 会被静默丢掉）。
    n_img = n_doc = 0
    for it in job["items"]:
        name = str(it.get("file_name") or it.get("name") or "")
        if _is_image_name(name):
            n_img += 1
        else:
            n_doc += 1
    over = []
    if max_images is not None and n_img > max_images:
        over.append(f"图片 {n_img} 张 > 上限 {max_images}")
    if max_documents is not None and n_doc > max_documents:
        over.append(f"文档 {n_doc} 份 > 上限 {max_documents}")
    if over:
        return {"ok": False, "job_id": job["job_id"], "groups_sent": [],
                "errors": [f"作业超出 Baileys 单作业配额（{'；'.join(over)}），"
                           "改由回退通道发送（避免静默截断）"],
                "timed_out": False, "confirmed": False}
    # 单作业文件互斥：notify.js 只认一个 whatsapp_send_baileys_job.json，若已有一个
    # 未被认领（pending）或仍在跑（running，且未超僵尸阈值）的作业，直接投递会把它
    # 覆盖掉 → 前一个作业静默丢失。正常情况下 SP 三个任务已按 cron 错峰（见
    # task_registry），且独立的 whatsapp_send_baileys 任务默认 enabled=False，
    # 这里再兜一道，避免「任务被手动启用 / 重试重叠」时互相踩踏。
    existing = _read_job()
    if existing:
        st = job_staleness.s(existing.get("status"))
        if st == "pending":
            return {"ok": False, "job_id": job["job_id"], "groups_sent": [],
                    "errors": [f"Baileys 已有一个待认领作业 {existing.get('job_id')}，本次投递让路"],
                    "timed_out": False, "confirmed": False}
        if st == "running" and not job_staleness.is_stale_running(existing, STALE_RUNNING_SECONDS):
            return {"ok": False, "job_id": job["job_id"], "groups_sent": [],
                    "errors": [f"Baileys 作业 {existing.get('job_id')} 仍在运行，本次投递让路"],
                    "timed_out": False, "confirmed": False}
    _write_job(job)
    job_id = job["job_id"]
    logger.info(
        "[WABaileys] 已投递待发作业 %s（groups=%s，items=%d）",
        job_id, job["groups"], len(job["items"]),
    )

    out = {
        "ok": False, "job_id": job_id, "groups_sent": [],
        "errors": [], "timed_out": False, "confirmed": False,
    }
    deadline = time.time() + WAIT_SECONDS
    while time.time() < deadline:
        time.sleep(TASK_POLL_INTERVAL)
        j = _read_job()
        if j and j.get("job_id") == job_id and j.get("status") in TERMINAL_STATUSES:
            ext = j.get("result") or {}
            out["groups_sent"] = list(ext.get("groups_sent", []))
            out["errors"] = list(ext.get("errors", []))
            out["confirmed"] = True
            # ok 必须同时满足：notify 报 ok + 至少一个群确认 + **无任何单项错误**。
            # errors 里含「读盘失败 / 空文件 / sendMessage 未回 id」等，任一都说明
            # 有 item 没发出去，不能算成功（否则静默丢附件）。
            out["ok"] = (bool(ext.get("ok"))
                         and bool(out["groups_sent"])
                         and not out["errors"])
            return out

    # 超时兜底：仅在作业仍非终态时标记 failed（生产者已回终态则绝不覆写，
    # 见 run_whatsapp_send_baileys 的 2026-10-08 事故注释）。
    out["timed_out"] = True
    out["errors"].append(
        f"notify.js 未在 {WAIT_SECONDS}s 内回报（检查 notify 进程 / 心跳 / auth-notify）"
    )
    j = _read_job()
    if j and j.get("job_id") == job_id and j.get("status") not in TERMINAL_STATUSES:
        j["status"] = "failed"
        j["completed_at"] = datetime.now().isoformat(timespec="seconds")
        j["result"] = {"ok": False, "groups_sent": [], "errors": list(out["errors"])}
        _write_job(j)
    return out


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

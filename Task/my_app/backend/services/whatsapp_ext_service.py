"""
WhatsApp 扩展发送服务（配合 Chrome 扩展 Task/my_app/whatsapp_sender_extension）

与 whatsapp_service.run_whatsapp_send（Playwright 自启浏览器）**并行**的第二种实现，
两者共用同一份图片目录与群组/备注配置；原任务保持不动。

工作模型（拉取/工人）：
- 本任务不直接发送。它在后端投递一个「待发作业」并阻塞等待；
- Chrome 扩展运行在用户已登录的 WhatsApp Web 标签页里，定期轮询
  GET /api/whatsapp/ext/job 认领作业、在浏览器里逐群逐图发送，
  完成后把结果 POST 回 /api/whatsapp/ext/job/result；
- 本任务收到扩展回报（或超时）后返回结果，从而在 /myapp/?page=sync
  像普通任务一样展示成功/失败/耗时/历史。

作业状态用一个「原子写的 JSON 文件」在任务进程与 Web API 进程之间共享。
队列模式（MY_APP_TASK_QUEUE=1）下二者可能是不同进程；该文件与 DB 无关，
sqlite / pg 两种 DB 模式都适用。写入走 临时文件 + os.replace（Windows 原子）。
"""
import os
import json
import time
import uuid
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from backend.services.whatsapp_service import SITE_OUTAGE_DIR, GROUPS

logger = logging.getLogger("whatsapp_ext_service")

# ========== 配置 ==========
# 任务最长等待扩展回报的秒数（扩展轮询间隔约 1 分钟 + 实际发送耗时）。
# 2026-09-01 由 300 调到 600：凌晨窗口最小化/锁屏场景下，Chrome 丢弃页签后
# 重新加载 WhatsApp Web（登录恢复 + DOM 渲染）可能超过 5 分钟，600s 留足余量。
WAIT_SECONDS = int(os.environ.get("WHATSAPP_EXT_WAIT_SECONDS", "600"))
# 任务侧轮询作业文件的间隔（秒）
TASK_POLL_INTERVAL = float(os.environ.get("WHATSAPP_EXT_POLL_INTERVAL", "1.0"))

JOB_FILE = Path(__file__).resolve().parent / "data" / "whatsapp_ext_job.json"

_IMAGE_EXTS = ("*.png", "*.PNG", "*.jpg", "*.JPG", "*.jpeg", "*.JPEG")
_MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


# ==========================================================
# 出图清单（与 whatsapp_service 同规则，但每次请求重新扫描，保证最新）
# ==========================================================
def _scan_images() -> list[Path]:
    found: set[Path] = set()
    for ext in _IMAGE_EXTS:
        found.update(SITE_OUTAGE_DIR.glob(ext))
    return sorted(p for p in found if "debug" not in p.name.lower())


def _captions_for(images: list[Path]) -> list[str]:
    env = os.environ.get("WHATSAPP_CAPTIONS", "").strip()
    if env:
        parts = [c.strip() for c in env.split(",") if c.strip()]
        return [parts[i] if i < len(parts) else f"*{p.stem}*" for i, p in enumerate(images)]
    return [f"*{p.stem}*" for p in images]


def _mime_for(path: Path) -> str:
    return _MIME_BY_EXT.get(path.suffix.lower(), "image/png")


def build_outbox_payload() -> dict:
    """返回群组 + 图片清单（图片按文件名排序，与任务行为一致）。"""
    images = _scan_images()
    captions = _captions_for(images)
    items = []
    for i, p in enumerate(images):
        if not p.is_file():
            continue
        items.append({
            "name": p.name,
            "caption": captions[i] if i < len(captions) else f"*{p.stem}*",
            "mime": _mime_for(p),
            "url": f"/api/whatsapp/outbox/image?name={quote(p.name)}",
        })
    return {
        "groups": list(GROUPS),
        "items": items,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def resolve_image_path(name: str) -> Path | None:
    """按文件名解析图片真实路径；只允许命中图片目录内的真实图片文件（防路径穿越）。"""
    base_dir = SITE_OUTAGE_DIR.resolve()
    target = (base_dir / Path(name).name).resolve()
    try:
        inside = target.is_relative_to(base_dir)
    except AttributeError:  # 极老 Python 兜底（本项目为 3.12，不会走到）
        inside = str(target).startswith(str(base_dir))
    if not inside or not target.is_file():
        return None
    if target.suffix.lower() not in _MIME_BY_EXT:
        return None
    return target


# ==========================================================
# 作业文件（原子写，跨进程共享）
# ==========================================================
def _read_job() -> dict | None:
    try:
        if not JOB_FILE.exists():
            return None
        with open(JOB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("[WhatsAppExt] 读取作业文件失败: %s", e)
        return None


def _write_job(job: dict) -> None:
    JOB_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = JOB_FILE.with_name(f"{JOB_FILE.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(JOB_FILE))


def create_pending_job() -> dict:
    """投递一个新的待发作业（会取代任何旧的 pending/running 作业）。"""
    job = {
        "job_id": datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8],
        "status": "pending",
        "groups": list(GROUPS),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "claimed_at": None,
        "completed_at": None,
        "result": None,
    }
    _write_job(job)
    logger.info("[WhatsAppExt] 已投递待发作业 %s（groups=%s）", job["job_id"], job["groups"])
    return job


def claim_pending_job() -> dict | None:
    """扩展认领待发作业：把状态置为 running，并附带最新的图片清单。"""
    job = _read_job()
    if not job or job.get("status") != "pending":
        return None
    job["status"] = "running"
    job["claimed_at"] = datetime.now().isoformat(timespec="seconds")
    outbox = build_outbox_payload()
    job["groups"] = outbox["groups"]
    _write_job(job)
    return {
        "pending": True,
        "job_id": job["job_id"],
        "groups": outbox["groups"],
        "items": outbox["items"],
    }


def complete_job(job_id: str, result: dict) -> bool:
    """扩展回报结果：把作业标记为 completed/failed 并落盘结果。

    幂等：作业已到终态（completed/failed）时，重复回报按 no-op 处理。
    （content 直报 wa:job-result 与 SW 自身回报可能各到达一次。）
    """
    job = _read_job()
    if not job or job.get("job_id") != job_id:
        logger.warning("[WhatsAppExt] 回报的 job_id 不匹配（可能已被新作业取代）: %s", job_id)
        return False
    if job.get("status") in ("completed", "failed"):
        logger.info("[WhatsAppExt] 作业 %s 已为终态(%s)，忽略重复回报", job_id, job.get("status"))
        return True
    ok = bool(result.get("ok"))
    job["status"] = "completed" if ok else "failed"
    job["completed_at"] = datetime.now().isoformat(timespec="seconds")
    job["result"] = result
    _write_job(job)
    logger.info("[WhatsAppExt] 作业 %s 回报 ok=%s groups_sent=%s", job_id, ok, result.get("groups_sent"))
    return True


# ==========================================================
# 任务入口（供 task_registry 的 whatsapp_send_ext 调用）
# ==========================================================
def run_whatsapp_send_ext() -> dict:
    start_time = time.time()
    result = {
        "success": False,
        "method": "extension",
        "groups_sent": [],
        "errors": [],
        "elapsed_seconds": 0,
    }

    if not GROUPS:
        result["errors"].append("未配置群组（环境变量 WHATSAPP_GROUPS 为空）")
        result["elapsed_seconds"] = round(time.time() - start_time, 2)
        return result
    if not _scan_images():
        result["errors"].append(f"图片目录无可发送图片: {SITE_OUTAGE_DIR}")
        result["elapsed_seconds"] = round(time.time() - start_time, 2)
        return result

    job = create_pending_job()
    job_id = job["job_id"]
    deadline = start_time + WAIT_SECONDS
    logger.info("[WhatsAppExt] 等待浏览器扩展认领并回报（最长 %ds）…", WAIT_SECONDS)

    while time.time() < deadline:
        time.sleep(TASK_POLL_INTERVAL)
        j = _read_job()
        if j and j.get("job_id") == job_id and j.get("status") in ("completed", "failed"):
            ext = j.get("result") or {}
            result["groups_sent"] = ext.get("groups_sent", [])
            result["errors"] = list(ext.get("errors", []))
            result["success"] = bool(ext.get("ok"))
            result["ext_elapsed_seconds"] = ext.get("elapsed_seconds")
            break
    else:
        result["errors"].append(
            f"浏览器扩展未在 {WAIT_SECONDS}s 内回报。请检查：Chrome 是否已打开并登录过 WhatsApp Web"
            "（标签页无需保持前台显示，后台即可）、扩展是否已启用；若 Chrome 刚启动，"
            "WhatsApp Web 需完成自动登录。"
        )
        # 超时兜底：把作业标记为 failed，避免 job 文件永远停在 running
        j = _read_job()
        if j and j.get("job_id") == job_id and j.get("status") == "running":
            j["status"] = "failed"
            j["completed_at"] = datetime.now().isoformat(timespec="seconds")
            j["result"] = {"ok": False, "groups_sent": [], "errors": list(result["errors"])}
            _write_job(j)

    result["elapsed_seconds"] = round(time.time() - start_time, 2)
    logger.info(
        "[WhatsAppExt] 完成 job=%s success=%s groups=%s 用时 %.2fs",
        job_id, result["success"], result["groups_sent"], result["elapsed_seconds"],
    )
    return result


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    print(f"图片目录: {SITE_OUTAGE_DIR}")
    print("群组:", GROUPS)
    r = run_whatsapp_send_ext()
    print("结果:", r)

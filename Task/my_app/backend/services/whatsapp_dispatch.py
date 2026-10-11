"""
WhatsApp 发送统一编排层（Baileys 默认 → Playwright 回退）。

## 为什么有这一层

SP 系列报表任务（sp_email_details / sp_online_report_send / sp_whatsapp_report）
此前**直接**调 `whatsapp_service.run_whatsapp_send`（Playwright 自启浏览器）。
2026-10-11 早间 05:55~08:25，三个任务只因共用同一 WhatsApp profile 互相抢锁，
就连续失败 7 次（`intercepts pointer events` / `等待登录超时`）。

用户 2026-10-11 决策（**A 方案**）：改用 **Baileys 为主通道，Playwright 为回退**。
理由：
  - Baileys 走「已关联设备」直连协议，回执是服务端 message id，不碰页面，
    没有 DOM 改版 / 弹窗遮挡 / 每 2~3 周掉登录的问题（见 whatsapp_send_baileys_service 的模块 docstring）；
  - Baileys 会话（账号：副号，`whatsapp-kb-bot/data/auth-notify`）与 Playwright
    的浏览器会话（`whatsapp_session`）**物理隔离**，一方被踢不影响另一方 ——
    这正是「主通道失败仍有回退通道兜底」能成立的前提；
  - 代价：群里看到的发送者变为**副号**（用户已知悉并接受）。
  - 保留 Playwright 回退：Baileys 是副号，万一被封（ToS 风险）整条通道失效，
    回退通道保证 WH&SP Management 这类真实工作群的消息不丢。

## 与 tt_alarm 的关系

这套「Baileys 默认 → 浏览器回退」的模式在 `tt_alarm_whatsapp_service.py`
（P1 告警，2026-10-01/08）已经落地并验证过；本模块是把它复用到 SP 报表产物上。
回退判据与 tt_alarm 一致：**投递失败 或 回报零确认**都算主通道失败。

## 关键约束（改动前必读）

1. **回退自身失败不再二次回退** —— 避免无限循环（沿用 tt_alarm 的约束）。
2. Playwright 回退仍走 `whatsapp_service`，因此 2026-10-11 加的「弹窗消解 +
   会话快照」对回退路径同样生效。
3. **不动 cron、不新增任务** —— 本模块只被既有任务的发送点调用。
4. 双通道**不并发**：先 Baileys 拿到终态，再决定是否回退；绝不两条通道同时发，
   否则群里会收到两份。
"""
import logging
import os

from backend.services.whatsapp_service import GROUPS

logger = logging.getLogger("whatsapp_dispatch")


def send_with_fallback(files: list, groups: list | None = None,
                       captions: list | None = None, photos: list | None = None,
                       channel: str | None = None) -> dict:
    """把「图片 + 文件」发到 groups，主通道 Baileys，失败回退 Playwright。

    与 `whatsapp_service.run_whatsapp_send` 的参数语义对齐，便于在 SP 任务的
    发送点直接替换：

      - ``photos`` / ``captions``：图片清单与一一对应的备注（可空）。
      - ``files``：作为文档发送的文件清单（可空）。可与 photos 同发。
      - ``groups``：目标群，缺省用 `whatsapp_service.GROUPS`。

    返回统一结构（供任务组装 error 用）：
      ``{"success": bool, "channel": "baileys"|"playwright", "fell_back": bool,
         "groups_sent": [...], "errors": [...], "baileys": {...}, "playwright": {...}}``

    ``channel`` 强制指定 ''（不强制，默认）或 'playwright'（跳过 Baileys，
    用于需要主号发送的场景 / 排查对比）；缺省先试 Baileys。
    """
    groups = list(groups if groups is not None else GROUPS)
    photos = [str(p) for p in (photos or [])]
    captions = list(captions or [])
    files = [str(f) for f in (files or [])]

    # 主通道开关：WHATSAPP_DISPATCH_CHANNEL=playwright 可整体退回旧行为
    # （例如 Baileys 副号被封时，运维改一个环境变量即可把三个任务打回 Playwright）。
    forced = (channel or os.environ.get("WHATSAPP_DISPATCH_CHANNEL", "")).strip().lower()
    use_baileys = forced != "playwright"

    out = {
        "success": False,
        "channel": None,
        "fell_back": False,
        "groups_sent": [],
        "errors": [],
        "baileys": None,
        "playwright": None,
    }

    if not groups:
        out["errors"].append("未配置目标群组")
        return out

    # ---- 主通道：Baileys（图片与文档一次性投递；notify.js 按扩展名分派） ----
    if use_baileys:
        baileys_res = _try_baileys(photos, captions, files, groups) or {}
        out["baileys"] = baileys_res
        if baileys_res.get("ok"):
            out["success"] = True
            out["channel"] = "baileys"
            out["groups_sent"] = list(baileys_res.get("groups_sent") or [])
            return out
        # 主通道失败 → 记录原因，进入回退（不在此处 return）
        reason = "; ".join(str(e) for e in (baileys_res.get("errors") or [])) or "Baileys 未确认"
        logger.warning("[WADispatch] Baileys 主通道失败（%s），回退 Playwright", reason)

    # ---- 回退通道：Playwright ----
    out["fell_back"] = use_baileys  # 只有「试过主通道」才叫回退
    pw_res = _try_playwright(photos, captions, files, groups) or {}
    out["playwright"] = pw_res
    if pw_res.get("success"):
        out["success"] = True
        out["channel"] = "playwright"
        out["groups_sent"] = list(pw_res.get("groups_sent") or [])
        return out

    out["errors"].append("Baileys 与 Playwright 两条通道均未确认送达：")
    if out["baileys"]:
        out["errors"].extend(str(e) for e in (out["baileys"].get("errors") or []))
    out["errors"].extend(str(e) for e in (pw_res.get("errors") or []))
    return out


def _try_baileys(photos: list, captions: list, files: list, groups: list) -> dict:
    """主通道：把 photos + files 合成 items 投给 Baileys，等回报。"""
    try:
        from backend.services import whatsapp_send_baileys_service as bsvc
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "errors": [f"加载 Baileys 服务失败: {e}"],
                "groups_sent": [], "confirmed": False, "timed_out": False}

    # photos 带备注、files 用文件名当备注，顺序与既有 Playwright 调用一致
    items = bsvc.build_items(photos, captions) + bsvc.build_items(files, None)
    if not items:
        return {"ok": False, "errors": ["无可发送内容（photos 与 files 均为空）"],
                "groups_sent": [], "confirmed": False, "timed_out": False}
    try:
        # 配额必须与 notify.js 进程实际生效的 CONFIG.notify.fileSend 一致，否则
        # 守卫会误判：拒掉 notify.js 本可接收的作业（或放行会被静默截断的）。
        # 2026-10-11：notify.js 默认是 6 图 / 1 文档，但 SP 报表需要一次发 2 份 xlsx，
        # 已在 whatsapp-kb-bot/.env 用 NOTIFY_FILE_SEND 放宽为 8 图 / 3 文档；
        # 此处的默认值与之对齐。**两边改一个必须改另一个**（同一判断的两份副本）。
        max_images = int(os.environ.get("WHATSAPP_BAILEYS_MAX_IMAGES", "8"))
        max_documents = int(os.environ.get("WHATSAPP_BAILEYS_MAX_DOCUMENTS", "3"))
        return bsvc.dispatch_items(items, groups,
                                   max_images=max_images, max_documents=max_documents)
    except Exception as e:  # noqa: BLE001
        logger.warning("[WADispatch] Baileys 投递异常: %s", e, exc_info=True)
        return {"ok": False, "errors": [f"Baileys 投递异常: {e}"],
                "groups_sent": [], "confirmed": False, "timed_out": False}


def _try_playwright(photos: list, captions: list, files: list, groups: list) -> dict:
    """回退通道：复用既有 Playwright 发送（含 2026-10-11 的弹窗消解/快照）。"""
    try:
        from backend.services.whatsapp_service import run_whatsapp_send
    except Exception as e:  # noqa: BLE001
        return {"success": False, "errors": [f"加载 Playwright 服务失败: {e}"],
                "groups_sent": []}
    try:
        return run_whatsapp_send(
            photos=photos or None,
            captions=captions or None,
            files=files or None,
            groups=groups,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[WADispatch] Playwright 投递异常: %s", e, exc_info=True)
        return {"success": False, "errors": [f"Playwright 投递异常: {e}"],
                "groups_sent": []}

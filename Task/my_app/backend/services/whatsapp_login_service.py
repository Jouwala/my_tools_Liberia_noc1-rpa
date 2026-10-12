# -*- coding: utf-8 -*-
"""WhatsApp 网页扫码登录 —— my_app 设置页 ↔ whatsapp-kb-bot 常驻 Node 进程的通道。

## 背景

WhatsApp 侧有两个「已关联设备」（**同一个号码**，两个设备槽）：
  - `device="notify"` → `whatsapp-kb-bot/src/notify.js`（P1 告警推送），凭据 `data/auth-notify`
  - `device="bot"`    → `whatsapp-kb-bot/src/index.js`（知识库问答），凭据 `data/auth`

以前换号必须去 bot 目录手动跑 `npm run relogin:notify` 并盯终端字符二维码。
本服务把这条路搬到网页：写一个「出码请求」文件，Node 侧 watcher（`src/qrLogin.js`）
读到后清凭据 + 重连出码，并把二维码原始字符串写进状态文件，前端渲染成二维码图片。

## 通道文件（与既有 job / heartbeat 同目录、同约定）

  - `data/qr_request.json` —— **本服务写**：`{ "notify": {"nonce","requested_at"}, "bot": {...} }`
  - `data/qr_status.json`  —— **Node 侧写**：`{ "notify": {"nonce","state","qr","at","message"}, ... }`

两个设备各占一个键，互不覆盖。

## 安全边界

- 路由走 `require_protected`（回环放行，外部需完整鉴权）。
- 本服务**只读号段用于展示**，绝不把 `creds.json` 里的密钥/预共享密钥放进返回值或日志。
- 返回给前端的字段只有：device / online / identity / state / qr / message / updated_at。
"""
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# 复用 wa_notify_service 的 bot 根目录解析（单一真相源：改动只改那一处）。
from backend.services.wa_notify_service import (
    _BOT_ROOT,
    _parse_iso,
    _s,
    HEARTBEAT_STALE_SECONDS,
    is_online,
)

logger = logging.getLogger("whatsapp_login")

DATA_DIR = _BOT_ROOT / "data"
QR_REQUEST_FILE = DATA_DIR / "qr_request.json"
QR_STATUS_FILE = DATA_DIR / "qr_status.json"

# bot（问答进程）的心跳文件，与 notify 的 notify_heartbeat.json 不同一个。
# 由 whatsapp.js 写入（见 `HEARTBEAT_FILE = join(CONFIG.authDirAbs, '..', 'bot_heartbeat.json')`）。
BOT_HEARTBEAT_FILE = DATA_DIR / "bot_heartbeat.json"

# 设备 → 凭据目录（展示当前登录身份用）。notify 的目录可由同款环境变量覆盖。
DEVICE_AUTH_DIRS: Dict[str, Path] = {
    "notify": Path(os.environ.get("NOTIFY_AUTH_DIR", str(DATA_DIR / "auth-notify"))),
    "bot": Path(os.environ.get("AUTH_DIR", str(DATA_DIR / "auth"))),
}

VALID_DEVICES = ("notify", "bot")


def _atomic_write_json(path: Path, data: Any) -> None:
    """原子写：先写临时文件再 `os.replace`，避免 Node 侧读到半截 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(path))


def _read_json(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001
        logger.warning("[WALogin] 读文件失败: %s", path, exc_info=True)
        return None


def request_qr(device: str) -> Dict[str, Any]:
    """请求某设备重新出码：写 `qr_request.json` 的对应键（带新 nonce）。

    读-改-写，**只覆盖自己的键**，不动另一个设备刚发起的请求。
    """
    if device not in VALID_DEVICES:
        raise ValueError(f"未知设备: {device}（应为 {' / '.join(VALID_DEVICES)}）")
    nonce = uuid.uuid4().hex
    cur = _read_json(QR_REQUEST_FILE) or {}
    cur[device] = {
        "nonce": nonce,
        "requested_at": datetime.now().isoformat(timespec="seconds"),
    }
    _atomic_write_json(QR_REQUEST_FILE, cur)
    logger.info("[WALogin] 已请求 %s 设备出码（nonce=%s）", device, nonce)
    return {"device": device, "nonce": nonce}


def _device_identity(device: str) -> Optional[Dict[str, str]]:
    """读凭据里的身份（仅号段/名称，用于展示）。

    ⚠️ 只取 `me.id` / `me.name` / `me.lid`。**绝不**读取或返回 signature、
    预共享密钥等任何密钥字段；`creds.json` 其余内容一概不碰。
    """
    creds = DEVICE_AUTH_DIRS.get(device)
    if creds is None:
        return None
    raw = _read_json(creds / "creds.json")
    if not raw:
        return None
    me = raw.get("me") or {}
    if not isinstance(me, dict):
        return None
    num = _s(me.get("id")).split("@")[0].split(":")[0]
    return {
        "number": num or "",
        "name": _s(me.get("name")),
        # 设备槽（:1 / :2）：两个设备同号不同槽，展示出来便于区分
        "device_slot": _s(me.get("id")).split("@")[0].split(":")[1] if ":" in _s(me.get("id")) else "",
    }


def _heartbeat_status(device: str) -> Dict[str, Any]:
    """按设备读心跳判在线（三态，与 ext_liveness / wa_notify 一致）。"""
    if device == "notify":
        # notify 的判定逻辑已成熟（含 pid 存活校验），直接复用。
        st = is_online()
        return {"online": st.get("status") == "online", "status": st.get("status"),
                "reason": st.get("reason")}

    # bot 设备：同款判定，只是换心跳文件。
    hb = _read_json(BOT_HEARTBEAT_FILE)
    if not isinstance(hb, dict):
        return {"online": False, "status": "unknown", "reason": "尚无机器人心跳（进程未启动或刚重启）"}
    if not hb.get("connected"):
        return {"online": False, "status": "offline",
                "reason": "机器人进程在运行但未连接（可能需要重新扫码）"}
    ts = _parse_iso(hb.get("at"))
    if ts is None:
        return {"online": False, "status": "unknown", "reason": "心跳时间不可解析"}
    age = datetime.now().timestamp() - ts
    if age > HEARTBEAT_STALE_SECONDS:
        return {"online": False, "status": "offline",
                "reason": f"机器人已 {round(age)}s 无心跳（阈值 {HEARTBEAT_STALE_SECONDS}s）"}
    return {"online": True, "status": "online", "reason": f"{round(age)}s 前心跳正常"}


def get_status(device: str) -> Dict[str, Any]:
    """汇总某设备的登录状态，供前端轮询。

    返回的 `state` 语义（来自 `qr_status.json[device].state`）：
      - `waiting`   已收到出码请求、Node 侧正在清凭据/重连
      - `qr`        二维码就绪，`qr` 为原始字符串，前端据此渲染图片
      - `connected` 扫码成功已连上
      - `error`     出错，`message` 说明
    无任何出码记录时为 `null`（前端据此只显示连接状态，不显示二维码）。
    """
    if device not in VALID_DEVICES:
        raise ValueError(f"未知设备: {device}（应为 {' / '.join(VALID_DEVICES)}）")

    hb = _heartbeat_status(device)
    identity = _device_identity(device)

    status_all = _read_json(QR_STATUS_FILE) or {}
    rec = status_all.get(device) if isinstance(status_all, dict) else None
    if not isinstance(rec, dict):
        rec = {}

    return {
        "device": device,
        "online": hb.get("online", False),
        "online_status": hb.get("status"),
        "online_reason": hb.get("reason"),
        "identity": identity,
        "state": rec.get("state"),
        "qr": rec.get("qr"),
        "message": rec.get("message"),
        "nonce": rec.get("nonce"),
        "updated_at": rec.get("at"),
    }

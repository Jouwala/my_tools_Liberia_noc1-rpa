# -*- coding: utf-8 -*-
"""
settings.py - 全局设置 API
==========================
- GET  /api/settings/remote-host   读取远程主机（FTP / API / SMB 共用，默认 192.168.100.19）
- PUT  /api/settings/remote-host   更新远程主机（页面写入 settings.json，本地访问即可）

与 credentials 路由保持一致：本地访问（回环）直接放行，不做额外鉴权，方便运维在页面上直接改。
"""
import ftplib
import logging
import socket
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import Optional

from backend.config.remote_host import (
    get_api_port,
    get_ftp_port,
    get_remote_host,
    set_remote_host,
)
from backend.services.remote_ftp import creds_for

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class RemoteHostIn(BaseModel):
    host: str


@router.get("/remote-host")
def get_remote_host_setting():
    """读取当前生效的远程主机（FTP / API / SMB 共用）。"""
    return {"remote_host": get_remote_host()}


@router.put("/remote-host")
def put_remote_host_setting(payload: RemoteHostIn, request: Request):
    """更新远程主机并持久化到 settings.json。"""
    host = set_remote_host(payload.host)
    logger.info(f"[SETTINGS] 远程主机已更新: {host}")
    return {"remote_host": host}


# ------------------------- 连接测试（FTP / API）-------------------------
def _probe_ftp(host: str, port: int) -> dict:
    """探测 FTP：TCP 连通 + 读取欢迎语 + 用默认凭据尝试登录。"""
    res = {
        "type": "ftp", "host": host, "port": port,
        "reachable": False, "authenticated": False,
        "banner": None, "latency_ms": None, "error": None,
    }
    ftp = None
    try:
        start = time.time()
        ftp = ftplib.FTP(timeout=8)
        ftp.connect(host, port)
        res["latency_ms"] = round((time.time() - start) * 1000, 1)
        res["banner"] = getattr(ftp, "welcome", None)
        res["reachable"] = True
        # 用默认凭据（与 remote_ftp.creds_for 兜底一致）验证可登录
        user, pw = creds_for("")
        try:
            ftp.login(user, pw)
            res["authenticated"] = True
        except Exception as le:  # noqa: BLE001
            res["auth_error"] = str(le)
        try:
            ftp.quit()
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        res["error"] = str(e)
    finally:
        try:
            if ftp is not None:
                ftp.close()
        except Exception:  # noqa: BLE001
            pass
    return res


def _probe_api(host: str, port: int) -> dict:
    """探测 API：依次 GET /health、/，记录状态码 / 响应体 / 耗时。"""
    base = f"http://{host}:{port}"
    res = {
        "type": "api", "host": host, "port": port,
        "reachable": False, "status": None, "path": None,
        "body": None, "latency_ms": None, "error": None,
    }
    for path in ("/health", "/"):
        url = base + path
        try:
            start = time.time()
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = resp.read().decode("utf-8", "replace")
                res["latency_ms"] = round((time.time() - start) * 1000, 1)
                res["status"] = resp.status
                res["body"] = body[:300]
                res["reachable"] = True
                res["path"] = path
                break
        except urllib.error.HTTPError as e:
            # 服务器有响应 = 端口开着，只是路径/业务问题
            res["status"] = e.code
            try:
                res["body"] = e.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            res["reachable"] = True
            res["path"] = path
            res["error"] = f"HTTP {e.code}"
            break
        except Exception as e:  # noqa: BLE001
            res["error"] = str(e)
            continue
    return res


class TestConnectionIn(BaseModel):
    host: Optional[str] = None


@router.post("/test-connection")
async def test_connection(payload: TestConnectionIn, request: Request):
    """测试远程主机的 FTP(21) 与 API(8765) 连通性。

    不传 host 时测试当前生效主机；传 host 可在保存前先验证新地址。
    """
    host = (payload.host or "").strip() or get_remote_host()
    ftp_res = await run_in_threadpool(_probe_ftp, host, get_ftp_port())
    api_res = await run_in_threadpool(_probe_api, host, get_api_port())
    logger.info("[SETTINGS] 连接测试 %s: FTP=%s API=%s",
                host, ftp_res.get("reachable"), api_res.get("reachable"))
    return {"host": host, "ftp": ftp_res, "api": api_res}

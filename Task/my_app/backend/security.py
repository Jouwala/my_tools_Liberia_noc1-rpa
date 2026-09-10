"""最小鉴权助手（仅用于保护高危写/触发端点）。

策略：
- 来自本机回环地址(127.0.0.1 / ::1 / localhost) 的请求直接放行
  （前端、同机调度脚本、nginx 反代都走回环，不会受影响）。
- 远程请求必须携带正确的 `X-API-Token` 头，否则 403。
  Token 取自环境变量 MY_APP_API_TOKEN；未设置时远程请求一律拒绝。
这样无需在代码里硬编码新密钥，也不会破坏同机调用。

注意：uvicorn 以 `--proxy-headers` 启动，nginx 反代会带 `X-Forwarded-For`，
所以 `request.client.host` 拿到的是**真实客户端 IP**（局域网访问者不会显示成 127.0.0.1）。
"""
import os
from fastapi import Request, Depends, HTTPException

API_TOKEN = os.environ.get("MY_APP_API_TOKEN", "")
_TRUSTED_LOCAL = {"127.0.0.1", "::1", "localhost"}


def client_is_local(request: Request) -> bool:
    """请求是否来自本机回环（经 nginx 反代时由 X-Forwarded-For 还原）。"""
    client_host = request.client.host if request.client else ""
    return client_host in _TRUSTED_LOCAL


def has_valid_token(request: Request) -> bool:
    """是否携带了正确的 X-API-Token（未配置该环境变量时恒为 False）。"""
    return bool(API_TOKEN) and request.headers.get("X-API-Token") == API_TOKEN


def is_privileged(request: Request) -> bool:
    """是否具备「本机 / 持令牌」写权限，判据与 require_protected 严格一致。

    供「先告诉前端能不能改」的场景复用（如界面配置接口返回 editable 标记），
    避免前端看到的权限与真正写入时的判定不一致。
    """
    return client_is_local(request) or has_valid_token(request)


def require_protected(request: Request):
    if is_privileged(request):
        return
    raise HTTPException(
        status_code=403,
        detail="Forbidden: 需从本机访问或携带正确的 X-API-Token 头",
    )

"""最小鉴权助手（仅用于保护高危写/触发端点）。

策略：
- 来自本机回环地址(127.0.0.1 / ::1 / localhost) 的请求直接放行
  （前端、同机调度脚本、nginx 反代都走回环，不会受影响）。
- 远程请求必须携带正确的 `X-API-Token` 头，否则 403。
  Token 取自环境变量 MY_APP_API_TOKEN；未设置时远程请求一律拒绝。
这样无需在代码里硬编码新密钥，也不会破坏同机调用。
"""
import os
from fastapi import Request, Depends, HTTPException

API_TOKEN = os.environ.get("MY_APP_API_TOKEN", "")
_TRUSTED_LOCAL = {"127.0.0.1", "::1", "localhost"}


def require_protected(request: Request):
    client_host = request.client.host if request.client else ""
    if client_host in _TRUSTED_LOCAL:
        return
    if API_TOKEN and request.headers.get("X-API-Token") == API_TOKEN:
        return
    raise HTTPException(
        status_code=403,
        detail="Forbidden: 需从本机访问或携带正确的 X-API-Token 头",
    )

# -*- coding: utf-8 -*-
"""基于 pyspnego（Windows SSPI）的 NTLM HTTP 认证。

exchangelib 默认使用 requests_ntlm.HttpNtlmAuth（纯 Python NTLM 实现），
该实现在某些 Exchange 服务器上会在 NTLM Type 3 握手后挂起。

本模块使用 pyspnego + sspilib 调用 Windows 原生 SSPI（与浏览器/IE 同一套），
完美兼容 Exchange 服务器的 NTLM 认证。

用法：
    from sspi_ntlm_auth import HttpSspiNtlmAuth
    # 直接传给 requests
    r = requests.post(url, auth=HttpSspiNtlmAuth(user, pwd), ...)
    # 或替换 exchangelib 的 AUTH_TYPE_MAP
    import exchangelib.transport as T
    T.AUTH_TYPE_MAP[T.NTLM] = HttpSspiNtlmAuth
"""
import base64
import logging

import requests.auth

log = logging.getLogger(__name__)


class HttpSspiNtlmAuth(requests.auth.AuthBase):
    """NTLM HTTP 认证，底层使用 Windows SSPI（通过 pyspnego）。

    与 requests_ntlm.HttpNtlmAuth 接口兼容，可直接替换。
    """

    def __init__(self, username, password, **kwargs):
        self.username = username
        self.password = password
        # 兼容 requests_ntlm 的参数（忽略不需要的）
        self.domain = kwargs.get("domain", "")

    def __call__(self, r):
        r.register_hook("response", self._handle_401)
        return r

    def _handle_401(self, response, **kwargs):
        """处理 401 响应，执行 NTLM 三步握手。"""
        # 检查服务器是否提供 NTLM
        www_auth = response.headers.get("www-authenticate", "")
        if "ntlm" not in www_auth.lower():
            return response

        import spnego

        log.debug("SSPI NTLM: starting handshake for user %s", self.username)

        # 创建 SSPI NTLM 上下文
        # protocol="ntlm" 强制使用 NTLM（不走 Kerberos 协商）
        # 在 Windows 上 pyspnego 自动使用 SSPI（与浏览器同一套认证栈）
        try:
            ctx = spnego.client(
                username=self.username,
                password=self.password,
                protocol="ntlm",
            )
        except Exception as e:
            log.error("SSPI NTLM: failed to create context: %s", e)
            return response

        # ── Step 1: 发送 Type 1 (Negotiate) ──
        try:
            type1_token = ctx.step()
        except Exception as e:
            log.error("SSPI NTLM: Type 1 step failed: %s", e)
            return response

        if type1_token is None:
            log.error("SSPI NTLM: Type 1 token is None")
            return response

        auth1 = "NTLM " + base64.b64encode(type1_token).decode("ascii")
        log.debug("SSPI NTLM: sent Type 1 (%d bytes)", len(type1_token))

        # 消费 401 响应体，将连接归还连接池（不关闭——NTLM 要求同一连接）
        response.content
        if hasattr(response, "raw") and response.raw:
            response.raw.release_conn()

        # 重发请求，带 Type 1 token（复用同一连接）
        prep = response.request.copy()
        prep.headers["Authorization"] = auth1

        try:
            resp2 = response.connection.send(prep, **kwargs)
        except Exception as e:
            log.error("SSPI NTLM: Type 1 request failed: %s", e)
            return response

        # ── Step 2: 接收 Type 2 (Challenge)，发送 Type 3 (Authenticate) ──
        www_auth2 = resp2.headers.get("www-authenticate", "")
        if not www_auth2.lower().startswith("ntlm "):
            log.warning("SSPI NTLM: no Type 2 challenge in response (status=%s, www-auth=%s)",
                        resp2.status_code, www_auth2[:100])
            return resp2

        type2_b64 = www_auth2.split(" ", 1)[1].strip()
        try:
            type2_token = base64.b64decode(type2_b64)
        except Exception as e:
            log.error("SSPI NTLM: failed to decode Type 2 token: %s", e)
            return resp2

        log.debug("SSPI NTLM: received Type 2 (%d bytes)", len(type2_token))

        try:
            type3_token = ctx.step(type2_token)
        except Exception as e:
            log.error("SSPI NTLM: Type 3 step failed: %s", e)
            return resp2

        if type3_token is None:
            log.error("SSPI NTLM: Type 3 token is None")
            return resp2

        auth3 = "NTLM " + base64.b64encode(type3_token).decode("ascii")
        log.debug("SSPI NTLM: sent Type 3 (%d bytes)", len(type3_token))

        # 消费 Type 2 响应体，将连接归还连接池
        resp2.content
        if hasattr(resp2, "raw") and resp2.raw:
            resp2.raw.release_conn()

        # 重发请求，带 Type 3 token（复用同一连接）
        prep2 = resp2.request.copy()
        prep2.headers["Authorization"] = auth3

        try:
            resp3 = resp2.connection.send(prep2, **kwargs)
        except Exception as e:
            log.error("SSPI NTLM: Type 3 request failed: %s", e)
            return resp2

        log.debug("SSPI NTLM: final status=%s", resp3.status_code)
        return resp3


def patch_exchangelib():
    """将 exchangelib 的 NTLM 认证替换为 SSPI 版本。

    调用一次即可全局生效：
        from sspi_ntlm_auth import patch_exchangelib
        patch_exchangelib()
    """
    import exchangelib.transport as T
    T.AUTH_TYPE_MAP[T.NTLM] = HttpSspiNtlmAuth
    log.info("exchangelib NTLM auth patched → HttpSspiNtlmAuth (SSPI)")

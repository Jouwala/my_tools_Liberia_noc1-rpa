# -*- coding: utf-8 -*-
"""EWS 健康探测（**只读**，绝不发信）。供 backend/services/email_recovery.py 调用。

在 stdout 末行输出单行 JSON：

    {"kind": "ok|auth_error|cred_mismatch|server_down", "detail": "...",
     "inbox": 435, "bad": ["ews_send_enhanced"]}

## 为什么单独成脚本（2026-09-18 重写）
原先的探测是塞在 email_recovery 里的一行 ``python -c`` 字符串，只有「成功/失败」
两种结果，导致两类完全不同的故障被混为一谈：

  - **凭据被拒（HTTP 401）** —— 需要人工改密码
  - **服务端不可用（超时/连接失败）** —— 只能等服务端恢复

2026-09-15 21:54 起密码失效，整整 65 小时里探测一律记为「EWS 降级」，告警文案
写着「连接 exchmail 超时…已进入降级静默」，把人引向「等服务端恢复」的错误结论。

## 判定顺序
1. **凭据一致性**：各发信模块解析出的密码必须与 credential_store 一致。
   这正是 2026-09-18 的直接教训——探测走 ``get_account()``（读 credential_store）
   而 1H 脚本的发送分支走 ``ews_send_enhanced``（当时用硬编码旧密码），于是出现
   「探测说 up、发送照样 401」。这一项能自动发现同类漂移。
2. **NTLM 快速预检**（requests_ntlm，约 1s）：401 立即判 auth_error，
   不必等 exchangelib 把 401 当成 ``ErrorServerBusy`` 退避 10/20/40/80s 后才报错
   （旧探测为此白等 300s）。
3. **真实 SOAP 只读往返**（GetFolder 读收件箱）：确认 EWS 服务端可用。

退出码：0 = ok，1 = 其他。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_MY_APP = _SCRIPT_DIR.parent
for _p in (str(_MY_APP), str(_SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 认证被拒的特征（IIS 认证层返回 401，或 exchangelib/.NET 的措辞）
#
# 注意 "HTTP 401" / "401 response"：exchangelib 会把**任何** HTTP 401 包装成
# ``ErrorServerBusy`` 并在重试耗尽后抛出
# ``RateLimitError: Max timeout reached (gave up when asked to back off 80.000
# seconds) Caused by HTTP 401 response`` —— 2026-09-18 那 65 小时里探测拿到的
# 就是这条。只看异常类型会把它当成"服务端限流"，必须看 cause 里的 401。
_AUTH_ERROR_KEYS = (
    "UnauthorizedError",
    "Invalid credentials",
    "HTTP status 401",
    "HTTP 401",
    "401 Unauthorized",
    "401 response",
    "Logon failure",
    "ErrorInvalidCredentials",
    "Access is denied",
    "invalid_grant",
)

# 服务端/网络不可用的特征
_SERVER_DOWN_KEYS = (
    "ReadTimeout",
    "ConnectTimeout",
    "ConnectionError",
    "ConnectionReset",
    "TransportError",
    "timed out",
    "Unable to connect",
    "could not be resolved",
    "NameResolutionError",
    "10060",
    "10061",
    "10054",
)


def _effective_passwords() -> dict:
    """各发信模块当前**实际会使用**的密码（用于与 credential_store 比对）。

    只返回密码值供内部比较；对外只报模块名，绝不打印密码本身。
    """
    out: dict = {}

    def _add(label, fn):
        try:
            out[label] = fn()
        except Exception as exc:  # noqa: BLE001
            out[label] = f"<{type(exc).__name__}: {exc}>"

    def _ews_enhanced():
        from email_reports import ews_send_enhanced
        return ews_send_enhanced._resolve_credentials(None, None)[1]

    def _dotnet():
        from email_reports import dotnet_ews_send
        return dotnet_ews_send.resolve_owa_credentials()[1]

    def _one_hour():
        from email_reports import owa_mail_1hour_TT_Report
        return owa_mail_1hour_TT_Report._resolve_credentials()[1]

    def _mail_report():
        from email_reports import owa_mail_report
        return owa_mail_report._resolve_credentials()[1]

    _add("ews_send_enhanced", _ews_enhanced)
    _add("dotnet_ews_send", _dotnet)
    _add("owa_mail_1hour_TT_Report", _one_hour)
    _add("owa_mail_report", _mail_report)
    return out


def _fast_ntlm_check(server: str, user: str, password: str, timeout: float = 15.0):
    """约 1s 的 NTLM 预检。返回 (kind, detail)，kind ∈ ok/auth_error/unknown。"""
    try:
        import urllib3
        import requests
        from requests_ntlm import HttpNtlmAuth
        urllib3.disable_warnings()
    except Exception as exc:  # noqa: BLE001
        return "unknown", f"requests_ntlm 不可用: {type(exc).__name__}"

    url = f"https://{server}/EWS/Exchange.asmx"
    try:
        r = requests.get(url, auth=HttpNtlmAuth(user, password),
                         verify=False, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return "unknown", f"{type(exc).__name__}: {str(exc)[:180]}"
    if r.status_code in (401, 403):
        return "auth_error", f"HTTP {r.status_code}（NTLM 认证被拒，凭据已失效）"
    if r.status_code < 500:
        # GET 到 .asmx 通常 405/200/302 —— 能走到这里说明认证已通过
        return "ok", f"HTTP {r.status_code}（NTLM 认证通过）"
    return "unknown", f"HTTP {r.status_code}"


def _soap_read_check() -> int:
    """真实 SOAP 只读往返：GetFolder 读收件箱总数。"""
    from owa_mail_1hour_TT_Report import get_account
    account = get_account()          # 惰性构造，不发请求
    return int(account.inbox.total_count)   # 这里才真正发起 SOAP


def _classify(exc: BaseException) -> tuple[str, str]:
    blob = f"{type(exc).__name__}: {exc}"
    if any(k in blob for k in _AUTH_ERROR_KEYS):
        return "auth_error", blob[:400]
    if any(k in blob for k in _SERVER_DOWN_KEYS):
        return "server_down", blob[:400]
    return "server_down", blob[:400]


def main() -> int:
    result = {"kind": "server_down", "detail": "", "inbox": None, "bad": []}

    # ---- 1) 凭据一致性 ----
    store_pwd = ""
    try:
        from backend.services.credential_store import get_credential
        _u, store_pwd = get_credential(
            "owa_mail", "", "",
            env_user="OWA_USERNAME", env_secret="OWA_PASSWORD",
        )
    except Exception as exc:  # noqa: BLE001
        result["detail"] = f"credential_store 读取失败: {type(exc).__name__}"

    passwords = _effective_passwords()
    if store_pwd:
        bad = [name for name, pwd in passwords.items()
               if not str(pwd).startswith("<") and pwd != store_pwd]
        if bad:
            result.update(
                kind="cred_mismatch", bad=bad,
                detail=(f"发信模块 {bad} 解析出的密码与 credential_store 不一致"
                        f"（这些路径会 401，而探测用的 get_account() 却是好的）"),
            )
            print(json.dumps(result, ensure_ascii=False))
            return 1

    # ---- 2) NTLM 快速预检（401 立即返回，不等 exchangelib 退避）----
    eff_user, eff_pwd = "", ""
    try:
        from email_reports import owa_mail_report
        eff_user, eff_pwd = owa_mail_report._resolve_credentials()
    except Exception:  # noqa: BLE001
        eff_user, eff_pwd = os.getenv("OWA_USERNAME", ""), os.getenv("OWA_PASSWORD", "")

    server = os.getenv("OWA_SERVER", "exchmail.orange-cit.ci")
    if eff_user and eff_pwd:
        kind, detail = _fast_ntlm_check(server, eff_user, eff_pwd)
        if kind == "auth_error":
            result.update(kind="auth_error", detail=detail)
            print(json.dumps(result, ensure_ascii=False))
            return 1

    # ---- 3) 真实 SOAP 只读往返 ----
    try:
        result["inbox"] = _soap_read_check()
        result.update(kind="ok", detail=f"EWS SOAP 正常，收件箱 {result['inbox']} 封")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        kind, detail = _classify(exc)
        result.update(kind=kind, detail=detail)
        print(json.dumps(result, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())

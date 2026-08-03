# -*- coding: utf-8 -*-
"""
test_email_health.py
====================
独立诊断脚本：检测 Orange OWA 邮件系统是否恢复正常。

它在「不依赖业务」的前提下，复用 owa_mail_report.py 的同一套 EWS 连接逻辑
（同一服务器、账号、认证方式、版本锁定、超时），逐项测试：

  1. TCP/HTTPS 网络连通性  —— exchmail.orange-cit.ci:443 能否建链
  2. SMTP 端口探测          —— 25 / 465 / 587 是否能连通（备用通道）
  3. EWS 登录 + SOAP 操作    —— 真实 NTLM 认证 + GetFolder（含超时）
  4. 真实发送（可选）        —— 向 dong.xinmin@zte.com.cn 发一封测试信

设计点
------
- 测试邮件**只**发往 dong.xinmin@zte.com.cn（安全铁律，绝不用真实名单）。
- 除「真实发送」外，其余步骤均为只读探测，不会对服务器产生副作用。
- 默认**不发送**，加 --send 才真正发一封测试信（便于反复敲命令做连通性观察）。
- 复用项目里已验证过的连接参数，避免测试脚本与真实发送逻辑出现偏差。

用法
----
    # 只做连通性 + 登录 + SOAP 探测（不真的发信）
    python test_email_health.py

    # 真正发一封测试信到 dong.xinmin@zte.com.cn
    python test_email_health.py --send

    # 自定义发送目标（仍必须走安全收件人，默认即合规地址）
    python test_email_health.py --send --to dong.xinmin@zte.com.cn
"""
from __future__ import annotations

import argparse
import io
import os
import socket
import sys
import time
import urllib3
import warnings
from datetime import datetime

# ---- 强制 stdout/stderr UTF-8（兼容 IDLE/PyCharm 等无 reconfigure/buffer 的环境）----
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    # IDLE 等环境的 StdOutputFile 既没有 reconfigure 也没有 buffer，跳过即可，
    # 由运行环境自身的编码处理（不强行 TextIOWrapper，避免 AttributeError）。
    try:
        if hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        if hasattr(sys.stderr, "buffer"):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        pass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# ---- 复用真实发送逻辑的连接参数（单一来源，避免偏差）----
from owa_mail_report import (  # noqa: E402
    OWA_SERVER,
    OWA_USERNAME,
    OWA_PASSWORD,
    OWA_SMTP,
    OWA_AUTH_TYPE,
    get_account,
)

_SAFE_TEST_RECIPIENT = "dong.xinmin@zte.com.cn"

# EWS SOAP 往返延迟阈值（毫秒）。超过即判定为「严重降级」：能连通但极慢/被服务端退避，
# 实际发信会超时或长时间卡住，不可靠。健康值通常 < 2-3s。
_DEGRADED_MS = 10000

# 终端配色（仅在真实 TTY 且非 IDLE 下启用，避免转义码在 IDLE 里变成乱码）
_IS_IDLE = "idlelib" in sys.modules
_USE_COLOR = (not _IS_IDLE) and bool(
    getattr(sys.stdout, "isatty", lambda: False)() if hasattr(sys.stdout, "isatty") else False
)
if _USE_COLOR:
    C_OK = "\033[92m"    # 绿
    C_FAIL = "\033[91m"  # 红
    C_WARN = "\033[93m"  # 黄
    C_DIM = "\033[2m"    # 暗
    C_BOLD = "\033[1m"
    C_RESET = "\033[0m"
else:
    C_OK = C_FAIL = C_WARN = C_DIM = C_BOLD = C_RESET = ""


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _line(label: str, ok: bool, detail: str = "", warn: bool = False) -> None:
    mark = "✓" if ok else ("!" if warn else "✗")
    color = C_OK if ok else (C_WARN if warn else C_FAIL)
    print(f"  {color}{mark}{C_RESET} {C_BOLD}{label}{C_RESET}"
          + (f"  {C_DIM}{detail}{C_RESET}" if detail else ""))


def _section(title: str) -> None:
    print(f"\n{C_BOLD}{title}{C_RESET}")
    print("  " + "-" * 48)


def test_tcp(host: str, port: int, timeout: float = 5.0) -> Tuple[bool, str]:
    """尝试 TCP 建链，返回 (是否成功, 说明)。"""
    start = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            cost = (time.time() - start) * 1000
            return True, f"connected in {cost:.0f}ms"
    except socket.timeout:
        return False, f"timeout {timeout:.0f}s (no response)"
    except socket.gaierror as e:
        return False, f"DNS/resolve error: {e}"
    except OSError as e:
        return False, f"OS error: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Test Orange OWA email health")
    ap.add_argument("--send", action="store_true", help="真正发一封测试信（默认只探测不发送）")
    ap.add_argument("--to", default=_SAFE_TEST_RECIPIENT, help="测试信收件人（默认合规地址）")
    ap.add_argument("--tcp-timeout", type=float, default=5.0, help="TCP 探测超时秒")
    ap.add_argument("--ews-timeout", type=float, default=None,
                    help="覆盖 EWS SOAP 超时（秒），默认用脚本自身值")
    ap.add_argument("--slow-threshold", type=float, default=_DEGRADED_MS / 1000.0,
                    help="SOAP 延迟超过该秒数判定为「严重降级」(默认 10s)")
    args = ap.parse_args()

    if args.send and args.to != _SAFE_TEST_RECIPIENT:
        print(f"{C_WARN}⚠ 测试收件人非合规地址 {_SAFE_TEST_RECIPIENT}，已强制改回以遵守安全规则。{C_RESET}")
        args.to = _SAFE_TEST_RECIPIENT

    print(f"{C_BOLD}Orange OWA 邮件健康检查  [{_ts()}]{C_RESET}")
    print(f"{C_DIM}server={OWA_SERVER}  user={OWA_USERNAME}  auth={OWA_AUTH_TYPE}  smtp={OWA_SMTP}{C_RESET}")

    overall = True
    degraded = False

    # 1) TCP / HTTPS
    _section("1. 网络连通性 (TCP)")
    ok, detail = test_tcp(OWA_SERVER, 443, args.tcp_timeout)
    _line(f"HTTPS 443 → {OWA_SERVER}", ok, detail)
    overall = overall and ok

    # 2) SMTP 端口探测（备用通道）
    _section("2. SMTP 备用端口探测")
    smtp_ports = [25, 465, 587]
    any_smtp = False
    for p in smtp_ports:
        ok, detail = test_tcp(OWA_SERVER, p, args.tcp_timeout)
        _line(f"SMTP {p}", ok, detail, warn=not ok)
        any_smtp = any_smtp or ok
    if not any_smtp:
        print(f"  {C_DIM}（SMTP 端口全不通属常态——本机出站 SMTP 被屏蔽，发送走 EWS 而非 SMTP）{C_RESET}")

    # 3) EWS 认证 + SOAP 往返
    # 注意：exchangelib 的 Account 对象构造是「惰性」的——构造即返回，
    # 不会真正发起 SOAP 请求。因此「登录」必须用一次真实 SOAP 往返来验证，
    # 否则会出现「登录 2ms 成功」的假阳性。这里用收件箱 GetFolder 作为真实往返。
    _section("3. EWS 认证 + SOAP 往返 (真实 NTLM 认证)")
    account = None
    cas_error = False
    try:
        if args.ews_timeout is not None:
            import exchangelib.protocol
            exchangelib.protocol.Protocol.TIMEOUT = args.ews_timeout
            print(f"  {C_DIM}(已用 --ews-timeout 覆盖 SOAP 超时 = {args.ews_timeout}s){C_RESET}")
        account = get_account()  # 惰性构造，仅建立对象
        t0 = time.time()
        # 真实 SOAP 往返：读取收件箱 (GetFolder)，验证 NTLM 认证 + CAS 能解析该邮箱
        try:
            cnt = account.inbox.total_count
            detail = f"{ (time.time()-t0)*1000:.0f}ms, 收件箱 {cnt} 封"
            cost_ms = (time.time() - t0) * 1000
            if cost_ms > args.slow_threshold * 1000:
                degraded = True
                overall = False
                _line("EWS 认证 + SOAP 往返", True, detail, warn=True)
                print(f"  {C_WARN}⚠ 响应 {cost_ms/1000:.0f}s 远超阈值 {args.slow_threshold:.0f}s "
                      f"—— 服务端严重降级/被退避，发信会超时或长时间卡住{C_RESET}")
            else:
                _line("EWS 认证 + SOAP 往返", True, detail)
        except Exception as e:
            # 收件箱读取本身抛错：区分「CAS/目录错误」与「其他」
            cost_ms = (time.time() - t0) * 1000
            ename = type(e).__name__
            estr = str(e)
            if "CAS" in ename or "Directory" in ename or "DirectoryOperation" in estr or "CASError" in estr:
                cas_error = True
                overall = False
                _line("EWS 认证 + SOAP 往返", False, f"{ename}: {estr[:160]}")
                print(f"  {C_FAIL}✗ 服务端目录/邮箱错误（CAS 无法对该邮箱做任意目录操作）{C_RESET}")
                print(f"  {C_DIM}   NTLM 认证已通过，但 EWS/CAS 对读收件箱、发信等操作统一返回 "
                      f"DirectoryOperationError —— 说明邮箱 {OWA_SMTP} 在 Exchange/AD 目录中处于异常态"
                      f"（被禁用/隔离/复制滞后），或该账号 EWS 被关闭。{C_RESET}")
                print(f"  {C_DIM}   这能解释「手动 OWA 能打开、脚本 EWS 发不出去」：OWA 走 RPC/HTTP 到邮箱服务器，"
                      f"EWS 走 CAS Web 服务，二者权限/状态可独立。非代码问题，需 Orange IT 核查该邮箱 EWS 状态。{C_RESET}")
            else:
                overall = False
                _line("EWS 认证 + SOAP 往返", False, f"{ename}: {estr[:160]}")
    except Exception as e:
        overall = False
        _line("EWS 认证 + SOAP 往返", False, f"{type(e).__name__}: {e}")
        account = None

    # 4) 真实发送（可选）
    _section("4. 真实发送测试")
    if not args.send:
        print(f"  {C_DIM}未加 --send，跳过真实发送（仅探测）。加 --send 可真正发测试信。{C_RESET}")
    else:
        if account is None:
            overall = False
            _line("发送测试信", False, "登录失败，无法发送（见上）")
        else:
            try:
                from exchangelib import Message, Mailbox
                subj = f"[TEST] OWA 邮件健康检查 {datetime.now():%Y-%m-%d %H:%M:%S}"
                body = (
                    "这是一封自动化健康检查测试信，用于确认 Orange OWA 邮件系统已恢复正常。\n"
                    f"发送时间(本地): {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                    f"服务器: {OWA_SERVER}  账号: {OWA_USERNAME}\n"
                    "若你收到此信，说明邮件系统 EWS 发送链路正常。请勿回复。"
                )
                msg = Message(
                    account=account,
                    subject=subj,
                    body=body,
                    to_recipients=[Mailbox(email_address=args.to)],
                )
                t0 = time.time()
                msg.send_and_save()
                cost = (time.time() - t0) * 1000
                _line(f"发送测试信 → {args.to}", True, f"{cost:.0f}ms")
                print(f"  {C_DIM}请登录 {args.to} 邮箱确认是否收到主题含 [TEST] 的来信。{C_RESET}")
            except Exception as e:
                overall = False
                _line(f"发送测试信 → {args.to}", False, f"{type(e).__name__}: {e}")

    # 结论
    _section("结论")
    if overall:
        print(f"  {C_OK}{C_BOLD}● 邮件系统正常{C_RESET}"
              + ("" if args.send else "（连通性+登录+SOAP 正常；未实际发送）"))
    elif cas_error:
        print(f"  {C_FAIL}{C_BOLD}● 邮件系统服务端故障（CAS/目录错误，发信必败）{C_RESET}")
        print(f"  {C_DIM}   NTLM 认证通过，但 EWS/CAS 对任意目录操作（读收件箱/发信）都返回 DirectoryOperationError。{C_RESET}")
        print(f"  {C_DIM}   当前用 {OWA_USERNAME} / {OWA_SMTP} 无法发信；这是 Exchange 服务端问题，非代码问题。{C_RESET}")
        print(f"  {C_DIM}   需联系 Orange IT 核查该邮箱的 EWS 状态（是否被禁用/隔离/复制滞后，或 EWS 被关）。{C_RESET}")
        print(f"  {C_DIM}   恢复后本脚本会显示「正常」，且 email_recovery(cron */20) 会自动补发近 3h 失败邮件。{C_RESET}")
    elif degraded:
        print(f"  {C_WARN}{C_BOLD}● 邮件系统严重降级（能连通但响应极慢/被服务端退避）{C_RESET}")
        print(f"  {C_DIM}   SOAP 往返 > 阈值，实际发信会超时或长时间卡住；建议等服务端恢复后再发。{C_RESET}")
        print(f"  {C_DIM}   可周期性重跑本脚本观察延迟是否回落到正常区间（< {args.slow_threshold:.0f}s）。{C_RESET}")
    else:
        print(f"  {C_FAIL}{C_BOLD}● 邮件系统仍存在异常{C_RESET}（见上方 ✗ 项）")
        print(f"  {C_DIM}典型原因：EWS SOAP 服务端降级/超时（exchmail.orange-cit.ci 的 CreateItem/GetFolder）。{C_RESET}")
        print(f"  {C_DIM}        TCP 通但 SOAP 失败 = 服务端问题，非代码问题，需等服务端恢复或联系 Orange IT。{C_RESET}")

    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())

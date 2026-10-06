"""无网络测试：`client_is_local` 不得被伪造的代理头旁路（2026-10-06 修复的回归守卫）。

背景见 `backend/security.py` 模块 docstring 的「XFF 伪造旁路修复」一节：
uvicorn 的 `--proxy-headers` 会在进入应用前把 `request.client.host` 改写成
`X-Forwarded-For` 里的值，只要 TCP 直连方是回环。修复前 `client_is_local()`
直接读这个被改写过的值，于是「能经由本机回环发起请求」的任何组件都能靠自带
`X-Forwarded-For: 127.0.0.1` 冒充本机 —— 实测可 200 读走 `/api/tasks/config/export`。

本测试锁定的核心性质：**远程访客经 nginx 反代后，必须仍被判定为非本机。**
一旦有人把实现改回"只看 request.client.host"，下面第一个用例会立刻失败。
"""

from backend.security import client_is_local, _is_loopback

LOOPBACK = "127.0.0.1"
REMOTE = "192.168.100.77"


class _Conn:
    def __init__(self, host):
        self.host = host


class _Req:
    """最小 Request 替身：只用到 .client.host 与 .headers。"""

    def __init__(self, peer, headers=None):
        self.client = _Conn(peer) if peer is not None else None
        self.headers = headers or {}


# ============================================================================
# 核心回归：远程访客经代理不得被当成本机
# ============================================================================

def test_remote_visitor_via_nginx_is_not_local():
    """nginx 会把真实客户端 IP 写进 X-Real-IP / XFF —— 必须据此判定为远程。"""
    assert client_is_local(_Req(LOOPBACK, {"X-Real-IP": REMOTE})) is False
    assert client_is_local(_Req(LOOPBACK, {"X-Forwarded-For": REMOTE})) is False
    assert client_is_local(
        _Req(LOOPBACK, {"X-Real-IP": REMOTE, "X-Forwarded-For": REMOTE})
    ) is False


def test_remote_visitor_cannot_spoof_loopback_header():
    """远程访客即便伪造 XFF=127.0.0.1，也不得获得本机身份。

    这是修复前的实际攻击载荷：直连 7038（对端=回环）+ 自带 XFF=127.0.0.1。
    修复后，若请求确实经 nginx 转发，nginx 会用真实 IP 覆盖该头；
    若对端本身非回环，则连看都不看这些头。
    """
    # 情形一：对端非回环（例如某个非受控入口直接连上来）
    assert client_is_local(_Req("10.1.2.3", {"X-Forwarded-For": LOOPBACK})) is False
    assert client_is_local(_Req("10.1.2.3", {"X-Real-IP": LOOPBACK})) is False
    assert client_is_local(
        _Req(REMOTE, {"X-Real-IP": LOOPBACK, "X-Forwarded-For": LOOPBACK})
    ) is False

    # 情形二：对端是回环，但代理头里是远程 IP（nginx 覆写后的真实情况）→ 必须拒绝
    assert client_is_local(
        _Req(LOOPBACK, {"X-Real-IP": REMOTE, "X-Forwarded-For": f"{REMOTE}, {LOOPBACK}"})
    ) is False


# ============================================================================
# 正常路径不得被破坏：同机调用仍须放行
# ============================================================================

def test_genuine_local_callers_still_allowed():
    """前端、调度脚本、看门狗走回环直连（无代理头），必须继续放行。"""
    assert client_is_local(_Req(LOOPBACK)) is True
    assert client_is_local(_Req("::1")) is True
    assert client_is_local(_Req("::ffff:127.0.0.1")) is True
    # 本机经 nginx 自访：nginx 覆写的头里就是回环
    assert client_is_local(_Req(LOOPBACK, {"X-Real-IP": LOOPBACK})) is True
    assert client_is_local(_Req(LOOPBACK, {"X-Forwarded-For": f"{LOOPBACK}, {LOOPBACK}"})) is True


def test_missing_client_is_not_local():
    assert client_is_local(_Req(None)) is False


# ============================================================================
# _is_loopback 边界
# ============================================================================

def test_is_loopback_covers_ipv4_mapped_and_port_forms():
    assert _is_loopback("127.0.0.1") is True
    assert _is_loopback("127.0.0.5") is True          # 整个 127.0.0.0/8
    assert _is_loopback("::1") is True
    assert _is_loopback("::ffff:127.0.0.1") is True   # IPv4-mapped IPv6
    assert _is_loopback("localhost") is True
    assert _is_loopback("127.0.0.1:8080") is True     # 带端口
    assert _is_loopback("[::1]:9000") is True

    assert _is_loopback("192.168.100.20") is False
    assert _is_loopback("10.0.0.1") is False
    assert _is_loopback("") is False
    assert _is_loopback("::ffff:192.168.100.20") is False

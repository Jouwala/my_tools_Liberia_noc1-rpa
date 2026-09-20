# -*- coding: utf-8 -*-
"""UME iMonitor 大屏嵌入页（?page=imonitor）离线接线测试 —— 不连门户、不起浏览器。

覆盖「接线容易漏、漏了线上就白屏」的几处不变量：
    1. React 页面注册齐全（lazy / PageKey / VALID_PAGES / PAGE_META / 菜单分组 / switch）
    2. 页面走的是 nginx 反代端口，且**端口号三处一致**（页面常量 / PROXY_PREFIXES / nginx conf）
    3. iframe 带 sandbox 且**不含 allow-top-navigation**（否则登录页的 frame-bust 会把
       myapp 外壳导航走 —— 门户 JS 里有 3 处 top.location 操作，实测确诊）
    4. 反代 conf 里三件事都在：摘 CSP/XFO（否则 iframe 被 frame-ancestors 拦死）、
       中和登录页内联 frame-bust、注入自动填表脚本
    5. 门户注册表里 ume_in 用的是 ume_in 凭据，且注入脚本会通知宿主登录已提交
    6. i18n 中英文案都补了
"""
import re
from pathlib import Path

from backend.services import portal_login_service as svc


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "frontend" / "src" / "pages" / "ImonitorScreen.tsx"
APP = ROOT / "frontend" / "src" / "App.tsx"
I18N = ROOT / "frontend" / "src" / "i18n.tsx"
NGINX_CONF = ROOT / "nginx" / "portal_ume_in_8088.conf"

# nginx 实际生效的那份（不在仓库里，缺失时只跳过端口一致性这一条）
NGINX_LIVE = Path(r"Y:\01_RPA\nginx-1.28.0\conf\portal_ports.conf")


def _page_text() -> str:
    return PAGE.read_text(encoding="utf-8")


# ==========================================================================
# 1. React 接线
# ==========================================================================
def test_react_page_is_registered_everywhere():
    app = APP.read_text(encoding="utf-8")
    assert "const ImonitorScreen = lazy(() => import('./pages/ImonitorScreen'))" in app
    assert "'imonitor'" in app.split("type PageKey =", 1)[1].split("\n", 1)[0]
    assert "'imonitor'" in app.split("const VALID_PAGES", 1)[1].split("\n", 1)[0]
    assert "imonitor: { icon:" in app and "'nav.imonitor'" in app
    # 菜单分组里出现（否则页面在侧栏没有入口）
    assert re.search(r"items: \[[^\]]*'imonitor'", app), "imonitor 未加入任何菜单分组"
    # renderPage 的 switch 分支
    assert re.search(r"case 'imonitor':\s*\n\s*return <ImonitorScreen />", app)


def test_registered_in_soft_refresh_pages():
    """跨端口 iframe 不能靠外壳重挂载刷新（会整页闪白），必须走软刷新协议。"""
    app = APP.read_text(encoding="utf-8")
    line = next((ln for ln in app.splitlines()
                 if "AR_SOFT_REFRESH_PAGES" in ln and "=" in ln), "")
    assert "'imonitor'" in line, line
    assert "'myapp-refresh'" in _page_text()


def test_i18n_keys_exist_in_both_locales():
    i18n = I18N.read_text(encoding="utf-8")
    assert i18n.count("'nav.imonitor'") == 2
    for key in ("imonitor.tip", "imonitor.refresh", "imonitor.relogin",
                "imonitor.open", "imonitor.fullscreen", "imonitor.loading"):
        assert i18n.count(f"'{key}'") == 2, f"{key} 缺中英文之一"


# ==========================================================================
# 2. 端口三处一致 + 上游地址
# ==========================================================================
def _page_port() -> str:
    m = re.search(r"const PORTAL_PORT = (\d+)", _page_text())
    assert m, "页面里没有 PORTAL_PORT 常量"
    return m.group(1)


def test_port_matches_backend_proxy_prefix():
    port = _page_port()
    assert svc.PROXY_PREFIXES["ume_in"] == f"//{{HOST}}:{port}"


def test_port_matches_nginx_conf():
    port = _page_port()
    conf = NGINX_CONF.read_text(encoding="utf-8")
    assert f"listen       {port};" in conf
    assert f"proxy_pass          https://172.17.208.1:28808;" in conf


def test_port_matches_live_nginx_if_present():
    """仓库留档与线上生效配置必须一致（漏同步时线上会静默 404/打不开）。"""
    if not NGINX_LIVE.is_file():
        return
    port = _page_port()
    live = NGINX_LIVE.read_text(encoding="utf-8", errors="replace")
    assert f"listen       {port};" in live
    assert "proxy_pass          https://172.17.208.1:28808;" in live


# ==========================================================================
# 3. iframe sandbox：必须禁掉顶层导航
# ==========================================================================
def test_iframe_sandbox_blocks_top_navigation():
    text = _page_text()
    m = re.search(r'sandbox="([^"]*)"', text)
    assert m, "iframe 没有 sandbox —— 登录页的 top.location 会把 myapp 外壳导航走"
    tokens = set(m.group(1).split())
    assert "allow-top-navigation" not in tokens
    assert "allow-top-navigation-by-user-activation" not in tokens
    # 门户要靠 same-origin 读写自己的 Cookie/localStorage，否则登录态存不住
    assert {"allow-scripts", "allow-same-origin", "allow-forms"} <= tokens


def test_page_targets_the_screen_deeplink_via_proxy():
    text = _page_text()
    assert "'/iui/guard-imonitor-iui/'" in text
    assert "'#/screen/screen-view?screen_id=1'" in text
    # 不能写死回环地址：远程访问者打开 myapp 时 127.0.0.1 是他自己那台机器。
    # 只看代码行 —— 注释里正解释「为什么不能写死 127.0.0.1」，会被误伤。
    code = "\n".join(
        ln for ln in text.splitlines()
        if not ln.strip().startswith(("*", "//", "/*"))
    )
    assert "127.0.0.1" not in code
    assert "window.location.hostname" in code


# ==========================================================================
# 4. nginx 反代三件事
# ==========================================================================
def test_nginx_conf_strips_framing_headers_and_injects_autologin():
    conf = NGINX_CONF.read_text(encoding="utf-8")
    # ① 上游带 CSP: frame-ancestors 'self'，不摘掉 iframe 直接被浏览器拦死
    assert "proxy_hide_header   Content-Security-Policy;" in conf
    assert "proxy_hide_header   X-Frame-Options;" in conf
    assert "proxy_hide_header   Strict-Transport-Security;" in conf
    # ② 中和登录页内联 frame-bust
    assert "sub_filter 'top.location = self.location;'" in conf
    # ③ 注入自动填表脚本
    assert 'sub_filter \'</head>\' \'<script src="/api/portals/inject.js?system=ume_in"></script></head>\'' in conf
    # sub_filter 要看到明文 HTML，必须关掉上游压缩
    assert 'proxy_set_header Accept-Encoding   "";' in conf
    # Cookie 要落到访问者主机上（门户 Cookie 名带端口后缀，不能跨门户共用）
    assert "proxy_cookie_domain 172.17.208.1 $host;" in conf


# ==========================================================================
# 5. 门户注册表 + 注入脚本通知
# ==========================================================================
def test_portal_registry_entry():
    spec = svc.PORTALS["ume_in"]
    assert spec["cred_key"] == "ume_in"
    assert spec["kind"] == "oauth2"
    assert (spec["default_host"], spec["default_port"]) == ("172.17.208.1", 28808)
    assert svc.build_login_url(spec).startswith(
        "https://172.17.208.1:28808/api/oauth2/v1/authorize?scope=user.login")


def test_inject_js_notifies_host_after_submit():
    """登录成功只会回落到 redirect_uri 根路径，hash 深链必丢 —— 宿主靠这条消息重指。"""
    js = svc.build_inject_js("ume_in", "u", "p")
    assert "myapp-portal-autologin" in js
    assert "window.parent.postMessage" in js
    # 宿主侧的监听要认这个 system
    assert "myapp-portal-autologin" in _page_text()
    assert "'ume_in'" in _page_text()

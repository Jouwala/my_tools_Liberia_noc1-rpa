"""
portal_login_service.py - 一键通过默认浏览器登录内部门户
================================================================

背景：各系统（ZTE UME / CCN UME / iPRAN UME / eFlow / FW(UMC) / VMAX CXO）的
用户名密码已集中在「系统设置 → 凭据」(backend/services/credential_store.py) 维护。
本模块让用户在 my_app 里点一下，就用**本机默认浏览器**打开对应门户并自动登录，
省去每次手工输入账号密码。

实现要点：
- 复用 credential_store.get_credential() 读取当前生效凭据（环境变量 > 数据库 > 代码默认）。
- 浏览器用【普通子进程】启动本机 Chrome（`--remote-debugging-port=0` + 独立 user-data-dir，
  **不传 `--enable-automation`**），再用 CDP 连上去做自动登录；登录后**断开 CDP 但保持窗口打开**
  供用户继续使用。历史：曾用 Playwright，其 CDP 连接会启用 Debugger 域，触发门户的反调试
  `debugger;` 语句把页面冻结 → 已弃用。自签证书用 CDP `Security.setIgnoreCertificateErrors`
  绕过，不再用 `--ignore-certificate-errors`（新版 Chrome 已禁用该 flag）。
- 多数门户的登录加密都在页面 JS 里完成（RSA / DES+SM3 / SM4 等），因此统一采用
  「填充用户名/密码 → 点击真实登录按钮」的方式，由页面自身完成加密提交，无需在
  Python 端复刻各套加密算法。
- eFlow / RAIS 例外：走「**直接鉴权**」——Python 端复刻各自加密算法拿会话
  （eFlow：RSA+OAuth2；RAIS：AES-256-CBC 换 SSO token），再用 CDP 把 cookie 种进浏览器，
  然后打开已登录主页，完全绕开登录页 DOM。
- 每个系统维护一个常驻浏览器会话（LIVE），用户可手动关闭或经 API 关闭。

> 注意：本模块在后端 Web 进程（uvicorn）里起一个后台线程驱动浏览器。默认浏览器
  必须运行在与用户相同的 Windows 桌面会话（start.bat 以当前用户拉起，满足），
  否则 headed 浏览器可能无法显示。
"""
import base64
import os
import re
import time
import uuid
import logging
import threading
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)

MY_APP_DIR = Path(__file__).resolve().parents[2]
PROFILE_ROOT = MY_APP_DIR / "data" / "portal_profiles"

# ============ 门户注册表 ============
# kind:
#   oauth2 -> ZTE UME 系 OAuth2 RSA 登录页（统一 login 表单 + 跳转 default.html/em-portal/...）
#   umc    -> DPtech UMC 经典登录（DES/SM3，页面 JS 加密，登录后跳 main.action）
#   vmax   -> VMAX CXO（RSA 加密，登录后跳 framework 主页）
PORTALS = {
    "zte_ume": {
        "name": "ZTE UME 网管",
        "name_en": "ZTE UME NMS",
        "cred_key": "zte_ume",
        "kind": "oauth2",
        "host_env": "RAN_UME_HOST", "port_env": "RAN_UME_PORT",
        "default_host": "10.100.28.27", "default_port": 28001,
        "redirect": "/uportal/framework/default.html",
        "success_regex": r"https://[^/]+/uportal/framework/default\.html",
    },
    "ccn_ume": {
        "name": "CCN UME 网管",
        "name_en": "CCN UME NMS",
        "cred_key": "ccn_ume",
        "kind": "oauth2",
        "host_env": None, "port_env": None,
        "default_host": "10.121.1.2", "default_port": 28808,
        "redirect": "/em-portal",
        "success_regex": r"https://[^/]+/em-portal",
    },
    "ipran_ume": {
        "name": "iPRAN UME 网管",
        "name_en": "iPRAN UME NMS",
        "cred_key": "ipran_ume",
        "kind": "oauth2",
        "host_env": "IPRAN_UME_HOST", "port_env": "IPRAN_UME_PORT",
        "default_host": "10.100.2.99", "default_port": 28001,
        "redirect": "/portal-athena/framework/default.html",
        "success_regex": r"https://[^/]+/portal-athena/framework/default\.html",
    },
    "eflow": {
        "name": "eFlow 告警系统",
        "name_en": "eFlow Alarm System",
        "cred_key": "eflow",
        "kind": "oauth2",
        "host_env": "EFLOW_HOST", "port_env": "EFLOW_PORT",
        "default_host": "10.100.20.8", "default_port": 28001,
        "redirect": "/uportal/framework/default.html",
        "success_regex": r"https://[^/]+/uportal/framework/default\.html",
        # 前端把根地址写死为 http://localhost，经同源反代后子页面/接口会打到访问者本机
        # → 客户端模式必须直连上游（不反代、无填表），见前端 DIRECT_PORTALS。
        "direct": True,
    },
    "rais": {
        "name": "RAIS 统一权限平台",
        "name_en": "RAIS Permission Platform",
        "cred_key": "rais",
        # RAIS 是 UAC-Lite 的 hash 路由 SPA（/raisprod/uacliteweb/），登录不靠页面填表，
        # 而是 POST verify4web.serv（AES-256-CBC 加密密码）换 token，再把 token 写成
        # SSO cookie 打开主页 —— 与 eFlow 的「直接鉴权」同一套路。
        "kind": "rais",
        "host_env": "RAIS_HOST", "port_env": "RAIS_PORT",
        "default_host": "10.100.20.9", "default_port": 8766,
        # 入口路径（hash 路由，SPA 会自动落到登录页）
        "login_path": "/raisprod/uacliteweb/#/login",
        # 直接鉴权成功后的落地页
        "redirect": "/raisprod/uacliteweb/#/homepage",
        # URL 离开登录页且停在 #/homepage 视为成功
        "success_regex": r"#/homepage",
        # 首屏就绪判定：hash 切到 #/homepage 是瞬时的，必须等 #app 真正渲染出内容
        # （用户名 / 工作台入口），否则截图与文案探针会误判成空白页。
        "ready_js": ("(() => { const a = document.querySelector('#app');"
                     " return !!(a && a.innerText && a.innerText.trim().length > 100); })()"),
        # 直接鉴权接口前缀（见 _rais_direct_auth）
        "api_base": "/raisprod/uaclite",
        # 客户端模式直连上游：不经 nginx 反代（RAIS 前端把 API 根地址写死为
        # https://10.100.20.9:8766/，反代到别的 host 会让登录响应种不下 cookie）
        "direct": True,
    },
    "fw_kpi": {
        "name": "FW 整机吞吐 (UMC)",
        "name_en": "FW Throughput (UMC)",
        "cred_key": "fw_kpi",
        "kind": "umc",
        "host_env": "FW_UME_HOST", "port_env": "FW_UME_PORT",
        "default_host": "10.100.2.101", "default_port": 443,
        "login_path": "/UMC/Login!start.action",
        # UMC 登录后跳 main.action；成功 = URL 离开 Login!start 且不含 login 字样
        "success_regex": None,
    },
    "vmax_cxo": {
        "name": "VMAX CXO 经营看板",
        "name_en": "VMAX CXO Dashboard",
        "cred_key": "vmax_cxo",
        "kind": "vmax",
        # 登录页有图形验证码（captchaInput），无法全自动 → 注入脚本只预填
        # 账号密码，用户在浏览器里输验证码后自己点登录
        "captcha": True,
        "host_env": "VMAX_HOST", "port_env": "VMAX_PORT",
        "default_host": "10.123.255.12", "default_port": 26180,
        "login_path": "/web/iui/framework/default.html",
        "success_regex": None,
    },
    "mw_ume": {
        "name": "MW UME 微波网管",
        "name_en": "MW UME (ZXMW Microwave) NMS",
        "cred_key": "mw_ume",
        "kind": "oauth2",
        "host_env": "MW_UME_HOST", "port_env": "MW_UME_PORT",
        "default_host": "192.168.169.247", "default_port": 28001,
        "redirect": "/uportal/framework/default.html",
        "success_regex": r"https://[^/]+/uportal/framework/default\.html",
    },
    # UME iMonitor 大屏门户（172.17.208.1:28808）——「客户业务 KPI」同步任务用的同一套
    # em-portal 账号（credential_store key=ume_in）。这里加进注册表有两个作用：
    #   1) 「门户登录」页出现一键登录入口（server 模式 = 本机 Chrome 自动填表）；
    #   2) client 模式经 nginx 8088 反代（见 PROXY_PREFIXES），登录页注入自动填表脚本，
    #      会话 Cookie 落在**访问者自己的浏览器**里 —— iMonitor 大屏页
    #      （?page=imonitor，frontend/src/pages/ImonitorScreen.tsx）正是靠这份
    #      浏览器会话在 iframe 里直接打开 https://172.17.208.1:28808/iui/guard-imonitor-iui/。
    "ume_in": {
        "name": "UME iMonitor 大屏 (172.17.208.1:28808)",
        "name_en": "UME iMonitor Screen (172.17.208.1:28808)",
        "cred_key": "ume_in",
        "kind": "oauth2",
        "host_env": "UME_IN_HOST", "port_env": "UME_IN_PORT",
        "default_host": "172.17.208.1", "default_port": 28808,
        "redirect": "/em-portal/",
        # 登录成功即落到 /em-portal/（该页再 meta refresh 到 framework/default.html）
        "success_regex": r"https://[^/]+/em-portal",
    },
    # Battery UME（192.168.170.2:443）——「电池 KPI」同步/邮件任务用的同一套账号
    # （credential_store key=battery_ume）。加进注册表后「门户登录」页出现一键登录入口，
    # 便于在图形验证码弹出时人工登录一次并核对账号密码是否有效。
    "battery_ume": {
        "name": "Battery UME 电池网管 (192.168.170.2:443)",
        "name_en": "Battery UME NMS (192.168.170.2:443)",
        "cred_key": "battery_ume",
        "kind": "oauth2",
        "host_env": "BATT_HOST", "port_env": "BATT_PORT",
        "default_host": "192.168.170.2", "default_port": 443,
        "redirect": "/uportal/framework/default.html",
        "success_regex": r"https://[^/]+/uportal/framework/default\.html",
        # 该 UME 前端把根地址写死为 https://192.168.170.2/，反代到别的 host 会
        # 让会话 Cookie 种不下 → 客户端模式直连上游（与 eflow / rais 同理）。
        "direct": True,
    },
    # OSS Portal（ZTE UME 服务器网管 10.121.8.2，Keystone v3 登录）。
    # 复用凭据组 ume_alarm（「DC server alarm WhatsApp push」任务同一套账号），
    # 不新增凭据组、不写第二份口令。
    # ⚠ 该门户的登录页由 Angular 渲染，账号/密码输入框没有稳定 id 与 name，
    #   只能用 placeholder 定位（见 _FIND_USER_SEL_JS / _build_fill_js 的 type=text 兜底）。
    #   实测若页面结构再变，一键登录会报「未找到登录表单」，此时用 client 模式手输登录。
    "oss_portal": {
        "name": "OSS Portal 服务器网管 (10.121.8.2)",
        "name_en": "OSS Portal Server NMS (10.121.8.2)",
        "cred_key": "ume_alarm",
        "kind": "oauth2",   # 仅用于 build_login_url 的兜底；实际入口见 login_path
        "host_env": None, "port_env": None,
        "default_host": "10.121.8.2", "default_port": 443,
        "login_path": "/ngportal/login",
        # 登录成功后 Keystone 门户会跳到框架主页，用模块地址作为成功判据
        "success_regex": r"/ngportal/(?!login)",
        # 前端把根地址/接口写死为 https://10.121.8.2/ → 客户端模式直连上游
        "direct": True,
    },
}


def resolve_endpoint(spec: dict):
    """解析门户 host/port：环境变量 > 代码默认。"""
    host = os.environ.get(spec["host_env"]) if spec.get("host_env") else None
    port = os.environ.get(spec["port_env"]) if spec.get("port_env") else None
    host = host or spec["default_host"]
    port = int(port) if port else spec["default_port"]
    return host, port


def build_login_url(spec: dict):
    host, port = resolve_endpoint(spec)
    # 显式给了 login_path 的门户按该路径打开（如 oss_portal 的 /ngportal/login）
    if spec.get("login_path"):
        return f"https://{host}:{port}{spec['login_path']}"
    if spec["kind"] == "oauth2":
        return (f"https://{host}:{port}/api/oauth2/v1/authorize"
                f"?scope=user.login&response_type=code&redirect_uri={spec['redirect']}")
    # umc / vmax
    return f"https://{host}:{port}{spec['login_path']}"


# ============ 常驻浏览器会话 & 任务状态 ============
LIVE: dict = {}                 # system_key -> {proc, started_at, profile_dir}
LIVE_LOCK = threading.Lock()
JOBS: dict = {}                 # job_id -> {system, state, message, log[], start, end}
JOBS_LOCK = threading.Lock()
_JOBS_MAX = 50

# 每个门户各起一个独立 Chrome 进程（独立临时 profile）；关闭时只 kill 该进程。
# 多门户 = 多个独立窗口，各自可单独 Close，互不干扰。
def _job_update(job_id, **fields):
    with JOBS_LOCK:
        j = JOBS.setdefault(job_id, {})
        # log 字段做「追加」而非整体替换，保证诊断链路完整（填充/兜底/提交/失败诊断都能看到）
        log = fields.pop("log", None)
        if log is not None:
            j.setdefault("log", []).extend(log)
        j.update(fields)
        # 简单裁剪，避免无界增长
        if len(JOBS) > _JOBS_MAX:
            old = sorted(JOBS.keys(), key=lambda k: JOBS[k].get("start", 0))[:10]
            for k in old:
                JOBS.pop(k, None)


def _close_live(system_key: str):
    with LIVE_LOCK:
        sess = LIVE.pop(system_key, None)
    if not sess:
        return
    pd = sess.get("profile_dir")
    proc = sess.get("proc")
    # 因为我们登录后已断开 CDP、浏览器是普通进程，关闭=直接结束该 Chrome 进程
    try:
        if proc is not None and proc.poll() is None:
            proc.kill()
    except Exception:
        logger.warning("[PORTAL] 关闭浏览器进程失败", exc_info=True)
    # 清理临时 profile 目录，避免磁盘堆积
    if pd and os.path.exists(pd):
        try:
            import shutil
            shutil.rmtree(pd, ignore_errors=True)
        except Exception:
            pass


# ============ 默认浏览器探测 ============
def get_default_browser_exe() -> str | None:
    """探测本机浏览器可执行文件路径（仅 Windows）。

    优先级：
      1) Google Chrome（本机若装有 Chrome 则优先使用）
      2) 系统默认浏览器（注册表 UserChoice -> ProgId -> shell\\open\\command）
      3) 其它常见 Chromium 系（Edge 等）
      4) 都找不到则回退到 playwright 自带 chromium（返回 None）
    """
    if os.name != "nt":
        return None

    # 1) 优先 Google Chrome
    chrome_candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for cand in chrome_candidates:
        if os.path.exists(cand):
            logger.info(f"[PORTAL] 选用 Google Chrome: {cand}")
            return cand

    # 2) 系统默认浏览器（注册表）
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        )
        progid = winreg.QueryValueEx(key, "ProgId")[0]
        key2 = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{progid}\shell\open\command")
        cmd = winreg.QueryValueEx(key2, "")[0]
        m = re.search(r'"([^"]+\.exe)"', cmd) or re.search(r"(\S+\.exe)", cmd)
        if m:
            exe = m.group(1).strip().strip('"')
            if exe.lower().endswith(".exe") and os.path.exists(exe):
                logger.info(f"[PORTAL] 默认浏览器: {exe} (ProgId={progid})")
                return exe
    except Exception:
        logger.warning("[PORTAL] 注册表探测默认浏览器失败，尝试常见路径", exc_info=True)

    # 3) 其它常见 Chromium（Edge 等）
    edge_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for cand in edge_candidates:
        if os.path.exists(cand):
            logger.info(f"[PORTAL] 回退浏览器路径: {cand}")
            return cand

    logger.info("[PORTAL] 未找到本机 Chromium 浏览器，将使用 playwright 自带 chromium")
    return None


# ============ 表单填充（统一「填用户名/密码 + 点登录按钮」） ============
USERNAME_CANDIDATES = [
    "#inputUserName", "input[name='username']", "#username",
    "input[id='username']", "input[name='user']", "input[name='j_username']",
    "input[type='text']",
]
PASSWORD_CANDIDATES = [
    "#inputCiphercode", "input[name='cipher_code']", "#password",
    "input[name='password']", "input[id='password']", "input[name='p']",
    "input[type='password']",
]
SUBMIT_CANDIDATES = [
    "#loginBut", "button:has-text('Login')", "button:has-text('登录')",
    "button:has-text('Sign in')", "input[type='submit']",
    "button[type='submit']", "button.login-btn", "button.btn-login",
]


def _detect(page, candidates, timeout=8000):
    for sel in candidates:
        if not sel:
            continue
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible(timeout=timeout):
                return sel
        except Exception:
            continue
    return None


def _fill_and_submit(page, user, pwd):
    """在已打开的登录页上填充凭据并提交。返回 (submitted: bool, info: str)。"""
    user_sel = _detect(page, USERNAME_CANDIDATES)
    if not user_sel:
        return False, "未找到用户名输入框（页面可能未加载或表单结构不同）"
    try:
        page.locator(user_sel).wait_for(state="visible", timeout=10000)
    except Exception:
        pass
    page.locator(user_sel).fill(user)

    pwd_sel = _detect(page, PASSWORD_CANDIDATES)
    if pwd_sel:
        try:
            page.locator(pwd_sel).fill(pwd)
        except Exception:
            page.locator(pwd_sel).focus(force=True)
            page.keyboard.type(pwd, delay=40)
    else:
        logger.warning("[PORTAL] 未找到密码框，仅填了用户名")

    submit_sel = _detect(page, SUBMIT_CANDIDATES)
    if not submit_sel:
        return True, "已填充凭据，但未找到登录按钮（可能页面有验证码，请手动点击登录）"
    try:
        page.locator(submit_sel).click(timeout=8000)
    except Exception:
        try:
            page.locator(submit_sel).click(force=True)
        except Exception:
            page.evaluate(f"() => {{ const b=document.querySelector({submit_sel!r}); if(b) b.click(); }}")
    return True, "已填充凭据并提交登录"


def _wait_success(page, spec, timeout=30000):
    """等待登录成功。oauth2 用精确 URL 正则；umc/vmax 用宽松判断。返回 (ok, info)。"""
    if spec.get("success_regex"):
        try:
            page.wait_for_url(re.compile(spec["success_regex"]), timeout=timeout)
            # 关键：等 SPA 框架 bootstrap + 事件绑定完成，否则用户去点应用卡片时
            # JS 可能还没就绪 → 链接/卡片看起来已渲染但点击无响应。
            # 1) 等 networkidle（最稳的"页面加载完"信号，best-effort）
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                logger.warning("[PORTAL] 等待 networkidle 超时（继续）")
            # 2) AngularJS 风格：等 ng-cloak 元素消失（bootstrap 完成的标志）
            try:
                page.wait_for_function(
                    "() => !document.querySelector('[ng-cloak],[data-ng-cloak]')",
                    timeout=8000,
                )
            except Exception:
                pass
            # 3) 再额外等 2 秒，让剩余的 click handler 绑定 / 动画 / 懒加载跑完
            try:
                page.wait_for_timeout(2000)
            except Exception:
                pass
            # 4) 诊断日志：记录页面状态、内容区尺寸、iframe，帮助排查
            try:
                diag = page.evaluate("""() => {
                    const iframes = Array.from(document.querySelectorAll('iframe'));
                    const main = document.querySelector(
                        'main, [role="main"], .main-content, .content, #content, .workspace, .app-launcher, .launcher'
                    );
                    return {
                        readyState: document.readyState,
                        viewport: { w: window.innerWidth, h: window.innerHeight },
                        iframes: iframes.length,
                        iframeSrcs: iframes.map(f => f.src || '(empty)').slice(0, 3),
                        ngCloak: document.querySelectorAll('[ng-cloak],[data-ng-cloak]').length,
                        bodyOverflow: getComputedStyle(document.body).overflow,
                        docHeight: document.documentElement.scrollHeight,
                        mainEl: main ? {
                            tag: main.tagName,
                            cls: (main.className || '').slice(0, 80),
                            w: main.offsetWidth, h: main.offsetHeight,
                        } : null,
                    };
                }""")
                logger.info(f"[PORTAL] 登录后页面诊断: {diag}")
            except Exception:
                pass
            return True, f"已跳转至门户主页 ({page.url})"
        except Exception:
            return False, "未在超时内跳转到门户主页（可能账号密码错误 / 需验证码 / 表单结构变化）"
    # 宽松判断：URL 离开登录页且页面无失败提示
    deadline = time.time() + timeout / 1000
    login_url = page.url
    fail_kw = ["登录失败", "login failed", "认证失败", "用户名或密码", "invalid", "incorrect"]
    while time.time() < deadline:
        try:
            cur = page.url
            if cur != login_url and "login" not in cur.lower() and "Login" not in cur:
                # 再确认没有失败文案
                txt = page.content().lower()
                if not any(k in txt for k in fail_kw):
                    return True, f"已离开登录页 ({cur})"
            # 检查失败文案
            txt = page.content().lower()
            if any(k in txt for k in fail_kw):
                return False, "页面出现登录失败提示，请检查凭据或验证码"
        except Exception:
            pass
        time.sleep(1.0)
    return False, "登录结果不确定：URL 未明显变化，请在已打开的浏览器中确认登录状态"


# ============ 启动后浏览器状态修正（证书 / 最大化） ============


def _handle_cert_error(page):
    """若页面停留在 Chrome 自签证书告警页（chrome-error:// / net::ERR_CERT_*），
    自动点「继续访问 / Proceed」，否则页面是证书警告屏、无法交互、链接也打不开。"""
    try:
        url = page.url or ""
        if "chrome-error://" not in url and "ERR_CERT" not in url and "ERR_SSL" not in url:
            return False
        logger.warning(f"[PORTAL] 检测到证书告警页，尝试自动继续: {url}")
        page.evaluate(
            "() => {"
            "  const go = () => {"
            "    const p = document.getElementById('proceed-link');"
            "    if (p) { p.click(); return true; }"
            "    const adv = document.getElementById('details-button');"
            "    if (adv) { adv.click(); const p2 = document.getElementById('proceed-link');"
            "      if (p2) { p2.click(); return true; } }"
            "    const btns = Array.from(document.querySelectorAll('button'));"
            "    const t = btns.find(x => /继续|proceed|advance/i.test(x.textContent || ''));"
            "    if (t) { t.click(); return true; }"
            "    return false;"
            "  };"
            "  return go();"
            "}"
        )
        page.wait_for_timeout(2000)
        return True
    except Exception:
        logger.warning("[PORTAL] 处理证书告警页失败（忽略）", exc_info=True)
        return False


# ============ 强制最大化（Windows API） ============
def _maximize_window(exe):
    """强制把浏览器窗口最大化（仅用 Windows API，最可靠）。"""
    try:
        _win32_maximize_by_exe(exe)
    except Exception:
        logger.warning("[PORTAL] win32 最大化失败（忽略）", exc_info=True)


def _win32_maximize_by_exe(exe: str):
    """通过 Windows API 找到由 exe 启动的浏览器主窗口并最大化。"""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    SW_MAXIMIZE = 3
    exe_norm = os.path.normpath(exe).lower()
    pid = wintypes.DWORD(0)
    found = 0

    # 设置精确参数类型，避免 64 位调用约定错误
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, lparam):
        nonlocal found
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(64)
        if user32.GetClassNameW(hwnd, cls, 64) == 0:
            return True
        if cls.value not in ("Chrome_WidgetWin_1", "Chrome_WidgetWin_0"):
            return True
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        p = pid.value
        if not p:
            return True
        h = kernel32.OpenProcess(0x1000, False, p)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return True
        try:
            buf = ctypes.create_unicode_buffer(2048)
            n = wintypes.DWORD(2048)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                if os.path.normpath(buf.value).lower() == exe_norm:
                    user32.ShowWindow(hwnd, SW_MAXIMIZE)
                    try:
                        user32.SetForegroundWindow(hwnd)
                    except Exception:
                        pass
                    found += 1
        finally:
            kernel32.CloseHandle(h)
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return found > 0


# ============ 原始 CDP 登录（不启用 Debugger 域，登录后断开连接） ============
def _build_fill_js(user: str, pwd: str) -> str:
    """生成在页面里执行的填表 JS。凭据用 json.dumps 编码，避免注入问题。

    关键点：用原生 value setter + 派发 input/change 事件，让 Angular/React 等
    受控输入框能感知到值的变化（直接 .value= 框架拿不到）。
    """
    import json as _json
    u = _json.dumps(user)
    p = _json.dumps(pwd)
    return (
        "(() => {\n"
        "  const U = " + u + ";\n"
        "  const P = " + p + ";\n"
        "  function fire(el, type){ el.dispatchEvent(new Event(type, {bubbles:true})); }\n"
        "  function setVal(el, val){\n"
        "    const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;\n"
        "    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;\n"
        "    setter.call(el, val);\n"
        "    fire(el, 'input'); fire(el, 'change');\n"
        "  }\n"
        "  // 部分门户（如 OSS Portal /ngportal/login）由 Angular 渲染，输入框无 id/name，"
        "只能靠 placeholder 识别\n"
        "  const ucss = ['#inputUserName', \"input[name='username']\", '#username', \"input[id='username']\", \"input[name='user']\", \"input[name='j_username']\", \"input[placeholder*='用户名']\", \"input[placeholder*='账号']\", \"input[placeholder*='ser' i]\", \"input[placeholder*='ccount' i]\", \"input[type='text']\"];\n"
        "  const pcss = ['#inputCiphercode', \"input[name='cipher_code']\", '#password', \"input[name='password']\", \"input[id='password']\", \"input[name='p']\", \"input[placeholder*='密码']\", \"input[placeholder*='assword' i]\", \"input[type='password']\"];\n"
        "  function find(sels){ for (const s of sels){ try { const el = document.querySelector(s); if (el && el.offsetWidth > 0) return el; } catch(e){} } return null; }\n"
        "  function findSubmit(){\n"
        "    const sels = ['#loginBut', \"input[type='submit']\", \"button[type='submit']\", '.login-btn', '.btn-login', '.login-button'];\n"
        "    let b = find(sels); if (b) return b;\n"
        "    const btns = Array.from(document.querySelectorAll('button, input[type=submit], a.btn'));\n"
        "    for (const x of btns){ const t = (x.textContent || x.value || '').trim().toLowerCase(); if (/登录|login|sign\\\\s*in|submit/.test(t)) return x; }\n"
        "    return null;\n"
        "  }\n"
        "  const u = find(ucss);\n"
        "  if (!u) return JSON.stringify({ok:false, msg:'no username input'});\n"
        "  setVal(u, U);\n"
        "  const pw = find(pcss);\n"
        "  if (pw) setVal(pw, P);\n"
        "  const sub = findSubmit();\n"
        "  const out = {ok:true, userSel:null, userSet:!!u, pwdSel:null, pwdSet:!!pw, submitSel:null, msg:'filled'};\n"
        "  out.userSel = u ? (u.id ? '#'+u.id : (u.name ? \"input[name='\"+u.name+\"']\" : 'input[type=text]')) : null;\n"
        "  out.pwdSel = pw ? (pw.id ? '#'+pw.id : (pw.name ? \"input[name='\"+pw.name+\"']\" : 'input[type=password]')) : null;\n"
        "  out.submitSel = sub ? (sub.id ? '#'+sub.id : (sub.textContent||sub.value||'button')) : null;\n"
        "  return JSON.stringify(out);\n"
        "})()"
    )


async def _cdp_wait_success(send, eval_js, spec, login_url):
    """轮询登录结果：URL 跳转 或 失败文案。"""
    success_regex = spec.get("success_regex")
    fail_kw = ["登录失败", "login failed", "认证失败", "用户名或密码", "invalid", "incorrect", "密码错误"]
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            res = await eval_js(
                "(() => ({url: location.href, txt: (document.body ? document.body.innerText : '').slice(0, 4000).toLowerCase()}))()")
            val = (res.get("result", {}).get("result", {}) or {}).get("value", {})
            url = val.get("url", "")
            txt = val.get("txt", "")
            if success_regex and re.search(success_regex, url):
                return True, f"已跳转至门户主页 ({url})"
            if "login" not in url.lower():
                if not any(k in txt for k in fail_kw):
                    return True, f"已离开登录页 ({url})"
            if any(k in txt for k in fail_kw):
                return False, "页面出现登录失败提示，请检查凭据或验证码"
        except Exception as e:
            logger.warning(f"[PORTAL] 轮询登录状态出错: {e}")
        await asyncio.sleep(1.5)
    return False, "登录结果不确定：URL 未明显变化，请在已打开的浏览器中确认登录状态"


# 轮询等待登录表单：返回匹配到的用户名输入框选择器，或空串（未找到）
_FIND_USER_SEL_JS = (
    "(() => {"
    "  function vis(el){ if(!el) return false; if(el.disabled) return false;"
    "    const t=(el.type||'').toLowerCase(); if(t==='hidden') return false;"
    "    if(el.offsetWidth>0||el.offsetHeight>0) return true; return el.offsetParent!==null; }"
    "  const sels=['#inputUserName',\"input[name='username']\",'#username',"
    "    \"input[id='username']\",\"input[name='user']\",\"input[name='j_username']\","
    "    \"input[placeholder*='用户名']\",\"input[placeholder*='账号']\","
    "    \"input[placeholder*='ser' i]\",\"input[placeholder*='ccount' i]\","
    "    'input[type=text]'];"
    "  for(const s of sels){ try{ const el=document.querySelector(s); if(el&&vis(el)) return s; }catch(e){} }"
    "  return '';"
    "})()"
)

# 诊断：dump 当前页面 url/title/输入框/按钮/正文，便于登录失败时定位根因
_CDP_DIAG_JS = (
    "(() => {"
    "  try{"
    "    const inp=Array.from(document.querySelectorAll('input,select,textarea')).slice(0,15)"
    "      .map(e=>({t:e.tagName,id:e.id||'',n:e.name||'',ty:e.type||'',"
    "        vlen:(e.value||'').length,vis:(e.offsetWidth>0||e.offsetHeight>0||e.offsetParent!==null)}));"
    "    const btn=Array.from(document.querySelectorAll('button')).slice(0,15)"
    "      .map(b=>(b.textContent||'').trim().slice(0,30));"
    "    return JSON.stringify({url:location.href,title:(document.title||'').slice(0,80),"
    "      inputs:inp,btns:btn,body:(document.body?document.body.innerText:'').slice(0,400)});"
    "  }catch(e){ return JSON.stringify({error:String(e)}); }"
    "})()"
)


async def _cdp_login(port, login_url, user, pwd, spec, job_id):
    """通过原始 CDP（WebSocket）连接 Chrome 做自动登录，然后断开连接（不关浏览器）。

    关键：
      - 只启用 Runtime / Page / Security / Input 域，**绝不启用 Debugger 域**，否则 eFlow
        的 anti-debugger `debugger;` 会触发 “Debugger paused in another tab” 并把页面冻结。
      - **先轮询等待登录表单真正渲染**（冷加载 / Angular bootstrap 可能 >5s），再填充；
        避免此前「盲等 5s 就填」在表单未就绪时找不到输入框、导致用户名密码根本没填进去。
      - 填充后**校验字段值是否真的写入**；若受控组件吞掉 .value 赋值，则改用
        CDP Input.insertText（模拟真实键入）兜底，确保凭据确实进入输入框。
      - **先填后提交**：确认凭据已进框再点登录（不再在填充里顺手点，避免空值提交）。
      - 登录完成后只 close WebSocket，不发送 Browser.close，浏览器继续作为正常浏览器运行。
    """
    import json as _json
    import urllib.request
    import websockets

    base = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{base}/json", timeout=5) as r:
            targets = _json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return False, f"无法读取 CDP targets: {e}"

    target = None
    for t in targets:
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            target = t
            break
    if target is None and targets:
        target = targets[0]
    if not target or not target.get("webSocketDebuggerUrl"):
        return False, "未找到可用的 CDP page target"

    ws_url = target["webSocketDebuggerUrl"]
    msg_id = [0]

    async with websockets.connect(ws_url, max_size=None) as ws:
        async def send(method, params=None, await_resp=True):
            msg_id[0] += 1
            mid = msg_id[0]
            payload = {"id": mid, "method": method}
            if params is not None:
                payload["params"] = params
            await ws.send(_json.dumps(payload))
            if not await_resp:
                return None
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                data = _json.loads(raw)
                if data.get("id") == mid:
                    return data

        async def eval_js(expr, await_resp=True):
            return await send("Runtime.evaluate",
                             {"expression": expr, "returnByValue": True,
                              "awaitPromise": True}, await_resp=await_resp)

        async def type_into(selector, text):
            """聚焦字段全选清空，用 CDP insertText 真实键入（兜底受控组件吞值）。"""
            sel_js = _json.dumps(selector)
            await eval_js(
                "(() => { const el=document.querySelector(" + sel_js + "); if(!el) return false;"
                " el.focus(); try{ const v=el.value||''; el.setSelectionRange(0, v.length); }catch(e){}"
                " return true; })()",
                await_resp=False,
            )
            await send("Input.insertText", {"text": text}, await_resp=False)
            await asyncio.sleep(0.4)

        # 启用必要域（不含 Debugger）
        await send("Runtime.enable", await_resp=False)
        await send("Page.enable", await_resp=False)
        await send("Security.enable", await_resp=False)
        await send("Security.setIgnoreCertificateErrors", {"ignore": True}, await_resp=False)
        await send("Input.enable", await_resp=False)

        cur = target.get("url", "")
        if not cur or cur in ("about:blank", "chrome://newtab/", "chrome://new-tab-page/"):
            await send("Page.navigate", {"url": login_url}, await_resp=False)
        else:
            # 重新导航以越过可能已出现的证书告警页
            await send("Page.navigate", {"url": login_url}, await_resp=False)

        # 轮询等待登录表单的输入框真正出现并可交互（最多 25s）
        user_sel = ""
        for _ in range(25):
            try:
                r = await eval_js(_FIND_USER_SEL_JS)
                user_sel = (r.get("result", {}).get("result", {}) or {}).get("value", "") or ""
            except Exception:
                user_sel = ""
            if user_sel:
                break
            await asyncio.sleep(1.0)
        if not user_sel:
            try:
                d = await eval_js(_CDP_DIAG_JS)
                diag = (d.get("result", {}).get("result", {}) or {}).get("value", "")
                logger.warning(f"[PORTAL] 未找到登录表单，页面诊断: {diag}")
                _job_update(job_id, log=[f"未找到登录表单输入框。诊断: {diag}"])
            except Exception:
                pass
            return False, "未在超时内找到登录表单输入框（页面可能未加载/证书拦截/表单结构变化）"

        # 填充用户名/密码（此时表单已就绪；_build_fill_js 只填不提交）
        res = await eval_js(_build_fill_js(user, pwd))
        info = ""
        try:
            info = res.get("result", {}).get("result", {}).get("value", "")
        except Exception:
            pass
        _job_update(job_id, log=[f"填充结果: {info}"])
        logger.info(f"[PORTAL] CDP 填表结果: {info}")

        # 校验字段值是否真的写入；未写入则改用 insertText 兜底（先填后提交的关键）
        check_js = (
            "(() => {"
            "  function val(sels){ for(const s of sels){ try{ const el=document.querySelector(s);"
            "    if(el) return el.value; }catch(e){} } return null; }"
            "  const u=['#inputUserName',\"input[name='username']\",'#username',"
            "    \"input[name='user']\",\"input[name='j_username']\",'input[type=text]'];"
            "  const p=['#inputCiphercode',\"input[name='cipher_code']\",'#password',"
            "    \"input[name='password']\",\"input[name='p']\",'input[type=password]'];"
            "  return JSON.stringify({u:val(u), p:val(p)});"
            "})()"
        )
        try:
            cv = await eval_js(check_js)
            cvj = _json.loads((cv.get("result", {}).get("result", {}) or {}).get("value", "{}") or "{}")
        except Exception:
            cvj = {}
        if cvj.get("u") != user:
            logger.warning(f"[PORTAL] 用户名原生赋值未生效(={cvj.get('u')!r})，改用 insertText 兜底")
            _job_update(job_id, log=["用户名原生赋值未生效，改用 insertText 兜底"])
            await type_into(user_sel, user)
        if cvj.get("p") != pwd:
            logger.warning("[PORTAL] 密码原生赋值未生效，改用 insertText 兜底")
            _job_update(job_id, log=["密码原生赋值未生效，改用 insertText 兜底"])
            await type_into(
                "#inputCiphercode,input[name='cipher_code'],#password,input[name='password'],"
                "input[name='p'],input[type=password]", pwd)

        # 确认凭据已入框后再点登录按钮（避免空值提交）
        submit_js = (
            "(() => {"
            "  function vis(el){ if(!el||el.disabled) return false; const t=(el.type||'').toLowerCase();"
            "    if(t==='hidden') return false; if(el.offsetWidth>0||el.offsetHeight>0) return true;"
            "    return el.offsetParent!==null; }"
            "  function find(sels){ for(const s of sels){ try{ const el=document.querySelector(s);"
            "    if(el&&vis(el)) return el; }catch(e){} } return null; }"
            "  const sels=['#loginBut',\"input[type='submit']\",\"button[type='submit']\","
            "    '.login-btn','.btn-login','.login-button'];"
            "  let b=find(sels); if(b){ b.click(); return 'clicked:'+(b.id||b.textContent||'btn'); }"
            "  const btns=Array.from(document.querySelectorAll('button,input[type=submit],a.btn'));"
            "  for(const x of btns){ const t=(x.textContent||x.value||'').trim().toLowerCase();"
            "    if(/登录|login|sign\\s*in|submit/.test(t)){ x.click(); return 'clicked:'+t; } }"
            "  return 'no-submit';"
            "})()"
        )
        try:
            sj = await eval_js(submit_js)
            sres = (sj.get("result", {}).get("result", {}) or {}).get("value", "")
            _job_update(job_id, log=[f"提交: {sres}"])
            logger.info(f"[PORTAL] 提交登录: {sres}")
        except Exception as e:
            logger.warning(f"[PORTAL] 点击登录按钮出错: {e}")

        ok, sinfo = await _cdp_wait_success(send, eval_js, spec, login_url)
        if not ok:
            try:
                d = await eval_js(_CDP_DIAG_JS)
                diag = (d.get("result", {}).get("result", {}) or {}).get("value", "")
                logger.warning(f"[PORTAL] 登录未成功，页面诊断: {diag}")
                _job_update(job_id, log=[f"登录未成功诊断: {diag}"])
            except Exception:
                pass
        return ok, sinfo
    # async with 退出时仅关闭 WebSocket，不发送 Browser.close → 浏览器继续作为正常浏览器运行


# ============ 核心：启动浏览器并登录 ============
def launch_and_login(system_key: str, browser: str | None = None, job_id: str | None = None) -> dict:
    """同步执行：启动默认浏览器、填充凭据、提交登录、保持窗口打开。

    供后台线程调用。返回结果 dict，同时会写入 LIVE（保持浏览器存活）与 JOBS。
    job_id 由调用方预生成并传入，确保前端轮询拿到的 id 与 JOBS 中一致。
    """
    if not job_id:
        job_id = uuid.uuid4().hex[:12]
    spec = PORTALS[system_key]
    _job_update(job_id, system=system_key, state="launching",
               message="正在启动浏览器...", log=[], start=time.time())

    # 先关掉该系统已有的会话，避免多开
    try:
        _close_live(system_key)
    except Exception:
        pass

    login_url = build_login_url(spec)
    user, pwd = _creds(spec["cred_key"])
    _job_update(job_id, log=[f"登录地址: {login_url}", f"账号: {user}"])

    proc = None
    profile_dir = None
    try:
        import subprocess
        import shutil
        import asyncio
        exe = get_default_browser_exe() if browser in (None, "default") else browser
        PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
        # 每次启动都用【全新临时 profile】，彻底避免旧 session 恢复出
        # "Debugger paused in another tab" 等残留 tab 挡住交互。
        for stale in [PROFILE_ROOT / system_key] + list(PROFILE_ROOT.glob(f"_tmp_{system_key}_*")):
            try:
                if stale.exists():
                    shutil.rmtree(stale, ignore_errors=True)
            except Exception:
                pass
        profile_dir = str(PROFILE_ROOT / f"_tmp_{system_key}_{uuid.uuid4().hex[:10]}")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        logger.info(f"[PORTAL] 用普通子进程启动 Chrome（无 --enable-automation，navigator.webdriver=false）: {profile_dir}")

        # 以【普通子进程】启动 Chrome：不带 Playwright 自动化标记，仅开
        # --remote-debugging-port 供我们 CDP 连上去做自动登录。关键：登录完成后
        # 我们【断开 CDP 连接】但【不关闭浏览器】，于是浏览器变为完全正常的浏览器，
        # 没有任何 debugger 附着 —— 这正是之前 "Debugger paused in another tab" +
        # 点不动 + 输网址打不开 的根因（Playwright 的 CDP 连接启用了 Debugger 域，
        # 触发 eFlow 的 anti-debugger `debugger;` 语句把页面冻结）。
        # 注意：不再传 --ignore-certificate-errors（新版 Chrome 已禁用该 flag 并弹警告），
        # 改为 CDP Security.setIgnoreCertificateErrors 绕过自签证书。
        proc = subprocess.Popen(
            [exe,
             f"--user-data-dir={profile_dir}",
             "--remote-debugging-port=0",
             "--start-maximized",
             "--no-first-run",
             "--no-default-browser-check",
             login_url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        # 读取 Chrome 写入 user-data-dir/DevToolsActivePort 的远程调试端口
        devtools_file = os.path.join(profile_dir, "DevToolsActivePort")
        port = None
        for _ in range(50):
            if os.path.exists(devtools_file):
                try:
                    with open(devtools_file, "r", encoding="utf-8") as f:
                        port = int(f.readline().strip())
                    break
                except Exception:
                    pass
            time.sleep(0.1)
        if not port:
            try:
                line = proc.stderr.readline().decode("utf-8", "ignore")
                m = re.search(r"127\.0\.0\.1:(\d+)", line)
                if m:
                    port = int(m.group(1))
            except Exception:
                pass
        if not port:
            raise RuntimeError("无法获取 Chrome 远程调试端口（浏览器可能启动失败）")

        # CDP 登录（异步）：连接 -> 绕过证书 -> 填表 -> 等成功 -> 【断开 socket 不断浏览器】
        ok, sinfo = asyncio.run(_cdp_login(
            port=port, login_url=login_url, user=user, pwd=pwd,
            spec=spec, job_id=job_id,
        ))

        # 强制最大化窗口（--start-maximized 在部分机器不可靠，win32 兜底）
        _maximize_window(exe)

        # 只保留子进程引用：浏览器已是正常进程，关闭时 kill 即可（不再持有 CDP/Playwright 对象）
        _keep_alive(system_key, proc, profile_dir)
        _job_update(job_id, state="success" if ok else "failed", message=sinfo, end=time.time())
        return _job_result(job_id, ok, sinfo)
    except Exception as e:
        logger.warning(f"[PORTAL] 登录失败 {system_key}: {e}", exc_info=True)
        # 出错：清理可能残留的 Chrome 进程与临时 profile
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        if profile_dir and os.path.exists(profile_dir):
            try:
                import shutil
                shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception:
                pass
        _job_update(job_id, state="failed", message=f"异常: {type(e).__name__}: {e}", end=time.time())
        return _job_result(job_id, False, f"异常: {type(e).__name__}: {e}")


# ============ eFlow 直接鉴权登录（不填表、不依赖登录页 DOM） ============
# 背景：eFlow 登录页有 anti-debugger（debugger;）且靠页面 JS 做 RSA 加密，
# 「填充表单 + 点按钮」这条链路脆弱（受登录页 DOM 结构、anti-debugger、SPA
# bootstrap 时序影响）。而项目里已有稳定可用的【直接鉴权】实现：
#   backend/services/auth_manager.get_auth(host, port, user, pwd)
# 它复刻 eFlow 的 RSA+OAuth2 登录协议（authorize -> publickey -> login_rsa），
# 直接返回会话 cookie（Z-AUTH-CODE-28001 等）+ forgery_token，eFlow 数据同步
# 任务一直在用它。本函数把它复用到「一键门户登录」：直接鉴权拿会话 -> 用 CDP
# Network.setCookie 把会话种到本机 Chrome 的 eFlow 域 -> 打开 eFlow 主页即已登录，
# 完全绕开「页面 JS 加密 + 填表」。
#
# 注意：这只对【坐在 my_app 服务器本机】的浏览器有效——会话 cookie 必须种进
# 能向 eFlow 服务器发请求的那个浏览器。远程访问者的浏览器受同源策略限制，
# 后端无法跨域种 cookie，此时应回退到 client 模式（本机直连 eFlow 填表）。

def _eflow_direct_auth(spec: dict):
    """直接鉴权走 ZTE OAuth2 RSA 登录的门户，返回会话 cookie 串。

    适用所有 ``kind == "oauth2"`` 的直连门户（eflow / battery_ume 等）：
    调用 auth_manager 复刻 RSA+OAuth2 登录流程。
    返回 (cookie_str, forgery_token)；失败抛异常。

    2026-10-06：接入 `_portal_probe(spec)` 探活。此前这里直接吃 `get_auth`
    的缓存快路径（只按 TTL 判过期、不探活），于是「一键登录总落回登录页」——
    后端把一个已经死掉的会话 cookie 种进了访问者浏览器，门户自然弹回登录页。
    RAN UME 实测会话 113 分钟即失效，而 TTL 当时是 86400。
    """
    from backend.services.auth_manager import get_auth
    host, port = resolve_endpoint(spec)
    user, pwd = _creds(spec["cred_key"])
    auth = get_auth(host, port, user, pwd, probe=_portal_probe(spec))
    return auth["cookie"], auth["forgery_token"]


# 语义化别名：新代码按「OAuth2 直连鉴权」而非「eFlow 专用」来读更清楚。
_oauth2_direct_auth = _eflow_direct_auth


# ============ 门户会话探活（2026-10-06） ============
# 为什么需要：`get_auth` 的快路径只按 created_at + ttl 判过期、不探活，
# 缓存「没过期」≠ 会话「还能用」。上游会因同账户再次登录、服务端空闲回收、
# 运维重启等原因随时作废一个还没到 TTL 的会话。把这种死会话种进访问者浏览器，
# 用户看到的就是「一键登录后又落回登录页」。
#
# ⚠️ 必须探**业务端点**，探登录首页会拿到误导性的 200（假绿）—— MW UME
# 2026-10-04 实测：首页 200，业务端点 401。所以下面每台都用各自真正在用的
# 业务接口。
#
# 未登记的门户返回 None ＝ 不探活，退回「只信 TTL」的历史行为。这是刻意的：
# 与其拿一个猜出来的端点去探（探错会把好会话判死、无谓增加登录），
# 不如显式留空，等有实测依据再补。**新增探活前先确认该端点确实要求鉴权。**


def _probe_json_endpoint(base: str, path: str, cookie: str,
                         forgery_token: str, timeout: int = 10) -> bool:
    """通用探活：向业务端点发一发空 body 的 POST，401/403 判死。

    上游先校验会话再解析参数，所以空 body 会得到 400/500 之类的参数错误
    —— 那恰恰证明会话是活的。只有 401/403 才说明会话不可用。
    """
    import requests
    try:
        from backend.security_tls import tls_verify, silence_insecure_warning
    except ImportError:  # pragma: no cover
        tls_verify = lambda _s: False  # noqa: E731
        silence_insecure_warning = lambda _v: None  # noqa: E731
    verify = tls_verify("ume")
    silence_insecure_warning(verify)
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie,
        "Referer": f"{base}/uportal/framework/default.html",
        "X-Requested-With": "XMLHttpRequest",
    }
    if forgery_token:
        # 裸 forgerydefense（不带端口后缀）—— 带后缀同样 403
        headers["forgerydefense"] = forgery_token
    try:
        r = requests.post(f"{base}{path}", headers=headers, json={},
                          verify=verify, timeout=timeout)
        alive = r.status_code not in (401, 403)
        if not alive:
            logger.info("[PORTAL] 会话已失效（探测 %s -> %s）", path, r.status_code)
        return alive
    except Exception as e:  # noqa: BLE001
        # 区分「探测本身坏了」与「会话真死了」：否则日志里两者长得一样
        logger.warning("[PORTAL] 会话探测异常（%s: %s），按不可用处理",
                       type(e).__name__, e)
        return False


# 门户 key → 探活用的业务端点（相对于 https://host:port）。
# 只登记**有实测依据**的端点；其余保持 None（不探活）。
PORTAL_PROBE_PATHS: dict[str, str] = {
    # UME 系（zte_ume / ccn_ume / ipran_ume / mw_ume / ume_in）共用 PM history
    # 业务端点，与 ran_ume_service.probe_pm_session 同一选择。
    # 依据：各服务的 HISTORY_PATH 常量都指向 /api/pm-analysis/v2/history
    # （ume_in 见 ume_in_kpi_service.py:67，MW 见 mw_ume_kpi_service.py 的 HISTORY_PATH）。
    "zte_ume": "/api/pm-analysis/v2/history",
    "ccn_ume": "/api/pm-analysis/v2/history",
    "ipran_ume": "/api/pm-analysis/v2/history",
    "mw_ume": "/api/pm-analysis/v2/history",
    # iMonitor 大屏（172.17.208.1:28808）：**确实走 auth_manager**
    # （build_client_login_plan 的通用分支调 _oauth2_direct_auth，见本文件
    # 「通用分支」注释），所以探活能生效。它与 MW UME 是同一套 UME PM-analysis
    # 协议、同一个 history 端点（ume_in_kpi_service.py:67）。
    # 这台此前正是「一键登录总落回登录页」的嫌疑对象之一。
    "ume_in": "/api/pm-analysis/v2/history",
    # Battery UME（192.168.170.2:443）：**不是 UME PM-analysis 协议**，
    # 不能用上面那个端点，必须用电池自己的业务接口。
    # 依据：battary_kpi_fetch_socket.py:258 的 PATH_GET_BY_CONDITION，
    # 正是 battery_kpi_sync 每小时真正在用的分页实时数据接口。
    #
    # 实测（2026-10-06，用原样多段 cookie 串）：
    #   · 垃圾 cookie  -> 401 {"source":"smagent",...}  -> 判死 ✅
    #   · 无 cookie    -> 401                            -> 判死 ✅
    #   · 真实会话 + 空 body {} -> 200 {"code":0,...}    -> 判活 ✅
    #   与生产同路径 `_post_json` 的结果一致（200，total=1532），不误杀。
    #
    # ⚠ 反面证据：门户首页 /uportal/framework/default.html **不能**当探针 ——
    # 它对「无 cookie」也返回 200（SPA 外壳，响应体与带垃圾 cookie 时逐字节相同）。
    # 用它探活会把死会话判成活的（假绿），这正是「一键登录落回登录页」的成因之一。
    "battery_ume": "/api/monitor-manager/v1/realtime-data/get-by-condition",
    # eFlow（10.100.20.8:28001）：kind=oauth2 → 走 auth_manager.get_auth，
    # 所以探活确实生效（与 battery_ume 同一条路径）。
    #
    # 端点取自 eflow_api_client.py:122 的 ALARM_API_PATH —— **生产真在用的**
    # 活动告警列表接口，不是猜的路径。
    #
    # 实测（2026-10-06，POST 空 body {}，走生产 _http_request 含 forgerydefense 头）：
    #   · 无 cookie   -> 401 {"source":"smagent","redirect_uri":"/api/oauth2/v1/authorize?..."}
    #   · 垃圾 cookie -> 401 {"hasLogged":true,"source":"smagent",...}   -> 判死 ✅
    #   · 真实会话    -> 200（真实告警 JSON，含 alarmtitle/mename 等字段）-> 判活 ✅
    #
    # ⚠ 两个坑，都实际踩过：
    #   1) `/uportal/framework/default.html`（门户首页）对无 cookie 也返回 200
    #      —— SPA 外壳，与 battery 那个首页同一种假绿，**不可作探针**。
    #   2) 自己用 urllib 拼请求会得到 403 `code=3329008 cross-site access`，
    #      因为漏了生产头的 `forgerydefense`。**探针必须复用生产请求路径**，
    #      否则会把真实会话误判成死的。这一点与 battery_ume 的探针同理。
    "eflow": "/api/fm-active/v1/activealarms/table",
}


def _portal_key(spec: dict) -> str:
    """反查 spec 在 `PORTALS` 里的门户键。

    注册表是 `{门户键: spec}`，**键不在 spec 内部**，而探活端点要按键查。
    优先用调用方显式注入的 `_key`（`_iter_portals()` 会加），否则按 spec
    对象身份反查 —— 这样即使调用方直接持有 spec（如各 `direct` 分支），
    也能拿到正确的键，不必让每个调用点都记得去注入。
    """
    key = spec.get("_key")
    if key:
        return key
    for k, v in PORTALS.items():
        if v is spec:
            return k
    return ""


def _portal_probe(spec: dict):
    """按门户 spec 返回探活函数；未登记的门户返回 None（不探活）。

    ⚠️ 门户标识是 `PORTALS` 的**字典键**，spec 里没有 `key` 字段 ——
    按 `spec["key"]` 取会永远拿不到值、静默退化成「全部门户都不探活」
    （2026-10-07 接线自检时抓到过这个 bug）。改用 `_portal_key()` 反查。
    """
    path = PORTAL_PROBE_PATHS.get(_portal_key(spec))
    if not path:
        return None
    host, port = resolve_endpoint(spec)
    base = f"https://{host}:{port}"

    def _probe(cookie, forgery_token):
        return _probe_json_endpoint(base, path, cookie, forgery_token)

    return _probe


def _iter_portals():
    """遍历门户注册表，给每个 spec 注入它自己的键名（`_key`）。

    注册表是 `{门户键: spec}`，而 `_portal_probe` 需要按键查探活端点；
    键不在 spec 里，所以统一在这里注入，避免每个调用点各拼一次。
    """
    for key, spec in PORTALS.items():
        yield key, {**spec, "_key": key}


def _split_cookies(cookie_str: str) -> list[dict]:
    """把 'k1=v1; k2=v2; ...' 会话串拆成 CDP Network.setCookie 所需的 dict 列表。"""
    out = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        out.append({"name": name.strip(), "value": value.strip()})
    return out


# 门户主页「真的渲染出来了」的判定（直接鉴权路径共用）。
# ⚠️ 只判 URL 或「innerText 非空」会假成功：2026-09-13 实测 eFlow 主页其实整页停在
# "This request is prohibited for cross-site access / Your session is error."，
# 却因为探针「拿到任意非空文本就 break」被报成「已登录」。
# 正证据：正文渲染出足够内容 + 无会话错误文案 + 无可见密码框（登录页特征）。
PORTAL_READY_JS = (
    "(() => { const b = document.body; if (!b) return false;"
    " const t = b.innerText || '';"
    " if (t.trim().length < 120) return false;"
    " if (/session is error|cross-site|prohibited|please login again"
    "|重新登录|会话已失效|跨站/i.test(t)) return false;"
    " const pw = document.querySelectorAll('input[type=password]');"
    " for (let i = 0; i < pw.length; i++) { const el = pw[i];"
    " if (el.offsetWidth > 0 || el.offsetHeight > 0 || el.offsetParent !== null) return false; }"
    " return true; })()"
)

# 会话被拒 / 未登录的文案特征（中英），命中即判定失败
_SESSION_ERR_RE = re.compile(
    r"session is error|cross-site|prohibited|please login again"
    r"|重新登录|会话已失效|跨站", re.I)


async def _cdp_set_eflow_cookies(port: int, host: str, cookie_str: str,
                                 csrf_token: str | None = None,
                                 origin_url: str | None = None,
                                 job_id: str | None = None):
    """通过 CDP 连接把 eFlow 会话 cookie 种到本机 Chrome 的 eFlow 域。

    返回 (成功种入的 cookie 数, csrftoken 是否写入)。只启用 Network/Runtime 域
    （不启用 Debugger 域，避免触发 eFlow 的 anti-debugger 冻结页面）。

    ⚠️ 必须同时补写 localStorage 的 csrftoken（JSON 串）与 forgerydefense（裸值）：门户的
    跨站防护要求前端把 `forgerydefense` 响应头的值带进后续请求，但不同消费方读的键与格式
    不同。只写 csrftoken 时纯 REST 的工单页正常，「当前告警」页（读 forgerydefense）却是
    整页空白。历史上还出现过完全没写 → 页面所有接口 403
    "This request is prohibited for cross-site access"、
    "Your session is error. Please login again."（2026-09-12 实测确诊）。

    ⚠️⚠️ 写 localStorage 前【必须等启动页真正落到 eFlow 源】（2026-09-13 实测确诊）：
    Chrome 一启动 DevToolsActivePort 就出现，此时页面还停在 about:blank
    （origin=null 的不透明源）。在不透明源上执行 localStorage.setItem 会抛
    SecurityError → csrftoken 写不进去（旧日志里的
    "csrftoken 写入 localStorage：失败（接口可能 403）"）→ 主页整页渲染
    "Your session is error. Please login again."。表现为「窗口打开了但没登录」，
    且因旧的成功判定太松常被误报成「已登录」。
    """
    import json as _json
    import urllib.request
    import websockets

    base = f"http://127.0.0.1:{port}"
    with urllib.request.urlopen(f"{base}/json", timeout=5) as r:
        targets = _json.loads(r.read().decode("utf-8"))
    target = None
    for t in targets:
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            target = t
            break
    if target is None and targets:
        target = targets[0]
    if not target or not target.get("webSocketDebuggerUrl"):
        raise RuntimeError("未找到可用的 CDP page target")

    ws_url = target["webSocketDebuggerUrl"]
    msg_id = [0]
    set_count = 0

    async with websockets.connect(ws_url, max_size=None) as ws:
        async def send(method, params=None, await_resp=True):
            msg_id[0] += 1
            mid = msg_id[0]
            payload = {"id": mid, "method": method}
            if params is not None:
                payload["params"] = params
            await ws.send(_json.dumps(payload))
            if not await_resp:
                return None
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                data = _json.loads(raw)
                if data.get("id") == mid:
                    return data

        async def eval_js(expr):
            r = await send("Runtime.evaluate",
                           {"expression": expr, "returnByValue": True})
            res = (r or {}).get("result", {}) or {}
            if res.get("exceptionDetails"):
                raise RuntimeError(f"JS 异常: {str(res['exceptionDetails'])[:160]}")
            return (res.get("result", {}) or {}).get("value")

        await send("Network.enable", await_resp=False)
        await send("Runtime.enable", await_resp=False)
        await send("Page.enable", await_resp=False)
        await send("Security.setIgnoreCertificateErrors", {"ignore": True}, await_resp=False)

        # 0) 等启动页真正落到 eFlow 源（about:blank 上写 localStorage 会抛 SecurityError）
        nav_url = origin_url or f"https://{host}/"

        async def _on_portal_origin() -> str:
            """返回当前页面 href；已在门户源上才算就绪（否则返回空串）。"""
            try:
                info = await eval_js("(() => ({href: location.href, rs: document.readyState}))()")
            except Exception:
                return ""
            href = str((info or {}).get("href") or "")
            if not href.startswith(("https://", "http://")):
                return ""
            netloc = href.split("//", 1)[1].split("/", 1)[0]
            return href if netloc.split(":")[0] == host else ""

        cur = ""
        for attempt in range(2):
            deadline = time.time() + 25
            while time.time() < deadline:
                cur = await _on_portal_origin()
                if cur:
                    break
                await asyncio.sleep(0.5)
            if cur:
                break
            # 兜底：启动页迟迟不落门户源 → 主动整页导航到门户入口再等
            _job_update(job_id, log=[f"启动页未落到 {host}（当前 {cur or 'about:blank'}），"
                                     "主动导航到门户入口"])
            await send("Page.navigate", {"url": nav_url}, await_resp=False)
        if not cur:
            raise RuntimeError(f"启动页未落到 eFlow 源（host={host}），无法写入 csrftoken")
        _job_update(job_id, log=[f"启动页已落到门户源：{cur[:120]}"])

        domain = host  # eFlow 无独立域名，直接以 host 作为 cookie domain
        for ck in _split_cookies(cookie_str):
            r = await send("Network.setCookie", {
                "name": ck["name"],
                "value": ck["value"],
                "domain": domain,
                "path": "/",
                # Z-AUTH-CODE 等会话 cookie 非持久，httpOnly 依服务端 Set-Cookie 属性
                "httpOnly": True,
                "secure": True,
            })
            if r.get("result", {}).get("success") is not False:
                set_count += 1
        if set_count == 0:
            raise RuntimeError("会话 cookie 一个都没种进去（CDP setCookie 全失败）")

        # 补写防伪令牌（门户前端从 forgerydefense 响应头取值后 JSON 序列化存盘）
        # ⚠️ 两个键都要写且格式不同：csrftoken = JSON 串（框架 store()/angularFm CometD 会
        # JSON.parse），forgerydefense = 裸值（uportal 告警语音 WebSocket 与 getCsrfValue 的
        # SM 场景直接当请求头用）。只写 csrftoken 时「当前告警」页拿到 null → 整页空白。
        # 写后回读校验；失败重试（页面可能正在重定向，源被换掉）
        csrf_ok = False
        if csrf_token:
            expr = ("(() => { try {"
                    " localStorage.setItem('csrftoken', %s);"
                    " localStorage.setItem('forgerydefense', %s);"
                    " return JSON.stringify([localStorage.getItem('csrftoken'),"
                    " localStorage.getItem('forgerydefense')]); }"
                    " catch (e) { return 'ERR:' + e; } })()"
                    % (_json.dumps(_json.dumps(csrf_token)), _json.dumps(csrf_token)))
            for _ in range(3):
                try:
                    val = await eval_js(expr)
                except Exception as e:
                    val = f"ERR:{e}"
                try:
                    got = _json.loads(str(val))
                except Exception:
                    got = []
                if (isinstance(got, list) and len(got) == 2
                        and str(got[0]).strip('"') == csrf_token and got[1] == csrf_token):
                    csrf_ok = True
                    break
                _job_update(job_id, log=[f"csrftoken/forgerydefense 写入未生效（{str(val)[:80]}），重试"])
                await asyncio.sleep(0.8)
    return set_count, csrf_ok


def launch_and_login_eflow_direct(system_key: str, browser: str | None = None,
                                  job_id: str | None = None) -> dict:
    """eFlow 专用：直接鉴权（RSA+OAuth2 复刻登录）拿会话 -> CDP 种 cookie -> 打开已登录主页。

    与 launch_and_login 的区别：不填表、不点登录按钮，绕开登录页 DOM 依赖与
    anti-debugger。其余（启动 Chrome、保持窗口、LIVE/JOBS 记账）逻辑一致。
    """
    if not job_id:
        job_id = uuid.uuid4().hex[:12]
    spec = PORTALS[system_key]
    host, port = resolve_endpoint(spec)
    _job_update(job_id, system=system_key, state="launching",
               message="正在直接鉴权...", log=[], start=time.time())

    try:
        _close_live(system_key)
    except Exception:
        pass

    proc = None
    profile_dir = None
    try:
        # 1) 直接鉴权（复用已验证的 auth_manager，走 RSA+OAuth2，无浏览器）
        _job_update(job_id, log=[f"直接鉴权 eFlow {host}:{port} ..."])
        cookie_str, forgery_token = _eflow_direct_auth(spec)
        _job_update(job_id, log=[f"鉴权成功，获取会话 cookie（{len(_split_cookies(cookie_str))} 项）"])

        import subprocess
        import shutil
        import asyncio
        exe = get_default_browser_exe() if browser in (None, "default") else browser
        PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
        for stale in [PROFILE_ROOT / system_key] + list(PROFILE_ROOT.glob(f"_tmp_{system_key}_*")):
            try:
                if stale.exists():
                    shutil.rmtree(stale, ignore_errors=True)
            except Exception:
                pass
        profile_dir = str(PROFILE_ROOT / f"_tmp_{system_key}_{uuid.uuid4().hex[:10]}")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        # 2) 启动 Chrome：先打开 eFlow 登录入口（种 cookie 后会被重定向到已登录主页）
        login_url = build_login_url(spec)
        _job_update(job_id, log=["启动浏览器（直接鉴权模式）"])
        proc = subprocess.Popen(
            [exe,
             f"--user-data-dir={profile_dir}",
             "--remote-debugging-port=0",
             "--start-maximized",
             "--no-first-run",
             "--no-default-browser-check",
             login_url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        # 3) 读取远程调试端口
        devtools_file = os.path.join(profile_dir, "DevToolsActivePort")
        dport = None
        for _ in range(50):
            if os.path.exists(devtools_file):
                try:
                    with open(devtools_file, "r", encoding="utf-8") as f:
                        dport = int(f.readline().strip())
                    break
                except Exception:
                    pass
            time.sleep(0.1)
        if not dport:
            raise RuntimeError("无法获取 Chrome 远程调试端口（浏览器可能启动失败）")

        # 4) 种 cookie + 补写 CSRF token + 重新导航到已登录主页
        _job_update(job_id, log=["向浏览器写入 eFlow 会话 cookie + CSRF token ..."])
        set_count, csrf_ok = asyncio.run(
            _cdp_set_eflow_cookies(dport, host, cookie_str, forgery_token,
                                   origin_url=login_url, job_id=job_id))
        _job_update(job_id, log=[
            f"已种入 {set_count} 个会话 cookie",
            f"csrftoken 写入 localStorage：{'成功' if csrf_ok else '失败（接口可能 403）'}",
        ])

        # 5) 用 CDP 重新导航到 eFlow 门户主页（此时携带会话 cookie → 直接进入已登录态）
        ok, sinfo = asyncio.run(_cdp_navigate_and_verify(
            dport, host, port, spec, job_id,
        ))

        # 6) 最大化 + 保活
        _maximize_window(exe)
        _keep_alive(system_key, proc, profile_dir)
        _job_update(job_id, state="success" if ok else "failed", message=sinfo, end=time.time())
        return _job_result(job_id, ok, sinfo)
    except Exception as e:
        logger.warning(f"[PORTAL] eFlow 直接鉴权登录失败 {system_key}: {e}", exc_info=True)
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        if profile_dir and os.path.exists(profile_dir):
            try:
                import shutil
                shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception:
                pass
        _job_update(job_id, state="failed", message=f"异常: {type(e).__name__}: {e}", end=time.time())
        return _job_result(job_id, False, f"异常: {type(e).__name__}: {e}")


async def _cdp_navigate_and_verify(port: int, host: str, eport: int, spec: dict, job_id: str):
    """种完 cookie 后，用 CDP 导航到 eFlow 门户主页并验证是否已登录（URL 离开登录页）。"""
    import json as _json
    import urllib.request
    import websockets

    base = f"http://127.0.0.1:{port}"
    with urllib.request.urlopen(f"{base}/json", timeout=5) as r:
        targets = _json.loads(r.read().decode("utf-8"))
    target = None
    for t in targets:
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            target = t
            break
    if target is None and targets:
        target = targets[0]
    if not target or not target.get("webSocketDebuggerUrl"):
        return False, "未找到可用的 CDP page target"

    ws_url = target["webSocketDebuggerUrl"]
    msg_id = [0]
    home_url = f"https://{host}:{eport}{spec.get('redirect', '/uportal/framework/default.html')}"

    async with websockets.connect(ws_url, max_size=None) as ws:
        async def send(method, params=None, await_resp=True):
            msg_id[0] += 1
            mid = msg_id[0]
            payload = {"id": mid, "method": method}
            if params is not None:
                payload["params"] = params
            await ws.send(_json.dumps(payload))
            if not await_resp:
                return None
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                data = _json.loads(raw)
                if data.get("id") == mid:
                    return data

        async def eval_js(expr):
            """返回表达式求值结果本身（不是整个 CDP 报文）。"""
            r = await send("Runtime.evaluate",
                           {"expression": expr, "returnByValue": True, "awaitPromise": True})
            res = (r or {}).get("result", {}) or {}
            if res.get("exceptionDetails"):
                raise RuntimeError(f"JS 异常: {str(res['exceptionDetails'])[:160]}")
            return (res.get("result", {}) or {}).get("value")

        await send("Runtime.enable", await_resp=False)
        await send("Page.enable", await_resp=False)
        await send("Security.setIgnoreCertificateErrors", {"ignore": True}, await_resp=False)
        await send("Page.navigate", {"url": home_url}, await_resp=False)

        success_regex = spec.get("success_regex")
        ready_js = spec.get("ready_js") or PORTAL_READY_JS
        deadline = time.time() + 45
        last_url = ""
        last_text = ""
        neg_hits = 0
        pos_hits = 0
        while time.time() < deadline:
            try:
                last_url = str(await eval_js("location.href") or "")
                last_text = str(await eval_js(
                    "(document.body?document.body.innerText:'').slice(0,1500)") or "")
                ready = bool(await eval_js(ready_js))
            except Exception as e:
                logger.warning(f"[PORTAL] eFlow 导航验证轮询出错: {e}")
                await asyncio.sleep(1.0)
                continue

            # 明确失败信号：整页会话错误文案 / 又被打回登录页
            back_to_login = ("/api/oauth2" in last_url) or ("/login" in last_url.lower())
            if _SESSION_ERR_RE.search(last_text) or back_to_login:
                # 连续两次命中才判定（页面重定向过程中会瞬时经过登录页）
                neg_hits += 1
                if neg_hits >= 2:
                    if back_to_login:
                        return False, f"会话未被接受，页面又回到登录页（{last_url}）"
                    snippet = " ".join(last_text.strip().split())[:90]
                    return False, f"页面已打开但会话被拒（{snippet}）: {last_url}"
            else:
                neg_hits = 0
                # 正证据：正文渲染出足够内容 + 无会话错误文案 + 无可见密码框。
                # 必须【连续两次】命中才算成功：eFlow 主页会周期性刷新，刷新瞬间
                # 各告警卡片会短暂清空（只剩 "My Favorites / No data."），
                # 单次命中会把这种中间态误判成「已登录」（2026-09-13 实测）。
                if ready and (not success_regex or re.search(success_regex, last_url)
                              or "login" not in last_url.lower()):
                    pos_hits += 1
                    if pos_hits >= 2:
                        return True, (f"已直接鉴权并进入 eFlow 主页 ({last_url})"
                                      "｜首屏已渲染且无会话错误")
                else:
                    pos_hits = 0
            await asyncio.sleep(1.0)

        snippet = " ".join(last_text.strip().split())[:90]
        return False, f"等待 eFlow 主页就绪超时（当前 URL: {last_url}｜文案: {snippet}）"


# ============ RAIS 直接鉴权登录（UAC-Lite：AES 加密密码换 SSO token） ============
# 背景：RAIS（https://10.100.20.9:8766/raisprod/uacliteweb/）是 ZTE UAC-Lite 的
# Vue hash 路由 SPA，登录页有三个「填表 + 点按钮」搞不定的点：
#   1) 密码不是明文提交：页面用 AES-256-CBC（key/iv 硬编码在前端 chunk 里）加密后再 POST；
#   2) 有一个 canvas 画出来的图形验证码，提交前只做**前端**比对（服务端 verifyCode 传空）；
#   3) 登录成功后 token 写进 document.cookie（RAIS_PORTALSSOCookie），不是 localStorage，
#      后端无法跨域给访问者浏览器种 cookie。
# 因此与 eFlow 一样走「直接鉴权」：Python 端复刻加密算法拿 token → CDP 把 SSO cookie
# 种进本机 Chrome → 打开主页即已登录。仅对坐在 my_app 服务器本机的浏览器有效。
RAIS_AES_KEY = b"ZXUniPOSRAIS20201234567890ABCDEF"
RAIS_AES_IV = b"ZXUniPOSRAIS2020"

# RAIS 前端把 SSO 状态放在这几个 document.cookie 键里（模块 d1b5 / f1ed），
# 用户名与 token 各有一个 RAIS_* 与一个 RAIS_ZTEDPG* 别名，两个都要写。
RAIS_SSO_COOKIES = (
    ("RAIS_PORTALSSOUser", "user"),
    ("RAIS_ZTEDPGSSOUser", "user"),
    ("RAIS_PORTALSSOCookie", "token"),
    ("RAIS_ZTEDPGSSOCookie", "token"),
)


def _rais_encrypt_password(pwd: str) -> str:
    """复刻 RAIS 前端密码加密，返回提交用的 Base64 密文。

    前端实现（webpack chunk-4125b5a5 模块 7834）：
        AES.encrypt(Utf8.parse(pwd), Utf8.parse(KEY),
                    {iv: Utf8.parse(IV), mode: CBC, padding: Pkcs7})
            .ciphertext.toString()      // hex 字符串
        → Hex.parse(...) → Base64.stringify(...)
    等价于「Base64(裸密文字节)」——注意不是 Base64(hex 字符串)。
    """
    from cryptography.hazmat.primitives import padding as sym_padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    padder = sym_padding.PKCS7(128).padder()
    data = padder.update(pwd.encode("utf-8")) + padder.finalize()
    enc = Cipher(algorithms.AES(RAIS_AES_KEY), modes.CBC(RAIS_AES_IV)).encryptor()
    ct = enc.update(data) + enc.finalize()
    return base64.b64encode(ct).decode("ascii")


def _rais_direct_auth(spec: dict):
    """直接鉴权 RAIS：POST verify4web.serv 换取 SSO token。返回 (account, token)。"""
    import httpx
    host, port = resolve_endpoint(spec)
    user, pwd = _creds(spec["cred_key"])
    base = f"https://{host}:{port}{spec.get('api_base', '/raisprod/uaclite')}"
    body = {
        "account": user,
        "passWord": _rais_encrypt_password(pwd),
        "dypwd": "",
        "loginClientIp": "",
        "originSystemCode": "",
        "loginSystemCode": "",
        "verifyCode": "",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Emp-No": user,
        "X-Auth-Value": "",
        "X-Product-Id": "0",
        "X-Tenant-Id": "0",
        "X-Lang-Id": "zh",
    }
    # trust_env=False：my_app 主机上可能配了 http_proxy，内网直连必须绕过代理
    with httpx.Client(verify=False, timeout=30, trust_env=False) as c:
        r = c.post(base + "/auth/uaccommauth/auth/comm/verify4web.serv",
                   json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
    code = (data.get("code") or {}).get("code")
    bocode = (data.get("bo") or {}).get("code")
    if code != "0000" or bocode != "0000":
        msg = ((data.get("code") or {}).get("msg")
               or (data.get("bo") or {}).get("msg") or str(data)[:200])
        raise RuntimeError(f"RAIS 鉴权失败: {msg}")
    token = ((data.get("other") or {}).get("token") or "").strip()
    if not token:
        raise RuntimeError(f"RAIS 鉴权未返回 token: {str(data)[:200]}")
    return user, token


def build_client_login_plan(system_key: str) -> dict:
    """构造供受管 Chrome 扩展执行的、一次性的本机登录计划。

    这个函数刻意不返回门户账号或密码。eFlow / RAIS / UME 系的密码学登录仍只在
    my_app 服务端完成；扩展只拿到必须写入其**本机 Chrome**的短期会话材料。
    调用方必须以短时、单次消费的票据保护返回值，见 routers/portals.py。
    """
    spec = PORTALS.get(system_key)
    if spec is None or not spec.get("direct"):
        raise ValueError(f"门户 {system_key} 不支持客户端会话登录")

    host, port = resolve_endpoint(spec)
    origin = f"https://{host}:{port}"

    if system_key == "eflow":
        cookie_str, forgery_token = _eflow_direct_auth(spec)
        cookies = [
            {
                "name": item["name"],
                "value": item["value"],
                "httpOnly": True,
            }
            for item in _split_cookies(cookie_str)
        ]
        if not cookies:
            raise RuntimeError("eFlow 鉴权未返回会话 cookie")
        # eFlow 前端会把这个值当 forgery 请求头使用；格式必须是 JSON 字符串。
        return {
            "system": system_key,
            "origin": origin,
            "target_url": origin + spec["redirect"],
            "cookies": cookies,
            "eflow_csrf_token": forgery_token,
        }

    if system_key != "rais":
        # 通用分支：标准 ZTE OAuth2 RSA 登录的直连门户（如 battery_ume）。
        # 走 auth_manager 的 _do_login，与「服务器模式」和「测试连接」同一套实现，
        # 拿到会话 cookie + forgery_token 后交给扩展写进访问者本机 Chrome。
        cookie_str, forgery_token = _oauth2_direct_auth(spec)
        cookies = [
            {"name": item["name"], "value": item["value"], "httpOnly": True}
            for item in _split_cookies(cookie_str)
        ]
        if not cookies:
            raise RuntimeError(f"{system_key} 鉴权未返回会话 cookie")
        # 落地页优先取 login_uri（登录入口，已登录时会自行跳转），否则取 redirect。
        target = spec.get("login_uri") or spec["redirect"]
        return {
            "system": system_key,
            "origin": origin,
            "target_url": origin + target,
            "cookies": cookies,
            "eflow_csrf_token": forgery_token,
        }

    account, token = _rais_direct_auth(spec)
    return {
        "system": system_key,
        "origin": origin,
        "target_url": origin + spec["redirect"],
        "cookies": [
            {
                "name": name,
                "value": account if kind == "user" else token,
                # RAIS 的前端路由守卫会读取这些 Cookie，不能标成 HttpOnly。
                "httpOnly": False,
            }
            for name, kind in RAIS_SSO_COOKIES
        ],
    }


async def _cdp_rais_seed_and_open(cdp_port: int, host: str, sport: int, account: str,
                                  token: str, spec: dict, job_id: str):
    """单一 CDP 连接内完成 RAIS 的「种 SSO cookie + 打开已登录主页」。

    ⚠️ 两个实测坑（2026-09-13）：
      1) 必须等 Chrome 的启动页文档加载完（readyState=complete）再动 URL。若在加载中
         就 Page.navigate 到 #/homepage，会得到一个 readyState=complete 但 **JS 从未
         执行**的空白文档（#app 为空，body 无文本），且之后不会自愈 —— 表现就是
         「登录成功但页面全白」。
      2) 只改 hash 属于同文档导航，容易踩上面的时序问题；这里先 about:blank 断一次，
         再整页加载主页，保证「全新文档 + 已带 cookie」。
    返回 (ok, message)。
    """
    import json as _json
    import urllib.request
    import websockets

    base = f"http://127.0.0.1:{cdp_port}"
    with urllib.request.urlopen(f"{base}/json", timeout=5) as r:
        targets = _json.loads(r.read().decode("utf-8"))
    target = None
    for t in targets:
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            target = t
            break
    if target is None and targets:
        target = targets[0]
    if not target or not target.get("webSocketDebuggerUrl"):
        return False, "未找到可用的 CDP page target"

    ws_url = target["webSocketDebuggerUrl"]
    msg_id = [0]
    home_url = f"https://{host}:{sport}{spec.get('redirect', '/raisprod/uacliteweb/#/homepage')}"
    ready_js = spec.get("ready_js") or (
        "(() => { const a = document.querySelector('#app');"
        " return !!(a && a.innerText && a.innerText.trim().length > 100); })()")
    last_url = ""

    async with websockets.connect(ws_url, max_size=None) as ws:
        async def send(method, params=None, await_resp=True):
            msg_id[0] += 1
            mid = msg_id[0]
            payload = {"id": mid, "method": method}
            if params is not None:
                payload["params"] = params
            await ws.send(_json.dumps(payload))
            if not await_resp:
                return None
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                data = _json.loads(raw)
                if data.get("id") == mid:
                    return data

        async def eval_js(expr):
            r = await send("Runtime.evaluate",
                           {"expression": expr, "returnByValue": True, "awaitPromise": True})
            return ((r or {}).get("result", {}).get("result", {}) or {}).get("value")

        await send("Runtime.enable", await_resp=False)
        await send("Page.enable", await_resp=False)
        await send("Network.enable", await_resp=False)
        await send("Security.enable", await_resp=False)
        await send("Security.setIgnoreCertificateErrors", {"ignore": True}, await_resp=False)

        # 1) 等启动页文档加载完（关键，见上面坑 1）
        for _ in range(40):
            try:
                if (await eval_js("document.readyState")) == "complete":
                    break
            except Exception:
                pass
            await asyncio.sleep(0.5)

        # 2) 种 SSO cookie（前端用 document.cookie 读写，故 httpOnly=False）
        set_count = 0
        for name, kind in RAIS_SSO_COOKIES:
            r = await send("Network.setCookie", {
                "name": name,
                "value": account if kind == "user" else token,
                "domain": host,
                "path": "/",
                "httpOnly": False,
                "secure": True,
            })
            if r.get("result", {}).get("success") is not False:
                set_count += 1
        _job_update(job_id, log=[f"已种入 {set_count} 个 SSO cookie"])

        # 3) 硬导航到主页（最多两次），等首屏真正渲染出内容
        for attempt in (1, 2):
            await send("Page.navigate", {"url": "about:blank"}, await_resp=False)
            await asyncio.sleep(0.6)
            await send("Page.navigate", {"url": home_url}, await_resp=False)
            deadline = time.time() + 40
            while time.time() < deadline:
                try:
                    last_url = await eval_js("location.href") or ""
                except Exception:
                    last_url = ""
                if last_url and "login" not in last_url.lower():
                    try:
                        if await eval_js(ready_js):
                            return True, f"已直接鉴权并进入 RAIS 主页 ({last_url})｜首屏已渲染"
                    except Exception:
                        pass
                await asyncio.sleep(1.0)
            _job_update(job_id, log=[f"第 {attempt} 次打开主页未渲染完成（{last_url}），重试"])
            await asyncio.sleep(1.0)
    return False, f"已种入会话但主页未渲染完成（当前 URL: {last_url}）"


def launch_and_login_rais_direct(system_key: str, browser: str | None = None,
                                 job_id: str | None = None) -> dict:
    """RAIS 专用：直接鉴权拿 token -> CDP 种 SSO cookie -> 打开已登录主页。

    不填表、不点登录按钮、不碰图形验证码，完全绕开登录页 DOM 与前端加密。
    """
    if not job_id:
        job_id = uuid.uuid4().hex[:12]
    spec = PORTALS[system_key]
    host, port = resolve_endpoint(spec)
    _job_update(job_id, system=system_key, state="launching",
               message="正在直接鉴权...", log=[], start=time.time())

    try:
        _close_live(system_key)
    except Exception:
        pass

    proc = None
    profile_dir = None
    try:
        _job_update(job_id, log=[f"直接鉴权 RAIS {host}:{port} ..."])
        account, token = _rais_direct_auth(spec)
        _job_update(job_id, log=[f"鉴权成功（账号 {account}），已获取 SSO token"])

        import subprocess
        import shutil
        import asyncio
        exe = get_default_browser_exe() if browser in (None, "default") else browser
        PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
        for stale in [PROFILE_ROOT / system_key] + list(PROFILE_ROOT.glob(f"_tmp_{system_key}_*")):
            try:
                if stale.exists():
                    shutil.rmtree(stale, ignore_errors=True)
            except Exception:
                pass
        profile_dir = str(PROFILE_ROOT / f"_tmp_{system_key}_{uuid.uuid4().hex[:10]}")
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        # 先开登录入口（hash 路由的 /login 在白名单里，不会被弹走），
        # 种完 cookie 后再用 CDP 切到 #/homepage，触发路由守卫放行。
        login_url = build_login_url(spec)
        _job_update(job_id, log=["启动浏览器（直接鉴权模式）"])
        proc = subprocess.Popen(
            [exe,
             f"--user-data-dir={profile_dir}",
             "--remote-debugging-port=0",
             "--start-maximized",
             "--no-first-run",
             "--no-default-browser-check",
             login_url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        devtools_file = os.path.join(profile_dir, "DevToolsActivePort")
        dport = None
        for _ in range(50):
            if os.path.exists(devtools_file):
                try:
                    with open(devtools_file, "r", encoding="utf-8") as f:
                        dport = int(f.readline().strip())
                    break
                except Exception:
                    pass
            time.sleep(0.1)
        if not dport:
            raise RuntimeError("无法获取 Chrome 远程调试端口（浏览器可能启动失败）")

        _job_update(job_id, log=["向浏览器写入 RAIS SSO cookie 并打开主页 ..."])
        ok, sinfo = asyncio.run(
            _cdp_rais_seed_and_open(dport, host, port, account, token, spec, job_id))

        _maximize_window(exe)
        _keep_alive(system_key, proc, profile_dir)
        _job_update(job_id, state="success" if ok else "failed", message=sinfo, end=time.time())
        return _job_result(job_id, ok, sinfo)
    except Exception as e:
        logger.warning(f"[PORTAL] RAIS 直接鉴权登录失败 {system_key}: {e}", exc_info=True)
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        if profile_dir and os.path.exists(profile_dir):
            try:
                import shutil
                shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception:
                pass
        _job_update(job_id, state="failed", message=f"异常: {type(e).__name__}: {e}", end=time.time())
        return _job_result(job_id, False, f"异常: {type(e).__name__}: {e}")


def _keep_alive(system_key, proc, profile_dir=None):
    """登记常驻浏览器会话，并起守护线程监听进程退出。

    ⚠️ 为什么必须监听：LIVE 原来只进不出，窗口被关掉后 LIVE 里仍有记录 →
    前端卡片一直显示 Live、点「关闭窗口」返回 closed=false（2026-09-12 实测）。
    退出时同步清理临时 profile，避免 data/portal_profiles 里残留累积。
    """
    with LIVE_LOCK:
        LIVE[system_key] = {
            "proc": proc, "started_at": time.time(), "profile_dir": profile_dir,
        }

    def _watch():
        try:
            code = proc.wait()
        except Exception:
            code = None
        with LIVE_LOCK:
            cur = LIVE.get(system_key)
            if cur is not None and cur.get("proc") is proc:
                LIVE.pop(system_key, None)
        logger.info(f"[PORTAL] {system_key} 浏览器窗口已退出 (returncode={code})，已移出常驻列表")
        if profile_dir and os.path.exists(profile_dir):
            try:
                import shutil
                shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception:
                pass

    threading.Thread(target=_watch, daemon=True).start()


def _creds(cred_key):
    from backend.services.credential_store import get_credential, _GROUP_INDEX
    g = _GROUP_INDEX.get(cred_key, {})
    du = g.get("default_user", "")
    ds = g.get("default_secret", "")
    return get_credential(cred_key, du, ds)


def _job_result(job_id, ok, message):
    with JOBS_LOCK:
        j = JOBS.get(job_id, {})
    return {"job_id": job_id, "ok": ok, "message": message,
            "state": j.get("state"), "system": j.get("system")}


def close_session(system_key: str) -> bool:
    """关闭某系统的常驻浏览器会话。"""
    with LIVE_LOCK:
        exists = system_key in LIVE
    if not exists:
        return False
    _close_live(system_key)
    return True


_LOCAL_ADDRS: set | None = None


def local_addresses() -> set:
    """本机所有地址（含回环），用于判断「访问者是否就坐在 my_app 服务器上」。"""
    global _LOCAL_ADDRS
    if _LOCAL_ADDRS is not None:
        return _LOCAL_ADDRS
    out = {"127.0.0.1", "::1", "localhost"}
    try:
        import socket
        for info in socket.getaddrinfo(socket.gethostname(), None):
            out.add(info[4][0])
    except Exception as e:  # pragma: no cover
        logger.warning(f"[PORTAL] 解析本机地址失败: {e}")
    _LOCAL_ADDRS = out
    return out


def client_is_local(ip: str | None) -> bool:
    """访问者 IP 是否就是本机（服务器自己）。

    用途：直连门户（eFlow / RAIS）只能在服务器桌面用「直接鉴权」登录，
    若访问者浏览器本来就在服务器上，那个窗口正好开在他自己桌面上 → 可以直接走服务器登录；
    远程访问者则只能打开上游登录页手动登录（见前端 handleLogin）。
    """
    if not ip:
        return False
    return ip.strip() in local_addresses()


def list_portals() -> list:
    """列出全部门户及其当前常驻状态（供前端展示）。"""
    out = []
    for key, spec in PORTALS.items():
        host, port = resolve_endpoint(spec)
        with LIVE_LOCK:
            ent = LIVE.get(key)
            # 双重保险：即使 watcher 线程还没跑到，也不把已退出的进程报成 live
            live = bool(ent) and (ent.get("proc") is None or ent["proc"].poll() is None)
        out.append({
            "key": key,
            "name": spec["name"],
            "name_en": spec["name_en"],
            "cred_key": spec["cred_key"],
            "host": host,
            "port": port,
            "kind": spec["kind"],
            "live": live,
            # 客户端本机登录（nginx 反代）：/portal/<key>/ → 门户根
            "proxy_prefix": PROXY_PREFIXES.get(key),
            "login_uri": _login_uri(spec),
            # direct=True：客户端模式直连上游（不经反代、无自动填表），
            # 前端据此在 client 模式下放行「打开登录页」按钮。
            "direct": bool(spec.get("direct")),
        })
    return out


# ===== 客户端本机登录（nginx 反代 + 页面内注入自动填表）=====
# nginx 把门户反代到同源的 /portal/<key>/ 下（见 nginx.conf 的 /portal/eflow/ 段），
# 门户页面与 my_app 同源 → 可在登录页里注入本脚本完成自动填表，
# 于是「在哪台电脑点登录，就在哪台电脑的浏览器里登录」，Cookie 落在访问者本机。
# 只有已在 nginx 配好反代的门户才出现在该表里，否则前端降级为服务器登录。
# 值是 proxy_base 模板："" = 与 my_app 同源（80 口）；"//{HOST}:<port>" = 独立端口
# （前端把 {HOST} 替换为 location.hostname）。
#
# ⚠️ 为什么 eFlow 走 80 口原生路径而其他门户分端口（实测结论，见 TMP/cdp_verify_portal_proxy_login.py）：
#    1) 门户前端按页面 URL 的「上下文」拼接 localStorage 键名（CSRF token 存 csrftoken），
#       放 /portal/eflow/ 前缀下会导致登录后主页取不到 token → 403 cross-site。
#       所以任何门户都不能剥前缀，必须按原生路径反代。
#    2) ZTE/iPRAN/MW/eFlow 的会话 Cookie 名完全相同（Z-AUTH-CODE-28001 等），
#       且 Cookie 不区分端口 → 同浏览器两个门户共用命名空间会互相顶掉会话。
#       因此除 eFlow 外每个门户独占一个端口（portal_ports.conf）。
PROXY_PREFIXES = {
    "eflow":     "",
    "zte_ume":   "//{HOST}:8081",
    "ccn_ume":   "//{HOST}:8082",
    "ipran_ume": "//{HOST}:8083",
    "mw_ume":    "//{HOST}:8084",
    "fw_kpi":    "//{HOST}:8085",
    "vmax_cxo":  "//{HOST}:8086",
    # 8087 被 ShadowBot 占用，iMonitor 用 8088（见 nginx/portal_ume_in_8088.conf）
    "ume_in":    "//{HOST}:8088",
}


def _login_uri(spec: dict) -> str:
    """登录入口的 path+query（不含 scheme/host/port），供反代前缀拼接。"""
    url = build_login_url(spec)
    idx = url.find("/", url.find("://") + 3)
    return url[idx:] if idx > 0 else "/"


def build_inject_js(system_key: str, user: str, pwd: str) -> str:
    """生成注入到门户登录页的自动填表脚本（凭据随本次请求下发，不落盘）。

    要点：
      - 页面 JS 端做 RSA/SM 加密，脚本只负责「填值 + 点真实登录按钮」；
      - 轮询等待登录表单渲染（Angular bootstrap 可能 >5s）；
      - 填完回读校验，值没进去则退回 execCommand('insertText') 模拟真实键入；
      - 只在找到用户名输入框时动作，非登录页直接退出（无副作用）。
    """
    import json as _json
    u = _json.dumps(user)
    p = _json.dumps(pwd)
    sysname = _json.dumps(system_key)
    return f"""(function () {{
  var SYS = {sysname}, USER = {u}, PWD = {p};
  var UCSS = ["#inputUserName", "input[name='username']", "#username",
    "input[id='username']", "input[name='user']", "input[name='j_username']",
    "#userNameInput", "input[name='userName']", "input[type='text']"];
  var PCSS = ["#inputCiphercode", "input[name='cipher_code']", "#password",
    "input[name='password']", "input[id='password']", "input[name='p']",
    "#passwordInput", "input[type='password']"];
  function vis(el) {{
    if (!el || el.disabled) return false;
    if ((el.type || '').toLowerCase() === 'hidden') return false;
    return (el.offsetWidth > 0 || el.offsetHeight > 0 || el.offsetParent !== null);
  }}
  function find(sels) {{
    for (var i = 0; i < sels.length; i++) {{
      try {{ var el = document.querySelector(sels[i]); if (el && vis(el)) return el; }} catch (e) {{}}
    }}
    return null;
  }}
  function setVal(el, v) {{
    try {{
      var proto = (el.tagName === 'TEXTAREA') ? window.HTMLTextAreaElement.prototype
                                             : window.HTMLInputElement.prototype;
      var d = Object.getOwnPropertyDescriptor(proto, 'value');
      if (d && d.set) {{ d.set.call(el, v); }} else {{ el.value = v; }}
      ['input', 'change', 'keyup', 'blur'].forEach(function (t) {{
        try {{ el.dispatchEvent(new Event(t, {{ bubbles: true }})); }} catch (e) {{}}
      }});
    }} catch (e) {{}}
  }}
  function typeInto(el, v) {{
    try {{
      el.focus();
      try {{ el.setSelectionRange(0, (el.value || '').length); }} catch (e) {{}}
      document.execCommand('insertText', false, v);
    }} catch (e) {{ try {{ el.value = v; }} catch (e2) {{}} }}
  }}
  function clickLogin() {{
    var sels = ["#loginBut", "#loginSubmit", "input[type='submit']", "button[type='submit']",
      ".login-btn", ".btn-login", ".login-button"];
    var b = find(sels);
    if (!b) {{
      var all = document.querySelectorAll("button,input[type=submit],a.btn");
      for (var i = 0; i < all.length; i++) {{
        var t = (all[i].textContent || all[i].value || '').trim().toLowerCase();
        if (/登录|login|sign\\s*in|submit/.test(t)) {{ b = all[i]; break; }}
      }}
    }}
    if (b) {{ try {{ b.click(); return (b.id || b.textContent || 'btn'); }} catch (e) {{}} }}
    return null;
  }}
  function attempt() {{
    var uEl = find(UCSS);
    if (!uEl) return false;
    // 验证码模式：登录页存在可见的验证码输入框时只预填账号密码，不自动提交；
    // 用户手动输入验证码后，脚本下一轮轮询检测到验证码非空会自动点登录。
    var cap = null;
    try {{
      var cands = ["#captchaInput", "input[name='captchaInput']", "input[placeholder='Code']", "input[name='captcha']"];
      for (var ci = 0; ci < cands.length; ci++) {{
        var ce = document.querySelector(cands[ci]);
        if (ce && (ce.offsetWidth > 0 || ce.offsetHeight > 0 || ce.offsetParent !== null)
            && (ce.type || '').toLowerCase() !== 'hidden') {{ cap = ce; break; }}
      }}
    }} catch (e) {{}}
    if (uEl.value !== USER) {{
      setVal(uEl, USER);
      if (uEl.value !== USER) typeInto(uEl, USER);
    }}
    var pEl = find(PCSS);
    if (pEl && pEl.value !== PWD) {{
      setVal(pEl, PWD);
      if (pEl.value !== PWD) typeInto(pEl, PWD);
    }}
    if (uEl.value !== USER) return false;
    if (cap && (cap.value || '') === '') {{
      console.log('[MYAPP-AUTOLOGIN] ' + SYS + ' captcha mode: prefilled, waiting for user');
      return false;   // 继续轮询等用户输验证码
    }}
    var r = clickLogin();
    console.log('[MYAPP-AUTOLOGIN] ' + SYS + ' filled, submit=' + r);
    // 通知宿主页面：登录已提交。宿主（myapp 的 iframe 容器，如 iMonitor 大屏页）
    // 据此在门户跳转完成后把 iframe 重新指回目标深链 —— 门户登录成功只会落到
    // redirect_uri 的根路径，带 hash 的路由（#/screen/screen-view?screen_id=1）会丢。
    try {{
      if (window.parent && window.parent !== window) {{
        window.parent.postMessage(
          {{ __type: 'myapp-portal-autologin', system: SYS, submit: r }}, '*');
      }}
    }} catch (e) {{}}
    return true;
  }}
  var tries = 0;
  var timer = setInterval(function () {{
    tries++;
    var done = false;
    try {{ done = attempt(); }} catch (e) {{ console.log('[MYAPP-AUTOLOGIN] err ' + e); }}
    if (done || tries > 50) clearInterval(timer);
  }}, 500);
}})();"""

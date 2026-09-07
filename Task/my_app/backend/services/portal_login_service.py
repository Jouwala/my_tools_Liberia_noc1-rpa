"""
portal_login_service.py - 一键通过默认浏览器登录内部门户
================================================================

背景：各系统（ZTE UME / CCN UME / iPRAN UME / eFlow / FW(UMC) / VMAX CXO）的
用户名密码已集中在「系统设置 → 凭据」(backend/services/credential_store.py) 维护。
本模块让用户在 my_app 里点一下，就用**本机默认浏览器**打开对应门户并自动登录，
省去每次手工输入账号密码。

实现要点：
- 复用 credential_store.get_credential() 读取当前生效凭据（环境变量 > 数据库 > 代码默认）。
- 启动 Playwright（优先本机 **Google Chrome**，无 Chrome 时回退到系统默认浏览器，
  exe 都找不到则回退到 playwright 自带 chromium），以 headed 模式 + 独立 user-data-dir
  打开，登录后**保持窗口打开**供用户继续使用。
- 所有门户的登录加密都在页面 JS 里完成（RSA / DES+SM3 / SM4 等），因此统一采用
  「填充用户名/密码 → 点击真实登录按钮」的方式，由页面自身完成加密提交，无需在
  Python 端复刻各套加密算法。
- 每个系统维护一个常驻浏览器会话（LIVE），用户可手动关闭或经 API 关闭。

> 注意：本模块在后端 Web 进程（uvicorn）里起一个后台线程驱动浏览器。默认浏览器
  必须运行在与用户相同的 Windows 桌面会话（start.bat 以当前用户拉起，满足），
  否则 headed 浏览器可能无法显示。
"""
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
        "  const ucss = ['#inputUserName', \"input[name='username']\", '#username', \"input[id='username']\", \"input[name='user']\", \"input[name='j_username']\", \"input[type='text']\"];\n"
        "  const pcss = ['#inputCiphercode', \"input[name='cipher_code']\", '#password', \"input[name='password']\", \"input[id='password']\", \"input[name='p']\", \"input[type='password']\"];\n"
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
    "    \"input[id='username']\",\"input[name='user']\",\"input[name='j_username']\",'input[type=text]'];"
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


def _keep_alive(system_key, proc, profile_dir=None):
    with LIVE_LOCK:
        LIVE[system_key] = {
            "proc": proc, "started_at": time.time(), "profile_dir": profile_dir,
        }


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


def list_portals() -> list:
    """列出全部门户及其当前常驻状态（供前端展示）。"""
    out = []
    for key, spec in PORTALS.items():
        host, port = resolve_endpoint(spec)
        with LIVE_LOCK:
            live = key in LIVE
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

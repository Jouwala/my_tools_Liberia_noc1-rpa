"""
Playwright 浏览器自动化 - 公共稳定模块

提供四个稳定模式，被 whatsapp_service.py / site_outage_service.py 共用：
1. wait_for_visible        - 显式等待元素可见（替代 time.sleep 硬等待）
2. retry_transient         - 分级重试（区分可重试 / 不可重试异常）
3. run_with_recovery       - 全流程重试（冷启动 → 失败恢复）
4. save_debug_snapshot     - 失败现场截屏 + HTML dump，便于复盘

设计目标：把两个脚本 10% 的偶发失败率降到 <1%。
"""
import os
import time
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

logger = logging.getLogger("playwright_utils")


# ==========================================================
# 异常分级
# ==========================================================
class TransientError(Exception):
    """瞬时错误 - 网络/页面抖动/预览框慢，可安全重试。"""


class FatalError(Exception):
    """致命错误 - 选择器失效、登录凭据错误，重试无意义，应直接抛出。"""


# ==========================================================
# 模式 1：显式等待元素可见（取代 time.sleep）
# ==========================================================
def wait_for_visible(page, selectors: Iterable[str], timeout: int = 10000,
                     poll_interval: float = 0.3):
    """在多个候选 selector 中等待任一可见。

    Args:
        page: Playwright Page / Frame
        selectors: 候选 selector 列表
        timeout: 总超时（毫秒）
        poll_interval: 轮询间隔（秒）

    Returns:
        第一个可见的 Locator

    Raises:
        TimeoutError: 超时仍未出现可见元素
    """
    selectors = [s for s in selectors if s]
    deadline = time.time() + timeout / 1000
    last_err = None

    while time.time() < deadline:
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        if loc.first.is_visible(timeout=500):
                            return loc.first
                    except Exception:
                        # 不可见但存在于 DOM，仍可能是页面在加载，继续等
                        last_err = f"{sel} exists but not visible"
                        continue
            except Exception as e:
                last_err = f"{sel}: {e}"
                continue
        time.sleep(poll_interval)

    raise TimeoutError(
        f"等待元素超时 ({timeout}ms): {selectors} last_err={last_err}"
    )


def wait_for_any(page, selectors: Iterable[str], timeout: int = 10000) -> bool:
    """宽松判断：selectors 中任一在 DOM 中存在即返回 True（用于登录态判断等）。"""
    selectors = [s for s in selectors if s]
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for sel in selectors:
            try:
                if page.locator(sel).count() > 0:
                    return True
            except Exception:
                continue
        time.sleep(0.3)
    return False


# ==========================================================
# 模式 2：分级重试（仅对 TransientError 重试）
# ==========================================================
def retry_transient(func: Callable, max_attempts: int = 3,
                    backoff_base: float = 2.0, label: str = ""):
    """对函数执行分级重试。

    - TransientError: 指数退避后重试
    - FatalError / 其他: 立即抛出，不重试

    Args:
        func: 无参可调用对象
        max_attempts: 最大尝试次数
        backoff_base: 退避基数（秒），第 i 次重试等待 backoff_base ** i
        label: 日志标签
    """
    last_err = None
    for i in range(max_attempts):
        try:
            return func()
        except TransientError as e:
            last_err = e
            if i < max_attempts - 1:
                wait = backoff_base ** i
                logger.warning(f"[{label}] 瞬时错误重试 {i + 1}/{max_attempts} 等待 {wait:.1f}s: {e}")
                time.sleep(wait)
        except FatalError:
            raise
        except Exception as e:
            # 未知异常默认视为瞬时（兼容旧代码），但打印 warning 提示
            last_err = e
            logger.warning(f"[{label}] 未分类异常当作瞬时错误重试 {i + 1}/{max_attempts}: {e}")
            if i < max_attempts - 1:
                time.sleep(backoff_base ** i)
    raise last_err


# ==========================================================
# 模式 3：全流程恢复（顶层重试）
# ==========================================================
def run_with_recovery(task_fn: Callable, max_total_retry: int = 2,
                      label: str = "task",
                      on_retry: Optional[Callable[[int, Exception], None]] = None):
    """整个任务最多重试 N 次，每次均从冷启动开始。

    Args:
        task_fn: 无参可调用对象，应返回 dict 或抛异常
        max_total_retry: 总尝试次数（含首次）
        label: 任务名称，用于日志
        on_retry: 重试前回调，可在此清理 session/进程等
    """
    last_err = None
    for i in range(max_total_retry):
        try:
            return task_fn()
        except TransientError as e:
            last_err = e
            logger.warning(f"[{label}] 全流程重试 {i + 1}/{max_total_retry}: {e}")
        except FatalError as e:
            # 致命错误不重试
            logger.error(f"[{label}] 致命错误，放弃重试: {e}")
            raise
        except Exception as e:
            last_err = e
            logger.warning(f"[{label}] 未分类异常全流程重试 {i + 1}/{max_total_retry}: {e}")

        if i < max_total_retry - 1:
            if on_retry:
                try:
                    on_retry(i + 1, last_err)
                except Exception as cb_err:
                    logger.error(f"[{label}] on_retry 回调异常: {cb_err}")
            time.sleep(3)
    raise last_err


# ==========================================================
# 模式 4：失败现场截屏 + HTML dump
# ==========================================================
def save_debug_snapshot(page, debug_dir: str, step: str, ts: Optional[str] = None):
    """异常时保存现场截图 + HTML，便于事后复盘 selector 是否变更。"""
    ts = ts or datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    Path(debug_dir).mkdir(parents=True, exist_ok=True)
    safe_step = "".join(c if c.isalnum() else "_" for c in step)
    png_path = os.path.join(debug_dir, f"fail_{safe_step}_{ts}.png")
    html_path = os.path.join(debug_dir, f"fail_{safe_step}_{ts}.html")

    try:
        page.screenshot(path=png_path, full_page=True)
        logger.info(f"[debug] 截图保存: {png_path}")
    except Exception as e:
        logger.warning(f"[debug] 截图失败: {e}")

    try:
        html = page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"[debug] HTML 保存: {html_path}")
    except Exception as e:
        logger.warning(f"[debug] HTML dump 失败: {e}")


# ==========================================================
# 辅助：loading 消失就绪信号（用于 SPA 数据加载完成判断）
# ==========================================================
def wait_for_loading_gone(frame, timeout: int = 15000):
    """等待 loading/spinner 元素消失，作为数据就绪信号。

    若原本就没有 loading 元素，立即返回。
    """
    loading_selectors = (
        ".ant-spin-spinning, "
        "[class*='loading'], "
        "[class*='spinner'], "
        "[class*='skeleton']"
    )
    try:
        loading = frame.locator(loading_selectors)
        if loading.count() > 0:
            loading.first.wait_for(state="hidden", timeout=timeout)
    except Exception:
        pass


# ==========================================================
# 辅助：截图非空白校验（可选依赖 Pillow）
# ==========================================================
def is_screenshot_blank(image_path: str, variance_threshold: float = 100.0) -> bool:
    """通过像素方差判断截图是否为空白页（容错降级）。

    Returns:
        True 表示判定为空白页
    """
    try:
        from PIL import Image
        import statistics
    except ImportError:
        # 无 Pillow 退化为只检查 size > 0
        try:
            return os.path.getsize(image_path) < 1024
        except Exception:
            return True

    try:
        img = Image.open(image_path).convert("L")
        pixels = list(img.resize((100, 100)).getdata())
        var = statistics.pvariance(pixels)
        return var < variance_threshold
    except Exception:
        return False


# ==========================================================
# 辅助：清理持久化 session 目录（二维码二次失败兜底）
# ==========================================================
def safe_clear_session(session_dir: str, backup_dir: Optional[str] = None):
    """删除持久化 session 目录以便重新扫码登录。

    Args:
        session_dir: 持久化 user_data_dir
        backup_dir: 若提供，先把目录重命名备份而非直接删除（便于排查）
    """
    if not os.path.exists(session_dir):
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if backup_dir:
        backup_path = os.path.join(backup_dir, f"session_bak_{ts}")
        try:
            Path(backup_dir).mkdir(parents=True, exist_ok=True)
            shutil.move(session_dir, backup_path)
            logger.warning(f"[session] 已备份旧 session 到: {backup_path}")
            return
        except Exception as e:
            logger.error(f"[session] 备份失败，改为直接删除: {e}")

    try:
        shutil.rmtree(session_dir, ignore_errors=False)
        logger.warning(f"[session] 已清理 session 目录: {session_dir}")
    except Exception as e:
        logger.error(f"[session] 清理失败: {e}")


# ==========================================================
# 辅助：精准清理 chrome 进程（只杀关联本脚本 user_data_dir 的实例）
# ==========================================================
def kill_chrome_by_profile(profile_keyword: str):
    """只杀命令行中包含指定 user_data_dir 关键字的 chrome 进程。

    Args:
        profile_keyword: USER_DATA_DIR 中的特征字符串（如 'whatsapp_session'）
    """
    import subprocess
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{profile_keyword}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; "
        "Write-Output $_.ProcessId }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
            creationflags=flags,
        )
        killed = [x for x in result.stdout.split() if x.strip()]
        if killed:
            logger.info(f"[chrome] 已精准清理 {len(killed)} 个 chrome 进程: {killed}")
        else:
            logger.info("[chrome] 无残留 chrome 进程需要清理")
    except Exception as e:
        logger.warning(f"[chrome] 进程清理失败: {e}")
    time.sleep(1)


# ==========================================================
# 装饰器：自动在异常时保存现场
# ==========================================================
def with_debug_snapshot(debug_dir: str, step: str):
    """装饰器：函数抛异常时自动保存现场截图 + HTML。"""
    def decorator(func):
        def wrapper(page, *args, **kwargs):
            try:
                return func(page, *args, **kwargs)
            except Exception:
                try:
                    save_debug_snapshot(page, debug_dir, step)
                except Exception:
                    pass
                raise
        return wrapper
    return decorator

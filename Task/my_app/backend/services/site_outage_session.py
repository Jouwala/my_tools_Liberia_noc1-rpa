"""Site Outage 任务的会话持久化。

## 为什么需要这个模块（2026-10-04）

`site_outage_screenshot` 每小时整点跑一次（DB 覆盖 `0 */1 * * *`，截图需要
每小时更新）。修复前它**每轮都重新登录** eFlow：每轮 17~25s，且 shared
`auth_cache` 里 admin 的 token 明明还有 14.6 小时有效期。

**根因与 token 过期无关**：eFlow 签发的 5 个会话 cookie
（`JSESSIONID` / `Z-AUTH-CODE-28001` / `forgerydefense-28001` /
`x-dexmesh-user-28001` / `X-Rm-Data-Version-zenap`）**全部是 session cookie**
（`expires=-1`），Chrome 在**浏览器关闭时一律丢弃**。而任务每轮结束都执行
`browser.close()`，于是持久化 profile 里的会话每轮都被清空 → 下一轮必然
回到登录页。

实测证据：`browser_session/Default/Network/Cookies` 的 cookie 表**为空**，
且该文件长期不被写入。

**因此"给 token 加 keepalive 心跳"修不了它** —— 心跳只会多一步
"发现已失效再登录"，省不下任何一次登录。

Chrome 丢弃 session cookie 是**浏览器行为**，改 profile 没用，必须由我们自己
把会话序列化到磁盘。Playwright 的 `storage_state()`（含 cookie + localStorage）
正是为此设计的，配合 `add_cookies()` + `add_init_script()` 回灌。

## 用法

    from site_outage_session import (
        STATE_FILE, state_is_fresh, load_state, save_state, clear_state,
        session_still_valid,
    )

⚠ `save_state()` **必须在 `browser.close()` 之前**调用 —— session cookie
一旦随浏览器关闭消失，就再没有机会序列化了。
"""
import json
import logging
import os
import time

logger = logging.getLogger("site_outage_service")

# profile 目录（与 site_outage_service.USER_DATA_DIR 保持一致）。
# 注意：本机另有 D:\01_RPA\Site_outage\，那是 7 月的**陈旧** profile，
# 排查时不要拿它当依据。
_HERE = os.path.dirname(os.path.abspath(__file__))
USER_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(_HERE))),
    "Site_outage", "browser_session",
)

# 会话副本。放在 profile 的**同级**而非内部：profile 在登录态损坏时会被
# 整体重命名清空（见 site_outage_service._on_retry），副本若放里面会一起丢。
STATE_FILE = os.path.abspath(os.path.join(USER_DATA_DIR, "..", "session_state.json"))

# 会话最多复用多久。会话本身寿命由服务端决定，这里只是本地安全阀，
# 避免上游已失效而我们仍反复用坏凭据去撞。
STATE_MAX_AGE_SEC = int(os.environ.get("SITE_OUTAGE_STATE_MAX_AGE", str(20 * 3600)))


def state_is_fresh():
    """判断磁盘上的会话副本是否还在有效期内。"""
    try:
        if not os.path.exists(STATE_FILE):
            return False
        age = time.time() - os.path.getmtime(STATE_FILE)
        if age > STATE_MAX_AGE_SEC:
            logger.info(
                f"[SiteOutage] 会话副本已过期（{age / 3600:.1f}h > "
                f"{STATE_MAX_AGE_SEC / 3600:.1f}h），将重新登录"
            )
            return False
        return True
    except OSError:
        return False


def load_state(context):
    """把上次保存的会话回灌进当前 context。

    只在 launch 之后、开页之前调用一次。
    """
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.warning(f"[SiteOutage] 会话副本解析失败，忽略: {e}")
        return False

    cookies = state.get("cookies") or []
    if not cookies:
        return False

    # 1) 先把 cookie 写回去。注意 storage_state() 里会话 cookie 的
    #    expires 是 -1，add_cookies 接受该值。
    try:
        context.add_cookies(cookies)
    except Exception as e:
        logger.warning(f"[SiteOutage] 回灌 cookie 失败: {e}")
        return False

    # 2) 再把 localStorage 写回去（按 origin 分组）。
    #    storage_state 的 origins[].localStorage 是 [{name,value},...]，
    #    但需要一个已打开该 origin 的页面才能 setItem，因此用
    #    add_init_script 在该 origin 的**下一个**页面加载前注入 ——
    #    这样不依赖"先开一次页面"，也就不会多打一次上游。
    origins = state.get("origins") or []
    for origin in origins:
        items = origin.get("localStorage") or []
        if not items:
            continue
        pairs = json.dumps(
            {it["name"]: it["value"] for it in items if "name" in it}
        )
        script = (
            "(function(){var d=%s;for(var k in d)"
            "{try{localStorage.setItem(k,d[k])}catch(e){}}})()" % pairs
        )
        try:
            context.add_init_script(script)
        except Exception as e:
            logger.warning(
                f"[SiteOutage] 注入 localStorage 失败({origin.get('origin')}): {e}"
            )

    # 3) sessionStorage 不在 storage_state 覆盖范围内，是 _save_state 额外
    #    抓的，一并注入。
    extra_ss = state.get("_sessionStorage") or {}
    if extra_ss:
        script = (
            "(function(){var d=%s;for(var k in d)"
            "{try{sessionStorage.setItem(k,d[k])}catch(e){}}})()"
            % json.dumps(extra_ss)
        )
        try:
            context.add_init_script(script)
        except Exception as e:
            logger.warning(f"[SiteOutage] 注入 sessionStorage 失败: {e}")

    logger.info(
        f"[SiteOutage] 已回灌上次会话（cookies={len(cookies)}, "
        f"origins={len(origins)}），尝试复用，避免重复登录"
    )
    return True


def save_state(context, page=None):
    """把当前会话落盘，供下一次任务复用。

    ⚠ 必须在 browser.close() **之前**调用。
    """
    try:
        state = context.storage_state()
    except Exception as e:
        logger.warning(f"[SiteOutage] storage_state() 失败，本轮会话无法复用: {e}")
        return False

    # storage_state() 只覆盖 cookie 与 localStorage；eFlow 门户还会用
    # sessionStorage 存一部分登录态，故额外抓一次并合并进同一份文件。
    if page is not None:
        try:
            ss = page.evaluate(
                "() => { try { return Object.fromEntries("
                "Object.entries(sessionStorage)); } catch (e) { return {}; } }"
            )
            if ss:
                state["_sessionStorage"] = ss
                logger.info(f"[SiteOutage] 额外捕获 sessionStorage {len(ss)} 项")
        except Exception as e:
            logger.warning(f"[SiteOutage] 读取 sessionStorage 失败（忽略）: {e}")

    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)  # 原子替换，避免半截文件
        logger.info(
            f"[SiteOutage] 已保存会话副本（cookies={len(state.get('cookies') or [])}）"
            f"→ 下次任务可直接复用"
        )
        return True
    except Exception as e:
        logger.warning(f"[SiteOutage] 保存会话副本失败: {e}")
        return False


def clear_state():
    """删除会话副本（登录确证失败时调用，避免反复用坏凭据撞上游）。"""
    try:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
            logger.info("[SiteOutage] 已清除失效的会话副本")
    except OSError as e:
        logger.warning(f"[SiteOutage] 清除会话副本失败: {e}")


def session_still_valid(page, dashboard_url, wait_timeout=120000):
    """探测回灌的会话是否仍然可用（**不触发登录**）。

    做法：直接访问看板页，若没有被重定向到登录页（URL 仍是 default.html
    且不含 authorize），说明会话有效。这是"按需验证"而非定时心跳 ——
    零额外请求，判断永远基于真实响应。

    注意：safe_goto 由调用方注入，避免本模块反向依赖 site_outage_service。
    """
    from _playwright_utils import safe_goto

    try:
        safe_goto(page, dashboard_url, timeout=wait_timeout)
    except Exception as e:
        logger.info(f"[SiteOutage] 会话探测导航失败（按失效处理）: {e}")
        return False

    url = page.url or ""
    if "authorize" in url or "login" in url.lower():
        logger.info(f"[SiteOutage] 会话已失效（被重定向到登录）: {url[:90]}")
        return False
    if "default.html" not in url:
        logger.info(f"[SiteOutage] 会话状态不明（URL 非看板页）: {url[:90]}")
        return False
    logger.info("[SiteOutage] 复用上次会话成功，本轮无需登录")
    return True

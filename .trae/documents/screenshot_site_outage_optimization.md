# screenshot_site_outage.py 速率和稳定性优化计划

## 摘要

对 `d:\01_RPA\Site_outage\screenshot_site_outage.py` 进行速率和稳定性优化，主要消除不必要的硬编码 `time.sleep()` 等待，改用 Playwright 智能等待机制；增加关键操作的重试和验证逻辑；精简冗余导航步骤。

## 当前状态分析

### 速率瓶颈

| 位置 | 问题 | 浪费时间 |
|------|------|----------|
| `login()` L63 | `time.sleep(3)` 固定等待 | 3s |
| `navigate_to_dashboard()` L138-152 | 连续 5 个 sleep（1+5+5+8+3） | 22s |
| `get_dashboard_frame()` L114 | 每轮重试后 `wait_for_timeout(3000)` | 最多 15s |
| `get_dropdown_options()` L210,227 | 点击后 sleep(2) + Escape 后 sleep(0.5) | ~5s |
| `select_and_screenshot()` L288,311,336 | 每次选择后 `time.sleep(5)` | 5s × N选项 |
| `click_fullscreen()` L269 | `time.sleep(2)` | 2s |

**总计固定等待：约 47s + 5s×N（N=选项数）**，实际页面可能 1-2s 就已就绪。

### 稳定性问题

1. **无操作结果验证**：选择下拉选项后不验证是否生效，直接截图
2. **无单选项重试**：某个选项截图失败后直接跳过，不重试
3. **iframe 检测超时过长**：每次 `wait_for(state="attached", timeout=5000)` + `wait_for_load_state(timeout=10000)` + `inner_text(timeout=3000)` = 单个选择器最多 18s
4. **导航冗余**：先 `goto("about:blank")` 再 `goto(DASHBOARD_URL)` 再可能 `reload()`，步骤过多
5. **下拉框关闭不可靠**：仅用 `Escape` 键，某些自定义组件可能不响应
6. **无截图文件验证**：不检查截图文件是否成功写入

##  Proposed Changes

### 文件：`d:\01_RPA\Site_outage\screenshot_site_outage.py`

#### 变更 1：新增智能等待工具函数

在文件顶部（`sanitize_filename` 之后）添加：

```python
def wait_for_network_idle(page_or_frame, timeout=10000):
    """等待网络空闲，超时则继续（不阻塞）"""
    try:
        page_or_frame.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass

def wait_for_data_refresh(frame, trigger_action, timeout=15000):
    """执行触发动作后，等待数据刷新完成。
    优先等待 networkidle，备选等待 loading 消失。
    """
    trigger_action()
    try:
        frame.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    # 备选：等待可能的 loading 遮罩消失
    try:
        loading = frame.locator(".ant-spin-spinning, [class*='loading'], [class*='spinner']")
        if loading.count() > 0:
            loading.first.wait_for(state="hidden", timeout=5000)
    except Exception:
        pass
```

**原因**：替代所有 `time.sleep(5)` 等硬编码等待，根据实际网络/渲染状态决定何时继续。

#### 变更 2：优化 `login()` 函数

- 移除 `time.sleep(3)`，改为 `page.wait_for_load_state("domcontentloaded")` 后直接调用 `zte_login`（`zte_login` 内部已有 `wait_for` 逻辑）

```python
def login(page):
    info("正在打开登录页...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
    # zte_login 内部已有元素等待逻辑，无需额外 sleep
    ok = zte_login(page)
    ...
```

#### 变更 3：优化 `navigate_to_dashboard()` 函数

- 移除 `goto("about:blank")` 步骤（直接 goto 目标 URL 即可覆盖 SPA 状态）
- 将 `time.sleep(5)` + `time.sleep(8)` + `time.sleep(3)` 替换为 `wait_for_load_state("networkidle")` + 关键元素等待
- 精简为：goto → wait networkidle → 检查 URL → 定位 iframe → 等待关键元素

```python
def navigate_to_dashboard(page):
    info(f"正在打开 Dashboard: {DASHBOARD_URL}")
    page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
    wait_for_network_idle(page, timeout=15000)

    if "_fms-sitedown-dashboard" not in page.url:
        info(f"URL未到位: {page.url}，尝试 JS 修改 hash + reload...")
        page.evaluate("window.location.hash = '#/_fms-sitedown-dashboard'")
        page.wait_for_timeout(1000)
        page.reload(wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
        wait_for_network_idle(page, timeout=15000)

    frame = get_dashboard_frame(page)
    # 等待关键元素（替代固定 sleep）
    for wait_sel in ["text=RAN Site Type", "select", "[class*='select']"]:
        try:
            frame.wait_for_selector(wait_sel, timeout=15000)
            info(f"检测到元素: {wait_sel}")
            break
        except Exception:
            continue
    return frame
```

**节省**：约 16-19s 固定等待 → 实际页面就绪即继续。

#### 变更 4：优化 `get_dashboard_frame()` 函数

- 缩短单次尝试的超时：`wait_for(state="attached", timeout=3000)`、`inner_text(timeout=2000)`
- 减少重试间隔：`page.wait_for_timeout(3000)` → `page.wait_for_timeout(1500)`
- 减少
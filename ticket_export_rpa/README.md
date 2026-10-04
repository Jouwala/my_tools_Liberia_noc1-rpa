# ZTE uSmartNet 工单导出自动化（影刀 RPA → Python）

将原本在「影刀 RPA」中运行的流程，重写为可独立执行的 Python 脚本，
实现：**登录内网 ZTE uSmartNet 门户 → 进入 Trouble Ticket 页面 → 高级查询 → 导出 → 下载 zip**。

> 目标系统：`https://10.100.20.8:28001`（内网，需自签证书，使用 admin 账号登录）

---

## 流程对照（影刀 → Python）

| 步骤 | 影刀原流程 | Python 实现 |
|------|-----------|-------------|
| 1 | 打开网页（授权 URL） | `page.goto(TARGET_URL)` |
| 2 | 窗口最大化 | `--start-maximized` + `no_viewport` |
| 3 | 图像识别点击（高级/继续） | `click_image_if_found()`（可选，默认开启） |
| 4 | 填写用户名 / 密码 / 点击 Login | 自动探测 `#inputUserName` / `#inputCiphercode` / `#loginBut` |
| 5 | 进入 Trouble Ticket | 跳转 `#/_troubleticket` |
| 6 | 高级查询 → 清空 Last Modified Time → Status 全选 → Query → 等结果 → Export Setting(Clear+勾选Available) → Confirm → My Export(每5秒刷新至Success) → Download | `run_export_flow()` |
| 7 | 导出 → Export Setting → Confirm | 网络拦截捕获 `fileName`/`ftpFilePath` |
| 8 | 我的导出 → 下载 | `requests` 调 `/api/eflow-ticket/v1/attachment/download/eflow-tt` |

---

## 目录结构

```
ticket_export_rpa/
├── yingdao_to_python.py      # 主脚本（入口）
├── requirements.txt          # 依赖清单
├── README.md                 # 本文件
├── process/                  # 过程文件（运行截图 + 诊断 HTML）
│   ├── login_result.png          # 登录成功截图
│   ├── 01_tt_page.png            # 进入 TT 页面截图
│   ├── 02_no_advanced_query.png  # 未定位到 Advanced Query（已知问题）
│   ├── 03_last_modified_cleared.png  # 已清空 Last Modified Time
│   ├── 04_status_all.png         # Status 已全选
│   ├── 06b_clear.png             # Export Setting 弹窗内已点 Clear
│   ├── 06c_available_checked.png # Available 复选框已勾选
│   ├── 08_my_export_list.png     # My Export 列表
│   ├── login_page.html           # 登录页 HTML（诊断）
│   └── tt_page_content.html      # TT 页面 HTML（诊断）
└── downloads/                # 导出文件保存目录（运行后生成 zip）
```

> Chromium 浏览器二进制不在本项目内，位于上级目录 `D:/01_RPA/chrome-win/chrome-win/chrome.exe`，
> 脚本会自动查找；也可用环境变量 `YD_CHROME_EXE` 显式指定。

---

## 运行方式

### 1. 安装依赖（首次）

```bash
# 使用项目内置 Python venv
"C:/Users/ZTEEMS/.workbuddy/binaries/python/envs/default/Scripts/python.exe" -m pip install -r requirements.txt
```

### 2. 执行（桌面 / 有界面）

直接运行即可，浏览器窗口会保持打开，便于观察：

```bash
"C:/Users/ZTEEMS/.workbuddy/binaries/python/envs/default/Scripts/python.exe" D:/01_RPA/ticket_export_rpa/yingdao_to_python.py
```

### 3. 无头测试（无界面环境）

```bash
set YD_HEADLESS=1
"C:/Users/ZTEEMS/.workbuddy/binaries/python/envs/default/Scripts/python.exe" D:/01_RPA/ticket_export_rpa/yingdao_to_python.py
```

---

## 配置项（脚本顶部「配置区」）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `TARGET_URL` | 完整授权 URL | 已填好 |
| `USERNAME` / `PASSWORD` | 登录凭据 | `admin` / 见凭据库 `eflow` 组（不写在此文档） |
| `ENABLE_IMAGE_BRANCH` | 是否启用图像识别点击 | `True` |
| `ENABLE_EXPORT_FLOW` | 是否执行登录后导出流程（或 `YD_EXPORT=0` 关闭） | `True` |
| `CLEAR_TIME_FIELD_LABEL` | 高级查询里需清空预填时间的字段 | `"Last Modified Time"` |
| `STATUS_SELECT_ALL_TEXT` | Status 多选面板中"全选"文本（大小写容错） | `"Select All"` |
| `OUTPUT_DIR` | 下载保存目录 | 项目内 `downloads/` |
| `YD_HEADLESS` | `1`=无头模式 | `0` |
| `YD_EXPORT` | `0`=只登录不导出 | `1` |
| `YD_CHROME_EXE` | 显式指定 Chrome 路径 | 自动查找 |

> 按用户要求，高级查询里**不再填指定日期**，而是：清空 `Last Modified Time` 预填的时间、
> 再把 `Status` 全部选中。相关配置：`CLEAR_TIME_FIELD_LABEL`、`STATUS_SELECT_ALL_TEXT`。
> 若字段名与实际 UI 不符，按 `process/03_last_modified_cleared.png`、`process/04_status_all.png` 截图调整。

---

## 已知问题 / 注意事项

1. **iframe 切换**：ZTE uSmartNet 的业务页面渲染在 `iframe[class^="page-mainIframe"]` 中，脚本已自动定位并切到该 iframe 内部执行点击（`get_tt_frame()`）。如果运行时仍然出现 `02_no_advanced_query.png`，说明 iframe 定位失败，请把该截图和 `01_tt_page.png` 发回。
2. **窗口最大化**：桌面模式下使用 `no_viewport=True` + `--start-maximized` + 屏幕分辨率 `--window-size` 三重保证，启动后窗口应填满屏幕。如仍未最大化，检查显示器是否缩放/多屏。
2. **图像识别分支**：当前登录页表单直接渲染，无需点击「高级/继续」图像即可登录；
   若真实环境确实先弹图像，把截图路径填到 `IMG_ADVANCED` / `IMG_CONTINUE` 并保留 `ENABLE_IMAGE_BRANCH=True`。
3. **自签证书**：脚本已设置 `ignore_https_errors=True`，跳过 28001 端口证书校验。
4. **导出下载**：依赖登录后的浏览器会话 Cookie，通过 `requests` 复用，无需重新鉴权。

---

## 依赖

- `playwright` —— 网页自动化
- `pyautogui` + `opencv-python` + `numpy` —— 图像识别点击（可选）
- `requests` —— 下载 zip
- 浏览器：本地 Chromium（`D:/01_RPA/chrome-win/chrome-win/chrome.exe`）

# Site Outage Dashboard Screenshot

## 功能说明

自动登录 ZTE 网管系统，打开 Site Down Dashboard 页面，逐个选择 **RAN Site Type** 下拉框中的选项，并对每个选项截图保存。

## 截图保存位置

截图保存在脚本同目录下的 `screenshots/` 文件夹中，文件名与下拉选项内容一致。

## 配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `USERNAME` | `admin` | 登录用户名 |
| `PASSWORD` | 见凭据库 `eflow` 组 | 登录密码（设置页可改，不写在此文档） |
| `HEADLESS` | `False` | 是否无头模式运行浏览器 |
| `USER_DATA_DIR` | `browser_session` | 浏览器持久化会话目录 |
| `OUTPUT_DIR` | `screenshots` | 截图输出目录 |

## 依赖安装

```bash
pip install -r requirements.txt
playwright install chromium
```

## 使用方法

```bash
python screenshot_site_outage.py
```

## 运行流程

1. 启动 Chromium 浏览器（持久化会话，保留登录状态）
2. 访问 OAuth2 授权页面完成登录
3. 导航到 Site Down Dashboard (`#/_fms-sitedown-dashboard`)
4. 自动检测 RAN Site Type 下拉框（兼容标准 `<select>` 和 Ant Design 自定义下拉框）
5. 逐个选择选项，等待数据刷新后截图
6. 截图以选项名称命名，保存为 PNG 格式

## 注意事项

- 首次运行需要 `playwright install chromium` 安装浏览器
- 浏览器会话缓存在 `browser_session/` 目录，后续运行可复用登录状态
- 如果页面结构变化导致截图失败，会在 `screenshots/` 目录生成 `debug_*.png` 调试截图
- 脚本兼容标准 `<select>` 和 Ant Design 等自定义下拉组件

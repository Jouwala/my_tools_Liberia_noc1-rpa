# my_app 前后台功能测试 & 详细测试记录

## 概述

本测试套件对 **数据洞察 SaaS MVP** 的前后台功能进行自动化测试，并生成带时间戳的详细测试记录（Markdown + JSON + Excel + 截图）。

| 测试类型 | 工具 | 覆盖范围 |
|----------|------|----------|
| 后端 API | FastAPI TestClient（进程内，无需启动服务） | 26 个用例：健康检查、数据库、表浏览、上传/分析归档、GIS、TT&WO Dashboard、任务管理 |
| 前端 E2E | Playwright Chromium（headless） | 8 个用例：8 个页面逐一点击菜单渲染验证，含控制台错误/JS异常/请求失败捕获 |

## 目录结构

```
tests/
├── .venv/                          # 独立 Python 虚拟环境（含所有依赖）
├── report_utils.py                 # 共享报告生成器
├── run_backend_tests.py            # 后端 API 测试套件
├── test_frontend_e2e.py            # 前端 E2E 测试套件
├── run_all_tests.py               # 统一编排器（后端+前端→合并报告）
├── README_tests.md                # 本文件
└── reports/
    ├── test_record_YYYYMMDD_HHMMSS.md      # 合并测试记录（主报告）
    ├── test_record_YYYYMMDD_HHMMSS.json
    ├── test_record_YYYYMMDD_HHMMSS.xlsx
    ├── backend_test_record_*.md/json/xlsx  # 后端独立记录
    ├── frontend_test_record_*.md/json/xlsx # 前端独立记录
    └── shots_YYYYMMDD_HHMMSS/
        ├── FE-01.png ~ FE-08.png          # 各页面截图
```

## 快速开始

### 1. 安装依赖（首次）

```bash
cd D:\01_RPA\Task\my_app

# 创建虚拟环境并安装依赖
python -m venv tests\.venv
tests\.venv\Scripts\pip install -r requirements.txt
tests\.venv\Scripts\pip install fastapi "uvicorn[standard]" httpx pandas openpyxl numpy pydantic scipy shapely sqlalchemy requests pytest playwright

# 安装 Playwright 浏览器
tests\.venv\Scripts\python -m playwright install chromium
```

> **注意**：`requirements.txt` 中 `apscheduler>=3.10.0` 未设上限；若 pip 自动安装了 apscheduler 4.x，
> 应用启动时会因 `job.next_run_time` 属性不存在而崩溃。建议固定为 `apscheduler==3.10.4`。

### 2. 运行全部测试（推荐）

```bash
cd D:\01_RPA\Task\my_app
tests\.venv\Scripts\python tests/run_all_tests.py
```

编排器会自动：
1. 运行后端 API 测试（进程内 TestClient）
2. 启动后端服务 (uvicorn :7038)
3. 运行前端 E2E 测试 (Playwright → :7038)
4. 停止后端服务
5. 输出合并测试记录到 `tests/reports/`

### 3. 仅运行后端测试

```bash
tests\.venv\Scripts\python tests/run_backend_tests.py
```

### 4. 仅运行前端测试（需先启动后端）

```bash
# 终端 A：启动后端
tests\.venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 7038

# 终端 B：运行前端测试
tests\.venv\Scripts\python tests/test_frontend_e2e.py http://localhost:7038
```

或使用跳过启动参数：
```bash
tests\.venv\Scripts\python tests/run_all_tests.py --skip-start
```

### 5. 查看测试记录

| 文件 | 用途 |
|------|------|
| `test_record_*.md` | **人类可读的详细记录**（推荐首先查看） |
| `test_record_*.json` | 结构化 JSON，���于程序解析 / CI 集成 |
| `test_record_*.xlsx` | Excel 表格，支持筛选/排序/打印 |
| `shots_*/FE-*.png` | 各前端页面的截图证据 |

## 测试用例清单

### 后端 API（26 例）

| ID | 模块 | 名称 | 方法 | 路径 |
|----|------|------|------|------|
| BE-01 | 系统 | 健康检查 | GET | `/api/health` |
| BE-02 | 系统 | 数据库概览 | GET | `/api/db/info` |
| BE-03 | 系统 | 数据源时间戳 | GET | `/api/data-source/timestamps` |
| BE-10~13 | 表浏览器 | 列表/数据/画像/列统计 | GET | `/api/tables/*` |
| BE-20~25 | 上传/分析 | 上传→分析→列表→详情→删除→历史 | POST/GET/DELETE | `/api/upload`, `/api/analysis` |
| BE-30~34 | GIS地图 | 站点/下钻/区域/拓扑/边界 | GET | `/api/gis/*` |
| BE-40~41 | TT&WO | Overview/Drilldown | GET | `/api/tt-wo-dashboard/*` |
| BE-50~52 | 任务管理 | 列表/详情/同步状态 | GET | `/api/tasks/*`, `/api/eflow/status` |
| BE-53~55 | 任务管理 | 手动触发/��行任务/启停改期 | — | **SKIP**（依赖外部 eFlow API） |

### 前端 E2E（8 例）

| ID | 页面 | 菜单标签 | 验证内容 |
|----|------|----------|----------|
| FE-01 | 数据总览 | 数据总览 | 表总数/总行数渲染 |
| FE-02 | TT&WO Dashboard | TT&WO Dashboard | SLA/MTTR/Domain 卡片 |
| FE-03 | GIS地图 | GIS地图 | 站点数/区域筛选控件 |
| FE-04 | 分析仪表盘 | 分析仪表盘 | 选择表/生成分析按钮 |
| FE-05 | 表浏览器 | 表浏览器 | 选择表/浏览/画像 Tab |
| FE-06 | 数据上传 | 数据上传 | 拖拽区/上传按钮 |
| FE-07 | 分析归档 | 分析归档 | 搜索框/列表头 |
| FE-08 | 任务管理 | 任务管理 | 任务表格/立即同步 |

## 测试结果解读

- **PASS**：断言全部满足（HTTP 200 + 业务逻辑校验通过 / 前端页面渲染且无 JS 异常）
- **FAIL**：HTTP 状态码不符或业务断言失败 / 页面未渲染或出现未捕获 JS 异常
- **SKIP**：用例依赖外部网络/API 凭据（如 eFlow 同步触发），标记为"建议手动验证"
- **前端诊断**：即使 PASS，也会记录控制台 error 日志和同源请求失败（如离线时地图瓦片加载失败属于正常现象）

## 扩展指南

### 新增后端用例

在 `run_backend_tests.py` 的 `_run_all()` 中添加新的 `_test_xxx(client, record)` 函数，
调用 `_req_case()` 或 `_skip_case()` 记录结果。

### 新增前端页面

在 `test_frontend_e2e.py` 的 `PAGES` 列表中添加元组 `(id, label, expected_texts, note)`。

---

## 深度测试（Deep Testing）

> 新增于 2026-07-24，覆盖错误路径、边界条件、安全、性能和前端工作流。

| 测试类型 | 工具 | 覆盖范围 |
|----------|------|----------|
| 后端深度 API | FastAPI TestClient（进程内） | **30 例**：13 个错误路径(404/422/400)、8 个边界条件(分页/排序/搜索/列校验)、5 个安全(CORS/注入/遍历/鉴权)、4 个性能(GIS/Voronoi/画像/并发) |
| 前端深度 E2E | Playwright Chromium（headless） | **4 例**：上传 CSV→表浏览器验证(含清理)、API 500 故障韧性、375px 移动端响应式、异步数据加载 |

### 运行深度测试

```bash
# 一键运���全部深度测试（后端+前端→合并报告）
tests\.venv\Scripts\python tests/run_deep_all.py

# 仅���端深度
tests\.venv\Scripts\python tests/run_deep_tests.py

# 仅前端深度（需先启动后端服务 :7038）
tests\.venv\Scripts\python tests/test_frontend_deep.py http://localhost:7038
```

### 深度测试发现与建议

完整报告见 **`tests/DEEP_FINDINGS_AND_SUGGESTIONS.md`**，包含 8 项发现（2 Bug / 3 安全 / 1 依赖 / 1 UX / 1 韧性验证）及优先修复路线图。

关键发现摘要：
- **[F-1 🔴]** stats 列名未校验 → 未处理异常 **500**（应返回 404）
- **[F-2 🟡]** sort_by 列名未校验 → 排序静默失效（SQLite 双引号容错）
- **[F-3 🟠]** 上传文件名未净化 + write-before-validate（路径遍历风险）
- **[F-6 🔵]** apscheduler 版本未锁定（新环境拉取 4.x 导致崩溃）
- **[F-7 🟣]** 移动端 375px 下固定侧边栏导致内容不可用

### 深度测试文件

```
tests/
├── run_deep_tests.py              # 后端深度测试套件 (30例)
├── test_frontend_deep.py          # 前端深度 E2E (4例)
├── run_deep_all.py                # 深度测试编排器
├── DEEP_FINDINGS_AND_SUGGESTIONS.md # 发现与建议报告
└── reports/
    ├── deep_test_record_*.md/json/xlsx   # 合并深度记录
    ├── deep_backend_record_*.md/json/xlsx # 后端深度独立记录
    ├── deep_frontend_record_*.md/json/xlsx # 前端深度独立记录
    └── deep_shots_*/                        # 深度测试截图
        ├── FE-D-01.png  # 上传流程截图
        ├── FE-D-02.png  # API 500 韧性截图
        ├── FE-D-03.png  # 移动端响应式截图
        └── FE-D-04.png  # 异步加载截图
```

## 独立守卫（不生成报告，只看退出码）

这类文件不用 pytest 框架（本机 venv 没装 pytest，跑不起来的守卫等于没有），纯计数 + `sys.exit`，
`python tests/test_xxx.py` 与 pytest 两种方式都能跑。**必须用后端实际运行的那个 python**
（本机是系统 Python 3.12）：`Scripts/python.exe` 的 site-packages 没进 `sys.path`，缺
pandas/sqlalchemy/apscheduler，会表现为一片"读不到"的假失败。

| 守卫 | 查什么 | 跑法 |
| --- | --- | --- |
| `test_worker_group_coverage.py` | 任务 ↔ 分组 ↔ 启动脚本 ↔ 前端帮助 四处清单一致（漏登记会让队列 pending 永久滞留） | `python tests/test_worker_group_coverage.py` |
| `test_task_config_live_effect.py` | Settings「任务配置」36 张卡片：页面改的值服务真用得上（死字段 / 派生量算早了 / 坏值没挡住 / 字段被静默丢弃） | `python tests/test_task_config_live_effect.py [task_id …]` |

`test_task_config_live_effect.py` 配一个子进程探针 `task_config_child_probe.py`：卡片保存后另起
全新解释器导入服务模块（配置覆盖只发生在导入期），读 `defaults_factory()` 的真实输出逐点比对。
它只调 service 层写入口，不经 HTTP，所以不会触发 `routers/task_configs.py` 里的 worker 重启；
运行期间会瞬时改写真实配置（每张卡 <1s 后按原始字节还原），别卡在任务正要启动的窗口跑。
改卡片 schema / factory 时请跟着跑一次，说明与背景见 `docs/manual/12-configuration.md` 的 3.1。

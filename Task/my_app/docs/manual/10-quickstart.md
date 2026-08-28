# 10 快速上手

## 环境要求

| 组件 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows | 启停脚本是 `.bat`/`.ps1`/`.vbs`，非跨平台 |
| Python | **3.12**（`pythonw.exe`） | 启动脚本按 `pythonw → PATH → %LOCALAPPDATA%\Programs\Python\Python312 → Python311 → C:\Python312 → $base\Scripts\pythonw.exe` 顺序探测（`start_hidden.ps1:88-103`）。找不到就直接 FAIL |
| Node | v24 已验证可用（本机 v24.16.0） | 前端构建与 OpenClaw 通知 CLI 依赖 |
| PostgreSQL | 16，装在 `C:\Program Files\PostgreSQL\16` | 自启脚本硬编码了 `bin`/`data` 路径（`start_autostart.bat:14,25`、`start_ensure.bat:15,20`、`stop.bat:25,100`） |

⚠️ 两个**不要使用**的解释器：仓库根 `pyvenv.cfg` 是 3.13.14，`.venv-test` 是 3.12.10——后者只被 `backend/migrations/smoke_test_pg.py:44` 用。运行时实际用的是脚本探测到的系统 Python 3.12。

## 第一次装

```powershell
# 1) 后端依赖（区间版，装当前兼容的最新）
pip install -r requirements.txt

# 想完全复刻现网环境，用精确锁版（由系统 Python 3.12 全量锁定）
pip install -r requirements.lock.txt

# 2) 配置数据库
#    新建 backend\.env，内容参照下方"最小可用 .env"

# 3) 建表
python backend/scripts/init_db.py
alembic upgrade head

# 4) 前端构建（产物目录必须是 _fe_dist，否则后端找不到静态文件）
cd frontend
npm install
npm run build
```

### 最小可用 `.env`

放在 `backend/.env`。键名如下，值按你自己的环境填（**不要把带真实值的 .env 提交或外发**）：

```ini
MY_APP_DB_MODE=pg
DATABASE_URL=postgresql+psycopg://<user>:<pass>@<host>:5432/<db>
MY_APP_WORKER_GROUPS=u,n,m,c
# 可选：对外暴露接口时启用
# MY_APP_API_TOKEN=<随机长串>
# 可选：覆盖 CORS 白名单
# MY_APP_CORS_ORIGINS=http://localhost:7090,http://localhost:7038
```

`MY_APP_DB_MODE=sqlite` 可脱离 PG 单机试跑（会退回本地 `db/app.db`）。

## 启动

| 场景 | 命令 | 行为 |
| --- | --- | --- |
| 日常手动启动 | `start.bat` | 清 `stopped.flag` → 调 `start_hidden.ps1` → 轮询 7038 就绪 → 校验 watchdog 与 4 个 worker PID → 打印访问地址（`start.bat:13,24,29-43,77-78`） |
| 静默启动（开机自启用） | `start_hidden.vbs` → `start_hidden.ps1 -Quiet` | 无窗口，尊重 `stopped.flag`（`start_hidden.ps1:125`） |
| 5 分钟一次的保活 | `start_ensure.bat`（计划任务） | `-Quiet -Force`，端口被占也抢回来（`start_hidden.ps1:161`） |
| 端口被非托管进程占用 | `start_hidden.ps1 -Force` | 先杀占 7038 的进程再启 |

`start_hidden.ps1` 是**唯一实质启动器**，它依次拉起：PG 健康检查（:137）→ `python -m backend.backend_watchdog`（:173）→ `python -m backend.worker_watchdog`（:199）→ `npm run preview`（:244）。执行结果写 `log\start_hidden_result.txt`，子进程输出写 `log\*_console.log(.err)`（:80-83,263-268）。

## 访问

| 地址 | 用途 |
| --- | --- |
| `http://localhost:7090/myapp/` | 前端主入口（生产经 nginx 则是 `http://<主机>/myapp/`） |
| `http://localhost:7090/myapp/?page=battery` | 直接定位到某个页面（`?page=` 见 `02-architecture.md`） |
| `http://localhost:7038/docs` | FastAPI 交互式接口文档（Swagger）。标题仍是 `"数据洞察 SaaS MVP"`（`main.py:73`），那是项目最初定位的历史命名，不代表现在的功能范围 |
| `http://<本机IP>:7090` | 局域网访问，后端与 preview 都绑 `0.0.0.0` |

局域网完整配置（PG 放行 5432、防火墙规则）见 `13-operations.md` 的"局域网访问"一节。

## 停止

```powershell
stop.bat        # 停前后端与 worker，保留 PostgreSQL
stop.bat all    # 连 PostgreSQL 一起停
```

`stop.bat` 做 8 层清理（树杀两 watchdog → 按端口杀 7038/8000/7040/8787/8790/7090/5173 → 命令行清扫 → 删 PID 与心跳 → 端口复核 → 可选停 PG → 写 `stopped.flag` → 有残留则 UAC 提权重跑）。

**`stopped.flag` 是"人工停机"意图标记**：写了它，`-Quiet` 自启就不会把你拉起来（`start_hidden.ps1:125`）。想恢复自动启动，用 `start.bat`（它开头就清这个标记，`start.bat:13`）。

## 装完之后必须做的三步

1. **系统设置 → 凭据**：把要用的分组填上账号口令，逐组点"测试连接"，全绿才继续。
2. **系统设置 → 收件人**：确认报表收件人名单（留默认则按内置清单发）。
3. **任务管理**：挑一个轻量任务点"执行"，等它变成功——这一步同时验证了队列、worker 分组认领、写库链路。若任务长时间 pending，先看 `04-task-system.md` 的 worker 分组，再看 `13-operations.md` 排障。

## 换机器部署要改的硬编码

按出现位置逐个改，漏一个就起不来：

| 位置 | 内容 |
| --- | --- |
| `start_autostart.bat:14,25`、`start_ensure.bat:15,20`、`stop.bat:25,100` | `C:\Program Files\PostgreSQL\16\{bin,data}` |
| 同上各脚本 | 当前用户目录下的 Python 路径、项目绝对路径 |
| `frontend/vite.config.ts:49` | `outDir: 'D:/01_RPA/Task/_fe_dist'`（绝对路径，**在 my_app 之外**） |
| `backend/data/settings.json` 或"系统设置 → 远程主机" | 远程主机地址（优先级 `MY_APP_REMOTE_HOST` > 该文件 > 内置默认，改后无需重启，`backend/config/remote_host.py:14-21`） |
| `backend/services/*.json` | 各网管/EMS 的 `host`/`port` 等连接参数 |

所有 `.bat` 必须保持 **CRLF 行尾 + 纯英文 `REM` 注释**（`start.bat:21-22` 明确写了 keep ASCII-only）。中文注释在 UTF-8 无 BOM 下会被 cmd 按 ANSI 解析，导致后续行被静默跳过却仍显示成功。

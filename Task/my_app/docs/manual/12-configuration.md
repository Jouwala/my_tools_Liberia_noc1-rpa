# 12 配置项与开关

三层配置，优先级从高到低：**环境变量 > 数据库/配置文件 > 代码默认值**。

## 一、界面能改的（推荐）

见 `11-feature-guide.md` 第 22 节。凭据、收件人、远程主机、任务参数都能在「系统设置」改，改完即生效，不需要重启。排程在「任务管理」改。

| 改动 | 落到哪 | 需要重启？ |
| --- | --- | --- |
| 凭据 | `db/app.db` 的 `credentials` 表（**明文**，见 `05-security-and-credentials.md`） | 否（缓存 TTL 30s） |
| 收件人 | 收件人存储 + `email_reports/` 下的名单文件 | 否 |
| 远程主机 | `backend/data/settings.json` 的 `remote_host` | 否 |
| 排程（cron） | 主库 `task_schedule_config` 表 | 否 |
| 任务参数 | 任务配置文件（`services/task_configs_registry.py` 注册 36 张卡片） | 否（保存后自动重启 worker 组，见 3.1） |

## 二、`.env` / 环境变量（改这些要重启）

放在 `backend/.env`。全仓库共有 **203 个**可被环境变量覆盖的键（统计口径：`grep -rhoE 'environ\.get\("[A-Z_0-9]+"|getenv\("[A-Z_0-9]+"' --include=*.py backend` 去重，2026-09-18 复算）。下面只列**需要知道存在**的分组，键名可写、值不可写。

**运行模式（最关键的一组）**

| 键 | 默认 | 作用 |
| --- | --- | --- |
| `MY_APP_DB_MODE` | `sqlite` | `sqlite` \| `pg`，主库后端（当前生产为 `pg`） |
| `DATABASE_URL` | — | PG 连接串 |
| `PG_POOL_SIZE` / `PG_MAX_OVERFLOW` | — | PG 连接池 |
| `MY_APP_TASK_QUEUE` | 未设 | `=1` 才走队列表 + worker；否则退回调度器进程内线程 |
| `MY_APP_WORKER_GROUPS` | 空 | 空=单 worker 全量；`u,n,s,w,m,c,v`=七组并行（**新增任务未归组会 pending 卡死**；新增组必须与 `GROUP_TASK_MAP`、`start_hidden.ps1` 同步，`restart_workers.py::ALL_GROUPS` 自动跟随 `GROUP_TASK_MAP`） |
| `MY_APP_WORKER_TASKS` / `MY_APP_WORKER_POLL` | — | 单 worker 模式的任务白名单与轮询间隔 |
| `WORKER_STALE_RUNNING_SECONDS` | `2160`（30min） | 僵尸 running 回收阈值（配合 PID 存活核对） |
| `WORKER_STALE_PENDING_SECONDS` | `21600`（6h） | pending 无人认领判陈旧并置 failed（释放单飞名额；下限 1800s） |
| `MY_APP_DISABLE_SCHEDULER` | 未设 | 置位则不启动任何定时投递（调试/维护窗口用） |
| `MY_APP_BACKEND_PORT` | `7038` | uvicorn 端口 |
| `MY_APP_CORS_ORIGINS` | 7038/5173 白名单 | CORS 允许来源 |
| `MY_APP_API_TOKEN` | 未设 | 远程接口令牌；**未设时远程一律 403**。判定已改为按代理头还原真实客户端（`backend/security.py:79-102`），详见 `05-security-and-credentials.md` |
| `MY_APP_REMOTE_HOST` | 覆盖 `settings.json` | 远程主机地址（DB 写入服务 `DB_WRITER_PORT`=8765、`FTP_PORT`=21） |

**统一门户登录链路（分机部署必看）**

my_app 没有自己的账号体系，登录靠回调门户校验。这组键决定"回调谁"：

| 键 | 默认 | 作用 |
| --- | --- | --- |
| `UNIPLAM_ME_URL` | `http://127.0.0.1:9267/uniplam/api/auth/me` | 门户 `/me` 校验地址。**默认值假定 my_app 与门户同机**；分机部署必须显式指向门户所在机器，否则门户登录成功、进 my_app 却一直未登录（`portal_auth.py:77`）。排障见 `13-operations.md` 的「门户回调用错地址」 |
| `UNIPLAM_TIMEOUT` | `5` | 回调门户的超时（秒） |
| `MYAPP_SESSION_TTL` | `28800`（8h） | myapp 会话有效期 |
| `MYAPP_SESSION_SLIDING` | `1` | 滑动续期开关 |
| `MYAPP_SESSION_COOKIE` | `myapp_session` | 会话 Cookie 名 |
| `MYAPP_SESSION_MAX_TTL` | `0`（不封顶） | 会话绝对上限 |
| `MYAPP_KIOSK_KEY` | 未设 | 大屏常驻登录密钥；未设时 `/api/auth/kiosk` 返回 404 |
| `MYAPP_KIOSK_COOKIE_MAX_AGE` | 10 年 | 常驻会话 Cookie 寿命 |

> 后端每次启动会自检 `UNIPLAM_ME_URL` 可达性并把结论打进启动日志，
> 配错时**不用等用户登录失败**就能在日志里看到。

**可靠性**

`AUTO_RETRY_ENABLED`、`AUTO_RETRY_EXTRA_EXCLUDE`、`AUTO_RETRY_INCLUDE_EMAIL`、`AUTO_RETRY_MISS_ENABLED`；`CREDENTIAL_CACHE_TTL`（默认 30s）、`EMAIL_RECIPIENT_CACHE_TTL`。

**上游连接与超时**（各系统同名套路：`*_HOST`/`*_PORT`/`*_USER`/`*_PASS(WORD)`/`*_CONNECT_TIMEOUT`/`*_READ_TIMEOUT`/`*_HTTP_MAX_RETRIES`/`*_HTTP_RETRY_DELAY`/`*_PARALLEL_WORKERS`/`*_DAYS_BACK`）

`RAN_UME_*`、`CNN_KPI_*`、`IPRAN_KPI_*`、`EFLOW_*`、`BATT_*`、`EMS_*`、`FTP_*`、`FW_*`、`SLA_PARALLEL_WORKERS`、`SLA_DAYS_BACK`。
证书校验开关见 `backend/security_tls.py:29-39`（`*_TLS_VERIFY`，**默认关闭**）。

**通知**：`WHATSAPP_*`、`TWILIO_*`、`PHONE`/`SMS_SERVICE_PROVIDER`、SMTP 系列、微信/OpenClaw 相关（走 `services/weixin_notifier.py`）。

**任务健康告警**（`services/task_health_alert.py`，2026-09-18 新增）：`TASK_HEALTH_ALERT_ENABLED`（默认 `1`，置 `0`/`false` 静音，维护窗口用）、`TASK_HEALTH_ALERT_RENOTIFY_HOURS`（同一异常持续多久后重提，默认 `24`）。告警去重状态文件：`TMP/task_health_alert_state.json`（可安全删：删后下轮会把当前异常当新异常再通知一次，不影响判定）。

**其他**：`GEMINI_API_KEY`（指标解释文本生成）、`CALL_CHAIN_DEPTH`（新鲜度巡检调用链深度）、`BATT_FRESH_HOURS`/`BATT_STALE_DAYS`/`BATT_SOC_LOW`/`BATT_HEALTH_*`（电池看板的"新鲜度/低电量/健康度"阈值——**页面上的数字直接受这些值影响**）。

## 三、配置文件（JSON）

| 文件 | 用途 | 关键字段（不是值） |
| --- | --- | --- |
| `backend/.env` | 上述环境变量 | — |
| `backend/data/settings.json` | 目前仅 `remote_host` | `remote_host` |
| `services/ran_ume_config.json` | RAN UME 登录与查询 | `host`/`port`/`query_configs`/`templateid`/`templatename`/`motid`/`nfctid`/`days_back` |
| `services/main_kpi_config.json`、`network_kpi_config.json`、`ipran_kpi_config.json`、`cnn_kpi_config.json`、`pl_config.json` | 各类 KPI 查询模板与回溯天数 | 同上套路 |
| `services/eflow_alarm_config.json` | eFlow FM Active/History 告警字段映射 | — |
| `services/cn_ems/ems_config.json` | CN EMS 客户端自动化 | `username`/`password`（**敏感**）、`client_exe`、`menu_path`、`login_timeout` |
| `services/cm_data/cm_flows.json` | RAN CM 小区配置导出流程 | `flows`、`payload`、`moc` |
| `services/eflow_rules/eflow_TT_rules_check_latest.json` | TT 级别矫正规则的最近一次快照 | 含上游网关地址，**外发前先脱敏** |
| `services/eflow_rules/eflow_TT_rules.xlsx` | **正式**的 TT 规则表（`eflow_rules_matcher.py:29` 读它） | — |

> 仓库根的 `eflow_TT_rules.xlsx` 与 `eflow_TT_Rule_Collector - Copy.py` 是**副本/草稿**，正式生效的是 `backend/services/eflow_rules/` 下那份。改规则请改 `eflow_rules/` 里的，否则改了不生效。

### 3.1 任务配置卡片（Settings →「任务配置」）

36 张卡片由 `backend/services/task_configs_registry.py` 注册。规则：

- **页面显示的默认值不是抄写的**：每张卡的 `defaults_factory` 从服务模块常量现读（例如 `_main_kpi_defaults`、`_sp_defaults`），所以页面上的默认值就是代码在用的值，不会与代码漂移。
- **优先级**：环境变量 > 配置文件（页面编辑） > 代码默认。覆盖都发生在**模块导入期**，因此由 HOST/PORT 拼出来的派生常量（`PM_REFERER`、`HISTORY_REFERER`、`LOGIN_URL`/`DASHBOARD_URL`、`ALARM_REFERER`）必须写在覆盖块**之后**，否则页面上改主机没用。
- **保存链路**：`PUT /api/task-configs/{id}`（`backend/routers/task_configs.py:72-80`）→ schema 校验（`task_config_files.py:204-249`）→ 合并（`:272`）→ 原子写 → `_restart_config_workers()`（`routers/task_configs.py:33-57`）杀掉 `backend/worker_{u,n,v,m,c}.pid`，看门狗秒级重拉 → 下次任务运行即用新值。**不碰 `worker_watchdog.pid`**（误杀它=改完配置任务再也不跑）。
- **table 类型是整表替换**（`task_config_files.py:272-288`）：保存时页面必须把所有行带回；在页面上删掉一行就是真删。行里非 schema 的键（`keep_columns`、`payload` 等内部字段）会原样保留。
- **逗号整数字段**（`itemsposition`/`itemsposition1`/`itempositionbusiness`）在 schema 里标了 `int_list:true`，填字母会在保存时被挡下（`task_config_files.py:223-228`）。原因：服务在导入期用 `int()` 解析它们，一个字母会让**整个模块 import 失败**——现象是任务直接不起，而不是"这项没生效"。
- **回到纯代码默认**：删掉对应的 `*_config.json` 即可，卡片下次打开时由 factory 从代码取真值。反过来，**文件一旦存在就以文件为准**：代码里改了默认值而磁盘上还有同名旧文件，页面和服务仍用文件值——这是"改了不生效"最常见的原因。
- **改注册表/校验代码本身**（不是改配置值）时，要重启后端 API 进程：它在启动时 import 一次注册表，uvicorn 没有开 `--reload`。只改配置值不需要重启 API（保存即重启 worker）。
- **凭据不进配置文件**：密码/Token 由「凭据管理」页签（`credentials` 表）管理，卡片上只有主机、端口、路径、模板、天这类非敏感项。
- **守卫**：`python tests/test_task_config_live_effect.py`（必须用后端实际运行的那个 python，本机是系统 Python 3.12）。它对每张卡走真实写入口写哨兵、再在全新解释器里读服务真正会用的值，覆盖"死字段 / 派生量算早了 / 坏值没挡住 / 字段被静默丢弃"四类问题，跑完自动还原配置文件。改卡片时请跟着跑一次。

## 四、前端与构建

| 项 | 位置 | 说明 |
| --- | --- | --- |
| 页面基础路径 | `vite.config.ts:6` `base:'/myapp/'` | 改了要同步 nginx 与 `main.py:280` |
| 端口与代理 | `vite.config.ts:9-11`（dev）、`:27-41`（preview） | 改端口要同步 `start.bat`、防火墙 |
| 构建输出 | `vite.config.ts:49` | **绝对路径，指向 my_app 之外**（见 `02-architecture.md` 的已知约束） |
| 语言 | `localStorage['app-locale']` | 界面右上切换 |
| 侧栏折叠 / 自动刷新间隔 | `localStorage['myapp_sider_collapsed']`、`localStorage['myapp_auto_refresh_sec']` | 存在浏览器，换电脑要重设 |

## 五、Python 依赖

| 文件 | 内容 |
| --- | --- |
| `requirements.txt` | `>=` 区间版（含 playwright、geoip2、exchangelib，`psycopg2-binary==2.9.12` 是唯一钉死的） |
| `requirements.lock.txt` | 由系统 Python 3.12 精确锁定的全量清单——**复刻现网用它** |

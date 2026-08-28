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
| 任务参数 | 任务配置文件（`services/task_configs_registry.py:1-30`） | 视任务，一般否 |

## 二、`.env` / 环境变量（改这些要重启）

放在 `backend/.env`。全仓库共有 **147 个**可被环境变量覆盖的键（统计口径：`grep -rhoE 'environ\.get\("[A-Z_0-9]+"|getenv\("[A-Z_0-9]+"' --include=*.py backend`）。下面只列**需要知道存在**的分组，键名可写、值不可写。

**运行模式（最关键的一组）**

| 键 | 默认 | 作用 |
| --- | --- | --- |
| `MY_APP_DB_MODE` | `sqlite` | `sqlite` \| `pg`，主库后端（当前生产为 `pg`） |
| `DATABASE_URL` | — | PG 连接串 |
| `PG_POOL_SIZE` / `PG_MAX_OVERFLOW` | — | PG 连接池 |
| `MY_APP_TASK_QUEUE` | 未设 | `=1` 才走队列表 + worker；否则退回调度器进程内线程 |
| `MY_APP_WORKER_GROUPS` | 空 | 空=单 worker 全量；`u,n,m,c`=四组并行（**新增任务未归组会 pending 卡死**） |
| `MY_APP_WORKER_TASKS` / `MY_APP_WORKER_POLL` | — | 单 worker 模式的任务白名单与轮询间隔 |
| `MY_APP_DISABLE_SCHEDULER` | 未设 | 置位则不启动任何定时投递（调试/维护窗口用） |
| `MY_APP_BACKEND_PORT` | `7038` | uvicorn 端口 |
| `MY_APP_CORS_ORIGINS` | 7038/5173 白名单 | CORS 允许来源 |
| `MY_APP_API_TOKEN` | 未设 | 远程接口令牌；**未设时远程一律 403**（反代场景下校验会被绕过，见风险章） |
| `MY_APP_REMOTE_HOST` | 覆盖 `settings.json` | 远程主机地址（DB 写入服务 `DB_WRITER_PORT`=8765、`FTP_PORT`=21） |

**可靠性**

`AUTO_RETRY_ENABLED`、`AUTO_RETRY_EXTRA_EXCLUDE`、`AUTO_RETRY_INCLUDE_EMAIL`、`AUTO_RETRY_MISS_ENABLED`；`CREDENTIAL_CACHE_TTL`（默认 30s）、`EMAIL_RECIPIENT_CACHE_TTL`。

**上游连接与超时**（各系统同名套路：`*_HOST`/`*_PORT`/`*_USER`/`*_PASS(WORD)`/`*_CONNECT_TIMEOUT`/`*_READ_TIMEOUT`/`*_HTTP_MAX_RETRIES`/`*_HTTP_RETRY_DELAY`/`*_PARALLEL_WORKERS`/`*_DAYS_BACK`）

`RAN_UME_*`、`CNN_KPI_*`、`IPRAN_KPI_*`、`EFLOW_*`、`BATT_*`、`EMS_*`、`FTP_*`、`FW_*`、`SLA_PARALLEL_WORKERS`、`SLA_DAYS_BACK`。
证书校验开关见 `backend/security_tls.py:29-39`（`*_TLS_VERIFY`，**默认关闭**）。

**通知**：`WHATSAPP_*`、`TWILIO_*`、`PHONE`/`SMS_SERVICE_PROVIDER`、SMTP 系列、微信/OpenClaw 相关（走 `services/weixin_notifier.py`）。
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

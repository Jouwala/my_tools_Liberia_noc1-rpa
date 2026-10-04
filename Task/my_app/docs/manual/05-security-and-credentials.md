# 05 访问控制与凭据

这一章既说明"现在怎么防护"，也如实记录**已验证存在的风险**。上线或移交前请先读完本章。

## 结论先说

**my_app 没有用户账号体系。** 没有注册、没有登录态、没有角色权限、没有操作审计。任何能访问到 `:7038` 或前端入口的人，都等于拥有系统的完整操作能力（包括触发任务、改凭据、导出全表数据）。

## 唯一的接口防护：`require_protected`

`backend/security.py:17-26`：

- 请求来自**回环地址** → 直接放行；
- 请求来自远程 → 要求请求头 `X-API-Token` 等于环境变量 `MY_APP_API_TOKEN`；
- `MY_APP_API_TOKEN` **未设置时，远程请求一律 403**（这是"默认拒绝"，比配了弱 token 更安全）。

挂载范围很窄，只有 4 个 router 共 18 处装饰器：`routers/tasks.py`、`routers/upload.py`、`routers/task_configs.py`、`routers/cm_flows.py`。

> 🔴 **已验证风险 1：Token 校验在反向代理后失效。**
> 生产链路是 nginx → vite preview → `/api` 反代到 7038，前端 `baseURL: '/api'`（`frontend/src/api.ts:4`）。经同源反代后，后端看到的 `request.client.host` **恒为 `127.0.0.1`**，于是所有请求都命中"回环放行"分支。也就是说：**只要访问走 nginx，Token 形同不存在。**
> 现实缓解手段只剩网络层：`:7038`/`:7090` 不对外网开放、内网访问范围可控。若要把系统放到更大范围，必须先改造防护（校验 `X-Forwarded-For` 真实来源或全站接入认证），不要指望这个 Token。

> 🔴 **已验证风险 2：其余绝大多数接口无防护。**
> 凭据读写、表数据导出、GIS/看板查询、设置保存等都不在 `require_protected` 覆盖范围内。

## 凭据存储

所有上游系统账号集中在一个注册表里，前端"系统设置 → 凭据"统一维护：

- **17 个分组 key**：`zte_ume`、`vmax_cxo`、`vmax_gbase`、`ipran_ume`、`ccn_ume`、`eflow`、`rais`、`fms_portal`、`fw_kpi`、`mw_ume`、`ume_in`、`battery_ume`、`cm_data`、`sftp_sp`、`mail_126`、`owa_mail`、`weixin`（`backend/services/credential_store.py:38-372`）。
- 每组元数据字段：`key`、`name`、`name_en`、`usage`、`usage_en`、`username_label`、`secret_label`、`env_user`、`env_secret`、`testable`、`test_host`、`test_port`。字段名可写进文档，**值不可以**。
- 读取优先级：**环境变量 > 数据库 > 代码默认值**（`env_user`/`env_secret` 指定对应变量名）；内存缓存 TTL 默认 30 秒（`CREDENTIAL_CACHE_TTL`）。
- 列表接口返回**掩码**，"显示明文"走 `GET /api/credentials/{key}/reveal`，"测试连接"走 `POST /api/credentials/test`（仅 `testable: true` 的组走真实登录）。

> ⚠️ **2026-09-23 修正：注册表曾漏掉两组，导致页面无法配置。**
> `battery_ume`（Battery UME 电池网管）与 `cm_data`（RAN CM 小区数据同步）此前**不在注册表内**：
> - `battary_kpi_fetch_socket.py` 把账号密码硬编码在 `DEFAULT_USERNAME`/`DEFAULT_PASSWORD`，
>   `load_credentials()` 的优先级链是 `命令行 > BATT_* 环境变量 > url.txt > 内置默认值`，**整条链没有 credential_store**；
> - `cm_data_export.py` 同样硬编码 `USERNAME`/`PASSWORD`，而 `task_configs_registry.py` 的文案却写着"凭据在凭据管理 → cm_data"，**页面实际没有该分组**，文案与实现对不上。
>
> 两组现已补入注册表，调用方各自新增 `_runtime_credentials()` 走本模块（约定见 `credential_store.md`）。

> 🔴 **已验证风险 3：凭据明文存储。** `set_credential` 把用户名口令**明文**写入 `db/app.db` 的 `credentials` 表，无加密、无哈希。
> 🔴 **已验证风险 4：凭据不随主库走。** `credential_store._get_conn` 用 `sqlite3` 直连本地 `app.db`，绕过 `MY_APP_DB_MODE`。当前 PG 模式下，业务数据在远程 PG、凭据在本机 `app.db`。备份/迁移只搬一边必然丢东西。

### 2026-09-27：硬编码口令清理与根因修复

**背景**：同一个口令在 30+ 个文件里各存一份副本（`PASSWORD = "..."`、`SFTP_PASS = "..."` 等），
既是**重复真相源**，也让口令明文进了版本库。多个文件还完全没接 `credential_store`。

**根因（值得记住）**：`get_credential(key, default_user, default_secret)` 此前**只认传进来的参数**，
从不回退到凭据组自己的 `default_user`/`default_secret`。于是每个调用方都被迫再写一遍字面量兜底 ——
"注册表里的默认值"和"代码里的默认值"成了两份必须同步的副本。

**修复**：`credential_store.get_credential` 现在会在调用方未传默认值时，自动回退到本组默认值
（`credential_store.py` 内 `if group:` 分支）。此后全仓 `get_credential("some_key", USER, PASS)`
一律简化为 `get_credential("some_key")`。

**清理范围**：30+ 个源码文件的口令/Token/授权码字面量已移除，涉及 `zte_ume`、`mw_ume`、`ccn_ume`、
`ipran_ume`、`fw_kpi`、`battery_ume`、`cm_data`、`sftp_sp`、`mail_126`、`owa_mail`、`weixin` 等分组。
三个原本**完全没接凭据系统**的模块（`mw_ume_kpi.py`、`gernarate_sp_report.py`、`ms_sla_service.py`）
已补上 `_runtime_credentials()`。

**两处刻意的例外**（不是漏网，勿"顺手清理"）：

| 文件 | 为何保留 |
| --- | --- |
| `backend/services/credential_store.py` | 中央凭据库，`CREDENTIAL_GROUPS` 里的默认值**就是**唯一真相源 |
| `email_reports/owa_credentials.py` | 刻意的最后兜底（`env > credential_store > 此处`）；且 `_LEGACY_DEFAULTS` 依赖该字面量的**值**来识别"调用方传了历史旧口令"，改值会同时改变那套识别逻辑。其 docstring 记录了 2026-09-18 的 65 小时邮件全故障 |

**守卫**：`tests/test_engineering_guards.py::test_no_hardcoded_secrets_in_source`
以"历史口令字面量黑名单"钉住，命中即失败；豁免必须连同理由写进 `_SECRET_LITERAL_EXEMPT`。

> ⚠️ **删源码 ≠ 消除泄露。这些口令已经进入 git 历史，必须轮换才能真正失效。**
> 本清理只解决了"不再继续留在工作树里"，**不能替代轮换**。

### 2026-10-04：清理收尾 —— my_app 内明文口令归零

**上一轮（09-27）遗留了两个问题**，本轮补齐。

**问题一：`default_secret` 仍是唯一真相源。**
上一轮把调用方的字面量删了，但 `credential_store.py` 自己还留着 **17 组明文默认值**，
并把它称为"唯一真相源"。实测这 17 组里有 **14 组从未在设置页配置过** ——
也就是说代码里的明文就是**唯一**来源，口令不仅入了库，**还无法在页面轮换**（改页面没用，
代码默认值仍在兜底）。

处理分两步，顺序不能反：
1. **先迁进 DB**：`TMP/_migrate_credentials_to_db.py` 把 14 组当前生效值写入 `credentials` 表。
   因为 `get_credential` 优先级是 `env > DB > 代码默认`，先写 DB **不改变任何行为**。
   迁移后 17 组全部有 DB 值，设置页可见可改。
2. **再清空代码**：`TMP/_strip_credential_defaults.py` 把 17 处 `default_secret` 置为空串。
   此时删掉它已无行为影响（DB 已兜住），但明文不再入库。

**问题二：守卫的两个盲区（比前者更危险）。**
- **只扫 `my_app`**：工作区其余 **52 个已入库文件**的明文副本完全不受检查
  （`Site_outage/`、`ticket_export_rpa/`、`Task/sp/`、`WareHouseDashBoard/` 等）。
- **黑名单少 5 个口令**：只有 12 条，漏了 `fms_portal` / `rais` / `ume_in` / `vmax_cxo` / `vmax_gbase`
  —— 这 5 个**写回源码也不会被拦**，守卫形同虚设。

已修：`_SCAN_ROOTS` 扩到全工作区，黑名单补到 17 条，扫描后缀加入 `.md`/`.txt`
（文档里的明文同样是泄露，`ticket_export_rpa/README.md` 就曾写着口令）。
**守卫必须能被反证**：`TMP/_verify_guard_catches_secrets.py` 会临时把口令写回源码、
确认守卫**确实失败**，再还原 —— 一个永远通过的守卫没有价值。

**本轮实际清理范围（my_app 内 12 个文件）**：

| 文件 | 处理 |
| --- | --- |
| `backend/services/credential_store.py` | 17 组 `default_secret` 清空；`weixin` 的 `default_user` 清空（那是 SendKey，本身就是凭据） |
| `backend/services/eflow_api_client.py`、`site_outage_service.py` | `os.environ.get("EFLOW_PASS", "<明文>")` → 空串，口令只从 env/凭据库取 |
| `tools/realtime_proxy.py`、`realtime_proxy_vmax.py` | `_load_cred(..., default_secret)` 传空串 |
| `backend/services/ume_in/ume_in_kpi_service.py` | 同上（`UME_IN_PASSWORD`） |
| `backend/services/vmax_multi_data/vmax_report_client.py` | 同上（vmax_cxo） |
| `backend/services/ume_in/url.txt` | 抓包记录里的 `password:` 行改为指向凭据库 |
| `backend/services/vmax_gbase/vmax_gbase_client.py`、`olib_soc_report/*.py` | 连接串示例中的口令改为 `<password>` 占位符 |
| `backend/services/credential_store.md`、`eFlow_API集成方案.md`、`.workbuddy-ai/memory/2026-09-13.md` | 文档里的明文删除 |
| `tests/test_olib_soc_report.py` | 脱敏测试改用**假哨兵**口令（原先是真实口令，等于写进版本库） |

**09-27 的两个"刻意例外"现已都不成立**（该表已作废）：

- `credential_store.py`：不再是例外 —— 17 组 `default_secret` 已清空，它的 docstring 里
  也补了"为什么这里必须留空、新环境首次部署该怎么办"。
- `email_reports/owa_credentials.py`：**按其 docstring 自己给出的正确做法执行** ——
  "让 credential_store 成为唯一来源并删掉第 3 级"。`DEFAULT_PASSWORD` 清空、
  `_LEGACY_DEFAULTS` 置空集（把历史口令列在里面等于又写进口令）。
  实参默认值本身已不存在，识别逻辑改为"空串即视为没传"。
  两级都取不到时返回空口令让认证**明确失败** —— 而不是静默用可能过期的旧口令，
  那正是 2026-09-18 那次 65 小时故障的形态。

**验证**：17 组凭据全部仍能解析（`ALL_CREDENTIALS_RESOLVE`）；离线回归 274 项通过；
`site_outage` 连续两轮实测均复用会话、0 次登录、各 4 张截图（凭据全部来自 DB）；
设置页 `/myapp/?page=settings` 17 组可见。

**尚未完成**：工作区 `my_app` **之外**的 52 个已入库文件仍有明文副本，
已在守卫的 `_PENDING_WORKSPACE_CLEANUP` / `_PENDING_TASK_SUBDIRS` 里**逐目录列明**
（不是降低检查强度：已清过的 `my_app` 仍受完整检查，清完一个就从清单删一个，
清空后删除该清单即可）。做法与 my_app 一致，见清单上方注释。

## 上游站点会话

`backend/services/auth_manager.py:83` 把登录后的站点会话 cookie 缓存在 `backend/services/auth_cache/`（RSA 加密登录流程 + `forgery_token`，带 TTL）。

含义：`auth_cache/` 目录里的内容等同于**有效登录态**，与口令同等对待——不外发、不入 git、不放进截图。

### 会话必须跨任务/跨进程复用（2026-10-04 修正）

`auth_cache/` 的存在意义就是**让多个任务/多个 worker 进程共用一份已申请的 token**，
避免同一账号反复登录把 eFlow 登录接口打崩。三条使用纪律：

| 场景 | 应当用 | 说明 |
| --- | --- | --- |
| 任务入口「确保已登录」 | `eflow_api_client.ensure_login()` | 本进程已有会话直接返回（零网络）；没有才走 `login()`，而 `login()` 先读磁盘缓存 |
| 长任务中途自检会话 | `eflow_api_client.ensure_login_fresh(max_age_seconds=…)` | 同上仍优先命中缓存，仅在本进程会话超龄时重新确认 |
| 已确认服务器会话已死（HTTP 401） | `login(force_refresh=True)` | **仅此一处**应强制真实登录，由 `_reauthenticate_on_401()` 调用（`eflow_api_client.py:210-219`） |

**反例（2026-10-04 修正前的缺陷）**：三个规则收集器
（`eflow_rules/eflow_Alarm_Rule_Collector.py:78`、`eflow_Push_Rule_Collector.py:70`、
`eflow_TT_Rule_Collector.py:63`）与两个 SP 同步任务曾**无条件裸调 `login()`**，
每次运行都走一遍鉴权流程，完全不看本进程是否已有会话。
（修正后分别改为 `eflow_Alarm_Rule_Collector.py:80`、`eflow_Push_Rule_Collector.py:72`、
`eflow_TT_Rule_Collector.py:65` 的 `ensure_login()`。）

**为什么这件事特别容易踩**：`eflow_api_client._session_cookie`（`:150`）是
**进程内全局变量**，而 worker 是 `u/n/v/m/c` 多进程分组（见 `AGENTS.md` 第七节）——
每个进程第一次碰 eFlow 都各自登录一次，磁盘上明明有可用 token 也发现不了。

**TTL 与调度周期的边界问题**：`auth_manager.DEFAULT_TTL = 1800`（30 分钟，
`auth_manager.py:87`，可用环境变量 `AUTH_TOKEN_TTL` 覆盖）与最密调度
`eflow_active_alarm`（`*/30 * * * *`，`task_registry.py:240`）**正好撞在边界上**——
缓存每次都在任务触发时「刚好过期」，于是每个周期都真实登录一次。
调长 TTL 前**必须先实测 eFlow 服务端会话的真实有效期**，测法见
`TMP/_probe_eflow_session_lifetime.py`；TTL 设为超过实测值会长期使用死会话。

### 登出能力（2026-10-04 新增，默认关闭）

**修正前的缺口：全仓库没有任何 eFlow 登出调用。** `auth_manager.invalidate_cache()`
（`auth_manager.py:284`）**只删本地缓存文件、不发网络请求**，服务端会话照旧挂着。
于是每次 TTL 过期后的"重新登录"都在上游**新增一个永不释放的会话**，旧会话只能等
自己超时 —— 高频任务叠加短 TTL，会在上游堆积大量僵尸会话，最终把登录接口拖垮。

新增 `auth_manager.logout()`（`auth_manager.py:319`）与
`eflow_api_client.logout()`（`eflow_api_client.py:511-540`）：

| 行为 | 说明 |
| --- | --- |
| 默认状态 | **未启用**。需置 `AUTH_LOGOUT_ENABLED=1` 才真正发请求 |
| 路径来源 | `AUTH_LOGOUT_PATH`，默认 `/web/res/web-common/loginOut?SSOAction=SSOLogout` |
| 失败处理 | 任何异常都吞掉并记 warning —— **登出失败不得阻断任务**（会话交给上游超时回收） |
| 幂等 | 可重复调用；无论成败都清空本进程 `_session_cookie`，使下次必定重新取会话 |

> ⚠️ **默认路径尚未实测确认。** 它来自
> `_myapp_trash_20260918/root_tmp/_tmp_menu.json`（一份真实的 ZTE 门户菜单 dump）
> 中"注销"菜单项的 URL，属于**强线索但非实测结论**。
> 确认方法：浏览器登录 eFlow → F12 Network → 点"注销" → 读真实请求的 URL 与方法。
> 辅助探针：`TMP/_probe_eflow_logout.py`（默认 dry-run，`--execute` 才发请求）。
> **在确认之前不要打开 `AUTH_LOGOUT_ENABLED`。**

## TLS

| 方向 | 状态 | 出处 |
| --- | --- | --- |
| 对外（用户 → 后端） | **不启用**，uvicorn 无 ssl 参数，仓库内无证书/密钥文件 | `backend_watchdog.py:147-150` |
| 对上游网管/eFlow | **默认关闭证书校验**（`UME_*`/`EFLOW_*`/`TLS_VERIFY` 系列开关），`request_verify=False` | `backend/security_tls.py:29-39`，:18-22 注释自述 MITM 风险 |
| 实时代理 | 只绑 `127.0.0.1`（8787/8790），不对局域网暴露 | `realtime_proxy_vmax.py:396` |

对外如需 HTTPS，请在 nginx 层终结；关闭上游证书校验是"能连通"优先的取舍，若网络路径不完全可信，应显式打开 `TLS_VERIFY` 并部署企业根证书。

## 仓库内的敏感文件（已验证未被 git 跟踪）

| 文件 | 内容 | 状态 |
| --- | --- | --- |
| `CREDENTIALS_LOCAL_REFERENCE.txt` | 各系统账号/口令/Token 的集中速查 | **禁止外发、禁止提交** |
| `backend/.env` | `DATABASE_URL` 等真实连接串 | 同上 |
| `db/app.db` | 含 `credentials` 表明文口令 | 同上（≈954 MB，含业务数据） |
| `backend/services/auth_cache/*.json` | 有效会话 cookie | 同上 |
| `log/*` | 部分报错原文含账号 | 打包外发前先扫一遍 |

注意 `my_app/.gitignore` 的全部内容是一行 `*`（venv 自动生成的残留，非有意设计）。它**恰好**挡住了上面这些文件——已验证三者都未被 git 跟踪。但这是意外效果：`git add -f` 可以绕过，且它同样挡住了所有应该提交的源码，跟踪状态完全依赖更早的强制添加。**不要把它当成安全边界。**

## 手册里禁止出现的内容（字段名级清单）

写文档、贴日志、截图时，以下一律不得出现具体值：

- `DATABASE_URL` 连接串（含用户/口令/IP）
- 各凭据分组 `user`/`secret` 的值，以及 `default_user` 之类带默认值的字段
- 环境变量对应值：`RAN_UME_USER/PASS`、`EFLOW_USER/PASS`、`MW_UME_USER/PASSWORD`、`UME_IN_USER/PASSWORD`、`BATT_USERNAME/PASSWORD`、`CM_USERNAME/PASSWORD`、`FMS_PORTAL_USER/PASS`、`VMAX_CXO_USER/PASS`、`VMAX_GBASE_USER/PASS`、`RAIS_USER/PASS`、`FTP_USER/FTP_PASS`、`EMS_USER/EMS_PASS`、SMTP 授权码、`TWILIO_ACCOUNT_SID/AUTH_TOKEN/PHONE_NUMBER`、`GEMINI_API_KEY`、`MY_APP_API_TOKEN`、`PHONE/SMS_SERVICE_PROVIDER`
- 内网 IP/主机名与端口组合、邮箱服务域名、微信 session key 与 OpenClaw 会话标识
- `backend/services/cn_ems/ems_config.json` 的 `username`/`password`

**分组 key、字段名、环境变量键名可以写。**

## 如果要提升安全性（按投入产出排序）

1. 把 `require_protected` 从"回环放行"改为解析真实客户端 IP（`X-Forwarded-For` + 可信代理白名单），并覆盖到**所有**写接口与导出接口。
2. `credential_store` 接进 `database.py` 走同一后端，并对 `secret` 列做可逆加密（密钥放环境变量）。
3. 给 `:7038` 加防火墙白名单，只允许 nginx 所在主机访问。
4. 加一层最简单的共享口令登录（够用且不改数据模型），换掉"裸奔"现状。
5. 打开上游 `TLS_VERIFY`。

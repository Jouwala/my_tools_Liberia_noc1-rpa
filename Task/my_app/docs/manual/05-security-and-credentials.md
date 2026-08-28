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

- **12 个分组 key**：`zte_ume`、`vmax_cxo`、`ipran_ume`、`ccn_ume`、`eflow`、`fms_portal`、`fw_kpi`、`mw_ume`、`sftp_sp`、`mail_126`、`owa_mail`、`weixin`（`backend/services/credential_store.py:38-251`）。
- 每组元数据字段：`key`、`name`、`usage`、`user_label`、`secret_label`、`env_user`、`env_secret`、`testable`。字段名可写进文档，**值不可以**。
- 读取优先级：**环境变量 > 数据库 > 空**（`env_user`/`env_secret` 指定对应变量名，:328-329）；内存缓存 TTL 默认 30 秒（`CREDENTIAL_CACHE_TTL`，:30）。
- 列表接口返回**掩码**（:397），"显示明文"走 `GET /api/credentials/{key}/reveal`，"测试连接"走 `POST /api/credentials/test`。

> 🔴 **已验证风险 3：凭据明文存储。** `set_credential`（:348-366）把用户名口令**明文**写入 `db/app.db` 的 `credentials` 表，无加密、无哈希。
> 🔴 **已验证风险 4：凭据不随主库走。** `credential_store._get_conn`（:263-266）用 `sqlite3` 直连本地 `app.db`，绕过 `MY_APP_DB_MODE`。当前 PG 模式下，业务数据在远程 PG、凭据在本机 `app.db`。备份/迁移只搬一边必然丢东西。

## 上游站点会话

`backend/services/auth_manager.py:81` 把登录后的站点会话 cookie 缓存在 `backend/services/auth_cache/`（RSA 加密登录流程 + `forgery_token`，带 TTL）。

含义：`auth_cache/` 目录里的内容等同于**有效登录态**，与口令同等对待——不外发、不入 git、不放进截图。

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
- 环境变量对应值：`RAN_UME_USER/PASS`、`EFLOW_USER/PASS`、`MW_UME_USER/PASSWORD`、`FMS_PORTAL_USER/PASS`、`VMAX_CXO_USER/PASS`、`FTP_USER/FTP_PASS`、`EMS_USER/EMS_PASS`、`BATT_HOST/USERNAME/PASSWORD`、SMTP 授权码、`TWILIO_ACCOUNT_SID/AUTH_TOKEN/PHONE_NUMBER`、`GEMINI_API_KEY`、`MY_APP_API_TOKEN`、`PHONE/SMS_SERVICE_PROVIDER`
- 内网 IP/主机名与端口组合、邮箱服务域名、微信 session key 与 OpenClaw 会话标识
- `backend/services/cn_ems/ems_config.json` 的 `username`/`password`

**分组 key、字段名、环境变量键名可以写。**

## 如果要提升安全性（按投入产出排序）

1. 把 `require_protected` 从"回环放行"改为解析真实客户端 IP（`X-Forwarded-For` + 可信代理白名单），并覆盖到**所有**写接口与导出接口。
2. `credential_store` 接进 `database.py` 走同一后端，并对 `secret` 列做可逆加密（密钥放环境变量）。
3. 给 `:7038` 加防火墙白名单，只允许 nginx 所在主机访问。
4. 加一层最简单的共享口令登录（够用且不改数据模型），换掉"裸奔"现状。
5. 打开上游 `TLS_VERIFY`。

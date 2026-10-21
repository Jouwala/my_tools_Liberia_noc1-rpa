# credential_tester.py - 凭据「连接测试」分发实现

## 为什么有这个模块

设置页「系统设置 → 凭据」原先只有 ZTE UME 系 / eFlow / RAIS 等 11 组带
「测试连接」按钮，其余 9 组（VMAX CXO、GBase 数仓、Greenplum 主节点、
UME 服务器网管、FW UMC、SFTP、126 邮箱、OWA 邮箱、微信推送）改完密码只能
"保存后等任务跑一次才知道对不对"。

2026-10-21 把这 9 组全部接上各自系统的真实登录/连通性检查，
并修正 `gp_ran_control` 的假阴性（它 `testable=True` 但无 `test_kind`，
被路由当成 ZTE 网管去打 22 端口的 OAuth2，按钮永远报"登录失败"）。

## 分发方式

`credential_store.CREDENTIAL_GROUPS` 每条记录带 `test_kind`；
`routers/credentials.py:157` 先看 kind：

- `zte_oauth2` / `rais` → 留在路由里走 `auth_manager`（带本地熔断冷却与终态错误判定）；
- 其余 → `credential_tester.run_test(key, group, user, pwd, en)`。

本模块用 `TESTERS` 字典（kind → 函数）登记，函数在定义处用 `@_register("kind")` 注册。

## 各 kind 的实现要点（含出处）

| kind | 函数 | 关键实现 |
| --- | --- | --- |
| `vmax_portal` | `_test_vmax_cxo` | 复刻 `tools/realtime_proxy_vmax.py:188` 的 `vmax_login()`：取 `publicKey` → `cryptography` PKCS#1 v1.5 加密 → `POST /web/res/web-common/login`，判 `result==1`；**测完调 logout**（门户按用户限并发）。网页登录有验证码，但这条接口链路不需要 |
| `gbase` | `_test_vmax_gbase` | 复用 `vmax_gbase_client.VmaxGbaseClient.healthy()`（内部 connect + `SELECT VERSION()`，只读） |
| `ssh` | `_test_gp_ran_control` | paramiko 口令登录 control1，连接参数来自 `gp_ran_client.resolve_endpoints()` |
| `ssh_via_control` | `_test_gp_ran_master` | `GpRanClient().connect()` 两跳；测这一组时 control1 凭据也必须有效 |
| `ume_keystone` | `_test_ume_alarm` | `ume_alarm_client.login(force_refresh=True)` —— 必须跳过缓存，否则拿旧会话说"通过" |
| `umc_portal` | `_test_fw_kpi` | `fw_kpi_services.Session()` + `login()`；依赖本机 Node 跑服务器原版 `e.js` |
| `sftp` | `_test_sftp_sp` | paramiko Transport + `auth_password` + 开 SFTP 通道 + `normalize(".")`，不下载文件 |
| `smtp` | `_test_mail_126` | `smtplib.SMTP_SSL` + AUTH 握手，**不发信**（避免污染收件箱） |
| `ews` | `_test_owa_mail` | `mailbox_cleanup.get_account()`（与 owa_mail_report 同源配置）+ 取收件箱总数探活 |
| `weixin_push` | `_test_weixin` | ⚠ Server酱 / PushPlus **都没有「只验 Token 不发消息」的接口**，测试会真的推送一条 |

## 约定（改动前请先读）

1. 每个函数自带超时（`DEFAULT_TIMEOUT=20`），**不许裸等** —— 设置页在 Web 进程里同步等结果。
2. 缺依赖（paramiko / pymysql / exchangelib / cryptography）**明确报"缺少依赖"**，
   不许静默降级成"看起来通过"的假测试。
3. 返回值里**不得出现口令**，只回账号名、主机端口、服务端版本这类非敏感信息。
4. `run_test()` 有兜底 `except`：任何未捕获异常都转成 `status=fail`，不能让设置页 500。
5. 新增凭据组时，若 kind 不在 `TESTERS` 里，`run_test()` 会返回 `unsupported`
   （界面提示"暂不支持自动测试"），不会报错。

## 环境注意

后端实际跑在 `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`，
**不是**仓库内的 `Scripts\python.exe`（后者没有 fastapi/sqlalchemy）。
报"缺少依赖"时要用前者装：

```
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m pip install -r requirements.txt
```

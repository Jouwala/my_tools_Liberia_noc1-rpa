# credentials.py - 凭据管理 API 路由

提供"设置"页面所需的凭据管理接口，存储实现见 `backend/services/credential_store.py`。

## 接口
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/credentials | 列出全部凭据组（密码掩码 + 来源标记 db/default/env） |
| PUT | /api/credentials | 按 key 更新用户名/密码，写 db/app.db credentials 表 |
| POST | /api/credentials/test | 连接测试（2026-10-21 起**全部 20 组都支持**） |

## 连接测试的分发

`POST /test` 按 `credential_store` 里该组的 `test_kind` 分发：

- `zte_oauth2` / `rais` → 本文件内的 `auth_manager` 路径（ZTE OAuth2 RSA 登录 /
  RAIS 直接鉴权），带本地熔断冷却提示（`get_lock_state`）与终态错误判定
  （`_is_terminal_login_error`）；
- 其余 kind → `backend/services/credential_tester.py::run_test()`
  （vmax_portal / gbase / ssh / ssh_via_control / ume_keystone / umc_portal /
  sftp / smtp / ews / weixin_push）。

分发判断在 `credentials.py:157`，必须放在 auth_manager 路径**之前** ——
否则 SSH / 数据库 / 邮件这类组会被当成 ZTE 网管去打 OAuth2
（`gp_ran_control` 在 2026-10-21 前就是这个假阴性：按钮一直报"登录失败"）。

各组实际做什么见 `backend/services/credential_store.md` 的凭据组表。

## 请求体示例
PUT:
```json
{"key": "zte_ume", "username": "NOC", "secret": "新密码"}
```
POST /test:
```json
{"key": "zte_ume"}
```

## 测试地址从哪来（2026-10-22）

**测试连接测的主机，与任务实际连接的主机是同一个来源。**

本文件与 `credential_tester.py` 都不再直接用 `CREDENTIAL_GROUPS[*].test_host`，
而是统一走 `credential_store.resolve_endpoint(key)`：

优先级 **环境变量 > 任务配置文件（页面可编辑） > 内置默认（原 test_host/test_port）**

| 组 | 地址来源 |
|---|---|
| `zte_ume` | `ran_ume_config.json`（另与 main_kpi / network_kpi / pl 交叉核对） |
| `ipran_ume` / `ccn_ume` / `mw_ume` / `ume_in` / `eflow` / `fw_kpi` / `cm_data` | 对应 `<task>_config.json` |
| `ume_alarm` | `UME_ALARM_HOST` / `UME_ALARM_PORT` 环境变量（与 `ume_alarm_client` 同名） |
| `sftp_sp` | `sp_sftp_config.json`（`credential_tester._sftp_host_port()`） |
| 其余（rais / fms_portal / battery_ume / vmax / gp_ran / 邮件 / 微信） | 代码常量（地址未外置，见 `credential_store._CONFIG_REF` 注释） |

为什么改：`test_host` 是硬编码，而任务配置在 JSON 里。两边各维护一份时，
改完配置点「测试连接」仍在测旧地址，结论不可信；`ume_keystone` / `umc_portal`
更严重 —— 它们实际连的是客户端模块的 `HOST`，消息里却打印组内死值，会显示
一台自己没连过的主机。同一个死值还被「改凭据后清会话缓存」
（`_invalidate_sessions_for`）和「熔断状态查询」引用，偏差会扩散到三条链路。

返回值里新增 `endpoint` 字段，便于页面/排障直接看到这次到底测了哪台机：

```json
{"status":"ok","key":"zte_ume",
 "endpoint":{"host":"10.100.28.27","port":28001,
             "source":"file:ran_ume_config.json",
             "default":"10.100.28.27:28001","conflicts":[]}}
```

`source` 是 `static` 表示配置文件还没生成（页面没保存过），用的内置默认。
`conflicts` 非空表示同一台设备的多个任务配置指向了不同地址，需要核对。

解析是**每次调用现读文件、不做模块级缓存**，所以页面保存配置后立刻生效，
不需要重启 7038，也不需要重启 worker。守卫用例见
`tests/test_credential_endpoint.py`。

## 依赖
无新增第三方依赖（fastapi / pydantic 已在项目 requirements 中）。

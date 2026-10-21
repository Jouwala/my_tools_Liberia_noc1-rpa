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

## 依赖
无新增第三方依赖（fastapi / pydantic 已在项目 requirements 中）。

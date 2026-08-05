# credentials.py - 凭据管理 API 路由

提供"设置"页面所需的凭据管理接口，存储实现见 `backend/services/credential_store.py`。

## 接口
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/credentials | 列出全部凭据组（密码掩码 + 来源标记 db/default/env） |
| PUT | /api/credentials | 按 key 更新用户名/密码，写 db/app.db credentials 表 |
| POST | /api/credentials/test | 连接测试（zte_ume/ipran_ume/ccn_ume/eflow 走真实 OAuth2 登录） |

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

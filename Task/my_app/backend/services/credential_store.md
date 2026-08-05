# credential_store.py - 集中凭据存储模块

## 功能
将 my_app 各服务（ZTE UME / iPRAN / CCN / eFlow / FW / SFTP / 126 邮箱 / 微信通知）
的用户名密码集中存入 `db/app.db` 的 `credentials` 表，前端"设置"页面维护，
服务运行时动态读取。密码定期更改时只需在页面上更新，无需改代码。

## 表结构
```sql
CREATE TABLE credentials (
    key        TEXT PRIMARY KEY,  -- 凭据组 key
    username   TEXT,
    secret     TEXT,
    updated_at TEXT               -- 最近更新时间
);
```

## 凭据组 key
| key | 系统 |
|---|---|
| zte_ume | ZTE UME 网管 (RAN KPI / MS SLA) |
| ipran_ume | iPRAN UME 网管 |
| ccn_ume | CCN UME 网管 |
| eflow | eFlow 告警系统 |
| fw_kpi | FW 整机吞吐 KPI (UMC) |
| sftp_sp | SFTP 备件报表服务器 |
| mail_126 | 126 邮箱（SMTP 授权码） |
| weixin | 微信/即时消息通知（Server酱/PushPlus Token） |

## 读取优先级
环境变量 > 数据库(credentials 表) > 代码默认值

## 缓存
进程内缓存 30 秒（环境变量 `CREDENTIAL_CACHE_TTL` 可调），
页面更新密码后最迟 30 秒生效，无需重启服务。

## 用法
```python
from backend.services.credential_store import get_credential
user, pwd = get_credential("zte_ume", "NOC", "Zte@2025!")
```

## 相关接口
- `GET /api/credentials` 列出全部凭据组（密码掩码）
- `PUT /api/credentials` 更新凭据
- `POST /api/credentials/test` 连接测试（仅 UME 系/eFlow 支持）

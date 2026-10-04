# credential_store.py - 集中凭据存储模块

## 功能
将 my_app 各服务（ZTE UME / Battery UME / iPRAN / CCN / eFlow / FW / SFTP /
126 邮箱 / OWA / 微信通知 / VMAX / RAIS / FMS / CM 数据同步）的用户名密码集中存入
`db/app.db` 的 `credentials` 表，前端"设置"页面维护，服务运行时动态读取。
密码定期更改时只需在页面上更新，无需改代码。

## 表结构
```sql
CREATE TABLE credentials (
    key        TEXT PRIMARY KEY,  -- 凭据组 key
    username   TEXT,
    secret     TEXT,
    updated_at TEXT               -- 最近更新时间
);
```

## 凭据组 key（共 17 组）
| key | 系统 | 可自动测试 |
|---|---|---|
| zte_ume | ZTE UME 网管 (RAN KPI / MS SLA) | ✅ |
| vmax_cxo | VMAX CXO 经营看板门户 | — |
| vmax_gbase | VMAX 数仓 GBase 8a | — |
| ipran_ume | iPRAN UME 网管 | ✅ |
| ccn_ume | CCN UME 网管 | ✅ |
| eflow | eFlow 告警系统 | ✅ |
| rais | RAIS 统一权限平台 | ✅ |
| fms_portal | FMS 实时代理门户 | ✅ |
| fw_kpi | FW 整机吞吐 KPI (UMC) | — |
| mw_ume | MW UME 微波网管 | ✅ |
| ume_in | UME 客户业务 KPI 门户 | ✅ |
| **battery_ume** | **Battery UME 电池网管 (r32.uedm.batt)** | ✅ |
| **cm_data** | **RAN CM 小区数据同步** | ✅ |
| sftp_sp | SFTP 备件报表服务器 | — |
| mail_126 | 126 邮箱（SMTP 授权码） | — |
| owa_mail | Exchange/OWA 邮箱（域账号） | — |
| weixin | 微信/即时消息通知（Server酱/PushPlus Token） | — |

> 新增 `battery_ume` / `cm_data`（2026-09-23）：这两组此前**不在注册表内**，
> 采集模块各自硬编码凭据、绕开本模块，导致设置页面上根本没有对应卡片、无法改密。
> 现已补入注册表并改造调用方（见下节）。

## 读取优先级
环境变量 > 数据库(credentials 表) > 代码默认值

## 缓存
进程内缓存 30 秒（环境变量 `CREDENTIAL_CACHE_TTL` 可调），
页面更新密码后最迟 30 秒生效，无需重启服务。

## 用法
```python
from backend.services.credential_store import get_credential
user, pwd = get_credential("zte_ume")   # 口令不写在代码/文档里
```

## 调用方约定（重要）
各采集模块**不要**直接读自己的模块级常量，应提供 `_runtime_credentials()`
统一走本模块，例如：

```python
def _runtime_credentials():
    """运行时凭据：环境变量 > credential_store > 模块默认值。"""
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        return USERNAME, PASSWORD
    return get_credential("cm_data", USERNAME, PASSWORD)
```

已按此约定的模块：`ipran_ume_kpi_service`、`ccn_ume_kpi_service`、`fw_kpi_services`、
`mw_ume_kpi_service`、`ume_in_kpi_service`、`ms_sla_sync`、`ran_ume_*`、
`get_sp_table`、`email_notifier`、`report/mail_126`、`site_outage_service`、
`eflow_api_client`、`vmax_gbase_client`、`vmax_report_client`、
**`cm_data_export`**、**`battary_kpi_fetch_socket`**（后两个为 2026-09-23 补入）。

## 相关接口
- `GET /api/credentials` 列出全部凭据组（密码掩码）
- `PUT /api/credentials` 更新凭据
- `GET /api/credentials/{key}/reveal` 显示明文（仅在设置页面用）
- `POST /api/credentials/test` 连接测试（`testable: true` 的组走真实登录）

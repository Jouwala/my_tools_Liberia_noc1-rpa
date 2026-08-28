# MS SLA 看板数据写入服务说明

## 功能

`ms_sla_dashboard.py` 负责把 **MS Contract KPIs / MS WOs SLA** 两份日报的底层数据
（KPI List 解析结果 + `lbr_ms_sla_kpi.sqlite3` 的 Network/Per-Site KPI）全量写入
独立看板库 `data/ms_sla/ms_sla_dashboard.sqlite3`，供看板 API 读取展示。

邮件发送功能（`kpi_email_report.py` / `owa_mail_report.py`）与本模块无关，不受影响。

## 调用位置

`backend/services/ms_sla_report.py` 的 `run_contract_kpis_report()`（任务 `ms_sla_full`，
每 6 小时）在报表导出上传完成后调用 `write_dashboard_data(datasets)`。

写库失败仅记入任务结果（`dashboard_error` 字段），不影响 Excel 更新 / 邮件发送主流程。

## 数据来源与口径

| 数据 | 来源 | dataset 值 |
| --- | --- | --- |
| NUR 日度 | KPI List NUR Daily（Global/2G/3G/4G） | `nur_daily` |
| NUR 月度 | KPI List NUR Monthly | `nur_monthly` |
| SLA 日度 | KPI List SLA Daily（TTR/TTR_P1..P4） | `sla_daily` |
| SLA 月度 | KPI List SLA Monthly | `sla_monthly` |
| Network KPI 日/月 | `lbr_ms_sla_kpi.sqlite3` 的 `*_NW` 表（2G_CSSR 等 7 项） | `network_daily` / `network_monthly` |
| Per-Site 占比 日/月 | `lbr_ms_sla_kpi.sqlite3` 的 `*_SITE` 表（PS_NUR_2G 等 11 项） | `persite_daily` / `persite_monthly` |
| WO SLA 日/月详情 | KPI List SLA Daily/Monthly 的 Total/Within SLA/Achieve 三列 | 独立表 `ms_sla_wo` |

NUR 原始值 = 比率（0~1），前端展示 ×100000（与 NurDashboard 口径一致）。

## 表结构

- `ms_sla_kpi(period, dataset, metric, value)`：标量指标，主键 `(period, dataset, metric)`
- `ms_sla_wo(period, metric, total, within_sla, achieve)`：WO SLA 详情，月份行 period 为 `YYYY-MM`
- `ms_sla_meta(key, value)`：`last_sync_time` / `kpi_list_mtime` 等数据新鲜度

## 写入策略

全量 upsert（`INSERT OR REPLACE` / PG `ON CONFLICT DO UPDATE`，经
`dialect_helpers.upsert` 双模兼容）：每次运行重写全部期间，天然历史回填与自愈。

## 运行

独立调试（读取现有 KPI List 并写库）：

```powershell
cd d:\01_RPA\Task\my_app
python -m backend.services.ms_sla_dashboard
```

## 依赖

无新增第三方依赖，复用现有 openpyxl / sqlite3。详见 `requirements_ms_sla_dashboard.txt`。

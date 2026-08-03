# Packet Loss 丢包数据同步与报告服务

## 概述

从 RAN UME 网管系统（https://10.100.28.27:28001）自动采集 SDR 与 ITRAN 两类丢包（Packet Loss Rate）PM 数据，全程内存处理（不落盘导出文件）直接写入本地 SQLite 数据库 `lte_pl.sqlite3`，并按模板 `Packet_Loss_Status_Output Automation.xlsx` 格式生成带公式的丢包报告（顶部含日期）；前端提供丢包看板（统计卡片+图表+地图）展示。

## 任务信息

| 项目 | 值 |
|------|-----|
| task_id | `packet_loss_sync` |
| 分类 | `packet_loss` |
| 默认调度 | 每天 06:30（`30 6 * * *`），支持手动触发 |
| 服务文件 | `backend/services/packet_loss_service.py` |
| 路由文件 | `backend/routers/packet_loss_dashboard.py` |
| 数据目录 | `data/packet_lost/` |
| 数据库 | `data/packet_lost/lte_pl.sqlite3` |
| 报告文件 | `data/packet_lost/Packet_Loss_Status_Report.xlsx` |
| 站点信息来源 | `data/eflow/eflow.sqlite3` 的 `site` 表 |

## 执行流程

```
登录 RAN UME → 并行提交 2 个 PM 历史查询（SDR / ITRAN，时间范围最近7天）
→ 轮询查询完成 → 导出 Excel 字节流（不落盘 exports 目录，内存直接处理）
→ 列裁剪/重命名（统一 dstIp / srcIp）→ 丢包率 ×100 转百分比数值（模板 Step 3 规则）
→ 合并两个 DataFrame → 写入 lte_pl.sqlite3（upsert 去重）
→ 站点维度聚合（站点×小时 sum）→ 关联 eflow site 表补全站点信息
→ 按模板格式生成带公式 Excel 报告（原子写入，第 1 行为日期）
→ 清理超期数据（默认保留 35 天）
```

## 查询配置

| 配置 | templateid | motid | nfctid | grouplayer |
|------|-----------|-------|--------|------------|
| Packet Loss Rate_SDR_IPPD | 1638004470045 | sdrmgr.PlatIPPD | SDR | `me,sdrmgr.SrcIP,sdrmgr.DesIP` |
| Packet Loss Rate_ITRAN_IPPD | 1638004470043 | IPPD | ITBBU | `me,TransportNetwork,IPPD` |

### 导出命名标识（仅内存，不落盘）

`templatename_grouplayer映射_gr映射`，下划线连接，仅作为内存数据标识写入日志与任务结果，不再保存文件到 exports 目录。

- grouplayer 映射：`me,WV4.IubLink`/`me,gv4.BTSSiteManager`/`me,eNodeBFunction`/`me,TransportNetwork,IPPD`/`me,sdrmgr.SrcIP,sdrmgr.DesIP` → Sites；`me,gv4.BTSSiteManager,gv4.BTS.cell`/`me,eNodeBFunction,EUtranCellFDD`/`me,WV4.IubLink,WV4.UtranCell` → Cells；`me,fservice`/`me` → NE；`all` 且 groupbygroup=false → NW，否则 Group
- gr 映射：2592000→1Month、86400→1Day、3600→1Hour

## 数据合并规则

合并后统一保留 10 列：`Begin Time;End Time;Granularity;SubnetWork ID;SubnetWork Name;ManagedElement ID;Managed Element;dstIp;srcIp;Packet Loss Rate(%)`。SDR 导出中 `Destination IP ID`→`dstIp`、`Source IP ID`→`srcIp`。

按模板 Step 3 规则，UME 返回的丢包率为小数，入库前 ×100 转为百分比数值（pl_meta 中 `value_scale=percent` 标记，历史数据首次运行时自动迁移）。

## 数据库结构（lte_pl.sqlite3）

| 表 | 说明 |
|------|------|
| packet_loss_data | 明细数据，UNIQUE(Begin Time, ManagedElement ID, srcIp, dstIp)，ON CONFLICT DO UPDATE |
| site_pl_summary | 站点汇总：站点信息 + LastDayMaxPL + AffectedHours + Status |
| pl_meta | 同步元数据（最近同步时间、行数等） |

## 报告结构（Packet_Loss_Status_Report.xlsx，按模板 Packet_Loss_Status_Output Automation.xlsx）

- **第 1 行**：日期（报告日期 + 数据范围）
- **Packet Loss Report**（第 2 行表头，第 3 行起数据）：
  - A~L 元数据列：Cluster/County/Locality/Site Code/Site_Name/Longitude/Latitude/Vendor/Media(TRM Type)/BB MW/Fiber Site1 code/Equipment BB1/Row Labels
  - 小时粒度丢包矩阵（168 列 = 7 天 × 24 小时，数值格式 0.00）
  - 公式列：`(Last 1 day Max PL)`=MAX(最近24小时)、`STATUS`=IF(SUM(小时块)=0,"OK","NOK")、`FINAL_STATUS`=IF+LOOKUP 五级分类
  - GC~GE：MW - IPRAN Link Status / Main Category / Expansion Planned?（预留手工填写）
  - 末尾 24 列（表头 0~23）：同一小时最近 3 天均 >0.5 计 1，供 STATUS 公式引用
- **Summary**：PL Status/Count of Sites(COUNTIF)/Link Congested/Link Issue/Power issue onsite/Up grade to IPRAN/Percentage of Sites
- **Database**：站点主数据（ME ID/Managed Element/County/Cluster/Longitude/Latitude）
- 丢包等级：Critical[>5] / Major[1-5] / Minor[0.5-1] / Warning[0.1-0.5] / No Packet loss[<0.1]

## 站点匹配规则

Managed Element 结构为 `站点名字(ID)`（如 `Aureus Mining(4255)`）：先用名字（去括号、转小写）匹配 eflow site 表 Site Name，失败再用括号内 ID 匹配 Site ID。Media 列取 site 表 TRM Type，Vendor 取 site 表 Vendor（eflow 中绝大多数为空）。

## 看板 API（prefix `/api/packet-loss-dashboard`，60s 缓存）

| 接口 | 说明 |
|------|------|
| GET /overview | 状态统计、饼图、Top 站点、区域分布、每日趋势 |
| GET /map-sites?include_ok=false | 地图站点（经纬度+状态） |
| GET /drilldown?status=&search=&limit=500 | 下钻明细 |

前端页面：`frontend/src/pages/PacketLossDashboard.tsx`（菜单「丢包看板 / Packet Loss」）。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| PL_DAYS_BACK | 7 | 查询回溯天数 |
| PL_RETENTION_DAYS | 35 | 明细数据保留天数 |

## 依赖

- pandas / openpyxl（数据处理与报告生成）
- 复用 `ran_ume_service.py` 的登录 / TLS HTTP / xlsx 解析基础设施（无新增第三方依赖）

## 自包含说明

本服务完全自包含于 my_app 项目内，数据与数据库均位于 `data/packet_lost/`，站点信息来自 `data/eflow/eflow.sqlite3`，无外部目录引用。

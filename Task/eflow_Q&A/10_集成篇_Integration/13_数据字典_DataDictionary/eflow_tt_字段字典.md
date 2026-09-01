---
标题: eflow_tt 字段字典（TT 故障工单）
分类: 10_集成篇_Integration/13_数据字典_DataDictionary
标签: [数据字典, eflow_tt]
状态: 已验证
适用对象: 开发
最后更新: 2026-09-01
作者: tools/gen_datadict.py
来源: 数据库读取
---

# eflow_tt 字段字典（TT 故障工单）

> ⚠️ 本文件由 `tools/gen_datadict.py` **自动生成**。
> **列名 / 类型 / 非空数 / 取值分布 = 数据库客观实际**，可信。
> **「业务含义」列是空的** —— 脚本不知道每个字段在业务上是什么意思，**需要人工补充**。
> 补充后请把 front-matter 的 `作者` 改成你，`来源` 改成 `数据库读取 + 人工补充`。

## 表概况

- 表名：`eflow_tt`（TT 故障工单）
- 行数：**28,455**
- 列数：**161**
- 数据来源：`D:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3`
- 生成时间：2026-09-01

> 🔒 **脱敏说明**：本表含 24 个疑似个人信息列，其示例值已脱敏、且不输出取值分布，避免泄露同事隐私。
>
> 涉及列：`Project Name`, `Template Name`, `Creator`, `Creator Contact Info`, `Sub Alarm Name`, `Sub Alarm NE Name`, `Appending Alarm Name`, `Appending Alarm NE Name`, `NE Name`, `Asset Name`, `Current Handler`, `Description`, `Alarm Description`, `Root Cause Description`, `Troubleshooting Personnel`, `process_description`, `mobile_generator_id`, `mobile_generator_model`, `mobile_generator_manufacturer`, `spare_name`…

## 字段清单

按填充率从高到低排序（空列排在最后）。

| # | 字段名 | 类型 | 非空 | 填充率 | 去重值 | 示例值 | 业务含义（待人工补） |
|---|--------|------|------|--------|--------|--------|----------------------|
| 1 | `2G Down Site Count` | | 28,455 | 100% | 32 | 0 | |
| 2 | `3G Down Site Count` | | 28,455 | 100% | 30 | 0 | |
| 3 | `4G Down Site Count` | | 28,455 | 100% | 38 | 0 | |
| 4 | `5G Down Site Count` | | 28,455 | 100% | 1 | 0 | |
| 5 | `_sync_source` | | 28,455 | 100% | 1 | eflow_api | |
| 6 | `_sync_time` | | 28,455 | 100% | 2 | 2026-08-07T01:07:45.7005… | |
| 7 | `Asset ID` | | 28,455 | 100% | 777 | 3045 / 3060 / 3067 | |
| 8 | `Asset Name` | | 28,455 | 100% | 768 | 🔒 已脱敏 | |
| 9 | `Create Detail` | | 28,455 | 100% | 27,899 | Operation:Create.  Opera… / Operation:Create.  Opera… / Operation:Create.  Opera… | |
| 10 | `Created Time` | | 28,455 | 100% | 27,901 | 2026-01-28 03:28:07 / 2026-01-28 13:49:12 / 2026-01-29 08:10:36 | |
| 11 | `Creator` | | 28,455 | 100% | 14 | 🔒 已脱敏 | |
| 12 | `Description` | | 28,455 | 100% | 7,293 | 🔒 已脱敏 | |
| 13 | `Down Site Count` | | 28,455 | 100% | 47 | 0 | |
| 14 | `Fault Duration Time` | | 28,455 | 100% | 2,278 | 0d3h38m / 0d0h15m / 0d1h13m | |
| 15 | `Fault Resolved` | | 28,455 | 100% | 2 | Yes | |
| 16 | `Last Modified Time` | | 28,455 | 100% | 18,198 | 2026-02-02 15:07:19 / 2026-02-02 15:17:19 / 2026-02-10 09:37:26 | |
| 17 | `Network Type` | | 28,455 | 100% | 12 | RAN | |
| 18 | `operation_type` | | 28,455 | 100% | 11 | Closed / Closed(WO Confirming) / FOProcess | |
| 19 | `Organization ID` | | 28,455 | 100% | 1 | ZTE | |
| 20 | `process_instance_id` | | 28,455 | 100% | 28,455 | 5d5c3e4c-fbf9-11f0-8edf-… / 209230b9-fc50-11f0-8edf-… / fdfd97d7-fce9-11f0-8edf-… | |
| 21 | `Region ID` | | 28,455 | 100% | 15 | Bong / Nimba / Grand_Bassa | |
| 22 | `Site Class` | | 28,455 | 100% | 4 | P2 | |
| 23 | `Site ID` | | 28,455 | 100% | 777 | 3045 / 3060 / 3067 | |
| 24 | `Source` | | 28,455 | 100% | 2 | UFM | |
| 25 | `Status` | | 28,455 | 100% | 10 | Closed / Waiting for FO Process / Waiting for FO Process(W… | |
| 26 | `Suspended` | | 28,455 | 100% | 2 | No | |
| 27 | `Title` | | 28,455 | 100% | 2,319 | 3045.[Totota]2G CELL DOW… / 3045.[Totota]Complete si… / 3045.[Totota]SITE DOWN D… | |
| 28 | `tt_no` | | 28,455 | 100% | 28,455 | TT202601280027 / TT202601280160 / TT202601290071 | |
| 29 | `VIP Down Site Count` | | 28,455 | 100% | 1 | 0 | |
| 30 | `Occurrence Time` | | 28,452 | 100% | 27,714 | 2026-01-28 03:12:45 / 2026-01-28 13:33:49 / 2026-01-29 07:55:13 | |
| 31 | `Alarm Severity` | | 28,450 | 100% | 4 | Critical | |
| 32 | `Hub Site` | | 28,450 | 100% | 2 | No / Yes | |
| 33 | `Project Name` | | 28,450 | 100% | 2 | 🔒 已脱敏 | |
| 34 | `Region Level1` | | 28,450 | 100% | 15 | Bong / Nimba / Grand Bassa | |
| 35 | `Template Name` | | 28,450 | 100% | 2 | 🔒 已脱敏 | |
| 36 | `Ticket Type` | | 28,450 | 100% | 2 | Trouble Ticket(UFM) | |
| 37 | `VIP Site` | | 28,450 | 100% | 2 | No | |
| 38 | `Specific Problem` | | 28,424 | 100% | 91 | 2G cell down / Complete site down (CSD) / SITE OUTAGE DUE TO POWER… | |
| 39 | `Ticket Severity` | | 28,422 | 100% | 4 | P4 / P2 | |
| 40 | `SLA Expected Finish Time` | | 28,418 | 100% | 27,791 | 2026-01-30 03:12:45 / 2026-01-30 13:33:49 / 2026-01-31 07:55:13 | |
| 41 | `SLA Remaining Duration` | | 28,418 | 100% | 2,920 | 1d20h21m / 1d23h44m / 1d22h46m | |
| 42 | `SLA Status` | | 28,418 | 100% | 3 | Pass | |
| 43 | `SLA Total Duration` | | 28,418 | 100% | 4 | 2d0h0m / 0d8h0m | |
| 44 | `alarm_server_time` | | 28,401 | 100% | 27,545 | 2026-01-28 03:13:07 / 2026-01-28 13:34:11 / 2026-01-29 07:55:35 | |
| 45 | `Alarm Code` | | 28,400 | 100% | 56 | 9981.0 / 9920.0 / 99933.0 | |
| 46 | `Vender` | | 28,400 | 100% | 1 | ZTE | |
| 47 | `moc` | | 28,396 | 100% | 20 | ZTE_RAN_BTS / ZTE_RAN_ENODEB / ZTE_RAN_NODEB | |
| 48 | `NE Name` | | 28,396 | 100% | 20 | 🔒 已脱敏 | |
| 49 | `Alarm ID` | | 28,391 | 100% | 28,391 | 1764163026252.0 / 1764163180306.0 / 1764163365771.0 | |
| 50 | `Alarm Clearing Time` | | 28,374 | 100% | 27,678 | 2026-01-28 06:51:29 / 2026-01-28 13:49:47 / 2026-01-29 09:08:51 | |
| 51 | `Additional Information` | | 28,200 | 99% | 3,186 | Alarm Object:CELL;  Site… / Alarm Object:CELL;  Site… / CSD caused by: 3G,2G | |
| 52 | `Site Information` | | 28,162 | 99% | 4 | REGULAR | |
| 53 | `Alarm Description` | | 28,135 | 99% | 35 | 🔒 已脱敏 | |
| 54 | `Sub Alarm Name` | | 26,781 | 94% | 1,195 | 🔒 已脱敏 | |
| 55 | `Sub Alarm NE Name` | | 26,781 | 94% | 3,094 | 🔒 已脱敏 | |
| 56 | `FO Process Detail` | | 26,560 | 93% | 26,436 | Operation:FOProcess.  Op… / Operation:FOProcess.  Op… / Operation:FOProcess.  Op… | |
| 57 | `Closed Detail` | | 24,252 | 85% | 432 | Operation:Closed.  Opera… / Operation:Closed.  Opera… / Operation:Closed.  Opera… | |
| 58 | `Sub Alarm NE IP` | | 23,578 | 83% | 1,507 | 129.0.1.1 / 10.17.61.2; 129.0.1.1 / 10.17.61.2 | |
| 59 | `Asset Type` | | 22,678 | 80% | 6 | NORMAL | |
| 60 | `Last Process Time` | | 20,172 | 71% | 20,163 | 2026-02-02 15:00:53 / 2026-02-02 15:12:11 / 2026-02-10 09:34:19 | |
| 61 | `Last Processer` | | 20,172 | 71% | 53 | Melvin Gono(FE_FE_119) / oss-101(oss-101) / IPT(IPT) | |
| 62 | `Root Cause` | | 18,693 | 66% | 11 | POWER / Fiber / Planned work | |
| 63 | `Confirm Detail` | | 18,655 | 66% | 18,651 | Operation:Confirm.  Oper… / Operation:Confirm.  Oper… / Operation:Confirm.  Oper… | |
| 64 | `Sub Root Cause` | | 18,433 | 65% | 21 | Power Solar / Power Genset / Power Grid | |
| 65 | `Root Cause Description` | | 17,981 | 63% | 67 | 🔒 已脱敏 | |
| 66 | `FO Accept Detail` | | 17,959 | 63% | 17,632 | Operation:FOAccept.  Ope… / Operation:FOAccept.  Ope… / Operation:FOAccept.  Ope… | |
| 67 | `Last Processer Group` | | 12,438 | 44% | 22 | G:ZTE_FE_FE; / G:3rd_Power; / G:ZTE_NOC_FO; | |
| 68 | `Ticket No.` | | 11,136 | 39% | 11,136 | WO202601280019 / WO202601280125 / WO202601290053 | |
| 69 | `WO No.` | | 11,136 | 39% | 11,136 | WO202601280019 / WO202601280125 / WO202601290053 | |
| 70 | `Third Accept Detail` | | 10,467 | 37% | 10,467 | Operation:ThirdAccept.  … / Operation:ThirdAccept.  … / Operation:ThirdAccept.  … | |
| 71 | `Third Process Detail` | | 9,283 | 33% | 9,283 | Operation:ThirdProcess. … / Operation:ThirdProcess. … / Operation:ThirdProcess. … | |
| 72 | `Current Handler` | | 4,201 | 15% | 22 | 🔒 已脱敏 | |
| 73 | `Site Outage` | | 2,834 | 10% | 2 | No / Yes | |
| 74 | `Whether Impacted Service` | | 2,834 | 10% | 2 | No / Yes | |
| 75 | `Appending Alarm Name` | | 2,370 | 8% | 229 | 🔒 已脱敏 | |
| 76 | `Appending Alarm NE Name` | | 2,370 | 8% | 741 | 🔒 已脱敏 | |
| 77 | `Appending Alarm NE IP` | | 1,767 | 6% | 320 | 129.0.1.1 / 10.16.127.20 / 10.17.244.89 | |
| 78 | `Impacted Service` | | 1,727 | 6% | 9 | 2G,3G / 2G,3G,4G / 2G | |
| 79 | `Down Site List` | | 1,706 | 6% | 770 | 3069,3635 / 4185,4077,4079,3591,4081… / 4777 | |
| 80 | `3G Down Site List` | | 1,301 | 5% | 495 | 3069,3635 / 4185,4077,4079,4081,3649… / 3283 | |
| 81 | `2G Down Site List` | | 1,250 | 4% | 490 | 3069,3635 / 4185,4077,4079,3591,4081… / 4777 | |
| 82 | `Actual Completion Time` | | 633 | 2% | 621 | 2026-01-17 07:16:55 / 2026-01-24 12:46:00 / 2026-01-31 23:28:00 | |
| 83 | `4G Down Site List` | | 612 | 2% | 382 | 4077,5479,4778,4856,4537 / 4075,4285,4330,4286,4420… / 4777 | |
| 84 | `Troubleshooting Personnel` | | 365 | 1% | 19 | 🔒 已脱敏 | |
| 85 | `WO Process Attachment` | | 358 | 1% | 1 | Process Attachments | |
| 86 | `NE IP` | | 317 | 1% | 102 | 129.0.1.1 / 10.17.121.193 / 10.17.35.1 | |
| 87 | `BO Accept Detail` | | 147 | 1% | 147 | Operation:BOAccept.  Ope… / Operation:BOAccept.  Ope… / Operation:BOAccept.  Ope… | |
| 88 | `BO Process Detail` | | 131 | 0% | 131 | Operation:BOProcess.  Op… / Operation:BOProcess.  Op… / Operation:BOProcess.  Op… | |
| 89 | `Alarm Category` | | 18 | 0% | 7 | Site Down / DWDM Fault / Small Cell Down - Cell | |
| 90 | `Alarm Sub Category` | | 11 | 0% | 3 | Site Down / Fiber Break / ZTE | |
| 91 | `Creator Contact Info` | | 10 | 0% | 6 | 🔒 已脱敏 | |
| 92 | `Last Suspend Operator` | | 7 | 0% | 1 | 🔒 已脱敏 | |
| 93 | `Last Suspend Status` | | 7 | 0% | 2 | Resume / Suspend | |
| 94 | `Last Suspend Time` | | 7 | 0% | 7 | 2026-03-01 22:52:41 / 2026-02-25 17:53:52 / 2026-01-28 17:05:18 | |
| 95 | `Suspend Detail` | | 7 | 0% | 7 | Operation: Suspend. Oper… / Operation: Suspend. Oper… / Operation: Suspend. Oper… | |
| 96 | `Last Resume Operator` | | 5 | 0% | 1 | 🔒 已脱敏 | |
| 97 | `Last Resume Time` | | 5 | 0% | 5 | 2026-03-01 22:53:57 / 2026-02-25 17:54:37 / 2026-03-04 20:29:54 | |
| 98 | `Alarm Type` | | 4 | 0% | 3 | Environment Alarm / QoS Alarm / Communication Alarm | |
| 99 | `last_resume_operator_group` | | 1 | 0% | 1 | 🔒 已脱敏 | |
| 100 | `last_suspend_operator_group` | | 1 | 0% | 1 | 🔒 已脱敏 | |
| 101 | `Alarm Reason Type` | | 0 | 0% | 0 | — | |
| 102 | `assignment_suggestions` | | 0 | 0% | 0 | — | |
| 103 | `battery_1_id` | | 0 | 0% | 0 | — | |
| 104 | `battery_1_manufacturer` | | 0 | 0% | 0 | — | |
| 105 | `battery_1_model` | | 0 | 0% | 0 | — | |
| 106 | `battery_2_id` | | 0 | 0% | 0 | — | |
| 107 | `battery_2_manufacturer` | | 0 | 0% | 0 | — | |
| 108 | `battery_2_model` | | 0 | 0% | 0 | — | |
| 109 | `battery_3_id` | | 0 | 0% | 0 | — | |
| 110 | `battery_3_manufacturer` | | 0 | 0% | 0 | — | |
| 111 | `battery_3_model` | | 0 | 0% | 0 | — | |
| 112 | `battery_count` | | 0 | 0% | 0 | — | |
| 113 | `bo_accept_attachment` | | 0 | 0% | 0 | — | |
| 114 | `bo_process_attachment` | | 0 | 0% | 0 | — | |
| 115 | `col_5g_down_site_list` | | 0 | 0% | 0 | — | |
| 116 | `confirm_attachment` | | 0 | 0% | 0 | — | |
| 117 | `create_attachment` | | 0 | 0% | 0 | — | |
| 118 | `create_wo_attachment` | | 0 | 0% | 0 | — | |
| 119 | `diagnosis_result` | | 0 | 0% | 0 | — | |
| 120 | `fail_reason` | | 0 | 0% | 0 | — | |
| 121 | `fault_recovery_time` | | 0 | 0% | 0 | — | |
| 122 | `fixed_generator_id` | | 0 | 0% | 0 | — | |
| 123 | `fixed_generator_manufacturer` | | 0 | 0% | 0 | — | |
| 124 | `fixed_generator_model` | | 0 | 0% | 0 | — | |
| 125 | `fo_accept_attachment` | | 0 | 0% | 0 | — | |
| 126 | `fo_process_attachment` | | 0 | 0% | 0 | — | |
| 127 | `Group SLA Remains Time` | | 0 | 0% | 0 | — | |
| 128 | `Group SLA Status` | | 0 | 0% | 0 | — | |
| 129 | `Group SLA Time` | | 0 | 0% | 0 | — | |
| 130 | `group_sla_deadline_time` | | 0 | 0% | 0 | — | |
| 131 | `last_maintenance_time` | | 0 | 0% | 0 | — | |
| 132 | `latest_power_generation_ticket_no` | | 0 | 0% | 0 | — | |
| 133 | `latest_power_generation_time` | | 0 | 0% | 0 | — | |
| 134 | `latest_refueling_ticket_no` | | 0 | 0% | 0 | — | |
| 135 | `latest_refueling_time` | | 0 | 0% | 0 | — | |
| 136 | `maintenance_suggestions` | | 0 | 0% | 0 | — | |
| 137 | `maintenance_team` | | 0 | 0% | 0 | — | |
| 138 | `maintenance_team_contract_no` | | 0 | 0% | 0 | — | |
| 139 | `mobile_generator_id` | | 0 | 0% | 0 | 🔒 已脱敏 | |
| 140 | `mobile_generator_manufacturer` | | 0 | 0% | 0 | 🔒 已脱敏 | |
| 141 | `mobile_generator_model` | | 0 | 0% | 0 | 🔒 已脱敏 | |
| 142 | `NE ID` | | 0 | 0% | 0 | — | |
| 143 | `next_level_optical_fiber_access_point` | | 0 | 0% | 0 | — | |
| 144 | `optical_fiber_access_point` | | 0 | 0% | 0 | — | |
| 145 | `position` | | 0 | 0% | 0 | — | |
| 146 | `preprocessed` | | 0 | 0% | 0 | — | |
| 147 | `process_description` | | 0 | 0% | 0 | 🔒 已脱敏 | |
| 148 | `process_time` | | 0 | 0% | 0 | — | |
| 149 | `Region Level2` | | 0 | 0% | 0 | — | |
| 150 | `severity` | | 0 | 0% | 0 | — | |
| 151 | `spare_available` | | 0 | 0% | 0 | — | |
| 152 | `spare_device` | | 0 | 0% | 0 | — | |
| 153 | `spare_domain` | | 0 | 0% | 0 | — | |
| 154 | `spare_name` | | 0 | 0% | 0 | 🔒 已脱敏 | |
| 155 | `spare_no` | | 0 | 0% | 0 | — | |
| 156 | `spare_required` | | 0 | 0% | 0 | — | |
| 157 | `third_accept_attachment` | | 0 | 0% | 0 | — | |
| 158 | `third_process_attachment` | | 0 | 0% | 0 | — | |
| 159 | `upper_level_optical_fiber_access_point` | | 0 | 0% | 0 | — | |
| 160 | `vip_down_site_list` | | 0 | 0% | 0 | — | |
| 161 | `wo_bonpo_process_attachment` | | 0 | 0% | 0 | — | |

## 枚举取值分布

> 仅列出去重值 ≤ 25 的列，按记录数倒序。**这是判断字段语义最有用的部分。**

### `_sync_time`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| 2026-08-07T01:07:45.700544 | 25,388 | 89.2% | |
| 2026-08-07T13:59:59.763043 | 3,067 | 10.8% | |

### `Fault Resolved`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| Yes | 28,374 | 99.7% | |
| No | 81 | 0.3% | |

### `Network Type`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| RAN | 27,890 | 98.0% | |
| VMAX | 264 | 0.9% | |
| TRM_IPRAN | 197 | 0.7% | |
| TRM_MW | 36 | 0.1% | |
| TRM_IPCORE | 31 | 0.1% | |
| TRM_DWDM | 22 | 0.1% | |
| CS | 7 | 0.0% | |
| VAS | 2 | 0.0% | |
| POWER | 2 | 0.0% | |
| 3G | 2 | 0.0% | |
| PS | 1 | 0.0% | |
| 4G | 1 | 0.0% | |

### `operation_type`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| Closed | 23,621 | 83.0% | |
| FOProcess | 1,848 | 6.5% | |
| FOProcess(WO RCA to FO Confirm) | 1,479 | 5.2% | |
| Closed(WO Confirming) | 631 | 2.2% | |
| ThirdAccept | 444 | 1.6% | |
| FOProcess(WO Reject to FO Confirm) | 142 | 0.5% | |
| BOAccept | 95 | 0.3% | |
| FOProcess(WO Dispatched FE Handling) | 68 | 0.2% | |
| ThirdProcess | 61 | 0.2% | |
| FOAccept | 52 | 0.2% | |
| BOProcess | 14 | 0.0% | |

### `Region ID`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| Montserrado | 10,627 | 37.3% | |
| Nimba | 4,971 | 17.5% | |
| Margibi | 2,302 | 8.1% | |
| Lofa | 1,955 | 6.9% | |
| Bong | 1,479 | 5.2% | |
| Grand_Bassa | 1,248 | 4.4% | |
| River_Gee | 1,026 | 3.6% | |
| Grand_Cape_Mount | 950 | 3.3% | |
| Grand_Kru | 844 | 3.0% | |
| Grand_Gedeh | 802 | 2.8% | |
| Maryland | 785 | 2.8% | |
| Bomi | 531 | 1.9% | |
| Sinoe | 434 | 1.5% | |
| Gbarpolu | 313 | 1.1% | |
| River_Cess | 188 | 0.7% | |

### `Site Class`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| P2 | 15,127 | 53.2% | |
| P4 | 6,447 | 22.7% | |
| P1 | 5,615 | 19.7% | |
| P3 | 1,266 | 4.4% | |

### `Source`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| UFM | 28,396 | 99.8% | |
| Manually | 59 | 0.2% | |

### `Status`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| Closed | 24,252 | 85.2% | |
| Waiting for FO Process | 1,848 | 6.5% | |
| Waiting for FO Process(WO RCA to FO Confirm) | 1,479 | 5.2% | |
| Waiting for Third Accept | 444 | 1.6% | |
| Waiting for FO Process(WO Reject to FO Confirm) | 142 | 0.5% | |
| Waiting for BO Accept | 95 | 0.3% | |
| Waiting for FO Process(WO Dispatched FE Handling) | 68 | 0.2% | |
| Waiting for Third Process | 61 | 0.2% | |
| Waiting for FO Accept | 52 | 0.2% | |
| Waiting for BO Process | 14 | 0.0% | |

### `Suspended`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| No | 28,453 | 100.0% | |
| Yes | 2 | 0.0% | |

### `Alarm Severity`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| Critical | 28,045 | 98.6% | |
| Major | 304 | 1.1% | |
| Minor | 97 | 0.3% | |
| （空） | 5 | 0.0% | |
| Medium | 4 | 0.0% | |

### `Hub Site`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| No | 22,228 | 78.1% | |
| Yes | 6,222 | 21.9% | |
| （空） | 5 | 0.0% | |

### `Region Level1`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| Montserrado | 10,624 | 37.3% | |
| Nimba | 4,970 | 17.5% | |
| Margibi | 2,302 | 8.1% | |
| Lofa | 1,955 | 6.9% | |
| Bong | 1,479 | 5.2% | |
| Grand Bassa | 1,248 | 4.4% | |
| River Gee | 1,026 | 3.6% | |
| Grand Cape Mount | 950 | 3.3% | |
| Grand Kru | 844 | 3.0% | |
| Grand Gedeh | 801 | 2.8% | |
| Maryland | 785 | 2.8% | |
| Bomi | 531 | 1.9% | |
| Sinoe | 434 | 1.5% | |
| Gbarpolu | 313 | 1.1% | |
| River Cess | 188 | 0.7% | |
| （空） | 5 | 0.0% | |

### `Ticket Type`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| Trouble Ticket(UFM) | 28,414 | 99.9% | |
| Trouble Ticket | 36 | 0.1% | |
| （空） | 5 | 0.0% | |

### `VIP Site`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| No | 25,753 | 90.5% | |
| Yes | 2,697 | 9.5% | |
| （空） | 5 | 0.0% | |

### `Ticket Severity`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| P2 | 15,679 | 55.1% | |
| P3 | 8,069 | 28.4% | |
| P4 | 2,442 | 8.6% | |
| P1 | 2,232 | 7.8% | |
| （空） | 33 | 0.1% | |

### `SLA Status`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| Pass | 25,958 | 91.2% | |
| Failed | 2,446 | 8.6% | |
| （空） | 37 | 0.1% | |
| Within SLA | 14 | 0.0% | |

### `SLA Total Duration`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| 0d8h0m | 15,678 | 55.1% | |
| 0d16h0m | 8,067 | 28.4% | |
| 2d0h0m | 2,441 | 8.6% | |
| 0d4h0m | 2,232 | 7.8% | |
| （空） | 37 | 0.1% | |

### `moc`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| ZTE_RAN_NODEB | 17,033 | 59.9% | |
| ZTE_RAN_ENODEB | 9,563 | 33.6% | |
| ZTE_RAN_BTS | 1,103 | 3.9% | |
| ZTE_VMAX_VMAX | 263 | 0.9% | |
| ZTE_RAN_ITBBU | 148 | 0.5% | |
| ZTE_TRM_IPRAN_ZXCTN_6120H_A_B | 82 | 0.3% | |
| ZTE_TRM_IPRAN_ZXCTN_6120H_S | 66 | 0.2% | |
| （空） | 59 | 0.2% | |
| ZTE_RAN_EMS | 32 | 0.1% | |
| ZTE_TRM_IPCORE_ZXR10_M6000_2S16 | 26 | 0.1% | |
| ZTE_TRM_IPRAN_ZXCTN_6180H_A | 21 | 0.1% | |
| ZTE_TRM_DWDM_ZXONE_9700 | 16 | 0.1% | |
| ZTE_TRM_MW_WL_LINK | 9 | 0.0% | |
| ZTE_TRM_MW_NR9150 | 9 | 0.0% | |
| ZTE_TRM_MW_NR9000 | 6 | 0.0% | |
| ZTE_TRM_IPRAN_ZXCTN_9000_8EA | 5 | 0.0% | |
| ZTE_TRM_IPCORE_ZXR10_M6000_8S_PLUS | 5 | 0.0% | |
| ZTE_CS_MSCS | 4 | 0.0% | |
| ZTE_CS_USPP | 3 | 0.0% | |
| ZTE_TRM_MW_NR9120 | 1 | 0.0% | |
| ZTE_TRM_IPRAN_ZXCTN_9000_3EA | 1 | 0.0% | |

### `Site Information`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| REGULAR | 22,497 | 79.1% | |
| ERA | 5,589 | 19.6% | |
| （空） | 293 | 1.0% | |
| REGULAR（Normal) | 63 | 0.2% | |
| REGULAR(COOL.i） | 13 | 0.0% | |

### `Asset Type`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| NORMAL | 20,358 | 71.5% | |
| （空） | 5,777 | 20.3% | |
| COOL | 2,196 | 7.7% | |
| REGULAR（Normal) | 63 | 0.2% | |
| ERA | 43 | 0.2% | |
| REGULAR(COOL.i） | 13 | 0.0% | |
| Site | 5 | 0.0% | |

### `Root Cause`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| POWER | 12,773 | 44.9% | |
| （空） | 9,762 | 34.3% | |
| Auto-recovery | 3,825 | 13.4% | |
| RAN | 689 | 2.4% | |
| Fiber | 365 | 1.3% | |
| MW | 361 | 1.3% | |
| Uknown | 333 | 1.2% | |
| Force Majeure | 157 | 0.6% | |
| Planned work | 103 | 0.4% | |
| VAS/OCS | 76 | 0.3% | |
| IP-DWDM Network | 8 | 0.0% | |
| CS Core | 3 | 0.0% | |

### `Sub Root Cause`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| （空） | 10,022 | 35.2% | |
| Power Genset | 9,474 | 33.3% | |
| Auto-recovery | 3,825 | 13.4% | |
| Power Solar | 2,645 | 9.3% | |
| Power Grid | 653 | 2.3% | |
| Hardware Fault | 428 | 1.5% | |
| Uknown | 333 | 1.2% | |
| Fiber cut | 261 | 0.9% | |
| High Temperature | 149 | 0.5% | |
| Link Degraded | 144 | 0.5% | |
| Other | 137 | 0.5% | |
| Hardware Hanging | 100 | 0.4% | |
| Cable Issue | 75 | 0.3% | |
| 3rd-party issue | 62 | 0.2% | |
| SFP Fault | 56 | 0.2% | |
| Fiber degraded | 24 | 0.1% | |
| Connector Issue | 16 | 0.1% | |
| Software issue | 14 | 0.0% | |
| others | 13 | 0.0% | |
| Patchcords Fault | 12 | 0.0% | |
| Hardware issue | 9 | 0.0% | |
| Others | 3 | 0.0% | |

### `Last Processer Group`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| （空） | 16,017 | 56.3% | |
| G:3rd_Power; | 9,250 | 32.5% | |
| G:ZTE_NOC_FO; | 2,570 | 9.0% | |
| G:ZTE_FE_FE; | 273 | 1.0% | |
| G:SOC-CEM; | 237 | 0.8% | |
| G:ZTE_NOC_FO;  G:ZTE_FE_FE; | 73 | 0.3% | |
| G:ZTE_BO_MW; | 5 | 0.0% | |
| G:ZTE_BO_RAN; | 4 | 0.0% | |
| G:ZTE_BO_MW;  G:ZTE_BO_RAN; | 4 | 0.0% | |
| G:ZTE_BO_manager; | 3 | 0.0% | |
| G:Fedesco Pelleh;  G:Zhang li;  G:Alex Nagbe; | 3 | 0.0% | |
| G:Zhang li;  G:Emmanuel Egbe; | 2 | 0.0% | |
| G:ZTE_NOC_FO;  G:ZTE_BO_manager;  G:ZTE_BO_RAN; | 2 | 0.0% | |
| G:ZTE_FE_MG;  G:ZTE_FE_FL;  G:ZTE_FE_FE; | 2 | 0.0% | |
| G:ZTE_BO_IP-DWDM-OLT; | 2 | 0.0% | |
| G:ZTE_NOC_FO;  G:ZTE_BO_RAN; | 1 | 0.0% | |
| G:ZTE_NOC_FO;  G:ZTE_BO_MW;  G:ZTE_BO_RAN; | 1 | 0.0% | |
| G:ZTE_NOC_FO;  G:ZTE_BO_MW; | 1 | 0.0% | |
| G:ZTE_BO_OCS-VAS;  G:ZTE_BO_manager;  G:ZTE_BO_PS;  G:ZTE_BO… | 1 | 0.0% | |
| G:ZTE_BO_CS; | 1 | 0.0% | |
| G:Prince K. Wilson; | 1 | 0.0% | |
| G:Prince Grugbaye; | 1 | 0.0% | |
| G:Patrick Monday; | 1 | 0.0% | |

### `Site Outage`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| （空） | 25,621 | 90.0% | |
| Yes | 1,720 | 6.0% | |
| No | 1,114 | 3.9% | |

### `Whether Impacted Service`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| （空） | 25,621 | 90.0% | |
| Yes | 1,727 | 6.1% | |
| No | 1,107 | 3.9% | |

### `Impacted Service`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| （空） | 26,728 | 93.9% | |
| 2G,3G | 917 | 3.2% | |
| 4G | 300 | 1.1% | |
| 2G,3G,4G | 227 | 0.8% | |
| 3G | 129 | 0.5% | |
| 2G,4G | 57 | 0.2% | |
| 2G | 49 | 0.2% | |
| 3G,4G | 30 | 0.1% | |
| ALL | 17 | 0.1% | |
| Others | 1 | 0.0% | |

### `Alarm Category`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| （空） | 28,437 | 99.9% | |
| RAN_BSC | 5 | 0.0% | |
| Fiber Break | 5 | 0.0% | |
| Site Down | 3 | 0.0% | |
| DWDM Fault | 2 | 0.0% | |
| VMAX Service Alarm | 1 | 0.0% | |
| Small Cell Down - Cell | 1 | 0.0% | |
| MW | 1 | 0.0% | |

### `Alarm Sub Category`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| （空） | 28,444 | 100.0% | |
| ZTE | 4 | 0.0% | |
| Fiber Break | 4 | 0.0% | |
| Site Down | 3 | 0.0% | |

### `Last Suspend Status`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| （空） | 28,448 | 100.0% | |
| Resume | 5 | 0.0% | |
| Suspend | 2 | 0.0% | |

### `Last Suspend Time`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| （空） | 28,448 | 100.0% | |
| 2026-07-31 15:52:18 | 1 | 0.0% | |
| 2026-03-05 19:06:00 | 1 | 0.0% | |
| 2026-03-04 20:28:43 | 1 | 0.0% | |
| 2026-03-01 22:52:41 | 1 | 0.0% | |
| 2026-02-25 17:53:52 | 1 | 0.0% | |
| 2026-01-28 17:05:18 | 1 | 0.0% | |
| 2026-01-26 21:05:29 | 1 | 0.0% | |

### `Suspend Detail`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| （空） | 28,448 | 100.0% | |
| Operation: Suspend. Operation Time:2026-07-31 15:52:18. Oper… | 1 | 0.0% | |
| Operation: Suspend. Operation Time:2026-03-05 19:06:00. Oper… | 1 | 0.0% | |
| Operation: Suspend. Operation Time:2026-03-04 20:28:43. Oper… | 1 | 0.0% | |
| Operation: Suspend. Operation Time:2026-03-01 22:45:13. Oper… | 1 | 0.0% | |
| Operation: Suspend. Operation Time:2026-02-25 17:53:52. Oper… | 1 | 0.0% | |
| Operation: Suspend. Operation Time:2026-01-28 17:05:15. Oper… | 1 | 0.0% | |
| Operation: Suspend. Operation Time:2026-01-26 21:05:29. Oper… | 1 | 0.0% | |

### `Last Resume Time`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| （空） | 28,450 | 100.0% | |
| 2026-07-31 15:53:30 | 1 | 0.0% | |
| 2026-03-05 19:07:25 | 1 | 0.0% | |
| 2026-03-04 20:29:54 | 1 | 0.0% | |
| 2026-03-01 22:53:57 | 1 | 0.0% | |
| 2026-02-25 17:54:37 | 1 | 0.0% | |

### `Alarm Type`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| （空） | 28,451 | 100.0% | |
| Environment Alarm | 2 | 0.0% | |
| QoS Alarm | 1 | 0.0% | |
| Communication Alarm | 1 | 0.0% | |

## 相关

- 索引：[00_索引.md](./00_索引.md)
- 术语：[90_术语表_Glossary.md](../../../90_术语表_Glossary.md)


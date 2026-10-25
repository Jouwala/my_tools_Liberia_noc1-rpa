# TT 单 - 推单与指派规则（Dispatch / Push Order / Group Config / Group Default）

本文件说明：一条 TT 单**派给谁、走哪条链路**由哪些规则决定。
共有四类规则，按下面的顺序理解：

1. **直接派发规则（ttDispatchRule）** —— 创建 TT 时按告警码/网络制式直接派给某组。
2. **条件推单规则（ttPushOrderRule）** —— 满足条件时，在某个环节自动推给指定组。
3. **环节可处理组名单（ttGroupConfigRule）** —— 某环节「谁有资格」接手。
4. **环节默认组（ttGroupDefaultRule）** —— 该环节没人被推单时默认给谁。

规则来源：eFlow 配置中心，导出文件 `eflow_push_rules.xlsx`（共 39 条 TT 相关规则）。
状态为 STOP 的规则仍然列出（配置中心的状态列可能滞后于实际生效情况），使用时请留意状态。

## 直接派发规则（ttDispatchRule）

### 规则 165：TT单直接派BO accept

- 状态：ACTIVE；优先级：2
- 触发步骤：autoDispatch
- 匹配条件：
  - eflow_ticket_ticket_wo.alarmCode = '199030729' ()
  - eflow_ticket_ticket_wo.alarmCode = '199030732' ()
  - eflow_ticket_ticket_wo.alarmCode = '199030728' ()
  - eflow_ticket_ticket_wo.alarmCode = '199030731' ()
  - eflow_ticket_ticket_wo.alarmCode = '199066010' ()
  - eflow_ticket_ticket_wo.alarmCode = '199066014' ()
  - eflow_ticket_ticket_wo.alarmCode = '199025860' ()
  - eflow_ticket_ticket_wo.alarmCode = '199025861' ()
  - eflow_ticket_ticket_wo.alarmCode = '199087506' ()
  - eflow_ticket_ticket_wo.alarmCode = '199087507' ()
  - eflow_ticket_ticket_wo.alarmCode = '199087344' ()
  - eflow_ticket_ticket_wo.alarmCode = '199087345' ()
  - eflow_ticket_ticket_wo.alarmCode = '199002560' ()
  - eflow_ticket_ticket_wo.alarmCode = '199066003' ()
  - eflow_ticket_ticket_wo.alarmCode = '199393986' ()
  - eflow_ticket_ticket_wo.alarmCode = '199393988' ()
  - eflow_ticket_ticket_wo.alarmCode = '10000100' ()
  - eflow_ticket_ticket_wo.alarmCode = '762183' ()
  - eflow_ticket_ticket_wo.alarmCode = '4758' ()
  - eflow_ticket_ticket_wo.alarmCode = '762136' ()
  - eflow_ticket_ticket_wo.alarmCode = '762143' ()
  - eflow_ticket_ticket_wo.alarmCode = '450112' ()
  - eflow_ticket_ticket_wo.alarmCode = '612614' ()
  - eflow_ticket_ticket_wo.alarmCode = '762149' ()
  - eflow_ticket_ticket_wo.alarmCode = '400136' ()
  - eflow_ticket_ticket_wo.alarmCode = '8' ()
  - eflow_ticket_ticket_wo.alarmCode = '687' ()
  - eflow_ticket_ticket_wo.alarmCode = '20623' ()
  - eflow_ticket_ticket_wo.alarmCode = '79' ()
  - eflow_ticket_ticket_wo.alarmCode = '20623' ()
  - eflow_ticket_ticket_wo.netWorkType = 'CS' ()
  - eflow_ticket_ticket_wo.netWorkType = 'PS' ()
  - eflow_ticket_ticket_wo.netWorkType = 'VAS' ()
  - eflow_ticket_ticket_wo.netWorkType = 'OCS' ()

### 规则 164：TT单直接派FO accept

- 状态：ACTIVE；优先级：3
- 触发步骤：autoDispatch

## 条件推单规则（ttPushOrderRule）

### 规则 119：TT_push_confirm_to_close with wo

- 状态：ACTIVE；优先级：1
- 触发步骤：Confirm
- 推送路径：Confirm,0>Closed
- 匹配条件：
  - eflow_ticket_ticket_wo.netWorkType not in 'VMAX' (enums)

### 规则 153：TT自动推单给BO-RAN组

- 状态：ACTIVE；优先级：2
- 触发步骤：BOAccept
- 推送路径：BOAccept,4>BOProcess
- 目标处理组：ZTE_BO_RAN
- 匹配条件：
  - eflow_ticket_ticket_wo.alarmCode = '199030729' ()
  - eflow_ticket_ticket_wo.alarmCode = '199030732' ()
  - eflow_ticket_ticket_wo.alarmCode = '199030728' ()
  - eflow_ticket_ticket_wo.alarmCode = '199030731' ()
  - eflow_ticket_ticket_wo.alarmCode = '199066010' ()
  - eflow_ticket_ticket_wo.alarmCode = '199066014' ()
  - eflow_ticket_ticket_wo.alarmCode = '199025860' ()
  - eflow_ticket_ticket_wo.alarmCode = '199025861' ()
  - eflow_ticket_ticket_wo.alarmCode = '199087506' ()
  - eflow_ticket_ticket_wo.alarmCode = '199087507' ()
  - eflow_ticket_ticket_wo.alarmCode = '199087344' ()
  - eflow_ticket_ticket_wo.alarmCode = '199087345' ()
  - eflow_ticket_ticket_wo.alarmCode = '199002560' ()
  - eflow_ticket_ticket_wo.alarmCode = '199066003' ()
  - eflow_ticket_ticket_wo.alarmCode = '199393986' ()
  - eflow_ticket_ticket_wo.alarmCode = '199393988' ()

### 规则 156：TT自动推单给BO-CS组

- 状态：ACTIVE；优先级：2
- 触发步骤：BOAccept
- 推送路径：BOAccept,4>BOProcess
- 目标处理组：ZTE_BO_CS
- 匹配条件：
  - eflow_ticket_ticket_wo.alarmCode = '8400384' ()
  - eflow_ticket_ticket_wo.alarmCode = '8402690' ()
  - eflow_ticket_ticket_wo.alarmCode = '4196864' ()
  - eflow_ticket_ticket_wo.alarmCode = '2534023175' ()
  - eflow_ticket_ticket_wo.alarmCode = '12596994' ()
  - eflow_ticket_ticket_wo.alarmCode = '2534023175' ()
  - eflow_ticket_ticket_wo.alarmCode = '2534034699' ()
  - eflow_ticket_ticket_wo.alarmCode = '514' ()
  - eflow_ticket_ticket_wo.alarmCode = '8400128' ()
  - eflow_ticket_ticket_wo.alarmCode = '12596994' ()
  - eflow_ticket_ticket_wo.alarmCode = '1929777156' ()
  - eflow_ticket_ticket_wo.alarmCode = '33577435' ()
  - eflow_ticket_ticket_wo.alarmCode = '25171456' ()
  - eflow_ticket_ticket_wo.netWorkType = 'CS' ()

### 规则 157：TT自动推单给BO-PS组

- 状态：ACTIVE；优先级：2
- 触发步骤：BOAccept
- 推送路径：BOAccept,4>BOProcess
- 目标处理组：ZTE_BO_PS
- 匹配条件：
  - eflow_ticket_ticket_wo.alarmCode = '3456237573' ()
  - eflow_ticket_ticket_wo.alarmCode = '2121924679' ()
  - eflow_ticket_ticket_wo.alarmCode = '108002' ()
  - eflow_ticket_ticket_wo.alarmCode = '108001' ()
  - eflow_ticket_ticket_wo.alarmCode = '2265317783' ()
  - eflow_ticket_ticket_wo.alarmCode = '8400384' ()
  - eflow_ticket_ticket_wo.alarmCode = '8402690' ()
  - eflow_ticket_ticket_wo.alarmCode = '2114322576' ()
  - eflow_ticket_ticket_wo.alarmCode = '8417537' ()
  - eflow_ticket_ticket_wo.alarmCode = '2114322678' ()
  - eflow_ticket_ticket_wo.netWorkType = 'PS' ()

### 规则 158：TT自动推单给BO-VAS_OCS组

- 状态：ACTIVE；优先级：2
- 触发步骤：BOAccept
- 推送路径：BOAccept,4>BOProcess
- 目标处理组：ZTE_BO_OCS-VAS
- 匹配条件：
  - eflow_ticket_ticket_wo.alarmCode = '47' ()
  - eflow_ticket_ticket_wo.alarmCode = '130' ()
  - eflow_ticket_ticket_wo.alarmCode = '135' ()
  - eflow_ticket_ticket_wo.alarmCode = '20008' ()
  - eflow_ticket_ticket_wo.alarmCode = '20016' ()
  - eflow_ticket_ticket_wo.alarmCode = '20063' ()
  - eflow_ticket_ticket_wo.alarmCode = '20103' ()
  - eflow_ticket_ticket_wo.alarmCode = '20132' ()
  - eflow_ticket_ticket_wo.alarmCode = '20142' ()

### 规则 162：能源告警推单给WO

- 状态：STOP；优先级：2
- 触发步骤：FOAccept
- 推送路径：FOAccept,2>FOProcess,8>FOProcess
- 目标处理组：ZTE_FE_FL
- 匹配条件：
  - eflow_ticket_ticket_wo.alarmCode = '50017011' ()
  - eflow_ticket_ticket_wo.alarmCode = '50008008' ()
  - eflow_ticket_ticket_wo.alarmCode = '50017012' ()
  - eflow_ticket_ticket_wo.alarmCode = '50008009' ()
  - eflow_ticket_ticket_wo.alarmCode = '50003005' ()
  - eflow_ticket_ticket_wo.alarmCode = '100110001' ()
  - eflow_ticket_ticket_wo.alarmCode = '50014001' ()
  - eflow_ticket_ticket_wo.alarmCode = '50003001' ()
  - eflow_ticket_ticket_wo.alarmCode = '198097062' ()

### 规则 155：TT自动推单给BO-IP_DWDM组

- 状态：ACTIVE；优先级：2
- 触发步骤：BOAccept
- 推送路径：BOAccept,4>BOProcess
- 目标处理组：ZTE_BO_IP-DWDM-OLT
- 匹配条件：
  - eflow_ticket_ticket_wo.alarmCode = '8' ()
  - eflow_ticket_ticket_wo.alarmCode = '687' ()
  - eflow_ticket_ticket_wo.alarmCode = '20623' ()
  - eflow_ticket_ticket_wo.alarmCode = '79' ()
  - eflow_ticket_ticket_wo.alarmCode = '20623' ()

### 规则 161：IP_DWDM告警推单给WO

- 状态：STOP；优先级：2
- 触发步骤：FOAccept
- 推送路径：FOAccept,2>FOProcess,8>FOProcess
- 目标处理组：ZTE_NOC_FO
- 匹配条件：
  - eflow_ticket_ticket_wo.alarmName = 'Fiber Break' ()
  - eflow_ticket_ticket_wo.alarmCode = '6497' ()
  - eflow_ticket_ticket_wo.alarmCode = '6419' ()
  - eflow_ticket_ticket_wo.alarmCode = '6583' ()
  - eflow_ticket_ticket_wo.alarmCode = '4369' ()

### 规则 200：Regular电源故障推送TT到IPT

- 状态：ACTIVE；优先级：2
- 触发步骤：FOAccept
- 推送路径：FOAccept,2>FOProcess,5>ThirdAccept
- 目标处理组：3rd_Power
- 匹配条件：
  - eflow_ticket_ticket_asset.siteSubType = 'REGULAR' (string)
  - eflow_ticket_ticket_asset.assetType in 'NORMAL, COOL' (string)
  - eflow_ticket_ticket_wo.alarmCode = '99933' (string)

### 规则 201：Regular断站故障手动到FO

- 状态：STOP；优先级：2
- 触发步骤：FOAccept
- 推送路径：FOAccept,2>FOProcess,8>FOProcess
- 目标处理组：ZTE_FE_FE
- 匹配条件：
  - eflow_ticket_ticket_asset.siteSubType = 'REGULAR' (string)
  - eflow_ticket_ticket_asset.assetType in 'NORMAL, COOL' (string)
  - eflow_ticket_ticket_wo.alarmCode in '9970, 9980, 9990, 9910, 9920, 9995' (string)

### 规则 203：ERA断站推单到ZTE WO

- 状态：ACTIVE；优先级：2
- 触发步骤：FOAccept
- 推送路径：FOAccept,2>FOProcess,8>FOProcess
- 目标处理组：ZTE_NOC_FO
- 匹配条件：
  - eflow_ticket_ticket_asset.siteSubType = 'ERA' (string)
  - eflow_ticket_ticket_wo.alarmCode in '9970, 9980, 9990, 9910, 9920, 9995, 99933' (string)

### 规则 253：P1_CSD_AUTO_WO

- 状态：ACTIVE；优先级：2
- 触发步骤：FOAccept
- 推送路径：FOAccept,2>FOProcess,8>FOProcess
- 目标处理组：ZTE_NOC_FO
- 匹配条件：
  - eflow_ticket_ticket_wo.alarmCode = '9920' (string)
  - eflow_ticket_ticket_wo.ticketSeverity = 'P1' (enums)

### 规则 160：微波告警推单给WO

- 状态：STOP；优先级：2
- 触发步骤：FOAccept
- 推送路径：FOAccept,2>FOProcess,8>FOProcess
- 目标处理组：ZTE_FE_MG
- 匹配条件：
  - eflow_ticket_ticket_wo.alarmCode = '761761' ()

### 规则 204：小区故障派ZTE WO

- 状态：ACTIVE；优先级：2
- 触发步骤：FOAccept
- 推送路径：FOAccept,2>FOProcess,8>FOProcess
- 目标处理组：ZTE_NOC_FO
- 匹配条件：
  - eflow_ticket_ticket_wo.alarmCode in '9971, 9981, 9991, 199087342, 199083022, 198094419, 198094832' (string)

### 规则 240：Vmax-TT-order-push-rule

- 状态：ACTIVE；优先级：2
- 触发步骤：FOAccept
- 推送路径：FOAccept,2>FOProcess
- 目标处理组：SOC-CEM
- 匹配条件：
  - eflow_ticket_ticket_wo.netWorkType = 'VMAX' ()

### 规则 154：TT自动推单给BO-MW组

- 状态：ACTIVE；优先级：3
- 触发步骤：BOAccept
- 推送路径：BOAccept,4>BOProcess
- 目标处理组：ZTE_BO_MW
- 匹配条件：
  - eflow_ticket_ticket_wo.alarmCode = '10000100' ()
  - eflow_ticket_ticket_wo.alarmCode = '762183' ()
  - eflow_ticket_ticket_wo.alarmName = 'Fiber/Link Break' ()
  - eflow_ticket_ticket_wo.alarmCode = '762136' ()
  - eflow_ticket_ticket_wo.alarmCode = '762143' ()
  - eflow_ticket_ticket_wo.alarmCode = '450112' ()
  - eflow_ticket_ticket_wo.alarmCode = '612614' ()
  - eflow_ticket_ticket_wo.alarmCode = '762149' ()
  - eflow_ticket_ticket_wo.alarmCode = '400136' ()
  - eflow_ticket_ticket_wo.alarmCode = '4758' ()

### 规则 252：TT_push_confirm_to_close without wo

- 状态：ACTIVE；优先级：4
- 触发步骤：Confirm
- 推送路径：Confirm,0>Closed
- 匹配条件：
  - eflow_ticket_ticket_wo.netWorkType not in 'VMAX' (enums)

## 环节可处理组名单（ttGroupConfigRule）

### 规则 237：Vmax-TT-BO-Accept

- 状态：STOP；优先级：2
- 触发步骤：GroupConfig_BOAccept
- 目标处理组：ZTE_BO_PS

### 规则 238：Vmax-TT-BO-Process

- 状态：STOP；优先级：2
- 触发步骤：GroupConfig_BOProcess
- 目标处理组：ZTE_BO_PS

### 规则 239：Vmax-TT-FO-Confirm

- 状态：STOP；优先级：2
- 触发步骤：GroupConfig_Confirm
- 目标处理组：SOC-CEM

### 规则 242：TT_BO_accept

- 状态：ACTIVE；优先级：2
- 触发步骤：GroupConfig_BOAccept
- 目标处理组：ZTE_BO_manager

### 规则 85：TT_FO_process

- 状态：ACTIVE；优先级：2
- 触发步骤：GroupConfig_FOProcess
- 目标处理组：ZTE_NOC_FO

### 规则 87：TT_BO_process

- 状态：ACTIVE；优先级：2
- 触发步骤：GroupConfig_BOProcess
- 目标处理组：ZTE_BO_MW

### 规则 88：TT_confirm

- 状态：ACTIVE；优先级：2
- 触发步骤：GroupConfig_Confirm
- 目标处理组：ZTE_NOC_FO

### 规则 89：TT_third_party_accept

- 状态：ACTIVE；优先级：2
- 触发步骤：GroupConfig_ThirdAccept
- 目标处理组：3rd_Power

### 规则 90：TT_third_party_process

- 状态：ACTIVE；优先级：2
- 触发步骤：GroupConfig_ThirdProcess
- 目标处理组：3rd_Power

### 规则 236：Vmax-TT-FO-Process

- 状态：ACTIVE；优先级：3
- 触发步骤：GroupConfig_FOProcess
- 目标处理组：SOC-CEM

### 规则 84：TT_FO_accept

- 状态：ACTIVE；优先级：3
- 触发步骤：GroupConfig_FOAccept
- 目标处理组：ZTE_NOC_FO

## 环节默认组（ttGroupDefaultRule）

### 规则 103：wo_to_unique_employee

- 状态：ACTIVE；优先级：2
- 触发步骤：GroupDefault_FOProcess

### 规则 123：TT_auto _choose_confirm_person

- 状态：ACTIVE；优先级：2
- 触发步骤：GroupDefault_BOProcess
- 目标处理组：ZTE_NOC_FO

### 规则 191：第三方提交关单

- 状态：ACTIVE；优先级：2
- 触发步骤：GroupDefault_ThirdProcess
- 目标处理组：ZTE_NOC_FO

### 规则 193：第三方转回

- 状态：ACTIVE；优先级：2
- 触发步骤：GroupDefault_ThirdProcess
- 目标处理组：ZTE_NOC_FO

### 规则 205：第三方拒绝回FO

- 状态：ACTIVE；优先级：2
- 触发步骤：GroupDefault_ThirdAccept
- 目标处理组：ZTE_NOC_FO

### 规则 210：FO处理提交确认默认审批人

- 状态：ACTIVE；优先级：2
- 触发步骤：GroupDefault_FOProcess
- 目标处理组：ZTE_NOC_FO

### 规则 241：TT rejected to FO confirm

- 状态：STOP；优先级：2
- 触发步骤：GroupDefault_FOProcess
- 目标处理组：ZTE_NOC_FO

### 规则 243：TT_BO_default_accept_group

- 状态：ACTIVE；优先级：2
- 触发步骤：GroupDefault_Create
- 目标处理组：ZTE_BO_manager

### 规则 182：default_FO_creat rule

- 状态：ACTIVE；优先级：4
- 触发步骤：GroupDefault_Create
- 目标处理组：ZTE_NOC_FO

## 判定顺序小结

1. 创建 TT 时先看**直接派发规则**：告警码/网络制式命中则直接派给目标组。
2. 否则按**条件推单规则**判断，命中则推给目标处理组并沿推送路径流转。
3. 若没有推单规则命中，走该环节的**默认组**。
4. 接手方必须在该环节的**可处理组名单**内，否则会出现指派断链。

# TT 单 - 级别判定规则（TT Update Severity Rule）

本文件说明：TT 单的严重级别（P1–P4）依据什么条件判定。
规则按**优先级**从小到大依次匹配，命中即停止，后面的规则不再参与。
同一优先级内，条件条数多的规则（更具体）优先。

级别含义：P1 最严重，P4 最轻。

## 规则 275：other ticket P4 → P4

- 目标级别：P4（优先级 5，状态 ACTIVE）

## 规则 274：Regular Cell Down P4 → P4

- 目标级别：P4（优先级 5，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.siteSubType = 'REGULAR' (enums)
  - AND | eflow_ticket_ticket_wo.alarmCode in '198094419, 198094832, 199087342, 199083022, 9971, 9981, 9991' (string)

## 规则 273：ERA Cell Down P4 → P4

- 目标级别：P4（优先级 5，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.siteSubType = 'ERA' (enums)
  - AND | eflow_ticket_ticket_wo.alarmCode in '198094419, 198094832, 199087342, 199083022, 9971, 9981, 9991' (string)

## 规则 272：High Temperature P4 → P4

- 目标级别：P4（优先级 5，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_wo.netWorkType = 'RAN' (enums)
  - AND | eflow_ticket_ticket_wo.alarmDescription = 'Board power-off due to overtemperature protection' (string)

## 规则 271：Single ERA Site P3 → P3

- 目标级别：P3（优先级 4，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.siteSubType = 'ERA' (enums)
  - AND | eflow_ticket_ticket_wo.alarmCode in '9910, 9920, 9970, 9980, 9990, 99933' (string)

## 规则 270：Single COOL Site P3 → P3

- 目标级别：P3（优先级 4，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.assetType = 'COOL' (string)
  - AND | eflow_ticket_ticket_wo.alarmCode in '9910, 9920, 9970, 9980, 9990, 99933' (string)

## 规则 269：Regular Nornal Site P2 → P2

- 目标级别：P2（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.assetType = 'NORMAL' (string)
  - AND | eflow_ticket_ticket_wo.alarmCode in '9910, 9920, 9970, 9980, 9990, 99933' (string)

## 规则 268：HUB site P2 → P2

- 目标级别：P2（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.hubSite = '1' (enums)
  - AND | eflow_ticket_ticket_asset.downstreamSites <= '4' (number)
  - AND | eflow_ticket_ticket_asset.downstreamSites >= '2' (number)
  - AND | eflow_ticket_ticket_wo.alarmCode = '9995' (string)

## 规则 277：HUB site P2-less than 5 → P2

- 目标级别：P2（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.hubSite = '1' (enums)
  - AND | eflow_ticket_ticket_wo.alarmCode = '9995' (string)
  - AND | eflow_ticket_ticket_asset.downstreamSites >= '5' (number)
  - AND | eflow_ticket_ticket_wo.downSiteCount <= '4' (number)

## 规则 266：HUB site P1 → P1

- 目标级别：P1（优先级 2，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.hubSite = '1' (enums)
  - AND | eflow_ticket_ticket_wo.alarmCode = '9995' (string)
  - AND | eflow_ticket_ticket_asset.downstreamSites >= '5' (number)
  - AND | eflow_ticket_ticket_wo.downSiteCount >= '5' (number)

## 规则 276：VIP site P2 for balance type site down → P2

- 目标级别：P2（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.vipSite = '1' (enums)
  - AND | eflow_ticket_ticket_wo.alarmCode in '9910, 9970, 9980, 9990, 99933' (string)

## 规则 267：VIP site P1 for CSD → P1

- 目标级别：P1（优先级 2，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.vipSite = '1' (enums)
  - AND | eflow_ticket_ticket_wo.alarmCode in '9920' (string)

## 判定流程小结

1. 取该 TT 单的字段值：告警码 alarmCode、是否 VIP 站点 vipSite、
   站点子类型 siteSubType、网络类型 netWorkType、断站数 downSiteCount。
2. 按优先级从小到大遍历规则，逐条判断条件是否全部满足。
3. 第一条命中的规则给出建议级别；与当前级别不同则建议调整。
4. 若所有规则都未命中，则无法判定，需人工确认。

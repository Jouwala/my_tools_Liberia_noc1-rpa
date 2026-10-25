# TT 单 - 级别判定规则（TT Update Severity Rule）

本文件说明：TT 单的严重级别（P1–P4）依据什么条件判定。
规则按**优先级**从小到大依次匹配，命中即停止，后面的规则不再参与。
同一优先级内，条件条数多的规则（更具体）优先。

级别含义：P1 最严重，P4 最轻。

## 规则 199：无线断小区级别重定义-P4 → P4

- 目标级别：P4（优先级 2，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_wo.alarmCode in '9971, 9981, 9991, 199087342, 199083022, 198094419, 198094832' (string)
  - AND | eflow_ticket_ticket_asset.vipSite = '0' (enums)

## 规则 207：MRNC和其他专业-P2 → P2

- 目标级别：P2（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_wo.alarmCode = '199066010' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '199066014' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '199025860' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '199025861' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '199087506' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '199087507' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '10000100' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '762183' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '4758' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '8' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '687' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '20623' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '6419' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '6583' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '4369' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '3456237573' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '2121924679' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '47' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '130' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '135' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '20008' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '20016' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '20063' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '20103' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '20132' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '20142' (string)

## 规则 229：无线断站级别重定义-P3-rule2 → P3

- 目标级别：P3（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.siteSubType = 'ERA' (enums)
  - AND | eflow_ticket_ticket_wo.alarmCode in '9970, 9980, 9990, 9910, 9920, 99933, 1014' (string)

## 规则 226：无线断站级别重定义-P1-rule2 → P1

- 目标级别：P1（优先级 2，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.vipSite = '1' (enums)
  - AND | eflow_ticket_ticket_wo.alarmCode in '9920' (string)

## 规则 230：TT-lowest severity → P4

- 目标级别：P4（优先级 4，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.vipSite in '0, 1' (enums)

## 规则 244：无线断站级别重定义-P2-rule3 → P2

- 目标级别：P2（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.vipSite = '1' (enums)
  - AND | eflow_ticket_ticket_wo.alarmCode in '9970, 9980, 9990, 9910, 99933' (string)

## 规则 225：无线断站级别重定义-P1-rule1 → P1

- 目标级别：P1（优先级 1，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_wo.alarmCode = '9995' (string)
  - AND | eflow_ticket_ticket_wo.downSiteCount >= '5' (number)

## 规则 234：High temperature alarm-bts → P3

- 目标级别：P3（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_wo.alarmCode = '198096491' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '198097061' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '198096400' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '198092042' (string)

## 规则 228：无线断站级别重定义-P3-rule1 → P3

- 目标级别：P3（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.assetType = 'COOL' (string)
  - AND | eflow_ticket_ticket_wo.alarmCode in '9970, 9980, 9990, 9910, 9920, 99933' (string)
  - AND | eflow_ticket_ticket_asset.vipSite = '0' (enums)

## 规则 233：无线断站级别重定义-P2-rule1 → P2

- 目标级别：P2（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_wo.alarmCode = '9995' (string)
  - AND | eflow_ticket_ticket_wo.downSiteCount <= '4' (number)

## 规则 227：无线断站级别重定义-P2-new → P2

- 目标级别：P2（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_asset.assetType = 'NORMAL' (string)
  - AND | eflow_ticket_ticket_wo.alarmCode in '9970, 9980, 9990, 9910, 9920, 99933' (string)
  - AND | eflow_ticket_ticket_asset.vipSite = '0' (enums)

## 规则 206：MRNC和其他专业-P1 → P1

- 目标级别：P1（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_wo.alarmCode = '199030729' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '199030732' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '199030728' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '199030731' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '79' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '20623' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '4758' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '6497' (string)
  - OR | eflow_ticket_ticket_wo.netWorkType = 'OCS' (enums)

## 规则 209：MRNC和其他专业-P4 → P4

- 目标级别：P4（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_wo.alarmCode = '199066003' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '199393986' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '199393988' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '8400384' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '8402690' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '4196864' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '2534023175' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '12596994' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '2534023175' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '2534034699' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '514' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '8400128' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '12596994' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '1929777156' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '108002' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '108001' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '2265317783' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '8400384' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '8402690' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '8417537' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '2114322678' (string)

## 规则 198：无线断小区级别重定义-P3 → P3

- 目标级别：P3（优先级 2，状态 ACTIVE）
- 匹配条件：
  - OR | eflow_ticket_ticket_asset.vipSite = '1' (enums)
  - AND | eflow_ticket_ticket_wo.alarmCode in '9971, 9981, 9991, 199087342, 199083022, 198094419, 198094832' (string)

## 规则 208：MRNC和其他专业-P3 → P3

- 目标级别：P3（优先级 3，状态 ACTIVE）
- 匹配条件：
  - AND | eflow_ticket_ticket_wo.alarmCode = '199087344' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '199087345' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '199002560' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '762136' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '762143' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '450112' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '612614' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '762149' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '400136' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '761761' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '2114322576' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '50017011' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '50008008' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '50017012' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '50008009' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '50003005' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '100110001' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '50014001' (string)
  - OR | eflow_ticket_ticket_wo.alarmCode = '50003001' (string)

## 判定流程小结

1. 取该 TT 单的字段值：告警码 alarmCode、是否 VIP 站点 vipSite、
   站点子类型 siteSubType、网络类型 netWorkType、断站数 downSiteCount。
2. 按优先级从小到大遍历规则，逐条判断条件是否全部满足。
3. 第一条命中的规则给出建议级别；与当前级别不同则建议调整。
4. 若所有规则都未命中，则无法判定，需人工确认。

# TT 单 - 告警压缩规则（告警相关性/父子衍生）

本文件说明：多条原始告警在什么条件下会被**压缩**成一条新的衍生告警。
压缩后，衍生出的告警作为**父告警**，参与压缩的基础告警作为**子告警**挂在下面。
所有规则来自 eFlow 告警配置中心，规则包为 OUTAGE（退服类）。

## 规则速览（每条规则的关键码，查压缩结果先看这里）

### 压缩规则速览：zte-4g-siteoutage

规则 zte-4g-siteoutage（4G），状态 ENABLED。
- 基础告警（子告警）站点断站码：198094422,2114322696,198200011
- 基础告警（子告警）小区退服码：198094419
- 关联告警码：198097062,10000,9971,9981,9991
- 衍生告警（父告警）根告警码：9970
- 衍生告警名称：4G site down

### 压缩规则速览：zte-3g-sitedown

规则 zte-3g-sitedown（3G），状态 ENABLED。
- 基础告警（子告警）站点断站码：199083023
- 基础告警（子告警）小区退服码：199083022
- 关联告警码：2365980930,198097062,9971,9981,9991
- 衍生告警（父告警）根告警码：9990
- 衍生告警名称：3G site down

### 压缩规则速览：zte-2g-siteoutage

规则 zte-2g-siteoutage（2G），状态 ENABLED。
- 基础告警（子告警）站点断站码：199087337
- 基础告警（子告警）小区退服码：199087342
- 关联告警码：198092072,198097062,9971,9981,9991
- 衍生告警（父告警）根告警码：9980
- 衍生告警名称：2G site down

### 压缩规则速览：mpf-outage

规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），状态 ENABLED。
- 基础告警（子告警）站点断站码：9910,9920,9980,9990,9970
- 衍生告警（父告警）根告警码：99933
- 衍生告警名称：SITE OUTAGE DUE TO POWER OFF

### 压缩规则速览：zte-4g-outage-new

规则 zte-4g-outage-new（4G），状态 DISABLED。
- 基础告警（子告警）站点断站码：198094422,2114322696,198200011
- 基础告警（子告警）小区退服码：198094419
- 关联告警码：10000
- 衍生告警（父告警）根告警码：9970
- 衍生告警名称：4G site down

### 压缩规则速览：mwlink-outage-new

规则 mwlink-outage-new（zte.ran.enodeb,zte.ran.nodeb,zte.ran.bts），状态 ENABLED。
- 基础告警（子告警）站点断站码：9970,9980,9990,9910,9920
- 衍生告警（父告警）根告警码：9995
- 衍生告警名称：MW LINK DOWN

### 压缩规则速览：zte-4g-celloutage

规则 zte-4g-celloutage（4G），状态 ENABLED。
- 基础告警（子告警）小区退服码：198094419,198094832
- 衍生告警（父告警）根告警码：9971
- 衍生告警名称：4G cell down

### 压缩规则速览：zte-3g-celloutage

规则 zte-3g-celloutage（3G），状态 ENABLED。
- 基础告警（子告警）小区退服码：199083022
- 衍生告警（父告警）根告警码：9991
- 衍生告警名称：3G cell down

### 压缩规则速览：zte-2g-celloutage

规则 zte-2g-celloutage（2G），状态 ENABLED。
- 基础告警（子告警）小区退服码：199087342
- 衍生告警（父告警）根告警码：9981
- 衍生告警名称：2G cell down

### 压缩规则速览：mwlink-outage

规则 mwlink-outage（zte.ran.nodeb），状态 DISABLED。
- 基础告警（子告警）站点断站码：9970,9980,9990,9910,9920
- 衍生告警（父告警）根告警码：9995
- 衍生告警名称：MW LINK DOWN

### 压缩规则速览：csd-outage

规则 csd-outage（zte.ran.enodeb），状态 ENABLED。
- 基础告警（子告警）站点断站码：9970,9980,9990
- 衍生告警（父告警）根告警码：9920
- 衍生告警名称：Complete site down (CSD)

### 压缩规则速览：psd-outage

规则 psd-outage（zte.ran.enodeb），状态 ENABLED。
- 基础告警（子告警）站点断站码：9970,9980,9990
- 衍生告警（父告警）根告警码：9910
- 衍生告警名称：Partial site down (PSD)

## 规则详情（完整参数）

## 压缩规则：zte-4g-siteoutage

- 作用：一个物理站点某个制式不可用时，逻辑站点退服告警会产生，同时归属此逻辑站点的所有小区会退服产生小区退服告警，这时衍生出逻辑站点退服告警作为父告警，基础告警作为子告警，建立起父子关联关系
- 状态：ENABLED
- 关键参数：
  - NE type(siteAlarmNeType) = ZTE_RAN_ENODEB,ZTE_PS_UMAC,zte.ran.itbbu
  - Site break alarm code(siteAlarmCode) = 198094422,2114322696,198200011
  - Cell out-of-service alarm NE type(cellAlarmNeType) = zte.ran.enodeb
  - Cell out-of-service alarm code(cellAlarmList) = 198094419
  - Whether to support CN alarms.(supportCoreAlarm) = true
  - Core network alarm NE type(siteCoreAlarmNeType) = zte.ps.uspp
  - Core network alarm code(siteCoreAlarmCode) = 10000
  - Number of Me types(maxMeTypeNum) = 1
  - Whether to configure only associated alarms(supportrelation) = true
  - Associated alarm NE types only(relationAlarmNeType) = ZTE_CS_MSCS,ZTE_RAN_BTS,ZTE_RAN_ITBBU,ZTE_RAN_NODEB,ZTE_RAN_ENODEB
  - Only associated alarm codes(relationAlarmCode) = 198097062,10000,9971,9981,9991
  - RAT(type) = 4G
  - Whether to enable cell blocking(cellBlock) = true
  - ruleFlag(vendor1) = ZTE
  - Derivative alarm name(specificProblem) = 4G site down
  - Delay derivation time window (s)(delayCreateTimeWindow) = 10
  - Delay recovery time window (s)(delayClearTimeWindow) = 120
  - NE type of the root alarm(rootResType) = zte.ran.enodeb
  - Root Alarm Code(rootAlarmCode) = 9970

## 压缩规则：zte-3g-sitedown

- 作用：一个物理站点某个制式不可用时，逻辑站点退服告警会产生，同时归属此逻辑站点的所有小区会退服产生小区退服告警，这时衍生出逻辑站点退服告警作为父告警，基础告警作为子告警，建立起父子关联关系
- 状态：ENABLED
- 关键参数：
  - NE type of the root alarm(rootResType) = zte.ran.nodeb
  - Root Alarm Code(rootAlarmCode) = 9990
  - NE type(siteAlarmNeType) = zte.ran.nodeb
  - Site break alarm code(siteAlarmCode) = 199083023
  - Cell out-of-service alarm NE type(cellAlarmNeType) = zte.ran.nodeb
  - Cell out-of-service alarm code(cellAlarmList) = 199083022
  - Whether to support CN alarms.(supportCoreAlarm) = true
  - Core network alarm NE type(siteCoreAlarmNeType) = zte.ps.umm
  - Core network alarm code(siteCoreAlarmCode) = 2365981958
  - Number of Me types(maxMeTypeNum) = 1
  - Whether to configure only associated alarms(supportrelation) = true
  - Associated alarm NE types only(relationAlarmNeType) = zte.ps.umm,ZTE_RAN_BTS,ZTE_RAN_ITBBU,ZTE_RAN_NODEB,ZTE_RAN_ENODEB
  - Only associated alarm codes(relationAlarmCode) = 2365980930,198097062,9971,9981,9991
  - RAT(type) = 3G
  - Whether to enable cell blocking(cellBlock) = true
  - ruleFlag(vendor1) = ZTE
  - Derivative alarm name(specificProblem) = 3G site down
  - Delay derivation time window (s)(delayCreateTimeWindow) = 10
  - Delay recovery time window (s)(delayClearTimeWindow) = 120

## 压缩规则：zte-2g-siteoutage

- 作用：一个物理站点某个制式不可用时，逻辑站点退服告警会产生，同时归属此逻辑站点的所有小区会退服产生小区退服告警，这时衍生出逻辑站点退服告警作为父告警，基础告警作为子告警，建立起父子关联关系
- 状态：ENABLED
- 关键参数：
  - NE type(siteAlarmNeType) = zte.ran.bts
  - Site break alarm code(siteAlarmCode) = 199087337
  - Cell out-of-service alarm NE type(cellAlarmNeType) = zte.ran.bts
  - Cell out-of-service alarm code(cellAlarmList) = 199087342
  - Whether to support CN alarms.(supportCoreAlarm) = true
  - Core network alarm NE type(siteCoreAlarmNeType) = zte.core.mscs
  - Core network alarm code(siteCoreAlarmCode) = 33577435
  - Number of Me types(maxMeTypeNum) = 1
  - Whether to configure only associated alarms(supportrelation) = true
  - Associated alarm NE types only(relationAlarmNeType) = ZTE_RAN_BTS,ZTE_RAN_ITBBU,ZTE_RAN_NODEB,ZTE_RAN_ENODEB
  - Only associated alarm codes(relationAlarmCode) = 198092072,198097062,9971,9981,9991
  - RAT(type) = 2G
  - Whether to enable cell blocking(cellBlock) = true
  - ruleFlag(vendor1) = ZTE
  - Derivative alarm name(specificProblem) = 2G site down
  - Delay derivation time window (s)(delayCreateTimeWindow) = 10
  - Delay recovery time window (s)(delayClearTimeWindow) = 120
  - NE type of the root alarm(rootResType) = zte.ran.bts
  - Root Alarm Code(rootAlarmCode) = 9980

## 压缩规则：mpf-outage

- 作用：如果某个物理站出现断站告警（2G，3G，4G，任一制式断站），时间窗内存在任一电源相关告警，则衍生电源断站告警.
- 状态：ENABLED
- 关键参数：
  - NE type(siteAlarmNeType) = zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb
  - Site break alarm code(siteAlarmCode) = 9910,9920,9980,9990,9970
  - Whether to associate site break alarm(relationSiteAlarm) = 0
  - Power alarm NE type(powerAlarmNeType) = zte.ran.itbbu,zte.ran.sdr
  - Power alarm code(powerAlarmList) = 198092053,198092295,198092296
  - Whether to associate power alarm(relationPowerAlarm) = 0
  - Vendor ID(vendor1) = ZTE
  - Derivative alarm name(specificProblem) = SITE OUTAGE DUE TO POWER OFF
  - Time window(timeWindow1) = 259200
  - Delay derivation time window (s)(delayCreateTimeWindow) = 30
  - Delay recovery time window (s)(delayClearTimeWindow) = 30
  - NE type of the root alarm(rootResType) = zte.ran.nodeb
  - Root Alarm Code(rootAlarmCode) = 99933

## 压缩规则：zte-4g-outage-new

- 作用：When a physical site of a certain RAN type becomes unavailable, the site is out of service alarm is generated. At the same time, all corresponding cells will be out of service and generating cell outage alarms. In this case, the site outage alarm is derived as the parent alarm, and the basic cell outage alarms are the child alarms, establishing a parent-child association relationship.
- 状态：DISABLED
- 关键参数：
  - NE type(siteAlarmNeType) = zte.ran.enodeb,zte.ps.umac,zte.ran.itbbu
  - Site break alarm code(siteAlarmCode) = 198094422,2114322696,198200011
  - Cell out-of-service alarm NE type(cellAlarmNeType) = zte.ran.enodeb
  - Cell out-of-service alarm code(cellAlarmList) = 198094419
  - ERA site break alarm alarm NE type(ERAAlarmNeType) = ZTE_RAN_EMS
  - ERA site break alarm code(ERAAlarmList) = 1014
  - Whether to support CN alarms.(supportCoreAlarm) = false
  - Core network alarm NE type(siteCoreAlarmNeType) = zte.cs.uspp
  - Core network alarm code(siteCoreAlarmCode) = 10000
  - Number of Me types(maxMeTypeNum) = 1
  - Whether to configure only associated alarms(supportrelation) = false
  - Associated alarm NE types only(relationAlarmNeType) = zte.cs.lig
  - Only associated alarm codes(relationAlarmCode) = 10000
  - RAT(type) = 4G
  - Whether to enable cell blocking(cellBlock) = true
  - ruleFlag(vendor1) = ZTE
  - Derivative alarm name(specificProblem) = 4G site down
  - Delay derivation time window (s)(delayCreateTimeWindow) = 10
  - Delay recovery time window (s)(delayClearTimeWindow) = 120
  - NE type of the root alarm(rootResType) = zte.ran.enodeb
  - Root Alarm Code(rootAlarmCode) = 9970

## 压缩规则：mwlink-outage-new

- 作用：根据链路数据表，将用户设定时间窗内发生的同链路断站告警压缩在一起，选取链路最上游的站点（Hub Site）的断站告警作为主告警，衍生新告警，其他所有的站点的断站告警挂在该告警下面作为子告警.
- 状态：ENABLED
- 关键参数：
  - NE type(siteAlarmNeType) = zte.ran.enodeb,zte.ran.nodeb,zte.ran.bts
  - Site break alarm code(siteAlarmCode) = 9970,9980,9990,9910,9920
  - IPBH NE type(IPAlarmNeType) = zte.trm_mw.nr9150
  - IPBH alarm code(IPAlarmCode) = 10000
  - Derivative alarm name(specificProblem) = MW LINK DOWN
  - Derivative time window (s)(timeWindow1) = 180
  - Delay derivation time window (s)(delayCreateTimeWindow) = 30
  - Delay recovery time window (s)(delayClearTimeWindow) = 30
  - Associated Time Window (s)(relationTimeWindow) = 360
  - NE type of the root alarm(rootResType) = zte.ran.nodeb
  - Root Alarm Code(rootAlarmCode) = 9995

## 压缩规则：zte-4g-celloutage

- 作用：当同一个制式的一个或多个小区退服时，对应的物理站点衍生出新的告警作为父告警，基础告警告警作为子告警，建立起关联关系
- 状态：ENABLED
- 关键参数：
  - NE type of the root alarm(rootResType) = zte.ran.enodeb
  - Root Alarm Code(rootAlarmCode) = 9971
  - Cell out-of-service alarm NE type(cellAlarmNeType) = zte.ran.enodeb
  - Cell out-of-service alarm code(cellAlarmList) = 198094419,198094832
  - RAT(type) = 4G
  - Whether to enable cell blocking(cellBlock) = true
  - rulefLAG(vendor1) = ZTE
  - Derivative alarm name(specificProblem) = 4G cell down
  - Delay derivation time window (s)(delayCreateTimeWindow) = 20
  - Delay recovery time window (s)(delayClearTimeWindow) = 20

## 压缩规则：zte-3g-celloutage

- 作用：当同一个制式的一个或多个小区退服时，对应的物理站点衍生出新的告警作为父告警，基础告警告警作为子告警，建立起关联关系
- 状态：ENABLED
- 关键参数：
  - NE type of the root alarm(rootResType) = zte.ran.nodeb
  - Root Alarm Code(rootAlarmCode) = 9991
  - Cell out-of-service alarm NE type(cellAlarmNeType) = zte.ran.nodeb
  - Cell out-of-service alarm code(cellAlarmList) = 199083022
  - RAT(type) = 3G
  - Whether to enable cell blocking(cellBlock) = true
  - rulefLAG(vendor1) = ZTE
  - Derivative alarm name(specificProblem) = 3G cell down
  - Delay derivation time window (s)(delayCreateTimeWindow) = 20
  - Delay recovery time window (s)(delayClearTimeWindow) = 20

## 压缩规则：zte-2g-celloutage

- 作用：当同一个制式的一个或多个小区退服时，对应的物理站点衍生出新的告警作为父告警，基础告警告警作为子告警，建立起关联关系
- 状态：ENABLED
- 关键参数：
  - NE type of the root alarm(rootResType) = zte.ran.bts
  - Root Alarm Code(rootAlarmCode) = 9981
  - Cell out-of-service alarm NE type(cellAlarmNeType) = zte.ran.bts
  - Cell out-of-service alarm code(cellAlarmList) = 199087342
  - RAT(type) = 2G
  - Whether to enable cell blocking(cellBlock) = true
  - rulefLAG(vendor1) = ZTE
  - Derivative alarm name(specificProblem) = 2G cell down
  - Delay derivation time window (s)(delayCreateTimeWindow) = 20
  - Delay recovery time window (s)(delayClearTimeWindow) = 20

## 压缩规则：mwlink-outage

- 作用：COMMON SAME LINK DERIVATIVE TEMPLATE
- 状态：DISABLED
- 关键参数：
  - NE type of the root alarm(rootResType) = zte.ran.nodeb
  - Root Alarm Code(rootAlarmCode) = 9995
  - NE type(siteAlarmNeType) = zte.ran.enodeb,zte.ran.bts,zte.ran.nodeb
  - Site break alarm code(siteAlarmCode) = 9970,9980,9990,9910,9920
  - IPBH NE type(IPAlarmNeType) = zte.trm_mw.nr9150
  - IPBH alarm code(IPAlarmCode) = 10000
  - Derivative alarm name(specificProblem) = MW LINK DOWN
  - Time window(timeWindow1) = 180
  - Delay derivation time window (s)(delayCreateTimeWindow) = 30
  - Delay recovery time window (s)(delayClearTimeWindow) = 30
  - Associated Time Window (s)(relationTimeWindow) = 360

## 压缩规则：csd-outage

- 作用：COMMON CSD DERIVATIVE TEMPLATE
- 状态：ENABLED
- 关键参数：
  - NE type of the root alarm(rootResType) = zte.ran.enodeb
  - Root Alarm Code(rootAlarmCode) = 9920
  - NE type(siteAlarmNeType) = zte.ran.enodeb,zte.ran.bts,zte.ran.nodeb
  - Site break alarm code(siteAlarmCode) = 9970,9980,9990
  - ruleFlag(vendor1) = ZTE
  - Derivative alarm name(specificProblem) = Complete site down (CSD)
  - Delay derivation time window (s)(delayCreateTimeWindow) = 10
  - Delay recovery time window (s)(delayClearTimeWindow) = 10

## 压缩规则：psd-outage

- 作用：COMMON PSD DERIVATIVE TEMPLATE
- 状态：ENABLED
- 关键参数：
  - NE type of the root alarm(rootResType) = zte.ran.enodeb
  - Root Alarm Code(rootAlarmCode) = 9910
  - NE type(siteAlarmNeType) = zte.ran.enodeb,zte.ran.bts,zte.ran.nodeb
  - Site break alarm code(siteAlarmCode) = 9970,9980,9990
  - ruleFlag(vendor1) = ZTE
  - Derivative alarm name(specificProblem) = Partial site down (PSD)
  - Delay derivation time window (s)(delayCreateTimeWindow) = 10
  - Delay recovery time window (s)(delayClearTimeWindow) = 30

## 告警码 → 压缩归属速查

本节按告警码逐个列出：它参与哪条压缩规则、扮演什么角色、压缩后的父告警码是什么。
查「某个告警码会被压缩成什么」，看这里最直接。

### 告警码 0

- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Whether to associate site break alarm(relationSiteAlarm)」
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）
- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Whether to associate power alarm(relationPowerAlarm)」
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）

### 告警码 1014

- 规则 zte-4g-outage-new（4G），字段「ERA site break alarm code(ERAAlarmList)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9970（4G site down）

### 告警码 9910

- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）
- 规则 mwlink-outage-new（zte.ran.enodeb,zte.ran.nodeb,zte.ran.bts），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 mwlink-outage（zte.ran.nodeb），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 psd-outage（zte.ran.enodeb），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9910（Partial site down (PSD)）

### 告警码 9920

- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）
- 规则 mwlink-outage-new（zte.ran.enodeb,zte.ran.nodeb,zte.ran.bts），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 mwlink-outage（zte.ran.nodeb），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 csd-outage（zte.ran.enodeb），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9920（Complete site down (CSD)）

### 告警码 9970

- 规则 zte-4g-siteoutage（4G），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）
- 规则 zte-4g-outage-new（4G），字段「Root Alarm Code(rootAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9970（4G site down）
- 规则 mwlink-outage-new（zte.ran.enodeb,zte.ran.nodeb,zte.ran.bts），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 mwlink-outage（zte.ran.nodeb），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 csd-outage（zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9920（Complete site down (CSD)）
- 规则 psd-outage（zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9910（Partial site down (PSD)）

### 告警码 9971

- 规则 zte-4g-siteoutage（4G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-3g-sitedown（3G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9990（3G site down）
- 规则 zte-2g-siteoutage（2G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）
- 规则 zte-4g-celloutage（4G），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9971（4G cell down）

### 告警码 9980

- 规则 zte-2g-siteoutage（2G），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）
- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）
- 规则 mwlink-outage-new（zte.ran.enodeb,zte.ran.nodeb,zte.ran.bts），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 mwlink-outage（zte.ran.nodeb），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 csd-outage（zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9920（Complete site down (CSD)）
- 规则 psd-outage（zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9910（Partial site down (PSD)）

### 告警码 9981

- 规则 zte-4g-siteoutage（4G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-3g-sitedown（3G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9990（3G site down）
- 规则 zte-2g-siteoutage（2G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）
- 规则 zte-2g-celloutage（2G），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9981（2G cell down）

### 告警码 9990

- 规则 zte-3g-sitedown（3G），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9990（3G site down）
- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）
- 规则 mwlink-outage-new（zte.ran.enodeb,zte.ran.nodeb,zte.ran.bts），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 mwlink-outage（zte.ran.nodeb），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 csd-outage（zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9920（Complete site down (CSD)）
- 规则 psd-outage（zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9910（Partial site down (PSD)）

### 告警码 9991

- 规则 zte-4g-siteoutage（4G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-3g-sitedown（3G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9990（3G site down）
- 规则 zte-2g-siteoutage（2G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）
- 规则 zte-3g-celloutage（3G），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9991（3G cell down）

### 告警码 9995

- 规则 mwlink-outage-new（zte.ran.enodeb,zte.ran.nodeb,zte.ran.bts），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 mwlink-outage（zte.ran.nodeb），字段「Root Alarm Code(rootAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9995（MW LINK DOWN）

### 告警码 10000

- 规则 zte-4g-siteoutage（4G），字段「Core network alarm code(siteCoreAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-4g-siteoutage（4G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-4g-outage-new（4G），字段「Core network alarm code(siteCoreAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-4g-outage-new（4G），字段「Only associated alarm codes(relationAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9970（4G site down）
- 规则 mwlink-outage-new（zte.ran.enodeb,zte.ran.nodeb,zte.ran.bts），字段「IPBH alarm code(IPAlarmCode)」
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 mwlink-outage（zte.ran.nodeb），字段「IPBH alarm code(IPAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9995（MW LINK DOWN）

### 告警码 99933

- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）

### 告警码 33577435

- 规则 zte-2g-siteoutage（2G），字段「Core network alarm code(siteCoreAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）

### 告警码 198092053

- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Power alarm code(powerAlarmList)」
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）

### 告警码 198092072

- 规则 zte-2g-siteoutage（2G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）

### 告警码 198092295

- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Power alarm code(powerAlarmList)」
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）

### 告警码 198092296

- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Power alarm code(powerAlarmList)」
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）

### 告警码 198094419

- 规则 zte-4g-siteoutage（4G），字段「Cell out-of-service alarm code(cellAlarmList)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-4g-outage-new（4G），字段「Cell out-of-service alarm code(cellAlarmList)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-4g-celloutage（4G），字段「Cell out-of-service alarm code(cellAlarmList)」
  → 压缩后的父告警码是 9971（4G cell down）

### 告警码 198094422

- 规则 zte-4g-siteoutage（4G），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-4g-outage-new（4G），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9970（4G site down）

### 告警码 198094832

- 规则 zte-4g-celloutage（4G），字段「Cell out-of-service alarm code(cellAlarmList)」
  → 压缩后的父告警码是 9971（4G cell down）

### 告警码 198097062

- 规则 zte-4g-siteoutage（4G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-3g-sitedown（3G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9990（3G site down）
- 规则 zte-2g-siteoutage（2G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）

### 告警码 198200011

- 规则 zte-4g-siteoutage（4G），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-4g-outage-new（4G），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9970（4G site down）

### 告警码 199083022

- 规则 zte-3g-sitedown（3G），字段「Cell out-of-service alarm code(cellAlarmList)」
  → 压缩后的父告警码是 9990（3G site down）
- 规则 zte-3g-celloutage（3G），字段「Cell out-of-service alarm code(cellAlarmList)」
  → 压缩后的父告警码是 9991（3G cell down）

### 告警码 199083023

- 规则 zte-3g-sitedown（3G），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9990（3G site down）

### 告警码 199087337

- 规则 zte-2g-siteoutage（2G），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）

### 告警码 199087342

- 规则 zte-2g-siteoutage（2G），字段「Cell out-of-service alarm code(cellAlarmList)」
  → 压缩后的父告警码是 9980（2G site down）
- 规则 zte-2g-celloutage（2G），字段「Cell out-of-service alarm code(cellAlarmList)」
  → 压缩后的父告警码是 9981（2G cell down）

### 告警码 2114322696

- 规则 zte-4g-siteoutage（4G），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-4g-outage-new（4G），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9970（4G site down）

### 告警码 2365980930

- 规则 zte-3g-sitedown（3G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9990（3G site down）

### 告警码 2365981958

- 规则 zte-3g-sitedown（3G），字段「Core network alarm code(siteCoreAlarmCode)」
  → 压缩后的父告警码是 9990（3G site down）

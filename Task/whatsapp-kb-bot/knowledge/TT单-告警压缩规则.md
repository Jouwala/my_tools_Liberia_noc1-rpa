# TT 单 - 告警压缩规则（告警相关性/父子衍生）

本文件说明：多条原始告警在什么条件下会被**压缩**成一条新的衍生告警。
压缩后，衍生出的告警作为**父告警**，参与压缩的基础告警作为**子告警**挂在下面。
所有规则来自 eFlow 告警配置中心，规则包为 OUTAGE（退服类）。

## 规则速览（每条规则的关键码，查压缩结果先看这里）

### 压缩规则速览：SYSTEM_COMMON_RAN_LINKREASONOWER_RULE

规则 SYSTEM_COMMON_RAN_LINKREASONOWER_RULE（zte.ran.nodeb,huawei.ran.nodeb,ericsson.ran.nodeb），状态 ENABLED。

### 压缩规则速览：SYSTEM_ERICSSON_RAN_REASONPOWER_RULE

规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），状态 ENABLED。

### 压缩规则速览：SYSTEM_ERICSSON_RAN_REASONRAN_RULE

规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），状态 ENABLED。

### 压缩规则速览：SYSTEM_HUAWEI_RAN_REASONPOWER_RULE

规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），状态 ENABLED。

### 压缩规则速览：SYSTEM_HUAWEI_RAN_REASONRAN_RULE

规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），状态 ENABLED。

### 压缩规则速览：SYSTEM_ZTE_RAN_REASONPOWER_RULE

规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），状态 ENABLED。

### 压缩规则速览：SYSTEM_ZTE_RAN_REASONRAN_RULE

规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），状态 ENABLED。

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

规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），状态 DISABLED。
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

## 压缩规则：SYSTEM_COMMON_RAN_LINKREASONOWER_RULE

- 作用：COMMON REASONING CORRELATION TEMPLATE
- 状态：ENABLED
- 关键参数：
  - Root Alarm Resource Type(rootResTypeUFM) = zte.ran.nodeb,huawei.ran.nodeb,ericsson.ran.nodeb
  - Root alarm code(rootAlarmUFM) = 9995
  - Secondary Alarm Resource Type(childResType1) = HUAWEI_TRM_IP_IP,HUAWEI_TRM_DWDM_DWDM,NEC_TRM_MW_MW,HUAWEI_TRM_MW_MW
  - Secondary Alarm List(childAlarmList1) = 1013073217,1013069130,1013073216,1012601101,1012505228
  - Inference delay time(s)(delayUpdateTimeWindow) = 5
  - Time Window Before (s)(timeWindowBefore) = 86313600
  - Time Window After (s)(timeWindowAfter) = 300
  - Root Cause(reason) = POWER

## 压缩规则：SYSTEM_ERICSSON_RAN_REASONPOWER_RULE

- 作用：COMMON REASONING CORRELATION TEMPLATE
- 状态：ENABLED
- 关键参数：
  - Root Alarm Resource Type(rootResTypeUFM) = ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts
  - Root alarm code(rootAlarmUFM) = 9910,9920,9980,9970,9990,9981,9991,9971
  - Secondary Alarm Resource Type(childResType1) = ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts,ericsson.ran.ems, ericsson.ran.rnc
  - Secondary Alarm List(childAlarmList1) = 23076028,24061399,18530803,36616644,92435266,948497664
  - Inference delay time(s)(delayUpdateTimeWindow) = 5
  - Time Window Before (s)(timeWindowBefore) = 86313600
  - Time Window After (s)(timeWindowAfter) = 300
  - Root Cause(reason) = POWER

## 压缩规则：SYSTEM_ERICSSON_RAN_REASONRAN_RULE

- 作用：COMMON REASONING CORRELATION TEMPLATE
- 状态：ENABLED
- 关键参数：
  - Root Alarm Resource Type(rootResTypeUFM) = ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts
  - Root alarm code(rootAlarmUFM) = 9910,9920,9980,9970,9990,9981,9991,9971
  - Secondary Alarm Resource Type(childResType1) = ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts,ericsson.ran.ems, ericsson.ran.rnc
  - Secondary Alarm List(childAlarmList1) = 20661844,85907667,61049066,3923440,49234691,75568605,12185764,13924243,67509387,61789575,66365039,88761151,96549388,25506051,26729469,92297199,24837008,54588780,66707044,59973720,25596472,64228879,80867976,87015723,88969328,59184112,19919714,7985129,42670633,2666261,62730456,30134307,96960059,27003785,29929776,85379204,18636643,63436696,6798471,29103637,81817948,77716134
  - Inference delay time(s)(delayUpdateTimeWindow) = 2
  - Time Window Before (s)(timeWindowBefore) = 86313600
  - Time Window After (s)(timeWindowAfter) = 300
  - Root Cause(reason) = RAN

## 压缩规则：SYSTEM_HUAWEI_RAN_REASONPOWER_RULE

- 作用：COMMON REASONING CORRELATION TEMPLATE
- 状态：ENABLED
- 关键参数：
  - Root Alarm Resource Type(rootResTypeUFM) = huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts
  - Root alarm code(rootAlarmUFM) = 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
  - Secondary Alarm Resource Type(childResType1) = huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts,huawei.ran.bts3900,huawei.ran.bts59005g,huawei.ran.bts5900,huawei.ran.microbts3900,huawei.ran.dbs3900ibs
  - Secondary Alarm List(childAlarmList1) = 65034,26113,25620,26546,26564,25622,26214,1017,979901952,26108,65134
  - Inference delay time(s)(delayUpdateTimeWindow) = 5
  - Time Window Before (s)(timeWindowBefore) = 86313600
  - Time Window After (s)(timeWindowAfter) = 300
  - Root Cause(reason) = POWER

## 压缩规则：SYSTEM_HUAWEI_RAN_REASONRAN_RULE

- 作用：HUAWEI REASONING CORRELATION TEMPLATE
- 状态：ENABLED
- 关键参数：
  - Root Alarm Resource Type(rootResTypeUFM) = huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb
  - Root alarm code(rootAlarmUFM) = 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
  - Secondary Alarm Resource Type(childResType1) = huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts
  - Secondary Alarm List(childAlarmList1) = 26200
  - Inference delay time(s)(delayUpdateTimeWindow) = 2
  - Time Window Before (s)(timeWindowBefore) = 86313600
  - Time Window After (s)(timeWindowAfter) = 300
  - Root Cause(reason) = RAN
  - Candidate Alarm Resource Type(candidateResType) = huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts
  - Candidate Alarm List(candidateAlarmList) = 26235,26563,26529,26525,26520
  - Cell Down Alarm Resource Type(cellDownResType) = huawei.ran.bts,huawei.ran.enodeb,huawei.ran.nodeb
  - Cell Down Alarm List(cellDownAlarmList) = 21801,28016,22202,22206,28203,29240

## 压缩规则：SYSTEM_ZTE_RAN_REASONPOWER_RULE

- 作用：COMMON REASONING CORRELATION TEMPLATE
- 状态：ENABLED
- 关键参数：
  - Root Alarm Resource Type(rootResTypeUFM) = zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb
  - Root alarm code(rootAlarmUFM) = 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
  - Secondary Alarm Resource Type(childResType1) = zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,huawei.trm_ip.ip,zte.ran.sdr,zte.ran.itbbu,zte.ran.bsc,zte.ran.rnc,zte.ran.ems,zte.ran.gnodeb
  - Secondary Alarm List(childAlarmList1) = 198092560,198092296,198092259,198092206,198092068,198098472,1017,960712704,198093060,198092295,198092053
  - Inference delay time(s)(delayUpdateTimeWindow) = 5
  - Time Window Before (s)(timeWindowBefore) = 86313600
  - Time Window After (s)(timeWindowAfter) = 300
  - Root Cause(reason) = POWER

## 压缩规则：SYSTEM_ZTE_RAN_REASONRAN_RULE

- 作用：COMMON REASONING CORRELATION TEMPLATE
- 状态：ENABLED
- 关键参数：
  - Root Alarm Resource Type(rootResTypeUFM) = zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb
  - Root alarm code(rootAlarmUFM) = 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
  - Secondary Alarm Resource Type(childResType1) = zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.itbbu,zte.ran.mrnc,zte.ran.ems
  - Secondary Alarm List(childAlarmList1) = 198092029,198092070,198092072,198092292,198092348,198092431,198097004,198097050,198097060,198097605,198098251,198098318,198098319,198098440,198098467,198098474,198100276
  - Inference delay time(s)(delayUpdateTimeWindow) = 2
  - Time Window Before (s)(timeWindowBefore) = 86313600
  - Time Window After (s)(timeWindowAfter) = 300
  - Root Cause(reason) = RAN

## 压缩规则：zte-4g-siteoutage

- 作用：一个物理站点某个制式不可用时，逻辑站点退服告警会产生，同时归属此逻辑站点的所有小区会退服产生小区退服告警，这时衍生出逻辑站点退服告警作为父告警，基础告警作为子告警，建立起父子关联关系
- 状态：ENABLED
- 关键参数：
  - NE type of the root alarm(rootResType) = zte.ran.enodeb
  - Root Alarm Code(rootAlarmCode) = 9970
  - NE type(siteAlarmNeType) = ZTE_RAN_ENODEB,ZTE_PS_UMAC,zte.ran.itbbu
  - Site break alarm code(siteAlarmCode) = 198094422,2114322696,198200011
  - Cell out-of-service alarm NE type(cellAlarmNeType) = zte.ran.enodeb
  - Cell out-of-service alarm code(cellAlarmList) = 198094419
  - Whether to support CN alarms.(supportCoreAlarm) = true
  - Core network alarm NE type(siteCoreAlarmNeType) = zte.ps.uspp
  - Core network alarm code(siteCoreAlarmCode) = 10000
  - Number of Me types(maxMeTypeNum) = 1
  - Whether to configure only associated alarms(supportrelation) = true
  - Associated alarm NE types only(relationAlarmNeType) = zte.cs.mscs,zte.ran.bts,zte.ran.itbbu,zte.ran.nodeb,zte.ran.enodeb
  - Only associated alarm codes(relationAlarmCode) = 198097062,10000,9971,9981,9991
  - RAT(type) = 4G
  - Whether to enable cell blocking(cellBlock) = true
  - ruleFlag(vendor1) = ZTE
  - Derivative alarm name(specificProblem) = 4G site down
  - Delay derivation time window (s)(delayCreateTimeWindow) = 10
  - Delay recovery time window (s)(delayClearTimeWindow) = 120

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
  - Associated alarm NE types only(relationAlarmNeType) = zte.ps.umm,zte.ran.bts,zte.ran.itbbu,zte.ran.nodeb,zte.ran.enode
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
  - NE type of the root alarm(rootResType) = zte.ran.bts
  - Root Alarm Code(rootAlarmCode) = 9980
  - NE type(siteAlarmNeType) = zte.ran.bts
  - Site break alarm code(siteAlarmCode) = 199087337
  - Cell out-of-service alarm NE type(cellAlarmNeType) = zte.ran.bts
  - Cell out-of-service alarm code(cellAlarmList) = 199087342
  - Whether to support CN alarms.(supportCoreAlarm) = true
  - Core network alarm NE type(siteCoreAlarmNeType) = zte.core.mscs
  - Core network alarm code(siteCoreAlarmCode) = 33577435
  - Number of Me types(maxMeTypeNum) = 1
  - Whether to configure only associated alarms(supportrelation) = true
  - Associated alarm NE types only(relationAlarmNeType) = zte.ran.bts,zte.ran.itbbu,zte.ran.nodeb,zte.ran.enodeb
  - Only associated alarm codes(relationAlarmCode) = 198092072,198097062,9971,9981,9991
  - RAT(type) = 2G
  - Whether to enable cell blocking(cellBlock) = true
  - ruleFlag(vendor1) = ZTE
  - Derivative alarm name(specificProblem) = 2G site down
  - Delay derivation time window (s)(delayCreateTimeWindow) = 10
  - Delay recovery time window (s)(delayClearTimeWindow) = 120

## 压缩规则：mpf-outage

- 作用：如果某个物理站出现断站告警（2G，3G，4G，任一制式断站），时间窗内存在任一电源相关告警，则衍生电源断站告警.
- 状态：DISABLED
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

- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Whether to associate site break alarm(relationSiteAlarm)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）
- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Whether to associate power alarm(relationPowerAlarm)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）

### 告警码 1014

- 规则 zte-4g-outage-new（4G），字段「ERA site break alarm code(ERAAlarmList)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9970（4G site down）

### 告警码 1017

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961

### 告警码 9910

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）
- 规则 mwlink-outage-new（zte.ran.enodeb,zte.ran.nodeb,zte.ran.bts），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 mwlink-outage（zte.ran.nodeb），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 psd-outage（zte.ran.enodeb），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9910（Partial site down (PSD)）

### 告警码 9920

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）
- 规则 mwlink-outage-new（zte.ran.enodeb,zte.ran.nodeb,zte.ran.bts），字段「Site break alarm code(siteAlarmCode)」
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 mwlink-outage（zte.ran.nodeb），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 csd-outage（zte.ran.enodeb），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9920（Complete site down (CSD)）

### 告警码 9960

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 9961

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 9970

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 zte-4g-siteoutage（4G），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
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

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 zte-4g-siteoutage（4G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-3g-sitedown（3G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9990（3G site down）
- 规则 zte-2g-siteoutage（2G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）
- 规则 zte-4g-celloutage（4G），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9971（4G cell down）

### 告警码 9980

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 zte-2g-siteoutage（2G），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）
- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
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

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 zte-4g-siteoutage（4G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-3g-sitedown（3G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9990（3G site down）
- 规则 zte-2g-siteoutage（2G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）
- 规则 zte-2g-celloutage（2G），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9981（2G cell down）

### 告警码 9990

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 zte-3g-sitedown（3G），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9990（3G site down）
- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Site break alarm code(siteAlarmCode)」，状态 DISABLED（未启用）
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

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971
- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 zte-4g-siteoutage（4G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-3g-sitedown（3G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9990（3G site down）
- 规则 zte-2g-siteoutage（2G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）
- 规则 zte-3g-celloutage（3G），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9991（3G cell down）

### 告警码 9995

- 规则 SYSTEM_COMMON_RAN_LINKREASONOWER_RULE（zte.ran.nodeb,huawei.ran.nodeb,ericsson.ran.nodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9995
- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 mwlink-outage-new（zte.ran.enodeb,zte.ran.nodeb,zte.ran.bts），字段「Root Alarm Code(rootAlarmCode)」
  → 压缩后的父告警码是 9995（MW LINK DOWN）
- 规则 mwlink-outage（zte.ran.nodeb），字段「Root Alarm Code(rootAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 9995（MW LINK DOWN）

### 告警码 9996

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961
- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Root alarm code(rootAlarmUFM)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961

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

### 告警码 21801

- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Cell Down Alarm List(cellDownAlarmList)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 22202

- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Cell Down Alarm List(cellDownAlarmList)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 22206

- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Cell Down Alarm List(cellDownAlarmList)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 25620

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961

### 告警码 25622

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961

### 告警码 26108

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961

### 告警码 26113

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961

### 告警码 26200

- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 26214

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961

### 告警码 26235

- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Candidate Alarm List(candidateAlarmList)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 26520

- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Candidate Alarm List(candidateAlarmList)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 26525

- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Candidate Alarm List(candidateAlarmList)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 26529

- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Candidate Alarm List(candidateAlarmList)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 26546

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961

### 告警码 26563

- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Candidate Alarm List(candidateAlarmList)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 26564

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961

### 告警码 28016

- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Cell Down Alarm List(cellDownAlarmList)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 28203

- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Cell Down Alarm List(cellDownAlarmList)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 29240

- 规则 SYSTEM_HUAWEI_RAN_REASONRAN_RULE（huawei.ran.bts,huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.gnodeb），字段「Cell Down Alarm List(cellDownAlarmList)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 65034

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961

### 告警码 65134

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961

### 告警码 99933

- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Root Alarm Code(rootAlarmCode)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）

### 告警码 2666261

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 3923440

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 6798471

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 7985129

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 12185764

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 13924243

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 18530803

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 18636643

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 19919714

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 20661844

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 23076028

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 24061399

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 24837008

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 25506051

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 25596472

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 26729469

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 27003785

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 29103637

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 29929776

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 30134307

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 33577435

- 规则 zte-2g-siteoutage（2G），字段「Core network alarm code(siteCoreAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）

### 告警码 36616644

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 42670633

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 49234691

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 54588780

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 59184112

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 59973720

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 61049066

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 61789575

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 62730456

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 63436696

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 64228879

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 66365039

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 66707044

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 67509387

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 75568605

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 77716134

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 80867976

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 81817948

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 85379204

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 85907667

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 87015723

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 88761151

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 88969328

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 92297199

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 92435266

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 96549388

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 96960059

- 规则 SYSTEM_ERICSSON_RAN_REASONRAN_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 198092029

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198092053

- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Power alarm code(powerAlarmList)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）

### 告警码 198092068

- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961

### 告警码 198092070

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198092072

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961
- 规则 zte-2g-siteoutage（2G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）

### 告警码 198092206

- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961

### 告警码 198092259

- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961

### 告警码 198092292

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198092295

- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Power alarm code(powerAlarmList)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）

### 告警码 198092296

- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961
- 规则 mpf-outage（zte.ran.bts,zte.ran.nodeb,zte.ran.enodeb），字段「Power alarm code(powerAlarmList)」，状态 DISABLED（未启用）
  → 压缩后的父告警码是 99933（SITE OUTAGE DUE TO POWER OFF）

### 告警码 198092348

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198092431

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198092560

- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961

### 告警码 198093060

- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961

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

### 告警码 198097004

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198097050

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198097060

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198097062

- 规则 zte-4g-siteoutage（4G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9970（4G site down）
- 规则 zte-3g-sitedown（3G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9990（3G site down）
- 规则 zte-2g-siteoutage（2G），字段「Only associated alarm codes(relationAlarmCode)」
  → 压缩后的父告警码是 9980（2G site down）

### 告警码 198097605

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198098251

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198098318

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198098319

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198098440

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198098467

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198098472

- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961

### 告警码 198098474

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

### 告警码 198100276

- 规则 SYSTEM_ZTE_RAN_REASONRAN_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9960,9961

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

### 告警码 948497664

- 规则 SYSTEM_ERICSSON_RAN_REASONPOWER_RULE（ericsson.ran.nodeb,ericsson.ran.enodeb,ericsson.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971

### 告警码 960712704

- 规则 SYSTEM_ZTE_RAN_REASONPOWER_RULE（zte.ran.nodeb,zte.ran.enodeb,zte.ran.bts,zte.ran.gnodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9995,9996,9960,9961

### 告警码 979901952

- 规则 SYSTEM_HUAWEI_RAN_REASONPOWER_RULE（huawei.ran.nodeb,huawei.ran.enodeb,huawei.ran.bts），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9910,9920,9980,9970,9990,9981,9991,9971,9996,9995,9960,9961

### 告警码 1012505228

- 规则 SYSTEM_COMMON_RAN_LINKREASONOWER_RULE（zte.ran.nodeb,huawei.ran.nodeb,ericsson.ran.nodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9995

### 告警码 1012601101

- 规则 SYSTEM_COMMON_RAN_LINKREASONOWER_RULE（zte.ran.nodeb,huawei.ran.nodeb,ericsson.ran.nodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9995

### 告警码 1013069130

- 规则 SYSTEM_COMMON_RAN_LINKREASONOWER_RULE（zte.ran.nodeb,huawei.ran.nodeb,ericsson.ran.nodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9995

### 告警码 1013073216

- 规则 SYSTEM_COMMON_RAN_LINKREASONOWER_RULE（zte.ran.nodeb,huawei.ran.nodeb,ericsson.ran.nodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9995

### 告警码 1013073217

- 规则 SYSTEM_COMMON_RAN_LINKREASONOWER_RULE（zte.ran.nodeb,huawei.ran.nodeb,ericsson.ran.nodeb），字段「Secondary Alarm List(childAlarmList1)」
  → 压缩后的父告警码是 9995

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

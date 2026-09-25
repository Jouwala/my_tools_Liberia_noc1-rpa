# 配置巡检与排障 SOP

## 一、新告警接入端到端配置检查单（告警→TT→指派）

1. **告警层**：确认告警码是否需要衍生/屏蔽/过滤（02_告警衍生规则.md）；
   断站类告警需确认衍生模板（OUTAGE 包）参数覆盖该 NE type。
2. **定级层**：确认 alarmCode 已被某条 ttLevelRule 覆盖，否则落兜底规则 230 (P4)；
   若需 P1~P3，新增 ttLevelRule 时注意优先级与条件特异性（03）。
3. **派发层**：确认 FO/BO 走向（ttDispatchRule 164/165）。
4. **指派层**（重点，决定“指派的人或组织是否正常”）：
   - 该环节 GroupConfig 名单是否包含目标组（05_指派一致性校验.md 审计表）；
   - 推单路径 pushPath 与状态机环节一致（如 `FOAccept,2>FOProcess,8>FOProcess`）；
   - 第三方单需确认 ThirdAccept/ThirdProcess 名单包含第三方组；
   - 目标组 ID 是否有效（targetHandler 中 id 与 name 对应，组被删会推单失败）。
5. **关单层**：Confirm 后是否会被 119 自动关闭（VMAX 例外）。

## 二、“指派不正常”故障树

```
TT 卡在 Accept/Process 没人处理
 ├─ 推单规则未命中? → 检查条件字段值(alarmCode/siteSubType/assetType/netWorkType)
 ├─ 推单目标组不在 GroupConfig 名单? → 见 05 审计 FAIL 项
 ├─ GroupConfig 全 STOP / 无 ACTIVE? → 走 GroupDefault 默认组；默认组也无 → 卡单
 ├─ 目标组被删除/改名? → targetHandler id 失效
 └─ 推单规则优先级冲突? → 低优先级被高优先级先推走
```

## 三、规则数据刷新方式

```bash
cd Y:\Task\my_app
python backend/services/eflow_rules/eflow_Push_Rule_Collector.py   # 全量规则→eflow_push_rules.xlsx
python backend/services/eflow_rules/eflow_TT_Rule_Collector.py     # ttLevelRule→eflow_TT_rules.xlsx
python backend/services/eflow_rules/eflow_Alarm_Rule_Collector.py  # 告警规则→eflow_alarm_rules.xlsx
python backend/services/eflow_rules/eflow_tt_rules_check_task.py   # 1000条TT回放→eflow_tt_severity_correction.xlsx
```

刷新后重新执行本目录 `build_kb.py` 再上传知识库，即可同步最新规则。

## 四、规则变更风险提示（本次审计发现）

- 规则 201（Regular 断站到 FO）为 STOP：Regular 站断站(9970/9980/9990/9910/9920/9995)
  目前无 FO 推单，仅 200（99933 电源类）推 3rd_Power —— 若现场需要处理 Regular 断站，需重新评估。
- BO 线推单规则 154~158 的告警码清单较长，新增告警码时注意同步维护。
- Vmax 系列 GroupConfig(237/238/239) STOP，仅 236(FOProcess→SOC-CEM) ACTIVE，
  VMAX 的 TT BOAccept 环节走默认组 243(TT_BO_default_accept_group)。

# eFlow TT 规则匹配分析报告 (v2)

生成时间：2026-10-09 15:12:59
运行耗时：19.38 秒

## 修正摘要

本版相对上一版的核心修复：

1. 加入 `downSiteCount` 字段（DB `down_site_count`），支持规则 225 / 233。
2. 比较运算符支持 `>= <= > < != <> in not in =`，正则不再把 `>=` 误吞为 `=`。
3. OR/AND 采用左折叠求值，修复 Rule 206/207/208/209/234 "首条 AND + 后续 OR" 类型的漏配。
4. 同优先级内按条件特异性降序匹配（条件数多者先），再按 ID 保证确定性。
5. 数据归一化补齐：`site_type` 脏值 (REGULAR（Normal)/REGULAR(COOL.i)) 合并到 NORMAL/COOL；`vip_site` NaN → 空串。
6. `site_type` 为空时回退到 `site_information` 取站点类型（ERA/REGULAR），使 Rule 229 (ERA) 等能正确命中原本被兜底 Rule 230 吞掉的 TT。

## 总体结果

| 指标 | 数量 | 占比 |
|------|------|------|
| 总 TT 记录数 | 1000 | 100.0% |
| 成功匹配规则 | 1000 | 100.0% |
| 未匹配 | 0 | 0.0% |
| 需要级别变更 | 0 | 0.0% |

## 按规则分组

| 优先级 | 规则 ID | 规则名称 | 目标级别 | 匹配数 | 需变更数 |
|--------|---------|----------|----------|--------|----------|
| 1 | 225 | 无线断站级别重定义-P1-rule1 | P1 | 6 | 0 |
| 2 | 198 | 无线断小区级别重定义-P3 | P3 | 43 | 0 |
| 2 | 199 | 无线断小区级别重定义-P4 | P4 | 91 | 0 |
| 3 | 207 | MRNC和其他专业-P2 | P2 | 3 | 0 |
| 3 | 227 | 无线断站级别重定义-P2-new | P2 | 366 | 0 |
| 3 | 228 | 无线断站级别重定义-P3-rule1 | P3 | 109 | 0 |
| 3 | 229 | 无线断站级别重定义-P3-rule2 | P3 | 277 | 0 |
| 3 | 233 | 无线断站级别重定义-P2-rule1 | P2 | 36 | 0 |
| 3 | 244 | 无线断站级别重定义-P2-rule3 | P2 | 45 | 0 |
| 4 | 230 | TT-lowest severity | P4 | 24 | 0 |

## 字段映射

| 规则字段 | DB 列 | 归一化 |
|----------|-------|--------|
| alarmCode | alarm_code | 去除末尾 `.0` |
| vipSite | vip_site | Yes/No → 1/0，NaN → 空串 |
| siteSubType | site_type → site_information | site_type 优先；为空回退 site_information，大写归一 |
| assetType | 同 siteSubType | 与 siteSubType 同源 |
| netWorkType | domain | 大写 |
| downSiteCount | down_site_count | 字符串数值，`to_numeric` 参与 >=/<= 比较 |

## 结论

- 修正后共 1000 条 TT 匹配到规则，占比 100.0%。
- 0 条需要级别调整，占比 0.0%（补 site_information 回退前为 161/1000 = 16.1%，最初错误版为 236/1000 = 23.6%）。
- alarmCode=9995 的 TT 已按 `down_site_count` 分流到 Rule 225 (P1) 或 Rule 233 (P2)，不再落入兜底 Rule 230。
- MRNC/高温类多 OR 规则（206/207/208/209/234）现在可以正常命中非首条告警码。
- `site_type` 为空时回退 `site_information`：原被 Rule 230 误判为 P3→P4 的 ERA 站点 TT 现匹配 Rule 229 (P3)，与本就 P3 一致，无需变更。
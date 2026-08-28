# eFlow TT Rules 收集脚本

## 使用说明

这个脚本用于从 eFlow 系统获取所有激活的 TT Update Severity Rule 并汇总到 Excel 表格中。

### 运行方式

在项目根目录执行：

```bash
cd d:\01_RPA\Task\my_app
python backend/services/eflow_rules/eflow_TT_Rule_Collector.py
```

或者在 `backend/services/eflow_rules` 目录下执行：

```bash
cd d:\01_RPA\Task\my_app\backend\services\eflow_rules
python eflow_TT_Rule_Collector.py
```

### 功能特点

1. **自动鉴权**: 使用项目已有的 `auth_manager` 和 `eflow_api_client` 进行登录认证
2. **批量查询**: 自动查询所有 `ttLevelRule` 类型的活跃规则
3. **详情合并**: 对每个规则 ID 分别调用详情页 API 获取完整信息
4. **条件格式化**: 将复杂的 conditions JSON 解析为可读文本格式
5. **Excel 导出**: 生成包含所有规则详情的 Excel 文件

### 输出文件

- **backend/services/eflow_rules/eflow_TT_rules.xlsx** - 包含所有规则的完整信息

### Excel 字段说明

| 字段名 | 说明 |
|--------|------|
| ID | 规则唯一标识 |
| 规则名称 | Rule Name |
| 规则类型 | Rule Type (ttLevelRule) |
| 工单类型 | WO Type (eflow-tt) |
| 触发步骤 | Trigger Step (autoCreateTT) |
| 描述 | Description |
| 优先级 | Priority |
| 严重级别 | Ticket Severity (P1-P4) |
| 状态 | Status (ACTIVE) |
| 创建人/时间 | Create By/Time |
| 更新人/时间 | Update By/Time |
| 条件 | Conditions (规则匹配条件) |

### API 调用路径

- 列表查询：`POST /api/eflow-configcenter/v1/eflow-configcenter-rule/base/query`
- 详情查询：`GET /api/eflow-configcenter/v1/eflow-configcenter-rule/base/detail/{id}`

---
Author: Qoder
Date: 2026-08-27

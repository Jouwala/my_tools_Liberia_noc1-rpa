# incident_overview_service

事件总览业务逻辑层（改写自 `Unified_Tools/incident_overview/app.py`）。

## 数据源
- Excel：`data/incident_overview/incident_overview.xlsx`（7 个 sheet）
- 地图：`data/incident_overview/lr-all.geo.json`

## 解析函数
| 函数 | 对应原 sheet | 说明 |
|---|---|---|
| `get_status_data` | Status | key→int 状态指标 |
| `get_tt_quality_data` | TT Quality | Total/Closed/Unclosed |
| `get_severity_data` | Owner1 | P1~P4 × 5 状态 × 7 域 矩阵 |
| `get_sla_data(sheet)` | ZTE / 3rd | P1~P4 的 gt100/lt100/lt75/lt50/lt25 |
| `get_details_data` | Details1 | 全量明细 + 列序 |
| `get_incident_log_data` | Details | **mtime 缓存**，返回全量 data+columns |
| `load_geojson` | lr-all.geo.json | 利比里亚边界 |

## 聚合
- `get_all_data()`：一次性返回 status/tt_quality/severity/sla_zte/sla_3rd/details/details_columns（各段独立 try，失败不阻断其余）。

## AI 分析（`analyze_with_ai`）
- 统一分发：provider ∈ {openai, deepseek, qianwen, glm, doubao, gemini, local}。
- openai 兼容类走 `_call_openai_compatible`；gemini 走独立接口；local/无 key 回退 `local_rules_summary`。
- 任意 provider 调用异常均回退本地规则，不抛 500。

## 虚拟助手
- `assistant_call` / `assistant_sms`：服务商由环境变量 `PHONE_SERVICE_PROVIDER` / `SMS_SERVICE_PROVIDER` 控制。
- 支持 twilio（需装 SDK+凭证）；aliyun/tencent 未启用时明确报错；默认 `none` 模拟模式返回成功。

## 改造点（相对原 Flask 版）
- `print` → `logging`
- 数据路径收敛到 `my_app/data/incident_overview/`
- 不引入 flask / openai SDK / python-dotenv；AI 调用统一用 `requests`
- 不迁移任何硬编码 API key（默认本地规则）

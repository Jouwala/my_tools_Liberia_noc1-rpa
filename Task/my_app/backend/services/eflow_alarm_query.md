# eflow_alarm_query.py 说明

## 作用
本地 `db/app.db` 的 `realtime_alarm` 只滚存约 48 小时，`history_alarm` 同步时又会过滤掉
没有 TT ID 的记录 —— 所以部分 TT 的 `alarm_id` 在本地库查不到。本模块直接调 eFlow 活接口
按 alarm_id 兜底查询，供 eflow_qa 页面的「告警信息」与 AI 分析入参使用。

## 接口（抓包参考 `url_aid.txt`）
| 顺序 | 接口 | 关键参数 |
| --- | --- | --- |
| 1 | `POST /api/fm-active/v1/activealarms/table` | `secondarycondition.id = alarm_id` |
| 2 | `POST /api/fm-history/v1/hisalarms/pageinfo` | `secondarycondition.id = alarm_id` + `condition.alarmraisedtime` 时间窗口 |

历史接口必须带告警发生时间窗口：有 TT 的 `alarm_occur_time` 时取「发生时刻前 3 天 ~ 现在」，
否则回退近 45 天（`_DEFAULT_BACK_DAYS`）。

## 返回
`find_alarm_by_id(alarm_id, occur_time=None)` →
```json
{"found": true, "source": "eflow_active|eflow_history|", "row": {...}, "error": null,
 "elapsed_sec": 1.23, "cached": false}
```
`row` 的键名已用 `_clean_column_name` 清洗为 snake_case（`Site Attribute` → `site_attribute`），
与本地告警表列名一致，可直接喂给 `inspect_tt.build_skill_prompt` / `build_alarm_block`。

## 缓存
按 alarm_id 做进程内 TTL 缓存：命中 300s（`_CACHE_TTL_HIT`）、未命中 60s（`_CACHE_TTL_MISS`）。
`/tt-alarm` 与 `/tt-ai` 短时间内重复查同一单只打一次 eFlow。

## 依赖
`requirements_eflow_alarm_query.txt`（本模块无额外第三方依赖，复用 my_app 后端已有实现）。

## 自测
```bash
python -X utf8 -c "import sys; sys.path.insert(0,r'D:\01_RPA\Task\my_app'); \
from backend.services.eflow_alarm_query import find_alarm_by_id; \
print(find_alarm_by_id('1764204783913'))"
```

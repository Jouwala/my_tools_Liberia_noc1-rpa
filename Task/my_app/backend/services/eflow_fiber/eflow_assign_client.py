# -*- coding: utf-8 -*-
"""Fiber Break 派单客户端 —— **共用实现的薄转发层**（2026-10-28）。

## 为什么改成转发（而不是各写一份）

立项 5G 站点告警派单时发现：Fiber 的派单客户端与 5G 要用的能力**完全重叠**
（查实时告警、解析用户组 groupId、解析站点、调派单接口）。两份实现必然漂移 ——
实测教训（Fiber 少传 site/sitename 导致「接口回 success 但 TT 建不出」）就是
写在注释里的，复制一份就等于复制一份可能过期的教训。

故把实现收到 `backend/services/eflow_assign/eflow_assign_client.py`，
本模块只做**显式再导出**，保持既有导入路径
（`from backend.services.eflow_fiber import eflow_assign_client as client`）
与单测引用（`client.SiteIndex` / `client._norm_name` 等私有辅助）继续可用。

⚠ 私有辅助（下划线开头）一并转发：单测直接断言它们的行为
（见 `tests/test_fiber_assign.py`），它们是**判定口径的一部分**，不是私有实现细节。

## 关键接口（来源：`backend/services/eflow_fiber/url_test.txt`）

| 用途 | 方法 | 路径 |
| --- | --- | --- |
| 用户组（拿 groupId） | GET | `/api/fms-assign-svr/v1/wo/userGroupList` |
| 派单（建 TT） | POST | `/api/alarm-assign/manual/assign` |
| 站点搜索（ME→站点 ID/名） | POST | `/api/cmdb/v1/data/search/Site` |
| 实时告警 | POST | `/api/fm-active/v1/activealarms/table` |
"""
from backend.services.eflow_assign import eflow_assign_client as _shared

# 接口路径常量
ASSIGN_API_PATH = _shared.ASSIGN_API_PATH
GROUP_API_PATH = _shared.GROUP_API_PATH
SITE_SEARCH_API_PATH = _shared.SITE_SEARCH_API_PATH
ACTIVE_ALARM_API_PATH = _shared.ACTIVE_ALARM_API_PATH

# 请求头 / 响应解析辅助（探测脚本与单测会用到）
_referer = _shared._referer
_headers = _shared._headers
_json_or_none = _shared._json_or_none
_iso_now = _shared._iso_now
_val = _shared._val
_s = _shared._s

# 用户组 / 站点 / 告警查询 / 派单
fetch_user_groups = _shared.fetch_user_groups
resolve_group = _shared.resolve_group
site_name_from_me = _shared.site_name_from_me
resolve_site = _shared.resolve_site
fetch_active_alarms = _shared.fetch_active_alarms
fetch_active_alarms_by_codes = _shared.fetch_active_alarms_by_codes
fetch_alarm_by_id = _shared.fetch_alarm_by_id
build_assign_payload = _shared.build_assign_payload
assign_alarm = _shared.assign_alarm

# 站点索引
SiteIndex = _shared.SiteIndex

# 站点名归一化与近似匹配规则（判定口径的一部分，单测直接断言）
_norm_name = _shared._norm_name
_vowel_swap_only = _shared._vowel_swap_only
_only_digit_suffix_diff = _shared._only_digit_suffix_diff
_pick = _shared._pick

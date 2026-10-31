# -*- coding: utf-8 -*-
"""AP（Action Plan）模块。

定位：把"问题/风险/管理要求"变成可跟踪、可审核、可追溯的整改任务。

模块边界（与方案 `AP_Development_Plan.md` 的差异见 `AP_Plan_Review.md`）：
- 首版**只做个人下发**（按人 / 按 Escalation Matrix 的岗位），不做部门维度 ——
  项目里没有可用的部门主数据（`app.person.department` 全空）。
- 组织架构取 **Escalation Matrix**（21 人 / 4 级，含 email + 电话 + 汇报链）。
- 身份以**门户 username** 为唯一键，不重建用户库；`ap_user_profile` 只是身份扩展。
- 权限：`role=admin` 或 `ap_role=AP_MANAGER` 才能创建/下发，其余人只能处理派给自己的。
"""

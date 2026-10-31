# -*- coding: utf-8 -*-
"""AP 权限判定 —— 唯一实现，路由层只调用这里。

## 为什么不能复用 `backend/security.py::require_protected`

`require_protected` 的语义是「只有本机能改配置」：本机回环**一律放行**。
而门户反代下所有请求都来自回环（`security.py` 顶部注释），于是它对远程用户
**等于不设防**。AP 是"任何登录用户按关系授权"，必须按会话身份判：

    role=admin（门户管理员）            → ADMIN
    ap_user_profile.ap_role=AP_MANAGER  → AP_MANAGER
    其余                                → MEMBER

方案 8.1 的判断是对的：前端隐藏按钮不算鉴权，每个写接口都要在这里过一遍。
"""
from __future__ import annotations

ADMIN = "ADMIN"
AP_MANAGER = "AP_MANAGER"
MEMBER = "MEMBER"

# 能创建/下发/取消/改派的人
MANAGE_ROLES = (ADMIN, AP_MANAGER)


def effective_role(profile: dict, portal_role: str | None) -> str:
    """门户 role=admin 视作 ADMIN；否则看身份档案里的 ap_role。"""
    if (portal_role or "").lower() == "admin":
        return ADMIN
    role = str((profile or {}).get("ap_role") or MEMBER).upper()
    return role if role in (ADMIN, AP_MANAGER, MEMBER) else MEMBER


def keys(username: str, aliases=None) -> set[str]:
    """一个人可能被写成多个名字，判定时全部算"我"。

    Escalation Matrix 里只有英文姓名（`VarfeeSarnor`），门户账号是
    `varfee_sarnor1`。下发的人从组织架构里挑姓名，执行人用账号登录 ——
    若只按账号精确比对，任务会"派了但看不见"。所以：
    账号 + 组织姓名 + 显示名，任一命中都算本人（`_Ctx.alias_set`）。
    """
    out = {(username or "").strip().lower()}
    for a in (aliases or ()):
        a = str(a or "").strip().lower()
        if a:
            out.add(a)
    out.discard("")
    return out


def _hit(value, ks: set[str]) -> bool:
    return bool(value) and str(value).strip().lower() in ks


def can_manage(eff_role: str) -> bool:
    return eff_role in MANAGE_ROLES


def is_owner(task: dict, username: str, aliases=None) -> bool:
    return _hit(task.get("owner_username"), keys(username, aliases))


def is_reviewer(task: dict, username: str, aliases=None) -> bool:
    return _hit(task.get("reviewer_username"), keys(username, aliases))


def is_creator(task: dict, username: str, aliases=None) -> bool:
    return _hit(task.get("created_by"), keys(username, aliases))


def can_view(task: dict, username: str, eff_role: str, aliases=None) -> bool:
    """可见范围：管理员/AP Manager 全见；其余只看与自己有关的。"""
    if can_manage(eff_role):
        return True
    return (is_owner(task, username, aliases) or is_reviewer(task, username, aliases)
            or is_creator(task, username, aliases))


def can_act(task: dict, username: str, eff_role: str, action: str, aliases=None) -> bool:
    """动作级权限。**状态合法性不在这里判**（见 store.TRANSITIONS + 路由）。"""
    if action in ("edit", "dispatch", "cancel", "reassign"):
        return can_manage(eff_role) or is_creator(task, username, aliases)
    if action in ("accept", "start", "progress", "submit", "attach"):
        return is_owner(task, username, aliases) or can_manage(eff_role)
    if action in ("approve", "reject"):
        # 审核人不能审自己提交的完成申请（方案 2.3）；管理员例外但要求留痕
        if is_reviewer(task, username, aliases):
            return True
        return eff_role == ADMIN
    return False

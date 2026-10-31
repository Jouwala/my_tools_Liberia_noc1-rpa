# -*- coding: utf-8 -*-
"""AP 组织架构 —— 取自项目既有的 **Escalation Matrix**（升级机制）。

## 为什么用它

`AP_Plan_Review.md` 的缺口 A 是「项目没有部门主数据」：`app.person` 的
`department / position / office / *_leader` 列实测**全部为空**（137 行，非空 0 行）。
而 Escalation Matrix 恰好是一份**结构化的组织清单**：4 级、21 人，每行带
岗位（position）、姓名、Orange/Lonestar 电话、邮箱 —— 正好满足 AP 需要的
"派给谁 / 通知到谁 / 逾期往上报给谁"。

## 数据来源与同步

源表：`升级机制.xlsx`（Sheet1，表头 1 行 + 数据 21 行，LEVEL1–LEVEL4）。
门户侧已把它落到 `MsPortal/assets/data.js` 的 `escalation.rows`（逐格照抄，
连源表的空格/缺号/大小写都保留）。本模块把同一份数据内置为 `ORG_SEED`，
首次访问时种进 `ap_org_people`，之后可在库里改（`active` 停用某人不会丢数据）。

> ⚠️ **内置副本是刻意的**：my_app 不能依赖门户项目的 JS 文件（跨仓库、且门户
> 可能单独部署）。若源表更新，改 `ORG_SEED` 后清空 `ap_org_people` 重新种，
> 或直接在库里改 `ap_org_people`（两者以库为准）。

## 身份桥（这是"派给人"能成立的关键）

门户会话只带 `username`，Escalation Matrix 只有英文姓名，两者没有外键。实测可行
的匹配顺序：

1. `ap_org_people.username` 已人工绑定 → 直接用；
2. `username` 归一后与 `name_key` 相等（`varfee_sarnor1` → `varfeesarnor1` ≠
   `varfeesarnor`，所以还需要第 3 步）；
3. 前缀匹配（≥4 字符）：`franklinp` → `franklinpeter` ✓、`varfee_sarnor1` →
   `varfeesarnor`（先剥掉尾部数字再比）；
4. 经 `app.flm_team_information` 的 `eFlow Acount` 反查姓名：
   `fe_fe_128` → `Luogon Justin` → `luogonjustin` ✓（现场人员走这条）。

匹配不到就**建档但不阻塞**：显示名用 username 兜底，邮箱为空则不发邮件。
绝不能因为"没建档"就 403 —— 新用户第一次点进来就是死路。
"""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Optional

from backend.services.ap_manager import store

logger = logging.getLogger("ap.org")

# ========== Escalation Matrix（源：升级机制.xlsx / 门户 MsPortal/assets/data.js） ==========
# 字段顺序：level, position, name, orange, lonestar, email
ORG_SEED: list[tuple[str, str, str, str, str, str]] = [
    ("LEVEL1", "ZTEMSNOC", "ZTEMSNOC", "-0773777115/0774777115", "0555193438", "ZTENOC.olr@orange.com"),
    ("LEVEL1", "RAN Engineer", "NathanaelLATRO", "0777509528", "0881560337", "latro.nathanel@zte.com.cn"),
    ("LEVEL1", "MW Engineer", "PradeepSirirathna", "0772741600", "0887092721", "pradeep.gosthinadurage@zte.com.cn"),
    ("LEVEL1", "PSCore Engineer", "PountounyinyiEmmanuel", "0776291037", "0888291783", "pountounyinyi.emmanuel1@zte.com.cn"),
    ("LEVEL1", "CSCore Engineer", "ShekuSheriff", "0778699566", "0888563518", "sheku.sheriff@zte.com.cn"),
    # 源表此行的姓名与邮箱不同人（IP/DWDM/OLT 缺 Orange/LONESTAR，邮箱填的是同事）——
    # 逐格照抄，不"顺手修正"，否则与源表对不上（门户侧同一约定）。
    ("LEVEL1", "IP/DWDM/OLT Engineer", "Goni Mustapha", "", "", "samuel.sarpong@zte.com.cn"),
    ("LEVEL1", "VAS/OSG Engineer", "DjoumeneReussite", "0776291055", "888563686", "djoumene.reussite1@zte.com.cn"),
    ("LEVEL1", "OCS Engineer", "KonanAtchelo.Desire", "0771431174", "", "konanatchelo.desire@iwhalecloud.com"),
    # 同一岗的第二联系人（源表此行无 Position）
    ("LEVEL1", "", "dai.wenhao", "0770972123", "088 987 8310", "dai.wenhao@iwhalecloud.com"),
    ("LEVEL1", "SOC Manager", "ZeeshanMazhar", "0772360781", "0887479843", "zeeshan.mazhar2@zte.com.cn"),
    ("LEVEL1", "FLMsupervisor", "VarfeeSarnor", "0777777279", "0880522684", "varfee.sarnor@zte.com.cn"),
    ("LEVEL1", "FLMsupervisor", "FranklinPeter", "0772320622", "0888680221", "franklin.peter@zte.com.cn"),
    ("LEVEL1", "FLMsupervisor", "Festus Emmanuel", "0776559255", "0880382876", "festus.emmanuel1@zte.com.cn"),
    ("LEVEL1", "FLM ERA Engineer", "LuogonJustin", "0775503110", "0886503134", "justin.luogon@zte.com.cn"),
    ("LEVEL1", "SPMSManager", "GorsonPrinceT", "0778086806", "0888823616", "gorson.t@zte.com.cn"),
    ("LEVEL2", "NOCManager", "NathanielSeku", "0777733770", "0886501585", "nathaniel.seku@zte.com.cn"),
    ("LEVEL2", "FLMManager", "AhmedAbdulwahed", "0773224338", "0889232199", "ahmed.youssif@zte.com.cn"),
    ("LEVEL2", "BOManager", "PountounyinyiEmmanuel", "0776291037", "0888291783", "pountounyinyi.emmanuel1@zte.com.cn"),
    ("LEVEL3", "Local PD", "KouassiJeanPaulAKPOUE", "0772742123", "0881047316", "akpoue.paul@zte.com.cn"),
    ("LEVEL3", "Chinese TD", "Chenxibin", "0775961237", "", "chen.xibin@zte.com.cn"),
    ("LEVEL4", "Chinese PD", "Yasin(ZhangWanqing)", "0778201440", "0887929005", "zhang.wanqing3@zte.com.cn"),
]

LEVELS = [
    ("LEVEL1", "LEVEL 1 · Duty hotline & discipline engineers"),
    ("LEVEL2", "LEVEL 2 · NOC / FLM / BO Managers"),
    ("LEVEL3", "LEVEL 3 · Local PD / Chinese TD"),
    ("LEVEL4", "LEVEL 4 · Chinese PD"),
]

# 逾期/退回时往上一级升级的映射
ESCALATE_UP = {"LEVEL1": "LEVEL2", "LEVEL2": "LEVEL3", "LEVEL3": "LEVEL4", "LEVEL4": "LEVEL4"}


def name_key(raw) -> str:
    """姓名归一：只留字母数字并小写。

    `VarfeeSarnor` / `varfee_sarnor1` / `Varfee Sarnor` → `varfeesarnor*`，
    与 `services/person_name.py` 的姓名归一互补（那边处理 `Name(FE_FE_111)` 这类
    带工号后缀的写法，这里只解决"同一姓名不同书写格式"）。
    """
    return re.sub(r"[^a-z0-9]", "", str(raw or "").lower())


def _strip_tail_digits(key: str) -> str:
    return re.sub(r"\d+$", "", key)


def ensure_seed(conn=None) -> int:
    """组织表为空时种入 Escalation Matrix，返回种入行数（已存在则 0）。"""
    own = conn is None
    conn = conn or store.get_raw_connection()
    try:
        store.ensure_tables(conn)
        row = conn.execute(f"SELECT COUNT(*) FROM {store.T_ORG}").fetchone()
        if row and row[0]:
            return 0
        ts = store.now()
        for i, (level, position, name, orange, lonestar, email) in enumerate(ORG_SEED):
            conn.execute(
                f"INSERT INTO {store.T_ORG} (level, position, name, name_key, orange, lonestar, "
                "email, username, sort_order, active, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (level, position, name, name_key(name), orange, lonestar, email, None, i, ts),
            )
        conn.commit()
        logger.info("[ap.org] Escalation Matrix 已种入 %s 行", len(ORG_SEED))
        return len(ORG_SEED)
    finally:
        if own:
            conn.close()


def _flm_name_by_account(conn, username: str) -> Optional[str]:
    """经 FLM 花名册的 `eFlow Acount` 反查姓名（现场人员 `fe_fe_128` 这类账号）。

    `app.flm_team_information` 是 Excel 直导表，列名是 `unnamed_1..11`
    （`unnamed_5` = eFlow Acount、`unnamed_3` = 姓名）。列名不友好但它是目前
    唯一能把"登录账号"和"英文姓名"接起来的表，故加异常兜底：表不在/列变了就返回 None。
    """
    try:
        row = conn.execute(
            'SELECT "unnamed_3" FROM flm_team_information '
            'WHERE lower(trim("unnamed_5")) = ? LIMIT 1',
            (username.strip().lower(),),
        ).fetchone()
        return (row[0] or None) if row else None
    except (sqlite3.Error, Exception):  # noqa: BLE001  PG 的 UndefinedTable 等一并兜底
        return None


def _match_org(conn, username: str) -> Optional[dict]:
    """按 4 级优先级把人匹配到组织行，匹配不到返回 None。"""
    key = name_key(username)
    if not key:
        return None

    def _q(sql, params):
        try:
            return store.row_to_dict(conn.execute(sql, params).fetchone())
        except Exception:  # noqa: BLE001
            return {}

    base = f"SELECT * FROM {store.T_ORG} WHERE active = 1"
    # 1) 已人工绑定
    hit = _q(base + " AND lower(username) = ? LIMIT 1", (username.strip().lower(),))
    if hit:
        return hit
    # 2) 姓名归一后完全相等
    hit = _q(base + " AND name_key = ? LIMIT 1", (key,))
    if hit:
        return hit
    # 3) 前缀匹配（去掉尾部数字后再比，`varfee_sarnor1` → `varfeesarnor`）
    stem = _strip_tail_digits(key)
    if len(stem) >= 4:
        hit = _q(base + " AND name_key = ? LIMIT 1", (stem,))
        if hit:
            return hit
        hit = _q(base + " AND name_key LIKE ? LIMIT 1", (stem + "%",))
        if hit:
            return hit
    # 4) 经 FLM 花名册反查姓名（fe_fe_128 → Luogon Justin）
    flm_name = _flm_name_by_account(conn, username)
    if flm_name:
        fkey = name_key(flm_name)
        if fkey:
            hit = _q(base + " AND name_key = ? LIMIT 1", (fkey,))
            if hit:
                return hit
            if len(fkey) >= 4:
                hit = _q(base + " AND name_key LIKE ? LIMIT 1", (fkey + "%",))
                if hit:
                    return hit
    return None


def resolve_profile(conn, username: str, role: str = "viewer") -> dict:
    """取（必要时创建）当前登录用户在本模块的身份档案。

    **无记录不报错**：显示名用 username 兜底，`ap_role` 默认 MEMBER。
    管理员（门户 role=admin）另算，见 `permissions.effective_role()`。
    """
    username = (username or "").strip()
    if not username:
        return {"username": "", "display_name": "", "email": "", "ap_role": "MEMBER"}

    row = conn.execute(
        f"SELECT * FROM {store.T_PROFILE} WHERE lower(username) = ? LIMIT 1", (username.lower(),)
    ).fetchone()
    if row:
        return store.row_to_dict(row)

    org = _match_org(conn, username)
    ts = store.now()
    profile = {
        "username": username,
        "display_name": (org.get("name") if org else "") or username,
        "email": (org.get("email") if org else "") or "",
        "org_name": (org.get("name") if org else "") or "",
        "org_position": (org.get("position") if org else "") or "",
        "org_level": (org.get("level") if org else "") or "",
        "ap_role": "MEMBER",
    }
    conn.execute(
        f"INSERT INTO {store.T_PROFILE} (username, display_name, email, org_name, org_position, "
        "org_level, ap_role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (profile["username"], profile["display_name"], profile["email"], profile["org_name"],
         profile["org_position"], profile["org_level"], profile["ap_role"], ts, ts),
    )
    # 顺手把组织行绑上 username，下次直接命中第 1 条规则
    if org:
        conn.execute(f"UPDATE {store.T_ORG} SET username = ? WHERE id = ?", (username, org["id"]))
    conn.commit()
    logger.info("[ap.org] 新身份档案 %s → %s（%s）", username, profile["display_name"],
                profile["org_position"] or "未匹配组织")
    return profile


def list_org(conn) -> list[dict]:
    """按 level 分组的组织清单（前端选择人/岗位用）。"""
    ensure_seed(conn)
    rows = conn.execute(
        f"SELECT id, level, position, name, email, username, orange, lonestar "
        f"FROM {store.T_ORG} WHERE active = 1 ORDER BY sort_order"
    ).fetchall()
    return [store.row_to_dict(r) for r in rows]


def email_of(conn, username: str) -> str:
    """取某人的通知邮箱：身份档案优先，其次组织行，最后为空。"""
    if not username:
        return ""
    row = conn.execute(
        f"SELECT email FROM {store.T_PROFILE} WHERE lower(username) = ? LIMIT 1", (username.lower(),)
    ).fetchone()
    if row and row[0]:
        return str(row[0]).strip()
    org = _match_org(conn, username)
    return str((org or {}).get("email") or "").strip()


def escalate_targets(conn, level: str | None) -> list[dict]:
    """逾期/退回时该通知的上级（按 Escalation Matrix 的层级往上走一级）。"""
    nxt = ESCALATE_UP.get((level or "").upper())
    if not nxt:
        return []
    rows = conn.execute(
        f"SELECT name, email, username, position, level FROM {store.T_ORG} "
        "WHERE active = 1 AND level = ? ORDER BY sort_order", (nxt,)
    ).fetchall()
    return [store.row_to_dict(r) for r in rows]

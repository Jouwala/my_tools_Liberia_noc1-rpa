"""人员姓名规范化 —— 跨表 JOIN 的共用口径。

**为什么需要这个模块**：`person`（人员）与 `eflow_wo`（工单）之间**没有外键**，
`eflow_wo` 里也没有 person 的稳定 ID，只能按「姓名」匹配。但同一批姓名在两张表里
的写法并不一致（2026-10-16 实测 `db/app.db`）：

  | 出处                        | 样例                                        |
  | ---                         | ---                                         |
  | `person.name`               | `Mark D. Paye`                              |
  | `eflow_wo.last_processer`   | `Mark D. Paye(FE_FE_111)`（带员工号后缀）   |
  | `eflow_wo.current_handler`  | `P:Patrick Monday`（带 `P:` 前缀）          |
  | `eflow_wo.current_handler`  | `P:A,,P:B,P:C`（逗号分隔的多人，含空段）    |

若各调用点各写一套清洗规则，口径必然漂移 —— 「概览统计的数字」与「点进去的列表行数」
对不上（AGENTS.md 第三节 1b 明令禁止的不一致）。故本模块是唯一实现，所有
人员↔WO、人员↔站点的匹配都必须 import 它。

**实测效果**：规范化后 `last_processer` 的 11173 行里 10747 行（96%）能匹配到 person。

**字段语义出处**：`backend/routers/eflow_qa.py:1197-1259`（`P:` = 个人，`G:` = 群组；
TT 的 current_handler 可能一直停在群组池，真正指派到人要去看 WO 层）。
"""
from __future__ import annotations

import re

# 尾部括号后缀：`Mark D. Paye(FE_FE_111)` / `张三(12345)` → 去掉整段括号
_PAREN_SUFFIX = re.compile(r"\([^)]*\)")
# 前缀 `P:` / `G:`（个人 / 群组），可能出现多段，如 `P:G:xxx`
_PREFIX = re.compile(r"^\s*[PGpg]\s*[::]\s*")


def normalize_person_name(raw) -> str:
    """规范化人员姓名，用于跨表 JOIN。

    规则（按顺序，依据 `db/app.db` 实测差异）：
      1. 去尾部括号后缀 —— WO 里形如 ``Mark D. Paye(FE_FE_111)``；
      2. 去 ``P:`` / ``G:`` 前缀 —— ``current_handler`` 形如 ``P:Patrick Monday``；
      3. 合并内部多余空白、去掉首尾空白与逗号、统一小写。

    ⚠ **只用于匹配，不用于回显** —— 回显要用原始姓名（`person.name`），
    规范化结果（全小写、无括号）不是给人看的。本函数返回空串表示「无有效姓名」，
    调用方应据此跳过该条，不要拿空串去 JOIN（会匹配到一片空值）。

    保持一致性的要求：同一批数据的「概览统计」与「下钻列表」必须共用本函数，
    否则数字对不上。
    """
    if raw is None:
        return ""
    s = str(raw)
    s = _PAREN_SUFFIX.sub("", s)   # 1. 去括号后缀
    s = _PREFIX.sub("", s)         # 2. 去 P:/G: 前缀
    s = " ".join(s.split())        # 3. 折叠空白
    s = s.strip(" ,")              #    去首尾逗号（实测存在 `Ernest Feikai  Sherman,`）
    return s.lower()


def split_multi_person(raw) -> list[str]:
    """把可能是「逗号分隔的多人」字段拆成规范化后的姓名列表。

    `current_handler` / `last_processer` 实测可能是多人，如
    ``P:Ernest Feikai Sherman,,P:Darlington Rue,P:Varfee Sarnor`` ——
    有逗号连写、有空段（`,,`）。逐个拆开、规范化、去重、丢弃空串。

    返回值已去重且保持首次出现顺序；空输入返回 ``[]``。
    """
    if raw is None:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in str(raw).split(","):
        key = normalize_person_name(part)
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def person_name_matches(raw_field, target_key: str) -> bool:
    """判断一个多值字段（如 ``current_handler``）里是否含目标人员。

    ``target_key`` 必须是已规范化的姓名（``normalize_person_name`` 的输出）。
    供无法下推到 SQL 的场景（如纯 Python 过滤）使用；能下推 SQL 时应优先
    在 SQL 侧用同一套规则过滤，避免把上万行拉进内存。
    """
    if not target_key:
        return False
    return target_key in split_multi_person(raw_field)

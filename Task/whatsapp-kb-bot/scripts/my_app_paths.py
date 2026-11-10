# -*- coding: utf-8 -*-
r"""定位 my_app 根目录 —— 让脚本不绑死某一台机器的盘符。

## 为什么需要这个模块

`tt-analyze.py` / `export-tt-knowledge.py` / `eflow-live-tt.py` 原本都把
my_app 路径**写死**成 `Y:/Task/my_app`。`Y:` 是 `192.168.100.19` 那台机器的
E 盘网络映射（`\\192.168.100.19\e`），只在那套环境里成立。

2026-10-03 事故：把 whatsapp-kb-bot 拷到**另一台机器**（本机 .20）后，
`Y:` 虽然还挂着，但 `Y:\Task\my_app` 根本不存在（那台上 my_app 在 D 盘），
于是 TT 分析直接抛：

    Something went wrong while analyzing TT202610020060:
    [Errno 2] No such file or directory:
    'Y:/Task/my_app\\backend\\services\\eflow_rules\\eflow_TT_rules.xlsx'

注意报错里那个 **`/` 与 `\\` 混用**的路径 —— 它正是「硬编码正斜杠的盘符
+ os.path.join 反斜杠」拼出来的，是这个 bug 的指纹。

## 解析策略（按优先级）

1. 环境变量 `MY_APP_DIR` —— 显式指定，最高优先级，运维可随时覆盖；
2. **从本仓库自身位置推导** —— 本模块在 `<whatsapp-kb-bot>/scripts/` 下，
   my_app 与它同在 `Task/` 目录，即 `../../my_app`。这与盘符无关，
   拷贝到任何一台机器上都成立（前提是两台项目按仓库布局并排放）；
3. 候选盘符回退（`Y:` → `D:` → `C:`）—— 兼容「my_app 不在本仓库布局里」
   的历史部署。

命中后**校验关键文件确实存在**，而不是只看目录在不在 —— 目录存在但缺
规则表/工单库照样会让下游报那个含糊的 Errno 2，那正是我们要消灭的故障形态。
校验不过就继续试下一个候选；全都不过则抛一个**说清怎么办**的错误，
而不是把底层 Errno 2 原样抛给群里。
"""
from __future__ import annotations

import os
import sys

# 关键文件（相对 my_app 根）。任缺其一，TT 分析链路就跑不通。
_REQUIRED = (
    os.path.join('backend', 'services', 'eflow_rules', 'eflow_TT_rules.xlsx'),
)

# 工单库与规则表分开判断：工单库可能还没同步过来（新装机），
# 此时「级别规则能用」仍好过直接失败，故不把它列为硬性要求。
_OPTIONAL = (
    os.path.join('db', 'app.db'),
    os.path.join('backend', 'services', 'eflow_rules', 'eflow_push_rules.xlsx'),
)

_HERE = os.path.dirname(os.path.abspath(__file__))
# <whatsapp-kb-bot>/scripts -> <whatsapp-kb-bot> -> Task -> 与 my_app 同级
_SIBLING = os.path.abspath(os.path.join(_HERE, '..', '..', 'my_app'))

# 仓库根：scripts -> whatsapp-kb-bot -> Task -> 仓库根
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, '..', '..', '..'))


def _is_isolated_copy() -> bool:
    """本仓库是不是「便携副本」（根目录有 ISOLATED_COPY.flag）。

    便携副本（D:\\01_olbr_portal）必须**完全自包含**：它有自己的 my_app、
    自己的 app.db、自己的 runtime。若副本在找不到自己的 my_app 时回落到
    D:/01_RPA/Task/my_app，就会读到**生产库的工单数据** —— 数据串库，
    而且是静默的（查询能返回结果，只是结果是生产的）。

    所以副本里禁用一切「指向仓库之外」的候选；找不到就明确报错。
    主仓库没有这个 flag，行为与收口前完全一致。
    """
    return os.path.isfile(os.path.join(_REPO_ROOT, 'ISOLATED_COPY.flag'))


_CANDIDATES = (
    os.environ.get('MY_APP_DIR'),   # 1. 显式指定
    _SIBLING,                       # 2. 与本仓库并排（与盘符无关）
)

# 指向仓库之外的候选（历史部署的盘符）。便携副本下必须禁用 ——
# 见 _is_isolated_copy() 的说明：落到生产库是静默的数据串库。
if not _is_isolated_copy():
    _CANDIDATES += (
        r'Y:/Task/my_app',              # 3. 历史部署（.19 的 E 盘映射）
        r'D:/01_RPA/Task/my_app',       # 3. 本机 .20
        r'C:/01_RPA/Task/my_app',
    )


def _is_usable(root: str | None) -> bool:
    if not root or not os.path.isdir(root):
        return False
    return all(os.path.isfile(os.path.join(root, rel)) for rel in _REQUIRED)


def find_my_app_dir() -> str:
    """返回可用的 my_app 根目录（绝对路径）。找不到就抛错并说明怎么办。"""
    tried = []
    for cand in _CANDIDATES:
        if not cand:
            continue
        norm = os.path.abspath(cand)
        if norm in tried:
            continue
        tried.append(norm)
        if _is_usable(norm):
            return norm

    missing = _REQUIRED[0]
    hint = (
        '解决办法（任选其一）：\n'
        '  1. 设置环境变量 MY_APP_DIR 指向 my_app 根目录，例如：\n'
        f'       set MY_APP_DIR={_SIBLING}\n'
        '  2. 把 my_app 放到与本项目同级的位置（即 <工作区>/Task/my_app）。\n'
    )
    if _is_isolated_copy():
        # 副本不提供「指向仓库之外」的候选 —— 落到生产库是静默的数据串库。
        hint = (
            '解决办法（任选其一）：\n'
            '  1. 设置环境变量 MY_APP_DIR 指向 my_app 根目录，例如：\n'
            f'       set MY_APP_DIR={_SIBLING}\n'
            '  2. 把 my_app 放到与本项目同级的位置（即 <工作区>/Task/my_app）。\n'
            '（便携副本不会回落到仓库之外的路径 —— 那里是生产环境的数据。）\n'
        )
    raise FileNotFoundError(
        '找不到 my_app 目录（TT 分析需要它下面的规则表与工单库）。\n'
        '已尝试以下位置，均不可用：\n'
        + ''.join(f'  · {p}\n' for p in tried)
        + f'\n每个位置都要求存在：{missing}\n'
        + hint
    )


def apply_fallback_site_packages(my_app_dir: str) -> None:
    """把 my_app 的 Lib/site-packages 加入 sys.path（openpyxl 常装在那里）。

    本机 Python 的 site-packages 里没有 openpyxl，而 my_app 内嵌 venv 的 shim
    已失效，实测可用的是 my_app/Lib/site-packages。
    """
    fallback = os.path.join(my_app_dir, 'Lib', 'site-packages')
    if os.path.isdir(fallback) and fallback not in sys.path:
        sys.path.append(fallback)


def resolve(env_var: str, *rel_parts: str, default: str | None = None) -> str:
    """解析 my_app 下的某个路径，允许用 env_var 覆盖。

    覆盖时**不做存在性校验** —— 用户显式指定就该被尊重，错了由下游报错。
    """
    override = os.environ.get(env_var)
    if override:
        return override
    if default is not None:
        return default
    return os.path.join(find_my_app_dir(), *rel_parts)

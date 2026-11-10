# -*- coding: utf-8 -*-
r"""定位可用的 Python 解释器 —— 让脚本不绑死某一台机器的安装路径。

## 为什么需要这个模块

原先有 7 处各自硬编码同一个解释器路径：

    C:/Users/ZTEEMS/AppData/Local/Programs/Python/Python312/python.exe

涉及 `scripts/tt-analyze-http.py`、`scripts/run-py.mjs`、`src/tt.js`、
`src/eflowRules.js`、`src/sitealarms.js`、`src/siteattr.js`、
`src/ttsource.js`。那个路径在便携副本（`D:\01_olbr_portal`）上**同样存在**
（同一个 Windows 用户），所以副本表面上「能跑」—— 但副本自带
`runtime/python312/python.exe`，副本要能脱离本机 Python 安装独立运行，
就不该优先用系统安装。

2026-11-10：便携化收口。

## 解析策略（按优先级）

1. 环境变量 `TT_PYTHON` —— 显式指定，最高优先级，运维可随时覆盖；
2. **仓库自带的 runtime** —— `<仓库根>/runtime/python312/python.exe`。
   便携副本用它（副本根目录才有 `runtime/`），版本与系统安装一致（3.12.x），
   且 site-packages 齐备（实测含 openpyxl / pandas / sqlalchemy）；
3. **系统 Python 3.12** —— `C:/Users/<用户>/AppData/Local/Programs/Python/
   Python312/python.exe` 与 `C:/Python312/python.exe`。生产仓库靠这一档
   （它没有 `runtime/`）；
4. **my_app 内嵌 venv** —— `<仓库根>/Task/my_app/Scripts/python.exe`，
   最后兜底（3.13，与前两档大版本不同，只在前面的都缺时才启用）。

## 为什么不做「同步时改写」

硬编码路径也可以靠同步脚本改写成副本路径，但那样**同一份源码在两个目录
下内容不同**：复制、比对、diff 全都失真，改写脚本一旦漏改就是隐蔽故障。
从代码自身位置推导则两边共用同一份源码、行为等价 —— 这是本次收口的主线。

## 优先级为什么把「系统 Python」排在「my_app venv」前面

生产仓库的 bot 一直用系统 Python 3.12 运行；my_app 内嵌 venv 是 3.13，
大版本不同。收口是便携化改造，**不应顺带改变生产的行为**，所以 venv 只作
兜底。便携副本没有 `runtime/` 时会落到系统 Python，与生产行为一致。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# scripts/python_path.py -> scripts -> whatsapp-kb-bot -> Task -> 仓库根
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]

# 候选的解释器（按优先级）。路径一律从仓库根推导，与盘符无关。
_CANDIDATES = (
    _REPO_ROOT / 'runtime' / 'python312' / 'python.exe',   # 便携副本自带
    Path(r'C:/Users/ZTEEMS/AppData/Local/Programs/Python/Python312/python.exe'),
    Path(r'C:/Python312/python.exe'),
    _REPO_ROOT / 'Task' / 'my_app' / 'Scripts' / 'python.exe',  # venv 兜底
)


def _is_usable(path: Path) -> bool:
    """文件存在即可用 —— 真正的可用性由调用方的 import 失败来暴露。"""
    try:
        return path.is_file()
    except OSError:
        return False


def candidates() -> list[str]:
    """返回候选解释器路径列表（按优先级，含 TT_PYTHON 覆盖）。

    给「需要额外依赖的解释器」用 —— 比如 eflow-live-alarms.py 要找的是
    **带 pandas + sqlalchemy** 的解释器，光有文件不够，还要逐个探测。
    这类调用方拿本列表去探测，胜过自己再抄一份候选表。
    """
    override = os.environ.get('TT_PYTHON')
    if override:
        return [override]
    return [str(c) for c in _CANDIDATES]


def resolve_python() -> str:
    """返回可用的 Python 解释器路径（字符串）。找不到就抛错并说明怎么办。"""
    override = os.environ.get('TT_PYTHON')
    if override:
        return override

    tried = []
    for cand in _CANDIDATES:
        norm = str(cand)
        if norm in tried:
            continue
        tried.append(norm)
        if _is_usable(cand):
            return norm

    raise FileNotFoundError(
        '找不到可用的 Python 解释器。\n'
        '已尝试以下位置，均不可用：\n'
        + ''.join(f'  · {p}\n' for p in tried)
        + '解决办法（任选其一）：\n'
        '  1. 设置环境变量 TT_PYTHON 指向 python.exe，例如：\n'
        f'       set TT_PYTHON={_REPO_ROOT / "runtime" / "python312" / "python.exe"}\n'
        '  2. 把便携 runtime 放到仓库根的 runtime/python312/ 下。\n'
    )


if __name__ == '__main__':
    # 自检：打印解析结果，便于运维一眼确认用的是哪个解释器。
    # 用目标解释器自己报版本 —— 当前进程的解释器不是答案。
    import subprocess
    target = resolve_python()
    print(f'resolved: {target}')
    try:
        out = subprocess.run(
            [target, '-c', 'import sys;print(sys.version.split()[0])'],
            capture_output=True, text=True, timeout=30,
        )
        print(f'version:  {out.stdout.strip() or out.stderr.strip()}')
    except Exception as e:  # noqa: BLE001 — 自检脚本，失败也要说清
        print(f'version:  <probe failed: {e}>')

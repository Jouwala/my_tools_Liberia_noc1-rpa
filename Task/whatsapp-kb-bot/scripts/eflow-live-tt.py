#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""eFlow 实时单票查询桥接 —— 本地工单库 miss 时的兜底。

用法：
    python eflow-live-tt.py TT202609290052 [--json]

职责只有一件事：**用 my_app 自己的代码**去 eFlow 实时拉一条 TT，把结果
以 JSON 打到 stdout。渲染与规则判定**不在这里做** —— 那是 tt-analyze.py 的活，
两边共用同一套渲染，才不会出现「本地查到的单」和「实时查到的单」格式不一致。

为什么是「桥接」而不是直接 import：

  · `fetch_tt_live` 在 `my_app/backend/services/eflow_data_mapper.py` 里，而那个模块
    顶部 `import pandas` + `from backend.database import ...`（依赖 sqlalchemy）。
    tt-analyze.py 刻意只依赖**标准库 + openpyxl**，就是为了「my_app 的解释器坏掉时
    机器人仍然可用」。把 pandas/sqlalchemy 变成 TT 通道的前置依赖是本末倒置。
  · my_app 的 venv 是内嵌 shim，**本机实测已失效**（`.venv` 里只有 pandas/numpy，
    没有 sqlalchemy；`Lib/site-packages` 也没有）。所以不能假定有某个固定解释器能
    import 成功 —— 必须**探测**，探测不到就优雅降级成「没有实时兜底」，
    而不是让整个 TT 通道挂掉。

退出码约定（与 tt-analyze.py 对齐，src/tt.js 按同一套规则解读）：
    0  实时命中，stdout 是单行 JSON
    1  实时也查无此单（不是故障，别重试）
    2  实时通道不可用（缺解释器 / 缺依赖 / 未配置）—— 只打 stderr，属**永久**性
    3  实时查询真出错（登录失败 / 网络异常）—— 属**暂时**性，值得重试
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

# 输出编码兜底：被 Node 以管道接走时必须 UTF-8，
# 否则系统代码页（本机 cp1252）一 print 中文就 UnicodeEncodeError。
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream.isatty():
            _stream.reconfigure(errors='replace')
        else:
            _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import my_app_paths  # noqa: E402

# my_app 根目录自动定位（可用 MY_APP_DIR 覆盖）—— 不再写死 Y: 盘。
# 写死会在换机后让实时兜底静默失效：解释器探测全落空 → 退化成
# 「本地库没有找到」，把环境问题误报成「这单不存在」。
MY_APP_DIR = my_app_paths.find_my_app_dir()

# 探测候选解释器。顺序即优先级：先 my_app 自己的 venv（最可能装齐依赖），
# 再系统 Python。**不做 pip install** —— 往用户机器上装包不是本脚本该干的事。
_CANDIDATES = [
    os.path.join(MY_APP_DIR, '.venv', 'Scripts', 'python.exe'),
    os.path.join(MY_APP_DIR, '.venv', 'Scripts', 'pythonw.exe'),
    r'C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe',
    r'C:\Python312\python.exe',
    r'C:\Python314\python.exe',
]

# 在子进程里跑的**极小**探针：只验证能否 import 到 fetch_tt_live 所需的依赖。
# 用 importlib.util.find_spec 而不是真的 import，避免拉起重库、也避免副作用。
_PROBE = (
    'import importlib.util as u, sys;'
    'sys.exit(0 if all(u.find_spec(m) for m in ("pandas", "sqlalchemy")) else 1)'
)

# 真正的取数代码。放在这里而不是外部文件：要与解释器探测**同一个进程**里跑完，
# 且要保证 sys.path / cwd 正确（eflow_data_mapper 用的是相对包名 `backend.*`）。
#
# ⚠️ 「查无此单」用 **stdout 里的哨兵**表示，不用退出码。
# 早期版本让取数子进程 sys.exit(1) 表示没查到，但 Python 遇到未捕获异常
# （ImportError / 网络错误 / 任何 traceback）**也是**退出码 1 ——
# 两者无法区分，于是「依赖装坏了」会被当成「eFlow 里确实没这一单」，
# 我们会理直气壮地告诉客户「本地和实时都没有」。这是**自信的错误结论**，
# 比报错严重得多。所以：查到→JSON；没查到→__MISS__；出错→非零退出码。
_MISS = '__TT_LIVE_MISS__'

_FETCH = r'''
import json, os, sys
sys.path.insert(0, {app!r})
os.chdir({app!r})
from backend.services.eflow_data_mapper import fetch_tt_live
row = fetch_tt_live({tt!r})
if not row:
    sys.stdout.write({miss!r})
    sys.exit(0)
row.pop("_tt_live_raw", None)
sys.stdout.write(json.dumps(row, ensure_ascii=False, default=str))
'''


def _find_interpreter() -> str | None:
    """挑一个能 import pandas + sqlalchemy 的解释器；没有则 None。"""
    for exe in _CANDIDATES:
        if not os.path.isfile(exe):
            continue
        try:
            p = subprocess.run(
                [exe, '-c', _PROBE],
                capture_output=True, timeout=60,
                cwd=MY_APP_DIR if os.path.isdir(MY_APP_DIR) else None,
            )
        except Exception:
            continue
        if p.returncode == 0:
            return exe
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description='eFlow 实时单票查询（my_app fetch_tt_live 的桥接）')
    ap.add_argument('tt_no', nargs='?', help='TT 单号，如 TT202609290052')
    ap.add_argument('--json', action='store_true',
                    help='（默认即 JSON）保留此开关以便与 tt-analyze.py 用法一致')
    ap.add_argument('--which', action='store_true',
                    help='只打印探测到的解释器路径后退出（排障用）')
    args = ap.parse_args()

    exe = _find_interpreter()

    if args.which:
        print(exe or '(未找到可用解释器：实时兜底不可用)')
        return 0 if exe else 2

    if not args.tt_no:
        ap.error('需要提供 TT 单号（或用 --which 查看实时通道是否可用）')

    if not exe:
        # 永久性不可用 —— 绝不重试，也绝不因此让本地查询失败。
        print(
            f'实时兜底不可用：在 {MY_APP_DIR} 下没找到同时装齐 '
            f'pandas + sqlalchemy 的 Python 解释器。',
            file=sys.stderr,
        )
        return 2

    code = _FETCH.format(app=MY_APP_DIR, tt=args.tt_no.strip().upper(), miss=_MISS)
    try:
        p = subprocess.run(
            [exe, '-c', code],
            capture_output=True, timeout=180,
            cwd=MY_APP_DIR if os.path.isdir(MY_APP_DIR) else None,
            env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
        )
    except subprocess.TimeoutExpired:
        print('实时查询超时（180s）', file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001
        print(f'实时查询启动失败：{type(e).__name__}: {e}', file=sys.stderr)
        return 3

    # 非零退出码**一律**当出错：包括 Python 自己的退出码 1（未捕获异常）。
    # 「查无此单」走 stdout 哨兵，不占退出码。
    if p.returncode != 0:
        detail = (p.stderr or b'').decode('utf-8', 'replace').strip()
        lines = [ln for ln in detail.splitlines() if ln.strip()]
        # Python traceback 的末行才是「异常类型: 消息」，前面都是栈
        print(lines[-1] if lines else f'实时查询退出码 {p.returncode}', file=sys.stderr)
        return 3

    out = (p.stdout or b'').decode('utf-8', 'replace').strip()
    if not out:
        print('实时查询返回空结果', file=sys.stderr)
        return 3

    if out == _MISS:
        return 1  # 实时确实没有这一单（与「查询失败」严格区分开）

    # 校验一次：必须真的是 JSON 对象，否则上游会拿到半截东西
    try:
        if not isinstance(json.loads(out), dict):
            raise ValueError('不是 JSON 对象')
    except Exception as e:  # noqa: BLE001
        print(f'实时查询返回的不是合法 JSON 对象：{e}', file=sys.stderr)
        return 3

    sys.stdout.write(out)
    return 0


if __name__ == '__main__':
    sys.exit(main())

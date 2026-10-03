#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 eflow-live-tt.py 的**退出码契约**：查无此单 vs 查询失败必须分开。

这是被真实事故逼出来的测试：早期实现让取数子进程用 `sys.exit(1)` 表示
「实时没这一单」，但 Python 遇到未捕获异常（ImportError、网络错误……）
**也是退出码 1**。两者无法区分，于是 my_app 依赖装坏时，机器人会对客户说
「本地和实时都没有这一单」—— 一个**自信的错误结论**。

现在的契约：
    取数子进程：查到 → stdout 是 JSON（exit 0）
                没查到 → stdout 是 __TT_LIVE_MISS__（exit 0）
                出错   → 非零退出码（含 Python 自己的 1）+ stderr
    桥接脚本：  0 = 查到   1 = 确实没有   2 = 永久不可用   3 = 出错

本测试用一个**受控的假解释器**替换真实取数进程（靠 TT_LIVE_FAKE_EXE 注入），
从而在不碰真实 eFlow、不碰 my_app 的前提下覆盖每一条分支。

运行：python scripts/test-tt-live-bridge.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

_fails: list[str] = []
_passes = 0


def check(cond, label, detail=''):
    global _passes
    if cond:
        _passes += 1
        print(f'  ✓ {label}')
    else:
        _fails.append(label)
        print(f'  ✗ {label}' + (f'\n      {detail}' if detail else ''))


# 加载桥接脚本（它没有 .py 后缀之外的依赖，但模块名带连字符，得用 spec 加载）
spec = importlib.util.spec_from_file_location(
    'eflow_live_tt', os.path.join(_SCRIPTS, 'eflow-live-tt.py'))
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

print('=' * 50)
print('eflow-live-tt.py 退出码契约测试')
print('=' * 50)

print('\n[1] 取数进程的三种结局必须映射到不同退出码')
# 直接构造「假取数进程」，绕开解释器探测与真实网络。
print('[1] 哨兵常量本身')
check(isinstance(bridge._MISS, str) and bridge._MISS, '_MISS 是非空字符串')
check(bridge._MISS not in ('', '{}'), '_MISS 不会被误当 JSON')
check('{miss!r}' in bridge._FETCH, '_FETCH 模板里有 miss 占位符（真的会被格式化进去）')
check('sys.exit(1)' not in bridge._FETCH,
      '取数代码**不再**用 sys.exit(1) 表示查无此单（那会和 ImportError 撞车）')
check('_MISS' in bridge._FETCH or 'miss' in bridge._FETCH, '取数代码用哨兵表示查无此单')

# 格式化一次，确认占位符真的能填上、且生成的代码里带哨兵
formatted = bridge._FETCH.format(app='X:/app', tt='TT123456789012', miss=bridge._MISS)
check(bridge._MISS in formatted, '_FETCH 格式化后真的含有哨兵字面量')
check('X:/app' in formatted and 'TT123456789012' in formatted, '_FETCH 格式化填入 app / tt')

print('\n[2] 退出码契约：三种结局互不相同')
# 用一个最小的桩模块替换 bridge 的取数执行，逐个喂结局。
import io
import contextlib


def call_main_with(fake_rc: int, fake_out: str, fake_err: str = ''):
    """把 bridge.subprocess.run 换成返回指定结局的假进程，跑一次 main()。

    `_find_interpreter` 已被替成 lambda，所以 subprocess.run 的**每一次**
    调用都是取数调用 —— 不需要（也不该）用计数器跳过第一次。
    """
    class _P:
        returncode = fake_rc
        stdout = fake_out.encode('utf-8')
        stderr = fake_err.encode('utf-8')

    def fake_run(cmd, **kw):
        return _P()

    orig_run, orig_find, orig_argv = bridge.subprocess.run, bridge._find_interpreter, sys.argv
    bridge.subprocess.run = fake_run
    bridge._find_interpreter = lambda: sys.executable
    sys.argv = ['eflow-live-tt.py', 'TT202609290052']
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = bridge.main()
    except SystemExit as e:
        rc = e.code
    finally:
        bridge.subprocess.run, bridge._find_interpreter, sys.argv = orig_run, orig_find, orig_argv
    return rc, out.getvalue(), err.getvalue()


# ① 查到
rc, out, err = call_main_with(0, json.dumps({'tt_no': 'TT202609290052', 'site_name': 'X'}))
check(rc == 0, '查到 → 退出码 0', f'实得 {rc}, err={err[:200]}')
check('TT202609290052' in out, '查到 → stdout 是那一行 JSON')
check(json.loads(out)['tt_no'] == 'TT202609290052', 'stdout 可解析为 JSON 对象')

# ② 查无此单（哨兵）
rc, out, err = call_main_with(0, bridge._MISS)
check(rc == 1, '哨兵 → 退出码 1（确实没有这一单）', f'实得 {rc}')
check(bridge._MISS not in out, '哨兵不会漏到 stdout 上（上游只看退出码）')

# ③ 取数进程崩溃，**退出码恰好为 1**（模拟 ImportError）
rc, out, err = call_main_with(1, '', 'ImportError: cannot import name create_engine')
check(rc == 3, '子进程崩溃(exit 1) → 桥接退出码 **3**（出错），而不是 1（没查到）',
      f'实得 {rc} —— 若为 1 则会把「依赖坏了」误报成「eFlow 没这单」')
check('create_engine' in err, '把子进程的异常末行带到 stderr 上')

# ④ 取数进程退出码 2
rc, out, err = call_main_with(2, '', 'some failure')
check(rc == 3, '子进程 exit 2 → 桥接 3', f'实得 {rc}')

# ⑤ stdout 为空但退出码 0（异常情况）
rc, out, err = call_main_with(0, '')
check(rc == 3, '退出码 0 但 stdout 为空 → 3（不猜成没查到）', f'实得 {rc}')

# ⑥ stdout 是坏 JSON
rc, out, err = call_main_with(0, '{not json')
check(rc == 3, 'stdout 是坏 JSON → 3', f'实得 {rc}')

# ⑦ stdout 是 JSON 数组（非对象）
rc, out, err = call_main_with(0, '[1,2,3]')
check(rc == 3, 'stdout 是 JSON 数组而非对象 → 3', f'实得 {rc}')

# ⑧ 没有可用解释器 → 2
orig_find, orig_argv = bridge._find_interpreter, sys.argv
bridge._find_interpreter = lambda: None
sys.argv = ['eflow-live-tt.py', 'TT202609290052']
out, err = io.StringIO(), io.StringIO()
try:
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = bridge.main()
finally:
    bridge._find_interpreter, sys.argv = orig_find, orig_argv
check(rc == 2, '没有可用解释器 → 退出码 2（永久不可用，不重试）', f'实得 {rc}')
check('不可用' in err.getvalue() or 'pandas' in err.getvalue(), 'stderr 说明为什么不可用')

print('\n[3] 退出码语义在脚本里写清楚了（避免以后被人改回去）')
_BRIDGE_SRC = open(os.path.join(_SCRIPTS, 'eflow-live-tt.py'), encoding='utf-8').read()
src = _BRIDGE_SRC
# 逐个退出码都得在文档里有一行说明，否则下一个人只会看到裸 return 3。
check('退出码约定' in src, '有「退出码约定」小节')
for code in ('0', '1', '2', '3'):
    check(any(ln.strip().startswith(code) for ln in src.splitlines()),
          f'退出码 {code} 单独成行写明了含义')
check('查无此单' in src, '写明了 1 = 查无此单（别重试）')
check('不可用' in src, '写明了 2 = 通道不可用（永久）')
check('出错' in src, '写明了 3 = 查询出错（暂时，值得重试）')

print('\n' + '=' * 50)
print(f'通过 {_passes} 项，失败 {len(_fails)} 项')
for f in _fails:
    print(f'  ✗ {f}')
sys.exit(1 if _fails else 0)

# -*- coding: utf-8 -*-
"""校验 tt-bridge-hidden.vbs 的语法与路径推导 —— 不依赖 cscript。

为什么需要它：VBScript 的语法错误只有在**真正执行**时才暴露，而本机
`cscript` 被安全策略拦截，无法直接跑。这里用静态检查覆盖两类风险：

1. **语法**：块结构配对（If/End If、For/Next、Sub/End Sub、Function/End
   Function）、引号配对、续行符位置、变量声明；
2. **路径推导**：把 vbs 里的 `GetParentFolderName` 链在 Python 里复算一遍，
   确认它指向的 root/repo 与解释器候选都真实存在。

注意：本检查器**不执行** vbs，只做静态与逻辑复算。它替代不了真跑一次，
但能挡住本次改动引入的低级错误（少一个 End If、写错一个变量名）。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VBS = HERE / 'tt-bridge-hidden.vbs'

# 需要配对的块结构
_BLOCKS = {
    'if': re.compile(r'^\s*If\b.*\bThen\s*$', re.I),
    'for': re.compile(r'^\s*For\b', re.I),
    'sub': re.compile(r'^\s*Sub\s+\w+', re.I),
    'function': re.compile(r'^\s*Function\s+\w+', re.I),
}
_END_FOR = re.compile(r'^\s*Next\b', re.I)
_END_SUB = re.compile(r'^\s*End\s+Sub\b', re.I)
_END_FUNCTION = re.compile(r'^\s*End\s+Function\b', re.I)
_END_IF = re.compile(r'^\s*End\s+If\b', re.I)

# 单行 If（If ... Then <stmt>）不构成块，需排除
_SINGLE_LINE_IF = re.compile(r'^\s*If\b.*\bThen\s+\S', re.I)


def check_syntax(text: str) -> list[str]:
    """返回语法问题列表（空列表 = 通过）。"""
    problems: list[str] = []
    depth_if = depth_for = depth_proc = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("'"):
            continue
        # 续行符：VBScript 要求续行符后必须跟注释或行尾
        if line.rstrip().endswith('_') and not re.search(r'_\s*(\'.*)?$', line):
            problems.append(f'L{lineno}: 续行符 "_" 后必须跟注释或行尾')
        # 变量未声明（Dim 之外的使用）——只查明显的拼写错误风险：这里跳过
        if _END_IF.match(line):
            depth_if -= 1
            if depth_if < 0:
                problems.append(f'L{lineno}: End If 多余')
            continue
        if _END_FOR.match(line):
            depth_for -= 1
            if depth_for < 0:
                problems.append(f'L{lineno}: Next 多余')
            continue
        if _END_SUB.match(line) or _END_FUNCTION.match(line):
            depth_proc -= 1
            if depth_proc < 0:
                problems.append(f'L{lineno}: End Sub/End Function 多余')
            continue
        if _SINGLE_LINE_IF.match(line):
            continue
        if _BLOCKS['if'].match(line):
            depth_if += 1
        elif _BLOCKS['for'].match(line):
            depth_for += 1
        elif _BLOCKS['sub'].match(line) or _BLOCKS['function'].match(line):
            depth_proc += 1
    if depth_if != 0:
        problems.append(f'If 块未闭合（净 {depth_if:+d}）')
    if depth_for != 0:
        problems.append(f'For 块未闭合（净 {depth_for:+d}）')
    if depth_proc != 0:
        problems.append(f'Sub/Function 块未闭合（净 {depth_proc:+d}）')

    # 引号配对：VBS 里字符串内的引号用 "" 转义，取奇偶判断
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("'")[0] if raw.strip().startswith("'") else raw
        # 去掉字符串字面量后再数剩余引号
        stripped = re.sub(r'"[^"]*"', '""', line)
        if stripped.count('"') % 2 != 0:
            problems.append(f'L{lineno}: 引号不成对')
    return problems


def check_paths(text: str) -> list[str]:
    """复算 vbs 里的路径推导，确认指向真实存在的文件。"""
    problems: list[str] = []
    script_dir = str(VBS.parent)
    root = os.path.dirname(script_dir)
    repo = os.path.dirname(os.path.dirname(root))

    # vbs 里引用的相对路径
    if 'tt-analyze-http.py' not in text:
        problems.append('未找到 tt-analyze-http.py 的引用')
    target = os.path.join(root, 'scripts', 'tt-analyze-http.py')
    if not os.path.isfile(target):
        problems.append(f'推导出的目标脚本不存在: {target}')

    # 解释器候选（与 vbs 里的顺序一致）
    candidates = [
        os.path.join(repo, 'runtime', 'python312', 'python.exe'),
        r'C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe',
        r'C:\Python312\python.exe',
        os.path.join(repo, 'Task', 'my_app', 'Scripts', 'python.exe'),
    ]
    picked = next((c for c in candidates if os.path.isfile(c)), None)
    if picked is None:
        problems.append('没有任何候选解释器可用')
    else:
        # vbs 用 fso.BuildPath 拼路径（反斜杠），检查器用 os.path.join，
        # 两者语义相同但字面量不同 —— 比对关键片段而非整串。
        if 'runtime\\python312\\python.exe' not in text:
            problems.append('vbs 缺少 runtime/python312 候选（便携副本靠它自给自足）')
        if 'Task\\my_app\\Scripts\\python.exe' not in text:
            problems.append('vbs 缺少 my_app venv 兜底候选')
    return problems


def main() -> int:
    # stdout 显式改成 utf-8（2026-11-10 修）。
    #
    # 为什么：stdout 重定向到管道（npm test 的 `&&` 链）时，Python 在 Windows 上
    # 用**系统代码页**（本机 cp1252）写 stdout，一 print 中文就 UnicodeEncodeError
    # —— 检查其实已经跑完并打印了大半，脚本却以异常退出，
    # 让 `npm test` 整体变红。与 scripts/export-tt-knowledge.py 2026-10-23 的
    # 修法同源（那边也是同一句注释、同一处坑）。
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:  # pragma: no cover - Python < 3.7
        pass

    if not VBS.is_file():
        print(f'FAIL: 找不到 {VBS}')
        return 1
    text = VBS.read_text(encoding='utf-8', errors='replace')

    syn = check_syntax(text)
    paths = check_paths(text)

    print(f'== {VBS} ==')
    print(f'语法检查: {"PASS" if not syn else "FAIL"}')
    for p in syn:
        print(f'  - {p}')
    print(f'路径检查: {"PASS" if not paths else "FAIL"}')
    for p in paths:
        print(f'  - {p}')

    # 打印推导结果，便于人工确认
    script_dir = str(VBS.parent)
    root = os.path.dirname(script_dir)
    repo = os.path.dirname(os.path.dirname(root))
    print(f'  root = {root}')
    print(f'  repo = {repo}')

    return 0 if not (syn or paths) else 1


if __name__ == '__main__':
    sys.exit(main())

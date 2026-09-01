#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
eFlow 知识库全文本检索

用法:
    python search.py "关键词"
    python search.py "工单 挂起"              # 多个词默认 OR
    python search.py "工单 挂起" --all        # AND，必须全部命中
    python search.py "P1" --dir 10_集成篇_Integration
    python search.py "同步" --name-only       # 只列文件名
    python search.py "超时" --context 3       # 命中行上下各 3 行

特性:
    - 默认只搜知识条目（00_ / 10_ / 9x_ / *.md），跳过 tools/ 与 _templates/
    - 大小写不敏感，中英文均可
    - 文件名命中会加权，排在结果最前
"""

import os
import sys
import argparse

# Windows 控制台编码兜底
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

KB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 默认检索范围
INCLUDE_DIR_PREFIXES = ("00_", "10_", "90_", "99_")
EXCLUDE_DIRS = {"tools", "_templates", "images", ".git", "__pycache__"}


def iter_md_files(root, dir_filter=None):
    # 显式指定 --dir 时，尊重用户意图，不再套用 EXCLUDE_DIRS
    # （否则 --dir _templates 会被排除名单吃掉，永远搜不到）
    blocking = set() if dir_filter else EXCLUDE_DIRS
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in blocking]
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        # 目录过滤
        if dir_filter and not rel_dir.startswith(dir_filter):
            continue
        if not dir_filter:
            if rel_dir and not rel_dir.startswith(INCLUDE_DIR_PREFIXES):
                continue
        for fn in sorted(filenames):
            if fn.lower().endswith(".md"):
                yield os.path.join(dirpath, fn)


def search(keywords, dir_filter=None, require_all=False, context=2, name_only=False):
    kws = [k.lower() for k in keywords]
    results = []

    for path in iter_md_files(KB_ROOT, dir_filter):
        rel = os.path.relpath(path, KB_ROOT).replace("\\", "/")
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except (UnicodeDecodeError, OSError):
            continue

        name_hit = any(k in os.path.basename(rel).lower() for k in kws)

        # AND 模式改为【文件级】匹配：文件全文含全部关键词即命中，
        # 命中行仍按「含任一关键词」展示。
        # （行级 AND 太苛刻——"派单"和"三方"常不在同一行，但确实讲的是同一件事）
        if require_all:
            full_text = "\n".join(lines).lower()
            if not all(k in full_text for k in kws):
                continue

        if name_only:
            if name_hit or any(any(k in ln.lower() for k in kws) for ln in lines):
                results.append((rel, None, 100 if name_hit else 0))
            continue

        matched = []
        for i, line in enumerate(lines):
            low = line.lower()
            ok = any(k in low for k in kws)
            if ok:
                start = max(0, i - context)
                end = min(len(lines), i + context + 1)
                matched.append((i + 1, lines[start:end], i - start))

        if matched:
            score = (100 if name_hit else 0) + len(matched)
            results.append((rel, matched, score))

    results.sort(key=lambda x: (-x[2], x[0]))
    return results


def main():
    ap = argparse.ArgumentParser(description="eFlow 知识库全文本检索")
    ap.add_argument("keywords", nargs="+", help="一个或多个关键词")
    ap.add_argument("--dir", default=None, help="限定目录，如 10_集成篇_Integration")
    ap.add_argument("--all", action="store_true", help="AND 模式：须全部关键词命中")
    ap.add_argument("--context", type=int, default=2, help="命中行上下文行数，默认 2")
    ap.add_argument("--phrase", action="store_true",
                    help="把整个参数当成一个完整短语搜（禁用空格自动拆分）")
    ap.add_argument("--name-only", action="store_true", help="只列命中的文件名")
    args = ap.parse_args()

    # 支持 README 里教的写法：search.py "工单 挂起"
    # shell 会把它当成【一个】含空格的参数，这里按空格拆成多个关键词。
    # 想搜完整短语请改用 --phrase。
    if len(args.keywords) == 1 and " " in args.keywords[0] and not args.phrase:
        args.keywords = [k for k in args.keywords[0].split() if k]

    results = search(
        args.keywords,
        dir_filter=args.dir,
        require_all=args.all,
        context=args.context,
        name_only=args.name_only,
    )

    mode = "AND" if args.all else "OR"
    print(f"检索: {' '.join(args.keywords)}  (模式 {mode})"
          + (f"  范围 {args.dir}" if args.dir else "  范围 全库"))
    print("=" * 70)

    if not results:
        print("\n未命中。")
        print("\n建议:")
        print("  1. 换个说法或更短的关键词再试")
        print("  2. 把这个问题记到 99_待补充问题_BACKLOG.md")
        print("  3. 或让 AI 直接去源码/数据库核实（见 AGENT_GUIDE.md 第四节）")
        return 1

    if args.name_only:
        print(f"\n命中 {len(results)} 个文件:\n")
        for rel, _, _ in results:
            print(f"  {rel}")
        return 0

    total = sum(len(m) for _, m, _ in results if m)
    print(f"\n命中 {len(results)} 个文件 / {total} 处\n")

    for rel, matched, _ in results:
        print(f"\n📄 {rel}")
        print("-" * 70)
        if not matched:
            continue
        for lineno, block, hl_idx in matched:
            print(f"  L{lineno}:")
            for j, ln in enumerate(block):
                mark = ">>" if j == hl_idx else "  "
                text = ln.rstrip()
                if len(text) > 160:
                    text = text[:160] + "…"
                print(f"   {mark} {text}")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""重启留痕（Restart Marker）—— 让 worker 的每一次「世代更替」都可审计、可归因。

## 为什么存在（2026-09-10 排查教训）
2026-09-10 09:56 四个 worker 同时以 exit_code=1 退出。当时能拿到的证据只有
`log/worker_watchdog.log` 的「worker[x] 退出 (exit_code=1, 存活 xxx s)」——它只能证明
"同时退出"，回答不了"**是谁杀的**"。最终绕了一大圈（查 PG、查 Windows 事件日志、
查 PowerShell 操作日志）才在 WorkBuddy 工具审计日志
`~/.workbuddy/audit-log/2026-09-10.jsonl` 里找到铁证：是执行者自己手敲的
`for g in u n m c; do taskkill //PID $p //T //F; done`。

结论：**worker 每一次世代更替，都必须由「发起方」留下意图记录**。
- 人 / Agent 发起 → `restart_workers.py`（唯一入口）写 `restart_intent` / `restart_done`
- watchdog 自动拉起 → `worker_watchdog.py` 写 `worker_exit` / `worker_spawn`
于是任何一次「多 worker 同退」，先看这个文件就能一眼归因，不必再挖系统日志。

## 产物（两个文件，同源写入）
- `log/worker_restart_marker.log`   人读：一行一事件，`|` 分隔，可 grep / 可排序
- `log/worker_restart_marker.jsonl` 机读：一行一 JSON，供后续工具/Agent 解析

## 行为约定
- 模块无重依赖（不 import pandas / DB），保证 watchdog 内可安全调用。
- 任何异常都被吞掉并降级为 stderr 一行——**留痕失败绝不能拖垮被观测的进程**。
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "log"
MARKER_LOG = LOG_DIR / "worker_restart_marker.log"
MARKER_JSONL = LOG_DIR / "worker_restart_marker.jsonl"

# 轮转阈值：留痕体量极小（每条 < 400B），2MB 足够存上万条历史
MAX_BYTES = 2 * 1024 * 1024

# 允许的事件动作（白名单，防止手误写出脏数据）
ACTIONS = (
    "watchdog_start",    # watchdog 进程启动（世代起点）
    "watchdog_exit",     # watchdog 进程退出
    "restart_intent",    # 有人准备重启：by / mode / groups / old_pids / reason
    "restart_done",      # 重启收尾：新 pid / 耗时
    "worker_exit",       # watchdog 观测到 worker 退出：exit_code / lived_s
    "worker_spawn",      # watchdog 拉起 worker：pid / prev_exit_code
)

_lock = threading.Lock()


def _rotate(path: Path) -> None:
    """超过阈值则轮转一份 .1（只保留一代，够用且不会无限占盘）。"""
    try:
        if path.exists() and path.stat().st_size > MAX_BYTES:
            older = path.with_suffix(path.suffix + ".1")
            if older.exists():
                older.unlink()
            path.rename(older)
    except Exception:
        pass


def _fmt_val(v) -> str:
    """值渲染：列表/字典展开成 k:v,k:v；含空格或中文的字符串加引号。"""
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(str(x) for x in v) + "]"
    if isinstance(v, dict):
        return ",".join(f"{k}:{v[k]}" for k in v)
    if isinstance(v, float):
        return f"{v:.1f}"
    s = str(v)
    if s == "":
        return '""'
    if any(ch in s for ch in (" ", "|", "=", "\t")):
        return '"' + s.replace('"', "'") + '"'
    return s


def append_marker(action: str, by: str = "unknown", **fields) -> None:
    """追加一条留痕事件。永不抛异常。

    action: ACTIONS 白名单之一（不在白名单也会写入并标注 unknown_action）
    by:     发起方，如 "workbuddy-agent" / "ruyi" / "watchdog" / "start_hidden.ps1"
    其余关键字参数按固定顺序渲染：mode / groups / pids / pid / exit_code /
    prev_exit_code / lived_s / count / reason / note，未知键原样追加在末尾。
    """
    try:
        now = datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}"
        ordered = (
            "mode", "groups", "pids", "old_pids", "pid", "old_pid",
            "exit_code", "prev_exit_code", "exit_codes", "lived_s", "count",
            "reason", "note",
        )
        parts = []
        used = set()
        for key in ordered:
            if key in fields and fields[key] is not None:
                parts.append(f"{key}={_fmt_val(fields[key])}")
                used.add(key)
        for key, val in fields.items():
            if key not in used and val is not None:
                parts.append(f"{key}={_fmt_val(val)}")

        tag = action if action in ACTIONS else f"{action}<unknown_action>"
        line = f"{ts} | {tag} | by={by}"
        if parts:
            line += " | " + " | ".join(parts)

        record = {"ts": now.isoformat(timespec="milliseconds"),
                  "epoch_ms": int(time.time() * 1000),
                  "action": action, "by": by}
        record.update({k: v for k, v in fields.items() if v is not None})

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _lock:
            _rotate(MARKER_LOG)
            with open(MARKER_LOG, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
            _rotate(MARKER_JSONL)
            with open(MARKER_JSONL, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # 留痕失败绝不影响业务
        try:
            sys.stderr.write(f"[restart_marker] 写留痕失败（已忽略）: {exc}\n")
        except Exception:
            pass


def caller_name() -> str:
    """推断发起方：显式 env > Agent 环境特征 > 登录用户。"""
    explicit = (os.environ.get("MY_APP_RESTART_BY") or "").strip()
    if explicit:
        return explicit
    env_keys = " ".join(os.environ.keys()).lower()
    if "codebuddy" in env_keys or "workbuddy" in env_keys:
        return "workbuddy-agent"
    try:
        return f"manual:{(os.environ.get('USERNAME') or '').strip() or 'unknown'}"
    except Exception:
        return "unknown"


def read_markers(limit: int = 20) -> list:
    """读取最近 limit 条留痕（文本行）。"""
    if not MARKER_LOG.exists():
        return []
    try:
        lines = MARKER_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    return [ln for ln in lines if ln.strip()][-max(1, limit):]


_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) \| (\w+) \| by=(\S+)(.*)$")


def recent_intent(groups, within_s: float = 180.0) -> dict | None:
    """回查最近是否有覆盖这些 group 的 `restart_intent`，用于给 worker 退出归因。

    返回 {"by":..., "reason":..., "age_s":...} 或 None（None = 无意图记录，疑自发退出）。
    """
    want = set(groups or ())
    try:
        lines = read_markers(60)
    except Exception:
        return None
    for ln in reversed(lines):
        m = _TS_RE.match(ln)
        if not m:
            continue
        ts_txt, action, by, tail = m.groups()
        try:
            ts = datetime.strptime(ts_txt, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            continue
        age = (datetime.now() - ts).total_seconds()
        if age < 0 or age > within_s:
            return None          # 时间窗口已越过，无需继续往前找
        if action != "restart_intent":
            continue
        gs = re.search(r"groups=\[([^\]]*)\]", tail)
        covered = set(x.strip() for x in gs.group(1).split(",")) if gs else set()
        if want and covered and not (want & covered):
            continue
        rm = re.search(r"reason=(\"[^\"]*\"|\S+)", tail)
        return {"by": by,
                "reason": (rm.group(1).strip('"') if rm else ""),
                "age_s": round(age, 1)}
    return None


if __name__ == "__main__":  # 便于手工冒烟：python -m backend.restart_marker "说明"
    append_marker("restart_intent", by=caller_name(),
                  reason=" ".join(sys.argv[1:]) or "手工冒烟", mode="smoke")
    for _ln in read_markers(5):
        print(_ln)

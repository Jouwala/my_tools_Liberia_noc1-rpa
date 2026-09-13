# -*- coding: utf-8 -*-
"""auth_switch.py - 一键启停 uniplam 门户 + myapp 的用户鉴权（日常开发用）
=========================================================================

用法（在 D:/01_RPA 下执行）：

    python auth_switch.py status    # 查看当前开关
    python auth_switch.py off       # 关闭鉴权 -> /uniplam/ 与 /myapp/ 都免登录
    python auth_switch.py on        # 开启鉴权 -> 恢复正常登录校验
    python auth_switch.py toggle    # 反转当前状态

写入的是共享开关文件 ``D:/01_RPA/auth-switch.json``，门户（server/authSwitch.ts）
与 my_app（backend/auth_switch.py）读的是同一份文件，因此不会出现两边不一致。

**改完必须重启进程**（开关在进程启动时解析并缓存）：

    9267 门户   -> 重启门户 start.bat / start_hidden.ps1
    7038 后端   -> 重启 my_app start.bat / start_hidden.ps1

输出全部为 ASCII，避免 Windows 控制台编码问题。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FLAG_FILE = Path(__file__).resolve().parent / "auth-switch.json"

USAGE = """usage: python auth_switch.py <status|on|off|toggle>

  status    show current switch state
  on        enable auth  (restore login for /uniplam/ and /myapp/)
  off       disable auth (skip login, daily development only)
  toggle    flip current state
"""


def load() -> dict:
    if not FLAG_FILE.is_file():
        return {"authEnabled": True, "note": "created by auth_switch.py"}
    try:
        data = json.loads(FLAG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"authEnabled": True}
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] cannot parse {FLAG_FILE}: {exc}; treating as authEnabled=true")
        return {"authEnabled": True}


def save(enabled: bool, previous: dict) -> None:
    payload = dict(previous)
    payload["authEnabled"] = enabled
    payload["updatedAt"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    payload.setdefault(
        "note",
        "Shared auth switch for uniplam portal + myapp. "
        "authEnabled=false skips user login (daily development only). Restart 9267 and 7038 after change.",
    )
    FLAG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def report(data: dict) -> None:
    enabled = bool(data.get("authEnabled"))
    print(f"file    : {FLAG_FILE}")
    print(f"authEnabled : {enabled}")
    print(f"mode        : {'enforced (login required)' if enabled else 'bypass (login skipped)'}")
    if data.get("updatedAt"):
        print(f"updatedAt   : {data['updatedAt']}")
    print()
    if enabled:
        print("=> /uniplam/ and /myapp/ require login.")
    else:
        print("=> /uniplam/ and /myapp/ skip login. DEVELOPMENT ONLY - do not leave this on in production.")
    print("=> restart 9267 (portal) and 7038 (myapp backend) for the change to take effect.")


def main(argv: list[str]) -> int:
    action = (argv[1] if len(argv) > 1 else "status").strip().lower()
    data = load()

    if action == "status":
        report(data)
        return 0

    if action == "on":
        target = True
    elif action == "off":
        target = False
    elif action == "toggle":
        target = not bool(data.get("authEnabled"))
    else:
        print(USAGE)
        return 2

    save(target, data)
    print(f"[ok] auth {'ENABLED' if target else 'DISABLED'}")
    print()
    report(load())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

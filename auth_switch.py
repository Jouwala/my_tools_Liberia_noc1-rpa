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

**文件不存在 = 开启鉴权（安全默认），这不是故障。** 两个应用的解析顺序都是
「环境变量 AUTH_ENABLED > 开关文件 > 缺省 true」（门户 ``server/authSwitch.ts:10-13``、
my_app ``backend/auth_switch.py:8-12``），所以删掉/没有该文件时两侧一律走"要求登录"。
``status`` 会打印 ``exists`` 与 ``source``，用于区分"文件写着 true"和"文件根本不在"。

**``auth-switch.json.prev`` 是"上一次写入前的旧值"，不是"建议恢复的值"。**
2026-10-06 排查中发现该文件曾停在 2026-09-13（内容 ``authEnabled=false``）而主文件早已不在：
原因是门户侧写前会滚动备份、而本 CLI 此前不会，两个写入方行为不一致。
现已对齐（``save()`` 同样滚动备份 + 原子写）。**不要照抄 .prev 的内容去恢复配置** ——
它代表的恰恰是"被改掉的那一版"。

**改完必须重启进程**（开关在进程启动时解析并缓存）：

    9267 门户   -> 重启门户 start.bat / start_hidden.ps1
    7038 后端   -> 重启 my_app start.bat / start_hidden.ps1

输出全部为 ASCII，避免 Windows 控制台编码问题。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

FLAG_FILE = Path(__file__).resolve().parent / "auth-switch.json"
# 注意：不能对 auth-switch.json 用 with_suffix('.json.prev') —— Path.with_suffix 只认
# 「最后一个点之后」为后缀，会把 "auth-switch.json" 变成 "auth-switch.json.prev" 看似正确，
# 但一旦文件名里出现多个点就会错位。这里显式拼字符串，语义一目了然。
PREV_FILE = FLAG_FILE.parent / (FLAG_FILE.name + ".prev")

USAGE = """usage: python auth_switch.py <status|on|off|toggle>

  status    show current switch state
  on        enable auth  (restore login for /uniplam/ and /myapp/)
  off       disable auth (skip login, daily development only)
  toggle    flip current state
"""


def load() -> dict:
    if not FLAG_FILE.is_file():
        # 文件缺失不是错误：两侧的解析顺序都是「环境变量 > 文件 > 缺省 true」，
        # 没有文件 = 走缺省 = 开启鉴权（安全默认）。这里显式标记来源，
        # 避免运维看到 "authEnabled: True" 却分不清是"文件写着 true"还是"文件根本不在"。
        return {"authEnabled": True, "_source": "default", "note": "created by auth_switch.py"}
    try:
        data = json.loads(FLAG_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"authEnabled": True, "_source": "default"}
        data["_source"] = "file"
        return data
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] cannot parse {FLAG_FILE}: {exc}; treating as authEnabled=true")
        return {"authEnabled": True, "_source": "default"}


def save(enabled: bool, previous: dict) -> None:
    """写入开关文件；写前把上一版滚动备份为 ``.prev``，采用「临时文件 + 改名」原子写。

    2026-10-06 与门户侧 ``server/authSwitch.ts`` 的 ``setAuthEnabled()`` 对齐：
    那里早就承诺「写前把旧内容留成 auth-switch.json.prev」（见 AUTH_SWITCH.md 第 0 节），
    但本 CLI 此前直接覆写、**没有**这一步 —— 两个写入方行为不一致，导致用命令行改过之后
    ``.prev`` 会停留在更早的一份上，看着像"最近一次的旧值"，实际早已过期（本次排查
    就遇到：``.prev`` 停在 2026-09-13 且内容为 authEnabled=false，容易被人误当成恢复依据）。
    """
    payload = {k: v for k, v in previous.items() if not k.startswith("_")}
    payload["authEnabled"] = enabled
    payload["updatedAt"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    payload.setdefault(
        "note",
        "Shared auth switch for uniplam portal + myapp. "
        "authEnabled=false skips user login (daily development only). Restart 9267 and 7038 after change.",
    )

    # 滚动备份：仅在确实存在旧文件时留档（首次创建无需 .prev）
    if FLAG_FILE.is_file():
        try:
            os.replace(FLAG_FILE, PREV_FILE)
        except OSError as exc:  # noqa: BLE001
            print(f"[warn] cannot rotate backup {PREV_FILE}: {exc}")

    # 原子写：先写临时文件再改名，避免进程在写到一半时读到半截 JSON
    tmp = FLAG_FILE.parent / (FLAG_FILE.name + f".tmp_{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, FLAG_FILE)


def report(data: dict) -> None:
    enabled = bool(data.get("authEnabled"))
    source = data.get("_source", "file")
    print(f"file    : {FLAG_FILE}")
    print(f"exists      : {FLAG_FILE.is_file()}")
    print(f"authEnabled : {enabled}")
    print(f"source      : {source}" + ("  (file missing -> safe default: auth required)" if source == "default" else ""))
    print(f"mode        : {'enforced (login required)' if enabled else 'bypass (login skipped)'}")
    if data.get("updatedAt"):
        print(f"updatedAt   : {data['updatedAt']}")
    if data.get("updatedBy"):
        print(f"updatedBy   : {data['updatedBy']}")

    # 暴露 .prev：它是"上一次写入前的旧值"，不是"建议恢复的值"。
    # 若 .prev 比主文件旧很多，说明写入方（门户 / CLI）之间曾不一致，值得看一眼。
    if PREV_FILE.is_file():
        print(f"backup      : {PREV_FILE.name} (previous value, NOT a restore recommendation)")
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

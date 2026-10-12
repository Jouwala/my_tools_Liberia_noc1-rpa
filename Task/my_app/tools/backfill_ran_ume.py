# -*- coding: utf-8 -*-
"""RAN UME 日报补跑脚本（用于账号解锁后补齐缺失日期）。

背景（2026-10-12）：`NOC` 账号在 UME(10.100.28.27) 被锁定，导致
10-11、10-12 两天日报数据缺失，库里最新数据停在 2026-10-10。

为什么不需要「按日期补」：ran_ume_service 的 PM 查询用的是**滚动窗口**
（`_build_pm_payload`：start = now - days_back，config 里 days_back=7），
所以只要重跑一次 `run_ran_ume_full_task()`，10-11 与 10-12 会自动包含进来。
本脚本的价值在于**跑之前先确认账号已解锁**，避免：
  · 锁没解就重跑 → 又是一次失败 + 一封告警邮件；
  · 锁没解就反复重试 → 持续消耗 worker 与上游登录额度。

用法：
    python tools/backfill_ran_ume.py            # 先探测，解锁了才跑
    python tools/backfill_ran_ume.py --force    # 跳过探测，强制执行一次
    python tools/backfill_ran_ume.py --check    # 只探测账号状态，不跑任务
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

from backend.services.credential_store import get_credential  # noqa: E402
from backend.services import auth_manager as am  # noqa: E402

HOST, PORT = "10.100.28.27", 28001


def probe_account() -> tuple:
    """返回 (是否可用, 说明)。真实登录一次以确认账号状态。"""
    user, pwd = get_credential("zte_ume")
    try:
        am._do_login(HOST, PORT, user, pwd)
        return True, f"账号 {user} 登录成功，可以补跑"
    except Exception as e:
        return False, str(e)


def main() -> int:
    ap = argparse.ArgumentParser(description="RAN UME 日报补跑（账号解锁后补齐缺失日期）")
    ap.add_argument("--force", action="store_true",
                    help="跳过账号探测，强制执行任务")
    ap.add_argument("--check", action="store_true",
                    help="只探测账号状态，不执行任务")
    args = ap.parse_args()

    if not args.force:
        ok, detail = probe_account()
        print("[探测] %s" % detail)
        if args.check:
            return 0 if ok else 2
        if not ok:
            print("\n[中止] 账号当前不可用，重跑只会再失败一次并触发告警。")
            if "locked" in detail.lower() or "锁定" in detail:
                print("       请先联系 UME 管理员解锁 NOC 账号，解锁后再运行本脚本。")
            else:
                print("       请先核对 credential_store 中 zte_ume 的用户名/密码。")
            return 2
    else:
        print("[探测] 已用 --force 跳过账号探测")
        if args.check:
            return 0

    print("\n[执行] 开始补跑 ran_ume_full_task（滚动 7 天窗口，自动覆盖缺失日期）...")
    from backend.services.ran_ume_service import run_ran_ume_full_task

    result = run_ran_ume_full_task()
    print("\n[结果] success=%s elapsed=%ss" % (result.get("success"), result.get("elapsed_seconds")))
    for err in result.get("errors", []):
        print("  错误: %s" % err)
    if not result.get("success"):
        print("\n[失败] 补跑未成功，请检查上面的错误信息。")
        return 1

    print("\n[完成] 补跑成功。建议核对最新数据日期是否已到当天。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

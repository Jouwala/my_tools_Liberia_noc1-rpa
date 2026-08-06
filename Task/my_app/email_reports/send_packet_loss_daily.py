# -*- coding: utf-8 -*-
"""
Packet Loss 丢包看板日报邮件 —— 每日定时任务入口
=================================================
由 WorkBuddy 定时任务（每天 06:45）调用。

行为：
- 截图：英文界面 + 已加载 + 无左侧栏 + 地图铺满（Playwright headless）
- 附件：最新 Packet_Loss_Status_Output Automation *.xlsx
- 收件人：远程 _PL_EMAIL 的 ss_email.txt(主送) + cc_email.txt(抄送)（生产清单）
- 发件人：OWA 账户 ztenoc.olr@orange.com（EWS/NTLM）

退出码：0=成功，非0=失败。同时打印 [SEND][OK]/[SEND][FAIL] 证据。
"""
import sys
from pathlib import Path

# 让脚本可在任意 cwd 下运行
MY_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MY_APP))
sys.path.insert(0, str(MY_APP / "backend"))

from backend.services import kpi_email_report as kpi  # noqa: E402


def main() -> int:
    print("[DAILY] Packet Loss 日报邮件开始发送 ...")
    # 不传 to/cc → 使用远程生产清单（ss_email.txt + cc_email.txt）
    res = kpi.run_packet_loss_email()
    success = bool(res.get("success"))
    if success:
        print(f"[SEND][OK] {res.get('message') or res.get('detail')}")
        return 0
    print(f"[SEND][FAIL] {res.get('error') or res.get('message') or res}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""临时工具：等待 EWS 邮件服务器可达后自动发送一次电池 KPI 测试邮件。

用途：Orange 邮件网关（exchmail.orange-cit.ci:443）在有线出口下不可达，
仅在无线/特定出口下连通。本脚本轮询 TCP 可达性，一旦连通立即发送，
避免人工反复重试。到达时间预算后自动退出。

用法：
    python _send_when_online.py [收件人] [轮询秒数] [总预算秒数]
"""
from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

EWS_HOST = "exchmail.orange-cit.ci"
EWS_PORT = 443


def ews_reachable(timeout: int = 6) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((EWS_HOST, EWS_PORT))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except OSError:
            pass


def main() -> int:
    to = sys.argv[1] if len(sys.argv) > 1 else "dong.xinmin@zte.com.cn"
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    budget = int(sys.argv[3]) if len(sys.argv) > 3 else 1800

    from backend.services.battary_kpi_fetch import battery_kpi_service as svc

    started = time.time()
    attempt = 0
    while time.time() - started < budget:
        attempt += 1
        elapsed = int(time.time() - started)
        if ews_reachable():
            print(f"[WATCH] t={elapsed}s 第{attempt}次探测: EWS 可达 -> 立即发送", flush=True)
            res = svc.run_battery_email(to=to, cc=None)
            print("SEND_RESULT_START", flush=True)
            print(res, flush=True)
            print("SEND_RESULT_END", flush=True)
            return 0 if res.get("success") else 1
        print(f"[WATCH] t={elapsed}s 第{attempt}次探测: EWS 仍不可达，{interval}s 后重试", flush=True)
        time.sleep(interval)

    print(f"[WATCH] 预算 {budget}s 内 EWS 始终不可达，放弃。请恢复无线网络后重试。", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

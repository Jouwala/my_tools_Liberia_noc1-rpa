# -*- coding: utf-8 -*-
"""Restart the 8790 VMAX proxy via realtime_proxy_ctl.ensure_proxy."""
import sys
import time

sys.path.insert(0, r"d:\01_RPA\Task\my_app")

from backend.services.realtime_proxy_ctl import PROXIES, _proxy_healthy, _port_alive, ensure_proxy

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

print("port alive:", _port_alive(8790), "healthy:", _proxy_healthy(8790))
if not (_port_alive(8790) and _proxy_healthy(8790)):
    print("restarting...")
    state = ensure_proxy(PROXIES[1], timeout=40)
    print("ensure_proxy:", state)
    deadline = time.time() + 40
    while time.time() < deadline and not _proxy_healthy(8790):
        time.sleep(1)
    print("final healthy:", _proxy_healthy(8790))

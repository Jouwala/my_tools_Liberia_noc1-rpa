# -*- coding: utf-8 -*-
"""mml_port_probe.py — ZTE U31 EMS MML 端口连通性探测

扫描 EMS 服务器 (10.100.2.240) 上可能的 MML/Telnet 端口,
并尝试读取 banner 判断服务类型。
"""

import socket
import sys
import os

# 避免 Windows 控制台编码问题
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HOST = "10.100.2.240"

# 常见 MML / Telnet / SSH 端口
PORTS = [
    2161,   # ZTE EMS MML (常见)
    2162,   # ZTE EMS MML 备用
    2160,   # ZTE EMS
    2163,
    2164,
    2200,
    2300,
    23,     # 标准 Telnet
    22,     # SSH
    3023,
    8023,
    21100,  # JNP (已知)
    21128,  # SFTP (已知)
    21101,  # JMS (已知)
    9090,
    8080,
    10099,
    10400,
]

TIMEOUT = 2  # 秒


def probe_port(host, port):
    """尝试连接端口并读取 banner"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        rc = s.connect_ex((host, port))
        if rc != 0:
            s.close()
            return None
        # 连接成功, 尝试读取 banner
        try:
            s.settimeout(3)
            banner = s.recv(1024)
            banner_text = banner.decode("utf-8", errors="replace").strip()
        except socket.timeout:
            banner_text = "<no banner>"
        except Exception as e:
            banner_text = "<error: %s>" % e
        s.close()
        return banner_text
    except Exception as e:
        return "<connect error: %s>" % e


def main():
    print("=== ZTE U31 EMS MML Port Probe ===")
    print("Target: %s" % HOST)
    print("Scanning %d ports (timeout=%ds)...\n" % (len(PORTS), TIMEOUT))

    open_ports = []
    for port in PORTS:
        result = probe_port(HOST, port)
        if result is not None:
            open_ports.append((port, result))
            print("  [OPEN]  port %-6d  banner: %s" % (port, result[:120]))
        else:
            print("  [CLOSED] port %-6d" % port)

    print("\n=== Summary ===")
    print("Open ports: %d / %d" % (len(open_ports), len(PORTS)))
    for port, banner in open_ports:
        print("  %d: %s" % (port, banner[:200]))

    # 对开放端口尝试 MML 风格交互
    if open_ports:
        print("\n=== MML Interaction Test ===")
        for port, banner in open_ports:
            if port in (21100, 21101, 21128):
                continue  # 跳过已知非 MML 端口
            print("\n--- Trying port %d ---" % port)
            try_mml_interaction(HOST, port)


def try_mml_interaction(host, port):
    """尝试在指定端口做简单 MML 交互"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((host, port))

        # 读取初始 banner
        try:
            initial = s.recv(4096).decode("utf-8", errors="replace")
            print("  Initial: %s" % initial[:300].replace("\r", "\\r").replace("\n", "\\n"))
        except socket.timeout:
            print("  Initial: <timeout>")
            initial = ""

        # 尝试发送 HELP 命令 (MML 通用)
        for cmd in ["HELP\r\n", "LST PMCURRENT::;\r\n", "LOGIN::USER=oss,PWD=Tool123;\r\n"]:
            try:
                s.sendall(cmd.encode())
                s.settimeout(5)
                resp = s.recv(4096).decode("utf-8", errors="replace")
                print("  CMD [%s] -> %s" % (cmd.strip(), resp[:300].replace("\r", "\\r").replace("\n", "\\n")))
            except socket.timeout:
                print("  CMD [%s] -> <timeout>" % cmd.strip())
            except Exception as e:
                print("  CMD [%s] -> error: %s" % (cmd.strip(), e))

        s.close()
    except Exception as e:
        print("  Interaction failed: %s" % e)


if __name__ == "__main__":
    main()

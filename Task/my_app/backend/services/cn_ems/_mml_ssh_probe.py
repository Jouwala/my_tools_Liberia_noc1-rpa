# -*- coding: utf-8 -*-
"""
_mml_ssh_probe.py — SSH 登录 EMS 服务器, 探测 MML 命令执行环境

目的:
  1. SSH 登录 10.100.2.240:22 (oss/Tool123)
  2. 查看 shell 类型、可用命令
  3. 寻找 MML 客户端工具 (如 zte_mml, mmlclient, cmdclient 等)
  4. 尝试直接执行 MML 命令

用法:
  python _mml_ssh_probe.py
"""

import sys
import os
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import paramiko
except ImportError:
    print("paramiko not installed. Run: pip install paramiko")
    sys.exit(1)

HOST = "10.100.2.240"
PORT = 22
USER = "oss"
PASSWD = "Tool123"
TIMEOUT = 15


def ssh_exec(client, cmd, timeout=TIMEOUT):
    """执行命令并返回 stdout + stderr"""
    print("\n>>> %s" % cmd)
    try:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if out.strip():
            print(out[:3000])
        if err.strip():
            print("[STDERR] %s" % err[:1000])
        return out, err
    except Exception as e:
        print("[ERROR] %s" % e)
        return "", str(e)


def interactive_probe(client):
    """通过 invoke_shell 做交互式探测"""
    print("\n=== Interactive Shell Probe ===")
    shell = client.invoke_shell(width=200, height=50)
    shell.settimeout(10)
    time.sleep(2)

    # 读取初始 banner
    try:
        initial = shell.recv(8192).decode("utf-8", errors="replace")
        print("[Banner]\n%s" % initial[:2000])
    except Exception:
        print("[Banner] <no initial output>")

    # 探测命令
    probe_cmds = [
        "whoami",
        "pwd",
        "ls -la",
        "which mmlclient 2>/dev/null; which ztemml 2>/dev/null; which cmdclient 2>/dev/null",
        "find / -name '*mml*' -type f 2>/dev/null | head -20",
        "find / -name '*mmlclient*' 2>/dev/null | head -10",
        "ls /opt/zte/ 2>/dev/null",
        "ls /home/ 2>/dev/null",
        "env | grep -i mml 2>/dev/null",
        "cat /etc/shells 2>/dev/null",
        "ps aux | grep -i mml 2>/dev/null | head -10",
    ]

    for cmd in probe_cmds:
        try:
            shell.sendall((cmd + "\n").encode())
            time.sleep(2)
            output = ""
            while True:
                try:
                    chunk = shell.recv(4096).decode("utf-8", errors="replace")
                    if not chunk:
                        break
                    output += chunk
                    if "$ " in output or "# " in output or ">" in output:
                        break
                except Exception:
                    break
            print("\n>>> %s" % cmd)
            print(output[:1500])
        except Exception as e:
            print("\n>>> %s -> %s" % (cmd, e))

    shell.close()


def main():
    print("=== ZTE U31 EMS SSH MML Probe ===")
    print("Target: %s:%d user=%s\n" % (HOST, PORT, USER))

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print("Connecting...")
    try:
        client.connect(HOST, port=PORT, username=USER, password=PASSWD,
                       timeout=TIMEOUT, allow_agent=False, look_for_keys=False)
        print("SSH connected OK")
    except Exception as e:
        print("SSH connect failed: %s" % e)
        # 尝试其他用户名
        for u in ["root", "admin", "zte", "zteoss"]:
            print("\nRetrying with user=%s..." % u)
            try:
                client.connect(HOST, port=PORT, username=u, password=PASSWD,
                               timeout=TIMEOUT, allow_agent=False, look_for_keys=False)
                print("SSH connected with user=%s" % u)
                break
            except Exception as e2:
                print("  Failed: %s" % e2)
        else:
            print("\nAll SSH login attempts failed.")
            return

    # 1. 基本命令探测
    ssh_exec(client, "whoami")
    ssh_exec(client, "pwd")
    ssh_exec(client, "uname -a")
    ssh_exec(client, "ls /")

    # 2. 查找 MML 相关工具
    ssh_exec(client, "find / -maxdepth 4 -name '*mml*' -type f 2>/dev/null | head -20")
    ssh_exec(client, "find / -maxdepth 4 -name '*MML*' -type f 2>/dev/null | head -20")
    ssh_exec(client, "find /opt -maxdepth 5 -name '*.jar' 2>/dev/null | grep -i mml | head -10")
    ssh_exec(client, "find /home -maxdepth 4 -type f 2>/dev/null | head -30")

    # 3. 查找 ZTE 安装目录
    ssh_exec(client, "ls -la /opt/zte/ 2>/dev/null || echo 'no /opt/zte'")
    ssh_exec(client, "ls -la /opt/ 2>/dev/null | head -20")
    ssh_exec(client, "ls -la /zte/ 2>/dev/null || echo 'no /zte'")
    ssh_exec(client, "ls -la /zteims/ 2>/dev/null || echo 'no /zteims'")

    # 4. 查看进程
    ssh_exec(client, "ps aux | head -30")

    # 5. 交互式 shell 探测
    interactive_probe(client)

    client.close()
    print("\n=== Done ===")


if __name__ == "__main__":
    main()

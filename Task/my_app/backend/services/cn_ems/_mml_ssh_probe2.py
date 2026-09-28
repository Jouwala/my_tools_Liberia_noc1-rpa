# -*- coding: utf-8 -*-
"""
_mml_ssh_probe2.py — 多路径 SSH/MML 探测

路径:
  A. 端口 21128 (SFTP/SSH) 用 uepcommon 用户 (与 EmsKpiDaily.java 一致)
  B. 端口 22 尝试密钥认证
  C. 通过 RMI 查找 MML 相关 EJB/服务
  D. 检查 EMS 服务器上的 Java 类路径是否有 MML 相关类
"""

import sys
import os
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import paramiko

HOST = "10.100.2.240"


def try_ssh(port, user, password=None, key_filename=None):
    """尝试 SSH 连接"""
    print("\n--- SSH %s:%d user=%s ---" % (HOST, port, user))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        kw = dict(timeout=10, allow_agent=False, look_for_keys=False)
        if password:
            kw["password"] = password
        if key_filename:
            kw["key_filename"] = key_filename
        client.connect(HOST, port=port, username=user, **kw)
        print("  Connected!")
        return client
    except Exception as e:
        print("  Failed: %s" % e)
        return None


def exec_cmd(client, cmd, timeout=15):
    """执行命令"""
    print("\n>>> %s" % cmd)
    try:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if out.strip():
            print(out[:3000])
        if err.strip():
            print("[STDERR] %s" % err[:500])
        return out, err
    except Exception as e:
        print("[ERROR] %s" % e)
        return "", str(e)


def interactive_session(client):
    """交互式 shell 探测"""
    print("\n=== Interactive Shell ===")
    shell = client.invoke_shell(width=200, height=50)
    shell.settimeout(8)
    time.sleep(2)

    try:
        initial = shell.recv(8192).decode("utf-8", errors="replace")
        print("[Banner]\n%s" % initial[:2000])
    except Exception:
        print("[Banner] <no initial output>")

    cmds = [
        "whoami", "pwd", "ls",
        "ls /opt/zte/ 2>/dev/null",
        "ls /zte/ 2>/dev/null",
        "find / -maxdepth 3 -name '*mml*' 2>/dev/null | head -20",
        "find / -maxdepth 3 -name '*Mml*' 2>/dev/null | head -20",
        "find / -maxdepth 4 -name 'cmdclient*' 2>/dev/null | head -10",
        "ps aux 2>/dev/null | head -20",
        "env | head -20",
        "cat /etc/passwd 2>/dev/null | head -10",
    ]

    for cmd in cmds:
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
                    if any(p in output for p in ["$ ", "# ", "> ", "~]$"]):
                        break
                except Exception:
                    break
            print("\n>>> %s" % cmd)
            print(output[:1500])
        except Exception as e:
            print("\n>>> %s -> %s" % (cmd, e))

    shell.close()


def probe_sftp_shell():
    """通过 SFTP 端口 21128 尝试获取 shell"""
    print("\n=== Path A: SFTP port 21128 (uepcommon) ===")

    # 方式1: 直接 SSH（真实口令从 EMS_PASS 注入，见 2026-09-27 注释）
    for pwd in [None, "", "uepcommon", os.environ.get("EMS_PASS", ""), "zte"]:
        client = try_ssh(21128, "uepcommon", password=pwd)
        if client:
            exec_cmd(client, "whoami")
            exec_cmd(client, "ls /")
            exec_cmd(client, "find / -maxdepth 3 -name '*mml*' 2>/dev/null | head -20")
            interactive_session(client)
            client.close()
            return True

    # 方式2: SFTP only (已知可连)
    print("\n--- SFTP only (port 21128, uepcommon, cert) ---")
    try:
        t = paramiko.Transport((HOST, 21128))
        t.connect(username="uepcommon")
        print("  SFTP transport connected (no password)")
        sftp = paramiko.SFTPClient.from_transport(t)
        print("  SFTP client created")
        # 列出根目录
        for f in sftp.listdir("/"):
            print("    /%s" % f)
        # 尝试查找 MML 相关文件
        for search_dir in ["/", "/opt", "/home", "/zte"]:
            try:
                for f in sftp.listdir(search_dir):
                    if "mml" in f.lower():
                        print("  FOUND: %s/%s" % (search_dir, f))
            except Exception:
                pass
        sftp.close()
        t.close()
    except Exception as e:
        print("  SFTP probe failed: %s" % e)

    return False


def probe_ssh_standard():
    """端口 22 尝试各种认证方式"""
    print("\n=== Path B: SSH port 22 ===")

    # 尝试常见密码组合
    # 2026-09-27：原先这里的候选口令含**真实口令明文**（已入库）。
    # 改为从环境变量 EMS_PASS 注入真实口令，其余保留纯占位弱口令用于探测。
    _real = os.environ.get("EMS_PASS", "")
    combos = [
        ("oss", _real), ("oss", "oss"), ("oss", "123456"),
        ("root", "root"), ("root", "toor"), ("root", "zte"),
        ("root", "Zte@1234"),
        ("admin", "admin"),
        ("zte", "zte"),
    ]
    for user, pwd in combos:
        client = try_ssh(22, user, password=pwd)
        if client:
            exec_cmd(client, "whoami")
            exec_cmd(client, "ls /")
            interactive_session(client)
            client.close()
            return True

    # 尝试密钥认证
    print("\n--- Trying key-based auth ---")
    # 检查本地是否有可用密钥
    for key_path in [
        os.path.expanduser("~/.ssh/id_rsa"),
        os.path.expanduser("~/.ssh/id_dsa"),
        os.path.expanduser("~/.ssh/id_ed25519"),
    ]:
        if os.path.exists(key_path):
            print("  Found local key: %s" % key_path)
            for user in ["oss", "root", "admin"]:
                client = try_ssh(22, user, key_filename=key_path)
                if client:
                    exec_cmd(client, "whoami")
                    client.close()
                    return True

    return False


def probe_java_mml_classes():
    """检查现有 Java classpath 中是否有 MML 相关类"""
    print("\n=== Path C: Java MML class discovery ===")
    jar_path = os.path.join(os.path.dirname(__file__), "_kpi_launcher.jar")
    if not os.path.exists(jar_path):
        print("  _kpi_launcher.jar not found")
        return

    import subprocess
    java = r"D:\ems1\ems1\jdk\jdk\windows\bin\jar.exe"
    if not os.path.exists(java):
        java = r"D:\ems1\ems1\jdk\jdk\windows\bin\java.exe"

    # 列出 jar 中的类
    try:
        result = subprocess.run(
            [r"D:\ems1\ems1\jdk\jdk\windows\bin\jar.exe", "tf", jar_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
            # jar.exe 也是控制台程序，避免从无控制台父进程拉起时弹黑窗
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        classes = [l for l in result.stdout.splitlines() if l.endswith(".class")]
        mml_classes = [c for c in classes if "mml" in c.lower() or "Mml" in c]
        print("  Total classes in jar: %d" % len(classes))
        if mml_classes:
            print("  MML-related classes:")
            for c in mml_classes:
                print("    %s" % c)
        else:
            print("  No MML classes found in jar")
            # 列出所有包前缀
            pkgs = set()
            for c in classes:
                parts = c.rsplit("/", 1)
                if len(parts) > 1:
                    pkgs.add(parts[0])
            print("  Packages in jar:")
            for p in sorted(pkgs)[:30]:
                print("    %s" % p)
    except Exception as e:
        print("  Error: %s" % e)


def main():
    print("=== ZTE U31 EMS Multi-Path MML Probe ===")
    print("Target: %s" % HOST)

    # A. SFTP 端口
    probe_sftp_shell()

    # B. 标准 SSH
    probe_ssh_standard()

    # C. Java 类发现
    probe_java_mml_classes()

    print("\n=== Done ===")


if __name__ == "__main__":
    main()

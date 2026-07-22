"""
定时执行脚本：每小时第 56 分钟执行一次
"""
import time
import os
import subprocess
from datetime import datetime

PYTHON = r"d:\01_RPA\.venv\Scripts\python.exe"
INTERVAL_MINUTES = 60  # 每小时执行一次，即 60 分钟间隔
SCRIPTS = [
    r"D:\01_RPA\Site_outage\fetch_site_outage_v2.py",
    r"D:\01_RPA\Site_outage\screenshot_site_outage.py",
    r"D:\01_RPA\whatsapp\sent_whatsapp_v2.py",
]

LOG_DIR = r"D:\01_RPA\scheduler_logs"
TARGET_MINUTE = 56  # 每小时第 56 分钟执行


def kill_chrome_processes():
    """杀掉所有残留的 Chrome 进程（通过 PowerShell）"""
    ps_cmd = "Get-Process chrome -ErrorAction SilentlyContinue | ForEach-Object { $_.Kill(); Write-Output $($_.Id) }"
    try:
        result = subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            for pid in pids:
                print(f"  [CLEANUP] 杀掉 Chrome PID={pid}")
    except Exception:
        pass
    time.sleep(1)


def run_script(path):
    name = os.path.basename(path)
    is_whatsapp = "whatsapp" in name.lower()

    if is_whatsapp:
        print(f"[{datetime.now():%H:%M:%S}] 清理残留 Chrome 进程...")
        kill_chrome_processes()

    print(f"[{datetime.now():%H:%M:%S}] 正在执行: {name}")
    os.makedirs(LOG_DIR, exist_ok=True)
    err_file = os.path.join(LOG_DIR, f"{name}.err.log")

    try:
        with open(err_file, "w", encoding="utf-8") as err_f:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                [PYTHON, path],
                stdout=subprocess.PIPE,
                stderr=err_f,
                timeout=600,
                cwd=os.path.dirname(path),
                env=env,
            )
        if result.returncode == 0:
            print(f"[{datetime.now():%H:%M:%S}] 完成: {name}")
        else:
            print(f"[{datetime.now():%H:%M:%S}] 失败 (exit={result.returncode}): {name}")
            print(f"  stderr 已写入: {err_file}")
            with open(err_file, "r", encoding="utf-8") as f:
                content = f.read()
            print(f"  stderr:\n{content}")
    except subprocess.TimeoutExpired:
        print(f"[{datetime.now():%H:%M:%S}] 超时: {name}")
        kill_chrome_processes()
    except FileNotFoundError:
        print(f"[{datetime.now():%H:%M:%S}] 找不到文件: {path}")
    except Exception as e:
        print(f"[{datetime.now():%H:%M:%S}] 异常: {name} -> {e}")


def main():
    print("=" * 60)
    print(f"定时执行脚本启动 | 间隔: {INTERVAL_MINUTES} 分钟")
    print(f"脚本列表:")
    for i, s in enumerate(SCRIPTS, 1):
        print(f"  {i}. {s}")
    print("=" * 60)

    while True:
        print(f"\n--- 第 {datetime.now():%Y-%m-%d %H:%M:%S} 轮 ---")
        for script in SCRIPTS:
            run_script(script)
            print()
        print(f"本轮完成，{INTERVAL_MINUTES} 分钟后执行下一轮...")
        time.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()

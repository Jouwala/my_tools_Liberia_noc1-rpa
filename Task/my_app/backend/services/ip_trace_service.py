# -*- coding: utf-8 -*-
"""
IP 链路探测（IP Trace）业务逻辑层

从 Unified_Tools/IP_Trace_Tool/ip_detect_tool.py 改写而来，保留：
- tracert 路由追踪（Windows 自动用 tracert，Linux/Mac 用 traceroute）
- 对每跳持续 ICMP + TCP 双协议 ping，统计时延/抖动/丢包
- 多会话内存态（session_id 隔离）
- GeoIP2 地理位置（mmdb 缺失时降级为“未知”）
- AI 智能分析（provider 选择；默认本地规则，无需 API）

改造点：
- print -> logging
- 数据落盘目录改为 my_app/data/ip_trace/：启动时初始化 JSON/CSV，
  每轮 ping 结束后节流写盘（默认 5 秒一次，避免高频 I/O）
- 移除硬编码 OpenAI API key，改为环境变量注入 / 默认本地规则
- 去除 Flask / 独立服务生命周期（由 my_app 统一管理）
"""
import os
import re
import sys
import time
import csv
import json
import uuid
import threading
import statistics
import datetime
import logging

logger = logging.getLogger("ip_trace_service")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data", "ip_trace")

# 落盘节流间隔（秒）：原工具每次 ping 都全量读写 JSON，I/O 开销大，
# 这里改为按轮节流，保证数据可恢复的同时不阻塞 ping 循环
FLUSH_INTERVAL_SEC = float(os.environ.get("IP_TRACE_FLUSH_SEC", "5"))

# ------------------------- 多会话状态 -------------------------
analysis_sessions: dict = {}
sessions_lock = threading.Lock()

# GeoIP2（可选）
geo_reader = None
GEO_DB_PATH = os.path.join(DATA_DIR, "GeoLite2-City.mmdb")


def _init_geoip():
    global geo_reader
    if geo_reader is not None:
        return
    if not os.path.exists(GEO_DB_PATH):
        logger.info("GeoIP2 数据库不存在，地理位置功能降级为'未知'")
        return
    try:
        import geoip2.database  # 懒加载
        geo_reader = geoip2.database.Reader(GEO_DB_PATH)
        logger.info("GeoIP2 数据库已加载")
    except Exception as e:  # noqa: BLE001
        logger.warning("GeoIP2 加载失败: %s", e)
        geo_reader = None


_init_geoip()


def get_location(ip, fallback=None):
    if not ip or ip == "*":
        return fallback or "未知"
    if geo_reader is None:
        return fallback or "未知"
    try:
        resp = geo_reader.city(ip)
        if resp.city and resp.city.name:
            return resp.city.name
        if resp.country and resp.country.name:
            return resp.country.name
    except Exception:  # noqa: BLE001
        pass
    return fallback or "未知"


def get_location_with_coords(ip):
    if not ip or ip == "*" or geo_reader is None:
        return None, None, "未知"
    try:
        resp = geo_reader.city(ip)
        lat = resp.location.latitude
        lon = resp.location.longitude
        loc = resp.city.name or resp.country.name or "未知"
        return lat, lon, loc
    except Exception:  # noqa: BLE001
        return None, None, "未知"


# ------------------------- 会话管理 -------------------------
def get_or_create_session(session_id=None):
    with sessions_lock:
        if not session_id:
            session_id = str(uuid.uuid4())
        if session_id not in analysis_sessions:
            analysis_sessions[session_id] = {
                "is_running": False,
                "should_stop": False,
                "target": None,
                "hops": [],
                "ping_data": {},    # hop_num -> {times, count}
                "icmp_data": {},    # hop_num -> {times, count}
                "tcp_data": {},     # hop_num -> {times, count}
                "ping_history": {}, # hop_num -> [records]
                "start_time": None,
                "data_file_path": None,
                "csv_file_path": None,
                "last_activity": datetime.datetime.now(),
                "lock": threading.Lock(),
            }
        return session_id, analysis_sessions[session_id]


# ------------------------- ping 实现 -------------------------
def ping_single(host):
    import platform
    system = platform.system().lower()
    cmd = ["ping", "-n", "1", "-w", "2000", host] if system == "windows" \
        else ["ping", "-c", "1", "-W", "2", host]
    try:
        import subprocess
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        output = result.stdout
        if system == "windows":
            for pattern in [r'时间[<=](\d+)ms', r'time[<=](\d+)ms', r'时间=(\d+)ms', r'time=(\d+)ms']:
                m = re.findall(pattern, output, re.IGNORECASE)
                if m:
                    return int(m[0])
            if "<1" in output or "< 1" in output:
                return 0.5
        else:
            m = re.findall(r'time=([\d.]+)\s*ms', output)
            if m:
                return float(m[0])
        return None
    except Exception:  # noqa: BLE001
        return None


def tcpping_single(host, port=80, timeout=3):
    try:
        import socket
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        elapsed = (time.time() - start) * 1000
        sock.close()
        return round(elapsed, 2) if result == 0 else None
    except Exception:  # noqa: BLE001
        return None


def ping_with_fallback(host, port=80):
    icmp_result = [None]
    tcp_result = [None]

    def do_icmp():
        icmp_result[0] = ping_single(host)

    def do_tcp():
        tcp_result[0] = tcpping_single(host, port, timeout=3)

    t1 = threading.Thread(target=do_icmp, daemon=True)
    t2 = threading.Thread(target=do_tcp, daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=3.5)
    t2.join(timeout=3.5)
    display = icmp_result[0] if icmp_result[0] is not None else tcp_result[0]
    return icmp_result[0], tcp_result[0], display


def traceroute_host(host):
    import platform
    import subprocess
    import locale
    system = platform.system().lower()
    cmd = ["tracert", "-d", "-h", "30", host] if system == "windows" \
        else ["traceroute", "-n", "-m", "30", host]
    hops = []
    try:
        try:
            encoding = locale.getpreferredencoding()
        except Exception:  # noqa: BLE001
            encoding = "gbk" if system == "windows" else "utf-8"
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding=encoding, errors="ignore", bufsize=1)
        start_time = time.time()
        output_lines = []
        while True:
            if time.time() - start_time > 60:
                process.terminate()
                break
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                time.sleep(0.1)
                continue
            line = line.strip()
            if line:
                output_lines.append(line)
                if system == "windows" and ("Trace complete" in line or "跟踪完成" in line):
                    break

        if system == "windows":
            for line in output_lines:
                if not line.strip():
                    continue
                if "Tracing route" in line or "over a maximum" in line or "Trace complete" in line:
                    continue
                hop_match = re.match(r'^\s*(\d+)\s+', line)
                if not hop_match:
                    continue
                hop_num = hop_match.group(1)
                if "*" in line or "请求超时" in line or "timeout" in line.lower():
                    hops.append({"hop": hop_num, "ip": "*", "avg_delay": None,
                                 "jitter": None, "location": "超时"})
                    continue
                ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', line)
                ip = ip_match.group(1) if ip_match else None
                delays = [float(d) for d in re.findall(r'(\d+)\s*ms', line, re.IGNORECASE)]
                if delays:
                    avg_delay = round(statistics.mean(delays), 2)
                    jitter = round(statistics.stdev(delays), 2) if len(delays) > 1 else 0.0
                else:
                    avg_delay = jitter = None
                loc = "未知"
                if ip:
                    try:
                        n = int(hop_num)
                        fb = "Local Gateway" if n == 1 else ("ISP Backbone" if n == 2 else f"Hop {hop_num} Node")
                    except Exception:  # noqa: BLE001
                        fb = f"Hop {hop_num} Node"
                    loc = get_location(ip, fallback=fb)
                hops.append({"hop": hop_num, "ip": ip or "*",
                             "avg_delay": avg_delay, "jitter": jitter, "location": loc})
        else:
            for line in output_lines:
                parts = line.split()
                if len(parts) < 2:
                    continue
                hop_num = parts[0]
                ip_match = re.match(r"\d+\.\d+\.\d+\.\d+", parts[1])
                ip = ip_match.group(0) if ip_match else None
                delays = [float(x.replace("ms", "")) for x in parts[2:] if "ms" in x]
                if delays:
                    avg_delay = round(statistics.mean(delays), 2)
                    jitter = round(statistics.stdev(delays), 2) if len(delays) > 1 else 0.0
                else:
                    avg_delay = jitter = None
                loc = get_location(ip) if ip else "未知"
                hops.append({"hop": hop_num, "ip": ip or "*",
                             "avg_delay": avg_delay, "jitter": jitter, "location": loc})
    except Exception as e:  # noqa: BLE001
        logger.warning("Traceroute 错误: %s", e)
    return hops


# ------------------------- 持续 ping 线程 -------------------------
def continuous_ping_test(session_id):
    _, state = get_or_create_session(session_id)
    while True:
        with state["lock"]:
            if state["should_stop"] or not state["is_running"]:
                state["is_running"] = False
                break
            hops = state["hops"].copy()
            state["last_activity"] = datetime.datetime.now()

        if not hops:
            time.sleep(1)
            continue

        for hop in hops:
            with state["lock"]:
                if state["should_stop"]:
                    break
            hop_num = hop["hop"]
            hop_ip = hop.get("ip")
            if not hop_ip or hop_ip == "*":
                continue

            icmp_r, tcp_r, disp_r = ping_with_fallback(hop_ip, port=80)
            with state["lock"]:
                for bucket in ("ping_data", "icmp_data", "tcp_data"):
                    if hop_num not in state[bucket]:
                        state[bucket][hop_num] = {"times": [], "count": 0}
                state["icmp_data"][hop_num]["count"] += 1
                if icmp_r is not None:
                    state["icmp_data"][hop_num]["times"].append(icmp_r)
                    if len(state["icmp_data"][hop_num]["times"]) > 100:
                        state["icmp_data"][hop_num]["times"].pop(0)
                state["tcp_data"][hop_num]["count"] += 1
                if tcp_r is not None:
                    state["tcp_data"][hop_num]["times"].append(tcp_r)
                    if len(state["tcp_data"][hop_num]["times"]) > 100:
                        state["tcp_data"][hop_num]["times"].pop(0)
                state["ping_data"][hop_num]["count"] += 1
                if disp_r is not None:
                    state["ping_data"][hop_num]["times"].append(disp_r)
                    if len(state["ping_data"][hop_num]["times"]) > 100:
                        state["ping_data"][hop_num]["times"].pop(0)
                    if hop_num not in state["ping_history"]:
                        state["ping_history"][hop_num] = []
                    state["ping_history"][hop_num].append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "delay": disp_r, "icmp": icmp_r, "tcp": tcp_r,
                    })

            # 节流落盘：JSON 全量快照 + CSV 增量行（文件被占用时跳过本轮）
            now_ts = time.time()
            if now_ts - state.get("last_flush", 0.0) >= FLUSH_INTERVAL_SEC:
                state["last_flush"] = now_ts
                _flush_session_files(session_id, state, hop_num, icmp_r, tcp_r, disp_r)
        time.sleep(0.5)


def _flush_session_files(session_id, state, hop_num, icmp_r, tcp_r, disp_r):
    """将会话数据落盘：JSON 快照 + CSV 增量。文件占用时静默跳过，不阻塞主循环。"""
    try:
        data_file = state.get("data_file_path")
        csv_file = state.get("csv_file_path")
        ts = datetime.datetime.now().isoformat()

        if data_file:
            file_data = {
                "target": state.get("target", ""),
                "start_time": state["start_time"].isoformat() if state.get("start_time") else ts,
                "hops": [dict(h) for h in state["hops"]],
                "ping_records": {k: v[-500:] for k, v in state["ping_history"].items()},
            }
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(file_data, f, indent=2, ensure_ascii=False)

        if csv_file and disp_r is not None:
            with open(csv_file, "a", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerow([
                    hop_num, ts,
                    icmp_r if icmp_r is not None else "",
                    tcp_r if tcp_r is not None else "",
                    disp_r,
                ])
    except PermissionError:
        logger.warning("[TRACE] Session %s 数据文件被占用，本轮跳过落盘", session_id[:12])
    except Exception as e:  # noqa: BLE001
        logger.warning("[TRACE] Session %s 落盘失败: %s", session_id[:12], e)


# ------------------------- 对外入口 -------------------------
def start_trace(target, session_id=None):
    if not target:
        return {"error": "Target hostname is required"}
    session_id, state = get_or_create_session(session_id)
    logger.info("[TRACE] Session %s 开始分析 %s", session_id[:20], target)

    os.makedirs(DATA_DIR, exist_ok=True)
    with state["lock"]:
        if state["is_running"]:
            state["should_stop"] = True
            time.sleep(0.5)
        state["is_running"] = True
        state["should_stop"] = False
        state["target"] = target
        state["hops"] = []
        state["ping_data"].clear()
        state["icmp_data"].clear()
        state["tcp_data"].clear()
        state["ping_history"].clear()
        state["start_time"] = datetime.datetime.now()
        state["last_activity"] = datetime.datetime.now()

        # 生成落盘文件名：目标主机（点替换为-）+ 开始时间；若文件被占用则追加序号
        target_safe = target.replace(".", "-")
        time_str = state["start_time"].strftime("%Y-%m-%d_%H-%M-%S")
        seq = 0
        while True:
            suffix = "" if seq == 0 else f"_{seq}"
            json_path = os.path.join(DATA_DIR, f"{target_safe}_{time_str}{suffix}.json")
            csv_path = os.path.join(DATA_DIR, f"{target_safe}_{time_str}{suffix}.csv")
            if not os.path.exists(json_path) and not os.path.exists(csv_path):
                break
            seq += 1
        state["data_file_path"] = json_path
        state["csv_file_path"] = csv_path
        state["last_flush"] = 0.0

    # 初始化 JSON 快照与 CSV 表头
    try:
        with open(state["data_file_path"], "w", encoding="utf-8") as f:
            json.dump({"target": target,
                       "start_time": state["start_time"].isoformat(),
                       "hops": [], "ping_records": {}}, f, indent=2, ensure_ascii=False)
        with open(state["csv_file_path"], "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(["Hop", "Timestamp", "ICMP Delay (ms)", "TCP Delay (ms)", "Display Delay (ms)"])
        logger.info("[TRACE] 数据文件已创建: %s", state["data_file_path"])
    except Exception as e:  # noqa: BLE001
        logger.warning("[TRACE] 初始化数据文件失败（不影响在线探测）: %s", e)

    hops = traceroute_host(target)
    with state["lock"]:
        state["hops"] = hops
    logger.info("[TRACE] Session %s traceroute 完成，%d 跳", session_id[:20], len(hops))

    t = threading.Thread(target=continuous_ping_test, args=(session_id,), daemon=True)
    t.start()
    state["thread"] = t
    return {"hops": hops, "session_id": session_id}


def stop_trace(session_id):
    if not session_id:
        return {"error": "Session ID is required"}
    _, state = get_or_create_session(session_id)
    with state["lock"]:
        state["should_stop"] = True
        state["is_running"] = False
        state["last_activity"] = datetime.datetime.now()
    return {"status": "stopped", "is_running": False, "session_id": session_id}


def get_status(session_id):
    if not session_id:
        return {"error": "Session ID is required"}
    _, state = get_or_create_session(session_id)
    with state["lock"]:
        state["last_activity"] = datetime.datetime.now()
        hops = []
        for hop in state["hops"]:
            h = dict(hop)
            if h.get("ip") and h["ip"] != "*":
                lat, lon, loc = get_location_with_coords(h["ip"])
                h["lat"] = lat
                h["lon"] = lon
                if loc and loc != "未知" and h.get("location") in (None, "未知"):
                    h["location"] = loc
            hops.append(h)

        def _agg(bucket):
            out = {}
            for hn, d in state[bucket].items():
                if d["times"]:
                    avg = round(statistics.mean(d["times"]), 2)
                    mn = round(min(d["times"]), 2)
                    mx = round(max(d["times"]), 2)
                    jit = round(statistics.stdev(d["times"]), 2) if len(d["times"]) > 1 else 0.0
                    loss = round((d["count"] - len(d["times"])) / d["count"] * 100, 2) if d["count"] > 0 else 0.0
                    out[hn] = {"avg": avg, "min": mn, "max": mx, "jitter": jit,
                               "count": d["count"], "loss": loss, "times": d["times"][-20:]}
                elif d["count"] > 0:
                    out[hn] = {"avg": None, "min": None, "max": None, "jitter": 0.0,
                               "count": d["count"], "loss": "" , "times": []}
                    out[hn]["loss"] = 100.0
            return out

        ping_data = _agg("ping_data")
        icmp_data = _agg("icmp_data")
        tcp_data = _agg("tcp_data")

        return {
            "is_running": state["is_running"],
            "hops": hops,
            "ping_data": ping_data,
            "icmp_data": icmp_data,
            "tcp_data": tcp_data,
            "session_id": session_id,
            "target": state.get("target"),
        }


def build_analysis_payload(session_id):
    """从会话状态聚合 icmp/tcp 统计，供 /analyze 使用。"""
    _, state = get_or_create_session(session_id)
    with state["lock"]:
        hops = [dict(h) for h in state["hops"]]

        def _agg(bucket):
            out = {}
            for hn, d in state[bucket].items():
                if d["times"]:
                    out[hn] = {
                        "avg": round(statistics.mean(d["times"]), 2),
                        "min": round(min(d["times"]), 2),
                        "max": round(max(d["times"]), 2),
                        "jitter": round(statistics.stdev(d["times"]), 2) if len(d["times"]) > 1 else 0.0,
                        "count": d["count"],
                        "loss": round((d["count"] - len(d["times"])) / d["count"] * 100, 2) if d["count"] > 0 else 0.0,
                    }
                elif d["count"] > 0:
                    out[hn] = {"avg": None, "min": None, "max": None, "jitter": 0.0,
                               "count": d["count"], "loss": 100.0}
            return out

        icmp_data = _agg("icmp_data")
        tcp_data = _agg("tcp_data")
        target = state.get("target") or "Unknown"
    return hops, icmp_data, tcp_data, target


# ------------------------- AI 分析 -------------------------
def analyze_with_ai(hops, icmp_data, tcp_data, target, ai_provider="local",
                    api_key=None, lang="zh", ai_model=None):
    is_en = (lang or "zh").lower() == "en"
    if is_en:
        text = f"Target Host: {target}\n\nRoute Hop Analysis:\nTotal Hops: {len(hops)}\n\n"
    else:
        text = f"目标主机: {target}\n\n路由跳数分析:\n总跳数: {len(hops)}\n\n"
    for hop in hops:
        hn = hop.get("hop", "")
        ip = hop.get("ip", "*")
        loc = hop.get("location", "Unknown")
        ic = icmp_data.get(hn, {})
        tc = tcp_data.get(hn, {})
        if is_en:
            text += f"Hop {hn}: {ip} ({loc})\n"
            if ic:
                text += f"  ICMP: Avg={ic.get('avg','-')}ms, Min={ic.get('min','-')}ms, Max={ic.get('max','' )}ms, Jitter={ic.get('jitter','-')}ms, Loss={ic.get('loss','-')}%\n"
            if tc:
                text += f"  TCP: Avg={tc.get('avg','-')}ms, Min={tc.get('min','-')}ms, Max={tc.get('max','-')}ms, Jitter={tc.get('jitter','-')}ms, Loss={tc.get('loss','-')}%\n"
        else:
            text += f"跳 {hn}: {ip} ({loc})\n"
            if ic:
                text += f"  ICMP: 平均={ic.get('avg','-')}ms, 最小={ic.get('min','-')}ms, 最大={ic.get('max','-')}ms, 抖动={ic.get('jitter','-')}ms, 丢包率={ic.get('loss','-')}%\n"
            if tc:
                text += f"  TCP: 平均={tc.get('avg','-')}ms, 最小={tc.get('min','-')}ms, 最大={tc.get('max','-')}ms, 抖动={tc.get('jitter','-')}ms, 丢包率={tc.get('loss','-')}%\n"
        text += "\n"

    if is_en:
        prompt = ("Please act as a network performance analysis expert and provide a professional "
                  "analysis of the following route trace data:\n\n" + text +
                  "\nPlease provide:\n1. Overall network path quality assessment\n"
                  "2. Identify potential performance bottlenecks\n"
                  "3. Analyze the reasons for ICMP and TCP latency differences\n"
                  "4. Provide optimization recommendations\n5. Assess network health status\n\n"
                  "Important: Respond in English, professional, detailed, and practical.")
    else:
        prompt = ("请作为网络性能分析专家，对以下路由追踪数据进行专业分析：\n\n" + text +
                  "\n请提供：\n1. 整体网络路径质量评估\n2. 识别潜在的性能瓶颈（高延迟、高抖动、丢包）\n"
                  "3. 分析ICMP和TCP时延差异的原因\n4. 给出优化建议和解决方案\n5. 评估网络健康状况\n\n"
                  "重要：请务必使用中文回答，分析要专业、详细、实用。")

    provider = (ai_provider or "local").lower()
    if provider == "local" or provider == "rule-based" or not api_key:
        return analyze_with_local_rules(hops, icmp_data, tcp_data, target, lang)

    try:
        import requests
        system = ("You are a data analyst specializing in network performance. "
                  "Respond in the same language as the user's question.")
        if provider == "gemini":
            key = api_key or os.environ.get("GEMINI_API_KEY")
            if not key:
                return analyze_with_local_rules(hops, icmp_data, tcp_data, target, lang)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{ai_model or 'gemini-pro'}:generateContent?key={key}"
            resp = requests.post(url, json={"contents": [{"parts": [{"text": f"{system}\n\n{prompt}"}]}]}, timeout=60)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            return {"analysis": resp.json()["candidates"][0]["content"]["parts"][0]["text"], "provider": "gemini"}
        provider_cfg = {
            "openai": ("https://api.openai.com/v1/chat/completions", "gpt-3.5-turbo"),
            "deepseek": ("https://api.deepseek.com/v1/chat/completions", "deepseek-chat"),
            "qianwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-plus"),
            "glm": ("https://open.bigmodel.cn/api/paas/v4/chat/completions", "glm-4-plus"),
            "doubao": ("https://ark.cn-beijing.volcengine.com/api/v3/chat/completions", "doubao-pro-4k"),
        }.get(provider)
        if not provider_cfg:
            return {"error": f"不支持的 AI 提供商: {provider}"}
        url, model = provider_cfg
        if ai_model:
            model = ai_model
        resp = requests.post(url, headers={"Authorization": f"Bearer {api_key}",
                                           "Content-Type": "application/json"},
                             json={"model": model, "messages": [
                                 {"role": "system", "content": system},
                                 {"role": "user", "content": prompt}], "temperature": 0.7,
                             "max_tokens": 1500}, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return {"analysis": resp.json()["choices"][0]["message"]["content"], "provider": provider}
    except Exception as e:  # noqa: BLE001
        logger.warning("IP Trace AI 调用失败，回退本地规则: %s", e)
        return analyze_with_local_rules(hops, icmp_data, tcp_data, target, lang)


def analyze_with_local_rules(hops, icmp_data, tcp_data, target, lang="zh"):
    """基于规则的本地智能分析（端口自 ip_detect_tool.py:1127 忠实改写）"""
    is_en = (lang or "zh").lower() == "en"
    a = []
    a.append("=" * 60)
    a.append("Network Route Performance Analysis Report (Local AI Analysis)" if is_en
             else "网络路由性能分析报告（本地智能分析）")
    a.append("=" * 60)
    a.append(f"\nTarget Host: {target}" if is_en else f"\n目标主机: {target}")
    a.append(f"Analysis Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" if is_en
             else f"分析时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    a.append(f"Total Hops: {len(hops)}\n" if is_en else f"总跳数: {len(hops)}\n")

    # 1. 整体评估
    a.append("【1. Overall Network Path Quality Assessment】" if is_en
             else "【1. 整体网络路径质量评估】")
    total_icmp, total_tcp, high_lat, high_jit, pkt_loss = [], [], [], [], []
    for hop in hops:
        hn = hop.get("hop", "")
        ic = icmp_data.get(hn, {})
        tc = tcp_data.get(hn, {})
        if ic and ic.get("avg"):
            total_icmp.append(ic["avg"])
        if tc and tc.get("avg"):
            total_tcp.append(tc["avg"])
        if ic:
            if ic.get("avg", 0) > 100:
                high_lat.append((hn, ic.get("avg", 0)))
            if ic.get("jitter", 0) > 20:
                high_jit.append((hn, ic.get("jitter", 0)))
            if ic.get("loss", 0) > 5:
                pkt_loss.append((hn, ic.get("loss", 0)))
    avg_icmp = statistics.mean(total_icmp) if total_icmp else 0
    avg_tcp = statistics.mean(total_tcp) if total_tcp else 0
    if is_en:
        quality = "Excellent" if avg_icmp < 50 else "Good" if avg_icmp < 100 else "Fair" if avg_icmp < 200 else "Poor"
        a.append(f"Average ICMP Latency: {avg_icmp:.2f}ms")
        a.append(f"Average TCP Latency: {avg_tcp:.2f}ms")
        a.append(f"Overall Quality Rating: {quality}")
        if avg_tcp > 0 and avg_icmp > 0:
            diff = abs(avg_tcp - avg_icmp)
            if diff > 50:
                a.append(f"⚠️ Notice: Significant difference between ICMP and TCP latency ({diff:.2f}ms)")
    else:
        quality = "优秀" if avg_icmp < 50 else "良好" if avg_icmp < 100 else "一般" if avg_icmp < 200 else "较差"
        a.append(f"平均ICMP延迟: {avg_icmp:.2f}ms")
        a.append(f"平均TCP延迟: {avg_tcp:.2f}ms")
        a.append(f"整体质量评级: {quality}")
        if avg_tcp > 0 and avg_icmp > 0:
            diff = abs(avg_tcp - avg_icmp)
            if diff > 50:
                a.append(f"⚠️ 注意: ICMP和TCP延迟差异较大 ({diff:.2f}ms)，可能存在防火墙或路由策略影响")
    a.append("")

    # 2. 瓶颈
    a.append("【2. Performance Bottleneck Identification】" if is_en else "【2. 性能瓶颈识别】")
    if high_lat:
        a.append(f"High Latency Hops ({len(high_lat)}):" if is_en else f"高延迟跳数 ({len(high_lat)}个):")
        for hn, d in sorted(high_lat, key=lambda x: x[1], reverse=True)[:5]:
            info = next((h for h in hops if h.get("hop") == hn), {})
            a.append(f"  - Hop {hn} ({info.get('ip','Unknown')}, {info.get('location','Unknown')}): {d:.2f}ms"
                     if is_en else
                     f"  - 跳 {hn} ({info.get('ip','Unknown')}, {info.get('location','Unknown')}): {d:.2f}ms")
    else:
        a.append("✓ No obvious high-latency hops found" if is_en else "✓ 未发现明显的高延迟跳数")
    if high_jit:
        a.append(f"\nHigh Jitter Hops ({len(high_jit)}):" if is_en else f"\n高抖动跳数 ({len(high_jit)}个):")
        for hn, j in sorted(high_jit, key=lambda x: x[1], reverse=True)[:5]:
            info = next((h for h in hops if h.get("hop") == hn), {})
            a.append(f"  - Hop {hn} ({info.get('ip','Unknown')}): Jitter {j:.2f}ms" if is_en
                     else f"  - 跳 {hn} ({info.get('ip','Unknown')}): 抖动 {j:.2f}ms")
    else:
        a.append("✓ No obvious high-jitter hops found" if is_en else "✓ 未发现明显的高抖动跳数")
    if pkt_loss:
        a.append(f"\nPacket Loss Hops ({len(pkt_loss)}):" if is_en else f"\n丢包跳数 ({len(pkt_loss)}个):")
        for hn, l in sorted(pkt_loss, key=lambda x: x[1], reverse=True)[:5]:
            info = next((h for h in hops if h.get("hop") == hn), {})
            a.append(f"  - Hop {hn} ({info.get('ip','Unknown')}): Loss {l:.2f}%" if is_en
                     else f"  - 跳 {hn} ({info.get('ip','Unknown')}): 丢包率 {l:.2f}%")
    else:
        a.append("✓ No obvious packet loss issues found" if is_en else "✓ 未发现明显的丢包问题")
    a.append("")

    # 3. ICMP vs TCP
    a.append("【3. ICMP vs TCP Latency Difference Analysis】" if is_en
             else "【3. ICMP与TCP时延差异分析】")
    sig = []
    for hop in hops:
        hn = hop.get("hop", "")
        ic = icmp_data.get(hn, {})
        tc = tcp_data.get(hn, {})
        if ic.get("avg") and tc.get("avg"):
            diff = abs(ic["avg"] - tc["avg"])
            if diff > 30:
                sig.append((hn, ic["avg"], tc["avg"], diff))
    if sig:
        a.append("Hops with significant ICMP and TCP latency differences:" if is_en
                 else "发现ICMP和TCP延迟差异较大的跳数:")
        for hn, ic, tc, d in sig[:5]:
            info = next((h for h in hops if h.get("hop") == hn), {})
            a.append(f"  - Hop {hn} ({info.get('ip','Unknown')}): ICMP={ic:.2f}ms, TCP={tc:.2f}ms, Diff={d:.2f}ms"
                     if is_en else f"  - 跳 {hn} ({info.get('ip','Unknown')}): ICMP={ic:.2f}ms, TCP={tc:.2f}ms, 差异={d:.2f}ms")
        a.append("\nPossible Causes:" if is_en else "\n可能原因:")
        a.append("  1. Firewall policies: Some nodes may block ICMP but allow TCP" if is_en
                 else "  1. 防火墙策略：某些节点可能阻止ICMP但允许TCP")
        a.append("  2. Routing priority: ICMP and TCP may take different paths" if is_en
                 else "  2. 路由优先级：ICMP和TCP可能走不同路径")
        a.append("  3. Network congestion: TCP may be subject to stricter QoS control" if is_en
                 else "  3. 网络拥塞：TCP可能受到更严格的QoS控制")
    else:
        a.append("✓ ICMP and TCP latencies are consistent, network path is stable" if is_en
                 else "✓ ICMP和TCP延迟基本一致，网络路径稳定")
    a.append("")

    # 4. 建议
    a.append("【4. Optimization Recommendations & Solutions】" if is_en
             else "【4. 优化建议与解决方案】")
    sug = []
    if high_lat:
        sug.append("• For high latency hops, recommendations:" if is_en
                   else "• 针对高延迟跳数，建议:")
        sug.append("  - Check geographical locations of these nodes, consider using CDN or closer servers" if is_en
                   else "  - 检查这些节点的地理位置，考虑使用CDN或更近的服务器")
        sug.append("  - Contact ISP for route optimization" if is_en else "  - 联系ISP检查路由优化")
        sug.append("  - If possible, use dedicated lines or VPN to optimize path" if is_en
                   else "  - 如果可能，使用专线或VPN优化路径")
    if high_jit:
        sug.append("• For high jitter issues, recommendations:" if is_en else "• 针对高抖动问题，建议:")
        sug.append("  - Check network congestion, avoid peak hours" if is_en else "  - 检查网络拥塞情况，避开高峰时段")
        sug.append("  - Consider using QoS (Quality of Service) configuration" if is_en
                   else "  - 考虑使用QoS（服务质量）配置")
        sug.append("  - Check if other applications are consuming bandwidth" if is_en
                   else "  - 检查是否有其他应用占用带宽")
    if pkt_loss:
        sug.append("• For packet loss issues, recommendations:" if is_en else "• 针对丢包问题，建议:")
        sug.append("  - Check network equipment (routers, switches) status" if is_en
                   else "  - 检查网络设备（路由器、交换机）状态")
        sug.append("  - Check physical connections (cables, interfaces)" if is_en
                   else "  - 检查物理连接（网线、接口）")
        sug.append("  - Contact ISP to check line quality" if is_en else "  - 联系ISP检查线路质量")
    if avg_icmp > 200:
        sug.append("• Overall latency is high, recommendations:" if is_en else "• 整体延迟较高，建议:")
        sug.append("  - Consider changing ISP or upgrading network plan" if is_en
                   else "  - 考虑更换ISP或升级网络套餐")
        sug.append("  - Use network acceleration services" if is_en else "  - 使用网络加速服务")
        sug.append("  - Optimize application architecture, reduce network round trips" if is_en
                   else "  - 优化应用架构，减少网络往返次数")
    if not sug:
        sug.append("• Network performance is good, recommendations:" if is_en
                   else "• 网络性能良好，建议:")
        sug.append("  - Continue maintaining current network configuration" if is_en
                   else "  - 继续保持当前网络配置")
        sug.append("  - Regularly monitor network performance" if is_en else "  - 定期监控网络性能")
        sug.append("  - Pay attention to network usage trends, identify issues in time" if is_en
                   else "  - 关注网络使用趋势，及时发现问题")
    a.extend(sug)
    a.append("")

    # 5. 健康评估
    a.append("【5. Network Health Status Assessment】" if is_en else "【5. 网络健康状况评估】")
    score = 100
    if avg_icmp > 200:
        score -= 30
    elif avg_icmp > 100:
        score -= 15
    score -= len(high_lat) * 5
    score -= len(high_jit) * 3
    score -= len(pkt_loss) * 10
    score = max(0, min(100, score))
    if is_en:
        status = "Excellent" if score >= 80 else "Good" if score >= 60 else "Fair" if score >= 40 else "Needs Improvement"
        a.append(f"Health Score: {score}/100 ({status})")
        a.append(f"Problem Hops: {len(high_lat) + len(high_jit) + len(pkt_loss)}")
        a.append("")
        a.append("=" * 60)
        a.append("Analysis Complete - Rule-based Intelligent Analysis")
        a.append("=" * 60)
        return {"analysis": "\n".join(a), "provider": "Local AI Analysis (No API required)"}
    status = "优秀" if score >= 80 else "良好" if score >= 60 else "一般" if score >= 40 else "需要改进"
    a.append(f"健康评分: {score}/100 ({status})")
    a.append(f"问题跳数: {len(high_lat) + len(high_jit) + len(pkt_loss)}")
    a.append("")
    a.append("=" * 60)
    a.append("分析完成 - 基于规则引擎的智能分析")
    a.append("=" * 60)
    return {"analysis": "\n".join(a), "provider": "本地智能分析（无需API）"}

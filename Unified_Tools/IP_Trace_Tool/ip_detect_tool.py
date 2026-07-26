from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import subprocess
import re
import statistics
import os
import threading
import time
import json
import csv
import uuid
import socket
import webbrowser
import sys
import signal
import requests
from collections import defaultdict
from datetime import datetime, timedelta

app = Flask(__name__)

# ==================== AI API 配置 ====================
# 可以在这里设置默认的API密钥（可选）
# 优先级：用户输入 > 环境变量 > 默认配置
DEFAULT_GEMINI_API_KEY = None  # 可以设置为: "your-gemini-api-key-here"
DEFAULT_OPENAI_API_KEY = "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"
DEFAULT_QWEN_API_KEY = None  # 可以设置为: "your-qwen-api-key-here"
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"  # 国内地域
# DEFAULT_QWEN_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"  # 新加坡地域
DEFAULT_QWEN_MODEL = "qwen-plus"  # 可选: qwen-plus, qwen-turbo, qwen-max等
DEFAULT_DOUBAO_API_KEY = None  # 可以设置为: "your-doubao-api-key-here"
DEFAULT_DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"  # 豆包API地址
DEFAULT_DOUBAO_MODEL = "doubao-seed-1-8-251228"  # 豆包模型名称（默认，如果没有指定则使用自动尝试列表）
# 豆包模型自动尝试列表（按顺序尝试，直到成功）
DOUBAO_MODEL_LIST = [
    "doubao-seed-1-6-flash-250828",
    "doubao-1-5-pro-32k-250115",
    "kimi-k2-thinking-251104"
]
# =====================================================

# 全局变量：控制服务器关闭
shutdown_flag = threading.Event()
server_thread = None
server_instance = None  # 服务器实例，用于关闭

# 多会话状态管理 - {session_id: state}
analysis_sessions = {}
sessions_lock = threading.Lock()


# 清理过期会话（超过1小时未活动）
def cleanup_expired_sessions():
    """清理超过1小时未活动的会话"""
    current_time = datetime.now()
    with sessions_lock:
        expired_sessions = []
        for session_id, state in analysis_sessions.items():
            if state.get('last_activity'):
                if current_time - state['last_activity'] > timedelta(hours=1):
                    expired_sessions.append(session_id)

        for session_id in expired_sessions:
            # 停止该会话的测试线程
            state = analysis_sessions[session_id]
            with state['lock']:
                state['should_stop'] = True
            del analysis_sessions[session_id]
            print(f"Cleaned up expired session: {session_id}")


def get_or_create_session(session_id=None):
    """获取或创建会话状态"""
    if not session_id:
        session_id = str(uuid.uuid4())

    with sessions_lock:
        if session_id not in analysis_sessions:
            analysis_sessions[session_id] = {
                'is_running': False,
                'should_stop': False,
                'target': None,
                'hops': [],
                'ping_data': defaultdict(lambda: {'times': [], 'count': 0}),
                'icmp_data': defaultdict(lambda: {'times': [], 'count': 0}),  # ICMP ping数据
                'tcp_data': defaultdict(lambda: {'times': [], 'count': 0}),  # TCP ping数据
                'start_time': None,
                'data_file_path': None,
                'csv_file_path': None,
                'ping_history': defaultdict(list),  # 存储带时间戳的时延记录
                'lock': threading.Lock(),
                'last_activity': datetime.now(),
                'thread': None
            }
        else:
            # 更新最后活动时间
            analysis_sessions[session_id]['last_activity'] = datetime.now()

        return session_id, analysis_sessions[session_id]


# 初始化 GeoIP2 读取器（如果数据库文件存在）
geo_reader = None
geoip_db_path = "GeoLite2-City.mmdb"
if os.path.exists(geoip_db_path):
    try:
        import geoip2.database

        geo_reader = geoip2.database.Reader(geoip_db_path)
    except ImportError:
        print("警告: geoip2 模块未安装，地理位置功能将不可用")
    except Exception as e:
        print(f"警告: 无法加载 GeoIP2 数据库: {e}")
else:
    print(f"警告: GeoIP2 数据库文件 '{geoip_db_path}' 不存在，地理位置功能将不可用")


def get_location(ip, fallback=None):
    """获取IP地理位置

    Args:
        ip: IP地址
        fallback: 如果查询失败，返回的备用位置信息
    """
    if geo_reader is None:
        return fallback or "未知（数据库不可用）"
    try:
        response = geo_reader.city(ip)
        # 获取国家名称
        country = response.country.name or response.country.iso_code or ""

        # 获取省份/州信息（subdivisions中最具体的那个）
        subdivision = ""
        if response.subdivisions:
            # subdivisions 是一个列表，通常最后一个是最具体的（如：省份 -> 市）
            most_specific_sub = response.subdivisions.most_specific
            subdivision = most_specific_sub.name or most_specific_sub.iso_code or ""

        # 获取城市名称
        city = response.city.name or ""

        # 构建位置字符串：优先显示 国家 - 省份 - 城市，如果没有城市则显示 国家 - 省份
        location_parts = []
        if country:
            location_parts.append(country)
        # 添加省份/州（如果存在且与城市不同）
        if subdivision and subdivision != city:
            location_parts.append(subdivision)
        # 添加城市（如果存在）
        if city:
            location_parts.append(city)

        location_str = " - ".join(location_parts).strip()

        # 如果结果是空或只有国家，尝试使用备用值
        if not location_str or location_str == country:
            # 如果只有国家信息，至少显示国家
            if country:
                location_str = country
            else:
                location_str = fallback or "未知"
        elif location_str == "未知":
            location_str = fallback or "未知"

        return location_str
    except Exception as e:
        # 如果查询失败，返回备用值
        return fallback or "未知"


def get_location_with_coords(ip):
    """获取IP地理位置和坐标"""
    if geo_reader is None:
        return None, None, "未知（数据库不可用）"
    try:
        response = geo_reader.city(ip)

        # 获取国家名称
        country = response.country.name or response.country.iso_code or ""

        # 获取省份/州信息
        subdivision = ""
        if response.subdivisions:
            most_specific_sub = response.subdivisions.most_specific
            subdivision = most_specific_sub.name or most_specific_sub.iso_code or ""

        # 获取城市名称
        city = response.city.name or ""

        # 构建位置字符串
        location_parts = []
        if country:
            location_parts.append(country)
        # 添加省份/州（如果存在且与城市不同）
        if subdivision and subdivision != city:
            location_parts.append(subdivision)
        # 添加城市（如果存在）
        if city:
            location_parts.append(city)

        location_str = " - ".join(location_parts).strip()

        # 如果结果为空，至少显示国家
        if not location_str:
            location_str = country or "未知"

        lat = response.location.latitude
        lon = response.location.longitude
        return lat, lon, location_str
    except Exception as e:
        return None, None, "未知"


def ping_single(host):
    """执行单次ICMP ping，返回延迟值（毫秒）"""
    import platform
    system = platform.system().lower()

    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", "2000", host]
    else:
        cmd = ["ping", "-c", "1", "-W", "2", host]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        output = result.stdout

        if system == "windows":
            patterns = [
                r'时间[<=](\d+)ms',
                r'time[<=](\d+)ms',
                r'时间=(\d+)ms',
                r'time=(\d+)ms'
            ]
            for pattern in patterns:
                matches = re.findall(pattern, output, re.IGNORECASE)
                if matches:
                    time_val = matches[0]
                    if time_val:
                        return int(time_val)
            if "<1" in output or "< 1" in output:
                return 0.5
        else:
            pattern = r'time=([\d.]+)\s*ms'
            matches = re.findall(pattern, output)
            if matches:
                return float(matches[0])

        return None
    except:
        return None


def tcpping_single(host, port=80, timeout=3):
    """执行TCP ping，返回延迟值（毫秒）"""
    try:
        start_time = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        elapsed = (time.time() - start_time) * 1000  # 转换为毫秒
        sock.close()

        if result == 0:
            return round(elapsed, 2)
        else:
            return None
    except:
        return None


def ping_with_fallback(host, port=80):
    """执行ping，对所有节点都同时执行ICMP和TCP ping，返回 (icmp_result, tcp_result, display_result)"""
    # 同时执行ICMP和TCP ping（并行执行以提高效率）
    import threading

    icmp_result = None
    tcp_result = None

    def do_icmp():
        nonlocal icmp_result
        icmp_result = ping_single(host)

    def do_tcp():
        nonlocal tcp_result
        tcp_result = tcpping_single(host, port, timeout=3)

    # 创建两个线程并行执行
    icmp_thread = threading.Thread(target=do_icmp, daemon=True)
    tcp_thread = threading.Thread(target=do_tcp, daemon=True)

    icmp_thread.start()
    tcp_thread.start()

    # 等待两个线程完成（最多等待3.5秒，给TCP ping额外0.5秒）
    icmp_thread.join(timeout=3.5)
    tcp_thread.join(timeout=3.5)

    # 确定显示哪个结果：优先使用ICMP，如果ICMP失败则使用TCP
    display_result = icmp_result if icmp_result is not None else tcp_result

    return icmp_result, tcp_result, display_result


def traceroute_host(host):
    """执行 traceroute，自动检测操作系统"""
    import platform
    system = platform.system().lower()

    if system == "windows":
        cmd = ["tracert", "-d", "-h", "30", host]  # -h 限制最大跳数
    else:
        cmd = ["traceroute", "-n", "-m", "30", host]  # Linux/Mac

    hops = []

    try:
        # 使用 Popen 实时读取输出，避免超时问题
        # Windows 需要处理编码问题
        import locale
        encoding = 'gbk' if system == "windows" else 'utf-8'
        try:
            encoding = locale.getpreferredencoding()
        except:
            pass

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=encoding,
            errors='ignore',
            bufsize=1
        )

        # 读取输出（最多等待60秒）
        import time
        start_time = time.time()
        timeout = 60
        output_lines = []

        while True:
            if time.time() - start_time > timeout:
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
                # Windows tracert 完成标志
                if system == "windows" and ("Trace complete" in line or "跟踪完成" in line):
                    break

        # 解析输出
        if system == "windows":
            # Windows tracert 格式: "  1     2 ms     2 ms     2 ms  192.168.1.1"
            for line in output_lines:
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                if "Tracing route" in line or "over a maximum" in line or "Trace complete" in line:
                    continue

                # 匹配跳数
                hop_match = re.match(r'^\s*(\d+)\s+', line)
                if not hop_match:
                    continue

                hop_num = hop_match.group(1)

                # 检查超时
                if "*" in line or "请求超时" in line or "timeout" in line.lower():
                    hops.append({
                        "hop": hop_num,
                        "ip": "*",
                        "avg_delay": None,
                        "jitter": None,
                        "location": "超时"
                    })
                    continue

                # 提取IP地址
                ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', line)
                ip = ip_match.group(1) if ip_match else None

                # 提取延迟值
                delay_matches = re.findall(r'(\d+)\s*ms', line, re.IGNORECASE)
                delays = [float(d) for d in delay_matches]

                if delays:
                    avg_delay = round(statistics.mean(delays), 2)
                    jitter = round(statistics.stdev(delays), 2) if len(delays) > 1 else 0.0
                else:
                    avg_delay = jitter = None

                # 获取位置信息，如果失败则使用默认描述
                location = "未知"
                if ip:
                    hop_num_int = int(hop_num) if hop_num.isdigit() else 0
                    if hop_num_int == 1:
                        location = get_location(ip, fallback="Local Gateway")
                    elif hop_num_int == 2:
                        location = get_location(ip, fallback="ISP Backbone")
                    else:
                        location = get_location(ip, fallback=f"Hop {hop_num} Node")
                else:
                    location = "超时"

                hops.append({
                    "hop": hop_num,
                    "ip": ip or "*",
                    "avg_delay": avg_delay,
                    "jitter": jitter,
                    "location": location
                })
        else:
            # Linux/Mac traceroute 格式
            for line in output_lines:
                parts = line.split()
                if len(parts) >= 2:
                    hop_num = parts[0]
                    ip_match = re.match(r"\d+\.\d+\.\d+\.\d+", parts[1])
                    ip = ip_match.group(0) if ip_match else None
                    delays = [float(x.replace("ms", "")) for x in parts[2:] if "ms" in x]
                    if delays:
                        avg_delay = round(statistics.mean(delays), 2)
                        jitter = round(statistics.stdev(delays), 2) if len(delays) > 1 else 0.0
                    else:
                        avg_delay = jitter = None
                    location = get_location(ip) if ip else "未知"
                    hops.append({
                        "hop": hop_num,
                        "ip": ip or "*",
                        "avg_delay": avg_delay,
                        "jitter": jitter,
                        "location": location
                    })

    except subprocess.TimeoutExpired:
        print(f"Traceroute 超时: {host}")
        return hops  # 返回已解析的跳数
    except Exception as e:
        print(f"Traceroute 执行错误: {e}")
        import traceback
        traceback.print_exc()
        return hops  # 返回已解析的跳数

    return hops


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/trace", methods=["POST"])
def trace():
    try:
        target = request.form.get("target")
        session_id = request.form.get("session_id") or request.headers.get("X-Session-ID")

        if not target:
            return jsonify({"error": "Target hostname is required"}), 400

        # 获取或创建会话
        session_id, analysis_state = get_or_create_session(session_id)

        print(f"[TRACE] Session {session_id[:20]}... starting analysis for {target}")

        # 创建 data 文件夹（如果不存在）
        data_dir = os.path.join(os.path.dirname(__file__), 'data')
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            print(f"Created data directory: {data_dir}")

        # 生成文件名：目标网站（点用-代替）+ 开始时间
        start_time = datetime.now()
        target_safe = target.replace('.', '-')
        time_str = start_time.strftime('%Y-%m-%d_%H-%M-%S')
        json_filename = f"{target_safe}_{time_str}.json"
        csv_filename = f"{target_safe}_{time_str}.csv"
        data_file_path = os.path.join(data_dir, json_filename)
        csv_file_path = os.path.join(data_dir, csv_filename)

        with analysis_state['lock']:
            # 如果该会话已经在运行，可以选择停止旧的分析或返回错误
            if analysis_state['is_running']:
                print(f"[TRACE] Session {session_id[:20]}... already running, stopping previous analysis")
                analysis_state['should_stop'] = True
                # 等待一下让旧线程停止
                time.sleep(0.5)

            analysis_state['is_running'] = True
            analysis_state['should_stop'] = False
            analysis_state['target'] = target
            analysis_state['hops'] = []
            analysis_state['ping_data'].clear()
            analysis_state['ping_history'].clear()
            analysis_state['start_time'] = start_time
            analysis_state['data_file_path'] = data_file_path
            analysis_state['csv_file_path'] = csv_file_path
            analysis_state['last_activity'] = datetime.now()

        # 初始化JSON数据文件
        initial_data = {
            'target': target,
            'start_time': start_time.isoformat(),
            'hops': [],
            'ping_records': {},  # {hop_num: [{'timestamp': '...', 'delay': ..., 'icmp': ..., 'tcp': ...}, ...]}
            'icmp_records': {},  # ICMP专用记录
            'tcp_records': {}  # TCP专用记录
        }
        try:
            with open(data_file_path, 'w', encoding='utf-8') as f:
                json.dump(initial_data, f, indent=2, ensure_ascii=False)
            print(f"Created data file: {data_file_path}")
        except Exception as e:
            print(f"Error creating data file: {e}")

        # 初始化CSV文件（写入表头）
        try:
            with open(csv_file_path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Hop', 'Timestamp', 'ICMP Delay (ms)', 'TCP Delay (ms)', 'Display Delay (ms)'])
            print(f"Created CSV file: {csv_file_path}")
        except Exception as e:
            print(f"Error creating CSV file: {e}")

        # 执行 traceroute
        hops = traceroute_host(target)

        with analysis_state['lock']:
            analysis_state['hops'] = hops
            print(f"[TRACE] Session {session_id[:20]}... traceroute completed, {len(hops)} hops")

        # 启动持续测试线程（传递session_id）
        test_thread = threading.Thread(target=continuous_ping_test, args=(session_id,), daemon=True)
        test_thread.start()
        analysis_state['thread'] = test_thread

        print(f"[TRACE] Session {session_id[:20]}... ping thread started")

        return jsonify({"hops": hops, "session_id": session_id})
    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f"Trace error: {error_msg}")
        print(traceback.format_exc())
        if 'analysis_state' in locals():
            with analysis_state['lock']:
                analysis_state['is_running'] = False
        return jsonify(
            {"error": error_msg, "hops": [], "session_id": session_id if 'session_id' in locals() else None}), 500


@app.route("/stop", methods=["POST"])
def stop_analysis():
    """停止持续测试"""
    session_id = request.form.get("session_id") or request.headers.get("X-Session-ID")

    if not session_id:
        return jsonify({"error": "Session ID is required"}), 400

    session_id, analysis_state = get_or_create_session(session_id)

    with analysis_state['lock']:
        analysis_state['should_stop'] = True
        analysis_state['is_running'] = False
        analysis_state['last_activity'] = datetime.now()

    return jsonify({"status": "stopped", "is_running": False, "session_id": session_id})


@app.route("/shutdown", methods=["POST", "GET"])
def shutdown():
    """关闭服务器"""
    global shutdown_flag, server_instance
    print("Received shutdown request from browser")
    shutdown_flag.set()

    # 在后台线程中延迟关闭服务器，先返回响应
    def shutdown_server():
        time.sleep(0.1)  # 等待响应返回
        if server_instance:
            try:
                print("Shutting down server instance...")
                server_instance.shutdown()
                print("Server shutdown signal sent")
            except Exception as e:
                print(f"Error shutting down server: {e}")

    # 在后台线程中执行关闭
    threading.Thread(target=shutdown_server, daemon=True).start()

    return jsonify({"status": "shutting down"})


def analyze_with_ai(hops, icmp_data, tcp_data, target, ai_provider='gemini', api_key=None, lang='zh', ai_model=None):
    """使用AI分析路由时延数据"""
    try:
        is_english = lang.lower() == 'en'

        # 准备分析数据
        if is_english:
            analysis_text = f"Target Host: {target}\n\n"
            analysis_text += "Route Hop Analysis:\n"
            analysis_text += f"Total Hops: {len(hops)}\n\n"
        else:
            analysis_text = f"目标主机: {target}\n\n"
            analysis_text += "路由跳数分析:\n"
            analysis_text += f"总跳数: {len(hops)}\n\n"

        for hop in hops:
            hop_num = hop.get('hop', '')
            ip = hop.get('ip', '*')
            location = hop.get('location', 'Unknown')

            icmp_info = icmp_data.get(hop_num, {})
            tcp_info = tcp_data.get(hop_num, {})

            if is_english:
                analysis_text += f"Hop {hop_num}: {ip} ({location})\n"
                if icmp_info:
                    analysis_text += f"  ICMP: Avg={icmp_info.get('avg', '-')}ms, "
                    analysis_text += f"Min={icmp_info.get('min', '-')}ms, "
                    analysis_text += f"Max={icmp_info.get('max', '-')}ms, "
                    analysis_text += f"Jitter={icmp_info.get('jitter', '-')}ms, "
                    analysis_text += f"Loss={icmp_info.get('loss', '-')}%\n"
                if tcp_info:
                    analysis_text += f"  TCP: Avg={tcp_info.get('avg', '-')}ms, "
                    analysis_text += f"Min={tcp_info.get('min', '-')}ms, "
                    analysis_text += f"Max={tcp_info.get('max', '-')}ms, "
                    analysis_text += f"Jitter={tcp_info.get('jitter', '-')}ms, "
                    analysis_text += f"Loss={tcp_info.get('loss', '-')}%\n"
            else:
                analysis_text += f"跳 {hop_num}: {ip} ({location})\n"
            if icmp_info:
                analysis_text += f"  ICMP: 平均={icmp_info.get('avg', '-')}ms, "
                analysis_text += f"最小={icmp_info.get('min', '-')}ms, "
                analysis_text += f"最大={icmp_info.get('max', '-')}ms, "
                analysis_text += f"抖动={icmp_info.get('jitter', '-')}ms, "
                analysis_text += f"丢包率={icmp_info.get('loss', '-')}%\n"
            if tcp_info:
                analysis_text += f"  TCP: 平均={tcp_info.get('avg', '-')}ms, "
                analysis_text += f"最小={tcp_info.get('min', '-')}ms, "
                analysis_text += f"最大={tcp_info.get('max', '-')}ms, "
                analysis_text += f"抖动={tcp_info.get('jitter', '-')}ms, "
                analysis_text += f"丢包率={tcp_info.get('loss', '-')}%\n"
            analysis_text += "\n"

        # 构建AI提示词
        if is_english:
            prompt = f"""Please act as a network performance analysis expert and provide a professional analysis of the following route trace data:

{analysis_text}

Please provide:
1. Overall network path quality assessment
2. Identify potential performance bottlenecks (high latency, high jitter, packet loss)
3. Analyze the reasons for ICMP and TCP latency differences
4. Provide optimization recommendations and solutions
5. Assess network health status

Important: Please respond in English, the analysis should be professional, detailed, and practical."""
        else:
            prompt = f"""请作为网络性能分析专家，对以下路由追踪数据进行专业分析：

{analysis_text}

请提供：
1. 整体网络路径质量评估
2. 识别潜在的性能瓶颈（高延迟、高抖动、丢包）
3. 分析ICMP和TCP时延差异的原因
4. 给出优化建议和解决方案
5. 评估网络健康状况

重要：请务必使用中文回答，分析要专业、详细、实用。"""

        if ai_provider.lower() == 'gemini':
            return analyze_with_gemini(prompt, api_key)
        elif ai_provider.lower() == 'chatgpt' or ai_provider.lower() == 'openai':
            return analyze_with_chatgpt(prompt, api_key)
        elif ai_provider.lower() == 'qwen' or ai_provider.lower() == 'tongyi':
            return analyze_with_qwen(prompt, api_key)
        elif ai_provider.lower() == 'doubao':
            return analyze_with_doubao(prompt, api_key, model=ai_model)
        elif ai_provider.lower() == 'local' or ai_provider.lower() == 'rule-based':
            return analyze_with_local_rules(hops, icmp_data, tcp_data, target, lang)
        else:
            error_msg = f"Unsupported AI provider: {ai_provider}" if is_english else f"不支持的AI提供商: {ai_provider}"
            return {"error": error_msg}

    except Exception as e:
        error_msg = f"AI analysis failed: {str(e)}" if lang.lower() == 'en' else f"AI分析失败: {str(e)}"
        return {"error": error_msg}


def analyze_with_gemini(prompt, api_key=None):
    """使用Google Gemini API进行分析"""
    try:
        # 优先级：用户输入 > 环境变量 > 默认配置
        if not api_key:
            api_key = os.environ.get('GEMINI_API_KEY')
        if not api_key:
            api_key = DEFAULT_GEMINI_API_KEY

        if not api_key:
            return {
                "error": "未配置Gemini API密钥。请设置环境变量 GEMINI_API_KEY、在代码中配置 DEFAULT_GEMINI_API_KEY 或在请求中提供 api_key 参数。"}

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={api_key}"

        payload = {
            "contents": [{
                "parts": [{
                    "text": prompt
                }]
            }]
        }

        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()

        if 'candidates' in result and len(result['candidates']) > 0:
            content = result['candidates'][0]['content']['parts'][0]['text']
            return {"analysis": content, "provider": "Gemini"}
        else:
            return {"error": "Gemini API返回格式异常"}

    except requests.exceptions.RequestException as e:
        return {"error": f"Gemini API请求失败: {str(e)}"}
    except Exception as e:
        return {"error": f"Gemini分析失败: {str(e)}"}


def analyze_with_chatgpt(prompt, api_key=None):
    """使用OpenAI ChatGPT API进行分析"""
    try:
        # 优先级：用户输入 > 环境变量 > 默认配置
        if not api_key:
            api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            api_key = DEFAULT_OPENAI_API_KEY

        if not api_key:
            return {
                "error": "未配置OpenAI API密钥。请设置环境变量 OPENAI_API_KEY、在代码中配置 DEFAULT_OPENAI_API_KEY 或在请求中提供 api_key 参数。"}

        url = "https://api.openai.com/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {
                    "role": "system",
                    "content": "你是一位专业的网络性能分析专家，擅长分析路由追踪数据、识别网络瓶颈并提供优化建议。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)

        # 处理HTTP错误
        if response.status_code == 429:
            error_detail = ""
            error_type = "频率限制"
            try:
                error_data = response.json()
                if 'error' in error_data and 'message' in error_data['error']:
                    error_msg = error_data['error']['message']
                    error_detail = f" 详情: {error_msg}"
                    # 检查是否是配额问题
                    if 'quota' in error_msg.lower() or 'exceeded' in error_msg.lower() or 'billing' in error_msg.lower():
                        error_type = "配额已用完"
                        error_detail = f"\n\n错误详情: {error_msg}\n\n解决方案:\n1. 检查OpenAI账户的API配额和账单\n2. 访问 https://platform.openai.com/account/billing 查看使用情况\n3. 升级账户计划或等待配额重置\n4. 可以尝试使用Gemini作为替代方案"
                    else:
                        error_detail = f"\n\n错误详情: {error_msg}\n\n解决方案:\n1. 等待几分钟后重试\n2. 减少请求频率\n3. 可以尝试使用Gemini作为替代方案"
            except:
                error_detail = "\n\n解决方案:\n1. 等待几分钟后重试\n2. 检查您的API配额\n3. 可以尝试使用Gemini作为替代方案"

            return {"error": f"API请求失败（429错误 - {error_type}）{error_detail}"}
        elif response.status_code == 401:
            return {
                "error": "API密钥无效或已过期。请检查您的API密钥是否正确，或访问 https://platform.openai.com/api-keys 获取新密钥。"}
        elif response.status_code == 403:
            return {
                "error": "API访问被拒绝。请检查您的API密钥权限或账户状态。访问 https://platform.openai.com/account 查看账户详情。"}
        elif response.status_code == 402:
            return {"error": "账户余额不足。请访问 https://platform.openai.com/account/billing 充值后重试。"}

        response.raise_for_status()

        result = response.json()

        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0]['message']['content']
            return {"analysis": content, "provider": "ChatGPT"}
        else:
            return {"error": "ChatGPT API返回格式异常"}

    except requests.exceptions.Timeout:
        return {"error": "ChatGPT API请求超时。请检查网络连接后重试。"}
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        if "429" in error_msg:
            return {"error": "API请求频率过高（429错误）。请稍后再试，或检查您的API配额。"}
        return {"error": f"ChatGPT API请求失败: {error_msg}"}
    except Exception as e:
        return {"error": f"ChatGPT分析失败: {str(e)}"}


def analyze_with_qwen(prompt, api_key=None, base_url=None, model=None):
    """使用阿里云通义千问（Qwen）API进行分析"""
    # 优先级：用户输入 > 环境变量 > 默认配置
    if not api_key:
        api_key = os.environ.get('QWEN_API_KEY') or os.environ.get('DASHSCOPE_API_KEY')
    if not api_key:
        api_key = DEFAULT_QWEN_API_KEY

    if not base_url:
        base_url = os.environ.get('QWEN_BASE_URL', DEFAULT_QWEN_BASE_URL)

    if not model:
        model = os.environ.get('QWEN_MODEL', DEFAULT_QWEN_MODEL)

    if not api_key:
        return {
            "error": "未配置通义千问API密钥。请设置环境变量 QWEN_API_KEY 或 DASHSCOPE_API_KEY、在代码中配置 DEFAULT_QWEN_API_KEY 或在请求中提供 api_key 参数。"}

    url = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "IP-Detect-Tool/1.0"
    }

    # 如果prompt太长，尝试简化（保留关键信息）
    prompt_length = len(prompt)
    if prompt_length > 8000:  # 如果超过8000字符，进行简化
        print(f"警告: Prompt长度 {prompt_length} 字符，可能影响响应速度，正在优化...")
        # 保留前4000和后4000字符（保留开头和结尾的关键信息）
        prompt = prompt[:4000] + "\n\n[中间数据已省略，保留关键统计信息]\n\n" + prompt[-4000:]
        print(f"优化后Prompt长度: {len(prompt)} 字符")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是一位专业的网络性能分析专家，擅长分析路由追踪数据、识别网络瓶颈并提供优化建议。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.7,
        "max_tokens": 2000
    }

    # 重试配置
    max_retries = 3
    timeout = 120  # 增加到120秒
    retry_delay = 2  # 初始重试延迟（秒）

    for attempt in range(max_retries):
        try:
            print(f"[通义千问] 尝试请求 (第 {attempt + 1}/{max_retries} 次)...")

            # 手动序列化JSON，确保UTF-8编码，避免latin-1编码错误
            json_data = json.dumps(payload, ensure_ascii=False).encode('utf-8')

            # 增加超时时间到120秒，因为通义千问可能需要更长时间
            # 使用data参数而不是json参数，避免编码问题
            response = requests.post(url, data=json_data, headers=headers, timeout=timeout)

            # 处理HTTP错误
            if response.status_code == 429:
                error_detail = ""
                try:
                    error_data = response.json()
                    if 'error' in error_data and 'message' in error_data['error']:
                        error_msg = error_data['error']['message']
                        error_detail = f"\n\n错误详情: {error_msg}"
                except:
                    pass

                # 429错误时，等待后重试
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)  # 指数退避
                    print(f"[通义千问] 遇到频率限制，等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    return {"error": f"API请求频率过高（429错误）{error_detail}\n\n已重试 {max_retries} 次，请稍后再试。"}

            elif response.status_code == 401:
                return {"error": "API密钥无效或已过期。请检查您的API密钥是否正确。"}
            elif response.status_code == 403:
                return {"error": "API访问被拒绝。请检查您的API密钥权限或账户状态。"}
            elif response.status_code == 402:
                return {"error": "账户余额不足。请访问阿里云控制台充值后重试。"}

            response.raise_for_status()

            result = response.json()

            if 'choices' in result and len(result['choices']) > 0:
                content = result['choices'][0]['message']['content']
                print(f"[通义千问] 请求成功 (第 {attempt + 1} 次尝试)")
                return {"analysis": content, "provider": "通义千问 (Qwen)"}
            else:
                return {"error": "通义千问API返回格式异常"}

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                print(f"[通义千问] 请求超时（{timeout}秒），等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
                # 每次重试时稍微增加超时时间
                timeout = min(timeout + 30, 180)  # 最多180秒
                continue
            else:
                return {
                    "error": f"通义千问API请求超时（已重试 {max_retries} 次，每次超时时间 {timeout} 秒）。\n\n可能原因：\n1. 网络连接不稳定或速度较慢\n2. API服务器响应较慢\n3. 请求数据量较大\n\n解决方案：\n1. 检查网络连接状态\n2. 稍后重试\n3. 尝试使用其他AI提供商（如本地智能分析）\n4. 如果使用国内地域，可以尝试切换到新加坡地域\n5. 尝试使用更快的模型（如 qwen-turbo）"}

        except requests.exceptions.ConnectionError as e:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                print(f"[通义千问] 连接失败，等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
                continue
            else:
                return {
                    "error": f"通义千问API连接失败（已重试 {max_retries} 次）。\n\n错误详情: {str(e)}\n\n可能原因：\n1. 网络无法访问API服务器\n2. DNS解析失败\n3. 防火墙阻止连接\n\n解决方案：\n1. 检查网络连接\n2. 检查防火墙设置\n3. 尝试使用VPN或代理\n4. 尝试切换到其他地域的API地址"}

        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if "429" in error_msg:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    print(f"[通义千问] 遇到频率限制，等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    return {"error": f"API请求频率过高（429错误，已重试 {max_retries} 次）。请稍后再试，或检查您的API配额。"}
            elif "timeout" in error_msg.lower():
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    print(f"[通义千问] 请求超时，等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    timeout = min(timeout + 30, 180)
                    continue
                else:
                    return {
                        "error": f"通义千问API请求超时（已重试 {max_retries} 次）。\n\n解决方案：\n1. 检查网络连接\n2. 稍后重试\n3. 尝试使用其他AI提供商\n4. 尝试使用更快的模型（如 qwen-turbo）"}
            else:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    print(f"[通义千问] 请求失败: {error_msg}，等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    return {
                        "error": f"通义千问API请求失败（已重试 {max_retries} 次）: {error_msg}\n\n请检查：\n1. API密钥是否正确\n2. 网络连接是否正常\n3. API服务是否可用"}

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                print(f"[通义千问] 发生错误: {str(e)}，等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
                continue
            else:
                return {"error": f"通义千问分析失败（已重试 {max_retries} 次）: {str(e)}\n\n请检查网络连接和API配置。"}

    # 如果所有重试都失败
    return {"error": f"通义千问API请求失败，已重试 {max_retries} 次。请检查网络连接或稍后重试。"}


def analyze_with_doubao(prompt, api_key=None, base_url=None, model=None):
    """使用字节跳动豆包（Doubao）API进行分析"""
    # 优先级：用户输入 > 环境变量 > 默认配置
    if not api_key:
        api_key = os.environ.get('ARK_API_KEY') or os.environ.get('DOUBAO_API_KEY')
    if not api_key:
        api_key = DEFAULT_DOUBAO_API_KEY

    if not base_url:
        base_url = os.environ.get('DOUBAO_BASE_URL', DEFAULT_DOUBAO_BASE_URL)

    if not api_key:
        return {
            "error": "未配置豆包API密钥。请设置环境变量 ARK_API_KEY 或 DOUBAO_API_KEY、在代码中配置 DEFAULT_DOUBAO_API_KEY 或在请求中提供 api_key 参数。"}

    # 确定要使用的模型
    if not model:
        # 如果没有指定，从环境变量获取，如果也没有，使用默认模型
        model = os.environ.get('DOUBAO_MODEL', DEFAULT_DOUBAO_MODEL)

    # 使用用户选择的模型
    model_to_use = model

    # 使用OpenAI兼容的API格式
    url = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model_to_use,
        "messages": [
            {
                "role": "system",
                "content": "你是一位专业的网络性能分析专家，擅长分析路由追踪数据、识别网络瓶颈并提供优化建议。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.7,
        "max_tokens": 2000
    }

    # 增加超时时间并添加重试机制
    max_retries = 3
    timeout = 60  # 增加到60秒
    retry_delay = 2  # 重试延迟（秒）

    # 对当前模型进行重试
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)

            # 处理HTTP错误
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (attempt + 1)
                    time.sleep(wait_time)
                    continue
                return {"error": f"API请求频率过高（429错误）。模型: {model_to_use}\n\n请稍后再试，或检查您的API配额。"}
            elif response.status_code == 401:
                return {"error": "API密钥无效或已过期。请检查您的API密钥是否正确，或访问火山引擎控制台获取新密钥。"}
            elif response.status_code == 403:
                return {"error": "API访问被拒绝。请检查您的API密钥权限或账户状态。"}
            elif response.status_code == 404:
                return {
                    "error": f"模型不存在（404错误）。模型: {model_to_use}\n\n请检查模型名称是否正确，或在界面中选择其他模型。"}
            elif response.status_code == 500 or response.status_code == 502 or response.status_code == 503:
                # 服务器错误，可以重试
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (attempt + 1)
                    time.sleep(wait_time)
                    continue
                return {"error": f"豆包API服务器错误（{response.status_code}）。模型: {model_to_use}\n\n请稍后重试。"}

            response.raise_for_status()

            result = response.json()

            if 'choices' in result and len(result['choices']) > 0:
                content = result['choices'][0]['message']['content']
                return {"analysis": content, "provider": f"豆包 (Doubao - {model_to_use})"}
            else:
                return {"error": f"豆包API返回格式异常。模型: {model_to_use}"}

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (attempt + 1)
                print(f"豆包模型 {model_to_use} 请求超时，{wait_time}秒后重试（{attempt + 1}/{max_retries}）...")
                time.sleep(wait_time)
                continue
            else:
                return {
                    "error": f"豆包API请求超时（已重试 {max_retries} 次，每次超时时间 {timeout} 秒）。模型: {model_to_use}\n\n可能原因：\n1. 网络连接不稳定或速度较慢\n2. API服务器响应较慢\n3. 请求数据量较大\n\n解决方案：\n1. 检查网络连接状态\n2. 尝试选择其他模型\n3. 稍后重试\n4. 尝试使用其他AI提供商（如本地智能分析或Gemini）"}
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if attempt < max_retries - 1:
                wait_time = retry_delay * (attempt + 1)
                print(
                    f"豆包模型 {model_to_use} 请求失败: {error_msg}，{wait_time}秒后重试（{attempt + 1}/{max_retries}）...")
                time.sleep(wait_time)
                continue
            if "404" in error_msg or "not found" in error_msg.lower():
                return {"error": f"模型不存在。模型: {model_to_use}\n\n请检查模型名称是否正确，或在界面中选择其他模型。"}
            return {
                "error": f"豆包API请求失败（已重试 {max_retries} 次）。模型: {model_to_use}\n\n错误: {error_msg}\n\n请检查网络连接和API配置。"}
        except Exception as e:
            error_msg = str(e)
            if attempt < max_retries - 1:
                wait_time = retry_delay * (attempt + 1)
                print(
                    f"豆包模型 {model_to_use} 分析失败: {error_msg}，{wait_time}秒后重试（{attempt + 1}/{max_retries}）...")
                time.sleep(wait_time)
                continue
            return {
                "error": f"豆包分析失败（已重试 {max_retries} 次）。模型: {model_to_use}\n\n错误: {error_msg}\n\n请检查网络连接和API配置。"}

    # 如果所有重试都失败
    return {
        "error": f"豆包API请求失败，已重试 {max_retries} 次。模型: {model_to_use}\n\n请检查网络连接或稍后重试，或尝试选择其他模型。"}


def analyze_with_local_rules(hops, icmp_data, tcp_data, target, lang='zh'):
    """使用基于规则的本地智能分析（无需API）"""
    try:
        is_english = lang.lower() == 'en'
        analysis = []
        analysis.append("=" * 60)
        if is_english:
            analysis.append("Network Route Performance Analysis Report (Local AI Analysis)")
        else:
            analysis.append("网络路由性能分析报告（本地智能分析）")
            analysis.append("=" * 60)
            if is_english:
                analysis.append(f"\nTarget Host: {target}")
                analysis.append(f"Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                analysis.append(f"Total Hops: {len(hops)}\n")
            else:
                analysis.append(f"\n目标主机: {target}")
                analysis.append(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                analysis.append(f"总跳数: {len(hops)}\n")

        # 1. 整体网络路径质量评估
        if is_english:
            analysis.append("【1. Overall Network Path Quality Assessment】")
        else:
            analysis.append("【1. 整体网络路径质量评估】")
        total_icmp_delays = []
        total_tcp_delays = []
        high_latency_hops = []
        high_jitter_hops = []
        packet_loss_hops = []

        for hop in hops:
            hop_num = hop.get('hop', '')
            icmp_info = icmp_data.get(hop_num, {})
            tcp_info = tcp_data.get(hop_num, {})

            if icmp_info and icmp_info.get('avg'):
                total_icmp_delays.append(icmp_info['avg'])
            if tcp_info and tcp_info.get('avg'):
                total_tcp_delays.append(tcp_info['avg'])

            # 识别问题跳
            if icmp_info:
                avg_delay = icmp_info.get('avg', 0)
                jitter = icmp_info.get('jitter', 0)
                loss = icmp_info.get('loss', 0)

                if avg_delay > 100:
                    high_latency_hops.append((hop_num, avg_delay))
                if jitter > 20:
                    high_jitter_hops.append((hop_num, jitter))
                if loss > 5:
                    packet_loss_hops.append((hop_num, loss))

        avg_icmp = statistics.mean(total_icmp_delays) if total_icmp_delays else 0
        avg_tcp = statistics.mean(total_tcp_delays) if total_tcp_delays else 0

        if is_english:
            if avg_icmp < 50:
                quality = "Excellent"
            elif avg_icmp < 100:
                quality = "Good"
            elif avg_icmp < 200:
                quality = "Fair"
            else:
                quality = "Poor"
            analysis.append(f"Average ICMP Latency: {avg_icmp:.2f}ms")
            analysis.append(f"Average TCP Latency: {avg_tcp:.2f}ms")
            analysis.append(f"Overall Quality Rating: {quality}")
            if avg_tcp > 0 and avg_icmp > 0:
                diff = abs(avg_tcp - avg_icmp)
                if diff > 50:
                    analysis.append(
                        f"⚠️ Notice: Significant difference between ICMP and TCP latency ({diff:.2f}ms), may be affected by firewall or routing policies")
        else:
            if avg_icmp < 50:
                quality = "优秀"
            elif avg_icmp < 100:
                quality = "良好"
            elif avg_icmp < 200:
                quality = "一般"
            else:
                quality = "较差"
        analysis.append(f"平均ICMP延迟: {avg_icmp:.2f}ms")
        analysis.append(f"平均TCP延迟: {avg_tcp:.2f}ms")
        analysis.append(f"整体质量评级: {quality}")
        if avg_tcp > 0 and avg_icmp > 0:
            diff = abs(avg_tcp - avg_icmp)
            if diff > 50:
                analysis.append(f"⚠️ 注意: ICMP和TCP延迟差异较大 ({diff:.2f}ms)，可能存在防火墙或路由策略影响")

        analysis.append("")

        # 2. 识别潜在的性能瓶颈
        if is_english:
            analysis.append("【2. Performance Bottleneck Identification】")
            if high_latency_hops:
                analysis.append(f"High Latency Hops ({len(high_latency_hops)}):")
                for hop_num, delay in sorted(high_latency_hops, key=lambda x: x[1], reverse=True)[:5]:
                    hop_info = next((h for h in hops if h.get('hop') == hop_num), {})
                    ip = hop_info.get('ip', 'Unknown')
                    location = hop_info.get('location', 'Unknown')
                    analysis.append(f"  - Hop {hop_num} ({ip}, {location}): {delay:.2f}ms")
            else:
                analysis.append("✓ No obvious high-latency hops found")

            if high_jitter_hops:
                analysis.append(f"\nHigh Jitter Hops ({len(high_jitter_hops)}):")
                for hop_num, jitter in sorted(high_jitter_hops, key=lambda x: x[1], reverse=True)[:5]:
                    hop_info = next((h for h in hops if h.get('hop') == hop_num), {})
                    ip = hop_info.get('ip', 'Unknown')
                    analysis.append(f"  - Hop {hop_num} ({ip}): Jitter {jitter:.2f}ms")
            else:
                analysis.append("✓ No obvious high-jitter hops found")

            if packet_loss_hops:
                analysis.append(f"\nPacket Loss Hops ({len(packet_loss_hops)}):")
                for hop_num, loss in sorted(packet_loss_hops, key=lambda x: x[1], reverse=True)[:5]:
                    hop_info = next((h for h in hops if h.get('hop') == hop_num), {})
                    ip = hop_info.get('ip', 'Unknown')
                    analysis.append(f"  - Hop {hop_num} ({ip}): Loss {loss:.2f}%")
            else:
                analysis.append("✓ No obvious packet loss issues found")
        else:
            analysis.append("【2. 性能瓶颈识别】")
        if high_latency_hops:
            analysis.append(f"高延迟跳数 ({len(high_latency_hops)}个):")
            for hop_num, delay in sorted(high_latency_hops, key=lambda x: x[1], reverse=True)[:5]:
                hop_info = next((h for h in hops if h.get('hop') == hop_num), {})
                ip = hop_info.get('ip', 'Unknown')
                location = hop_info.get('location', 'Unknown')
                analysis.append(f"  - 跳 {hop_num} ({ip}, {location}): {delay:.2f}ms")
        else:
            analysis.append("✓ 未发现明显的高延迟跳数")

        if high_jitter_hops:
            analysis.append(f"\n高抖动跳数 ({len(high_jitter_hops)}个):")
            for hop_num, jitter in sorted(high_jitter_hops, key=lambda x: x[1], reverse=True)[:5]:
                hop_info = next((h for h in hops if h.get('hop') == hop_num), {})
                ip = hop_info.get('ip', 'Unknown')
                analysis.append(f"  - 跳 {hop_num} ({ip}): 抖动 {jitter:.2f}ms")
        else:
            analysis.append("✓ 未发现明显的高抖动跳数")

        if packet_loss_hops:
            analysis.append(f"\n丢包跳数 ({len(packet_loss_hops)}个):")
            for hop_num, loss in sorted(packet_loss_hops, key=lambda x: x[1], reverse=True)[:5]:
                hop_info = next((h for h in hops if h.get('hop') == hop_num), {})
                ip = hop_info.get('ip', 'Unknown')
                analysis.append(f"  - 跳 {hop_num} ({ip}): 丢包率 {loss:.2f}%")
        else:
            analysis.append("✓ 未发现明显的丢包问题")

        analysis.append("")

        # 3. ICMP和TCP时延差异分析
        if is_english:
            analysis.append("【3. ICMP vs TCP Latency Difference Analysis】")
        else:
            analysis.append("【3. ICMP与TCP时延差异分析】")
        significant_diff_hops = []
        for hop in hops:
            hop_num = hop.get('hop', '')
            icmp_info = icmp_data.get(hop_num, {})
            tcp_info = tcp_data.get(hop_num, {})

            if icmp_info.get('avg') and tcp_info.get('avg'):
                diff = abs(icmp_info['avg'] - tcp_info['avg'])
                if diff > 30:
                    significant_diff_hops.append((hop_num, icmp_info['avg'], tcp_info['avg'], diff))

        if is_english:
            if significant_diff_hops:
                analysis.append("Hops with significant ICMP and TCP latency differences:")
                for hop_num, icmp, tcp, diff in significant_diff_hops[:5]:
                    hop_info = next((h for h in hops if h.get('hop') == hop_num), {})
                    ip = hop_info.get('ip', 'Unknown')
                    analysis.append(f"  - Hop {hop_num} ({ip}): ICMP={icmp:.2f}ms, TCP={tcp:.2f}ms, Diff={diff:.2f}ms")
                analysis.append("\nPossible Causes:")
                analysis.append("  1. Firewall policies: Some nodes may block ICMP but allow TCP")
                analysis.append("  2. Routing priority: ICMP and TCP may take different paths")
                analysis.append("  3. Network congestion: TCP may be subject to stricter QoS control")
            else:
                analysis.append("✓ ICMP and TCP latencies are consistent, network path is stable")
        else:
            if significant_diff_hops:
                analysis.append("发现ICMP和TCP延迟差异较大的跳数:")
                for hop_num, icmp, tcp, diff in significant_diff_hops[:5]:
                    hop_info = next((h for h in hops if h.get('hop') == hop_num), {})
                    ip = hop_info.get('ip', 'Unknown')
                    analysis.append(f"  - 跳 {hop_num} ({ip}): ICMP={icmp:.2f}ms, TCP={tcp:.2f}ms, 差异={diff:.2f}ms")
                analysis.append("\n可能原因:")
                analysis.append("  1. 防火墙策略：某些节点可能阻止ICMP但允许TCP")
                analysis.append("  2. 路由优先级：ICMP和TCP可能走不同路径")
                analysis.append("  3. 网络拥塞：TCP可能受到更严格的QoS控制")
            else:
                analysis.append("✓ ICMP和TCP延迟基本一致，网络路径稳定")

        analysis.append("")

        # 4. 优化建议
        if is_english:
            analysis.append("【4. Optimization Recommendations & Solutions】")
        else:
            analysis.append("【4. 优化建议与解决方案】")
        suggestions = []

        if is_english:
            if high_latency_hops:
                suggestions.append("• For high latency hops, recommendations:")
                suggestions.append(
                    "  - Check geographical locations of these nodes, consider using CDN or closer servers")
                suggestions.append("  - Contact ISP for route optimization")
                suggestions.append("  - If possible, use dedicated lines or VPN to optimize path")

            if high_jitter_hops:
                suggestions.append("• For high jitter issues, recommendations:")
                suggestions.append("  - Check network congestion, avoid peak hours")
                suggestions.append("  - Consider using QoS (Quality of Service) configuration")
                suggestions.append("  - Check if other applications are consuming bandwidth")

            if packet_loss_hops:
                suggestions.append("• For packet loss issues, recommendations:")
                suggestions.append("  - Check network equipment (routers, switches) status")
                suggestions.append("  - Check physical connections (cables, interfaces)")
                suggestions.append("  - Contact ISP to check line quality")

            if avg_icmp > 200:
                suggestions.append("• Overall latency is high, recommendations:")
                suggestions.append("  - Consider changing ISP or upgrading network plan")
                suggestions.append("  - Use network acceleration services")
                suggestions.append("  - Optimize application architecture, reduce network round trips")

            if not suggestions:
                suggestions.append("• Network performance is good, recommendations:")
                suggestions.append("  - Continue maintaining current network configuration")
                suggestions.append("  - Regularly monitor network performance")
                suggestions.append("  - Pay attention to network usage trends, identify issues in time")
        else:
            if high_latency_hops:
                suggestions.append("• 针对高延迟跳数，建议:")
                suggestions.append("  - 检查这些节点的地理位置，考虑使用CDN或更近的服务器")
            suggestions.append("  - 联系ISP检查路由优化")
            suggestions.append("  - 如果可能，使用专线或VPN优化路径")

        if high_jitter_hops:
            suggestions.append("• 针对高抖动问题，建议:")
            suggestions.append("  - 检查网络拥塞情况，避开高峰时段")
            suggestions.append("  - 考虑使用QoS（服务质量）配置")
            suggestions.append("  - 检查是否有其他应用占用带宽")

        if packet_loss_hops:
            suggestions.append("• 针对丢包问题，建议:")
            suggestions.append("  - 检查网络设备（路由器、交换机）状态")
            suggestions.append("  - 检查物理连接（网线、接口）")
            suggestions.append("  - 联系ISP检查线路质量")

        if avg_icmp > 200:
            suggestions.append("• 整体延迟较高，建议:")
            suggestions.append("  - 考虑更换ISP或升级网络套餐")
            suggestions.append("  - 使用网络加速服务")
            suggestions.append("  - 优化应用架构，减少网络往返次数")

        if not suggestions:
            suggestions.append("• 网络性能良好，建议:")
            suggestions.append("  - 继续保持当前网络配置")
            suggestions.append("  - 定期监控网络性能")
            suggestions.append("  - 关注网络使用趋势，及时发现问题")

        analysis.extend(suggestions)
        analysis.append("")

        # 5. 网络健康状况评估
        if is_english:
            analysis.append("【5. Network Health Status Assessment】")
        else:
            analysis.append("【5. 网络健康状况评估】")
        health_score = 100

        if avg_icmp > 200:
            health_score -= 30
        elif avg_icmp > 100:
            health_score -= 15

        health_score -= len(high_latency_hops) * 5
        health_score -= len(high_jitter_hops) * 3
        health_score -= len(packet_loss_hops) * 10

        health_score = max(0, min(100, health_score))

        if is_english:
            if health_score >= 80:
                health_status = "Excellent"
            elif health_score >= 60:
                health_status = "Good"
            elif health_score >= 40:
                health_status = "Fair"
            else:
                health_status = "Needs Improvement"
            analysis.append(f"Health Score: {health_score}/100 ({health_status})")
            analysis.append(f"Problem Hops: {len(high_latency_hops) + len(high_jitter_hops) + len(packet_loss_hops)}")
            analysis.append("")
            analysis.append("=" * 60)
            analysis.append("Analysis Complete - Rule-based Intelligent Analysis")
            analysis.append("=" * 60)
            return {"analysis": "\n".join(analysis), "provider": "Local AI Analysis (No API required)"}
        else:
            if health_score >= 80:
                health_status = "优秀"
            elif health_score >= 60:
                health_status = "良好"
            elif health_score >= 40:
                health_status = "一般"
            else:
                health_status = "需要改进"
        analysis.append(f"健康评分: {health_score}/100 ({health_status})")
        analysis.append(f"问题跳数: {len(high_latency_hops) + len(high_jitter_hops) + len(packet_loss_hops)}")
        analysis.append("")
        analysis.append("=" * 60)
        analysis.append("分析完成 - 基于规则引擎的智能分析")
        analysis.append("=" * 60)
        return {"analysis": "\n".join(analysis), "provider": "本地智能分析（无需API）"}

    except Exception as e:
        error_msg = f"Local analysis failed: {str(e)}" if lang.lower() == 'en' else f"本地分析失败: {str(e)}"
        return {"error": error_msg}


@app.route("/analyze", methods=["POST"])
def analyze_route():
    """AI分析路由时延数据"""
    try:
        # 支持form和json两种格式
        if request.is_json:
            data = request.json
            session_id = data.get("session_id")
            ai_provider = data.get("ai_provider", "gemini")
            api_key = data.get("api_key")
            lang = data.get("lang", "zh")  # 获取语言参数
            ai_model = data.get("ai_model")  # 获取用户选择的模型
        else:
            session_id = request.form.get("session_id") or request.headers.get("X-Session-ID")
            ai_provider = request.form.get("ai_provider", "gemini")
            api_key = request.form.get("api_key")
            lang = request.form.get("lang", "zh")  # 获取语言参数
            ai_model = request.form.get("ai_model")  # 获取用户选择的模型

        if not session_id:
            error_msg = "Session ID is required" if lang.lower() == 'en' else "需要Session ID"
            return jsonify({"error": error_msg}), 400

        session_id, analysis_state = get_or_create_session(session_id)

        with analysis_state['lock']:
            hops = analysis_state['hops'].copy()

            # 获取ICMP和TCP数据
            icmp_data = {}
            for hop_num, data in analysis_state['icmp_data'].items():
                if data['times']:
                    icmp_data[hop_num] = {
                        'avg': round(statistics.mean(data['times']), 2),
                        'min': round(min(data['times']), 2),
                        'max': round(max(data['times']), 2),
                        'jitter': round(statistics.stdev(data['times']), 2) if len(data['times']) > 1 else 0.0,
                        'count': data['count'],
                        'loss': round(((data['count'] - len(data['times'])) / data['count'] * 100), 2) if data[
                                                                                                              'count'] > 0 else 0.0
                    }

            tcp_data = {}
            for hop_num, data in analysis_state['tcp_data'].items():
                # 确保所有节点都包含在TCP数据中，即使没有成功的ping结果
                if data['times']:
                    tcp_data[hop_num] = {
                        'avg': round(statistics.mean(data['times']), 2),
                        'min': round(min(data['times']), 2),
                        'max': round(max(data['times']), 2),
                        'jitter': round(statistics.stdev(data['times']), 2) if len(data['times']) > 1 else 0.0,
                        'count': data['count'],
                        'loss': round(((data['count'] - len(data['times'])) / data['count'] * 100), 2) if data[
                                                                                                              'count'] > 0 else 0.0
                    }
                elif data['count'] > 0:
                    # 即使没有成功的ping，也包含节点信息（用于显示测试次数和丢包率）
                    tcp_data[hop_num] = {
                        'avg': None,
                        'min': None,
                        'max': None,
                        'jitter': 0.0,
                        'count': data['count'],
                        'loss': 100.0  # 所有ping都失败，丢包率100%
                    }

            target = analysis_state.get('target', 'Unknown')

        # 调用AI分析，传递语言参数
        result = analyze_with_ai(hops, icmp_data, tcp_data, target, ai_provider, api_key, lang, ai_model)

        return jsonify(result)

    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f"AI Analysis error: {error_msg}")
        print(traceback.format_exc())
        return jsonify({"error": error_msg}), 500


@app.route("/status", methods=["GET"])
def get_status():
    """获取当前测试状态和最新数据"""
    session_id = request.args.get("session_id") or request.headers.get("X-Session-ID")

    if not session_id:
        return jsonify({"error": "Session ID is required"}), 400

    session_id, analysis_state = get_or_create_session(session_id)

    with analysis_state['lock']:
        analysis_state['last_activity'] = datetime.now()

        hops = []
        for hop in analysis_state['hops']:
            hop_copy = hop.copy()
            # 添加坐标信息（如果可用）
            if hop_copy.get('ip') and hop_copy['ip'] != '*':
                lat, lon, loc = get_location_with_coords(hop_copy['ip'])
                hop_copy['lat'] = lat
                hop_copy['lon'] = lon
                # 如果位置查询失败，保持原有的 location（不覆盖为"未知"）
                if loc and loc != "未知" and loc != "未知（数据库不可用）":
                    hop_copy['location'] = loc
                # 如果位置是"未知"，使用备用描述
                elif hop_copy.get('location') in ["未知", "未知（数据库不可用）"]:
                    hop_num = hop_copy.get('hop', '0')
                    try:
                        hop_num_int = int(hop_num)
                        if hop_num_int == 1:
                            hop_copy['location'] = "Local Gateway"
                        elif hop_num_int == 2:
                            hop_copy['location'] = "ISP Backbone"
                        else:
                            hop_copy['location'] = f"Hop {hop_num} Node"
                    except:
                        pass
            hops.append(hop_copy)

        # 处理显示数据（优先使用有数据的方法）
        ping_data = {}
        for hop_num, data in analysis_state['ping_data'].items():
            if data['times']:
                ping_data[hop_num] = {
                    'avg': round(statistics.mean(data['times']), 2),
                    'min': round(min(data['times']), 2),
                    'max': round(max(data['times']), 2),
                    'jitter': round(statistics.stdev(data['times']), 2) if len(data['times']) > 1 else 0.0,
                    'count': data['count'],
                    'loss': round(((data['count'] - len(data['times'])) / data['count'] * 100), 2) if data[
                                                                                                          'count'] > 0 else 0.0,
                    'times': data['times'][-20:]  # 返回最近20个数据点
                }

        # 处理ICMP数据
        icmp_data = {}
        for hop_num, data in analysis_state['icmp_data'].items():
            if data['times']:
                icmp_data[hop_num] = {
                    'avg': round(statistics.mean(data['times']), 2),
                    'min': round(min(data['times']), 2),
                    'max': round(max(data['times']), 2),
                    'jitter': round(statistics.stdev(data['times']), 2) if len(data['times']) > 1 else 0.0,
                    'count': data['count'],
                    'loss': round(((data['count'] - len(data['times'])) / data['count'] * 100), 2) if data[
                                                                                                          'count'] > 0 else 0.0,
                    'times': data['times'][-20:]  # 返回最近20个数据点
                }

        # 处理TCP数据
        tcp_data = {}
        for hop_num, data in analysis_state['tcp_data'].items():
            # 确保所有节点都包含在TCP数据中，即使没有成功的ping结果
            if data['times']:
                tcp_data[hop_num] = {
                    'avg': round(statistics.mean(data['times']), 2),
                    'min': round(min(data['times']), 2),
                    'max': round(max(data['times']), 2),
                    'jitter': round(statistics.stdev(data['times']), 2) if len(data['times']) > 1 else 0.0,
                    'count': data['count'],
                    'loss': round(((data['count'] - len(data['times'])) / data['count'] * 100), 2) if data[
                                                                                                          'count'] > 0 else 0.0,
                    'times': data['times'][-20:]  # 返回最近20个数据点
                }
            elif data['count'] > 0:
                # 即使没有成功的ping，也包含节点信息（用于显示测试次数和丢包率）
                tcp_data[hop_num] = {
                    'avg': None,
                    'min': None,
                    'max': None,
                    'jitter': 0.0,
                    'count': data['count'],
                    'loss': 100.0,  # 所有ping都失败，丢包率100%
                    'times': []  # 没有成功的数据点
                }

        return jsonify({
            'is_running': analysis_state['is_running'],
            'hops': hops,
            'ping_data': ping_data,
            'icmp_data': icmp_data,
            'tcp_data': tcp_data,
            'session_id': session_id,
            'target': analysis_state.get('target')
        })


def continuous_ping_test(session_id):
    """持续ping测试循环"""
    session_id, analysis_state = get_or_create_session(session_id)

    while True:
        with analysis_state['lock']:
            if analysis_state['should_stop']:
                analysis_state['is_running'] = False
                break
            if not analysis_state['is_running']:
                break
            hops = analysis_state['hops'].copy()
            analysis_state['last_activity'] = datetime.now()

        if not hops:
            time.sleep(1)
            continue

        # 对每个跳进行ping测试
        for hop in hops:
            with analysis_state['lock']:
                if analysis_state['should_stop']:
                    break

            hop_num = hop['hop']
            hop_ip = hop.get('ip')

            if not hop_ip or hop_ip == '*':
                continue

            # 执行ping（ICMP优先，超时则使用TCP）
            icmp_result, tcp_result, display_result = ping_with_fallback(hop_ip, port=80)
            current_timestamp = datetime.now()

            with analysis_state['lock']:
                # 初始化数据结构
                if hop_num not in analysis_state['ping_data']:
                    analysis_state['ping_data'][hop_num] = {'times': [], 'count': 0}
                if hop_num not in analysis_state['icmp_data']:
                    analysis_state['icmp_data'][hop_num] = {'times': [], 'count': 0}
                if hop_num not in analysis_state['tcp_data']:
                    analysis_state['tcp_data'][hop_num] = {'times': [], 'count': 0}

                # 记录ICMP数据
                analysis_state['icmp_data'][hop_num]['count'] += 1
                if icmp_result is not None:
                    analysis_state['icmp_data'][hop_num]['times'].append(icmp_result)
                    if len(analysis_state['icmp_data'][hop_num]['times']) > 100:
                        analysis_state['icmp_data'][hop_num]['times'].pop(0)

                # 记录TCP数据 - 无论成功还是失败都记录一次尝试
                # 确保TCP ping对所有节点都进行测试，和ICMP一样
                analysis_state['tcp_data'][hop_num]['count'] += 1
                if tcp_result is not None:
                    analysis_state['tcp_data'][hop_num]['times'].append(tcp_result)
                    if len(analysis_state['tcp_data'][hop_num]['times']) > 100:
                        analysis_state['tcp_data'][hop_num]['times'].pop(0)
                # 注意：即使tcp_result为None（连接失败），count也已经增加，这样可以正确计算丢包率

                # 显示数据：优先使用有数据的方法
                analysis_state['ping_data'][hop_num]['count'] += 1
                if display_result is not None:
                    analysis_state['ping_data'][hop_num]['times'].append(display_result)
                    # 限制历史记录数量
                    if len(analysis_state['ping_data'][hop_num]['times']) > 100:
                        analysis_state['ping_data'][hop_num]['times'].pop(0)

                    # 记录带时间戳的时延数据（包含ICMP和TCP）
                    ping_record = {
                        'timestamp': current_timestamp.isoformat(),
                        'delay': display_result,
                        'icmp': icmp_result,
                        'tcp': tcp_result
                    }
                    analysis_state['ping_history'][hop_num].append(ping_record)

                    # 保存到文件（异步保存，避免阻塞）
                    data_file_path = analysis_state.get('data_file_path')
                    csv_file_path = analysis_state.get('csv_file_path')

                    if data_file_path:
                        try:
                            # 读取现有数据
                            if os.path.exists(data_file_path):
                                with open(data_file_path, 'r', encoding='utf-8') as f:
                                    file_data = json.load(f)
                            else:
                                file_data = {
                                    'target': analysis_state.get('target', ''),
                                    'start_time': analysis_state.get('start_time',
                                                                     datetime.now()).isoformat() if analysis_state.get(
                                        'start_time') else datetime.now().isoformat(),
                                    'hops': [],
                                    'ping_records': {},
                                    'icmp_records': {},
                                    'tcp_records': {}
                                }

                            # 更新 ping_records（包含ICMP和TCP）
                            if hop_num not in file_data['ping_records']:
                                file_data['ping_records'][hop_num] = []
                            file_data['ping_records'][hop_num].append(ping_record)

                            # 更新ICMP记录
                            if hop_num not in file_data['icmp_records']:
                                file_data['icmp_records'][hop_num] = []
                            if icmp_result is not None:
                                file_data['icmp_records'][hop_num].append({
                                    'timestamp': current_timestamp.isoformat(),
                                    'delay': icmp_result
                                })

                            # 更新TCP记录
                            if hop_num not in file_data['tcp_records']:
                                file_data['tcp_records'][hop_num] = []
                            if tcp_result is not None:
                                file_data['tcp_records'][hop_num].append({
                                    'timestamp': current_timestamp.isoformat(),
                                    'delay': tcp_result
                                })

                            # 更新 hops（如果还没有）
                            if not file_data['hops']:
                                file_data['hops'] = [h.copy() for h in analysis_state['hops']]

                            # 保存JSON文件
                            with open(data_file_path, 'w', encoding='utf-8') as f:
                                json.dump(file_data, f, indent=2, ensure_ascii=False)
                        except Exception as e:
                            print(f"Error saving ping data to JSON file: {e}")

                    # 保存到CSV文件（同时记录ICMP和TCP）
                    if csv_file_path:
                        try:
                            with open(csv_file_path, 'a', encoding='utf-8-sig', newline='') as f:
                                writer = csv.writer(f)
                                writer.writerow([
                                    hop_num,
                                    current_timestamp.isoformat(),
                                    icmp_result if icmp_result is not None else '',
                                    tcp_result if tcp_result is not None else '',
                                    display_result if display_result is not None else ''
                                ])
                        except Exception as e:
                            print(f"Error saving ping data to CSV file: {e}")

        time.sleep(0.5)  # 每轮之间延迟


def run_server():
    """在单独线程中运行Flask服务器"""
    global server_instance
    from werkzeug.serving import make_server
    server_instance = make_server("127.0.0.1", 7090, app, threaded=True)
    try:
        server_instance.serve_forever()
    except Exception as e:
        print(f"Server error: {e}")
    finally:
        if server_instance:
            try:
                server_instance.shutdown()
            except:
                pass


if __name__ == "__main__":
    # 注册信号处理器，优雅退出
    def signal_handler(sig, frame):
        print("\nReceived interrupt signal, shutting down...")
        shutdown_flag.set()
        sys.exit(0)


    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 在单独线程中启动Flask服务器
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # 等待服务器启动
    time.sleep(1.5)

    # 打开浏览器
    url = "http://127.0.0.1:7090"
    try:
        webbrowser.open(url)
        print(f"Browser opened: {url}")
    except Exception as e:
        print(f"Failed to open browser: {e}")

    print("Starting server at http://127.0.0.1:7090")
    print("Press Ctrl+C to stop the server")

    # 等待关闭信号
    try:
        while not shutdown_flag.is_set():
            time.sleep(0.5)
            # 检查服务器线程是否还在运行
            if not server_thread.is_alive():
                break
    except KeyboardInterrupt:
        print("\nReceived keyboard interrupt")
        shutdown_flag.set()

    # 关闭所有会话
    print("Stopping all analysis sessions...")
    with sessions_lock:
        for session_id, state in list(analysis_sessions.items()):
            with state['lock']:
                state['should_stop'] = True
                state['is_running'] = False

    # 等待一下让线程清理
    time.sleep(1)

    print("Server shutdown complete")
    os._exit(0)

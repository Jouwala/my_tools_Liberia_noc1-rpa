from flask import Flask, render_template, redirect, request
from werkzeug.middleware.dispatcher import DispatcherMiddleware
import os
import sys
import importlib.util

# 保存当前工作目录
base_dir = os.path.dirname(os.path.abspath(__file__))
original_cwd = os.getcwd()

# 定义项目路径
ip_trace_path = os.path.join(base_dir, "IP_Trace_Tool")
incident_path = os.path.join(base_dir, "incident_overview")
sp_dashboard_path = os.path.join(base_dir, "WareHouseDashBoard")
sp_ug_path = os.path.join(base_dir, "WareHouseDashBoard_UG")
sp_cg_path = os.path.join(base_dir, "WareHouseDashBoard_CG")
sp_mmr_path = os.path.join(base_dir, "WareHouseDashBoard_MMR")
sp_npl_path = os.path.join(base_dir, "WareHouseDashBoard_NPL")

# 添加路径到sys.path（用于标准导入）
sys.path.insert(0, ip_trace_path)
sys.path.insert(0, incident_path)


def load_app_module(module_path, module_name):
    """动态加载Flask应用模块，避免模块名冲突"""
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module spec from {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.app


def configure_app_folders(app, app_path):
    """配置应用的template_folder和static_folder"""
    templates_path = os.path.join(app_path, "templates")
    static_path = os.path.join(app_path, "static")

    if not hasattr(app, "template_folder") or app.template_folder == "templates":
        if os.path.isdir(templates_path):
            app.template_folder = templates_path
    elif app.template_folder == ".":
        if os.path.isdir(templates_path):
            app.template_folder = templates_path

    if not hasattr(app, "static_folder") or app.static_folder == "static":
        if os.path.isdir(static_path):
            app.static_folder = static_path
    elif app.static_folder == ".":
        if os.path.isdir(static_path):
            app.static_folder = static_path

    return app


def import_sub_app(app_path, app_name):
    """导入子应用的统一方法，自动管理工作目录，优先使用 app_sp_optimized.py"""
    original_cwd_local = os.getcwd()
    path_was_added = False

    try:
        os.chdir(app_path)

        if app_path not in sys.path:
            sys.path.insert(0, app_path)
            path_was_added = True

        app_py_files = [
            f for f in os.listdir(app_path)
            if f.endswith(".py") and not f.startswith("__")
        ]
        has_app_sp_optimized = "app_sp_optimized.py" in app_py_files
        has_app_sp = "app_sp.py" in app_py_files
        has_app = "app.py" in app_py_files

        if app_name in ("ip_trace", "incident"):
            if has_app_sp_optimized:
                app_file = os.path.join(app_path, "app_sp_optimized.py")
                module_name = f"{app_name}_module"
                app = load_app_module(app_file, module_name)
            elif has_app_sp:
                app_file = os.path.join(app_path, "app_sp.py")
                module_name = f"{app_name}_module"
                app = load_app_module(app_file, module_name)
            else:
                if app_name == "ip_trace":
                    from ip_detect_tool import app as app  # type: ignore
                else:
                    from app import app as app  # type: ignore
        else:
            if has_app_sp_optimized:
                app_file = os.path.join(app_path, "app_sp_optimized.py")
            elif has_app_sp:
                app_file = os.path.join(app_path, "app_sp.py")
            elif has_app:
                app_file = os.path.join(app_path, "app.py")
            else:
                raise FileNotFoundError(
                    f"No app_sp_optimized.py, app_sp.py or app.py found in {app_path}"
                )

            module_name = f"{app_name}_module"
            app = load_app_module(app_file, module_name)

        app = configure_app_folders(app, app_path)
        return app

    except Exception as e:
        print(f"Error importing {app_name}: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        os.chdir(original_cwd_local)
        if path_was_added and app_path in sys.path:
            sys.path.remove(app_path)


# 导入应用 - 使用重构后的统一方法
ip_trace_app = import_sub_app(ip_trace_path, "ip_trace")
incident_app = import_sub_app(incident_path, "incident")
sp_dashboard_app = import_sub_app(sp_dashboard_path, "sp_dashboard")
sp_ug_app = import_sub_app(sp_ug_path, "sp_ug")
sp_cg_app = import_sub_app(sp_cg_path, "sp_cg")
sp_mmr_app = import_sub_app(sp_mmr_path, "sp_mmr")
sp_npl_app = import_sub_app(sp_npl_path, "sp_npl")

# 创建主应用用于根路由，显式指定模板目录（更稳妥）
main_app = Flask(__name__, template_folder="templates")

# 使用DispatcherMiddleware整合应用
application = DispatcherMiddleware(
    main_app,
    {
        "/ip-trace": ip_trace_app,
        "/incident": incident_app,
        "/sp_lbr": sp_dashboard_app,
        "/sp_ug": sp_ug_app,
        "/sp_cg": sp_cg_app,
        "/sp_mmr": sp_mmr_app,
        "/sp_npl": sp_npl_app,
    },
)


@main_app.route("/")
def index():
    """主页面 - 提供统一导航入口"""
    return render_template("index.html")


@main_app.route("/api/data")
def redirect_api_data():
    """重定向/api/data请求到/sp_lbr/api/data"""
    return redirect("/sp_lbr/api/data")


@main_app.route("/api/details")
def redirect_api_details():
    """重定向/api/details请求到/sp_lbr/api/details"""
    params = request.query_string.decode("utf-8")
    if params:
        return redirect(f"/sp_lbr/api/details?{params}")
    return redirect("/sp_lbr/api/details")


if __name__ == "__main__":
    import threading
    import time
    import webbrowser
    import signal
    from werkzeug.serving import make_server
    from werkzeug.serving import BaseWSGIServer

    shutdown_flag = threading.Event()
    server_instance = None

    def run_server():
        """在单独线程中运行Flask服务器"""
        nonlocal_server: dict[str, BaseWSGIServer | None] = {"instance": None}
        nonlocal_server["instance"] = make_server(
            "192.168.100.19", 7038, application, threaded=True
        )

        try:
            nonlocal_server["instance"].serve_forever()
        except Exception as e:
            print(f"Server error: {e}")
        finally:
            if nonlocal_server["instance"]:
                try:
                    nonlocal_server["instance"].shutdown()
                except Exception:
                    pass

    def signal_handler(sig, frame):
        print("\nReceived interrupt signal, shutting down...")
        shutdown_flag.set()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    time.sleep(1.5)

    url = "http://127.0.0.1:7038"
    try:
        webbrowser.open(url)
        print(f"Browser opened: {url}")
    except Exception as e:
        print(f"Failed to open browser: {e}")

    print("Starting unified server at http://127.0.0.1:7038")
    print("Available routes:")
    print("  - http://127.0.0.1:7038/ - 导航页面")
    print("  - http://127.0.0.1:7038/ip-trace - IP追踪工具")
    print("  - http://127.0.0.1:7038/incident - 事件概览仪表板")
    print("  - http://127.0.0.1:7038/sp_lbr - 仓库仪表板(默认)")
    print("  - http://127.0.0.1:7038/sp_ug - 乌干达仓库仪表板")
    print("  - http://127.0.0.1:7038/sp_cg - 刚果仓库仪表板")
    print("  - http://127.0.0.1:7038/sp_mmr - 缅甸仓库仪表板")
    print("  - http://127.0.0.1:7038/sp_npl - 尼泊尔仓库仪表板")
    print("Press Ctrl+C to stop the server")

    try:
        while not shutdown_flag.is_set():
            time.sleep(0.5)
            if not server_thread.is_alive():
                break
    except KeyboardInterrupt:
        print("\nReceived keyboard interrupt")
        shutdown_flag.set()

    print("Server shutdown complete")
    os._exit(0)

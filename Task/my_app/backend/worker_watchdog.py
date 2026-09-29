"""Worker 看门狗 (Watchdog) —— 保证 backend.worker 持续运行、崩溃自动拉起

设计要点：
- 本进程是 worker 的父进程（subprocess 托管），轮询子进程存活；
- worker 异常退出（崩溃 / 被误杀）后，按退避策略自动重新拉起；
  worker.py 自身仍会把 PID 写入 backend/worker.pid，stop.bat 原机制继续可用；
- 停止：stop.bat 树杀本进程 (taskkill /PID <watchdog> /T /F)，连带 worker 一起停，
  且本进程被树杀后不会再复活 worker（_shutdown 置位）；
- 自身 PID 写入 backend/worker_watchdog.pid，供 stop.bat 定位。

启动（替代原 start.bat 中的 `python -m backend.worker`）：
    python -m backend.worker_watchdog
"""
import os
import sys
import time
import json
import signal
import logging
import subprocess
from datetime import datetime
from pathlib import Path

# 重启留痕（2026-09-10 加）：worker 的每一次世代更替都写入
# log/worker_restart_marker.log，让「多 worker 同退是谁干的」一眼可归因。
# 见 backend/restart_marker.py 顶部的事故背景说明。
try:
    from backend.restart_marker import append_marker, recent_intent
except Exception:  # pragma: no cover - 兼容非 -m 方式直接执行
    try:
        from .restart_marker import append_marker, recent_intent
    except Exception:
        def append_marker(*_a, **_k):
            pass

        def recent_intent(*_a, **_k):
            return None

# 项目根目录（backend 的父目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 2026-09-11：日志不再把句柄交给子进程继承，改由父进程 pipe 泵 + 按大小轮转
# （详见 backend/log_writer.py 的模块说明）。
try:
    from backend.log_writer import attach_rotating_output
except ImportError:  # pragma: no cover - 兼容非 -m 方式直接执行
    sys.path.insert(0, str(PROJECT_ROOT))
    from backend.log_writer import attach_rotating_output
BACKEND_DIR = PROJECT_ROOT / "backend"

PID_FILE = Path(os.environ.get(
    "MY_APP_WORKER_WATCHDOG_PID",
    str(BACKEND_DIR / "worker_watchdog.pid")
))
LOG_DIR = PROJECT_ROOT / "log"
# default（未分组）组沿用的旧文件名；分组 worker 各写 worker_runtime_<group>.log
# 2026-09-11：文件名加启动日期，配合 log_cleanup 定时任务做 7 天保留。
# Windows 下被进程占用的文件无法被外部重命名/删除，只能在写入方按日期分文件。
_LOG_DATE = datetime.now().strftime("%Y%m%d")
WORKER_LOG = LOG_DIR / f"worker_runtime_{_LOG_DATE}.log"
WATCHDOG_LOG = LOG_DIR / f"worker_watchdog_{_LOG_DATE}.log"


def worker_log_path(group: str) -> Path:
    """返回某组 worker 的日志文件路径（每组一个文件 = 单一写入者）。

    2026-09-10 改造原因：此前 4 组 worker 的 stdout/stderr 全部重定向到同一个
    worker_runtime.log —— 由本模块 open(...,"ab") 打开一个句柄后作为同一个（被继承的）
    句柄传给 4 个子进程。多个进程共用一个继承句柄即共享文件位置，并发写会互相打断：
    实测出现撕裂行（`2026-08-21 2026-08-21 13:00:01,171 ...`、
    `2026-09-10 2026-09-10 09:56:36,166 ...`），并且**文件里的行序完全不代表时序**
    （不同 worker 的行按调度交错，排障时极易把「顺序」误读成「因果」）。
    改为每组一个文件后：每个文件只有一个写入者 → 行不会被撕裂，且
    **文件内行序 == 该 worker 的时序**，可直接据此判断单组是否并发/串行。
    命名保持 worker_runtime 前缀，`log/worker_runtime*.log` 一把即可搜全部分组。
    """
    g = str(group or "").strip()
    if not g or g == "default":
        return WORKER_LOG
    safe = "".join(ch for ch in g if ch.isalnum() or ch in "-_") or "default"
    return LOG_DIR / f"worker_runtime_{safe}_{_LOG_DATE}.log"

POLL_INTERVAL = 2.0        # 子进程状态轮询间隔（秒）
CRASH_THRESHOLD = 10.0     # 子进程存活短于此值（秒）视为异常崩溃
MAX_BACKOFF = 30.0         # 最大退避间隔（秒）
STARTUP_FAIL_LIMIT = 10    # 连续快速崩溃达到此次数则放弃并告警

# ===== 多 worker 分组配置 =====
# MY_APP_WORKER_GROUPS=u,n,m：按数据源会话/写库把任务分成互不干扰的组，
# 每组一个独立 worker 进程并行消费；组内串行（与旧行为完全一致），组间并行
# （行为等价并发）。每组任务清单见 GROUP_TASK_MAP；未配置时保持单 worker 全量。
GROUP_TASK_MAP = {
    "u": (  # UME 192.168.170.2 单账号会话：必须串行
        "ran_ume_daily,main_kpi_sync,cell_availability_sync,network_kpi_sync,packet_loss_sync,"
        "packet_loss_email,battery_kpi_sync,ipran_kpi_sync,cm_data_sync,"
        # cells_kpi_sync 2026-09-11 补录：该任务直接调用 ran_cell_availability_sync 的
        # run_cell_availability_sync()（同一 UME 单账号会话 + 同一份原始库
        # data/ran_kpi_avalability_1day.sqlite3），必须与 cell_availability_sync 同组串行。
        # 2026-09-11 10:48 注册任务时漏了本步骤 → 无 worker 认领，队列 pending 卡死
        # （新任务必须显式分组，同 sp_material_sync / log_cleanup 的教训）
        "cells_kpi_sync,"
        # avail_recon_sync 2026-09-21 注册：重建可用率核对宽表（读远端 Site_Daily，
        # 写本机 data/avail_recon.sqlite3）。归 u 组的理由：源表 2G/3G/4G_Main_Kpi_Site_Daily
        # 正是同组 main_kpi_sync(04:00) 写的，同组串行 + 排队先后即可保证「先写后读」，
        # 也避免与写入方并发。此前该表由已退役的 my-finebi 手工 ETL 维护，
        # 无人调度 → 冻结在 2026-09-13，看板静默停更（本次事故）。
        "avail_recon_sync,"
        # bp_report_sync 2026-09-29 注册：从 RAN_UME 更新 BP 劣化小区报告
        # （读远端 4G_Main_Kpi_Cell_Daily，写本机 data/bp_report.sqlite3）。
        # 归 u 组的理由同 avail_recon_sync：源表正是同组 main_kpi_sync(04:00) 写的，
        # 同组串行 + 排队先后即可保证「先写后读」。本任务不新建 UME PM 模板
        # （templateid 必须服务端已存在，不可臆造），只复用已物化的那张表。
        "bp_report_sync"),
    "n": (  # eFlow API / config-center 同源会话组（2026-09-27 收窄：s/w 两组已拆出）
        # 【2026-09-27 拆组背景】本组原先 17 项，实测近 24h 单 worker 串行占用：
        #   sp_data_sync 347min + eflow_sync 236min + eflow_active_alarm 103min = 686min/天，
        #   即该 worker 约 48% 时间在忙，且全部挤在同一条串行道上；队列实测等待达
        #   mw_ume_kpi_sync_rt 964s / eflow_active_alarm 688s（本机 28 逻辑核基本闲置）。
        # 更严重的是**故障域**：worker.py:83-93 记载 sp_data_sync 的 SFTP channel 读挂死
        # 5.5h，因同组串行把整个 n 组（含 MW 实时看板、实时告警）一起拖停摆。
        # 拆组依据为「上游会话/写库是否真的互斥」，不是「任务像不像」：
        #   sp_data_sync → 远端 SFTP 10.100.20.11（独占 channel）+ UNC 镜像库；与 eFlow 无共享 → 拆到 s
        #   mw_ume_*     → MW UME 网管（credential_store key=mw_ume）独立会话 → 拆到 w
        # 保留在本组的都是 eFlow API / config-center 同源或保守依赖，必须继续串行。
        "eflow_sync,eflow_sync_full,eflow_active_alarm,eflow_history_alarm,eflow_tt_rules_check,"
        "ms_sla_full,cnn_kpi_sync,fw_kpi_sync,"
        # sp_online_sync 2026-09-02 补录：SP 在线工单走 eFlow API 同源会话，归入 eFlow 组
        "sp_online_sync,"
        # sp_material_sync 2026-09-09 补录：SP 物料主数据同样走 eFlow API 同源会话，
        # 新建任务必须显式分组，否则无 worker 认领 → 队列 pending 卡死直到 300s 超时
        "sp_material_sync,"
        # eflow_alarm_rules_collect 2026-09-02 补录：eFlow 告警关联规则收集，走 eFlow API 同源会话
        "eflow_alarm_rules_collect,"
        # eflow_push_rules_collect 2026-09-03 补录：eFlow 推单规则收集，走 config-center 同源会话
        "eflow_push_rules_collect,"
        # ume_in_kpi_sync 2026-09-15 补录：UME Dong customer 业务 KPI（门户 172.17.208.1:28808，
        # 与 MW UME 不同主机/不同会话，但与其它网管类任务保守同组）
        "ume_in_kpi_sync,"
        # ume_in_osg_report 2026-09-18 注册：客户业务 KPI + OSG 周报邮件（每天 06:30）。
        # 第 1 步就调用 ume_in_kpi_service.run_ume_in_kpi_sync()，与 ume_in_kpi_sync 共用
        # 同一 UME Dong 门户会话，必须同组串行（且第 3 步走 EWS 发信，组内串行不影响时效）。
        "ume_in_osg_report"),
    "s": (  # SP 备件 SFTP 组（2026-09-27 从 n 组拆出）：上游是**独立 SFTP 服务器**
        # （get_sp_table.py:68 SFTP_HOST，独占 channel），成功后另做 UNC 网络路径镜像
        # 写 FineBI 的 WareHouseDashBoard/inventory.db（get_sp_table.py:86-88）。
        # 拆出理由有二：
        #   ① 它是 n 组最大的单体负载：实测 39 次/天 × 平均 534s ≈ 347min/天，串行时
        #      每个小时级 eFlow 采集都要排在它后面；
        #   ② 它是 n 组已知的**挂死源**：worker.py:83-93 记载其 SFTP channel 读挂死
        #      5.5h，同组串行导致整组（含实时告警）停摆。独立成组后，即使再次挂死
        #      （仍由 WORKER_TASK_MAX_SECONDS=4h 兜底强杀重拉）也**只影响 s 组自身**。
        # 与 eFlow/config-center/UME 无任何会话或写库交集，串行约束仅为自己内部
        # （多次投递需按序写同一批 SP 表），故单独成组。
        "sp_data_sync"),
    "w": (  # MW UME 微波网管组（2026-09-27 从 n 组拆出）：独立于 eFlow 的网管会话
        # （credential_store key=mw_ume，mw_ume_kpi_service.py:98-107 运行时取凭据）。
        # 两个任务写同一张库/同族表（mw_ume_bw_ultilazation 与 _rt），必须彼此串行，
        # 但与非 MW 任务无共享，故整组平移到 w，不与 n 组抢同一条串行道。
        # 其中 mw_ume_kpi_sync_rt 是 */15 高频任务，实测 153 次/天，此前每次都要排在
        # sp_data_sync（>8min/次）后面，队列等待实测达 964s（全场最久）→ 实时看板滞后。
        "mw_ume_kpi_sync,mw_ume_kpi_sync_rt"),
    "v": (  # VMAX 门户（本机 8790 单会话代理）：三个任务共用同一个 VMAX 会话，必须彼此串行。
        # 2026-09-18 从 n 组拆出独立成组：它们与 eFlow/网管任务本就无会话冲突，混在 n 组只会
        # 让每小时 :15/:45 的 VMAX 采集排在 sp_data_sync（实测 1.5~2h）、ms_sla_full 等长任务
        # 后面，看板与 vreport 明细长期滞后一个多小时。拆组后 n 组 16 项、v 组 3 项并行消费。
        # ⚠ 新增分组必须同步三处，否则该组任务仍然无人认领：
        #   start_hidden.ps1 的 MY_APP_WORKER_GROUPS、restart_workers.py 的 ALL_GROUPS、
        #   以及本表（守卫 tests/test_worker_group_coverage.py 会交叉校验三处一致性）。
        # cxo_dashboard_cache_sync 2026-09-02 补录：CXO 看板缓存同步（每 10 分钟）经 8790
        # VMAX 代理进程（DETACHED、单会话）取数
        "cxo_dashboard_cache_sync,"
        # vmax_cxo_daily_sync 2026-09-15 补录：VMAX CXO 天粒度日值归档（每小时 :15），
        # 写独立目录 data/vmax_cxo_daily/
        "vmax_cxo_daily_sync,"
        # vmax_multi_data_sync 2026-09-18 补录：任务 41（每小时 :45）vreport 明细采集。
        # 上线时只登记了 TASK_SPECS、漏登记本表 → 队列 id=39082（created 2026-09-16T19:45）
        # 无人认领一直 pending，且这条陈旧 pending 占住该任务
        # 的单飞名额，把之后每一次小时级调度全部挡掉（vreport 明细断档约 37 小时）。
        # 教训同 finebi_report_sync / whatsapp_send_ext / sp_email_details：第四次踩坑。
        "vmax_multi_data_sync"),
    "m": (  # 内务轻任务：EWS 邮件会话 + 截图/WhatsApp 文件依赖
        # whatsapp_send_ext 2026-08-31 补录：新注册时漏分组，无 worker 认领，
        # 任务管理页手动执行一直「队列中等待」直到 300s 超时（同下方 finebi 教训）
        "site_outage_screenshot,whatsapp_send,whatsapp_send_ext,liberia_email_1h,liberia_email_8h,"
        "kpi_ms_contract,kpi_ms_wo_sla,kpi_sp_spareparts,kpi_sp_consumables,"
        "kpi_ran_availability,email_recovery,ipran_m6k_chart_email,"
        "ccn_free_rating_chart_email,battery_email,mailbox_cleanup,"
        "incident_overview_sync,auto_retry_failed,db_freshness_check,sp_report_generate,"
        # sp_email_details 2026-09-01 补录：新注册时漏分组，无 worker 认领，
        # 任务管理页手动执行一直「队列中等待」直到 300s 超时（同 whatsapp_send_ext 教训）
        "sp_email_details,"
        # sp_online_report_generate/send 2026-09-02 补录：SP 在线未关闭单报表
        # 生成（06:00）+ 邮件/WhatsApp 发送（06:20），新任务显式分组防 pending 卡死
        "sp_online_report_generate,sp_online_report_send,"
        # mttr_tt_sync / progress_sync 2026-09-21 注册：MTTR/TT 与 Progress 宽表重建。
        # 数据源 Eflow_TT_FB / Eflow_WO_FB 由 n 组的 eflow_sync（每小时 :22）写，
        # 但本任务只用远端**只读** API + 写本机 data/*.sqlite3，不占任何业务会话；
        # 排在 :40/:50 取到的一定是 :22 那一版，故与 db_freshness_check 等内务任务同组。
        # 此前这两张表由已退役 my-finebi 的手工 ETL 维护，无调度 → 冻结在 2026-08-31。
        "mttr_tt_sync,progress_sync,"
        # sp_whatsapp_report 2026-09-09 补录：Comsumables&SpareParts 报表 WhatsApp 发送（07:15），
        # 新任务显式分组防 pending 卡死（同 whatsapp_send_ext / sp_email_details 教训）
        "sp_whatsapp_report,"
        # sp_material_report 2026-09-11 补录：SP 物料库存与消耗报表邮件（07:33），
        # 只读本地/PG 数据 + EWS 发信，内务轻任务，归 m 组。
        # 新任务必须显式分组，否则无 worker 认领 → 队列 pending 卡死直到 300s 超时
        "sp_material_report,"
        # finebi_report_sync/pg_to_sqlite_sync：注册表中存在但此前未分组，
        # 2026-08-25 分组模式启用后无任何 worker 认领，队列 pending 卡死断档
        "finebi_report_sync,pg_to_sqlite_sync,"
        # log_cleanup 2026-09-11 补录：日志文件清理（每天 03:17），内务轻任务。
        # 新任务必须显式分组，否则无 worker 认领 → 队列 pending 卡死直到 300s 超时
        "log_cleanup,"
        # tmp_cleanup 2026-09-18 注册：TMP 目录两段式回收（每天 03:47），同为内务轻任务。
        "tmp_cleanup,"
        # olib_soc_kpi_daily_sync / olib_soc_vmax_report 2026-09-18 补录：VMAX 数仓 GBase 8a
        # 直连取数（10.123.255.12:5258，只读），独立会话、只写 data/olib_soc_report/ 自己的
        # sqlite，与 m 组其它任务无会话/写库冲突（日增量几秒、月报约 4 分钟，量级可接受）。
        # 2026-09-16 上线时同样漏登记本表 → 两个任务从未执行过一次
        # （task_execution_log 0 条记录），队列 id=39422（created 2026-09-17T02:20）一直
        # pending + 单飞保护挡掉后续调度 → 90 天经营看板（?page=vmaxCxoDashboard_90Days）
        # 停在 2026-09-16（那天的数据还是手工 CLI 补进去的）。
        "olib_soc_kpi_daily_sync,olib_soc_vmax_report,"
        # tt_alarm_whatsapp_alert 2026-09-28 注册：eFlow P1 未清除 TT 告警 WhatsApp 推送
        # （*/15 高频）。归 m 组理由：与 whatsapp_send_ext 同属 WhatsApp 通道（共用
        # data/ 作业文件与扩展认领链路）；只**只读** eflow_tt、不占任何上游业务会话；
        # 自身只写 eflow_tt_whatsapp_alert_log（本任务独占表，与同组任务无写冲突）。
        # 该组已有 */15 的 mw_ume_kpi_sync_rt 先例，可承载高频任务。
        # 新任务必须显式分组，否则无 worker 认领 → 队列 pending 卡死直到 300s 超时
        "tt_alarm_whatsapp_alert"),
    "c": (  # CN EMS (10.100.2.240) 独立会话：缓存同步与日聚合共享 _pmcache/daily_raw.json，
        # 同组串行保证互斥（ems_kpi_cache_sync 每15分钟 + ems_kpi_daily 每天00:20）
        "ems_kpi_cache_sync,ems_kpi_daily"),
}
_WORKER_GROUPS = [g.strip() for g in
                  os.environ.get("MY_APP_WORKER_GROUPS", "").split(",") if g.strip()]
_GROUPS = _WORKER_GROUPS or ["default"]

logger = logging.getLogger("worker_watchdog")

_shutdown = False
_children = {}          # group -> Popen
_spawn_time = {}        # group -> spawn 时间戳
_crashes = {}           # group -> 连续崩溃计数
_backoff = {}           # group -> 当前退避秒数
_last_exit = {}         # group -> 最近一次观测到的退出码（供 worker_spawn 留痕携带，配对用）
_exit_marked = set()    # 已完成 worker_exit 留痕的 group，避免同一世代重复记

# 心跳文件：供外部守护（start_hidden.ps1 / MyApp_EnsureRunning）判断看门狗是否卡死。
# 进程在但心跳超过 3 分钟未更新 → 判定 hung，由守护脚本强杀后重新拉起。
HB_FILE = LOG_DIR / "heartbeat_worker_watchdog.json"
_last_hb = 0.0
_HB_INTERVAL = 15.0        # 心跳写入间隔（秒），2s 轮询循环下约每 15s 落盘一次


def _request_shutdown(signum, _frame):
    global _shutdown
    _shutdown = True
    logger.info(f"收到退出信号 ({signum})，准备停止 worker 并退出...")


def _another_watchdog_running() -> bool:
    """检查是否已有 watchdog 实例在跑（避免重复托管导致双 worker 抢队列）。"""
    if not PID_FILE.exists():
        return False
    try:
        pid_text = PID_FILE.read_text(encoding="utf-8").strip()
        if not pid_text:
            return False
        pid = int(pid_text)
    except (ValueError, OSError):
        return False
    if pid == os.getpid():
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            import ctypes.wintypes  # noqa: F401  确保 DWORD 可用
            kernel32 = ctypes.windll.kernel32
            # 显式 restype：ctypes 默认按 32 位 int 截断 64 位句柄，存活进程
            # 可能被误判为不存在 → 重复启动第二个 watchdog 抢队列。
            #
            # 用 PROCESS_QUERY_LIMITED_INFORMATION(0x1000)，不要用
            # PROCESS_QUERY_INFORMATION(0x0400)：后者受 Windows 完整性级别(MIC)
            # 约束——由计划任务 MyApp_AutoStart(RunLevel=Highest) 启动的进程完整性
            # 级别为 High，普通会话/定时任务(Medium) 对其 OpenProcess(0x0400) 直接
            # 返回 NULL，于是被误判为"watchdog 已死"并重复拉起实例。
            # 0x1000 仅查询进程存在性，不受 MIC 限制，足以完成存活判定。
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if h:
                # 2026-09-20 加固：OpenProcess 成功 ≠ 存活。taskkill /F 对卡在内核
                # 调用的进程发起终止后，进程对象可能长时间「已终止(exit_code≠259)
                # 但未回收」——此时它不可能再执行任何任务，若仍视为运行中，
                # 新 watchdog 会被互斥检查永久挡住（2026-09-20 全链停摆事故的
                # 死锁环：旧 watchdog 僵尸 → 新 watchdog 拒启 → 无人拉 worker）。
                kernel32.GetExitCodeProcess.restype = ctypes.c_int
                kernel32.GetExitCodeProcess.argtypes = [
                    ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.DWORD)]
                ec = ctypes.wintypes.DWORD()
                terminated = bool(kernel32.GetExitCodeProcess(h, ctypes.byref(ec))) \
                    and ec.value != 259  # 259 = STILL_ACTIVE
                kernel32.CloseHandle(h)
                if terminated:
                    try:
                        PID_FILE.unlink()
                    except OSError:
                        pass
                    return False
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, AttributeError, Exception):
        return False


def _spawn_worker(group: str):
    """拉起一组 worker 子进程，stdout/stderr 重定向到【本组专属】日志文件（追加）。
    分组 worker 带 MY_APP_WORKER_TASKS（仅认领本组任务）与独立 PID 文件。"""
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log_path = worker_log_path(group)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # 关键：worker 日志流是 charmap（Windows 非 tty 文件默认），中文日志会 UnicodeEncodeError
    # 导致截图等链路被静默打断。强制 UTF-8（与 backend/main.py 的 reconfigure 一致）。
    env["PYTHONUTF8"] = "1"
    # eFlow API 超时加固（与 backend_watchdog 一致）：连 10s / 读 30s / 重试 2 次。
    # worker 才是 eflow_sync 的实际执行方，必须同样注入，否则仍用默认 90s 读超时。
    env["EFLOW_CONNECT_TIMEOUT"] = os.environ.get("EFLOW_CONNECT_TIMEOUT", "10")
    env["EFLOW_READ_TIMEOUT"] = os.environ.get("EFLOW_READ_TIMEOUT", "30")
    env["EFLOW_HTTP_MAX_RETRIES"] = os.environ.get("EFLOW_HTTP_MAX_RETRIES", "2")
    # 执行模式一致性（2026-09-10 修复）：backend_watchdog 给 uvicorn 显式设了
    # MY_APP_TASK_QUEUE=1（只投递不执行），但本函数此前遗漏该变量，导致 worker 进程内
    # QUEUE_ENABLED=0 —— auto_retry 调用 task_runner.run_task_async 时会走 threading.Thread
    # 分支，在【同一进程内并发】拉起多个任务，撞上 CPython 的 import 竞态：
    #   ImportError: cannot import name 'HTTPAdapter' from partially initialized module
    #   'requests.adapters' (most likely due to a circular import)
    # 实测 2026-09-10 09:35:01 auto_retry 一次投递 eflow_sync/ipran_kpi_sync/mailbox_cleanup，
    # 三个任务在同一 worker 进程内被 3 个线程同时拉起，抢到导入锁的 eflow_sync 成功，
    # ipran_kpi_sync 与 mailbox_cleanup 双双失败。
    # 修复：与 backend_watchdog 对齐——worker 的 run_task_async 只投递 task_queue，
    # 由本 worker 主循环原子认领后串行执行（与 worker.py 文档声明的"串行执行"一致），
    # 彻底杜绝进程内并发首次导入。
    env["MY_APP_TASK_QUEUE"] = "1"
    task_list = GROUP_TASK_MAP.get(group, "")
    if task_list:
        env["MY_APP_WORKER_TASKS"] = task_list
        env["MY_APP_WORKER_PID"] = str(BACKEND_DIR / f"worker_{group}.pid")
    else:
        # default 组（未分组场景）：保持原 PID 文件，stop.bat 兼容
        env.pop("MY_APP_WORKER_TASKS", None)
        env.pop("MY_APP_WORKER_PID", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "backend.worker"],
        cwd=str(PROJECT_ROOT),
        env=env,
        # stdout/stderr 由父进程接管（不再是继承的文件句柄），日志写满
        # LOG_ROTATE_MAX_MB（默认 100MB）后自动切 _pN 分片，无需重启 worker。
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    attach_rotating_output(proc, log_path, name=f"worker-{group}")
    _children[group] = proc
    _spawn_time[group] = time.time()
    _exit_marked.discard(group)
    prev_exit = _last_exit.pop(group, None)
    logger.info(f"已拉起 worker[{group}]: pid={proc.pid} log={log_path.name} tasks={task_list or '全部'}")
    append_marker("worker_spawn", by="watchdog", groups=[group], pid=proc.pid,
                  prev_exit_code=prev_exit,
                  note=(f"tasks={len(task_list.split(','))}项" if task_list else "全部任务"))
    return proc.pid


def _terminate_child():
    """终止所有 worker 子进程（按组）。"""
    for group, proc in list(_children.items()):
        try:
            if proc.poll() is None:
                proc.kill()  # TerminateProcess：确保子进程退出
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
        except Exception as e:
            logger.warning(f"终止 worker[{group}] 子进程失败: {e}")
    _children.clear()


def _mark_exit(group: str, exit_code, lived: float) -> None:
    """记录一次 worker 退出留痕（同一世代只记一次）。

    退出码指纹（与用户级记忆一致，用于反推「谁杀的」）：
        1          = taskkill /F 或 Popen.kill()（TerminateProcess(h,1)）
        4294967295 = PowerShell Stop-Process -Force（.NET Process.Kill()）
        3221225786 = CTRL_C / 控制台关闭；1073807364 = 系统关机
    注意：本函数只能证明「退出码是多少」，无法证明「谁杀的」——
    「谁杀的」由发起方（restart_workers.py）写 restart_intent 留痕来回答。
    """
    if group in _exit_marked:
        return
    _exit_marked.add(group)
    _last_exit[group] = exit_code
    hint = {
        1: "taskkill /F 或 Popen.kill()",
        4294967295: "PowerShell Stop-Process -Force",
        3221225786: "CTRL_C / 控制台关闭",
        1073807364: "系统关机/重启",
        0: "正常退出",
    }.get(exit_code if isinstance(exit_code, int) else -1, "未知退出码")
    # 归因联动：回查最近 180s 内是否有覆盖本组的 restart_intent。
    # 有 → 明确标注是谁/为什么；无 → 标 ⚠ 疑自发退出，这才是真正需要排查的对象。
    try:
        intent = recent_intent([group], within_s=180.0)
    except Exception:
        intent = None
    if intent:
        note = (f"{hint} | 归因: 由 {intent['by']} 发起重启"
                f"({intent['age_s']}s 前, reason={intent['reason'] or '未说明'})")
    else:
        note = f"{hint} | ⚠ 无重启意图记录，疑自发退出/外部强杀"
    append_marker("worker_exit", by="watchdog", groups=[group], exit_code=exit_code,
                  lived_s=round(lived, 1), note=note)


def _write_heartbeat():
    """周期性写心跳文件（节流），供外部守护检测看门狗卡死。"""
    global _last_hb
    now = time.time()
    if now - _last_hb < _HB_INTERVAL:
        return
    _last_hb = now
    try:
        HB_FILE.write_text(
            json.dumps({
                "name": "worker_watchdog",
                "pid": os.getpid(),
                "ts": datetime.now().isoformat(timespec="seconds"),
            }, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _child_exit_code(proc):
    """读取子进程退出码；仍在运行返回 None（正常路径）。

    2026-09-20 加固：Windows 下 taskkill /F 对卡在内核调用（如无超时 SFTP 读）
    的子进程发起终止后，退出码已置值但进程对象未 signaled——proc.poll() 长期
    返回 None，_loop_once 的 wait(timeout) 永远超时，watchdog 永不重拉该组
    （2026-09-20 sp_data_sync 挂死事故：worker[n] 僵尸 15 分钟无人重拉）。
    这里直读 GetExitCodeProcess：非 STILL_ACTIVE(259) 即视为已退出，
    返回其退出码。"""
    if proc is None:
        return None
    rc = proc.poll()
    if rc is not None:
        return rc
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        import ctypes.wintypes
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        h = kernel32.OpenProcess(0x1000, False, proc.pid)
        if not h:
            return 1  # 对象已消失（等回收）：视作已退出
        try:
            kernel32.GetExitCodeProcess.restype = ctypes.c_int
            kernel32.GetExitCodeProcess.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.DWORD)]
            ec = ctypes.wintypes.DWORD()
            if kernel32.GetExitCodeProcess(h, ctypes.byref(ec)) and ec.value != 259:
                return ec.value
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return None
    return None


def _loop_once() -> bool:
    """单轮主循环：逐组确保 worker 存活。

    返回 False 表示应退出看门狗（收到停止信号）；
    抛出的未预期异常由 main() 统一捕获记录，防止看门狗静默死亡。
    """
    for group in list(_GROUPS):
        proc = _children.get(group)
        # 0) 2026-09-20：poll() 无法感知「已终止未排空」的僵尸子进程，
        #    直读退出码补判（见 _child_exit_code 文档）。
        zombied_exit = _child_exit_code(proc) if proc is not None else None
        # 1) 确保该组 worker 在跑
        if proc is None or proc.poll() is not None or zombied_exit is not None:
            if proc is not None:
                exit_code = proc.returncode if proc.returncode is not None else zombied_exit
                lived = time.time() - _spawn_time.get(group, 0.0)
                logger.warning(
                    f"worker[{group}] 已退出 (exit_code={exit_code}, 存活 {lived:.1f}s)，准备重新拉起"
                )
                _mark_exit(group, exit_code, lived)
                _children.pop(group, None)
            # 退避：连续快速崩溃时延迟重拉，避免死循环
            if _backoff.get(group, 0.0) > 0:
                logger.info(f"worker[{group}] 退避等待 {_backoff[group]:.1f}s 后重拉")
                waited = 0.0
                while waited < _backoff[group] and not _shutdown:
                    time.sleep(min(POLL_INTERVAL, _backoff[group] - waited))
                    waited += POLL_INTERVAL
                if _shutdown:
                    return False
            _spawn_worker(group)
            _crashes[group] = 0
            _backoff[group] = 0.0
            continue
        # 2) 该组 worker 存活，轮询等待（超时即仍在运行）
        try:
            proc.wait(timeout=POLL_INTERVAL)
        except subprocess.TimeoutExpired:
            if time.time() - _spawn_time.get(group, 0.0) >= CRASH_THRESHOLD:
                _crashes[group] = 0
                _backoff[group] = 0.0
            continue
        # 3) worker 退出（wait 返回且 poll 非 None）
        exit_code = proc.returncode
        lived = time.time() - _spawn_time.get(group, 0.0)
        logger.warning(f"worker[{group}] 退出 (exit_code={exit_code}, 存活 {lived:.1f}s)")
        _mark_exit(group, exit_code, lived)
        _children.pop(group, None)
        if _shutdown:
            return False
        if lived < CRASH_THRESHOLD:
            _crashes[group] = _crashes.get(group, 0) + 1
            _backoff[group] = min(MAX_BACKOFF, 2 ** _crashes[group])
            logger.warning(
                f"worker[{group}] 异常崩溃（存活过短），连续崩溃 {_crashes[group]} 次，"
                f"下次退避 {_backoff[group]:.1f}s"
            )
            if _crashes[group] >= STARTUP_FAIL_LIMIT:
                logger.error(
                    f"worker[{group}] 连续崩溃 {STARTUP_FAIL_LIMIT} 次，停止自动拉起"
                    f"（请检查 {worker_log_path(group).name}）。"
                )
                _GROUPS.remove(group)
        else:
            _crashes[group] = 0
            _backoff[group] = 0.0
    return True


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(WATCHDOG_LOG, encoding="utf-8")]
    if sys.stdout.isatty():
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        handlers=handlers,
    )
    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    if _another_watchdog_running():
        logger.error("已有 watchdog 在运行，拒绝重复启动。退出。")
        sys.exit(1)

    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception as e:
        logger.warning(f"watchdog PID 文件写入失败: {e}")

    logger.info(f"Worker Watchdog 启动: project_root={PROJECT_ROOT}, "
                f"worker_log={LOG_DIR / 'worker_runtime_<group>.log'}（default 组为 worker_runtime.log）, "
                f"groups={_GROUPS}")
    # 配置自检（2026-09-18 拆 v 组时新增）：分组表与本组集合各写一处，任一侧漏改都会出事：
    #   · GROUP_TASK_MAP 有、MY_APP_WORKER_GROUPS 无 → 该组从不被拉起，任务永远 pending
    #     （现象与「漏登记分组」完全一样，已发生过四次）
    #   · MY_APP_WORKER_GROUPS 有、GROUP_TASK_MAP 无 → 该 worker 拿到空白名单，
    #     按 _spawn_worker 语义【全量认领】所有 pending，直接破坏分组串行约束（更危险）
    # 只告警不退出：宁可降级跑着，也不要让看门狗本身不起来。
    if _WORKER_GROUPS:
        _map_only = sorted(set(GROUP_TASK_MAP) - set(_GROUPS))
        _env_only = sorted(set(_GROUPS) - set(GROUP_TASK_MAP))
        if _map_only:
            logger.warning(
                f"⚠ GROUP_TASK_MAP 定义了组 {_map_only}，但 MY_APP_WORKER_GROUPS={_WORKER_GROUPS} "
                f"未启用 → 这些组的任务不会被任何 worker 认领（请同步 start_hidden.ps1 / "
                f"restart_workers.py 的组集合）"
            )
        if _env_only:
            logger.warning(
                f"⚠ MY_APP_WORKER_GROUPS 启用了组 {_env_only}，但 GROUP_TASK_MAP 无对应清单 → "
                f"该组 worker 无任务白名单，会全量认领所有 pending 任务（分组串行约束失效）"
            )
    try:
        _launcher = (os.environ.get("MY_APP_RESTART_BY") or "").strip() or f"ppid={os.getppid()}"
    except Exception:
        _launcher = "unknown"
    append_marker("watchdog_start", by="watchdog", pid=os.getpid(),
                  groups=_GROUPS, note=f"launcher={_launcher}")

    try:
        while not _shutdown:
            try:
                _write_heartbeat()
                if not _loop_once():
                    break
            except Exception:
                # 2026-08-15 加固：主循环任何未预期异常都必须记录并继续，
                # 否则看门狗会静默死亡（无日志），自愈链断裂。
                logger.exception("worker_watchdog 主循环异常，已捕获并继续（防止看门狗静默死亡）")
                try:
                    time.sleep(5)
                except Exception:
                    pass
    finally:
        append_marker("watchdog_exit", by="watchdog", pid=os.getpid(),
                      note="进程退出（stop.bat 或收到退出信号）")
        _terminate_child()
        try:
            if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
                PID_FILE.unlink()
        except Exception:
            pass
        logger.info("Worker Watchdog 已退出")


if __name__ == "__main__":
    main()

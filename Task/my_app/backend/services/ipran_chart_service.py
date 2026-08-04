# -*- coding: utf-8 -*-
"""
IP RAN M6K-FW Chart Email Service
==================================

从远程 API 或本地数据库查询 HQ_M6K_FW_bnctp_15mins 表，按指定 ME + SmartGroup 组合
生成折线图（过去 3 天 15分钟粒度），然后通过 EWS 发送邮件。

数据源优先级：
  1. 远程 API (http://192.168.100.19:8765/api/read)
  2. data/ipran_ume/ipran_ume_kpi.sqlite3（本地 SQLite）
  3. data/ipran_ume/exports/（Excel 降级方案）

筛选条件（3 组）：
  1. ME=HQ-M6K-8S_Plus_PS01, Measure Object=SmartGroup:9
  2. ME=HQ-M6K-8S_Plus_PS02, Measure Object=SmartGroup:9
  3. ME=HQ-M6K-8S_Plus_PS01, Measure Object=SmartGroup:3

图表命名：HQ-M6K-8S_Plus_PS01--SmartGroup:9.png 等
发送调度：每天 6:45（task_id: ipran_m6k_chart_email）
"""
from __future__ import annotations

import glob
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

logger = logging.getLogger("ipran_chart_service")

# ===== 路径配置 =====
MY_APP_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = MY_APP_DIR / "data" / "ipran_ume" / "ipran_ume_kpi.sqlite3"
EXCEL_EXPORTS_DIR = MY_APP_DIR / "data" / "ipran_ume" / "exports"
OUTPUT_DIR = MY_APP_DIR / "TMP" / "ipran_charts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EMAIL_REPORTS_DIR = MY_APP_DIR / "email_reports"
EMAIL_LIST_DIR = Path(r"Y:\01_RPA\LBR_Tools\KPI\IPRAN\ip_ran_email")
SS_EMAIL_FILE = EMAIL_LIST_DIR / "ss_email.txt"
CC_EMAIL_FILE = EMAIL_LIST_DIR / "cc_email.txt"

_MANAGED_VENV_PY = (
    r"C:\Users\ZTEEMS\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
)

# ===== 筛选配置（ME + Measure Object + 表名） =====
# SmartGroup:9 在 IPCORE_HQ_ODC_bnctp_15mins 表
# SmartGroup:3 在 HQ_M6K_FW_bnctp_15mins 表
QUERY_FILTERS: List[Tuple[str, str, str]] = [
    ("HQ-M6K-8S_Plus_PS01", "SmartGroup:9", "IPCORE_HQ_ODC_bnctp_15mins"),
    ("HQ-M6K-8S_Plus_PS02", "SmartGroup:9", "IPCORE_HQ_ODC_bnctp_15mins"),
    ("HQ-M6K-8S_Plus_PS01", "SmartGroup:3", "HQ_M6K_FW_bnctp_15mins"),
]

# 图表颜色配置（与 ran_ume 仪表板风格一致）
COLOR_INGRESS = '#2E86AB'
COLOR_EGRESS = '#A23B72'
BG_COLOR = '#E8F0FE'
TITLE_COLOR = '#2F5496'
GRID_COLOR = '#C5C5C5'


def _read_addresses(path: Path) -> list:
    """从名单文件读取邮箱地址。"""
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for part in line.replace(";", ",").split(","):
            p = part.strip()
            if p:
                out.append(p)
    return out


def _resolve_recipients() -> Tuple[list, list]:
    to_list = _read_addresses(SS_EMAIL_FILE)
    cc_list = _read_addresses(CC_EMAIL_FILE)
    return to_list, cc_list


def _query_remote_api(me: str, measure_obj: str, table_name: str) -> Optional[pd.DataFrame]:
    """尝试从远程 API 读取 IP RAN 数据。
    支持两种表结构：
    - 宽表：Receive/Send Traffic Rate(Mbps) 作为独立列
    - EAV：Counter + Counter Value 列（需 pivot）
    """
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from remote_db_reader import get_remote_reader
        
        reader = get_remote_reader()
        
        # 先检查 API 是否可达
        try:
            health = reader.health_check()
            if health.get("status") != "ok":
                logger.warning("远程 API 健康检查失败")
                return None
        except Exception as e:
            logger.warning(f"无法连接远程 API: {e}")
            return None
        
        # 调用查询 API（先查所有列，自动适配表结构）
        try:
            result = reader.read_table(
                db="ipran_ume_kpi.sqlite3",
                table=table_name,
                columns=None,  # 查所有列
                where=f'"ME" = "{me}" AND "Measure Object" = "{measure_obj}"',
                limit=10000
            )
            
            if not result.get("success") or not result.get("rows"):
                logger.warning(f"远程 API 返回空结果 (ME={me}, MO={measure_obj})")
                return None
            
            df = pd.DataFrame(result["rows"], columns=result["columns"])
            cols = df.columns.tolist()
            
            # 验证数据有效性：数值列必须包含实际数字，不能是列名字符串
            candidate_numeric = ["Counter Value", "Receive Traffic Rate(Mbps)",
                                 "Send Traffic Rate(Mbps)"]
            check_cols = [c for c in candidate_numeric if c in cols]
            if check_cols:
                sample = pd.to_numeric(df[check_cols].iloc[:5].stack(), errors='coerce')
                if sample.notna().sum() == 0:
                    logger.warning(
                        f"远程 API 返回数据无效（数值列全为字符串），"
                        f"降级到本地 SQLite (ME={me}, MO={measure_obj})")
                    return None
            
            # 自动检测表结构
            if "Counter" in cols and "Counter Value" in cols:
                # EAV 格式：需要 pivot
                df["Counter Value"] = pd.to_numeric(df["Counter Value"], errors='coerce')
                df["Begin Time"] = pd.to_datetime(df["Begin Time"], errors='coerce')
                
                # Pivot: Counter 值变为列
                pivot = df.pivot_table(
                    index=["Begin Time", "ME", "Measure Object"],
                    columns="Counter",
                    values="Counter Value",
                    aggfunc='first'
                ).reset_index()
                
                # 重命名
                rename_map = {}
                for c in pivot.columns:
                    if "Receive" in str(c) and "Traffic" in str(c):
                        rename_map[c] = "ingress_util"
                    elif "Send" in str(c) and "Traffic" in str(c):
                        rename_map[c] = "egress_util"
                df = pivot.rename(columns=rename_map)
                
            else:
                # 宽表格式：直接重命名
                df = df.rename(columns={
                    "Receive Traffic Rate(Mbps)": "ingress_util",
                    "Send Traffic Rate(Mbps)": "egress_util"
                })
            
            # 确保数值类型
            for col in ["ingress_util", "egress_util"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df = df.dropna(subset=["ingress_util", "egress_util"], how='all')
            if "Begin Time" in df.columns:
                df["Begin Time"] = pd.to_datetime(df["Begin Time"], errors='coerce')
                df = df.dropna(subset=["Begin Time"])
            
            logger.info(f"从远程 API 读取到 {len(df)} 行数据 (ME={me}, MO={measure_obj}, 表={table_name})")
            return df
            
        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg or "not found" in error_msg.lower():
                logger.warning("远程 API 不支持 /api/read 端点，使用降级方案")
            else:
                logger.warning(f"远程 API 查询失败: {e}")
            return None
        
    except Exception as e:
        logger.warning(f"远程 API 查询失败 (ME={me}, MO={measure_obj}): {e}")
        return None


def _read_from_sqlite(me: str, measure_obj: str, table_name: str, days_back: int = 3) -> Optional[pd.DataFrame]:
    """从本地 SQLite 读取数据。table_name 必须显式传入，不同 SmartGroup 对应不同表。"""
    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        return None
    
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days_back)
    
    # 表名通过参数传入，避免写死导致查错表
    sql = f"""
        SELECT "Begin Time", "ME", "Measure Object", 
               "C019911991", "C019901990"
        FROM "{table_name}"
        WHERE "ME" = ? 
          AND "Measure Object" = ?
          AND "Begin Time" >= ?
          AND "Begin Time" <= ?
        ORDER BY "Begin Time" ASC
    """
    
    try:
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        df = pd.read_sql_query(sql, conn, params=[me, measure_obj, 
                                                    start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                                                    end_dt.strftime("%Y-%m-%d %H:%M:%S")])
        conn.close()
        
        if df.empty:
            return None
        
        df["Begin Time"] = pd.to_datetime(df["Begin Time"])
        df = df.rename(columns={"C019911991": "ingress_util", "C019901990": "egress_util"})
        return df
    except Exception as e:
        logger.warning(f"SQLite 查询失败: {e}")
        return None


def _read_from_excel_fallback(me: str, measure_obj: str) -> Optional[pd.DataFrame]:
    """降级方案：从 Excel 导出文件读取数据。"""
    pattern = str(EXCEL_EXPORTS_DIR / "*HQ*M6K*FW*.xlsx")
    files = glob.glob(pattern)
    if not files:
        return None
    
    latest_file = max(files, key=os.path.getmtime)
    logger.info(f"使用降级方案从 Excel 读取: {os.path.basename(latest_file)}")
    
    try:
        df = pd.read_excel(latest_file, sheet_name='Sheet0')
        
        # 查找列名
        col_map = {}
        for col in df.columns:
            col_lower = str(col).lower()
            if "begin" in col_lower and "time" in col_lower:
                col_map[col] = "Begin Time"
            elif col == "ME":
                col_map[col] = "ME"
            elif "measure" in col_lower or "object" in col_lower:
                col_map[col] = "Measure Object"
            elif "ingress" in col_lower or "uplink" in col_lower:
                col_map[col] = "C019911991"
            elif "egress" in col_lower or "downlink" in col_lower:
                col_map[col] = "C019901990"
        
        if col_map:
            df = df.rename(columns=col_map)
        
        if "ME" in df.columns:
            df = df[df["ME"].astype(str) == me]
        if "Measure Object" in df.columns:
            df = df[df["Measure Object"].astype(str) == measure_obj]
        
        if df.empty:
            return None
        
        if "Begin Time" in df.columns:
            df["Begin Time"] = pd.to_datetime(df["Begin Time"], errors="coerce")
            df = df.dropna(subset=["Begin Time"])
        
        if "C019911991" not in df.columns and len(df.columns) > 2:
            df["C019911991"] = df.iloc[:, 2]
        if "C019901990" not in df.columns and len(df.columns) > 3:
            df["C019901990"] = df.iloc[:, 3]
        
        df = df.rename(columns={"C019911991": "ingress_util", "C019901990": "egress_util"})
        return df
    except Exception as e:
        logger.error(f"Excel 读取失败: {e}")
        return None


def query_data(me: str, measure_obj: str, table_name: str, days_back: int = 3) -> Optional[pd.DataFrame]:
    """查询数据，优先级：远程 API → SQLite → Excel"""
    
    # 1. 尝试远程 API
    df = _query_remote_api(me, measure_obj, table_name)
    if df is not None and not df.empty:
        return df
    
    # 2. 尝试本地 SQLite（传入正确的表名）
    df = _read_from_sqlite(me, measure_obj, table_name, days_back)
    if df is not None and not df.empty:
        return df
    
    # 3. 降级到 Excel
    return _read_from_excel_fallback(me, measure_obj)


def _detect_granularity(time_series: pd.Series) -> str:
    """检测数据时间粒度：'day' 或 'hour'。"""
    if len(time_series) < 2:
        return 'day'
    sorted_ts = time_series.sort_values()
    diffs = sorted_ts.diff().dropna()
    median_diff = diffs.median()
    # 中位间隔 >= 12小时 视为天粒度
    if median_diff >= pd.Timedelta(hours=12):
        return 'day'
    return 'hour'


def generate_chart(df: pd.DataFrame, me: str, measure_obj: str, output_path: Path) -> bool:
    """生成折线图并保存为 PNG，风格与 ran_ume 仪表板一致。"""
    try:
        fig, ax = plt.subplots(figsize=(14, 5.5))
        
        # 设置背景色
        ax.set_facecolor(BG_COLOR)
        fig.patch.set_facecolor(BG_COLOR)
        
        # 确保有数据
        if "Begin Time" not in df.columns or len(df) == 0:
            logger.warning("无时间数据")
            return False
        
        # 检测时间粒度
        granularity = _detect_granularity(df["Begin Time"])
        
        # 使用整数 x 轴（与 ran_ume 一致）
        x = range(len(df))
        
        # 绘制两条吞吐量曲线（无 marker，线条简洁）
        ax.plot(x, df["ingress_util"], 
                linewidth=1.2, 
                label="Receive Traffic Rate(Mbps)", color=COLOR_INGRESS, alpha=0.85)
        ax.plot(x, df["egress_util"], 
                linewidth=1.2, 
                label="Send Traffic Rate(Mbps)", color=COLOR_EGRESS, alpha=0.85)
        
        ax.set_xlabel("Time", fontsize=9)
        ax.set_ylabel("Traffic Rate(Mbps)", fontsize=9)
        ax.set_title(f"{me} -- {measure_obj}\nPort Throughput", 
                     fontsize=13, fontweight="bold", color=TITLE_COLOR, pad=12)
        ax.legend(loc='upper left', fontsize=8, frameon=True,
                  facecolor='white', framealpha=0.8, edgecolor='#CCCCCC')
        ax.grid(axis='y', linestyle='--', color=GRID_COLOR, linewidth=0.6, alpha=0.6)
        ax.set_axisbelow(True)
        
        # 边框样式
        for spine in ax.spines.values():
            spine.set_color('#B0B0B0')
            spine.set_linewidth(0.5)
        
        # 格式化时间轴标签（根据粒度决定显示格式）
        date_labels = []
        for t in df["Begin Time"]:
            s = str(t)
            # 兼容 ISO 格式（T 分隔）和空格分隔的时间戳
            if 'T' in s:
                s = s.split('T')[0]
            elif ' ' in s:
                s = s.split(' ')[0]
            if granularity == 'day':
                # 天粒度：只显示 MM-DD
                if len(s) >= 10:
                    date_labels.append(s[5:])
                else:
                    date_labels.append(s)
            else:
                # 小时粒度：显示 MM-DD HH:MM
                raw = str(t)
                if len(raw) >= 16:
                    date_labels.append(raw[5:16])
                elif len(raw) >= 10:
                    date_labels.append(raw[5:])
                else:
                    date_labels.append(raw)
        
        n = len(date_labels)
        # 根据数据量控制刻度密度
        max_ticks = 20
        if n > max_ticks:
            step = max(1, n // max_ticks)
            tick_positions = list(range(0, n, step))
        else:
            tick_positions = list(range(n))
        
        ax.set_xticks(tick_positions)
        ax.set_xticklabels([date_labels[i] for i in tick_positions],
                           rotation=45, fontsize=7, ha='right')
        ax.tick_params(axis='both', labelsize=8)
        
        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight", 
                    facecolor=BG_COLOR, edgecolor='none')
        plt.close(fig)
        
        logger.info(f"图表已保存: {output_path.name} (粒度={granularity}, 数据点={len(df)})")
        return True
        
    except Exception as e:
        logger.error(f"生成图表失败: {e}")
        return False


def _send_email(to: list, cc: list, subject: str, body: str, 
                inline_images: List[Path]) -> dict:
    """调用通用邮件脚本发送。"""
    py = _MANAGED_VENV_PY
    script = EMAIL_REPORTS_DIR / "owa_mail_report.py"
    
    if not script.is_file():
        return {"success": False, "error": f"脚本不存在: {script}"}
    
    cmd = [
        py, str(script),
        "--data-dir", str(OUTPUT_DIR),
        "--email-dir", str(EMAIL_REPORTS_DIR),
        "--no-excel",
        "--subject", subject,
        "--body", body,
        "--to", ";".join(to),
        "--cc", ";".join(cc) if cc else "",
    ]
    
    # 添加内嵌图片
    for img in inline_images:
        cmd += ["--images", str(img)]
    
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            cwd=str(MY_APP_DIR),
        )
        
        if proc.returncode == 0:
            return {"success": True, "message": proc.stdout[-500:] if proc.stdout else ""}
        else:
            return {"success": False, "error": proc.stderr[-1000:] if proc.stderr else proc.stdout}
            
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "超时"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_chart_and_send(to_override: Optional[str] = None, 
                       cc_override: Optional[str] = None) -> dict:
    """主入口：生成图表并发送邮件。"""
    t0 = time.perf_counter()
    
    # 读取收件人
    if to_override:
        to_list = [addr.strip() for addr in to_override.split(",")]
    else:
        to_list, _ = _resolve_recipients()
    
    if cc_override is not None:
        cc_list = [addr.strip() for addr in cc_override.split(",")] if cc_override else []
    else:
        _, cc_list = _resolve_recipients()
    
    logger.info(f"收件人: {len(to_list)} 主送, {len(cc_list)} 抄送")
    
    # 生成图表
    chart_files = []
    for me, measure_obj, table_name in QUERY_FILTERS:
        # Windows 文件名不允许 : 字符，替换为 _
        safe_me = me.replace(":", "_").replace('"', "")
        safe_mo = measure_obj.replace(":", "_").replace('"', "")
        chart_name = f"{safe_me}--{safe_mo}.png"
        chart_path = OUTPUT_DIR / chart_name
        
        df = query_data(me, measure_obj, table_name)
        if df is None or df.empty:
            logger.warning(f"跳过 {chart_name}: 无数据")
            continue
        
        if not generate_chart(df, me, measure_obj, chart_path):
            logger.error(f"跳过 {chart_name}: 图表生成失败")
            continue
        
        chart_files.append(chart_path)
    
    if not chart_files:
        logger.warning("没有生成任何图表，跳过邮件发送")
        return {"success": False, "error": "无图表数据"}
    
    logger.info(f"共生成 {len(chart_files)} 张图表")
    
    # 发送邮件
    subject = f"IP RAN M6K-FW Port Utilization Report - {datetime.now().strftime('%Y-%m-%d')}"
    body = (
        "<h3>Dear Team,</h3>"
        "<p>Please find the IP RAN M6K-FW Port Utilization charts attached.</p>"
        "<p>Charts cover the last 3 days of 15-minute granularity data.</p>"
        "<br><p>Best regards,<br>ZTENOC OLR</p>"
    )
    
    result = _send_email(
        to=to_list,
        cc=cc_list,
        subject=subject,
        body=body,
        inline_images=chart_files,
    )
    
    elapsed = time.perf_counter() - t0
    result["elapsed_seconds"] = round(elapsed, 2)
    result["charts_generated"] = len(chart_files)
    
    logger.info(f"任务完成: {result}")
    return result


def run_ipran_m6k_chart_email() -> dict:
    """供 Task Manager 调用的入口。"""
    logger.info("开始 IP RAN M6K-FW 图表邮件任务")
    try:
        return run_chart_and_send()
    except Exception as e:
        logger.error(f"任务异常: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    result = run_ipran_m6k_chart_email()
    print(f"\n结果: {result}")

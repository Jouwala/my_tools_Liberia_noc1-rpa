# -*- coding: utf-8 -*-
"""
CNN Free Rating Group Chart Email Service
==========================================

从远程 API 或 Excel 导出文件查询 FREE_RATING_GROUP_TEMPLATE_OSS_update_UME 数据，
按 Measurement Object 过滤生成折线图（时间序列），然后通过 EWS 发送邮件。

数据源优先级：
  1. 远程 API (http://192.168.100.19:8765/api/read)
  2. data/cnn_ume/exports/（Excel 降级方案）

筛选条件（4 个 Measurement Object）：
  - 30
  - 12
  - 11
  - 6

图表命名：RG-30.png, RG-12.png, RG-11.png, RG-6.png
发送调度：每天 7:45（task_id: ccn_free_rating_chart_email）
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

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

logger = logging.getLogger("ccn_free_rating_chart_service")

# ===== 路径配置 =====
MY_APP_DIR = Path(__file__).resolve().parent.parent.parent
EXCEL_EXPORTS_DIR = MY_APP_DIR / "data" / "cnn_ume" / "exports"
OUTPUT_DIR = MY_APP_DIR / "TMP" / "ccn_free_rating_charts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EMAIL_REPORTS_DIR = MY_APP_DIR / "email_reports"
EMAIL_LIST_DIR = Path(r"Y:\01_RPA\LBR_Tools\KPI\CCN\ccn_email")
SS_EMAIL_FILE = EMAIL_LIST_DIR / "ss_email.txt"
CC_EMAIL_FILE = EMAIL_LIST_DIR / "cc_email.txt"

_MANAGED_VENV_PY = (
    r"C:\Users\ZTEEMS\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
)

# ===== 筛选配置（Measurement Object） =====
MEASUREMENT_OBJECTS = ["30", "12", "11", "6"]

# 图表颜色配置（与 ran_ume 仪表板风格一致）
COLOR_BALANCE = '#2E86AB'
COLOR_USED = '#A23B72'
COLOR_TOTAL = '#F18F01'
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


def _query_remote_api(mo: str) -> Optional[pd.DataFrame]:
    """尝试从远程 API 读取数据。"""
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
        
        # 检查表是否存在
        try:
            tables = reader.list_tables("db_ps_cs_cn.sqlite3")
            table_names = [t['name'] for t in tables]
            if "FREE_RATING_GROUP_TEMPLATE_OSS_update_UME" not in table_names:
                logger.warning("远程数据库中不存在目标表")
                return None
        except Exception as e:
            logger.warning(f"列出远程表失败: {e}")
            return None
        
        # 调用查询 API（用 SELECT * 而非指定列名，因为远程数据库列名是长名称
        # 如 "Bytes of flows of uplink packets based RG(Byte)"，而非 C550400011。
        # 如果指定不存在的列名，SQLite 会将其当作字符串常量返回，导致数据全为列名字符串。）
        try:
            result = reader.read_table(
                db="db_ps_cs_cn.sqlite3",
                table="FREE_RATING_GROUP_TEMPLATE_OSS_update_UME",
                columns=None,  # SELECT *
                where='"Measurement Object" = "' + mo + '"',
                limit=10000
            )
            
            if result.get("success") and result.get("rows"):
                df = pd.DataFrame(result["rows"], columns=result["columns"])
                # 将实际列名映射为短名称
                col_map = {
                    "Bytes of flows of uplink packets based RG(Byte)": "C550400011",
                    "Bytes of flows of downlink packets based RG(Byte)": "C550400012",
                    "Bytes of total packets based RG(Byte)": "C550400013",
                }
                df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
                # 验证数据有效性：数值列必须包含实际数字
                numeric_cols = ["C550400011", "C550400012", "C550400013"]
                valid_cols = [c for c in numeric_cols if c in df.columns]
                if valid_cols:
                    sample = pd.to_numeric(df[valid_cols].iloc[:5].stack(), errors='coerce')
                    if sample.notna().sum() == 0:
                        logger.warning(
                            f"远程 API 返回数据无效（数值列全为字符串/列名），"
                            f"降级到 Excel (MO={mo})")
                        return None
                logger.info(f"从远程 API 读取到 {len(df)} 行数据 (MO={mo})")
                return df
            
            logger.warning(f"远程 API 返回空结果 (MO={mo})")
            return None
            
        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg or "not found" in error_msg.lower():
                logger.warning("远程 API 不支持 /api/read 端点，使用 Excel 降级方案")
            else:
                logger.warning(f"远程 API 查询失败: {e}")
            return None
        
    except Exception as e:
        logger.warning(f"远程 API 查询失败 (MO={mo}): {e}")
        return None


def _read_from_excel_fallback(mo: str) -> Optional[pd.DataFrame]:
    """降级方案：从 Excel 导出文件读取数据。"""
    pattern = str(EXCEL_EXPORTS_DIR / "*FREE_RATING*2026*.xlsx")
    files = glob.glob(pattern)
    if not files:
        logger.warning(f"未找到 FREE_RATING Excel 文件: {pattern}")
        return None
    
    latest_file = max(files, key=os.path.getmtime)
    logger.info(f"使用降级方案从 Excel 读取: {os.path.basename(latest_file)}")
    
    try:
        df = pd.read_excel(latest_file, sheet_name='Sheet0')
        
        # 映射列名
        col_map = {
            "Begin Time": "Begin Time",
            "End Time": "End Time",
            "Measurement Object": "Measurement Object",
            "Bytes of flows of uplink packets based RG(Byte)": "C550400011",
            "Bytes of flows of downlink packets based RG(Byte)": "C550400012",
            "Bytes of total packets based RG(Byte)": "C550400013",
        }
        df = df.rename(columns={old: new for old, new in col_map.items() if old in df.columns})
        
        if "Measurement Object" not in df.columns:
            logger.error("Excel 中无 Measurement Object 列")
            return None
        
        df = df[df["Measurement Object"].astype(str) == mo]
        
        if df.empty:
            logger.warning(f"Excel 中无 Measurement Object={mo} 的数据")
            return None
        
        if "Begin Time" in df.columns:
            df["Begin Time"] = pd.to_datetime(df["Begin Time"])
        
        return df.rename(columns={
            "C550400011": "balance",
            "C550400012": "used",
            "C550400013": "total"
        })
    except Exception as e:
        logger.error(f"Excel 读取失败 (MO={mo}): {e}")
        return None


def query_free_rating_data(mo: str, days_back: int = 7) -> Optional[pd.DataFrame]:
    """查询指定 Measurement Object 的数据。优先级：远程 API → Excel
    同一 Begin Time 可能有多行（多个网元/组），按时间求和聚合为每个时间点一个值。"""
    
    df = None
    # 1. 尝试远程 API
    raw = _query_remote_api(mo)
    if raw is not None and not raw.empty:
        raw["Begin Time"] = pd.to_datetime(raw["Begin Time"])
        df = raw.rename(columns={
            "C550400011": "balance",
            "C550400012": "used", 
            "C550400013": "total"
        })
    else:
        # 2. 降级到 Excel
        df = _read_from_excel_fallback(mo)
    
    if df is None or df.empty:
        return None
    
    # 确保数值列为数值类型
    for col in ["balance", "used", "total"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    # 按 Begin Time 求和聚合（同一时间点多行合并为一行）
    agg_cols = [c for c in ["balance", "used", "total"] if c in df.columns]
    df = df.groupby("Begin Time")[agg_cols].sum().reset_index()
    df = df.sort_values("Begin Time").reset_index(drop=True)
    
    logger.info(f"MO={mo}: 聚合后 {len(df)} 个时间点")
    return df


def _detect_granularity(time_series: pd.Series) -> str:
    """检测数据时间粒度：'day' 或 'hour'。
    注意：必须在聚合后的数据上调用，否则同一时间点多行会导致 diff=0。"""
    if len(time_series) < 2:
        return 'day'
    sorted_ts = time_series.sort_values()
    diffs = sorted_ts.diff().dropna()
    median_diff = diffs.median()
    # 中位间隔 >= 12小时 视为天粒度
    if median_diff >= pd.Timedelta(hours=12):
        return 'day'
    return 'hour'


def _safe_savefig(fig, output_path: Path) -> Path:
    """保存图表到 output_path。

    遇 PermissionError（Windows 上目标文件被其它进程锁定，常见于覆盖上一轮
    运行遗留的同名 PNG）时：先短暂重试，仍失败则落到带序号的副本文件名，
    确保整张图不会因单点写权限问题而失败（否则会触发"无图表数据"）。
    返回最终实际保存的路径。
    """
    output_path = Path(output_path)
    for attempt in range(4):
        try:
            fig.savefig(output_path, dpi=150, bbox_inches="tight",
                        facecolor=BG_COLOR, edgecolor='none')
            return output_path
        except PermissionError:
            if attempt < 3:
                time.sleep(0.5)
                continue
            break
    # 全部重试仍失败 -> 换名（带序号），不使用已锁定的文件名
    stem, suffix = output_path.stem, output_path.suffix
    idx = 1
    while True:
        alt = output_path.with_name(f"{stem}_{idx}{suffix}")
        if not alt.exists():
            break
        idx += 1
    fig.savefig(alt, dpi=150, bbox_inches="tight",
                facecolor=BG_COLOR, edgecolor='none')
    return alt


def _cleanup_old_run_dirs(keep_days: int = 14) -> None:
    """清理 OUTPUT_DIR 下超过 keep_days 天的历史运行子目录（仅删时间戳命名的子目录）。"""
    try:
        import shutil
        cutoff = time.time() - keep_days * 86400
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


def generate_line_chart(df: pd.DataFrame, mo: str, output_path: Path) -> "bool | Path":
    """生成折线图（时间序列）并保存为 PNG，风格与 ran_ume 仪表板一致。
    成功时返回实际保存的 Path，失败时返回 False。"""
    try:
        fig, ax = plt.subplots(figsize=(14, 5.5))
        
        # 设置背景色
        ax.set_facecolor(BG_COLOR)
        fig.patch.set_facecolor(BG_COLOR)
        
        # 确保有 Begin Time 列
        if "Begin Time" not in df.columns or len(df) == 0:
            logger.warning("无时间数据")
            return False
        
        # 检测时间粒度
        granularity = _detect_granularity(df["Begin Time"])
        
        # 使用整数 x 轴（与 ran_ume 一致），避免 matplotlib 日期格式问题
        x = range(len(df))
        
        # 绘制三条曲线（无 marker，线条简洁）
        if "balance" in df.columns:
            ax.plot(x, df["balance"], 
                    linewidth=1.2, 
                    label="Balance (Bytes)", color=COLOR_BALANCE, alpha=0.85)
        if "used" in df.columns:
            ax.plot(x, df["used"], 
                    linewidth=1.2, 
                    label="Used (Bytes)", color=COLOR_USED, alpha=0.85)
        if "total" in df.columns:
            ax.plot(x, df["total"], 
                    linewidth=1.2, 
                    label="Total (Bytes)", color=COLOR_TOTAL, alpha=0.85)
        
        ax.set_xlabel("Time", fontsize=9)
        ax.set_ylabel("Value (Bytes)", fontsize=9)
        ax.set_title(f"Free Rating Group - MO: {mo}", 
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
        final_path = _safe_savefig(fig, output_path)
        plt.close(fig)
        
        logger.info(f"图表已保存: {final_path.name} (粒度={granularity}, 数据点={len(df)})")
        return final_path
        
    except Exception as e:
        logger.error(f"生成图表失败 (MO={mo}): {e}")
        return False


def _send_email(to: list, cc: list, subject: str, body: str,
                inline_images: List[Path], data_dir: Path = OUTPUT_DIR) -> dict:
    """调用通用邮件脚本发送。"""
    py = _MANAGED_VENV_PY
    script = EMAIL_REPORTS_DIR / "owa_mail_report.py"
    
    if not script.is_file():
        return {"success": False, "error": f"脚本不存在: {script}"}
    
    cmd = [
        py, str(script),
        "--data-dir", str(data_dir),
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
            creationflags=_SUBPROCESS_FLAGS,
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
    
    # 读取收件人（Settings 维护，未保存时回退原名单文件）
    from backend.services.email_recipient_store import get_email_recipients
    to_arg, cc_arg = get_email_recipients("ccn_free_rating_chart_email", to_override, cc_override)
    to_list = [a.strip() for a in (to_arg or "").split(";") if a.strip()]
    cc_list = [a.strip() for a in (cc_arg or "").split(";") if a.strip()]

    logger.info(f"收件人: {len(to_list)} 主送, {len(cc_list)} 抄送")
    
    # 每次运行使用独立的时间戳子目录，避免覆盖上一轮遗留的、可能被其它进程
    # 锁定的同名 PNG（这正是此前"无图表数据"的根因）。
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / run_stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成图表
    chart_files = []
    for mo in MEASUREMENT_OBJECTS:
        chart_name = f"RG-{mo}.png"
        chart_path = run_dir / chart_name
        
        df = query_free_rating_data(mo)
        if df is None or df.empty:
            logger.warning(f"跳过 {chart_name}: 无数据")
            continue
        
        saved = generate_line_chart(df, mo, chart_path)
        if not saved:
            logger.error(f"跳过 {chart_name}: 图表生成失败")
            continue
        
        chart_files.append(saved)
    
    if not chart_files:
        logger.warning("没有生成任何图表，跳过邮件发送")
        return {"success": False, "error": "无图表数据"}
    
    logger.info(f"共生成 {len(chart_files)} 张图表")
    
    # 发送邮件
    subject = f"CNN Free Rating Group Report - {datetime.now().strftime('%Y-%m-%d')}"
    body = (
        "<h3>Dear Team,</h3>"
        "<p>Please find the CNN Free Rating Group charts attached.</p>"
        "<p>Charts show Balance, Used, and Total metrics by Measurement Object over time.</p>"
        "<br><p>Best regards,<br>ZTENOC OLR</p>"
    )
    
    result = _send_email(
        to=to_list,
        cc=cc_list,
        subject=subject,
        body=body,
        inline_images=chart_files,
        data_dir=run_dir,
    )
    
    elapsed = time.perf_counter() - t0
    result["elapsed_seconds"] = round(elapsed, 2)
    result["charts_generated"] = len(chart_files)
    
    # 清理历史运行子目录，避免无限堆积
    _cleanup_old_run_dirs(keep_days=14)
    
    logger.info(f"任务完成: {result}")
    return result


def run_ccn_free_rating_chart_email() -> dict:
    """供 Task Manager 调用的入口。"""
    logger.info("开始 CNN Free Rating Group 图表邮件任务")
    try:
        return run_chart_and_send()
    except Exception as e:
        logger.error(f"任务异常: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    result = run_ccn_free_rating_chart_email()
    print(f"\n结果: {result}")

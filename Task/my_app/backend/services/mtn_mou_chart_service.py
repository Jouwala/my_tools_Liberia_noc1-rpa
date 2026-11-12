# -*- coding: utf-8 -*-
"""
MTN MOU Daily Traffic 图表邮件
==============================

每天 07:00 从远程库 db_ps_cs_cn.sqlite3 的 MTN_Outgoing_MOU_OSS_EMS 读取
按日汇总好的 MTN 去话量，分别画 Outgoing MOU / Incoming MOU 两张折线图，
经项目统一的 EWS 邮件脚本（email_reports/owa_mail_report.py）内嵌图片发送。

数据口径（与入表口径一致，见 Task/PS_CS_CORE_Scripts/ps_cs_core.py）：
  - 该表每行 = 一个自然日，两个指标按天从中继组（16/17）加总而来；
  - 运行当天的数据不完整，读出来也一律剔除（只发完整自然日）。

收件人：Settings → 邮件收件人 → 「MTN MOU 日报邮件」分组（key=mtn_mou_daily_email），
未保存时回退默认名单 dong.xinmin@zte.com.cn。

调度：task_id = mtn_mou_daily_email，default_cron = 0 7 * * *
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from datetime import datetime
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

logger = logging.getLogger("mtn_mou_chart_service")

# ===== 路径 / 数据源配置 =====
MY_APP_DIR = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = MY_APP_DIR / "TMP" / "mtn_mou_charts"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EMAIL_REPORTS_DIR = MY_APP_DIR / "email_reports"
_MANAGED_VENV_PY = os.environ.get("MY_APP_REPORT_PY") or sys.executable

REMOTE_DB = "db_ps_cs_cn.sqlite3"
REMOTE_TABLE = "MTN_Outgoing_MOU_OSS_EMS"

SUBJECT = "MTN MOU Daily Traffic"
EMAIL_GROUP_KEY = "mtn_mou_daily_email"

# 图表风格与 ccn_free_rating_chart_service / ran_ume 看板一致
COLOR_OUT = "#2E86AB"
COLOR_IN = "#F18F01"
BG_COLOR = "#E8F0FE"
TITLE_COLOR = "#2F5496"
GRID_COLOR = "#C5C5C5"
TEXT_COLOR = "#333333"

# 展示窗口（完整自然日）
DISPLAY_DAYS = 31


def _fetch_mou_data() -> Optional[pd.DataFrame]:
    """从远程 API 读取按日 MOU 数据；先剔除运行当天（不完整）。"""
    try:
        from backend.services.remote_db_reader import get_remote_reader

        reader = get_remote_reader()
        health = reader.health_check()
        if health.get("status") != "ok":
            logger.warning("远程 API 健康检查未通过: %s", health)

        result = reader.read_table(
            db=REMOTE_DB,
            table=REMOTE_TABLE,
            columns=["Start Time", "Outgoing MOU", "Incoming MOU"],
            order_by='"Start Time"',
            limit=2000,
        )
        rows = result.get("rows") or []
        if not rows:
            logger.warning("远程表 %s 没有数据", REMOTE_TABLE)
            return None

        df = pd.DataFrame(rows, columns=result.get("columns")
                          or ["Start Time", "Outgoing MOU", "Incoming MOU"])
    except Exception as e:
        logger.error("读取远程库失败: %s", e, exc_info=True)
        return None

    df["Start Time"] = pd.to_datetime(df["Start Time"], errors="coerce")
    df = df.dropna(subset=["Start Time"])
    for col in ("Outgoing MOU", "Incoming MOU"):
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", "", regex=False), errors="coerce")

    # 今天还没过完，不展示也不发送
    today = pd.Timestamp(datetime.now().date())
    before = len(df)
    df = df[df["Start Time"] < today]
    if before != len(df):
        logger.info("剔除运行当天未完整数据 %d 行", before - len(df))

    if df.empty:
        return None

    df = df.sort_values("Start Time").tail(DISPLAY_DAYS).reset_index(drop=True)
    logger.info("读取 %d 天数据：%s ~ %s",
                len(df), df["Start Time"].iloc[0].date(), df["Start Time"].iloc[-1].date())
    return df


def _safe_savefig(fig, output_path: Path) -> Path:
    """保存图表；同名文件被占用时重试，仍失败则换带序号的文件名。"""
    output_path = Path(output_path)
    for attempt in range(4):
        try:
            fig.savefig(output_path, dpi=150, bbox_inches="tight",
                        facecolor=BG_COLOR, edgecolor="none")
            return output_path
        except PermissionError:
            if attempt < 3:
                time.sleep(0.5)
                continue
            break
    idx = 1
    stem, suffix = output_path.stem, output_path.suffix
    while True:
        alt = output_path.with_name(f"{stem}_{idx}{suffix}")
        if not alt.exists():
            break
        idx += 1
    fig.savefig(alt, dpi=150, bbox_inches="tight",
                facecolor=BG_COLOR, edgecolor="none")
    return alt


def _compact_number(v: float, _pos=None) -> str:
    """Y 轴刻度用紧凑单位，避免 matplotlib 的 1e6 偏移量。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if abs(v) >= 1e6:
        return f"{v / 1e6:.1f}M"
    if abs(v) >= 1e3:
        return f"{v / 1e3:.0f}K"
    return f"{v:.0f}"


def _plot_series(df: pd.DataFrame, column: str, title: str, color: str,
                 output_path: Path) -> Optional[Path]:
    """画单指标折线图（按日）。"""
    if column not in df.columns or df[column].notna().sum() == 0:
        logger.warning("无 %s 数据，跳过出图", column)
        return None

    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.set_facecolor(BG_COLOR)
    fig.patch.set_facecolor(BG_COLOR)

    x = list(range(len(df)))
    ax.plot(x, df[column], linewidth=1.6, color=color, label=column)
    ax.fill_between(x, df[column].fillna(0), color=color, alpha=0.12)
    ax.set_ylim(bottom=0)

    # 最新一个点的数值直接标在图上
    last_x = x[-1]
    last_v = df[column].iloc[-1]
    if pd.notna(last_v):
        ax.annotate(_compact_number(last_v), (last_x, last_v),
                    textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=8, color=color, fontweight="bold")

    ax.set_title(title, fontsize=13, fontweight="bold", color=TITLE_COLOR, pad=12)
    ax.set_ylabel("MOU", fontsize=9, color=TEXT_COLOR)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_compact_number))
    ax.grid(axis="y", linestyle="--", color=GRID_COLOR, linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color("#B0B0B0")
        spine.set_linewidth(0.5)

    labels = [t.strftime("%m-%d") for t in df["Start Time"]]
    n = len(labels)
    step = max(1, n // 16) if n > 16 else 1
    positions = list(range(0, n, step))
    ax.set_xticks(positions)
    ax.set_xticklabels([labels[i] for i in positions],
                       rotation=45, fontsize=7, ha="right")
    ax.tick_params(axis="both", labelsize=8)
    ax.legend(loc="upper left", fontsize=8, frameon=True,
              facecolor="white", framealpha=0.8, edgecolor="#CCCCCC")

    plt.tight_layout()
    final_path = _safe_savefig(fig, output_path)
    plt.close(fig)
    logger.info("图表已保存: %s", Path(final_path).name)
    return Path(final_path)


def _summary_table(df: pd.DataFrame) -> str:
    """正文里的最近 7 天汇总表（HTML）。"""
    tail = df.tail(7)
    rows = []
    for _, r in tail.iterrows():
        out_v = r.get("Outgoing MOU")
        in_v = r.get("Incoming MOU")
        rows.append(
            "<tr>"
            f"<td>{r['Start Time'].strftime('%Y-%m-%d')}</td>"
            f"<td align='right'>{'' if pd.isna(out_v) else f'{out_v:,.2f}'}</td>"
            f"<td align='right'>{'' if pd.isna(in_v) else f'{in_v:,.2f}'}</td>"
            "</tr>"
        )
    return (
        "<table border='1' cellspacing='0' cellpadding='6' "
        "style='border-collapse:collapse;font-family:Segoe UI,Arial;font-size:12px'>"
        "<thead><tr style='background:#2F5496;color:#fff'>"
        "<th>Date</th><th>Outgoing MOU</th><th>Incoming MOU</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _send_email(to: List[str], cc: List[str], body: str,
                inline_images: List[Path], data_dir: Path) -> dict:
    """经统一 EWS 邮件脚本发送（内嵌图片，不带 Excel）。"""
    script = EMAIL_REPORTS_DIR / "owa_mail_report.py"
    if not script.is_file():
        return {"success": False, "error": f"邮件脚本不存在: {script}"}

    cmd = [
        _MANAGED_VENV_PY, str(script),
        "--data-dir", str(data_dir),
        "--email-dir", str(EMAIL_REPORTS_DIR),
        "--no-excel",
        "--subject", SUBJECT,
        "--body", body,
        "--html",
        "--to", ";".join(to),
        "--cc", ";".join(cc) if cc else "",
    ]
    for img in inline_images:
        cmd += ["--images", str(img)]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, cwd=str(MY_APP_DIR), creationflags=_SUBPROCESS_FLAGS,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "发送超时"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    if proc.returncode == 0:
        return {"success": True, "message": (proc.stdout or "")[-500:]}
    return {"success": False, "error": (proc.stderr or proc.stdout or "")[-1000:]}


def _cleanup_old_run_dirs(keep_days: int = 14) -> None:
    """清理历史运行目录，避免 PNG 无限堆积。"""
    try:
        import shutil
        cutoff = time.time() - keep_days * 86400
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


def run_mtn_mou_daily_email(to_override: Optional[str] = None,
                            cc_override: Optional[str] = None) -> dict:
    """主入口：取数 → 出两张图 → 发邮件。"""
    t0 = time.perf_counter()

    from backend.services.email_recipient_store import get_email_recipients
    to_arg, cc_arg = get_email_recipients(EMAIL_GROUP_KEY, to_override, cc_override)
    to_list = [a.strip() for a in (to_arg or "").split(";") if a.strip()]
    cc_list = [a.strip() for a in (cc_arg or "").split(";") if a.strip()]
    if not to_list:
        return {"success": False, "error": "收件人为空（Settings → 邮件收件人）"}
    logger.info("收件人: %d 主送, %d 抄送", len(to_list), len(cc_list))

    df = _fetch_mou_data()
    if df is None or df.empty:
        return {"success": False, "error": f"{REMOTE_TABLE} 无可用数据"}

    run_dir = OUTPUT_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    charts: List[Path] = []
    p = _plot_series(df, "Outgoing MOU", "MTN Outgoing MOU (Daily)",
                     COLOR_OUT, run_dir / "Outgoing MOU.png")
    if p:
        charts.append(p)
    p = _plot_series(df, "Incoming MOU", "MTN Incoming MOU (Daily)",
                     COLOR_IN, run_dir / "Incoming MOU.png")
    if p:
        charts.append(p)

    if not charts:
        return {"success": False, "error": "两张图都没有生成，跳过发送"}

    last = df.iloc[-1]
    # 图片由 owa_mail_report.py 按 --images 自动内嵌（每张图上方带文件名作说明），
    # 正文里不要自己再写 <img>，否则会出现重复/断图。
    body = (
        "<p>Dear Team,</p>"
        f"<p>Please find the MTN MOU traffic for the last {len(df)} complete days "
        f"(latest: <b>{last['Start Time'].strftime('%Y-%m-%d')}</b>).</p>"
        "<p>Last 7 days:</p>"
        + _summary_table(df)
        + "<br><p>Best regards,<br>ZTENOC OLR</p>"
    )

    result = _send_email(to_list, cc_list, body, charts, run_dir)
    result["charts_generated"] = len(charts)
    result["rows"] = len(df)
    result["elapsed_seconds"] = round(time.perf_counter() - t0, 2)

    _cleanup_old_run_dirs(keep_days=14)
    logger.info("任务完成: %s", result)
    return result


def run_mtn_mou_chart_email() -> dict:
    """供 Task Manager 调用的入口。"""
    logger.info("开始 MTN MOU Daily Traffic 图表邮件任务")
    try:
        return run_mtn_mou_daily_email()
    except Exception as e:
        logger.error("任务异常: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    print(run_mtn_mou_chart_email())

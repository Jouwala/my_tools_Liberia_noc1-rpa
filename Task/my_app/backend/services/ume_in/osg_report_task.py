# -*- coding: utf-8 -*-
"""客户业务 KPI 同步 + OSG 周报邮件（定时任务 `ume_in_osg_report`）
=================================================================

一条任务把三件事按顺序串起来（"分步执行"，任一步失败即中止后续步骤）：

  1. **同步**：调用 ``ume_in_kpi_service.run_ume_in_kpi_sync()``，从 UME 门户
     （172.17.208.1:28808）抓 Dong customer 7 个模板（IVR/P4M/VC/USSD/PPS/CPU/Memory），
     直写主库表 ``ume_in_customer_kpi``（联合去重，幂等）。
  2. **生成**：调用 ``t_osg_build.build_osg_report()``，取表里最新 7 天填充
     ``OSG Weekly QoS Analysis Report`` 模板，产出
     ``data/in_data/OSG Weekly QoS Analysis Report_<起>_<止>.xlsx``。
  3. **发信**：把该 Excel 作为附件经 Orange EWS 发给
     ``djoumene.reussite1@zte.com.cn``，抄送 ``dong.xinmin@zte.com.cn``
     （收件人可在 Settings → Email Recipient Settings 的
     ``ume_in_osg_report`` 组覆盖）。

调度：每天早上 06:30（``30 6 * * *``），worker 组 ``n``
（与 ``ume_in_kpi_sync`` 同一 UME Dong 门户会话，必须同组串行）。
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("ume_in_osg_report")


def run_ume_in_osg_report(days_back=None, win_start=None, win_end=None,
                          to=None, cc=None, send_email=True) -> dict:
    """定时任务入口：同步 KPI → 生成 OSG 周报 → 邮件发送。

    Args:
        days_back: 传给 ume_in_kpi_service 的回看天数（None = 用服务默认 7 天）。
        win_start / win_end: 报告窗口（7 天）；默认取同步后表里最新一天为结束日。
        to / cc: 收件人覆盖（测试用）；默认读 Settings 的 ume_in_osg_report 组。
        send_email: False 时只同步+生成，不发邮件（手工核对用）。

    Returns:
        {success, message, sync, build, email}
        任一步失败：success=False 且 error 指向失败步骤，后续步骤不再执行。
    """
    t0 = time.time()
    result: dict = {"success": False, "sync": None, "build": None, "email": None}

    # ---- 1. 同步（ume_in_kpi_service）----
    try:
        from backend.services.ume_in import ume_in_kpi_service
    except Exception as e:  # noqa: BLE001
        result["error"] = f"导入 ume_in_kpi_service 失败: {e}"
        return result

    try:
        sync_res = (ume_in_kpi_service.run_ume_in_kpi_sync()
                    if days_back is None
                    else ume_in_kpi_service.run_ume_in_kpi_sync(days_back=days_back))
    except Exception as e:  # noqa: BLE001
        logger.exception("[ume_in_osg] KPI 同步异常")
        result["error"] = f"KPI 同步异常: {e}"
        return result

    result["sync"] = {
        "success": bool(sync_res.get("success")),
        "rows_written": sync_res.get("rows_written"),
        "kpis": sync_res.get("kpis"),
        "errors": sync_res.get("errors"),
    }
    if not sync_res.get("success"):
        errs = "; ".join(str(x) for x in (sync_res.get("errors") or [])) or "未知原因"
        # 同步失败不生成报告：否则会把上一窗口的旧数据当新报告发出去
        result["error"] = f"ume_in KPI 同步失败，已中止后续步骤: {errs}"
        return result

    # ---- 2. 生成（t_osg_build）----
    try:
        from backend.services.ume_in import t_osg_build
        build_res = t_osg_build.build_osg_report(win_start=win_start, win_end=win_end)
    except Exception as e:  # noqa: BLE001
        logger.exception("[ume_in_osg] OSG 报告生成异常")
        result["error"] = f"OSG 报告生成异常: {e}"
        return result

    result["build"] = build_res
    if not build_res.get("success"):
        result["error"] = f"OSG 报告生成失败: {build_res.get('error')}"
        return result

    if not send_email:
        result["success"] = True
        result["message"] = f"仅生成（未发信）: {build_res.get('file_name')}"
        return result

    # ---- 3. 发信（Orange EWS，附件 = 刚生成的 Excel）----
    try:
        from backend.services import kpi_email_report
        email_res = kpi_email_report.run_ume_in_osg_report_email(
            report_path=build_res.get("output"), to=to, cc=cc)
    except Exception as e:  # noqa: BLE001
        logger.exception("[ume_in_osg] 邮件发送异常")
        result["error"] = f"邮件发送异常: {e}"
        return result

    result["email"] = email_res
    if not email_res.get("success"):
        result["error"] = f"Email: {email_res.get('error')}"
        return result

    result["success"] = True
    result["message"] = (
        f"同步 {sync_res.get('rows_written')} 行 → 生成 {build_res.get('file_name')} "
        f"→ 邮件已发送（{build_res.get('win_start')} ~ {build_res.get('win_end')}，"
        f"{time.time() - t0:.1f}s）"
    )
    logger.info("[ume_in_osg] %s", result["message"])
    return result

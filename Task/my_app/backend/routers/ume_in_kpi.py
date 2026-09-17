# -*- coding: utf-8 -*-
"""UME「Dong customer」周度业务 KPI 看板 API（ume_in）

数据来源：UME 门户 https://172.17.208.1:28808/em-portal/ 的 PM-analysis 历史指标接口
（7 个模板：IVR / P4M / VC / USSD / PPS / CPU / Memory），由
`ume_in_kpi_sync` 定时任务（每日 05:45）或本模块的同步端点写入主库表 `ume_in_customer_kpi`。

GET  /api/ume-in/overview?days=7
    -> {meta, summary, kpis[], alerts[]}
       kpis[].kind=success_rate：attempts/success/failed/success_rate
                                  + system_failed/user_failed（失败归因）
                                  + services[]（按 SERVICE 下钻）+ trend[]（多日）
       kpis[].kind=resource    ：avg/top + services[]（按 SERVICE）+ trend[]
       alerts[]：level=critical|warning|info（告警只来自系统侧失败率与资源利用率）

POST /api/ume-in/sync?days_back=7
    -> 立即登录门户重新抓取 7 个模板并写库，返回 {success, rows_written, kpis, errors}

GET  /api/ume-in/specs
    -> 模板清单（供前端展示口径说明）
"""
import logging

from fastapi import APIRouter, Query

from backend.services.ume_in import ume_in_kpi_service as svc

logger = logging.getLogger("ume_in_kpi_router")
router = APIRouter(prefix="/api/ume-in", tags=["ume-in"])


@router.get("/overview")
def overview(days: int = Query(7, ge=1, le=90, description="回看天数（按已有数据的最后 N 天）")):
    """返回业务 KPI 概览、失败归因分析、资源利用率与告警清单。"""
    try:
        return svc.load_overview(days=days)
    except Exception as e:  # noqa: BLE001
        logger.exception("ume_in overview failed")
        return {"error": str(e), "has_data": False}


@router.post("/sync")
def sync(days_back: int = Query(7, ge=1, le=90, description="抓取回看天数")):
    """立即抓取 UME 门户数据并写入主库（约 10~60 秒）。"""
    return svc.run_ume_in_kpi_sync(days_back=days_back)


@router.get("/specs")
def specs():
    """返回 KPI 模板与判定口径（供页面展示说明）。"""
    return {
        "source": f"https://{svc.HOST}:{svc.PORT}{svc.LOGIN_PORTAL}",
        "table": svc.TABLE_NAME,
        "granularity": "86400 (1 day)",
        "thresholds": {
            "success_warn": svc.SUCCESS_WARN, "success_crit": svc.SUCCESS_CRIT,
            "sys_fail_warn": svc.SYS_FAIL_WARN, "sys_fail_crit": svc.SYS_FAIL_CRIT,
            "res_warn": svc.RES_WARN, "res_crit": svc.RES_CRIT,
        },
        "kpis": [
            {"key": s["key"], "template": s["template"], "kind": s["kind"],
             "title_zh": s["title_zh"], "title_en": s["title_en"],
             "rate_label_zh": s.get("rate_label_zh", "成功率"),
             "rate_label_en": s.get("rate_label_en", "Success rate"),
             "alarm": s.get("alarm", True)}
            for s in svc.KPI_SPECS
        ],
    }

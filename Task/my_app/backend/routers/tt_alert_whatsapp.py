"""TT 告警文本作业接口 —— 供「TT 告警推送」Chrome 扩展使用。

业务逻辑（取数 / 渲染 / 节流 / 落库 / 作业状态机）都在
`backend/services/tt_alarm_whatsapp_service.py`；本文件只做 HTTP 薄封装，
与 `backend/routers/whatsapp_outbox.py`（发图作业）同构，但作业文件相互独立
（`data/tt_alert_job.json`），互不覆盖。

端点（均走 require_protected；扩展与后端同机，回环地址自动放行，无需 token）：
- GET  /api/whatsapp/tt-alert/job          → 认领一个待发文本作业，无则 {pending:false}
- POST /api/whatsapp/tt-alert/job/result   → 扩展回报发送结果
- GET  /api/whatsapp/tt-alert/log          → 查看发送日志表（运维排查用）

> 说明：扩展侧的**纯文本发送**能力尚未实现（现有扩展只发图片）。这些端点是
> 为补齐该能力预留的对接面，扩展实现后即可直接认领 job.kind == "text" 的作业。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.database import get_raw_connection
from backend.security import require_protected
from backend.services import tt_alarm_job as job_transport
from backend.services import tt_alarm_whatsapp_service as svc

logger = logging.getLogger("tt_alert_router")

router = APIRouter(tags=["tt_alert_whatsapp"])


class TtAlertJobResultBody(BaseModel):
    job_id: str
    ok: bool = False
    sent: list[str] = []
    errors: list[str] = []
    elapsed_seconds: float | None = None


@router.get("/api/whatsapp/tt-alert/job", dependencies=[Depends(require_protected)])
def poll_tt_alert_job():
    """扩展轮询：认领一个待发文本作业；无则 {pending:false}。"""
    claimed = job_transport.claim_pending_job()
    if claimed is None:
        return {"pending": False}
    return claimed


@router.post("/api/whatsapp/tt-alert/job/result", dependencies=[Depends(require_protected)])
def post_tt_alert_job_result(body: TtAlertJobResultBody):
    """扩展回报发送结果（sent 里列出真正发出的 tt_no）。"""
    accepted = job_transport.complete_job(
        body.job_id,
        {
            "ok": body.ok,
            "sent": body.sent,
            "errors": body.errors,
            "elapsed_seconds": body.elapsed_seconds,
        },
    )
    if not accepted:
        raise HTTPException(status_code=409, detail="job_id 不匹配或已被新作业取代")
    return {"ok": True}


@router.get("/api/whatsapp/tt-alert/log", dependencies=[Depends(require_protected)])
def get_tt_alert_log(limit: int = Query(100, ge=1, le=1000)):
    """发送日志表（最近 N 行），供运维核对发送状态。"""
    with get_raw_connection() as conn:
        svc.ensure_log_table(conn)
        cur = conn.execute(
            f"SELECT tt_no, alarm_occur_time, ticket_severity, alarm_code, site_name, "
            f"send_status, send_count, last_send_time, last_error, updated_time "
            f"FROM {svc.LOG_TABLE} ORDER BY updated_time DESC LIMIT ?",
            (int(limit),),
        )
        names = [d[0] for d in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]
    return {"count": len(rows), "rows": rows, "table": svc.LOG_TABLE}

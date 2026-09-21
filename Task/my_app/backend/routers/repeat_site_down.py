"""Daily repeat site-down dashboard API and drilldown endpoints."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Query
from backend.services.repeat_site_down import repeat_site_down_service as svc

logger = logging.getLogger("repeat_site_down")
router = APIRouter(prefix="/api/repeat-site-down", tags=["repeat-site-down"])


def _error_payload(exc: Exception) -> dict:
    logger.exception("repeat site-down API failed: %s", exc)
    return {"error": str(exc), "meta": {"warnings": [str(exc)]}, "summary": {"outage_events": 0, "affected_sites": 0, "repeat_sites": 0, "peak_day": "", "peak_day_count": 0}, "daily": [], "sites": [], "events": []}


def _window(start: str, end: str) -> tuple[str, str]:
    return (start, end) if start and end else svc.default_window()


@router.get("/filters")
def filters():
    try: return svc.get_filters()
    except Exception as exc: return {"regions": [], "default_start": "", "default_end": "", "schema": {"warnings": [str(exc)]}}


@router.get("/overview")
def overview(start: str = Query(""), end: str = Query(""), region: str = Query("", max_length=120), site: str = Query("", max_length=160)):
    try:
        start, end = _window(start, end); return svc.get_overview(start, end, region, site)
    except Exception as exc: return _error_payload(exc)


@router.get("/sites")
def sites(start: str = Query(""), end: str = Query(""), region: str = Query("", max_length=120), site: str = Query("", max_length=160), page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500)):
    try:
        start, end = _window(start, end); payload = svc.get_overview(start, end, region, site); all_sites = payload["sites"]; offset = (page - 1) * page_size
        payload["sites"] = all_sites[offset:offset + page_size]; payload["pagination"] = {"page": page, "page_size": page_size, "total": len(all_sites)}; return payload
    except Exception as exc: return _error_payload(exc)


@router.get("/events")
def events(start: str = Query(""), end: str = Query(""), site_id: str = Query("", max_length=120), site_name: str = Query("", max_length=160), day: str = Query("", max_length=10), region: str = Query("", max_length=120)):
    try:
        start, end = _window(start, end); return svc.get_site_drilldown(start, end, site_id, site_name, region)
    except Exception as exc: return _error_payload(exc)


@router.get("/day-drilldown")
def day_drilldown(start: str = Query(""), end: str = Query(""), day: str = Query(..., min_length=10, max_length=10), region: str = Query("", max_length=120), site: str = Query("", max_length=160)):
    try:
        start, end = _window(start, end); return svc.get_day_drilldown(start, end, day, region, site)
    except Exception as exc: return _error_payload(exc)


@router.get("/site-drilldown")
def site_drilldown(start: str = Query(""), end: str = Query(""), site_id: str = Query("", max_length=120), site_name: str = Query("", max_length=160), region: str = Query("", max_length=120), site: str = Query("", max_length=160)):
    try:
        start, end = _window(start, end); return svc.get_site_drilldown(start, end, site_id, site_name, region, site)
    except Exception as exc: return _error_payload(exc)


@router.get("/event-detail")
def event_detail(start: str = Query(""), end: str = Query(""), tt_no: str = Query("", max_length=120), alarm_occur_time: str = Query("", max_length=40), site_id: str = Query("", max_length=120), site_name: str = Query("", max_length=160), region: str = Query("", max_length=120)):
    try:
        start, end = _window(start, end); return svc.get_event_detail(start, end, tt_no, alarm_occur_time, site_id, site_name, region)
    except Exception as exc: return _error_payload(exc)

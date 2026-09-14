"""无网络测试：客户端门户扩展的短票据与会话计划。"""

import pytest
from fastapi import HTTPException

from backend.routers import portals
from backend.services import portal_login_service as svc


def test_eflow_client_plan_contains_session_not_password(monkeypatch):
    monkeypatch.setattr(svc, "_eflow_direct_auth", lambda spec: ("A=one; B=two", "csrf-value"))
    plan = svc.build_client_login_plan("eflow")

    assert plan["system"] == "eflow"
    assert plan["origin"] == "https://10.100.20.8:28001"
    assert plan["eflow_csrf_token"] == "csrf-value"
    assert plan["cookies"] == [
        {"name": "A", "value": "one", "httpOnly": True},
        {"name": "B", "value": "two", "httpOnly": True},
    ]
    assert "username" not in plan and "password" not in plan


def test_rais_client_plan_seeds_all_browser_sso_cookies(monkeypatch):
    monkeypatch.setattr(svc, "_rais_direct_auth", lambda spec: ("portal-user", "session-token"))
    plan = svc.build_client_login_plan("rais")

    assert plan["target_url"].endswith("#/homepage")
    assert {item["name"] for item in plan["cookies"]} == {name for name, _ in svc.RAIS_SSO_COOKIES}
    assert all(item["httpOnly"] is False for item in plan["cookies"])
    assert all(item["value"] in {"portal-user", "session-token"} for item in plan["cookies"])


def test_client_ticket_is_single_use(monkeypatch):
    with portals._CLIENT_TICKETS_LOCK:
        portals._CLIENT_TICKETS.clear()
    monkeypatch.setattr(svc, "build_client_login_plan", lambda system: {"system": system})

    issued = portals.create_client_login_ticket(portals.PortalClientTicketRequest(system="eflow"))
    consumed = portals.consume_client_login_ticket(
        portals.PortalClientConsumeRequest(ticket=issued["ticket"])
    )

    assert consumed == {"plan": {"system": "eflow"}}
    with pytest.raises(HTTPException) as error:
        portals.consume_client_login_ticket(portals.PortalClientConsumeRequest(ticket=issued["ticket"]))
    assert error.value.status_code == 401

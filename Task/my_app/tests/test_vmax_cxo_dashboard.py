from pathlib import Path

from backend.routers import vmax_cxo_dashboard as api


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "frontend" / "public" / "vmax_cxo_dashboard.html"
PAGE = ROOT / "frontend" / "src" / "pages" / "VmaxCxoDashboard.tsx"


def test_react_route_targets_deployed_public_file():
    assert 'file="vmax_cxo_dashboard.html"' in PAGE.read_text(encoding="utf-8")
    assert HTML.is_file()


def test_theme_and_request_race_guards_are_present():
    text = HTML.read_text(encoding="utf-8")
    assert 'data-theme="light"' in text
    assert "__type==='myapp-theme'" in text
    assert "operationalController.abort()" in text
    assert "requestId!==operationalRequest" in text
    assert "/api/cxo-dashboard/cache" not in text


def test_api_views_strip_internal_fields():
    raw = {
        "showName": "Traffic",
        "kpiValue": 42,
        "unit": "GB",
        "queryData": {"cookie": "secret"},
        "option": {"series": [{"data": [1]}]},
    }
    assert api._overview_view(raw) == {"showName": "Traffic", "kpiValue": 42, "unit": "GB"}
    assert "queryData" not in api._trend_view(raw)
    assert "queryData" not in api._chart_view(raw)


def test_all_declared_tabs_have_indicators():
    assert set(api.NET_TABS) == {1, 2, 3, 4, 5}
    assert all(api.NET_TABS.values())
    assert {"Mobility", "Voice", "Data", "Video", "SMS", "Web Browse", "Game", "OTTVoice", "OTTVideo"} == set(api.SERVICE_MANIFEST)

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.routers.vmax_cxo_dashboard import get_vmax_cxo_summary

response = get_vmax_cxo_summary()
payload = json.loads(response.body)
assert payload["status"] == "ok", payload
assert len(payload["summary"]["overview"]) == 4, payload
assert len(payload["summary"]["trends"]) == 6, payload
print("VMAX_CXO_BACKEND_OK", payload["source"], payload.get("updated_at"))

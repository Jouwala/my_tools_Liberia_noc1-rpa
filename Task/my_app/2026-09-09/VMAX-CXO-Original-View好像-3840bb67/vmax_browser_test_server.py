import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

PUBLIC = Path(r"Y:\Task\my_app\frontend\public")
PORT = 4178

def line(title, values=(10, 20, 15, 28)):
    return {"title": title, "option": {"xAxis": {"type": "category", "data": ["00:00", "06:00", "12:00", "18:00"]}, "yAxis": {"type": "value"}, "series": [{"name": "day-0", "type": "line", "data": list(values)}]}}

SUMMARY = {"status":"ok","source":"cache","updated_at":"2026-09-09T10:00:00Z","summary":{"overview":{"131":{"showName":"User(K)","kpiValue":"158.71"},"132":{"showName":"Traffic(TB)","kpiValue":"2.81"},"133":{"showName":"TCP Uplink RTT","kpiValue":"80.96"},"134":{"showName":"TCP Downlink RTT","kpiValue":"119.90"}},"trends":{"91":line("Traffic",(100,130,125,160)),"92":line("Users",(20,24,23,28)),"93":line("Throughput",(4,7,6,9))},"geMap":{"series":[{"data":[{"name":"Montserrado","value":5200},{"name":"Bomi","value":1200}]}]},"userData":{"option":{"series":[{"type":"pie","data":[{"name":"Video","value":79},{"name":"Web","value":21}]}]}},"cityUser":{"option":{"yAxis":[{}, {"data":[158709]}]}}}}

def operational(view, key):
    items=[{"id":"391","title":"Success Rate","value":"99.2%","option":line("Success",(97,98,99,99.2))["option"]},{"id":"392","title":"Latency","value":"42 ms","option":line("Latency",(48,45,44,42))["option"]}]
    body={"status":"ok","source":"cache","updated_at":"2026-09-09T10:00:00Z","indicators":items,"map":{"option":{"series":[{"data":[{"name":"Montserrado","value":88}]}]}}}
    if view=="service":
        body.update({"business":key,"delimit":{"option":{"series":[{"type":"pie","data":[{"name":"Normal","value":82},{"name":"Radio","value":18}]}]}},"limit":{"header":["Cause","Count"],"data":[["Radio",12],["Transport",4]]}})
    else: body["tab"]=int(key)
    return body

class Handler(BaseHTTPRequestHandler):
    def send_json(self, value):
        raw=json.dumps(value).encode(); self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        path=unquote(urlparse(self.path).path)
        if path=="/api/vmax-cxo-dashboard/summary": return self.send_json(SUMMARY)
        if path.startswith("/api/vmax-cxo-dashboard/service/"): return self.send_json(operational("service",path.rsplit("/",1)[-1]))
        if path.startswith("/api/vmax-cxo-dashboard/network/"): return self.send_json(operational("network",path.rsplit("/",1)[-1]))
        rel=path.lstrip("/") or "vmax_cxo_dashboard.html"
        if rel.startswith("myapp/"):
            rel=rel[len("myapp/"):]
        target=(PUBLIC/rel).resolve()
        if PUBLIC.resolve() not in target.parents and target!=PUBLIC.resolve(): self.send_error(403); return
        if not target.is_file(): self.send_error(404); return
        raw=target.read_bytes(); self.send_response(200); self.send_header("Content-Type",mimetypes.guess_type(target.name)[0] or "application/octet-stream"); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def log_message(self, fmt, *args): pass

if __name__=="__main__": ThreadingHTTPServer(("0.0.0.0",PORT),Handler).serve_forever()

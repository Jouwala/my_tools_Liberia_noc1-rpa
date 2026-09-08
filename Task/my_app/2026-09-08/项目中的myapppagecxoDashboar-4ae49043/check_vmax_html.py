from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
target = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "frontend" / "public" / "vmax_cxo_dashboard.html"
html = target.read_text(encoding="utf-8")
scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, flags=re.S | re.I)
inline = "\n".join(s for s in scripts if s.strip())
out = Path(__file__).with_name("vmax_cxo_inline_check.js")
out.write_text(inline, encoding="utf-8")
node = Path(r"C:\Program Files\nodejs\node.exe")
result = subprocess.run([str(node), "--check", str(out)], text=True, capture_output=True)
print(result.stdout, end="")
print(result.stderr, end="")
raise SystemExit(result.returncode)

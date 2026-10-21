#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TT 规则引擎 HTTP 桥 —— 把 tt-analyze.py 的确定性判定暴露给 Open WebUI。

## 为什么需要这个桥

Open WebUI 跑在 Docker 容器里，看不到宿主机上的 tt-analyze.py，也装不了它的
依赖（openpyxl + 规则 Excel）。而 tt-analyze.py 是这套系统里**唯一**能给出
「命中了哪条级别规则 / 命中了哪条推单规则 / 为什么派给 FE」的地方 ——
Open WebUI 自带的 `inspect-tt` 只返回原始字段，规则判定得让 LLM 自己猜。

所以本服务只做一件事：**收 HTTP 请求 → subprocess 调 tt-analyze.py → 回文本**。
不做取数、不做渲染、不做判定，全部复用 bot 已有的那套逻辑，保证
「Open WebUI 说的」和「WhatsApp 说的」永远同源。

## 用法

    python tt-analyze-http.py --port 8765 --token <token>

## 请求

    GET /health
    GET /analyze?tt=TT202610200121&lang=en
    Header: X-Token: <token>

## 设计取舍

- **用 subprocess 而不是 import**：tt-analyze.py 是个 2800 行的脚本，顶部有
  模块级常量和 CLI 解析。import 它会在本进程里留下状态，一次异常就可能拖垮
  整个服务。subprocess 的代价是每次多 ~0.3s 启动，换来的是「脚本崩了服务还在」。
- **默认回渲染后的文本**：LLM 读 `[Assignment basis] Dispatch: #204 ... → ZTE_NOC_FO`
  比读嵌套 JSON 省 token，也更不容易漏字段。
- **必须带 token**：本服务监听 0.0.0.0（Docker 容器要走 host.docker.internal
  进来），不设鉴权等于把内部工单分析接口裸奔在局域网上。
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ANALYZE = HERE / 'tt-analyze.py'

# ── 索引缓存放本地盘，不放 Y 盘 ────────────────────────────────────────────
# tt-analyze.py 默认把单号索引写在 <项目>/data/tt-index.json，而 Y: 是网络盘
# （实测解析成 \\192.168.100.20\01_rpa\...）。索引 1.3MB，从网络盘读写虽不算慢，
# 但**写**这一侧实测 mtime 一直不更新 —— 重建完的索引落不了盘，下一个进程又重建，
# 于是每次调用都吃一次 11~32 秒的全表扫描。
# 指到本地盘后实测：首次重建 27s，之后命中索引稳定 8s。
_INDEX_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'tt-analyze-bridge'
_INDEX_DIR.mkdir(parents=True, exist_ok=True)
INDEX_CACHE = _INDEX_DIR / 'tt-index.json'

# 索引 TTL：my_app 的同步不是实时的，索引里的「新单号」本来就滞后。
# 设长一点（1 天）让命中路径稳定；真正的安全性由 tt-analyze.py 的锚点抽查兜底
# —— rowid 被重排时锚点会对不上，索引自动作废重建，不依赖 TTL 发现问题。
INDEX_TTL = '86400'

# 与 src/tt.js 同一个解释器约定（可用 TT_PYTHON 覆盖）。
DEFAULT_PYTHON = r'C:/Users/ZTEEMS/AppData/Local/Programs/Python/Python312/python.exe'

# 单号白名单：只允许字母数字与 - _，防命令注入（subprocess 用列表传参，这里再加一层）
TT_RE = re.compile(r'^[A-Z0-9_\-]{4,64}$')
LANGS = ('zh', 'en')

# 首次调用要建 rowid 索引（全表扫描），实测可达数十秒；之后走索引约 1-3s。
TIMEOUT = 120

TOKEN = ''


class Handler(BaseHTTPRequestHandler):
    server_version = 'tt-analyze-bridge/1.0'

    # 静默默认的逐请求 access log，只记错误和慢请求
    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        got = self.headers.get('X-Token') or ''
        return bool(TOKEN) and hmac.compare_digest(got, TOKEN)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        u = urlparse(self.path)

        if u.path == '/health':
            self._send(200, {'ok': True, 'service': 'tt-analyze-bridge',
                             'script': str(ANALYZE), 'script_exists': ANALYZE.exists(),
                             'index_cache': str(INDEX_CACHE),
                             'index_exists': INDEX_CACHE.exists()})
            return

        if u.path != '/analyze':
            self._send(404, {'ok': False, 'error': 'unknown path'})
            return

        if not self._authed():
            self._send(401, {'ok': False, 'error': 'bad or missing X-Token'})
            return

        q = parse_qs(u.query)
        tt = (q.get('tt') or [''])[0].strip().upper()
        lang = (q.get('lang') or ['en'])[0].strip().lower()

        if not TT_RE.match(tt):
            self._send(400, {'ok': False, 'error': 'invalid tt_no'})
            return
        if lang not in LANGS:
            lang = 'en'
        if not ANALYZE.exists():
            self._send(500, {'ok': False, 'error': f'script not found: {ANALYZE}'})
            return

        cmd = [PYTHON, str(ANALYZE), tt, '--lang', lang]
        env = {**os.environ,
               'TT_INDEX_CACHE': str(INDEX_CACHE),
               'TT_INDEX_TTL': INDEX_TTL}
        t0 = time.time()
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT, env=env)
        except subprocess.TimeoutExpired:
            self._send(504, {'ok': False, 'error': f'analyze timeout after {TIMEOUT}s'})
            return
        except Exception as e:  # 解释器缺失等
            self._send(500, {'ok': False, 'error': f'{type(e).__name__}: {e}'})
            return

        out = p.stdout.decode('utf-8', 'replace').strip()
        err = p.stderr.decode('utf-8', 'replace').strip()
        elapsed = round(time.time() - t0, 2)

        # 退出码约定（见 tt-analyze.py 的 main）：0 命中 / 1 查无此单 / 2 输入问题 / 3 分析异常
        if p.returncode == 0 and out:
            self._send(200, {'ok': True, 'tt': tt, 'lang': lang,
                             'elapsed_s': elapsed, 'text': out})
        elif p.returncode == 1:
            self._send(200, {'ok': True, 'tt': tt, 'lang': lang, 'found': False,
                             'elapsed_s': elapsed,
                             'text': f'TT {tt} not found in the local TT database.'})
        else:
            self._send(500, {'ok': False, 'tt': tt, 'exit_code': p.returncode,
                             'elapsed_s': elapsed,
                             'error': err[-800:] or out[-800:] or 'unknown error'})

    def do_POST(self) -> None:  # noqa: N802
        self._send(405, {'ok': False, 'error': 'GET only'})


def main() -> int:
    global PYTHON, TOKEN
    ap = argparse.ArgumentParser(description='tt-analyze.py 的 HTTP 桥')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--token', default='', help='必填；请求需带 X-Token 头')
    ap.add_argument('--python', default=DEFAULT_PYTHON, help='tt-analyze.py 的解释器')
    args = ap.parse_args()

    if not args.token:
        print('必须提供 --token', file=sys.stderr)
        return 2
    TOKEN = args.token
    PYTHON = args.python

    if not ANALYZE.exists():
        print(f'找不到 {ANALYZE}', file=sys.stderr)
        return 2
    if not Path(PYTHON).exists():
        print(f'解释器不存在：{PYTHON}（可用 --python 覆盖）', file=sys.stderr)
        return 2

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'tt-analyze bridge listening on {args.host}:{args.port}', flush=True)
    print(f'  script : {ANALYZE}', flush=True)
    print(f'  python : {PYTHON}', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())

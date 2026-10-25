#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""eFlow 实时「按站点查活动告警」桥接 —— 原型（v0）。

用法：
    python eflow-live-alarms.py "Palm Bay" [--json]

职责：用 my_app 自己的代码去 eFlow 活接口拉**当前活动告警**，按站点名过滤，
把结论以 JSON 打到 stdout。渲染不在本脚本做（与 eflow-live-tt.py 同约定）。

为什么是「拉全量再本地过滤」而不是「让 eFlow 按站点过滤」：
  · `/api/fm-active/v1/activealarms/table` 的 condition 里加站点过滤键，
    仓库里**没有抓到现成样例**（URL_EFLOW_ALARM.txt 只有 detail/subtab 调用），
    键名靠猜会 400/静默返回空 —— 那正是「自信的错误」最坏的形态。
  · 活动告警总量很小（当前实测 ~29~200 行），拉全量再本地匹配，代价可忽略，
    且**复用已跑通的生产 payload**（eflow_alarm_service.ALARM_CONDITION）。
  · 站名匹配用「规范化包含」：去空格、大小写不敏感，避免 "Palm  Bay" /
    "palm bay" 这类输入漏match。

退出码（与 eflow-live-tt.py 对齐）：
    0  查到站点且**有**活动告警，stdout 是 JSON
    1  查到站点但**无**活动告警（明确的「干净」，不是故障）
    2  通道不可用（缺解释器/依赖/未配置）—— 永久，别重试
    3  真出错（登录失败/网络）—— 暂时，值得重试
    4  站点名在告警/站表里**找不到**（不是「无告警」，是「没这个站」）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import my_app_paths
    MY_APP_DIR = my_app_paths.find_my_app_dir()
except Exception:
    MY_APP_DIR = os.environ.get('MY_APP_DIR', r'D:/01_RPA/Task/my_app')

_CANDIDATES = [
    os.path.join(MY_APP_DIR, '.venv', 'Scripts', 'python.exe'),
    r'C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe',
    r'C:\Python312\python.exe',
    r'C:\Python314\python.exe',
]
_PROBE = ('import importlib.util as u, sys;'
          'sys.exit(0 if all(u.find_spec(m) for m in ("pandas","sqlalchemy")) else 1)')
_MISS = '__ALARM_SITE_MISS__'

# 真正取数：复用生产 pipeline，按 site 名过滤。 
_FETCH = """
import json, os, sys
app = os.environ["ALARMS_APP_DIR"]
site = os.environ["ALARMS_SITE"]
sys.path.insert(0, app); os.chdir(app)
try:
    from backend.services.eflow_alarm_service import _fetch_alarm_pipeline
except Exception as e:
    print("IMPORT_FAIL: %s" % e, file=sys.stderr); sys.exit(3)
try:
    _, rows = _fetch_alarm_pipeline()
except Exception as e:
    print("FETCH_FAIL: %s: %s" % (type(e).__name__, e), file=sys.stderr); sys.exit(3)

def norm(s):
    return "".join(str(s or "").lower().split())
target = norm(site)
def site_of(r):
    for k in ("Site Name", "site_name", "Site ID", "site", "mename", "Object Name"):
        v = r.get(k)
        if v not in (None, "", "--"):
            return v
    return ""
hits = [r for r in rows
        if target and (target in norm(site_of(r)) or norm(site_of(r)) in target)]

# 站点名可能要连站号一起匹配（用户常写「Grand Cess(3629)」）。站号在
# "Site ID" / "Object Name" 里；上面 site_of 取的是站名，所以这里补一次。
if not hits:
    num = "".join(ch for ch in site if ch.isdigit())
    if num:
        hits = [r for r in rows
                if str(r.get("Site ID") or "").strip() == num
                or str(r.get("Object Name") or "").strip() == num]

def _clean(v):
    # 把 eFlow 里的占位值（空串 / "--" / "-" / None）统一成空串。
    # 注意：这里用行注释而不是 docstring —— 占位值本身的引号会提前闭合三引号。
    s = str(v if v is not None else "").strip()
    return "" if s in ("", "--", "-") else s

def pick(r):
    # 注意：`codename` 是**告警名**（"Complete site down (CSD)"），
    # 真正的告警码在 `alarmcode`（9920）。早期版本把两者混成 "code" 字段，
    # 导致群里收到「Alarm code 9920 → …」之后站点告警回复里反而没有码。
    return {
        "site": site_of(r),
        "site_id": _clean(r.get("Site ID")) or _clean(r.get("Object Name")),
        "alarm": _clean(r.get("Alarm Title")) or _clean(r.get("codename")),
        "code": _clean(r.get("alarmcode")),
        "severity": _clean(r.get("perceivedseverityname")) or _clean(r.get("perceivedseverity")),
        "duration": _clean(r.get("durationname")),
        # 用户常拿「Alarm occurred <时间>」来核对是哪一条，所以必须原样给出。
        "raised": r.get("alarmraisedtime") or r.get("raised") or "",
        "tt": _clean(r.get("TT ID")) or _clean(r.get("TT Info")),
        "region": _clean(r.get("Region")),
        "clearstate": r.get("clearstate"),
        "clearstate_name": _clean(r.get("clearstatename")),
        # 派单侧诊断：这三项在活动告警接口里是现成的，不用二次查询。
        "assign_delay": _clean(r.get("Assign Delay")),
        "hub_site_flag": _clean(r.get("Hub Site Flag")),
        "link_path": _clean(r.get("Link Path")),
    }

def _raised_key(a):
    # 按告警发生时间倒序（最新在前），让用户问的那条排第一。
    # eFlow 的 alarmraisedtime 是毫秒时间戳；缺失的排最后。
    v = a.get("raised")
    try:
        return -int(v)
    except Exception:
        return 0

alarms = sorted((pick(r) for r in hits), key=_raised_key)
out = {"site_query": site, "total_active": len(rows),
       "matched": len(hits), "alarms": alarms}
sys.stdout.write(json.dumps(out, ensure_ascii=False, default=str))
"""



def _find_interpreter():
    for exe in _CANDIDATES:
        if os.path.isfile(exe):
            try:
                p = subprocess.run([exe, '-c', _PROBE], capture_output=True, timeout=60,
                                   cwd=MY_APP_DIR if os.path.isdir(MY_APP_DIR) else None)
            except Exception:
                continue
            if p.returncode == 0:
                return exe
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description='eFlow 实时按站点查活动告警（原型）')
    ap.add_argument('site', nargs='?', help='站点名，如 "Palm Bay"')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--which', action='store_true')
    args = ap.parse_args()

    exe = _find_interpreter()
    if args.which:
        print(exe or '(未找到可用解释器：通道不可用)')
        return 0 if exe else 2
    if not args.site:
        ap.error('需要站点名（或用 --which 查看通道是否可用）')
    if not exe:
        print(f'通道不可用：在 {MY_APP_DIR} 下没找到装齐 pandas+sqlalchemy 的解释器。',
              file=sys.stderr)
        return 2

    code = _FETCH
    try:
        child_env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
                     'ALARMS_APP_DIR': MY_APP_DIR, 'ALARMS_SITE': args.site.strip()}
        p = subprocess.run([exe, '-c', code], capture_output=True, timeout=180,
                           cwd=MY_APP_DIR if os.path.isdir(MY_APP_DIR) else None,
                           env=child_env)
    except subprocess.TimeoutExpired:
        print('实时告警查询超时（180s）', file=sys.stderr); return 3
    except Exception as e:
        print(f'启动失败：{type(e).__name__}: {e}', file=sys.stderr); return 3

    if p.returncode != 0:
        detail = (p.stderr or b'').decode('utf-8', 'replace').strip()
        lines = [l for l in detail.splitlines() if l.strip()]
        print(lines[-1] if lines else f'退出码 {p.returncode}', file=sys.stderr)
        return 3

    out = (p.stdout or b'').decode('utf-8', 'replace').strip()
    if not out:
        print('返回空结果', file=sys.stderr); return 3
    try:
        obj = json.loads(out)
    except Exception as e:
        print(f'非法 JSON：{e}', file=sys.stderr); return 3

    sys.stdout.write(out)
    # 没匹配到任何活动告警：区分「站点存在但干净」与「查无此站」需要站表，
    # 原型阶段先只区分「有告警 / 无活动告警」。
    return 0 if obj.get("matched") else 1


if __name__ == '__main__':
    sys.exit(main())

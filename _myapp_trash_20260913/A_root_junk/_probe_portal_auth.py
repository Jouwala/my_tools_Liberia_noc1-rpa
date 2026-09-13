# -*- coding: utf-8 -*-
"""portal_auth 会话落盘验证（无副作用：只建表 + 自建自删探针记录）。

运行：cwd = my_app 根目录，用系统 Python312。
"""
import os
import secrets
import sys
import time

sys.path.insert(0, os.getcwd())

from backend.database import DB_MODE, DB_PATH, get_raw_connection  # noqa: E402
from backend.services import portal_auth as pa  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))
    if not cond:
        fails.append(name)


print("=== 环境 ===")
print("MY_APP_DB_MODE =", DB_MODE)
print("DB_PATH        =", DB_PATH)
print("SESSION_TTL    =", pa.SESSION_TTL)
print("SESSION_MAX_TTL=", pa.SESSION_MAX_TTL, "SLIDING=", pa.SESSION_SLIDING)
print("COOKIE_MAX_AGE =", pa.SESSION_COOKIE_MAX_AGE, "KIOSK_KEY set =", bool(pa.KIOSK_KEY))
print()

# --- 1. 建表并确认落点（PG 模式应落在 app schema） ---
now = time.time()
sid = "__probe__" + secrets.token_hex(8)
kid = "__kiosk_probe__" + secrets.token_hex(8)

try:
    with get_raw_connection() as conn:
        pa._ensure_table(conn)
        rows = conn.execute(
            "SELECT table_schema, table_name FROM information_schema.tables WHERE table_name='portal_sessions'"
        ).fetchall() if DB_MODE == "pg" else conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='portal_sessions'"
        ).fetchall()
    print("portal_sessions 落点:", [tuple(r) for r in rows])
    check("建表 portal_sessions 已存在", len(rows) >= 1)
except Exception as e:  # noqa: BLE001
    check("建表 portal_sessions 已存在", False, repr(e))

# --- 2. 普通会话写入 / 读回（含 JSON 字段） ---
normal = {
    "username": "probe_user",
    "role": "viewer",
    "exp": now + 3600,
    "created": now,
    "last_seen": now,
    "allowedGroups": ["g1", "g2"],
    "allowedCards": None,
    "persistent": False,
}
pa._db_upsert(sid, normal)
got = pa._db_get(sid)
check("普通会话可读回", got is not None and got["username"] == "probe_user", got)
check("JSON 字段 allowedGroups 保持", got is not None and got["allowedGroups"] == ["g1", "g2"], got and got["allowedGroups"])
check("allowedCards 为 None 不失真", got is not None and got["allowedCards"] is None, got and got["allowedCards"])
check("exp 秒级不丢精度", got is not None and abs(got["exp"] - int(now + 3600)) <= 1, got and got["exp"])

# --- 3. 常驻会话（exp=0 永不过期） ---
kiosk = dict(normal, username="kiosk", exp=0.0, persistent=True)
pa._db_upsert(kid, kiosk)
kgot = pa._db_get(kid)
check("常驻会话 exp=0", kgot is not None and kgot["exp"] == 0.0, kgot and kgot["exp"])
check("常驻会话 persistent=True", kgot is not None and kgot["persistent"] is True, kgot and kgot["persistent"])
check("_is_expired(常驻)=False", not pa._is_expired(kgot or {}))

# --- 4. 模拟进程重启：清空内存 + 清掉 warm 标记，再从库预热 ---
pa._SESSIONS.clear()
pa._last_persist.clear()
pa._warm_done = False
loaded = pa._db_load_all(time.time())
check("重启后能从未过期会话回填", sid in loaded and kid in loaded, sorted(loaded.keys()))

pa._SESSIONS.clear()
pa._warm_done = False
pa._warm()
check("_warm() 把会话灌回内存", sid in pa._SESSIONS and kid in pa._SESSIONS, list(pa._SESSIONS.keys()))
check("预热后 _is_expired(普通)=False", not pa._is_expired(pa._SESSIONS.get(sid, {})))

# --- 5. 过期会话不应被载入 ---
dead = "__dead__" + secrets.token_hex(8)
pa._db_upsert(dead, dict(normal, exp=time.time() - 10))
check("过期会话 _db_get 仍取得到(由调用方判过期)", pa._db_get(dead) is not None)
after = pa._db_load_all(time.time())
check("过期会话不被预热载入", dead not in after)
pa._db_purge(time.time())
check("过期会话被 _db_purge 清除", pa._db_get(dead) is None)
pa._db_delete(dead)

# --- 6. 滑动续期逻辑（纯内存，不落库） ---
pa._last_persist[sid] = time.time()  # 抑制落盘，保持探针干净
before = pa._SESSIONS[sid]["exp"]
pa._touch(sid, pa._SESSIONS[sid])
after_exp = pa._SESSIONS[sid]["exp"]
check("滑动续期把 exp 往后推", after_exp >= before, (before, after_exp))
pa._last_persist.pop(sid, None)
pa._touch(kid, pa._SESSIONS[kid])
check("常驻会话不参与续期(exp 仍为 0)", pa._SESSIONS[kid]["exp"] == 0.0, pa._SESSIONS[kid]["exp"])

# --- 7. 清理探针 ---
pa._db_delete(sid)
pa._db_delete(kid)
check("探针记录已删除", pa._db_get(sid) is None and pa._db_get(kid) is None)

# --- 8. 上限定界：SESSION_MAX_TTL 生效时的续期封顶 ---
orig_max, orig_slide = pa.SESSION_MAX_TTL, pa.SESSION_SLIDING
try:
    pa.SESSION_MAX_TTL = 100
    pa.SESSION_SLIDING = True
    s2 = {"exp": time.time() + 10, "created": time.time() - 90, "persistent": False}
    pa._last_persist["__x__"] = time.time()
    pa._touch("__x__", s2)
    check("MAX_TTL 封顶生效", s2["exp"] <= time.time() - 90 + 100 + 2, s2["exp"])
finally:
    pa.SESSION_MAX_TTL, pa.SESSION_SLIDING = orig_max, orig_slide

print()
print("=== 结果: %d 项失败 ===" % len(fails))
if fails:
    for f in fails:
        print("  FAIL:", f)
    sys.exit(1)
print("ALL PASS")

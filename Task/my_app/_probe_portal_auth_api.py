# -*- coding: utf-8 -*-
"""portal_auth 接口端到端验证（TestClient，客户端 IP=testclient -> 视为远程）。

覆盖：未登录 401 / 缺 token 400 / 常驻接口关停 404 / 密钥错 403 /
常驻登录 302+落盘 / 带 Cookie 访问 200 / 开放重定向被拦 / 注销后 401。
运行：cwd = my_app 根目录，用系统 Python312。
"""
import os
import sys

sys.path.insert(0, os.getcwd())

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.services import portal_auth as pa  # noqa: E402

fails = []
created_sids = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))
    if not cond:
        fails.append(name)


app = FastAPI()
app.include_router(pa.router)
c = TestClient(app)

print("=== 已注册的 auth 路由 ===")
for r in app.routes:
    p = getattr(r, "path", "")
    if p.startswith("/api/auth"):
        print(" ", sorted(getattr(r, "methods", []) or []), p)
print()

# --- 1. 未登录访问 /me -> 401（客户端非回环） ---
r = c.get("/api/auth/me")
check("未登录 /me -> 401", r.status_code == 401, r.status_code)

# --- 2. 缺 token 的 portal-login -> 400 ---
r = c.post("/api/auth/portal-login", json={})
check("缺 token -> 400", r.status_code == 400, r.text[:80])

# --- 3. 未设置 KIOSK_KEY 时常驻接口应 404（默认关闭，行为不变） ---
orig_key = pa.KIOSK_KEY
try:
    pa.KIOSK_KEY = ""
    r = c.get("/api/auth/kiosk", params={"key": "x"})
    check("未启用常驻 -> 404", r.status_code == 404, r.status_code)
    r = c.post("/api/auth/kiosk-login", json={"key": "x"})
    check("未启用常驻(kiosk-login) -> 404", r.status_code == 404, r.status_code)

    # --- 4. 启用后：密钥错误 -> 403 ---
    pa.KIOSK_KEY = "s3cret-key"
    r = c.get("/api/auth/kiosk", params={"key": "wrong"}, follow_redirects=False)
    check("常驻密钥错 -> 403", r.status_code == 403, r.status_code)

    # --- 5. 正确密钥 -> 302 跳回看板 + 种 Cookie + 落盘 exp=0 ---
    r = c.get(
        "/api/auth/kiosk",
        params={"key": "s3cret-key", "next": "/myapp/?page=sync"},
        follow_redirects=False,
    )
    check("常驻登录 -> 302", r.status_code == 302, r.status_code)
    check("重定向到 next", r.headers.get("location") == "/myapp/?page=sync", r.headers.get("location"))
    sc = r.headers.get("set-cookie", "")
    check("种下会话 Cookie", pa.SESSION_COOKIE in sc, sc[:120])
    check("Cookie 为 HttpOnly", "httponly" in sc.lower(), sc[:160])
    sid = r.cookies.get(pa.SESSION_COOKIE)
    created_sids.append(sid)
    row = pa._db_get(sid) if sid else None
    check("常驻会话已落盘", row is not None, row)
    check("落盘 exp=0（永不过期）", row is not None and row["exp"] == 0.0, row and row["exp"])
    check("落盘 persistent=1", row is not None and row["persistent"] is True, row and row["persistent"])
    check("落盘 username=kiosk", row is not None and row["username"] == "kiosk", row and row["username"])

    # --- 6. 带该 Cookie 访问受保护接口 -> 200 ---
    r = c.get("/api/auth/me")
    check("带常驻 Cookie /me -> 200", r.status_code == 200, r.text[:80])
    check("身份为 kiosk", r.status_code == 200 and r.json().get("user", {}).get("username") == "kiosk", r.text[:120])

    # --- 7. 开放重定向防护：外部 URL 应被丢弃 ---
    r = c.get("/api/auth/kiosk", params={"key": "s3cret-key", "next": "https://evil.example.com"}, follow_redirects=False)
    check("外部 next 被拦回站内", r.headers.get("location") == "/myapp/", r.headers.get("location"))
    created_sids.append(r.cookies.get(pa.SESSION_COOKIE))
    r = c.get("/api/auth/kiosk", params={"key": "s3cret-key", "next": "//evil.example.com"}, follow_redirects=False)
    check("协议相对 next 被拦", r.headers.get("location") == "/myapp/", r.headers.get("location"))
    created_sids.append(r.cookies.get(pa.SESSION_COOKIE))

    # --- 8. 注销后应 401 且「当前」会话落盘被清 ---
    # 注意：上面的两次 kiosk 登录已把 Cookie jar 覆盖成最新 sid，
    # 因此要按客户端当前实际持有的 Cookie 来断言，而不是最早那个 sid。
    current_sid = c.cookies.get(pa.SESSION_COOKIE)
    check("当前 Cookie 已非最早会话（前置条件）", current_sid and current_sid != sid, (current_sid or "")[:12])
    r = c.post("/api/auth/logout")
    check("注销 -> 200", r.status_code == 200, r.status_code)
    check("注销后当前会话落盘已删", pa._db_get(current_sid) is None, pa._db_get(current_sid))
    check("注销不影响其它会话(最早 sid 仍在)", pa._db_get(sid) is not None)
    r = c.get("/api/auth/me")
    check("注销后 /me -> 401", r.status_code == 401, r.status_code)

    # --- 9. kiosk-login（JSON 版）--- 
    r = c.post("/api/auth/kiosk-login", json={"key": "s3cret-key"})
    check("kiosk-login -> 200", r.status_code == 200, r.text[:80])
    created_sids.append(r.cookies.get(pa.SESSION_COOKIE))
finally:
    pa.KIOSK_KEY = orig_key

# --- 清理本次探针产生的会话 ---
for s in created_sids:
    if s:
        with pa._LOCK:
            pa._SESSIONS.pop(s, None)
            pa._last_persist.pop(s, None)
        pa._db_delete(s)
print()
print("已清理探针会话数:", len([s for s in created_sids if s]))
print("=== 结果: %d 项失败 ===" % len(fails))
if fails:
    for f in fails:
        print("  FAIL:", f)
    sys.exit(1)
print("ALL PASS")

# -*- coding: utf-8 -*-
"""用户反馈接口的权限模型回归守卫（2026-11-08）。

背景：修复前 `/api/feedback` 的写接口（PUT 改状态 / DELETE 删记录）**零鉴权**，
列表与统计也不按提交人过滤 —— 任何登录用户（甚至内网未登录访客在开发模式下）
都能改掉别人的反馈状态、删除记录，并读到全部反馈的联系方式邮箱与附件。

本测试锁定的三条性质（纯本地，不连 PG、不发网络请求）：

1. **提交人身份来自会话账号**，不是表单里手填的「反馈人」（后者是自由文本）。
2. **非管理员只看得到自己提交的**：列表 / 统计 / 附件下载都按 `submitter` 收敛。
3. **处理与删除是管理员专属**：非管理员一律 403 —— 前端隐藏按钮不算防线。
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.routers import feedback

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_PAGE = PROJECT_ROOT / "frontend" / "src" / "pages" / "IssueFeedback.tsx"
FEEDBACK_ROUTER = PROJECT_ROOT / "backend" / "routers" / "feedback.py"


class _FakeRequest:
    """最小 Request 替身：只用到 headers（判中英文）与 cookies（用不到）。"""

    def __init__(self, accept_language: str = ""):
        self.headers = {"accept-language": accept_language}
        self.cookies = {}


@pytest.fixture
def as_viewer(monkeypatch):
    monkeypatch.setattr(
        feedback.portal_auth, "current_user",
        lambda request: {"username": "ekoiwu", "role": "viewer"},
    )


@pytest.fixture
def as_admin(monkeypatch):
    monkeypatch.setattr(
        feedback.portal_auth, "current_user",
        lambda request: {"username": "admin", "role": "admin"},
    )


# ============================================================================
# 身份解析
# ============================================================================

def test_actor_takes_username_from_session(as_viewer):
    actor = feedback._actor(_FakeRequest())
    assert actor["username"] == "ekoiwu"
    assert actor["role"] == "viewer"
    assert actor["is_admin"] is False


def test_actor_without_role_is_viewer(monkeypatch):
    """会话里没有角色字段时按普通用户处理（fail-closed）。"""
    monkeypatch.setattr(
        feedback.portal_auth, "current_user",
        lambda request: {"username": "someone"},
    )
    actor = feedback._actor(_FakeRequest())
    assert actor["is_admin"] is False
    assert actor["username"] == "someone"


def test_admin_actor(as_admin):
    actor = feedback._actor(_FakeRequest())
    assert actor["is_admin"] is True


# ============================================================================
# 可见范围：非管理员只看自己提交的
# ============================================================================

def test_visibility_filter_scopes_non_admin(as_viewer):
    scope_sql, params = feedback._visibility_filter(feedback._actor(_FakeRequest()))
    assert scope_sql == "submitter = ?"
    assert params == ["ekoiwu"]


def test_visibility_filter_unfiltered_for_admin(as_admin):
    scope_sql, params = feedback._visibility_filter(feedback._actor(_FakeRequest()))
    assert scope_sql == ""
    assert params == []


# ============================================================================
# 管理类操作：非管理员 403
# ============================================================================

def test_require_admin_blocks_viewer(as_viewer):
    with pytest.raises(HTTPException) as exc:
        feedback._require_admin(_FakeRequest(), "仅管理员可用", "Admin only", "测试操作")
    assert exc.value.status_code == 403
    assert exc.value.detail == "仅管理员可用"


def test_require_admin_english_detail(as_viewer):
    with pytest.raises(HTTPException) as exc:
        feedback._require_admin(
            _FakeRequest(accept_language="en-US,en;q=0.9"), "仅管理员可用", "Admin only", "测试操作"
        )
    assert exc.value.detail == "Admin only"


def test_require_admin_allows_admin(as_admin):
    """管理员不被拦（不抛异常即通过）。"""
    feedback._require_admin(_FakeRequest(), "仅管理员可用", "Admin only", "测试操作")


# ============================================================================
# 表结构：submitter 列存在，且老库能被幂等补列
# ============================================================================

def test_ensure_table_creates_submitter_column():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    feedback._ensure_table(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(issue_reports)").fetchall()]
    assert "submitter" in cols
    conn.close()


def test_ensure_table_migrates_legacy_table_without_submitter():
    """老库（无 submitter 列）首次访问即自动补列，不报「no such column」。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE issue_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter TEXT NOT NULL,
            contact TEXT,
            category TEXT NOT NULL DEFAULT 'other',
            priority TEXT NOT NULL DEFAULT 'medium',
            page TEXT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            attachments TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            handler TEXT,
            resolution TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    feedback._ensure_table(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(issue_reports)").fetchall()]
    assert "submitter" in cols
    # 幂等：再跑一次不报错
    feedback._ensure_table(conn)
    conn.close()


def test_list_scopes_by_submitter_end_to_end_sqlite(monkeypatch):
    """列表 SQL 真的带上 submitter 条件，且只返回本人记录。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    feedback._ensure_table(conn)
    conn.execute(
        "INSERT INTO issue_reports (reporter, contact, submitter, category, priority, page, title,"
        " description, status, created_at, updated_at)"
        " VALUES ('甲', 'a@x', 'ekoiwu', 'bug', 'low', 'p', '我的', 'd1', 'open', '2026-11-08 10:00:00', '2026-11-08 10:00:00')"
    )
    conn.execute(
        "INSERT INTO issue_reports (reporter, contact, submitter, category, priority, page, title,"
        " description, status, created_at, updated_at)"
        " VALUES ('乙', 'b@x', 'other', 'bug', 'low', 'p', '别人的', 'd2', 'open', '2026-11-08 10:00:00', '2026-11-08 10:00:00')"
    )
    conn.commit()

    class _Ctx:
        """get_raw_connection 的替身：上下文管理器 + 同一份 sqlite 连接。"""

        def __enter__(self):
            return conn

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(feedback, "get_raw_connection", lambda: _Ctx())
    monkeypatch.setattr(
        feedback.portal_auth, "current_user",
        lambda request: {"username": "ekoiwu", "role": "viewer"},
    )

    class _Req(_FakeRequest):
        pass

    res = feedback.list_feedback(_Req(), None, None, None, None, 100, 0)
    assert res["total"] == 1
    assert res["items"][0]["title"] == "我的"
    conn.close()


# ============================================================================
# 源码级守卫：后端写接口必须过 _require_admin，前端操作列必须按角色渲染
# ============================================================================

def test_backend_write_endpoints_require_admin():
    """PUT / DELETE 两个处理器都必须先过 _require_admin（静态检查，防后人改回去）。"""
    src = FEEDBACK_ROUTER.read_text(encoding="utf-8")
    for func in ("def update_feedback(", "def delete_feedback("):
        start = src.index(func)
        body = src[start: start + 1200]
        assert "_require_admin(" in body, f"{func} 缺少 _require_admin 调用"


def test_frontend_actions_column_is_admin_only():
    """前端「处理 / 删除」操作列只在管理员下渲染（体验层，后端 403 才是防线）。"""
    src = FEEDBACK_PAGE.read_text(encoding="utf-8")
    assert "if (isAdmin) {" in src
    assert "getBootRole()" in src
    # 管理员才有「操作」列；普通用户页面挂可见范围说明
    assert "fb.scope.myOnly" in src

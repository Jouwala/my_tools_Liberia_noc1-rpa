# -*- coding: utf-8 -*-
"""工程纪律守卫（pytest 用例，无副作用、不连网、不碰生产库）。

把 AGENTS.md 第四节的几条硬性约束变成机器可验证的检查，防止回归。
本文件是**真正的 pytest 用例**（不是 tests/README_tests.md 里那类"手动脚本"），
因此模块级不调用 sys.exit()，可被 `pytest tests/` 正常收集。

覆盖：
  1. routers/ 内禁止裸 sqlite3.connect —— 请求路径必须走 get_raw_connection，
     否则 MY_APP_DB_MODE=pg 下必然失败（AGENTS.md 第六节）。
  2. E9 + F821 必须为零 —— F821 是"未定义名"，也就是必然 NameError。
     2026-09-27 实测曾命中 10 处真实缺陷（ftp_sync / openwebui_client 等），
     修完后钉死，防止再退化。
  3. /docs、/redoc、/openapi.json 默认不得暴露 —— 它们不走 /api/ 前缀，
     因此绕过会话中间件，曾公开泄露 223 条 API 路径的完整清单。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
ROUTERS = BACKEND / "routers"

# 故意保留裸连接的白名单：这些读的是"固定本地快照/侧库"，与 DB_MODE 无关。
# 新增条目必须在注释里写清理由，否则就是绕过守卫。
_SQLITE_ALLOWLIST: dict[str, str] = {}


def _iter_py(root: Path):
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


# ---------------------------------------------------------------- 守卫 1
def test_routers_have_no_bare_sqlite_connect():
    """routers/ 是请求路径，一律走 get_raw_connection。

    裸 sqlite3.connect 绕过 database.py 的 `?`→`%s` 占位符翻译与
    _ClosingConnection 语义，在 MY_APP_DB_MODE=pg 下必然失败。
    （2026-09-27 修复了 routers/gis.py 的最后一处。）
    """
    offenders = []
    for path in _iter_py(ROUTERS):
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "sqlite3.connect(" not in line:
                continue
            if line.lstrip().startswith("#"):
                continue  # 注释里提到不算
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            if rel in _SQLITE_ALLOWLIST:
                continue
            offenders.append(f"{rel}:{i}: {line.strip()}")

    assert not offenders, (
        "routers/ 内出现裸 sqlite3.connect（必须改用 get_raw_connection）：\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------- 守卫 2
@pytest.mark.parametrize("rule", ["E9", "F821"])
def test_ruff_critical_rules_are_clean(rule: str):
    """E9（语法/运行时错误）与 F821（未定义名）必须为零。

    F821 不是风格问题 —— 它等价于"这行一旦执行就是 NameError"。
    """
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "backend",
         "--select", rule, "--output-format", "concise"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    if proc.returncode == 2 and "No module named ruff" in (proc.stderr or ""):
        pytest.skip("ruff 未安装（pip install -r requirements.txt 后生效）")
    assert proc.returncode == 0, (
        f"ruff --select {rule} 发现违规（必须修完）：\n{proc.stdout}"
    )


# ---------------------------------------------------------------- 守卫 3
def test_docs_are_opt_in_not_opt_out():
    """`MY_APP_ENABLE_DOCS` 必须是**显式开关**，且默认值为 "0"。

    这三条路径由 FastAPI 内建，**不带 /api/ 前缀**，因此
    require_session_middleware 的 `if not path.startswith("/api/")` 分支会放行，
    _PUBLIC_API 白名单也管不到。实测曾匿名返回 189KB / 223 条 API 路径。

    ⚠️ 这里刻意**不**断言"运行时一定看不到 /docs" —— 因为本机
    `backend/.env` 出于内网调试需要**显式置了 `MY_APP_ENABLE_DOCS=1`**
    （用户 2026-09-27 确认需要 Swagger）。那时再看运行时路由必然看到 /docs，
    断言"不得出现"会误报。真正要钉死的是**代码里的默认值**：
    没有显式配置时必须是关的，否则换台机器/新部署就会静默裸奔。

    另注：不能靠"删掉环境变量再看结果"来测默认值 ——
    `database.py:19` 在 import 期会 `load_dotenv()` 把 `.env` 里显式写的值
    重新读回来，删不掉。所以改为直接读源码里的默认字面量。
    """
    src = (BACKEND / "main.py").read_text(encoding="utf-8", errors="replace")
    m = re.search(
        r"""_ENABLE_DOCS\s*=\s*os\.environ\.get\(\s*["']MY_APP_ENABLE_DOCS["']\s*,\s*["']([^"']*)["']""",
        src,
    )
    assert m, (
        "main.py 里找不到 MY_APP_ENABLE_DOCS 的默认值定义；"
        "请确认 docs 开关仍是显式 opt-in（形如 "
        "os.environ.get(\"MY_APP_ENABLE_DOCS\", \"0\") == \"1\"）"
    )
    assert m.group(1) == "0", (
        f"MY_APP_ENABLE_DOCS 的默认值被改成了 {m.group(1)!r}，必须保持 '0'（默认关闭）。"
        " 否则任何未显式配置的部署都会匿名暴露 /openapi.json（223 条 API 路径）。"
    )

    # 同时确认三条路由确实受该开关控制（而不是写死开启）
    for kw in ("docs_url", "redoc_url", "openapi_url"):
        assert re.search(rf"{kw}\s*=\s*[^,\n]*_ENABLE_DOCS", src), (
            f"main.py 的 FastAPI(...) 未用 _ENABLE_DOCS 控制 {kw}"
        )


# ---------------------------------------------------------------- 守卫 5
def test_task_db_modules_are_all_redirected_by_the_test_fixture():
    """`test_task_runner.py` 的 tmp_db fixture 必须覆盖它实际用到的每个 DB_PATH 副本。

    背景（2026-09-27 实际踩到）：`task_stats.py:14` 用的是
    `from backend.database import DB_PATH` —— 导入即绑定成**独立引用**。
    于是只 patch `task_runner.DB_PATH` 时，统计/历史查询仍指向**真的
    db/app.db**：断言 `len(rows)==2` 实测得到 6/7，而且测试持续往生产库写
    脏数据（事后从中清出 71 行 `__t_*` 残留）。

    全仓共 11 个模块持有 DB_PATH 副本（含 8 个 routers），但**只有
    task_runner / task_stats 被这组测试真正调用**，所以只钉住这两个 ——
    守卫要的是"测试不会静默打到生产库"，不是"禁止 import DB_PATH"。

    新增 `from backend.database import DB_PATH` 的**任务执行链**模块时，
    本用例会失败，提示你去 fixture 里补 monkeypatch。
    """
    fixture = (PROJECT_ROOT / "tests" / "test_task_runner.py").read_text(
        encoding="utf-8", errors="replace"
    )
    # 这两个模块被 test_task_runner 直接或间接调用，必须都被重定向
    must_redirect = {
        "backend/services/task_runner.py": "tr",
        "backend/services/task_stats.py": "_ts",
    }
    missing = []
    for rel, alias in must_redirect.items():
        src = (PROJECT_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if not re.search(r"^from backend\.database import.*\bDB_PATH\b", src, re.M):
            continue  # 该模块不再持有副本，无需重定向
        if f'monkeypatch.setattr({alias}, "DB_PATH"' not in fixture:
            missing.append(f"{rel}（fixture 里缺少 monkeypatch.setattr({alias}, \"DB_PATH\", p)）")

    assert not missing, (
        "以下模块持有 DB_PATH 副本，但 tests/test_task_runner.py 的 fixture "
        "没有把它重定向到临时库 —— 测试会连上生产 db/app.db：\n  "
        + "\n  ".join(missing)
    )


# ---------------------------------------------------------------- 守卫 4
def test_swallow_helper_exists_and_is_importable():
    """统一吞异常入口必须可用（AGENTS.md 第四节第 2 条）。

    目的：让"吞异常"从散落的隐式行为变成显式、带上下文的契约。
    """
    try:
        from backend.services import silent_except  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"backend.services.silent_except 不可导入: {exc!r}")


# ---------------------------------------------------------------- 守卫 6
# 唯一的合法例外：credential_store.py 是**中央凭据库**，它的 CREDENTIAL_GROUPS
# 里存的就是各组默认口令，这正是"单一真相源"本身。owa_credentials.py 是另一处
# 刻意保留的最后兜底（其 docstring 记录了 2026-09-18 的 65 小时邮件故障，
# 且 _LEGACY_DEFAULTS 依赖该字面量的**值**来识别"调用方传了历史旧口令"）。
_SECRET_LITERAL_EXEMPT: dict[str, str] = {
    "backend/services/credential_store.py":
        "中央凭据库，CREDENTIAL_GROUPS 的默认值就是唯一真相源",
    "email_reports/owa_credentials.py":
        "刻意的最后兜底（env > credential_store > 此处），并被 _LEGACY_DEFAULTS 依赖",
}

# 历史上出现在本仓库源码里的真实口令/凭据字面量（2026-09-27 全仓清理）。
# 只要它们再次出现在**非豁免**的源码里，就说明有人把明文写回来了。
_KNOWN_SECRETS = (
    "Zte@2025!",
    "Zte@202608",
    "Zte_ZM2028",
    "Mwebazeaaron@25",
    "Zte@lbr202607",
    "Zte@orange123!",
    "LQcTaMMuWmhvAfRB",
    "UbuntU1!2@3#4$",
    "Postcode@202608",
    "Tool123",
    "f9cf7778112f486ab618d153456e2553",
    "SCT389311TrwFJS9k0ZxfX5Plb9g0gozix",
)

# 只扫"会进版本库的源码"，跳过虚拟环境/产物/运行时目录
_SCAN_SKIP_DIRS = {
    "Lib", "Scripts", "include", ".venv", "TMP", "node_modules",
    "_fe_dist", "_fe_dist_tmp", "log", "db", "auth_cache", "__pycache__",
    ".workbuddy", ".git",
}
_SCAN_SUFFIXES = {".py", ".ps1", ".bat", ".json", ".ts", ".tsx", ".js", ".mjs"}


def test_no_hardcoded_secrets_in_source():
    """源码里不得再出现明文口令/凭据字面量（AGENTS.md 第四节第 2 条）。

    背景（2026-09-27 清理）：同一个口令在 30+ 个文件里各存一份副本，既是重复真相源，
    也让口令明文进了版本库。根因是 `credential_store.get_credential()` 从不回退到
    凭据组自己的 default_user/default_secret，调用方只能各自传字面量兜底
    （已修复：见 credential_store.py 的 get_credential）。

    本用例只做"字面量黑名单"这一件确定的事：
      * 命中即失败，并指出文件:行号；
      * 豁免文件必须在 _SECRET_LITERAL_EXEMPT 里写明理由。

    注意：**这些口令已经进入 git 历史**，删源码不等于失效 —— 必须轮换才能根治。
    本守卫只能防止"再写回去"，不能替代轮换。
    """
    offenders: list[str] = []
    self_rel = Path(__file__).resolve().relative_to(PROJECT_ROOT).as_posix()
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
            continue
        if any(part in _SCAN_SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if rel in _SECRET_LITERAL_EXEMPT:
            continue
        # 本文件自身持有黑名单（_KNOWN_SECRETS），跳过以免自证其罪
        if rel == self_rel:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            # 注释/文档串里说明"某处曾经硬编码过 X"不算泄露，且是有价值的上下文
            if stripped.startswith("#") or stripped.startswith("*"):
                continue
            for secret in _KNOWN_SECRETS:
                if secret in line:
                    offenders.append(f"{rel}:{i}: 含明文凭据 {secret[:6]}…")

    assert not offenders, (
        "源码里出现明文口令/凭据（必须改用 credential_store.get_credential(key)）：\n  "
        + "\n  ".join(offenders)
        + "\n\n若确属刻意的兜底设计，请连同理由加入 _SECRET_LITERAL_EXEMPT。"
        "\n⚠ 这些值已在 git 历史中，删除源码后仍需**轮换口令**才算真正消除。"
    )


# ---------------------------------------------------------------- 守卫 7
def test_mirror_failure_is_surfaced_as_warning():
    """镜像写失败必须进 warnings，否则监控全绿而看板静默停更。

    背景（2026-09-27 实测）：`sp_data_sync` 的 app.db 落库成功、镜像写
    FineBI `inventory.db` 长期失败（14 天内 76 次执行、75 次失败，起于
    2026-09-24）。但任务告警只在 `success=False` 时触发
    （task_runner.py 的 `if not result["success"]` 分支），而 result["success"]
    恒为 True —— 于是「看板数据不更新」这件事在**任何监控上都不可见**。

    这个守卫钉住两件事：
      1. get_sp_table 在 mirror 失败时确实追加 warnings；
      2. task_runner 在 success=True 时也会消费 warnings 触发降级告警。
    任何一侧被删掉，都会退回"静默失败"。
    """
    sp = (BACKEND / "services" / "get_sp_table.py").read_text(encoding="utf-8", errors="replace")
    runner = (BACKEND / "services" / "task_runner.py").read_text(encoding="utf-8", errors="replace")

    assert 'result.setdefault("warnings", []).append(' in sp, (
        "get_sp_table.py 不再把镜像失败写进 result['warnings'] —— "
        "镜像失败会退回静默（看板停更而监控全绿）"
    )
    assert '"mirror_success"] = False' in sp or "'mirror_success'] = False" in sp, (
        "get_sp_table.py 不再标记 mirror_success=False"
    )
    # task_runner 必须在 success 分支（而非仅失败分支）里读 warnings
    assert re.search(r'if result\["success"\]:\s*\n\s*_warns\s*=', runner), (
        "task_runner.py 不再在 success=True 时读取 warnings —— 降级告警失效，"
        "sp_data_sync 的镜像失败将不再产生任何通知"
    )

    # 2026-09-28：mirror_errs 的遍历必须跳过非表条目。_mirror_write_all 的返回值里
    # 混着 _meta/_retention（dict）与 _diagnosis（**字符串**），对后者取 .get 会抛
    # AttributeError，被外层 try 包装成"SFTP 连接/同步失败"，既谎报了故障面
    # （SFTP 其实一直是好的），又让整轮重试 3 次（534s → 1576s），
    # 还使上面刚加的降级告警永远走不到。
    assert re.search(r'mirror_errs = \[t for t, v in mirror_res\.items\(\)\s*\n\s*'
                     r'if not t\.startswith\("_"\)\s*\n\s*and isinstance\(v, dict\)', sp), (
        "get_sp_table.py 的 mirror_errs 又变成遍历返回值的全部键了 —— "
        "镜像失败时会抛 'str' object has no attribute 'get'，并被误报成 SFTP 故障"
    )


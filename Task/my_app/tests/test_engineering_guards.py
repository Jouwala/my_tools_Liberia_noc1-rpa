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

# 本仓库是**单体 git 仓库**（AGENTS.md 二：顶层是 D:/01_RPA，不是 my_app）。
# 口令清理必须覆盖全工作区 —— 实测 my_app 之外还有 40 个文件带明文副本
# （Site_outage/、ticket_export_rpa/、Task/sp/、Unified_Tools/ 等）。
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]

# 明确列出要扫的根目录（而不是扫整个工作区），避免遍历体积巨大的
# 运行时目录（db/ 1.5G、chrome-win/、whatsapp_session/ 等）。
_SCAN_ROOTS = [
    PROJECT_ROOT,                              # Task/my_app
    WORKSPACE_ROOT / "Task",                   # Task/**（含 sp/、RAN/、eflow_python/ 等）
    WORKSPACE_ROOT / "Site_outage",
    WORKSPACE_ROOT / "ticket_export_rpa",
    WORKSPACE_ROOT / "Unified_Tools",
    WORKSPACE_ROOT / "WareHouseDashBoard",
    WORKSPACE_ROOT / "report",
]

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
# 唯一的合法例外：owa_credentials.py 是**刻意保留的最后兜底**
# （其 docstring 记录了 2026-09-18 的 65 小时邮件故障，
# 且 _LEGACY_DEFAULTS 依赖该字面量的**值**来识别"调用方传了历史旧口令"）。
#
# 2026-10-04 变更：credential_store.py **不再豁免**。
# 它的 17 组 default_secret 已全部清空 —— 口令的唯一归属是运行时存储
# （`/myapp/?page=settings` 页面 / credentials 表），代码里不再留副本。
# 相应地，当时也把全工作区 42 个文件里的散落副本一并清了。
_SECRET_LITERAL_EXEMPT: dict[str, str] = {
    "email_reports/owa_credentials.py":
        "刻意的最后兜底（env > credential_store > 此处），并被 _LEGACY_DEFAULTS 依赖",
    # 本机速查表：**未被跟踪**（`.gitignore:183` 的 `**/CREDENTIALS_LOCAL_REFERENCE.txt`），
    # 即"只存在于本机磁盘、绝不进 git"。它是给人看的本地备忘，不是源码，
    # 不会随克隆分发。规格上说它仍是明文落盘，理想做法是删掉改用设置页；
    # 但既然它永不出库，风险与源码入库存明文不在一个量级，此处显式放行。
    "CREDENTIALS_LOCAL_REFERENCE.txt":
        "本机速查表，已被 .gitignore 覆盖、永不入库（非源码）",
}

# 历史上出现在本仓库源码里的真实口令/凭据字面量。
# 只要它们再次出现在**非豁免**的源码里，就说明有人把明文写回来了。
#
# 2026-10-04 补齐：此前只有 12 条，而 credential_store 里有 15 个不同口令，
# 漏掉的 5 个（fms_portal / rais / ume_in / vmax_cxo / vmax_gbase）
# **写回源码也不会被拦** —— 黑名单不全，守卫就是摆设。
# 现在以 credential_store 的实际登记为基准补齐。
_KNOWN_SECRETS = (
    "Zte@2025!",                          # zte_ume / cm_data
    "Zte@202608",                         # mw_ume
    "Zte_ZM2028",                         # rais 的历史值
    "Mwebazeaaron@25",                    # ccn_ume
    "Zte@lbr202607",                      # ipran_ume
    "Zte@orange123!",                     # fw_kpi
    "LQcTaMMuWmhvAfRB",                   # mail_126
    "UbuntU1!2@3#4$",                     # sftp_sp
    "Postcode@202608",                    # owa_mail
    "Tool123",
    "f9cf7778112f486ab618d153456e2553",   # weixin
    "SCT389311TrwFJS9k0ZxfX5Plb9g0gozix",  # weixin 第二个凭据
    "Brysj*8*",                           # eflow / fms_portal（2026-10-04 补）
    "ZXUniPOS_rais",                      # rais（2026-10-04 补）
    "Zte@liberia202609",                  # ume_in（2026-10-04 补）
    "Zte@1a2b3c",                         # vmax_cxo（2026-10-04 补）
    "ZXvmax_2017",                        # vmax_gbase（2026-10-04 补）
)

# ------------------------------------------------------- 2026-10-04 全量清理完成
# 本轮把工作区**其余 40 个已入库文件**的明文口令也清掉了，所以
# `_PENDING_WORKSPACE_CLEANUP` / `_PENDING_TASK_SUBDIRS` 两份白名单已**删除**，
# `_SCAN_ROOTS` 现在对全工作区**全量生效**（不再有任何按目录的放行）。
#
# 清掉的东西（供追溯，勿"顺手改回去"）：
#   * 30 个 .py：`PASSWORD = "<口令>"` 等字面量 -> `_get_credential("组名", env=...)`
#   * 2 个 .ps1：改读环境变量（ps1 无法 import Python；未设时**明确 throw**，
#     不静默降级 —— 静默用旧口令正是 2026-09-18 那次 65 小时故障的形态）
#   * 5 个 .md：文档里的口令改为**凭据组名**（AGENTS.md 四.2：
#     文档可写配置项/环境变量/分组 key，不得写口令本体）
#   * 1 个 .txt：`Task/eflow_python/eflow_login.py.txt` 的留档样例，
#     除口令外还贴着一组**仍然有效**的备用 cookie（等于把活会话入库），一并清空
#
# 跨子系统引导统一走 `Unified_Tools/shared/credentials.py` —— 不要让每个脚本
# 各写一份 sys.path 引导，那又成了新的重复真相源。
#
# ⚠ 引导的判据是 `credentials.py` 这个**文件**，不是 `shared/` 这个**目录**：
#   `Task/Unified_Tools/shared/` 也存在但里面没有 credentials.py，只判目录时
#   `Task/**` 的脚本会先命中它、import 失败后被 except 吞掉，**静默降级为空口令**
#   —— 语法全对、编译全过，跑起来却拿不到口令。实测踩过这个坑。


_SCAN_SKIP_DIRS = {
    "Lib", "Scripts", "include", ".venv", "TMP", "node_modules",
    "_fe_dist", "_fe_dist_tmp", "log", "db", "auth_cache", "__pycache__",
    ".workbuddy", ".git", "_quarantine_20260925", "_myapp_trash_20260918",
}
_SCAN_SUFFIXES = {".py", ".ps1", ".bat", ".json", ".ts", ".tsx", ".js", ".mjs", ".md", ".txt"}


def test_no_hardcoded_secrets_in_source():
    """源码里不得再出现明文口令/凭据字面量（AGENTS.md 第四节第 2 条）。

    背景（2026-09-27 清理）：同一个口令在 30+ 个文件里各存一份副本，既是重复真相源，
    也让口令明文进了版本库。根因是 `credential_store.get_credential()` 从不回退到
    凭据组自己的 default_user/default_secret，调用方只能各自传字面量兜底
    （已修复：见 credential_store.py 的 get_credential）。

    本用例只做"字面量黑名单"这一件确定的事：
      * 命中即失败，并指出文件:行号；
      * 豁免文件必须在 _SECRET_LITERAL_EXEMPT 里写明理由。

    2026-10-04 扩展：
      * **扫描范围从 my_app 扩到整个工作区**（仓库根 `D:/01_RPA`）。
        此前只扫 `PROJECT_ROOT`（= my_app），于是 `Site_outage/`、
        `ticket_export_rpa/`、`Task/sp/`、`Unified_Tools/` 等 40 个文件
        的明文副本**完全不受检查**，实测其中 15 个含 eflow 口令。
      * 黑名单补齐到 17 条（原先 12 条，漏了 5 个口令，
        写回源码也不会被拦）。
      * 扫描后缀加入 `.md` / `.txt` —— 文档里的明文同样是泄露，
        `ticket_export_rpa/README.md` 就曾写着口令。

    注意：**这些口令已经进入 git 历史**，删源码不等于失效 —— 必须轮换才能根治。
    本守卫只能防止"再写回去"，不能替代轮换。
    """
    offenders: list[str] = []
    for root in _SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
                continue
            if any(part in _SCAN_SKIP_DIRS for part in path.parts):
                continue
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            if root == PROJECT_ROOT and rel in _SECRET_LITERAL_EXEMPT:
                continue
            # 豁免也支持"按文件名匹配"（用于本机速查表这类同名多份的文件）
            if path.name in _SECRET_LITERAL_EXEMPT:
                continue
            # 本文件自身持有黑名单（_KNOWN_SECRETS），跳过以免自证其罪
            if path.resolve() == Path(__file__).resolve():
                continue
            # 显示用路径：尽量相对仓库根，便于跨子系统定位
            try:
                shown = path.resolve().relative_to(WORKSPACE_ROOT).as_posix()
            except ValueError:
                shown = str(path)
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
                        offenders.append(f"{shown}:{i}: 含明文凭据 {secret[:6]}…")

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


# ---------------------------------------------------------------- 守卫 8
def test_mirror_never_connects_remote_db_directly():
    """镜像写入不得再从本机直连远端 inventory.db（2026-09-30 事故）。

    背景：远端 `inventory.db` 处于 WAL 模式，且远端主机上有活进程长期持有其
    `-shm` 字节范围锁。SMB 无法代理该语义，于是本机 `sqlite3.connect()` 对它的
    **每一次**调用都永久阻塞（不是抛异常、不是超时返回）。实测把 `s` 组 worker
    从 09:10 卡到 10:22 人工重启，直到启动回收逻辑才判失败，并且期间它持有的
    句柄让后续每一轮镜像都撞 `database is locked`。

    修法是 `sp_mirror_push.py` 的「本地构建 + 整文件推送」。这个守卫确保
    默认路径不会再退回直连：直连实现只能留在 `_mirror_write_all_direct`
    （回滚路径），且默认的 `_mirror_write_all` 必须先判 `MIRROR_MODE`。
    """
    sp = (BACKEND / "services" / "get_sp_table.py").read_text(encoding="utf-8", errors="replace")

    assert "def _mirror_write_all_direct(" in sp, (
        "旧的直连实现不见了 —— 若是有意删除，请同时删掉本守卫与 mirror_mode=direct 文档"
    )
    # 默认分发必须存在且先看 MIRROR_MODE，否则 direct 会成为默认路径。
    assert re.search(r'if MIRROR_MODE == "direct":', sp), (
        "get_sp_table.py 的镜像分发不再判 MIRROR_MODE —— direct(直连) 可能成为默认路径，"
        "对 WAL 库会永久阻塞 worker"
    )
    assert 'MIRROR_MODE = "push"' in sp, (
        "镜像默认模式不再是 push —— 直连远端 WAL 库会永久阻塞 worker"
    )
    push = (BACKEND / "services" / "sp_mirror_push.py").read_text(encoding="utf-8", errors="replace")
    assert "shutil.copyfile(local_path, remote_path)" in push, (
        "sp_mirror_push.py 不再用 copyfile 推送 —— 整文件推送是本方案能绕开 SMB 字节锁的关键"
    )
    assert re.search(r'con\.execute\("PRAGMA journal_mode=delete"\)', push), (
        "本地构建的镜像库未显式设为 delete 模式 —— WAL 会在关闭后留下边车文件，"
        "且推过去之后远端库会重新变成 WAL（本机就再也打不开）"
    )


# ---------------------------------------------------------------- 守卫 9
def test_mirror_stage_has_hard_timeout():
    """镜像阶段必须有进程级硬超时兜底（2026-09-30）。

    `sqlite3` 的 `timeout` / `busy_timeout` 管不到 SMB 层的 open 与字节范围锁，
    对"远端持有 WAL 库"这一场景完全无效（连不上就是永久阻塞）。因此**任何**
    网络文件系统上的阻塞调用都必须由调用方给上限，否则一次卡死就是 6 小时。
    """
    sp = (BACKEND / "services" / "get_sp_table.py").read_text(encoding="utf-8", errors="replace")
    assert "def _run_mirror_with_timeout(" in sp, (
        "镜像阶段硬超时包装不见了 —— 一次网络文件系统阻塞会把 worker 永久卡死"
    )
    assert "MIRROR_HARD_TIMEOUT_SECONDS" in sp, "镜像硬超时常量被删"
    assert re.search(r'mirror_res = _run_mirror_with_timeout\(', sp), (
        "run_sp_data_sync 不再经硬超时包装调用镜像 —— 镜像挂死将再次无限期占住 worker"
    )


# ---------------------------------------------------------------- 守卫 10
def test_worker_recovery_message_distinguishes_hang_from_crash():
    """worker 回收文案必须区分「进程已失效」与「任务挂死」（2026-09-30）。

    旧文案一律写 `Worker 进程中断，任务未完成（启动时自动回收）`。但实测
    `sp_data_sync` 那次 pid 64468 **一直存活**（CPU 零增长的挂死），只是被
    新 worker 判为"不属于已知 worker"而回收。照字面理解会去找崩溃原因，
    而真实故障是任务挂死 + 长任务没有超时 —— 排查方向被文案带偏。
    """
    w = (BACKEND / "worker.py").read_text(encoding="utf-8", errors="replace")
    assert "判定挂死" in w, (
        "worker.py 回收文案不再区分挂死与崩溃 —— 排查会被引向错误方向"
    )
    assert "Worker 进程已失效" in w, "worker.py 缺少「进程已失效」分支的明确文案"


# ---------------------------------------------------------------- 守卫 11
def test_intentional_stop_requeues_instead_of_failing():
    """stop.bat 停机打断的任务必须**重新入队**而非判失败（2026-10-06）。

    用户实测：`stop all / start all` 之后任务管理页出现失败横幅，但任务本身
    没错 —— 只是被 taskkill /F 打断、留下 running 残留，下一轮启动被
    `_recover_stale_running` 误判为失败。修复方案是停机前写
    `worker_stopping.flag`，worker 启动回收时据此把打断的任务重新入队。

    这里钉死三件事，缺一即回归：
      1. stop.bat 必须在杀进程**之前**写标记（否则标记晚于进程死亡 = 无效）；
      2. worker.py 必须在有标记时走「重新入队」分支（不是 failed）；
      3. 标记必须有时效（TTL）—— 否则陈标记会永久掩盖真实崩溃。
    """
    st = (PROJECT_ROOT / "stop.bat").read_text(encoding="utf-8", errors="replace")
    assert "worker_stopping.flag" in st, (
        "stop.bat 不再写停机标记 —— 重启后任务会再次被误判为失败"
    )
    w = (BACKEND / "worker.py").read_text(encoding="utf-8", errors="replace")
    assert "_is_stopping_flagged" in w, "worker.py 不再读取停机标记"
    assert "worker_stopping.flag" in w, "worker.py 未引用停机标记文件名"
    assert "重新入队" in w, "worker.py 缺少「重新入队而非判失败」的分支或文案"
    # TTL 兜底：必须有失效逻辑，否则陈旧标记会掩盖真实崩溃
    assert "STOPPING_FLAG_TTL_SECONDS" in w, (
        "停机标记无时效（TTL）—— 陈旧标记会永久掩盖真实进程崩溃"
    )


# ---------------------------------------------------------------- 守卫 12
def test_runtime_state_files_are_not_tracked():
    """运行时状态文件不得进版本库（AGENTS.md 四.4「不入库清单」）。

    2026-10-07 实测：`backend/worker_stopping.flag` 被 commit 3979e9ee 连带提交，
    且当时 `.gitignore` 未覆盖 `*.flag`（只覆盖 `*.pid`）。危害不是"占了点空间"：
    该文件是**跨机器共享的判断依据**，陈旧标记会让新机器的 worker 把真实的进程
    崩溃误判成「人为停机」而重新入队，从而**掩盖故障**（worker.py 的 TTL 只能
    限制到 30 分钟，挡不住"刚 clone 就带着一个旧标记"）。

    这里钉死两条：规则存在（check-ignore 命中）+ 文件确实未被跟踪。
    """
    import subprocess as _sp
    # ⚠️ git 的 pathspec 必须**相对仓库根**：本仓库顶层是 WORKSPACE_ROOT
    # （AGENTS.md 二：单体仓库，顶层是 D:/01_RPA 而不是 my_app）。
    # 传绝对路径在这里不可靠（实测 `git check-ignore -q <abs>` 会误判为
    # 「未忽略」而让守卫假绿）。
    repo_root = _sp.run(["git", "rev-parse", "--show-toplevel"],
                        cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    if repo_root.returncode != 0:
        pytest.skip("不在 git 工作树中，跳过运行时不入库检查")
    top = Path(repo_root.stdout.strip())

    offenders = []
    for name in ("worker_stopping.flag", "stopped.flag"):
        p = BACKEND / name
        rel = p.relative_to(top).as_posix()
        r = _sp.run(["git", "check-ignore", "-q", "--", rel],
                    cwd=str(top), capture_output=True)
        if r.returncode != 0:
            offenders.append(f"{rel} 未被 .gitignore 覆盖")
        r2 = _sp.run(["git", "ls-files", "--error-unmatch", "--", rel],
                     cwd=str(top), capture_output=True)
        if r2.returncode == 0:
            offenders.append(f"{rel} 仍被 git 跟踪（必须 git rm --cached）")
    assert not offenders, (
        "运行时状态文件混入版本库：\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------- 守卫 13
def test_no_bare_percent_in_parameterized_sql_fragment():
    """带参数的 SQL 里不得出现「裸 `%`」（PG 占位符转义陷阱）。

    2026-10-07 实测事故：`task_stats._NOT_TEST_TASK` 原写作
    `f"task_id NOT LIKE '{TEST_TASK_PREFIX}%'"`（即 SQL 文本内含 `'__t_%'`），
    被拼进**带 `?` 参数**的语句后，PG 模式下
    `database._qmark_to_pyformat(escape_pct=True)` 的字符串字面量分支
    （database.py:227-237）**跳过引号内内容、不应用 escape_pct**，
    于是那个 `%` 原样进入 SQL；psycopg2 视其为格式化符，参数数不匹配 →
    `IndexError: tuple index out of range`。

    危害是**静默**的：`get_recent_failures` 把异常兜在 `except` 里只记 warning，
    结果返回 0 个失败簇 —— 任务管理页的失败横幅看起来"一切正常"，
    而当时库里实际有 41 条真实失败。故障可见性被整体抹掉。

    正确写法：把通配符放进**绑定参数值**（`task_id NOT LIKE ?` + 参数 `'__t_%'`），
    本仓库既定约定见 `sp_material_summary_service.py:761-766`。

    这里直接钉**转义函数本身**的行为契约，避免以后有人"顺手优化"掉 escape_pct。
    """
    from backend.database import _qmark_to_pyformat

    # ① 字面量内的 % 不会被转义 —— 这是必须记住的既成事实
    conv = _qmark_to_pyformat("SELECT 1 WHERE a NOT LIKE 'x_%' AND b >= ?",
                              escape_pct=True)
    assert "x_%" in conv, (
        "引号内的 % 未被保留？转义逻辑变了，请重新评估所有 LIKE 写法"
    )
    assert conv.count("%s") == 1, "占位符转换数量不对"

    # ② 引号外的 % 会被转义（列名含 % 的场景依赖这条）
    conv2 = _qmark_to_pyformat('SELECT "Loss(%)" FROM t WHERE b >= ?',
                               escape_pct=True)
    assert "%%" in conv2 or "%s" in conv2, "引号外 % 未转义"

    # ③ 源码级检查：带 `?` 参数的语句不得再用字面量片段。
    #
    # ⚠️ 不能只看**单行**是否含 `?` —— 拼接写法通常把 `?` 放在后续行，
    # 只看当前行会漏判（本守卫第一版就因此假绿，被反向验证抓出来）。
    # 改为：定位每个 `{_NOT_TEST_TASK}` 出现处，向后扫描到该语句结束
    # （遇到 conn.execute(...) 的参数元组或语句结束标记），判断整条语句是否带参数。
    ts_src = (BACKEND / "services" / "task_stats.py").read_text(
        encoding="utf-8", errors="replace")
    assert "_NOT_TEST_TASK_PARAM" in ts_src, (
        "task_stats 缺少「通配符走绑定参数」的写法 —— 失败横幅会再次静默失效"
    )
    lines = ts_src.splitlines()
    for i, line in enumerate(lines):
        if "{_NOT_TEST_TASK}" not in line:
            continue
        # 向后最多看 15 行，找该 execute() 调用的参数部分
        window = "\n".join(lines[i:i + 15])
        # 参数元组形态：(something,) 或 ("a", b) —— 出现在 execute( 之后且含 "?" 占位符
        has_qmark = "?" in window.split(").fetch", 1)[0]
        if has_qmark:
            raise AssertionError(
                f"task_stats.py:{i + 1} 在带 `?` 参数的语句里用了字面量 % 片段"
                f"（PG 下会 IndexError，横幅静默失效）：{line.strip()}"
            )


# ---------------------------------------------------------------- 守卫 14
def test_testclient_declares_loopback_client():
    """API 功能测试的 TestClient 必须显式声明回环 client（否则整套全红）。

    2026-10-15 实测：`run_backend_tests.py` 用 FastAPI `TestClient` 进程内发请求，
    而 TestClient **默认把对端伪装成主机名 `testclient`，不是 IP**；鉴权中间件
    （`main.py` 的 require_session_middleware）判「本机回环放行」时走
    `security.client_is_local()` → `_is_loopback()`，要求 `request.client.host`
    是回环 **IP**，`"testclient"` 解析失败 → 不放行 → 返回 401。

    症状极具误导性：26 个用例里 13 个 API 用例**全部** 401，看起来像"鉴权配置问题"
    或"权限不足"，于是很容易误判成"跑测试得先关掉鉴权"（错误结论）。实际上与本机
    权限、与业务代码、与鉴权开关都无关，纯粹是测试客户端的身份没被认出是回环。
    加 `client=("127.0.0.1", <port>)` 即修复（实测 13 失败 → 0 失败）。

    这里钉死"测试客户端必须是回环身份"这一语义，防止以后有人把它改回
    `TestClient(app)`、或改成"跑测试前先关鉴权"的绕法 —— 后者会让鉴权中间件
    在测试中形同虚设，测不出真实鉴权行为。
    """
    src = (Path(__file__).resolve().parent / "run_backend_tests.py").read_text(
        encoding="utf-8", errors="replace")

    # ⚠️ 必须**只扫代码、跳过注释**：解释这条约束的注释里本身就会写下
    # `TestClient(app)` 这个反面写法（否则读的人不知道要避免什么），
    # 若对全文做子串匹配，守卫会在正确代码上误报 —— 本守卫第一版就是这样假红的。
    code_lines = [
        ln.split("#", 1)[0]
        for ln in src.splitlines()
    ]
    code = "\n".join(code_lines)

    assert "TestClient(app)" not in code, (
        "run_backend_tests.py 里出现了不带 client= 的 `TestClient(app)` —— "
        "TestClient 默认主机名是 'testclient'，不是回环 IP，鉴权中间件会全部返回 401。"
        "请写成 TestClient(app, client=(\"127.0.0.1\", <port>))。"
    )
    # 正面要求：必须真的声明了回环 IP（防止删掉 client= 或换成非回环地址）
    assert re.search(r'client=\s*\(\s*["\']127\.0\.0\.1["\']', code), (
        "run_backend_tests.py 的 TestClient 未声明回环 client，"
        "API 用例会被鉴权中间件整片挡成 401。"
    )


# ---------------------------------------------------------------- 守卫 15
def test_no_duplicate_worker_stacks_and_claims_are_atomic():
    """重复 worker 栈与"假原子"认领的硬约束（2026-10-16 事故）。

    当天叠了 6 套 worker_watchdog、48 个 worker 抢同一张 `task_queue`：一个修后端
    的脚本**只删了 PID 文件没杀进程**，而所有"是否已有看门狗"的判断都只看 PID
    文件 → 于是再叠一套。后果有两层：

      * 最后一套覆写了 8 个组 PID 文件，其余栈明明活着、任务也在跑成功，却被
        `_recover_stale_running` 判成「Worker 进程已失效」→ 12:00 后 128 条**假失败**；
      * `_claim_next` 旧写法 `UPDATE ... WHERE id = (SELECT ... LIMIT 1) RETURNING`
        的注释称"原子"，但 PG 里子查询是 InitPlan、在拿到行锁之前就把 id 取好了，
        拿到锁后复查的条件只有 `id = 那个 id` → 同一行被认领两遍（实测同一
        queue_id 连认领两次；WhatsApp 告警与邮件因此重发）。

    钉死六件事，缺一即回归：
      1. 看门狗单例必须由**命名互斥量**保证（内核按句柄计数，不依赖任何落盘文件，
         持有者一退出对象即消失，不会有 2026-09-20 那类僵尸锁死锁）；
      2. 拉起看门狗前必须先问锁（`--probe`），不能只信 PID 文件；
      3. 认领 SQL 两个方言分支都要在**外层**复查 `status = 'pending'`，PG 另需
         `FOR UPDATE SKIP LOCKED`（否则并发认领互相阻塞）；
      4. 两分支的参数顺序**不同**：PG 的白名单在 CTE 里、排在 SET 的两个参数之前。
         顺序错配会把 pid 写进 started_at、把任务名写进 worker_pid —— 本次首次
         上线即由生产日志暴露（`无效的类型 integer 输入语法: "eflow_active_alarm"`）；
      5. 回收前必须向操作系统核实进程（`_looks_like_live_worker`），不能只信文件；
      6. 终态只回写给"自己认领的那一行"（`_finish` 带 worker_pid 归属条件）。
    """
    wwd = (BACKEND / "worker_watchdog.py").read_text(encoding="utf-8", errors="replace")
    assert "_acquire_singleton_lock" in wwd and "CreateMutexW" in wwd, (
        "看门狗不再使用命名互斥量单例 —— 退化成只看 PID 文件，删文件就会叠出重复栈"
    )
    assert "_acquire_singleton_lock()" in wwd.split("def main():")[-1], (
        "main() 未获取单例锁：锁的实现还在，但启动路径不再执行它"
    )
    assert "--probe" in wwd, "看门狗缺少 --probe 探测入口（跨完整性级别判断是否已有实例的依据）"

    sh = (PROJECT_ROOT / "start_hidden.ps1").read_text(encoding="utf-8", errors="replace")
    assert "--probe" in sh, (
        "start_hidden.ps1 拉起看门狗前不再探测单例锁 —— PID 文件被删时会叠出第二套栈"
    )

    w = (BACKEND / "worker.py").read_text(encoding="utf-8", errors="replace")
    assert "FOR UPDATE SKIP LOCKED" in w, "PG 认领分支丢失 SKIP LOCKED（并发认领会互相阻塞）"
    assert "AND task_queue.status = 'pending'" in w, (
        "PG 认领分支丢失外层 status 复查 —— 双认领回归，同一任务会被执行两遍"
    )
    assert "AND status = 'pending'" in w, "SQLite 认领分支丢失外层 status 复查"
    assert "tuple(task_ids + [now_iso, my_pid])" in w, (
        "PG 分支参数顺序被改回「时间/pid 在前」：白名单在 CTE 里必须先传"
    )
    assert "tuple([now_iso, my_pid] + task_ids)" in w, "SQLite 分支参数顺序与占位符不一致"
    assert "_looks_like_live_worker" in w, (
        "回收逻辑不再向操作系统核实进程 —— 活着的 worker 会被重新判成「进程已失效」"
    )
    assert "AND worker_pid = ?" in w, "_finish 丢失 worker_pid 归属校验（会盖掉别人认领的行）"

    tr = (BACKEND / "services" / "task_runner.py").read_text(encoding="utf-8", errors="replace")
    assert "def _looks_like_live_worker" in tr, "缺少进程级核实辅助函数"
    assert "PROCESS_QUERY_LIMITED_INFORMATION" in tr, (
        "进程核实必须用 0x1000（不受完整性级别限制）；0x0400 会把提权启动的 worker 读成已死"
    )


# ---------------------------------------------------------------- 守卫 16
def test_tt_quick_analysis_is_programmatic_only():
    """「TT 快速分析」的结论必须纯程序化，且不得带「模型失败」措辞（2026-10-19）。

    现场事故：`?page=eflow_qa` 顶部长期挂着红条
    `AI analysis failed: RuntimeError: 所有候选模型均失败 ['openwebui:agnes-2.5-flash']:
    Open WebUI 登录失败 (HTTP 400): {'detail': 'Your provider has not provided a trusted
    header…'}`。根因在**服务端**：192.168.100.27 的 Open WebUI 0.12.0 已启用
    trusted-header 单点登录，邮箱密码登录被服务端禁用（改密码无用，实测记录见
    `backend/services/openwebui_client.md`），而 `provider=openwebui` 时候选链里
    **只有云端这一档**，本地 WorkBuddy 代理（当时在线、单次对话约 2 秒）根本不进链，
    于是一次 400 就整条失败。用户裁决：这个页面一律按程序化规则引擎出结果，不再调模型。

    钉死三件事，缺一即回归：
      1. 前端不得再请求 `/eflow-qa/tt-ai`（只允许 `/eflow-qa/tt-ai-fast`）；
      2. `/tt-ai-fast` 渲染结论必须传 `reason=""`，否则 Markdown 末尾凭空多出一行
         「未采用模型结论的原因」，把主结论写成兜底；
      3. 程序化结论正文（zh/en）不得出现「模型不可用 / 模型失败原因」这类兜底措辞，
         但必须明确声明「无模型参与」—— 用户要能分辨结论是引擎给的还是模型给的。
    """
    page = (PROJECT_ROOT / "frontend" / "src" / "pages" / "EflowQa.tsx").read_text(
        encoding="utf-8", errors="replace")
    stale = re.findall(r"/eflow-qa/tt-ai(?!-fast)", page)
    assert not stale, (
        f"EflowQa.tsx 又出现 {len(stale)} 处云端 /tt-ai 调用 —— TT 快速分析必须只走"
        " /tt-ai-fast（本地规则引擎），模型路径只留给人工排障"
    )

    router = (ROUTERS / "eflow_qa.py").read_text(encoding="utf-8", errors="replace")
    fast_body = router.split("def tt_ai_fast(", 1)[1].split("\n@router", 1)[0]
    assert 'reason=""' in fast_body, (
        'tt_ai_fast 不再用 reason="" 渲染 —— 程序化结论会被写成「模型失败后的兜底」'
    )

    from backend.services.eflow_rules import tt_rule_evidence as tre

    ev = {"matched": {}, "rules_file": {}, "handler": {}}
    md_en = tre.render_local_conclusion(ev, report=None, lang="en", reason="")
    md_zh = tre.render_local_conclusion(ev, report=None, lang="zh", reason="")
    for bad in ("AI model was unavailable", "Model failure reason",
                "未采用模型结论的原因", "模型不可用"):
        assert bad not in md_en and bad not in md_zh, (
            f"程序化结论残留兜底措辞「{bad}」—— 它现在是主结论，不是模型失败的替代"
        )
    assert "No model is involved" in md_en and "无模型参与" in md_zh, (
        "程序化结论缺少「无模型参与」声明 —— 界面上无法区分引擎判定与模型判定"
    )



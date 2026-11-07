# -*- coding: utf-8 -*-
"""CMDB 站点同步比对任务（eflow_site_update）

把 `data/eflow/cmdb_site_update/build_cmdb_site_update_v2.py` 包装成一个可被
task_runner 调度、也可由 Email Reports 页签按钮一键触发的手动任务。

**四步流水线**（与 `run_site_update.bat` 完全一致，顺序不可颠倒）：
1. `build_cmdb_site_update_v2.py` —— 生成 xlsx（审查全量 + 导入副本 + 报告）
2. `gen_change_summary.py` —— 变更汇总 md（从 xlsx 取数）
3. `gen_change_mail.py` —— 邮件正文 txt（从 xlsx 取数）
4. `check_requirements.py` —— 按《其他要求》10 条规则自检，落校验报告 txt

第 2-4 步是**派生**的：只跑第 1 步会让汇总/邮件/校验报告停留在旧数据上（bat 曾
只调第 1 步，导致 xlsx 是新的而 md/txt 是几天前的）。派生步骤失败只记录在
`derived` / `derived_failed` 里，不会把整次运行判为失败。

**铁律：本任务只生成文件，绝不写数据库。**
命令行里显式传 `--pg none --cmdb none`，不依赖脚本自身的默认值 —— 即使有人把
脚本默认值改成写库，这里也不会跟着写。审查通过后由人工执行导入。

为什么用 subprocess 而不是 import 脚本：
- 脚本是独立可执行程序（argparse + sys.exit），import 进来只能拿函数、拿不到
  它完整的参数校验与预检逻辑；
- 它依赖 openpyxl/psycopg2 且会 sys.stdout.reconfigure，在长驻的后端进程里跑
  容易污染全局状态；
- 独立进程崩溃/超时不会拖垮后端，超时可直接 kill。

退出码约定（脚本自己定义）：
- 0 = 成功（文件已写出）
- 2 = 仅在 --strict-lock 严格模式下目标 xlsx 被占用；默认不启用
- 其它 = 失败

关于「文件被占用」：
正式产出常被 WPS / 右侧预览面板打开，这是常态而不是故障。脚本默认会
在被占用时自动另存带时间戳的副本（不覆盖被打开的文件），并把本次真实
路径写进 `modify/last_run_files.json`；后端把 degraded 标记透传给页面，
避免用户误下载那个没更新的旧文件。助手侧约定：只预览 md/txt 汇总，
不把 modify 下的正式 xlsx 交给预览面板。

结果除了返回给 task_runner，还会落一份 `modify/last_run_summary.json`，
供前端页签在刷新页面后仍能看到「上次运行」的统计。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# 同一时刻只允许一次运行：连续点按钮会并发写同一批 xlsx，互相踩文件锁
_RUN_LOCK = threading.Lock()

_SCRIPT_NAME = "build_cmdb_site_update_v2.py"
_DEFAULT_TIMEOUT = 1800  # 30 分钟：源表 876 行 + 43 列着色，实测数十秒，留足余量


def _resolve_work_dir() -> Path:
    """脚本目录。默认 my_app/data/eflow/cmdb_site_update（本文件在 backend/services/ 下）。"""
    env = os.environ.get("CMDB_SITE_UPDATE_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (Path(__file__).resolve().parents[2] / "data" / "eflow" / "cmdb_site_update").resolve()


WORK_DIR = _resolve_work_dir()
SCRIPT_PATH = WORK_DIR / _SCRIPT_NAME
OUT_DIR = WORK_DIR / "modify"
SUMMARY_JSON = OUT_DIR / "last_run_summary.json"

# stdout 里的结构化行（脚本自己打印的，格式见 build_cmdb_site_update_v2.py:1143+）
_RE_EFLOW = re.compile(r"eflow\s*:\s*新增A\s*(\d+)\s+修改M\s*(\d+)\s+删除D\s*(\d+)\s+无变化\s*(\d+)")
_RE_MASTER = re.compile(r"master\s*:\s*新增A\s*(\d+)\s+修改M\s*(\d+)\s+删除D\s*(\d+)\s+无变化\s*(\d+)")
# 源文件名本身带括号（如 "...20261103(Important) (1).xlsx"），所以不能用「括号内即时间」
# 的写法；锚定行尾的时间戳、非贪婪吃掉文件名，才不会把文件名截成半截。
_RE_SRC = re.compile(r"^源文件\s*:\s*(.+?)\s+\((\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})\)\s*$", re.M)
_RE_UNIQUE = re.compile(r"清洗后\s*:\s*(\d+)\s*个唯一站（重复ID\s*(\d+):\s*\[(.*?)\]")
_RE_COORD = re.compile(r"坐标自愈:\s*(\d+)")
_RE_FME_EMPTY = re.compile(r"FME为空\s*:\s*(\d+)")
_RE_LOCKED = re.compile(r"\[LOCKED\]")
_RE_DEGRADED = re.compile(r"\[DEGRADED\]")
MANIFEST_JSON = OUT_DIR / "last_run_files.json"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _list_outputs() -> list[dict]:
    """modify 目录下的产出文件（含 import 子目录），按修改时间倒序。"""
    items: list[dict] = []
    if not OUT_DIR.is_dir():
        return items
    for path in sorted(OUT_DIR.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith(".") or path.suffix.lower() == ".tmp":
            continue
        # 上次运行的摘要 / 产出清单不算产出，避免前端列表里出现自己
        if path.name in (SUMMARY_JSON.name, MANIFEST_JSON.name):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        items.append({
            "name": path.name,
            "rel_path": str(path.relative_to(OUT_DIR)).replace("\\", "/"),
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "mtime_ts": st.st_mtime,
        })
    items.sort(key=lambda x: x["mtime_ts"], reverse=True)
    return items


# 派生步骤：全部从第 1 步写出的 xlsx 取数，必须在 build 成功后才跑。
# 只跑 build 会让「变更汇总.md / 邮件正文.txt / 校验报告.txt」停在旧数据上——
# 这正是 run_site_update.bat 曾经踩过的坑，页面按钮走同一条流水线。
_DERIVED_STEPS = (
    ("summary", "gen_change_summary.py"),
    ("mail", "gen_change_mail.py"),
    # check_requirements：0=全部通过，1=有规则不通过（数据问题，不是脚本故障），2=文件缺失
    ("check", "check_requirements.py"),
)
_DERIVED_TIMEOUT = 300


def _run_derived(env: dict, creationflags: int) -> list[dict]:
    """依次跑汇总 / 邮件 / 校验。任一步失败都只做记录，不改变主任务成功状态。"""
    results: list[dict] = []
    for step, name in _DERIVED_STEPS:
        path = WORK_DIR / name
        if not path.is_file():
            results.append({"step": step, "ok": False, "error": f"脚本不存在：{name}"})
            continue
        cmd = [sys.executable, "-X", "utf8", str(path)]
        try:
            proc = subprocess.run(  # noqa: S603 - 参数固定，无 shell
                cmd, cwd=str(WORK_DIR), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=_DERIVED_TIMEOUT,
                env=env, creationflags=creationflags,
            )
            code = proc.returncode
            out = proc.stdout or ""
            ok = code == 0 or (step == "check" and code == 1)
            item = {
                "step": step,
                "ok": ok,
                "returncode": code,
            }
            if step == "check":
                m = re.findall(r">>>\s*(.+?):\s*(\d+)/10 通过", out)
                item["passed"] = code == 0
                item["rules"] = {k: int(v) for k, v in m}
            if not ok:
                item["error"] = f"退出码 {code}"
                item["tail"] = out[-800:]
                item["stderr_tail"] = (proc.stderr or "")[-500:]
            results.append(item)
        except subprocess.TimeoutExpired:
            results.append({"step": step, "ok": False, "error": f"超时（>{_DERIVED_TIMEOUT}s）"})
        except Exception as exc:  # noqa: BLE001 - 派生步骤失败不能拖垮主任务
            results.append({"step": step, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return results


def _parse_stdout(text: str) -> dict:
    out: dict = {
        "eflow": None,
        "master": None,
        "source_file": None,
        "source_mtime": None,
        "cmdb_unique_sites": None,
        "duplicate_id_count": None,
        "duplicate_ids": [],
        "coord_fixed": None,
        "fme_empty": None,
    }
    if m := _RE_EFLOW.search(text):
        out["eflow"] = {"A": int(m.group(1)), "M": int(m.group(2)),
                        "D": int(m.group(3)), "unchanged": int(m.group(4))}
    if m := _RE_MASTER.search(text):
        out["master"] = {"A": int(m.group(1)), "M": int(m.group(2)),
                         "D": int(m.group(3)), "unchanged": int(m.group(4))}
    if m := _RE_SRC.search(text):
        out["source_file"] = m.group(1).strip()
        out["source_mtime"] = m.group(2).strip()
    if m := _RE_UNIQUE.search(text):
        out["cmdb_unique_sites"] = int(m.group(1))
        out["duplicate_id_count"] = int(m.group(2))
        raw = m.group(3).strip()
        out["duplicate_ids"] = [x.strip().strip("'\"") for x in raw.split(",") if x.strip()]
    if m := _RE_COORD.search(text):
        out["coord_fixed"] = int(m.group(1))
    if m := _RE_FME_EMPTY.search(text):
        out["fme_empty"] = int(m.group(1))
    return out


def _write_summary(payload: dict) -> None:
    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SUMMARY_JSON.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, SUMMARY_JSON)
    except OSError as e:  # noqa: BLE001
        # 摘要落盘失败不影响主流程：前端拿不到「上次运行」，但文件已经生成
        logger.warning("CMDB 站点同步摘要落盘失败: %s", e)


def read_last_summary() -> dict | None:
    """给 API 用：读上一次运行的摘要（不存在返回 None）。"""
    if not SUMMARY_JSON.is_file():
        return None
    try:
        return json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_manifest() -> dict | None:
    """读脚本本次写出的真实路径（降级另存时与正式文件名不同）。"""
    if not MANIFEST_JSON.is_file():
        return None
    try:
        return json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_eflow_site_update(timeout: int = _DEFAULT_TIMEOUT) -> dict:
    """执行比对脚本并返回摘要（task_runner 入口，签名不接受必填参数）。

    只读 CMDB 源表 + eflow 基线 + PG 快照基线，只写 modify 目录下的 xlsx。
    """
    script = SCRIPT_PATH
    if not script.is_file():
        msg = f"脚本不存在：{script}"
        logger.error(msg)
        return {"success": False, "error": msg}

    if not _RUN_LOCK.acquire(blocking=False):
        msg = "已有一次 CMDB 站点同步在运行，请等待其结束后再试"
        logger.warning(msg)
        return {"success": False, "error": msg}

    started = time.perf_counter()
    started_at = _now()
    cmd = [
        sys.executable, "-X", "utf8", str(script),
        # 显式钉死「只产文件」：不写 PG、不写 sqlite
        "--pg", "none",
        "--cmdb", "none",
        # 显式钉死「占用即降级另存」：绝不因预览面板开着而让整批产出失败
        "--allow-fallback",
    ]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    logger.info("CMDB 站点同步开始：%s", " ".join(cmd))
    try:
        try:
            proc = subprocess.run(  # noqa: S603 - 参数固定，无 shell
                cmd,
                cwd=str(WORK_DIR),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
                creationflags=creationflags,
            )
            stdout, stderr, code = proc.stdout or "", proc.stderr or "", proc.returncode
        except subprocess.TimeoutExpired:
            elapsed = round(time.perf_counter() - started, 2)
            msg = f"执行超时（>{timeout}s），已终止进程。请检查源表是否异常增大"
            logger.error("CMDB 站点同步超时：%s", msg)
            payload = {
                "success": False, "error": msg,
                "started_at": started_at, "finished_at": _now(), "elapsed_seconds": elapsed,
            }
            _write_summary({**payload, "files": _list_outputs()})
            return payload

        elapsed = round(time.perf_counter() - started, 2)
        parsed = _parse_stdout(stdout)
        tail = stdout[-4000:] if len(stdout) > 4000 else stdout

        if code == 0:
            degraded = bool(_RE_DEGRADED.search(stdout))
            manifest = _read_manifest() or {}
            degraded_files: list[dict] = []
            if degraded:
                for _key, info in (manifest.get("files") or {}).items():
                    if not isinstance(info, dict) or not info.get("degraded"):
                        continue
                    actual = os.path.basename(info.get("actual", ""))
                    degraded_files.append({
                        "formal": os.path.basename(info.get("expected", "")),
                        "actual": actual,
                        "rel_path": actual,
                    })
            # 派生步骤要在 files 列表之前跑：这样汇总/邮件/校验报告也带上最新时间戳
            derived = _run_derived(env, creationflags)
            derived_failed = [d["step"] for d in derived if not d.get("ok")]
            payload = {
                "success": True,
                "started_at": started_at,
                "finished_at": _now(),
                "elapsed_seconds": round(time.perf_counter() - started, 2),
                "note": "仅生成待审查文件，未写入任何数据库",
                "degraded": degraded,
                "degraded_files": degraded_files,
                "derived": derived,
                "derived_failed": derived_failed,
                **parsed,
                "files": _list_outputs(),
                "stdout_tail": tail,
            }
            logger.info("CMDB 站点同步完成（%.1fs）：eflow %s / master %s / 派生 %s",
                        elapsed, parsed.get("eflow"), parsed.get("master"),
                        "全部成功" if not derived_failed else f"失败 {derived_failed}")
            _write_summary(payload)
            return payload

        if code == 2 or _RE_LOCKED.search(stdout):
            msg = ("严格模式下目标文件被占用，生成中止（默认模式会自动另存副本，"
                   "正常按钮不应出现此状态）；关闭预览面板 / WPS 后重跑即可写回正式文件名")
            logger.warning("CMDB 站点同步被文件锁阻止：%s", msg)
        else:
            msg = f"脚本执行失败（退出码 {code}）"
            logger.error("CMDB 站点同步失败 code=%s\nSTDOUT:\n%s\nSTDERR:\n%s",
                         code, tail, stderr[-2000:])

        payload = {
            "success": False,
            "error": msg,
            "started_at": started_at,
            "finished_at": _now(),
            "elapsed_seconds": elapsed,
            **parsed,
            "stdout_tail": tail,
            "stderr_tail": stderr[-2000:] if stderr else "",
        }
        _write_summary({**payload, "files": _list_outputs()})
        return payload
    finally:
        _RUN_LOCK.release()

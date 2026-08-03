# -*- coding: utf-8 -*-
"""
原子写工具：所有对最终 xlsx 文件的覆盖写都走这里。

原理：
  1. 先把内容写到一个临时文件 `<final>.<pid>.tmp`
  2. 用 os.replace() 原子替换到最终路径（Windows 上 replace 是原子的）
  3. 写临时文件 / 替换两步都带固定间隔重试，专门扛"文件被占用(Permission denied)"
     —— 典型场景：Excel 打开着报表、WPS云同步、Defender实时扫描、索引服务。
  4. 重试耗尽后启用 fallback：保存到同目录下带时间戳的备用文件，确保数据不丢失。

这样即使目标文件此刻被外部进程锁住，只要几秒内锁释放，任务就能自己穿过去，
而不是一上来就失败。重试耗尽才走 fallback（与 UME 的重试语义一致）。
"""
import os
import time
import logging
import shutil
import glob as _glob
import uuid
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime
from pandas import ExcelWriter  # 模块级导入：atomic_to_excel / atomic_excel_writer 共用

logger = logging.getLogger("atomic_write")

_RETRYABLE = (PermissionError, OSError)


def _temporary_path(final):
    """Return a per-write temporary filename in the target directory.

    PID alone is not unique: two threads in the same process can otherwise
    write the same ``*.tmp.xlsx`` file and lock each other on Windows.
    """
    final_p = Path(final)
    return final_p.with_name(
        f"{final_p.stem}.{os.getpid()}.{uuid.uuid4().hex}.tmp{final_p.suffix}"
    )


def _cleanup(tmp):
    try:
        if os.path.exists(str(tmp)):
            os.remove(str(tmp))
    except OSError:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _cleanup: exception swallowed", exc_info=True)
        pass


def find_lock_owners(final):
    """返回独占/打开文件 final 的进程列表 [(pid, name)]。

    优先用 Sysinternals ``handle.exe``（若已加入 PATH）做最可靠的解析；
    不可用则返回空列表（此时 ``_diagnose_lock`` 仍会用「可写性探测」给出锁定状态）。
    **只读探测，不做任何修改**，仅用于排查文件被谁锁住
    （杀毒实时扫描 / 前端热读 / 索引服务 / 残留的 openpyxl 进程等）。
    """
    try:
        import re
        import shutil
        import subprocess
        h = shutil.which("handle") or shutil.which("handle64") or shutil.which("handle.exe")
        if h:
            out = subprocess.run(
                [h, "-nobanner", str(final)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
            ).stdout
            owners = []
            # handle.exe 输出形如:  python.exe  pid: 1234  type: File  ...  C:\path\file.xlsx
            for m in re.finditer(r"pid:\s*(\d+).*?type:\s*File[^\n]*\n\s*(.+)", out):
                owners.append((int(m.group(1)), m.group(2).strip()))
            if owners:
                return owners
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] find_lock_owners: exception swallowed", exc_info=True)
        pass
    return []


def _diagnose_lock(final):
    """诊断谁锁住了文件并输出日志；同时做可写性探测。"""
    try:
        import ctypes
        from ctypes import wintypes
        handle = ctypes.windll.kernel32.CreateFileW(
            str(final), 0x40000000, 0, None, 3, 0x80, None  # GENERIC_WRITE, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL
        )
        writable = handle != -1
        if writable:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _diagnose_lock: exception swallowed", exc_info=True)
        writable = None

    owners = find_lock_owners(final)
    if owners:
        procs = ", ".join(f"pid={p} {n}" for p, n in owners)
        logger.warning("  🔒 文件锁诊断: 目标被进程独占: %s | 持有者: %s", final, procs)
    elif writable is True:
        logger.info("  文件锁诊断: 目标此刻可写（锁已释放）: %s", final)
    elif writable is False:
        logger.warning("  文件锁诊断: 目标被独占(WinError 5 类): %s", final)
    return owners


def _fallback_save(tmp, final):
    """重试耗尽后的兜底：把 tmp 移动到同目录带时间戳的备用文件，确保数据不丢失。"""
    final_p = Path(str(final))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # A second-level timestamp can collide when concurrent writers fall back.
    fallback_name = f"{final_p.stem}_{ts}_{uuid.uuid4().hex[:8]}{final_p.suffix}"
    fallback_path = final_p.parent / fallback_name
    try:
        os.replace(str(tmp), str(fallback_path))
        logger.warning(
            "⚠️ 原子替换最终失败，数据已保存到备用文件: %s（原目标被锁: %s）",
            fallback_path, final_p.name,
        )
        return str(fallback_path)
    except Exception as e:
        logger.error("fallback 保存也失败: %s -> %s: %s", tmp, fallback_path, e)
        _cleanup(tmp)
        return None


def _atomic_replace(tmp, final, max_retries, base_wait):
    """把 tmp 原子替换到 final，重试扛文件锁。

    间歇性锁场景（如云同步/杀软/索引服务周期扫描 xlsx）下，固定间隔重试
    比指数退避更稳：无论锁何时释放，长窗口内总能穿过。
    对 WinError 5/13 这类独占锁，每几次额外尝试「先删旧文件再 rename」兜底。
    重试耗尽后走 fallback 备用路径，确保数据不丢失。
    """
    last_err = None
    for attempt in range(max_retries + 1):
        # 策略 A：原子替换（最干净）
        try:
            os.replace(str(tmp), str(final))
            return True
        except _RETRYABLE as e:
            last_err = e
            # 策略 B：独占锁导致 replace 失败时，尝试删旧文件再 rename
            if attempt > 0 and attempt % 4 == 0:
                try:
                    if os.path.exists(str(final)):
                        os.remove(str(final))
                    os.rename(str(tmp), str(final))
                    return True
                except _RETRYABLE as e2:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] _atomic_replace: exception swallowed", exc_info=True)
                    last_err = e2
            if attempt < max_retries:
                time.sleep(base_wait)
                if attempt % 10 == 9:  # 每 10 次输出一次诊断，避免刷屏
                    logger.warning(
                        "原子替换被拒(文件被占用?)，已重试 %d/%d 次: %s",
                        attempt + 1, max_retries, final,
                    )
                    _diagnose_lock(final)
            else:
                break

    # 重试耗尽前的最后手段：目标被独占但允许写入(共享写)时，就地覆盖内容。
    # 典型场景：读者(openpyxl 读、看板热读)以 共享读+写 但不共享删除 打开文件，
    # 此时 os.replace(需删旧文件) 失败，但 copyfile(只写内容) 可穿过去。
    for _ in range(3):
        try:
            shutil.copyfile(str(tmp), str(final))
            logger.warning("✅ 通过就地覆盖(copyfile)写穿文件锁: %s", final)
            _cleanup(tmp)
            return True
        except _RETRYABLE:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _atomic_replace: exception swallowed", exc_info=True)
            time.sleep(base_wait)

    # 重试耗尽：诊断 + fallback
    logger.error("原子替换 %d 次重试全部失败: %s -> %s: %s", max_retries + 1, tmp, final, last_err)
    _diagnose_lock(final)
    fallback_path = _fallback_save(tmp, final)
    if fallback_path:
        # 数据已保全，抛出自定义异常让上层知道走了 fallback
        raise AtomicReplaceFallback(
            f"原子替换失败(文件被锁)，数据已保存到: {fallback_path}",
            fallback_path=fallback_path,
            original_error=last_err,
        )
    raise last_err or OSError(f"atomic replace failed: {final}")


class AtomicReplaceFallback(Exception):
    """原子替换失败但数据已通过 fallback 路径保全。上层可捕获此异常决定是否视为成功。"""
    def __init__(self, message, fallback_path=None, original_error=None):
        super().__init__(message)
        self.fallback_path = fallback_path
        self.original_error = original_error


def cleanup_stale_tmp_files(directory, pattern="*.tmp.xlsx"):
    """清理目录下残留的 .tmp.xlsx 文件（进程异常退出后遗留）。"""
    cleaned = 0
    for fpath in _glob.glob(os.path.join(str(directory), pattern)):
        try:
            os.remove(fpath)
            cleaned += 1
            logger.info("清理残留临时文件: %s", os.path.basename(fpath))
        except OSError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] cleanup_stale_tmp_files: exception swallowed", exc_info=True)
            pass
    return cleaned


def atomic_save_workbook(wb, path, max_retries=45, base_wait=2.0):
    """openpyxl Workbook 的原子落盘（覆盖写）。wb 对象由调用方管理生命周期。"""
    final = Path(path)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = _temporary_path(final)

    last_err = None
    for attempt in range(max_retries + 1):
        try:
            wb.save(str(tmp))
            break
        except _RETRYABLE as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(base_wait)
            else:
                _cleanup(tmp)
                raise
    _atomic_replace(tmp, final, max_retries, base_wait)


def atomic_to_excel(df, path, sheet_name="Sheet1", index=False,
                    max_retries=45, base_wait=2.0):
    """pandas DataFrame 的原子落盘（覆盖写）。"""
    final = Path(path)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = _temporary_path(final)
    try:
        with ExcelWriter(str(tmp), engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=index)
    except Exception:
        _cleanup(tmp)
        raise
    _atomic_replace(tmp, final, max_retries, base_wait)


def atomic_replace_file(src, dst, max_retries=45, base_wait=2.0):
    """把已存在的临时文件 src 原子替换到最终路径 dst，重试扛文件锁。

    用于 sftp.get 等「先下载到临时文件、再落定」的场景。
    """
    _atomic_replace(str(src), str(dst), max_retries, base_wait)


@contextmanager
def atomic_excel_writer(path, engine="openpyxl", max_retries=45, base_wait=2.0):
    """多 sheet 场景：yield 一个写到临时文件的 ExcelWriter，退出时原子替换。

    用法：
        with atomic_excel_writer(out_path) as writer:
            df1.to_excel(writer, sheet_name="A", index=False)
            df2.to_excel(writer, sheet_name="B", index=False)
    """
    final = Path(path)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = _temporary_path(final)
    try:
        with ExcelWriter(str(tmp), engine=engine) as writer:
            yield writer
        _atomic_replace(tmp, final, max_retries, base_wait)
    except Exception:
        _cleanup(tmp)
        raise

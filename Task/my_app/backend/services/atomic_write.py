# -*- coding: utf-8 -*-
"""
原子写工具：所有对最终 xlsx 文件的覆盖写都走这里。

原理：
  1. 先把内容写到一个临时文件 `<final>.<pid>.tmp`
  2. 用 os.replace() 原子替换到最终路径（Windows 上 replace 是原子的）
  3. 写临时文件 / 替换两步都带指数退避重试，专门扛"文件被占用(Permission denied)"
     —— 典型场景：Excel 打开着报表、或 FineBI/同事通过 SMB(D$) 正在读该文件。

这样即使目标文件此刻被外部进程锁住，只要几秒内锁释放，任务就能自己穿过去，
而不是一上来就失败。重试耗尽才真正报错（与 UME 的重试语义一致）。
"""
import os
import time
import logging
from pathlib import Path
from contextlib import contextmanager
from pandas import ExcelWriter  # 模块级导入：atomic_to_excel / atomic_excel_writer 共用

logger = logging.getLogger("atomic_write")

_RETRYABLE = (PermissionError, OSError)


def _cleanup(tmp):
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except OSError:
        pass


def _atomic_replace(tmp, final, max_retries, base_wait):
    """把 tmp 原子替换到 final，重试扛文件锁。

    间歇性锁场景（如云同步/杀软/索引服务周期扫描 xlsx）下，固定间隔重试
    比指数退避更稳：无论锁何时释放，长窗口内总能穿过。
    对 WinError 5/13 这类独占锁，每几次额外尝试「先删旧文件再 rename」兜底。
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
                    last_err = e2
            if attempt < max_retries:
                time.sleep(base_wait)
                logger.warning(
                    "原子替换被拒(文件被占用?)，%ss 后重试 (%d/%d): %s",
                    base_wait, attempt + 1, max_retries, final,
                )
            else:
                break
    _cleanup(tmp)
    raise last_err or OSError(f"atomic replace failed: {final}")


def atomic_save_workbook(wb, path, max_retries=45, base_wait=2.0):
    """openpyxl Workbook 的原子落盘（覆盖写）。wb 对象由调用方管理生命周期。"""
    final = Path(path)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(f"{final.stem}.{os.getpid()}.tmp.xlsx")

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
    tmp = final.with_name(f"{final.stem}.{os.getpid()}.tmp.xlsx")
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
    tmp = final.with_name(f"{final.stem}.{os.getpid()}.tmp.xlsx")
    try:
        with ExcelWriter(str(tmp), engine=engine) as writer:
            yield writer
        _atomic_replace(tmp, final, max_retries, base_wait)
    except Exception:
        _cleanup(tmp)
        raise

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

logger = logging.getLogger("atomic_write")

_RETRYABLE = (PermissionError, OSError)


def _cleanup(tmp):
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except OSError:
        pass


def _atomic_replace(tmp, final, max_retries, base_wait):
    """把 tmp 原子替换到 final，重试扛文件锁。"""
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            os.replace(str(tmp), str(final))
            return True
        except _RETRYABLE as e:
            last_err = e
            if attempt < max_retries:
                wait = base_wait * (2 ** attempt)
                logger.warning(
                    "原子替换被拒(Permission denied?)，%ss 后重试 (%d/%d): %s",
                    wait, attempt + 1, max_retries, final,
                )
                time.sleep(wait)
            else:
                break
    _cleanup(tmp)
    raise last_err or OSError(f"atomic replace failed: {final}")


def atomic_save_workbook(wb, path, max_retries=4, base_wait=1.0):
    """openpyxl Workbook 的原子落盘（覆盖写）。wb 对象由调用方管理生命周期。"""
    final = Path(path)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_suffix(final.suffix + f".{os.getpid()}.tmp")

    last_err = None
    for attempt in range(max_retries + 1):
        try:
            wb.save(str(tmp))
            break
        except _RETRYABLE as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(base_wait * (2 ** attempt))
            else:
                _cleanup(tmp)
                raise
    _atomic_replace(tmp, final, max_retries, base_wait)


def atomic_to_excel(df, path, sheet_name="Sheet1", index=False,
                    max_retries=4, base_wait=1.0):
    """pandas DataFrame 的原子落盘（覆盖写）。"""
    from pandas import ExcelWriter
    final = Path(path)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_suffix(final.suffix + f".{os.getpid()}.tmp")
    try:
        with ExcelWriter(str(tmp), engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=index)
    except Exception:
        _cleanup(tmp)
        raise
    _atomic_replace(tmp, final, max_retries, base_wait)


@contextmanager
def atomic_excel_writer(path, engine="openpyxl", max_retries=4, base_wait=1.0):
    """多 sheet 场景：yield 一个写到临时文件的 ExcelWriter，退出时原子替换。

    用法：
        with atomic_excel_writer(out_path) as writer:
            df1.to_excel(writer, sheet_name="A", index=False)
            df2.to_excel(writer, sheet_name="B", index=False)
    """
    final = Path(path)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_suffix(final.suffix + f".{os.getpid()}.tmp")
    try:
        with ExcelWriter(str(tmp), engine=engine) as writer:
            yield writer
        _atomic_replace(tmp, final, max_retries, base_wait)
    except Exception:
        _cleanup(tmp)
        raise

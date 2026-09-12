"""子进程输出落盘：pipe 泵 + 按大小轮转（防止单文件无上限增长）。

背景（2026-09-11 实证）
----------------------
此前各 watchdog / proxy 拉起子进程时，是把自家 ``open(path, "ab")`` 的句柄
直接交给子进程继承（``stdout=log_fh``）。Windows 下**被进程持有的文件无法
被外部 rename / delete / 轮转**（WinError 32），于是单文件只能一路追加：

    backend_runtime.log              177 MB
    realtime_proxy_fms_console.log   154 MB
    worker_runtime_20260910.log       89 MB

且 log_cleanup 任务因为文件被占用，连删除都做不到（只能跳过）。

方案
----
把子进程输出改由**父进程**接管：

    Popen(..., stdout=PIPE, stderr=STDOUT)
        -> pump 线程 read1()
        -> RotatingLogWriter 追加写盘

写文件的句柄始终在父进程手里，因此可以在运行中随时 close + 切到下一个分片，
**无需重启子进程** —— 这是与"只能在重启时 rollover"做法的关键区别
（uvicorn / worker 常年不重启，重启式轮转实际等于不轮转）。

用法
----
    from backend.log_writer import attach_rotating_output

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, ...)
    writer = attach_rotating_output(proc, log_path, name="backend")

环境变量
--------
    LOG_ROTATE_MAX_MB   单文件上限（MB），默认 100
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger("log_writer")

READ_CHUNK = 65536        # 单次 pipe 读取块大小
MAX_PARTS = 500           # 分片数上限（异常保护）
# 连续写入失败达此次数 -> 降级为 drain（丢弃），宁可丢日志也不能让子进程被 pipe 堵死
_MAX_CONSEC_ERR = 20


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def max_bytes_from_env() -> int:
    """单文件上限字节数，由 LOG_ROTATE_MAX_MB 控制（默认 100MB）。"""
    return max(1, _env_int("LOG_ROTATE_MAX_MB", 100)) * 1024 * 1024


class RotatingLogWriter:
    """把字节流追加写入 base_path，超过 max_bytes 自动切 ``_pN`` 分片。

    线程安全；句柄由本对象独占持有，因此切换文件不需要子进程配合。
    分片命名：``xxx.log`` -> ``xxx_p2.log`` -> ``xxx_p3.log`` ...
    """

    def __init__(self, base_path, max_bytes=None, logger_=None):
        self.base = Path(base_path)
        self.max_bytes = int(max_bytes or max_bytes_from_env())
        self._log = logger_ or logger
        self._lock = threading.Lock()
        self._fh = None
        self._path = None
        self._size = 0
        self.base.parent.mkdir(parents=True, exist_ok=True)
        self._open_initial()

    # ---------------- 内部 ----------------
    def _candidate(self, idx: int) -> Path:
        if idx <= 1:
            return self.base
        return self.base.with_name(f"{self.base.stem}_p{idx}{self.base.suffix}")

    @staticmethod
    def _size_of(p: Path) -> int:
        try:
            return p.stat().st_size
        except OSError:
            return 0

    def _flush_and_close(self):
        if self._fh is None:
            return
        try:
            self._fh.flush()
        except Exception:
            pass
        try:
            self._fh.close()
        except Exception:
            pass
        self._fh = None

    def _open_initial(self):
        """定位当前可用分片：跳过已经写满的 part（进程重启后重名文件可能已满）。"""
        for idx in range(1, MAX_PARTS + 1):
            p = self._candidate(idx)
            sz = self._size_of(p)
            if sz < self.max_bytes:
                self._path = p
                self._size = sz
                self._fh = open(p, "ab")
                return
        # 极端情况：所有分片都满 —— 继续用最后一个（不丢数据优先于切分）
        self._path = self._candidate(MAX_PARTS)
        self._size = self._size_of(self._path)
        self._fh = open(self._path, "ab")

    def _rollover(self):
        self._flush_and_close()
        idx = 2
        while idx <= MAX_PARTS and self._size_of(self._candidate(idx)) >= self.max_bytes:
            idx += 1
        p = self._candidate(min(idx, MAX_PARTS))
        self._path = p
        self._size = self._size_of(p)
        self._fh = open(p, "ab")
        self._log.info(
            "[log_writer] 单文件超过 %dMB，切换到新分片: %s",
            self.max_bytes // 1048576, p.name,
        )

    # ---------------- 对外 ----------------
    @property
    def current_path(self):
        return self._path

    def write(self, chunk: bytes) -> None:
        if not chunk:
            return
        with self._lock:
            if self._fh is None:
                self._open_initial()
            if self._size + len(chunk) > self.max_bytes:
                self._rollover()
            self._fh.write(chunk)
            self._size += len(chunk)
            self._fh.flush()  # 保持与原 buffering=0 一致的实时性

    def close(self):
        with self._lock:
            self._flush_and_close()


def _read_some(stream) -> bytes:
    """尽量读一段数据但不等满（pipe 友好）。返回 b'' 表示 EOF。"""
    read1 = getattr(stream, "read1", None)
    if read1 is not None:
        return read1(READ_CHUNK) or b""
    try:
        # raw 流（bufsize=0）没有 read1；os.read 不等满，且 EOF 时返回 b''
        return os.read(stream.fileno(), READ_CHUNK)
    except OSError:
        return b""


def _pump_loop(proc, writer: RotatingLogWriter, name: str) -> None:
    """后台线程：持续把子进程输出泵进 writer，直到子进程 stdout 关闭。"""
    stream = proc.stdout
    if stream is None:
        writer.close()
        return
    consecutive_err = 0
    draining = False
    try:
        while True:
            try:
                chunk = _read_some(stream)
            except ValueError:
                break  # 流已关闭
            if not chunk:
                break  # EOF：子进程退出或关闭了 stdout
            if draining:
                continue
            try:
                writer.write(chunk)
                consecutive_err = 0
            except Exception as e:  # noqa: BLE001
                consecutive_err += 1
                if consecutive_err == 1 or consecutive_err % 10 == 0:
                    logger.error("[log_writer] %s: 写日志失败(%d次): %s", name, consecutive_err, e)
                if consecutive_err >= _MAX_CONSEC_ERR:
                    logger.error(
                        "[log_writer] %s: 持续写入失败，降级为丢弃输出，避免子进程被 pipe 阻塞", name,
                    )
                    draining = True
                time.sleep(0.2)
    finally:
        try:
            stream.close()
        except Exception:
            pass
        writer.close()


def resolve_free_path(base_path, max_bytes: int = None) -> Path:
    """返回一个【未写满】的可用分片路径（供"句柄仍由子进程继承"的场景使用）。

    有些子进程（如 realtime_proxy）以 detach 方式拉起，与拉起者生命周期不同：
    父进程退出后 pipe 读端消失，子进程再写 stdout 会得到 broken pipe，甚至因
    pipe 缓冲区无人消费而阻塞。**这类进程不能改用 pipe 泵**，只能在"拉起时"
    挑一个还没写满的分片，写满后由它下一次重启继续切。
    """
    base = Path(base_path)
    limit = int(max_bytes or max_bytes_from_env())
    base.parent.mkdir(parents=True, exist_ok=True)

    def _size_of(p: Path) -> int:
        try:
            return p.stat().st_size
        except OSError:
            return 0

    def _candidate(idx: int) -> Path:
        if idx <= 1:
            return base
        return base.with_name(f"{base.stem}_p{idx}{base.suffix}")

    for idx in range(1, MAX_PARTS + 1):
        p = _candidate(idx)
        if _size_of(p) < limit:
            return p
    return base


def attach_rotating_output(proc, base_log_path, name: str = "", max_bytes: int = None):
    """把 proc 的 stdout 接到 RotatingLogWriter（后台 daemon 线程泵）。

    前置条件：Popen 时必须 ``stdout=subprocess.PIPE``，建议 ``stderr=subprocess.STDOUT``
    合并，否则 stderr 无处可去。
    返回 writer（持有者可通过 ``writer.current_path`` 观察当前正在写的文件）。
    """
    writer = RotatingLogWriter(base_log_path, max_bytes=max_bytes)
    tag = name or Path(base_log_path).stem
    t = threading.Thread(
        target=_pump_loop, args=(proc, writer, tag),
        name=f"logpump-{tag}", daemon=True,
    )
    t.start()
    return writer

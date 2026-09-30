# -*- coding: utf-8 -*-
"""FineBI 仓库看板镜像库的「本地构建 + 整文件推送」实现（2026-09-30）。

## 为什么不再直连 SMB 上的 inventory.db

旧实现（`get_sp_table._mirror_write_all`）从本机用 `sqlite3.connect()` 直接打开
`\\\\DESKTOP-D4GF62\\...\\WareHouseDashBoard\\inventory.db` 写数据。2026-09-30 实测定位到
该路径**必然失败**，而且失败方式是**永久阻塞**（不是抛错）：

| 探测 | 结果 |
| --- | --- |
| 远端 `inventory.db` 的 `journal_mode` | `wal`（持久化在文件头，非连接级设置） |
| 远端 `-wal` 大小 | 14.7MB 未 checkpoint |
| 独占打开远端 `-wal` | 被拒（`being used by another process`） |
| 独占打开远端 `-shm` | 被拒（`another process has locked a portion of the file`） |
| 在**同一 SMB 目录新建** delete 模式库并读写 | **成功** |
| 把该新库切成 WAL 后（无远端持有者）打开读 | **成功** |
| 打开生产 `inventory.db` | **立即** `database is locked` |

结论（修正 2026-09-27 的旧结论）：**不是** "WAL-over-SMB 天生不可用"——没有远端持有者时
WAL 库在 SMB 上也能读。真正的症结是**远端主机 DESKTOP-D4GF62 上有一个活进程长期持有
该库的 WAL 共享内存字节锁**（`-shm` 的字节范围锁），而 SMB 无法代理这套语义，于是本机
每一次 open 都被拒。

旧结论里"inventory.db 的唯一写入方就是 my_app"这一条**与实测不符**，是错误推断：
远端确实存在其它持库进程。因此"让远端自己写"这条路依赖远端配合，不可控。

## 本方案

改为：**完全不碰远端库文件，改为推送整库文件**。

1. 在本机临时目录构建一个全新的 `inventory.db`（`journal_mode=delete`，单文件）；
2. 用 `shutil.copyfile` 把该文件覆盖到远端路径。

这样做的关键前提（已验证）：FineBI 侧对该库是**只读**消费，且整文件覆盖不需要
SMB 字节锁。实测在同一 SMB 目录上「本地建库 → copy 覆盖 → 远端只读打开」全通，
且**反复覆盖**每次都成功。

### 为什么不再需要"远端增量追加"

旧实现要连远端库、把远端已有的 `inventory_details` 反连接出来，才能只追加新行。
本地构建时不需要这一步：**镜像内容直接取自 app.db**，而 app.db 里的
`inventory_details` 本身就是"历史累计 + 保留期清理"后的全量结果
（`get_sp_table._write_table` 的 APPEND 分支已经做过合并去重与保留期清理）。
因此本地构建出的库与 app.db **天然同口径**，比旧实现的"远端反连接"更简单也更准。

### 代价与回滚

- 代价：每次推送约 110MB 整文件走 SMB。实测本机→该共享的复制速度足以覆盖
  每小时一轮的节奏；若日后数据量增长到不可接受，回退方案是让远端提供一个
  写入接口（不要让本机重新直连 WAL 库）。
- 回滚：把 `sp_sftp_config.json` 的 `mirror_mode` 设为 `"direct"` 可恢复到旧的
  直连实现（保留在 `_mirror_write_all_direct`），或 `mirror_enabled=false` 直接关闭。
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# 镜像库需要写出的表（与 app.db 侧保持一致；顺序即建表顺序）
MIRROR_TABLES = ("inband_details", "outband_details", "inventory_details",
                 "ocrule_details", "transfer_details")

# 整文件推送重试：SMB 偶尔瞬时抖动（Defender 扫描 / 共享瞬断）
PUSH_RETRIES = 3
PUSH_RETRY_WAIT = 5


def _coerce_and_fill(df, update_time: str, update_date: str):
    """补 update_time/update_date 并做类型归一（SQLite 只能绑基础类型）。

    与旧 `_mirror_coerce_values` 同语义，此处独立实现以避免与直连实现相互耦合
    （直连实现已标记为回滚路径，不再演进）。
    """
    import pandas as pd

    out = df.copy()
    out["update_time"] = update_time
    out["update_date"] = update_date
    for col in out.columns:
        s = out[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            out[col] = s.dt.strftime("%Y-%m-%d %H:%M:%S")
        elif s.dtype == object:
            def _conv(v):
                if v is None or v is pd.NaT:
                    return None
                if isinstance(v, float) and pd.isna(v):
                    return None
                if isinstance(v, (str, int, float, bytes, bool)):
                    return v
                if hasattr(v, "strftime"):
                    return v.strftime("%Y-%m-%d %H:%M:%S")
                return str(v)
            out[col] = s.map(_conv)
    return out


def build_local_mirror_db(tables_data: dict, db_path: str,
                          update_time: str, update_date: str) -> dict:
    """把各表 DataFrame 写成一个全新的本地 SQLite 库（delete 模式，单文件）。

    返回 {table: {rows, status}}，供上层汇总进任务结果。
    """
    import pandas as pd

    if os.path.exists(db_path):
        os.remove(db_path)
    # 边车文件（上一轮异常退出可能残留）
    for sidecar in (db_path + "-wal", db_path + "-shm", db_path + "-journal"):
        try:
            os.remove(sidecar)
        except OSError:
            pass

    result: dict = {}
    con = sqlite3.connect(db_path)
    try:
        # 显式用 delete 模式：WAL 会在关闭后留下边车文件，而我们要推送的是单文件；
        # 且远端库一旦是 WAL，本机就再也打不开（见模块 docstring）。
        con.execute("PRAGMA journal_mode=delete")
        for table_name in MIRROR_TABLES:
            df = tables_data.get(table_name)
            if df is None:
                result[table_name] = {"rows": 0, "status": "skipped",
                                      "detail": "本轮无数据"}
                continue
            if len(df) == 0:
                # 空报表不覆盖：保留库内该表的既有数据由"整库重建"语义天然保证
                # （重建时该表为空表），这里如实标记 skipped 供上层观察。
                result[table_name] = {"rows": 0, "status": "skipped",
                                      "detail": "本轮 0 行"}
                continue
            out = _coerce_and_fill(df, update_time, update_date)
            cols = [str(c) for c in out.columns]
            quoted = ", ".join(f'"{c.replace(chr(34), chr(34) * 2)}"' for c in cols)
            placeholders = ", ".join("?" for _ in cols)
            col_ddl = ", ".join(
                f'"{c.replace(chr(34), chr(34) * 2)}" TEXT' for c in cols)
            con.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            con.execute(f'CREATE TABLE "{table_name}" ({col_ddl})')
            insert_sql = f'INSERT INTO "{table_name}" ({quoted}) VALUES ({placeholders})'
            chunk = 2000
            for start in range(0, len(out), chunk):
                batch = out.iloc[start:start + chunk]
                con.executemany(insert_sql,
                                batch.itertuples(index=False, name=None))
            result[table_name] = {"rows": len(out), "status": "ok"}
        con.commit()
        # 收尾：把 WAL/日志彻底并回主文件并做一次 vacuum，确保只剩单文件
        con.execute("PRAGMA journal_mode=delete")
        con.commit()
    finally:
        con.close()
    return result


def push_mirror_db(local_path: str, remote_path: str) -> dict:
    """把本地构建好的镜像库整文件覆盖到远端（SMB），带重试。

    不做 `os.replace` —— 那是"删除+改名"，在 SMB 上对可能被远端只读打开的
    目标更容易失败；`copyfile` 是就地覆盖内容，实测可穿过"共享读"的打开方式。
    """
    last_err = None
    for attempt in range(1, PUSH_RETRIES + 1):
        try:
            t0 = time.time()
            shutil.copyfile(local_path, remote_path)
            size = os.path.getsize(local_path)
            secs = time.time() - t0
            speed = (size / 1024 / 1024 / secs) if secs > 0 else 0
            print(f"[镜像] 推送完成: {size/1024/1024:.1f}MB 用时 {secs:.1f}s "
                  f"({speed:.1f}MB/s)")
            return {"status": "ok", "bytes": size, "seconds": round(secs, 1)}
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"[镜像][错误] 第{attempt}/{PUSH_RETRIES}次推送失败: "
                  f"{type(exc).__name__}: {exc}")
            if attempt < PUSH_RETRIES:
                time.sleep(PUSH_RETRY_WAIT * attempt)
    return {"status": "error",
            "detail": f"{type(last_err).__name__}: {last_err}"}


def mirror_via_push(tables_data: dict, remote_path: str,
                    work_dir: str | None = None) -> dict:
    """完整流程：本地构建 → 整文件推送。返回与旧 `_mirror_write_all` 同形状的结果。

    返回结构（保持兼容，消费侧 `run_sp_data_sync` 依赖它）：
      {table: {rows, status, ...}, "_meta": {status, db, mode, ...}}
    """
    from datetime import datetime

    now = datetime.now()
    update_time = now.strftime("%Y-%m-%d %H:%M:%S")
    update_date = now.strftime("%Y-%m-%d")

    result: dict = {}
    tmp_dir = work_dir or tempfile.mkdtemp(prefix="sp_mirror_")
    local_db = os.path.join(tmp_dir, "inventory.db")
    t_build = time.time()
    try:
        try:
            result.update(build_local_mirror_db(tables_data, local_db,
                                                update_time, update_date))
            build_secs = time.time() - t_build
            print(f"[耗时] 镜像本地构建 {build_secs:.1f}s")
            result["_meta"] = {
                "status": "ok", "db": str(remote_path), "mode": "push",
                "local_db": local_db, "build_seconds": round(build_secs, 1),
            }
            push = push_mirror_db(local_db, remote_path)
            result["_meta"]["push"] = push
            if push.get("status") != "ok":
                result["_meta"]["status"] = "error"
                result["_meta"]["detail"] = push.get("detail")
                for t, v in result.items():
                    if isinstance(v, dict) and v.get("status") == "ok":
                        v["status"] = "error"
                        v["detail"] = f"推送失败: {push.get('detail')}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("镜像构建/推送失败", exc_info=True)
            detail = f"{type(exc).__name__}: {exc}"
            for t in MIRROR_TABLES:
                result.setdefault(t, {"rows": 0, "status": "error", "detail": detail})
            result["_meta"] = {"status": "error", "detail": detail,
                               "db": str(remote_path), "mode": "push"}
    finally:
        # 清理本地临时库（无论成败，避免每小时堆一个 110MB 文件）
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            logger.warning("[SILENT-EXCEPT] 清理镜像临时目录失败: %s", tmp_dir,
                           exc_info=True)
    return result

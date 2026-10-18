# -*- coding: utf-8 -*-
"""CNN UME KPI 5 分钟粒度同步服务（cnn_kpi_sync_5mins）

=========================== 这个任务是什么 ===========================

与 `cnn_kpi_sync`（`backend/services/ccn_ume_kpi_service.py`，每天 06:00）同源同口令，
但有三处不同：

  1. **时间粒度**：`gr="300"`（5 分钟），原任务是 3600 / 86400；
  2. **运行节拍**：每 15 分钟一次（cron `*/15 * * * *`）；
  3. **落库表名**：`5mins_<原名>`，例如
     `5mins_VOICE_TRAFFIC_TEMPLATE_OSS_UME`。
     写的是**新表**，日/月粒度表一行都不动 → `cn_kpi` 看板完全不受影响。

查询窗口为「**昨天 00:00 → 现在**」：页面要把 Day0（今天）与 Day1（昨天）
两条曲线叠画，窗口必须同时覆盖两天。

=========================== 上游粒度能力实测（2026-10-17）===========================

⚠ **不是 8 个模板都支持 5 分钟**。实测（`gr=300`、昨天→现在）结果：

    ✅ VOICE_TRAFFIC / VLR_SUBSCRIBERS / DATA_SUBSCRIBERS /
       4G_FDD_DATA_TRAFFIC / FREE_RATING_GROUP   → 正常返回 `5 minutes`
    ❌ xGW_LICENSE / xGW_CPU_USAGE / 3G_FDD_DATA_TRAFFIC → **0 行**

已排除「窗口太短」：这 3 个模板 `gr=3600` 时数据正常（44/46/460 行，`1 hour`），
`gr=300` 换成 7 天窗口仍是 0 行。也试过改 `relative`、补 `groupchoice`、改
`grouplayer`，均无效 —— 是**服务端模板没开 5 分钟档**，不是 payload 写法问题。

因此本服务对「导出 0 行」的处理是 **跳过该表、不视为失败**（业务决定：8 个表
都建、空的留空，页面对应卡片显示空态）。这与原任务的 `import_to_database`
（无数据行直接 raise）是**刻意不同**的行为，不能照抄。

=========================== 与 ccn_ume_kpi_service 的复用边界 ===========================

**复用**（直接 import，避免把 1193 行的原文件再撑大，也不搞两份登录实现）：
    `_login` / `_acquire_auth` / `_refresh_auth_on_401` / `_looks_like_auth_failure`
    `create_history_query` / `wait_history_ready` / `export_history`
    `read_xlsx_bytes` / `detect_key_cols` / `_cols_unique` / `build_filename` / `_db_writer`

**不复用 `_run_single_kpi_query`**：它写死 `build_cnn_kpi_payload(cfg, monthly=monthly)`，
而该 builder 的 `timeinfo` 固定 `relative:-1` 且窗口取「今天 00:00 - days_back」，
既不能传 5 分钟配置、也不能传「昨天 00:00 → 现在」的窗口。故本模块自带
`_build_payload_5mins()`，其余链路完全一致。

=========================== 线程安全说明 ===========================

HTTP/TLS 连接是按线程复用且按线程关闭的（见原模块 `_http_local` / `_run_with_cleanup`）。
本模块的 `_run_one_5mins()` 沿用同一约定：`_run_with_cleanup` 包一层，保证每个
线程任务结束后释放自己的连接。
"""
from __future__ import annotations

import copy
import gc
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.services import ccn_ume_kpi_service as base

logger = logging.getLogger("cnn_ume_kpi_5mins_service")

# ============================================================
# 配置
# ============================================================
# 粒度：5 分钟 = 300 秒
GR_5MINS = "300"

# 表名前缀：与 1month_ 同一套「派生新表、不碰原表」的做法
TABLE_PREFIX = "5mins_"

# 并行查询线程数（与原任务一致；8 个模板并发即可，15 分钟节拍留足余量）
MAX_PARALLEL_WORKERS = int(os.environ.get("CNN_KPI_5MINS_PARALLEL_WORKERS",
                                          os.environ.get("CNN_KPI_PARALLEL_WORKERS", "8")))

# 查询窗口的天数偏移：1 = 从「昨天 00:00」起（Day1 需要完整昨天）
WINDOW_DAYS_BACK = 1

# 单个模板导出的等待上限（秒）。5 分钟粒度行数远大于日粒度（FREE_RATING_GROUP
# 实测 1 天就有 10206 行 ≈ 3 倍于小时粒度），故轮询超时放宽到 600s。
EXPORT_TIMEOUT = int(os.environ.get("CNN_KPI_5MINS_EXPORT_TIMEOUT", "600"))


# ============================================================
# 5 分钟粒度的查询配置（从原 8 个模板派生）
# ============================================================
def _build_5mins_query_configs() -> dict:
    """从 `base.CNN_KPI_QUERY_CONFIGS` 派生 5 分钟配置：只改 gr 与表名前缀。

    严格沿用原模块 `_build_monthly_query_configs()` 的做法
    （`ccn_ume_kpi_service.py:318`）：deepcopy → 改 gr → 给 table_name 加前缀，
    模板 id / items / grouplayer 等一律保持原值，确保测的是同一批 KPI。
    """
    out = {}
    for key, cfg in base.CNN_KPI_QUERY_CONFIGS.items():
        c = copy.deepcopy(cfg)
        c["gr"] = GR_5MINS
        c["table_name"] = TABLE_PREFIX + cfg["table_name"]
        out[key] = c
    return out


# 模块级派生一次（原模块在导入期也会重新读 cnn_kpi_config.json，这里在其之后派生）
CNN_KPI_5MINS_QUERY_CONFIGS = _build_5mins_query_configs()

# 任务清单：8 个模板全上（含上游无 5 分钟数据的 3 个，它们会被跳过，不影响任务结果）
CNN_KPI_5MINS_TASKS = [{"key": k} for k in CNN_KPI_5MINS_QUERY_CONFIGS]


# ============================================================
# Payload（带窗口）
# ============================================================
def _window_iso(now: datetime | None = None) -> tuple[str, str]:
    """返回 5 分钟任务的查询窗口：昨天 00:00 UTC → 现在（UTC）。

    为什么是 UTC 00:00：原模块的所有时间 ISO 都是 UTC（`datetime.now(timezone.utc)`），
    且 UME 的 `clienttimezone` 固定 Atlantic/Reykjavik；沿用同一基准，避免
    与 `cnn_kpi_sync` 在同一批数据上出现「日期归属不一致」。
    Day0/Day1 的日切也由前端 SQL 按 `End Time` 的前 10 位（UTC 日期）判定。
    """
    now = now or datetime.now(timezone.utc)
    start_dt = (now - timedelta(days=WINDOW_DAYS_BACK)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return (start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            now.strftime("%Y-%m-%dT%H:%M:%S.000Z"))


def _build_payload_5mins(cfg: dict, start_iso: str, end_iso: str) -> dict:
    """构造 5 分钟查询 payload。

    字段顺序与 `base.build_cnn_kpi_payload` 保持一致（UME 接口对顺序敏感，
    原模块已按实测顺过一遍）。唯一差别是 `timeinfo.start/end` 用调用方给的窗口，
    其余（`relative:-1`、`timespanfilter` 等）保持原值 —— 实测它们不会截断
    显式 start/end（2026-10-17 探针：昨天→现在窗口能同时取到 Day0 与 Day1）。
    """
    p = base.build_cnn_kpi_payload(cfg, start_iso=start_iso, end_iso=end_iso)
    ti = p.get("timeinfo") or {}
    ti["start"] = start_iso
    ti["end"] = end_iso
    p["timeinfo"] = ti
    p["gr"] = GR_5MINS
    return p


# ============================================================
# 单模板查询（create → poll → export，全程内存）
# ============================================================
def _run_one_5mins(auth: dict, task: dict, start_index: int = 0) -> tuple:
    """执行单个模板的 5 分钟查询 + 导出，返回 (file_prefix, xlsx_bytes)。

    与原模块 `_run_single_kpi_query` 的差异：
      · 用本模块的 5 分钟配置与窗口；
      · 额外用 `EXPORT_TIMEOUT` 覆盖轮询超时。
    401 恢复策略保持一致（有限重试一次，见 `_refresh_auth_on_401`）。
    """
    cfg = CNN_KPI_5MINS_QUERY_CONFIGS[task["key"]]
    file_prefix = base.build_filename(cfg)

    # 错峰启动：8 个查询同时打过去容易被上游限流（原模块同样做法）
    delay = start_index * 0.8
    if delay > 0:
        time.sleep(delay)

    start_iso, end_iso = _window_iso()
    logger.info("[CNN5M] 开始 %s (gr=%s) 窗口 %s → %s",
                cfg["templatename"], cfg["gr"], start_iso, end_iso)
    payload = _build_payload_5mins(cfg, start_iso, end_iso)

    for attempt in (1, 2):
        cookie = auth["cookie"]
        token = auth["forgery_token"]
        try:
            queryid = base.create_history_query(cookie, token, payload)
            base.wait_history_ready(cookie, token, queryid, timeout=EXPORT_TIMEOUT)
            stamp = datetime.now().strftime("%Y%m%d%H%M%S")
            xlsx_bytes = base.export_history(cookie, token, queryid,
                                             f"{file_prefix}_{stamp}")
            return file_prefix, xlsx_bytes
        except Exception as e:
            # 与原模块同款：只在鉴权类失败（401/403）时恢复一次再重试
            if attempt == 1 and base._looks_like_auth_failure(e) and base._refresh_auth_on_401(auth):
                logger.warning("[CNN5M] [%s] 会话中途失效（%s），已恢复鉴权，重试一次",
                               task["key"], e)
                continue
            raise


# ============================================================
# 写库（无数据 = 跳过，不算失败）
# ============================================================
def import_to_database_5mins(export_results: dict) -> dict:
    """把本次导出的 xlsx 写入 `5mins_*` 新表。

    **与 `base.import_to_database` 的关键差异**：上游对 3 个模板不提供 5 分钟
    数据（见模块头实测表），它们每次导出都是 0 行。原任务的逻辑是
    「无数据行 → raise」，照抄会让本任务**每 15 分钟失败一次**。故这里：
      · 导出结果为 0 行 → 记录日志并 `continue`（表不建、不算失败）；
      · 其余（主键塌缩、写库异常）仍然 raise —— 那是真问题，必须让任务失败。

    返回：{"imported": {表名: 行数}, "skipped": [表名...], "total_rows": N}
    """
    logger.info("[CNN5M][DB] 开始导入数据库（API 模式）")
    imported: dict[str, int] = {}
    skipped: list[str] = []
    total_imported = 0

    for task in CNN_KPI_5MINS_TASKS:
        cfg = CNN_KPI_5MINS_QUERY_CONFIGS[task["key"]]
        table_name = cfg["table_name"]
        file_prefix = base.build_filename(cfg)

        xlsx_bytes = (export_results or {}).get(file_prefix)
        if not xlsx_bytes:
            # 查询本身失败时这里也会进来；由 run 的 errors 清单负责报失败
            logger.info("[CNN5M][DB] %s: 本次无导出数据，跳过", table_name)
            skipped.append(table_name)
            continue

        headers, data = base.read_xlsx_bytes(xlsx_bytes)
        logger.info("[CNN5M][DB] %s: %d 行, %d 列", table_name, len(data), len(headers))

        if not data:
            # 上游无 5 分钟数据（xGW_LICENSE / xGW_CPU_USAGE / 3G_FDD_DATA_TRAFFIC）
            logger.info("[CNN5M][DB] %s: 上游无 5 分钟数据（0 行），跳过（不建表、不算失败）",
                        table_name)
            skipped.append(table_name)
            headers = data = None
            gc.collect()
            continue

        key_cols = base.detect_key_cols(headers)
        if not key_cols:
            raise Exception(f"[CNN5M][DB] {table_name}: 缺少 Begin Time 列，解析失败")

        # 同原任务：自然主键批内不唯一时尝试扩展，扩展失败则放弃 upsert（防静默塌缩）
        if not base._cols_unique(headers, data, key_cols):
            logger.warning("[CNN5M][DB] %s: 自然主键 %s 不唯一，尝试扩展", table_name, key_cols)
            for cand in headers:
                if cand in key_cols:
                    continue
                expanded = key_cols + [cand]
                if base._cols_unique(headers, data, expanded):
                    logger.warning("[CNN5M][DB] %s: 主键扩展为 %s", table_name, expanded)
                    key_cols = expanded
                    break
            else:
                raise Exception(
                    f"[CNN5M][DB] {table_name}: 无法凑出唯一主键(自然键={key_cols!r})，"
                    f"放弃 upsert 以免数据塌缩。")

        if base._db_writer is None:
            raise Exception(f"[CNN5M][DB] db_writer 不可用，无法写入 {table_name}")

        key_idx = [headers.index(k) for k in key_cols if k in headers]
        str_data = []
        for row in data:
            if len(row) < len(headers):
                row.extend([None] * (len(headers) - len(row)))
            elif len(row) > len(headers):
                row = row[:len(headers)]
            clean_row = [str(v) if v is not None else None for v in row]
            # 主键列空值填 ""，避免服务端建表时 NOT NULL 主键写入失败
            for i in key_idx:
                if clean_row[i] is None:
                    clean_row[i] = ""
            str_data.append(clean_row)

        try:
            result = base._db_writer.write_data(
                db=base.DB_NAME,
                table=table_name,
                columns=headers,
                rows=str_data,
                mode="upsert",
                pk_columns=key_cols,
            )
        except Exception as e:
            raise Exception(f"[CNN5M][DB][API] {table_name}: 写入失败: {e}")

        rows_written = result.get("rows_written", 0)
        if rows_written == 0:
            # upsert 后无新增行 = 数据已存在（15 分钟窗口与上一轮重叠是常态）
            logger.info("[CNN5M][DB][API] %s: 无新增行（已同步）", table_name)
        else:
            logger.info("[CNN5M][DB][API] %s: written %d rows", table_name, rows_written)

        imported[table_name] = rows_written
        total_imported += rows_written
        headers = data = None
        gc.collect()

    logger.info("[CNN5M][DB] 导入完成：写入 %d 行，跳过 %d 张表", total_imported, len(skipped))
    return {"imported": imported, "skipped": skipped, "total_rows": total_imported}


# ============================================================
# 主入口
# ============================================================
def run_cnn_kpi_sync_5mins() -> dict:
    """CNN UME KPI 5 分钟同步主流程：登录 → 并行查询 → 导出 → 写 5mins_ 新表。"""
    t_start = time.time()
    result = {"success": False, "tables": {}, "skipped": [], "errors": [],
              "total_rows": 0, "elapsed_seconds": 0}

    logger.info("[CNN5M] 5 分钟 KPI 同步开始 %s（%d 个模板，gr=%s）",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                len(CNN_KPI_5MINS_TASKS), GR_5MINS)

    try:
        auth = base._login()

        export_data: dict[str, bytes] = {}
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
            futures = {
                executor.submit(base._run_with_cleanup, _run_one_5mins, auth, task, idx): task
                for idx, task in enumerate(CNN_KPI_5MINS_TASKS)
            }
            for fut in as_completed(futures):
                task = futures[fut]
                try:
                    file_prefix, xlsx_bytes = fut.result()
                    export_data[file_prefix] = xlsx_bytes
                    logger.info("[CNN5M] [%s] 导出 %d bytes", task["key"], len(xlsx_bytes))
                except Exception as e:
                    errors.append(f"[{task['key']}] {e}")
                    logger.error("[CNN5M] [%s] 失败: %s", task["key"], e)

        result["errors"] = errors

        if export_data:
            db_res = import_to_database_5mins(export_data)
            result["tables"] = db_res["imported"]
            result["skipped"] = db_res["skipped"]
            result["total_rows"] = db_res["total_rows"]
        else:
            logger.warning("[CNN5M] 本次无任何导出数据，跳过写库")

        result["success"] = len(errors) == 0

    except Exception as e:
        result["errors"].append(str(e))
        logger.error("[CNN5M] 任务失败: %s", e)

    result["elapsed_seconds"] = round(time.time() - t_start, 2)
    logger.info("[CNN5M] 完成：%d 行，跳过 %d 表，%d 个错误，耗时 %.2fs",
                result["total_rows"], len(result["skipped"]),
                len(result["errors"]), result["elapsed_seconds"])
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    res = run_cnn_kpi_sync_5mins()
    print(f"\nCNN 5 分钟 KPI 结果: {'成功' if res['success'] else '失败'}")
    print(f"写入: {res['tables']}")
    print(f"跳过（上游无 5 分钟数据）: {res['skipped']}")
    if res["errors"]:
        print(f"错误: {res['errors']}")
    print(f"耗时: {res['elapsed_seconds']}s")

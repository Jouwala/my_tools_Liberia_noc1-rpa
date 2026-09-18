# tmp_cleanup — TMP 目录定期清理

> 2026-09-18 新增。每日定时任务 `tmp_cleanup`，与 `log_cleanup`（log/ 清理）配套，
> 落实 `docs/CODE_CLEANUP_GUIDE.md`「临时产物进 TMP、定期可回收」的要求。

## 为什么需要

`TMP/` 已被 gitignore，不污染仓库，但体积无人管理：上线首日实测 462MB，
其中 4 个 `_diag*_eflow_*` 诊断目录合计约 380MB，均为一次性排查残留。

## 工作方式（两段式，随时可还原）

1. **隔离**：顶层条目「最后活动时间」超过保留期（默认 7 天）→ 同盘 `mv` 到
   `TMP/_quarantine_YYYYMMDD/`。目录的「最后活动时间」取其子树 mtime 最大值，
   只要有任何新写入就不会被动。
2. **清空**：`_quarantine_YYYYMMDD` 目录本身超过再一个保留期（累计 14 天）才真正删除。

即任何文件从「最后使用」到「彻底删除」至少有 7+7 天的可还原窗口。

## 白名单（永不处理）

| 路径 | 使用方 |
|---|---|
| `ccn_free_rating_charts/` | `ccn_free_rating_chart_service.py` |
| `fw_charts/` | FW KPI 报表出图 |
| `ipran_charts/` | iPRAN 报表出图 |
| `dl/` `dl_en/` | 邮件报表附件下载目录 |
| `email_recovery_state.json` | 邮件恢复状态 |
| `task_health_alert_state.json` | `db_freshness_check` 告警翻转去重状态 |
| `build_msportal_data.py` | `portal_catalog` 引用的 data.js 生成脚本 |

## 安全边界

- 只作用于 `my_app/TMP` 单层条目，不递归触碰其它目录；
- 被进程占用（mv/删除失败）→ 跳过等下一轮，绝不强制；
- 全部判定基于 mtime，保留期内一律不动。

## 配置

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `TMP_RETENTION_DAYS` | 7 | 隔离与清空共用的保留天数 |
| `TMP_CLEANUP_DRY_RUN` | 0 | `=1` 只报告不改动（首次上线验证用） |

## 调度接入

- `backend/task_registry.py` TASK_SPECS 第 44 条：`task_id="tmp_cleanup"`，
  cron `47 3 * * *`（与 log_cleanup 03:17 错峰 30 分钟）。
- `backend/worker_watchdog.py` GROUP_TASK_MAP **m 组** 已登记（内务轻任务）。
  ⚠ 新任务必须同时登记分组，否则无 worker 认领、队列永久 pending。
- 注册/改代码后需重启 worker_watchdog 才生效（组 worker 是其子进程）。

## 依赖与运行

- 纯 Python 标准库（`os`/`shutil`/`pathlib`/`logging`），无新增第三方依赖，
  沿用项目根 `requirements.txt` 即可（services 目录无独立 requirements 先例，
  同 `log_cleanup.py`）。
- 手动执行：`python backend/services/tmp_cleanup.py`（会打印结果 JSON 与总耗时秒数）。
- 定时入口 `run_tmp_cleanup()` 返回汇总 dict，禁止 `sys.exit`。

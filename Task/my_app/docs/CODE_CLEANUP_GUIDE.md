# 代码清洁规范（my_app）

> 2026-09-13 首次全量清洁后整理。目标：让工作区里**只剩源码和配置**，
> 所有临时产物都有固定去处，并且随时可回收。

## 1. 三条底线

1. **临时产物不进源码树根**。截图、抓包 JSON、一次性探针脚本一律放 `TMP/`，
   不要丢在项目根目录。根目录只允许出现：源码目录、配置、启动/停止脚本、文档。
2. **临时文件必须可识别**。命名加前缀 `_`（个人探针）或 `t_`（一次性验证），
   便于批量扫描和回收。永远不要用 `routes` / `send` / `reload` 这类
   **会与真实命令同名**的文件名 —— 曾经就是命令重定向误建出这三个文件。
3. **每季度归档一次**。用 `_myapp_trash_YYYYMMDD` 同盘归档，确认无影响后再整体删除。
   **不要直接 `rm`**，也不要在归档前删除。

## 2. 目录归属表

| 路径 | 性质 | 可否清理 |
|---|---|---|
| `backend/` `frontend/src/` `docs/` `alembic/` | 源码 | 否 |
| `TMP/` | 临时产物（服务也用） | 清理其中内容，**保留** `ccn_free_rating_charts/` `fw_charts/` `ipran_charts/` `email_recovery_state.json` |
| `outputs/` | 交付样例 / 预览 | 可清调试产物，保留正式交付文件 |
| `data/portal_profiles/_tmp_*` | Chrome 临时 profile | 可清理（异常退出残留） |
| `log/` | 运行日志 | 归档带日期且已关闭的旧日志 |
| `**/__pycache__/` `*.pyc` | 编译缓存 | 可清理，自动重建 |
| `db/` `data/*.sqlite3` | 业务数据 | **否** |
| `Lib/` `Scripts/` | 项目内 venv | 否 |

## 3. 命名约定

| 用途 | 约定 | 示例 |
|---|---|---|
| 个人探针脚本 | 放 `TMP/`，前缀 `_` | `TMP/_probe_sp_online3.py` |
| 一次性验证脚本 | 放 `TMP/`，前缀 `t_` | `TMP/t_ready_probe.py` |
| 抓包 / 中间结果 | 放 `TMP/`，`.json` | `TMP/oa.json` |
| 截图 | 放 `TMP/`，语义化名 | `TMP/portal_login_rais_card.png` |
| 正式交付 | 放 `outputs/`，**无前缀** | `outputs/SP_Material_Summary_统一格式示例.xlsx` |

## 4. `.gitignore`（2026-09-13 已补充）

`TMP/`、`log/`、`data/portal_profiles/` 此前是**未跟踪但也没被忽略**的状态，
会把 `git status` 刷屏。现已在 `.gitignore` 追加：

```gitignore
# 临时产物目录（截图 / 抓包 / 一次性探针脚本 / Chrome 临时 profile）
# 服务在用的 TMP/ccn_free_rating_charts、fw_charts、ipran_charts、email_recovery_state.json
# 同属运行时产出，一并忽略。
/TMP/

# 代码清洁归档目录（同盘移动，确认无碍后整体删除）
/_myapp_trash_*/

# 误建的空 sqlite 占位（真正库是 /db/app.db）
/backend/app.db

# Chrome 临时 profile（portal_login_service 正常退出时会自清，异常退出会残留）
/data/portal_profiles/_tmp_*/
```

`/db/`、`/log/` 已在原有 `.gitignore` 中。

## 5. 每月自检清单

```bash
cd /d/01_RPA/Task/my_app

# 1) 根目录是否出现新的散落文件（源码/配置白名单之外）
ls -1 | grep -vE '^(backend|frontend|docs|data|db|log|TMP|tests|outputs|Lib|Scripts|include|alembic|monitor_fixes|whatsapp_sender_extension|whatsapp_session|email_reports|nginx|\.|_myapp_trash|CREDENTIALS|PROJECT_DOCS|requirements|start|stop|fix_backend|restart_workers|mw_links_sync|pyvenv|reload|routes|send)'

# 2) 临时 profile 是否堆积
ls -d data/portal_profiles/_tmp_* 2>/dev/null | wc -l

# 3) TMP 顶层文件数（正常应 < 30，因为服务只写 4 个子路径）
ls TMP | wc -l

# 4) 旧日志
ls log/*_2026*.log | wc -l
```

任一项异常增长，就跑一次归档脚本（见 `D:\01_RPA\_cleanup_20260913.sh` 的模板）。

## 6. 归档脚本模板

归档 = **同盘 `mv` 到 `D:\01_RPA\_myapp_trash_YYYYMMDD\<分类桶>\<原相对路径>`**，
同时写 `manifest_full.tsv`。同盘移动是重命名，秒级完成且 100% 可还原。
还原脚本：`D:\01_RPA\_myapp_restore_YYYYMMDD.sh`。

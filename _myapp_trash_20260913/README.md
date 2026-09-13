# my_app 清理归档 — 2026-09-13

本目录是 2026-09-13 对 `D:\01_RPA\Task\my_app` 做代码清洁时**同盘移动**出来的文件。
**没有做任何永久删除**，全部可原样还原。

## 归档结构（镜像原相对路径）

```
_myapp_trash_20260913/
├── A_root_junk/         根目录碎片、调试脚本、空文件          (15 项,  53 KB)
├── B_portal_profiles/   Chrome 临时 profile 残留              ( 6 项, 962 MB)
├── B_tmp/               TMP/ 下的调试产物                     (487 项, 771 MB)
├── B_outputs/           outputs/ 下的调试产物                 (14 项, 3.1 MB)
├── C_pycache/           __pycache__ 编译缓存                  (20 项, 5.0 MB)
├── D_logs/              2026-09-10 / 09-11 的旧日志           (12 项,  57 MB)
├── manifest_full.tsv    完整搬移清单（bucket / 原相对路径 / 类型）
├── manifest.tsv         脚本运行时的逐条记录
└── README.md            本文件
```

合计约 **1.8 GB**，554 个搬移单元。

## 还原方法

归档目录**镜像了原始相对路径**，例如
`B_tmp/TMP/_probe_sp_online3.py` 的原位置就是 `my_app/TMP/_probe_sp_online3.py`。

一键全部还原：

```bash
bash D:/01_RPA/_myapp_restore_20260913.sh
```

只还原某个桶（例如只想找回根目录脚本）：

```bash
bash D:/01_RPA/_myapp_restore_20260913.sh A_root_junk
```

脚本对已存在的文件会跳过，不会覆盖。

## 分类依据

- **A_root_junk** — `routes`/`send`/`reload` 是 2026-09-11 17:14 同一秒误建的命令输出碎片；
  9 个 `_*.py` 调试脚本全项目零引用；2 个 0 字节空文件。**其中 25 个文件曾被 git 跟踪，
  也可用 `git checkout <path>` 从历史恢复。**
- **B_portal_profiles** — `portal_login_service.py` 注释明确「退出时同步清理临时 profile」，
  这批 `_tmp_*` 是异常退出后的残留。搬移前已核实无 Chrome 进程占用。
- **B_tmp** — 截图 / JSON 抓包 / 一次性探针脚本 / 临时 Chrome profile。
  已**保留**服务在用的 `TMP/ccn_free_rating_charts`、`TMP/fw_charts`、`TMP/ipran_charts`、
  `TMP/email_recovery_state.json`。
- **B_outputs** — 0 字节失败产物 + 调试预览。已保留 `SP_Material_Summary_统一格式示例.xlsx`。
- **C_pycache** — Python 编译缓存，导入时自动重建。
- **D_logs** — 带日期且已关闭的旧日志；当天日志与心跳/pid 文件均保留。

## 未处理项（有意保留）

- `db/app.db`(1.5 GB)、`data/ran_kpi_avalability_1day.sqlite3`(757 MB) — 业务数据
- `Lib/`、`Scripts/` — 项目内 venv
- `tests/`、`monitor_fixes/` — 可能有参考价值
- 清理期间（10:00–10:07）**新生成**的 eFlow 调试产物 — 当时有会话正在使用

## 提醒

归档目录位于 `D:\01_RPA`（git 仓库内）。确认不再需要后建议整体删除，
或在 `.gitignore` 加一行 `/_myapp_trash_*/` 避免 git 噪声。

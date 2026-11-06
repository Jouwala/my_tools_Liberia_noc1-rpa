# SQLite 远程写入代理服务

## 概述

解决 SQLite WAL 模式数据库不能通过网络共享直接写入的问题。在数据库所在服务器（192.168.100.19）部署轻量 FastAPI 写入代理，本地 RPA 脚本通过 HTTP API 完成数据写入，替代原有 FTP 下载-本地修改-FTP 上传流程。

## 架构

本地 RPA 脚本 (db_writer_client.py) --HTTP--> 远程服务器 192.168.100.19 (db_writer_api.py:8765)
远程服务使用 threading.Lock 串行写入 -> db.sqlite3 (WAL) / ran_kpi_daily.sqlite3

## 文件说明

| 文件 | 部署位置 | 说明 |
|------|----------|------|
| db_writer_api.py | 远程 192.168.100.19 | FastAPI 写入服务 |
| db_writer_client.py | 本地 RPA 机器 | HTTP 客户端模块（纯标准库） |
| test_db_writer_api.py | 不部署 | 服务端改动的回归用例（见「回归测试」） |

## API 接口

### GET /health
健康检查，返回服务状态和数据库路径。

### POST /api/write
直接写入数据（JSON body）：
- db: 数据库名称
- table: 目标表名
- columns: 列名列表
- rows: 数据行列表
- mode: upsert（INSERT OR REPLACE）或 dedup_insert（按主键去重插入）
- pk_columns: 主键列

upsert 仅在目标表缺少 `u_<表名>` 唯一索引时执行一次历史去重并建索引；索引已存在时直接批量写入，不再重复全表 `DELETE`。客户端对 upsert 不做超时盲重试，避免服务端已提交但响应丢失时重复排队写入。

### POST /api/read
读取远端表数据；IPRAN 增量同步用 `order_by=<时间列> DESC&limit=1` 的等价 JSON 请求获取远端水位。远端水位不可用时调用方退化为全量 upsert，不使用本地兜底库水位代替。

**`columns` 一律传裸列名，不要自己加引号**：列名由服务端加引号（含空格的列如 `Begin Time` 不加引号就是语法错误），而调用方已经带引号时会被再包一层成 `""Begin Time""`，同样是语法错误。`where` 与 `order_by` 是原样拼接，要自己写引号。2026-11-05 打线上实测过这两种错，`db_freshness_check._api_window_max` 早年就踩过并留了注释。

**版本现状（2026-11-05 已对齐）**：线上跑的现役文件是 `Y:\01_RPA\db_writer_api.py`（网络映射，即 .19 的 `E:\01_RPA\`），此前版本 1.2.0，而本仓库那份还是 1.0.0 —— 线上比仓库新两轮。现已把 1.2.0 的内容**逐字节**取回并入本文件（在其上打改动，版本升为 **1.2.1**），所以**本文件就是唯一真相源**，不再存在「仓库落后于线上」的分叉。

**改动要落地 = 复制到 `Y:\01_RPA\db_writer_api.py` 并重启 8765**，具体步骤与风险见下面「部署步骤（远程服务器 .19）」一节。`GET /health` 能读到服务实际使用的库路径，例如 `db_ipran=E:\01_RPA\LBR_Tools\KPI\IPRAN\ipran_ume_kpi.sqlite3`。

### POST /api/upload_excel
上传 Excel 文件（multipart/form-data）：
- file: Excel 文件
- db: 数据库名称
- table: 目标表名
- table_type: Cells/Sites/Group/NW
- add_group_column: 是否添加 Group 列
- group_value: Group 列值

### GET /api/tables?db=xxx
列出数据库中所有表。

## 部署步骤（远程服务器 .19）

现役文件在 `E:\01_RPA\db_writer_api.py`，本机从网络映射看是 `Y:\01_RPA\db_writer_api.py`（`Y:` = `\\192.168.100.19\e`）。

1. 覆盖前先看线上文件有没有被改动过：`diff -u /y/01_RPA/db_writer_api.py db_writer_api.py`，只应看到本次的改动。
2. 留快照：线上同目录已有 `db_writer_api.py.bak_20260914` / `.bak_20261104` 的先例，按 `bak_<日期>` 命名继续留一份。
3. 复制本文件到 `Y:\01_RPA\db_writer_api.py`。
4. 重启 8765 服务：在 **.19 本机**（远程桌面）执行同目录的 `restart_8765_migration.bat`。它会打印 8765 上的 PID 与属主、`taskkill`，再用隐藏窗口拉起 `python db_writer_api.py`，日志重定向到 `dbw.out` / `dbw.err`，最后 curl `/api/dbs` 与 `/health` 自证。该脚本自带 UAC 提权且有 `pause`，**不能**从 .20 隔着映射盘跑。
   （旧脚本 `restart_api.bat` 用 `wmic` 猜进程、`cd /d Y:\01_RPA` 依赖映射盘，别再用它。）
5. 验证: `curl http://192.168.100.19:8765/health`，`version` 应为 `1.2.1`。

⚠ 第 4 步会中断 .19 上**所有**远程写入（FW / CCN / RAN / IPRAN / MS_SLA），必须取得确认后再做。

## 数据库路径配置

在 db_writer_api.py 顶部修改（2026-11-05 从线上 1.2.x 核实的实际值，键名 → 常量名）：
- DB_MAIN_PATH = C:\\FineBI6.0\\webapps\\Python\\db.sqlite3
- DB_DAILY_PATH = E:\\01_RPA\\LBR_Tools\\KPI\\RAN\\ran_kpi_daily.sqlite3
- DB_IPRAN_PATH = E:\\01_RPA\\LBR_Tools\\KPI\\IPRAN\\ipran_ume_kpi.sqlite3

逻辑库名 → 文件路径的映射是 `_BUILTIN_DB_MAP`，可被同目录 `db_map.json` 或环境变量 `DB_MAP_JSON` 指向的文件覆盖；本机自测服务时用这一点把逻辑名映射到临时 sqlite 文件，不需要碰线上库。

## 回退机制

所有调用方脚本保留 FTP 回退逻辑：
- 如果 db_writer_client 导入失败 -> 使用 FTP
- 如果 API 健康检查失败 -> 使用 FTP
- 如果 API 写入异常 -> 回退到本地写入 + FTP 上传

## 已改造的脚本

| 脚本 | 写入方式 | 回退 |
|------|----------|------|
| ran_ume_main_kpi.py | upload_excel -> API | FTP 下载/上传 |
| ran_ume_network_kpi.py | write_data -> API | 本地 write_to_db + FTP |
| excel2db.py | upload_excel -> API | 本地 sync + FTP |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| DB_WRITER_HOST | 192.168.100.19 | API 服务地址 |
| DB_WRITER_PORT | 8765 | API 服务端口 |

## 回归测试

在本目录执行 `python -m unittest test_db_writer_api.py -v`（5 个用例，纯标准库 + 内存 SQLite，不连接生产库）：

| 用例类 | 查什么 |
|--------|--------|
| `UpsertIndexMaintenanceTest` | 缺唯一索引时做一次历史去重并建索引；索引已存在时**不再**执行全表 `DELETE` |
| `ReadColumnClauseTest` | `/api/read` 的列片段由服务端加引号（`Begin Time` → `"Begin Time"`）、空列时是 `*`、名字里含 `"` 时翻倍转义而不是拼出语法错误 |

⚠ 根 `.gitignore:42` 有 `data_base/`，已跟踪的 10 个文件不受影响，但**新建在这个目录里的文件默认不会被 `git add` 收进来**。`test_db_writer_api.py` 是 2026-11-05 新建的，入库需要 `git add -f Task/data_base/test_db_writer_api.py`；忘记加就会「本地能跑、别人拉下来没有」。

## 运行时间

所有脚本均显示从开始到完成的运行时间（秒）。

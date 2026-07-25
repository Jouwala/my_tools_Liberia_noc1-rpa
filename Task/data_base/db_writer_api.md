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

## 部署步骤（远程服务器）

1. 复制 db_writer_api.py 到远程服务器 E:\\Python\\
2. pip install -r requirements.txt
3. python db_writer_api.py （监听 0.0.0.0:8765）
4. 验证: curl http://192.168.100.19:8765/health

## 数据库路径配置

在 db_writer_api.py 顶部修改：
- DB_MAIN_PATH = E:\\Python\\db.sqlite3
- DB_DAILY_PATH = E:\\01_RPA\\LBR_Tools\\KPI\\RAN\\ran_kpi_daily.sqlite3

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

## 运行时间

所有脚本均显示从开始到完成的运行时间（秒）。

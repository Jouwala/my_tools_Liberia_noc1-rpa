# RAN Cell Availability 1-Daily KPI 数据导入脚本（多进程并行版）

## 架构

```
csv模块(C实现)  ──┐
                   ├─→  ProcessPoolExecutor  ──→  Queue  ──→  SQLite Writer
calamine(Rust) ──┘     (N个Worker进程)        (进程间通信)   (独立写入进程)
```

## 功能说明
1. 从 Downloads 文件夹查找 `KPI_RPA_CELL_AVAIL_*` 的 zip/csv/xlsx 文件
2. ZIP 内文件自动解压到临时文件后由 calamine 读取
3. **多进程并行读取**：ProcessPoolExecutor + calamine (Rust引擎)
4. **Queue 解耦读写**：Reader 进程不等待 Writer，通过 Queue 传递数据批次
5. **独立 SQLite Writer 进程**：单连接单事务批量写入
6. 上传数据库到 FTP 服务器
7. 删除本地已处理的源文件

## 表名规则
- 表名 = `Daily_` + 文件名（不含扩展名）
- 示例：
  - `KPI_RPA_CELL_AVAIL_GSM1day_001.csv` → `Daily_KPI_RPA_CELL_AVAIL_GSM1day_001`
  - `KPI_RPA_CELL_AVAIL_FDD_Day_20260706.csv` → `Daily_KPI_RPA_CELL_AVAIL_FDD_Day_20260706`

## 配置
- **数据库文件**: `ran_kpi_avalability_1day.sqlite3`（脚本所在目录）
- **FTP**: `192.168.100.19`，用户 `ZTEEMS`，远程目录 `/01_RPA/LBR_Tools/KPI/RAN`
- **批量插入大小**: 50000 行/批
- **并行 Reader 进程数**: 4（MAX_WORKERS）
- **Queue 最大积压数**: 200（QUEUE_MAX，防内存溢出）

## 运行
```powershell
python ran_kpi_avalability_1day.py
```

## 依赖
```
pip install -r requirements.txt
```

## 运行时间统计
脚本启动时打印开始时间，结束时打印：
- 脚本开始/完成时间
- 总耗时（秒/分钟）
- 写入总行数
- 各阶段耗时（查找/读取写入/FTP）
# RAN Cell Availability 1-Daily KPI 数据导入脚本

## 功能说明
1. 从 Downloads 文件夹查找 `KPI_RPA_CELL_AVAIL_*` 的 zip/xlsx 文件
2. zip 内**所有 xlsx 文件**全部并行读取，每个 xlsx 对应一个独立的数据库表
3. 多线程并行读取 xlsx，单连接单事务顺序写入 SQLite（最快方案）
4. 上传数据库到 FTP 服务器
5. 删除本地已处理的 zip/xlsx 文件

## 表名规则
- 表名 = `Daily_` + xlsx文件名（不含 `.xlsx` 扩展名）
- 示例：
  - `KPI_RPA_CELL_AVAIL_GSM1day_001.xlsx` → `Daily_KPI_RPA_CELL_AVAIL_GSM1day_001`
  - `KPI_RPA_CELL_AVAIL_GSM1day_002.xlsx` → `Daily_KPI_RPA_CELL_AVAIL_GSM1day_002`
  - `KPI_RPA_CELL_AVAIL_FDD_Day_20260706.xlsx` → `Daily_KPI_RPA_CELL_AVAIL_FDD_Day_20260706`

## 配置
- **数据库文件**: `ran_kpi_avalability_1day.sqlite3`（脚本所在目录）
- **FTP**: `192.168.100.19`，用户 `ZTEEMS`，远程目录 `/01_RPA/LBR_Tools/KPI/RAN`
- **批量插入大小**: 5000 行/批
- **并行读取线程数**: 4

## 运行
```powershell
python ran_kpi_avalability_1day.py
```

## 依赖
```
pip install -r requirements.txt
```

## 运行时间统计
脚本启动时打印开始时间，结束时打印：
- 脚本开始/完成时间
- 总耗时（秒/分钟）
- 写入总行数
- 各阶段耗时（查找/读取/写入/FTP）

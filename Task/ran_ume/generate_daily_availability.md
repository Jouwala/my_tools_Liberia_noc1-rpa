# Daily Availability KPI 生成脚本

## 功能

1. 从 `ran_kpi_202606.sqlite3` 数据库读取 OLIB Network KPIs 数据
2. 提取 Cell Availability 指标，生成 `Daily_Aailability_KPI.xlsx`（含 4 个 Sheet）
3. 按仪表板样式生成折线图 PNG（与脚本同目录）
4. 自动上传图片到 FTP 服务器

## 输出

| 文件 | 说明 |
|------|------|
| `Daily_Aailability_KPI.xlsx` | 4 个 Sheet: NW / Regular / COOL / ERA |
| `Availability-NW.png` | ALL 组折线图 |
| `Availability-Regular.png` | Regular 组折线图 |
| `Availability-COOL.png` | Cooli 组折线图 |
| `Availability-ERA.png` | ERA 组折线图 |

## 使用方法

```bash
# 正常运行：生成 Excel + 图表 + FTP 上传
python generate_daily_availability.py

# 仅测试 FTP 连接
python generate_daily_availability.py --test-ftp
```

## FTP 配置

| 参数 | 值 |
|------|------|
| Host | 192.168.100.19:21 |
| User | ZTEEMS |
| Path | /01_RPA/LBR_Tools/KPI/RAN/ORANGE |

## 依赖

```bash
pip install -r requirements.txt
```

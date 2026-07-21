# ZTE OLR MS Contract KPIs & WOs Achievement Auto-Reports 自动更新说明文档

## 1. 概述

本脚本 `update_contract_kpis_report.py` 用于自动更新 Excel 文件 **ZTE OLR MS Contract KPIs & WOs Achievement Auto-Reports.xlsx** 中的两个 Sheet：

| Sheet 名称 | 内容 | 数据来源 |
|-----------|------|---------|
| **Contract KPIs Report (New)** | Operation KPIs + Network KPIs + PerSite KPIs | KPI List Excel + SQLite 数据库 |
| **WOs SLA achievement Report** | TTR 相关 SLA 达成统计 | KPI List Excel (SLA Daily/Monthly) |

更新完成后，自动将两个 Sheet 分别导出为独立 **xlsx**、**html**、**png** 文件，并上传到 FTP 服务器。

---

## 2. 执行流程

```
┌─────────────────────────────────────────────────────────┐
│  Step 0: FTP下载最新 KPI list - Operation.xlsx          │
│  (服务器: 192.168.100.19, 用户: FINEBI)                 │
│  远程路径: /webroot/WEB-INF/schedule/NUR_SLA/日期/       │
│           ID/通用结果/KPI list - Operation.xlsx          │
├─────────────────────────────────────────────────────────┤
│  Step 1: 读取 KPI List 数据                              │
│  - KPI List NUR Daily   → NUR 日度数据                   │
│  - KPI List NUR Monthly → NUR 月度数据                   │
│  - KPI List SLA Daily   → TTR 日度数据                   │
│  - KPI List SLA Monthly → TTR 月度数据                   │
├─────────────────────────────────────────────────────────┤
│  Step 2: 连接 SQLite 数据库 lbr_ms_sla_kpi.sqlite3       │
├─────────────────────────────────────────────────────────┤
│  Step 3: 更新 Contract KPIs Report (New)                 │
│  - 自动检测 Month 行位置                                  │
│  - 更新 Month 行 (月度汇总)                               │
│  - 遍历每日数据行 (Operation KPIs + Network KPIs         │
│    + PerSite KPIs)                                       │
├─────────────────────────────────────────────────────────┤
│  Step 4: 更新 WOs SLA achievement Report                 │
│  - 自动检测 Month 行位置                                  │
│  - 更新 Month 行 + 每日数据行                             │
│  - 写入 Total / Within SLA / Achieve 三列值               │
├─────────────────────────────────────────────────────────┤
│  Step 5: 导出 + FTP上传                                   │
│  - 导出 6 个文件 (2个xlsx + 2个html + 2个png)            │
│  - 上传到 FTP 服务器 (用户: ZTEEMS)                       │
│  - 远程路径: /01_RPA/LBR_Tools/KPI/MS_SLA               │
└─────────────────────────────────────────────────────────┘
```

### 运行命令

```bash
# 在虚拟环境中运行
python d:\01_RPA\Task\RAN\MS_SLA\update_contract_kpis_report.py

# 或使用系统 Python
C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe d:\01_RPA\Task\RAN\MS_SLA\update_contract_kpis_report.py
```

---

## 3. 文件与路径配置

### 3.1 本地文件

| 文件 | 路径 | 说明 |
|------|------|------|
| 目标 Excel | `D:\01_RPA\Task\RAN\MS_SLA\ZTE OLR MS Contract KPIs & WOs Achievement Auto-Reports.xlsx` | 被更新的主文件 |
| KPI List | `D:\01_RPA\Task\RAN\MS_SLA\KPI list - Operation.xlsx` | NUR/TTR 数据源 (从FTP下载) |
| 数据库 | `D:\01_RPA\Task\RAN\MS_SLA\lbr_ms_sla_kpi.sqlite3` | Network KPIs + PerSite KPIs 数据源 |

### 3.2 FTP 配置

| 用途 | 服务器 | 端口 | 用户名 | 密码 | 远程路径 |
|------|--------|------|--------|------|---------|
| **下载** KPI List | 192.168.100.19 | 21 | FINEBI | DX | /webroot/WEB-INF/schedule/NUR_SLA/ |
| **上传** 导出文件 | 192.168.100.19 | 21 | ZTEEMS | DX | /01_RPA/LBR_Tools/KPI/MS_SLA |

### 3.3 FTP 下载逻辑

- 远程目录结构: `/webroot/WEB-INF/schedule/NUR_SLA/{日期}/{ID}/通用结果/KPI list - Operation.xlsx`
- 自动扫描所有日期文件夹（格式 YYYY-MM-DD），按日期排序取最新
- 递归查找目标文件名 `KPI list - Operation.xlsx`（优先精确匹配，否则取任意xlsx）
- FTP dir 输出解析使用 `split(None, 8)` 处理含空格的文件名
- 下载失败时回退使用本地已有文件

---

## 4. Sheet 1: Contract KPIs Report (New)

### 4.1 表格结构

```
Row 1: 标题 "ZTE OLR MS Contract KPIs Achievements Daily Report"
Row 2: 分类  | Operation KPIs (B-J)  | Network KPIs (K-Q) | PerSite KPIs (R-AB) |
Row 3: 子分类 | NUR (B-E) | TTR (F-J) | 2G Voice (K-L) | 3G Voice (M-N) | 3G+ Data (O-Q) | 2G (R-U) | 3G (V-AB) |
Row 4: 列头（28列 A~AB）
Row 5: Target 目标值
Row 6: Month 月度汇总行 (自动检测)
Row 7-37: 每日数据行 (2026-07-01 ~ 2026-07-31)
```

### 4.2 列映射详情

#### Operation KPIs — NUR (Network Unavailability Ratio)

| 列 | 列名 | 数据来源 | 取值逻辑 |
|----|------|---------|---------|
| B | NUR Network (n) | KPI List NUR Daily | Row "Global_NUR_Daily" 对应日期列 |
| C | NUR 2G (n) | KPI List NUR Daily | Row "2G_NUR_Daily" 对应日期列 |
| D | NUR 3G (n) | KPI List NUR Daily | Row "3G_NUR_Daily" 对应日期列 |
| E | NUR 4G (n) | KPI List NUR Daily | Row "4G NUR Daily" 对应日期列 |

**数据源结构 (KPI List NUR Daily)**:
- 转置结构：日期为列（Row 1），指标为行（Row 2-5）
- Col A = 指标名，Col B+ = 日期值（最新日期在前）
- NUR Monthly 同理，但列头为月份

#### Operation KPIs — TTR (Time-to-Restore)

| 列 | 列名 | 数据来源 | 取值逻辑 |
|----|------|---------|---------|
| F | TTR (%) | KPI List SLA Daily | Row "Global" 对应日期的 **Achieve 列** |
| G | TTR_P1_4h (%) | KPI List SLA Daily | Row "P1" 对应日期的 Achieve 列 |
| H | TTR_P2_8h (%) | KPI List SLA Daily | Row "P2" 对应日期的 Achieve 列 |
| I | TTR_P3_16h (%) | KPI List SLA Daily | Row "P3" 对应日期的 Achieve 列 |
| J | TTR_P4_2Days (%) | KPI List SLA Daily | Row "P4" 对应日期的 Achieve 列 |

**数据源结构 (KPI List SLA Daily)**:
- 转置结构：每个日期占 3 列
- Row 1 = 日期，Row 2 = 子表头（Achieve / Total / Within SLA）
- Row 3 = Global, Row 4 = P1, Row 5 = P2, Row 6 = P3, Row 7 = P4
- **TTR 取 Achieve 列**（百分比值），列位置 = date_col（每日期第1列）

> **重要**: Daily 列顺序为 `Achieve(col) / Total(col+1) / Within SLA(col+2)`
> Monthly 列顺序为 `Total(col) / Within SLA(col+1) / Achieve(col+2)`，取 col+2

#### Network KPIs

| 列 | 列名 | 数据库表 (日度) | 数据库列 |
|----|------|---------------|---------|
| K | 2G CSSR voice (%) | GSM1day_NW | OCI_2G_CSSR_CS(%) |
| L | 2G DCR (%) | GSM1day_NW | TCH in call drop rate(include handover)(%) |
| M | 3G CSSR (%) | UMTS1day_NW | U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO |
| N | 3G DCR (%) | UMTS1day_NW | Ratio of CS Call Drop(%) |
| O | 3G CSSR HSDPA (%) | UMTS1day_NW | U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO |
| P | 3G DCR HSDPA (%) | UMTS1day_NW | U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO |
| Q | 3G to 2G HO (%) | UMTS1day_NW | Cell Inter-RAT CS Outgoing Handover Success Rate(WCDMA->GSM)(%) |

> **重要**: 3G 相关指标全部从 **UMTS** 表查询，不是 GSM 表。
> 月度使用对应 `1month_NW` 后缀表。
> 数据库值从 TEXT 类型自动转换为数字（float/int）。

#### PerSite KPIs（站点达标占比）

**计算逻辑**: 满足阈值的站点个数 / 该日期总站点个数

| 列 | 列名 | 数据库表 (日度) | 数据库列 | 阈值条件 |
|----|------|---------------|---------|---------|
| R | NUR (2G) | GSM1day_SITE | TCH in service rate(%) | >= 99.65% |
| S | DCR 2G (%) | GSM1day_SITE | TCH in call drop rate(include handover)(%) | <= 2% |
| T | 2G CSSR voice (%) | GSM1day_SITE | OCI_2G_CSSR_CS(%) | >= 97% |
| U | 2G TCH Blocking at BH (%) | GSM1day_SITE | TCH in congestion rate(include handover)(%) | <= 2% |
| V | NUR (3G) | UMTS1day_SITE | Cell Validity Rate(%) | >= 99.65% |
| W | 3G CSSR (%) | UMTS1day_SITE | U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO | >= 97% |
| X | 3G DCR (%) | UMTS1day_SITE | Ratio of CS Call Drop(%) | <= 2% |
| Y | 3G CSSR HSDPA (%) | UMTS1day_SITE | U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO | >= 98% |
| Z | 3G DCR HSDPA (%) | UMTS1day_SITE | U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO | <= 2% |
| AA | 3G to 2G HO (%) | UMTS1day_SITE | Cell Inter-RAT CS Outgoing Handover Success Rate(WCDMA->GSM)(%) | >= 95% |
| AB | 3G/3G+ Radio congest(%) | UMTS1day_SITE | U31_3G & 3G+ Radio Congestion Rate_901620_2_UROP.RNC-MO | <= 2% |

> 月度使用对应 `1month_SITE` 后缀表。
> 数据库 KPI 列值使用 `CAST AS REAL` 转换后比较。
> 返回值: 0~1 之间的比值（如 0.95 表示 95% 站点达标）。

---

## 5. Sheet 2: WOs SLA achievement Report

### 5.1 表格结构

```
Row 1: 标题 "ZTE OLR MS WOs SLA Achievements Daily Report"
Row 2: 主表头  | TTR(%) (C2-4) | TTR_P1(C5-7) | TTR_P2(C8-10) | TTR_P3(C11-13) | TTR_P4(C14-16) |
Row 3: Target  | 0.98 | 0.98 | 0.95 | 0.9 | 0.9 |
Row 4: 子表头  | Total | Within SLA | Achieve | (重复5组) |
Row 5: Month 月度汇总行 (自动检测)
Row 6-36: 每日数据行 (2026-07-01 ~ 2026-07-31)
```

### 5.2 列映射详情

每个 TTR 指标占 3 列（Total, Within SLA, Achieve）:

| 指标 | Total 列 | Within SLA 列 | Achieve 列 | 对应 KPI List 行 |
|------|---------|-------------|-----------|----------------|
| TTR (%) | C2 | C3 | C4 | Global (Row 3) |
| TTR_P1_4h (%) | C5 | C6 | C7 | P1 (Row 4) |
| TTR_P2_8h (%) | C8 | C9 | C10 | P2 (Row 5) |
| TTR_P3_16h (%) | C11 | C12 | C13 | P3 (Row 6) |
| TTR_P4_2Days (%) | C14 | C15 | C16 | P4 (Row 7) |

### 5.3 数据取值逻辑

**SLA Daily（每日数据）:**
- 每个日期占 3 列: `Achieve(col) / Total(col+1) / Within SLA(col+2)`
- 日期出现在 Row 1（Col 2, 5, 8, 11, ...）
- 从对应 severity 行读取 Total、Within SLA、Achieve 值

**SLA Monthly（月度数据）:**
- 每个月份占 3 列: `Total(col) / Within SLA(col+1) / Achieve(col+2)`
- 月份出现在 Row 1（Col 2, 5, 8, ...）
- 注意列顺序与 Daily 不同

---

## 6. 数据库表结构 (lbr_ms_sla_kpi.sqlite3)

### 6.1 相关表清单

| 表名 | 数据粒度 | 用途 |
|------|---------|------|
| Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_NW | 2G 日度 网络级 | Network KPIs |
| Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_NW | 2G 月度 网络级 | Network KPIs |
| Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_NW | 3G 日度 网络级 | Network KPIs |
| Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_NW | 3G 月度 网络级 | Network KPIs |
| Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_SITE | 2G 日度 站点级 | PerSite KPIs |
| Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_SITE | 2G 月度 站点级 | PerSite KPIs |
| Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE | 3G 日度 站点级 | PerSite KPIs |
| Hourly_KPI_RPA_SITE_MS_SLA_UMTS1month_SITE | 3G 月度 站点级 | PerSite KPIs |

### 6.2 公共字段

- **日期列**: `Begin Time`（格式: `2026-07-01 00:00:00`）
- **站点标识**: `SITE ID`, `SITE Name`（SITE 表）
- 所有 KPI 列类型为 TEXT，读取时自动 CAST 为 REAL

### 6.3 GSM 表关键列 (17列)

```
Begin Time, End Time, Granularity,
TCH total traffic number(erl),
U31_ZTE_Traffic of Uplink Data TBF (GByte),
U31_ZTE_Traffic of Downlink Data TBF (GByte),
SDCCH in congestion rate(%),
TCH in congestion rate(include handover)(%),
SDCCH channel in call drop rate(%),
TCH in call drop rate(include handover)(%),
Handover in success rate(%),
Handover out success rate(%),
U31_Orange_Randem Access Success Rate(%),
OCI_2G_CSSR_CS(%),
TCH in service rate(%),
2G outage(min),
OCI_2G_CSSR_DATA(%)
```

### 6.4 UMTS 表关键列 (31列)

```
Begin Time, End Time, Granularity,
Ratio of CS Call Drop(%),
Number of CS Call Drop,
Ratio of PS Call Drop(%),
Number of PS Call Drop,
U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO,
Ratio of successful RRC connection establishment(%),
Ratio of successful CS RAB establishment(%),
Ratio of successful PS RAB establishment(%),
Cell Inter-RAT CS Outgoing Handover Success Rate(WCDMA->GSM)(%),
Cell Inter-RAT PS Outgoing Handover Success Rate(WCDMA->GPRS)(%),
Cell Traffic Volume CS(Erl),
Cell Validity Rate(%),
Average Cell TCP Utilization Ratio(%),
Average Cell Freq RTWP(dBm),
U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO,
U31_3G+ Call Setup Success Rate – HSUPA Data services_901598_2_UROP.RNC-MO,
Call Setup Success rate(%),
U31_HSDPA Average Throughput per User_900005_2_UROP.RNC-MO,
U31_Cell DL Traffic Volume PS(GB)_901411_2_UROP.RNC-MO,
U31_Cell UL Traffic Volume PS(GB)_901410_2_UROP.RNC-MO,
U31_3G & 3G+ Radio Congestion Rate_901620_2_UROP.RNC-MO,
U31_3G & 3G+ Channel Elements Congestion Rate_901621_2_UROP.RNC-MO,
U31_3G & 3G+ Codes congestion_901622_2_UROP.RNC-MO,
U31_3G & 3G+ IuB congestion_901623_2_UROP.RNC-MO,
U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO,
U31_3G+ Drop Call Rate - HSUPA Data services_901605_2_UROP.RNC-MO,
U31_3G Drop Call Rate - R99 Data services_901603_2_UROP.RNC-MO,
U31_3G Call Setup Success Rate - R99 Data services_901596_2_UROP.RNC-MO
```

---

## 7. 导出与上传

### 7.1 导出文件命名规则

| Sheet | 导出 xlsx | 导出 html | 导出 png |
|-------|-----------|-----------|----------|
| Contract KPIs Report (New) | `ZTE OLR MS Contract KPIs Achievements Daily Report_YYYY-MM-DD.xlsx` | `...Report_YYYY-MM-DD.html` | `...Report_YYYY-MM-DD.png` |
| WOs SLA achievement Report | `ZTE OLR MS WOs SLA Achievements Daily Report_YYYY-MM-DD.xlsx` | `...Report_YYYY-MM-DD.html` | `...Report_YYYY-MM-DD.png` |

- **日期格式**: `YYYY-MM-DD`（当前执行日期）
- **xlsx 导出方式**: 复制整个工作簿，删除其他 sheet，保留目标 sheet 的完整格式
- **html 导出方式**: 生成 HTML table，保留背景色、字体、合并单元格、列宽等样式
- **png 导出方式**: 使用 Pillow 将 Excel 内容渲染为表格图片，保留背景色、字体粗体/颜色、合并单元格等样式，使用微软雅黑字体支持中文

### 7.2 HTML/PNG 数值格式化规则

| 数值范围 | 格式化方式 | 示例 |
|---------|-----------|------|
| 0 < \|val\| <= 1 | 百分比 (xx.xx%) | 0.98 → "98.00%", 1.0 → "100.00%" |
| val == 0 | "0" | 0 → "0" |
| float 且为整数 | 整数显示 | 66.0 → "66" |
| \|val\| > 100 | 保留2位小数 | 1744.51 → "1744.51" |
| 其他 float | 保留4位小数 | 3.14 → "3.1400" |
| int | 原值 | 66 → "66" |

### 7.3 FTP 上传

- 服务器: `192.168.100.19:21`
- 用户: `ZTEEMS` / 密码: `DX`
- 远程目录: `/01_RPA/LBR_Tools/KPI/MS_SLA`
- 自动创建不存在的子目录
- 上传 6 个文件（2 xlsx + 2 html + 2 png）

---

## 8. KPI List - Operation.xlsx 文件结构

### 8.1 Sheets 列表

| Sheet 名称 | 说明 |
|-----------|------|
| KPI List NUR Daily | NUR 日度数据 |
| KPI List NUR Monthly | NUR 月度数据 |
| KPI List SLA Daily | SLA/TTR 日度数据 |
| KPI List SLA Monthly | SLA/TTR 月度数据 |
| KPI List SLA Weekly | SLA/TTR 周度数据（未使用） |

### 8.2 KPI List NUR Daily 结构

```
Row 1: Date_YYYY-MM-DD | 2026-07-02 | 2026-07-01 | ... (日期为列)
Row 2: Global_NUR_Daily | value | value | ...
Row 3: 2G_NUR_Daily | value | value | ...
Row 4: 3G_NUR_Daily | value | value | ...
Row 5: 4G NUR Daily | value | value | ... (注意: 4G 有空格，非下划线)
```

### 8.3 KPI List NUR Monthly 结构

```
Row 1: Month | 2026-07 | 2026-06 | ... (月份为列)
Row 2: Global_NUR_Daily | value | value | ...
Row 3-5: 同 Daily
```

### 8.4 KPI List SLA Daily 结构

```
Row 1: Date_YYYY-MM-DD | 2026-07-02 |        |        | 2026-07-01 |        |        | ...
Row 2: Ticket Severity  | Achieve  | Total  | Within SLA | Achieve | Total  | Within SLA | ...
Row 3: Global           | 0.9697   | 66.0   | 64.0    | 0.7636  | 110.0  | 84.0    | ...
Row 4: P1               | 1.0      | 1.0    | 1.0     | 1.0     | 7.0    | 7.0     | ...
Row 5: P2               | 1.0      | 42.0   | 42.0    | 0.9063  | 64.0   | 58.0    | ...
Row 6: P3               | ...
Row 7: P4               | ...
```

> 每日期占 3 列: **Achieve**(col), **Total**(col+1), **Within SLA**(col+2)

### 8.5 KPI List SLA Monthly 结构

```
Row 1: Month | 2026-07 |        |         | 2026-06 |        |         | ...
Row 2: Ticket Severity | Total | Within SLA | Achieve | Total | Within SLA | Achieve | ...
Row 3: Global | 176.0 | 148.0 | 0.8409 | ...
Row 4: P1 | ...
Row 5-7: P2, P3, P4
```

> 每月占 3 列: **Total**(col), **Within SLA**(col+1), **Achieve**(col+2)
> **注意**: Monthly 列顺序与 Daily 不同!

---

## 9. 关键技术细节

### 9.1 Month 行自动检测

不硬编码行号，自动扫描 Column A 查找 "Month" 关键字：

```python
for row_idx in range(1, ws.max_row + 1):
    cell_val = ws.cell(row=row_idx, column=1).value
    if cell_val is not None:
        if str(cell_val).strip().lower() == "month":
            month_row = row_idx
```

### 9.2 数据库 TEXT → 数字转换

数据库所有 KPI 列类型为 TEXT。读取后通过 `to_number()` 函数自动转换：

```python
def to_number(val):
    if isinstance(val, (int, float)):
        return val
    try:
        f = float(val)
        if f == int(f):
            return int(f)
        return f
    except (ValueError, TypeError):
        return val
```

- `'0.9807'` → `0.9807` (float)
- `'53'` → `53` (int)
- `None` → `None`

### 9.3 日期匹配策略

按优先级尝试匹配日期：
1. 精确匹配: `WHERE "Begin Time" = '2026-07-01'`
2. 前缀匹配: `WHERE "Begin Time" LIKE '2026-07-01%'`（处理 `2026-07-01 00:00:00` 格式）

### 9.4 列名校验

写入前自动检查数据库列是否存在（`PRAGMA table_info`），避免列名不匹配导致报错。

### 9.5 PNG 导出容错

Pillow 为可选依赖，未安装时自动跳过 PNG 导出，其他功能不受影响：

```python
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
```

---

## 10. 错误处理

| 场景 | 处理方式 |
|------|---------|
| FTP 下载失败 | 打印 WARN，回退使用本地已有文件 |
| 本地文件不存在 | 打印 ERROR，终止执行 |
| Sheet 不存在 | 打印 WARN，跳过该数据源 |
| 数据库表不存在 | 返回 None，跳过该指标 |
| 数据库列不存在 | 返回 None，跳过该指标 |
| 日期无数据 | 跳过该单元格，不覆盖 |
| Pillow 未安装 | 打印 [SKIP]，跳过 PNG 导出，其他功能正常 |
| FTP 上传失败 | 打印 FAIL，继续上传其他文件 |

---

## 11. 依赖

| 库 | 必需 | 说明 |
|----|------|------|
| openpyxl | 是 | Excel 读写 |
| Pillow | 否（可选） | PNG 图片生成 |
| sqlite3 | 内置 | 数据库（Python 内置） |
| ftplib | 内置 | FTP（Python 内置） |

**安装 Pillow**
```bash
# 虚拟环境
d:\01_RPA\.venv\Scripts\pip.exe install Pillow

# 系统 Python
C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe -m pip install Pillow
```

---

## 12. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0 | 2026-06 | 初始版本：Operation KPIs + Network KPIs 更新 |
| 1.1 | 2026-07 | 修复 TTR 取 SLA 列、Month 行自动检测、3G 指标用 UMTS 表 |
| 1.2 | 2026-07 | 新增 FTP 自动下载 KPI List 文件 |
| 1.3 | 2026-07 | 修复 FTP 文件名含空格解析、数据库 TEXT→数字转换 |
| 1.4 | 2026-07 | 新增 PerSite KPIs 计算（站点达标占比） |
| 1.5 | 2026-07 | 新增 WOs SLA achievement Report 更新 |
| 1.6 | 2026-07 | 新增双 Sheet 导出 xlsx/html + FTP 上传 |
| 1.7 | 2026-07 | 新增 PNG 图片导出（Pillow渲染）+ 上传，Pillow 可选依赖 |

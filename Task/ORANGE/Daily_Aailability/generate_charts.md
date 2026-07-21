# Daily Availability KPI 图表生成

## 功能说明

自动从FTP服务器下载最新的 `Daily_Aailability_KPI.xlsx` 文件，根据仪表板样式生成各sheet的折线图，并将图片上传回FTP服务器。

## 处理Sheet

| Sheet名称 | 说明 |
|---|---|
| Availability-NW | 全网可用性 (2G/3G/FDD/TDD ALL) |
| Availability-Regular | 常规区域可用性 (2G/3G/4G FDD Regular) |
| Availability-COOL | COOL区域可用性 (2G/3G Cooli) |
| Availability-ERA | ERA区域可用性 (2G/4G FDD ERA) |

## 运行方式

```powershell
cd D:\01_RPA\Task\ORANGE\Daily_Aailability
python generate_charts.py
```

## 依赖安装

```powershell
pip install -r requirements.txt
```

## FTP配置

### 下载源
- 服务器: 192.168.100.19:21
- 用户: FINEBI / DX
- 路径: /webroot/WEB-INF/schedule/MS Network Availability Daily Report/

### 上传目标
- 服务器: 192.168.100.19:21
- 用户: ZTEEMS / DX
- 路径: /01_RPA/LBR_Tools/KPI/RAN/ORANGE

## 输出

生成的PNG图片保存在 `D:\01_RPA\Task\ORANGE\Daily_Aailability\` 目录下，文件名与sheet名称一致。

# Site Outage Data Fetcher v2

从 ZTE 网管系统 (https://10.100.20.8:28001) 自动登录并获取 Site Outage 数据，写入 Excel 多 Sheet。

## 功能

- OAuth2 + RSA 自动登录获取鉴权 Cookie
- 获取 8 个 API 数据写入同一 Excel 的不同 Sheet
- 每个 API 获取 ALL/ERA/REGULAR 三种 sitetype 数据
- 计算 Diff 列 (ALL - ERA - REGULAR)，非零值黄色填充+红色加粗高亮
- 生成新 Excel 后自动删除旧文件，只保留最新一个

## Sheet 列表

| Sheet | API | 方法 |
|-------|-----|------|
| Logical Site | getRegionSiteDataTable | GET |
| Logical Cell | getRegionCellDataTable | GET |
| Physical Site | getCountRepetitionSiteDown | GET |
| Logical Total | getBorDataByVendor | GET |
| Physical Site Map | getCountRepetitionSiteDownToMap | GET |
| Site Class Statistics | getSiteDownStatisticOfClass | GET |
| Mains Fail Duration | getMainsFailOfDuration | POST |
| Logical Site Outages Hour | getCountSiteDownToHour | POST |

## 运行

```bash
pip install -r requirements.txt
python fetch_site_outage_v2.py
```

## 技术要点

- 使用原始 socket + SSL 连接（ZTE 服务器拒绝标准 HTTP 库的 TLS 握手）
- SSL 配置：`set_ciphers('ALL:@SECLEVEL=0')`，不发 SNI
- RSA PKCS#1 v1.5 加密密码，base64 编码后提交
- POST API 需要 `timeRange` 数组参数：`["0-2","2-4","4-6","6-12","12-24",">24"]`

## 输出

- 文件：`site_outage_YYYYMMDD_HHMMSS.xlsx`（自动清理旧文件）
- 耗时：约 1 秒

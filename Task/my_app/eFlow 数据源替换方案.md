\# eFlow 数据源替换方案



\## 1. 背景与目标



`my\_app` 原先依赖 Excel/FTP 方式导入 TT、WO、Site、Alarm 等数据。为了数据更实时、减少手工操作，决定将数据源整体替换为 `get\_eflow\_table.py` 和 `get\_eflow\_alarm.py` 从 eFlow API 拉取的数据。



\*\*核心目标：\*\*



\- 除拓扑数据外，所有看板数据均改为 API 数据源。

\- 保留 CR、PM 数据。

\- TT 的 `netWorkType` 字段用于 "Domain \& Root Cause Analysis" 的 domain 维度。

\- 清理不再使用的旧表，减少数据库噪音。



\*\*\*



\## 2. 整体替换思路



```

┌─────────────────────────────────────────────────────────────────────┐

│                          eFlow API                                   │

│  get\_eflow\_table.py  (TT/WO/CR/PM/Site/Person)                       │

│  get\_eflow\_alarm.py  (realtime\_alarm)                                │

└──────────────────────────────┬──────────────────────────────────────┘

&#x20;                              │ 生成 eflow.sqlite3

&#x20;                              ▼

┌─────────────────────────────────────────────────────────────────────┐

│            sync\_from\_eflow\_api.py (字段映射 + 清洗)                   │

│   TT.netWorkType ──► domain                                          │

│   WO.networkType ──► domain                                          │

│   毫秒时间戳 ──► 可读日期字符串                                       │

│   CR/PM 保留为独立表                                                  │

└──────────────────────────────┬──────────────────────────────────────┘

&#x20;                              │ 写入

&#x20;                              ▼

┌─────────────────────────────────────────────────────────────────────┐

│                        my\_app/db/app.db                              │

│  eflow\_tt / eflow\_wo / eflow\_cr / eflow\_pm / master\_site\_db          │

│  realtime\_alarm / topology(保留)                                     │

└─────────────────────────────────────────────────────────────────────┘

```




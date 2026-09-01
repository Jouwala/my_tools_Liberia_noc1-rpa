---
标题: person 字段字典（人员）
分类: 10_集成篇_Integration/13_数据字典_DataDictionary
标签: [数据字典, person]
状态: 已验证
适用对象: 开发
最后更新: 2026-09-01
作者: tools/gen_datadict.py
来源: 数据库读取
---

# person 字段字典（人员）

> ⚠️ 本文件由 `tools/gen_datadict.py` **自动生成**。
> **列名 / 类型 / 非空数 / 取值分布 = 数据库客观实际**，可信。
> **「业务含义」列是空的** —— 脚本不知道每个字段在业务上是什么意思，**需要人工补充**。
> 补充后请把 front-matter 的 `作者` 改成你，`来源` 改成 `数据库读取 + 人工补充`。

## 表概况

- 表名：`person`（人员）
- 行数：**133**
- 列数：**36**
- 数据来源：`D:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3`
- 生成时间：2026-09-01

> 🔒 **脱敏说明**：本表含 12 个疑似个人信息列，其示例值已脱敏、且不输出取值分布，避免泄露同事隐私。
>
> 涉及列：`Name`, `Gender`, `Address`, `Nationality`, `Phone`, `Phone_2`, `Age`, `IDNumber`, `Email`, `Remark`, `Sub Region Leader`, `Region Leader`

## 字段清单

按填充率从高到低排序（空列排在最后）。

| # | 字段名 | 类型 | 非空 | 填充率 | 去重值 | 示例值 | 业务含义（待人工补） |
|---|--------|------|------|--------|--------|--------|----------------------|
| 1 | `contractor` | | 133 | 100% | 4 | zte_liberia / testContractor / orange_liberia | |
| 2 | `leaveStatus` | | 133 | 100% | 3 | On duty / Leaved / Resgin | |
| 3 | `Managed Regions` | | 133 | 100% | 23 | River Gee;Sinoe;Grand Ca… / 102001 / River Gee;Sinoe;Grand Ca… | |
| 4 | `ManagedOrganization` | | 133 | 100% | 4 | ZTE / ZTE;orange / orange;ZTE | |
| 5 | `Name` | | 133 | 100% | 133 | 🔒 已脱敏 | |
| 6 | `ObjectID` | | 133 | 100% | 133 | NOC_FO_119 / NOC_FO_103 / CR_NOTIFATION_2 | |
| 7 | `Status` | | 133 | 100% | 2 | Active / Inactive | |
| 8 | `Phone` | | 119 | 89% | 92 | 🔒 已脱敏 | |
| 9 | `Email` | | 49 | 37% | 48 | 🔒 已脱敏 | |
| 10 | `Remark` | | 36 | 27% | 36 | 🔒 已脱敏 | |
| 11 | `Sub Region Leader` | | 34 | 26% | 15 | 🔒 已脱敏 | |
| 12 | `Phone_2` | | 26 | 20% | 26 | 🔒 已脱敏 | |
| 13 | `Groups` | | 3 | 2% | 2 | warehouse / FE | |
| 14 | `Gender` | | 1 | 1% | 1 | 🔒 已脱敏 | |
| 15 | `IDNumber` | | 1 | 1% | 1 | 🔒 已脱敏 | |
| 16 | `Address` | | 0 | 0% | 0 | 🔒 已脱敏 | |
| 17 | `Age` | | 0 | 0% | 0 | 🔒 已脱敏 | |
| 18 | `DataSource` | | 0 | 0% | 0 | — | |
| 19 | `department` | | 0 | 0% | 0 | — | |
| 20 | `Domain` | | 0 | 0% | 0 | — | |
| 21 | `Exclude Dispach` | | 0 | 0% | 0 | — | |
| 22 | `latitude` | | 0 | 0% | 0 | — | |
| 23 | `level1score` | | 0 | 0% | 0 | — | |
| 24 | `level2score` | | 0 | 0% | 0 | — | |
| 25 | `level3score` | | 0 | 0% | 0 | — | |
| 26 | `longitude` | | 0 | 0% | 0 | — | |
| 27 | `Nationality` | | 0 | 0% | 0 | 🔒 已脱敏 | |
| 28 | `office` | | 0 | 0% | 0 | — | |
| 29 | `position` | | 0 | 0% | 0 | — | |
| 30 | `Region Leader` | | 0 | 0% | 0 | 🔒 已脱敏 | |
| 31 | `Skill` | | 0 | 0% | 0 | — | |
| 32 | `skill1Type` | | 0 | 0% | 0 | — | |
| 33 | `skill2Type` | | 0 | 0% | 0 | — | |
| 34 | `skill3Type` | | 0 | 0% | 0 | — | |
| 35 | `SMS Group` | | 0 | 0% | 0 | — | |
| 36 | `Sub Company` | | 0 | 0% | 0 | — | |

## 枚举取值分布

> 仅列出去重值 ≤ 25 的列，按记录数倒序。**这是判断字段语义最有用的部分。**

### `contractor`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| zte_liberia | 106 | 79.7% | |
| orange_liberia | 24 | 18.0% | |
| testContractor | 2 | 1.5% | |
| zte_liberia;testContractor | 1 | 0.8% | |

### `leaveStatus`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| On duty | 131 | 98.5% | |
| Resgin | 1 | 0.8% | |
| Leaved | 1 | 0.8% | |

### `Managed Regions`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| River Gee;Sinoe;Grand Cape Mount;Grand Gedeh;Grand Kru;Lofa;… | 95 | 71.4% | |
| Montserrado;Margibi | 8 | 6.0% | |
| River Gee;Sinoe;Grand Cape Mount;Grand Gedeh;Grand Kru;Lofa;… | 4 | 3.0% | |
| Nimba | 4 | 3.0% | |
| Bong | 3 | 2.3% | |
| River Gee;Sinoe;Grand Cape Mount;Grand Gedeh;Grand Kru;Lofa;… | 2 | 1.5% | |
| Sinoe;Lofa;Margibi;Montserrado;Sinoe;Lofa;Margibi;Montserrad… | 1 | 0.8% | |
| Sinoe;Grand Kru | 1 | 0.8% | |
| River Gee | 1 | 0.8% | |
| Nimba;River Gee;Sinoe;Grand Cape Mount;Grand Gedeh;Grand Kru… | 1 | 0.8% | |
| Maryland | 1 | 0.8% | |
| Margibi | 1 | 0.8% | |
| Lofa;Bong | 1 | 0.8% | |
| Lofa | 1 | 0.8% | |
| Grand Kru | 1 | 0.8% | |
| Grand Gedeh;River Gee | 1 | 0.8% | |
| Grand Cape Mount | 1 | 0.8% | |
| Grand Bassa;River Cess | 1 | 0.8% | |
| Grand Bassa | 1 | 0.8% | |
| Gbarpolu;Bomi | 1 | 0.8% | |
| Bomi;Gbarpolu;River Gee;Sinoe;Grand Cape Mount;Grand Gedeh;G… | 1 | 0.8% | |
| 102001 | 1 | 0.8% | |
| 101001 | 1 | 0.8% | |

### `ManagedOrganization`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| ZTE | 111 | 83.5% | |
| orange;ZTE | 14 | 10.5% | |
| ZTE;orange | 7 | 5.3% | |
| orange | 1 | 0.8% | |

### `Status`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| Active | 131 | 98.5% | |
| Inactive | 2 | 1.5% | |

### `Groups`

| 取值 | 记录数 | 占比 | 业务含义（待人工补） |
|------|--------|------|----------------------|
| （空） | 130 | 97.7% | |
| warehouse | 2 | 1.5% | |
| FE | 1 | 0.8% | |

## 相关

- 索引：[00_索引.md](./00_索引.md)
- 术语：[90_术语表_Glossary.md](../../../90_术语表_Glossary.md)


---
标题: person Field Dictionary (Personnel)
分类: 10_集成篇_Integration/13_数据字典_DataDictionary
标签: [数据字典, person]
状态: 已验证
适用对象: 开发
最后更新: 2026-09-01
作者: tools/gen_datadict.py
来源: Database reading
---

# person Field Dictionary (Personnel)

> ⚠️ This file is **auto-generated** by `tools/gen_datadict.py`.
> **Column name / type / non-null count / value distribution = objective reality of the database**, trustworthy.
> **The "Business meaning" column is empty** — the script doesn't know what each field means in business, **needs human input**.
> After filling in, change the front-matter `作者` to yourself and `来源` to `数据库读取 + 人工补充`.

## Table Overview

- Table name: `person` (personnel)
- Row count: **133**
- Column count: **36**
- Data source: `D:\01_RPA\Task\my_app\data\eflow\eflow.sqlite3`
- Generated: 2026-09-01

> 🔒 **Anonymization note**: This table contains 12 suspected personal-info columns whose sample values are anonymized and whose value distributions are not output, to avoid leaking colleague privacy.
>
> Affected columns: `Name`, `Gender`, `Address`, `Nationality`, `Phone`, `Phone_2`, `Age`, `IDNumber`, `Email`, `Remark`, `Sub Region Leader`, `Region Leader`

## Field List

Sorted by fill rate descending (empty columns at the end).

| # | Field name | Type | Non-null | Fill rate | Distinct | Sample value | Business meaning (to be filled) |
|---|--------|------|------|--------|--------|--------|----------------------|
| 1 | `contractor` | | 133 | 100% | 4 | zte_liberia / testContractor / orange_liberia | |
| 2 | `leaveStatus` | | 133 | 100% | 3 | On duty / Leaved / Resgin | |
| 3 | `Managed Regions` | | 133 | 100% | 23 | River Gee;Sinoe;Grand Ca… / 102001 / River Gee;Sinoe;Grand Ca… | |
| 4 | `ManagedOrganization` | | 133 | 100% | 4 | ZTE / ZTE;orange / orange;ZTE | |
| 5 | `Name` | | 133 | 100% | 133 | 🔒 Anonymized | |
| 6 | `ObjectID` | | 133 | 100% | 133 | NOC_FO_119 / NOC_FO_103 / CR_NOTIFATION_2 | |
| 7 | `Status` | | 133 | 100% | 2 | Active / Inactive | |
| 8 | `Phone` | | 119 | 89% | 92 | 🔒 Anonymized | |
| 9 | `Email` | | 49 | 37% | 48 | 🔒 Anonymized | |
| 10 | `Remark` | | 36 | 27% | 36 | 🔒 Anonymized | |
| 11 | `Sub Region Leader` | | 34 | 26% | 15 | 🔒 Anonymized | |
| 12 | `Phone_2` | | 26 | 20% | 26 | 🔒 Anonymized | |
| 13 | `Groups` | | 3 | 2% | 2 | warehouse / FE | |
| 14 | `Gender` | | 1 | 1% | 1 | 🔒 Anonymized | |
| 15 | `IDNumber` | | 1 | 1% | 1 | 🔒 Anonymized | |
| 16 | `Address` | | 0 | 0% | 0 | 🔒 Anonymized | |
| 17 | `Age` | | 0 | 0% | 0 | 🔒 Anonymized | |
| 18 | `DataSource` | | 0 | 0% | 0 | — | |
| 19 | `department` | | 0 | 0% | 0 | — | |
| 20 | `Domain` | | 0 | 0% | 0 | — | |
| 21 | `Exclude Dispach` | | 0 | 0% | 0 | — | |
| 22 | `latitude` | | 0 | 0% | 0 | — | |
| 23 | `level1score` | | 0 | 0% | 0 | — | |
| 24 | `level2score` | | 0 | 0% | 0 | — | |
| 25 | `level3score` | | 0 | 0% | 0 | — | |
| 26 | `longitude` | | 0 | 0% | 0 | — | |
| 27 | `Nationality` | | 0 | 0% | 0 | 🔒 Anonymized | |
| 28 | `office` | | 0 | 0% | 0 | — | |
| 29 | `position` | | 0 | 0% | 0 | — | |
| 30 | `Region Leader` | | 0 | 0% | 0 | 🔒 Anonymized | |
| 31 | `Skill` | | 0 | 0% | 0 | — | |
| 32 | `skill1Type` | | 0 | 0% | 0 | — | |
| 33 | `skill2Type` | | 0 | 0% | 0 | — | |
| 34 | `skill3Type` | | 0 | 0% | 0 | — | |
| 35 | `SMS Group` | | 0 | 0% | 0 | — | |
| 36 | `Sub Company` | | 0 | 0% | 0 | — | |

## Enum Value Distribution

> Only columns with distinct values ≤ 25 are listed, in descending record count. **This is the most useful part for judging field semantics.**

### `contractor`

| Value | Records | Share | Business meaning (to be filled) |
|------|--------|------|----------------------|
| zte_liberia | 106 | 79.7% | |
| orange_liberia | 24 | 18.0% | |
| testContractor | 2 | 1.5% | |
| zte_liberia;testContractor | 1 | 0.8% | |

### `leaveStatus`

| Value | Records | Share | Business meaning (to be filled) |
|------|--------|------|----------------------|
| On duty | 131 | 98.5% | |
| Resgin | 1 | 0.8% | |
| Leaved | 1 | 0.8% | |

### `Managed Regions`

| Value | Records | Share | Business meaning (to be filled) |
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

| Value | Records | Share | Business meaning (to be filled) |
|------|--------|------|----------------------|
| ZTE | 111 | 83.5% | |
| orange;ZTE | 14 | 10.5% | |
| ZTE;orange | 7 | 5.3% | |
| orange | 1 | 0.8% | |

### `Status`

| Value | Records | Share | Business meaning (to be filled) |
|------|--------|------|----------------------|
| Active | 131 | 98.5% | |
| Inactive | 2 | 1.5% | |

### `Groups`

| Value | Records | Share | Business meaning (to be filled) |
|------|--------|------|----------------------|
| (empty) | 130 | 97.7% | |
| warehouse | 2 | 1.5% | |
| FE | 1 | 0.8% | |

## Related

- Index: [00_索引.md](./00_索引.md)
- Terms: [90_术语表_Glossary.md](../../../90_术语表_Glossary.md)

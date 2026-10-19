# gp_ran —— RAN Greenplum（L_T216）只读取数客户端

需求来源：2026-10-19 现场同事（+231 77 699 0822）给的两条取数语句 —— 按时间窗取
**VoLTE 用户**与 **N78 频段用户**的号码清单（`SELECT DISTINCT D023 FROM L_T216 ...`），
原先完全靠人工登数据库敲 `copy ... to '/home/gpadmin/*.csv'`，再 `chmod 777` + `scp` 回跳板机下载。
本包把这条流程自动化。

## 1. 它和 `vmax_gbase` 不是一套东西（别混用）

| | `vmax_gbase`（已有） | `gp_ran`（本包） |
|---|---|---|
| 数据库 | GBase 8a | Greenplum（ZTE PaaS 托管，`RAN_gp_master_cluster1`） |
| 协议 | **MySQL**，`pymysql` 直连 `10.123.255.12:5258` | PostgreSQL 语法，**端口不可直连** |
| 表 | `aggr_5gsa_*` 聚合表（90 天分区保留） | `L_T216` 信令明细 |
| 身份 | `gbase` | `ubuntu` → `sudo` root → `su - gpadmin` → `psql` |
| 访问方式 | 一条 TCP | **两跳 SSH**（必须经 control1 转发） |

判据很硬：现场 SQL 用了 `::TIMESTAMP` 和 `EXTRACT(EPOCH FROM ...)`，GBase 8a 不支持 `::` 转换；
`gpadmin` / `psql` / `pdm-cli` 也都是 Greenplum 的东西。**不要**试图用 `VmaxGbaseClient` 跑这两条。

## 2. 连接事实（2026-10-19 本机实测）

| 目标 | 结果 |
|---|---|
| `10.100.29.12:22`（control1） | **OPEN**，`SSH-2.0-OpenSSH_8.5` |
| `10.100.29.12:5432` | refused（control1 上没有可直接连的库） |
| `193.168.0.6:22 / :5432`（GP 主节点） | **超时**，本机不可路由 → 只能经 control1 转发 |
| control1 可用认证 | `publickey, gssapi-keyex, gssapi-with-mic, password` |
| 本机 `~/.ssh/id_ed25519` | 在 control1 上**未被信任**（publickey 被拒），走口令 |

代码里的链路：`paramiko` 登 control1 → `direct-tcpip` 开一条到 `193.168.0.6:22` 的通道 →
在该通道上再建一个 SSH 会话 → `sudo -S -p "" su - gpadmin -c 'echo <base64> | base64 -d | psql ...'`。

SQL 用 **base64** 传，是为了绕开 sudo/su/psql 三层 shell 的引号嵌套 —— 这些语句里全是单引号，
直接拼命令行会在某一层被截断，且报错点很难定位。

### 2b. 2026-10-19 首次实跑已确认的事实

| 项 | 实测值 |
|---|---|
| 两跳登录 | **通**（ubuntu 口令，password 认证即可，无需 keyboard-interactive） |
| `sudo -S` 非交互 | **可用**，没有 requiretty 问题（`cat /home/gpadmin/paas_hosts_master.cc` → `193.168.0.6`） |
| 主节点 | `np-pdn-ngi-1`，EL7 `3.10.0-693.21.1.el7` |
| 版本 | `psql 9.4.26` / **`Greenplum 6.23.5`**（2026-03-27 build） |
| gpadmin 默认库 | **`netmaxdb`**，`L_T216` 就在这里；同节点还有 `apommdb` / `postgres` |
| `COPY ... WITH (FORMAT csv, HEADER true)` | **支持**（所以不需要 psql 的 `--csv`，那个要 PG 12） |
| 分区 | 按 `D027` 做 **12 小时一个分区** 的 range 分区，列存 AO + zlib；126 个分区 |
| 时间窗能否裁剪 | 能。单个 12h 分区 1985 万行，`count(distinct)` 只花 **0.8s** |
| 单日导出量 | 2026-10-18 全天：**890,261 行 / 13.9 MB / 51s** |
| 数据新鲜度 | max(D027) 落后当前约 2 小时，**「今天」是移动靶**，取数默认取上一个完整自然日 |
| **回溯上限** | 最早分区 `2026-08-18 12:00 UTC` → 约 **62 天**，不是 VMAX 那边的 90 天 |

凭据：分组 `gp_ran_control`（control1 的 ubuntu）、`gp_ran_master`（主节点 ubuntu，
**留空自动复用 control1 的口令**）。环境变量 `GP_RAN_CONTROL_USER/PASS`、`GP_RAN_MASTER_USER/PASS`、
`GP_RAN_CONTROL_HOST`、`GP_RAN_MASTER_HOST`、`GP_RAN_DB`。口令只进 credentials 表，不进代码/日志/git。

### 2c. `L_T216` 关键列（`pg_attribute` 实测）

| 列 | 类型 | 含义与坑 |
|---|---|---|
| `D027` | int8 | 记录时间，**口径是「自 2000-01-01 起的秒」**（`to_timestamp(D027+946684800)` 校验过） |
| `D023` | text | **IMSI，不是 MSISDN**：89 万行样本 100% 为 15 位纯数字，98.8% 以 `618`（利比里亚 MCC）开头，其余 `612/310/404/619/613` 是漫游用户。**要电话号码得另找 IMSI↔MSISDN 关联表**，别把这份清单当可拨打号码交给需求方 |
| `D023` 空值率 | — | 单个 12h 分区 1985 万行里只有 **297 万行非空（15%）**。不加 `D023 <> ''`，空串会被 `DISTINCT` 当成一个合法身份带进结果文件 |
| `C031/C032/C033` | int4 | VoLTE 相关标志位，取值 0/1（具体语义以需求方为准） |
| `C043` | text | **`$` 分隔的频段列表**，如 `1$3$7$8$20$28$38$40$41$78`。所以 `POSITION('$78$' IN '$'||C043||'$')` 的整词匹配是对的，`LIKE '%78%'` 会误命中 |

## 3. 相比人工流程改掉的两件事

**(1) 不落盘：`COPY ... TO STDOUT` 取代 `TO '/home/gpadmin/volte.csv'`。**
CSV 经 SSH 标准输出直接回本机 `backend/data/gp_ran/`。于是 `chmod 777`、
`scp` 到 `/home/ubuntu`、再从跳板机下载这三步全部消失，**数仓和跳板机上不留任何文件**。
这不只是为了省事：`D023` 是 MSISDN，属于订阅者个人信息，人工流程里它先被 `chmod 777`
摊在共享目录上，再躺在跳板机的 `/home/ubuntu` 里不清理。

本包的 `.gitignore:119` 显式挡住了 `/backend/data/gp_ran/`（注意 `my_app/.gitignore` 有一条
`!backend/data/` 的取反用于 GIS 地理文件，如果不补这条，号码清单会变成可提交文件）。

**(2) 只读守卫（`assert_readonly`）**：只放行 `SELECT/WITH/SHOW/EXPLAIN/COPY...TO STDOUT`，并显式拒绝
- `COPY ... TO '文件'`（在数仓上留 PII 文件）
- `COPY ... TO PROGRAM '...'`（**以 gpadmin 身份执行操作系统命令**）
- 以 `\` 开头的 psql 元命令（`\!` 同样能起 shell，而 SQL 正是从 `psql -f -` 喂进去的）
- 一切 DML/DDL 关键字

以及会被拼进远端 shell 的 `db_user` / `database` 两个字段必须匹配合法标识符（防注入）。
回归测试见 `tests/test_gp_ran.py`（19 条，全离线，不连生产）。

## 4. ⚠ 现场那条 volte 语句本身是错的

```sql
WHERE A.C031 = 1 OR A.C032 = 1 OR A.C033 = 1 and d027 > X and d027 < Y
```
SQL 里 `AND` 优先级高于 `OR`，实际解析成
```sql
C031=1 OR C032=1 OR (C033=1 AND d027 > X AND d027 < Y)
```
**时间窗只作用在 C033 那一支**，C031/C032 两支等于全历史 —— 拿到的是「历史上开过 VoLTE 的所有号码」，
而且因为无法用时间裁剪，要扫整张 `L_T216`。本包生成的语句补了括号并改成左闭右开：

```sql
WHERE (A.C031 = 1 OR A.C032 = 1 OR A.C033 = 1)
  AND A.D027 >= EXTRACT(EPOCH FROM ('2026-10-08'::TIMESTAMP - TIMESTAMP '2000-01-01 00:00:00'))
  AND A.D027 <  EXTRACT(EPOCH FROM ('2026-10-15'::TIMESTAMP - TIMESTAMP '2000-01-01 00:00:00'))
```
（人工版两支都用 `>`，会漏掉起始日 00:00:00 整点的记录。利比里亚 UTC+0，`TIMESTAMP` 无时区不产生偏移。
`D027` 的口径是「自 2000-01-01 起的秒」，沿用现场写法便于对账。）

**口径变化会让结果比人工版少很多行，这是修正不是 bug** —— 第一次跑要拿一天的数据与人工结果对一下数量级，
并把这个差异同步给提需求的同事，别让人以为数据丢了。

## 5. 用法

```
cd D:\01_RPA\Task\my_app
python -m backend.services.gp_ran.gp_ran_check --check          # 逐层探测链路
python -m backend.services.gp_ran.gp_ran_check --describe       # L_T216 列与类型
python -m backend.services.gp_ran.gp_ran_check --count  --kind volte --start 2026-10-08 --end 2026-10-15
python -m backend.services.gp_ran.gp_ran_check --export --kind n78  --start 2026-10-08 --end 2026-10-15
```

```python
from backend.services.gp_ran import GpRanClient, sql_volte_users
with GpRanClient() as c:                     # 自动两跳 + 关闭
    df = c.query_df(sql_volte_users("2026-10-08", "2026-10-15"))
```

## 6. 还剩下的开放项（都是**业务口径**，不是技术未知数）

技术侧已实测跑通（见 §2b），下面几条需要需求方回答，直接影响任务与看板怎么做：

1. **`C031/C032/C033` 各自的语义**。现在按现场给的「三者任一为 1」算 VoLTE，但实测这个条件
   几乎不筛选人（单 12h 分区：全部非空 IMSI 302,773 个，其中满足标志位条件的 302,265 个，
   占 99.8%）。要么三者本来就是同一件事的不同侧面，要么 VoLTE 该用别的列 —— 得问清楚，
   否则「VoLTE 用户数」这个 KPI 等于「所有用户数」。
2. **漫游用户要不要留**。非 `618` 开头的 IMSI 约占 1.2%（612 塞拉利昂、310 美国、404 巴基斯坦…）。
3. **要不要 IMSI→MSISDN 映射**。现场要的是「用户清单」，如果最终用途是外呼/短信，IMSI 不能直接用。
4. **窗口与频率**。「今天」是移动靶（数据落后约 2 小时），默认应取**上一个完整自然日**；
   回溯最多约 62 天，超过就没有分区了。

换机房/换环境只改配置，不改代码：`GP_RAN_CONTROL_HOST` / `GP_RAN_MASTER_HOST`（主节点 IP 由
control1 上的 PaaS 决定，`cat /home/gpadmin/paas_hosts_master.cc` 可查），以及 `GP_RAN_DB`。

## 7. 已登记为定时任务

`gp_ran_user_sync`（任务号 46）：

| 项 | 值 |
|---|---|
| 入口 | `gp_ran_sync.run_gp_ran_user_sync()` |
| cron | `20 13 * * *`（**13:20 UTC**，本机时钟就是 UTC）—— 实测落库延迟约 10.5h，「昨天」要到约 10:30 UTC 才完整；跑早了会**静默少一天** |
| 窗口 | `[今天-N, 今天)` 的完整 UTC 日，`N` 默认 7，可用 `GP_RAN_WINDOW_DAYS` 改（上限 60，超过就没有分区了） |
| worker 组 | 新建的 **`g` 组**（独立故障域，理由见 `worker_watchdog.py` 的分组注释） |
| 产物 | `backend/data/gp_ran/{volte,n78}_<起>_<止>.csv` + 旁路库 `gp_ran.sqlite3`（只存计数与路径，**IMSI 不进主库**）；CSV 只保留最近 30 次 |
| 实测首轮 | 2026-10-19 16:15 UTC：窗口 10-12~10-19，扫描 1,041,325,158 行，`data_last=2026-10-18 23:59:59 UTC`（证明窗口取到了完整一天）；**VoLTE 1,114,371 个 IMSI / 17.0 MB / 29.0s**，**N78 77,916 个 / 1.2 MB / 23.1s**，总耗时 **72.6s** |

上线时踩到的一次失败值得记着：**本机 stdout 默认 cp1252，任务里第一行中文 print 就抛
`UnicodeEncodeError`**，在建连之前整个任务就崩了。现在 `gp_ran_sync.py` 在导入期就
`reconfigure(encoding="utf-8")`（同 `get_sp_table.py:54-58`）。worker 把日志重定向到文件时同样会踩，
所以这行不能只放在 `__main__` 里。

诊断入口：`python -m backend.services.gp_ran.gp_ran_check --check`（逐层打印两跳、sudo、psql、库、表、分区）。
离线守卫：`python -m pytest tests/test_gp_ran.py tests/test_gp_ran_sync.py -q`（35 条，不连生产）。
分组联动守卫：`python tests/test_worker_group_coverage.py`（5 项，改分组必跑）。

## 8. 用户宽表（`gp_ran_profile.py`）

两份扁平清单只能整包推送，做不了「终端支持 N78 × 还没在用 5G × 近 7 天活跃」这类交集判断。
宽表把 80 列收敛成**一个 IMSI 一行、26 列**：

```
imsi | first_seen_utc | last_seen_utc | records | imeisv_any | tac | bands_any | band_combo_any
| n78_in_bands | n78_in_combo | volte_any | c031_any | c032_any | c033_any
| cell_cnt | geo_recs | ip_recs | c027/c029/c030/c034/c035/c038/c039/c040/issupportedtm8tdd _any
```

```
python -m backend.services.gp_ran.gp_ran_profile --start 2026-10-12 --end 2026-10-19
python -m backend.services.gp_ran.gp_ran_profile --start ... --end ... --show-sql   # 只看 SQL
```

**三条刻意的设计约束**（都有实测依据，改之前先读）：

1. **必须是一次 `GROUP BY` 能算出来的形状**。7 天约 10 亿行，`DISTINCT ON` + join 取
   "最后一次记录的各字段"要对 10 亿行排序 —— 本表上 `runaway_cleaner` 内存熔断真实触发过
   （80 路 UNION ALL 那次）。由测试 `test_profile_is_one_group_by_pass` 守住。
2. **不给经纬度**。同一用户 `max(c070)` 与 `max(c071)` 很可能来自不同记录，
   拼出来是一个谁都没去过的坐标。只给 `geo_recs`（该用户有多少条带定位的记录，
   实测 79.1% 的用户 >0）。要"最新位置"必须换成成对取值并实测内存 ——
   由 `test_profile_never_emits_a_fabricated_coordinate` 守住。
3. **裁掉了 `c036`/`c037`**：它们覆盖 44.6% 看着比 `c043` 香，
   但实测取值只含 LTE 频段（`1A$3A$7A$8A$20A$28A$38A$40A$41A`，**没有 78**），
   对 NR 判据无用，却占单日文件 314 MB 里的 139 MB（44%）。

实测成本：

| 窗口 | 用户数 | 耗时 | 文件 |
|---|---:|---:|---:|
| 单日 2026-10-18（含 c036/c037） | 891,645 | 370s | 314 MB |
| **7 天 10-12~10-19（裁列后）** | **1,116,192** | **242s** | **228 MB** |

> 7 天比单日**还快**，反直觉但合理：`max()` 把 `c036`/`c037` 两条长文本穿过聚合与 shuffle
> 搬运的开销，远大于多扫 6 天数据的代价（列存只读被引用的列）。
> 我最初估的"40 分钟量级"是照单日线性外推的，**错了 10 倍** —— 记在这里，
> 提醒后人别用线性外推估 Greenplum 的成本。
>
> 一致性自检：宽表里 `last_seen` 落在 10-18 的用户数 = **891,645**，与单日窗口独立跑出的
> 用户数**完全相等**（每天都活跃的人，last_seen 自然落在窗口最后一天）。

7 天窗口跑出来的可圈人群（同一份宽表，2026-10-19 实测）：

| 判据 | 人数 | 占比 |
|---|---:|---:|
| N78 能力（`c043` 或 `c075`） | 77,937 | 6.98% |
| VoLTE 任一标志位 | 1,114,371 | 99.84% |
| **N78 终端 且 非 VoLTE** | **3** | 0.0003% |
| 有定位记录（≥1 条） | 1,047,189 | **93.82%** |
| 跨 10 个以上小区 | 631,800 | 56.60% |
| 记录数 ≥50（近似"活跃 5 天+"） | 663,378 | 59.43% |
| `c035`=1 / `c038`=1 / `c039`=1 | 236,209 / 19,541 / 56,928 | 21.2% / 1.75% / 5.1% |
| 不同 TAC 机型数 | 29,076 | 平均 38 人/机型 |

两条值得注意的结论：

* **`c075` 不是独立证据**。它相对 `c043` 只多认 21 个人（99.97% 重叠）—— 我之前说它是
  "第二份独立佐证"是错的，两者是同一批记录的两个视图。
* **7 天窗口对定位覆盖是真增益**：行级 `c070` 只有 46.1%，但用户级"至少一条带定位"达 **93.8%**。
  而 N78 判定几乎不随窗口变长而增加（7.6% → 6.98%），进一步说明它是终端属性而非采集稀疏。

## 9. 待办：看板页

数据侧已经齐了（旁路库里有逐次运行的 `users / rows_scanned / data_last / csv_path`，
CSV 可直接下载）。**看板页尚未开工** —— 按 `AGENTS.md` 第三节第 1 条要三处同步
（`App.tsx` 菜单 + `i18n.tsx` 中英两处 + `11-feature-guide.md`），并按第 1b 条做到「能下钻尽下钻」：
本页的下钻只能是**下载 CSV**（IMSI 清单不进主库，无法在页面里分页展示明细，
这是刻意的隐私取舍，不是偷懒）。做之前先确认：要不要顺带把 `data_last` 的滞后小时数
做成告警（数仓上游停更时，看板的数字会看起来"正常"但其实是旧的）。

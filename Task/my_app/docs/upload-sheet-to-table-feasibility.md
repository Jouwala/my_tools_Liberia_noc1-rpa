# 可行性调研：通过 ?page=upload 按 Sheet 选择目标表更新

**调研对象**
- `db/ZTE OLR MS Master Site Database.xlsx`
- `db/ZTE OLR MS MW Topology _OSS.xlsx`
- 入口 `http://192.168.100.20/myapp/?page=upload`

**结论：可行，但不能直接复用现有上传通道，需要新增「按 sheet 指定目标表」的映射式导入。**

> ### 补充调研（第二轮）：应该用 `?page=tables` 而不是 `?page=upload`
>
> 你的判断是对的。`?page=tables` 已有可用的导入弹窗，比 `?page=upload` 更合适。
> 详见文末 **第 7 节**，MW 缺失表清单见 **第 8 节**。
>
> ### 定稿（第三轮）：以 MW 两个页面为准
> 第 1–9 节是前两轮的调研过程，**最终口径以第 10 节为准**：
> MW 两页实际依赖 4 张表且均已存在，真正缺导入通道的只有 **`zte_mw_links`**。
>
> ### 已实施（第四轮）
> 第 11 节记录了**已落地**的 `kml_mw_links` 方案（KML 入库 + 页面导入）。

---

## 1. 现状事实（已实测）

### 1.1 ?page=upload 页面确实存在并且已连通后端

| 层 | 位置 | 行为 |
|---|---|---|
| 前端页面 | `frontend/src/pages/DataUpload.tsx` | antd `Dragger` 单文件上传 |
| 路由注册 | `frontend/src/App.tsx:1277` | `case 'upload': return <DataUpload />` |
| 后端接口 | `backend/routers/upload.py:36` | `POST /api/upload`（带 `require_protected`） |
| 历史接口 | `backend/routers/upload.py:143` | `GET /api/upload/history` |
| 后端进程 | `pythonw -m uvicorn backend.main:app --port 7038` | 运行中；实测 `/api/tables` 返回 50 张表 |

也就是说「上传入口」这条链路是通的，缺的只是**目标表语义**。

### 1.2 关键障碍：现有 /api/upload 故意不写业务表

`backend/routers/upload.py:92-95` 明确写着：

```python
# 生成表名：隔离在 upload_ 命名空间并加 uuid，避免覆盖系统表（如 master_site_db）
table_name = f"upload_{uuid.uuid4().hex[:8]}_{...}"
```

**每一次上传都建一张一次性表**（`upload_<uuid>_<文件名>_<sheet名>`），永远不会碰
`master_site_db` / `topology`。这是刻意的安全设计，所以：

- 用现在这个页面传这两个 xlsx → **对业务表零影响**，只是多出一堆垃圾表。
- 想实现你的需求，**必须新增映射逻辑**，不能只改前端。

实测佐证：`uploaded_files` 表 0 行，库里那批 `eflow_eflow_*` / `ms_sla_*` 表都不是走这个接口产生的。

### 1.3 好消息：已经存在一个「指定表名导入」的接口可作蓝本

`backend/routers/tables.py:341` 有 `POST /api/tables/import`：

- 接收 `file` + `table_name` + `overwrite` 三个表单字段；
- 支持 `overwrite=True` **真替换已存在表**（`if_exists="replace"`）；
- 列名清洗逻辑与 upload 同源（`clean_column_name`）；
- 有多 sheet 时按 `table_name_<sheet>` 建表。

这个接口在语义上已经非常接近目标，**只差「多 sheet → 各自映射到不同表名」这一步**：
它现在是「一个前缀 + 每 sheet 后缀」，而你要的是「每个 sheet 映射到一张固定业务表」。

### 1.4 库表 ↔ Sheet 的映射关系（已在系统里固化）

`backend/scripts/init_db.py:27-41` 已经写好了 `SHEET_TABLE_MAP`，实测对应表全部存在：

| Sheet 名 | 目标表 | 现有行数 |
|---|---|---|
| `Master Site Database ` | `master_site_db` | 805 |
| `E-flow Database` | `eflow_database` | 767 |
| `FLM Database` | `flm_database` | 767 |
| `FLM Team information ` | `flm_team_new` | 32 |
| `FLM Team information` | `flm_team` | 34 |
| `SLA and Tickes Priority` | `sla_priority` | 8 |
| `Victim topology（Pradeep update)` | `victim_topology` | 764 |
| `Satellite sites list` | `satellite_sites` | 187 |
| `ERA(VIP&No-VIP）` | `era_sites` | 209 |
| `GateWay Sites` | `gateway_sites` | 56 |
| `Special Sites` | `special_sites` | 31 |
| `ISP Sites` | `isp_sites` | 50 |
| `LandLord and AML Sites` | `landlord_sites` | 35 |

Topology 文件是另一条独立链路：`backend/import_topology.py`，单 sheet `Sheet1`
（表头 `Site A / Site A Name / Site B / Site B Name / 0th / 1st / 2nd ...`）
→ 表 `topology`（515 行）。它**不是**「按列铺开」，而是要展开 hop 路径。

---

## 2. 必须先解决的三个真实问题

这三条是调研中最值得注意的部分，任何实现方案都绕不开。

### 问题 A：Sheet 名漂移，映射表已对不上

`SHEET_TABLE_MAP` 里写的 sheet 名和当前文件**已经不一致**：

| 映射表里写的 | 文件里实际的 | 状态 |
|---|---|---|
| `New FLM Team information ` | `FLM Team information ` | 名字变了 |
| `Victim topology（Pradeep update)` | `Victim topology（Pradeep update)` | ✅ 一致 |
| — | `VIP site List` | **映射表没有** |
| — | `Startlink ERA sites` | **映射表没有** |
| `Special Sites` / `ISP Sites` | 文件里已无这两个 sheet | **表在库、sheet 没了** |

而且注意：`Victim topology（Pradeep update)` 和 `ERA(VIP&No-VIP）` 用的是**全角括号**，
`Master Site Database ` / `FLM Team information ` 末尾**带尾随空格**。

→ 所以**不能靠 sheet 名自动匹配**。必须：要么把映射表改成「显式、可维护、存库」的配置，
要么在 UI 上让用户**自己候选 sheet 与目标表**（推荐后者，容错且透明）。

### 问题 B：不是每个 sheet 都能一行对一行地replace

实测各 sheet 情况差异很大：

| Sheet | 表头列数 | 能否直接 replace |
|---|---|---|
| `Master Site Database ` | 25 | ✅ 可以（`master_site_db` 28 列 = 25 + 3 元数据列） |
| `E-flow Database` | 42 | ✅ 可以 |
| `FLM Database` | 33 | ✅ 可以 |
| `FLM Team information ` | **0**（第 1 行不是表头） | ⚠️ 需指定表头行 |
| `SLA and Tickes Priority` | **0** | ⚠️ 需指定表头行 |
| `Satellite sites list` | **0** | ⚠️ 需指定表头行 |
| `LandLord and AML Sites` | **0** | ⚠️ 需指定表头行 |
| `VIP site List` | 8（重复列名 `Victims`×2） | ⚠️ 有重复列，靠 `victims`/`victims_1` 兜住 |
| `GateWay Sites` | 6 | ⚠️ 库表 56 行但 sheet 767 行（**口径不一致**） |
| `Startlink ERA sites` | 2 | ⚠️ 对应 `startlink_era_sites`（5 列） |

有 4 个 sheet 第 1 行不是表头（`header_count=0`），说明数据前有标题行/合并行。
**盲传会直接把标题行当数据写进表**。

### 问题 C：topology 不能用通用「整表替换」

`import_topology.py:77-82` 显示 topology 需要**变换**：

```python
hops = [str(v) for v in vals[4:25] if v is not None]  # 26 列里取 hop 路径
hop_count = len(hops); hop_path = ','.join(hops)
a_is_hub = 1 if site_a_id in hub_sites else 0   # 依赖 master_site_db.hub_site
```

而且 `a_is_hub/b_is_hub` **依赖 `master_site_db` 的当前内容**（实测 hub 站点 168 个）。
→ topology 必须走「专用导入器」，且**要在 master_site_db 更新之后再跑**，否则 hub 标记会错。
另外 `Sheet2`/`Sheet3` 是空表（1×1），必须跳过。

---

## 3. 附带风险

1. **数据被清空的风险（最大）**：`master_site_db` 被 805 行、`topology` 被 GIS 地图
   （`backend/routers/gis.py:922` `/api/gis/topology`）和 `import_topology.py` 依赖。
   用 `if_exists="replace"` 一旦传错文件，业务表当场清空。
   → 必须要有**预览 + 影响行数 + 二次确认**，并落备份。
2. **WAL 与大库**：`app.db` 已 1.58 GB 且开着 WAL，写入期间要避免和 worker 抢锁。
3. **并发**：有 6 个 `backend.worker` 进程在跑，导入应加锁/串行。
4. **`app.db` 被占用**：`instance.lock` 存在，说明有实例锁机制，需沿用。

---

## 4. 建议方案

**分三档，建议做第 2 档。**

### 档 1：最小可用（改动小，1 个接口 + 1 个 UI 区块）
在 `?page=upload` 增加「映射模式」开关：

1. 选文件 → 前端调 `POST /api/upload/inspect`，回传每个 sheet 的**名字、行数、表头预览**；
2. 每个 sheet 一行，用户从下拉里选目标表（默认用库内 `SHEET_TABLE_MAP` 反查，查不到留空）；
3. 每个 sheet 给「跳过 / 追加 / 替换」三选一 + **表头所在行**输入框（解决问题 B）；
4. 提交 `POST /api/upload/apply`，后端逐 sheet 写入，返回每张表**变更前后行数**。

这一步能覆盖 9 个结构规整的 sheet（master_site_db、eflow_database、flm_database、
flm_team_new、sla_priority、victim_topology、satellite_sites、era_sites、landlord_sites）。

### 档 2：档 1 + topology 专用导入器（推荐）
在档 1 基础上加一个 `importers/` 注册表：

```python
IMPORTERS = {
  "topology": import_topology_impl,      # 复用 import_topology.py 的 hop 展开 + hub 标记
  "gateway_sites": ...,                  # 处理 6 列 vs 56 行的口径差异
}
```

并在 UI 上**强制顺序**：先 `master_site_db`，再 `topology`（因为 hub 标记有依赖），
导入完成后自动重建 `idx_topology_site_a/b` 索引。

### 档 3：完全自动化（映射存库 + 定时）
把映射关系做成 `_sheet_table_map` 表，实现「拖文件 → 自动按映射入库」，
并支持「映射变更留痕」。适合后续频繁更新。

### 无论哪档都必须有的护栏
- **备份**：导入前 `ALTER TABLE x RENAME TO x_bak_<ts>`（或导出 parquet），保留最近 3 份；
- **预览**：提交前显示「表 / 列名映射 / 行数 old→new / 新增列 / 丢失列」；
- **禁止空导入**：解析出 0 行直接报错，不放行（正是问题 B 的兜底）；
- **dry-run**：`?dry_run=1` 只回报告不落库；
- **复用**：直接调用 `backend/dialect_helpers.py` 的 `write_df`，它已兼容 sqlite/PG 双模。

---

## 5. 工作量估算

| 项 | 内容 | 量级 |
|---|---|---|
| 后端 | `inspect` + `apply` 两个接口、映射解析、护栏、备份 | ~250–400 行 |
| 前端 | `DataUpload.tsx` 加映射表格 + 确认弹窗 | ~150–250 行 |
| topology | 把 `import_topology.py` 包成可调用导入器 | ~60 行 |
| 验证 | 4 个「无表头」sheet 的表头行确认、gateway 口径核对 | 需你确认业务口径 |

主要不确定项**不在代码，在业务口径**：`GateWay Sites` sheet 767 行 vs 库 56 行、
`Special Sites`/`ISP Sites` 两个 sheet 已消失但表还在 —— 这两个需要你确认「以哪个为准」。

---

## 6. 一句话回答（第一轮，`?page=upload` 视角）

**能做到。** `?page=upload` 页面和上传链路本来就是通的，库表也都在；
但现有接口**故意只写一次性 `upload_*` 表**，所以要新增「sheet → 目标表」的映射式导入
（可参考已有的 `POST /api/tables/import`），并且要专门处理 topology 的 hop 展开、
4 个 sheet 没有表头行、以及 sheet 名已漂移这三件事。建议先做档 2 并配齐预览/备份护栏。

---

## 7. 更正：应该走 `?page=tables`，不是 `?page=upload`
**结论：你的判断正确，`?page=tables` 是更好的落点。** 实测对比如下：

| 能力 | `?page=upload` (`/api/upload`) | `?page=tables` (`/api/tables/import`) |
|---|---|---|
| 能否指定目标表名 | ❌ 强制 `upload_<uuid>_*` | ✅ 有 `table_name` 输入框 |
| 能否覆盖已存在表 | ❌ 永远不会 | ✅ 有 `overwrite` 勾选框（→ `if_exists="replace"`） |
| 能否只导某个 sheet | ❌ 全部 sheet 都导 | ✅ 有 sheet 下拉（`tables.py:346` 的 `sheet` 参数） |
| 前端是否已实现 | 无 sheet/表选择 UI | ✅ 弹窗已完整实现 |
| 结果反馈 | 质量画像 | 表名 + 行数/列数 |

前端已有完整交互：`TableBrowser.tsx:447` 的「导入」按钮 → `:526-598` 的
`importModalTitle` 弹窗（选文件 → sheet 下拉 → 表名 → 覆盖勾选 → 提交）。
后端 `tables.py:341` 的 `POST /api/tables/import` 也已支持 `sheet` 参数
（`:382-401`，传 `__all__`/空 表示全部）。

**所以不用重写通道，只要在现有弹窗上补齐三件事。** 另外修正我在第一轮的说法：
`TableBrowser.tsx:183` 传的 `sheet` 字段后端**是认的**（`tables.py:346`），前端弹窗
只在 `importSheets.length > 1` 时才显示 sheet 下拉，逻辑是自洽的。

### 7.1 `?page=tables` 路线仍需补的 3 个缺口

1. **一次只能导一个 sheet**（缺口最明显）。
   `tables.py:417-424` 的规则是「单 sheet 用 `table_name`；多 sheet 追加 `_<sheet>`」。
   所以想更新 12 个 sheet → 要**手工导 12 次**，且每次表名都不能打错
   （`Master Site Database ` 带尾随空格，极易输错）。
   → 建议加「映射模式」：一次传整文件，弹窗里每个 sheet 一行、各选目标表，一次提交。

2. **没有「无表头行」处理**。`pd.read_excel` 默认 `header=0`，而 4 个 sheet 第 1 行不是表头
   （见 §2 问题 B）→ 会把标题行当数据写进表。需要 `header` 参数 + 每 sheet 可调。

3. **覆盖是「哑覆盖」，没有护栏**。
   `if_exists="replace"` 会**先 DROP 再建**，一旦传错文件 `master_site_db` 当场清空。
   而它被 `gis.py:36`、`site_availability_service.py:288`、`eflow_data_mapper.py:1257`、
   `mw_ume_topology.py:475` 多处依赖。→ 必须加备份 + 行数预览 + 二次确认。

### 7.2 建议的最小改动清单（都在现有通道上扩）

| # | 位置 | 改动 |
|---|---|---|
| 1 | `tables.py` `import_excel_to_table` | 新增 `header_row` 表单参数（默认 0） |
| 2 | `tables.py` 新增 `POST /api/tables/import/preview` | 只回「每 sheet 的候选表名 + 表头预览 + 行数 + 目标表现有行数」，不落库 |
| 3 | `tables.py` `import_excel_to_table` | 导入前把目标表 `RENAME TO <表>_bak_<ts>` 备份 |
| 4 | `tables.py` `import_excel_to_table` | 解析出 0 行 → 400 拦截（防问题 B） |
| 5 | `TableBrowser.tsx` import 弹窗 | 由「一个表名」改为「sheet 列表 × 每行一个目标表下拉」 |
| 6 | `TableBrowser.tsx` import 弹窗 | 冲突时（目标表已存在）显示行数 old→new 并要求勾选确认 |

第 2 项是关键：**先预览再提交**，才能避免 §3 里「数据被清空」的最大风险。

---

## 8. MW 相关：哪些还没进库 / 已进库但该淘汰

你问「mw 用到了哪些选择没有在数据库里面」。实测逐项核对（表存在性 + 行数）如下。

### 8.1 库中存在但 **Excel 已经没有来源 sheet**（3 张，建议确认后淘汰或补数据源）

| 表 | 行数 | 原 sheet | 问题 |
|---|---|---|---|
| `flm_team` | 34 | `FLM Team information` | 已被 `FLM Team information `（带空格）→ `flm_team_new` 取代；`flm_team` 列名全是 `unnamed_1..unnamed_10`，**说明当初导入时根本没识别到表头** |
| `isp_sites` | 50 | `ISP Sites` | sheet 已从文件删除，表成孤儿 |
| `special_sites` | 31 | `Special Sites` | 同上 |

`flm_team` 的 `unnamed_*` 列名是**问题 B 的直接受害者**——证明「无表头行」不是假设，
而是已经造成过实际脏数据。这条强烈支持 §7.1 第 2 点（`header_row` 参数）的必要性。

### 8.2 sheet 存在但**映射表没有** → 目前只能手工导入（2 张）

| Sheet | 库里对应表 | 状态 |
|---|---|---|
| `VIP site List` | `vip_site_list` | 表在（50 行），但 `SHEET_TABLE_MAP` 里没这条，自动导入会漏 |
| `Startlink ERA sites` | `startlink_era_sites` | 表在（41 行），同样不在映射表 |

### 8.3 **完全没有表**（1 张）——这是真正的缺口

| Sheet | 目标表 | 状态 |
|---|---|---|
| `E-flow Database` | `eflow_database` | ❌ **表不存在** |

注意：库里另有 `eflow_site`(808 行)、`eflow_tt`、`eflow_wo` 等表，但
`eflow_database` 这张确实不在。`E-flow Database` sheet 有 771 行 / 42 列，
是 `master_site_db`(805 行) 之外最大的一张业务表。
→ **这是「要改成能通过页面导入来更新」时第一个必须补上的表。**

### 8.4 MW Topology 文件（独立通道，不走上面映射）

- `ZTE OLR MS MW Topology _OSS.xlsx` → `Sheet1`(776 行) → 表 `topology`（515 行）
- 另两个 `Sheet2`/`Sheet3` 是空表（1×1），**必须跳过**
- 该表**不能整表 replace**，需 hop 展开 + 依赖 `master_site_db.hub_site`（见 §2 问题 C）
- 且 `mw_ume_topology.py:475` 也读 `master_site_db` 做 site_id 映射
  → **导入顺序必须是：先 `master_site_db`，再 `topology`**

### 8.5 完整映射建议（可直接作为弹窗默认值）

把下面这张表落成 `_sheet_table_map`（存库），弹窗打开时自动预填，用户可改：

```
Master Site Database          -> master_site_db        (优先，被 topology 依赖)
E-flow Database               -> eflow_database        (表不存在，需新建)
FLM Database                  -> flm_database
FLM Team information          -> flm_team_new
SLA and Tickes Priority       -> sla_priority
Victim topology（Pradeep update)-> victim_topology
Satellite sites list          -> satellite_sites
ERA(VIP&No-VIP）               -> era_sites
GateWay Sites                 -> gateway_sites         (口径待确认: sheet 767 行 vs 表 56 行)
LandLord and AML Sites        -> landlord_sites
VIP site List                 -> vip_site_list         (映射表原来没有)
Startlink ERA sites           -> startlink_era_sites   (映射表原来没有)
```
（`Special Sites` / `ISP Sites` / `FLM Team information`(无空格) 已无 sheet，不出现在候选里）

MW Topology 文件单独走 `topology` 导入器，不在上面这张表内。

---

## 9. 修正后的一句话回答

**走 `?page=tables` 更对。** 它的导入弹窗和 `POST /api/tables/import` 已经具备
「指定表名 + 覆盖已存在表 + 选 sheet」三项能力，不用新建通道；
只需在它上面补 3 件事：**① 多 sheet 一次映射到多张表（现在得手工导 12 次）、
② `header_row` 参数（`flm_team` 的 `unnamed_*` 列就是被这个坑出来的）、
③ 备份 + 预览 + 0 行拦截护栏（防 `master_site_db` 被清空）。**

MW 侧的真实缺口是：**`E-flow Database` → `eflow_database` 表根本不存在，必须先补**；
`VIP site List`、`Startlink ERA sites` 两张表在但不在映射表里，会自动漏掉；
`special_sites`、`isp_sites`、`flm_team` 三张表已成孤儿（来源 sheet 被删）。

---

## 10. 定稿：以 MW 两个页面为准（第三轮，最终口径）

**范围约束（按你的要求）**
1. 以 `?page=mwRealTime` 和 `?page=mwUmeTopology` **实际用到的表**为准；
2. **不修改数据库里其他任何表**；
3. 缺表则新建；
4. 保证这两个页面能用。

### 10.1 两个页面实际用到的表（已实测追踪）

两个页面都是 iframe 承载独立 HTML（`MwRealTimeDashboard.tsx` / `MwUmeDashboard.tsx`
→ `LegacyToolFrame`），各自只打一个 API：

| 页面 | HTML | API | 数据表 |
|---|---|---|---|
| `?page=mwUmeTopology` | `public/mw_ume_topology.html:997` | `/api/mw-ume/topology` | `mw_ume_bw_ultilazation` |
| `?page=mwRealTime` | `public/mw_real_time.html:962` | `/api/mw-ume/realtime` | `mw_ume_bw_ultilazation_rt` |

但 `mw_ume_topology.py` 在**构建**拓扑时还要读另外两张表，这才是关键：

| 表 | 行数 | 用途（实测代码位置） | 现状 |
|---|---|---|---|
| `mw_ume_bw_ultilazation` | 35,379 | 日粒度 KPI（`TABLE_NAME`, `:43`） | ✅ 存在，由任务每日 05:15 同步 |
| `mw_ume_bw_ultilazation_rt` | 74,467 | 15 分钟 KPI（`RT_TABLE_NAME`, `:46`） | ✅ 存在，由任务每 15 分钟同步 |
| `zte_mw_links` | 374 | **物理链路骨架 + 站点经纬度 + 链路 A→B 方向**（`:140/229/420`） | ⚠️ 存在，但**只能手工维护** |
| `master_site_db` | 805 | site_name → site_id 映射（`:475`）+ hub 标记 | ✅ 存在，有 Excel 来源 |

**两个 API 实测均正常**（实测返回 `nodes=649 edges=373`，`nodes_without_coords=0`）。
即：页面现在是**能用的**。

### 10.2 真正的缺口：`zte_mw_links` 完全没有导入通道

这是本轮最重要的发现。在**全仓库**（backend + scripts + 根目录）搜索：

- `INSERT INTO zte_mw_links` → **0 处**
- `CREATE TABLE ... zte_mw_links` → **0 处**
- `write_df(... zte_mw_links ...)` → **0 处**

`zte_mw_links` 在 `mw_ume_topology.py` 里**只有读、没有写**（28 处引用全是 SELECT/缓存）。
而且它决定了三件对页面效果至关重要的事：

1. **拓扑骨架**：`_load_phys_cache()`（`:404-444`）用它的**全表**作为 nodes/edges 基础；
2. **站点经纬度**：`_load_site_cache()`（`:123-161`）按 IP 精确匹配优先、站名兜底；
   → 坐标缺失会直接让**地理布局**画不出来；
3. **链路方向**：`_load_link_orientations()`（`:205-240`）用 `ip_address_a/b` 把无向链路
   锚定成 A→B 单向；未命中时回退旧双向口径（`:275` 注释明说「保证页面有数」）。

字段：`site_id_a, sit_a_ran_name, site_a_lat, site_a_lon, site_id_b,
site_b_ran_name, site_b_lat, site_b_lon, ip_address_a, ip_address_b`（10 列，374 行）。

→ **结论：要让这两个页面「通过页面导入来更新」，要新建的就是 `zte_mw_links` 的导入通道。**
这正好符合你说的「如果没有则要新建」。

### 10.3 好消息：刷新机制已经现成，不用重启后端

`mw_ume_topology.py` 的缓存设计对「页面导入」极其友好：

- `get_topology(force=True)`（`:774-779`）会依次 `_reset_site_cache()`、
  `_reset_link_orientation()`、`_reset_phys_cache()` 再重读；
- `_load_site_cache()` 的注释（`:177`）明确写着：
  「zte_mw_links 坐标被人工修正后，**点页面「刷新」即可生效，无需重启后端**」。

→ 所以导入 `zte_mw_links` 后，页面点「刷新」（即 `/api/mw-ume/topology?refresh=1`）
就能看到新数据。**无需改 `mw_ume_topology.py`。**

### 10.4 建议方案：`?page=tables` 加「MW 链路导入」，只碰 `zte_mw_links`

严格遵守「不改其他表」的约束，具体做法：

| # | 改动 | 说明 |
|---|---|---|
| 1 | `POST /api/tables/import` 加 `header_row` 参数（默认 0） | 通用能力，不针对某表 |
| 2 | 新增 `POST /api/mw-ume/links/import` | **专用**导入器，只写 `zte_mw_links` |
| 3 | `?page=tables` 导入弹窗加一个「MW 物理链路」预设 | 选中后表名锁死为 `zte_mw_links`，不给改成别的 |
| 4 | 导入前 `RENAME TO zte_mw_links_bak_<ts>` 备份 | 保留最近 3 份 |
| 5 | 导入后自动调 `get_topology(force=True)` 清缓存 | 页面刷新即生效 |

**第 3 条是关键的安全设计**：把目标表**锁死**，从 UI 上就杜绝了误改
`master_site_db` / `mw_ume_bw_*` 的可能，正好满足你「不要修改数据库其他表」的要求。

如果 `zte_mw_links` 的数据来源也是 Excel（比如现有的
`ZTE OLR MS MW Topology _OSS.xlsx`，它是 26 列的 A/B + hop 路径格式），
则第 2 步就是在导入时做字段映射：

```
Site A      -> site_id_a          Site B       -> site_id_b
Site A Name -> sit_a_ran_name     Site  Name B -> site_b_ran_name
（经纬度需从 master_site_db 按 site_id 补，或由用户提供列映射）
```
**这一步需要你确认**：`zte_mw_links` 的 374 行原始来源是哪个文件/系统？
现有两个 xlsx 里都没有 10 列这个形态的数据。

### 10.5 与「不改其他表」冲突的一处，需你拍板

按第 10.1 节，MW 页面还依赖 `master_site_db`（读 site_id 映射 + hub 标记）。
它**不是 MW 专属表**，还被 GIS（`gis.py:36`）、站点可用率（`site_availability_service.py:288`）、
eFlow 映射（`eflow_data_mapper.py:1257`）等共用。

所以「更新 MW 所需数据」和「不修改其他表」在 `master_site_db` 上有一点张力：
- 若只在 MW 范围内更新，**`master_site_db` 应保持不动**（它现在是好的，映射实测已加载）；
- 若它也需要更新，建议走**单独的一次操作**，而不是混在 MW 导入里。

**我的建议：本轮只做 `zte_mw_links`，`master_site_db` 不动。** 这样最安全，
且两页实测已经正常（`nodes=649 edges=373`，坐标 0 缺失）。

### 10.6 最终结论

1. MW 两个页面实际依赖 **4 张表**，全部存在且 API 实测正常；
2. 其中 **`zte_mw_links` 是唯一没有任何导入通道的表**，也正是「要新建」的那个；
3. 它的刷新机制现成（`?refresh=1` 即可生效），**不用改 `mw_ume_topology.py`**；
4. 建议在 `?page=tables` 加一个**目标表锁死为 `zte_mw_links`** 的专用导入，
   从 UI 上杜绝误改其他表，完全满足「不改数据库其他表」；
5. 唯一待你确认：**`zte_mw_links` 的 374 行原始数据来自哪里**（现有两个 xlsx 都没有这个格式）。

---

## 11. 已实施：KML 叠加图层入库（`kml_mw_links`）

**状态：已完成并验证。** `master_site_db` 等业务表零改动。

### 11.1 问题确认

`MW LINKS.kml`（2.2 MB，1694 站点 + 847 链路）原先只由脚本转换：

```
mw_links_sync.bat -> kml_to_geojson.py -> frontend/public/mw_ume_orange_links.geojson
                                       -> 复制到 _fe_dist/
```

两个 MW 页面用 `fetch('./mw_ume_orange_links.geojson')` 消费这个**静态文件**，
所以每次更新都要跑脚本 + 手工部署。

### 11.2 交付物

| 文件 | 作用 |
|---|---|
| `backend/services/mw_ume/mw_links_store.py` | KML 解析 + `kml_mw_links` 读写 + GeoJSON 生成 |
| `backend/routers/mw_links.py` | 3 个接口（status / geojson / import + rebuild） |
| `backend/main.py` | 注册 `mw_links.router` |
| `frontend/public/mw_ume_topology.html` | 改为「先试 DB 接口，失败回退静态文件」 |
| `frontend/public/mw_real_time.html` | 同上 |
| `frontend/src/pages/TableBrowser.tsx` | 新增「MW Links (KML)」导入按钮 + 弹窗 |
| `frontend/src/i18n.tsx` | 中英文案 |

**新表 `kml_mw_links`**（2534 行）：

```
kind, name, a, b, lon, lat, lon2, lat2,
color, antenna_a, antenna_b, remark, _source_file, _import_time
```
- `kind='site'`：`lon/lat` 为站点坐标
- `kind='link'`：`lon/lat` 为 A 端，`lon2/lat2` 为 B 端

### 11.3 接口

| 接口 | 说明 |
|---|---|
| `GET /api/mw-links/status` | 行数/站点数/链路数/导入时间 |
| `GET /api/mw-links/geojson` | 从库里生成 GeoJSON（页面消费） |
| `POST /api/mw-links/import` | 上传 `.kml`，整表替换 + 自动备份 |
| `POST /api/mw-links/rebuild` | 由库重建静态回退副本 |

### 11.4 安全设计（满足「不改其他表」）

1. **表名硬编码**：`TABLE_NAME = "kml_mw_links"` 是模块常量，接口**不接受表名参数**，
   从代码层面杜绝写入 `master_site_db` / `mw_ume_bw_*`。
2. **UI 无表名输入框**：`?page=tables` 的 MW 导入弹窗只选 KML 文件，不给改表名的入口。
3. **自动备份 + 轮转**：导入前 `ALTER TABLE ... RENAME TO kml_mw_links_bak_<ts>`，
   只保留最近 3 份。
4. **双保险渲染**：页面先请求 DB 接口，失败才回退静态文件 → 接口异常也不会白屏。

### 11.5 验证结果

| 项 | 结果 |
|---|---|
| 上传导入（HTTP 端到端） | ✅ 返回 1690 站点 / 844 链路，0.4s |
| `kml_mw_links` | ✅ 2534 行 |
| `GET /api/mw-links/geojson` | ✅ 2534 要素 |
| mwUmeTopology API | ✅ `nodes=649 edges=373` |
| mwRealTime API | ✅ `nodes=649 edges=373` |
| 两页 HTML 含 DB 接口 | ✅ 均为 True |
| `master_site_db` | ✅ 805 行，未变 |
| `zte_mw_links` / `topology` / 其余 | ✅ 全部未变 |
| 备份轮转 | ✅ 保留 2 份（<=3） |

### 11.6 顺带修正了一个既有 Bug

旧转换脚本 `kml_to_geojson.parse_endpoints()`（`:67-79`）**从来没能解析出站名**——
KML 的 `<description>` 以裸 `<br>` 开头，`ET.fromstring("<root>" + desc + "</root>")`
必抛 `ParseError`，于是静默回退到「按 `-` 拆分 placemark 名称」。

结果：**13 条链路的两端站名被拆错**，例如：

| 实际站名 | 旧脚本错误输出 |
|---|---|
| `New Site-7` → `Sue Town` | `New Site` → `7-Sue Town` |
| `Du-Port Road Junction` → `Duport Road` | `Du` → `Port Road Junction-Duport Road` |
| `Po-River` → `Ricks` | `Po` → `River-Ricks` |

新解析器先剥掉 `<table>` 之前的裸标签再解析，并加正则兜底。
**几何坐标与站点完全不变**（实测 `link geometry identical: True`、`site points identical: True`），
只是这 13 条链路的 A/B 站名修正为正确值。同时新增了解析 `Antenna Height` 与 `Link Remark`
（实测 remark 分布：ZTE 573 / NEC 232 / NEC IX 27 / HUAWEI 12，与颜色分组完全吻合）。

### 11.7 后续可选项（未做）

- 把 `mw_links_sync.bat` 与静态 geojson 彻底移除（验证稳定后再做）
- 将 `zte_mw_links` 也做成页面导入（它目前只能手工维护，374 行）

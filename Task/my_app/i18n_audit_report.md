# my_app 国际化（i18n）系统审计报告

- 审计对象：`D:\01_RPA\Task\my_app`
- 审计日期：2026-08-05
- 审计方式：静态全量扫描（`TMP/i18n_audit.py`、`i18n_audit_en.py`、`i18n_classify.py`、`i18n_backend_scan.py`）+ 后端实测（`curl -H "Accept-Language: en|zh-CN" /api/tasks`）
- 覆盖范围：前端 22 个 `.tsx/.ts`（7157 行）、后端 62 个 `.py`、`index.html`、`public/warehouse-dashboard.html`

---

## 1. 架构现状

| 项 | 现状 |
|---|---|
| 方案 | 自研 React Context（`frontend/src/i18n.tsx`），**无** react-i18next/FormatJS |
| 语言 | `zh` / `en`，单文件内联字典 |
| 键总量 | zh **413**，en **412** |
| 回退链 | `translations[locale][key]` → `translations['zh'][key]` → `key` |
| 持久化 | `localStorage['app-locale']`，缺省探测 `navigator.language` |
| 组件库 | antd `ConfigProvider locale` 已随语言切换（`zhCN`/`enUS`）✅ |
| 后端协商 | `Accept-Language` 头，仅 `/api/tasks`、`/api/tasks/{id}` 两个端点 |

**结论：机制本身可用且设计合理，问题全部出在「覆盖率」和「实现一致性」。**

---

## 2. 缺陷清单（按严重度）

### P0 — 界面直接暴露原始 key（3 处）

`t()` 调用了字典中不存在的键，回退链最终返回 key 字符串本身，中英文模式下都会把 `batt.count` 这类技术标识符渲染到界面上。

| 键 | 位置 | 渲染位置 |
|---|---|---|
| `batt.count` | `pages/BatteryDashboard.tsx:399` | ECharts 趋势图 **右侧 Y 轴名称** |
| `batt.samples` | `pages/BatteryDashboard.tsx:406` | ECharts 趋势图 **图例/series 名** |
| `gis.drilldown.colTTNo` | `pages/gismap/helpers.tsx:160` | WO 明细表 **列头** |

修复：在 `i18n.tsx` 的 zh/en 两侧各补 3 个键。

---

### P1 — 整页未国际化

#### 2.1 `pages/TTWODashboard.tsx`（687 行）— 覆盖率 0%
文件第 15 行 `import { useI18n }`、第 68 行 `const { t } = useI18n()`，**但全文 0 次 `t()` 调用**，`t` 变量被解构后从未使用。全部 37 处面向用户文案为英文硬编码：

- KPI 标签：`TT Total` / `WO Total` / `WO No. (Unique)`
- 卡片标题：`TT Statistics` / `MTTR Weekly Trend` / `Domain & Root Cause Analysis` / `Work Order Analytics` / `Site Information`
- 图表标题：`Ticket Severity` / `SLA Status` / `TT by Domain` / `Root Cause (Main)` / `Root Cause (Sub)` / `WO by Source` / `WO by Status`
- 时间筛选：`All Time` / `Last 7 days` / `Last 30 days` / `Last 3 months` / `Last 6 months` / `Custom`
- 状态文案：`Loading TT&WO data...` / `Failed to load TT&WO Dashboard data` / `No data returned`
- 占位符：`All Regions` / `Search across all fields...`
- 图表轴名：`TT Count` / `MTTR (min)`

字典中 **`ttwo.*` 命名空间条目数 = 0**，即从未为该页建过翻译。

#### 2.2 `pages/AlarmDashboard.tsx`（732 行）— 覆盖率约 10%
仅 4 处 `t()`（`alarm.drillHint`、`alarm.dispatchedWithTT`、`alarm.overdueDesc`、`alarm.recordCount`），其余 37 处英文硬编码：`Total Active Alarms`、`Affected Sites`、`Total Alarm Hours`、`Critical Alerts`、`History Alarm Dispatch Timeliness`、`Dispatch Delay (Eflow)`、`Alarm Fetch Delay`、`Dispatch Overdue Total`、`Alarm Breakdown`、`Technology Distribution`、`Severity Distribution`、`Network Type`、`Regional Alarm Profile` 等。

另有 **2 处中文硬编码**，且其中一处是死三元：
```tsx
// AlarmDashboard.tsx:88  —— 两个分支完全相同，判断无意义
{label !== 'Critical Alerts' ? '点击下钻' : '点击下钻'} <RightOutlined/>
// AlarmDashboard.tsx:582
点击下钻 <RightOutlined/>
```
字典里已有 `alarm.drillHint`（zh `点击下钻明细 →` / en `Click to drill down →`），第 118 行也正确用了它 —— 88、582 两处属遗漏。

#### 2.3 `pages/WarehouseDashboard.tsx` — 完全脱离 i18n 体系
该页是 `<iframe src="warehouse-dashboard.html">`，静态 HTML（116 KB）**不接收语言上下文**，语言恒定不变。且其中含中文 `alert()` 文案（`邮件发送成功！`、`请输入收件人邮箱地址：`、`邮件发送失败: ...`）混在英文界面里。

连带后果：字典中 **12 个 `sp.*` 键全部成为死键**（`sp.inbound`/`sp.outbound`/`sp.inventory`/`sp.ocRule`/`sp.transfer`/`sp.closed`/`sp.unclosed`/`sp.countByTable`/`sp.invTypeDist`/`sp.detailTables`/`sp.searchPlaceholder`/`sp.loadRowsError`/`sp.lastSync`），系早期 React 版遗留。

---

### P1 — Task Manager 模块：三套 i18n 机制并存

`pages/DataSync.tsx` + `pages/datasync/*` 同时使用三种方式，无统一规范：

| 机制 | 用量 | 说明 |
|---|---|---|
| `t('key')` | 16 处 | 标准方式 |
| `locale === 'zh' ? '中文' : 'EN'` 内联三元 | **66 处** | 能切换，但文案散落在 JSX 里，无法集中维护/复用 |
| `label_zh` / `label_en` 对象字段 | 32 组 | `helpers.tsx` 的 `CRON_PRESETS`、`CATEGORY_CONFIG`；`DataSync.tsx` 的 `ROW_GROUPS` |

连带后果：**8 个 `sync.*` 键成为死键**（`sync.title`/`sync.subtitle`/`sync.syncNow`/`sync.syncing`/`sync.syncSuccess`/`sync.syncFailed`/`sync.noHistory`）—— 页面重写时改用了三元，旧键未清理。

#### 该模块内的确定性 BUG

**① `DataSync.tsx:606` — 分类筛选下拉在英文模式下混排中文**
```tsx
options={[
  { value: 'all', label: locale === 'zh' ? '全部分类' : 'All Categories' },  // ✅ 会切换
  ...Object.keys(CATEGORY_CONFIG).map(c => ({ value: c, label: CATEGORY_CONFIG[c].label_zh })),  // ❌ 写死 label_zh
]}
```
英文模式下该下拉显示为：`All Categories` / `eFlow 数据` / `通用` / `SP 备件` / `邮件报告` / `电池 KPI` … 中英混排。
同文件 441 行、686 行的同类调用都正确写了 `locale === 'zh' ? label_zh : label_en`，仅此处漏判。

**② `DataSync.tsx:657` — 失败任务兜底文案硬编码**
```tsx
{firstLine(t.recent_runs?.[0]?.error || '未知错误')}
```
英文模式下失败任务卡片显示"未知错误"。

---

### P1 — 后端调用链标注全中文（28/28）

实测 `GET /api/tasks` 携带 `Accept-Language: en`：
- `name` / `description`：**28 个任务全部正确返回英文**，无一残留中文 ✅
- `call_chain`：**28/28 全部含中文**，且英文模式下原样透出到前端 Tooltip ❌

示例（EN 模式实际返回）：
```
sync_from_eflow_api (backend/services/sync_from_eflow_api.py:485)
  ⟵ [DB: app.db (db/app.db, 主) ; DB: eflow.sqlite3 (data/eflow/, 报告生成副产品) ;
     API: eFlow (10.100.20.8) ; 远程DB: db.sqlite3 (via db_writer API, ...) ;
     远程FTP: tt_reports 上传 (FTP_REMOTE_DIR, 默认 /Python)]
```
标注文本在 `backend/services/task_runner.py` 的 `TASK_IO` / `CALL_CHAIN_IO` 两张表里，目前是单语字符串。

---

### P2 — 后端错误文案全中文直传前端（43 处）

后端 `HTTPException.detail` 与响应字段中的中文，被前端**拼接在已翻译前缀之后**直接展示，产生"英文前缀 + 中文详情"的混合语言：

```tsx
// CredentialSettings.tsx:76
message.error(t('settings.saveFailed') + ': ' + e?.response?.data?.detail)
// EN 模式实际效果：Save failed: 未知凭据组: xxx

// DataUpload.tsx:58
message.error(t('upload.failed', { msg: err.response?.data?.detail }))
// EN 模式实际效果：Upload failed: 仅支持 .xlsx, .xls, .csv 文件
```

分布：`main.py` 5、`routers/tables.py` 6、`routers/credentials.py` 8、`routers/gis.py` 4、`routers/analysis.py` 4、`routers/upload.py` 3、`routers/battery_dashboard.py` 3、`services/task_runner.py` 10。

典型条目：`任务 {task_id} 未找到`、`表 {table_name} 不存在`、`表为空，无法分析`、`非法排序列名`、`仅支持 .xlsx, .xls, .csv 文件`、`未知凭据组`、`用户名和密码不能同时为空`、`无电池数据（请执行任务: battery_kpi_sync）`、`凭据已保存，最迟 30 秒后生效`、`任务正在运行中`。

同时 `main.py:170` 直接返回硬编码 `"schedule": "每小时第22分钟"`。

---

### P2 — 文档级 / 格式化问题

| 问题 | 位置 | 影响 |
|---|---|---|
| `<html lang="zh-CN">` 固定 | `frontend/index.html:2` | 英文模式下 lang 属性错误，影响屏幕阅读器发音、浏览器"翻译此页"判断、SEO |
| `<title>数据洞察 SaaS MVP</title>` 固定中文 | `frontend/index.html:6` | 浏览器标签页恒为中文；且与字典 `app.title`（数据洞察 MVP / Data Insight MVP）文案不一致 |
| `toLocaleString()` 未传 locale（**10 处**） | AlarmDashboard ×2、TTWODashboard ×4、PacketLossDashboard、Dashboard、DataUpload、TableBrowser | 千分位分隔符跟随**浏览器**语言而非**应用**语言。`DataSync.tsx:255` 是唯一正确写法（显式传 `zh-CN`/`en-US`），应作为范本 |
| dayjs locale 从未导入设置 | 全局 | 当前 4 种格式均为 `YYYY-MM-DD` 类固定模式，暂无可见问题；一旦使用 `.fromNow()` 或本地化格式将恒为英文 |

---

### P2 — Provider 时序（潜在，当前无可见症状）

```tsx
<I18nProvider>            {/* useEffect → setApiLocale(locale) */}
  <TaskStatusProvider>    {/* useEffect → api.get('/tasks')  */}
```
React 副作用**自子向父**执行，`TaskStatusProvider` 的首个 `/tasks` 请求先于 `setApiLocale` 完成，该请求不带应用层 `Accept-Language`（退化为浏览器头）。

当前无可见影响：`TaskStatusContext` 只读取 `t.running` 布尔字段，不消费 `name`/`description`。但该竞态是隐患 —— 若后续在此 Provider 中使用文案字段即会出现首屏语言错误。

建议：把 `setApiLocale(detectLocale())` 提到模块初始化（`api.ts` 或 `main.tsx`）同步执行，而非依赖 effect。

---

### P3 — 字典卫生

| 项 | 数量 | 明细 |
|---|---|---|
| 重复键 | **0** | zh / en 均无重复定义 ✅ |
| 占位符不一致 | **0** | 385 个共有键的 `{n}`/`{col}`/`{msg}` 全部对齐 ✅ |
| en 缺失键 | 1 | `gis.exportSuccess`（zh 有 en 无）。该键当前未被使用，无实际影响，但会静默回退中文 |
| en 值仍为中文 | 1 | `lang.switch: '中文'` —— **属正确设计**（切换按钮显示目标语言），非缺陷 |
| en 空串 | 3 | `overview.tableSuffix` / `overview.rowSuffix` / `table.scoreUnit` —— **属正确设计**（中文量词"表/行/分"英文不需要），非缺陷 |
| 死键（定义未使用） | **28** | `sp.*` ×13、`sync.*` ×8、`common.*` ×4（`items`/`noData`/`seconds`/`total`）、`overview.tableSuffix`/`rowSuffix`、`gis.exportSuccess`、`lang.current` |
| 动态 `t(变量)` 调用 | **0** | 所有 `t()` 均为字面量键，静态可分析性良好 ✅ |

---

## 3. 量化总览

```
字典键          zh 413 / en 412        重复 0    占位符不一致 0
实际使用         388 键                 未定义 3   死键 28
硬编码中文       112 命中 → 真缺陷 21    （其余为注释 47 / locale 三元 44）
硬编码英文        88 命中 → 真缺陷 74    （其余为 aria-label / 数据值 / 属性名等误报 14）
后端中文外泄      43 处 + call_chain 28 条
```

**按页面覆盖率（`t()` 调用数）**

| 页面 | t() 次数 | 评价 |
|---|---|---|
| BatteryDashboard | 113 | ✅ 优 |
| PacketLossDashboard / GISMap / gismap.helpers | 50 / 50 / 50 | ✅ 优 |
| SiteDrilldownDrawer | 31 | ✅ 良 |
| ArchiveList / TableBrowser / Dashboard | 28 / 26 / 26 | ✅ 良 |
| CredentialSettings / DataUpload / App | 23 / 21 / 18 | ✅ 良 |
| Overview | 11 | ✅ 良 |
| **DataSync** | 15（+66 三元） | ⚠️ 机制混乱 |
| **AlarmDashboard** | **4** | ❌ 差 |
| **TTWODashboard** | **0** | ❌ 无 |
| **WarehouseDashboard** | **0** | ❌ 体系外（iframe） |
| datasync/TaskHistoryModal、helpers | 0 | ⚠️ 全部走三元 / label_zh |

---

## 4. 修复建议（按投入产出排序）

| # | 动作 | 工作量 | 收益 |
|---|---|---|---|
| 1 | 补 3 个未定义键（`batt.count`/`batt.samples`/`gis.drilldown.colTTNo`） | 5 分钟 | **消除界面暴露技术 key** |
| 2 | 修 `DataSync.tsx:606` 改 `locale === 'zh' ? label_zh : label_en`；`:657` 兜底文案改 `t()` | 10 分钟 | 消除下拉中英混排 |
| 3 | `AlarmDashboard.tsx:88/582` 改用已有 `t('alarm.drillHint')`，删除死三元 | 5 分钟 | 消除中文泄漏 |
| 4 | `index.html`：`lang` 由 JS 按 locale 写入 `document.documentElement.lang`，`title` 用 `t('app.title')` 动态设置 | 15 分钟 | 无障碍 / 浏览器行为正确 |
| 5 | 10 处 `toLocaleString()` 统一改为 `toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US')`（参照 `DataSync.tsx:255`） | 30 分钟 | 数字格式与应用语言一致 |
| 6 | `setApiLocale` 移出 effect，改模块初始化同步调用 | 10 分钟 | 消除首屏语言竞态 |
| 7 | 后端错误改为**错误码 + 参数**（如 `{"code":"TASK_NOT_FOUND","params":{"id":...}}`），前端用 `err.<code>` 键渲染 | 半天 | 根除 43 处混合语言 |
| 8 | **TTWODashboard 全量国际化**：新建 `ttwo.*` 命名空间约 40 键 | 半天 | 补齐最大缺口 |
| 9 | **AlarmDashboard 全量国际化**：扩充 `alarm.*` 至约 45 键 | 半天 | 补齐第二大缺口 |
| 10 | Task Manager 三套机制统一到 `t()`；`CRON_PRESETS`/`CATEGORY_CONFIG`/`ROW_GROUPS` 的 `label_zh/label_en` 改为存 key，渲染时 `t(key)` | 1 天 | 可维护性 |
| 11 | 清理 28 个死键；或为 `sp.*` 找回落点（若计划把 Warehouse 从 iframe 迁回 React） | 1 小时 | 字典卫生 |
| 12 | `call_chain` 标注双语化：`TASK_IO`/`CALL_CHAIN_IO` 值改 `{"zh":..., "en":...}`，`_annotate_call_chain` 按 lang 取值 | 半天 | 英文模式完整可读 |
| 13 | 拆分 `i18n.tsx`（958 行）为 `locales/zh.ts` + `locales/en.ts`；加 CI 校验脚本（键对齐 / 未定义键 / 占位符）阻断回归 | 半天 | 防回归 |

**最小可行修复（#1–#6，约 1.5 小时）即可消除全部"界面显示原始 key / 中英混排 / 中文泄漏"类可见缺陷。**

---

## 5. 做得好的部分

- 键命名规范统一（`模块.子模块.语义`），无重复、无冲突
- 385 个共有键的插值占位符 **100% 对齐**，无 `{n}`/`{col}` 错配
- 所有 `t()` 均为字面量键，**零动态键**，静态分析与提取工具友好
- 三层回退（locale → zh → key）避免了白屏/undefined
- antd `ConfigProvider` 已正确联动，日期选择器、分页器、表格空状态等组件内建文案随语言切换
- 后端任务名/描述双语字段 **28/28 全覆盖**，`name_en`/`description_en` 无一遗漏，实测 EN 响应零中文残留
- `en` 侧刻意的空串（量词后缀）与 `lang.switch` 反向显示，说明作者对细节有考虑
- BatteryDashboard、PacketLoss、GISMap 三大模块国际化质量高，可作为其余页面的实现范本

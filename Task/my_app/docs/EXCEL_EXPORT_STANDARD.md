# 项目统一 Excel 导出格式（UNIFIED_EXCEL_V1）

所有看板/报表页面的「导出 Excel」都必须使用本格式，避免每个页面各写一套。
本规范与后端邮件报表生成器
`backend/services/sp_report_gen/gernarate_sp_report.py`（`style_excel` / `style_summary_changed`）
**同源**——Web 导出与邮件附件长得一样。

## 1. 前端模块

```
frontend/src/utils/excelReport.ts
```

基于 `exceljs`（社区版 `xlsx` 不支持写样式，已替换）。对外 API：

| 函数 | 说明 |
| --- | --- |
| `exportReport(sheets, filename)` | 主力入口。多 sheet、带样式，自动触发浏览器下载 |
| `buildReportWorkbook(sheets)` | 只构建 `Workbook`，不下载（单测 / 二次加工用） |
| `exportAoaReport({...})` | 单 sheet 快捷入口，直接替换裸 `XLSX.utils.aoa_to_sheet([header, ...rows])` |
| `downloadBlob(buf, filename)` / `safeFileName(name)` | 底层下载 / 文件名净化 |
| `SHEET_TAB_COLORS` / `UNIFIED_EXCEL_VERSION` | 标签页配色表 / 版本标记 |

> **sheet 名由模块统一净化**（`uniqueSheetName`，内部函数）：替换 Excel 禁用字符 `* ? : \ / [ ]`、
> 截断到 31 字符、重名追加 `_2`。传入业务名即可，**调用方不要自己 `substring(0,31)` 或写去重循环**。
> 这三条都是 ExcelJS 的**硬性限制，违反会直接抛错**（非静默降级）。

### `ReportSheetSpec` 字段

```ts
{
  name: string                    // sheet 名（>31 字符会被截断）
  title?: string                  // 第 1 行标题（不传则不生成标题行）
  subtitle?: string               // 第 2 行灰字；默认 "Generated: <时间>    |    Sheet: <名>"
  tabColor?: string               // '#2F5496' / 'FF2F5496'；不传按 name 查 SHEET_TAB_COLORS
  header: string[] | HeaderCell[][]   // 单层 / 多层（带合并）
  rows: CellValue[][]             // 数据行
  totalRow?: CellValue[]          // 合计行，插在表头与数据之间
  numericCols?: number[]          // 数字列下标（0 基）：右对齐 + #,##0
  valueColors?: boolean | number[]// 数值着色：0 灰 / >0 加粗绿 / <0 加粗红
  columnWidths?: number[]         // 指定列宽；不传则自动算
  autoWidth?: boolean             // 默认 true
  freeze?: boolean                // 默认 true，冻结在表头下方
  autoFilter?: boolean            // 默认 true
}
```

多层表头用 `HeaderCell`，`colSpan` 横向合并、`rowSpan` 纵向合并；
`fill: 'accent'` 走橙色分组底纹（对齐邮件报表的 Summary-Changed）。

## 2. 视觉规范（改样式只改这一处）

| 位置 | 规格 |
| --- | --- |
| 第 1 行 标题 | Calibri 14 bold `#1F3864`，左对齐，横向合并整表 |
| 第 2 行 副标题 | Calibri 9 `#808080`，`Generated: <时间>    |    Sheet: <名>` |
| 表头 | Calibri 11 bold `#FFFFFF` / 底纹 `#2F5496`，居中 + 自动换行，细框 `#B4C6E7` + 底边中粗 `#4472C4` |
| 分组表头 | 底纹 `#FF8C00`（橙） |
| 数据行 | Calibri 10，隔行底纹 `#F2F2F2` / `#FFFFFF`，细框 `#B4C6E7`，数字右对齐 + `#,##0` |
| 合计行 | Calibri 11 bold `#1F3864` / 底纹 `#D6DCE4`，上下中粗框 `#4472C4` |
| 数值着色 | `0` → `#C0C0C0`；`>0` → bold `#006100`；`<0` → bold `#9C0006` |
| 列宽 | `min(max(内容最长 + 2, 10), 42)`，最多扫描前 200 行 |
| 冻结 | 冻结在表头下方 |
| 筛选 | 自动筛选覆盖表头行 → 末行 |
| 页面 | 横向、按宽度缩放到 1 页、页边距 `0.4/0.4/0.5/0.5`（header/footer `0.3`） |
| 标签页色 | Summary `#2F5496` / Inbound `#548235` / Outbound `#BF8F00` / Inventory `#843C0C` |

> 隔行底纹按**工作表绝对行号**奇偶判断（偶数行 `#F2F2F2`），与 Python 端 `_apply_zebra` 完全一致。

## 3. 用法示例

### 单表（最常见的迁移场景）

```ts
import { exportAoaReport } from '../utils/excelReport'

await exportAoaReport({
  filename: `site_availability_${day}.xlsx`,
  sheetName: 'Site Availability',
  title: 'Site Availability Detail',
  header: ['Site ID', 'Site Name', 'Availability'],
  rows: rows.map(r => [r.site_id, r.site_name, r.availability]),
  numericCols: [2],
  tabColor: '#2F5496',
})
```

### 多层合并表头 + 合计行

见 `frontend/src/pages/SpMaterialSummary.tsx` 的 `exportExcel`：
两层表头（`rowSpan` 的 WH/DOP + `colSpan` 的日期/消耗窗口）、合计行、消耗列数值着色。

## 4. 迁移清单

> **状态：前端导出已全部迁移完成（2026-09-24）。** 全仓已无裸 `xlsx` 写文件调用，
> 校验命令：`Select-String -Path frontend\src\pages\*.tsx -Pattern "XLSX\.utils\.(aoa|json)_to_sheet|XLSX\.writeFile"`
> 应返回空（`utils\excelReport.ts` 内部的注释除外）。
>
> ⚠ **本表的「已迁移」只表示"已改用 `utils/excelReport`、不再裸用 `xlsx`"，不表示"页面上有导出入口"。**
> 下表有多页原先**只有下钻弹窗内的导出按钮**，页面级入口是缺的；2026-09-27 起按下节补。判据要分开看。

### 4.1 页面级导出入口（2026-09-27 补充）

**判据：用户打开该页，不点任何数字/不看弹窗，能否直接在工具栏看到导出按钮。**

此前用「全文是否出现 `common.exportExcel`」做判据是错的 —— 弹窗内的按钮也会命中，
于是 `ttwo`（含 `v1_ttwo`）、`alarm`、`site_avail`、`fme_ranking`、`ran_cells_kpi`、
`ms_sla`、`nur`、`ume_in_kpi` 八页被误判为"已有导出"，实际页面上都没有入口。

| 文件 | 仅弹窗导出 → 页面级入口 |
| --- | --- |
| `pages/TTWODashboard.tsx` | ✅ 2026-09-27 补（`exportOverview`，同时惠及 `v1_ttwo` 切片页） |
| `pages/AlarmDashboard.tsx` | ✅ 2026-09-27 补 |
| `pages/SiteAvailability.tsx` | ✅ 2026-09-27 补（多 sheet：汇总指标 + 站点明细） |
| `pages/FmeRanking.tsx` | ✅ 2026-09-27 补 |
| `pages/RanCellsKpi.tsx` | ✅ 2026-09-27 补 |
| `pages/MsSlaDashboard.tsx` | ✅ 2026-09-27 补 |
| `pages/NurDashboard.tsx` | ✅ 2026-09-27 补 |
| `pages/UmeInKpi.tsx` | ✅ 2026-09-27 补 |

**导出内容一律为"当前页显示的全部汇总数据"**（沿用各页既有 `useMemo` 结果，不在导出里另起一套计算），
筛选条件写进 `subtitle`。空块自动跳过；取不到数据输出 `—` 而非 `0`。

| 文件 | 状态 |
| --- | --- |
| `pages/SpMaterialSummary.tsx` | ✅ 已迁移（汇总 + 下钻明细） |
| `pages/SiteAvailability.tsx` | ✅ 已迁移 + 页面级入口（2026-09-27） |
| `pages/RanCellsKpi.tsx` | ✅ 已迁移（多 sheet）+ 页面级入口（2026-09-27） |
| `pages/PacketLossDashboard.tsx` | ✅ 已迁移 |
| `pages/AlarmDashboard.tsx` | ✅ 已迁移 + 页面级入口（2026-09-27） |
| `pages/BatteryDashboard.tsx` | ✅ 已迁移（原 `json_to_sheet`） |
| `pages/MsSlaDashboard.tsx` | ✅ 已迁移 + 页面级入口（2026-09-27） |
| `pages/NurDashboard.tsx` | ✅ 已迁移 + 页面级入口（2026-09-27） |
| `pages/TTWODashboard.tsx` | ✅ 已迁移 + 页面级入口（2026-09-27，含 `v1_ttwo`） |
| `pages/gismap/helpers.tsx` | ✅ 已迁移 |
| `pages/FmeRanking.tsx` | ✅ 已迁移 + 页面级入口（2026-09-27） |
| `pages/UmeInKpi.tsx` | ✅ 已迁移 + 页面级入口（2026-09-27） |
| `pages/CnKpi.tsx` | ✅ 已迁移（多 sheet，元信息行保留在数据区） |
| `pages/RepeatSiteDown.tsx` | ✅ 已迁移（原 `json_to_sheet`） |
| `pages/EflowQa.tsx` | ✅ 导出已迁移。**仍 import `xlsx`**：用于上传清单文件的**解析**（`XLSX.read`），非导出用途，应保留 |
| `pages/TableBrowser.tsx` | ⛔ **无需迁移**：导出走后端接口 `GET /api/tables/{name}/export`，前端不生成 Excel。**仍 import `xlsx`** 用于上传文件解析 |
| `pages/DataUpload.tsx`、`pages/Help.tsx` | ⛔ 无需迁移：同样仅用 `xlsx` 做上传解析 |

### 4.0 迁移要点（留给后续新页面）

- **单表** → `exportAoaReport({ filename, sheetName, title, header, rows, numericCols, columnWidths, tabColor })`。
  它直接替代 `XLSX.utils.aoa_to_sheet([header, ...rows])` + `book_new` + `book_append_sheet` + `writeFile` 四连。
- **多表** → `exportReport(sheets, filename)`，`sheets: ReportSheetSpec[]`。
- **`json_to_sheet` 的替代**：`json_to_sheet` 会按对象键自动生成列头，`exportAoaReport` 不会。
  迁移时须显式取键：`const keys = Object.keys(rows[0])`，再 `header: keys` / `rows: rows.map(r => keys.map(k => r[k] ?? ''))`，
  否则列头与列序会与原来不一致。
- **sheet 名不要自己截断/去重**：`xlsx` 的 `substring(0,31)` 惯用法可以删掉。
  `excelReport` 的 `uniqueSheetName()` 已统一处理「禁用字符 `* ? : \ / [ ]` 替换」+「31 字符截断」
  +「重名追加 `_2`」，且处理了**截断后才撞名**的边界情况
  （此三种情形下 ExcelJS 会**直接抛错**，实测：`Worksheet name already exists` / `cannot include any of the following characters`）。
- **非表格的前置说明行**（如 CnKpi 的口径/SQL 文本）继续放在 `rows` 里，
  不要塞进 `subtitle` —— `subtitle` 是为 `Generated: <时间> | Sheet: <名>` 之类固定格式准备的。

### 4.1 服务端导出（openpyxl）

上述前端模块基于 `exceljs`。原生看板（17 个，见 `backend/services/dashboard_service.py`
的 `build_excel`）因一次要导 10+ 个 sheet、且需在服务端复用已取好的数据，改为
**服务端 openpyxl 生成后以 blob 下发**（`GET /api/native-boards/{slug}/export`）。

两端配色/字号取值**保持同源**，改样式时须同时改：

| 元素 | 取值 |
| --- | --- |
| 标题 | Calibri 14 bold `#1F3864`，横向合并 |
| 副标题 | Calibri 9 `#808080`，`Generated: <时间>    |    Sheet: <名>` |
| 表头 | Calibri 11 bold `#FFFFFF` / 底纹 `#2F5496` |
| 数据行 | Calibri 10，偶数绝对行号底纹 `#F2F2F2` |
| 边框 | 细框 `#B4C6E7` |
| 冻结/筛选 | 冻结表头下方；`auto_filter` 覆盖表头→末行 |
| 页面 | 横向、`fitToWidth=1` |
| 数字列 | 右对齐 + `#,##0` |

每个 sheet 名取组件标题（>31 字符截断、非法字符替换 `_`、重名加 `_2` 后缀），
另附首个「说明」sheet 记录看板名/数据源/时间窗口/取数时间，便于对账。

## 5. 注意事项

- 改动本模块后需重新 `vite build`；**不需要重启后端**（纯前端静态资源）。
- 构建产物校验：`grep -l "2F5496" <dist>/assets/SpMaterialSummary-*.js`。
- ExcelJS 的 `ws.getCell(r, c)` 对**已被合并覆盖**的格子会返回主格，
  因此写表头时用「占用位图」跳过被上方 `rowSpan` 占用的列，合并统一放在写值之后
  （`Cell.merge` 会自动把主格样式同步给覆盖格）。改 `buildSheet` 时务必保持这个顺序。

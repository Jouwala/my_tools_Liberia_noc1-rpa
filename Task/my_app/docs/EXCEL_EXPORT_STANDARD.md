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

仍在用裸 `xlsx`（无样式）的导出点，建议逐个迁到本模块：

| 文件 | 状态 |
| --- | --- |
| `pages/SpMaterialSummary.tsx` | ✅ 已迁移（汇总 + 下钻明细） |
| `pages/SiteAvailability.tsx` | ⬜ 待迁移 |
| `pages/RanCellsKpi.tsx` | ⬜ 待迁移（多 sheet） |
| `pages/PacketLossDashboard.tsx` | ⬜ 待迁移 |
| `pages/AlarmDashboard.tsx` | ⬜ 待迁移 |
| `pages/BatteryDashboard.tsx` | ⬜ 待迁移 |
| `pages/MsSlaDashboard.tsx` | ⬜ 待迁移 |
| `pages/NurDashboard.tsx` | ⬜ 待迁移 |
| `pages/TTWODashboard.tsx` | ⬜ 待迁移 |
| `pages/gismap/helpers.tsx` | ⬜ 待迁移 |

## 5. 注意事项

- 改动本模块后需重新 `vite build`；**不需要重启后端**（纯前端静态资源）。
- 构建产物校验：`grep -l "2F5496" <dist>/assets/SpMaterialSummary-*.js`。
- ExcelJS 的 `ws.getCell(r, c)` 对**已被合并覆盖**的格子会返回主格，
  因此写表头时用「占用位图」跳过被上方 `rowSpan` 占用的列，合并统一放在写值之后
  （`Cell.merge` 会自动把主格样式同步给覆盖格）。改 `buildSheet` 时务必保持这个顺序。

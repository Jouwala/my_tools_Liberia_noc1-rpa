/**
 * 项目统一 Excel 导出格式 —— UNIFIED_EXCEL_V1
 * =============================================================================
 * 视觉规范与后端邮件报表生成器
 *   backend/services/sp_report_gen/gernarate_sp_report.py  (style_excel /
 *   style_summary_changed) 完全一致，两边同源：
 *
 *   行 1  Title     : Calibri 14 bold  #1F3864，左对齐，横向合并整表
 *   行 2  Subtitle  : Calibri 9        #808080，`Generated: <时间>    |    Sheet: <名>`
 *   行 3+ Header    : Calibri 11 bold  #FFFFFF / 底纹 #2F5496，居中 + 自动换行
 *                     分组表头底纹用 #FF8C00（橙色，对齐 Summary-Changed）
 *   数据行          : Calibri 10，隔行底纹 #F2F2F2 / #FFFFFF，细边框 #B4C6E7
 *                     数字右对齐 + 千分位 `#,##0`
 *   合计行          : Calibri 11 bold  #1F3864 / 底纹 #D6DCE4，上下中粗框 #4472C4
 *   数值着色        : 0 -> #C0C0C0，>0 -> bold #006100（对齐 Summary-Changed）
 *   列宽            : min(max(内容最长 + 2, 10), 42)，最多扫描前 200 行
 *   冻结            : 冻结在表头下方；自动筛选覆盖表头行
 *   页面            : 横向、按宽度缩放到 1 页、页边距 0.4/0.4/0.5/0.5
 *   标签页颜色      : Summary #2F5496 / Inbound #548235 / Outbound #BF8F00 / Inventory #843C0C
 *
 * 用法（新页面直接套用，替代裸 XLSX.utils.aoa_to_sheet）：
 *
 *   import { exportReport } from '../utils/excelReport'
 *
 *   await exportReport(
 *     [{
 *       name: 'Site Availability',
 *       title: 'Site Availability Detail',
 *       tabColor: '#2F5496',
 *       header: ['Site ID', 'Site Name', 'Availability'],
 *       rows: rows.map(r => [r.site_id, r.site_name, r.availability]),
 *       numericCols: [2],
 *     }],
 *     'site_availability_2026-09-11.xlsx',
 *   )
 *
 * 多行表头（带横向合并）用 HeaderCell[][]：
 *   header: [
 *     [{ text: 'WH/DOP', rowSpan: 2 },
 *      { text: 'Current Date', colSpan: 2 }, ...],
 *     [{ text: 'Spare Part (Good)' }, { text: 'Consumables' }, ...],
 *   ]
 */
import ExcelJS from 'exceljs'

/** 便于在构建产物里 grep 的版本标记 */
export const UNIFIED_EXCEL_VERSION = 'UNIFIED_EXCEL_V1'

// =============================================================================
// 样式常量（与 Python 端一一对应）
// =============================================================================
const C = {
  titleText: 'FF1F3864',
  subtitleText: 'FF808080',
  headerText: 'FFFFFFFF',
  headerFill: 'FF2F5496',
  accentFill: 'FFFF8C00',
  totalText: 'FF1F3864',
  totalFill: 'FFD6DCE4',
  zebraFill: 'FFF2F2F2',
  whiteFill: 'FFFFFFFF',
  zeroText: 'FFC0C0C0',
  posText: 'FF006100',
  negText: 'FF9C0006',
  thinBorder: 'FFB4C6E7',
  mediumBorder: 'FF4472C4',
}

const FONT_TITLE: Partial<ExcelJS.Font> = { name: 'Calibri', size: 14, bold: true, color: { argb: C.titleText } }
const FONT_SUBTITLE: Partial<ExcelJS.Font> = { name: 'Calibri', size: 9, color: { argb: C.subtitleText } }
const FONT_HEADER: Partial<ExcelJS.Font> = { name: 'Calibri', size: 11, bold: true, color: { argb: C.headerText } }
const FONT_CELL: Partial<ExcelJS.Font> = { name: 'Calibri', size: 10 }
const FONT_TOTAL: Partial<ExcelJS.Font> = { name: 'Calibri', size: 11, bold: true, color: { argb: C.totalText } }
const FONT_ZERO: Partial<ExcelJS.Font> = { name: 'Calibri', size: 10, color: { argb: C.zeroText } }
const FONT_POS: Partial<ExcelJS.Font> = { name: 'Calibri', size: 10, bold: true, color: { argb: C.posText } }
const FONT_NEG: Partial<ExcelJS.Font> = { name: 'Calibri', size: 10, bold: true, color: { argb: C.negText } }

const ALIGN_HEADER: Partial<ExcelJS.Alignment> = { horizontal: 'center', vertical: 'middle', wrapText: true }
const ALIGN_CELL: Partial<ExcelJS.Alignment> = { vertical: 'middle', wrapText: false }
const ALIGN_NUM: Partial<ExcelJS.Alignment> = { horizontal: 'right', vertical: 'middle' }
const ALIGN_LEFT: Partial<ExcelJS.Alignment> = { horizontal: 'left', vertical: 'middle' }

const NUM_FMT_INT = '#,##0'

function fill(argb: string): ExcelJS.Fill {
  return { type: 'pattern', pattern: 'solid', fgColor: { argb } }
}

const FILL_HEADER = fill(C.headerFill)
const FILL_ACCENT = fill(C.accentFill)
const FILL_TOTAL = fill(C.totalFill)
const FILL_ZEBRA = fill(C.zebraFill)
const FILL_WHITE = fill(C.whiteFill)

const S_THIN: Partial<ExcelJS.Border> = { style: 'thin', color: { argb: C.thinBorder } }
const S_MEDIUM: Partial<ExcelJS.Border> = { style: 'medium', color: { argb: C.mediumBorder } }
const BORDER_HEADER: Partial<ExcelJS.Borders> = { left: S_THIN, right: S_THIN, top: S_THIN, bottom: S_MEDIUM }
const BORDER_CELL: Partial<ExcelJS.Borders> = { left: S_THIN, right: S_THIN, top: S_THIN, bottom: S_THIN }
const BORDER_TOTAL: Partial<ExcelJS.Borders> = { left: S_THIN, right: S_THIN, top: S_MEDIUM, bottom: S_MEDIUM }

/** 与 Python 端 SHEET_COLORS 一致 */
export const SHEET_TAB_COLORS: Record<string, string> = {
  Summary: 'FF2F5496',
  Inbound: 'FF548235',
  Outbound: 'FFBF8F00',
  Inventory: 'FF843C0C',
}

// =============================================================================
// 类型
// =============================================================================
export type CellValue = string | number | boolean | Date | null | undefined

export interface HeaderCell {
  text: string
  /** 横向合并的列数，默认 1 */
  colSpan?: number
  /** 纵向合并的行数，默认 1 */
  rowSpan?: number
  /** 底色：header=深蓝(默认) / accent=橙色分组 / none=不填 */
  fill?: 'header' | 'accent' | 'none'
}

export interface ReportSheetSpec {
  /** sheet 名（Excel 限制 31 字符，超出会被截断） */
  name: string
  /** 第 1 行标题；不传则不生成标题行 */
  title?: string
  /** 第 2 行副标题；默认 `Generated: <本地时间>    |    Sheet: <name>` */
  subtitle?: string
  /** 标签页颜色，ARGB 或 #RRGGBB；不传则按 name 查 SHEET_TAB_COLORS */
  tabColor?: string
  /** 表头：单层 string[]，或多层 HeaderCell[][] */
  header: string[] | HeaderCell[][]
  /** 数据行（二维数组，列顺序与表头一致） */
  rows: CellValue[][]
  /** 合计行，插在表头与数据之间，套用 Total 样式 */
  totalRow?: CellValue[]
  /** 数字列下标（0 基）：右对齐 + 千分位格式 */
  numericCols?: number[]
  /** 数据区数值着色：true=全部数字列，number[]=仅指定列（0 基）；0 -> 灰、>0 -> 加粗绿、<0 -> 加粗红 */
  valueColors?: boolean | number[]
  /** 指定列宽（字符数，按列顺序）；不传则自动计算 */
  columnWidths?: number[]
  /** 是否自动计算列宽，默认 true */
  autoWidth?: boolean
  /** 是否冻结表头，默认 true */
  freeze?: boolean
  /** 是否加自动筛选，默认 true */
  autoFilter?: boolean
}

export interface ExportReportOptions {
  /** 单 sheet 快捷入口用：标题 */
  title?: string
  subtitle?: string
  tabColor?: string
  numericCols?: number[]
  columnWidths?: number[]
}

// =============================================================================
// 内部工具
// =============================================================================
function normalizeHeader(header: string[] | HeaderCell[][]): HeaderCell[][] {
  if (!header.length) return [[]]
  if (typeof header[0] === 'string') {
    return [(header as string[]).map(text => ({ text: String(text) }))]
  }
  return (header as HeaderCell[][]).map(row => row.map(h => ({ ...h })))
}

function headerWidth(rows: HeaderCell[][]): number {
  return rows.reduce((m, row) => Math.max(m, row.reduce((s, h) => s + (h.colSpan || 1), 0)), 0)
}

function argb(color?: string): string | undefined {
  if (!color) return undefined
  const c = color.replace('#', '').toUpperCase()
  return c.length === 6 ? `FF${c}` : c
}

function localTimestamp(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} `
    + `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function isNumeric(v: CellValue): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

/** 触发浏览器下载 */
export function downloadBlob(data: ArrayBuffer | Uint8Array, filename: string) {
  const blob = new Blob([data as unknown as BlobPart], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.setTimeout(() => URL.revokeObjectURL(url), 2000)
}

/** 文件名净化（去掉 Windows/Excel 非法字符） */
export function safeFileName(name: string): string {
  return (name || 'report').replace(/[\\/:*?"<>|\r\n\t]/g, '_').slice(0, 120)
}

// =============================================================================
// 核心：构建单个 sheet
// =============================================================================
function buildSheet(wb: ExcelJS.Workbook, spec: ReportSheetSpec) {
  const ws = wb.addWorksheet(spec.name.slice(0, 31), {
    views: [],
    pageSetup: {
      orientation: 'landscape',
      fitToPage: true,
      fitToWidth: 1,
      fitToHeight: 0,
      margins: { left: 0.4, right: 0.4, top: 0.5, bottom: 0.5, header: 0.3, footer: 0.3 },
    },
  })

  const tab = argb(spec.tabColor) || SHEET_TAB_COLORS[spec.name]
  if (tab) ws.properties.tabColor = { argb: tab }

  const hasTitle = !!spec.title
  const headerRows = normalizeHeader(spec.header)
  const ncol = Math.max(
    headerWidth(headerRows),
    spec.rows.reduce((m, r) => Math.max(m, r.length), 0),
    spec.totalRow ? spec.totalRow.length : 0,
    1,
  )

  // ---- 标题 / 副标题 ----
  if (hasTitle) {
    ws.mergeCells(1, 1, 1, ncol)
    const t = ws.getCell(1, 1)
    t.value = spec.title as string
    t.font = FONT_TITLE
    t.alignment = ALIGN_LEFT

    ws.mergeCells(2, 1, 2, ncol)
    const s = ws.getCell(2, 1)
    s.value = spec.subtitle || `Generated: ${localTimestamp()}    |    Sheet: ${spec.name}`
    s.font = FONT_SUBTITLE
    s.alignment = ALIGN_LEFT
  }

  // ---- 表头 ----
  const headerStart = hasTitle ? 3 : 1
  const headerEnd = headerStart + headerRows.length - 1
  // 已被上方 rowSpan 占用的格子（避免下一行表头写串列 —— ExcelJS 的 getCell 对
  // 已合并的覆盖格会返回主格，直接顺序写会把整行左移）
  const occupied: boolean[][] = headerRows.map(() => new Array(ncol + 2).fill(false))
  for (let ri = 0; ri < headerRows.length; ri++) {
    let col = 1
    for (const h of headerRows[ri]) {
      while (col <= ncol && occupied[ri][col]) col++
      const colSpan = h.colSpan || 1
      const rowSpan = h.rowSpan || 1
      const r1 = headerStart + ri
      const r2 = r1 + rowSpan - 1
      const c1 = col
      const c2 = col + colSpan - 1
      if (rowSpan > 1 || colSpan > 1) ws.mergeCells(r1, c1, r2, c2)
      // 合并后覆盖格会自动继承主格样式（ExcelJS Cell.merge 默认同步 style）
      const cell = ws.getCell(r1, c1)
      cell.value = h.text
      cell.font = FONT_HEADER
      cell.fill = h.fill === 'none' ? FILL_WHITE : (h.fill === 'accent' ? FILL_ACCENT : FILL_HEADER)
      cell.alignment = ALIGN_HEADER
      cell.border = BORDER_HEADER
      for (let rr = ri; rr < ri + rowSpan && rr < headerRows.length; rr++) {
        for (let cc = c1; cc <= c2; cc++) occupied[rr][cc] = true
      }
      col += colSpan
    }
  }

  const numericCols = new Set(spec.numericCols || [])
  const vc = spec.valueColors
  const vcAll = vc === true
  const vcSet = Array.isArray(vc) ? new Set(vc) : null
  const colorOn = (colIdx: number) => vcAll || (vcSet ? vcSet.has(colIdx) : false)
  const styleCell = (
    cell: ExcelJS.Cell,
    value: CellValue,
    rowIdx: number,
    colIdx: number,
    zebra: boolean,
    opts: { total?: boolean; valueColors?: boolean },
  ) => {
    cell.value = (value === undefined ? null : value) as ExcelJS.CellValue
    const baseFill = zebra ? FILL_ZEBRA : FILL_WHITE
    if (opts.total) {
      cell.font = FONT_TOTAL
      cell.fill = FILL_TOTAL
      cell.border = BORDER_TOTAL
    } else {
      cell.fill = baseFill
      cell.border = BORDER_CELL
      if (opts.valueColors && isNumeric(value)) {
        cell.font = value === 0 ? FONT_ZERO : (value > 0 ? FONT_POS : FONT_NEG)
      } else {
        cell.font = FONT_CELL
      }
    }
    if (isNumeric(value)) {
      cell.alignment = ALIGN_NUM
      cell.numFmt = NUM_FMT_INT
    } else if (numericCols.has(colIdx)) {
      cell.alignment = ALIGN_NUM
    } else {
      cell.alignment = ALIGN_CELL
    }
  }

  let r = headerEnd + 1
  // ---- 合计行 ----
  if (spec.totalRow) {
    for (let c = 0; c < ncol; c++) {
      styleCell(ws.getCell(r, c + 1), spec.totalRow[c], r, c, r % 2 === 0, { total: true })
    }
    r += 1
  }
  const dataStart = r
  // ---- 数据行 ----
  for (const row of spec.rows) {
    for (let c = 0; c < ncol; c++) {
      styleCell(ws.getCell(r, c + 1), row[c], r, c, r % 2 === 0, { valueColors: colorOn(c) })
    }
    r += 1
  }
  const lastRow = r - 1

  // ---- 列宽 ----
  const autoWidth = spec.autoWidth !== false
  for (let c = 1; c <= ncol; c++) {
    const column = ws.getColumn(c)
    if (spec.columnWidths && spec.columnWidths[c - 1] != null) {
      column.width = spec.columnWidths[c - 1]
      continue
    }
    if (!autoWidth) continue
    // 与 Python _auto_width 同口径：min(max(最长内容 + 2, 10), 42)，最多扫前 200 行
    let maxLen = 0
    if (hasTitle && c === 1) {
      maxLen = Math.max(
        String(spec.title || '').length,
        String(spec.subtitle || `Generated: ${localTimestamp()}    |    Sheet: ${spec.name}`).length,
      )
    }
    const scanTo = Math.min(lastRow, headerEnd + 200)
    for (let rr = headerStart; rr <= scanTo; rr++) {
      const v = ws.getCell(rr, c).value
      if (v !== null && v !== undefined) maxLen = Math.max(maxLen, String(v).length)
    }
    column.width = Math.min(Math.max(maxLen + 2, 10), 42)
  }

  // ---- 冻结 / 筛选 ----
  if (spec.freeze !== false) {
    ws.views = [{ state: 'frozen', ySplit: headerEnd, xSplit: 0 }]
  }
  if (spec.autoFilter !== false && lastRow >= headerEnd) {
    ws.autoFilter = {
      from: { row: headerEnd, column: 1 },
      to: { row: lastRow, column: ncol },
    }
  }
  return ws
}

// =============================================================================
// 对外 API
// =============================================================================
/** 构建工作簿（不下载），便于单测 / 二次加工 */
export function buildReportWorkbook(specs: ReportSheetSpec[]): ExcelJS.Workbook {
  const wb = new ExcelJS.Workbook()
  wb.creator = 'NOC Dashboard'
  wb.created = new Date()
  for (const s of specs) buildSheet(wb, s)
  return wb
}

/** 生成并下载多 sheet 报表（项目统一格式） */
export async function exportReport(specs: ReportSheetSpec[], filename: string): Promise<void> {
  const wb = buildReportWorkbook(specs)
  const buf = await wb.xlsx.writeBuffer()
  downloadBlob(buf as ArrayBuffer, safeFileName(filename).endsWith('.xlsx') ? safeFileName(filename) : `${safeFileName(filename)}.xlsx`)
}

/**
 * 单 sheet 快捷入口 —— 直接替换裸 `XLSX.utils.aoa_to_sheet([header, ...rows])`。
 * 保持与旧代码同形的入参，方便各页面无痛迁移到统一格式。
 */
export async function exportAoaReport(opts: {
  filename: string
  sheetName?: string
  title?: string
  header: string[]
  rows: CellValue[][]
  numericCols?: number[]
  columnWidths?: number[]
  tabColor?: string
}): Promise<void> {
  await exportReport(
    [{
      name: opts.sheetName || 'Sheet1',
      title: opts.title,
      header: opts.header,
      rows: opts.rows,
      numericCols: opts.numericCols,
      columnWidths: opts.columnWidths,
      tabColor: opts.tabColor,
    }],
    opts.filename,
  )
}

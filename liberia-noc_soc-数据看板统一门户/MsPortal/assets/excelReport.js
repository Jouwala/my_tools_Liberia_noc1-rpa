/* ==========================================================================
   MsPortal — 统一 Excel 导出格式 UNIFIED_EXCEL_V1（下钻 / 明细弹窗共用）
   --------------------------------------------------------------------------
   本文件是 my_app 那份统一格式的 **1:1 移植**，只把 TS 换成无构建的 ES5 写法：

     · my_app 前端  frontend/src/utils/excelReport.ts      （UNIFIED_EXCEL_V1）
     · my_app 后端  backend/services/sp_report_gen/gernarate_sp_report.py
                    （style_excel / style_summary_changed，两边同源同规范）

   视觉规范（与上面两份逐条对齐，改这里就要同步改那边）：

     行 1  Title     : Calibri 14 bold  #1F3864，左对齐，横向合并整表
     行 2  Subtitle  : Calibri 9        #808080，`Generated: <时间>    |    Sheet: <名>`
     行 3+ Header    : Calibri 11 bold  #FFFFFF / 底纹 #2F5496，居中 + 自动换行
                       分组表头底纹用 #FF8C00（橙色，对齐 Summary-Changed）
     数据行          : Calibri 10，隔行底纹 #F2F2F2 / #FFFFFF，细边框 #B4C6E7
                       数字右对齐 + 千分位 `#,##0`
     合计行          : Calibri 11 bold  #1F3864 / 底纹 #D6DCE4，上下中粗框 #4472C4
     数值着色        : 0 -> #C0C0C0，>0 -> bold #006100，<0 -> bold #9C0006
     列宽            : min(max(内容最长 + 2, 10), 42)，最多扫描前 200 行
     冻结            : 冻结在表头下方；自动筛选覆盖表头行
     页面            : 横向、按宽度缩放到 1 页、页边距 0.4/0.4/0.5/0.5
     标签页颜色      : Summary #2F5496 / Inbound #548235 / Outbound #BF8F00 / Inventory #843C0C

   用法（MsPortal 里任何下钻/明细弹窗都套这个，不要再手写 CSV）：

     MsExcelReport.exportAoaReport({
       filename: 'qc-wo-20260920_1412.xlsx',
       sheetName: 'WOs',
       title: 'WOs · Details',
       subtitle: 'Generated: ... | Sheet: WOs | Search: "fiber"',
       header: columns.map(c => c.label),
       rows: rows.map(row => columns.map(c => row[c.key])),
     })

   ExcelJS 不打进 index.html：它约 0.9MB，只有真点「导出 Excel」时才
   loadExcelJS() 按需注入 assets/vendor/exceljs.min.js（本机静态，无 CDN 依赖）。
   ========================================================================== */
(function (root, factory) {
  /* 双模：浏览器挂 window.MsExcelReport；Node 里 require 得到同一份实现，
     便于用真实接口数据离线校验产物（见 TMP 里的校验脚本）。 */
  if (typeof module === 'object' && module.exports) module.exports = factory(root);
  else root.MsExcelReport = factory(root);
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';

  /** 便于在构建产物里 grep 的版本标记 */
  var UNIFIED_EXCEL_VERSION = 'UNIFIED_EXCEL_V1';

  /* 自身脚本地址 → assets/ 目录。ExcelJS 就放在它旁边的 vendor/ 下，
     这样无论页面挂在 /MsPortal/ 还是 /MsPortal/index.html 都能定位。 */
  var SELF_SRC = (typeof document !== 'undefined' && document.currentScript &&
                  document.currentScript.src) || '';
  var ASSET_BASE = SELF_SRC ? SELF_SRC.replace(/[^/]*$/, '') : 'assets/';
  var EXCELJS_SRC = ASSET_BASE + 'vendor/exceljs.min.js';

  // ===========================================================================
  // 样式常量（与 my_app 前端 excelReport.ts / 后端 style_excel 一一对应）
  // ===========================================================================
  var C = {
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
    mediumBorder: 'FF4472C4'
  };

  /* 样式对象一律现造：ExcelJS 把传入的对象直接挂在单元格 style 上，
     共用同一个字面量会让「改一格」意外波及其它格（TS 那份是常量复用，
     这里更保守，产物逐字节等价）。 */
  function fontTitle() { return { name: 'Calibri', size: 14, bold: true, color: { argb: C.titleText } }; }
  function fontSubtitle() { return { name: 'Calibri', size: 9, color: { argb: C.subtitleText } }; }
  function fontHeader() { return { name: 'Calibri', size: 11, bold: true, color: { argb: C.headerText } }; }
  function fontCell() { return { name: 'Calibri', size: 10 }; }
  function fontTotal() { return { name: 'Calibri', size: 11, bold: true, color: { argb: C.totalText } }; }
  function fontZero() { return { name: 'Calibri', size: 10, color: { argb: C.zeroText } }; }
  function fontPos() { return { name: 'Calibri', size: 10, bold: true, color: { argb: C.posText } }; }
  function fontNeg() { return { name: 'Calibri', size: 10, bold: true, color: { argb: C.negText } }; }

  function alignHeader() { return { horizontal: 'center', vertical: 'middle', wrapText: true }; }
  function alignCell() { return { vertical: 'middle', wrapText: false }; }
  function alignNum() { return { horizontal: 'right', vertical: 'middle' }; }
  function alignLeft() { return { horizontal: 'left', vertical: 'middle' }; }

  var NUM_FMT_INT = '#,##0';

  function fill(argb) {
    return { type: 'pattern', pattern: 'solid', fgColor: { argb: argb } };
  }
  function fillHeader() { return fill(C.headerFill); }
  function fillAccent() { return fill(C.accentFill); }
  function fillTotal() { return fill(C.totalFill); }
  function fillZebra() { return fill(C.zebraFill); }
  function fillWhite() { return fill(C.whiteFill); }

  function thin() { return { style: 'thin', color: { argb: C.thinBorder } }; }
  function medium() { return { style: 'medium', color: { argb: C.mediumBorder } }; }
  function borderHeader() { return { left: thin(), right: thin(), top: thin(), bottom: medium() }; }
  function borderCell() { return { left: thin(), right: thin(), top: thin(), bottom: thin() }; }
  function borderTotal() { return { left: thin(), right: thin(), top: medium(), bottom: medium() }; }

  /** 与 Python 端 SHEET_COLORS 一致 */
  var SHEET_TAB_COLORS = {
    Summary: 'FF2F5496',
    Inbound: 'FF548235',
    Outbound: 'FFBF8F00',
    Inventory: 'FF843C0C'
  };

  // ===========================================================================
  // 内部工具
  // ===========================================================================
  function normalizeHeader(header) {
    if (!header || !header.length) return [[]];
    if (typeof header[0] === 'string') {
      return [header.map(function (text) { return { text: String(text) }; })];
    }
    return header.map(function (row) {
      return row.map(function (h) {
        return { text: h.text, colSpan: h.colSpan, rowSpan: h.rowSpan, fill: h.fill };
      });
    });
  }

  function headerWidth(rows) {
    return rows.reduce(function (m, row) {
      return Math.max(m, row.reduce(function (s, h) { return s + (h.colSpan || 1); }, 0));
    }, 0);
  }

  function argb(color) {
    if (!color) return undefined;
    var c = String(color).replace('#', '').toUpperCase();
    return c.length === 6 ? 'FF' + c : c;
  }

  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  function localTimestamp() {
    var d = new Date();
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) +
      ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  }

  function isNumeric(v) {
    return typeof v === 'number' && isFinite(v);
  }

  /** 触发浏览器下载 */
  function downloadBlob(data, filename) {
    var blob = new Blob([data], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    root.setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }

  /** 文件名净化（去掉 Windows/Excel 非法字符） */
  function safeFileName(name) {
    return String(name || 'report').replace(/[\\/:*?"<>|\r\n\t]/g, '_').slice(0, 120);
  }

  // ===========================================================================
  // ExcelJS 按需加载
  // ===========================================================================
  var exceljsPromise = null;

  function loadExcelJS() {
    if (root.ExcelJS) return Promise.resolve(root.ExcelJS);
    if (exceljsPromise) return exceljsPromise;
    exceljsPromise = new Promise(function (resolve, reject) {
      if (typeof document === 'undefined') {
        reject(new Error('ExcelJS unavailable (non-browser environment and not pre-injected)'));
        return;
      }
      var s = document.createElement('script');
      s.src = EXCELJS_SRC;
      s.async = true;
      s.onload = function () {
        if (root.ExcelJS) resolve(root.ExcelJS);
        else { exceljsPromise = null; reject(new Error('ExcelJS not attached to window: ' + EXCELJS_SRC)); }
      };
      s.onerror = function () {
        exceljsPromise = null;                     // 允许下次重试
        reject(new Error('ExcelJS failed to load: ' + EXCELJS_SRC));
      };
      document.head.appendChild(s);
    });
    return exceljsPromise;
  }

  // ===========================================================================
  // 核心：构建单个 sheet
  // ===========================================================================
  function buildSheet(wb, spec) {
    var ws = wb.addWorksheet(String(spec.name).slice(0, 31), {
      views: [],
      pageSetup: {
        orientation: 'landscape',
        fitToPage: true,
        fitToWidth: 1,
        fitToHeight: 0,
        margins: { left: 0.4, right: 0.4, top: 0.5, bottom: 0.5, header: 0.3, footer: 0.3 }
      }
    });

    var tab = argb(spec.tabColor) || SHEET_TAB_COLORS[spec.name];
    if (tab) ws.properties.tabColor = { argb: tab };

    var hasTitle = !!spec.title;
    var headerRows = normalizeHeader(spec.header);
    var ncol = Math.max(
      headerWidth(headerRows),
      (spec.rows || []).reduce(function (m, r) { return Math.max(m, r.length); }, 0),
      spec.totalRow ? spec.totalRow.length : 0,
      1
    );

    // ---- 标题 / 副标题 ----
    if (hasTitle) {
      ws.mergeCells(1, 1, 1, ncol);
      var t = ws.getCell(1, 1);
      t.value = spec.title;
      t.font = fontTitle();
      t.alignment = alignLeft();

      ws.mergeCells(2, 1, 2, ncol);
      var st = ws.getCell(2, 1);
      st.value = spec.subtitle || ('Generated: ' + localTimestamp() + '    |    Sheet: ' + spec.name);
      st.font = fontSubtitle();
      st.alignment = alignLeft();
    }

    // ---- 表头 ----
    var headerStart = hasTitle ? 3 : 1;
    var headerEnd = headerStart + headerRows.length - 1;
    // 已被上方 rowSpan 占用的格子（避免下一行表头写串列 —— ExcelJS 的 getCell 对
    // 已合并的覆盖格会返回主格，直接顺序写会把整行左移）
    var occupied = headerRows.map(function () { return new Array(ncol + 2).fill(false); });
    for (var ri = 0; ri < headerRows.length; ri++) {
      var col = 1;
      for (var hi = 0; hi < headerRows[ri].length; hi++) {
        var h = headerRows[ri][hi];
        while (col <= ncol && occupied[ri][col]) col++;
        var colSpan = h.colSpan || 1;
        var rowSpan = h.rowSpan || 1;
        var r1 = headerStart + ri;
        var r2 = r1 + rowSpan - 1;
        var c1 = col;
        var c2 = col + colSpan - 1;
        if (rowSpan > 1 || colSpan > 1) ws.mergeCells(r1, c1, r2, c2);
        var cell = ws.getCell(r1, c1);
        cell.value = h.text;
        cell.font = fontHeader();
        cell.fill = h.fill === 'none' ? fillWhite() : (h.fill === 'accent' ? fillAccent() : fillHeader());
        cell.alignment = alignHeader();
        cell.border = borderHeader();
        for (var rr = ri; rr < ri + rowSpan && rr < headerRows.length; rr++) {
          for (var cc = c1; cc <= c2; cc++) occupied[rr][cc] = true;
        }
        col += colSpan;
      }
    }

    var numericCols = {};
    (spec.numericCols || []).forEach(function (i) { numericCols[i] = true; });
    var vc = spec.valueColors;
    var vcAll = vc === true;
    var vcSet = null;
    if (Object.prototype.toString.call(vc) === '[object Array]') {
      vcSet = {};
      vc.forEach(function (i) { vcSet[i] = true; });
    }
    function colorOn(colIdx) { return vcAll || (vcSet ? !!vcSet[colIdx] : false); }

    function styleCell(cell, value, rowIdx, colIdx, zebra, opts) {
      cell.value = (value === undefined ? null : value);
      if (opts.total) {
        cell.font = fontTotal();
        cell.fill = fillTotal();
        cell.border = borderTotal();
      } else {
        cell.fill = zebra ? fillZebra() : fillWhite();
        cell.border = borderCell();
        if (opts.valueColors && isNumeric(value)) {
          cell.font = value === 0 ? fontZero() : (value > 0 ? fontPos() : fontNeg());
        } else {
          cell.font = fontCell();
        }
      }
      if (isNumeric(value)) {
        cell.alignment = alignNum();
        cell.numFmt = NUM_FMT_INT;
      } else if (numericCols[colIdx]) {
        cell.alignment = alignNum();
      } else {
        cell.alignment = alignCell();
      }
    }

    var r = headerEnd + 1;
    // ---- 合计行 ----
    if (spec.totalRow) {
      for (var tc = 0; tc < ncol; tc++) {
        styleCell(ws.getCell(r, tc + 1), spec.totalRow[tc], r, tc, r % 2 === 0, { total: true });
      }
      r += 1;
    }
    // ---- 数据行 ----
    var rows = spec.rows || [];
    for (var di = 0; di < rows.length; di++) {
      for (var dc = 0; dc < ncol; dc++) {
        styleCell(ws.getCell(r, dc + 1), rows[di][dc], r, dc, r % 2 === 0, { valueColors: colorOn(dc) });
      }
      r += 1;
    }
    var lastRow = r - 1;

    // ---- 列宽 ----
    var autoWidth = spec.autoWidth !== false;
    for (var wc = 1; wc <= ncol; wc++) {
      var column = ws.getColumn(wc);
      if (spec.columnWidths && spec.columnWidths[wc - 1] != null) {
        column.width = spec.columnWidths[wc - 1];
        continue;
      }
      if (!autoWidth) continue;
      // 与 Python _auto_width 同口径：min(max(最长内容 + 2, 10), 42)，最多扫前 200 行
      var maxLen = 0;
      if (hasTitle && wc === 1) {
        maxLen = Math.max(
          String(spec.title || '').length,
          String(spec.subtitle || ('Generated: ' + localTimestamp() + '    |    Sheet: ' + spec.name)).length
        );
      }
      var scanTo = Math.min(lastRow, headerEnd + 200);
      for (var sr = headerStart; sr <= scanTo; sr++) {
        var v = ws.getCell(sr, wc).value;
        if (v !== null && v !== undefined) maxLen = Math.max(maxLen, String(v).length);
      }
      column.width = Math.min(Math.max(maxLen + 2, 10), 42);
    }

    // ---- 冻结 / 筛选 ----
    if (spec.freeze !== false) {
      ws.views = [{ state: 'frozen', ySplit: headerEnd, xSplit: 0 }];
    }
    if (spec.autoFilter !== false && lastRow >= headerEnd) {
      ws.autoFilter = {
        from: { row: headerEnd, column: 1 },
        to: { row: lastRow, column: ncol }
      };
    }
    return ws;
  }

  // ===========================================================================
  // 对外 API
  // ===========================================================================
  /** 构建工作簿（不下载），便于单测 / 二次加工。需先 loadExcelJS()。 */
  function buildReportWorkbook(specs) {
    var ExcelJS = root.ExcelJS;
    if (!ExcelJS) throw new Error('ExcelJS not loaded yet; await MsExcelReport.loadExcelJS() first');
    var wb = new ExcelJS.Workbook();
    wb.creator = 'NOC Dashboard';
    wb.created = new Date();
    specs.forEach(function (s) { buildSheet(wb, s); });
    return wb;
  }

  /** 生成并下载多 sheet 报表（项目统一格式） */
  function exportReport(specs, filename) {
    return loadExcelJS().then(function () {
      var wb = buildReportWorkbook(specs);
      return wb.xlsx.writeBuffer();
    }).then(function (buf) {
      var name = safeFileName(filename);
      if (!/\.xlsx$/i.test(name)) name += '.xlsx';
      downloadBlob(buf, name);
    });
  }

  /**
   * 单 sheet 快捷入口 —— 直接替换裸 CSV 拼接 / `XLSX.utils.aoa_to_sheet`。
   * 入参形态与 my_app 的 exportAoaReport 保持一致。
   */
  function exportAoaReport(opts) {
    return exportReport([{
      name: opts.sheetName || 'Sheet1',
      title: opts.title,
      subtitle: opts.subtitle,
      header: opts.header,
      rows: opts.rows,
      numericCols: opts.numericCols,
      columnWidths: opts.columnWidths,
      tabColor: opts.tabColor
    }], opts.filename);
  }

  return {
    UNIFIED_EXCEL_VERSION: UNIFIED_EXCEL_VERSION,
    SHEET_TAB_COLORS: SHEET_TAB_COLORS,
    EXCELJS_SRC: EXCELJS_SRC,
    loadExcelJS: loadExcelJS,
    buildReportWorkbook: buildReportWorkbook,
    exportReport: exportReport,
    exportAoaReport: exportAoaReport,
    downloadBlob: downloadBlob,
    safeFileName: safeFileName
  };
}));

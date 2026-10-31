// ============================================================================
// v1/olbrportal 手写静态壳的外部全局声明
// ----------------------------------------------------------------------------
// olbr.js 是 IIFE 全局脚本，运行时由 /MsPortal/assets/ 下的几个脚本往 window
// 上注入对象/函数。tsc 的 DOM lib 不认识这些业务全局，会在 checkJs 时报
// `Property 'X' does not exist on type 'Window'`。这里集中声明，让守卫只抓
// 真正的 bug（语法错、引用未声明的本地变量），不被「外部注入的全局」噪声淹没。
//
// 每条都标注来源脚本，改对应脚本时回来核对签名是否还匹配。
// ============================================================================

// olbr.js 多处给 `new Error(...)` 挂自定义 `.code`（'locked'/'bad'/'net'/'duplicate'
// 等）做错误分流。标准 Error 没有这个属性，这里扩展它，避免 3 处 @ts-expect-error。
interface Error {
  code?: string;
}

/** /MsPortal/assets/data.js 注入：51 个看板 / 9 分组 / QC 定义 / 升级机制 */
declare interface Window {
  MS_PORTAL_DATA: any;
  /** /MsPortal/assets/access.js 注入：权限判定 + 跨门户看板 id 映射 */
  MSPortalAccess: {
    canSee: (view: string, item?: any) => boolean;
    dashboardAccessId?: (it: any) => string;
  } | undefined;
  /** /MsPortal/assets/terms.js 注入：中英文词条映射查表 */
  msPortalTerm: ((kind: string, zh: string) => string) | undefined;
  /** /MsPortal/assets/terms.js 注入：英文字段含汉字时回查映射表（en, kind, zh 三参） */
  msPortalEnOf: ((en: string, kind: string, zh: string) => string) | undefined;
  /** /MsPortal/assets/qcDrill.drag.js 注入：下钻弹窗的拖动与定位 */
  QcDrill: { position: (anchor: Element | null) => void } | undefined;
  /** /MsPortal/assets/excelReport.js 注入：导出 Excel（UNIFIED_EXCEL_V1 格式） */
  MsExcelReport: any;
  /**
   * 本页自己的纯数据母本，由 assets/olbr-data.js（在本页 olbr.js 之前加载）注入。
   * 2026-09-25 从 olbr.js 拆分出来的 i18n 字典 / 图标 / layout / QC 阈值 / KPI 规格。
   * 主文件只读不写：改这些常量请改 olbr-data.js，不要在这里补写。
   */
  OLBR_DATA: any;

  /* ==================================================== 团队门户专用全局 ==
     下面三个全局只在 /v3/{fo,bo,flm,smc,cxo}_portal/ 这一套页面里存在
     （v3/olbrportal/ 上游那页不引这三个脚本，故 window 上没有它们）。
     声明放在本文件是因为 team_portal 与 olbrportal 共用同一份 globals 形状，
     上游那页的 tsc 检查同样会因为「不声明」而报噪声错误 —— 故此处只声明，
     不给上游那页引入任何运行时代码。 */
  /** assets/team-matrix.js 注入：可见性矩阵（生成文件，勿手改） */
  OLBR_TEAM_MATRIX: {
    [domain: string]: { [sub: string]: string[] };
  };
  /**
   * assets/team-scope-map.js 注入：作用域映射（生成文件，勿手改）。
   * 与 OLBR_TEAM_MATRIX 同源（都来自 v3/team_portal/scope-map.json）：
   * 一个说「勾了哪些」，一个说「子键怎么对应到门户组件」。
   * urlPatterns 只在 OSS 域出现（槽位 → 门户目录条目的匹配依据）。
   */
  OLBR_SCOPE_MAP: {
    [domain: string]: { [sub: string]: { urlPatterns?: string[] } };
  } | null;
  /** assets/team-scope.js 注入：作用域查询引擎 */
  OLBR_SCOPE: {
    teamId: string;
    team: { id: string; zh: string; en: string } | null;
    isTeamPortal: boolean;
    matrix: { [domain: string]: { [sub: string]: string[] } };
    ok: (domain: string, sub?: string) => boolean;
    subs: (domain: string) => string[];
    ossSlotOf: (item: any) => string;
    ossSlots: () => string[];
    viewGroups: () => string[];
    mapPages: () => string[];
    qaTabs: () => string[];
    reportIds: () => string[];
    hasComplaint: () => boolean;
    hasEscalation: () => boolean;
    hasFeedback: () => boolean;
  } | null;
  /** assets/team-panels.js 注入：团队门户专属面板（Auto Report 表 + 投诉入口） */
  OLBR_TEAM_REPORTS: {
    render: (el: Element | null) => void;
    renderComplaint: (el: Element | null) => void;
    loadReports: (force?: boolean) => void;
  } | null;
}

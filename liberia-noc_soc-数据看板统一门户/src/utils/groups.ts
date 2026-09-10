// ============================================================================
// 看板「分组」纯函数工具
// ----------------------------------------------------------------------------
// 设计要点：
//  1) 分组名称是**一等公民**：组列表（groups: string[]）独立持久化，空分组也能存在
//     （此前分组是从卡片 category 去重推导，无法新增空分组）。
//  2) 卡片与分组的关联**只存分组名**（DashboardItem.category === 组名）。
//     因此「重命名分组」只需一处批量改写：把 category === 旧组名 的卡片改成新组名，
//     关联关系天然保持，无需逐张卡片重设，也不会遗留旧组名。
//  3) 删除分组时，该组卡片统一迁移到兜底分组（默认「其他」），绝不产生孤儿卡片
//     （category 指向一个不存在的分组会导致该卡片在任何 Tab / 矩阵分组里都看不到）。
//
// 本模块不依赖 React / DOM，便于直接用 node 断言验证。
// ============================================================================

/** 「全部」是伪分组（过滤入口），不是真实分组，永远不进入 groups 列表 */
export const GROUP_ALL = '全部';
/** 删除分组时卡片优先迁移到的兜底分组 */
export const FALLBACK_GROUP = '其他';
/** 分组名称最大长度（与 i18n 提示保持一致） */
export const MAX_GROUP_NAME_LENGTH = 30;

export type GroupErrorCode =
  | 'empty' // 名称为空
  | 'too_long' // 超过最大长度
  | 'duplicate' // 已存在同名分组
  | 'reserved' // 使用了内置保留名（「全部」是过滤入口，不是真实分组）
  | 'not_found' // 目标分组不存在
  | 'last_group'; // 只剩最后一个分组，不允许删除

export interface GroupOpResult<T> {
  ok: boolean;
  error?: GroupErrorCode;
  /** 操作后的分组列表（失败时原样返回） */
  groups: string[];
  /** 操作后的卡片列表（失败时原样返回） */
  dashboards: T[];
  /** 本次因分组变更而被自动同步改写的卡片数量 */
  moved: number;
  /** 删除分组时实际使用的兜底分组名 */
  fallback?: string;
}

/** 归一化分组名：折叠连续空白并去首尾空格 */
export function normalizeGroupName(raw: unknown): string {
  return String(raw ?? '')
    .replace(/\s+/g, ' ')
    .trim();
}

/** 查找同名分组（忽略大小写）；ignore 用于「重命名自身」时跳过原名 */
function findDuplicate(groups: string[], name: string, ignore?: string): string | undefined {
  const lower = name.toLowerCase();
  return groups.find((g) => g !== ignore && g.toLowerCase() === lower);
}

/** 过滤服务端/导入文件里的分组数组：去空、去伪分组、忽略大小写去重、保序 */
export function sanitizeGroups(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const item of raw) {
    if (typeof item !== 'string') continue;
    const name = normalizeGroupName(item);
    if (!name || name === GROUP_ALL) continue;
    if (findDuplicate(out, name)) continue;
    out.push(name);
  }
  return out;
}

/**
 * 推导完整分组列表：以 seeds（当前分组）为基准保序，再把卡片中出现过、
 * 但不在列表里的 category 追加进去。
 * 用于：服务端旧格式（纯数组）加载、导入历史 JSON、手工改过数据的兜底。
 */
export function deriveGroups(dashboards: { category?: string }[], seeds: string[] = []): string[] {
  const result = sanitizeGroups(seeds);
  for (const item of dashboards) {
    const name = normalizeGroupName(item?.category);
    if (!name || name === GROUP_ALL) continue;
    if (findDuplicate(result, name)) continue;
    result.push(name);
  }
  return result;
}

// ============================================================================
// 分组名的多语言标签
// ----------------------------------------------------------------------------
// 分组名本身是**规范值（中文）**，卡片只存这个规范值；界面按当前语言取值：
//   zh → 规范值本身；en → 先查运行时标签表 groupLabels，再查内置 i18n 字典，最后原样。
// 这样「改名」只需要改一处规范值 + 一处标签，中英文界面同时生效，
// 也不会出现「英文界面里显示中文分组名」或「编辑英文界面把英文写回源数据」。
// ============================================================================

/** 分组标签表：key = 分组规范名，value = 英文显示名 */
export type GroupLabels = Record<string, string>;

/** 过滤标签表：丢掉非字符串/空值，以及已不存在的分组（防止删组/改名后残留脏键） */
export function sanitizeGroupLabels(raw: unknown, groups: string[]): GroupLabels {
  const out: GroupLabels = {};
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return out;
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    const name = normalizeGroupName(key);
    if (!groups.includes(name)) continue;
    if (typeof value !== 'string') continue;
    const label = normalizeGroupName(value);
    if (!label) continue;
    out[name] = label;
  }
  return out;
}

/** 写入/清除某个分组的英文标签（传空即清除，界面回落到内置字典/原样） */
export function setGroupLabel(labels: GroupLabels, name: string, label: string): GroupLabels {
  const next: GroupLabels = { ...labels };
  const key = normalizeGroupName(name);
  const value = normalizeGroupName(label);
  if (!key) return next;
  if (value) next[key] = value;
  else delete next[key];
  return next;
}

/** 重命名分组时同步搬移标签（旧键删除，新键写入；没填就回落内置字典） */
export function renameGroupLabel(
  labels: GroupLabels,
  oldName: string,
  newName: string,
  label: string
): GroupLabels {
  const next = setGroupLabel(labels, oldName, '');
  return setGroupLabel(next, newName, label);
}

/** 删除分组时清掉它的标签 */
export function dropGroupLabel(labels: GroupLabels, name: string): GroupLabels {
  const next: GroupLabels = { ...labels };
  delete next[normalizeGroupName(name)];
  return next;
}

/** 取某语言的显示名：en 先看标签表，再看内置字典（由调用方注入 translator），最后原样 */
export function groupDisplayName(
  name: string,
  lang: 'zh' | 'en',
  labels: GroupLabels,
  fallbackTranslator?: (name: string) => string
): string {
  if (lang !== 'en') return name;
  const custom = labels[name];
  if (custom) return custom;
  return fallbackTranslator ? fallbackTranslator(name) : name;
}

/** 统计每个分组下的卡片数量（键为归一化后的组名） */
export function countByGroup(dashboards: { category?: string }[]): Record<string, number> {
  const map: Record<string, number> = {};
  for (const item of dashboards) {
    const name = normalizeGroupName(item?.category);
    if (!name) continue;
    map[name] = (map[name] ?? 0) + 1;
  }
  return map;
}

// ============================================================================
// 分组排序
// ----------------------------------------------------------------------------
// 分组顺序就是 groups 数组的顺序（FilterBar 的 Tab、矩阵视图的分组块、
// 卡片编辑弹窗的下拉框都按这个顺序渲染）。排序只动数组顺序，不动任何卡片：
// 卡片只存 category，所以「换位置」不影响任何关联关系。
// ============================================================================

export interface GroupReorderResult {
  ok: boolean;
  error?: GroupErrorCode;
  /** 排序后的分组列表（失败或无需移动时原样返回） */
  groups: string[];
  /** 实际生效的起始下标；失败为 -1 */
  from: number;
  /** 实际生效的目标下标；失败为 -1 */
  to: number;
}

/**
 * 把第 from 个分组移动到第 to 个位置，其余分组相对顺序不变。
 * 下标会被夹紧到有效区间；from === to 视为无变化（仍返回 ok，便于 UI 直接落地）。
 */
export function reorderGroups(groups: string[], from: number, to: number): GroupReorderResult {
  const list = [...groups];
  const n = list.length;
  if (n === 0 || !Number.isFinite(from) || !Number.isFinite(to)) {
    return { ok: false, error: 'not_found', groups: list, from: -1, to: -1 };
  }
  const src = Math.max(0, Math.min(n - 1, Math.trunc(from)));
  const dst = Math.max(0, Math.min(n - 1, Math.trunc(to)));
  if (src === dst) return { ok: true, groups: list, from: src, to: dst };

  const [moved] = list.splice(src, 1);
  list.splice(dst, 0, moved);
  return { ok: true, groups: list, from: src, to: dst };
}

/**
 * 按组名把分组上移/下移 offset 位（负数=上移）。用于「上移 / 下移」按钮。
 * 已经在首/末位时返回 ok 且顺序不变（按钮本身会被置灰，这里是双保险）。
 */
export function moveGroup(groups: string[], rawName: string, offset: number): GroupReorderResult {
  const name = normalizeGroupName(rawName);
  const from = groups.indexOf(name);
  if (from < 0) return { ok: false, error: 'not_found', groups: [...groups], from: -1, to: -1 };
  return reorderGroups(groups, from, from + Math.trunc(offset));
}

/** 把某个分组直接挪到最前 / 最后（用于拖拽与快捷键） */
export function moveGroupToEdge(
  groups: string[],
  rawName: string,
  edge: 'first' | 'last'
): GroupReorderResult {
  const name = normalizeGroupName(rawName);
  const from = groups.indexOf(name);
  if (from < 0) return { ok: false, error: 'not_found', groups: [...groups], from: -1, to: -1 };
  return reorderGroups(groups, from, edge === 'first' ? 0 : groups.length - 1);
}

function validateName(name: string): GroupErrorCode | null {
  if (!name) return 'empty';
  if (name === GROUP_ALL) return 'reserved';
  if (name.length > MAX_GROUP_NAME_LENGTH) return 'too_long';
  return null;
}

function fail<T>(groups: string[], dashboards: T[], error: GroupErrorCode): GroupOpResult<T> {
  return { ok: false, error, groups: [...groups], dashboards, moved: 0 };
}

/** 新增分组（允许空分组：只登记组名，不改变任何卡片） */
export function addGroup<T>(
  groups: string[],
  rawName: string,
  dashboards: T[] = []
): GroupOpResult<T> {
  const name = normalizeGroupName(rawName);
  const invalid = validateName(name);
  if (invalid) return fail(groups, dashboards, invalid);
  if (findDuplicate(groups, name)) return fail(groups, dashboards, 'duplicate');
  return { ok: true, groups: [...groups, name], dashboards, moved: 0 };
}

/**
 * 重命名分组：同步把该分组下所有卡片的 category 改写为新组名。
 * 卡片与分组的关联（category === 组名）保持不变，不会出现「卡片留在不存在的老组里」。
 */
export function renameGroup<T extends { category?: string }>(
  groups: string[],
  dashboards: T[],
  rawOldName: string,
  rawNewName: string
): GroupOpResult<T> {
  const oldName = normalizeGroupName(rawOldName);
  const newName = normalizeGroupName(rawNewName);
  if (!groups.some((g) => g === oldName)) return fail(groups, dashboards, 'not_found');
  if (newName === oldName) return { ok: true, groups: [...groups], dashboards, moved: 0 };

  const invalid = validateName(newName);
  if (invalid) return fail(groups, dashboards, invalid);
  if (findDuplicate(groups, newName, oldName)) return fail(groups, dashboards, 'duplicate');

  let moved = 0;
  const nextDashboards = dashboards.map((item) => {
    if (normalizeGroupName(item?.category) !== oldName) return item;
    moved += 1;
    return { ...item, category: newName };
  });

  return {
    ok: true,
    groups: groups.map((g) => (g === oldName ? newName : g)),
    dashboards: nextDashboards,
    moved,
  };
}

/**
 * 删除分组：该分组下的卡片统一迁移到兜底分组（优先 preferredFallback，否则取剩余
 * 分组里的第一个），保证卡片不会挂在已删除的分组上而「消失」。
 * 至少保留一个分组，删最后一个会被拒绝。
 */
export function deleteGroup<T extends { category?: string }>(
  groups: string[],
  dashboards: T[],
  rawName: string,
  preferredFallback: string = FALLBACK_GROUP
): GroupOpResult<T> {
  const name = normalizeGroupName(rawName);
  if (!groups.some((g) => g === name)) return fail(groups, dashboards, 'not_found');
  if (groups.length <= 1) return fail(groups, dashboards, 'last_group');

  const remaining = groups.filter((g) => g !== name);
  const fallback = remaining.includes(preferredFallback) ? preferredFallback : remaining[0];

  let moved = 0;
  const nextDashboards = dashboards.map((item) => {
    if (normalizeGroupName(item?.category) !== name) return item;
    moved += 1;
    return { ...item, category: fallback };
  });

  return { ok: true, groups: remaining, dashboards: nextDashboards, moved, fallback };
}

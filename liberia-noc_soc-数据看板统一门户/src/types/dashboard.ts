export type PlatformType = 'finebi' | 'custom' | 'external';

/**
 * 分组（分类）名称。
 * 早期版本写死为字面量联合类型，分组无法新增/改名；现改为自由字符串：
 * 分组是可在「分组管理」里新增/重命名/删除的一等实体，具体有哪些分组由
 * 目录的 groups 字段（服务端 portal-default.json）决定，见 utils/groups.ts。
 */
export type CategoryType = string;

/** 「全部」伪分组：仅作为过滤入口，不属于真实分组，不进入 groups 列表 */
export const CATEGORY_ALL: CategoryType = '全部';

/**
 * 服务端 portal-default.json / 导出 JSON 的 v2 结构：
 *   { version: 2, savedAt, groups: string[], dashboards: DashboardItem[] }
 * 兼容旧版（纯 DashboardItem[] 数组），读取时自动推导 groups。
 */
export interface PortalCatalogFile {
  version?: number;
  savedAt?: string;
  exportedAt?: string;
  /** 分组名称列表（含尚无卡片的空分组），顺序即 Tab / 矩阵分组展示顺序 */
  groups?: string[];
  /** 分组名的多语言标签：key = 分组规范名（中文），value = 英文显示名。
   *  分组的「规范名」是唯一标识（卡片 category 存的就是它），英文名只是展示层标签。 */
  groupLabels?: Record<string, string>;
  dashboards: DashboardItem[];
}

export type UpdateFrequency = '实时流式' | '每小时' | '每日0点' | '周度更新' | '月度汇总';

export type DashboardStatus = 'online' | 'maintenance' | 'beta';

export interface DashboardItem {
  id: string;
  title: string;
  description: string;
  platform: PlatformType;
  url: string;
  /** 相对路径（含 path/query/hash，不含主机），如 /myapp/?page=alarm、/webroot/decision#/...。
   *  存在时由全局主机配置实时拼出完整 URL，远程 IP 变更只需改配置一处。外部大屏(external)不填。 */
  rel?: string;
  category: Exclude<CategoryType, '全部'>;
  tags: string[];
  iconName: string;
  updateFrequency: UpdateFrequency;
  department: string;
  owner: string;
  isFavorite: boolean;
  isPinned: boolean;
  clickCount: number;
  lastVisited?: string;
  themeColor: 'teal' | 'indigo' | 'emerald' | 'cyan' | 'purple' | 'amber' | 'rose' | 'blue' | 'green';
  status: DashboardStatus;
  customThumbnail?: string;
  /** 仅本机隐藏标记：来自各浏览器 localStorage 偏好，「保存为默认目录」时会被剥离，
   *  任何电脑都可以隐藏自己不想看的看板，互不影响，也不会进入服务端全局默认。 */
  hidden?: boolean;
}

export type ViewMode = 'grid' | 'list' | 'matrix' | 'tasks';

export type SortOption = 'pinned' | 'popular' | 'recent' | 'name' | 'platform';

export interface EnvironmentSetting {
  name: string;
  id: string;
  host: string;
  description: string;
  isCurrent: boolean;
}

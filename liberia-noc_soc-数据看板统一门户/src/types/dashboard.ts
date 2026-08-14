export type PlatformType = 'finebi' | 'custom' | 'external';

export type CategoryType = 
  | '全部'
  | 'MS 综合运维管理'
  | '告警与工单故障'
  | '网络性能与无线/核心网'
  | '传输承载与业务时延'
  | '现场动力与备件仓储'
  | '自动化调度与数据集成'
  | '其他';

export type UpdateFrequency = '实时流式' | '每小时' | '每日0点' | '周度更新' | '月度汇总';

export type DashboardStatus = 'online' | 'maintenance' | 'beta';

export interface DashboardItem {
  id: string;
  title: string;
  description: string;
  platform: PlatformType;
  url: string;
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
  themeColor: 'indigo' | 'emerald' | 'cyan' | 'purple' | 'amber' | 'rose' | 'blue';
  status: DashboardStatus;
  customThumbnail?: string;
}

export type ViewMode = 'grid' | 'list' | 'matrix';

export type SortOption = 'pinned' | 'popular' | 'recent' | 'name' | 'platform';

export interface EnvironmentSetting {
  name: string;
  id: string;
  host: string;
  description: string;
  isCurrent: boolean;
}

import React from 'react';
import {
  Activity,
  AlertTriangle,
  Antenna,
  BarChart3,
  BatteryCharging,
  BookOpen,
  Bot,
  Box,
  Boxes,
  CalendarClock,
  Clock,
  Coins,
  Compass,
  Cpu,
  Crown,
  Database,
  Factory,
  FileSearch,
  FileSpreadsheet,
  FileText,
  Gauge,
  Globe,
  HelpCircle,
  History,
  LayoutGrid,
  ListChecks,
  LogIn,
  MessageCircle,
  Network,
  Package,
  Palette,
  PieChart,
  RadioTower,
  Settings,
  Settings2,
  ShieldCheck,
  Signal,
  Terminal,
  TrendingUp,
  Trophy,
  Truck,
  UploadCloud,
  UserCheck,
  UserRound,
  Users,
  Zap,
} from 'lucide-react';

interface DynamicIconProps {
  name: string;
  className?: string;
  size?: number;
}

type IconComponent = React.ComponentType<{ className?: string; size?: number }>;

// 显式图标表（2026-11-12 性能轮）：此前 `import * as Icons from 'lucide-react'`
// 会把 lucide 全量 1500+ 图标打进首屏 chunk（约 850KB），tree-shaking 对命名空间
// 导入无效。这里只列实际用到的图标：看板图标选择器 AVAILABLE_ICONS、内置目录
// iconName、文档索引 entry.icon 三处之并集；未收录的名字（如服务端旧数据里的
// 生僻图标名）回退到 LayoutGrid，与之前 `|| Icons.LayoutGrid` 的行为一致。
// 新增图标时：先在 AVAILABLE_ICONS / 内置目录里加名字，再同步补进这张表。
const ICON_MAP: Record<string, IconComponent> = {
  Activity,
  AlertTriangle,
  Antenna,
  BarChart3,
  BatteryCharging,
  BookOpen,
  Bot,
  Box,
  Boxes,
  CalendarClock,
  Clock,
  Coins,
  Compass,
  Cpu,
  Crown,
  Database,
  Factory,
  FileSearch,
  FileSpreadsheet,
  FileText,
  Gauge,
  Globe,
  HelpCircle,
  History,
  LayoutGrid,
  ListChecks,
  LogIn,
  MessageCircle,
  Network,
  Package,
  Palette,
  PieChart,
  RadioTower,
  Settings,
  Settings2,
  ShieldCheck,
  Signal,
  Terminal,
  TrendingUp,
  Trophy,
  Truck,
  UploadCloud,
  UserCheck,
  UserRound,
  Users,
  Zap,
};

export const DynamicIcon: React.FC<DynamicIconProps> = ({ name, className = 'w-5 h-5', size }) => {
  const IconComponent = ICON_MAP[name] || LayoutGrid;
  return <IconComponent className={className} size={size} />;
};

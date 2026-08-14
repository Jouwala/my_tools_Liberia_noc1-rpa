import React, { useState, useEffect } from 'react';
import {
  X,
  Plus,
  Save,
  Link2,
  Tag,
  Building,
  User,
  Clock,
  Palette,
  Sparkles,
  Layers,
  Star,
  Pin,
} from 'lucide-react';
import {
  DashboardItem,
  PlatformType,
  CategoryType,
  UpdateFrequency,
} from '../types/dashboard';
import { CATEGORIES, AVAILABLE_ICONS } from '../data/initialDashboards';
import { DynamicIcon } from './DynamicIcon';

interface DashboardModalProps {
  isOpen: boolean;
  onClose: () => void;
  dashboardToEdit: DashboardItem | null;
  onSave: (dashboard: DashboardItem) => void;
}

export const DashboardModal: React.FC<DashboardModalProps> = ({
  isOpen,
  onClose,
  dashboardToEdit,
  onSave,
}) => {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [platform, setPlatform] = useState<PlatformType>('finebi');
  const [url, setUrl] = useState('');
  const [category, setCategory] = useState<Exclude<CategoryType, '全部'>>('MS 综合运维管理');
  const [tagInput, setTagInput] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [iconName, setIconName] = useState('LayoutGrid');
  const [updateFrequency, setUpdateFrequency] = useState<UpdateFrequency>('每日0点');
  const [department, setDepartment] = useState('');
  const [owner, setOwner] = useState('');
  const [isFavorite, setIsFavorite] = useState(false);
  const [isPinned, setIsPinned] = useState(false);
  const [themeColor, setThemeColor] = useState<DashboardItem['themeColor']>('indigo');

  useEffect(() => {
    if (dashboardToEdit) {
      setTitle(dashboardToEdit.title);
      setDescription(dashboardToEdit.description);
      setPlatform(dashboardToEdit.platform);
      setUrl(dashboardToEdit.url);
      setCategory(dashboardToEdit.category);
      setTags(dashboardToEdit.tags);
      setIconName(dashboardToEdit.iconName);
      setUpdateFrequency(dashboardToEdit.updateFrequency);
      setDepartment(dashboardToEdit.department);
      setOwner(dashboardToEdit.owner);
      setIsFavorite(dashboardToEdit.isFavorite);
      setIsPinned(dashboardToEdit.isPinned);
      setThemeColor(dashboardToEdit.themeColor);
    } else {
      // Defaults for new dashboard
      setTitle('');
      setDescription('');
      setPlatform('finebi');
      setUrl('http://192.168.100.19/webroot/decision#/directory?activeTab=dec-tabs-homepage');
      setCategory('MS 综合运维管理');
      setTags(['报表', '运维']);
      setIconName('LayoutGrid');
      setUpdateFrequency('每日0点');
      setDepartment('MS 运营管理部');
      setOwner('系统管理员');
      setIsFavorite(false);
      setIsPinned(false);
      setThemeColor('indigo');
    }
  }, [dashboardToEdit, isOpen]);

  if (!isOpen) return null;

  const handleAddTag = () => {
    if (tagInput.trim() && !tags.includes(tagInput.trim())) {
      setTags([...tags, tagInput.trim()]);
      setTagInput('');
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    setTags(tags.filter((t) => t !== tagToRemove));
  };

  const handleQuickUrlFill = (type: 'finebi' | 'custom') => {
    if (type === 'finebi') {
      setPlatform('finebi');
      setThemeColor('indigo');
      setUrl('http://192.168.100.19/webroot/decision#/directory?activeTab=dec-tabs-homepage');
      if (!title) setTitle('Liberia Data Portal (FineBI)');
    } else {
      setPlatform('custom');
      setThemeColor('cyan');
      setUrl('http://192.168.100.19/myapp/');
      if (!title) setTitle('Data Insight MVP 自研看板');
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !url.trim()) return;

    const newItem: DashboardItem = {
      id: dashboardToEdit ? dashboardToEdit.id : `board-${Date.now()}`,
      title: title.trim(),
      description: description.trim() || '企业级数据指标与决策分析看板',
      platform,
      url: url.trim(),
      category,
      tags: tags.length > 0 ? tags : ['看板'],
      iconName,
      updateFrequency,
      department: department.trim() || '信息技术中心',
      owner: owner.trim() || '管理员',
      isFavorite,
      isPinned,
      clickCount: dashboardToEdit ? dashboardToEdit.clickCount : 0,
      lastVisited: dashboardToEdit?.lastVisited,
      themeColor,
      status: dashboardToEdit ? dashboardToEdit.status : 'online',
    };

    onSave(newItem);
    onClose();
  };

  const colorOptions: Array<{ id: DashboardItem['themeColor']; label: string; bg: string }> = [
    { id: 'indigo', label: '深邃蓝紫 (FineBI推荐)', bg: 'bg-indigo-500' },
    { id: 'cyan', label: '敏捷青蓝 (自研推荐)', bg: 'bg-cyan-500' },
    { id: 'emerald', label: '生机翠绿 (增长/供应链)', bg: 'bg-emerald-500' },
    { id: 'purple', label: '极光高贵紫 (高管/HR)', bg: 'bg-purple-500' },
    { id: 'amber', label: '工业暖橙 (制造/IoT)', bg: 'bg-amber-500' },
    { id: 'rose', label: '财务玫瑰红 (资金/成本)', bg: 'bg-rose-500' },
    { id: 'blue', label: '经典企业蓝', bg: 'bg-blue-500' },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl max-w-2xl w-full max-h-[92vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400">
              {dashboardToEdit ? <Save className="w-5 h-5" /> : <Plus className="w-5 h-5" />}
            </div>
            <div>
              <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-base">
                {dashboardToEdit ? '编辑看板配置' : '添加新看板链接'}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                配置 FineBI 报表或自研系统看板的访问入口
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Scrollable Form */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* Quick presets */}
          {!dashboardToEdit && (
            <div className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200/80 dark:border-slate-700/80 flex items-center justify-between">
              <span className="text-xs text-slate-600 dark:text-slate-400 font-medium flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-indigo-500" /> 快速填入局域网模板：
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => handleQuickUrlFill('finebi')}
                  className="px-2.5 py-1 text-xs font-medium rounded-lg bg-indigo-100 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-200 transition-colors"
                >
                  填入 FineBI 平台
                </button>
                <button
                  type="button"
                  onClick={() => handleQuickUrlFill('custom')}
                  className="px-2.5 py-1 text-xs font-medium rounded-lg bg-cyan-100 dark:bg-cyan-950 text-cyan-700 dark:text-cyan-300 hover:bg-cyan-200 transition-colors"
                >
                  填入 自研 MyApp
                </button>
              </div>
            </div>
          )}

          {/* Platform & Category */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
                所属系统平台 *
              </label>
              <div className="grid grid-cols-3 gap-2">
                {(['finebi', 'custom', 'external'] as PlatformType[]).map((p) => (
                  <button
                    type="button"
                    key={p}
                    onClick={() => {
                      setPlatform(p);
                      if (p === 'finebi') setThemeColor('indigo');
                      if (p === 'custom') setThemeColor('cyan');
                    }}
                    className={`py-2 px-2 text-xs font-medium rounded-xl border transition-all ${
                      platform === p
                        ? 'border-indigo-600 bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 ring-2 ring-indigo-500/20'
                        : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
                    }`}
                  >
                    {p === 'finebi' ? 'FineBI 平台' : p === 'custom' ? '自研系统' : '外部大屏'}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
                业务分类 *
              </label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value as any)}
                className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {CATEGORIES.filter((c) => c !== '全部').map((cat) => (
                  <option key={cat} value={cat}>
                    {cat}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Title */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
              看板名称 *
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例如：集团销售回款分析 / 智能制造车间数字孪生"
              className="w-full px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500"
              required
            />
          </div>

          {/* URL */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
              <Link2 className="w-3.5 h-3.5 text-slate-400" />
              跳转目标 URL *
            </label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="http://192.168.100.19/webroot/decision#..."
              className="w-full px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
              required
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
              功能简述
            </label>
            <textarea
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="简要说明此看板展示的业务指标及用途..."
              className="w-full px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
            />
          </div>

          {/* Department, Owner, UpdateFrequency */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1 flex items-center gap-1">
                <Building className="w-3.5 h-3.5" /> 业务部门
              </label>
              <input
                type="text"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                placeholder="如: 销售管理部"
                className="w-full px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1 flex items-center gap-1">
                <User className="w-3.5 h-3.5" /> 负责人
              </label>
              <input
                type="text"
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                placeholder="如: 张经理"
                className="w-full px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1 flex items-center gap-1">
                <Clock className="w-3.5 h-3.5" /> 数据更新周期
              </label>
              <select
                value={updateFrequency}
                onChange={(e) => setUpdateFrequency(e.target.value as UpdateFrequency)}
                className="w-full px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="实时流式">实时流式</option>
                <option value="每小时">每小时</option>
                <option value="每日0点">每日0点</option>
                <option value="周度更新">周度更新</option>
                <option value="月度汇总">月度汇总</option>
              </select>
            </div>
          </div>

          {/* Icon & Theme Color */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2 border-t border-slate-100 dark:border-slate-800">
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5" /> 图标样式
              </label>
              <div className="grid grid-cols-6 gap-1.5 max-h-28 overflow-y-auto p-1.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
                {AVAILABLE_ICONS.map((ico) => (
                  <button
                    type="button"
                    key={ico.name}
                    onClick={() => setIconName(ico.name)}
                    title={ico.label}
                    className={`p-2 rounded-lg flex items-center justify-center transition-colors ${
                      iconName === ico.name
                        ? 'bg-indigo-600 text-white shadow-sm'
                        : 'text-slate-600 dark:text-slate-400 hover:bg-slate-200/60 dark:hover:bg-slate-700'
                    }`}
                  >
                    <DynamicIcon name={ico.name} className="w-4 h-4" />
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                <Palette className="w-3.5 h-3.5" /> 卡片主题色调
              </label>
              <div className="space-y-1.5 max-h-28 overflow-y-auto">
                {colorOptions.map((opt) => (
                  <button
                    type="button"
                    key={opt.id}
                    onClick={() => setThemeColor(opt.id)}
                    className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-xs transition-all ${
                      themeColor === opt.id
                        ? 'bg-indigo-50 dark:bg-indigo-950/60 border border-indigo-300 dark:border-indigo-800 font-medium'
                        : 'hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400'
                    }`}
                  >
                    <span className={`w-3 h-3 rounded-full ${opt.bg} shrink-0`} />
                    <span className="truncate">{opt.label}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Tags */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
              <Tag className="w-3.5 h-3.5 text-slate-400" />
              标签管理 (支持回车添加)
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAddTag();
                  }
                }}
                placeholder="输入标签名按回车..."
                className="flex-1 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <button
                type="button"
                onClick={handleAddTag}
                className="px-3 py-1.5 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-xs font-medium rounded-lg text-slate-700 dark:text-slate-300"
              >
                添加
              </button>
            </div>
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {tags.map((t) => (
                  <span
                    key={t}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs"
                  >
                    #{t}
                    <button
                      type="button"
                      onClick={() => handleRemoveTag(t)}
                      className="hover:text-rose-500 ml-0.5"
                    >
                      &times;
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Options (Pin, Favorite) */}
          <div className="pt-2 flex items-center gap-6 border-t border-slate-100 dark:border-slate-800">
            <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={isPinned}
                onChange={(e) => setIsPinned(e.target.checked)}
                className="rounded text-indigo-600 focus:ring-indigo-500"
              />
              <span className="flex items-center gap-1 font-medium">
                <Pin className="w-3.5 h-3.5 text-amber-500" />
                置顶在门户最前列
              </span>
            </label>

            <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={isFavorite}
                onChange={(e) => setIsFavorite(e.target.checked)}
                className="rounded text-indigo-600 focus:ring-indigo-500"
              />
              <span className="flex items-center gap-1 font-medium">
                <Star className="w-3.5 h-3.5 text-amber-400 fill-amber-400" />
                加入我的星标常用
              </span>
            </label>
          </div>
        </form>

        {/* Footer */}
        <div className="px-6 py-3.5 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-100 dark:border-slate-800 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-xl transition-colors"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            className="px-5 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded-xl shadow-sm shadow-indigo-600/20 transition-all flex items-center gap-1.5"
          >
            <Save className="w-3.5 h-3.5" />
            保存配置
          </button>
        </div>
      </div>
    </div>
  );
};

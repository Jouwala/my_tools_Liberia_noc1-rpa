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
import { getFinebiHomeUrl, getMyappHomeUrl, buildRel } from '../config';
import { DynamicIcon } from './DynamicIcon';
import { useI18n, translateCategory, translateTag, translateDept, translateOwner, translateDashboard, reverseTranslateCategory, reverseTranslateTag, reverseTranslateDept, reverseTranslateOwner } from '../i18n';

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
  const { t, lang } = useI18n();
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
      // 编辑模式：显示翻译后的数据（用户看到的是当前语言的文本）
      const translated = translateDashboard(dashboardToEdit, lang, t);
      setTitle(translated.title);
      setDescription(translated.description);
      setPlatform(translated.platform);
      setUrl(translated.url);
      setCategory(translated.category);
      setTags(translated.tags);
      setIconName(translated.iconName);
      setUpdateFrequency(translated.updateFrequency);
      setDepartment(translated.department);
      setOwner(translated.owner);
      setIsFavorite(translated.isFavorite);
      setIsPinned(translated.isPinned);
      setThemeColor(translated.themeColor);
    } else {
      // Defaults for new dashboard
      setTitle('');
      setDescription('');
      setPlatform('finebi');
      setUrl(getFinebiHomeUrl());
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
  }, [dashboardToEdit, isOpen, lang, t]);

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
      setUrl(getFinebiHomeUrl());
      if (!title) setTitle('Liberia Data Portal (FineBI)');
    } else {
      setPlatform('custom');
      setThemeColor('teal');
      setUrl(getMyappHomeUrl());
      if (!title) setTitle('Data Insight MVP 自研看板');
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !url.trim()) return;

    // 保存时：将翻译后的值映射回原始中文值
    const originalCategory = reverseTranslateCategory(category, lang, t);
    const originalTags = tags.map((tag) => reverseTranslateTag(tag, lang, t));
    const originalDept = reverseTranslateDept(department, lang, t);
    const originalOwner = reverseTranslateOwner(owner, lang, t);

    console.log('[DashboardModal] Save:', { lang, department, originalDept, owner, originalOwner });

    const newItem: DashboardItem = {
      id: dashboardToEdit ? dashboardToEdit.id : `board-${Date.now()}`,
      title: title.trim(),
      description: description.trim() || '企业级数据指标与决策分析看板',
      platform,
      url: url.trim(),
      rel: buildRel(platform, url.trim()),
      category: originalCategory as DashboardItem['category'],
      tags: originalTags.length > 0 ? originalTags : ['看板'],
      iconName,
      updateFrequency,
      department: originalDept.trim() || '信息技术中心',
      owner: originalOwner.trim() || '管理员',
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
    { id: 'teal', label: t('color.teal'), bg: 'bg-teal-500' },
    { id: 'cyan', label: t('color.cyan'), bg: 'bg-cyan-500' },
    { id: 'indigo', label: t('color.indigo'), bg: 'bg-indigo-500' },
    { id: 'emerald', label: t('color.emerald'), bg: 'bg-emerald-500' },
    { id: 'purple', label: t('color.purple'), bg: 'bg-purple-500' },
    { id: 'amber', label: t('color.amber'), bg: 'bg-amber-500' },
    { id: 'rose', label: t('color.rose'), bg: 'bg-rose-500' },
    { id: 'blue', label: t('color.blue'), bg: 'bg-blue-500' },
    { id: 'green', label: t('color.green'), bg: 'bg-[#008B00]' },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl max-w-2xl w-full max-h-[92vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-300">
              {dashboardToEdit ? <Save className="w-5 h-5" /> : <Plus className="w-5 h-5" />}
            </div>
            <div>
              <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-base">
                {dashboardToEdit ? t('modal.editTitle') : t('modal.addTitle')}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('modal.subtitle')}
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
                <Sparkles className="w-3.5 h-3.5 text-teal-500" /> {t('modal.quickTip')}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => handleQuickUrlFill('finebi')}
                  className="px-2.5 py-1 text-xs font-medium rounded-lg bg-indigo-100 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-200 transition-colors"
                >
                  {t('modal.quickFinebi')}
                </button>
                <button
                  type="button"
                  onClick={() => handleQuickUrlFill('custom')}
                  className="px-2.5 py-1 text-xs font-medium rounded-lg bg-teal-100 dark:bg-teal-950 text-teal-700 dark:text-teal-300 hover:bg-teal-200 transition-colors"
                >
                  {t('modal.quickCustom')}
                </button>
              </div>
            </div>
          )}

          {/* Platform & Category */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
                {t('modal.platform')}
              </label>
              <div className="grid grid-cols-3 gap-2">
                {(['finebi', 'custom', 'external'] as PlatformType[]).map((p) => (
                  <button
                    type="button"
                    key={p}
                    onClick={() => {
                      setPlatform(p);
                      if (p === 'finebi') setThemeColor('indigo');
                      if (p === 'custom') setThemeColor('teal');
                      if (p === 'external') setThemeColor('green');
                    }}
                    className={`py-2 px-2 text-xs font-medium rounded-xl border transition-all ${
                      platform === p
                        ? 'border-teal-600 bg-teal-50 dark:bg-teal-950 text-teal-700 dark:text-teal-300 ring-2 ring-teal-500/20'
                        : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
                    }`}
                  >
                    {p === 'finebi' ? t('modal.pFinebi') : p === 'custom' ? t('modal.pCustom') : t('modal.pExternal')}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
                {t('modal.category')}
              </label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value as any)}
                className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-teal-500"
              >
                {CATEGORIES.filter((c) => c !== '全部').map((cat) => (
                  <option key={cat} value={cat}>
                    {translateCategory(cat, lang, t)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Title */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
              {t('modal.name')}
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t('modal.namePh')}
              className="w-full px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:outline-none focus:ring-2 focus:ring-teal-500"
              required
            />
          </div>

          {/* URL */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
              <Link2 className="w-3.5 h-3.5 text-slate-400" />
              {t('modal.url')}
            </label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t('modal.urlPh')}
              className="w-full px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-teal-500"
              required
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
              {t('modal.desc')}
            </label>
            <textarea
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('modal.descPh')}
              className="w-full px-3.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-xs focus:outline-none focus:ring-2 focus:ring-teal-500 resize-none"
            />
          </div>

          {/* Department, Owner, UpdateFrequency */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1 flex items-center gap-1">
                <Building className="w-3.5 h-3.5" /> {t('modal.dept')}
              </label>
              <input
                type="text"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                placeholder={t('modal.deptPh')}
                className="w-full px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1 flex items-center gap-1">
                <User className="w-3.5 h-3.5" /> {t('modal.owner')}
              </label>
              <input
                type="text"
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                placeholder={t('modal.ownerPh')}
                className="w-full px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1 flex items-center gap-1">
                <Clock className="w-3.5 h-3.5" /> {t('modal.freq')}
              </label>
              <select
                value={updateFrequency}
                onChange={(e) => setUpdateFrequency(e.target.value as UpdateFrequency)}
                className="w-full px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
              >
                <option value="实时流式">{t('freq.realtime')}</option>
                <option value="每小时">{t('freq.hourly')}</option>
                <option value="每日0点">{t('freq.daily')}</option>
                <option value="周度更新">{t('freq.weekly')}</option>
                <option value="月度汇总">{t('freq.monthly')}</option>
              </select>
            </div>
          </div>

          {/* Icon & Theme Color */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2 border-t border-slate-100 dark:border-slate-800">
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5" /> {t('modal.icons')}
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
                        ? 'bg-teal-600 text-white shadow-sm'
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
                <Palette className="w-3.5 h-3.5" /> {t('modal.color')}
              </label>
              <div className="space-y-1.5 max-h-28 overflow-y-auto">
                {colorOptions.map((opt) => (
                  <button
                    type="button"
                    key={opt.id}
                    onClick={() => setThemeColor(opt.id)}
                    className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg text-xs transition-all ${
                      themeColor === opt.id
                        ? 'bg-teal-50 dark:bg-teal-950/60 border border-teal-300 dark:border-teal-800 font-medium'
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
              {t('modal.tags')}
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
                placeholder={t('modal.tagPh')}
                className="flex-1 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
              <button
                type="button"
                onClick={handleAddTag}
                className="px-3 py-1.5 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-xs font-medium rounded-lg text-slate-700 dark:text-slate-300"
              >
                {t('modal.tagAdd')}
              </button>
            </div>
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs"
                  >
                    #{translateTag(tag, lang, t)}
                    <button
                      type="button"
                      onClick={() => handleRemoveTag(tag)}
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
                className="rounded text-teal-600 focus:ring-teal-500"
              />
              <span className="flex items-center gap-1 font-medium">
                <Pin className="w-3.5 h-3.5 text-amber-500" />
                {t('modal.pinOpt')}
              </span>
            </label>

            <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={isFavorite}
                onChange={(e) => setIsFavorite(e.target.checked)}
                className="rounded text-teal-600 focus:ring-teal-500"
              />
              <span className="flex items-center gap-1 font-medium">
                <Star className="w-3.5 h-3.5 text-amber-400 fill-amber-400" />
                {t('modal.favOpt')}
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
            {t('modal.cancel')}
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            className="px-5 py-2 text-xs font-semibold text-white bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 rounded-xl shadow-sm shadow-teal-600/20 transition-all flex items-center gap-1.5"
          >
            <Save className="w-3.5 h-3.5" />
            {t('modal.save')}
          </button>
        </div>
      </div>
    </div>
  );
};

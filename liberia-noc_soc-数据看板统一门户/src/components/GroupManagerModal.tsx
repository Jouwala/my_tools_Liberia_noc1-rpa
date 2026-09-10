import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  X,
  Plus,
  Pencil,
  Trash2,
  Check,
  Layers,
  AlertCircle,
  Info,
  Save,
  RefreshCw,
  Languages,
  GripVertical,
  ChevronUp,
  ChevronDown,
  Search,
  Inbox,
} from 'lucide-react';
import { DashboardItem } from '../types/dashboard';
import {
  FALLBACK_GROUP,
  MAX_GROUP_NAME_LENGTH,
  countByGroup,
  type GroupErrorCode,
  type GroupReorderResult,
} from '../utils/groups';
import { useI18n } from '../i18n';

export interface GroupOpFeedback {
  ok: boolean;
  error?: GroupErrorCode;
  /** 因本次分组变更被自动同步改写的卡片数量 */
  moved?: number;
  /** 删除分组时卡片实际迁移到的分组 */
  fallback?: string;
}

interface GroupManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
  groups: string[];
  dashboards: DashboardItem[];
  /** 新增分组：中文规范名 + 英文显示名（可空） */
  onAdd: (name: string, enLabel: string) => GroupOpFeedback;
  /** 重命名分组：中文规范名可改，英文显示名同步保存（卡片会自动同步） */
  onRename: (oldName: string, newName: string, enLabel: string) => GroupOpFeedback;
  onDelete: (name: string) => GroupOpFeedback;
  /** 调整分组顺序：把 from 位置的分组挪到 to 位置（App 内部落地 groups 数组顺序） */
  onReorder: (from: number, to: number) => GroupReorderResult;
  /** 取某分组当前生效的英文名（含内置字典兜底），用于编辑时回填 */
  labelOfEn: (name: string) => string;
  /** 是否具备「保存为默认目录」的条件（本机 localhost + 管理员） */
  canSaveDefault?: boolean;
  onSaveDefault?: () => void;
}

const inputCls =
  'w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500';

const iconBtnCls =
  'p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors shrink-0 disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent';

export const GroupManagerModal: React.FC<GroupManagerModalProps> = ({
  isOpen,
  onClose,
  groups,
  dashboards,
  onAdd,
  onRename,
  onDelete,
  onReorder,
  labelOfEn,
  canSaveDefault = false,
  onSaveDefault,
}) => {
  const { t } = useI18n();
  const [newName, setNewName] = useState('');
  const [newNameEn, setNewNameEn] = useState('');
  const [editingName, setEditingName] = useState<string | null>(null);
  const [draftName, setDraftName] = useState('');
  const [draftNameEn, setDraftNameEn] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [filter, setFilter] = useState('');
  const [dragName, setDragName] = useState<string | null>(null);

  // 拖拽过程中回调会立刻改写 groups，用 ref 拿最新值，避免闭包读到旧顺序
  const groupsRef = useRef(groups);
  groupsRef.current = groups;
  const dragNameRef = useRef<string | null>(null);
  /** 本次拖拽是否真的发生过位移（只点一下手柄不该提示「已调整」） */
  const dragMovedRef = useRef(false);

  // 每次打开重置临时状态，避免上次的报错/草稿残留
  useEffect(() => {
    if (isOpen) {
      setNewName('');
      setNewNameEn('');
      setEditingName(null);
      setDraftName('');
      setDraftNameEn('');
      setError('');
      setNotice('');
      setFilter('');
      setDragName(null);
      dragNameRef.current = null;
    }
  }, [isOpen]);

  const counts = useMemo(() => countByGroup(dashboards), [dashboards]);
  const totalBoards = useMemo(
    () => dashboards.filter((d) => groups.includes(d.category)).length,
    [dashboards, groups]
  );

  // 筛选同时匹配规范名与英文名，方便分组变多后快速定位
  const visibleGroups = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return groups;
    return groups.filter(
      (g) => g.toLowerCase().includes(q) || labelOfEn(g).toLowerCase().includes(q)
    );
  }, [groups, filter, labelOfEn]);

  const errorText = (code?: GroupErrorCode): string => {
    switch (code) {
      case 'empty':
        return t('grp.errEmpty');
      case 'too_long':
        return t('grp.errTooLong', { n: MAX_GROUP_NAME_LENGTH });
      case 'duplicate':
        return t('grp.errDup');
      case 'reserved':
        return t('grp.errReserved');
      case 'not_found':
        return t('grp.errNotFound');
      case 'last_group':
        return t('grp.errLast');
      default:
        return '';
    }
  };

  const applyFeedback = (fb: GroupOpFeedback, okMessage: string): boolean => {
    if (!fb.ok) {
      setNotice('');
      setError(errorText(fb.error));
      return false;
    }
    setError('');
    setNotice(okMessage);
    return true;
  };

  const handleAdd = () => {
    const name = newName.trim();
    const ok = applyFeedback(onAdd(name, newNameEn), t('grp.addOk', { name }));
    if (ok) {
      setNewName('');
      setNewNameEn('');
    }
    return ok;
  };

  const startEdit = (name: string) => {
    setEditingName(name);
    setDraftName(name);
    setDraftNameEn(labelOfEn(name));
    setError('');
    setNotice('');
  };

  /** 提交重命名；返回是否成功（失败时保持编辑态并显示原因，绝不静默丢弃） */
  const commitEdit = (): boolean => {
    if (!editingName) return true;
    const ok = applyFeedback(
      onRename(editingName, draftName, draftNameEn),
      t('grp.renameOk', { old: editingName, new: draftName.trim() })
    );
    if (ok) setEditingName(null);
    return ok;
  };

  /** 焦点离开整个编辑块才提交（在中文/英文两个输入框之间切换不应提前提交） */
  const handleEditBlur = (e: React.FocusEvent<HTMLDivElement>) => {
    if (!editingName) return;
    const next = e.relatedTarget as Node | null;
    if (next && e.currentTarget.contains(next)) return;
    commitEdit();
  };

  /** 关闭前先把未提交的分组名改动落下来，避免「输入了名字却什么都没发生」 */
  const handleClose = () => {
    if (editingName && !commitEdit()) return;
    onClose();
  };

  const handleDelete = (name: string) => {
    const remaining = groups.filter((g) => g !== name);
    if (remaining.length === 0) {
      setNotice('');
      setError(t('grp.errLast'));
      return;
    }
    const fallback = remaining.includes(FALLBACK_GROUP) ? FALLBACK_GROUP : remaining[0];
    const affected = counts[name] ?? 0;
    if (!window.confirm(t('grp.deleteConfirm', { name, n: affected, fallback }))) return;
    applyFeedback(onDelete(name), t('grp.deleteOk', { name, n: affected, fallback }));
  };

  /**
   * 统一的排序入口：先把未提交的改名落地（绝不静默丢弃），再调整顺序。
   * 校验直接在 groups 里查真实下标，所以即便列表被筛选过，落位也准确。
   */
  const moveByName = (name: string, delta: number) => {
    const from = groups.indexOf(name);
    if (from < 0) return;
    const to = from + delta;
    if (to < 0 || to >= groups.length) return;
    if (!commitEdit()) return;
    const r = onReorder(from, to);
    if (r.ok) {
      setError('');
      setNotice(t('grp.reorderOk', { name: r.groups[r.to], n: r.to + 1 }));
    } else {
      setNotice('');
      setError(errorText(r.error));
    }
  };

  // —— 拖拽排序：按住手柄拖动，松开结束 ——
  const startDrag = (name: string) => {
    if (!commitEdit()) return;
    dragNameRef.current = name;
    dragMovedRef.current = false;
    setDragName(name);
  };

  useEffect(() => {
    if (!dragName) return;
    const onMove = (e: PointerEvent) => {
      const cur = dragNameRef.current;
      if (!cur) return;
      const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null;
      const row = el?.closest('[data-group-row]') as HTMLElement | null;
      const target = row?.getAttribute('data-group-row');
      if (!target || target === cur) return;
      const list = groupsRef.current;
      const from = list.indexOf(cur);
      const to = list.indexOf(target);
      if (from < 0 || to < 0 || from === to) return;
      const r = onReorder(from, to);
      if (r.ok) {
        dragNameRef.current = r.groups[r.to];
        dragMovedRef.current = true;
      }
    };
    const onUp = () => {
      const cur = dragNameRef.current;
      const moved = dragMovedRef.current;
      dragNameRef.current = null;
      dragMovedRef.current = false;
      setDragName(null);
      // 只是点了一下手柄（没拖动）就什么都不提示，别给「假成功」反馈
      if (!cur || !moved) return;
      const idx = groupsRef.current.indexOf(cur);
      if (idx >= 0) {
        setError('');
        setNotice(t('grp.reorderOk', { name: cur, n: idx + 1 }));
      }
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
    };
  }, [dragName, onReorder, t]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="spatial-modal-surface bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl w-full max-w-[95vw] sm:max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-4 sm:px-6 py-3 sm:py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2 sm:gap-2.5 min-w-0">
            <div className="p-2 rounded-lg bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-400 shrink-0">
              <Layers className="w-4 h-4 sm:w-5 sm:h-5" />
            </div>
            <div className="min-w-0">
              <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-sm sm:text-base truncate">
                {t('grp.title')}
              </h3>
              <p className="text-[11px] sm:text-xs text-slate-500 dark:text-slate-400 truncate">
                {t('grp.subtitle', { n: groups.length })}
              </p>
            </div>
          </div>
          <button
            onClick={handleClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-4 sm:p-6 space-y-3 overflow-y-auto">
          <div className="p-2.5 sm:p-3 bg-teal-50/70 dark:bg-teal-950/30 rounded-xl border border-teal-200/70 dark:border-teal-900 text-[11px] sm:text-xs text-teal-800 dark:text-teal-300 flex items-start gap-2">
            <Info className="w-4 h-4 shrink-0 mt-0.5" />
            <span>
              {t('grp.syncHint')}
              <br />
              {t('grp.blurCommitHint')}
              <br />
              {t('grp.reorderHint')}
            </span>
          </div>

          {error && (
            <div className="p-2.5 sm:p-3 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 rounded-xl flex items-start gap-2 text-red-700 dark:text-red-300 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {notice && (
            <div className="p-2.5 sm:p-3 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900 rounded-xl flex items-start gap-2 text-emerald-700 dark:text-emerald-300 text-xs">
              <RefreshCw className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{notice}</span>
            </div>
          )}

          {/* 新增分组：中文规范名 + 英文显示名 */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleAdd();
                }
              }}
              maxLength={MAX_GROUP_NAME_LENGTH}
              placeholder={t('grp.addPh')}
              className={`${inputCls} sm:flex-1`}
            />
            <input
              type="text"
              value={newNameEn}
              onChange={(e) => setNewNameEn(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleAdd();
                }
              }}
              maxLength={MAX_GROUP_NAME_LENGTH}
              placeholder={t('grp.addPhEn')}
              className={`${inputCls} sm:flex-1`}
            />
            <button
              type="button"
              onClick={handleAdd}
              className="px-3 py-2 rounded-lg bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 text-white text-xs font-semibold flex items-center justify-center gap-1 shadow-sm shrink-0"
            >
              <Plus className="w-3.5 h-3.5" />
              {t('grp.add')}
            </button>
          </div>

          {/* 筛选 + 统计 */}
          <div className="flex items-center gap-2">
            <div className="relative flex-1 min-w-0">
              <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
              <input
                type="text"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder={t('grp.filterPh')}
                className="w-full pl-8 pr-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
            <span className="text-[11px] text-slate-400 whitespace-nowrap shrink-0">
              {filter.trim()
                ? t('grp.filterCount', { total: groups.length, n: visibleGroups.length })
                : t('grp.boardTotal', { n: totalBoards })}
            </span>
          </div>

          {/* 分组列表 */}
          <div className="divide-y divide-slate-100 dark:divide-slate-800 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
            {groups.length === 0 && (
              <div className="p-4 text-center text-xs text-slate-400">{t('grp.empty')}</div>
            )}
            {groups.length > 0 && visibleGroups.length === 0 && (
              <div className="p-4 text-center text-xs text-slate-400">{t('grp.filterEmpty')}</div>
            )}
            {visibleGroups.map((group) => {
              const isEditing = editingName === group;
              const boardCount = counts[group] ?? 0;
              const en = labelOfEn(group);
              const realIndex = groups.indexOf(group);
              const isFirst = realIndex <= 0;
              const isLast = realIndex === groups.length - 1;
              const isFallback = group === FALLBACK_GROUP;
              return (
                <div
                  key={group}
                  data-group-row={group}
                  className={`px-2 sm:px-3 py-2.5 flex items-center gap-1 sm:gap-1.5 transition-colors ${
                    dragName === group
                      ? 'bg-teal-50/80 dark:bg-teal-950/40 opacity-70'
                      : 'bg-white dark:bg-slate-900 hover:bg-slate-50/70 dark:hover:bg-slate-800/40'
                  }`}
                >
                  <button
                    type="button"
                    data-drag-handle={group}
                    onPointerDown={() => startDrag(group)}
                    onKeyDown={(e) => {
                      if (e.altKey && e.key === 'ArrowUp') {
                        e.preventDefault();
                        moveByName(group, -1);
                      }
                      if (e.altKey && e.key === 'ArrowDown') {
                        e.preventDefault();
                        moveByName(group, 1);
                      }
                    }}
                    title={t('grp.dragTitle')}
                    className="p-1 rounded-md text-slate-300 dark:text-slate-600 hover:text-teal-600 dark:hover:text-teal-400 hover:bg-teal-50 dark:hover:bg-teal-950/40 cursor-grab active:cursor-grabbing touch-none select-none shrink-0"
                  >
                    <GripVertical className="w-4 h-4" />
                  </button>

                  <span className="w-4 text-[11px] font-mono text-slate-400 shrink-0">
                    {realIndex + 1}
                  </span>

                  {isEditing ? (
                    /* 编辑块：中文名 + 英文名 + 确认/取消；焦点离开整块才提交 */
                    <div
                      className="flex-1 flex flex-col sm:flex-row items-stretch sm:items-center gap-1.5"
                      onBlur={handleEditBlur}
                    >
                      <input
                        autoFocus
                        type="text"
                        value={draftName}
                        maxLength={MAX_GROUP_NAME_LENGTH}
                        placeholder={t('grp.colNameZh')}
                        onChange={(e) => setDraftName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            commitEdit();
                          }
                          if (e.key === 'Escape') setEditingName(null);
                        }}
                        className="flex-1 px-2 py-1.5 rounded-lg border border-teal-400 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
                      />
                      <input
                        type="text"
                        value={draftNameEn}
                        maxLength={MAX_GROUP_NAME_LENGTH}
                        placeholder={t('grp.addPhEn')}
                        onChange={(e) => setDraftNameEn(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            commitEdit();
                          }
                          if (e.key === 'Escape') setEditingName(null);
                        }}
                        className="flex-1 px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
                      />
                      <div className="flex items-center gap-0.5 shrink-0">
                        <button
                          onClick={commitEdit}
                          title={t('grp.saveName')}
                          className="p-1.5 rounded-lg text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-950/40 transition-colors"
                        >
                          <Check className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => setEditingName(null)}
                          title={t('grp.cancel')}
                          className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <span className="flex-1 min-w-0 flex items-center gap-1.5">
                        <span className="truncate">
                          <span className="text-sm font-medium text-slate-800 dark:text-slate-200">
                            {group}
                          </span>
                        </span>
                        <span
                          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-[10px] font-medium text-slate-500 dark:text-slate-400 shrink-0"
                          title={t('grp.colNameEn')}
                        >
                          <Languages className="w-3 h-3" />
                          {en && en !== group ? en : t('grp.enMissing')}
                        </span>
                        {isFallback && (
                          <span
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-950/50 text-[10px] font-medium text-amber-700 dark:text-amber-300 shrink-0"
                            title={t('grp.fallbackTip')}
                          >
                            <Inbox className="w-3 h-3" />
                            {t('grp.fallbackTag')}
                          </span>
                        )}
                      </span>

                      <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-[10px] font-medium text-slate-500 dark:text-slate-400 shrink-0 hidden sm:inline-block">
                        {t('grp.boardCount', { n: boardCount })}
                      </span>

                      <div className="flex items-center gap-0.5 shrink-0">
                        <button
                          type="button"
                          onClick={() => moveByName(group, -1)}
                          disabled={isFirst}
                          title={t('grp.moveUp')}
                          className={iconBtnCls}
                        >
                          <ChevronUp className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => moveByName(group, 1)}
                          disabled={isLast}
                          title={t('grp.moveDown')}
                          className={iconBtnCls}
                        >
                          <ChevronDown className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => startEdit(group)}
                          title={t('grp.rename')}
                          className={iconBtnCls}
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => handleDelete(group)}
                          title={t('grp.delete')}
                          className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors shrink-0"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>

          <p className="text-[11px] text-slate-400">
            {canSaveDefault ? t('grp.localSavedHint') : t('grp.saveHint')}
          </p>
        </div>

        {/* Footer */}
        <div className="px-4 sm:px-6 py-3 sm:py-4 border-t border-slate-100 dark:border-slate-800 flex items-center justify-end gap-2.5 shrink-0">
          {canSaveDefault && onSaveDefault && (
            <button
              type="button"
              onClick={() => {
                if (editingName && !commitEdit()) return;
                onSaveDefault();
              }}
              className="px-3.5 py-2 text-xs font-semibold rounded-lg bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 text-white flex items-center gap-1.5 shadow-sm"
            >
              <Save className="w-3.5 h-3.5" />
              {t('grp.saveNow')}
            </button>
          )}
          <button
            type="button"
            onClick={handleClose}
            className="px-4 py-2 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
          >
            {t('grp.close')}
          </button>
        </div>
      </div>
    </div>
  );
};

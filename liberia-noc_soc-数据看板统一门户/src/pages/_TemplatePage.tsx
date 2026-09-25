import React, { useCallback, useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { PORTAL_API } from '../config';
import { useAuth } from '../auth/AuthContext';
import { RequireAuth } from '../components/RequireAuth';
import { useI18n } from '../i18n';

// ============================================================================
// 新页面接入模板（照抄本文件即可）
// ----------------------------------------------------------------------------
// 本文件的用途：把「新增一个受登录保护的门户页面」从「读源码自己悟」变成
// 「复制本文件 → 改名 → 改接口路径」。设计与契约见
// docs/auth-module-design.md 第二节形态 A。
//
// ⚠ 文件名以下划线开头是**有意为之**（与 my_app 的 _TemplatePage.tsx 同惯例），
//   表示「这是模板，不是业务页面」。**它必须留在版本库里**：
//   .gitignore 的 `_*` 规则会匹配到它，靠 `!src/**/_*` 递归豁免救回来；
//   vite.config.ts 的 watch.ignored 同样刻意不再用 `**/_*` 以免把它一起忽略。
//   若你改了这两处规则，务必复验该文件仍在版本库里：
//     git status --porcelain src/pages/_TemplatePage.tsx
//   它必须输出 `??` 或 `M`；**什么都不输出 = 已被静默忽略**（这正是 2026-09-25
//   修掉的那个 bug，当时 `!src/_*` 只豁免一级目录，救不回 src/pages/ 下的文件）。
//
// 接入一个页面只需三件事（本文件全部演示了）：
//   1) 用 useAuth() 取身份与 apiFetch（AuthProvider 已在 src/main.tsx 全局包裹，零配置）
//   2) 用 <RequireAuth>（或 <RequireAuth admin>）包住页面，未登录自动回登录页
//   3) 所有请求走 apiFetch + PORTAL_API —— 绝不写裸 '/api/...'（会命中 nginx 的
//      通用 /api/ 打到 my_app 7038，POST 被回 405，见 src/config.ts 顶部注释）
//
// apiFetch 已自动注入 Bearer token，且**任意请求返回 401 会自动清会话回登录态**，
// 因此页面内不需要自己处理「登录过期」。
// ============================================================================

/** 接口返回的业务数据结构（按你的后端改） */
interface TemplateItem {
  id: string;
  name: string;
}

const TemplatePageInner: React.FC = () => {
  const { user, apiFetch } = useAuth();
  const { t } = useI18n();

  const [items, setItems] = useState<TemplateItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 请求竞态：用序号作废过期响应，避免快速点两次刷新时旧响应覆盖新结果。
  // 这是本项目既有约定（见 docs/architecture.md 第六节），照做即可。
  const seqRef = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seqRef.current;
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch(`${PORTAL_API}/your-endpoint`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { items?: TemplateItem[] };
      if (mine !== seqRef.current) return; // 过期响应，丢弃
      setItems(data.items ?? []);
    } catch (e) {
      if (mine !== seqRef.current) return;
      setError(String(e));
    } finally {
      if (mine === seqRef.current) setLoading(false);
    }
  }, [apiFetch]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="w-full mx-auto px-3 sm:px-6 lg:px-8 xl:px-10 py-6 flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            {t('tpl.title')}
          </h2>
          {/* 演示：如何读当前登录用户 */}
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {user?.username} · {user?.role}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-200 dark:border-navy-700 hover:bg-slate-50 dark:hover:bg-navy-800 disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          {t('tpl.refresh')}
        </button>
      </div>

      {/* 三种状态都要有：加载中 / 出错（可重试）/ 空 —— 见 AGENTS.md 原则 6。
          另注意：取不到数显示「—」而非 0（本项目硬性约束 6）。 */}
      {loading && <div className="text-xs text-slate-500">{t('app.loading')}</div>}

      {error && (
        <div className="text-xs text-rose-600 dark:text-rose-400">
          {error} ——{' '}
          <button type="button" className="underline" onClick={() => void load()}>
            {t('tpl.retry')}
          </button>
        </div>
      )}

      {!loading && !error && items?.length === 0 && (
        <div className="text-xs text-slate-500">{t('tpl.empty')}</div>
      )}

      {!loading && !error && !!items?.length && (
        <ul className="flex flex-col gap-2">
          {items.map((it) => (
            <li
              key={it.id}
              className="px-3 py-2 rounded-lg bg-white dark:bg-navy-900 border border-slate-200 dark:border-navy-700 text-sm"
            >
              {it.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

/**
 * 对外导出的页面：已包好鉴权门。
 * 仅管理员可访问的页面用 <RequireAuth admin>。
 *
 * 在 App.tsx 里接入（视图分支处）：
 *   import { TemplatePage } from './pages/_TemplatePage';
 *   ... if (view === 'template') return <TemplatePage />;
 */
export const TemplatePage: React.FC = () => (
  <RequireAuth>
    <TemplatePageInner />
  </RequireAuth>
);

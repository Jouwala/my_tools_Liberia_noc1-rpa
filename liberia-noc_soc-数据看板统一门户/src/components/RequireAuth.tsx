import React from 'react';
import { Loader2 } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { LoginView } from './LoginView';
import { useI18n } from '../i18n';

// ============================================================================
// 鉴权门组件 —— 新页面复用的**唯一入口**
// ----------------------------------------------------------------------------
// 在此之前，这段守卫是硬编码在 App.tsx:727-739 的两个裸 if（且内联了 loading
// 骨架与 LoginView 的渲染），新页面想要求登录只能复制粘贴。
// 2026-09-25 抽为本组件，接入方式见 docs/auth-module-design.md 第二节形态 A。
//
//   <RequireAuth>       登录即可访问
//   <RequireAuth admin> 仅管理员（非管理员显示无权限提示，而非白屏）
//
// 注意：本组件只负责**前端呈现层的拦截**，它不构成安全边界 ——
// 真正的强制点在服务端（server/auth/guard.ts 的 resolveCaller）。
// 前端拦截只是为了体验，绝不能作为唯一的权限依据。
// ============================================================================

interface RequireAuthProps {
  children: React.ReactNode;
  /** true = 仅管理员可访问 */
  admin?: boolean;
}

/** 全屏加载态（与 App.tsx 原内联实现保持一致） */
const LoadingScreen: React.FC = () => {
  const { t } = useI18n();
  return (
    <div className="min-h-screen bg-slate-100/60 dark:bg-navy-950 text-slate-500 dark:text-slate-400 flex flex-col items-center justify-center gap-3 font-sans">
      <Loader2 className="w-6 h-6 animate-spin text-teal-500" />
      <span className="text-xs">{t('app.loading')}</span>
    </div>
  );
};

export const RequireAuth: React.FC<RequireAuthProps> = ({ children, admin = false }) => {
  const { status, user } = useAuth();
  const { t } = useI18n();

  if (status === 'loading') return <LoadingScreen />;
  if (status === 'anon' || !user) return <LoginView />;

  if (admin && user.role !== 'admin') {
    return (
      <div className="min-h-screen bg-slate-100/60 dark:bg-navy-950 text-slate-500 dark:text-slate-400 flex flex-col items-center justify-center gap-2 font-sans px-6 text-center">
        <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          {t('auth.noPermission')}
        </span>
        <span className="text-xs">{t('auth.noPermissionHint')}</span>
      </div>
    );
  }

  return <>{children}</>;
};

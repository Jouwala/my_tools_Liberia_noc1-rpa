import React, { useState } from 'react';
import {
  Layers,
  Lock,
  User,
  LogIn,
  AlertCircle,
  Languages,
  UserPlus,
  CheckCircle2,
  ArrowLeft,
} from 'lucide-react';
import { useI18n } from '../i18n';
import { PORTAL_API } from '../config';
import { useAuth } from '../auth/AuthContext';

export const LoginView: React.FC = () => {
  const { t, lang, setLang } = useI18n();
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // —— 账号申请（游客自助提交，管理员审批）——
  const [mode, setMode] = useState<'login' | 'request'>('login');
  const [reqUser, setReqUser] = useState('');
  const [reqPwd, setReqPwd] = useState('');
  const [reqPwd2, setReqPwd2] = useState('');
  const [reqNote, setReqNote] = useState('');
  const [reqError, setReqError] = useState('');
  const [reqOk, setReqOk] = useState('');
  const [reqSubmitting, setReqSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setError('');
    setSubmitting(true);
    try {
      await login(username, password);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      if (detail.includes('invalid username or password')) {
        setError(t('auth.badCredentials'));
      } else if (detail.includes('too many failed attempts')) {
        setError(t('auth.locked'));
      } else if (detail.startsWith('HTTP') || detail.includes('fetch')) {
        setError(t('auth.networkError'));
      } else {
        setError(detail);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const switchMode = (next: 'login' | 'request') => {
    setMode(next);
    setError('');
    setReqError('');
    setReqOk('');
  };

  const handleRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (reqSubmitting) return;
    setReqError('');
    setReqOk('');
    if (reqPwd.length < 8) {
      setReqError(t('ar.pwdTooShort'));
      return;
    }
    if (reqPwd !== reqPwd2) {
      setReqError(t('ar.pwdMismatch'));
      return;
    }
    setReqSubmitting(true);
    try {
      const res = await fetch(`${PORTAL_API}/auth/register-request`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: reqUser, password: reqPwd, note: reqNote }),
      });
      const data = (await res.json().catch(() => null)) as { detail?: string } | null;
      if (!res.ok) {
        const detail = data?.detail || '';
        setReqError(
          detail === 'username_taken'
            ? t('ar.duplicate')
            : detail === 'request_pending'
              ? t('ar.pendingDup')
              : detail === 'too_many_requests'
                ? t('ar.tooMany')
                : detail.startsWith('HTTP') || detail.includes('fetch')
                  ? t('ar.networkError')
                  : detail || `HTTP ${res.status}`
        );
        return;
      }
      setReqOk(t('ar.ok'));
      setReqUser('');
      setReqPwd('');
      setReqPwd2('');
      setReqNote('');
    } catch (err) {
      setReqError(t('ar.networkError'));
    } finally {
      setReqSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-100/60 dark:bg-navy-950 text-slate-900 dark:text-slate-100 flex items-center justify-center p-4 relative font-sans">
      {/* Language Switcher */}
      <button
        onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
        className="absolute top-4 right-4 px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-900/80 backdrop-blur text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors flex items-center gap-1.5"
        title={t('nav.langTip')}
      >
        <Languages className="w-4 h-4" />
        <span className="text-xs font-bold">{lang === 'zh' ? 'EN' : '中文'}</span>
      </button>

      <div className="w-full max-w-sm">
        {/* Brand */}
        <div className="flex flex-col items-center mb-6">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-teal-500 via-cyan-500 to-sky-400 flex items-center justify-center text-white shadow-lg shadow-teal-500/25 mb-3">
            <Layers className="w-7 h-7" />
          </div>
          <h1 className="text-lg font-extrabold tracking-tight text-center">{t('app.title')}</h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            {mode === 'login' ? t('auth.subtitle') : t('ar.subtitle')}
          </p>
        </div>

        {mode === 'login' ? (
        <form
          onSubmit={handleSubmit}
          className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-xl p-6 space-y-4"
        >
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
              {t('auth.username')}
            </label>
            <div className="relative">
              <User className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder={t('auth.usernamePh')}
                autoComplete="username"
                autoFocus
                required
                className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
              {t('auth.password')}
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t('auth.passwordPh')}
                autoComplete="current-password"
                required
                className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
          </div>

          {error && (
            <div className="p-3 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 rounded-xl flex items-start gap-2 text-red-700 dark:text-red-300 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={!username.trim() || !password || submitting}
            className="w-full px-4 py-2.5 rounded-xl bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold text-sm flex items-center justify-center gap-2 shadow-sm shadow-teal-600/25 transition-all"
          >
            <LogIn className="w-4 h-4" />
            {submitting ? t('auth.submitting') : t('auth.submit')}
          </button>
        </form>
        ) : (
        <form
          onSubmit={handleRequest}
          className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-xl p-6 space-y-4"
        >
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
              {t('auth.username')}
            </label>
            <div className="relative">
              <User className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={reqUser}
                onChange={(e) => setReqUser(e.target.value)}
                placeholder={t('ar.usernamePh')}
                autoComplete="username"
                autoFocus
                required
                className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
              {t('auth.password')}
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="password"
                value={reqPwd}
                onChange={(e) => setReqPwd(e.target.value)}
                placeholder={t('ar.passwordPh')}
                autoComplete="new-password"
                required
                className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
          </div>

          <div>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="password"
                value={reqPwd2}
                onChange={(e) => setReqPwd2(e.target.value)}
                placeholder={t('ar.confirmPh')}
                autoComplete="new-password"
                required
                className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
          </div>

          <div>
            <textarea
              value={reqNote}
              onChange={(e) => setReqNote(e.target.value)}
              placeholder={t('ar.notePh')}
              rows={2}
              maxLength={500}
              className="w-full px-3 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 resize-none"
            />
          </div>

          {reqOk ? (
            <div className="p-3 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900 rounded-xl flex items-start gap-2 text-emerald-700 dark:text-emerald-300 text-xs">
              <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{reqOk}</span>
            </div>
          ) : null}

          {reqError ? (
            <div className="p-3 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 rounded-xl flex items-start gap-2 text-red-700 dark:text-red-300 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{reqError}</span>
            </div>
          ) : null}

          <button
            type="submit"
            disabled={!reqUser.trim() || !reqPwd || !reqPwd2 || reqSubmitting}
            className="w-full px-4 py-2.5 rounded-xl bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold text-sm flex items-center justify-center gap-2 shadow-sm shadow-teal-600/25 transition-all"
          >
            <UserPlus className="w-4 h-4" />
            {reqSubmitting ? t('ar.submitting') : t('ar.submit')}
          </button>
        </form>
        )}

        <div className="mt-4 text-center">
          <button
            onClick={() => switchMode(mode === 'login' ? 'request' : 'login')}
            className="text-xs font-semibold text-teal-600 dark:text-teal-400 hover:text-teal-500 inline-flex items-center gap-1.5 transition-colors"
          >
            {mode === 'login' ? (
              <>
                <UserPlus className="w-3.5 h-3.5" />
                {t('ar.requestLink')}
              </>
            ) : (
              <>
                <ArrowLeft className="w-3.5 h-3.5" />
                {t('ar.backToLogin')}
              </>
            )}
          </button>
        </div>

        <p className="text-[11px] text-slate-400 dark:text-slate-500 text-center mt-4">
          {t('auth.footer')}
        </p>
      </div>
    </div>
  );
};

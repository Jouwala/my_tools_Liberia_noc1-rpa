import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { PORTAL_API } from '../config';

// ============================================================================
// 门户鉴权上下文
//  - token 存 localStorage（liberia_noc_auth_v1），刷新后 GET /api/auth/me 恢复会话
//  - apiFetch 自动注入 Authorization: Bearer；任意请求 401 → 清 token 回到登录态
// ============================================================================

export type Role = 'admin' | 'viewer';

/** 门户自身视图（与 App 的 ViewMode 一致） */
export type PortalViewMode = 'grid' | 'list' | 'matrix' | 'tasks';

/** 登录后落地目标：门户视图 或 指定卡片（管理员在用户管理里配置） */
export interface LandingTarget {
  view?: PortalViewMode;
  cardId?: string;
}

export interface AuthUser {
  id: string;
  username: string;
  role: Role;
  mustChangePassword: boolean;
  createdAt: string;
  /** 登录后落地页（缺省 = 不干预） */
  landing?: LandingTarget | null;
  /** 可见分组白名单（分组规范名）；null = 不限制 */
  allowedGroups?: string[] | null;
  /** 可见卡片白名单（DashboardItem.id）；null = 不限制 */
  allowedCards?: string[] | null;
}

export type AuthStatus = 'loading' | 'anon' | 'authed';

const TOKEN_KEY = 'liberia_noc_auth_v1';

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  updateUser: (user: AuthUser) => void;
  setToken: (token: string) => void;
  /** 自动携带 Bearer token 的 fetch；遇 401 自动清除会话回到登录态 */
  apiFetch: (path: string, init?: RequestInit) => Promise<Response>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setTokenState] = useState<string | null>(() => readStoredToken());

  const clearSession = useCallback(() => {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      // localStorage 不可用时仅清内存态
    }
    setTokenState(null);
    setUser(null);
    setStatus('anon');
  }, []);

  useEffect(() => {
    if (!token) {
      setStatus('anon');
      return;
    }
    let cancelled = false;
    fetch(`${PORTAL_API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { user: AuthUser };
        if (cancelled) return;
        setUser(data.user);
        setStatus('authed');
      })
      .catch(() => {
        if (!cancelled) clearSession();
      });
    return () => {
      cancelled = true;
    };
  }, [token, clearSession]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await fetch(`${PORTAL_API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = (await res.json().catch(() => null)) as {
      token?: string;
      user?: AuthUser;
      detail?: string;
    } | null;
    if (!res.ok || !data?.token || !data.user) {
      throw new Error(data?.detail || `HTTP ${res.status}`);
    }
    try {
      localStorage.setItem(TOKEN_KEY, data.token);
    } catch {
      // 忽略持久化失败（会话仅存活于本页内存）
    }
    setTokenState(data.token);
    setUser(data.user);
    setStatus('authed');
  }, []);

  const logout = useCallback(async () => {
    const current = token;
    clearSession();
    if (current) {
      try {
        await fetch(`${PORTAL_API}/auth/logout`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${current}` },
        });
      } catch {
        // 登出上报失败不影响本地登出
      }
    }
  }, [token, clearSession]);

  const updateUser = useCallback((next: AuthUser) => setUser(next), []);

  /** 重新拉取当前用户（管理员改动页面配置/角色后，无需重新登录即可生效） */
  const refreshUser = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${PORTAL_API}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return;
      const data = (await res.json().catch(() => null)) as { user?: AuthUser } | null;
      if (data?.user) setUser(data.user);
    } catch {
      // 网络异常时保留现有用户态，避免误判成登出
    }
  }, [token]);

  // 窗口重新获得焦点 / 标签页切回时刷新用户态（30s 节流）：
  // 管理员在用户管理里刚改完「页面配置」，被改的账号切回页面即可看到新范围。
  useEffect(() => {
    if (!token) return;
    let last = 0;
    const onFocus = () => {
      const now = Date.now();
      if (now - last < 30_000) return;
      last = now;
      void refreshUser();
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
    };
  }, [token, refreshUser]);

  const setToken = useCallback((next: string) => {
    try {
      localStorage.setItem(TOKEN_KEY, next);
    } catch {
      // 忽略
    }
    setTokenState(next);
  }, []);

  const apiFetch = useCallback(
    async (path: string, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      if (token) headers.set('Authorization', `Bearer ${token}`);
      const res = await fetch(path, { ...init, headers });
      if (res.status === 401) clearSession();
      return res;
    },
    [token, clearSession]
  );

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, login, logout, updateUser, setToken, apiFetch }),
    [status, user, login, logout, updateUser, setToken, apiFetch]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

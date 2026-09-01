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

export interface AuthUser {
  id: string;
  username: string;
  role: Role;
  mustChangePassword: boolean;
  createdAt: string;
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

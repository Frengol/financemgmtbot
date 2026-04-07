import type { ReactNode } from 'react';
import { createContext, startTransition, useContext, useEffect, useState } from 'react';
import { getAuthSession, localDevBypassEnabled, logoutAuthSession } from '@/lib/adminApi';
import {
  clearBrowserAdminProfile,
  clearBrowserAdminTestSession,
  decodeAccessTokenIdentity,
  loadBrowserAdminProfile,
  loadBrowserAdminTestSession,
  saveBrowserAdminProfile,
} from '@/lib/auth';
import { supabase } from '@/lib/supabase';

type AuthUser = {
  id: string;
  email?: string | null;
};

type SessionLike = {
  access_token?: string;
  user?: {
    id: string;
    email?: string | null;
  } | null;
} | null;

type AuthContextValue = {
  authenticated: boolean;
  user: AuthUser | null;
  csrfToken: string;
  loading: boolean;
  localBypass: boolean;
  signOut: () => Promise<void>;
  refreshSession: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function stripTokenFragment() {
  if (typeof window === 'undefined') {
    return;
  }

  if (window.location.pathname.endsWith('/auth/callback')) {
    return;
  }

  const hash = window.location.hash || '';
  if (!hash.includes('access_token=') && !hash.includes('refresh_token=')) {
    return;
  }

  const cleanUrl = `${window.location.pathname}${window.location.search}`;
  window.history.replaceState({}, document.title, cleanUrl);
}

function isAuthCallbackRoute() {
  return typeof window !== 'undefined' && window.location.pathname.endsWith('/auth/callback');
}

function buildAuthUser(session: SessionLike): AuthUser | null {
  if (!session?.access_token) {
    return null;
  }

  const claims = decodeAccessTokenIdentity(session.access_token);
  const storedProfile = loadBrowserAdminProfile();
  const userId = session.user?.id || claims?.id || storedProfile?.id;
  const email = session.user?.email ?? claims?.email ?? storedProfile?.email ?? null;

  if (!userId) {
    return null;
  }

  return {
    id: userId,
    email,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [csrfToken, setCsrfToken] = useState('');
  const [loading, setLoading] = useState(true);

  const refreshSession = async () => {
    const authCallbackRoute = isAuthCallbackRoute();

    if (localDevBypassEnabled) {
      startTransition(() => {
        setAuthenticated(true);
        setUser({
          id: 'local-dev',
          email: 'local-dev@localhost',
        });
        setCsrfToken('local-dev-csrf');
        setLoading(false);
      });
      return;
    }

    try {
      const browserAuthTestSession = loadBrowserAdminTestSession();
      if (browserAuthTestSession?.accessToken && browserAuthTestSession.user?.id) {
        startTransition(() => {
          setAuthenticated(true);
          setUser(browserAuthTestSession.user);
          setCsrfToken('');
          setLoading(false);
        });
        return;
      }

      const { data } = await supabase.auth.getSession();
      const session = data.session;
      const authUser = buildAuthUser(session);
      if (session?.access_token && authUser) {
        saveBrowserAdminProfile(authUser);
        startTransition(() => {
          setAuthenticated(true);
          setUser(authUser);
          setCsrfToken('');
          setLoading(false);
        });
        return;
      }

      if (authCallbackRoute) {
        startTransition(() => {
          setAuthenticated(false);
          setUser(null);
          setCsrfToken('');
          setLoading(false);
        });
        return;
      }

      const payload = await getAuthSession();
      if (!payload.authenticated) {
        clearBrowserAdminProfile();
        clearBrowserAdminTestSession();
      }
      startTransition(() => {
        setAuthenticated(Boolean(payload.authenticated));
        setUser(payload.user || null);
        setCsrfToken(payload.csrfToken || '');
        setLoading(false);
      });
    } catch {
      if (!authCallbackRoute) {
        clearBrowserAdminProfile();
        clearBrowserAdminTestSession();
      }
      startTransition(() => {
        setAuthenticated(false);
        setUser(null);
        setCsrfToken('');
        setLoading(false);
      });
    }
  };

  useEffect(() => {
    let mounted = true;
    stripTokenFragment();

    const load = async () => {
      await refreshSession();
      if (!mounted) {
        return;
      }
    };

    void load();

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_, session) => {
      if (!session?.access_token) {
        void refreshSession();
        return;
      }

      const authUser = buildAuthUser(session);
      if (!authUser) {
        void refreshSession();
        return;
      }

      saveBrowserAdminProfile(authUser);
      startTransition(() => {
        setAuthenticated(true);
        setUser(authUser);
        setCsrfToken('');
        setLoading(false);
      });
    });

    const onFocus = () => {
      void refreshSession();
    };
    window.addEventListener('focus', onFocus);

    return () => {
      mounted = false;
      subscription.unsubscribe();
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  return (
    <AuthContext.Provider
      value={{
        authenticated,
        user,
        csrfToken,
        loading,
        localBypass: localDevBypassEnabled,
        signOut: async () => {
          if (!localDevBypassEnabled) {
            await supabase.auth.signOut();
            await logoutAuthSession().catch(() => undefined);
          }
          clearBrowserAdminProfile();
          clearBrowserAdminTestSession();
          startTransition(() => {
            setAuthenticated(false);
            setUser(null);
            setCsrfToken('');
          });
        },
        refreshSession,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider.');
  }

  return context;
}

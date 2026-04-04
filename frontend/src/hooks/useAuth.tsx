import type { ReactNode } from 'react';
import { createContext, startTransition, useContext, useEffect, useState } from 'react';
import { getAuthSession, localDevBypassEnabled, logoutAuthSession } from '@/lib/adminApi';

type AuthUser = {
  id: string;
  email?: string | null;
};

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

  const hash = window.location.hash || '';
  if (!hash.includes('access_token=') && !hash.includes('refresh_token=')) {
    return;
  }

  const cleanUrl = `${window.location.pathname}${window.location.search}`;
  window.history.replaceState({}, document.title, cleanUrl);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [csrfToken, setCsrfToken] = useState('');
  const [loading, setLoading] = useState(true);

  const refreshSession = async () => {
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

    stripTokenFragment();

    try {
      const payload = await getAuthSession();
      startTransition(() => {
        setAuthenticated(Boolean(payload.authenticated));
        setUser(payload.user || null);
        setCsrfToken(payload.csrfToken || '');
        setLoading(false);
      });
    } catch {
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

    const load = async () => {
      await refreshSession();
      if (!mounted) {
        return;
      }
    };

    void load();

    const onFocus = () => {
      void refreshSession();
    };
    window.addEventListener('focus', onFocus);

    return () => {
      mounted = false;
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
            await logoutAuthSession();
          }
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

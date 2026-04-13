import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  ApiError,
  getAdminMe,
  localDevBypassEnabled,
} from '@/features/admin/api';
import {
  browserAdminAuthTestModeEnabled,
  clearBrowserAdminLoginNotice,
  decodeAccessTokenIdentity,
  loadBrowserAdminTestSession,
  saveBrowserAdminLoginNotice,
  saveBrowserAdminProfile,
} from '@/features/auth/lib/browserState';
import {
  clearBrowserAuthState,
  purgeLegacyBrowserAuthStorage,
  setCachedBrowserAccessToken,
  supabase,
} from '@/features/auth/lib/supabaseBrowserSession';

type AuthUser = {
  id: string;
  email?: string | null;
};

type AuthContextValue = {
  authenticated: boolean;
  user: AuthUser | null;
  loading: boolean;
  localBypass: boolean;
  refreshSession: () => Promise<void>;
  signOut: () => Promise<void>;
};

type AuthState = {
  authenticated: boolean;
  user: AuthUser | null;
  loading: boolean;
  localBypass: boolean;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const UNAUTHENTICATED_STATE: AuthState = {
  authenticated: false,
  user: null,
  loading: true,
  localBypass: false,
};

const LOCAL_BYPASS_STATE: AuthState = {
  authenticated: true,
  user: {
    id: 'local-dev',
    email: 'local-dev@localhost',
  },
  loading: false,
  localBypass: true,
};

function normalizeBasePath(baseUrl: string) {
  if (!baseUrl || baseUrl === '/') {
    return '';
  }
  return baseUrl.replace(/\/$/, '');
}

function currentPathname() {
  return globalThis.location?.pathname || '/';
}

function routeMatches(suffix: string) {
  const basePath = normalizeBasePath(import.meta.env.BASE_URL || '/');
  return currentPathname() === `${basePath}${suffix}`;
}

function isLoginRoute() {
  return routeMatches('/login');
}

function isAuthCallbackRoute() {
  return routeMatches('/auth/callback');
}

function isPublicAuthRoute() {
  return isLoginRoute() || isAuthCallbackRoute();
}

function isJwtShapeValid(token?: string | null) {
  return typeof token === 'string' && token.split('.').length === 3;
}

function toAuthUser(user?: { id?: string | null; email?: string | null } | null): AuthUser | null {
  if (!user?.id) {
    return null;
  }

  return {
    id: user.id,
    email: user.email ?? null,
  };
}

function fallbackUserFromAccessToken(accessToken?: string | null) {
  return decodeAccessTokenIdentity(accessToken);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(
    localDevBypassEnabled ? LOCAL_BYPASS_STATE : UNAUTHENTICATED_STATE,
  );
  const mountedRef = useRef(true);

  const setSafeState = useCallback((nextState: AuthState) => {
    if (!mountedRef.current) {
      return;
    }
    setState(nextState);
  }, []);

  const setLoggedOutState = useCallback((loading = false) => {
    setCachedBrowserAccessToken(null);
    setSafeState({
      authenticated: false,
      user: null,
      loading,
      localBypass: false,
    });
  }, [setSafeState]);

  const persistAuthFailure = useCallback(async (message: string) => {
    await clearBrowserAuthState();
    saveBrowserAdminLoginNotice({ message });
    setLoggedOutState(false);
  }, [setLoggedOutState]);

  const persistAuthorizedProfile = useCallback((authorizedUser: AuthUser) => {
    try {
      clearBrowserAdminLoginNotice();
      saveBrowserAdminProfile(authorizedUser);
    } catch {
      // Browser profile persistence is best-effort; a valid session must keep working in-memory.
    }
  }, []);

  const authorizeAccessToken = useCallback(async (
    accessToken: string,
    browserUser?: { id?: string | null; email?: string | null } | null,
  ) => {
    if (!isJwtShapeValid(accessToken)) {
      await persistAuthFailure(
        'Sua sessao de acesso e invalida. Faca login novamente. Diagnostico: auth_state_unusable',
      );
      return;
    }

    setCachedBrowserAccessToken(accessToken);

    try {
      const payload = await getAdminMe(accessToken);
      if (!payload.authenticated || !payload.authorized) {
        throw new ApiError(
          'Seu usuario nao esta autorizado a acessar o painel.',
          {
            code: 'AUTH_ACCESS_DENIED',
            status: 403,
          },
        );
      }

      const authorizedUser = toAuthUser(payload.user)
        || toAuthUser(browserUser)
        || fallbackUserFromAccessToken(accessToken);

      if (!authorizedUser) {
        throw new ApiError(
          'Nao foi possivel validar sua sessao agora. Faca login novamente.',
          {
            code: 'AUTH_SESSION_INVALID',
            diagnostic: 'auth_state_unusable',
            status: 401,
          },
        );
      }

      persistAuthorizedProfile(authorizedUser);
      setSafeState({
        authenticated: true,
        user: authorizedUser,
        loading: false,
        localBypass: false,
      });
    } catch (error) {
      if (error instanceof ApiError) {
        await persistAuthFailure(error.message);
        return;
      }

      await persistAuthFailure(
        'Nao foi possivel validar sua sessao agora. Faca login novamente. Diagnostico: auth_validation_failed',
      );
    }
  }, [persistAuthFailure, persistAuthorizedProfile, setSafeState]);

  const refreshSession = useCallback(async () => {
    if (localDevBypassEnabled) {
      purgeLegacyBrowserAuthStorage();
      clearBrowserAdminLoginNotice();
      setSafeState(LOCAL_BYPASS_STATE);
      return;
    }

    if (isPublicAuthRoute()) {
      setState((currentState) => ({
        ...currentState,
        loading: false,
      }));
      return;
    }

    const authTestMode = browserAdminAuthTestModeEnabled();

    if (mountedRef.current) {
      setState((currentState) => ({
        ...currentState,
        loading: true,
      }));
    }
    purgeLegacyBrowserAuthStorage();

    if (authTestMode) {
      const authTestSession = loadBrowserAdminTestSession();
      if (authTestSession?.accessToken && authTestSession.user?.id) {
        setCachedBrowserAccessToken(authTestSession.accessToken);
        persistAuthorizedProfile(authTestSession.user);
        setSafeState({
          authenticated: true,
          user: authTestSession.user,
          loading: false,
          localBypass: false,
        });
        return;
      }

      setLoggedOutState(false);
      return;
    }

    try {
      const { data } = await supabase.auth.getSession();
      const session = data.session ?? null;
      const accessToken = session?.access_token ?? null;

      if (!accessToken) {
        setLoggedOutState(false);
        return;
      }

      await authorizeAccessToken(accessToken, session?.user ?? null);
    } catch {
      await clearBrowserAuthState();
      setLoggedOutState(false);
    }
  }, [authorizeAccessToken, persistAuthorizedProfile, setLoggedOutState, setSafeState]);

  const signOut = useCallback(async () => {
    if (localDevBypassEnabled) {
      purgeLegacyBrowserAuthStorage();
      clearBrowserAdminLoginNotice();
      setLoggedOutState(false);
      return;
    }

    await clearBrowserAuthState();
    clearBrowserAdminLoginNotice();
    setLoggedOutState(false);
  }, [setLoggedOutState]);

  useEffect(() => {
    mountedRef.current = true;
    const authTestMode = browserAdminAuthTestModeEnabled();

    if (!localDevBypassEnabled) {
      void refreshSession();
    }

    if (localDevBypassEnabled || authTestMode) {
      return () => {
        mountedRef.current = false;
      };
    }

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (!mountedRef.current || localDevBypassEnabled) {
        return;
      }

      if (isPublicAuthRoute()) {
        return;
      }

      if (event === 'SIGNED_OUT') {
        setLoggedOutState(false);
        return;
      }

      if (event === 'INITIAL_SESSION' || event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED') {
        const accessToken = session?.access_token ?? null;
        if (!accessToken) {
          setLoggedOutState(false);
          return;
        }
        void authorizeAccessToken(accessToken, session?.user ?? null);
      }
    });

    return () => {
      mountedRef.current = false;
      subscription.unsubscribe();
    };
  }, [authorizeAccessToken, refreshSession, setLoggedOutState]);

  const value = useMemo<AuthContextValue>(() => ({
    authenticated: state.authenticated,
    user: state.user,
    loading: state.loading,
    localBypass: state.localBypass,
    refreshSession,
    signOut,
  }), [refreshSession, signOut, state]);

  return (
    <AuthContext.Provider value={value}>
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

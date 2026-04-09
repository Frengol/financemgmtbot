import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from './useAuth';
import { ApiError } from '@/lib/adminApi';

const mockGetAdminMe = vi.fn();
const mockLogoutAuthSession = vi.fn();
const mockGetSession = vi.fn();
const mockOnAuthStateChange = vi.fn();
const mockClearBrowserAuthState = vi.fn();
const mockPurgeLegacyBrowserAuthStorage = vi.fn();
const mockSetCachedBrowserAccessToken = vi.fn();
const mockBrowserAdminAuthTestModeEnabled = vi.fn();
const mockLoadBrowserAdminTestSession = vi.fn();
const mockSaveBrowserAdminProfile = vi.fn();
const mockSaveBrowserAdminLoginNotice = vi.fn();
const mockClearBrowserAdminLoginNotice = vi.fn();
const mockDecodeAccessTokenIdentity = vi.fn();

function buildJwtLikeToken(...segments: string[]) {
  return segments.join('.');
}

vi.mock('@/lib/adminApi', () => ({
  ApiError: class ApiError extends Error {
    code: string;
    status: number;

    constructor(message: string, { code, status }: { code: string; status: number }) {
      super(message);
      this.name = 'ApiError';
      this.code = code;
      this.status = status;
    }
  },
  getAdminMe: (...args: unknown[]) => mockGetAdminMe(...args),
  logoutAuthSession: (...args: unknown[]) => mockLogoutAuthSession(...args),
  localDevBypassEnabled: false,
}));

vi.mock('@/lib/supabase', () => ({
  clearBrowserAuthState: (...args: unknown[]) => mockClearBrowserAuthState(...args),
  purgeLegacyBrowserAuthStorage: (...args: unknown[]) => mockPurgeLegacyBrowserAuthStorage(...args),
  setCachedBrowserAccessToken: (...args: unknown[]) => mockSetCachedBrowserAccessToken(...args),
  supabase: {
    auth: {
      getSession: (...args: unknown[]) => mockGetSession(...args),
      onAuthStateChange: (...args: unknown[]) => mockOnAuthStateChange(...args),
    },
  },
}));

vi.mock('@/lib/auth', async () => {
  const actual = await vi.importActual<typeof import('@/lib/auth')>('@/lib/auth');
  return {
    ...actual,
    browserAdminAuthTestModeEnabled: (...args: unknown[]) => mockBrowserAdminAuthTestModeEnabled(...args),
    loadBrowserAdminTestSession: (...args: unknown[]) => mockLoadBrowserAdminTestSession(...args),
    saveBrowserAdminProfile: (...args: unknown[]) => mockSaveBrowserAdminProfile(...args),
    saveBrowserAdminLoginNotice: (...args: unknown[]) => mockSaveBrowserAdminLoginNotice(...args),
    clearBrowserAdminLoginNotice: (...args: unknown[]) => mockClearBrowserAdminLoginNotice(...args),
    decodeAccessTokenIdentity: (...args: unknown[]) => mockDecodeAccessTokenIdentity(...args),
  };
});

function AuthHarness() {
  const { authenticated, user, csrfToken, loading, refreshSession, signOut } = useAuth();

  return (
    <div>
      <div data-testid="loading">{loading ? 'loading' : 'ready'}</div>
      <div data-testid="authenticated">{authenticated ? 'yes' : 'no'}</div>
      <div data-testid="email">{user?.email || ''}</div>
      <div data-testid="csrf">{csrfToken}</div>
      <button type="button" onClick={() => void refreshSession()}>
        Refresh
      </button>
      <button type="button" onClick={() => void signOut()}>
        Sign out
      </button>
    </div>
  );
}

describe('useAuth', () => {
  beforeEach(() => {
    mockGetAdminMe.mockReset();
    mockLogoutAuthSession.mockReset();
    mockGetSession.mockReset();
    mockOnAuthStateChange.mockReset();
    mockClearBrowserAuthState.mockReset();
    mockPurgeLegacyBrowserAuthStorage.mockReset();
    mockSetCachedBrowserAccessToken.mockReset();
    mockBrowserAdminAuthTestModeEnabled.mockReset();
    mockLoadBrowserAdminTestSession.mockReset();
    mockSaveBrowserAdminProfile.mockReset();
    mockSaveBrowserAdminLoginNotice.mockReset();
    mockClearBrowserAdminLoginNotice.mockReset();
    mockDecodeAccessTokenIdentity.mockReset();

    mockBrowserAdminAuthTestModeEnabled.mockReturnValue(false);
    mockLoadBrowserAdminTestSession.mockReturnValue(null);
    mockGetSession.mockResolvedValue({ data: { session: null } });
    mockOnAuthStateChange.mockReturnValue({
      data: {
        subscription: {
          unsubscribe: vi.fn(),
        },
      },
    });
    mockGetAdminMe.mockResolvedValue({
      authenticated: true,
      authorized: true,
      user: {
        id: 'user-1',
        email: 'admin@example.com',
      },
    });
    mockClearBrowserAuthState.mockResolvedValue(undefined);
    mockLogoutAuthSession.mockResolvedValue({ loggedOut: true });
    mockDecodeAccessTokenIdentity.mockReturnValue(null);
  });

  it('hydrates the app from the official Supabase browser session and validates admin access', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload', 'signature');
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('ready');
    });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('yes');
    expect(screen.getByTestId('email')).toHaveTextContent('admin@example.com');
    expect(screen.getByTestId('csrf')).toHaveTextContent('');
    expect(mockGetAdminMe).toHaveBeenCalledWith(accessToken);
    expect(mockSetCachedBrowserAccessToken).toHaveBeenCalledWith(accessToken);
    expect(mockSaveBrowserAdminProfile).toHaveBeenCalledWith({
      id: 'user-1',
      email: 'admin@example.com',
    });
  });

  it('uses the auth test session only in local auth test mode', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-test', 'signature');
    mockBrowserAdminAuthTestModeEnabled.mockReturnValue(true);
    mockLoadBrowserAdminTestSession.mockReturnValue({
      accessToken,
      refreshToken: 'refresh-1',
      user: {
        id: 'auth-test-user',
        email: 'admin@example.com',
      },
    });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('ready');
    });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('yes');
    expect(screen.getByTestId('email')).toHaveTextContent('admin@example.com');
    expect(mockGetSession).not.toHaveBeenCalled();
    expect(mockGetAdminMe).not.toHaveBeenCalled();
    expect(mockOnAuthStateChange).not.toHaveBeenCalled();
    expect(mockSetCachedBrowserAccessToken).toHaveBeenCalledWith(accessToken);
  });

  it('does not let an empty Supabase session overwrite a valid local auth test session', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-test', 'signature');
    mockBrowserAdminAuthTestModeEnabled.mockReturnValue(true);
    mockLoadBrowserAdminTestSession.mockReturnValue({
      accessToken,
      refreshToken: 'refresh-1',
      user: {
        id: 'auth-test-user',
        email: 'admin@example.com',
      },
    });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('ready');
    });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('yes');
    expect(screen.getByTestId('email')).toHaveTextContent('admin@example.com');
    expect(mockGetSession).not.toHaveBeenCalled();
    expect(mockOnAuthStateChange).not.toHaveBeenCalled();
    expect(mockClearBrowserAuthState).not.toHaveBeenCalled();
  });

  it('clears malformed browser auth state instead of falling back to /auth/session', async () => {
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: 'not-a-jwt',
          user: { id: 'user-1', email: 'broken@example.com' },
        },
      },
    });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('ready');
    });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    expect(mockClearBrowserAuthState).toHaveBeenCalledTimes(1);
    expect(mockSaveBrowserAdminLoginNotice).toHaveBeenCalledWith({
      message: 'Sua sessao de acesso e invalida. Faca login novamente. Diagnostico: auth_state_unusable',
    });
    expect(mockGetAdminMe).not.toHaveBeenCalled();
  });

  it('reacts to auth state changes and signs out cleanly', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-refresh', 'signature');
    let authStateHandler: ((event: string, session: { access_token?: string; user?: { id?: string; email?: string | null } | null } | null) => void) | undefined;
    mockOnAuthStateChange.mockImplementation((handler: typeof authStateHandler) => {
      authStateHandler = handler;
      return {
        data: {
          subscription: {
            unsubscribe: vi.fn(),
          },
        },
      };
    });
    mockGetSession.mockResolvedValue({ data: { session: null } });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });

    authStateHandler?.('SIGNED_IN', {
      access_token: accessToken,
      user: { id: 'user-2', email: 'admin2@example.com' },
    });

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('yes');
    });

    authStateHandler?.('SIGNED_OUT', null);

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));

    await waitFor(() => {
      expect(mockClearBrowserAuthState).toHaveBeenCalled();
      expect(mockLogoutAuthSession).toHaveBeenCalledTimes(1);
    });
  });

  it('treats an empty initial browser session as logged out in the published flow', async () => {
    let authStateHandler: ((event: string, session: { access_token?: string; user?: { id?: string; email?: string | null } | null } | null) => void) | undefined;
    mockOnAuthStateChange.mockImplementation((handler: typeof authStateHandler) => {
      authStateHandler = handler;
      return {
        data: {
          subscription: {
            unsubscribe: vi.fn(),
          },
        },
      };
    });
    mockGetSession.mockResolvedValue({ data: { session: null } });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });

    authStateHandler?.('INITIAL_SESSION', null);

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });
  });

  it('persists a short validation failure notice when backend authorization throws a non-api error', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload', 'signature');
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });
    mockGetAdminMe.mockRejectedValue(new Error('network boom'));

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('ready');
    });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    expect(mockSaveBrowserAdminLoginNotice).toHaveBeenCalledWith({
      message: 'Nao foi possivel validar sua sessao agora. Faca login novamente. Diagnostico: auth_validation_failed',
    });
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
  });

  it('keeps the backend auth message when validation fails with a typed ApiError', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload', 'signature');
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });
    mockGetAdminMe.mockRejectedValue(new ApiError('Seu usuario nao esta autorizado a acessar o painel.', {
      code: 'AUTH_ACCESS_DENIED',
      status: 403,
    }));

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });

    expect(mockSaveBrowserAdminLoginNotice).toHaveBeenCalledWith({
      message: 'Seu usuario nao esta autorizado a acessar o painel.',
    });
  });

  it('logs out when the backend responds with an unauthenticated or unauthorized payload', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-denied', 'signature');
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });
    mockGetAdminMe.mockResolvedValue({
      authenticated: false,
      authorized: false,
      user: null,
    });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });

    expect(mockSaveBrowserAdminLoginNotice).toHaveBeenCalledWith({
      message: 'Seu usuario nao esta autorizado a acessar o painel.',
    });
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
  });

  it('clears browser state when reading the persisted Supabase session throws unexpectedly', async () => {
    mockGetSession.mockRejectedValue(new Error('session read failed'));

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('ready');
    });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
  });

  it('uses the decoded access token identity when the backend response omits the user payload', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-fallback', 'signature');
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: null,
        },
      },
    });
    mockGetAdminMe.mockResolvedValue({
      authenticated: true,
      authorized: true,
      user: null,
    });
    mockDecodeAccessTokenIdentity.mockReturnValue({
      id: 'token-user',
      email: 'token@example.com',
    });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('yes');
    });

    expect(screen.getByTestId('email')).toHaveTextContent('token@example.com');
    expect(mockSaveBrowserAdminProfile).toHaveBeenCalledWith({
      id: 'token-user',
      email: 'token@example.com',
    });
  });

  it('logs the browser out when neither backend nor token claims provide a usable identity', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-empty', 'signature');
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: null,
        },
      },
    });
    mockGetAdminMe.mockResolvedValue({
      authenticated: true,
      authorized: true,
      user: null,
    });
    mockDecodeAccessTokenIdentity.mockReturnValue(null);

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });

    expect(mockSaveBrowserAdminLoginNotice).toHaveBeenCalledWith({
      message: 'Nao foi possivel validar sua sessao agora. Faca login novamente.',
    });
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
  });

  it('keeps the browser flow logged out when an auth event arrives without an access token', async () => {
    let authStateHandler: ((event: string, session: { access_token?: string; user?: { id?: string; email?: string | null } | null } | null) => void) | undefined;
    mockOnAuthStateChange.mockImplementation((handler: typeof authStateHandler) => {
      authStateHandler = handler;
      return {
        data: {
          subscription: {
            unsubscribe: vi.fn(),
          },
        },
      };
    });
    mockGetSession.mockResolvedValue({ data: { session: null } });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });

    authStateHandler?.('SIGNED_IN', { user: { id: 'user-1', email: 'admin@example.com' } });

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });
  });

  it('ignores late auth events after the provider unmounts', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-late', 'signature');
    let authStateHandler: ((event: string, session: { access_token?: string; user?: { id?: string; email?: string | null } | null } | null) => void) | undefined;
    mockOnAuthStateChange.mockImplementation((handler: typeof authStateHandler) => {
      authStateHandler = handler;
      return {
        data: {
          subscription: {
            unsubscribe: vi.fn(),
          },
        },
      };
    });
    mockGetSession.mockResolvedValue({ data: { session: null } });

    const view = render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });

    view.unmount();
    authStateHandler?.('SIGNED_IN', {
      access_token: accessToken,
      user: { id: 'user-1', email: 'admin@example.com' },
    });

    expect(mockGetAdminMe).not.toHaveBeenCalledWith(accessToken);
  });

  it('stays logged out in auth test mode when no deterministic local session exists', async () => {
    mockBrowserAdminAuthTestModeEnabled.mockReturnValue(true);
    mockLoadBrowserAdminTestSession.mockReturnValue(null);

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('ready');
    });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    expect(mockGetSession).not.toHaveBeenCalled();
    expect(mockOnAuthStateChange).not.toHaveBeenCalled();
  });

  it('supports local development bypass without touching Supabase or backend auth routes', async () => {
    vi.resetModules();

    const bypassGetSession = vi.fn();
    const bypassOnAuthStateChange = vi.fn().mockReturnValue({
      data: {
        subscription: {
          unsubscribe: vi.fn(),
        },
      },
    });
    const bypassClearBrowserAuthState = vi.fn();
    const bypassPurgeLegacyBrowserAuthStorage = vi.fn();
    const bypassLogout = vi.fn();

    vi.doMock('@/lib/adminApi', () => ({
      ApiError: class ApiError extends Error {},
      getAdminMe: vi.fn(),
      logoutAuthSession: (...args: unknown[]) => bypassLogout(...args),
      localDevBypassEnabled: true,
    }));
    vi.doMock('@/lib/supabase', () => ({
      clearBrowserAuthState: (...args: unknown[]) => bypassClearBrowserAuthState(...args),
      purgeLegacyBrowserAuthStorage: (...args: unknown[]) => bypassPurgeLegacyBrowserAuthStorage(...args),
      setCachedBrowserAccessToken: vi.fn(),
      supabase: {
        auth: {
          getSession: (...args: unknown[]) => bypassGetSession(...args),
          onAuthStateChange: (...args: unknown[]) => bypassOnAuthStateChange(...args),
        },
      },
    }));

    const authModule = await import('./useAuth');

    function BypassHarness() {
      const { authenticated, user, csrfToken, loading, signOut } = authModule.useAuth();
      return (
        <div>
          <div data-testid="bypass-loading">{loading ? 'loading' : 'ready'}</div>
          <div data-testid="bypass-authenticated">{authenticated ? 'yes' : 'no'}</div>
          <div data-testid="bypass-email">{user?.email || ''}</div>
          <div data-testid="bypass-csrf">{csrfToken}</div>
          <button type="button" onClick={() => void signOut()}>
            Bypass sign out
          </button>
        </div>
      );
    }

    render(
      <authModule.AuthProvider>
        <BypassHarness />
      </authModule.AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('bypass-loading')).toHaveTextContent('ready');
    });

    expect(screen.getByTestId('bypass-authenticated')).toHaveTextContent('yes');
    expect(screen.getByTestId('bypass-email')).toHaveTextContent('local-dev@localhost');
    expect(screen.getByTestId('bypass-csrf')).toHaveTextContent('local-dev-csrf');

    await userEvent.click(screen.getByRole('button', { name: 'Bypass sign out' }));

    expect(bypassGetSession).not.toHaveBeenCalled();
    expect(bypassLogout).not.toHaveBeenCalled();
    expect(bypassClearBrowserAuthState).not.toHaveBeenCalled();
    expect(bypassPurgeLegacyBrowserAuthStorage).toHaveBeenCalledTimes(1);
  });

  it('throws outside the provider', () => {
    function InvalidHarness() {
      useAuth();
      return null;
    }

    expect(() => render(<InvalidHarness />)).toThrow('useAuth must be used within AuthProvider.');
  });
});

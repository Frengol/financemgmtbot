import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from './useAuth';

const mockGetAuthSession = vi.fn();
const mockGetSession = vi.fn();
const mockOnAuthStateChange = vi.fn();
const mockSignOut = vi.fn();
const mockLogoutAuthSession = vi.fn();

vi.mock('@/lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: (...args: unknown[]) => mockGetSession(...args),
      onAuthStateChange: (...args: unknown[]) => mockOnAuthStateChange(...args),
      signOut: (...args: unknown[]) => mockSignOut(...args),
    },
  },
}));

vi.mock('@/lib/adminApi', () => ({
  getAuthSession: (...args: unknown[]) => mockGetAuthSession(...args),
  logoutAuthSession: (...args: unknown[]) => mockLogoutAuthSession(...args),
  localDevBypassEnabled: false,
}));

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
    mockGetAuthSession.mockReset();
    mockGetSession.mockReset();
    mockOnAuthStateChange.mockReset();
    mockSignOut.mockReset();
    mockLogoutAuthSession.mockReset();
    window.localStorage.clear();
    window.history.pushState({}, '', '/#access_token=abc&refresh_token=def');
    mockOnAuthStateChange.mockReturnValue({
      data: {
        subscription: {
          unsubscribe: vi.fn(),
        },
      },
    });
  });

  it('loads the Supabase session and refreshes on focus', async () => {
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: 'token-1',
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

    window.dispatchEvent(new Event('focus'));

    await waitFor(() => {
      expect(mockGetSession).toHaveBeenCalledTimes(2);
    });
    expect(mockGetAuthSession).not.toHaveBeenCalled();
  });

  it('falls back to the backend session lookup when the browser session is missing', async () => {
    mockGetSession.mockResolvedValue({
      data: {
        session: null,
      },
    });
    mockGetAuthSession.mockResolvedValue({
      authenticated: true,
      user: { id: 'user-1', email: 'admin@example.com' },
      csrfToken: 'csrf-token',
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
    expect(screen.getByTestId('csrf')).toHaveTextContent('csrf-token');
  });

  it('hydrates the authorized user from JWT claims when the Supabase session omits user metadata', async () => {
    const jwtPayload = btoa(JSON.stringify({
      sub: 'user-claims',
      email: 'admin@example.com',
      exp: 9999999999,
    }))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/g, '');

    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: `header.${jwtPayload}.signature`,
          user: null,
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
    expect(mockGetAuthSession).not.toHaveBeenCalled();
  });

  it('accepts the browser auth test session fallback used by the integrated magic-link tests', async () => {
    window.localStorage.setItem('financemgmtbot-admin-auth-test-session', JSON.stringify({
      accessToken: 'auth-test-token',
      refreshToken: 'auth-test-refresh',
      user: {
        id: 'auth-test-user',
        email: 'admin@example.com',
      },
    }));
    mockGetSession.mockResolvedValue({
      data: {
        session: null,
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
    expect(mockGetAuthSession).not.toHaveBeenCalled();
  });

  it('falls back to a logged-out state when both session lookups fail', async () => {
    mockGetSession.mockRejectedValue(new Error('network'));
    mockGetAuthSession.mockRejectedValue(new Error('network'));

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('ready');
    });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
  });

  it('signs out through Supabase, clears local auth state and clears legacy backend cookies best-effort', async () => {
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: 'token-1',
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });
    mockSignOut.mockResolvedValue({ error: null });
    mockLogoutAuthSession.mockResolvedValue({ loggedOut: true });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('yes');
    });

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));

    await waitFor(() => {
      expect(mockSignOut).toHaveBeenCalledTimes(1);
      expect(mockLogoutAuthSession).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    expect(screen.getByTestId('csrf')).toHaveTextContent('');
  });

  it('allows manual refresh, reacts to auth state changes and throws outside the provider', async () => {
    let authStateHandler: ((event: string, session: { access_token?: string; user?: { id: string; email?: string | null } } | null) => void) | undefined;
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
    mockGetSession
      .mockResolvedValueOnce({
        data: {
          session: null,
        },
      })
      .mockResolvedValueOnce({
        data: {
          session: {
            access_token: 'token-2',
            user: { id: 'user-2', email: 'admin2@example.com' },
          },
        },
      })
      .mockResolvedValueOnce({
        data: {
          session: null,
        },
      });
    mockGetAuthSession
      .mockResolvedValueOnce({
        authenticated: false,
      })
      .mockResolvedValueOnce({
        authenticated: false,
      });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });

    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('yes');
    });
    authStateHandler?.('SIGNED_OUT', null);
    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });
    expect(mockGetAuthSession).toHaveBeenCalledTimes(2);

    function InvalidHarness() {
      useAuth();
      return null;
    }

    expect(() => render(<InvalidHarness />)).toThrow('useAuth must be used within AuthProvider.');
  });

  it('falls back to refreshSession when the auth state change does not resolve a usable user', async () => {
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
    mockGetSession
      .mockResolvedValueOnce({
        data: {
          session: null,
        },
      })
      .mockResolvedValueOnce({
        data: {
          session: null,
        },
      });
    mockGetAuthSession
      .mockResolvedValueOnce({
        authenticated: false,
      })
      .mockResolvedValueOnce({
        authenticated: false,
      });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });

    authStateHandler?.('SIGNED_IN', {
      access_token: 'token-without-user',
      user: null,
    });

    await waitFor(() => {
      expect(mockGetSession).toHaveBeenCalledTimes(2);
    });
    expect(mockGetAuthSession).toHaveBeenCalledTimes(2);
  });

  it('hydrates the authenticated state directly from a valid auth state change session', async () => {
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
    mockGetSession.mockResolvedValue({
      data: {
        session: null,
      },
    });
    mockGetAuthSession.mockResolvedValue({
      authenticated: false,
    });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });

    authStateHandler?.('SIGNED_IN', {
      access_token: 'token-3',
      user: { id: 'user-3', email: 'admin3@example.com' },
    });

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('yes');
    });
    expect(screen.getByTestId('email')).toHaveTextContent('admin3@example.com');
    expect(screen.getByTestId('csrf')).toHaveTextContent('');
  });

  it('preserves the magic-link token fragment while the auth callback route is mounting', async () => {
    window.history.pushState({}, '', '/auth/callback#access_token=abc&refresh_token=def');
    mockGetSession.mockResolvedValue({
      data: {
        session: null,
      },
    });
    mockGetAuthSession.mockResolvedValue({
      authenticated: false,
    });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('ready');
    });

    expect(window.location.hash).toContain('access_token=abc');
    expect(window.location.hash).toContain('refresh_token=def');
    expect(mockGetAuthSession).not.toHaveBeenCalled();
  });

  it('supports local development bypass without calling the backend logout route', async () => {
    vi.resetModules();
    const bypassGetSession = vi.fn();
    const bypassOnAuthStateChange = vi.fn().mockReturnValue({
      data: {
        subscription: {
          unsubscribe: vi.fn(),
        },
      },
    });
    const bypassSignOut = vi.fn();
    const bypassLogout = vi.fn();

    vi.doMock('@/lib/supabase', () => ({
      supabase: {
        auth: {
          getSession: (...args: unknown[]) => bypassGetSession(...args),
          onAuthStateChange: (...args: unknown[]) => bypassOnAuthStateChange(...args),
          signOut: (...args: unknown[]) => bypassSignOut(...args),
        },
      },
    }));
    vi.doMock('@/lib/adminApi', () => ({
      getAuthSession: (...args: unknown[]) => bypassGetSession(...args),
      logoutAuthSession: (...args: unknown[]) => bypassLogout(...args),
      localDevBypassEnabled: true,
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
    expect(bypassSignOut).not.toHaveBeenCalled();
    expect(bypassLogout).not.toHaveBeenCalled();
    expect(screen.getByTestId('bypass-authenticated')).toHaveTextContent('no');
  });
});

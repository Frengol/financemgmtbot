import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';

type UseAuthCaseContext = Record<string, any>;

export function registerUseAuthEventCases({
  AuthProvider,
  AuthHarness,
  buildJwtLikeToken,
  mockClearBrowserAuthState,
  mockGetAdminMe,
  mockGetSession,
  mockOnAuthStateChange,
}: UseAuthCaseContext) {
  it('reacts to auth state changes and signs out cleanly', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-refresh', 'signature');
    let authStateHandler:
      | ((event: string, session: { access_token?: string; user?: { id?: string; email?: string | null } | null } | null) => void)
      | undefined;

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
    });
  });

  it('treats an empty initial browser session as logged out in the published flow', async () => {
    let authStateHandler:
      | ((event: string, session: { access_token?: string; user?: { id?: string; email?: string | null } | null } | null) => void)
      | undefined;

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

  it('keeps the browser flow logged out when an auth event arrives without an access token', async () => {
    let authStateHandler:
      | ((event: string, session: { access_token?: string; user?: { id?: string; email?: string | null } | null } | null) => void)
      | undefined;

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
    let authStateHandler:
      | ((event: string, session: { access_token?: string; user?: { id?: string; email?: string | null } | null } | null) => void)
      | undefined;

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

  it('stays silent during /auth/callback so the callback owns session completion alone', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-callback', 'signature');
    let authStateHandler:
      | ((event: string, session: { access_token?: string; user?: { id?: string; email?: string | null } | null } | null) => void)
      | undefined;

    window.history.pushState({}, '', '/auth/callback');
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
      expect(mockOnAuthStateChange).toHaveBeenCalledTimes(1);
    });

    expect(mockGetSession).not.toHaveBeenCalled();
    expect(mockGetAdminMe).not.toHaveBeenCalled();

    authStateHandler?.('SIGNED_IN', {
      access_token: accessToken,
      user: { id: 'user-1', email: 'admin@example.com' },
    });

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });
    expect(mockGetAdminMe).not.toHaveBeenCalled();
  });

  it('stays silent during /login so the screen can bootstrap auth without touching /api/admin/me', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-login', 'signature');
    let authStateHandler:
      | ((event: string, session: { access_token?: string; user?: { id?: string; email?: string | null } | null } | null) => void)
      | undefined;

    window.history.pushState({}, '', '/login');
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
      expect(mockOnAuthStateChange).toHaveBeenCalledTimes(1);
    });

    expect(mockGetSession).not.toHaveBeenCalled();
    expect(mockGetAdminMe).not.toHaveBeenCalled();

    authStateHandler?.('INITIAL_SESSION', {
      access_token: accessToken,
      user: { id: 'user-1', email: 'admin@example.com' },
    });

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });
    expect(mockGetAdminMe).not.toHaveBeenCalled();
  });

  it('stays silent during the published callback route when BASE_URL is not root', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-callback-base', 'signature');
    let authStateHandler:
      | ((event: string, session: { access_token?: string; user?: { id?: string; email?: string | null } | null } | null) => void)
      | undefined;

    vi.stubEnv('BASE_URL', '/financemgmtbot/');
    window.history.pushState({}, '', '/financemgmtbot/auth/callback');
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
      expect(mockOnAuthStateChange).toHaveBeenCalledTimes(1);
    });

    expect(mockGetSession).not.toHaveBeenCalled();
    authStateHandler?.('TOKEN_REFRESHED', {
      access_token: accessToken,
      user: { id: 'user-1', email: 'admin@example.com' },
    });

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });
    expect(mockGetAdminMe).not.toHaveBeenCalled();
  });

  it('stays silent during the published login route when BASE_URL is not root', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-login-base', 'signature');
    let authStateHandler:
      | ((event: string, session: { access_token?: string; user?: { id?: string; email?: string | null } | null } | null) => void)
      | undefined;

    vi.stubEnv('BASE_URL', '/financemgmtbot/');
    window.history.pushState({}, '', '/financemgmtbot/login');
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
      expect(mockOnAuthStateChange).toHaveBeenCalledTimes(1);
    });

    expect(mockGetSession).not.toHaveBeenCalled();
    authStateHandler?.('TOKEN_REFRESHED', {
      access_token: accessToken,
      user: { id: 'user-1', email: 'admin@example.com' },
    });

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    });
    expect(mockGetAdminMe).not.toHaveBeenCalled();
  });
}

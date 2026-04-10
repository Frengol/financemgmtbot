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
}

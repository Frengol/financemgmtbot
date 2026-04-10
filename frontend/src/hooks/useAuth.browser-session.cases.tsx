import { render, screen, waitFor } from '@testing-library/react';
import { expect, it } from 'vitest';

type UseAuthCaseContext = Record<string, any>;

export function registerUseAuthBrowserSessionCases({
  AuthProvider,
  AuthHarness,
  buildJwtLikeToken,
  mockBrowserAdminAuthTestModeEnabled,
  mockLoadBrowserAdminTestSession,
  mockGetAdminMe,
  mockGetSession,
  mockOnAuthStateChange,
  mockClearBrowserAuthState,
  mockSaveBrowserAdminLoginNotice,
  mockSaveBrowserAdminProfile,
  mockSetCachedBrowserAccessToken,
}: UseAuthCaseContext) {
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
}

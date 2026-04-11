import { render, screen, waitFor } from '@testing-library/react';
import { expect, it } from 'vitest';

type UseAuthCaseContext = Record<string, any>;

export function registerUseAuthValidationCases({
  ApiError,
  AuthProvider,
  AuthHarness,
  buildJwtLikeToken,
  mockClearBrowserAuthState,
  mockDecodeAccessTokenIdentity,
  mockGetAdminMe,
  mockGetSession,
  mockSaveBrowserAdminLoginNotice,
  mockSaveBrowserAdminProfile,
}: UseAuthCaseContext) {
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

  it('keeps the user authenticated when browser profile persistence fails after a valid admin handshake', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-storage', 'signature');
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-1', email: 'admin@example.com' },
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
    mockSaveBrowserAdminProfile.mockImplementation(() => {
      throw new Error('storage unavailable');
    });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('yes');
    });

    expect(screen.getByTestId('email')).toHaveTextContent('admin@example.com');
    expect(mockSaveBrowserAdminLoginNotice).not.toHaveBeenCalledWith({
      message: 'Nao foi possivel validar sua sessao agora. Faca login novamente. Diagnostico: auth_validation_failed',
    });
    expect(mockClearBrowserAuthState).not.toHaveBeenCalled();
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
}

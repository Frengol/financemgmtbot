import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

function buildJwtLikeToken(...segments: string[]) {
  return segments.join('.');
}

const mockGetSession = vi.fn();
const mockOnAuthStateChange = vi.fn();
const mockGetAdminMe = vi.fn();
const mockClearBrowserAuthState = vi.fn();
const mockSetCachedBrowserAccessToken = vi.fn();
const mockSaveBrowserAdminProfile = vi.fn();
const mockSaveBrowserAdminTestSession = vi.fn();
const mockSaveBrowserAdminLoginNotice = vi.fn();
const mockClearBrowserAdminLoginNotice = vi.fn();
const mockClearBrowserAdminProfile = vi.fn();
const mockClearBrowserAdminTestSession = vi.fn();
const mockDecodeAccessTokenIdentity = vi.fn();
const mockBrowserAdminAuthTestModeEnabled = vi.fn();
const mockEmitClientTelemetry = vi.fn();
const mockBuildPublicApiUrl = vi.fn();
const mockSaveAuthCallbackDiagnosticSnapshot = vi.fn();
const mockClearAuthCallbackDiagnosticSnapshot = vi.fn();
const runtimeFetchMock = vi.fn();

vi.mock('@/features/auth/lib/supabaseBrowserSession', () => ({
  clearBrowserAuthState: (...args: unknown[]) => mockClearBrowserAuthState(...args),
  setCachedBrowserAccessToken: (...args: unknown[]) => mockSetCachedBrowserAccessToken(...args),
  supabase: {
    auth: {
      getSession: (...args: unknown[]) => mockGetSession(...args),
      onAuthStateChange: (...args: unknown[]) => mockOnAuthStateChange(...args),
    },
  },
}));

vi.mock('@/features/admin/api', async () => {
  const actual = await vi.importActual<typeof import('@/features/admin/api')>('@/features/admin/api');
  return {
    ...actual,
    getAdminMe: (...args: unknown[]) => mockGetAdminMe(...args),
  };
});

vi.mock('@/features/auth/lib/browserState', async () => {
  const actual = await vi.importActual<typeof import('@/features/auth/lib/browserState')>('@/features/auth/lib/browserState');
  return {
    ...actual,
    saveBrowserAdminProfile: (...args: unknown[]) => mockSaveBrowserAdminProfile(...args),
    saveBrowserAdminTestSession: (...args: unknown[]) => mockSaveBrowserAdminTestSession(...args),
    saveBrowserAdminLoginNotice: (...args: unknown[]) => mockSaveBrowserAdminLoginNotice(...args),
    clearBrowserAdminLoginNotice: (...args: unknown[]) => mockClearBrowserAdminLoginNotice(...args),
    clearBrowserAdminProfile: (...args: unknown[]) => mockClearBrowserAdminProfile(...args),
    clearBrowserAdminTestSession: (...args: unknown[]) => mockClearBrowserAdminTestSession(...args),
    decodeAccessTokenIdentity: (...args: unknown[]) => mockDecodeAccessTokenIdentity(...args),
    browserAdminAuthTestModeEnabled: (...args: unknown[]) => mockBrowserAdminAuthTestModeEnabled(...args),
  };
});

vi.mock('@/features/observability/clientTelemetry', () => ({
  buildPublicApiUrl: (...args: unknown[]) => mockBuildPublicApiUrl(...args),
  clearAuthCallbackDiagnosticSnapshot: (...args: unknown[]) => mockClearAuthCallbackDiagnosticSnapshot(...args),
  emitClientTelemetry: (...args: unknown[]) => mockEmitClientTelemetry(...args),
  ensureSupportCodeInMessage: (message: string, clientEventId?: string) =>
    clientEventId && !/codigo de suporte:/i.test(message)
      ? `${message} Codigo de suporte: ${clientEventId}`
      : message,
  saveAuthCallbackDiagnosticSnapshot: (...args: unknown[]) => mockSaveAuthCallbackDiagnosticSnapshot(...args),
}));

describe('AuthCallback', () => {
  beforeEach(() => {
    vi.resetModules();
    mockGetSession.mockReset();
    mockOnAuthStateChange.mockReset();
    mockGetAdminMe.mockReset();
    mockClearBrowserAuthState.mockReset();
    mockSetCachedBrowserAccessToken.mockReset();
    mockSaveBrowserAdminProfile.mockReset();
    mockSaveBrowserAdminTestSession.mockReset();
    mockSaveBrowserAdminLoginNotice.mockReset();
    mockClearBrowserAdminLoginNotice.mockReset();
    mockClearBrowserAdminProfile.mockReset();
    mockClearBrowserAdminTestSession.mockReset();
    mockDecodeAccessTokenIdentity.mockReset();
    mockBrowserAdminAuthTestModeEnabled.mockReset();
    mockEmitClientTelemetry.mockReset();
    mockBuildPublicApiUrl.mockReset();
    mockSaveAuthCallbackDiagnosticSnapshot.mockReset();
    mockClearAuthCallbackDiagnosticSnapshot.mockReset();
    runtimeFetchMock.mockReset();

    mockBrowserAdminAuthTestModeEnabled.mockReturnValue(false);
    mockClearBrowserAuthState.mockResolvedValue(undefined);
    mockBuildPublicApiUrl.mockImplementation((path: string) => path);
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
      user: { id: 'user-1', email: 'admin@example.com' },
    });
    mockDecodeAccessTokenIdentity.mockReturnValue({ id: 'user-1', email: 'admin@example.com' });
    runtimeFetchMock.mockResolvedValue(new Response('{}', {
      status: 200,
      headers: { 'X-Request-ID': 'req_runtime_default' },
    }));
    vi.stubGlobal('fetch', runtimeFetchMock);
    window.history.pushState({}, '', '/auth/callback');
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('shows an explicit error when the upstream link is invalid or expired', async () => {
    window.history.pushState({}, '', '/auth/callback#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired');

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    expect(await screen.findByText(/link de acesso invalido ou expirado/i)).toBeInTheDocument();
    expect(mockGetAdminMe).not.toHaveBeenCalled();
    expect(mockClearBrowserAdminProfile).toHaveBeenCalled();
    expect(mockClearBrowserAdminTestSession).toHaveBeenCalled();
  });

  it('surfaces non-expired upstream callback failures without leaking raw provider details', async () => {
    window.history.pushState({}, '', '/auth/callback#error=server_error&error_description=Temporary+provider+failure');

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    expect(await screen.findByText(/temporary provider failure/i)).toBeInTheDocument();
    expect(mockGetAdminMe).not.toHaveBeenCalled();
  });

  it('waits for the persisted Supabase browser session and validates admin access before redirecting home', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload', 'signature');
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    await waitFor(() => {
      expect(mockGetAdminMe).toHaveBeenCalledWith(accessToken);
    });
    expect(mockSetCachedBrowserAccessToken).toHaveBeenCalledWith(accessToken);
    expect(mockSaveBrowserAdminProfile).toHaveBeenCalledWith({
      id: 'user-1',
      email: 'admin@example.com',
    });
    expect(mockClearBrowserAdminLoginNotice).toHaveBeenCalled();
    expect(replaceSpy).toHaveBeenCalledWith(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
  });

  it('accepts a session that arrives later through onAuthStateChange', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-late', 'signature');
    let authStateHandler: ((event: string, session: { access_token?: string; user?: { id?: string; email?: string | null } | null } | null) => void) | undefined;
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    mockGetSession.mockResolvedValue({ data: { session: null } });
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

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    await waitFor(() => {
      expect(mockOnAuthStateChange).toHaveBeenCalledTimes(1);
    });

    authStateHandler?.('SIGNED_IN', {
      access_token: accessToken,
      user: { id: 'user-2', email: 'admin2@example.com' },
    });

    await waitFor(() => {
      expect(mockGetAdminMe).toHaveBeenCalledWith(accessToken);
    });
    expect(mockSaveBrowserAdminProfile).toHaveBeenCalledWith({
      id: 'user-2',
      email: 'admin2@example.com',
    });
    expect(replaceSpy).toHaveBeenCalledWith(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
  });

  it('retries the admin validation once and completes the login when the second attempt succeeds', async () => {
    vi.useFakeTimers();
    const { ApiError } = await import('@/features/admin/api');
    const accessToken = buildJwtLikeToken('header', 'payload-retry', 'signature');
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });
    mockGetAdminMe
      .mockRejectedValueOnce(new ApiError('transport failed', {
        code: 'NETWORK_ERROR',
        diagnostic: 'frontend_cross_origin_transport_failed',
        status: 0,
        clientEventId: 'cli_retry_1',
      }))
      .mockResolvedValueOnce({
        authenticated: true,
        authorized: true,
        user: { id: 'user-1', email: 'admin@example.com' },
      });

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(mockGetAdminMe).toHaveBeenCalledTimes(2);
    expect(replaceSpy).toHaveBeenCalledWith(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
    expect(mockSaveBrowserAdminLoginNotice).not.toHaveBeenCalled();
    expect(mockSaveAuthCallbackDiagnosticSnapshot).not.toHaveBeenCalled();
  });

  it('keeps the loopback auth test callback path isolated from the production runtime', async () => {
    mockBrowserAdminAuthTestModeEnabled.mockReturnValue(true);
    const accessToken = buildJwtLikeToken('header', 'payload-test', 'signature');
    window.history.pushState(
      {},
      '',
      `/auth/callback#access_token=${accessToken}&refresh_token=refresh-1&auth_test_user_id=user-1&auth_test_email=admin%40example.com`,
    );
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    await waitFor(() => {
      expect(mockSaveBrowserAdminTestSession).toHaveBeenCalledWith({
        accessToken,
        refreshToken: 'refresh-1',
        user: {
          id: 'user-1',
          email: 'admin@example.com',
        },
      });
    });
    expect(mockGetAdminMe).not.toHaveBeenCalled();
    expect(replaceSpy).toHaveBeenCalledWith(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
  });

  it('shows a short diagnostic when the browser session never becomes usable', async () => {
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: 'not-a-jwt',
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });
    mockEmitClientTelemetry.mockReturnValue('cli_invalid_session_1');

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    expect(await screen.findByText(/diagnostico: session_store_invalid/i)).toBeInTheDocument();
    expect(screen.getByText(/codigo de suporte: cli_invalid_session_1/i)).toBeInTheDocument();
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
    expect(mockEmitClientTelemetry).toHaveBeenCalledWith(expect.objectContaining({
      event: 'auth_callback_failed',
      phase: 'callback_session_resolution',
      diagnostic: 'session_store_invalid',
    }));
  });

  it('shows a short diagnostic when the browser session never appears after the callback', async () => {
    mockGetSession.mockResolvedValue({ data: { session: null } });
    mockOnAuthStateChange.mockReturnValue({
      data: {
        subscription: {
          unsubscribe: vi.fn(),
        },
      },
    });

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    expect(await screen.findByText(/diagnostico: session_store_invalid/i, {}, { timeout: 6000 })).toBeInTheDocument();
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
  });

  it('saves a short notice and returns to login when backend authorization fails', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-denied', 'signature');
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    mockEmitClientTelemetry.mockReturnValue('cli_auth_callback_1');
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });
    mockGetAdminMe.mockRejectedValue(new Error('Seu usuario nao esta autorizado a acessar o painel. Codigo de suporte: req_authz_1'));

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    await waitFor(() => {
      expect(mockSaveBrowserAdminLoginNotice).toHaveBeenCalledWith({
        message: 'Seu usuario nao esta autorizado a acessar o painel. Codigo de suporte: req_authz_1',
      });
    });
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
    expect(replaceSpy).toHaveBeenCalledWith(new URL('login', new URL(import.meta.env.BASE_URL, window.location.origin)).toString());
    expect(mockEmitClientTelemetry).toHaveBeenCalledWith(expect.objectContaining({
      event: 'auth_callback_failed',
      phase: 'callback_admin_validation',
      requestId: 'req_authz_1',
    }));
  });

  it('keeps the user on the callback page and saves a local snapshot when transport fails twice but runtime stays reachable', async () => {
    vi.useFakeTimers();
    const { ApiError } = await import('@/features/admin/api');
    const accessToken = buildJwtLikeToken('header', 'payload-runtime-ok', 'signature');
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });
    mockGetAdminMe
      .mockRejectedValueOnce(new ApiError('transport failed', {
        code: 'NETWORK_ERROR',
        diagnostic: 'frontend_cross_origin_transport_failed',
        status: 0,
        clientEventId: 'cli_runtime_ok',
      }))
      .mockRejectedValueOnce(new ApiError('transport failed again', {
        code: 'NETWORK_ERROR',
        diagnostic: 'frontend_cross_origin_transport_failed',
        status: 0,
        clientEventId: 'cli_runtime_ok',
      }));
    runtimeFetchMock.mockResolvedValue(new Response('{}', {
      status: 200,
      headers: { 'X-Request-ID': 'req_runtime_ok' },
    }));

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(mockSaveAuthCallbackDiagnosticSnapshot).toHaveBeenCalled();
    expect(screen.getByText(/diagnostico: auth_callback_admin_validation_failed/i)).toBeInTheDocument();
    expect(screen.getByText(/codigo de suporte: cli_runtime_ok/i)).toBeInTheDocument();
    expect(replaceSpy).not.toHaveBeenCalledWith(new URL('login', new URL(import.meta.env.BASE_URL, window.location.origin)).toString());
    expect(mockSaveBrowserAdminLoginNotice).not.toHaveBeenCalled();
    expect(mockClearBrowserAuthState).not.toHaveBeenCalled();
    expect(runtimeFetchMock).toHaveBeenCalledWith('/api/meta/runtime', expect.objectContaining({
      method: 'GET',
      mode: 'cors',
      cache: 'no-store',
    }));
    expect(mockSaveAuthCallbackDiagnosticSnapshot).toHaveBeenCalledWith(expect.objectContaining({
      clientEventId: 'cli_runtime_ok',
      diagnostic: 'auth_callback_admin_validation_failed',
      retryOutcome: 'retry_failed',
      runtimeProbeOutcome: 'reachable',
      runtimeRequestId: 'req_runtime_ok',
    }));
    expect(mockEmitClientTelemetry).toHaveBeenCalledWith(expect.objectContaining({
      clientEventId: 'cli_runtime_ok',
      diagnostic: 'auth_callback_admin_validation_failed',
    }));
  });

  it('keeps the user on the callback page and confirms a browser transport problem when runtime probing also fails', async () => {
    vi.useFakeTimers();
    const { ApiError } = await import('@/features/admin/api');
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com');
    const accessToken = buildJwtLikeToken('header', 'payload-runtime-down', 'signature');
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });
    mockGetAdminMe
      .mockRejectedValueOnce(new ApiError('transport failed', {
        code: 'NETWORK_ERROR',
        diagnostic: 'frontend_cross_origin_transport_failed',
        status: 0,
        clientEventId: 'cli_runtime_down',
      }))
      .mockRejectedValueOnce(new ApiError('transport failed again', {
        code: 'NETWORK_ERROR',
        diagnostic: 'frontend_cross_origin_transport_failed',
        status: 0,
        clientEventId: 'cli_runtime_down',
      }));
    runtimeFetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(mockSaveAuthCallbackDiagnosticSnapshot).toHaveBeenCalled();
    expect(screen.getByText(/diagnostico: frontend_cors_blocked_confirmed/i)).toBeInTheDocument();
    expect(screen.getByText(/codigo de suporte: cli_runtime_down/i)).toBeInTheDocument();
    expect(replaceSpy).not.toHaveBeenCalled();
    expect(mockSaveBrowserAdminLoginNotice).not.toHaveBeenCalled();
    expect(mockSaveAuthCallbackDiagnosticSnapshot).toHaveBeenCalledWith(expect.objectContaining({
      clientEventId: 'cli_runtime_down',
      diagnostic: 'frontend_cors_blocked_confirmed',
      retryOutcome: 'retry_failed',
      runtimeProbeOutcome: 'transport_failed',
    }));
    expect(mockEmitClientTelemetry).toHaveBeenCalledWith(expect.objectContaining({
      clientEventId: 'cli_runtime_down',
      diagnostic: 'frontend_cors_blocked_confirmed',
      corsSuspected: true,
    }));
  });

  it('falls back to the regular login redirect when the retry turns into an explicit auth denial', async () => {
    vi.useFakeTimers();
    const { ApiError } = await import('@/features/admin/api');
    const accessToken = buildJwtLikeToken('header', 'payload-retry-authz', 'signature');
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });
    mockGetAdminMe
      .mockRejectedValueOnce(new ApiError('transport failed', {
        code: 'NETWORK_ERROR',
        diagnostic: 'frontend_cross_origin_transport_failed',
        status: 0,
        clientEventId: 'cli_retry_authz',
      }))
      .mockRejectedValueOnce(new ApiError('Seu usuario nao esta autorizado a acessar o painel.', {
        code: 'AUTH_ACCESS_DENIED',
        status: 403,
        requestId: 'req_retry_authz',
      }));

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockSaveBrowserAdminLoginNotice).toHaveBeenCalledWith({
      message: 'Seu usuario nao esta autorizado a acessar o painel.',
    });
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
    expect(replaceSpy).toHaveBeenCalledWith(new URL('login', new URL(import.meta.env.BASE_URL, window.location.origin)).toString());
  });

  it('uses the generic transport diagnostic when the runtime probe also fails on the same origin', async () => {
    vi.useFakeTimers();
    const { ApiError } = await import('@/features/admin/api');
    const accessToken = buildJwtLikeToken('header', 'payload-same-origin', 'signature');
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });
    mockGetAdminMe
      .mockRejectedValueOnce(new ApiError('transport failed', {
        code: 'NETWORK_ERROR',
        diagnostic: 'frontend_transport_failed',
        status: 0,
        clientEventId: 'cli_same_origin',
      }))
      .mockRejectedValueOnce(new ApiError('transport failed again', {
        code: 'NETWORK_ERROR',
        diagnostic: 'frontend_transport_failed',
        status: 0,
        clientEventId: 'cli_same_origin',
      }));
    runtimeFetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText(/diagnostico: frontend_transport_failed/i)).toBeInTheDocument();
    expect(mockSaveAuthCallbackDiagnosticSnapshot).toHaveBeenCalledWith(expect.objectContaining({
      diagnostic: 'frontend_transport_failed',
      runtimeProbeOutcome: 'transport_failed',
    }));
  });

  it('clears auth state and local diagnostics when the user returns to login from an inline callback error', async () => {
    vi.useFakeTimers();
    const { ApiError } = await import('@/features/admin/api');
    const accessToken = buildJwtLikeToken('header', 'payload-button', 'signature');
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-1', email: 'admin@example.com' },
        },
      },
    });
    mockGetAdminMe
      .mockRejectedValueOnce(new ApiError('transport failed', {
        code: 'NETWORK_ERROR',
        diagnostic: 'frontend_cross_origin_transport_failed',
        status: 0,
        clientEventId: 'cli_button_retry',
      }))
      .mockRejectedValueOnce(new ApiError('transport failed again', {
        code: 'NETWORK_ERROR',
        diagnostic: 'frontend_cross_origin_transport_failed',
        status: 0,
        clientEventId: 'cli_button_retry',
      }));
    runtimeFetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
      await Promise.resolve();
      await Promise.resolve();
    });

    fireEvent.click(screen.getByRole('button', { name: /voltar para o login/i }));
    await Promise.resolve();
    await Promise.resolve();

    expect(mockClearBrowserAuthState).toHaveBeenCalled();
    expect(mockClearAuthCallbackDiagnosticSnapshot).toHaveBeenCalled();
    expect(replaceSpy).toHaveBeenCalledWith(new URL('login', new URL(import.meta.env.BASE_URL, window.location.origin)).toString());
  });

  it('treats a resolved but unauthorized admin identity as a login failure', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-denied', 'signature');
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
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
      authorized: false,
      user: { id: 'user-1', email: 'admin@example.com' },
    });

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    await waitFor(() => {
      expect(mockSaveBrowserAdminLoginNotice).toHaveBeenCalledWith({
        message: 'Seu usuario nao esta autorizado a acessar o painel.',
      });
    });
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
    expect(replaceSpy).toHaveBeenCalledWith(new URL('login', new URL(import.meta.env.BASE_URL, window.location.origin)).toString());
  });

  it('uses the callback fallback profile when the browser session does not expose a user object', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-fallback', 'signature');
    window.history.pushState({}, '', '/auth/callback?user_id=user-from-query&email=admin%40example.com');
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    mockDecodeAccessTokenIdentity.mockReturnValue(null);
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: null,
        },
      },
    });

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    await waitFor(() => {
      expect(mockSaveBrowserAdminProfile).toHaveBeenCalledWith({
        id: 'user-from-query',
        email: 'admin@example.com',
      });
    });
    expect(replaceSpy).toHaveBeenCalledWith(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
  });

  it('shows a short diagnostic when the callback finishes with no resolvable user profile', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-noprofile', 'signature');
    mockDecodeAccessTokenIdentity.mockReturnValue(null);
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: null,
        },
      },
    });
    window.history.pushState({}, '', '/auth/callback');

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    expect(await screen.findByText(/diagnostico: session_store_invalid/i)).toBeInTheDocument();
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
  });

  it('stops the callback flow cleanly when the component unmounts before the browser session resolves', async () => {
    let resolveSession: ((value: { data: { session: null } }) => void) | undefined;
    mockGetSession.mockReturnValue(new Promise((resolve) => {
      resolveSession = resolve;
    }));

    const { default: AuthCallback } = await import('./AuthCallback');
    const view = render(<AuthCallback />);

    view.unmount();
    resolveSession?.({ data: { session: null } });
    await Promise.resolve();

    expect(mockClearBrowserAuthState).not.toHaveBeenCalled();
  });

  it('ignores a valid session that resolves only after the callback component unmounts', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-late-unmount', 'signature');
    let resolveSession: ((value: { data: { session: { access_token: string; user: { id: string; email: string } } } }) => void) | undefined;
    mockGetSession.mockReturnValue(new Promise((resolve) => {
      resolveSession = resolve;
    }));

    const { default: AuthCallback } = await import('./AuthCallback');
    const view = render(<AuthCallback />);

    view.unmount();
    resolveSession?.({
      data: {
        session: {
          access_token: accessToken,
          user: { id: 'user-late', email: 'late@example.com' },
        },
      },
    });
    await Promise.resolve();
    await Promise.resolve();

    expect(mockGetAdminMe).not.toHaveBeenCalledWith(accessToken);
    expect(mockSaveBrowserAdminProfile).not.toHaveBeenCalledWith({
      id: 'user-late',
      email: 'late@example.com',
    });
  });
});

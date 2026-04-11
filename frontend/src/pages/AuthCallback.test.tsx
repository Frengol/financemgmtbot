import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockGetSession = vi.fn();
const mockOnAuthStateChange = vi.fn();
const mockClearBrowserAuthState = vi.fn();
const mockSaveBrowserAdminTestSession = vi.fn();
const mockClearBrowserAdminLoginNotice = vi.fn();
const mockClearBrowserAdminTestSession = vi.fn();
const mockBrowserAdminAuthTestModeEnabled = vi.fn();
const mockEmitClientTelemetry = vi.fn();

function buildJwtLikeToken(...segments: string[]) {
  return segments.join('.');
}

vi.mock('@/features/auth/lib/supabaseBrowserSession', () => ({
  clearBrowserAuthState: (...args: unknown[]) => mockClearBrowserAuthState(...args),
  supabase: {
    auth: {
      getSession: (...args: unknown[]) => mockGetSession(...args),
      onAuthStateChange: (...args: unknown[]) => mockOnAuthStateChange(...args),
    },
  },
}));

vi.mock('@/features/auth/lib/browserState', async () => {
  const actual = await vi.importActual<typeof import('@/features/auth/lib/browserState')>('@/features/auth/lib/browserState');
  return {
    ...actual,
    browserAdminAuthTestModeEnabled: (...args: unknown[]) => mockBrowserAdminAuthTestModeEnabled(...args),
    clearBrowserAdminLoginNotice: (...args: unknown[]) => mockClearBrowserAdminLoginNotice(...args),
    clearBrowserAdminTestSession: (...args: unknown[]) => mockClearBrowserAdminTestSession(...args),
    saveBrowserAdminTestSession: (...args: unknown[]) => mockSaveBrowserAdminTestSession(...args),
  };
});

vi.mock('@/features/observability/clientTelemetry', () => ({
  emitClientTelemetry: (...args: unknown[]) => mockEmitClientTelemetry(...args),
  ensureSupportCodeInMessage: (message: string, clientEventId?: string) =>
    clientEventId && !/codigo de suporte:/i.test(message)
      ? `${message} Codigo de suporte: ${clientEventId}`
      : message,
}));

describe('AuthCallback', () => {
  beforeEach(() => {
    vi.resetModules();
    mockGetSession.mockReset();
    mockOnAuthStateChange.mockReset();
    mockClearBrowserAuthState.mockReset();
    mockSaveBrowserAdminTestSession.mockReset();
    mockClearBrowserAdminLoginNotice.mockReset();
    mockClearBrowserAdminTestSession.mockReset();
    mockBrowserAdminAuthTestModeEnabled.mockReset();
    mockEmitClientTelemetry.mockReset();

    mockBrowserAdminAuthTestModeEnabled.mockReturnValue(false);
    mockClearBrowserAuthState.mockResolvedValue(undefined);
    mockGetSession.mockResolvedValue({ data: { session: null } });
    mockOnAuthStateChange.mockReturnValue({
      data: {
        subscription: {
          unsubscribe: vi.fn(),
        },
      },
    });
    mockEmitClientTelemetry.mockReturnValue('cli_callback_failure_1');
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
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
  });

  it('surfaces non-expired upstream callback failures without hiding the message', async () => {
    window.history.pushState({}, '', '/auth/callback#error=server_error&error_description=Temporary+provider+failure');

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    expect(await screen.findByText(/temporary provider failure/i)).toBeInTheDocument();
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
    expect(replaceSpy).toHaveBeenCalledWith(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
  });

  it('redirects home when a valid Supabase browser session already exists', async () => {
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
      expect(mockClearBrowserAdminLoginNotice).toHaveBeenCalled();
    });
    expect(mockClearBrowserAdminTestSession).toHaveBeenCalled();
    expect(replaceSpy).toHaveBeenCalledWith(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
  });

  it('accepts a session that arrives later through onAuthStateChange', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload-late', 'signature');
    let authStateHandler:
      | ((event: string, session: { access_token?: string } | null) => void)
      | undefined;
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
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

    act(() => {
      authStateHandler?.('SIGNED_IN', { access_token: accessToken });
    });

    await waitFor(() => {
      expect(replaceSpy).toHaveBeenCalledWith(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
    });
  });

  it('shows a retry-the-link error when the persisted session is malformed', async () => {
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: 'not-a-jwt',
        },
      },
    });
    mockEmitClientTelemetry.mockReturnValue('cli_invalid_session_1');

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    expect(await screen.findByText(/solicite um novo magic link/i)).toBeInTheDocument();
    expect(screen.getByText(/codigo de suporte: cli_invalid_session_1/i)).toBeInTheDocument();
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
    expect(mockEmitClientTelemetry).toHaveBeenCalledWith(expect.objectContaining({
      event: 'auth_callback_failed',
      phase: 'callback_session_resolution',
      diagnostic: 'session_store_invalid',
    }));
  });

  it('shows a retry-the-link error when the session never appears after the callback', async () => {
    vi.useFakeTimers();

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText(/solicite um novo magic link/i)).toBeInTheDocument();
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
  });

  it('returns to the login screen after an unrecoverable callback failure', async () => {
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: 'not-a-jwt',
        },
      },
    });
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });

    const { default: AuthCallback } = await import('./AuthCallback');
    render(<AuthCallback />);

    fireEvent.click(await screen.findByRole('button', { name: /voltar para o login/i }));

    await waitFor(() => {
      expect(replaceSpy).toHaveBeenCalledWith(new URL('login', new URL(import.meta.env.BASE_URL, window.location.origin)).toString());
    });
  });
});

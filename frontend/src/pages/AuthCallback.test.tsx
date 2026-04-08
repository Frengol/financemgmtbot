import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

function buildJwtLikeToken(...segments: string[]) {
  return segments.join('.');
}

const mockSetSession = vi.fn();
const mockExchangeCodeForSession = vi.fn();
const mockGetSession = vi.fn();
const mockClearBrowserAuthState = vi.fn();
const mockSaveBrowserAdminProfile = vi.fn();
const mockSaveBrowserAdminTestSession = vi.fn();
const mockClearBrowserAdminProfile = vi.fn();
const mockClearBrowserAdminTestSession = vi.fn();
const mockDecodeAccessTokenIdentity = vi.fn();
const mockLoadBrowserAdminTestSession = vi.fn();

vi.mock('@/lib/supabase', () => ({
  clearBrowserAuthState: (...args: unknown[]) => mockClearBrowserAuthState(...args),
  supabase: {
    auth: {
      setSession: (...args: unknown[]) => mockSetSession(...args),
      exchangeCodeForSession: (...args: unknown[]) => mockExchangeCodeForSession(...args),
      getSession: (...args: unknown[]) => mockGetSession(...args),
    },
  },
}));

vi.mock('@/lib/auth', async () => {
  const actual = await vi.importActual<typeof import('@/lib/auth')>('@/lib/auth');
  return {
    ...actual,
    saveBrowserAdminProfile: (...args: unknown[]) => mockSaveBrowserAdminProfile(...args),
    saveBrowserAdminTestSession: (...args: unknown[]) => mockSaveBrowserAdminTestSession(...args),
    clearBrowserAdminProfile: (...args: unknown[]) => mockClearBrowserAdminProfile(...args),
    clearBrowserAdminTestSession: (...args: unknown[]) => mockClearBrowserAdminTestSession(...args),
    decodeAccessTokenIdentity: (...args: unknown[]) => mockDecodeAccessTokenIdentity(...args),
    loadBrowserAdminTestSession: (...args: unknown[]) => mockLoadBrowserAdminTestSession(...args),
  };
});

describe('AuthCallback', () => {
  beforeEach(() => {
    mockSetSession.mockReset();
    mockExchangeCodeForSession.mockReset();
    mockGetSession.mockReset();
    mockClearBrowserAuthState.mockReset();
    mockSaveBrowserAdminProfile.mockReset();
    mockSaveBrowserAdminTestSession.mockReset();
    mockClearBrowserAdminProfile.mockReset();
    mockClearBrowserAdminTestSession.mockReset();
    mockDecodeAccessTokenIdentity.mockReset();
    mockLoadBrowserAdminTestSession.mockReset();
    mockGetSession.mockResolvedValue({ data: { session: null } });
    mockLoadBrowserAdminTestSession.mockReturnValue(null);
    window.history.pushState(
      {},
      '',
      `/auth/callback#access_token=${buildJwtLikeToken('header-segment', 'payload-segment-1', 'signature-segment')}&refresh_token=refresh-1&type=magiclink`,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('consumes the upstream tokens, stores the session and redirects to the app root', async () => {
    const accessToken = buildJwtLikeToken('header-segment', 'payload-segment-2', 'signature-segment');
    window.history.pushState({}, '', `/auth/callback#access_token=${accessToken}&refresh_token=refresh-1&type=magiclink`);
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    mockSetSession.mockResolvedValue({ data: {}, error: null });
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: {
            id: 'user-1',
            email: 'admin@example.com',
          },
        },
      },
    });
    mockDecodeAccessTokenIdentity.mockReturnValue({ id: 'user-1', email: 'admin@example.com' });

    const { default: AuthCallback } = await import('./AuthCallback');

    render(<AuthCallback />);

    await waitFor(() => {
      expect(mockSetSession).toHaveBeenCalledWith({
        access_token: accessToken,
        refresh_token: 'refresh-1',
      });
    });
    expect(mockSaveBrowserAdminProfile).toHaveBeenCalledWith({ id: 'user-1', email: 'admin@example.com' });
    expect(replaceSpy).toHaveBeenCalledWith(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
  });

  it('shows an explicit error when the upstream link is invalid or expired', async () => {
    window.history.pushState({}, '', '/auth/callback#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired');

    const { default: AuthCallback } = await import('./AuthCallback');

    render(<AuthCallback />);

    expect(await screen.findByText(/link de acesso invalido ou expirado/i)).toBeInTheDocument();
    expect(mockSetSession).not.toHaveBeenCalled();
    expect(mockClearBrowserAdminProfile).toHaveBeenCalled();
    expect(mockClearBrowserAdminTestSession).toHaveBeenCalled();
    expect(window.location.hash).toContain('otp_expired');
  });

  it('shows an explicit error when the callback does not contain usable tokens', async () => {
    window.history.pushState({}, '', '/auth/callback');

    const { default: AuthCallback } = await import('./AuthCallback');

    render(<AuthCallback />);

    expect(await screen.findByText(/nao foi possivel concluir o login/i)).toBeInTheDocument();
    expect(mockSetSession).not.toHaveBeenCalled();
  });

  it('exchanges query code callbacks for a browser session and redirects to the app root', async () => {
    window.history.pushState({}, '', '/auth/callback?code=pkce-code-1');
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    const accessToken = buildJwtLikeToken('header-segment', 'payload-segment-code', 'signature-segment');
    mockExchangeCodeForSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: {
            id: 'user-1',
            email: 'admin@example.com',
          },
        },
      },
      error: null,
    });
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: {
            id: 'user-1',
            email: 'admin@example.com',
          },
        },
      },
    });
    mockDecodeAccessTokenIdentity.mockReturnValue({ id: 'user-1', email: 'admin@example.com' });

    const { default: AuthCallback } = await import('./AuthCallback');

    render(<AuthCallback />);

    await waitFor(() => {
      expect(mockExchangeCodeForSession).toHaveBeenCalledWith('pkce-code-1');
    });
    expect(mockSetSession).not.toHaveBeenCalled();
    expect(mockSaveBrowserAdminProfile).toHaveBeenCalledWith({ id: 'user-1', email: 'admin@example.com' });
    expect(replaceSpy).toHaveBeenCalledWith(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
  });

  it('shows an explicit error when a query-based callback cannot exchange the session', async () => {
    window.history.pushState({}, '', '/auth/callback?code=expired-code');
    mockExchangeCodeForSession.mockResolvedValue({
      data: { session: null },
      error: { message: 'invalid flow state' },
    });

    const { default: AuthCallback } = await import('./AuthCallback');

    render(<AuthCallback />);

    expect(await screen.findByText(/nao foi possivel concluir o login/i)).toBeInTheDocument();
    expect(mockSetSession).not.toHaveBeenCalled();
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
  });

  it('shows a short diagnostic when the exchanged session cannot be persisted safely', async () => {
    window.history.pushState({}, '', '/auth/callback?code=pkce-code-invalid');
    mockExchangeCodeForSession.mockResolvedValue({
      data: {
        session: {
          access_token: buildJwtLikeToken('header-segment', 'payload-segment-code-invalid', 'signature-segment'),
          user: {
            id: 'user-1',
            email: 'admin@example.com',
          },
        },
      },
      error: null,
    });
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: 'not-a-jwt',
          user: {
            id: 'user-1',
            email: 'admin@example.com',
          },
        },
      },
    });

    const { default: AuthCallback } = await import('./AuthCallback');

    render(<AuthCallback />);

    expect(await screen.findByText(/diagnostico: session_store_invalid/i)).toBeInTheDocument();
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
  });

  it('stores a minimal browser auth profile derived from the access token claims', async () => {
    const payload = btoa(JSON.stringify({
      sub: 'user-1',
      email: 'admin@example.com',
      exp: 9999999999,
    }))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/g, '');
    window.history.pushState(
      {},
      '',
      `/auth/callback?user_id=user-1&email=admin%40example.com#access_token=header.${payload}.sig&refresh_token=refresh-1&type=magiclink`,
    );
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    mockSetSession.mockResolvedValue({ data: {}, error: null });
    mockDecodeAccessTokenIdentity.mockReturnValue(null);

    const { default: AuthCallback } = await import('./AuthCallback');

    render(<AuthCallback />);

    await waitFor(() => {
      expect(mockSaveBrowserAdminProfile).toHaveBeenCalledWith({
        id: 'user-1',
        email: 'admin@example.com',
      });
    });
    expect(mockSaveBrowserAdminTestSession).toHaveBeenCalledWith({
      accessToken: `header.${payload}.sig`,
      refreshToken: 'refresh-1',
      user: {
        id: 'user-1',
        email: 'admin@example.com',
      },
    });
    expect(mockSetSession).not.toHaveBeenCalled();
  });

  it('reuses an existing browser auth test session when the callback effect is replayed without hash tokens', async () => {
    window.history.pushState({}, '', '/auth/callback');
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    mockLoadBrowserAdminTestSession.mockReturnValue({
      accessToken: buildJwtLikeToken('header-segment', 'payload-segment-4', 'signature-segment'),
      refreshToken: 'existing-auth-test-refresh',
      user: {
        id: 'user-1',
        email: 'admin@example.com',
      },
    });

    const { default: AuthCallback } = await import('./AuthCallback');

    render(<AuthCallback />);

    await waitFor(() => {
      expect(replaceSpy).toHaveBeenCalledWith(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
    });
    expect(mockClearBrowserAdminTestSession).not.toHaveBeenCalled();
    expect(mockSetSession).not.toHaveBeenCalled();
  });

  it('reuses an existing Supabase browser session when the callback reloads without tokens', async () => {
    window.history.pushState({}, '', '/auth/callback?email=admin%40example.com');
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    const accessToken = buildJwtLikeToken('header-segment', 'payload-segment-existing', 'signature-segment');
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: accessToken,
          user: {
            id: 'user-1',
            email: 'admin@example.com',
          },
        },
      },
    });

    const { default: AuthCallback } = await import('./AuthCallback');

    render(<AuthCallback />);

    await waitFor(() => {
      expect(mockSaveBrowserAdminProfile).toHaveBeenCalledWith({ id: 'user-1', email: 'admin@example.com' });
    });
    expect(replaceSpy).toHaveBeenCalledWith(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
    expect(mockClearBrowserAdminTestSession).not.toHaveBeenCalled();
  });

  it('shows a diagnostic when an existing persisted session is unusable during callback replay', async () => {
    window.history.pushState({}, '', '/auth/callback?email=admin%40example.com');
    mockGetSession.mockResolvedValue({
      data: {
        session: {
          access_token: 'not-a-jwt',
          user: {
            id: 'user-1',
            email: 'admin@example.com',
          },
        },
      },
    });

    const { default: AuthCallback } = await import('./AuthCallback');

    render(<AuthCallback />);

    expect(await screen.findByText(/diagnostico: auth_state_unusable/i)).toBeInTheDocument();
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
  });
});

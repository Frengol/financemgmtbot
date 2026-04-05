import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockSetSession = vi.fn();
const mockSaveBrowserAdminProfile = vi.fn();
const mockSaveBrowserAdminTestSession = vi.fn();
const mockClearBrowserAdminProfile = vi.fn();
const mockClearBrowserAdminTestSession = vi.fn();
const mockDecodeAccessTokenIdentity = vi.fn();

vi.mock('@/lib/supabase', () => ({
  supabase: {
    auth: {
      setSession: (...args: unknown[]) => mockSetSession(...args),
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
  };
});

describe('AuthCallback', () => {
  beforeEach(() => {
    mockSetSession.mockReset();
    mockSaveBrowserAdminProfile.mockReset();
    mockSaveBrowserAdminTestSession.mockReset();
    mockClearBrowserAdminProfile.mockReset();
    mockClearBrowserAdminTestSession.mockReset();
    mockDecodeAccessTokenIdentity.mockReset();
    window.history.pushState({}, '', '/auth/callback#access_token=token-1&refresh_token=refresh-1&type=magiclink');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('consumes the upstream tokens, stores the session and redirects to the app root', async () => {
    window.history.pushState({}, '', '/auth/callback#access_token=token-1&refresh_token=refresh-1&type=magiclink');
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    mockSetSession.mockResolvedValue({ data: {}, error: null });
    mockDecodeAccessTokenIdentity.mockReturnValue({ id: 'user-1', email: 'admin@example.com' });

    const { default: AuthCallback } = await import('./AuthCallback');

    render(<AuthCallback />);

    await waitFor(() => {
      expect(mockSetSession).toHaveBeenCalledWith({
        access_token: 'token-1',
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
  });

  it('shows an explicit error when the callback does not contain usable tokens', async () => {
    window.history.pushState({}, '', '/auth/callback');

    const { default: AuthCallback } = await import('./AuthCallback');

    render(<AuthCallback />);

    expect(await screen.findByText(/nao foi possivel concluir o login/i)).toBeInTheDocument();
    expect(mockSetSession).not.toHaveBeenCalled();
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
});

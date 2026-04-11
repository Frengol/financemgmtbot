import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockCreateClient = vi.fn();
const mockGetSession = vi.fn();
const mockLoadBrowserAdminTestSession = vi.fn();
const mockSignOut = vi.fn();
const mockClearBrowserAdminArtifacts = vi.fn();
const mockBrowserAdminAuthTestModeEnabled = vi.fn();

function buildJwtLikeToken(...segments: string[]) {
  return segments.join('.');
}

vi.mock('@supabase/supabase-js', () => ({
  createClient: (...args: unknown[]) => mockCreateClient(...args),
}));

vi.mock('@/features/auth/lib/browserState', () => ({
  browserAdminAuthTestModeEnabled: (...args: unknown[]) => mockBrowserAdminAuthTestModeEnabled(...args),
  clearBrowserAdminArtifacts: (...args: unknown[]) => mockClearBrowserAdminArtifacts(...args),
  isJwtShapeValid: (token?: string | null) => typeof token === 'string' && token.split('.').length === 3,
  loadBrowserAdminTestSession: (...args: unknown[]) => mockLoadBrowserAdminTestSession(...args),
}));

describe('supabase helpers', () => {
  beforeEach(() => {
    vi.resetModules();
    mockCreateClient.mockReset();
    mockGetSession.mockReset();
    mockLoadBrowserAdminTestSession.mockReset();
    mockSignOut.mockReset();
    mockClearBrowserAdminArtifacts.mockReset();
    mockBrowserAdminAuthTestModeEnabled.mockReset();
    mockBrowserAdminAuthTestModeEnabled.mockReturnValue(false);
    mockCreateClient.mockReturnValue({
      auth: {
        getSession: (...args: unknown[]) => mockGetSession(...args),
        signOut: (...args: unknown[]) => mockSignOut(...args),
      },
    });
    mockGetSession.mockResolvedValue({ data: { session: null } });
    mockLoadBrowserAdminTestSession.mockReturnValue(null);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    window.localStorage.clear();
  });

  it('creates the client with the official browser auth configuration', async () => {
    vi.stubEnv('VITE_SUPABASE_URL', 'https://your-project-ref.supabase.co/ ');
    vi.stubEnv('VITE_SUPABASE_ANON_KEY', ' public-anon-key ');

    await import('@/features/auth/lib/supabaseBrowserSession');

    expect(mockCreateClient).toHaveBeenCalledWith(
      'https://your-project-ref.supabase.co',
      'public-anon-key',
      {
        auth: {
          autoRefreshToken: true,
          detectSessionInUrl: true,
          flowType: 'pkce',
          persistSession: true,
          storageKey: 'financemgmtbot-admin-auth-v2',
        },
      },
    );
  });

  it('prefers the auth test session only when auth test mode is enabled', async () => {
    mockBrowserAdminAuthTestModeEnabled.mockReturnValue(true);
    mockLoadBrowserAdminTestSession.mockReturnValue({
      accessToken: 'test-access-token',
      user: { id: 'user-1', email: 'admin@example.com' },
    });

    const { getAccessToken } = await import('@/features/auth/lib/supabaseBrowserSession');

    await expect(getAccessToken()).resolves.toBe('test-access-token');
    expect(mockGetSession).not.toHaveBeenCalled();
  });

  it('falls back to the persisted Supabase browser session in production runtimes', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload', 'signature');
    mockGetSession.mockResolvedValueOnce({
      data: {
        session: {
          access_token: accessToken,
        },
      },
    });

    const { getAccessToken } = await import('@/features/auth/lib/supabaseBrowserSession');

    await expect(getAccessToken()).resolves.toBe(accessToken);
    expect(mockGetSession).toHaveBeenCalledTimes(1);
  });

  it('returns null when there is no cached token, no auth test session and no persisted Supabase session', async () => {
    mockGetSession.mockResolvedValueOnce({ data: { session: null } });

    const { getAccessToken } = await import('@/features/auth/lib/supabaseBrowserSession');

    await expect(getAccessToken()).resolves.toBeNull();
    expect(mockGetSession).toHaveBeenCalledTimes(1);
  });

  it('reuses the cached browser access token before touching Supabase again', async () => {
    const accessToken = buildJwtLikeToken('header', 'payload', 'signature');
    const { getAccessToken, setCachedBrowserAccessToken } = await import('@/features/auth/lib/supabaseBrowserSession');

    setCachedBrowserAccessToken(accessToken);

    await expect(getAccessToken()).resolves.toBe(accessToken);
    expect(mockGetSession).not.toHaveBeenCalled();
  });

  it('clears malformed persisted sessions instead of returning them', async () => {
    mockGetSession.mockResolvedValueOnce({
      data: {
        session: {
          access_token: 'not-a-jwt',
        },
      },
    });

    const { getAccessToken } = await import('@/features/auth/lib/supabaseBrowserSession');

    await expect(getAccessToken()).resolves.toBeNull();
    expect(mockClearBrowserAdminArtifacts).toHaveBeenCalledTimes(1);
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });

  it('purges the v1 and v2 browser storage keys when clearing auth state', async () => {
    window.localStorage.setItem('financemgmtbot-admin-auth', '{"access_token":"stale-v1"}');
    window.localStorage.setItem('financemgmtbot-admin-auth-v2', '{"access_token":"stale-v2"}');

    const { clearBrowserAuthState } = await import('@/features/auth/lib/supabaseBrowserSession');

    await clearBrowserAuthState();

    expect(window.localStorage.getItem('financemgmtbot-admin-auth')).toBeNull();
    expect(window.localStorage.getItem('financemgmtbot-admin-auth-v2')).toBeNull();
    expect(mockClearBrowserAdminArtifacts).toHaveBeenCalledTimes(1);
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });

  it('still clears local browser state when Supabase signOut itself fails', async () => {
    window.localStorage.setItem('financemgmtbot-admin-auth', '{"access_token":"stale-v1"}');
    window.localStorage.setItem('financemgmtbot-admin-auth-v2', '{"access_token":"stale-v2"}');
    mockSignOut.mockRejectedValueOnce(new Error('signout failed'));

    const { clearBrowserAuthState } = await import('@/features/auth/lib/supabaseBrowserSession');

    await clearBrowserAuthState();

    expect(window.localStorage.getItem('financemgmtbot-admin-auth')).toBeNull();
    expect(window.localStorage.getItem('financemgmtbot-admin-auth-v2')).toBeNull();
    expect(mockClearBrowserAdminArtifacts).toHaveBeenCalledTimes(1);
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });
});

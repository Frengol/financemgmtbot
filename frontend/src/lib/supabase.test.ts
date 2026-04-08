import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockCreateClient = vi.fn();
const mockGetSession = vi.fn();
const mockLoadBrowserAdminTestSession = vi.fn();
const mockSignOut = vi.fn();
const mockClearBrowserAdminArtifacts = vi.fn();
const mockBrowserAdminTestSessionAllowed = vi.fn();

function buildJwtLikeToken(...segments: string[]) {
  return segments.join('.');
}

vi.mock('@supabase/supabase-js', () => ({
  createClient: (...args: unknown[]) => mockCreateClient(...args),
}));

vi.mock('@/lib/auth', () => ({
  browserAdminTestSessionAllowed: (...args: unknown[]) => mockBrowserAdminTestSessionAllowed(...args),
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
    mockBrowserAdminTestSessionAllowed.mockReset();
    mockBrowserAdminTestSessionAllowed.mockReturnValue(true);
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

  it('creates the client with trimmed configured values', async () => {
    vi.stubEnv('VITE_SUPABASE_URL', 'https://your-project-ref.supabase.co/ ');
    vi.stubEnv('VITE_SUPABASE_ANON_KEY', ' public-anon-key ');

    await import('./supabase');

    expect(mockCreateClient).toHaveBeenCalledWith(
      'https://your-project-ref.supabase.co',
      'public-anon-key',
      {
        auth: {
          autoRefreshToken: true,
          detectSessionInUrl: false,
          persistSession: true,
          storageKey: 'financemgmtbot-admin-auth',
        },
      },
    );
  });

  it('falls back to the local defaults when build env vars are absent', async () => {
    vi.stubEnv('VITE_SUPABASE_URL', '');
    vi.stubEnv('VITE_SUPABASE_ANON_KEY', '');

    await import('./supabase');

    expect(mockCreateClient).toHaveBeenCalledWith(
      'http://127.0.0.1:54321',
      'public-anon-key-for-local-tests',
      expect.any(Object),
    );
  });

  it('prefers the browser auth test session access token when present', async () => {
    mockLoadBrowserAdminTestSession.mockReturnValue({
      accessToken: 'test-access-token',
      user: { id: 'user-1', email: 'admin@example.com' },
    });

    const { getAccessToken } = await import('./supabase');

    await expect(getAccessToken()).resolves.toBe('test-access-token');
    expect(mockGetSession).not.toHaveBeenCalled();
  });

  it('falls back to the Supabase browser session token and then null', async () => {
    const accessToken = buildJwtLikeToken('header-segment', 'payload-segment-1', 'signature-segment');
    mockGetSession.mockResolvedValueOnce({
      data: {
        session: {
          access_token: accessToken,
        },
      },
    });

    const { getAccessToken } = await import('./supabase');

    await expect(getAccessToken()).resolves.toBe(accessToken);

    mockGetSession.mockResolvedValueOnce({ data: { session: null } });
    await expect(getAccessToken()).resolves.toBeNull();
  });

  it('ignores the browser auth test session outside of loopback runtimes', async () => {
    mockBrowserAdminTestSessionAllowed.mockReturnValue(false);
    mockLoadBrowserAdminTestSession.mockReturnValue({
      accessToken: buildJwtLikeToken('header-segment', 'payload-segment-loopback', 'signature-segment'),
      user: { id: 'user-1', email: 'admin@example.com' },
    });
    mockGetSession.mockResolvedValueOnce({
      data: {
        session: {
          access_token: buildJwtLikeToken('header-segment', 'payload-segment-pages', 'signature-segment'),
        },
      },
    });

    const { getAccessToken } = await import('./supabase');

    await expect(getAccessToken()).resolves.toBe(buildJwtLikeToken('header-segment', 'payload-segment-pages', 'signature-segment'));
    expect(mockGetSession).toHaveBeenCalledTimes(1);
  });

  it('clears a malformed persisted Supabase session token instead of returning it', async () => {
    mockGetSession.mockResolvedValueOnce({
      data: {
        session: {
          access_token: 'not-a-jwt',
        },
      },
    });

    const { getAccessToken } = await import('./supabase');

    await expect(getAccessToken()).resolves.toBeNull();
    expect(mockClearBrowserAdminArtifacts).toHaveBeenCalledTimes(1);
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });

  it('purges the persisted Supabase browser storage key when clearing auth state', async () => {
    window.localStorage.setItem('financemgmtbot-admin-auth', '{"access_token":"stale"}');

    const { clearBrowserAuthState } = await import('./supabase');

    await clearBrowserAuthState();

    expect(window.localStorage.getItem('financemgmtbot-admin-auth')).toBeNull();
    expect(mockClearBrowserAdminArtifacts).toHaveBeenCalledTimes(1);
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });
});

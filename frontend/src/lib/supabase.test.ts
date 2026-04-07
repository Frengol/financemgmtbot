import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockCreateClient = vi.fn();
const mockGetSession = vi.fn();
const mockLoadBrowserAdminTestSession = vi.fn();

vi.mock('@supabase/supabase-js', () => ({
  createClient: (...args: unknown[]) => mockCreateClient(...args),
}));

vi.mock('@/lib/auth', () => ({
  loadBrowserAdminTestSession: (...args: unknown[]) => mockLoadBrowserAdminTestSession(...args),
}));

describe('supabase helpers', () => {
  beforeEach(() => {
    vi.resetModules();
    mockCreateClient.mockReset();
    mockGetSession.mockReset();
    mockLoadBrowserAdminTestSession.mockReset();
    mockCreateClient.mockReturnValue({
      auth: {
        getSession: (...args: unknown[]) => mockGetSession(...args),
      },
    });
    mockGetSession.mockResolvedValue({ data: { session: null } });
    mockLoadBrowserAdminTestSession.mockReturnValue(null);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
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
    mockGetSession.mockResolvedValueOnce({
      data: {
        session: {
          access_token: 'session-access-token',
        },
      },
    });

    const { getAccessToken } = await import('./supabase');

    await expect(getAccessToken()).resolves.toBe('session-access-token');

    mockGetSession.mockResolvedValueOnce({ data: { session: null } });
    await expect(getAccessToken()).resolves.toBeNull();
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('isAllowedAdminEmail', () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('allows any e-mail when no allowlist is configured', async () => {
    vi.stubEnv('VITE_ALLOWED_ADMIN_EMAILS', '');
    const { isAllowedAdminEmail } = await import('./auth');

    expect(isAllowedAdminEmail('admin@example.com')).toBe(true);
    expect(isAllowedAdminEmail()).toBe(true);
  });

  it('enforces the configured allowlist in a case-insensitive way', async () => {
    vi.stubEnv('VITE_ALLOWED_ADMIN_EMAILS', 'admin@example.com,finance@example.com');
    const { isAllowedAdminEmail } = await import('./auth');

    expect(isAllowedAdminEmail('ADMIN@example.com')).toBe(true);
    expect(isAllowedAdminEmail('blocked@example.com')).toBe(false);
    expect(isAllowedAdminEmail()).toBe(false);
  });

  it('decodes access token identities and ignores malformed payloads', async () => {
    const { decodeAccessTokenIdentity } = await import('./auth');
    const payload = btoa(JSON.stringify({ sub: 'user-1', email: 'admin@example.com' }))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/g, '');

    expect(decodeAccessTokenIdentity(`header.${payload}.signature`)).toEqual({
      id: 'user-1',
      email: 'admin@example.com',
    });
    expect(decodeAccessTokenIdentity()).toBeNull();
    expect(decodeAccessTokenIdentity('not-a-jwt')).toBeNull();

    const noSubjectPayload = btoa(JSON.stringify({ email: 'admin@example.com' }))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/g, '');
    expect(decodeAccessTokenIdentity(`header.${noSubjectPayload}.signature`)).toBeNull();
    expect(decodeAccessTokenIdentity('header.invalid-json.signature')).toBeNull();
  });

  it('falls back to Buffer decoding and gracefully handles environments without window', async () => {
    const {
      decodeAccessTokenIdentity,
      loadBrowserAdminProfile,
      loadBrowserAdminTestSession,
      saveBrowserAdminProfile,
      clearBrowserAdminProfile,
      saveBrowserAdminTestSession,
      clearBrowserAdminTestSession,
    } = await import('./auth');
    const originalAtob = window.atob;
    Object.defineProperty(window, 'atob', {
      configurable: true,
      value: undefined,
    });

    const payload = Buffer.from(JSON.stringify({ sub: 'user-buffer', email: 'buffer@example.com' }), 'utf-8')
      .toString('base64')
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/g, '');
    expect(decodeAccessTokenIdentity(`header.${payload}.signature`)).toEqual({
      id: 'user-buffer',
      email: 'buffer@example.com',
    });

    vi.stubGlobal('window', undefined);
    expect(loadBrowserAdminProfile()).toBeNull();
    expect(loadBrowserAdminTestSession()).toBeNull();
    saveBrowserAdminProfile({ id: 'ignored-user', email: 'ignored@example.com' });
    clearBrowserAdminProfile();
    saveBrowserAdminTestSession({
      accessToken: 'ignored-token',
      user: { id: 'ignored-user', email: 'ignored@example.com' },
    });
    clearBrowserAdminTestSession();

    vi.stubGlobal('Buffer', undefined);
    expect(decodeAccessTokenIdentity(`header.${payload}.signature`)).toBeNull();

    vi.unstubAllGlobals();
    Object.defineProperty(window, 'atob', {
      configurable: true,
      value: originalAtob,
    });
  });

  it('persists and clears the browser admin profile safely', async () => {
    const {
      saveBrowserAdminProfile,
      loadBrowserAdminProfile,
      clearBrowserAdminProfile,
    } = await import('./auth');

    saveBrowserAdminProfile({ id: 'user-1', email: 'admin@example.com' });
    expect(loadBrowserAdminProfile()).toEqual({ id: 'user-1', email: 'admin@example.com' });

    window.localStorage.setItem('financemgmtbot-admin-profile', '{"email":"missing-id"}');
    expect(loadBrowserAdminProfile()).toBeNull();

    window.localStorage.setItem('financemgmtbot-admin-profile', '{bad-json');
    expect(loadBrowserAdminProfile()).toBeNull();

    saveBrowserAdminProfile(null);
    expect(window.localStorage.getItem('financemgmtbot-admin-profile')).toBeNull();

    saveBrowserAdminProfile({ id: 'user-2', email: null });
    clearBrowserAdminProfile();
    expect(window.localStorage.getItem('financemgmtbot-admin-profile')).toBeNull();
  });

  it('persists and clears the browser auth test session safely', async () => {
    const {
      saveBrowserAdminTestSession,
      loadBrowserAdminTestSession,
      clearBrowserAdminTestSession,
    } = await import('./auth');

    saveBrowserAdminTestSession({
      accessToken: 'token-1',
      refreshToken: 'refresh-1',
      user: {
        id: 'user-1',
        email: 'admin@example.com',
      },
    });
    expect(loadBrowserAdminTestSession()).toEqual({
      accessToken: 'token-1',
      refreshToken: 'refresh-1',
      user: {
        id: 'user-1',
        email: 'admin@example.com',
      },
    });

    window.localStorage.setItem('financemgmtbot-admin-auth-test-session', '{"accessToken":"token-only"}');
    expect(loadBrowserAdminTestSession()).toBeNull();

    window.localStorage.setItem('financemgmtbot-admin-auth-test-session', '{bad-json');
    expect(loadBrowserAdminTestSession()).toBeNull();

    saveBrowserAdminTestSession(null);
    expect(window.localStorage.getItem('financemgmtbot-admin-auth-test-session')).toBeNull();

    saveBrowserAdminTestSession({
      accessToken: 'token-2',
      user: {
        id: 'user-2',
        email: null,
      },
    });
    clearBrowserAdminTestSession();
    expect(window.localStorage.getItem('financemgmtbot-admin-auth-test-session')).toBeNull();
  });

  it('treats invalid profile/session payloads as removals', async () => {
    const {
      saveBrowserAdminProfile,
      saveBrowserAdminTestSession,
    } = await import('./auth');

    saveBrowserAdminProfile({ id: '' as unknown as string, email: 'invalid@example.com' });
    expect(window.localStorage.getItem('financemgmtbot-admin-profile')).toBeNull();

    saveBrowserAdminTestSession({
      accessToken: '' as unknown as string,
      user: { id: 'user-3', email: 'admin@example.com' },
    });
    expect(window.localStorage.getItem('financemgmtbot-admin-auth-test-session')).toBeNull();
  });
});

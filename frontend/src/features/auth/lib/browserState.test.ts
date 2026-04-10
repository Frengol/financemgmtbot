import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

function buildJwtLikeToken(...segments: string[]) {
  return segments.join('.');
}

describe('isAllowedAdminEmail', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv('VITE_AUTH_TEST_MODE', 'true');
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it('allows any e-mail when no allowlist is configured', async () => {
    vi.stubEnv('VITE_ALLOWED_ADMIN_EMAILS', '');
    const { isAllowedAdminEmail } = await import('@/features/auth/lib/browserState');

    expect(isAllowedAdminEmail('admin@example.com')).toBe(true);
    expect(isAllowedAdminEmail()).toBe(true);
  });

  it('enforces the configured allowlist in a case-insensitive way', async () => {
    vi.stubEnv('VITE_ALLOWED_ADMIN_EMAILS', 'admin@example.com,finance@example.com');
    const { isAllowedAdminEmail } = await import('@/features/auth/lib/browserState');

    expect(isAllowedAdminEmail('ADMIN@example.com')).toBe(true);
    expect(isAllowedAdminEmail('blocked@example.com')).toBe(false);
    expect(isAllowedAdminEmail()).toBe(false);
  });

  it('decodes access token identities and ignores malformed payloads', async () => {
    const { decodeAccessTokenIdentity, isJwtShapeValid } = await import('@/features/auth/lib/browserState');
    const payload = btoa(JSON.stringify({ sub: 'user-1', email: 'admin@example.com' }))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/g, '');
    const validJwt = buildJwtLikeToken('header-segment', payload, 'signature-segment');

    expect(isJwtShapeValid(validJwt)).toBe(true);
    expect(decodeAccessTokenIdentity(validJwt)).toEqual({
      id: 'user-1',
      email: 'admin@example.com',
    });
    expect(decodeAccessTokenIdentity()).toBeNull();
    expect(decodeAccessTokenIdentity('not-a-jwt')).toBeNull();

    const noSubjectPayload = btoa(JSON.stringify({ email: 'admin@example.com' }))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/g, '');
    expect(decodeAccessTokenIdentity(buildJwtLikeToken('header-segment', noSubjectPayload, 'signature-segment'))).toBeNull();
    expect(decodeAccessTokenIdentity(buildJwtLikeToken('header-segment', 'invalid-json', 'signature-segment'))).toBeNull();
    expect(isJwtShapeValid('not-a-jwt')).toBe(false);
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
    } = await import('@/features/auth/lib/browserState');
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
    expect(decodeAccessTokenIdentity(buildJwtLikeToken('header-segment', payload, 'signature-segment'))).toEqual({
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
    expect(decodeAccessTokenIdentity(buildJwtLikeToken('header-segment', payload, 'signature-segment'))).toBeNull();

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
    } = await import('@/features/auth/lib/browserState');

    saveBrowserAdminProfile({ id: 'user-1', email: 'admin@example.com' });
    expect(loadBrowserAdminProfile()).toEqual({ id: 'user-1', email: 'admin@example.com' });

    window.localStorage.setItem('financemgmtbot-admin-profile-v2', '{"email":"missing-id"}');
    expect(loadBrowserAdminProfile()).toBeNull();

    window.localStorage.setItem('financemgmtbot-admin-profile-v2', '{bad-json');
    expect(loadBrowserAdminProfile()).toBeNull();

    saveBrowserAdminProfile(null);
    expect(window.localStorage.getItem('financemgmtbot-admin-profile-v2')).toBeNull();

    saveBrowserAdminProfile({ id: 'user-2', email: null });
    clearBrowserAdminProfile();
    expect(window.localStorage.getItem('financemgmtbot-admin-profile-v2')).toBeNull();
  });

  it('purges legacy profile and auth-test storage when the v2 keys are missing', async () => {
    const {
      loadBrowserAdminProfile,
      loadBrowserAdminTestSession,
    } = await import('@/features/auth/lib/browserState');

    window.localStorage.setItem('financemgmtbot-admin-profile', JSON.stringify({ id: 'legacy-user', email: 'legacy@example.com' }));
    window.localStorage.setItem('financemgmtbot-admin-auth-test-session', JSON.stringify({
      accessToken: buildJwtLikeToken('header-segment', 'payload-segment', 'signature-segment'),
      user: { id: 'legacy-user', email: 'legacy@example.com' },
    }));

    expect(loadBrowserAdminProfile()).toBeNull();
    expect(loadBrowserAdminTestSession()).toBeNull();
    expect(window.localStorage.getItem('financemgmtbot-admin-profile')).toBeNull();
    expect(window.localStorage.getItem('financemgmtbot-admin-auth-test-session')).toBeNull();
  });

  it('persists and clears the browser auth test session safely', async () => {
    const {
      saveBrowserAdminTestSession,
      loadBrowserAdminTestSession,
      clearBrowserAdminTestSession,
    } = await import('@/features/auth/lib/browserState');
    const validJwt = buildJwtLikeToken('header-segment', 'payload-segment', 'signature-segment');

    saveBrowserAdminTestSession({
      accessToken: validJwt,
      refreshToken: 'refresh-1',
      user: {
        id: 'user-1',
        email: 'admin@example.com',
      },
    });
    expect(loadBrowserAdminTestSession()).toEqual({
      accessToken: validJwt,
      refreshToken: 'refresh-1',
      user: {
        id: 'user-1',
        email: 'admin@example.com',
      },
    });

    window.localStorage.setItem('financemgmtbot-admin-auth-test-session-v2', '{"accessToken":"token-only"}');
    expect(loadBrowserAdminTestSession()).toBeNull();

    window.localStorage.setItem('financemgmtbot-admin-auth-test-session-v2', '{bad-json');
    expect(loadBrowserAdminTestSession()).toBeNull();

    saveBrowserAdminTestSession(null);
    expect(window.localStorage.getItem('financemgmtbot-admin-auth-test-session-v2')).toBeNull();

    saveBrowserAdminTestSession({
      accessToken: validJwt,
      user: {
        id: 'user-2',
        email: null,
      },
    });
    clearBrowserAdminTestSession();
    expect(window.localStorage.getItem('financemgmtbot-admin-auth-test-session-v2')).toBeNull();
  });

  it('treats invalid profile/session payloads as removals', async () => {
    const {
      saveBrowserAdminProfile,
      saveBrowserAdminTestSession,
    } = await import('@/features/auth/lib/browserState');

    saveBrowserAdminProfile({ id: '' as unknown as string, email: 'invalid@example.com' });
    expect(window.localStorage.getItem('financemgmtbot-admin-profile-v2')).toBeNull();

    saveBrowserAdminTestSession({
      accessToken: '' as unknown as string,
      user: { id: 'user-3', email: 'admin@example.com' },
    });
    expect(window.localStorage.getItem('financemgmtbot-admin-auth-test-session-v2')).toBeNull();
  });

  it('clears auth test session storage outside loopback runtimes', async () => {
    const {
      browserAdminTestSessionAllowed,
      loadBrowserAdminTestSession,
      saveBrowserAdminTestSession,
    } = await import('@/features/auth/lib/browserState');
    const originalWindow = window;
    const validJwt = buildJwtLikeToken('header-segment', 'payload-segment', 'signature-segment');

    vi.stubGlobal('window', {
      localStorage: originalWindow.localStorage,
      location: {
        hostname: 'frengol.github.io',
      },
    });

    expect(browserAdminTestSessionAllowed()).toBe(false);
    saveBrowserAdminTestSession({
      accessToken: validJwt,
      refreshToken: 'refresh-1',
      user: {
        id: 'user-1',
        email: 'admin@example.com',
      },
    });
    expect(loadBrowserAdminTestSession()).toBeNull();
    expect(originalWindow.localStorage.getItem('financemgmtbot-admin-auth-test-session-v2')).toBeNull();
  });

  it('purges legacy v1 browser auth storage as soon as the new runtime touches it', async () => {
    const {
      clearBrowserAdminArtifacts,
      loadBrowserAdminProfile,
      loadBrowserAdminTestSession,
      saveBrowserAdminProfile,
      saveBrowserAdminTestSession,
    } = await import('@/features/auth/lib/browserState');
    const validJwt = buildJwtLikeToken('header-segment', 'payload-segment', 'signature-segment');

    window.localStorage.setItem('financemgmtbot-admin-profile', JSON.stringify({ id: 'legacy-user', email: 'legacy@example.com' }));
    window.localStorage.setItem('financemgmtbot-admin-auth-test-session', JSON.stringify({
      accessToken: validJwt,
      user: { id: 'legacy-user', email: 'legacy@example.com' },
    }));

    saveBrowserAdminProfile({ id: 'user-v2', email: 'admin@example.com' });
    saveBrowserAdminTestSession({
      accessToken: validJwt,
      user: { id: 'user-v2', email: 'admin@example.com' },
    });

    expect(loadBrowserAdminProfile()).toEqual({ id: 'user-v2', email: 'admin@example.com' });
    expect(loadBrowserAdminTestSession()).toEqual({
      accessToken: validJwt,
      user: { id: 'user-v2', email: 'admin@example.com' },
    });
    expect(window.localStorage.getItem('financemgmtbot-admin-profile')).toBeNull();
    expect(window.localStorage.getItem('financemgmtbot-admin-auth-test-session')).toBeNull();

    clearBrowserAdminArtifacts();

    expect(window.localStorage.getItem('financemgmtbot-admin-profile-v2')).toBeNull();
    expect(window.localStorage.getItem('financemgmtbot-admin-auth-test-session-v2')).toBeNull();
  });

  it('clears browser admin artifacts safely even when no window is available', async () => {
    const { clearBrowserAdminArtifacts, browserAdminTestSessionAllowed } = await import('@/features/auth/lib/browserState');

    vi.stubGlobal('window', undefined);

    expect(browserAdminTestSessionAllowed()).toBe(false);
    expect(() => clearBrowserAdminArtifacts()).not.toThrow();
  });

  it('persists and clears short login notices safely', async () => {
    const {
      clearBrowserAdminLoginNotice,
      loadBrowserAdminLoginNotice,
      saveBrowserAdminLoginNotice,
    } = await import('@/features/auth/lib/browserState');

    saveBrowserAdminLoginNotice({ message: 'notice-1' });
    expect(loadBrowserAdminLoginNotice()).toEqual({ message: 'notice-1' });

    window.sessionStorage.setItem('financemgmtbot-admin-login-notice-v1', '{"missing":"message"}');
    expect(loadBrowserAdminLoginNotice()).toBeNull();

    window.sessionStorage.setItem('financemgmtbot-admin-login-notice-v1', '{bad-json');
    expect(loadBrowserAdminLoginNotice()).toBeNull();

    saveBrowserAdminLoginNotice(null);
    expect(window.sessionStorage.getItem('financemgmtbot-admin-login-notice-v1')).toBeNull();

    saveBrowserAdminLoginNotice({ message: 'notice-2' });
    clearBrowserAdminLoginNotice();
    expect(window.sessionStorage.getItem('financemgmtbot-admin-login-notice-v1')).toBeNull();
  });

  it('safely handles environments without window when touching auth test storage', async () => {
    const {
      browserAdminTestSessionAllowed,
      saveBrowserAdminTestSession,
    } = await import('@/features/auth/lib/browserState');
    const validJwt = buildJwtLikeToken('header-segment', 'payload-segment', 'signature-segment');

    vi.stubGlobal('window', undefined);
    expect(browserAdminTestSessionAllowed()).toBe(false);
    expect(() => saveBrowserAdminTestSession({
      accessToken: validJwt,
      user: { id: 'ignored-user', email: 'ignored@example.com' },
    })).not.toThrow();
  });
});

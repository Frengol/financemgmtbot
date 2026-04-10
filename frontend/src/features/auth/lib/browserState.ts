const configuredAdminEmails = (import.meta.env.VITE_ALLOWED_ADMIN_EMAILS || '')
  .split(',')
  .map((email) => email.trim().toLowerCase())
  .filter(Boolean);

const authTestModeEnabled = import.meta.env.VITE_AUTH_TEST_MODE === 'true';

export const legacyBrowserAdminProfileStorageKey = 'financemgmtbot-admin-profile';
export const browserAdminProfileStorageKey = 'financemgmtbot-admin-profile-v2';
export const legacyBrowserAdminTestSessionStorageKey = 'financemgmtbot-admin-auth-test-session';
export const browserAdminTestSessionStorageKey = 'financemgmtbot-admin-auth-test-session-v2';
export const browserAdminLoginNoticeStorageKey = 'financemgmtbot-admin-login-notice-v1';

const jwtSegmentPattern = /^[A-Za-z0-9_-]+$/;

export type BrowserAdminProfile = {
  id: string;
  email?: string | null;
};

export type BrowserAdminTestSession = {
  accessToken: string;
  refreshToken?: string | null;
  user: BrowserAdminProfile;
};

export type BrowserAdminLoginNotice = {
  message: string;
};

function isLoopbackHostname(hostname: string) {
  return ['localhost', '127.0.0.1', '::1'].includes((hostname || '').toLowerCase());
}

function removeStorageKeys(keys: string[]) {
  if (typeof window === 'undefined') {
    return;
  }

  for (const key of keys) {
    window.localStorage.removeItem(key);
  }
}

export function browserAdminTestSessionAllowed() {
  if (typeof window === 'undefined') {
    return false;
  }

  return isLoopbackHostname(window.location.hostname);
}

export function browserAdminAuthTestModeEnabled() {
  return authTestModeEnabled && browserAdminTestSessionAllowed();
}

export function isJwtShapeValid(token?: string | null) {
  if (!token || typeof token !== 'string') {
    return false;
  }

  const segments = token.split('.');
  return (
    segments.length === 3
    && segments.every((segment) => segment.length > 0 && jwtSegmentPattern.test(segment))
  );
}

export function clearBrowserAdminArtifacts() {
  removeStorageKeys([
    browserAdminProfileStorageKey,
    legacyBrowserAdminProfileStorageKey,
    browserAdminTestSessionStorageKey,
    legacyBrowserAdminTestSessionStorageKey,
  ]);
}

export function saveBrowserAdminLoginNotice(notice: BrowserAdminLoginNotice | null) {
  if (typeof window === 'undefined') {
    return;
  }

  if (!notice?.message) {
    clearBrowserAdminLoginNotice();
    return;
  }

  window.sessionStorage.setItem(browserAdminLoginNoticeStorageKey, JSON.stringify(notice));
}

export function loadBrowserAdminLoginNotice(): BrowserAdminLoginNotice | null {
  if (typeof window === 'undefined') {
    return null;
  }

  const raw = window.sessionStorage.getItem(browserAdminLoginNoticeStorageKey);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as BrowserAdminLoginNotice;
    if (!parsed?.message) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function clearBrowserAdminLoginNotice() {
  if (typeof window === 'undefined') {
    return;
  }

  window.sessionStorage.removeItem(browserAdminLoginNoticeStorageKey);
}

export function isAllowedAdminEmail(email?: string | null) {
  if (configuredAdminEmails.length === 0) {
    return true;
  }

  return !!email && configuredAdminEmails.includes(email.toLowerCase());
}

export function decodeAccessTokenIdentity(token?: string | null): BrowserAdminProfile | null {
  if (!token || !isJwtShapeValid(token)) {
    return null;
  }

  try {
    const segments = token.split('.');
    const normalized = segments[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
    let decodedPayload = '';

    if (typeof window !== 'undefined' && typeof window.atob === 'function') {
      decodedPayload = window.atob(padded);
    } else if (typeof Buffer !== 'undefined') {
      decodedPayload = Buffer.from(padded, 'base64').toString('utf-8');
    } else {
      return null;
    }

    const decoded = JSON.parse(decodedPayload) as { sub?: string; email?: string | null };
    if (!decoded.sub) {
      return null;
    }

    return {
      id: decoded.sub,
      email: decoded.email ?? null,
    };
  } catch {
    return null;
  }
}

export function saveBrowserAdminProfile(profile: BrowserAdminProfile | null) {
  if (typeof window === 'undefined') {
    return;
  }

  if (!profile?.id) {
    clearBrowserAdminProfile();
    return;
  }

  window.localStorage.removeItem(legacyBrowserAdminProfileStorageKey);
  window.localStorage.setItem(browserAdminProfileStorageKey, JSON.stringify(profile));
}

export function loadBrowserAdminProfile(): BrowserAdminProfile | null {
  if (typeof window === 'undefined') {
    return null;
  }

  const raw = window.localStorage.getItem(browserAdminProfileStorageKey);
  if (!raw) {
    window.localStorage.removeItem(legacyBrowserAdminProfileStorageKey);
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as BrowserAdminProfile;
    if (!parsed?.id) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function clearBrowserAdminProfile() {
  removeStorageKeys([
    browserAdminProfileStorageKey,
    legacyBrowserAdminProfileStorageKey,
  ]);
}

export function saveBrowserAdminTestSession(session: BrowserAdminTestSession | null) {
  if (typeof window === 'undefined') {
    return;
  }

  if (!browserAdminAuthTestModeEnabled() || !session?.accessToken || !isJwtShapeValid(session.accessToken) || !session.user?.id) {
    clearBrowserAdminTestSession();
    return;
  }

  window.localStorage.removeItem(legacyBrowserAdminTestSessionStorageKey);
  window.localStorage.setItem(browserAdminTestSessionStorageKey, JSON.stringify(session));
}

export function loadBrowserAdminTestSession(): BrowserAdminTestSession | null {
  if (typeof window === 'undefined') {
    return null;
  }

  if (!browserAdminAuthTestModeEnabled()) {
    clearBrowserAdminTestSession();
    return null;
  }

  const raw = window.localStorage.getItem(browserAdminTestSessionStorageKey);
  if (!raw) {
    window.localStorage.removeItem(legacyBrowserAdminTestSessionStorageKey);
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as BrowserAdminTestSession;
    if (!parsed?.accessToken || !isJwtShapeValid(parsed.accessToken) || !parsed.user?.id) {
      clearBrowserAdminTestSession();
      return null;
    }
    return parsed;
  } catch {
    clearBrowserAdminTestSession();
    return null;
  }
}

export function clearBrowserAdminTestSession() {
  removeStorageKeys([
    browserAdminTestSessionStorageKey,
    legacyBrowserAdminTestSessionStorageKey,
  ]);
}

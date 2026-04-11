import { createClient } from '@supabase/supabase-js';

import {
  browserAdminAuthTestModeEnabled,
  clearBrowserAdminArtifacts,
  isJwtShapeValid,
  loadBrowserAdminTestSession,
} from '@/features/auth/lib/browserState';

const supabaseUrl = (import.meta.env.VITE_SUPABASE_URL || 'http://127.0.0.1:54321').trim().replace(/\/$/, '');
const supabaseAnonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY || 'public-anon-key-for-local-tests').trim();

export const legacySupabaseBrowserSessionStorageKey = 'financemgmtbot-admin-auth';
export const supabaseBrowserSessionStorageKey = 'financemgmtbot-admin-auth-v2';

let cachedBrowserAccessToken: string | null = null;

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    autoRefreshToken: true,
    detectSessionInUrl: true,
    flowType: 'pkce',
    persistSession: true,
    storageKey: supabaseBrowserSessionStorageKey,
  },
});

export function setCachedBrowserAccessToken(token?: string | null) {
  cachedBrowserAccessToken = isJwtShapeValid(token) ? (token ?? null) : null;
}

export function purgeLegacyBrowserAuthStorage() {
  if (typeof window !== 'undefined') {
    window.localStorage.removeItem(legacySupabaseBrowserSessionStorageKey);
  }
}

export async function clearBrowserAuthState() {
  cachedBrowserAccessToken = null;
  if (typeof window !== 'undefined') {
    purgeLegacyBrowserAuthStorage();
    window.localStorage.removeItem(supabaseBrowserSessionStorageKey);
  }

  clearBrowserAdminArtifacts();

  try {
    await supabase.auth.signOut();
  } catch {
    return;
  }
}

export async function getAccessToken() {
  purgeLegacyBrowserAuthStorage();

  if (cachedBrowserAccessToken && isJwtShapeValid(cachedBrowserAccessToken)) {
    return cachedBrowserAccessToken;
  }

  const browserAuthTestSession = browserAdminAuthTestModeEnabled() ? loadBrowserAdminTestSession() : null;
  if (browserAuthTestSession?.accessToken) {
    setCachedBrowserAccessToken(browserAuthTestSession.accessToken);
    return browserAuthTestSession.accessToken;
  }

  const { data } = await supabase.auth.getSession();
  const accessToken = data.session?.access_token || null;
  if (accessToken && !isJwtShapeValid(accessToken)) {
    await clearBrowserAuthState();
    return null;
  }

  setCachedBrowserAccessToken(accessToken);
  return accessToken;
}

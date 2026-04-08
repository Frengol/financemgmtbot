import { createClient } from '@supabase/supabase-js';
import {
  browserAdminTestSessionAllowed,
  clearBrowserAdminArtifacts,
  isJwtShapeValid,
  loadBrowserAdminTestSession,
} from '@/lib/auth';

const supabaseUrl = (import.meta.env.VITE_SUPABASE_URL || 'http://127.0.0.1:54321').trim().replace(/\/$/, '');
const supabaseAnonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY || 'public-anon-key-for-local-tests').trim();
export const supabaseBrowserSessionStorageKey = 'financemgmtbot-admin-auth';

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    autoRefreshToken: true,
    detectSessionInUrl: false,
    persistSession: true,
    storageKey: supabaseBrowserSessionStorageKey,
  },
});

export async function clearBrowserAuthState() {
  if (typeof window !== 'undefined') {
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
  const browserAuthTestSession = browserAdminTestSessionAllowed() ? loadBrowserAdminTestSession() : null;
  if (browserAuthTestSession?.accessToken) {
    return browserAuthTestSession.accessToken;
  }

  const { data } = await supabase.auth.getSession();
  const accessToken = data.session?.access_token || null;
  if (accessToken && !isJwtShapeValid(accessToken)) {
    await clearBrowserAuthState();
    return null;
  }

  return accessToken;
}

import { createClient } from '@supabase/supabase-js';
import {
  clearBrowserAdminArtifacts,
  isJwtShapeValid,
  loadBrowserAdminTestSession,
} from '@/lib/auth';

const supabaseUrl = (import.meta.env.VITE_SUPABASE_URL || 'http://127.0.0.1:54321').trim().replace(/\/$/, '');
const supabaseAnonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY || 'public-anon-key-for-local-tests').trim();

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    autoRefreshToken: true,
    detectSessionInUrl: false,
    persistSession: true,
    storageKey: 'financemgmtbot-admin-auth',
  },
});

export async function clearBrowserAuthState() {
  clearBrowserAdminArtifacts();
  try {
    await supabase.auth.signOut();
  } catch {
    return;
  }
}

export async function getAccessToken() {
  const browserAuthTestSession = loadBrowserAdminTestSession();
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

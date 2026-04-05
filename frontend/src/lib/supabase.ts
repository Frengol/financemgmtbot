import { createClient } from '@supabase/supabase-js';
import { loadBrowserAdminTestSession } from '@/lib/auth';

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

export async function getAccessToken() {
  const browserAuthTestSession = loadBrowserAdminTestSession();
  if (browserAuthTestSession?.accessToken) {
    return browserAuthTestSession.accessToken;
  }

  const { data } = await supabase.auth.getSession();
  return data.session?.access_token || null;
}

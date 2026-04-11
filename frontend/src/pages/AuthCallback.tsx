import { useEffect, useState } from 'react';
import { Activity, Loader2 } from 'lucide-react';

import {
  browserAdminAuthTestModeEnabled,
  clearBrowserAdminLoginNotice,
  clearBrowserAdminTestSession,
  saveBrowserAdminTestSession,
} from '@/features/auth/lib/browserState';
import { clearBrowserAuthState, supabase } from '@/features/auth/lib/supabaseBrowserSession';
import { emitClientTelemetry, ensureSupportCodeInMessage } from '@/features/observability/clientTelemetry';

function isJwtShapeValid(token?: string | null) {
  return typeof token === 'string' && token.split('.').length === 3;
}

function decodeAuthValue(value: string | null) {
  if (!value) {
    return '';
  }
  return decodeURIComponent(value.replace(/\+/g, ' '));
}

function fallbackProfileFromCallback(queryParams: URLSearchParams, hashParams: URLSearchParams) {
  const userId = (
    hashParams.get('auth_test_user_id')
    || queryParams.get('user_id')
    || hashParams.get('user_id')
    || ''
  ).trim();
  if (!userId) {
    return null;
  }

  const email = (
    hashParams.get('auth_test_email')
    || queryParams.get('email')
    || hashParams.get('email')
    || ''
  ).trim();

  return {
    id: decodeAuthValue(userId),
    email: email ? decodeAuthValue(email) : null,
  };
}

function mapUpstreamAuthError(upstreamError: string, upstreamCode: string | null) {
  const normalizedError = upstreamError.toLowerCase();
  const normalizedCode = (upstreamCode || '').toLowerCase();

  if (
    normalizedCode === 'otp_expired'
    || normalizedError.includes('invalid or has expired')
    || normalizedError.includes('expired')
  ) {
    return 'Link de acesso invalido ou expirado. Solicite um novo magic link.';
  }

  return upstreamError || 'Nao foi possivel concluir o login com este link. Solicite um novo magic link.';
}

function buildHomeUrl() {
  return new URL(import.meta.env.BASE_URL, window.location.origin).toString();
}

function buildLoginUrl() {
  return new URL('login', new URL(import.meta.env.BASE_URL, window.location.origin)).toString();
}

function clearTokenFragment() {
  if (!window.location.hash) {
    return;
  }

  const cleanUrl = `${window.location.pathname}${window.location.search}`;
  window.history.replaceState({}, document.title, cleanUrl);
}

async function waitForBrowserSession() {
  const currentSession = await supabase.auth.getSession();
  const currentAccessToken = currentSession.data.session?.access_token ?? null;

  if (currentAccessToken) {
    return isJwtShapeValid(currentAccessToken) ? currentSession.data.session : 'invalid';
  }

  return new Promise<Awaited<ReturnType<typeof supabase.auth.getSession>>['data']['session'] | 'invalid' | null>((resolve) => {
    let unsubscribe = () => {};
    const timeoutId = window.setTimeout(() => {
      unsubscribe();
      resolve(null);
    }, 4000);

    const subscription = supabase.auth.onAuthStateChange((_event, session) => {
      if (!session?.access_token) {
        return;
      }

      window.clearTimeout(timeoutId);
      unsubscribe();
      resolve(isJwtShapeValid(session.access_token) ? session : 'invalid');
    });

    unsubscribe = () => {
      subscription.data.subscription.unsubscribe();
    };
  });
}

export default function AuthCallback() {
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    const failLogin = async () => {
      const clientEventId = emitClientTelemetry({
        event: 'auth_callback_failed',
        phase: 'callback_session_resolution',
        errorCode: 'AUTH_CALLBACK_SESSION_INVALID',
        diagnostic: 'session_store_invalid',
      });

      await clearBrowserAuthState();
      if (cancelled) {
        return;
      }

      setError(
        ensureSupportCodeInMessage(
          'Nao foi possivel concluir o login com este link. Solicite um novo magic link.',
          clientEventId,
        ),
      );
    };

    const completeLogin = async () => {
      const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ''));
      const queryParams = new URLSearchParams(window.location.search);
      const upstreamError = decodeAuthValue(
        hashParams.get('error_description') || queryParams.get('error_description'),
      );
      const upstreamCode = hashParams.get('error_code') || queryParams.get('error_code');

      if (hashParams.get('error') || queryParams.get('error')) {
        await clearBrowserAuthState();
        clearTokenFragment();
        if (!cancelled) {
          setError(mapUpstreamAuthError(upstreamError, upstreamCode));
        }
        return;
      }

      const callbackProfile = fallbackProfileFromCallback(queryParams, hashParams);
      const accessToken = hashParams.get('access_token');
      const refreshToken = hashParams.get('refresh_token');

      if (callbackProfile && browserAdminAuthTestModeEnabled() && accessToken && refreshToken) {
        saveBrowserAdminTestSession({
          accessToken,
          refreshToken,
          user: callbackProfile,
        });
        clearTokenFragment();
        window.location.replace(buildHomeUrl());
        return;
      }

      const browserSession = await waitForBrowserSession();
      if (cancelled) {
        return;
      }

      if (browserSession === 'invalid' || !browserSession?.access_token) {
        await failLogin();
        return;
      }

      clearTokenFragment();
      clearBrowserAdminLoginNotice();
      clearBrowserAdminTestSession();
      window.location.replace(buildHomeUrl());
    };

    void completeLogin();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="max-w-md w-full bg-white rounded-2xl shadow-sm border p-8 space-y-6">
        <div className="flex flex-col items-center justify-center space-y-3">
          <div className="h-12 w-12 bg-blue-50 text-blue-600 rounded-full flex items-center justify-center">
            <Activity className="h-6 w-6" />
          </div>
          <h2 className="text-2xl font-semibold text-slate-800">Finance Copilot</h2>
        </div>

        {error ? (
          <div className="space-y-4">
            <div className="bg-rose-50 text-rose-600 p-4 rounded-lg text-sm border border-rose-100">
              {error}
            </div>
            <button
              type="button"
              onClick={() => {
                void clearBrowserAuthState().finally(() => {
                  window.location.replace(buildLoginUrl());
                });
              }}
              className="block w-full text-center rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700"
            >
              Voltar para o login
            </button>
          </div>
        ) : (
          <div className="bg-blue-50 text-blue-700 p-4 rounded-lg flex flex-col items-center gap-3 text-center border border-blue-100">
            <Loader2 className="h-6 w-6 animate-spin" />
            <p className="text-sm font-medium">Finalizando login...</p>
          </div>
        )}
      </div>
    </div>
  );
}

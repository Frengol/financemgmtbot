import { useEffect, useState } from 'react';
import { Activity, Loader2 } from 'lucide-react';
import {
  clearBrowserAdminProfile,
  clearBrowserAdminTestSession,
  decodeAccessTokenIdentity,
  saveBrowserAdminProfile,
  saveBrowserAdminTestSession,
} from '@/lib/auth';
import { supabase } from '@/lib/supabase';

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

export default function AuthCallback() {
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    const completeLogin = async () => {
      const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ''));
      const queryParams = new URLSearchParams(window.location.search);
      const upstreamError = decodeAuthValue(hashParams.get('error_description') || queryParams.get('error_description'));
      const upstreamCode = hashParams.get('error_code') || queryParams.get('error_code');

      if (hashParams.get('error') || queryParams.get('error')) {
        clearBrowserAdminProfile();
        clearBrowserAdminTestSession();
        setError(mapUpstreamAuthError(upstreamError, upstreamCode));
        clearTokenFragment();
        return;
      }

      const accessToken = hashParams.get('access_token');
      const refreshToken = hashParams.get('refresh_token');
      if (!accessToken || !refreshToken) {
        clearBrowserAdminProfile();
        clearBrowserAdminTestSession();
        setError('Nao foi possivel concluir o login com este link. Solicite um novo magic link.');
        clearTokenFragment();
        return;
      }

      const callbackProfile = fallbackProfileFromCallback(queryParams, hashParams);
      if (callbackProfile) {
        saveBrowserAdminProfile(callbackProfile);
        saveBrowserAdminTestSession({
          accessToken,
          refreshToken,
          user: callbackProfile,
        });
        clearTokenFragment();
        window.location.replace(buildHomeUrl());
        return;
      }

      const { error: sessionError } = await supabase.auth.setSession({
        access_token: accessToken,
        refresh_token: refreshToken,
      });

      clearTokenFragment();

      if (cancelled) {
        return;
      }

      if (sessionError) {
        clearBrowserAdminProfile();
        clearBrowserAdminTestSession();
        setError('Nao foi possivel concluir o login com este link. Solicite um novo magic link.');
        return;
      }

      saveBrowserAdminProfile(decodeAccessTokenIdentity(accessToken));
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
            <a
              href={buildLoginUrl()}
              className="block w-full text-center rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700"
            >
              Voltar para o login
            </a>
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

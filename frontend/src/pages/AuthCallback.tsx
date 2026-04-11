import { useEffect, useState } from 'react';
import { Activity, Loader2 } from 'lucide-react';
import {
  browserAdminAuthTestModeEnabled,
  clearBrowserAdminProfile,
  clearBrowserAdminLoginNotice,
  clearBrowserAdminTestSession,
  decodeAccessTokenIdentity,
  isJwtShapeValid,
  saveBrowserAdminLoginNotice,
  saveBrowserAdminProfile,
  saveBrowserAdminTestSession,
} from '@/features/auth/lib/browserState';
import { ApiError, getAdminMe } from '@/features/admin/api';
import { clearBrowserAuthState, setCachedBrowserAccessToken, supabase } from '@/features/auth/lib/supabaseBrowserSession';
import {
  buildPublicApiUrl,
  clearAuthCallbackDiagnosticSnapshot,
  emitClientTelemetry,
  ensureSupportCodeInMessage,
  saveAuthCallbackDiagnosticSnapshot,
} from '@/features/observability/clientTelemetry';

const CALLBACK_VALIDATION_RETRY_DELAY_MS = 300;

type RuntimeProbeResult = {
  reachable: boolean;
  requestId?: string;
};

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

function withDiagnostic(message: string, diagnostic?: string) {
  return diagnostic ? `${message} Diagnostico: ${diagnostic}` : message;
}

function extractSupportRequestId(message: string) {
  const matchedRequestId = message.match(/codigo de suporte:\s*(req_[a-z0-9_-]+)/i);
  return matchedRequestId?.[1];
}

function buildHomeUrl() {
  return new URL(import.meta.env.BASE_URL, window.location.origin).toString();
}

function buildLoginUrl() {
  return new URL('login', new URL(import.meta.env.BASE_URL, window.location.origin)).toString();
}

function isCrossOriginApiRequest() {
  const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/$/, '');
  if (!configuredApiBaseUrl) {
    return false;
  }

  try {
    return new URL(configuredApiBaseUrl).origin !== window.location.origin;
  } catch {
    return false;
  }
}

function delay(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

async function probeRuntimeMeta(): Promise<RuntimeProbeResult> {
  try {
    const response = await fetch(buildPublicApiUrl('/api/meta/runtime'), {
      method: 'GET',
      mode: 'cors',
      cache: 'no-store',
    });
    return {
      reachable: true,
      requestId: response.headers.get('X-Request-ID') || undefined,
    };
  } catch {
    return { reachable: false };
  }
}

function clearTokenFragment() {
  if (!window.location.hash) {
    return;
  }
  const cleanUrl = `${window.location.pathname}${window.location.search}`;
  window.history.replaceState({}, document.title, cleanUrl);
}

function resolveAuthProfile(options: {
  accessToken?: string | null;
  user?: {
    id?: string | null;
    email?: string | null;
  } | null;
  fallbackProfile?: {
    id: string;
    email: string | null;
  } | null;
}) {
  const { accessToken, user, fallbackProfile } = options;
  const claims = decodeAccessTokenIdentity(accessToken);
  const userId = user?.id || claims?.id || fallbackProfile?.id || null;
  const email = user?.email ?? claims?.email ?? fallbackProfile?.email ?? null;

  if (!userId) {
    return null;
  }

  return {
    id: userId,
    email,
  };
}

async function waitForBrowserSession() {
  const currentSession = await supabase.auth.getSession();
  const currentAccessToken = currentSession.data.session?.access_token ?? null;
  if (currentAccessToken) {
    if (!isJwtShapeValid(currentAccessToken)) {
      return 'invalid';
    }
    return currentSession.data.session;
  }

  return new Promise<any | null>((resolve) => {
    const timeoutId = window.setTimeout(() => {
      subscription.data.subscription.unsubscribe();
      resolve(null);
    }, 4000);

    const subscription = supabase.auth.onAuthStateChange((_event, session) => {
      if (session?.access_token && isJwtShapeValid(session.access_token)) {
        window.clearTimeout(timeoutId);
        subscription.data.subscription.unsubscribe();
        resolve(session);
      }
    });
  });
}

export default function AuthCallback() {
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    const completeLogin = async () => {
      const failLogin = async (diagnostic?: string) => {
        const clientEventId = emitClientTelemetry({
          event: 'auth_callback_failed',
          phase: 'callback_session_resolution',
          errorCode: 'AUTH_CALLBACK_SESSION_INVALID',
          diagnostic,
        });
        await clearBrowserAuthState();
        setError(
          ensureSupportCodeInMessage(
            withDiagnostic('Nao foi possivel concluir o login com este link. Solicite um novo magic link.', diagnostic),
            clientEventId,
          ),
        );
      };

      const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ''));
      const queryParams = new URLSearchParams(window.location.search);
      const upstreamError = decodeAuthValue(hashParams.get('error_description') || queryParams.get('error_description'));
      const upstreamCode = hashParams.get('error_code') || queryParams.get('error_code');

      clearAuthCallbackDiagnosticSnapshot();

      if (hashParams.get('error') || queryParams.get('error')) {
        clearBrowserAdminProfile();
        clearBrowserAdminTestSession();
        setError(mapUpstreamAuthError(upstreamError, upstreamCode));
        return;
      }

      const callbackProfile = fallbackProfileFromCallback(queryParams, hashParams);
      const accessToken = hashParams.get('access_token');
      const refreshToken = hashParams.get('refresh_token');

      if (callbackProfile && browserAdminAuthTestModeEnabled() && accessToken && refreshToken) {
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
      clearTokenFragment();


      const browserSession = await waitForBrowserSession();
      if (cancelled) {
        return;
      }

      if (browserSession === 'invalid') {
        await failLogin('session_store_invalid');
        return;
      }

      const resolvedProfile = resolveAuthProfile({
        accessToken: browserSession?.access_token ?? null,
        user: browserSession?.user ?? null,
        fallbackProfile: callbackProfile,
      });

      if (!browserSession?.access_token || !isJwtShapeValid(browserSession.access_token) || !resolvedProfile) {
        await failLogin('session_store_invalid');
        return;
      }

      try {
        setCachedBrowserAccessToken(browserSession.access_token);
        const adminIdentity = await getAdminMe(browserSession.access_token);
        if (!adminIdentity.authenticated || !adminIdentity.authorized) {
          throw new ApiError('Seu usuario nao esta autorizado a acessar o painel.', {
            code: 'AUTH_ACCESS_DENIED',
            status: 403,
          });
        }
      } catch (authError) {
        let typedError = authError instanceof ApiError ? authError : null;

        if (typedError?.code === 'NETWORK_ERROR') {
          await delay(CALLBACK_VALIDATION_RETRY_DELAY_MS);
          if (cancelled) {
            return;
          }

          try {
            const retriedIdentity = await getAdminMe(browserSession.access_token);
            if (!retriedIdentity.authenticated || !retriedIdentity.authorized) {
              throw new ApiError('Seu usuario nao esta autorizado a acessar o painel.', {
                code: 'AUTH_ACCESS_DENIED',
                status: 403,
              });
            }
            clearAuthCallbackDiagnosticSnapshot();
            clearBrowserAdminLoginNotice();
            clearBrowserAdminTestSession();
            saveBrowserAdminProfile(resolvedProfile);
            if (!cancelled) {
              window.location.replace(buildHomeUrl());
            }
            return;
          } catch (retryError) {
            const retryTypedError = retryError instanceof ApiError ? retryError : null;
            if (retryTypedError?.code === 'NETWORK_ERROR') {
              const runtimeProbe = await probeRuntimeMeta();
              const diagnostic = runtimeProbe.reachable
                ? 'auth_callback_admin_validation_failed'
                : isCrossOriginApiRequest()
                  ? 'frontend_cors_blocked_confirmed'
                  : 'frontend_transport_failed';
              const clientEventId = retryTypedError.clientEventId || typedError.clientEventId;

              saveAuthCallbackDiagnosticSnapshot({
                clientEventId,
                phase: 'callback_admin_validation',
                diagnostic,
                retryOutcome: 'retry_failed',
                runtimeProbeOutcome: runtimeProbe.reachable ? 'reachable' : 'transport_failed',
                runtimeRequestId: runtimeProbe.requestId,
              });
              emitClientTelemetry({
                event: 'auth_callback_failed',
                phase: 'callback_admin_validation',
                clientEventId,
                httpStatus: retryTypedError.status,
                errorCode: retryTypedError.code,
                diagnostic,
                corsSuspected: diagnostic === 'frontend_cors_blocked_confirmed',
              });
              if (!cancelled) {
                setError(
                  ensureSupportCodeInMessage(
                    withDiagnostic(
                      'Nao foi possivel validar sua sessao agora. Tente novamente em instantes.',
                      diagnostic,
                    ),
                    clientEventId,
                  ),
                );
              }
              return;
            }
            typedError = retryTypedError;
            authError = retryError;
          }

          if (!(authError instanceof ApiError)) {
            typedError = null;
          }
        }

        const fallbackRequestId = authError instanceof Error
          ? extractSupportRequestId(authError.message)
          : undefined;
        const clientEventId = typedError?.clientEventId || emitClientTelemetry({
          event: 'auth_callback_failed',
          phase: 'callback_admin_validation',
          httpStatus: typedError?.status,
          errorCode: typedError?.code || 'AUTH_CALLBACK_ADMIN_VALIDATION_FAILED',
          diagnostic: typedError?.requestId
            ? typedError.detail || typedError.diagnostic || 'auth_callback_admin_validation_failed'
            : typedError?.diagnostic || 'auth_callback_admin_validation_failed',
          requestId: typedError?.requestId || fallbackRequestId,
          corsSuspected: typedError?.code === 'NETWORK_ERROR',
        });
        const message = authError instanceof Error
          ? authError.message
          : 'Nao foi possivel validar sua sessao agora. Faca login novamente.';
        const supportMessage = typedError?.requestId || fallbackRequestId
          ? message
          : ensureSupportCodeInMessage(message, clientEventId);
        await clearBrowserAuthState();
        saveBrowserAdminLoginNotice({ message: supportMessage });
        if (!cancelled) {
          window.location.replace(buildLoginUrl());
        }
        return;
      }

      clearAuthCallbackDiagnosticSnapshot();
      clearBrowserAdminLoginNotice();
      clearBrowserAdminTestSession();
      saveBrowserAdminProfile(resolvedProfile);
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
                  clearAuthCallbackDiagnosticSnapshot();
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

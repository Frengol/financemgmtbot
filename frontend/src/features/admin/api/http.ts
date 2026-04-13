import { clearBrowserAuthState, getAccessToken } from '@/features/auth/lib/supabaseBrowserSession';
import type {
  ApiErrorPayload,
  ApiResponse,
} from '@/features/admin/api/contracts';
import {
  ApiError,
} from '@/features/admin/api/contracts';
import { emitClientTelemetry } from '@/features/observability/clientTelemetry';

const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

export const localDevBypassEnabled = import.meta.env.DEV && import.meta.env.VITE_LOCAL_DEV_BYPASS_AUTH === 'true';

const ERROR_MESSAGES: Record<string, string> = {
  ADMIN_ACTION_FAILED: 'Nao foi possivel concluir a operacao agora.',
  ADMIN_DATA_LOAD_FAILED: 'Nao foi possivel carregar os dados agora.',
  AUTH_ACCESS_DENIED: 'Seu usuario nao esta autorizado a acessar o painel.',
  AUTH_CONFIGURATION_INVALID: 'A configuracao de login esta indisponivel no momento. Tente novamente mais tarde.',
  AUTH_SESSION_INVALID: 'Sua sessao expirou. Faca login novamente.',
  AUTH_SESSION_TOKEN_MALFORMED: 'Sua sessao de acesso e invalida. Faca login novamente.',
  AUTH_SESSION_STORAGE_UNAVAILABLE: 'O login esta temporariamente indisponivel. Tente novamente em instantes.',
  NETWORK_ERROR: 'Nao foi possivel conectar ao servidor agora. Verifique sua conexao e tente novamente.',
};

const AUTH_RECOVERY_ERROR_CODES = new Set([
  'AUTH_SESSION_INVALID',
  'AUTH_SESSION_TOKEN_MALFORMED',
]);

function generateClientRequestId() {
  const randomUuid = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID().replace(/-/g, '')
    : Math.random().toString(16).slice(2);
  return `reqc_${randomUuid.slice(0, 24)}`;
}

function buildApiUrl(path: string) {
  return `${configuredApiBaseUrl}${path}`;
}

function isAdminApiPath(path: string) {
  return path.startsWith('/api/admin/');
}

function isCrossOriginApiRequest() {
  if (!configuredApiBaseUrl) {
    return false;
  }

  try {
    return new URL(configuredApiBaseUrl).origin !== window.location.origin;
  } catch {
    return false;
  }
}

function resolveTransportDiagnostic() {
  const crossOriginRequest = isCrossOriginApiRequest();
  const browserOnline = typeof navigator === 'undefined' || navigator.onLine !== false;

  if (crossOriginRequest && browserOnline) {
    return {
      diagnostic: 'frontend_cross_origin_transport_failed',
      corsSuspected: true,
    };
  }

  return {
    diagnostic: 'frontend_transport_failed',
    corsSuspected: false,
  };
}

function buildSupportMessage({
  message,
  requestId,
  clientEventId,
  clientRequestId,
  detail,
  diagnostic,
}: {
  message: string;
  requestId?: string;
  clientEventId?: string;
  clientRequestId?: string;
  detail?: string;
  diagnostic?: string;
}) {
  const supportMessageParts = [message];
  if (requestId) {
    supportMessageParts.push(`Codigo de suporte: ${requestId}`);
  } else if (clientEventId) {
    supportMessageParts.push(`Codigo de suporte: ${clientEventId}`);
  }
  if (detail) {
    supportMessageParts.push(`Detalhe: ${detail}`);
  }
  if (clientRequestId) {
    supportMessageParts.push(`Correlacao: ${clientRequestId}`);
  }
  if (diagnostic) {
    supportMessageParts.push(`Diagnostico: ${diagnostic}`);
  }
  return supportMessageParts.join(' ');
}

function createClientApiError({
  code,
  status,
  message,
  diagnostic,
  clientEventId,
  clientRequestId,
  retryable = false,
}: {
  code: string;
  status: number;
  message: string;
  diagnostic?: string;
  clientEventId?: string;
  clientRequestId?: string;
  retryable?: boolean;
}) {
  return new ApiError(
    buildSupportMessage({ message, clientEventId, clientRequestId, diagnostic }),
    {
      code,
      diagnostic,
      status,
      clientEventId,
      clientRequestId,
      retryable,
    },
  );
}

async function parseError(response: Response) {
  let payload: ApiErrorPayload = {};
  try {
    payload = await response.json() as ApiErrorPayload;
  } catch {
    payload = {};
  }

  const requestId = payload.requestId || response.headers.get('X-Request-ID') || undefined;
  const clientRequestId = response.headers.get('X-Client-Request-ID') || undefined;
  const code = payload.code || 'UNKNOWN_ERROR';
  const detail = typeof payload.detail === 'string' && /^[a-z0-9_:-]{1,64}$/i.test(payload.detail)
    ? payload.detail
    : undefined;
  const fallbackMessage = payload.message || payload.error || `Request failed with status ${response.status}`;
  const mappedMessage = ERROR_MESSAGES[code] || fallbackMessage;
  const supportMessage = buildSupportMessage({
    message: mappedMessage,
    requestId,
    clientRequestId,
    detail,
  });

  return new ApiError(supportMessage, {
    code,
    detail,
      status: response.status,
      requestId,
      clientRequestId,
      retryable: payload.retryable ?? false,
      retryAfterSeconds: payload.retryAfterSeconds,
    });
}

export function isReauthenticationError(error: unknown): error is ApiError {
  return error instanceof ApiError && AUTH_RECOVERY_ERROR_CODES.has(error.code);
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  accessTokenOverride?: string | null,
): Promise<ApiResponse<T>> {
  const headers = new Headers(init.headers);
  const isAdminRoute = isAdminApiPath(path);
  const accessToken = accessTokenOverride ?? (isAdminRoute ? await getAccessToken() : null);

  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`);
  } else if (isAdminRoute) {
    await clearBrowserAuthState();
    throw createClientApiError({
      code: 'AUTH_SESSION_INVALID',
      status: 401,
      message: ERROR_MESSAGES.AUTH_SESSION_INVALID,
      diagnostic: 'auth_state_unusable',
    });
  }

  let response: Response;
  const clientRequestId = isAdminRoute ? generateClientRequestId() : undefined;
  try {
    const requestInit: RequestInit = {
      ...init,
      headers,
    };
    if (clientRequestId) {
      headers.set('X-Client-Request-ID', clientRequestId);
    }
    if (!accessToken && !isAdminRoute) {
      requestInit.credentials = 'include';
    }

    response = await fetch(buildApiUrl(path), requestInit);
  } catch {
    const { diagnostic, corsSuspected } = resolveTransportDiagnostic();
    const clientEventId = emitClientTelemetry({
      event: 'admin_api_transport_failed',
      phase: 'api_request',
      clientRequestId,
      httpStatus: 0,
      errorCode: 'NETWORK_ERROR',
      diagnostic,
      corsSuspected,
    });
    throw new ApiError(buildSupportMessage({
      message: ERROR_MESSAGES.NETWORK_ERROR,
      clientEventId,
      clientRequestId,
      diagnostic,
    }), {
      code: 'NETWORK_ERROR',
      diagnostic,
      status: 0,
      clientEventId,
      clientRequestId,
      retryable: true,
    });
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json() as Promise<ApiResponse<T>>;
}

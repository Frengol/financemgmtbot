import type { TransactionDraft, TransactionRecord } from '@/lib/transactions';
import { browserAdminTestSessionAllowed } from '@/lib/auth';
import { clearBrowserAuthState, getAccessToken } from '@/lib/supabase';

const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
export const localDevBypassEnabled = import.meta.env.DEV && import.meta.env.VITE_LOCAL_DEV_BYPASS_AUTH === 'true';

type ApiResponse<T> = {
  status: string;
  message?: string;
  code?: string;
  detail?: string;
  requestId?: string;
  retryable?: boolean;
  retryAfterSeconds?: number;
} & T;

type ApiErrorPayload = {
  message?: string;
  error?: string;
  code?: string;
  detail?: string;
  requestId?: string;
  retryable?: boolean;
  retryAfterSeconds?: number;
};

const ERROR_MESSAGES: Record<string, string> = {
  ADMIN_ACTION_FAILED: 'Nao foi possivel concluir a operacao agora.',
  ADMIN_DATA_LOAD_FAILED: 'Nao foi possivel carregar os dados agora.',
  AUTH_ACCESS_DENIED: 'Seu usuario nao esta autorizado a acessar o painel.',
  AUTH_CONFIGURATION_INVALID: 'A configuracao de login esta indisponivel no momento. Tente novamente mais tarde.',
  AUTH_CSRF_INVALID: 'Sua sessão não pôde ser validada. Atualize a pagina e tente novamente.',
  AUTH_MAGIC_LINK_RATE_LIMIT: 'Muitos pedidos de login em pouco tempo. Aguarde alguns minutos e tente novamente.',
  AUTH_MAGIC_LINK_SEND_FAILED: 'Nao foi possivel enviar o link de acesso agora. Tente novamente em instantes.',
  AUTH_SESSION_INVALID: 'Sua sessao expirou. Faca login novamente.',
  AUTH_SESSION_TOKEN_MALFORMED: 'Sua sessao de acesso e invalida. Faca login novamente.',
  AUTH_SESSION_STORAGE_UNAVAILABLE: 'O login esta temporariamente indisponivel. Tente novamente em instantes.',
  NETWORK_ERROR: 'Nao foi possivel conectar ao servidor agora. Verifique sua conexao e tente novamente.',
};

const AUTH_RECOVERY_ERROR_CODES = new Set([
  'AUTH_SESSION_INVALID',
  'AUTH_SESSION_TOKEN_MALFORMED',
]);

export class ApiError extends Error {
  code: string;
  detail?: string;
  diagnostic?: string;
  status: number;
  requestId?: string;
  retryable: boolean;
  retryAfterSeconds?: number;

  constructor(
    message: string,
    {
      code,
      detail,
      diagnostic,
      status,
      requestId,
      retryable = false,
      retryAfterSeconds,
    }: {
      code: string;
      detail?: string;
      diagnostic?: string;
      status: number;
      requestId?: string;
      retryable?: boolean;
      retryAfterSeconds?: number;
    },
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.detail = detail;
    this.diagnostic = diagnostic;
    this.status = status;
    this.requestId = requestId;
    this.retryable = retryable;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export type AuthSessionPayload = {
  authenticated: boolean;
  csrfToken?: string;
  expiresAt?: string;
  user?: {
    id: string;
    email?: string | null;
  } | null;
};

export type PendingApprovalItem = {
  id: string;
  kind: string;
  created_at: string;
  expires_at?: string;
  preview: {
    summary?: string;
    metodo_pagamento?: string;
    conta?: string;
    itens?: string[];
    itens_count?: number;
    total_estimado?: number;
    records_count?: number;
  };
};

function buildApiUrl(path: string) {
  return `${configuredApiBaseUrl}${path}`;
}

function isAdminApiPath(path: string) {
  return path.startsWith('/api/admin/');
}

function buildSupportMessage({
  message,
  requestId,
  detail,
  diagnostic,
}: {
  message: string;
  requestId?: string;
  detail?: string;
  diagnostic?: string;
}) {
  const supportMessageParts = [message];
  if (requestId) {
    supportMessageParts.push(`Codigo de suporte: ${requestId}`);
  }
  if (detail) {
    supportMessageParts.push(`Detalhe: ${detail}`);
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
  retryable = false,
}: {
  code: string;
  status: number;
  message: string;
  diagnostic?: string;
  retryable?: boolean;
}) {
  return new ApiError(
    buildSupportMessage({ message, diagnostic }),
    {
      code,
      diagnostic,
      status,
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
  const code = payload.code || 'UNKNOWN_ERROR';
  const detail = typeof payload.detail === 'string' && /^[a-z0-9_:-]{1,64}$/i.test(payload.detail)
    ? payload.detail
    : undefined;
  const fallbackMessage = payload.message || payload.error || `Request failed with status ${response.status}`;
  const mappedMessage = ERROR_MESSAGES[code] || fallbackMessage;
  const supportMessage = buildSupportMessage({ message: mappedMessage, requestId, detail });

  return new ApiError(supportMessage, {
    code,
    detail,
    status: response.status,
    requestId,
    retryable: payload.retryable ?? false,
    retryAfterSeconds: payload.retryAfterSeconds,
  });
}

export function isReauthenticationError(error: unknown): error is ApiError {
  return error instanceof ApiError && AUTH_RECOVERY_ERROR_CODES.has(error.code);
}

async function apiRequest<T>(path: string, init: RequestInit = {}, csrfToken?: string): Promise<ApiResponse<T>> {
  const headers = new Headers(init.headers);
  const method = (init.method || 'GET').toUpperCase();
  const isAdminRoute = isAdminApiPath(path);
  const accessToken = isAdminRoute ? await getAccessToken() : null;
  const allowLegacyCookieFallback = browserAdminTestSessionAllowed();

  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`);
  } else if (isAdminRoute && !allowLegacyCookieFallback) {
    await clearBrowserAuthState();
    throw createClientApiError({
      code: 'AUTH_SESSION_INVALID',
      status: 401,
      message: ERROR_MESSAGES.AUTH_SESSION_INVALID,
      diagnostic: 'auth_state_unusable',
    });
  } else if (csrfToken && ['POST', 'PATCH', 'DELETE'].includes(method)) {
    headers.set('X-CSRF-Token', csrfToken);
  }

  let response: Response;
  try {
    const requestInit: RequestInit = {
      ...init,
      headers,
    };
    if (!accessToken) {
      requestInit.credentials = 'include';
    }

    response = await fetch(buildApiUrl(path), requestInit);
  } catch {
    throw new ApiError(ERROR_MESSAGES.NETWORK_ERROR, {
      code: 'NETWORK_ERROR',
      status: 0,
      retryable: true,
    });
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  return response.json() as Promise<ApiResponse<T>>;
}

export function requestMagicLink(email: string, redirectTo: string) {
  return apiRequest<{ message: string }>('/auth/magic-link', {
    method: 'POST',
    body: JSON.stringify({ email, redirectTo }),
  });
}

export function getAuthSession() {
  return apiRequest<AuthSessionPayload>('/auth/session', {
    method: 'GET',
  });
}

export function logoutAuthSession() {
  return apiRequest<{ loggedOut: boolean }>('/auth/logout', {
    method: 'POST',
  });
}

export function deleteTransaction(transactionId: string, csrfToken?: string) {
  return apiRequest<{ id: string }>(`/api/admin/gastos/${transactionId}`, {
    method: 'DELETE',
  }, csrfToken);
}

export function getTransactions(params?: { dateFrom?: string; dateTo?: string }) {
  const searchParams = new URLSearchParams();
  if (params?.dateFrom) {
    searchParams.set('date_from', params.dateFrom);
  }
  if (params?.dateTo) {
    searchParams.set('date_to', params.dateTo);
  }

  const suffix = searchParams.toString() ? `?${searchParams.toString()}` : '';
  return apiRequest<{ transactions: TransactionRecord[] }>(`/api/admin/gastos${suffix}`, {
    method: 'GET',
  });
}

export function createTransaction(payload: TransactionDraft, csrfToken?: string) {
  return apiRequest<{ transaction: TransactionRecord }>('/api/admin/gastos', {
    method: 'POST',
    body: JSON.stringify(payload),
  }, csrfToken);
}

export function updateTransaction(transactionId: string, payload: TransactionDraft, csrfToken?: string) {
  return apiRequest<{ transaction: TransactionRecord }>(`/api/admin/gastos/${transactionId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }, csrfToken);
}

export function approvePendingReceipt(cacheId: string, csrfToken?: string) {
  return apiRequest<{ id: string; linhas?: number; total?: number; deleted_records?: number }>(`/api/admin/cache-aprovacao/${cacheId}/approve`, {
    method: 'POST',
  }, csrfToken);
}

export function rejectPendingReceipt(cacheId: string, csrfToken?: string) {
  return apiRequest<{ id: string }>(`/api/admin/cache-aprovacao/${cacheId}/reject`, {
    method: 'POST',
  }, csrfToken);
}

export function getPendingReceipts() {
  return apiRequest<{ items: PendingApprovalItem[] }>('/api/admin/cache-aprovacao', {
    method: 'GET',
  });
}

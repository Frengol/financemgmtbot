import type { TransactionDraft, TransactionRecord } from '@/lib/transactions';

const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
export const localDevBypassEnabled = import.meta.env.DEV && import.meta.env.VITE_LOCAL_DEV_BYPASS_AUTH === 'true';

type ApiResponse<T> = {
  status: string;
  message?: string;
} & T;

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

async function parseError(response: Response) {
  try {
    const data = await response.json() as { message?: string; error?: string };
    return data.message || data.error || `Request failed with status ${response.status}`;
  } catch {
    return `Request failed with status ${response.status}`;
  }
}

async function apiRequest<T>(path: string, init: RequestInit = {}, csrfToken?: string): Promise<ApiResponse<T>> {
  const headers = new Headers(init.headers);
  const method = (init.method || 'GET').toUpperCase();

  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  if (csrfToken && ['POST', 'PATCH', 'DELETE'].includes(method)) {
    headers.set('X-CSRF-Token', csrfToken);
  }

  const response = await fetch(buildApiUrl(path), {
    ...init,
    credentials: 'include',
    headers,
  });

  if (!response.ok) {
    throw new Error(await parseError(response));
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

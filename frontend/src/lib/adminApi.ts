import type { TransactionDraft, TransactionRecord } from '@/lib/transactions';

const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
export const localDevBypassEnabled = import.meta.env.DEV && import.meta.env.VITE_LOCAL_DEV_BYPASS_AUTH === 'true';

type AdminResponse<T> = {
  status: string;
  message?: string;
} & T;

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

async function adminRequest<T>(path: string, accessToken: string, init: RequestInit): Promise<AdminResponse<T>> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");

  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  const response = await fetch(buildApiUrl(path), {
    ...init,
    headers,
  });

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json() as Promise<AdminResponse<T>>;
}

export function deleteTransaction(accessToken: string, transactionId: string) {
  return adminRequest<{ id: string }>(`/api/admin/gastos/${transactionId}`, accessToken, {
    method: "DELETE",
  });
}

export function getTransactions(accessToken: string, params?: { dateFrom?: string; dateTo?: string }) {
  const searchParams = new URLSearchParams();
  if (params?.dateFrom) {
    searchParams.set('date_from', params.dateFrom);
  }
  if (params?.dateTo) {
    searchParams.set('date_to', params.dateTo);
  }

  const suffix = searchParams.toString() ? `?${searchParams.toString()}` : '';
  return adminRequest<{ transactions: TransactionRecord[] }>(`/api/admin/gastos${suffix}`, accessToken, {
    method: 'GET',
  });
}

export function createTransaction(accessToken: string, payload: TransactionDraft) {
  return adminRequest<{ transaction: TransactionRecord }>('/api/admin/gastos', accessToken, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateTransaction(accessToken: string, transactionId: string, payload: TransactionDraft) {
  return adminRequest<{ transaction: TransactionRecord }>(`/api/admin/gastos/${transactionId}`, accessToken, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function approvePendingReceipt(accessToken: string, cacheId: string) {
  return adminRequest<{ id: string; linhas: number; total: number }>(`/api/admin/cache-aprovacao/${cacheId}/approve`, accessToken, {
    method: "POST",
  });
}

export function rejectPendingReceipt(accessToken: string, cacheId: string) {
  return adminRequest<{ id: string }>(`/api/admin/cache-aprovacao/${cacheId}/reject`, accessToken, {
    method: "POST",
  });
}

export function getPendingReceipts(accessToken: string) {
  return adminRequest<{ items: Array<{ id: string; payload: unknown; created_at: string }> }>('/api/admin/cache-aprovacao', accessToken, {
    method: 'GET',
  });
}

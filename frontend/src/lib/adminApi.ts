const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

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
  const response = await fetch(buildApiUrl(path), {
    ...init,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
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

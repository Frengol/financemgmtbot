import type { TransactionDraft, TransactionRecord } from '@/lib/transactions';
import { apiRequest } from '@/features/admin/api/http';

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

export function createTransaction(payload: TransactionDraft) {
  return apiRequest<{ transaction: TransactionRecord }>('/api/admin/gastos', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateTransaction(transactionId: string, payload: TransactionDraft) {
  return apiRequest<{ transaction: TransactionRecord }>(`/api/admin/gastos/${transactionId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteTransaction(transactionId: string) {
  return apiRequest<{ id: string }>(`/api/admin/gastos/${transactionId}`, {
    method: 'DELETE',
  });
}

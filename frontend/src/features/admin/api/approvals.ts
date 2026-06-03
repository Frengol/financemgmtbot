import type { PendingApprovalItem } from '@/features/admin/api/contracts';
import { apiRequest } from '@/features/admin/api/http';

export function approvePendingReceipt(cacheId: string) {
  return apiRequest<{ id: string; linhas?: number; total?: number; deleted_records?: number }>(`/api/admin/cache-aprovacao/${cacheId}/approve`, {
    method: 'POST',
  });
}

export function rejectPendingReceipt(cacheId: string) {
  return apiRequest<{ id: string }>(`/api/admin/cache-aprovacao/${cacheId}/reject`, {
    method: 'POST',
  });
}

export function getPendingReceipts() {
  return apiRequest<{ items: PendingApprovalItem[] }>('/api/admin/cache-aprovacao', {
    method: 'GET',
  });
}

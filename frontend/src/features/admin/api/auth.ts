import type { AdminIdentityPayload } from '@/features/admin/api/contracts';
import { apiRequest } from '@/features/admin/api/http';

export function getAdminMe(accessToken?: string | null) {
  return apiRequest<AdminIdentityPayload>('/api/admin/me', {
    method: 'GET',
  }, accessToken);
}

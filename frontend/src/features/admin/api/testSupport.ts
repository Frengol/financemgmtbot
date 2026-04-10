import { apiRequest } from '@/features/admin/api/http';

export function requestTestMagicLink(email: string, redirectTo: string, userId?: string) {
  return apiRequest<{ magicLink: { link: string } }>('/__test__/auth/magic-link', {
    method: 'POST',
    body: JSON.stringify({ email, redirectTo, userId }),
  });
}

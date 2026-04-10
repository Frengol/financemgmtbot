import { clearBrowserAdminArtifacts } from '@/features/auth/lib/browserState';
import { ApiError, isReauthenticationError } from '@/features/admin/api';

export function createSessionUnavailableError(message = 'Sua sessao expirou. Faca login novamente.') {
  return new ApiError(message, {
    code: 'AUTH_SESSION_INVALID',
    diagnostic: 'auth_state_unusable',
    status: 401,
  });
}

export function normalizeAdminPageError(error: unknown, fallbackMessage: string) {
  if (isReauthenticationError(error)) {
    clearBrowserAdminArtifacts();
  }

  return error instanceof Error ? error : new Error(fallbackMessage);
}

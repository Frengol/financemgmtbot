import { type ReactNode } from 'react';

import { ApiError, isReauthenticationError } from '@/features/admin/api';

type AdminRequestErrorBannerProps = {
  error: ApiError | Error;
  onRetry?: () => void;
  onReauthenticate: () => void;
  retryLabel?: ReactNode;
};

export default function AdminRequestErrorBanner({
  error,
  onRetry,
  onReauthenticate,
  retryLabel = 'Tentar novamente',
}: AdminRequestErrorBannerProps) {
  const requiresReauthentication = isReauthenticationError(error);

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700 md:flex-row md:items-center md:justify-between">
      <span>{error.message}</span>
      {requiresReauthentication ? (
        <button
          type="button"
          onClick={onReauthenticate}
          className="inline-flex items-center justify-center rounded-lg border border-rose-200 bg-white px-3 py-2 font-medium text-rose-700 transition hover:bg-rose-100"
        >
          Fazer login novamente
        </button>
      ) : onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center justify-center rounded-lg border border-rose-200 bg-white px-3 py-2 font-medium text-rose-700 transition hover:bg-rose-100"
        >
          {retryLabel}
        </button>
      ) : null}
    </div>
  );
}

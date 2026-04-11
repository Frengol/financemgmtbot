export type ApiResponse<T> = {
  status: string;
  message?: string;
  code?: string;
  detail?: string;
  requestId?: string;
  retryable?: boolean;
  retryAfterSeconds?: number;
} & T;

export type ApiErrorPayload = {
  message?: string;
  error?: string;
  code?: string;
  detail?: string;
  requestId?: string;
  retryable?: boolean;
  retryAfterSeconds?: number;
};

export class ApiError extends Error {
  code: string;
  detail?: string;
  diagnostic?: string;
  status: number;
  requestId?: string;
  clientEventId?: string;
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
      clientEventId,
      retryable = false,
      retryAfterSeconds,
    }: {
      code: string;
      detail?: string;
      diagnostic?: string;
      status: number;
      requestId?: string;
      clientEventId?: string;
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
    this.clientEventId = clientEventId;
    this.retryable = retryable;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export type AdminIdentityPayload = {
  authenticated: boolean;
  authorized: boolean;
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

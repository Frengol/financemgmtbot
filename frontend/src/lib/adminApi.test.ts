import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  approvePendingReceipt,
  createTransaction,
  deleteTransaction,
  getAuthSession,
  getPendingReceipts,
  getTransactions,
  isReauthenticationError,
  logoutAuthSession,
  rejectPendingReceipt,
  requestMagicLink,
  updateTransaction,
} from './adminApi';

const fetchMock = vi.fn();
const mockGetAccessToken = vi.fn();
const mockClearBrowserAuthState = vi.fn();
const mockBrowserAdminTestSessionAllowed = vi.fn();

vi.mock('@/lib/supabase', () => ({
  clearBrowserAuthState: (...args: unknown[]) => mockClearBrowserAuthState(...args),
  getAccessToken: (...args: unknown[]) => mockGetAccessToken(...args),
}));

vi.mock('@/lib/auth', () => ({
  browserAdminTestSessionAllowed: (...args: unknown[]) => mockBrowserAdminTestSessionAllowed(...args),
}));

describe('adminApi', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    mockGetAccessToken.mockReset();
    mockClearBrowserAuthState.mockReset();
    mockBrowserAdminTestSessionAllowed.mockReset();
    mockBrowserAdminTestSessionAllowed.mockReturnValue(true);
    vi.stubGlobal('fetch', fetchMock);
  });

  it('sends bearer auth and query parameters for transaction listing', async () => {
    mockGetAccessToken.mockResolvedValue('token-123');
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ status: 'ok', transactions: [] }),
    });

    await getTransactions({ dateFrom: '2026-04-01', dateTo: '2026-04-30' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/admin/gastos?date_from=2026-04-01&date_to=2026-04-30');
    expect(init.method).toBe('GET');
    expect(init.credentials).toBeUndefined();
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer token-123');
  });

  it('adds JSON and bearer headers for mutating admin requests', async () => {
    mockGetAccessToken.mockResolvedValue('token-456');
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ status: 'ok', transaction: { id: 'tx-1' } }),
    });

    await createTransaction({
      data: '2026-04-03',
      natureza: 'Essencial',
      categoria: 'Mercado',
      descricao: 'Mercado do mês',
      valor: 89.5,
      conta: 'Nubank',
      metodo_pagamento: 'Pix',
    }, 'csrf-token');

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(init.method).toBe('POST');
    expect(init.credentials).toBeUndefined();
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(headers.get('Authorization')).toBe('Bearer token-456');
    expect(headers.has('X-CSRF-Token')).toBe(false);
  });

  it('surfaces backend error messages for failed requests', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 403,
      headers: new Headers({ 'X-Request-ID': 'req_support_1' }),
      json: vi.fn().mockResolvedValue({ message: 'Missing or invalid CSRF token.', code: 'AUTH_CSRF_INVALID' }),
    });

    await expect(deleteTransaction('tx-1', 'csrf-token')).rejects.toMatchObject({
      name: 'ApiError',
      code: 'AUTH_CSRF_INVALID',
      requestId: 'req_support_1',
    });
    await expect(deleteTransaction('tx-1', 'csrf-token')).rejects.toThrow('Sua sessão não pôde ser validada.');
  });

  it('falls back to the status code when the error body is not JSON', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      headers: new Headers(),
      json: vi.fn().mockRejectedValue(new Error('bad json')),
    });

    await expect(updateTransaction('tx-1', {
      data: '2026-04-03',
      natureza: 'Essencial',
      categoria: 'Mercado',
      descricao: 'Compra',
      valor: 10,
      conta: 'Nubank',
      metodo_pagamento: 'Pix',
    }, 'csrf-token')).rejects.toThrow('Request failed with status 500');
  });

  it('maps stable backend error codes to user-friendly messages with support code', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 429,
      headers: new Headers({ 'X-Request-ID': 'req_auth_123' }),
      json: vi.fn().mockResolvedValue({
        status: 'error',
        message: 'Too many login requests. Try again later.',
        code: 'AUTH_MAGIC_LINK_RATE_LIMIT',
        retryable: true,
        retryAfterSeconds: 300,
      }),
    });

    await expect(requestMagicLink('admin@example.com', 'http://localhost/')).rejects.toMatchObject({
      name: 'ApiError',
      code: 'AUTH_MAGIC_LINK_RATE_LIMIT',
      status: 429,
      requestId: 'req_auth_123',
      retryable: true,
      retryAfterSeconds: 300,
    });
    await expect(requestMagicLink('admin@example.com', 'http://localhost/')).rejects.toThrow(
      'Muitos pedidos de login em pouco tempo. Aguarde alguns minutos e tente novamente. Codigo de suporte: req_auth_123'
    );
  });

  it('preserves a short safe error detail for malformed auth sessions', async () => {
    mockGetAccessToken.mockResolvedValue(buildMalformedToken());
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      headers: new Headers({ 'X-Request-ID': 'req_auth_bad_token' }),
      json: vi.fn().mockResolvedValue({
        status: 'error',
        code: 'AUTH_SESSION_TOKEN_MALFORMED',
        detail: 'bearer_malformed',
        message: 'Invalid or expired session.',
      }),
    });

    await expect(getTransactions()).rejects.toMatchObject({
      name: 'ApiError',
      code: 'AUTH_SESSION_TOKEN_MALFORMED',
      detail: 'bearer_malformed',
      requestId: 'req_auth_bad_token',
    });
    await expect(getTransactions()).rejects.toThrow(
      'Sua sessao de acesso e invalida. Faca login novamente. Codigo de suporte: req_auth_bad_token Detalhe: bearer_malformed',
    );
  });

  it('wraps network failures in a typed retryable error', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(getTransactions()).rejects.toMatchObject({
      name: 'ApiError',
      code: 'NETWORK_ERROR',
      retryable: true,
      status: 0,
    });
  });

  it('flags auth recovery errors for re-login flows', () => {
    expect(isReauthenticationError(new ApiError('x', {
      code: 'AUTH_SESSION_TOKEN_MALFORMED',
      detail: 'bearer_malformed',
      status: 401,
    }))).toBe(true);
    expect(isReauthenticationError(new ApiError('x', {
      code: 'ADMIN_DATA_LOAD_FAILED',
      status: 503,
    }))).toBe(false);
  });

  it('fails locally with a short diagnostic when the Pages runtime has no usable bearer token', async () => {
    mockGetAccessToken.mockResolvedValue(null);
    mockBrowserAdminTestSessionAllowed.mockReturnValue(false);

    const request = getTransactions();

    await expect(request).rejects.toMatchObject({
      name: 'ApiError',
      code: 'AUTH_SESSION_INVALID',
      diagnostic: 'auth_state_unusable',
      status: 401,
    });
    await expect(request).rejects.toThrow(
      'Sua sessao expirou. Faca login novamente. Diagnostico: auth_state_unusable',
    );
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('keeps the auth endpoints on the same origin and includes the JSON payload', async () => {
    mockGetAccessToken.mockResolvedValue('token-123');
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ status: 'ok', message: 'sent', loggedOut: true }),
    });

    await requestMagicLink('admin@example.com', 'http://localhost/');
    await logoutAuthSession();

    const [magicUrl, magicInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const [logoutUrl, logoutInit] = fetchMock.mock.calls[1] as [string, RequestInit];

    expect(magicUrl).toBe('/auth/magic-link');
    expect(logoutUrl).toBe('/auth/logout');
    expect(magicInit.method).toBe('POST');
    expect(logoutInit.method).toBe('POST');
    expect(new Headers(magicInit.headers).has('Authorization')).toBe(false);
    expect(new Headers(logoutInit.headers).has('Authorization')).toBe(false);
    expect(magicInit.credentials).toBe('include');
    expect(logoutInit.credentials).toBe('include');
  });

  it('covers the remaining admin methods with bearer auth', async () => {
    mockGetAccessToken.mockResolvedValue('token-789');
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({ status: 'ok', authenticated: true }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({ status: 'ok', items: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({ status: 'ok', id: 'pending-1' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({ status: 'ok', id: 'pending-2' }),
      });

    await getAuthSession();
    await getPendingReceipts();
    await approvePendingReceipt('pending-1', 'csrf-1');
    await rejectPendingReceipt('pending-2', 'csrf-2');

    expect(fetchMock.mock.calls[0][0]).toBe('/auth/session');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/admin/cache-aprovacao');
    expect(fetchMock.mock.calls[2][0]).toBe('/api/admin/cache-aprovacao/pending-1/approve');
    expect(fetchMock.mock.calls[3][0]).toBe('/api/admin/cache-aprovacao/pending-2/reject');
    expect(new Headers(fetchMock.mock.calls[2][1].headers).get('Authorization')).toBe('Bearer token-789');
    expect(new Headers(fetchMock.mock.calls[3][1].headers).get('Authorization')).toBe('Bearer token-789');
    expect(new Headers(fetchMock.mock.calls[2][1].headers).has('X-CSRF-Token')).toBe(false);
    expect(new Headers(fetchMock.mock.calls[3][1].headers).has('X-CSRF-Token')).toBe(false);
  });

  it('falls back to cookie csrf transport when no bearer token is available', async () => {
    mockGetAccessToken.mockResolvedValue(null);
    mockBrowserAdminTestSessionAllowed.mockReturnValue(true);
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ status: 'ok', transaction: { id: 'tx-1' } }),
    });

    await updateTransaction('tx-1', {
      data: '2026-04-03',
      natureza: 'Essencial',
      categoria: 'Mercado',
      descricao: 'Compra',
      valor: 10,
      conta: 'Nubank',
      metodo_pagamento: 'Pix',
    }, 'csrf-token');

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(init.credentials).toBe('include');
    expect(headers.get('X-CSRF-Token')).toBe('csrf-token');
    expect(headers.has('Authorization')).toBe(false);
  });
});

function buildMalformedToken() {
  return 'not-a-jwt';
}

import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  approvePendingReceipt,
  createTransaction,
  deleteTransaction,
  getAdminMe,
  getPendingReceipts,
  getTransactions,
  isReauthenticationError,
  rejectPendingReceipt,
  requestTestMagicLink,
  updateTransaction,
} from '@/features/admin/api';

const fetchMock = vi.fn();
const mockGetAccessToken = vi.fn();
const mockClearBrowserAuthState = vi.fn();
const mockEmitClientTelemetry = vi.fn();

vi.mock('@/features/auth/lib/supabaseBrowserSession', () => ({
  clearBrowserAuthState: (...args: unknown[]) => mockClearBrowserAuthState(...args),
  getAccessToken: (...args: unknown[]) => mockGetAccessToken(...args),
}));

vi.mock('@/features/observability/clientTelemetry', () => ({
  emitClientTelemetry: (...args: unknown[]) => mockEmitClientTelemetry(...args),
  ensureSupportCodeInMessage: (message: string, clientEventId?: string) =>
    clientEventId && !/codigo de suporte:/i.test(message)
      ? `${message} Codigo de suporte: ${clientEventId}`
      : message,
}));

describe('adminApi', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    mockGetAccessToken.mockReset();
    mockClearBrowserAuthState.mockReset();
    mockEmitClientTelemetry.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  it('sends bearer auth and query parameters for transaction listing', async () => {
    mockGetAccessToken.mockResolvedValue('token-123');
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ status: 'ok', transactions: [] }),
    });

    await getTransactions({ dateFrom: '2026-04-01', dateTo: '2026-04-30' });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/admin/gastos?date_from=2026-04-01&date_to=2026-04-30');
    expect(init.method).toBe('GET');
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer token-123');
  });

  it('uses /api/admin/me as the lightweight authorization handshake', async () => {
    mockGetAccessToken.mockResolvedValue('token-abc');
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        status: 'ok',
        authenticated: true,
        authorized: true,
        user: { id: 'user-1', email: 'admin@example.com' },
      }),
    });

    await getAdminMe();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/admin/me');
    expect(init.method).toBe('GET');
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer token-abc');
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
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(init.method).toBe('POST');
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(headers.get('Authorization')).toBe('Bearer token-456');
    expect(headers.has('X-CSRF-Token')).toBe(false);
  });

  it('surfaces backend error messages for failed requests', async () => {
    mockGetAccessToken.mockResolvedValue('token-403');
    fetchMock.mockResolvedValue({
      ok: false,
      status: 403,
      headers: new Headers({ 'X-Request-ID': 'req_support_1' }),
      json: vi.fn().mockResolvedValue({ message: 'Forbidden.', code: 'AUTH_ACCESS_DENIED' }),
    });

    await expect(deleteTransaction('tx-1')).rejects.toMatchObject({
      name: 'ApiError',
      code: 'AUTH_ACCESS_DENIED',
      requestId: 'req_support_1',
    });
    await expect(deleteTransaction('tx-1')).rejects.toThrow('Seu usuario nao esta autorizado a acessar o painel.');
  });

  it('preserves short safe auth details for malformed bearer sessions', async () => {
    mockGetAccessToken.mockResolvedValue('not-a-jwt');
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

  it('keeps the auth test endpoint on the same origin without bearer transport', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ status: 'ok', message: 'sent' }),
    });

    await requestTestMagicLink('admin@example.com', 'http://localhost/auth/callback');
    const [magicUrl, magicInit] = fetchMock.mock.calls[0] as [string, RequestInit];

    expect(magicUrl).toBe('/__test__/auth/magic-link');
    expect(new Headers(magicInit.headers).has('Authorization')).toBe(false);
    expect(magicInit.credentials).toBe('include');
  });

  it('covers the remaining admin methods with bearer auth', async () => {
    mockGetAccessToken.mockResolvedValue('token-789');
    fetchMock
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

    await getPendingReceipts();
    await approvePendingReceipt('pending-1');
    await rejectPendingReceipt('pending-2');

    expect(fetchMock.mock.calls[0][0]).toBe('/api/admin/cache-aprovacao');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/admin/cache-aprovacao/pending-1/approve');
    expect(fetchMock.mock.calls[2][0]).toBe('/api/admin/cache-aprovacao/pending-2/reject');
    expect(new Headers(fetchMock.mock.calls[1][1].headers).get('Authorization')).toBe('Bearer token-789');
    expect(new Headers(fetchMock.mock.calls[2][1].headers).get('Authorization')).toBe('Bearer token-789');
  });

  it('requires a usable bearer token for admin mutations in the published runtime', async () => {
    mockGetAccessToken.mockResolvedValue(null);

    const request = updateTransaction('tx-1', {
      data: '2026-04-03',
      natureza: 'Essencial',
      categoria: 'Mercado',
      descricao: 'Compra',
      valor: 10,
      conta: 'Nubank',
      metodo_pagamento: 'Pix',
    });

    await expect(request).rejects.toMatchObject({
      name: 'ApiError',
      code: 'AUTH_SESSION_INVALID',
      diagnostic: 'auth_state_unusable',
      status: 401,
    });
    expect(mockClearBrowserAuthState).toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('emits client telemetry and surfaces a client support code when the browser cannot reach the backend', async () => {
    mockGetAccessToken.mockResolvedValue('token-transport');
    mockEmitClientTelemetry.mockReturnValue('cli_transport_1');
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(getTransactions()).rejects.toMatchObject({
      name: 'ApiError',
      code: 'NETWORK_ERROR',
      status: 0,
      diagnostic: 'frontend_transport_failed',
      clientEventId: 'cli_transport_1',
    });
    await expect(getTransactions()).rejects.toThrow(
      'Nao foi possivel conectar ao servidor agora. Verifique sua conexao e tente novamente. Codigo de suporte: cli_transport_1 Diagnostico: frontend_transport_failed',
    );
    expect(mockEmitClientTelemetry).toHaveBeenCalledWith(expect.objectContaining({
      event: 'admin_api_transport_failed',
      phase: 'api_request',
      errorCode: 'NETWORK_ERROR',
      diagnostic: 'frontend_transport_failed',
    }));
  });
});

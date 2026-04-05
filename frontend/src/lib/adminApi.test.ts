import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  approvePendingReceipt,
  createTransaction,
  deleteTransaction,
  getAuthSession,
  getPendingReceipts,
  getTransactions,
  logoutAuthSession,
  rejectPendingReceipt,
  requestMagicLink,
  updateTransaction,
} from './adminApi';

const fetchMock = vi.fn();

describe('adminApi', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  it('sends browser credentials and query parameters for transaction listing', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ status: 'ok', transactions: [] }),
    });

    await getTransactions({ dateFrom: '2026-04-01', dateTo: '2026-04-30' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/admin/gastos?date_from=2026-04-01&date_to=2026-04-30');
    expect(init.credentials).toBe('include');
    expect(init.method).toBe('GET');
    expect(new Headers(init.headers).has('Authorization')).toBe(false);
  });

  it('adds JSON and CSRF headers for mutating admin requests', async () => {
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
    expect(init.credentials).toBe('include');
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(headers.get('X-CSRF-Token')).toBe('csrf-token');
    expect(headers.has('Authorization')).toBe(false);
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

  it('wraps network failures in a typed retryable error', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(getTransactions()).rejects.toMatchObject({
      name: 'ApiError',
      code: 'NETWORK_ERROR',
      retryable: true,
      status: 0,
    });
  });

  it('keeps the auth endpoints on the same origin and includes the JSON payload', async () => {
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
  });

  it('covers the remaining admin methods with credentials and csrf tokens', async () => {
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
    expect(new Headers(fetchMock.mock.calls[2][1].headers).get('X-CSRF-Token')).toBe('csrf-1');
    expect(new Headers(fetchMock.mock.calls[3][1].headers).get('X-CSRF-Token')).toBe('csrf-2');
  });
});

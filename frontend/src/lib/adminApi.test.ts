import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createTransaction,
  deleteTransaction,
  getTransactions,
  logoutAuthSession,
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
      json: vi.fn().mockResolvedValue({ message: 'Missing or invalid CSRF token.' }),
    });

    await expect(deleteTransaction('tx-1', 'csrf-token')).rejects.toThrow('Missing or invalid CSRF token.');
  });

  it('falls back to the status code when the error body is not JSON', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
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
});

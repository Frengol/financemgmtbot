import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as adminApi from '@/features/admin/api';
import {
  createRecurringExpense,
  deleteRecurringExpense,
  getRecurringExpenses,
  updateRecurringExpense,
} from '@/features/admin/api';
import type { RecurringExpenseDraft } from '@/lib/transactions';

const fetchMock = vi.fn();
const mockGetAccessToken = vi.fn();
const mockClearBrowserAuthState = vi.fn();

vi.mock('@/features/auth/lib/supabaseBrowserSession', () => ({
  clearBrowserAuthState: (...args: unknown[]) => mockClearBrowserAuthState(...args),
  getAccessToken: (...args: unknown[]) => mockGetAccessToken(...args),
}));

vi.mock('@/features/observability/clientTelemetry', () => ({
  emitClientTelemetry: vi.fn(),
  ensureSupportCodeInMessage: (message: string, clientEventId?: string) =>
    clientEventId && !/c[oó]digo de suporte:/i.test(message)
      ? `${message} Código de suporte: ${clientEventId}`
      : message,
}));

const sampleDraft: RecurringExpenseDraft = {
  nome: 'Netflix',
  valor: 39.9,
  mes_inicio: '2026-04-01',
  mes_fim: null,
  dia_mes: 5,
  natureza: 'Lazer',
  categoria: 'Diversão',
  metodo_pagamento: 'Cartao de Credito',
  conta: 'Nubank',
  ativo: true,
};

describe('recurring expenses API client', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    mockGetAccessToken.mockReset();
    mockClearBrowserAuthState.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  it('lists recurring expenses with bearer authentication', async () => {
    mockGetAccessToken.mockResolvedValue('token-list');
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ status: 'ok', items: [] }),
    });

    await getRecurringExpenses();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe('/api/admin/despesas-recorrentes');
    expect(init.method).toBe('GET');
    expect(headers.get('Authorization')).toBe('Bearer token-list');
  });

  it('strips natureza from create payload before sending', async () => {
    mockGetAccessToken.mockResolvedValue('token-create');
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ status: 'ok', recurring_expense: { id: 'rec-1' } }),
    });

    await createRecurringExpense(sampleDraft);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    const body = JSON.parse(String(init.body));
    expect(url).toBe('/api/admin/despesas-recorrentes');
    expect(init.method).toBe('POST');
    expect(headers.get('Authorization')).toBe('Bearer token-create');
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(body).not.toHaveProperty('natureza');
    expect(body).not.toHaveProperty('descricao');
    expect(body.nome).toBe('Netflix');
    expect(body.valor).toBe(39.9);
  });

  it('strips natureza from update payload and targets the right id', async () => {
    mockGetAccessToken.mockResolvedValue('token-update');
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ status: 'ok', recurring_expense: { id: 'rec-42' } }),
    });

    await updateRecurringExpense('rec-42', sampleDraft);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(url).toBe('/api/admin/despesas-recorrentes/rec-42');
    expect(init.method).toBe('PATCH');
    expect(body).not.toHaveProperty('natureza');
    expect(body).not.toHaveProperty('descricao');
    expect(body.dia_mes).toBe(5);
  });

  it('issues delete with the expense id in the URL', async () => {
    mockGetAccessToken.mockResolvedValue('token-delete');
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ status: 'ok', id: 'rec-7' }),
    });

    await deleteRecurringExpense('rec-7');

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/admin/despesas-recorrentes/rec-7');
    expect(init.method).toBe('DELETE');
  });

  it('does not expose a manual recurring expenses execution client', () => {
    expect(adminApi).not.toHaveProperty('executeRecurringExpenses');
  });

  it('surfaces backend error messages for create failures', async () => {
    mockGetAccessToken.mockResolvedValue('token-fail');
    fetchMock.mockResolvedValue({
      ok: false,
      status: 400,
      headers: new Headers({ 'X-Request-ID': 'req_recurring_invalid' }),
      json: vi.fn().mockResolvedValue({
        status: 'error',
        message: 'Recurring expense category is invalid.',
        code: 'VALIDATION_FAILED',
      }),
    });

    await expect(createRecurringExpense(sampleDraft)).rejects.toMatchObject({
      name: 'ApiError',
      code: 'VALIDATION_FAILED',
      requestId: 'req_recurring_invalid',
    });
  });

  it('surfaces 401 errors so the page can trigger re-authentication', async () => {
    mockGetAccessToken.mockResolvedValue('token-stale');
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      headers: new Headers({ 'X-Request-ID': 'req_recurring_401' }),
      json: vi.fn().mockResolvedValue({
        status: 'error',
        message: 'Invalid session.',
        code: 'AUTH_SESSION_TOKEN_MALFORMED',
        detail: 'bearer_malformed',
      }),
    });

    await expect(getRecurringExpenses()).rejects.toMatchObject({
      name: 'ApiError',
      code: 'AUTH_SESSION_TOKEN_MALFORMED',
      status: 401,
    });
  });
});

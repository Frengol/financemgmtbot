import { endOfMonth, eachWeekOfInterval } from 'date-fns';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import Dashboard from './Dashboard';
import { ApiError } from '@/features/admin/api';

const mockGetTransactions = vi.fn();
const mockUseAuth = vi.fn();
const mockSignOut = vi.fn();

vi.mock('@/features/admin/api', async () => {
  const actual = await vi.importActual<typeof import('@/features/admin/api')>('@/features/admin/api');
  return {
    ...actual,
    getTransactions: (...args: unknown[]) => mockGetTransactions(...args),
  };
});

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock('@tremor/react', () => ({
  AreaChart: ({ data, categories }: { data: Array<unknown>; categories: Array<string> }) => (
    <div data-testid="area-chart" data-categories={categories.join(',')}>
      {data.length}
    </div>
  ),
  BarChart: ({ data }: { data: Array<unknown> }) => <div data-testid="bar-chart">{data.length}</div>,
  DonutChart: ({ data }: { data: Array<unknown> }) => <div data-testid="donut-chart">{data.length}</div>,
}));

describe('Dashboard', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date('2026-04-12T12:00:00Z'));
    mockGetTransactions.mockReset();
    mockSignOut.mockReset();
    mockUseAuth.mockReturnValue({ authenticated: true, localBypass: false, signOut: mockSignOut });
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it('loads the top summary cards and filtered chart data for the selected month', async () => {
    mockGetTransactions.mockImplementation((query?: { dateFrom?: string; dateTo?: string }) => {
      if (query) {
        return Promise.resolve({
          transactions: [
            { data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 100 },
            { data: '2026-04-03', natureza: 'Lazer', categoria: 'Diversao', valor: 50 },
            { data: '2026-04-04', natureza: 'Receita', categoria: 'Salario', valor: 400 },
          ],
        });
      }

      return Promise.resolve({
        transactions: [
          { data: '2026-02-01', natureza: 'Receita', categoria: 'Salario', valor: 1000 },
          { data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 100 },
          { data: '2026-04-03', natureza: 'Lazer', categoria: 'Diversao', valor: 50 },
          { data: '2026-04-04', natureza: 'Receita', categoria: 'Salario', valor: 400 },
        ],
      });
    });

    render(<Dashboard />);

    await waitFor(() => {
      expect(mockGetTransactions).toHaveBeenCalledWith({
        dateFrom: '2026-04-01',
        dateTo: '2026-04-30',
      });
    });
    await waitFor(() => {
      expect(mockGetTransactions).toHaveBeenCalledWith();
    });

    expect(screen.getByText('Saldo atual')).toBeInTheDocument();
    expect(screen.getByText('Receitas do mês')).toBeInTheDocument();
    expect(screen.getByText('Gastos do mês')).toBeInTheDocument();
    expect(screen.getByText('Saldo do mês')).toBeInTheDocument();
    expect(screen.getByText('Entradas no mês de referência')).toBeInTheDocument();
    expect(screen.getByText('Saídas no mês de referência')).toBeInTheDocument();
    expect(screen.getByText('Resultado no mês de referência')).toBeInTheDocument();
    expect(screen.getByText('Período')).toBeInTheDocument();

    expect(within(screen.getByTestId('dashboard-kpi-current-balance')).getByText('R$ 1.250,00')).toBeInTheDocument();
    expect(within(screen.getByTestId('dashboard-kpi-month-income')).getByText('R$ 400,00')).toBeInTheDocument();
    expect(within(screen.getByTestId('dashboard-kpi-month-expenses')).getByText('R$ 150,00')).toBeInTheDocument();
    expect(within(screen.getByTestId('dashboard-kpi-month-balance')).getByText('R$ 250,00')).toBeInTheDocument();
    expect(within(screen.getByTestId('dashboard-kpi-month-balance')).getByText('Positivo')).toBeInTheDocument();
    expect(screen.getByTestId('area-chart')).toHaveTextContent('30');
    expect(screen.getByTestId('area-chart')).toHaveAttribute('data-categories', 'Receitas,Gastos,Saldo líquido');
    expect(screen.getAllByTestId('donut-chart')).toHaveLength(2);
    expect(screen.getByText('Receitas x gastos no tempo')).toBeInTheDocument();
    expect(screen.getByText('Gastos por categoria')).toBeInTheDocument();
    expect(screen.getByText('Receitas por categoria')).toBeInTheDocument();
    expect(screen.getByText('Essencial vs Lazer')).toBeInTheDocument();
    expect(screen.getByText('Maior gasto do mês')).toBeInTheDocument();
    expect(screen.queryByText('Gráfico principal')).not.toBeInTheDocument();
    expect(screen.queryByText('Composição')).not.toBeInTheDocument();
    expect(screen.queryByText('Saúde financeira')).not.toBeInTheDocument();
  });

  it('switches to total mode while keeping the monthly cards tied to the current month', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockGetTransactions.mockImplementation((query?: { dateFrom?: string; dateTo?: string }) => {
      if (query) {
        return Promise.resolve({
          transactions: [
            { data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 25 },
          ],
        });
      }

      return Promise.resolve({
        transactions: [
          { data: '2025-01-10', natureza: 'Essencial', categoria: 'Moradia', valor: 200 },
          { data: '2026-04-02', natureza: 'Lazer', categoria: 'Diversao', valor: 25 },
          { data: '2026-04-03', natureza: 'Receita', categoria: 'Salario', valor: 3000 },
        ],
      });
    });

    render(<Dashboard />);
    await waitFor(() => {
      expect(within(screen.getByTestId('dashboard-kpi-month-expenses')).getByText('R$ 25,00')).toBeInTheDocument();
    });

    await user.click(within(screen.getByTestId('dashboard-overview-period-picker')).getByRole('button', { name: /abr\/2026/i }));
    await user.click(screen.getByRole('button', { name: 'Total' }));

    await waitFor(() => {
      expect(mockGetTransactions).toHaveBeenLastCalledWith(undefined);
    });

    expect(screen.getAllByText('Desde o primeiro registro').length).toBeGreaterThan(0);
    expect(within(screen.getByTestId('dashboard-kpi-current-balance')).getByText('R$ 2.775,00')).toBeInTheDocument();
    expect(within(screen.getByTestId('dashboard-kpi-month-income')).getByText('R$ 3.000,00')).toBeInTheDocument();
    expect(within(screen.getByTestId('dashboard-kpi-month-expenses')).getByText('R$ 25,00')).toBeInTheDocument();
    expect(within(screen.getByTestId('dashboard-kpi-month-balance')).getByText('R$ 2.975,00')).toBeInTheDocument();
    expect(screen.getByText('Receitas x gastos no tempo')).toBeInTheDocument();
    expect(screen.getByTestId('area-chart')).toHaveTextContent('16');
  });

  it('applies a month range and switches the charts to weekly aggregation for medium periods', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const expectedWeekCount = eachWeekOfInterval(
      {
        start: new Date('2026-01-01T00:00:00'),
        end: endOfMonth(new Date('2026-04-01T00:00:00')),
      },
      { weekStartsOn: 1 },
    ).length;

    mockGetTransactions.mockImplementation((query?: { dateFrom?: string; dateTo?: string }) => {
      if (query?.dateFrom === '2026-04-01') {
        return Promise.resolve({
          transactions: [
            { data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 25 },
          ],
        });
      }

      if (query?.dateFrom === '2026-01-01') {
        return Promise.resolve({
          transactions: [
            { data: '2026-01-07', natureza: 'Essencial', categoria: 'Moradia', valor: 100 },
            { data: '2026-02-14', natureza: 'Lazer', categoria: 'Viagem', valor: 80 },
            { data: '2026-04-05', natureza: 'Essencial', categoria: 'Mercado', valor: 30 },
          ],
        });
      }

      return Promise.resolve({
        transactions: [
          { data: '2026-01-07', natureza: 'Essencial', categoria: 'Moradia', valor: 100 },
          { data: '2026-02-14', natureza: 'Lazer', categoria: 'Viagem', valor: 80 },
          { data: '2026-04-05', natureza: 'Essencial', categoria: 'Mercado', valor: 30 },
          { data: '2026-04-09', natureza: 'Receita', categoria: 'Salario', valor: 400 },
        ],
      });
    });

    render(<Dashboard />);
    await waitFor(() => {
      expect(within(screen.getByTestId('dashboard-kpi-month-expenses')).getByText('R$ 30,00')).toBeInTheDocument();
    });

    await user.click(within(screen.getByTestId('dashboard-overview-period-picker')).getByRole('button', { name: /abr\/2026/i }));
    await user.click(screen.getByRole('tab', { name: 'Filtro' }));
    await user.click(screen.getByRole('button', { name: /^Inicio/i }));
    await user.click(screen.getByRole('button', { name: /^Jan$/i }));
    await user.click(screen.getByRole('button', { name: /^Abr$/i }));

    await waitFor(() => {
      expect(mockGetTransactions).toHaveBeenCalledWith({
        dateFrom: '2026-01-01',
        dateTo: '2026-04-30',
      });
    });

    expect(screen.getAllByText('Jan/2026 - Abr/2026').length).toBeGreaterThan(0);
    expect(screen.getByText('Receitas x gastos no tempo')).toBeInTheDocument();
    expect(within(screen.getByTestId('dashboard-kpi-current-balance')).getByText('R$ 190,00')).toBeInTheDocument();
    expect(within(screen.getByTestId('dashboard-kpi-month-income')).getByText('R$ 400,00')).toBeInTheDocument();
    expect(within(screen.getByTestId('dashboard-kpi-month-expenses')).getByText('R$ 30,00')).toBeInTheDocument();
    expect(within(screen.getByTestId('dashboard-kpi-month-balance')).getByText('R$ 370,00')).toBeInTheDocument();
    expect(screen.getByTestId('area-chart')).toHaveTextContent(String(expectedWeekCount));
  });

  it('refreshes the data when transactions change', async () => {
    mockGetTransactions
      .mockResolvedValueOnce({
        transactions: [{ data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 10 }],
      })
      .mockResolvedValueOnce({
        transactions: [{ data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 10 }],
      })
      .mockResolvedValueOnce({
        transactions: [{ data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 20 }],
      })
      .mockResolvedValueOnce({
        transactions: [{ data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 20 }],
      });

    render(<Dashboard />);
    await waitFor(() => {
      expect(within(screen.getByTestId('dashboard-kpi-month-expenses')).getByText('R$ 10,00')).toBeInTheDocument();
    });

    window.dispatchEvent(new CustomEvent('transactions:changed'));

    await waitFor(() => {
      expect(within(screen.getByTestId('dashboard-kpi-month-expenses')).getByText('R$ 20,00')).toBeInTheDocument();
    });
  });

  it('falls back to zeroed metrics when the request fails', async () => {
    mockGetTransactions.mockRejectedValue(new Error('Nao foi possivel carregar os dados agora. Codigo de suporte: req_dash_1'));

    render(<Dashboard />);

    expect(await screen.findByText(/Nao foi possivel carregar os dados agora/i)).toBeInTheDocument();
    expect(screen.getByText(/Codigo de suporte: req_dash_1/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tentar novamente' })).toBeInTheDocument();
  });

  it('uses the generic dashboard error when the rejection is not an Error instance', async () => {
    mockGetTransactions.mockRejectedValue('falha-crua');

    render(<Dashboard />);

    expect(await screen.findByText('Nao foi possivel carregar os dados agora.')).toBeInTheDocument();
  });

  it('shows zeroed charts when the backend returns no transaction payload', async () => {
    mockGetTransactions.mockResolvedValue({});

    render(<Dashboard />);

    expect((await screen.findAllByText('R$ 0,00')).length).toBeGreaterThanOrEqual(6);
    expect(screen.getByTestId('area-chart')).toHaveTextContent('0');
    expect(screen.queryAllByTestId('donut-chart')).toHaveLength(0);
    expect(screen.getByText('Nenhum gasto no período analítico.')).toBeInTheDocument();
    expect(screen.getByText('Nenhuma receita no período analítico.')).toBeInTheDocument();
  });

  it('renders a revenue fallback when the filtered period has no income records', async () => {
    mockGetTransactions.mockImplementation((query?: { dateFrom?: string; dateTo?: string }) => {
      if (query) {
        return Promise.resolve({
          transactions: [
            { data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 90 },
            { data: '2026-04-03', natureza: 'Lazer', categoria: 'Diversao', valor: 40 },
          ],
        });
      }

      return Promise.resolve({
        transactions: [
          { data: '2026-03-01', natureza: 'Receita', categoria: 'Salario', valor: 1200 },
          { data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 90 },
          { data: '2026-04-03', natureza: 'Lazer', categoria: 'Diversao', valor: 40 },
        ],
      });
    });

    render(<Dashboard />);

    expect(await screen.findByText('Nenhuma receita no período analítico.')).toBeInTheDocument();
    expect(screen.getAllByTestId('donut-chart')).toHaveLength(1);
  });

  it('shows a positive monthly insight when the reference month has income but no expenses', async () => {
    mockGetTransactions.mockImplementation((query?: { dateFrom?: string; dateTo?: string }) => {
      if (query) {
        return Promise.resolve({
          transactions: [
            { data: '2026-04-09', natureza: 'Receita', categoria: 'Salario', valor: 1800 },
          ],
        });
      }

      return Promise.resolve({
        transactions: [
          { data: '2026-04-09', natureza: 'Receita', categoria: 'Salario', valor: 1800 },
        ],
      });
    });

    render(<Dashboard />);

    expect(await screen.findByText('Receitas sem gastos no mês')).toBeInTheDocument();
    expect(within(screen.getByTestId('dashboard-kpi-month-balance')).getByText('Positivo')).toBeInTheDocument();
    expect(screen.getByText('Nenhum gasto no período analítico.')).toBeInTheDocument();
  });

  it('shows a negative monthly insight when expenses exceed income in the reference month', async () => {
    mockGetTransactions.mockImplementation((query?: { dateFrom?: string; dateTo?: string }) => {
      if (query) {
        return Promise.resolve({
          transactions: [
            { data: '2026-04-03', natureza: 'Receita', categoria: 'Freelance', valor: 150 },
            { data: '2026-04-04', natureza: 'Essencial', categoria: 'Mercado', valor: 300 },
          ],
        });
      }

      return Promise.resolve({
        transactions: [
          { data: '2026-04-03', natureza: 'Receita', categoria: 'Freelance', valor: 150 },
          { data: '2026-04-04', natureza: 'Essencial', categoria: 'Mercado', valor: 300 },
        ],
      });
    });

    render(<Dashboard />);

    expect(await screen.findByText('Gastos superam receitas em R$ 150,00')).toBeInTheDocument();
    expect(within(screen.getByTestId('dashboard-kpi-month-balance')).getByText('Negativo')).toBeInTheDocument();
  });

  it('skips dashboard loading when the admin session is not available', async () => {
    mockUseAuth.mockReturnValue({ authenticated: false, localBypass: false });

    render(<Dashboard />);

    expect((await screen.findAllByText('R$ 0,00')).length).toBeGreaterThanOrEqual(6);
    expect(mockGetTransactions).not.toHaveBeenCalled();
  });

  it('retries the request after an error', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockGetTransactions
      .mockRejectedValueOnce(new Error('Nao foi possivel carregar os dados agora. Codigo de suporte: req_dash_retry'))
      .mockResolvedValueOnce({
        transactions: [{ data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 42 }],
      })
      .mockResolvedValueOnce({
        transactions: [{ data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 42 }],
      });

    render(<Dashboard />);

    expect(await screen.findByText(/Codigo de suporte: req_dash_retry/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Tentar novamente' }));

    await waitFor(() => {
      expect(within(screen.getByTestId('dashboard-kpi-month-expenses')).getByText('R$ 42,00')).toBeInTheDocument();
    });
  });

  it('shows a re-login action instead of retry for malformed auth sessions', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockGetTransactions.mockRejectedValue(new ApiError(
      'Sua sessao de acesso e invalida. Faca login novamente. Codigo de suporte: req_dash_auth Detalhe: bearer_malformed',
      {
        code: 'AUTH_SESSION_TOKEN_MALFORMED',
        detail: 'bearer_malformed',
        status: 401,
        requestId: 'req_dash_auth',
      },
    ));

    render(<Dashboard />);

    expect(await screen.findByText(/detalhe: bearer_malformed/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Fazer login novamente' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Tentar novamente' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Fazer login novamente' }));

    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });
});

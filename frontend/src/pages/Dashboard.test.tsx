import { endOfMonth, eachWeekOfInterval } from 'date-fns';
import { render, screen, waitFor } from '@testing-library/react';
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
  AreaChart: ({ data }: { data: Array<unknown> }) => <div data-testid="area-chart">{data.length}</div>,
  BarChart: ({ data }: { data: Array<unknown> }) => <div data-testid="bar-chart">{data.length}</div>,
  Card: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
  DonutChart: ({ data }: { data: Array<unknown> }) => <div data-testid="donut-chart">{data.length}</div>,
  Grid: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Metric: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Text: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  Title: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
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

  it('loads KPI totals and daily chart data for the selected month', async () => {
    mockGetTransactions.mockResolvedValue({
      transactions: [
        { data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 100 },
        { data: '2026-04-03', natureza: 'Lazer', categoria: 'Diversao', valor: 50 },
        { data: '2026-04-04', natureza: 'Receita', categoria: 'Salario', valor: 999 },
      ],
    });

    render(<Dashboard />);

    await waitFor(() => {
      expect(mockGetTransactions).toHaveBeenCalledWith({
        dateFrom: '2026-04-01',
        dateTo: '2026-04-30',
      });
    });

    expect(await screen.findByText('R$ 150,00')).toBeInTheDocument();
    expect(screen.getByText('R$ 100,00')).toBeInTheDocument();
    expect(screen.getByText('R$ 50,00')).toBeInTheDocument();
    expect(screen.getByTestId('area-chart')).toHaveTextContent('30');
    expect(screen.getByTestId('bar-chart')).toHaveTextContent('30');
    expect(screen.getByText('Gastos por Dia')).toBeInTheDocument();
  });

  it('switches to the all-time total mode from the popover', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockGetTransactions
      .mockResolvedValueOnce({
        transactions: [
          { data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 25 },
        ],
      })
      .mockResolvedValueOnce({
        transactions: [
          { data: '2025-01-10', natureza: 'Essencial', categoria: 'Moradia', valor: 200 },
          { data: '2026-04-02', natureza: 'Lazer', categoria: 'Diversao', valor: 25 },
          { data: '2026-04-03', natureza: 'Receita', categoria: 'Salario', valor: 3000 },
        ],
      });

    render(<Dashboard />);
    expect(await screen.findAllByText('R$ 25,00')).toHaveLength(2);

    await user.click(screen.getAllByRole('button', { name: /abr\/2026/i })[0]);
    await user.click(screen.getByRole('button', { name: 'Total' }));

    await waitFor(() => {
      expect(mockGetTransactions).toHaveBeenLastCalledWith(undefined);
    });

    expect(screen.getAllByText('Desde o primeiro registro').length).toBeGreaterThan(0);
    expect(screen.getByText('R$ 225,00')).toBeInTheDocument();
    expect(screen.getByText('Gastos por Mes')).toBeInTheDocument();
    expect(screen.getByTestId('area-chart')).toHaveTextContent('16');
    expect(screen.getByTestId('bar-chart')).toHaveTextContent('16');
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

    mockGetTransactions
      .mockResolvedValueOnce({
        transactions: [
          { data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 25 },
        ],
      })
      .mockResolvedValueOnce({
        transactions: [
          { data: '2026-01-07', natureza: 'Essencial', categoria: 'Moradia', valor: 100 },
          { data: '2026-02-14', natureza: 'Lazer', categoria: 'Viagem', valor: 80 },
          { data: '2026-04-05', natureza: 'Essencial', categoria: 'Mercado', valor: 30 },
        ],
      });

    render(<Dashboard />);
    expect(await screen.findAllByText('R$ 25,00')).toHaveLength(2);

    await user.click(screen.getAllByRole('button', { name: /abr\/2026/i })[0]);
    await user.click(screen.getByRole('tab', { name: 'Filtro' }));
    await user.click(screen.getByRole('button', { name: /^Inicio/i }));
    await user.click(screen.getByRole('button', { name: /^Jan$/i }));
    await user.click(screen.getByRole('button', { name: /^Abr$/i }));

    await waitFor(() => {
      expect(mockGetTransactions).toHaveBeenLastCalledWith({
        dateFrom: '2026-01-01',
        dateTo: '2026-04-30',
      });
    });

    expect(screen.getAllByText('Jan/2026 - Abr/2026').length).toBeGreaterThan(0);
    expect(screen.getByText('Gastos por Semana')).toBeInTheDocument();
    expect(screen.getByText('R$ 210,00')).toBeInTheDocument();
    expect(screen.getByTestId('area-chart')).toHaveTextContent(String(expectedWeekCount));
    expect(screen.getByTestId('bar-chart')).toHaveTextContent(String(expectedWeekCount));
  });

  it('refreshes the data when transactions change', async () => {
    mockGetTransactions
      .mockResolvedValueOnce({
        transactions: [{ data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 10 }],
      })
      .mockResolvedValueOnce({
        transactions: [{ data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 20 }],
      });

    render(<Dashboard />);
    expect(await screen.findAllByText('R$ 10,00')).toHaveLength(2);

    window.dispatchEvent(new CustomEvent('transactions:changed'));

    await waitFor(() => {
      expect(screen.getAllByText('R$ 20,00')).toHaveLength(2);
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

    expect(await screen.findAllByText('R$ 0,00')).toHaveLength(3);
    expect(screen.getByTestId('area-chart')).toHaveTextContent('0');
    expect(screen.getByTestId('donut-chart')).toHaveTextContent('0');
    expect(screen.getByTestId('bar-chart')).toHaveTextContent('0');
  });

  it('skips dashboard loading when the admin session is not available', async () => {
    mockUseAuth.mockReturnValue({ authenticated: false, localBypass: false });

    render(<Dashboard />);

    expect(await screen.findAllByText('R$ 0,00')).toHaveLength(3);
    expect(mockGetTransactions).not.toHaveBeenCalled();
  });

  it('retries the request after an error', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockGetTransactions
      .mockRejectedValueOnce(new Error('Nao foi possivel carregar os dados agora. Codigo de suporte: req_dash_retry'))
      .mockResolvedValueOnce({
        transactions: [{ data: '2026-04-02', natureza: 'Essencial', categoria: 'Mercado', valor: 42 }],
      });

    render(<Dashboard />);

    expect(await screen.findByText(/Codigo de suporte: req_dash_retry/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Tentar novamente' }));

    await waitFor(() => {
      expect(screen.getAllByText('R$ 42,00')).toHaveLength(2);
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

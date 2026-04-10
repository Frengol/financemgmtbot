import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
    mockGetTransactions.mockReset();
    mockSignOut.mockReset();
    mockUseAuth.mockReturnValue({ authenticated: true, localBypass: false, signOut: mockSignOut });
  });

  it('loads KPI totals and chart data for the selected month', async () => {
    mockGetTransactions.mockResolvedValue({
      transactions: [
        { data: '2026-03-02', natureza: 'Essencial', categoria: 'Mercado', valor: 100 },
        { data: '2026-03-03', natureza: 'Lazer', categoria: 'Diversão', valor: 50 },
        { data: '2026-03-04', natureza: 'Receita', categoria: 'Salário', valor: 999 },
      ],
    });

    render(<Dashboard />);

    expect(await screen.findByText('R$ 150,00')).toBeInTheDocument();
    expect(screen.getByText('R$ 100,00')).toBeInTheDocument();
    expect(screen.getByText('R$ 50,00')).toBeInTheDocument();
    expect(screen.getByTestId('area-chart')).toBeInTheDocument();
    expect(screen.getByTestId('donut-chart')).toBeInTheDocument();
    expect(screen.getByTestId('bar-chart')).toBeInTheDocument();
  });

  it('refreshes the data when transactions change', async () => {
    mockGetTransactions
      .mockResolvedValueOnce({
        transactions: [{ data: '2026-03-02', natureza: 'Essencial', categoria: 'Mercado', valor: 10 }],
      })
      .mockResolvedValueOnce({
        transactions: [{ data: '2026-03-02', natureza: 'Essencial', categoria: 'Mercado', valor: 20 }],
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
    mockGetTransactions
      .mockRejectedValueOnce(new Error('Nao foi possivel carregar os dados agora. Codigo de suporte: req_dash_retry'))
      .mockResolvedValueOnce({
        transactions: [{ data: '2026-03-02', natureza: 'Essencial', categoria: 'Mercado', valor: 42 }],
      });

    render(<Dashboard />);

    expect(await screen.findByText(/Codigo de suporte: req_dash_retry/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Tentar novamente' }));

    await waitFor(() => {
      expect(screen.getAllByText('R$ 42,00')).toHaveLength(2);
    });
  });

  it('shows a re-login action instead of retry for malformed auth sessions', async () => {
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

    await userEvent.click(screen.getByRole('button', { name: 'Fazer login novamente' }));

    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });
});

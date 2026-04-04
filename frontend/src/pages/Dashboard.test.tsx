import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Dashboard from './Dashboard';

const mockGetTransactions = vi.fn();
const mockUseAuth = vi.fn();

vi.mock('@/lib/adminApi', () => ({
  getTransactions: (...args: unknown[]) => mockGetTransactions(...args),
}));

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
    mockUseAuth.mockReturnValue({ authenticated: true });
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
    mockGetTransactions.mockRejectedValue(new Error('network'));

    render(<Dashboard />);

    expect(await screen.findAllByText('R$ 0,00')).toHaveLength(3);
  });
});

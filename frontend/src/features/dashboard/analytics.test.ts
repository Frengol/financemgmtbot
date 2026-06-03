import { describe, expect, it } from 'vitest';

import {
  EMPTY_SUMMARY,
  buildCategoryData,
  buildFinancialTimeSeries,
  buildInsights,
  buildRevenueVsExpenseMessage,
  buildSplitMetrics,
  calculateCurrentBalance,
  formatPeriodLabel,
  granularityLabel,
  normalizeDashboardTransaction,
  resolveChartGranularity,
  resolveMonthlyStatus,
  resolvePeriodBounds,
  resolvePeriodQuery,
  summarizeMonthlySnapshot,
  summarizePeriod,
  type DashboardTransaction,
} from './analytics';
import type { DashboardPeriod } from '@/components/DashboardPeriodPicker';
import type { TransactionRecord } from '@/lib/transactions';

function tx(overrides: Partial<TransactionRecord>): DashboardTransaction {
  return normalizeDashboardTransaction({
    id: overrides.id || crypto.randomUUID(),
    data: overrides.data || '2026-04-05',
    natureza: overrides.natureza || 'Essencial',
    categoria: overrides.categoria || 'Mercado',
    descricao: overrides.descricao || 'Teste',
    valor: overrides.valor ?? 10,
    conta: overrides.conta || 'Nubank',
    metodo_pagamento: overrides.metodo_pagamento || 'Pix',
  });
}

describe('dashboard analytics', () => {
  it('summarizes current balance, monthly snapshot and categories without React', () => {
    const records = [
      tx({ data: '2026-04-05', natureza: 'Receita', categoria: 'Salário', valor: 5000 }),
      tx({ data: '2026-04-06', natureza: 'Essencial', categoria: 'Mercado', valor: 600 }),
      tx({ data: '2026-04-07', natureza: 'Lazer', categoria: 'Diversão', valor: 120 }),
    ];

    expect(calculateCurrentBalance(records)).toBe(4280);
    expect(summarizeMonthlySnapshot(records, new Date('2026-04-01T00:00:00'))).toEqual({
      income: 5000,
      expenses: 720,
      balance: 4280,
    });

    const summary = summarizePeriod(records);
    expect(summary.net).toBe(4280);
    expect(summary.expenseCategories.map((item) => item.name)).toEqual(['Mercado', 'Diversão']);
    expect(summary.incomeCategories[0]).toMatchObject({ name: 'Salário', value: 5000 });
  });

  it('builds period query and time series buckets for a selected range', () => {
    const period: DashboardPeriod = {
      kind: 'range',
      startMonth: new Date('2026-04-01T00:00:00'),
      endMonth: new Date('2026-05-01T00:00:00'),
    };
    const records = [
      tx({ data: '2026-04-05', natureza: 'Receita', valor: 100 }),
      tx({ data: '2026-05-05', natureza: 'Essencial', valor: 40 }),
    ];
    const bounds = resolvePeriodBounds(period, records);

    expect(resolvePeriodQuery(period)).toEqual({ dateFrom: '2026-04-01', dateTo: '2026-05-31' });
    expect(resolveChartGranularity(bounds)).toBe('day');
    expect(buildFinancialTimeSeries(records, bounds, 'month')).toEqual([
      { period: 'Abr/26', Receitas: 100, Gastos: 0, 'Saldo líquido': 100 },
      { period: 'Mai/26', Receitas: 0, Gastos: 40, 'Saldo líquido': -40 },
    ]);
  });

  it('handles empty periods, all-time periods and wider chart granularities', () => {
    const allPeriod: DashboardPeriod = { kind: 'all' };
    const reversedRange: DashboardPeriod = {
      kind: 'range',
      startMonth: new Date('2026-08-01T00:00:00'),
      endMonth: new Date('2026-01-01T00:00:00'),
    };

    expect(resolvePeriodQuery(allPeriod)).toBeUndefined();
    expect(resolvePeriodBounds(allPeriod, [])).toBeNull();
    expect(resolveChartGranularity(null)).toBe('day');
    expect(buildFinancialTimeSeries([], null, 'day')).toEqual([]);
    expect(buildCategoryData([], 'expense')).toEqual([]);
    expect(formatPeriodLabel(allPeriod)).toBe('Desde o primeiro registro');
    expect(resolvePeriodQuery(reversedRange)).toEqual({ dateFrom: '2026-01-01', dateTo: '2026-08-31' });

    expect(resolveChartGranularity({
      start: new Date('2026-01-01T00:00:00'),
      end: new Date('2026-05-31T00:00:00'),
    })).toBe('week');
    expect(resolveChartGranularity({
      start: new Date('2026-01-01T00:00:00'),
      end: new Date('2026-08-31T00:00:00'),
    })).toBe('month');
    expect(granularityLabel('day')).toBe('dia');
    expect(granularityLabel('week')).toBe('semana');
    expect(granularityLabel('month')).toBe('mês');
  });

  it('summarizes other expenses and split metrics without UI dependencies', () => {
    const summary = summarizePeriod([
      tx({ natureza: 'Essencial', categoria: 'Mercado', valor: 60 }),
      tx({ natureza: 'Lazer', categoria: 'Diversão', valor: 30 }),
      tx({ natureza: 'Outros', categoria: 'Outros', valor: 10 }),
    ]);

    expect(summary.otherExpenses).toBe(10);
    expect(buildSplitMetrics(EMPTY_SUMMARY)).toEqual([
      { label: 'Essencial', value: 0, share: 0, tone: 'neutral' },
      { label: 'Lazer', value: 0, share: 0, tone: 'neutral' },
    ]);
    expect(buildSplitMetrics(summary).map((item) => item.label)).toEqual(['Essencial', 'Lazer', 'Outros']);
  });

  it('builds revenue versus expense messages for neutral, missing and positive cases', () => {
    expect(buildRevenueVsExpenseMessage({ income: 0, expenses: 0, balance: 0 })).toEqual({
      value: 'Sem movimentações no mês',
      tone: 'neutral',
    });
    expect(buildRevenueVsExpenseMessage({ income: 0, expenses: 30, balance: -30 })).toEqual({
      value: 'Sem receitas registradas no mês',
      tone: 'negative',
    });
    expect(buildRevenueVsExpenseMessage({ income: 200, expenses: 0, balance: 200 })).toEqual({
      value: 'Receitas sem gastos no mês',
      tone: 'positive',
    });
    expect(buildRevenueVsExpenseMessage({ income: 200, expenses: 50, balance: 150 })).toEqual({
      value: 'Gastos consomem 25% das receitas',
      tone: 'positive',
    });
    expect(resolveMonthlyStatus(0)).toEqual({ label: 'Neutro', tone: 'neutral' });
    expect(resolveMonthlyStatus(10)).toEqual({ label: 'Positivo', tone: 'positive' });
  });

  it('builds stable quick insights from month records and period summary', () => {
    const records = [
      tx({ data: '2026-04-05', natureza: 'Essencial', categoria: 'Mercado', valor: 400 }),
      tx({ data: '2026-04-06', natureza: 'Lazer', categoria: 'Diversão', valor: 50 }),
    ];

    const insights = buildInsights(records, summarizePeriod(records), {
      income: 100,
      expenses: 450,
      balance: -350,
    });

    expect(insights.map((item) => item.label)).toEqual([
      'Maior gasto do mês',
      'Categoria com maior peso',
      'Estado do mês',
      'Receita versus gasto',
    ]);
    expect(insights[0].value).toBe('Mercado · R$ 400,00');
    expect(insights[2]).toMatchObject({ value: 'Negativo', tone: 'negative' });
  });
});

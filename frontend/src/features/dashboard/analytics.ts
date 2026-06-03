import {
  differenceInCalendarMonths,
  eachDayOfInterval,
  eachMonthOfInterval,
  eachWeekOfInterval,
  endOfMonth,
  format,
  isAfter,
  isBefore,
  startOfMonth,
  startOfWeek,
} from 'date-fns';
import { ptBR } from 'date-fns/locale';

import type { DashboardPeriod } from '@/components/DashboardPeriodPicker';
import { formatCategoryLabel, type TransactionRecord } from '@/lib/transactions';

export type DashboardTransaction = TransactionRecord & {
  recordDate: Date;
};

export type DashboardMonthlySnapshot = {
  income: number;
  expenses: number;
  balance: number;
};

export type TimeSeriesPoint = {
  period: string;
  Receitas: number;
  Gastos: number;
  'Saldo líquido': number;
};

export type DonutPoint = {
  name: string;
  value: number;
  share: number;
};

export type DashboardPeriodSummary = {
  income: number;
  expenses: number;
  net: number;
  essential: number;
  leisure: number;
  otherExpenses: number;
  expenseCategories: DonutPoint[];
  incomeCategories: DonutPoint[];
};

export type QuickInsight = {
  label: string;
  value: string;
  tone: 'neutral' | 'positive' | 'negative';
};

export type SplitMetric = {
  label: string;
  value: number;
  share: number;
  tone: 'neutral' | 'positive' | 'negative';
};

export type PeriodBounds = {
  start: Date;
  end: Date;
};

export type ChartGranularity = 'day' | 'week' | 'month';

export const EMPTY_SUMMARY: DashboardPeriodSummary = {
  income: 0,
  expenses: 0,
  net: 0,
  essential: 0,
  leisure: 0,
  otherExpenses: 0,
  expenseCategories: [],
  incomeCategories: [],
};

export function normalizeMonth(date: Date) {
  return startOfMonth(date);
}

export function toMonthRange(referenceDate: Date) {
  return {
    start: startOfMonth(referenceDate),
    end: endOfMonth(referenceDate),
  };
}

export function formatCurrency(value: number) {
  return `R$ ${value.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;
}

export function formatPercent(value: number) {
  return `${Math.round(value)}%`;
}

export function formatMonthLabel(value: Date, token = 'MMM/yyyy') {
  const label = format(value, token, { locale: ptBR });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export function formatMonthChip(value: Date) {
  return formatMonthLabel(value);
}

export function formatPeriodLabel(period: DashboardPeriod) {
  if (period.kind === 'month') {
    return formatMonthLabel(period.month);
  }

  if (period.kind === 'all') {
    return 'Desde o primeiro registro';
  }

  return `${formatMonthLabel(period.startMonth)} - ${formatMonthLabel(period.endMonth)}`;
}

export function parseTransactionDate(value: string) {
  return new Date(`${value}T00:00:00`);
}

export function normalizeDashboardTransaction(record: TransactionRecord): DashboardTransaction {
  return {
    ...record,
    categoria: record.categoria || 'Outros',
    conta: record.conta || 'Nao Informada',
    metodo_pagamento: record.metodo_pagamento || 'Outros',
    recordDate: parseTransactionDate(record.data),
  };
}

export function resolveFirstRecordDate(records: DashboardTransaction[]) {
  if (records.length === 0) {
    return null;
  }

  return records.reduce((earliest, currentRecord) => (
    isBefore(currentRecord.recordDate, earliest) ? currentRecord.recordDate : earliest
  ), records[0].recordDate);
}

export function resolvePeriodQuery(period: DashboardPeriod) {
  if (period.kind === 'all') {
    return undefined;
  }

  if (period.kind === 'month') {
    const { start, end } = toMonthRange(period.month);
    return {
      dateFrom: format(start, 'yyyy-MM-dd'),
      dateTo: format(end, 'yyyy-MM-dd'),
    };
  }

  const [startMonth, endMonth] = isAfter(period.startMonth, period.endMonth)
    ? [period.endMonth, period.startMonth]
    : [period.startMonth, period.endMonth];

  return {
    dateFrom: format(startOfMonth(startMonth), 'yyyy-MM-dd'),
    dateTo: format(endOfMonth(endMonth), 'yyyy-MM-dd'),
  };
}

export function resolvePeriodBounds(period: DashboardPeriod, records: DashboardTransaction[]) {
  if (period.kind === 'month') {
    return toMonthRange(period.month);
  }

  if (period.kind === 'range') {
    const [startMonth, endMonth] = isAfter(period.startMonth, period.endMonth)
      ? [period.endMonth, period.startMonth]
      : [period.startMonth, period.endMonth];

    return {
      start: startOfMonth(startMonth),
      end: endOfMonth(endMonth),
    };
  }

  const firstRecordDate = resolveFirstRecordDate(records);
  if (!firstRecordDate) {
    return null;
  }

  return {
    start: firstRecordDate,
    end: new Date(),
  };
}

export function isWithinBounds(recordDate: Date, bounds: PeriodBounds) {
  return !isBefore(recordDate, bounds.start) && !isAfter(recordDate, bounds.end);
}

export function resolveChartGranularity(bounds: PeriodBounds | null): ChartGranularity {
  if (!bounds) {
    return 'day';
  }

  const monthSpan = differenceInCalendarMonths(bounds.end, bounds.start) + 1;
  if (monthSpan <= 3) {
    return 'day';
  }
  if (monthSpan <= 6) {
    return 'week';
  }
  return 'month';
}

export function buildBucketKey(recordDate: Date, granularity: ChartGranularity) {
  if (granularity === 'day') {
    return format(recordDate, 'yyyy-MM-dd');
  }

  if (granularity === 'week') {
    return format(startOfWeek(recordDate, { weekStartsOn: 1 }), 'yyyy-MM-dd');
  }

  return format(startOfMonth(recordDate), 'yyyy-MM');
}

export function buildBucketLabel(bucketDate: Date, granularity: ChartGranularity) {
  if (granularity === 'day') {
    return format(bucketDate, 'dd/MM');
  }

  if (granularity === 'week') {
    return format(startOfWeek(bucketDate, { weekStartsOn: 1 }), 'dd/MM');
  }

  return formatMonthLabel(bucketDate, 'MMM/yy');
}

export function buildTimeBuckets(bounds: PeriodBounds, granularity: ChartGranularity) {
  if (granularity === 'day') {
    return eachDayOfInterval(bounds);
  }

  if (granularity === 'week') {
    return eachWeekOfInterval(bounds, { weekStartsOn: 1 });
  }

  return eachMonthOfInterval(bounds);
}

export function buildFinancialTimeSeries(
  records: DashboardTransaction[],
  bounds: PeriodBounds | null,
  granularity: ChartGranularity,
) {
  if (!bounds) {
    return [];
  }

  const totalsByBucket = records.reduce<Record<string, { income: number; expenses: number }>>((accumulator, item) => {
    const bucketKey = buildBucketKey(item.recordDate, granularity);
    const currentBucket = accumulator[bucketKey] || { income: 0, expenses: 0 };
    const value = Number(item.valor) || 0;

    if (item.natureza === 'Receita') {
      currentBucket.income += value;
    } else {
      currentBucket.expenses += value;
    }

    accumulator[bucketKey] = currentBucket;
    return accumulator;
  }, {});

  return buildTimeBuckets(bounds, granularity).map((bucketDate) => {
    const key = buildBucketKey(bucketDate, granularity);
    const currentBucket = totalsByBucket[key] || { income: 0, expenses: 0 };

    return {
      period: buildBucketLabel(bucketDate, granularity),
      Receitas: currentBucket.income,
      Gastos: currentBucket.expenses,
      'Saldo líquido': currentBucket.income - currentBucket.expenses,
    };
  });
}

export function buildCategoryData(records: DashboardTransaction[], type: 'income' | 'expense') {
  const categories = records.reduce<Record<string, number>>((accumulator, item) => {
    const isIncome = item.natureza === 'Receita';
    if ((type === 'income' && !isIncome) || (type === 'expense' && isIncome)) {
      return accumulator;
    }

    const category = item.categoria || 'Outros';
    accumulator[category] = (accumulator[category] || 0) + (Number(item.valor) || 0);
    return accumulator;
  }, {});

  const total = Object.values(categories).reduce((sum, value) => sum + value, 0);
  if (!total) {
    return [];
  }

  return Object.entries(categories)
    .map(([name, value]) => ({
      name: formatCategoryLabel(name),
      value,
      share: (value / total) * 100,
    }))
    .sort((left, right) => right.value - left.value);
}

export function summarizePeriod(records: DashboardTransaction[]): DashboardPeriodSummary {
  return records.reduce<DashboardPeriodSummary>((accumulator, item) => {
    const value = Number(item.valor) || 0;

    if (item.natureza === 'Receita') {
      accumulator.income += value;
      accumulator.net += value;
      return accumulator;
    }

    accumulator.expenses += value;
    accumulator.net -= value;

    if (item.natureza === 'Essencial') {
      accumulator.essential += value;
    } else if (item.natureza === 'Lazer') {
      accumulator.leisure += value;
    } else {
      accumulator.otherExpenses += value;
    }

    return accumulator;
  }, {
    ...EMPTY_SUMMARY,
    expenseCategories: buildCategoryData(records, 'expense'),
    incomeCategories: buildCategoryData(records, 'income'),
  });
}

export function resolveSnapshotMonth(period: DashboardPeriod) {
  if (period.kind === 'month') {
    return normalizeMonth(period.month);
  }

  return normalizeMonth(new Date());
}

export function summarizeMonthlySnapshot(records: DashboardTransaction[], snapshotMonth: Date): DashboardMonthlySnapshot {
  const bounds = toMonthRange(snapshotMonth);

  return records.reduce<DashboardMonthlySnapshot>((accumulator, item) => {
    if (!isWithinBounds(item.recordDate, bounds)) {
      return accumulator;
    }

    const value = Number(item.valor) || 0;
    if (item.natureza === 'Receita') {
      accumulator.income += value;
      accumulator.balance += value;
      return accumulator;
    }

    accumulator.expenses += value;
    accumulator.balance -= value;
    return accumulator;
  }, { income: 0, expenses: 0, balance: 0 });
}

export function calculateCurrentBalance(records: DashboardTransaction[]) {
  return records.reduce((accumulator, item) => {
    const value = Number(item.valor) || 0;
    if (item.natureza === 'Receita') {
      return accumulator + value;
    }

    return accumulator - value;
  }, 0);
}

export function granularityLabel(granularity: ChartGranularity) {
  if (granularity === 'day') {
    return 'dia';
  }

  if (granularity === 'week') {
    return 'semana';
  }

  return 'mês';
}

export function resolveMonthlyStatus(balance: number) {
  if (balance > 0) {
    return {
      label: 'Positivo',
      tone: 'positive' as const,
    };
  }

  if (balance < 0) {
    return {
      label: 'Negativo',
      tone: 'negative' as const,
    };
  }

  return {
    label: 'Neutro',
    tone: 'neutral' as const,
  };
}

export function buildSplitMetrics(summary: DashboardPeriodSummary): SplitMetric[] {
  const totalExpenseBase = summary.expenses;
  if (!totalExpenseBase) {
    return [
      { label: 'Essencial', value: 0, share: 0, tone: 'neutral' },
      { label: 'Lazer', value: 0, share: 0, tone: 'neutral' },
    ];
  }

  const metrics: SplitMetric[] = [
    {
      label: 'Essencial',
      value: summary.essential,
      share: (summary.essential / totalExpenseBase) * 100,
      tone: 'positive',
    },
    {
      label: 'Lazer',
      value: summary.leisure,
      share: (summary.leisure / totalExpenseBase) * 100,
      tone: 'negative',
    },
  ];

  if (summary.otherExpenses > 0) {
    metrics.push({
      label: 'Outros',
      value: summary.otherExpenses,
      share: (summary.otherExpenses / totalExpenseBase) * 100,
      tone: 'neutral',
    });
  }

  return metrics;
}

export function buildRevenueVsExpenseMessage(snapshot: DashboardMonthlySnapshot) {
  if (snapshot.income === 0 && snapshot.expenses === 0) {
    return {
      value: 'Sem movimentações no mês',
      tone: 'neutral' as const,
    };
  }

  if (snapshot.income === 0) {
    return {
      value: 'Sem receitas registradas no mês',
      tone: 'negative' as const,
    };
  }

  if (snapshot.expenses === 0) {
    return {
      value: 'Receitas sem gastos no mês',
      tone: 'positive' as const,
    };
  }

  if (snapshot.balance >= 0) {
    return {
      value: `Gastos consomem ${formatPercent((snapshot.expenses / snapshot.income) * 100)} das receitas`,
      tone: 'positive' as const,
    };
  }

  return {
    value: `Gastos superam receitas em ${formatCurrency(Math.abs(snapshot.balance))}`,
    tone: 'negative' as const,
  };
}

export function buildInsights(
  snapshotMonthRecords: DashboardTransaction[],
  periodSummary: DashboardPeriodSummary,
  monthlySnapshot: DashboardMonthlySnapshot,
): QuickInsight[] {
  const largestMonthlyExpense = snapshotMonthRecords
    .filter((item) => item.natureza !== 'Receita')
    .sort((left, right) => (Number(right.valor) || 0) - (Number(left.valor) || 0))[0] || null;

  const dominantExpenseCategory = periodSummary.expenseCategories[0];
  const monthlyStatus = resolveMonthlyStatus(monthlySnapshot.balance);
  const revenueVsExpense = buildRevenueVsExpenseMessage(monthlySnapshot);

  return [
    {
      label: 'Maior gasto do mês',
      value: largestMonthlyExpense
        ? `${formatCategoryLabel(largestMonthlyExpense.categoria)} · ${formatCurrency(Number(largestMonthlyExpense.valor) || 0)}`
        : 'Nenhum gasto no mês',
      tone: largestMonthlyExpense ? 'negative' : 'neutral',
    },
    {
      label: 'Categoria com maior peso',
      value: dominantExpenseCategory
        ? `${dominantExpenseCategory.name} · ${formatPercent(dominantExpenseCategory.share)}`
        : 'Sem saídas no período',
      tone: dominantExpenseCategory ? 'neutral' : 'neutral',
    },
    {
      label: 'Estado do mês',
      value: monthlyStatus.label,
      tone: monthlyStatus.tone,
    },
    {
      label: 'Receita versus gasto',
      value: revenueVsExpense.value,
      tone: revenueVsExpense.tone,
    },
  ];
}

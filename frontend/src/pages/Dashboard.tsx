import { AreaChart, BarChart, Card, DonutChart, Grid, Metric, Text, Title } from "@tremor/react";
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
} from "date-fns";
import { ptBR } from "date-fns/locale";
import { useEffect, useState } from "react";

import DashboardPeriodPicker, { type DashboardPeriod } from "@/components/DashboardPeriodPicker";
import { ApiError, getTransactions } from "@/features/admin/api";
import AdminRequestErrorBanner from "@/features/admin/components/AdminRequestErrorBanner";
import { normalizeAdminPageError } from "@/features/admin/lib/pageErrors";
import { useAuth } from "@/hooks/useAuth";
import type { TransactionRecord } from "@/lib/transactions";

type DashboardMetrics = {
  total: number;
  essencial: number;
  superfluous: number;
};

type TimeSeriesPoint = {
  period: string;
  Gasto: number;
};

type DonutPoint = {
  name: string;
  value: number;
};

type ChartGranularity = 'day' | 'week' | 'month';

type DashboardTransaction = TransactionRecord & {
  recordDate: Date;
};

type PeriodBounds = {
  start: Date;
  end: Date;
};

function normalizeMonth(date: Date) {
  return startOfMonth(date);
}

function toMonthRange(referenceDate: Date) {
  return {
    start: startOfMonth(referenceDate),
    end: endOfMonth(referenceDate),
  };
}

function formatCurrency(value: number) {
  return `R$ ${value.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;
}

function formatMonthLabel(value: Date, token = 'MMM/yyyy') {
  const label = format(value, token, { locale: ptBR });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function formatPeriodLabel(period: DashboardPeriod) {
  if (period.kind === 'month') {
    return formatMonthLabel(period.month);
  }

  if (period.kind === 'all') {
    return 'Desde o primeiro registro';
  }

  return `${formatMonthLabel(period.startMonth)} - ${formatMonthLabel(period.endMonth)}`;
}

function parseTransactionDate(value: string) {
  return new Date(`${value}T00:00:00`);
}

function normalizeDashboardTransaction(record: TransactionRecord): DashboardTransaction {
  return {
    ...record,
    categoria: record.categoria || 'Outros',
    conta: record.conta || 'Nao Informada',
    metodo_pagamento: record.metodo_pagamento || 'Outros',
    recordDate: parseTransactionDate(record.data),
  };
}

function resolveFirstRecordDate(records: DashboardTransaction[]) {
  if (records.length === 0) {
    return null;
  }

  return records.reduce((earliest, currentRecord) => (
    isBefore(currentRecord.recordDate, earliest) ? currentRecord.recordDate : earliest
  ), records[0].recordDate);
}

function resolvePeriodQuery(period: DashboardPeriod) {
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

function resolvePeriodBounds(period: DashboardPeriod, records: DashboardTransaction[]) {
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

function isWithinBounds(recordDate: Date, bounds: PeriodBounds) {
  return !isBefore(recordDate, bounds.start) && !isAfter(recordDate, bounds.end);
}

function resolveChartGranularity(bounds: PeriodBounds | null): ChartGranularity {
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

function buildBucketKey(recordDate: Date, granularity: ChartGranularity) {
  if (granularity === 'day') {
    return format(recordDate, 'yyyy-MM-dd');
  }

  if (granularity === 'week') {
    return format(startOfWeek(recordDate, { weekStartsOn: 1 }), 'yyyy-MM-dd');
  }

  return format(startOfMonth(recordDate), 'yyyy-MM');
}

function buildBucketLabel(bucketDate: Date, granularity: ChartGranularity) {
  if (granularity === 'day') {
    return format(bucketDate, 'dd/MM');
  }

  if (granularity === 'week') {
    return format(startOfWeek(bucketDate, { weekStartsOn: 1 }), 'dd/MM');
  }

  return formatMonthLabel(bucketDate, 'MMM/yy');
}

function buildTimeBuckets(bounds: PeriodBounds, granularity: ChartGranularity) {
  if (granularity === 'day') {
    return eachDayOfInterval(bounds);
  }

  if (granularity === 'week') {
    return eachWeekOfInterval(bounds, { weekStartsOn: 1 });
  }

  return eachMonthOfInterval(bounds);
}

function buildTimeSeries(expenseData: DashboardTransaction[], bounds: PeriodBounds | null, granularity: ChartGranularity) {
  if (!bounds) {
    return [];
  }

  const totalsByBucket = expenseData.reduce<Record<string, number>>((accumulator, item) => {
    const bucketKey = buildBucketKey(item.recordDate, granularity);
    accumulator[bucketKey] = (accumulator[bucketKey] || 0) + (Number(item.valor) || 0);
    return accumulator;
  }, {});

  return buildTimeBuckets(bounds, granularity).map((bucketDate) => {
    const key = buildBucketKey(bucketDate, granularity);
    return {
      period: buildBucketLabel(bucketDate, granularity),
      Gasto: totalsByBucket[key] || 0,
    };
  });
}

function summarizeExpenses(expenseData: DashboardTransaction[]): DashboardMetrics {
  return expenseData.reduce<DashboardMetrics>((accumulator, item) => {
    const value = Number(item.valor) || 0;
    accumulator.total += value;

    if (item.natureza === 'Essencial') {
      accumulator.essencial += value;
    } else {
      accumulator.superfluous += value;
    }

    return accumulator;
  }, { total: 0, essencial: 0, superfluous: 0 });
}

function buildDonutData(expenseData: DashboardTransaction[]): DonutPoint[] {
  const categories = expenseData.reduce<Record<string, number>>((accumulator, item) => {
    const category = item.categoria || 'Outros';
    accumulator[category] = (accumulator[category] || 0) + (Number(item.valor) || 0);
    return accumulator;
  }, {});

  return Object.entries(categories).map(([name, value]) => ({ name, value }));
}

function granularityLabel(granularity: ChartGranularity) {
  if (granularity === 'day') {
    return 'Dia';
  }

  if (granularity === 'week') {
    return 'Semana';
  }

  return 'Mes';
}

export default function Dashboard() {
  const { authenticated, localBypass, signOut } = useAuth();
  const [period, setPeriod] = useState<DashboardPeriod>(() => ({
    kind: 'month',
    month: normalizeMonth(new Date()),
  }));
  const [dataGeral, setDataGeral] = useState<DashboardMetrics>({ total: 0, essencial: 0, superfluous: 0 });
  const [timeSeriesData, setTimeSeriesData] = useState<TimeSeriesPoint[]>([]);
  const [donutData, setDonutData] = useState<DonutPoint[]>([]);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [chartGranularity, setChartGranularity] = useState<ChartGranularity>('day');

  useEffect(() => {
    const fetchKPIs = async () => {
      if (!authenticated && !localBypass) {
        setDataGeral({ total: 0, essencial: 0, superfluous: 0 });
        setTimeSeriesData([]);
        setDonutData([]);
        setChartGranularity('day');
        setError(null);
        return;
      }

      try {
        const query = resolvePeriodQuery(period);
        const { transactions } = await getTransactions(query);
        const normalizedData = (transactions || []).map(normalizeDashboardTransaction);
        const bounds = resolvePeriodBounds(period, normalizedData);
        const expensesInBounds = normalizedData
          .filter((item) => item.natureza !== 'Receita')
          .filter((item) => !bounds || isWithinBounds(item.recordDate, bounds));
        const nextGranularity = resolveChartGranularity(bounds);

        setDataGeral(summarizeExpenses(expensesInBounds));
        setTimeSeriesData(buildTimeSeries(expensesInBounds, bounds, nextGranularity));
        setDonutData(buildDonutData(expensesInBounds));
        setChartGranularity(nextGranularity);
        setError(null);
      } catch (fetchError) {
        setDataGeral({ total: 0, essencial: 0, superfluous: 0 });
        setTimeSeriesData([]);
        setDonutData([]);
        setChartGranularity('day');
        setError(normalizeAdminPageError(fetchError, "Nao foi possivel carregar os dados agora."));
      }
    };

    void fetchKPIs();
  }, [authenticated, localBypass, period, reloadToken]);

  useEffect(() => {
    const refresh = () => {
      setReloadToken((current) => current + 1);
    };

    window.addEventListener('transactions:changed', refresh);
    return () => window.removeEventListener('transactions:changed', refresh);
  }, []);

  const periodLabel = formatPeriodLabel(period);
  const chartLabel = granularityLabel(chartGranularity);

  return (
    <div className="space-y-6">
      {error && (
        <AdminRequestErrorBanner
          error={error}
          onRetry={() => setReloadToken((current) => current + 1)}
          onReauthenticate={() => void signOut()}
        />
      )}
      <Grid numItemsSm={2} numItemsLg={3} className="gap-6">
        <Card decoration="top" decorationColor="blue">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <Text>Gasto Total</Text>
              <p className="mt-1 text-xs text-slate-500">{periodLabel}</p>
            </div>
            <DashboardPeriodPicker value={period} onChange={setPeriod} />
          </div>
          <Metric>{formatCurrency(dataGeral.total)}</Metric>
        </Card>
        <Card decoration="top" decorationColor="emerald">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <Text>Total Essencial</Text>
              <p className="mt-1 text-xs text-slate-500">{periodLabel}</p>
            </div>
            <DashboardPeriodPicker value={period} onChange={setPeriod} />
          </div>
          <Metric>{formatCurrency(dataGeral.essencial)}</Metric>
        </Card>
        <Card decoration="top" decorationColor="rose">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <Text>Total Outros/Lazer</Text>
              <p className="mt-1 text-xs text-slate-500">{periodLabel}</p>
            </div>
            <DashboardPeriodPicker value={period} onChange={setPeriod} />
          </div>
          <Metric>{formatCurrency(dataGeral.superfluous)}</Metric>
        </Card>
      </Grid>

      <Card>
        <div className="flex items-center justify-between gap-3">
          <div>
            <Title>Fluxo de Caixa no Tempo</Title>
            <p className="mt-1 text-sm text-slate-500">
              Visualizacao por {chartLabel.toLowerCase()} no periodo selecionado.
            </p>
          </div>
          <DashboardPeriodPicker value={period} onChange={setPeriod} />
        </div>
        <AreaChart
          className="mt-4 h-72"
          data={timeSeriesData}
          index="period"
          categories={["Gasto"]}
          colors={["blue"]}
          valueFormatter={(number) => `R$ ${Intl.NumberFormat("pt-BR").format(number).toString()}`}
        />
      </Card>

      <Grid numItemsSm={1} numItemsLg={2} className="gap-6">
        <Card>
          <div className="flex items-center justify-between gap-3">
            <div>
              <Title>Composicao por Categoria</Title>
              <p className="mt-1 text-sm text-slate-500">{periodLabel}</p>
            </div>
            <DashboardPeriodPicker value={period} onChange={setPeriod} />
          </div>
          <DonutChart
            className="mt-6 h-60"
            data={donutData}
            category="value"
            index="name"
            colors={["blue", "cyan", "indigo", "violet", "fuchsia", "rose"]}
            valueFormatter={(number) => `R$ ${Intl.NumberFormat("pt-BR").format(number).toString()}`}
          />
        </Card>

        <Card>
          <div className="flex items-center justify-between gap-3">
            <div>
              <Title>Gastos por {chartLabel}</Title>
              <p className="mt-1 text-sm text-slate-500">{periodLabel}</p>
            </div>
            <DashboardPeriodPicker value={period} onChange={setPeriod} />
          </div>
          <BarChart
            className="mt-6 h-60"
            data={timeSeriesData}
            index="period"
            categories={["Gasto"]}
            colors={["emerald"]}
            valueFormatter={(number) => `R$ ${Intl.NumberFormat("pt-BR").format(number).toString()}`}
          />
        </Card>
      </Grid>
    </div>
  );
}

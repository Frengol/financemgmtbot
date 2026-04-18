import { AreaChart, DonutChart } from "@tremor/react";
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
import { useEffect, useState, type ComponentType } from "react";
import { ArrowDownRight, ArrowUpRight, Landmark, Wallet } from "lucide-react";

import DashboardPeriodPicker, { type DashboardPeriod } from "@/components/DashboardPeriodPicker";
import { ApiError, getTransactions } from "@/features/admin/api";
import AdminRequestErrorBanner from "@/features/admin/components/AdminRequestErrorBanner";
import { normalizeAdminPageError } from "@/features/admin/lib/pageErrors";
import { useAuth } from "@/hooks/useAuth";
import type { TransactionRecord } from "@/lib/transactions";

type DashboardTransaction = TransactionRecord & {
  recordDate: Date;
};

type DashboardMonthlySnapshot = {
  income: number;
  expenses: number;
  balance: number;
};

type TimeSeriesPoint = {
  period: string;
  Receitas: number;
  Gastos: number;
  "Saldo líquido": number;
};

type DonutPoint = {
  name: string;
  value: number;
  share: number;
};

type DashboardPeriodSummary = {
  income: number;
  expenses: number;
  net: number;
  essential: number;
  leisure: number;
  otherExpenses: number;
  expenseCategories: DonutPoint[];
  incomeCategories: DonutPoint[];
};

type QuickInsight = {
  label: string;
  value: string;
  tone: "neutral" | "positive" | "negative";
};

type SplitMetric = {
  label: string;
  value: number;
  share: number;
  tone: "neutral" | "positive" | "negative";
};

type PeriodBounds = {
  start: Date;
  end: Date;
};

type ChartGranularity = "day" | "week" | "month";

type KpiCardProps = {
  testId: string;
  title: string;
  value: number;
  context: string;
  supportingText: string;
  icon: ComponentType<{ className?: string }>;
  tone: "neutral" | "positive" | "negative";
  status?: {
    label: string;
    tone: "neutral" | "positive" | "negative";
  };
};

const EMPTY_SUMMARY: DashboardPeriodSummary = {
  income: 0,
  expenses: 0,
  net: 0,
  essential: 0,
  leisure: 0,
  otherExpenses: 0,
  expenseCategories: [],
  incomeCategories: [],
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
  return `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
}

function formatPercent(value: number) {
  return `${Math.round(value)}%`;
}

function formatMonthLabel(value: Date, token = "MMM/yyyy") {
  const label = format(value, token, { locale: ptBR });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function formatMonthChip(value: Date) {
  return formatMonthLabel(value);
}

function formatPeriodLabel(period: DashboardPeriod) {
  if (period.kind === "month") {
    return formatMonthLabel(period.month);
  }

  if (period.kind === "all") {
    return "Desde o primeiro registro";
  }

  return `${formatMonthLabel(period.startMonth)} - ${formatMonthLabel(period.endMonth)}`;
}

function parseTransactionDate(value: string) {
  return new Date(`${value}T00:00:00`);
}

function normalizeDashboardTransaction(record: TransactionRecord): DashboardTransaction {
  return {
    ...record,
    categoria: record.categoria || "Outros",
    conta: record.conta || "Nao Informada",
    metodo_pagamento: record.metodo_pagamento || "Outros",
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
  if (period.kind === "all") {
    return undefined;
  }

  if (period.kind === "month") {
    const { start, end } = toMonthRange(period.month);
    return {
      dateFrom: format(start, "yyyy-MM-dd"),
      dateTo: format(end, "yyyy-MM-dd"),
    };
  }

  const [startMonth, endMonth] = isAfter(period.startMonth, period.endMonth)
    ? [period.endMonth, period.startMonth]
    : [period.startMonth, period.endMonth];

  return {
    dateFrom: format(startOfMonth(startMonth), "yyyy-MM-dd"),
    dateTo: format(endOfMonth(endMonth), "yyyy-MM-dd"),
  };
}

function resolvePeriodBounds(period: DashboardPeriod, records: DashboardTransaction[]) {
  if (period.kind === "month") {
    return toMonthRange(period.month);
  }

  if (period.kind === "range") {
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
    return "day";
  }

  const monthSpan = differenceInCalendarMonths(bounds.end, bounds.start) + 1;
  if (monthSpan <= 3) {
    return "day";
  }
  if (monthSpan <= 6) {
    return "week";
  }
  return "month";
}

function buildBucketKey(recordDate: Date, granularity: ChartGranularity) {
  if (granularity === "day") {
    return format(recordDate, "yyyy-MM-dd");
  }

  if (granularity === "week") {
    return format(startOfWeek(recordDate, { weekStartsOn: 1 }), "yyyy-MM-dd");
  }

  return format(startOfMonth(recordDate), "yyyy-MM");
}

function buildBucketLabel(bucketDate: Date, granularity: ChartGranularity) {
  if (granularity === "day") {
    return format(bucketDate, "dd/MM");
  }

  if (granularity === "week") {
    return format(startOfWeek(bucketDate, { weekStartsOn: 1 }), "dd/MM");
  }

  return formatMonthLabel(bucketDate, "MMM/yy");
}

function buildTimeBuckets(bounds: PeriodBounds, granularity: ChartGranularity) {
  if (granularity === "day") {
    return eachDayOfInterval(bounds);
  }

  if (granularity === "week") {
    return eachWeekOfInterval(bounds, { weekStartsOn: 1 });
  }

  return eachMonthOfInterval(bounds);
}

function buildFinancialTimeSeries(
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

    if (item.natureza === "Receita") {
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
      "Saldo líquido": currentBucket.income - currentBucket.expenses,
    };
  });
}

function buildCategoryData(records: DashboardTransaction[], type: "income" | "expense") {
  const categories = records.reduce<Record<string, number>>((accumulator, item) => {
    const isIncome = item.natureza === "Receita";
    if ((type === "income" && !isIncome) || (type === "expense" && isIncome)) {
      return accumulator;
    }

    const category = item.categoria || "Outros";
    accumulator[category] = (accumulator[category] || 0) + (Number(item.valor) || 0);
    return accumulator;
  }, {});

  const total = Object.values(categories).reduce((sum, value) => sum + value, 0);
  if (!total) {
    return [];
  }

  return Object.entries(categories)
    .map(([name, value]) => ({
      name,
      value,
      share: (value / total) * 100,
    }))
    .sort((left, right) => right.value - left.value);
}

function summarizePeriod(records: DashboardTransaction[]): DashboardPeriodSummary {
  return records.reduce<DashboardPeriodSummary>((accumulator, item) => {
    const value = Number(item.valor) || 0;

    if (item.natureza === "Receita") {
      accumulator.income += value;
      accumulator.net += value;
      return accumulator;
    }

    accumulator.expenses += value;
    accumulator.net -= value;

    if (item.natureza === "Essencial") {
      accumulator.essential += value;
    } else if (item.natureza === "Lazer") {
      accumulator.leisure += value;
    } else {
      accumulator.otherExpenses += value;
    }

    return accumulator;
  }, {
    ...EMPTY_SUMMARY,
    expenseCategories: buildCategoryData(records, "expense"),
    incomeCategories: buildCategoryData(records, "income"),
  });
}

function resolveSnapshotMonth(period: DashboardPeriod) {
  if (period.kind === "month") {
    return normalizeMonth(period.month);
  }

  return normalizeMonth(new Date());
}

function summarizeMonthlySnapshot(records: DashboardTransaction[], snapshotMonth: Date): DashboardMonthlySnapshot {
  const bounds = toMonthRange(snapshotMonth);

  return records.reduce<DashboardMonthlySnapshot>((accumulator, item) => {
    if (!isWithinBounds(item.recordDate, bounds)) {
      return accumulator;
    }

    const value = Number(item.valor) || 0;
    if (item.natureza === "Receita") {
      accumulator.income += value;
      accumulator.balance += value;
      return accumulator;
    }

    accumulator.expenses += value;
    accumulator.balance -= value;
    return accumulator;
  }, { income: 0, expenses: 0, balance: 0 });
}

function calculateCurrentBalance(records: DashboardTransaction[]) {
  return records.reduce((accumulator, item) => {
    const value = Number(item.valor) || 0;
    if (item.natureza === "Receita") {
      return accumulator + value;
    }

    return accumulator - value;
  }, 0);
}

function granularityLabel(granularity: ChartGranularity) {
  if (granularity === "day") {
    return "dia";
  }

  if (granularity === "week") {
    return "semana";
  }

  return "mês";
}

function resolveMonthlyStatus(balance: number) {
  if (balance > 0) {
    return {
      label: "Positivo",
      tone: "positive" as const,
    };
  }

  if (balance < 0) {
    return {
      label: "Negativo",
      tone: "negative" as const,
    };
  }

  return {
    label: "Neutro",
    tone: "neutral" as const,
  };
}

function buildSplitMetrics(summary: DashboardPeriodSummary): SplitMetric[] {
  const totalExpenseBase = summary.expenses;
  if (!totalExpenseBase) {
    return [
      { label: "Essencial", value: 0, share: 0, tone: "neutral" },
      { label: "Lazer", value: 0, share: 0, tone: "neutral" },
    ];
  }

  const metrics: SplitMetric[] = [
    {
      label: "Essencial",
      value: summary.essential,
      share: (summary.essential / totalExpenseBase) * 100,
      tone: "positive",
    },
    {
      label: "Lazer",
      value: summary.leisure,
      share: (summary.leisure / totalExpenseBase) * 100,
      tone: "negative",
    },
  ];

  if (summary.otherExpenses > 0) {
    metrics.push({
      label: "Outros",
      value: summary.otherExpenses,
      share: (summary.otherExpenses / totalExpenseBase) * 100,
      tone: "neutral",
    });
  }

  return metrics;
}

function buildRevenueVsExpenseMessage(snapshot: DashboardMonthlySnapshot) {
  if (snapshot.income === 0 && snapshot.expenses === 0) {
    return {
      value: "Sem movimentações no mês",
      tone: "neutral" as const,
    };
  }

  if (snapshot.income === 0) {
    return {
      value: "Sem receitas registradas no mês",
      tone: "negative" as const,
    };
  }

  if (snapshot.expenses === 0) {
    return {
      value: "Receitas sem gastos no mês",
      tone: "positive" as const,
    };
  }

  if (snapshot.balance >= 0) {
    return {
      value: `Gastos consomem ${formatPercent((snapshot.expenses / snapshot.income) * 100)} das receitas`,
      tone: "positive" as const,
    };
  }

  return {
    value: `Gastos superam receitas em ${formatCurrency(Math.abs(snapshot.balance))}`,
    tone: "negative" as const,
  };
}

function buildInsights(
  snapshotMonthRecords: DashboardTransaction[],
  periodSummary: DashboardPeriodSummary,
  monthlySnapshot: DashboardMonthlySnapshot,
): QuickInsight[] {
  const largestMonthlyExpense = snapshotMonthRecords
    .filter((item) => item.natureza !== "Receita")
    .sort((left, right) => (Number(right.valor) || 0) - (Number(left.valor) || 0))[0] || null;

  const dominantExpenseCategory = periodSummary.expenseCategories[0];
  const monthlyStatus = resolveMonthlyStatus(monthlySnapshot.balance);
  const revenueVsExpense = buildRevenueVsExpenseMessage(monthlySnapshot);

  return [
    {
      label: "Maior gasto do mês",
      value: largestMonthlyExpense
        ? `${largestMonthlyExpense.categoria} · ${formatCurrency(Number(largestMonthlyExpense.valor) || 0)}`
        : "Nenhum gasto no mês",
      tone: largestMonthlyExpense ? "negative" : "neutral",
    },
    {
      label: "Categoria com maior peso",
      value: dominantExpenseCategory
        ? `${dominantExpenseCategory.name} · ${formatPercent(dominantExpenseCategory.share)}`
        : "Sem saídas no período",
      tone: dominantExpenseCategory ? "neutral" : "neutral",
    },
    {
      label: "Estado do mês",
      value: monthlyStatus.label,
      tone: monthlyStatus.tone,
    },
    {
      label: "Receita versus gasto",
      value: revenueVsExpense.value,
      tone: revenueVsExpense.tone,
    },
  ];
}

function SectionHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow?: string;
  title: string;
  description: string;
}) {
  return (
    <div className="space-y-2">
      {eyebrow ? (
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">{eyebrow}</p>
      ) : null}
      <div>
        <h3 className="text-xl font-semibold tracking-[-0.03em] text-slate-950 md:text-[1.35rem]">{title}</h3>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">{description}</p>
      </div>
    </div>
  );
}

function KpiCard({ testId, title, value, context, supportingText, icon: Icon, tone, status }: KpiCardProps) {
  const toneClasses = {
    neutral: {
      icon: "text-slate-600",
      badge: "border-slate-200 bg-slate-50 text-slate-600",
      value: "text-slate-950",
    },
    positive: {
      icon: "text-emerald-600",
      badge: "border-emerald-200 bg-emerald-50 text-emerald-700",
      value: "text-slate-950",
    },
    negative: {
      icon: "text-rose-600",
      badge: "border-rose-200 bg-rose-50 text-rose-700",
      value: "text-slate-950",
    },
  } as const;

  return (
    <section
      data-testid={testId}
      className="h-full rounded-[30px] border border-slate-200/80 bg-white p-5 shadow-[0_20px_42px_-34px_rgba(15,23,42,0.34)] transition hover:-translate-y-0.5 hover:shadow-[0_22px_46px_-32px_rgba(15,23,42,0.38)] md:p-6"
    >
      <div className="flex items-start justify-between gap-5">
        <div className="space-y-2">
          <p className="text-sm font-medium text-slate-500">{title}</p>
          <p className={`text-[1.95rem] font-semibold leading-none tracking-[-0.04em] md:text-[2.2rem] ${toneClasses[tone].value}`}>
            {formatCurrency(value)}
          </p>
        </div>
        <div className={`inline-flex h-10 w-10 items-center justify-center rounded-2xl border shadow-[0_10px_20px_-18px_rgba(15,23,42,0.4)] md:h-11 md:w-11 ${toneClasses[tone].badge}`}>
          <Icon className={`h-[18px] w-[18px] md:h-5 md:w-5 ${toneClasses[tone].icon}`} />
        </div>
      </div>

      <div className="mt-6 flex flex-wrap items-end justify-between gap-3">
        <p className="max-w-[16rem] text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">{supportingText}</p>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-semibold text-slate-600">
            {context}
          </span>
          {status && (
            <span className={`rounded-full border px-3 py-1 text-[11px] font-semibold ${toneClasses[status.tone].badge}`}>
              {status.label}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

function CategoryBreakdownCard({
  title,
  description,
  data,
  emptyMessage,
  donutColors,
}: {
  title: string;
  description: string;
  data: DonutPoint[];
  emptyMessage: string;
  donutColors: string[];
}) {
  const totalValue = data.reduce((sum, item) => sum + item.value, 0);

  return (
    <section className="h-full rounded-[32px] border border-slate-200/80 bg-white p-5 shadow-[0_24px_48px_-34px_rgba(15,23,42,0.32)] md:p-6">
      <div className="flex flex-col gap-4">
        <SectionHeader
          title={title}
          description={description}
        />

        {data.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-semibold text-slate-600">
              {data.length} categorias
            </span>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-semibold text-slate-600">
              {formatCurrency(totalValue)}
            </span>
          </div>
        )}
      </div>

      {data.length > 0 ? (
        <div className="mt-6 grid gap-6 lg:mt-8 lg:grid-cols-[0.92fr_1.08fr] lg:items-center">
          <DonutChart
            className="h-64 md:h-72"
            data={data}
            category="value"
            index="name"
            colors={donutColors}
            valueFormatter={(number) => `R$ ${Intl.NumberFormat("pt-BR").format(number).toString()}`}
          />

          <div className="space-y-3">
            {data.slice(0, 5).map((item) => (
              <div
                key={`${title}-${item.name}`}
                className="flex items-center justify-between rounded-[22px] border border-slate-200 bg-slate-50/70 px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-slate-700">{item.name}</p>
                  <p className="mt-1 text-xs text-slate-500">{formatPercent(item.share)} do total</p>
                </div>
                <p className="text-sm font-semibold text-slate-900">{formatCurrency(item.value)}</p>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-6 flex min-h-[15rem] items-center rounded-[28px] border border-dashed border-slate-200 bg-slate-50/60 p-6 text-sm leading-6 text-slate-500 md:mt-8">
          {emptyMessage}
        </div>
      )}
    </section>
  );
}

function FinancialHealthCard({
  splitMetrics,
  insights,
  periodLabel,
  snapshotLabel,
}: {
  splitMetrics: SplitMetric[];
  insights: QuickInsight[];
  periodLabel: string;
  snapshotLabel: string;
}) {
  const toneClasses = {
    neutral: "text-slate-600",
    positive: "text-emerald-700",
    negative: "text-rose-700",
  } as const;

  return (
    <section className="h-full rounded-[32px] border border-slate-200/80 bg-white p-5 shadow-[0_24px_48px_-34px_rgba(15,23,42,0.32)] md:p-6">
      <SectionHeader
        title="Essencial vs Lazer"
        description={`Equilíbrio das saídas no período analítico ${periodLabel.toLowerCase()}.`}
      />

      <div className="mt-6 space-y-4 md:mt-8">
        {splitMetrics.map((item) => (
          <div key={item.label} className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium text-slate-700">{item.label}</span>
              <span className="font-semibold text-slate-900">{formatCurrency(item.value)}</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                <div
                  className={`h-full rounded-full ${
                    item.tone === "positive"
                      ? "bg-emerald-500"
                      : item.tone === "negative"
                        ? "bg-rose-500"
                        : "bg-slate-400"
                  }`}
                  style={{ width: `${Math.min(item.share, 100)}%` }}
                />
              </div>
              <span className="min-w-[3rem] text-right text-xs font-semibold text-slate-500">
                {formatPercent(item.share)}
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="my-6 border-t border-slate-200 md:my-8" />

      <div className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">Insights rápidos</p>
        <p className="text-sm leading-6 text-slate-500">
          Leitura automática do mês de referência {snapshotLabel.toLowerCase()} e do período analítico atual.
        </p>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
        {insights.map((item) => (
          <div
            key={item.label}
            className="rounded-[22px] border border-slate-200 bg-slate-50/70 px-4 py-3"
          >
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">{item.label}</p>
            <p className={`mt-2 text-sm font-semibold ${toneClasses[item.tone]}`}>{item.value}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function Dashboard() {
  const { authenticated, localBypass, signOut } = useAuth();
  const [period, setPeriod] = useState<DashboardPeriod>(() => ({
    kind: "month",
    month: normalizeMonth(new Date()),
  }));
  const [currentBalance, setCurrentBalance] = useState(0);
  const [monthlySnapshot, setMonthlySnapshot] = useState<DashboardMonthlySnapshot>({ income: 0, expenses: 0, balance: 0 });
  const [periodSummary, setPeriodSummary] = useState<DashboardPeriodSummary>(EMPTY_SUMMARY);
  const [timeSeriesData, setTimeSeriesData] = useState<TimeSeriesPoint[]>([]);
  const [quickInsights, setQuickInsights] = useState<QuickInsight[]>([]);
  const [chartGranularity, setChartGranularity] = useState<ChartGranularity>("day");
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const fetchDashboard = async () => {
      if (!authenticated && !localBypass) {
        setCurrentBalance(0);
        setMonthlySnapshot({ income: 0, expenses: 0, balance: 0 });
        setPeriodSummary(EMPTY_SUMMARY);
        setTimeSeriesData([]);
        setQuickInsights([]);
        setChartGranularity("day");
        setError(null);
        return;
      }

      try {
        const query = resolvePeriodQuery(period);
        const [filteredResponse, allResponse] = await Promise.all([
          getTransactions(query),
          period.kind === "all" ? Promise.resolve(null) : getTransactions(),
        ]);

        const filteredData = (filteredResponse.transactions || []).map(normalizeDashboardTransaction);
        const allData = allResponse ? (allResponse.transactions || []).map(normalizeDashboardTransaction) : filteredData;
        const bounds = resolvePeriodBounds(period, filteredData);
        const nextGranularity = resolveChartGranularity(bounds);
        const snapshotMonth = resolveSnapshotMonth(period);
        const snapshotBounds = toMonthRange(snapshotMonth);
        const snapshotMonthRecords = allData.filter((item) => isWithinBounds(item.recordDate, snapshotBounds));
        const nextPeriodSummary = summarizePeriod(filteredData);
        const nextMonthlySnapshot = summarizeMonthlySnapshot(allData, snapshotMonth);

        setCurrentBalance(calculateCurrentBalance(allData));
        setMonthlySnapshot(nextMonthlySnapshot);
        setPeriodSummary(nextPeriodSummary);
        setTimeSeriesData(buildFinancialTimeSeries(filteredData, bounds, nextGranularity));
        setQuickInsights(buildInsights(snapshotMonthRecords, nextPeriodSummary, nextMonthlySnapshot));
        setChartGranularity(nextGranularity);
        setError(null);
      } catch (fetchError) {
        setCurrentBalance(0);
        setMonthlySnapshot({ income: 0, expenses: 0, balance: 0 });
        setPeriodSummary(EMPTY_SUMMARY);
        setTimeSeriesData([]);
        setQuickInsights([]);
        setChartGranularity("day");
        setError(normalizeAdminPageError(fetchError, "Nao foi possivel carregar os dados agora."));
      }
    };

    void fetchDashboard();
  }, [authenticated, localBypass, period, reloadToken]);

  useEffect(() => {
    const refresh = () => {
      setReloadToken((current) => current + 1);
    };

    window.addEventListener("transactions:changed", refresh);
    return () => window.removeEventListener("transactions:changed", refresh);
  }, []);

  const periodLabel = formatPeriodLabel(period);
  const snapshotMonth = resolveSnapshotMonth(period);
  const snapshotLabel = formatMonthChip(snapshotMonth);
  const balanceStatus = resolveMonthlyStatus(monthlySnapshot.balance);
  const splitMetrics = buildSplitMetrics(periodSummary);
  const chartSummaryMetrics = [
    { label: "Receitas", value: periodSummary.income, toneClass: "bg-emerald-500" },
    { label: "Gastos", value: periodSummary.expenses, toneClass: "bg-rose-500" },
    { label: "Saldo líquido", value: periodSummary.net, toneClass: "bg-blue-500" },
  ];
  const monthlyCards = [
    {
      testId: "dashboard-kpi-current-balance",
      title: "Saldo atual",
      value: currentBalance,
      context: "Acumulado",
      supportingText: "Saldo consolidado até hoje",
      icon: Wallet,
      tone: "neutral" as const,
    },
    {
      testId: "dashboard-kpi-month-income",
      title: "Receitas do mês",
      value: monthlySnapshot.income,
      context: snapshotLabel,
      supportingText: "Entradas no mês de referência",
      icon: ArrowUpRight,
      tone: "positive" as const,
    },
    {
      testId: "dashboard-kpi-month-expenses",
      title: "Gastos do mês",
      value: monthlySnapshot.expenses,
      context: snapshotLabel,
      supportingText: "Saídas no mês de referência",
      icon: ArrowDownRight,
      tone: "negative" as const,
    },
    {
      testId: "dashboard-kpi-month-balance",
      title: "Saldo do mês",
      value: monthlySnapshot.balance,
      context: snapshotLabel,
      supportingText: "Resultado no mês de referência",
      icon: Landmark,
      tone: balanceStatus.tone,
      status: balanceStatus,
    },
  ];

  return (
    <div className="space-y-6 md:space-y-8">
      {error && (
        <AdminRequestErrorBanner
          error={error}
          onRetry={() => setReloadToken((current) => current + 1)}
          onReauthenticate={() => void signOut()}
        />
      )}

      <section className="space-y-5">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">Resumo financeiro</p>
            <div>
              <h2 className="text-2xl font-semibold tracking-[-0.03em] text-slate-950 md:text-[2.1rem]">Visão geral do painel</h2>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">
                Indicadores do mês, saúde financeira e composição do período filtrado em uma leitura única.
              </p>
            </div>
          </div>
          <div
            data-testid="dashboard-overview-period-picker"
            className="flex w-full items-center justify-between gap-3 rounded-[26px] border border-slate-200/80 bg-white px-4 py-3 shadow-[0_18px_40px_-32px_rgba(15,23,42,0.35)] sm:w-auto lg:min-w-[18rem]"
          >
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Período</p>
              <p className="mt-1 text-sm font-medium text-slate-600">{periodLabel}</p>
            </div>
            <DashboardPeriodPicker value={period} onChange={setPeriod} />
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {monthlyCards.map((card) => (
            <KpiCard key={card.testId} {...card} />
          ))}
        </div>
      </section>

      <section
        data-testid="dashboard-primary-chart"
        className="rounded-[32px] border border-slate-200/80 bg-white p-5 shadow-[0_24px_48px_-34px_rgba(15,23,42,0.32)] md:p-6 lg:p-7"
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <SectionHeader
            title="Receitas x gastos no tempo"
            description={`Comparativo entre entradas, saídas e saldo líquido por ${granularityLabel(chartGranularity)} no período selecionado.`}
          />

          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-semibold text-slate-600">
              {periodLabel}
            </span>
            <span className={`rounded-full border px-3 py-1 text-[11px] font-semibold ${
              balanceStatus.tone === "positive"
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : balanceStatus.tone === "negative"
                  ? "border-rose-200 bg-rose-50 text-rose-700"
                  : "border-slate-200 bg-slate-50 text-slate-600"
            }`}>
              {balanceStatus.label}
            </span>
          </div>
        </div>

        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          {chartSummaryMetrics.map((metric) => (
            <div
              key={metric.label}
              className="rounded-[22px] border border-slate-200 bg-slate-50/70 px-4 py-3"
            >
              <div className="flex items-center gap-2">
                <span className={`h-2.5 w-2.5 rounded-full ${metric.toneClass}`} />
                <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">{metric.label}</span>
              </div>
              <p className="mt-2 text-base font-semibold text-slate-900">{formatCurrency(metric.value)}</p>
            </div>
          ))}
        </div>

        <AreaChart
          className="mt-6 h-72 md:mt-8 md:h-80"
          data={timeSeriesData}
          index="period"
          categories={["Receitas", "Gastos", "Saldo líquido"]}
          colors={["emerald", "rose", "blue"]}
          valueFormatter={(number) => `R$ ${Intl.NumberFormat("pt-BR").format(number).toString()}`}
        />
      </section>

      <section data-testid="dashboard-secondary-grid" className="grid gap-6 lg:grid-cols-2 xl:grid-cols-[1fr_1fr_0.92fr]">
        <CategoryBreakdownCard
          title="Gastos por categoria"
          description="Distribuição das saídas no período analítico selecionado."
          data={periodSummary.expenseCategories}
          emptyMessage="Nenhum gasto no período analítico."
          donutColors={["rose", "orange", "amber", "slate", "cyan", "indigo"]}
        />

        <CategoryBreakdownCard
          title="Receitas por categoria"
          description="Composição das entradas quando houver receitas no período filtrado."
          data={periodSummary.incomeCategories}
          emptyMessage="Nenhuma receita no período analítico."
          donutColors={["emerald", "teal", "blue", "cyan", "lime", "slate"]}
        />

        <div className="lg:col-span-2 xl:col-span-1">
          <FinancialHealthCard
            splitMetrics={splitMetrics}
            insights={quickInsights}
            periodLabel={periodLabel}
            snapshotLabel={snapshotLabel}
          />
        </div>
      </section>
    </div>
  );
}

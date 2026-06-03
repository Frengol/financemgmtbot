import { AreaChart, DonutChart } from "@tremor/react";
import { useState, type ComponentType } from "react";
import { ArrowDownRight, ArrowUpRight, Landmark, Wallet } from "lucide-react";

import DashboardPeriodPicker, { type DashboardPeriod } from "@/components/DashboardPeriodPicker";
import AdminRequestErrorBanner from "@/features/admin/components/AdminRequestErrorBanner";
import {
  buildSplitMetrics,
  formatCurrency,
  formatMonthChip,
  formatPercent,
  formatPeriodLabel,
  granularityLabel,
  normalizeMonth,
  resolveMonthlyStatus,
  resolveSnapshotMonth,
  type DonutPoint,
  type QuickInsight,
  type SplitMetric,
} from "@/features/dashboard/analytics";
import { useDashboardData } from "@/features/dashboard/useDashboardData";
import { useAuth } from "@/hooks/useAuth";

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
  const {
    currentBalance,
    monthlySnapshot,
    periodSummary,
    timeSeriesData,
    quickInsights,
    chartGranularity,
    error,
    reloadDashboard,
  } = useDashboardData({ authenticated, localBypass, period });

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
          onRetry={reloadDashboard}
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

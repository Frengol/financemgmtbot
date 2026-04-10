import { AreaChart, BarChart, Card, DonutChart, Grid, Metric, Text, Title } from "@tremor/react";
import { eachDayOfInterval, endOfMonth, format, startOfMonth } from "date-fns";
import { ptBR } from "date-fns/locale";
import { useEffect, useState } from "react";
import { ApiError, getTransactions } from "@/features/admin/api";
import { useAuth } from "@/hooks/useAuth";
import CompactMonthPicker from "@/components/CompactMonthPicker";
import AdminRequestErrorBanner from "@/features/admin/components/AdminRequestErrorBanner";
import { normalizeAdminPageError } from "@/features/admin/lib/pageErrors";

type DashboardTransaction = {
  data: string;
  natureza: string;
  categoria: string;
  valor: number;
};

function toMonthRange(referenceDate: Date) {
  return {
    start: startOfMonth(referenceDate),
    end: endOfMonth(referenceDate),
  };
}

export default function Dashboard() {
  const { authenticated, localBypass, signOut } = useAuth();
  const [referenceMonth, setReferenceMonth] = useState(() => startOfMonth(new Date()));
  const [dataGeral, setDataGeral] = useState({ total: 0, essencial: 0, superfluous: 0 });
  const [chartData, setChartData] = useState<Array<{ date: string; Gasto: number }>>([]);
  const [donutData, setDonutData] = useState<Array<{ name: string; value: number }>>([]);
  const [heatmapData, setHeatmapData] = useState<Array<{ name: string; "Valor Acumulado": number }>>([]);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const fetchKPIs = async () => {
      if (!authenticated && !localBypass) {
        setDataGeral({ total: 0, essencial: 0, superfluous: 0 });
        setChartData([]);
        setDonutData([]);
        setHeatmapData([]);
        setError(null);
        return;
      }

      try {
        const { start, end } = toMonthRange(referenceMonth);
        const { transactions: data } = await getTransactions({
          dateFrom: format(start, 'yyyy-MM-dd'),
          dateTo: format(end, 'yyyy-MM-dd'),
        });

        if (!data) {
          setDataGeral({ total: 0, essencial: 0, superfluous: 0 });
          setChartData([]);
          setDonutData([]);
          setHeatmapData([]);
          setError(null);
          return;
        }

        const expenseData = (data as DashboardTransaction[]).filter((item) => item.natureza !== 'Receita');
        let total = 0;
        let essencial = 0;
        let superfluous = 0;
        const fluxo: Record<string, number> = {};
        const catCount: Record<string, number> = {};
        const heatCount: Record<string, number> = { Seg: 0, Ter: 0, Qua: 0, Qui: 0, Sex: 0, Sab: 0, Dom: 0 };

        for (const item of expenseData) {
          const value = Number(item.valor) || 0;
          total += value;

          if (item.natureza === 'Essencial') {
            essencial += value;
          } else {
            superfluous += value;
          }

          fluxo[item.data] = (fluxo[item.data] || 0) + value;

          const category = item.categoria || 'Outros';
          catCount[category] = (catCount[category] || 0) + value;

          const weekday = format(new Date(`${item.data}T00:00:00`), 'EEE', { locale: ptBR });
          const normalizedDay = weekday.charAt(0).toUpperCase() + weekday.slice(1, 3);
          if (heatCount[normalizedDay] !== undefined) {
            heatCount[normalizedDay] += value;
          }
        }

        const daysInMonth = eachDayOfInterval({ start, end });
        setChartData(daysInMonth.map((day) => {
          const key = format(day, 'yyyy-MM-dd');
          return {
            date: format(day, 'dd/MM'),
            Gasto: fluxo[key] || 0,
          };
        }));

        setDataGeral({ total, essencial, superfluous });
        setDonutData(Object.entries(catCount).map(([name, value]) => ({ name, value })));
        setHeatmapData(Object.entries(heatCount).map(([name, value]) => ({ name, "Valor Acumulado": value })));
        setError(null);
      } catch (fetchError) {
        setDataGeral({ total: 0, essencial: 0, superfluous: 0 });
        setChartData([]);
        setDonutData([]);
        setHeatmapData([]);
        setError(normalizeAdminPageError(fetchError, "Nao foi possivel carregar os dados agora."));
      }
    };

    void fetchKPIs();
  }, [authenticated, localBypass, referenceMonth, reloadToken]);

  useEffect(() => {
    const refresh = () => {
      setReferenceMonth((currentMonth) => new Date(currentMonth));
    };

    window.addEventListener('transactions:changed', refresh);
    return () => window.removeEventListener('transactions:changed', refresh);
  }, []);
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
            <Text>Gasto Total do Mes</Text>
            <CompactMonthPicker value={referenceMonth} onChange={setReferenceMonth} />
          </div>
          <Metric>R$ {dataGeral.total.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</Metric>
        </Card>
        <Card decoration="top" decorationColor="emerald">
          <div className="mb-4 flex items-start justify-between gap-3">
            <Text>Total Essencial</Text>
            <CompactMonthPicker value={referenceMonth} onChange={setReferenceMonth} />
          </div>
          <Metric>R$ {dataGeral.essencial.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</Metric>
        </Card>
        <Card decoration="top" decorationColor="rose">
          <div className="mb-4 flex items-start justify-between gap-3">
            <Text>Total Outros/Lazer</Text>
            <CompactMonthPicker value={referenceMonth} onChange={setReferenceMonth} />
          </div>
          <Metric>R$ {dataGeral.superfluous.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</Metric>
        </Card>
      </Grid>

      <Card>
        <div className="flex items-center justify-between">
          <div>
            <Title>Fluxo de Caixa no Tempo</Title>
            <p className="mt-1 text-sm text-slate-500">Selecione o mes para navegar no historico mensal.</p>
          </div>
          <CompactMonthPicker value={referenceMonth} onChange={setReferenceMonth} />
        </div>
        <AreaChart
          className="mt-4 h-72"
          data={chartData}
          index="date"
          categories={["Gasto"]}
          colors={["blue"]}
          valueFormatter={(number) => `R$ ${Intl.NumberFormat("pt-BR").format(number).toString()}`}
        />
      </Card>

      <Grid numItemsSm={1} numItemsLg={2} className="gap-6">
        <Card>
          <div className="flex items-center justify-between gap-3">
            <Title>Composicao por Categoria</Title>
            <CompactMonthPicker value={referenceMonth} onChange={setReferenceMonth} />
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
            <Title>Padrao de Gastos por Dia</Title>
            <CompactMonthPicker value={referenceMonth} onChange={setReferenceMonth} />
          </div>
          <BarChart
            className="mt-6 h-60"
            data={heatmapData}
            index="name"
            categories={["Valor Acumulado"]}
            colors={["emerald"]}
            valueFormatter={(number) => `R$ ${Intl.NumberFormat("pt-BR").format(number).toString()}`}
          />
        </Card>
      </Grid>
    </div>
  );
}

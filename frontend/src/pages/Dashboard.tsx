import { Card, Text, Metric, Grid, AreaChart, DonutChart, Title, BarChart } from "@tremor/react";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

export default function Dashboard() {
  const [dataGeral, setDataGeral] = useState({ total: 0, essencial: 0, superfluous: 0 });
  const [chartData, setChartData] = useState<any[]>([]);
  const [donutData, setDonutData] = useState<any[]>([]);
  const [heatmapData, setHeatmapData] = useState<any[]>([]);

  useEffect(() => {
    const fetchKPIs = async () => {
      const { data, error } = await supabase.from('gastos').select('*');
      if (error || !data) return;

      let total = 0, essencial = 0, superfluous = 0;
      const fluxo: Record<string, number> = {};
      const catCount: Record<string, number> = {};
      const heatCount: Record<string, number> = { "Seg": 0, "Ter": 0, "Qua": 0, "Qui": 0, "Sex": 0, "Sab": 0, "Dom": 0 };

      data.forEach(item => {
        const val = Number(item.valor);
        total += val;
        
        if (item.natureza?.toLowerCase() === 'essencial') essencial += val;
        else superfluous += val;

        const dateKey = item.data;
        if (dateKey) fluxo[dateKey] = (fluxo[dateKey] || 0) + val;

        const cat = item.categoria || 'Outros';
        catCount[cat] = (catCount[cat] || 0) + val;

        if (item.data) {
          const day = new Date(item.data).toLocaleDateString("pt-BR", { timeZone: "UTC", weekday: "short" });
          const dayCap = day.charAt(0).toUpperCase() + day.slice(1, 3);
          if (heatCount[dayCap] !== undefined) heatCount[dayCap] += val;
        }
      });

      setDataGeral({ total, essencial, superfluous });

      const sortedDates = Object.keys(fluxo).sort();
      setChartData(sortedDates.map(d => ({ date: d, "Gasto": fluxo[d] })));

      setDonutData(Object.keys(catCount).map(name => ({ name, value: catCount[name] })));
      
      setHeatmapData(Object.keys(heatCount).map(name => ({ name, "Valor Acumulado": heatCount[name] })));
    };
    fetchKPIs();
  }, []);

  return (
    <div className="space-y-6">
      <Grid numItemsSm={2} numItemsLg={3} className="gap-6">
        <Card decoration="top" decorationColor="blue">
          <Text>Gasto Total do Mês</Text>
          <Metric>R$ {dataGeral.total.toFixed(2)}</Metric>
        </Card>
        <Card decoration="top" decorationColor="emerald">
          <Text>Total Essencial</Text>
          <Metric>R$ {dataGeral.essencial.toFixed(2)}</Metric>
        </Card>
        <Card decoration="top" decorationColor="rose">
          <Text>Total Outros/Lazer</Text>
          <Metric>R$ {dataGeral.superfluous.toFixed(2)}</Metric>
        </Card>
      </Grid>

      <div className="mt-6">
        <Card>
          <Title>Fluxo de Caixa no Tempo</Title>
          <AreaChart
            className="h-72 mt-4"
            data={chartData}
            index="date"
            categories={["Gasto"]}
            colors={["blue"]}
            valueFormatter={(number) => `R$ ${Intl.NumberFormat("pt-BR").format(number).toString()}`}
          />
        </Card>
      </div>

      <Grid numItemsSm={1} numItemsLg={2} className="gap-6 mt-6">
        <Card>
          <Title>Composição por Categoria</Title>
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
          <Title>Padrão de Gastos (Dias da Semana)</Title>
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

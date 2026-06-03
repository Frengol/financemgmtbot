import { useCallback, useEffect, useState } from 'react';

import type { DashboardPeriod } from '@/components/DashboardPeriodPicker';
import { ApiError, getTransactions } from '@/features/admin/api';
import { normalizeAdminPageError } from '@/features/admin/lib/pageErrors';
import {
  EMPTY_SUMMARY,
  buildFinancialTimeSeries,
  buildInsights,
  calculateCurrentBalance,
  normalizeDashboardTransaction,
  resolveChartGranularity,
  resolvePeriodBounds,
  resolvePeriodQuery,
  resolveSnapshotMonth,
  summarizeMonthlySnapshot,
  summarizePeriod,
  toMonthRange,
  type ChartGranularity,
  type DashboardMonthlySnapshot,
  type DashboardPeriodSummary,
  type QuickInsight,
  type TimeSeriesPoint,
} from './analytics';

type UseDashboardDataParams = {
  authenticated: boolean;
  localBypass: boolean;
  period: DashboardPeriod;
};

export function useDashboardData({ authenticated, localBypass, period }: UseDashboardDataParams) {
  const [currentBalance, setCurrentBalance] = useState(0);
  const [monthlySnapshot, setMonthlySnapshot] = useState<DashboardMonthlySnapshot>({ income: 0, expenses: 0, balance: 0 });
  const [periodSummary, setPeriodSummary] = useState<DashboardPeriodSummary>(EMPTY_SUMMARY);
  const [timeSeriesData, setTimeSeriesData] = useState<TimeSeriesPoint[]>([]);
  const [quickInsights, setQuickInsights] = useState<QuickInsight[]>([]);
  const [chartGranularity, setChartGranularity] = useState<ChartGranularity>('day');
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const resetDashboard = useCallback(() => {
    setCurrentBalance(0);
    setMonthlySnapshot({ income: 0, expenses: 0, balance: 0 });
    setPeriodSummary(EMPTY_SUMMARY);
    setTimeSeriesData([]);
    setQuickInsights([]);
    setChartGranularity('day');
  }, []);

  const reloadDashboard = useCallback(() => {
    setReloadToken((current) => current + 1);
  }, []);

  useEffect(() => {
    const fetchDashboard = async () => {
      if (!authenticated && !localBypass) {
        resetDashboard();
        setError(null);
        return;
      }

      try {
        const query = resolvePeriodQuery(period);
        const [filteredResponse, allResponse] = await Promise.all([
          getTransactions(query),
          period.kind === 'all' ? Promise.resolve(null) : getTransactions(),
        ]);

        const filteredData = (filteredResponse.transactions || []).map(normalizeDashboardTransaction);
        const allData = allResponse ? (allResponse.transactions || []).map(normalizeDashboardTransaction) : filteredData;
        const bounds = resolvePeriodBounds(period, filteredData);
        const nextGranularity = resolveChartGranularity(bounds);
        const snapshotMonth = resolveSnapshotMonth(period);
        const snapshotBounds = toMonthRange(snapshotMonth);
        const snapshotMonthRecords = allData.filter((item) => (
          item.recordDate >= snapshotBounds.start && item.recordDate <= snapshotBounds.end
        ));
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
        resetDashboard();
        setError(normalizeAdminPageError(fetchError, 'Não foi possível carregar os dados agora.'));
      }
    };

    void fetchDashboard();
  }, [authenticated, localBypass, period, reloadToken, resetDashboard]);

  useEffect(() => {
    window.addEventListener('transactions:changed', reloadDashboard);
    return () => window.removeEventListener('transactions:changed', reloadDashboard);
  }, [reloadDashboard]);

  return {
    currentBalance,
    monthlySnapshot,
    periodSummary,
    timeSeriesData,
    quickInsights,
    chartGranularity,
    error,
    reloadDashboard,
  };
}

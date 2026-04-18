import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { format, getMonth, getYear, isAfter, isBefore, isSameMonth, setMonth, startOfMonth } from 'date-fns';
import { ptBR } from 'date-fns/locale';

export type DashboardPeriod =
  | { kind: 'month'; month: Date }
  | { kind: 'all' }
  | { kind: 'range'; startMonth: Date; endMonth: Date };

type DashboardPeriodPickerProps = {
  value: DashboardPeriod;
  onChange: (value: DashboardPeriod) => void;
};

type PickerTab = 'month' | 'range';
type RangeTarget = 'start' | 'end';

const monthLabels = Array.from({ length: 12 }, (_, monthIndex) =>
  format(new Date(2026, monthIndex, 1), 'MMM', { locale: ptBR }),
);

function normalizeMonth(date: Date) {
  return startOfMonth(date);
}

function formatMonthLabel(value: Date, token = 'MMM/yyyy') {
  const label = format(value, token, { locale: ptBR });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function buildMonthDate(year: number, monthIndex: number) {
  return normalizeMonth(setMonth(new Date(year, 0, 1), monthIndex));
}

function sortRangeMonths(startMonth: Date, endMonth: Date) {
  return isAfter(startMonth, endMonth)
    ? [endMonth, startMonth] as const
    : [startMonth, endMonth] as const;
}

function createInitialRange(value: DashboardPeriod) {
  if (value.kind === 'range') {
    return {
      startMonth: normalizeMonth(value.startMonth),
      endMonth: normalizeMonth(value.endMonth),
    };
  }

  if (value.kind === 'month') {
    return {
      startMonth: normalizeMonth(value.month),
      endMonth: normalizeMonth(value.month),
    };
  }

  const currentMonth = normalizeMonth(new Date());
  return {
    startMonth: currentMonth,
    endMonth: currentMonth,
  };
}

function resolveDisplayYear(value: DashboardPeriod) {
  if (value.kind === 'month') {
    return getYear(value.month);
  }

  if (value.kind === 'range') {
    return getYear(value.endMonth);
  }

  return getYear(new Date());
}

function formatTriggerLabel(value: DashboardPeriod) {
  if (value.kind === 'month') {
    return formatMonthLabel(value.month);
  }

  if (value.kind === 'all') {
    return 'Total';
  }

  return `${formatMonthLabel(value.startMonth, 'MMM/yy')} - ${formatMonthLabel(value.endMonth, 'MMM/yy')}`;
}

export default function DashboardPeriodPicker({ value, onChange }: DashboardPeriodPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<PickerTab>('month');
  const [displayYear, setDisplayYear] = useState(() => resolveDisplayYear(value));
  const [rangeTarget, setRangeTarget] = useState<RangeTarget>('start');
  const [{ startMonth, endMonth }, setDraftRange] = useState(() => createInitialRange(value));
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const initialRange = createInitialRange(value);
    setActiveTab('month');
    setRangeTarget('start');
    setDisplayYear(resolveDisplayYear(value));
    setDraftRange(initialRange);
  }, [isOpen, value]);

  const selectedMonth = useMemo(
    () => (value.kind === 'month' ? getMonth(value.month) : null),
    [value],
  );

  const handleMonthSelection = (monthIndex: number) => {
    onChange({
      kind: 'month',
      month: buildMonthDate(displayYear, monthIndex),
    });
    setIsOpen(false);
  };

  const handleRangeMonthSelection = (monthIndex: number) => {
    const selectedMonthDate = buildMonthDate(displayYear, monthIndex);

    if (rangeTarget === 'start') {
      setDraftRange((currentRange) => ({
        ...currentRange,
        startMonth: selectedMonthDate,
      }));
      setRangeTarget('end');
      setDisplayYear(getYear(endMonth));
      return;
    }

    const [sortedStartMonth, sortedEndMonth] = sortRangeMonths(startMonth, selectedMonthDate);
    setDraftRange({
      startMonth: sortedStartMonth,
      endMonth: sortedEndMonth,
    });
    onChange({
      kind: 'range',
      startMonth: sortedStartMonth,
      endMonth: sortedEndMonth,
    });
    setRangeTarget('start');
    setIsOpen(false);
  };

  const isRangeMonthSelected = (monthIndex: number) => {
    const candidateMonth = buildMonthDate(displayYear, monthIndex);
    const [sortedStartMonth, sortedEndMonth] = sortRangeMonths(startMonth, endMonth);

    if (isSameMonth(candidateMonth, sortedStartMonth) || isSameMonth(candidateMonth, sortedEndMonth)) {
      return 'edge';
    }

    if (isAfter(candidateMonth, sortedStartMonth) && isBefore(candidateMonth, sortedEndMonth)) {
      return 'between';
    }

    return 'none';
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        className="inline-flex min-h-[46px] max-w-[15rem] items-center rounded-2xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm font-semibold text-slate-700 shadow-[0_10px_26px_-20px_rgba(15,23,42,0.45)] transition hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2"
      >
        <span className="block truncate">{formatTriggerLabel(value)}</span>
      </button>

      {isOpen && (
        <div
          role="dialog"
          aria-label="Selecionar período analítico"
          className="absolute left-1/2 top-[3.7rem] z-30 w-[min(21rem,calc(100vw-2rem))] -translate-x-1/2 rounded-[28px] border border-slate-200/90 bg-white p-4 shadow-[0_28px_50px_-30px_rgba(15,23,42,0.4)] sm:left-auto sm:right-0 sm:translate-x-0 sm:p-5"
        >
          <div role="tablist" aria-label="Filtro de periodo da dashboard" className="mb-4 grid grid-cols-2 gap-2 rounded-2xl bg-slate-100 p-1">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'month'}
              onClick={() => {
                setActiveTab('month');
                setDisplayYear(resolveDisplayYear(value));
              }}
              className={`rounded-xl px-3 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 ${
                activeTab === 'month'
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-500 hover:text-slate-900'
              }`}
            >
              Mes
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === 'range'}
              onClick={() => {
                setActiveTab('range');
                setDisplayYear(getYear(rangeTarget === 'start' ? startMonth : endMonth));
              }}
              className={`rounded-xl px-3 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 ${
                activeTab === 'range'
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-500 hover:text-slate-900'
              }`}
            >
              Filtro
            </button>
          </div>

          {activeTab === 'range' && (
            <div className="mb-4 grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => {
                  setRangeTarget('start');
                  setDisplayYear(getYear(startMonth));
                }}
                className={`rounded-2xl border px-3 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 ${
                  rangeTarget === 'start'
                    ? 'border-slate-900 bg-slate-900 text-white'
                    : 'border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-300 hover:bg-slate-100'
                }`}
              >
                <span className="block text-[11px] uppercase tracking-wide opacity-80">Inicio</span>
                <span className="mt-1 block text-sm font-semibold">{formatMonthLabel(startMonth)}</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setRangeTarget('end');
                  setDisplayYear(getYear(endMonth));
                }}
                className={`rounded-2xl border px-3 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 ${
                  rangeTarget === 'end'
                    ? 'border-slate-900 bg-slate-900 text-white'
                    : 'border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-300 hover:bg-slate-100'
                }`}
              >
                <span className="block text-[11px] uppercase tracking-wide opacity-80">Fim</span>
                <span className="mt-1 block text-sm font-semibold">{formatMonthLabel(endMonth)}</span>
              </button>
            </div>
          )}

          <div className="mb-4 flex items-center justify-between">
            <button
              type="button"
              onClick={() => setDisplayYear((current) => current - 1)}
              aria-label="Ano anterior"
              className="rounded-2xl border border-slate-200 p-2.5 text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="text-sm font-semibold tracking-[0.08em] text-slate-700">{displayYear}</span>
            <button
              type="button"
              onClick={() => setDisplayYear((current) => current + 1)}
              aria-label="Próximo ano"
              className="rounded-2xl border border-slate-200 p-2.5 text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          <div className="grid grid-cols-3 gap-2">
            {monthLabels.map((label, monthIndex) => {
              const monthLabel = label.charAt(0).toUpperCase() + label.slice(1);
              const monthSelectionState = activeTab === 'month'
                ? (value.kind === 'month' && displayYear === getYear(value.month) && monthIndex === selectedMonth ? 'selected' : 'idle')
                : isRangeMonthSelected(monthIndex);

              return (
                <button
                  key={`${activeTab}-${displayYear}-${label}`}
                  type="button"
                  onClick={() => {
                    if (activeTab === 'month') {
                      handleMonthSelection(monthIndex);
                      return;
                    }

                    handleRangeMonthSelection(monthIndex);
                  }}
                  className={`min-h-[44px] rounded-2xl px-3 py-3 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 ${
                    monthSelectionState === 'selected' || monthSelectionState === 'edge'
                      ? 'bg-slate-900 text-white shadow-sm'
                      : monthSelectionState === 'between'
                        ? 'bg-sky-50 text-sky-700'
                        : 'bg-slate-50 text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  {monthLabel}
                </button>
              );
            })}

            {activeTab === 'month' && (
              <button
                type="button"
                onClick={() => {
                  onChange({ kind: 'all' });
                  setIsOpen(false);
                }}
                className={`col-span-3 min-h-[44px] rounded-2xl px-3 py-3 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 ${
                  value.kind === 'all'
                    ? 'bg-slate-900 text-white shadow-sm'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                }`}
              >
                Total
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

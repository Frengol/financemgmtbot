import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { format, getMonth, getYear, setMonth, startOfMonth } from 'date-fns';
import { ptBR } from 'date-fns/locale';

type CompactMonthPickerProps = {
  value: Date;
  onChange: (value: Date) => void;
};

const monthLabels = Array.from({ length: 12 }, (_, monthIndex) =>
  format(new Date(2026, monthIndex, 1), 'MMM', { locale: ptBR }),
);

function formatTriggerLabel(value: Date) {
  const label = format(value, 'MMM/yyyy', { locale: ptBR });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export default function CompactMonthPicker({ value, onChange }: CompactMonthPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [displayYear, setDisplayYear] = useState(() => getYear(value));
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setDisplayYear(getYear(value));
  }, [value]);

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

  const selectedMonth = useMemo(() => getMonth(value), [value]);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 shadow-sm transition hover:bg-slate-50"
      >
        {formatTriggerLabel(value)}
      </button>

      {isOpen && (
        <div className="absolute right-0 top-11 z-30 w-64 rounded-2xl border border-slate-200 bg-white p-3 shadow-2xl">
          <div className="mb-3 flex items-center justify-between">
            <button
              type="button"
              onClick={() => setDisplayYear((current) => current - 1)}
              className="rounded-lg border border-slate-200 p-2 text-slate-500 transition hover:bg-slate-50"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="text-sm font-semibold text-slate-700">{displayYear}</span>
            <button
              type="button"
              onClick={() => setDisplayYear((current) => current + 1)}
              className="rounded-lg border border-slate-200 p-2 text-slate-500 transition hover:bg-slate-50"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          <div className="grid grid-cols-3 gap-2">
            {monthLabels.map((label, monthIndex) => {
              const isSelected = displayYear === getYear(value) && monthIndex === selectedMonth;
              return (
                <button
                  key={`${displayYear}-${label}`}
                  type="button"
                  onClick={() => {
                    onChange(startOfMonth(setMonth(new Date(displayYear, 0, 1), monthIndex)));
                    setIsOpen(false);
                  }}
                  className={`rounded-xl px-3 py-2 text-sm font-medium transition ${
                    isSelected
                      ? 'bg-slate-900 text-white shadow-sm'
                      : 'bg-slate-50 text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  {label.charAt(0).toUpperCase() + label.slice(1)}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { format, getMonth, getYear, setMonth, startOfMonth } from 'date-fns';
import { ptBR } from 'date-fns/locale';

type CompactMonthPickerProps = {
  value: Date | null;
  onChange: (value: Date) => void;
  placeholder?: string;
  ariaLabel?: string;
  buttonClassName?: string;
  align?: 'left' | 'right';
};

const monthLabels = Array.from({ length: 12 }, (_, monthIndex) =>
  format(new Date(2026, monthIndex, 1), 'MMM', { locale: ptBR }),
);

const POPOVER_WIDTH = 256;
const POPOVER_ESTIMATED_HEIGHT = 276;
const POPOVER_GAP = 8;
const VIEWPORT_PADDING = 12;

type PopoverPosition = {
  top: number;
  left: number;
  width: number;
};

function formatTriggerLabel(value: Date | null, placeholder: string) {
  if (!value) {
    return placeholder;
  }

  const label = format(value, 'MMM/yyyy', { locale: ptBR });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function getInitialDisplayYear(value: Date | null) {
  return getYear(value || new Date());
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

export default function CompactMonthPicker({
  value,
  onChange,
  placeholder = 'Selecionar mês',
  ariaLabel,
  buttonClassName,
  align = 'right',
}: CompactMonthPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [displayYear, setDisplayYear] = useState(() => getInitialDisplayYear(value));
  const [popoverPosition, setPopoverPosition] = useState<PopoverPosition | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const triggerLabel = formatTriggerLabel(value, placeholder);

  useEffect(() => {
    if (value) {
      setDisplayYear(getYear(value));
    }
  }, [value]);

  const resolvePopoverPosition = useCallback((): PopoverPosition | null => {
    const trigger = triggerRef.current;
    if (!trigger) {
      return null;
    }

    const triggerRect = trigger.getBoundingClientRect();
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth || POPOVER_WIDTH;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || POPOVER_ESTIMATED_HEIGHT;
    const width = Math.min(POPOVER_WIDTH, Math.max(160, viewportWidth - VIEWPORT_PADDING * 2));
    const preferredLeft = align === 'left' ? triggerRect.left : triggerRect.right - width;
    const left = clamp(
      preferredLeft,
      VIEWPORT_PADDING,
      viewportWidth - width - VIEWPORT_PADDING,
    );

    let top = triggerRect.bottom + POPOVER_GAP;
    if (top + POPOVER_ESTIMATED_HEIGHT > viewportHeight - VIEWPORT_PADDING) {
      top = triggerRect.top - POPOVER_ESTIMATED_HEIGHT - POPOVER_GAP;
    }

    return {
      top: Math.max(VIEWPORT_PADDING, top),
      left,
      width,
    };
  }, [align]);

  const updatePopoverPosition = useCallback(() => {
    const nextPosition = resolvePopoverPosition();
    if (nextPosition) {
      setPopoverPosition(nextPosition);
    }
  }, [resolvePopoverPosition]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (containerRef.current?.contains(target) || popoverRef.current?.contains(target)) {
        return;
      }
      setIsOpen(false);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };

    updatePopoverPosition();
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    window.addEventListener('resize', updatePopoverPosition);
    window.addEventListener('scroll', updatePopoverPosition, true);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('resize', updatePopoverPosition);
      window.removeEventListener('scroll', updatePopoverPosition, true);
    };
  }, [isOpen, updatePopoverPosition]);

  const selectedMonth = useMemo(() => (value ? getMonth(value) : null), [value]);
  const resolvedButtonClassName = buttonClassName
    || 'rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 shadow-sm transition hover:bg-slate-50';
  const resolvedAriaLabel = ariaLabel ? `${ariaLabel}: ${triggerLabel}` : undefined;
  const popoverStyle = {
    top: `${popoverPosition?.top ?? VIEWPORT_PADDING}px`,
    left: `${popoverPosition?.left ?? VIEWPORT_PADDING}px`,
    width: `${popoverPosition?.width ?? POPOVER_WIDTH}px`,
    maxWidth: `calc(100vw - ${VIEWPORT_PADDING * 2}px)`,
  };

  const handleTriggerClick = () => {
    if (isOpen) {
      setIsOpen(false);
      return;
    }

    const nextPosition = resolvePopoverPosition();
    if (nextPosition) {
      setPopoverPosition(nextPosition);
    }
    setIsOpen(true);
  };

  const popover = isOpen
    ? createPortal(
      <div
        ref={popoverRef}
        data-testid="compact-month-picker-popover"
        className="fixed z-[120] rounded-xl border border-slate-200 bg-white p-3 shadow-2xl"
        style={popoverStyle}
      >
        <div className="mb-3 flex items-center justify-between">
          <button
            type="button"
            aria-label="Ano anterior"
            onClick={() => setDisplayYear((current) => current - 1)}
            className="rounded-lg border border-slate-200 p-2 text-slate-500 transition hover:bg-slate-50"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="text-sm font-semibold text-slate-700">{displayYear}</span>
          <button
            type="button"
            aria-label="Proximo ano"
            onClick={() => setDisplayYear((current) => current + 1)}
            className="rounded-lg border border-slate-200 p-2 text-slate-500 transition hover:bg-slate-50"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        <div className="grid grid-cols-3 gap-2" data-testid="compact-month-picker-grid">
          {monthLabels.map((label, monthIndex) => {
            const isSelected = value !== null && displayYear === getYear(value) && monthIndex === selectedMonth;
            return (
              <button
                key={`${displayYear}-${label}`}
                type="button"
                onClick={() => {
                  onChange(startOfMonth(setMonth(new Date(displayYear, 0, 1), monthIndex)));
                  setIsOpen(false);
                }}
                className={`rounded-lg px-3 py-2 text-sm font-medium transition ${
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
      </div>,
      document.body,
    )
    : null;

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={handleTriggerClick}
        aria-label={resolvedAriaLabel}
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        className={resolvedButtonClassName}
      >
        {triggerLabel}
      </button>

      {popover}
    </div>
  );
}

import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CompactMonthPicker from './CompactMonthPicker';

function mockTriggerRect(element: HTMLElement, rect: Partial<DOMRect> = {}) {
  vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({
    x: 120,
    y: 120,
    width: 180,
    height: 42,
    top: 120,
    right: 300,
    bottom: 162,
    left: 120,
    toJSON: () => ({}),
    ...rect,
  } as DOMRect);
}

describe('CompactMonthPicker', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('changes the displayed year and selects the requested month', async () => {
    const onChange = vi.fn();

    render(
      <CompactMonthPicker
        value={new Date('2026-03-01T12:00:00Z')}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /mar\/2026/i }));
    await userEvent.click(screen.getByRole('button', { name: /Proximo ano/i }));
    expect(screen.getByText('2027')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^Fev$/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const selectedDate = onChange.mock.calls[0][0] as Date;
    expect(selectedDate.getFullYear()).toBe(2027);
    expect(selectedDate.getMonth()).toBe(1);
  });

  it('closes the popover when clicking outside of the picker', async () => {
    render(
      <CompactMonthPicker
        value={new Date('2026-03-01T12:00:00Z')}
        onChange={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /mar\/2026/i }));
    expect(screen.getByRole('button', { name: /^Jan$/i })).toBeInTheDocument();

    fireEvent.mouseDown(document.body);

    expect(screen.queryByRole('button', { name: /^Jan$/i })).not.toBeInTheDocument();
  });

  it('renders the popover in document.body with fixed positioning', async () => {
    const { container } = render(
      <div className="max-h-20 overflow-hidden" data-testid="clipped-parent">
        <CompactMonthPicker
          value={new Date('2026-03-01T12:00:00Z')}
          onChange={vi.fn()}
          align="left"
        />
      </div>,
    );

    const trigger = screen.getByRole('button', { name: /mar\/2026/i });
    mockTriggerRect(trigger, {
      top: 96,
      bottom: 138,
      left: 32,
      right: 212,
      y: 96,
    });

    await userEvent.click(trigger);

    const popover = screen.getByTestId('compact-month-picker-popover');
    expect(popover.parentElement).toBe(document.body);
    expect(container).not.toContainElement(popover);
    expect(popover).toHaveClass('fixed');
    expect(popover.style.top).not.toBe('');
    expect(popover.style.left).not.toBe('');
  });

  it('closes the popover when Escape is pressed', async () => {
    render(
      <CompactMonthPicker
        value={new Date('2026-03-01T12:00:00Z')}
        onChange={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /mar\/2026/i }));
    expect(screen.getByTestId('compact-month-picker-popover')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByTestId('compact-month-picker-popover')).not.toBeInTheDocument();
  });

  it('keeps the portal width and left position inside narrow viewports', async () => {
    vi.stubGlobal('innerWidth', 220);
    vi.stubGlobal('innerHeight', 360);

    render(
      <CompactMonthPicker
        value={new Date('2026-03-01T12:00:00Z')}
        onChange={vi.fn()}
        align="left"
      />,
    );

    const trigger = screen.getByRole('button', { name: /mar\/2026/i });
    mockTriggerRect(trigger, {
      width: 64,
      height: 42,
      top: 120,
      right: 232,
      bottom: 162,
      left: 168,
      x: 168,
      y: 120,
    });

    await userEvent.click(trigger);

    const popover = screen.getByTestId('compact-month-picker-popover');
    expect(popover.style.width).toBe('196px');
    expect(popover.style.left).toBe('12px');
    expect(popover.style.maxWidth).toBe('calc(100vw - 24px)');
  });

  it('supports an empty value with a placeholder and keeps months in a three-column grid', async () => {
    const onChange = vi.fn();
    const currentYear = new Date().getFullYear();

    render(
      <CompactMonthPicker
        value={null}
        onChange={onChange}
        placeholder="Selecionar mês"
        ariaLabel="Mes de inicio"
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /Selecionar mês/i }));
    expect(screen.getByTestId('compact-month-picker-grid')).toHaveClass('grid-cols-3');
    await userEvent.click(screen.getByRole('button', { name: /Proximo ano/i }));
    expect(screen.getByText(String(currentYear + 1))).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^Fev$/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const selectedDate = onChange.mock.calls[0][0] as Date;
    expect(selectedDate.getFullYear()).toBe(currentYear + 1);
    expect(selectedDate.getMonth()).toBe(1);
  });
});

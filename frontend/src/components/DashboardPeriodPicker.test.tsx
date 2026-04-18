import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import DashboardPeriodPicker, { type DashboardPeriod } from './DashboardPeriodPicker';

describe('DashboardPeriodPicker', () => {
  it('opens on the month tab and exposes the Total action below the month grid', async () => {
    const onChange = vi.fn();

    render(
      <DashboardPeriodPicker
        value={{ kind: 'month', month: new Date('2026-04-01T12:00:00Z') }}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /abr\/2026/i }));

    expect(screen.getByRole('tab', { name: 'Mes' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('button', { name: 'Total' })).toBeInTheDocument();
  });

  it('applies the all-time total mode from the month tab', async () => {
    const onChange = vi.fn();

    render(
      <DashboardPeriodPicker
        value={{ kind: 'month', month: new Date('2026-04-01T12:00:00Z') }}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /abr\/2026/i }));
    await userEvent.click(screen.getByRole('button', { name: 'Total' }));

    expect(onChange).toHaveBeenCalledWith({ kind: 'all' });
  });

  it('shows the all-time selection as active when the current value is total', async () => {
    render(
      <DashboardPeriodPicker
        value={{ kind: 'all' }}
        onChange={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Total' }));

    const totalButtons = screen.getAllByRole('button', { name: 'Total' });
    expect(totalButtons[totalButtons.length - 1]).toHaveClass('bg-slate-900');
  });

  it('reorders the selected range months when the end month is chosen before the start month', async () => {
    const onChange = vi.fn();

    render(
      <DashboardPeriodPicker
        value={{ kind: 'month', month: new Date('2026-04-01T12:00:00Z') }}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /abr\/2026/i }));
    await userEvent.click(screen.getByRole('tab', { name: 'Filtro' }));
    await userEvent.click(screen.getByRole('button', { name: /^Inicio/i }));
    await userEvent.click(screen.getByRole('button', { name: /^Ago$/i }));
    await userEvent.click(screen.getByRole('button', { name: /^Mar$/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const selectedPeriod = onChange.mock.calls[0][0] as DashboardPeriod;

    expect(selectedPeriod.kind).toBe('range');
    if (selectedPeriod.kind !== 'range') {
      return;
    }

    expect(selectedPeriod.startMonth.getFullYear()).toBe(2026);
    expect(selectedPeriod.startMonth.getMonth()).toBe(2);
    expect(selectedPeriod.endMonth.getFullYear()).toBe(2026);
    expect(selectedPeriod.endMonth.getMonth()).toBe(7);
  });

  it('updates the draft range before applying the final month selection', async () => {
    const onChange = vi.fn();

    render(
      <DashboardPeriodPicker
        value={{
          kind: 'range',
          startMonth: new Date('2026-01-01T12:00:00Z'),
          endMonth: new Date('2026-03-01T12:00:00Z'),
        }}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /jan\/26 - mar\/26/i }));
    await userEvent.click(screen.getByRole('tab', { name: 'Filtro' }));

    expect(screen.getByRole('button', { name: /^Fev$/i })).toHaveClass('bg-sky-50');

    await userEvent.click(screen.getByRole('button', { name: /^Inicio/i }));
    await userEvent.click(screen.getByRole('button', { name: /^Fev$/i }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /^Inicio/i })).toHaveTextContent('Fev/2026');

    await userEvent.click(screen.getByRole('button', { name: /^Abr$/i }));

    expect(onChange).toHaveBeenCalledWith({
      kind: 'range',
      startMonth: expect.any(Date),
      endMonth: expect.any(Date),
    });

    const selectedPeriod = onChange.mock.calls[0][0] as DashboardPeriod;
    expect(selectedPeriod.kind).toBe('range');
    if (selectedPeriod.kind !== 'range') {
      return;
    }

    expect(selectedPeriod.startMonth.getMonth()).toBe(1);
    expect(selectedPeriod.endMonth.getMonth()).toBe(3);
  });

  it('closes the popover when clicking outside', async () => {
    render(
      <DashboardPeriodPicker
        value={{ kind: 'month', month: new Date('2026-04-01T12:00:00Z') }}
        onChange={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /abr\/2026/i }));
    expect(screen.getByRole('button', { name: /^Jan$/i })).toBeInTheDocument();

    fireEvent.mouseDown(document.body);

    expect(screen.queryByRole('button', { name: /^Jan$/i })).not.toBeInTheDocument();
  });

  it('closes the popover when pressing escape', async () => {
    render(
      <DashboardPeriodPicker
        value={{ kind: 'month', month: new Date('2026-04-01T12:00:00Z') }}
        onChange={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /abr\/2026/i }));
    expect(screen.getByRole('dialog', { name: 'Selecionar período analítico' })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog', { name: 'Selecionar período analítico' })).not.toBeInTheDocument();
  });
});

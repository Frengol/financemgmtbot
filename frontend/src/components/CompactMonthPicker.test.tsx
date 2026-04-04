import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import CompactMonthPicker from './CompactMonthPicker';

describe('CompactMonthPicker', () => {
  it('changes the displayed year and selects the requested month', async () => {
    const onChange = vi.fn();

    render(
      <CompactMonthPicker
        value={new Date('2026-03-01T12:00:00Z')}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /mar\/2026/i }));
    await userEvent.click(screen.getAllByRole('button')[2]);
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
});

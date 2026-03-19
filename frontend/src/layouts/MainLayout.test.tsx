import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import MainLayout from './MainLayout';

const mockSignOut = vi.fn();
const mockOpenCreate = vi.fn();
const mockGetTransactions = vi.fn();

vi.mock('@/lib/adminApi', () => ({
  getTransactions: (...args: unknown[]) => mockGetTransactions(...args),
}));

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    accessToken: 'token',
    user: { email: 'test@example.com' },
    signOut: mockSignOut,
  }),
}));

vi.mock('@/hooks/useTransactionComposer', () => ({
  useTransactionComposer: () => ({
    openCreate: mockOpenCreate,
  }),
}));

describe('MainLayout mobile navigation', () => {
  beforeEach(() => {
    mockGetTransactions.mockResolvedValue([]);
    mockSignOut.mockReset();
    mockOpenCreate.mockReset();
  });

  it('opens the mobile menu drawer and shows navigation links', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<MainLayout />}>
            <Route index element={<div>Dashboard content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    const dialog = screen.getByRole('dialog', { name: 'Menu de navegacao' });

    expect(dialog).toHaveClass('-translate-x-full');

    await user.click(screen.getByRole('button', { name: 'Abrir menu de navegacao' }));

    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveClass('translate-x-0');
    expect(within(dialog).getByRole('link', { name: 'Dashboard' })).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Aprovações' })).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Histórico' })).toBeInTheDocument();
  });
});

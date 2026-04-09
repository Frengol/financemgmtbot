import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import MainLayout from './MainLayout';

const mockSignOut = vi.fn();
const mockOpenCreate = vi.fn();
const mockGetTransactions = vi.fn();
const mockUseAuth = vi.fn();

vi.mock('@/lib/adminApi', () => ({
  getTransactions: (...args: unknown[]) => mockGetTransactions(...args),
}));

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock('@/hooks/useTransactionComposer', () => ({
  useTransactionComposer: () => ({
    openCreate: mockOpenCreate,
  }),
}));

describe('MainLayout mobile navigation', () => {
  beforeEach(() => {
    mockGetTransactions.mockReset();
    mockGetTransactions.mockResolvedValue({ transactions: [] });
    mockSignOut.mockReset();
    mockOpenCreate.mockReset();
    mockUseAuth.mockReset();
    mockUseAuth.mockReturnValue({
      authenticated: true,
      loading: false,
      user: { email: 'test@example.com' },
      signOut: mockSignOut,
    });
  });

  function renderLayout(initialEntry = '/') {
    return render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/" element={<MainLayout />}>
            <Route index element={<div>Dashboard content</div>} />
            <Route path="historico" element={<div>Historico content</div>} />
          </Route>
          <Route path="/auth/callback" element={<MainLayout />}>
            <Route index element={<div>Callback content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
  }

  it('opens the mobile menu drawer and shows navigation links', async () => {
    const user = userEvent.setup();

    renderLayout();

    const dialog = screen.getByRole('dialog', { name: 'Menu de navegacao' });

    expect(dialog).toHaveClass('-translate-x-full');

    await user.click(screen.getByRole('button', { name: 'Abrir menu de navegacao' }));

    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveClass('translate-x-0');
    expect(within(dialog).getByRole('link', { name: 'Dashboard' })).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Aprovações' })).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Histórico' })).toBeInTheDocument();
  });

  it('tracks online and offline state and triggers quick-create shortcuts', async () => {
    const user = userEvent.setup();
    mockGetTransactions.mockRejectedValueOnce(new Error('offline'));

    renderLayout();

    expect(await screen.findByText('Offline')).toBeInTheDocument();

    await user.keyboard('{Control>}k{/Control}');
    expect(mockOpenCreate).toHaveBeenCalledTimes(1);
  });

  it('skips the admin health check while auth is loading, unauthenticated or inside the callback route', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      loading: true,
      user: null,
      signOut: mockSignOut,
    });

    renderLayout('/auth/callback');

    expect(await screen.findByText('Offline')).toBeInTheDocument();
    expect(mockGetTransactions).not.toHaveBeenCalled();
  });

  it('closes the mobile menu on escape, overlay click, navigation and mobile sign-out', async () => {
    const user = userEvent.setup();
    renderLayout();

    const dialog = screen.getByRole('dialog', { name: 'Menu de navegacao' });
    await user.click(screen.getByRole('button', { name: 'Abrir menu de navegacao' }));
    expect(dialog).toHaveClass('translate-x-0');
    expect(document.body.style.overflow).toBe('hidden');

    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => {
      expect(dialog).toHaveClass('-translate-x-full');
    });

    await user.click(screen.getByRole('button', { name: 'Abrir menu de navegacao' }));
    const overlay = document.querySelector('button.absolute.inset-0') as HTMLButtonElement;
    expect(overlay).toBeTruthy();
    await user.click(overlay);
    await waitFor(() => {
      expect(dialog).toHaveClass('-translate-x-full');
    });

    await user.click(screen.getByRole('button', { name: 'Abrir menu de navegacao' }));
    await user.click(within(dialog).getByRole('link', { name: 'Histórico' }));
    await waitFor(() => {
      expect(dialog).toHaveClass('-translate-x-full');
    });
    expect(screen.getByRole('heading', { name: 'Histórico' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Abrir menu de navegacao' }));
    await user.click(within(dialog).getByRole('button', { name: 'Sair' }));
    await waitFor(() => {
      expect(mockSignOut).toHaveBeenCalledTimes(1);
    });
    expect(dialog).toHaveClass('-translate-x-full');
    expect(document.body.style.overflow).toBe('');
  });

  it('supports the desktop sign-out action', async () => {
    const user = userEvent.setup();
    renderLayout();

    await user.click(screen.getAllByRole('button', { name: 'Sair' })[0]);

    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });
});

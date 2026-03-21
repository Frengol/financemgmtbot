import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TransactionModal from './TransactionModal';

const mockCreateTransaction = vi.fn();
const mockUpdateTransaction = vi.fn();
const mockUseAuth = vi.fn();
const mockClose = vi.fn();
const mockSetDraft = vi.fn();
const mockComposer = vi.fn();

vi.mock('@/lib/adminApi', () => ({
  createTransaction: (...args: unknown[]) => mockCreateTransaction(...args),
  updateTransaction: (...args: unknown[]) => mockUpdateTransaction(...args),
}));

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock('@/hooks/useTransactionComposer', () => ({
  useTransactionComposer: () => mockComposer(),
}));

describe('TransactionModal', () => {
  beforeEach(() => {
    mockCreateTransaction.mockReset();
    mockUpdateTransaction.mockReset();
    mockClose.mockReset();
    mockSetDraft.mockReset();
    mockUseAuth.mockReturnValue({
      accessToken: 'token',
      loading: false,
      localBypass: false,
    });
    mockComposer.mockReturnValue({
      close: mockClose,
      draft: {
        data: '2026-03-20',
        natureza: 'Essencial',
        categoria: 'Mercado',
        descricao: 'Compra inicial',
        valor: 12.5,
        conta: 'Nubank',
        metodo_pagamento: 'Pix',
      },
      editingId: null,
      isOpen: true,
      setDraft: mockSetDraft,
    });
  });

  it('creates a transaction with parsed currency input and emits refresh', async () => {
    const eventSpy = vi.fn();
    window.addEventListener('transactions:changed', eventSpy);
    mockCreateTransaction.mockResolvedValue({
      transaction: { id: 'tx-1' },
    });

    render(<TransactionModal />);

    const valueInput = screen.getByPlaceholderText('12,50');
    await userEvent.clear(valueInput);
    await userEvent.type(valueInput, '45,90');
    await userEvent.click(screen.getAllByRole('button', { name: 'Criar transacao' })[0]);

    await waitFor(() => {
      expect(mockCreateTransaction).toHaveBeenCalledWith('token', expect.objectContaining({
        valor: 45.9,
        descricao: 'Compra inicial',
      }));
    });
    expect(mockClose).toHaveBeenCalled();
    expect(eventSpy).toHaveBeenCalled();
    window.removeEventListener('transactions:changed', eventSpy);
  });

  it('shows a session validation error before saving without access token', async () => {
    mockUseAuth.mockReturnValue({
      accessToken: '',
      loading: false,
      localBypass: false,
    });

    render(<TransactionModal />);

    await userEvent.click(screen.getByRole('button', { name: 'Criar transacao' }));

    expect(await screen.findByText('Nao foi possivel validar sua sessao. Entre novamente.')).toBeInTheDocument();
    expect(mockCreateTransaction).not.toHaveBeenCalled();
  });

  it('updates an existing transaction when editingId is present', async () => {
    mockComposer.mockReturnValue({
      close: mockClose,
      draft: {
        data: '2026-03-20',
        natureza: 'Lazer',
        categoria: 'Diversão',
        descricao: 'Cinema',
        valor: 55,
        conta: 'Nubank',
        metodo_pagamento: 'Pix',
      },
      editingId: 'tx-2',
      isOpen: true,
      setDraft: mockSetDraft,
    });
    mockUpdateTransaction.mockResolvedValue({ transaction: { id: 'tx-2' } });

    render(<TransactionModal />);

    await userEvent.click(screen.getByRole('button', { name: 'Salvar alteracoes' }));

    await waitFor(() => {
      expect(mockUpdateTransaction).toHaveBeenCalledWith('token', 'tx-2', expect.objectContaining({
        descricao: 'Cinema',
        valor: 55,
      }));
    });
  });
});

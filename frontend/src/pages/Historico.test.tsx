import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Historico from './Historico';

const mockDeleteTransaction = vi.fn();
const mockGetTransactions = vi.fn();
const mockUseAuth = vi.fn();
const mockOpenEdit = vi.fn();

vi.mock('@/lib/adminApi', () => ({
  deleteTransaction: (...args: unknown[]) => mockDeleteTransaction(...args),
  getTransactions: (...args: unknown[]) => mockGetTransactions(...args),
}));

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock('@/hooks/useTransactionComposer', () => ({
  useTransactionComposer: () => ({
    openEdit: mockOpenEdit,
  }),
}));

describe('Historico', () => {
  beforeEach(() => {
    mockDeleteTransaction.mockReset();
    mockGetTransactions.mockReset();
    mockOpenEdit.mockReset();
    mockUseAuth.mockReturnValue({
      authenticated: true,
      csrfToken: 'csrf-token',
      loading: false,
      localBypass: false,
    });

    vi.stubGlobal('confirm', vi.fn(() => true));
  });

  it('loads transactions, normalizes fallbacks and deletes a row', async () => {
    const eventSpy = vi.fn();
    window.addEventListener('transactions:changed', eventSpy);
    mockGetTransactions
      .mockResolvedValueOnce({
        transactions: [{
          id: 'tx-1',
          data: '2026-03-19',
          natureza: 'Essencial',
          categoria: 'Mercado',
          descricao: 'Compra do mes',
          valor: 99.9,
          conta: '',
          metodo_pagamento: '',
        }],
      })
      .mockResolvedValueOnce({
        transactions: [],
      });
    mockDeleteTransaction.mockResolvedValue({ id: 'tx-1' });

    render(<Historico />);

    expect(await screen.findByText('Compra do mes')).toBeInTheDocument();
    expect(screen.getByText('Nao Informada')).toBeInTheDocument();

    await userEvent.click(screen.getAllByTitle('Excluir')[0]);

    await waitFor(() => {
      expect(mockDeleteTransaction).toHaveBeenCalledWith('tx-1', 'csrf-token');
    });
    await waitFor(() => {
      expect(screen.queryByText('Compra do mes')).not.toBeInTheDocument();
    });
    expect(eventSpy).toHaveBeenCalled();
    window.removeEventListener('transactions:changed', eventSpy);
  });

  it('shows auth error before deleting when the session is unavailable', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: true,
      csrfToken: '',
      loading: false,
      localBypass: false,
    });
    mockGetTransactions.mockResolvedValue({
      transactions: [{
        id: 'tx-1',
        data: '2026-03-19',
        natureza: 'Essencial',
        categoria: 'Mercado',
        descricao: 'Compra',
        valor: 10,
        conta: 'Nubank',
        metodo_pagamento: 'Pix',
      }],
    });

    render(<Historico />);

    expect(await screen.findByText('Compra')).toBeInTheDocument();
    await userEvent.click(screen.getAllByTitle('Excluir')[0]);

    expect(await screen.findByText('Nao foi possivel validar sua sessao. Entre novamente.')).toBeInTheDocument();
    expect(mockDeleteTransaction).not.toHaveBeenCalled();
  });

  it('opens edit mode with the selected transaction', async () => {
    mockGetTransactions.mockResolvedValue({
      transactions: [{
        id: 'tx-2',
        data: '2026-03-19',
        natureza: 'Lazer',
        categoria: 'Diversão',
        descricao: 'Cinema com amigos',
        valor: 55,
        conta: 'Nubank',
        metodo_pagamento: 'Pix',
      }],
    });

    render(<Historico />);

    expect(await screen.findByText('Cinema com amigos')).toBeInTheDocument();
    await userEvent.click(screen.getAllByTitle('Editar')[0]);

    expect(mockOpenEdit).toHaveBeenCalledWith(expect.objectContaining({
      id: 'tx-2',
      descricao: 'Cinema com amigos',
    }));
  });
});

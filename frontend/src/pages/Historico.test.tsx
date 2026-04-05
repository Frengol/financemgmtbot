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

  it('shows the mapped backend error when the history cannot be loaded', async () => {
    mockGetTransactions.mockRejectedValue(new Error('Nao foi possivel carregar os dados agora. Codigo de suporte: req_hist_1'));

    render(<Historico />);

    expect(await screen.findByText(/Nao foi possivel carregar os dados agora/i)).toBeInTheDocument();
    expect(screen.getByText(/Codigo de suporte: req_hist_1/i)).toBeInTheDocument();
  });

  it('skips loading history when the session is unavailable', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      csrfToken: '',
      loading: false,
      localBypass: false,
    });

    render(<Historico />);

    expect(await screen.findByText('Mostrando 0 registros')).toBeInTheDocument();
    expect(mockGetTransactions).not.toHaveBeenCalled();
  });

  it('does not delete when the confirmation dialog is cancelled', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false));
    mockGetTransactions.mockResolvedValue({
      transactions: [{
        id: 'tx-3',
        data: '2026-03-19',
        natureza: 'Essencial',
        categoria: 'Mercado',
        descricao: 'Compra protegida',
        valor: 10,
        conta: 'Nubank',
        metodo_pagamento: 'Pix',
      }],
    });

    render(<Historico />);

    expect(await screen.findByText('Compra protegida')).toBeInTheDocument();
    await userEvent.click(screen.getAllByTitle('Excluir')[0]);
    expect(mockDeleteTransaction).not.toHaveBeenCalled();
  });

  it('shows an auth loading error before deleting', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: true,
      csrfToken: 'csrf-token',
      loading: true,
      localBypass: false,
    });
    mockGetTransactions.mockResolvedValue({
      transactions: [{
        id: 'tx-4',
        data: '2026-03-19',
        natureza: 'Essencial',
        categoria: 'Mercado',
        descricao: 'Compra aguardando auth',
        valor: 10,
        conta: 'Nubank',
        metodo_pagamento: 'Pix',
      }],
    });

    render(<Historico />);
    expect(await screen.findByText('Compra aguardando auth')).toBeInTheDocument();
    await userEvent.click(screen.getAllByTitle('Excluir')[0]);
    expect(await screen.findByText('Sua autenticacao ainda esta sendo carregada. Tente novamente em alguns segundos.')).toBeInTheDocument();
  });

  it('filters, paginates and allows local bypass deletes', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      csrfToken: '',
      loading: false,
      localBypass: true,
    });
    mockGetTransactions.mockResolvedValue({
      transactions: Array.from({ length: 11 }, (_, index) => ({
        id: `tx-${index + 1}`,
        data: `2026-03-${String(index + 1).padStart(2, '0')}`,
        natureza: 'Essencial',
        categoria: index === 10 ? 'Viagem' : 'Mercado',
        descricao: index === 10 ? 'Viagem especial' : `Compra ${index + 1}`,
        valor: index + 1,
        conta: 'Nubank',
        metodo_pagamento: 'Pix',
      })),
    });
    mockDeleteTransaction.mockResolvedValue({ id: 'tx-11' });

    render(<Historico />);

    expect(await screen.findByText('Compra 1')).toBeInTheDocument();
    expect(screen.getByText('Mostrando 10 registros')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Próxima' }));
    expect(await screen.findByText('Viagem especial')).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText('Buscar (ex: Mercado)...'), 'Viagem');
    expect(await screen.findByText('Viagem especial')).toBeInTheDocument();
    expect(screen.queryByText('Compra 1')).not.toBeInTheDocument();

    await userEvent.click(screen.getAllByTitle('Excluir')[0]);
    await waitFor(() => {
      expect(mockDeleteTransaction).toHaveBeenCalledWith('tx-11', '');
    });
  });
});

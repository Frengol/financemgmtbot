import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Historico from './Historico';
import { ApiError } from '@/features/admin/api';

const mockDeleteTransaction = vi.fn();
const mockGetTransactions = vi.fn();
const mockUseAuth = vi.fn();
const mockOpenEdit = vi.fn();
const mockSignOut = vi.fn();

vi.mock('@/features/admin/api', async () => {
  const actual = await vi.importActual<typeof import('@/features/admin/api')>('@/features/admin/api');
  return {
    ...actual,
    deleteTransaction: (...args: unknown[]) => mockDeleteTransaction(...args),
    getTransactions: (...args: unknown[]) => mockGetTransactions(...args),
  };
});

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
    mockSignOut.mockReset();
    mockUseAuth.mockReturnValue({
      authenticated: true,
      loading: false,
      localBypass: false,
      signOut: mockSignOut,
    });

    vi.stubGlobal('confirm', vi.fn(() => true));
  });

  it('loads transactions, normalizes fallbacks and deletes a row with bearer-only auth state', async () => {
    const eventSpy = vi.fn();
    window.addEventListener('transactions:changed', eventSpy);
    mockUseAuth.mockReturnValue({
      authenticated: true,
      loading: false,
      localBypass: false,
      signOut: mockSignOut,
    });
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
      expect(mockDeleteTransaction).toHaveBeenCalledWith('tx-1');
    });
    await waitFor(() => {
      expect(screen.queryByText('Compra do mes')).not.toBeInTheDocument();
    });
    expect(eventSpy).toHaveBeenCalled();
    window.removeEventListener('transactions:changed', eventSpy);
  });

  it('keeps the history empty when the admin session is unavailable', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
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

    expect(await screen.findByText('Mostrando 0 registros')).toBeInTheDocument();
    expect(screen.queryByText('Compra')).not.toBeInTheDocument();
    expect(screen.queryByTitle('Excluir')).not.toBeInTheDocument();
    expect(mockDeleteTransaction).not.toHaveBeenCalled();
  });

  it('shows an auth error when the session becomes unavailable after a row is already loaded', async () => {
    const authState = {
      authenticated: true,
      loading: false,
      localBypass: false,
      signOut: mockSignOut,
    };
    mockUseAuth.mockImplementation(() => authState);
    mockGetTransactions.mockResolvedValue({
      transactions: [{
        id: 'tx-1',
        data: '2026-03-19',
        natureza: 'Essencial',
        categoria: 'Mercado',
        descricao: 'Compra protegida por sessao',
        valor: 10,
        conta: 'Nubank',
        metodo_pagamento: 'Pix',
      }],
    });

    const { rerender } = render(<Historico />);

    expect(await screen.findByText('Compra protegida por sessao')).toBeInTheDocument();

    await act(async () => {
      authState.authenticated = false;
      rerender(<Historico />);
    });

    expect(await screen.findByText('Sua sessao expirou. Faca login novamente.')).toBeInTheDocument();
    expect(screen.getByText('Compra protegida por sessao')).toBeInTheDocument();
    await userEvent.click(screen.getAllByTitle('Excluir')[0]);
    window.dispatchEvent(new CustomEvent('transactions:changed'));

    expect(mockDeleteTransaction).not.toHaveBeenCalled();
    expect(mockGetTransactions).toHaveBeenCalledTimes(1);
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

  it('offers re-login instead of generic retry when the auth token is malformed', async () => {
    mockGetTransactions.mockRejectedValue(new ApiError(
      'Sua sessao de acesso e invalida. Faca login novamente. Codigo de suporte: req_hist_auth Detalhe: bearer_malformed',
      {
        code: 'AUTH_SESSION_TOKEN_MALFORMED',
        detail: 'bearer_malformed',
        status: 401,
        requestId: 'req_hist_auth',
      },
    ));

    render(<Historico />);

    expect(await screen.findByText(/detalhe: bearer_malformed/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Fazer login novamente' }));
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });

  it('offers re-login when deleting fails with malformed auth', async () => {
    mockGetTransactions.mockResolvedValue({
      transactions: [{
        id: 'tx-auth-delete',
        data: '2026-03-19',
        natureza: 'Essencial',
        categoria: 'Mercado',
        descricao: 'Compra com token invalido',
        valor: 10,
        conta: 'Nubank',
        metodo_pagamento: 'Pix',
      }],
    });
    mockDeleteTransaction.mockRejectedValue(new ApiError(
      'Sua sessao de acesso e invalida. Faca login novamente. Codigo de suporte: req_hist_delete_auth Detalhe: bearer_malformed',
      {
        code: 'AUTH_SESSION_TOKEN_MALFORMED',
        detail: 'bearer_malformed',
        status: 401,
        requestId: 'req_hist_delete_auth',
      },
    ));

    render(<Historico />);

    expect(await screen.findByText('Compra com token invalido')).toBeInTheDocument();
    await userEvent.click(screen.getAllByTitle('Excluir')[0]);

    expect(await screen.findByText(/detalhe: bearer_malformed/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Fazer login novamente' }));
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });

  it('skips loading history when the session is unavailable', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      loading: false,
      localBypass: false,
    });

    render(<Historico />);

    expect(await screen.findByText('Mostrando 0 registros')).toBeInTheDocument();
    expect(mockGetTransactions).not.toHaveBeenCalled();
  });

  it('ignores refresh events while the session is unavailable and no rows are loaded', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      loading: false,
      localBypass: false,
    });

    render(<Historico />);

    expect(await screen.findByText('Mostrando 0 registros')).toBeInTheDocument();
    window.dispatchEvent(new CustomEvent('transactions:changed'));

    expect(mockGetTransactions).not.toHaveBeenCalled();
    expect(screen.queryByText('Nao foi possivel validar sua sessao. Entre novamente.')).not.toBeInTheDocument();
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

    await userEvent.click(screen.getByRole('button', { name: 'Anterior' }));
    expect(await screen.findByText('Compra 1')).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText('Buscar (ex: Mercado)...'), 'Viagem');
    expect(await screen.findByText('Viagem especial')).toBeInTheDocument();
    expect(screen.queryByText('Compra 1')).not.toBeInTheDocument();

    await userEvent.click(screen.getAllByTitle('Excluir')[0]);
    await waitFor(() => {
      expect(mockDeleteTransaction).toHaveBeenCalledWith('tx-11');
    });
  });
});

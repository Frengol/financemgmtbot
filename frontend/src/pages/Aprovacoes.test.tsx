import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Aprovacoes from './Aprovacoes';
import { ApiError } from '@/features/admin/api';

const mockApprovePendingReceipt = vi.fn();
const mockGetPendingReceipts = vi.fn();
const mockRejectPendingReceipt = vi.fn();
const mockUseAuth = vi.fn();
const mockSignOut = vi.fn();

vi.mock('@/features/admin/api', async () => {
  const actual = await vi.importActual<typeof import('@/features/admin/api')>('@/features/admin/api');
  return {
    ...actual,
    approvePendingReceipt: (...args: unknown[]) => mockApprovePendingReceipt(...args),
    getPendingReceipts: (...args: unknown[]) => mockGetPendingReceipts(...args),
    rejectPendingReceipt: (...args: unknown[]) => mockRejectPendingReceipt(...args),
  };
});

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => mockUseAuth(),
}));

describe('Aprovacoes', () => {
  beforeEach(() => {
    mockApprovePendingReceipt.mockReset();
    mockGetPendingReceipts.mockReset();
    mockRejectPendingReceipt.mockReset();
    mockSignOut.mockReset();
    mockUseAuth.mockReturnValue({
      authenticated: true,
      localBypass: false,
      signOut: mockSignOut,
    });
  });

  it('loads pending receipts and approves one item with bearer-only auth state', async () => {
    const eventSpy = vi.fn();
    window.addEventListener('transactions:changed', eventSpy);
    mockUseAuth.mockReturnValue({
      authenticated: true,
      localBypass: false,
      signOut: mockSignOut,
    });
    mockGetPendingReceipts.mockResolvedValue({
      items: [{
        id: 'C1',
        kind: 'receipt_batch',
        expires_at: '2026-03-20T10:00:00Z',
        created_at: '2026-03-19T10:00:00Z',
        preview: {
          summary: 'Cupom pendente',
          metodo_pagamento: 'Pix',
          conta: 'Nubank',
          itens_count: 2,
          total_estimado: 20,
          itens: ['Arroz', 'Feijao'],
        },
      }],
    });
    mockApprovePendingReceipt.mockResolvedValue({ id: 'C1', linhas: 2, total: 21 });

    render(<Aprovacoes />);

    expect(await screen.findByText(/Cupom pendente/i)).toBeInTheDocument();
    expect(screen.getByText(/Arroz/)).toBeInTheDocument();
    expect(screen.getByText(/Total: R\$ 20.00/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Aprovar/i }));

    await waitFor(() => {
      expect(mockApprovePendingReceipt).toHaveBeenCalledWith('C1');
    });
    await waitFor(() => {
      expect(screen.queryByText('Arroz')).not.toBeInTheDocument();
    });
    expect(eventSpy).toHaveBeenCalled();
    window.removeEventListener('transactions:changed', eventSpy);
  });

  it('keeps approvals empty when the admin session is unavailable before rejection', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      localBypass: false,
    });
    mockGetPendingReceipts.mockResolvedValue({
      items: [{
        id: 'C2',
        kind: 'receipt_batch',
        expires_at: '2026-03-20T10:00:00Z',
        created_at: '2026-03-19T10:00:00Z',
        preview: { itens: ['Cafe'], itens_count: 1, total_estimado: 8 },
      }],
    });

    render(<Aprovacoes />);

    expect(await screen.findByText('A caixa de aprovações está vazia. Tudo atualizado!')).toBeInTheDocument();
    expect(screen.queryByText(/Cafe/)).not.toBeInTheDocument();
    expect(mockRejectPendingReceipt).not.toHaveBeenCalled();
  });

  it('keeps approvals empty when the admin session is unavailable before approval', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      localBypass: false,
    });
    mockGetPendingReceipts.mockResolvedValue({
      items: [{
        id: 'C2A',
        kind: 'receipt_batch',
        expires_at: '2026-03-20T10:00:00Z',
        created_at: '2026-03-19T10:00:00Z',
        preview: { itens: ['Leite'], itens_count: 1, total_estimado: 7 },
      }],
    });

    render(<Aprovacoes />);

    expect(await screen.findByText('A caixa de aprovações está vazia. Tudo atualizado!')).toBeInTheDocument();
    expect(screen.queryByText(/Leite/)).not.toBeInTheDocument();
    expect(mockApprovePendingReceipt).not.toHaveBeenCalled();
  });

  it('shows a session error when approval becomes unavailable after the item is already loaded', async () => {
    const authState = {
      authenticated: true,
      localBypass: false,
      signOut: mockSignOut,
    };
    mockUseAuth.mockImplementation(() => authState);
    mockGetPendingReceipts.mockResolvedValue({
      items: [{
        id: 'C2B',
        kind: 'receipt_batch',
        expires_at: '2026-03-20T10:00:00Z',
        created_at: '2026-03-19T10:00:00Z',
        preview: { itens: ['Leite'], itens_count: 1, total_estimado: 7 },
      }],
    });

    const { rerender } = render(<Aprovacoes />);

    expect(await screen.findByText(/Leite/)).toBeInTheDocument();

    await act(async () => {
      authState.authenticated = false;
      rerender(<Aprovacoes />);
    });

    expect(await screen.findByText('Sua sessao expirou. Faca login novamente.')).toBeInTheDocument();
    expect(screen.getByText(/Leite/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Aprovar/i }));
    window.dispatchEvent(new CustomEvent('transactions:changed'));

    expect(mockApprovePendingReceipt).not.toHaveBeenCalled();
    expect(mockGetPendingReceipts).toHaveBeenCalledTimes(1);
  });

  it('shows a session error when rejection becomes unavailable after the item is already loaded', async () => {
    const authState = {
      authenticated: true,
      localBypass: false,
      signOut: mockSignOut,
    };
    mockUseAuth.mockImplementation(() => authState);
    mockGetPendingReceipts.mockResolvedValue({
      items: [{
        id: 'C2C',
        kind: 'receipt_batch',
        expires_at: '2026-03-20T10:00:00Z',
        created_at: '2026-03-19T10:00:00Z',
        preview: { itens: ['Cafe'], itens_count: 1, total_estimado: 8 },
      }],
    });

    const { rerender } = render(<Aprovacoes />);

    expect(await screen.findByText(/Cafe/)).toBeInTheDocument();

    await act(async () => {
      authState.authenticated = false;
      rerender(<Aprovacoes />);
    });

    expect(await screen.findByText('Sua sessao expirou. Faca login novamente.')).toBeInTheDocument();
    expect(screen.getByText(/Cafe/)).toBeInTheDocument();
    const buttons = screen.getAllByRole('button');
    await userEvent.click(buttons[buttons.length - 1]);
    window.dispatchEvent(new CustomEvent('transactions:changed'));

    expect(mockRejectPendingReceipt).not.toHaveBeenCalled();
    expect(mockGetPendingReceipts).toHaveBeenCalledTimes(1);
  });

  it('renders the empty state when there are no pending receipts', async () => {
    mockGetPendingReceipts.mockResolvedValue({ items: [] });

    render(<Aprovacoes />);

    expect(await screen.findByText('A caixa de aprovações está vazia. Tudo atualizado!')).toBeInTheDocument();
  });

  it('skips loading when the admin session is unavailable', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      localBypass: false,
    });

    render(<Aprovacoes />);

    expect(await screen.findByText('A caixa de aprovações está vazia. Tudo atualizado!')).toBeInTheDocument();
    expect(mockGetPendingReceipts).not.toHaveBeenCalled();
  });

  it('ignores refresh events while the admin session is unavailable and the queue is empty', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      localBypass: false,
    });

    render(<Aprovacoes />);

    expect(await screen.findByText('A caixa de aprovações está vazia. Tudo atualizado!')).toBeInTheDocument();
    window.dispatchEvent(new CustomEvent('transactions:changed'));

    expect(mockGetPendingReceipts).not.toHaveBeenCalled();
    expect(screen.queryByText('Sua sessão expirou. Faça login novamente.')).not.toBeInTheDocument();
  });

  it('renders delete confirmations and rejects them successfully with bearer-only auth state', async () => {
    const eventSpy = vi.fn();
    window.addEventListener('transactions:changed', eventSpy);
    mockUseAuth.mockReturnValue({
      authenticated: true,
      localBypass: false,
      signOut: mockSignOut,
    });
    mockGetPendingReceipts
      .mockResolvedValueOnce({
        items: [{
          id: 'D1',
          kind: 'delete_confirmation',
          expires_at: '2026-03-20T10:00:00Z',
          created_at: '2026-03-19T10:00:00Z',
          preview: {
            summary: 'Excluir registros',
            records_count: 2,
            itens: [],
          },
        }],
      })
      .mockResolvedValueOnce({ items: [] });
    mockRejectPendingReceipt.mockResolvedValue({ id: 'D1' });

    render(<Aprovacoes />);

    expect(await screen.findByText(/Excluir registros/i)).toBeInTheDocument();
    expect(screen.getByText(/Registros: 2/i)).toBeInTheDocument();
    expect(screen.getByText(/Aguardando confirmacao da exclusao segura/i)).toBeInTheDocument();

    await userEvent.click(screen.getAllByRole('button')[1]);

    await waitFor(() => {
      expect(mockRejectPendingReceipt).toHaveBeenCalledWith('D1');
    });
    await waitFor(() => {
      expect(screen.queryByText(/Excluir registros/i)).not.toBeInTheDocument();
    });
    expect(eventSpy).toHaveBeenCalled();
    window.removeEventListener('transactions:changed', eventSpy);
  });

  it('shows the mapped backend error when pending receipts cannot be loaded', async () => {
    mockGetPendingReceipts.mockRejectedValue(new Error('Nao foi possivel carregar os dados agora. Codigo de suporte: req_pending_1'));

    render(<Aprovacoes />);

    expect(await screen.findByText(/Nao foi possivel carregar os dados agora/i)).toBeInTheDocument();
    expect(screen.getByText(/Codigo de suporte: req_pending_1/i)).toBeInTheDocument();
  });

  it('offers re-login when pending approvals fail with malformed auth', async () => {
    mockGetPendingReceipts.mockRejectedValue(new ApiError(
      'Sua sessao de acesso e invalida. Faca login novamente. Codigo de suporte: req_pending_auth Detalhe: bearer_malformed',
      {
        code: 'AUTH_SESSION_TOKEN_MALFORMED',
        detail: 'bearer_malformed',
        status: 401,
        requestId: 'req_pending_auth',
      },
    ));

    render(<Aprovacoes />);

    expect(await screen.findByText(/detalhe: bearer_malformed/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Fazer login novamente' }));
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });

  it('offers re-login when rejection fails with malformed auth', async () => {
    mockGetPendingReceipts.mockResolvedValue({
      items: [{
        id: 'D-auth',
        kind: 'delete_confirmation',
        expires_at: '2026-03-20T10:00:00Z',
        created_at: '2026-03-19T10:00:00Z',
        preview: {
          summary: 'Excluir registros',
          records_count: 1,
          itens: [],
        },
      }],
    });
    mockRejectPendingReceipt.mockRejectedValue(new ApiError(
      'Sua sessao de acesso e invalida. Faca login novamente. Codigo de suporte: req_pending_reject_auth Detalhe: bearer_malformed',
      {
        code: 'AUTH_SESSION_TOKEN_MALFORMED',
        detail: 'bearer_malformed',
        status: 401,
        requestId: 'req_pending_reject_auth',
      },
    ));

    render(<Aprovacoes />);

    expect(await screen.findByText(/Excluir registros/i)).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole('button')[1]);

    expect(await screen.findByText(/detalhe: bearer_malformed/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Fazer login novamente' }));
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });

  it('offers re-login when approval fails with malformed auth', async () => {
    mockGetPendingReceipts.mockResolvedValue({
      items: [{
        id: 'D-approve-auth',
        kind: 'receipt_batch',
        expires_at: '2026-03-20T10:00:00Z',
        created_at: '2026-03-19T10:00:00Z',
        preview: {
          summary: 'Cupom pendente',
          itens: ['Arroz'],
          itens_count: 1,
          total_estimado: 10,
        },
      }],
    });
    mockApprovePendingReceipt.mockRejectedValue(new ApiError(
      'Sua sessao de acesso e invalida. Faca login novamente. Codigo de suporte: req_pending_approve_auth Detalhe: bearer_malformed',
      {
        code: 'AUTH_SESSION_TOKEN_MALFORMED',
        detail: 'bearer_malformed',
        status: 401,
        requestId: 'req_pending_approve_auth',
      },
    ));

    render(<Aprovacoes />);

    expect(await screen.findByText(/Arroz/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Aprovar/i }));

    expect(await screen.findByText(/detalhe: bearer_malformed/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Fazer login novamente' }));
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });

  it('falls back to the generic loading error when the rejection is not an Error instance', async () => {
    mockGetPendingReceipts.mockRejectedValue('falha-crua');

    render(<Aprovacoes />);

    expect(await screen.findByText('Nao foi possivel carregar as aprovacoes agora.')).toBeInTheDocument();
  });

  it('surfaces action errors when approval fails', async () => {
    mockGetPendingReceipts.mockResolvedValue({
      items: [{
        id: 'C3',
        kind: 'receipt_batch',
        expires_at: '2026-03-20T10:00:00Z',
        created_at: '2026-03-19T10:00:00Z',
        preview: {
          summary: 'Cupom pendente',
          metodo_pagamento: 'Pix',
          conta: 'Nubank',
          itens_count: 1,
          total_estimado: 10,
          itens: ['Cafe'],
        },
      }],
    });
    mockApprovePendingReceipt.mockRejectedValue(new Error('Nao foi possivel aprovar agora. Codigo de suporte: req_approve_1'));

    render(<Aprovacoes />);

    expect(await screen.findByText(/Cafe/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Aprovar/i }));

    expect(await screen.findByText(/Nao foi possivel aprovar agora/i)).toBeInTheDocument();
    expect(screen.getByText(/Codigo de suporte: req_approve_1/i)).toBeInTheDocument();
  });
});

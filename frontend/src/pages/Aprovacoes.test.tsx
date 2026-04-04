import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Aprovacoes from './Aprovacoes';

const mockApprovePendingReceipt = vi.fn();
const mockGetPendingReceipts = vi.fn();
const mockRejectPendingReceipt = vi.fn();
const mockUseAuth = vi.fn();

vi.mock('@/lib/adminApi', () => ({
  approvePendingReceipt: (...args: unknown[]) => mockApprovePendingReceipt(...args),
  getPendingReceipts: (...args: unknown[]) => mockGetPendingReceipts(...args),
  rejectPendingReceipt: (...args: unknown[]) => mockRejectPendingReceipt(...args),
}));

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => mockUseAuth(),
}));

describe('Aprovacoes', () => {
  beforeEach(() => {
    mockApprovePendingReceipt.mockReset();
    mockGetPendingReceipts.mockReset();
    mockRejectPendingReceipt.mockReset();
    mockUseAuth.mockReturnValue({
      authenticated: true,
      csrfToken: 'csrf-token',
      localBypass: false,
    });
  });

  it('loads pending receipts and approves one item', async () => {
    const eventSpy = vi.fn();
    window.addEventListener('transactions:changed', eventSpy);
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
      expect(mockApprovePendingReceipt).toHaveBeenCalledWith('C1', 'csrf-token');
    });
    await waitFor(() => {
      expect(screen.queryByText('Arroz')).not.toBeInTheDocument();
    });
    expect(eventSpy).toHaveBeenCalled();
    window.removeEventListener('transactions:changed', eventSpy);
  });

  it('shows session error before rejecting when there is no access token', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: true,
      csrfToken: '',
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

    expect(await screen.findByText(/Cafe/)).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole('button')[1]);

    expect(await screen.findByText('Sua sessão expirou. Faça login novamente.')).toBeInTheDocument();
    expect(mockRejectPendingReceipt).not.toHaveBeenCalled();
  });

  it('renders the empty state when there are no pending receipts', async () => {
    mockGetPendingReceipts.mockResolvedValue({ items: [] });

    render(<Aprovacoes />);

    expect(await screen.findByText('A caixa de aprovações está vazia. Tudo atualizado!')).toBeInTheDocument();
  });
});

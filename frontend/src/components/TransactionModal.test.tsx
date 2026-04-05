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
      authenticated: true,
      csrfToken: 'csrf-token',
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
      expect(mockCreateTransaction).toHaveBeenCalledWith(expect.objectContaining({
        valor: 45.9,
        descricao: 'Compra inicial',
      }), 'csrf-token');
    });
    expect(mockClose).toHaveBeenCalled();
    expect(eventSpy).toHaveBeenCalled();
    window.removeEventListener('transactions:changed', eventSpy);
  });

  it('shows a session validation error before saving without access token', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      csrfToken: '',
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
      expect(mockUpdateTransaction).toHaveBeenCalledWith('tx-2', expect.objectContaining({
        descricao: 'Cinema',
        valor: 55,
      }), 'csrf-token');
    });
  });

  it('normalizes invalid categories for the selected nature', () => {
    mockComposer.mockReturnValue({
      close: mockClose,
      draft: {
        data: '2026-03-20',
        natureza: 'Essencial',
        categoria: 'Diversão',
        descricao: 'Compra inicial',
        valor: 12.5,
        conta: 'Nubank',
        metodo_pagamento: 'Pix',
      },
      editingId: null,
      isOpen: true,
      setDraft: mockSetDraft,
    });

    render(<TransactionModal />);
    expect(mockSetDraft).toHaveBeenCalledWith(expect.objectContaining({ categoria: 'Moradia' }));
  });

  it('returns null when the composer is closed', () => {
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
      isOpen: false,
      setDraft: mockSetDraft,
    });

    const { container } = render(<TransactionModal />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows auth loading error before submitting', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: true,
      csrfToken: 'csrf-token',
      loading: true,
      localBypass: false,
    });

    render(<TransactionModal />);

    await userEvent.click(screen.getByRole('button', { name: 'Criar transacao' }));
    expect(await screen.findByText('Aguarde a autenticacao concluir antes de salvar.')).toBeInTheDocument();
  });

  it('shows validation errors for invalid numeric input', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: true,
      csrfToken: 'csrf-token',
      loading: false,
      localBypass: false,
    });

    render(<TransactionModal />);
    const valueInput = screen.getByPlaceholderText('12,50');
    await userEvent.clear(valueInput);
    await userEvent.type(valueInput, ',');
    await userEvent.click(screen.getByRole('button', { name: 'Criar transacao' }));

    expect(await screen.findByText('Informe um valor numerico valido usando virgula para os centavos.')).toBeInTheDocument();
    expect(mockCreateTransaction).not.toHaveBeenCalled();
  });

  it('surfaces backend save errors, supports local bypass and allows closing the modal', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      csrfToken: '',
      loading: false,
      localBypass: true,
    });
    mockCreateTransaction.mockRejectedValueOnce(new Error('Nao foi possivel salvar agora.'));

    render(<TransactionModal />);

    await userEvent.click(screen.getByRole('button', { name: 'Criar transacao' }));
    expect(await screen.findByText('Nao foi possivel salvar agora.')).toBeInTheDocument();

    mockCreateTransaction.mockResolvedValueOnce({ transaction: { id: 'tx-3' } });
    await userEvent.click(screen.getByRole('button', { name: 'Criar transacao' }));
    await waitFor(() => {
      expect(mockCreateTransaction).toHaveBeenLastCalledWith(expect.objectContaining({ descricao: 'Compra inicial' }), '');
    });

    await userEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(mockClose).toHaveBeenCalled();
  });

  it('updates category options when the nature changes and closes from the icon button', async () => {
    render(<TransactionModal />);

    await userEvent.selectOptions(screen.getByDisplayValue('Essencial'), 'Lazer');

    expect(mockSetDraft).toHaveBeenCalledWith(expect.objectContaining({
      natureza: 'Lazer',
      categoria: 'Bares e Restaurantes',
    }));

    await userEvent.click(screen.getAllByRole('button')[0]);
    expect(mockClose).toHaveBeenCalled();
  });

  it('falls back to the generic save error when the backend rejects with a non-error value', async () => {
    mockCreateTransaction.mockRejectedValueOnce('falha-bruta');

    render(<TransactionModal />);

    await userEvent.click(screen.getByRole('button', { name: 'Criar transacao' }));

    expect(await screen.findByText('Nao foi possivel salvar a transacao.')).toBeInTheDocument();
  });
});

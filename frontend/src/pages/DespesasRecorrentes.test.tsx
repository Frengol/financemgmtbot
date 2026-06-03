import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DespesasRecorrentes from './DespesasRecorrentes';
import { ApiError } from '@/features/admin/api';

const mockGetRecurringExpenses = vi.fn();
const mockCreateRecurringExpense = vi.fn();
const mockUpdateRecurringExpense = vi.fn();
const mockDeleteRecurringExpense = vi.fn();
const mockUseAuth = vi.fn();
const mockSignOut = vi.fn();

vi.mock('@/features/admin/api', async () => {
  const actual = await vi.importActual<typeof import('@/features/admin/api')>('@/features/admin/api');
  return {
    ...actual,
    getRecurringExpenses: (...args: unknown[]) => mockGetRecurringExpenses(...args),
    createRecurringExpense: (...args: unknown[]) => mockCreateRecurringExpense(...args),
    updateRecurringExpense: (...args: unknown[]) => mockUpdateRecurringExpense(...args),
    deleteRecurringExpense: (...args: unknown[]) => mockDeleteRecurringExpense(...args),
  };
});

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => mockUseAuth(),
}));

const sampleRecord = {
  id: 'rec-1',
  nome: 'Netflix',
  valor: 39.9,
  mes_inicio: '2026-04-01',
  mes_fim: null,
  dia_mes: 5,
  natureza: 'Lazer' as const,
  categoria: 'Diversão',
  metodo_pagamento: 'Cartao de Credito',
  conta: 'Nubank',
  ativo: true,
};

describe('DespesasRecorrentes', () => {
  beforeEach(() => {
    mockGetRecurringExpenses.mockReset();
    mockCreateRecurringExpense.mockReset();
    mockUpdateRecurringExpense.mockReset();
    mockDeleteRecurringExpense.mockReset();
    mockSignOut.mockReset();
    mockUseAuth.mockReturnValue({
      authenticated: true,
      loading: false,
      localBypass: false,
      signOut: mockSignOut,
    });
    vi.stubGlobal('confirm', vi.fn(() => true));
  });

  it('renders the empty state with a call-to-action when no records exist', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [] });

    render(<DespesasRecorrentes />);

    expect(await screen.findByText('Nenhuma despesa recorrente cadastrada')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Nova despesa recorrente/i })).toBeInTheDocument();
  });

  it('does not expose a manual generation action in the page', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [sampleRecord] });

    render(<DespesasRecorrentes />);

    expect(await screen.findByText('Netflix')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /gerar/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/despesas de hoje/i)).not.toBeInTheDocument();
  });

  it('lists records with formatted values and shows "Sem fim" when mes_fim is null', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [sampleRecord] });

    render(<DespesasRecorrentes />);

    expect(await screen.findByText('Netflix')).toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /Descrição/i })).not.toBeInTheDocument();
    expect(screen.getByText(/R\$\s*39,90/)).toBeInTheDocument();
    expect(screen.getByText('Dia 5')).toBeInTheDocument();
    expect(screen.getByText('04/2026')).toBeInTheDocument();
    expect(screen.getByText('Sem fim')).toBeInTheDocument();
  });

  it('opens the create modal pre-filled with defaults and submits a new record', async () => {
    mockGetRecurringExpenses
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ items: [sampleRecord] });
    mockCreateRecurringExpense.mockResolvedValue({ recurring_expense: sampleRecord });

    render(<DespesasRecorrentes />);

    expect(await screen.findByText('Nenhuma despesa recorrente cadastrada')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Nova despesa recorrente/i }));

    expect(await screen.findByRole('heading', { name: /Nova despesa recorrente/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/Descrição/i)).not.toBeInTheDocument();
    const modalOverlay = screen.getByTestId('recurring-expense-modal-overlay');
    expect(modalOverlay.parentElement).toBe(document.body);
    const modalBody = screen.getByTestId('recurring-expense-modal-body');
    expect(screen.getByTestId('recurring-expense-top-fields')).toContainElement(screen.getByLabelText('Ativo'));
    expect(screen.getByRole('button', { name: /Selecionar mês de início/i })).toHaveClass('w-full');
    expect(screen.getByRole('button', { name: /Selecionar mês de fim/i })).toHaveClass('w-full');

    await userEvent.type(screen.getByLabelText('Nome da despesa'), 'Netflix');
    const valor = screen.getByLabelText('Valor') as HTMLInputElement;
    await userEvent.clear(valor);
    await userEvent.type(valor, '3990');
    expect(valor.value).toBe('39,90');
    const dia = screen.getByLabelText('Dia do mês');
    await userEvent.clear(dia);
    await userEvent.type(dia, '5');

    await userEvent.click(screen.getByRole('button', { name: /Selecionar mês de início/i }));
    const startMonthPopover = screen.getByTestId('compact-month-picker-popover');
    expect(startMonthPopover.parentElement).toBe(document.body);
    expect(modalBody).not.toContainElement(startMonthPopover);
    expect(startMonthPopover).toHaveClass('fixed');
    await userEvent.click(screen.getByRole('button', { name: /^Abr$/i }));

    await userEvent.click(screen.getByRole('button', { name: /Criar/i }));

    await waitFor(() => {
      expect(mockCreateRecurringExpense).toHaveBeenCalled();
    });
    const callPayload = mockCreateRecurringExpense.mock.calls[0][0];
    expect(callPayload.nome).toBe('Netflix');
    expect(callPayload).not.toHaveProperty('descricao');
    expect(callPayload.valor).toBe(39.9);
    expect(callPayload.dia_mes).toBe(5);
    expect(callPayload.mes_inicio).toBe('2026-04-01');
  });

  it('opens the edit modal pre-filled with the selected record', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [sampleRecord] });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByTitle('Editar'));

    expect(await screen.findByText('Editar despesa recorrente')).toBeInTheDocument();
    expect((screen.getByLabelText('Nome da despesa') as HTMLInputElement).value).toBe('Netflix');
    expect(screen.queryByLabelText(/Descrição/i)).not.toBeInTheDocument();
  });

  it('blocks save with a validation message when the name is empty', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [] });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByRole('button', { name: /Nova despesa recorrente/i }));
    await userEvent.click(await screen.findByRole('button', { name: /Criar/i }));

    expect(await screen.findByText(/O nome da despesa é obrigatório/i)).toBeInTheDocument();
    expect(mockCreateRecurringExpense).not.toHaveBeenCalled();
  });

  it('deletes a record after confirmation', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [sampleRecord] });
    mockDeleteRecurringExpense.mockResolvedValue({ id: 'rec-1' });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByTitle('Excluir'));

    await waitFor(() => {
      expect(mockDeleteRecurringExpense).toHaveBeenCalledWith('rec-1');
    });
    await waitFor(() => {
      expect(screen.queryByText('Netflix')).not.toBeInTheDocument();
    });
  });

  it('does not delete when the confirmation dialog is cancelled', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false));
    mockGetRecurringExpenses.mockResolvedValue({ items: [sampleRecord] });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByTitle('Excluir'));

    expect(mockDeleteRecurringExpense).not.toHaveBeenCalled();
  });

  it('renders the admin error banner when the list cannot be loaded', async () => {
    mockGetRecurringExpenses.mockRejectedValue(new Error('Backend out. Código de suporte: req_recurring_err'));

    render(<DespesasRecorrentes />);

    expect(await screen.findByText(/Backend out/)).toBeInTheDocument();
    expect(screen.getByText(/Código de suporte: req_recurring_err/)).toBeInTheDocument();
  });

  it('offers re-login when the bearer token is malformed', async () => {
    mockGetRecurringExpenses.mockRejectedValue(
      new ApiError(
        'Sua sessão de acesso é inválida. Faça login novamente. Código de suporte: req_recurring_auth Detalhe: bearer_malformed',
        {
          code: 'AUTH_SESSION_TOKEN_MALFORMED',
          detail: 'bearer_malformed',
          status: 401,
          requestId: 'req_recurring_auth',
        },
      ),
    );

    render(<DespesasRecorrentes />);

    expect(await screen.findByText(/detalhe: bearer_malformed/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Fazer login novamente/i }));
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });

  it('keeps the page empty when the admin session is unavailable', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      loading: false,
      localBypass: false,
      signOut: mockSignOut,
    });

    render(<DespesasRecorrentes />);

    expect(await screen.findByText('Nenhuma despesa recorrente cadastrada')).toBeInTheDocument();
    expect(mockGetRecurringExpenses).not.toHaveBeenCalled();
  });

  it('rejects save when dia_mes is out of range', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [] });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByRole('button', { name: /Nova despesa recorrente/i }));

    await userEvent.type(screen.getByLabelText('Nome da despesa'), 'Test');
    await userEvent.type(screen.getByLabelText('Valor'), '1000');
    await userEvent.click(screen.getByRole('button', { name: /Selecionar mês de início/i }));
    await userEvent.click(screen.getByRole('button', { name: /^Abr$/i }));

    const dia = screen.getByLabelText('Dia do mês');
    await userEvent.clear(dia);
    await userEvent.type(dia, '40');

    await userEvent.click(screen.getByRole('button', { name: /Criar/i }));
    expect(await screen.findByText(/O dia do mês deve estar entre 1 e 31/i)).toBeInTheDocument();
    expect(mockCreateRecurringExpense).not.toHaveBeenCalled();
  });

  it('rejects save when valor is invalid', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [] });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByRole('button', { name: /Nova despesa recorrente/i }));

    await userEvent.type(screen.getByLabelText('Nome da despesa'), 'Test');
    await userEvent.click(screen.getByRole('button', { name: /Selecionar mês de início/i }));
    await userEvent.click(screen.getByRole('button', { name: /^Abr$/i }));

    const valor = screen.getByLabelText('Valor') as HTMLInputElement;
    fireEvent.change(valor, { target: { value: ',' } });

    await userEvent.click(screen.getByRole('button', { name: /Criar/i }));
    expect(await screen.findByText(/Informe um valor válido/i)).toBeInTheDocument();
    expect(mockCreateRecurringExpense).not.toHaveBeenCalled();
  });

  it('rejects save when mes_inicio is missing', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [] });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByRole('button', { name: /Nova despesa recorrente/i }));

    await userEvent.type(screen.getByLabelText('Nome da despesa'), 'Test');
    await userEvent.click(screen.getByRole('button', { name: /Criar/i }));
    expect(await screen.findByText(/O mês de início é obrigatório/i)).toBeInTheDocument();
  });

  it('updates an existing record with mes_fim and saves it', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [sampleRecord] });
    mockUpdateRecurringExpense.mockResolvedValue({ recurring_expense: { ...sampleRecord, nome: 'Atualizado' } });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByTitle('Editar'));

    const nome = screen.getByLabelText('Nome da despesa');
    await userEvent.clear(nome);
    await userEvent.type(nome, 'Atualizado');

    await userEvent.click(screen.getByRole('button', { name: /Selecionar mês de fim/i }));
    const endMonthPopover = screen.getByTestId('compact-month-picker-popover');
    expect(endMonthPopover.parentElement).toBe(document.body);
    expect(screen.getByTestId('recurring-expense-modal-body')).not.toContainElement(endMonthPopover);
    expect(endMonthPopover).toHaveClass('fixed');
    await userEvent.click(screen.getByRole('button', { name: /^Dez$/i }));

    await userEvent.click(screen.getByRole('button', { name: /Salvar/i }));

    await waitFor(() => {
      expect(mockUpdateRecurringExpense).toHaveBeenCalled();
    });
    const [calledId, calledPayload] = mockUpdateRecurringExpense.mock.calls[0];
    expect(calledId).toBe('rec-1');
    expect(calledPayload.nome).toBe('Atualizado');
    expect(calledPayload).not.toHaveProperty('descricao');
    expect(calledPayload.mes_fim).toBe('2026-12-01');
  });

  it('switches categoria when natureza changes and updates other dropdowns', async () => {
    mockGetRecurringExpenses
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ items: [sampleRecord] });
    mockCreateRecurringExpense.mockResolvedValue({ recurring_expense: sampleRecord });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByRole('button', { name: /Nova despesa recorrente/i }));

    const natureza = screen.getByLabelText('Natureza') as HTMLSelectElement;
    const initialCategoria = (screen.getByLabelText('Categoria') as HTMLSelectElement).value;
    await userEvent.selectOptions(natureza, 'Lazer');

    const categoria = screen.getByLabelText('Categoria') as HTMLSelectElement;
    await waitFor(() => {
      expect(categoria.value).not.toBe(initialCategoria);
    });

    const previousCategoria = categoria.value;
    if (categoria.options.length > 1) {
      await userEvent.selectOptions(categoria, categoria.options[1].value);
      expect(categoria.value).not.toBe(previousCategoria);
    }

    const metodo = screen.getByLabelText('Método de pagamento') as HTMLSelectElement;
    await userEvent.selectOptions(metodo, metodo.options[metodo.options.length - 1].value);
    expect(metodo.value).toBe(metodo.options[metodo.options.length - 1].value);

    const conta = screen.getByLabelText('Conta') as HTMLSelectElement;
    await userEvent.selectOptions(conta, conta.options[conta.options.length - 1].value);
    expect(conta.value).toBe(conta.options[conta.options.length - 1].value);
  });

  it('shows the error banner when delete fails on the backend', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [sampleRecord] });
    mockDeleteRecurringExpense.mockRejectedValue(new Error('Backend rejected delete'));

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByTitle('Excluir'));

    expect(await screen.findByText(/Backend rejected delete/i)).toBeInTheDocument();
  });

  it('blocks delete with an auth-loading message while authentication is pending', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: true,
      loading: true,
      localBypass: false,
      signOut: mockSignOut,
    });
    mockGetRecurringExpenses.mockResolvedValue({ items: [sampleRecord] });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByTitle('Excluir'));

    expect(await screen.findByText(/Sua autenticação ainda está sendo carregada/i)).toBeInTheDocument();
    expect(mockDeleteRecurringExpense).not.toHaveBeenCalled();
  });

  it('loads data when running under local bypass and submits valid input', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      loading: false,
      localBypass: true,
      signOut: mockSignOut,
    });
    mockGetRecurringExpenses.mockResolvedValue({ items: [sampleRecord] });

    render(<DespesasRecorrentes />);

    expect(await screen.findByText('Netflix')).toBeInTheDocument();
    expect(mockGetRecurringExpenses).toHaveBeenCalled();
  });

  it('toggles the ativo checkbox when editing', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [sampleRecord] });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByTitle('Editar'));

    const ativo = screen.getByLabelText('Ativo') as HTMLInputElement;
    expect(ativo.checked).toBe(true);
    await userEvent.click(ativo);
    expect(ativo.checked).toBe(false);
  });

  it('closes the modal via the Cancelar button without saving', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [] });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByRole('button', { name: /Nova despesa recorrente/i }));
    expect(await screen.findByRole('heading', { name: /Nova despesa recorrente/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Cancelar/i }));
    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: /Nova despesa recorrente/i })).not.toBeInTheDocument();
    });
  });

  it('shows a form error when save fails on the backend', async () => {
    mockGetRecurringExpenses.mockResolvedValue({ items: [] });
    mockCreateRecurringExpense.mockRejectedValue(new Error('Conflict on backend'));

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByRole('button', { name: /Nova despesa recorrente/i }));
    await userEvent.type(screen.getByLabelText('Nome da despesa'), 'Netflix');
    await userEvent.type(screen.getByLabelText('Valor'), '3990');
    await userEvent.click(screen.getByRole('button', { name: /Selecionar mês de início/i }));
    await userEvent.click(screen.getByRole('button', { name: /^Abr$/i }));

    await userEvent.click(screen.getByRole('button', { name: /Criar/i }));

    expect(await screen.findByText(/Conflict on backend/i)).toBeInTheDocument();
  });

  it('changes mes_fim back to null when the field is cleared', async () => {
    const recordWithEnd = { ...sampleRecord, mes_fim: '2026-12-01' };
    mockGetRecurringExpenses.mockResolvedValue({ items: [recordWithEnd] });
    mockUpdateRecurringExpense.mockResolvedValue({ recurring_expense: { ...recordWithEnd, mes_fim: null } });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByTitle('Editar'));

    expect(screen.getByRole('button', { name: /Dez\/2026/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Limpar mês de fim/i }));

    await userEvent.click(screen.getByRole('button', { name: /Salvar/i }));

    await waitFor(() => {
      expect(mockUpdateRecurringExpense).toHaveBeenCalled();
    });
    const [, calledPayload] = mockUpdateRecurringExpense.mock.calls[0];
    expect(calledPayload.mes_fim).toBeNull();
  });

  it('blocks save while authentication is loading', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: true,
      loading: true,
      localBypass: false,
      signOut: mockSignOut,
    });
    mockGetRecurringExpenses.mockResolvedValue({ items: [] });

    render(<DespesasRecorrentes />);

    await userEvent.click(await screen.findByRole('button', { name: /Nova despesa recorrente/i }));
    await userEvent.type(screen.getByLabelText('Nome da despesa'), 'Test');

    await userEvent.click(screen.getByRole('button', { name: /Criar/i }));

    expect(await screen.findByText(/Sua autenticação ainda está sendo carregada/i)).toBeInTheDocument();
    expect(mockCreateRecurringExpense).not.toHaveBeenCalled();
  });

  it('paginates large datasets', async () => {
    const records = Array.from({ length: 12 }, (_, idx) => ({
      ...sampleRecord,
      id: `rec-${idx + 1}`,
      nome: `Item ${idx + 1}`,
    }));
    mockGetRecurringExpenses.mockResolvedValue({ items: records });

    render(<DespesasRecorrentes />);

    expect(await screen.findByText('Item 1')).toBeInTheDocument();
    expect(screen.queryByText('Item 11')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Próxima/ }));
    expect(await screen.findByText('Item 11')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Anterior/ }));
    expect(await screen.findByText('Item 1')).toBeInTheDocument();
  });

  it('filters records using the search field', async () => {
    const records = [
      { ...sampleRecord, id: 'rec-a', nome: 'Netflix Stream' },
      { ...sampleRecord, id: 'rec-b', nome: 'Spotify Music' },
    ];
    mockGetRecurringExpenses.mockResolvedValue({ items: records });

    render(<DespesasRecorrentes />);

    expect(await screen.findByText('Netflix Stream')).toBeInTheDocument();
    expect(screen.getByText('Spotify Music')).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText('Buscar...'), 'Spotify');

    await waitFor(() => {
      expect(screen.queryByText('Netflix Stream')).not.toBeInTheDocument();
    });
    expect(screen.getByText('Spotify Music')).toBeInTheDocument();
  });

  it('shows the session-expired error when the auth state drops after data is loaded', async () => {
    const authState = {
      authenticated: true,
      loading: false,
      localBypass: false,
      signOut: mockSignOut,
    };
    mockUseAuth.mockImplementation(() => authState);
    mockGetRecurringExpenses.mockResolvedValue({ items: [sampleRecord] });

    const { rerender } = render(<DespesasRecorrentes />);

    expect(await screen.findByText('Netflix')).toBeInTheDocument();

    await act(async () => {
      authState.authenticated = false;
      rerender(<DespesasRecorrentes />);
    });

    expect(await screen.findByText(/Sua sessão expirou/i)).toBeInTheDocument();
  });

  it('blocks save and delete when the session is unavailable but the page already has rows', async () => {
    const authState = {
      authenticated: true,
      loading: false,
      localBypass: false,
      signOut: mockSignOut,
    };
    mockUseAuth.mockImplementation(() => authState);
    mockGetRecurringExpenses.mockResolvedValue({ items: [sampleRecord] });

    const { rerender } = render(<DespesasRecorrentes />);
    expect(await screen.findByText('Netflix')).toBeInTheDocument();

    await act(async () => {
      authState.authenticated = false;
      rerender(<DespesasRecorrentes />);
    });

    await userEvent.click(screen.getByTitle('Editar'));
    await userEvent.click(screen.getByRole('button', { name: /Salvar/i }));
    const matches = await screen.findAllByText(/Sua sessão expirou/i);
    expect(matches.length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole('button', { name: /Cancelar/i }));
    await userEvent.click(screen.getByTitle('Excluir'));

    expect(mockDeleteRecurringExpense).not.toHaveBeenCalled();
  });
});

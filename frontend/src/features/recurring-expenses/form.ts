import {
  normalizeNatureLabel,
  parseTransactionValueInput,
  type RecurringExpenseDraft,
  type RecurringExpenseRecord,
} from '@/lib/transactions';

type ValidateRecurringExpenseDraftParams = {
  draft: RecurringExpenseDraft;
  valueInput: string;
  loading: boolean;
  authenticated: boolean;
  localBypass: boolean;
};

type ValidateRecurringExpenseDraftResult =
  | { ok: true; parsedValue: number }
  | { ok: false; error: string };

export function formatMonthLabel(raw: string) {
  if (!raw) return '';
  const [year, month] = raw.split('-');
  if (!year || !month) return raw;
  return `${month}/${year}`;
}

export function parseMonthValue(raw: string | null | undefined) {
  if (!raw) return null;
  const [year, month] = raw.split('-').map(Number);
  if (!year || !month) return null;
  return new Date(year, month - 1, 1);
}

export function formatMonthValue(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  return `${year}-${month}-01`;
}

export function normalizeRecurringExpenseRecord(item: RecurringExpenseRecord): RecurringExpenseRecord {
  return {
    ...item,
    natureza: normalizeNatureLabel(item.natureza),
    metodo_pagamento: item.metodo_pagamento || 'Outros',
    conta: item.conta || 'Nao Informada',
  };
}

export function buildRecurringExpenseDraft(item: RecurringExpenseRecord): RecurringExpenseDraft {
  return {
    nome: item.nome,
    valor: item.valor,
    mes_inicio: item.mes_inicio,
    mes_fim: item.mes_fim,
    dia_mes: item.dia_mes,
    natureza: item.natureza,
    categoria: item.categoria,
    metodo_pagamento: item.metodo_pagamento,
    conta: item.conta,
    ativo: item.ativo,
  };
}

export function validateRecurringExpenseDraft({
  draft,
  valueInput,
  loading,
  authenticated,
  localBypass,
}: ValidateRecurringExpenseDraftParams): ValidateRecurringExpenseDraftResult {
  if (loading) {
    return { ok: false, error: 'Sua autenticação ainda está sendo carregada. Tente novamente em alguns segundos.' };
  }
  if (!authenticated && !localBypass) {
    return { ok: false, error: 'Sua sessão expirou. Faça login novamente.' };
  }
  if (!draft.nome.trim()) {
    return { ok: false, error: 'O nome da despesa é obrigatório.' };
  }
  if (!draft.mes_inicio) {
    return { ok: false, error: 'O mês de início é obrigatório.' };
  }

  const parsedValue = parseTransactionValueInput(valueInput);
  if (parsedValue === null) {
    return { ok: false, error: 'Informe um valor válido.' };
  }
  if (parsedValue < 0) {
    return { ok: false, error: 'O valor deve ser maior ou igual a zero.' };
  }
  if (draft.dia_mes < 1 || draft.dia_mes > 31) {
    return { ok: false, error: 'O dia do mês deve estar entre 1 e 31.' };
  }

  return { ok: true, parsedValue };
}

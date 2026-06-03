export type TransactionNature = 'Essencial' | 'Lazer' | 'Receita' | 'Outros';

export type TransactionRecord = {
  id: string;
  data: string;
  natureza: TransactionNature;
  categoria: string;
  descricao: string;
  valor: number;
  conta: string;
  metodo_pagamento: string;
};

export type TransactionDraft = Omit<TransactionRecord, 'id'>;

export const transactionCategories: Record<TransactionNature, string[]> = {
  Essencial: ['Moradia', 'Mercado', 'Transporte', 'Saúde', 'Educação', 'Contas Fixas', 'Cuidados Pessoais'],
  Lazer: ['Bares e Restaurantes', 'Delivery e Fast Food', 'Bebidas Alcoólicas', 'Viagens', 'Diversão', 'Vestuário'],
  Receita: ['Salário', 'Investimentos', 'Cashback', 'Entradas Diversas'],
  Outros: ['Outros'],
};

export const transactionNatureLabels: TransactionNature[] = ['Essencial', 'Lazer', 'Receita', 'Outros'];

export const paymentMethodOptions = ['Pix', 'Cartao de Credito', 'Cartao de Debito', 'Dinheiro', 'Transferencia', 'Outros'];

export const accountOptions = ['Nubank', 'Bradesco', 'Itau', 'Santander', 'Inter', 'Caixa', 'Dinheiro', 'Nao Informada'];

const categoryDisplayLabels: Record<string, string> = {
  'Contas Fixas': 'Contas fixas',
  'Cuidados Pessoais': 'Cuidados pessoais',
  'Bares e Restaurantes': 'Bares e restaurantes',
  'Delivery e Fast Food': 'Delivery e fast food',
  'Bebidas Alcoólicas': 'Bebidas alcoólicas',
  'Entradas Diversas': 'Entradas diversas',
};

const paymentMethodDisplayLabels: Record<string, string> = {
  'Cartao de Credito': 'Cartão de crédito',
  'Cartao de Debito': 'Cartão de débito',
  Transferencia: 'Transferência',
};

const accountDisplayLabels: Record<string, string> = {
  Itau: 'Itaú',
  'Nao Informada': 'Não informada',
};

export function formatCategoryLabel(value?: string | null) {
  if (!value) {
    return '';
  }

  return categoryDisplayLabels[value] || value;
}

export function formatPaymentMethodLabel(value?: string | null) {
  if (!value) {
    return '';
  }

  return paymentMethodDisplayLabels[value] || value;
}

export function formatAccountLabel(value?: string | null) {
  if (!value) {
    return '';
  }

  return accountDisplayLabels[value] || value;
}

export function createEmptyTransactionDraft(today: string): TransactionDraft {
  return {
    data: today,
    natureza: 'Essencial',
    categoria: transactionCategories.Essencial[0],
    descricao: '',
    valor: 0,
    conta: 'Nao Informada',
    metodo_pagamento: 'Pix',
  };
}

export function normalizeNatureLabel(value?: string | null): TransactionNature {
  if (value === 'Essencial' || value === 'Lazer' || value === 'Receita' || value === 'Outros') {
    return value;
  }

  return 'Outros';
}

export function formatTransactionValue(value: number) {
  if (!value) {
    return '';
  }

  return value.toFixed(2).replace('.', ',');
}

export function normalizeTransactionValueInput(rawValue: string) {
  const digitsOnly = rawValue.replace(/\D/g, '');
  if (!digitsOnly) {
    return '';
  }

  const cents = Number.parseInt(digitsOnly, 10);
  const integerPart = Math.floor(cents / 100);
  const decimalPart = String(cents % 100).padStart(2, '0');
  return `${integerPart},${decimalPart}`;
}

export function parseTransactionValueInput(rawValue: string) {
  const digitsOnly = rawValue.replace(/\D/g, '');
  if (!digitsOnly) {
    return null;
  }

  const parsed = Number.parseInt(digitsOnly, 10) / 100;
  if (!Number.isFinite(parsed)) {
    return null;
  }

  return parsed;
}

export type RecurringExpenseRecord = {
  id: string;
  nome: string;
  valor: number;
  mes_inicio: string;
  mes_fim: string | null;
  dia_mes: number;
  natureza: TransactionNature;
  categoria: string;
  metodo_pagamento: string;
  conta: string;
  ativo: boolean;
};

export type RecurringExpenseDraft = Omit<RecurringExpenseRecord, 'id'>;

export function createEmptyRecurringExpenseDraft(): RecurringExpenseDraft {
  return {
    nome: '',
    valor: 0,
    mes_inicio: '',
    mes_fim: null,
    dia_mes: 1,
    natureza: 'Essencial',
    categoria: transactionCategories.Essencial[0],
    metodo_pagamento: 'Pix',
    conta: 'Nao Informada',
    ativo: true,
  };
}

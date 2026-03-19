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

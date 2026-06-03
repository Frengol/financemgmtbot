import { describe, expect, it } from 'vitest';
import {
  createEmptyTransactionDraft,
  formatAccountLabel,
  formatCategoryLabel,
  formatPaymentMethodLabel,
  formatTransactionValue,
  normalizeNatureLabel,
  normalizeTransactionValueInput,
  parseTransactionValueInput,
} from './transactions';

describe('transactions helpers', () => {
  it('creates a deterministic empty draft', () => {
    expect(createEmptyTransactionDraft('2026-04-03')).toEqual({
      data: '2026-04-03',
      natureza: 'Essencial',
      categoria: 'Moradia',
      descricao: '',
      valor: 0,
      conta: 'Nao Informada',
      metodo_pagamento: 'Pix',
    });
  });

  it('normalizes unknown nature labels to Outros', () => {
    expect(normalizeNatureLabel('Receita')).toBe('Receita');
    expect(normalizeNatureLabel('Algo Invalido')).toBe('Outros');
    expect(normalizeNatureLabel()).toBe('Outros');
  });

  it('formats legacy domain values as polished Portuguese labels without changing values', () => {
    expect(formatPaymentMethodLabel('Cartao de Credito')).toBe('Cartão de crédito');
    expect(formatPaymentMethodLabel('Cartao de Debito')).toBe('Cartão de débito');
    expect(formatPaymentMethodLabel('Transferencia')).toBe('Transferência');
    expect(formatAccountLabel('Itau')).toBe('Itaú');
    expect(formatAccountLabel('Nao Informada')).toBe('Não informada');
    expect(formatCategoryLabel('Contas Fixas')).toBe('Contas fixas');
    expect(formatCategoryLabel('Delivery e Fast Food')).toBe('Delivery e fast food');
    expect(formatCategoryLabel('Mercado')).toBe('Mercado');
  });

  it('formats numeric values for the input field', () => {
    expect(formatTransactionValue(0)).toBe('');
    expect(formatTransactionValue(12.5)).toBe('12,50');
  });

  it('normalizes currency input using bank-style cents-first typing', () => {
    expect(normalizeTransactionValueInput('1')).toBe('0,01');
    expect(normalizeTransactionValueInput('13')).toBe('0,13');
    expect(normalizeTransactionValueInput('137')).toBe('1,37');
    expect(normalizeTransactionValueInput('13700')).toBe('137,00');
    expect(normalizeTransactionValueInput('R$ 1.234,56')).toBe('1234,56');
    expect(normalizeTransactionValueInput('12abc34')).toBe('12,34');
    expect(normalizeTransactionValueInput('99,,9')).toBe('9,99');
  });

  it('parses normalized decimal input and rejects invalid values', () => {
    expect(parseTransactionValueInput('45,90')).toBe(45.9);
    expect(parseTransactionValueInput('4590')).toBe(45.9);
    expect(parseTransactionValueInput('1')).toBe(0.01);
    expect(parseTransactionValueInput('137')).toBe(1.37);
    expect(parseTransactionValueInput('13700')).toBe(137);
    expect(parseTransactionValueInput('')).toBeNull();
    expect(parseTransactionValueInput('...')).toBeNull();
  });
});

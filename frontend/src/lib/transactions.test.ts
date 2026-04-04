import { describe, expect, it } from 'vitest';
import {
  createEmptyTransactionDraft,
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

  it('formats numeric values for the input field', () => {
    expect(formatTransactionValue(0)).toBe('');
    expect(formatTransactionValue(12.5)).toBe('12,50');
  });

  it('normalizes free-form currency input to a safe decimal string', () => {
    expect(normalizeTransactionValueInput('R$ 123,456')).toBe('123,45');
    expect(normalizeTransactionValueInput('12abc34')).toBe('1234');
    expect(normalizeTransactionValueInput('99,,9')).toBe('99,9');
  });

  it('parses normalized decimal input and rejects invalid values', () => {
    expect(parseTransactionValueInput('45,90')).toBe(45.9);
    expect(parseTransactionValueInput('')).toBeNull();
    expect(parseTransactionValueInput('...')).toBeNull();
  });
});

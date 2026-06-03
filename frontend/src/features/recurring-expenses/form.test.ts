import { describe, expect, it } from 'vitest';

import {
  buildRecurringExpenseDraft,
  formatMonthLabel,
  formatMonthValue,
  normalizeRecurringExpenseRecord,
  parseMonthValue,
  validateRecurringExpenseDraft,
} from './form';
import type { RecurringExpenseRecord } from '@/lib/transactions';

const sampleRecord: RecurringExpenseRecord = {
  id: 'rec-1',
  nome: 'Netflix',
  valor: 39.9,
  mes_inicio: '2026-04-01',
  mes_fim: null,
  dia_mes: 5,
  natureza: 'Lazer',
  categoria: 'Diversão',
  metodo_pagamento: '',
  conta: '',
  ativo: true,
};

describe('recurring expense form helpers', () => {
  it('formats and parses month values used by the compact picker', () => {
    expect(formatMonthLabel('2026-04-01')).toBe('04/2026');
    expect(formatMonthLabel('invalid')).toBe('invalid');
    expect(parseMonthValue('2026-04-01')).toEqual(new Date(2026, 3, 1));
    expect(parseMonthValue(null)).toBeNull();
    expect(formatMonthValue(new Date(2026, 3, 5))).toBe('2026-04-01');
  });

  it('normalizes loaded records and builds editable drafts', () => {
    expect(normalizeRecurringExpenseRecord(sampleRecord)).toMatchObject({
      natureza: 'Lazer',
      metodo_pagamento: 'Outros',
      conta: 'Nao Informada',
    });

    expect(buildRecurringExpenseDraft(sampleRecord)).toEqual({
      nome: 'Netflix',
      valor: 39.9,
      mes_inicio: '2026-04-01',
      mes_fim: null,
      dia_mes: 5,
      natureza: 'Lazer',
      categoria: 'Diversão',
      metodo_pagamento: '',
      conta: '',
      ativo: true,
    });
  });

  it('validates client-side form errors before API calls', () => {
    const baseDraft = buildRecurringExpenseDraft(sampleRecord);

    expect(validateRecurringExpenseDraft({
      draft: { ...baseDraft, nome: '' },
      valueInput: '39,90',
      loading: false,
      authenticated: true,
      localBypass: false,
    })).toEqual({ ok: false, error: 'O nome da despesa é obrigatório.' });

    expect(validateRecurringExpenseDraft({
      draft: baseDraft,
      valueInput: 'abc',
      loading: false,
      authenticated: true,
      localBypass: false,
    })).toEqual({ ok: false, error: 'Informe um valor válido.' });

    expect(validateRecurringExpenseDraft({
      draft: baseDraft,
      valueInput: '39,90',
      loading: false,
      authenticated: true,
      localBypass: false,
    })).toEqual({ ok: true, parsedValue: 39.9 });
  });
});

import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TransactionComposerProvider, useTransactionComposer } from './useTransactionComposer';

function wrapper({ children }: { children: React.ReactNode }) {
  return <TransactionComposerProvider>{children}</TransactionComposerProvider>;
}

describe('useTransactionComposer', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-03T15:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('opens a fresh draft for new transactions using the current day', () => {
    const { result } = renderHook(() => useTransactionComposer(), { wrapper });

    act(() => {
      result.current.openCreate();
    });

    expect(result.current.isOpen).toBe(true);
    expect(result.current.editingId).toBeNull();
    expect(result.current.draft).toEqual({
      data: '2026-04-03',
      natureza: 'Essencial',
      categoria: 'Moradia',
      descricao: '',
      valor: 0,
      conta: 'Nao Informada',
      metodo_pagamento: 'Pix',
    });
  });

  it('opens an existing transaction for editing and closes the modal cleanly', () => {
    const { result } = renderHook(() => useTransactionComposer(), { wrapper });

    act(() => {
      result.current.openEdit({
        id: 'tx-77',
        data: '2026-04-02',
        natureza: 'Lazer',
        categoria: 'Diversão',
        descricao: 'Cinema',
        valor: 55,
        conta: '',
        metodo_pagamento: '',
      });
    });

    expect(result.current.isOpen).toBe(true);
    expect(result.current.editingId).toBe('tx-77');
    expect(result.current.draft).toEqual({
      data: '2026-04-02',
      natureza: 'Lazer',
      categoria: 'Diversão',
      descricao: 'Cinema',
      valor: 55,
      conta: 'Nao Informada',
      metodo_pagamento: 'Outros',
    });

    act(() => {
      result.current.close();
    });

    expect(result.current.isOpen).toBe(false);
    expect(result.current.editingId).toBeNull();
  });

  it('allows manual draft updates and rejects usage outside the provider', () => {
    const { result } = renderHook(() => useTransactionComposer(), { wrapper });

    act(() => {
      result.current.openCreate();
      result.current.setDraft({
        ...result.current.draft,
        descricao: 'Compra ajustada',
        valor: 99,
      });
    });

    expect(result.current.draft.descricao).toBe('Compra ajustada');
    expect(result.current.draft.valor).toBe(99);

    expect(() => renderHook(() => useTransactionComposer())).toThrow(
      'useTransactionComposer must be used within TransactionComposerProvider.',
    );
  });
});

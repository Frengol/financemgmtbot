import type { ReactNode } from 'react';
import { createContext, useContext, useMemo, useState } from 'react';
import { createEmptyTransactionDraft, type TransactionDraft, type TransactionRecord } from '@/lib/transactions';

type TransactionComposerContextValue = {
  isOpen: boolean;
  draft: TransactionDraft;
  editingId: string | null;
  openCreate: () => void;
  openEdit: (transaction: TransactionRecord) => void;
  close: () => void;
  setDraft: (nextDraft: TransactionDraft) => void;
};

const TransactionComposerContext = createContext<TransactionComposerContextValue | null>(null);

function getTodayDate() {
  return new Date().toISOString().slice(0, 10);
}

export function TransactionComposerProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<TransactionDraft>(() => createEmptyTransactionDraft(getTodayDate()));

  const value = useMemo<TransactionComposerContextValue>(() => ({
    isOpen,
    draft,
    editingId,
    openCreate: () => {
      setEditingId(null);
      setDraft(createEmptyTransactionDraft(getTodayDate()));
      setIsOpen(true);
    },
    openEdit: (transaction) => {
      setEditingId(transaction.id);
      setDraft({
        data: transaction.data,
        natureza: transaction.natureza,
        categoria: transaction.categoria,
        descricao: transaction.descricao,
        valor: transaction.valor,
        conta: transaction.conta || 'Nao Informada',
        metodo_pagamento: transaction.metodo_pagamento || 'Outros',
      });
      setIsOpen(true);
    },
    close: () => {
      setIsOpen(false);
      setEditingId(null);
    },
    setDraft,
  }), [draft, editingId, isOpen]);

  return <TransactionComposerContext.Provider value={value}>{children}</TransactionComposerContext.Provider>;
}

export function useTransactionComposer() {
  const context = useContext(TransactionComposerContext);
  if (!context) {
    throw new Error('useTransactionComposer must be used within TransactionComposerProvider.');
  }

  return context;
}

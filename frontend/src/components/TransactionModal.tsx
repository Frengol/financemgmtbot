import { useEffect, useMemo, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { createTransaction, updateTransaction } from '@/lib/adminApi';
import {
  accountOptions,
  formatTransactionValue,
  normalizeTransactionValueInput,
  parseTransactionValueInput,
  paymentMethodOptions,
  transactionCategories,
  transactionNatureLabels,
} from '@/lib/transactions';
import { useAuth } from '@/hooks/useAuth';
import { useTransactionComposer } from '@/hooks/useTransactionComposer';

function emitTransactionsChanged() {
  window.dispatchEvent(new CustomEvent('transactions:changed'));
}

export default function TransactionModal() {
  const { authenticated, csrfToken, loading: authLoading, localBypass } = useAuth();
  const { close, draft, editingId, isOpen, setDraft } = useTransactionComposer();
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [valueInput, setValueInput] = useState('');

  const availableCategories = useMemo(() => transactionCategories[draft.natureza], [draft.natureza]);

  useEffect(() => {
    if (!availableCategories.includes(draft.categoria)) {
      setDraft({ ...draft, categoria: availableCategories[0] });
    }
  }, [availableCategories, draft, setDraft]);

  useEffect(() => {
    setValueInput(formatTransactionValue(draft.valor));
  }, [draft.valor, editingId, isOpen]);

  if (!isOpen) {
    return null;
  }

  const title = editingId ? 'Editar transacao' : 'Nova transacao';

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    if (authLoading) {
      setError('Aguarde a autenticacao concluir antes de salvar.');
      return;
    }

    if ((!authenticated || !csrfToken) && !localBypass) {
      setError('Nao foi possivel validar sua sessao. Entre novamente.');
      return;
    }

    const parsedValue = parseTransactionValueInput(valueInput);
    if (parsedValue === null) {
      setError('Informe um valor numerico valido usando virgula para os centavos.');
      return;
    }

    const payload = {
      ...draft,
      valor: parsedValue,
    };

    try {
      setSaving(true);
      setError('');

      if (editingId) {
        await updateTransaction(editingId, payload, csrfToken);
      } else {
        await createTransaction(payload, csrfToken);
      }

      emitTransactionsChanged();
      close();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Nao foi possivel salvar a transacao.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
            <p className="text-sm text-slate-500">Crie ou ajuste um lancamento manualmente no painel.</p>
          </div>
          <button
            type="button"
            onClick={close}
            className="rounded-full p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5 px-6 py-5">
          {error && (
            <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          )}

          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">Data</span>
              <input
                type="date"
                value={draft.data}
                onChange={(event) => setDraft({ ...draft, data: event.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none transition focus:border-blue-500 focus:bg-white"
                required
              />
            </label>

            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">Valor</span>
              <input
                type="text"
                inputMode="decimal"
                value={valueInput}
                onChange={(event) => {
                  setValueInput(normalizeTransactionValueInput(event.target.value));
                }}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none transition focus:border-blue-500 focus:bg-white"
                placeholder="12,50"
                required
              />
            </label>

            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">Natureza</span>
              <select
                value={draft.natureza}
                onChange={(event) => {
                  const nextNature = event.target.value as typeof draft.natureza;
                  setDraft({ ...draft, natureza: nextNature, categoria: transactionCategories[nextNature][0] });
                }}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none transition focus:border-blue-500 focus:bg-white"
              >
                {transactionNatureLabels.map((nature) => (
                  <option key={nature} value={nature}>{nature}</option>
                ))}
              </select>
            </label>

            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">Categoria</span>
              <select
                value={draft.categoria}
                onChange={(event) => setDraft({ ...draft, categoria: event.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none transition focus:border-blue-500 focus:bg-white"
              >
                {availableCategories.map((category) => (
                  <option key={category} value={category}>{category}</option>
                ))}
              </select>
            </label>

            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">Metodo de pagamento</span>
              <select
                value={draft.metodo_pagamento}
                onChange={(event) => setDraft({ ...draft, metodo_pagamento: event.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none transition focus:border-blue-500 focus:bg-white"
              >
                {paymentMethodOptions.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </label>

            <label className="space-y-1 text-sm">
              <span className="font-medium text-slate-700">Conta</span>
              <select
                value={draft.conta}
                onChange={(event) => setDraft({ ...draft, conta: event.target.value })}
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none transition focus:border-blue-500 focus:bg-white"
              >
                {accountOptions.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </label>
          </div>

          <label className="block space-y-1 text-sm">
            <span className="font-medium text-slate-700">Descricao</span>
            <textarea
              value={draft.descricao}
              onChange={(event) => setDraft({ ...draft, descricao: event.target.value })}
              rows={4}
              maxLength={250}
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-slate-900 outline-none transition focus:border-blue-500 focus:bg-white"
              placeholder="Ex.: Almoco com cliente, farmacia, compras do mercado..."
              required
            />
          </label>

          <div className="flex items-center justify-end gap-3 border-t border-slate-200 pt-4">
            <button
              type="button"
              onClick={close}
              className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-50"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-60"
            >
              {saving && <Loader2 className="h-4 w-4 animate-spin" />}
              {editingId ? 'Salvar alteracoes' : 'Criar transacao'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

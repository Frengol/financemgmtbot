import { useEffect, type Dispatch, type SetStateAction } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, X } from 'lucide-react';

import CompactMonthPicker from '@/components/CompactMonthPicker';
import {
  accountOptions,
  formatAccountLabel,
  formatCategoryLabel,
  formatPaymentMethodLabel,
  normalizeTransactionValueInput,
  paymentMethodOptions,
  transactionCategories,
  transactionNatureLabels,
  type RecurringExpenseDraft,
  type RecurringExpenseRecord,
} from '@/lib/transactions';
import { formatMonthValue, parseMonthValue } from './form';

type RecurringExpenseModalProps = {
  editingId: string | null;
  form: RecurringExpenseDraft;
  setForm: Dispatch<SetStateAction<RecurringExpenseDraft>>;
  valueInput: string;
  setValueInput: Dispatch<SetStateAction<string>>;
  formError: string | null;
  saving: boolean;
  onClose: () => void;
  onSave: () => void;
};

export default function RecurringExpenseModal({
  editingId,
  form,
  setForm,
  valueInput,
  setValueInput,
  formError,
  saving,
  onClose,
  onSave,
}: RecurringExpenseModalProps) {
  const categoriesForNature = transactionCategories[form.natureza];

  useEffect(() => {
    if (!categoriesForNature.includes(form.categoria)) {
      setForm((prev) => ({ ...prev, categoria: categoriesForNature[0] }));
    }
  }, [categoriesForNature, form.categoria, setForm]);

  return createPortal((
    <div
      data-testid="recurring-expense-modal-overlay"
      className="fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto bg-slate-950/45 px-3 py-4 backdrop-blur-sm sm:px-6 sm:py-8"
    >
      <div className="w-full max-w-2xl overflow-hidden rounded-xl border border-slate-200 bg-white shadow-[0_32px_56px_-32px_rgba(15,23,42,0.45)]">
        <div className="flex items-center justify-between border-b border-slate-200/80 px-5 py-4 sm:px-6">
          <h3 className="text-lg font-semibold text-slate-950">
            {editingId ? 'Editar despesa recorrente' : 'Nova despesa recorrente'}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div
          data-testid="recurring-expense-modal-body"
          className="max-h-[76vh] space-y-5 overflow-y-auto px-5 py-5 sm:px-6"
        >
          {formError && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {formError}
            </div>
          )}

          <div
            data-testid="recurring-expense-top-fields"
            className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_8.5rem] sm:items-end"
          >
            <div className="space-y-1">
              <label htmlFor="nome" className="text-sm font-medium text-slate-700">
                Nome da despesa
              </label>
              <input
                id="nome"
                type="text"
                value={form.nome}
                onChange={(e) => setForm((prev) => ({ ...prev, nome: e.target.value }))}
                placeholder="Ex: Youtube Premium"
                className="h-11 w-full rounded-lg border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200"
              />
            </div>

            <label
              htmlFor="ativo"
              className="flex h-11 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700"
            >
              <input
                id="ativo"
                type="checkbox"
                checked={form.ativo}
                onChange={(e) => setForm((prev) => ({ ...prev, ativo: e.target.checked }))}
                className="h-4 w-4 rounded border-slate-300 text-slate-950 focus:ring-slate-200"
              />
              <span>Ativo</span>
            </label>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <label htmlFor="valor" className="text-sm font-medium text-slate-700">
                Valor
              </label>
              <input
                id="valor"
                type="text"
                inputMode="numeric"
                value={valueInput}
                onChange={(e) => setValueInput(normalizeTransactionValueInput(e.target.value))}
                placeholder="0,00"
                className="h-11 w-full rounded-lg border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200"
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="dia_mes" className="text-sm font-medium text-slate-700">
                Dia do mês
              </label>
              <input
                id="dia_mes"
                type="number"
                min={1}
                max={31}
                value={form.dia_mes}
                onChange={(e) => setForm((prev) => ({ ...prev, dia_mes: Number(e.target.value) }))}
                className="h-11 w-full rounded-lg border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-700">
                Mês de início
              </label>
              <CompactMonthPicker
                value={parseMonthValue(form.mes_inicio)}
                onChange={(value) => setForm((prev) => ({ ...prev, mes_inicio: formatMonthValue(value) }))}
                placeholder="Selecionar mês de início"
                ariaLabel="Mês de início"
                align="left"
                buttonClassName="flex h-11 w-full items-center justify-between rounded-lg border border-slate-200 bg-white px-4 text-left text-sm text-slate-900 outline-none transition hover:bg-slate-50 focus-visible:border-slate-400 focus-visible:ring-2 focus-visible:ring-slate-200"
              />
            </div>
            <div className="space-y-1">
              <label className="text-sm font-medium text-slate-700">
                Mês de fim (opcional)
              </label>
              <div className="flex gap-2">
                <div className="min-w-0 flex-1">
                  <CompactMonthPicker
                    value={parseMonthValue(form.mes_fim)}
                    onChange={(value) => setForm((prev) => ({ ...prev, mes_fim: formatMonthValue(value) }))}
                    placeholder="Selecionar mês de fim"
                    ariaLabel="Mês de fim"
                    align="left"
                    buttonClassName="flex h-11 w-full items-center justify-between rounded-lg border border-slate-200 bg-white px-4 text-left text-sm text-slate-900 outline-none transition hover:bg-slate-50 focus-visible:border-slate-400 focus-visible:ring-2 focus-visible:ring-slate-200"
                  />
                </div>
                {form.mes_fim && (
                  <button
                    type="button"
                    aria-label="Limpar mês de fim"
                    onClick={() => setForm((prev) => ({ ...prev, mes_fim: null }))}
                    className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-200"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <label htmlFor="natureza" className="text-sm font-medium text-slate-700">
                Natureza
              </label>
              <select
                id="natureza"
                value={form.natureza}
                onChange={(e) => setForm((prev) => ({
                  ...prev,
                  natureza: e.target.value as RecurringExpenseRecord['natureza'],
                }))}
                className="h-11 w-full rounded-lg border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200"
              >
                {transactionNatureLabels.map((nature) => (
                  <option key={nature} value={nature}>
                    {nature}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label htmlFor="categoria" className="text-sm font-medium text-slate-700">
                Categoria
              </label>
              <select
                id="categoria"
                value={form.categoria}
                onChange={(e) => setForm((prev) => ({ ...prev, categoria: e.target.value }))}
                className="h-11 w-full rounded-lg border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200"
              >
                {categoriesForNature.map((category) => (
                  <option key={category} value={category}>
                    {formatCategoryLabel(category)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <label htmlFor="metodo_pagamento" className="text-sm font-medium text-slate-700">
                Método de pagamento
              </label>
              <select
                id="metodo_pagamento"
                value={form.metodo_pagamento}
                onChange={(e) => setForm((prev) => ({ ...prev, metodo_pagamento: e.target.value }))}
                className="h-11 w-full rounded-lg border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200"
              >
                {paymentMethodOptions.map((method) => (
                  <option key={method} value={method}>
                    {formatPaymentMethodLabel(method)}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label htmlFor="conta" className="text-sm font-medium text-slate-700">
                Conta
              </label>
              <select
                id="conta"
                value={form.conta}
                onChange={(e) => setForm((prev) => ({ ...prev, conta: e.target.value }))}
                className="h-11 w-full rounded-lg border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200"
              >
                {accountOptions.map((account) => (
                  <option key={account} value={account}>
                    {formatAccountLabel(account)}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="flex flex-col-reverse gap-2 border-t border-slate-200/80 px-5 py-4 sm:flex-row sm:items-center sm:justify-end sm:px-6">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="h-11 rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 disabled:opacity-50 sm:h-10"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={saving}
            className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 text-sm font-medium text-white transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 disabled:opacity-50 sm:h-10"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            {editingId ? 'Salvar' : 'Criar'}
          </button>
        </div>
      </div>
    </div>
  ), document.body);
}

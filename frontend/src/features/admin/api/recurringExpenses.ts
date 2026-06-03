import type { RecurringExpenseDraft, RecurringExpenseRecord } from '@/lib/transactions';
import { apiRequest } from '@/features/admin/api/http';

function stripNatureza(payload: RecurringExpenseDraft) {
  const { natureza: _natureza, ...rest } = payload;
  return rest;
}

export function getRecurringExpenses() {
  return apiRequest<{ items: RecurringExpenseRecord[] }>('/api/admin/despesas-recorrentes', {
    method: 'GET',
  });
}

export function createRecurringExpense(payload: RecurringExpenseDraft) {
  return apiRequest<{ recurring_expense: RecurringExpenseRecord }>('/api/admin/despesas-recorrentes', {
    method: 'POST',
    body: JSON.stringify(stripNatureza(payload)),
  });
}

export function updateRecurringExpense(expenseId: string, payload: RecurringExpenseDraft) {
  return apiRequest<{ recurring_expense: RecurringExpenseRecord }>(`/api/admin/despesas-recorrentes/${expenseId}`, {
    method: 'PATCH',
    body: JSON.stringify(stripNatureza(payload)),
  });
}

export function deleteRecurringExpense(expenseId: string) {
  return apiRequest<{ id: string }>(`/api/admin/despesas-recorrentes/${expenseId}`, {
    method: 'DELETE',
  });
}

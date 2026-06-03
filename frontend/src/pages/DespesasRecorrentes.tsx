import { useEffect, useState, useMemo, useCallback } from "react";
import {
  ApiError,
  createRecurringExpense,
  deleteRecurringExpense,
  getRecurringExpenses,
  updateRecurringExpense,
} from "@/features/admin/api";
import { useAuth } from "@/hooks/useAuth";
import {
  Edit,
  Loader2,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import {
  createEmptyRecurringExpenseDraft,
  formatCategoryLabel,
  formatTransactionValue,
  type RecurringExpenseRecord,
  type RecurringExpenseDraft,
} from "@/lib/transactions";
import AdminRequestErrorBanner from "@/features/admin/components/AdminRequestErrorBanner";
import { createSessionUnavailableError, normalizeAdminPageError } from "@/features/admin/lib/pageErrors";
import RecurringExpenseModal from "@/features/recurring-expenses/RecurringExpenseModal";
import {
  buildRecurringExpenseDraft,
  formatMonthLabel,
  normalizeRecurringExpenseRecord,
  validateRecurringExpenseDraft,
} from "@/features/recurring-expenses/form";
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable, getFilteredRowModel, getPaginationRowModel } from "@tanstack/react-table";

const columnHelper = createColumnHelper<RecurringExpenseRecord>();

export default function DespesasRecorrentes() {
  const { authenticated, loading, localBypass, signOut } = useAuth();
  const [data, setData] = useState<RecurringExpenseRecord[]>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [fetching, setFetching] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<RecurringExpenseDraft>(createEmptyRecurringExpenseDraft());
  const [valueInput, setValueInput] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const fetchItems = useCallback(async () => {
    setFetching(true);
    try {
      const { items } = await getRecurringExpenses();
      setData((items || []).map(normalizeRecurringExpenseRecord));
      setError(null);
    } catch (fetchError) {
      setError(normalizeAdminPageError(fetchError, "Não foi possível carregar as despesas recorrentes agora."));
    }
    setFetching(false);
  }, []);

  useEffect(() => {
    if (!authenticated && !localBypass) {
      setFetching(false);
      if (data.length > 0) {
        setError(createSessionUnavailableError());
      } else {
        setData([]);
        setError(null);
      }
      return;
    }
    void fetchItems();
  }, [authenticated, localBypass]);

  const openCreate = () => {
    const nextForm = createEmptyRecurringExpenseDraft();
    setEditingId(null);
    setForm(nextForm);
    setValueInput(formatTransactionValue(nextForm.valor));
    setFormError(null);
    setModalOpen(true);
  };

  const openEdit = (item: RecurringExpenseRecord) => {
    setEditingId(item.id);
    const nextForm = buildRecurringExpenseDraft(item);
    setForm(nextForm);
    setValueInput(formatTransactionValue(item.valor));
    setFormError(null);
    setModalOpen(true);
  };

  const closeModal = () => {
    setModalOpen(false);
    setEditingId(null);
    setFormError(null);
  };

  const handleSave = async () => {
    const validation = validateRecurringExpenseDraft({
      draft: form,
      valueInput,
      loading,
      authenticated,
      localBypass,
    });
    if (!validation.ok) {
      setFormError(validation.error);
      return;
    }

    setSaving(true);
    setFormError(null);

    const payload = {
      ...form,
      valor: validation.parsedValue,
    };

    try {
      if (editingId) {
        await updateRecurringExpense(editingId, payload);
        setData((current) =>
          current.map((item) =>
            item.id === editingId ? normalizeRecurringExpenseRecord({ ...item, ...payload }) : item
          )
        );
      } else {
        const { recurring_expense } = await createRecurringExpense(payload);
        setData((current) => [...current, normalizeRecurringExpenseRecord(recurring_expense)]);
      }
      closeModal();
    } catch (saveError) {
      setFormError(
        normalizeAdminPageError(saveError, "Não foi possível salvar a despesa recorrente.").message
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (confirm("Deseja mesmo excluir esta despesa recorrente? A ação não pode ser desfeita.")) {
      if (loading) {
        setError(new Error("Sua autenticação ainda está sendo carregada. Tente novamente em alguns segundos."));
        return;
      }
      if (!authenticated && !localBypass) {
        setError(createSessionUnavailableError());
        return;
      }

      try {
        setPendingDeleteId(id);
        setError(null);
        await deleteRecurringExpense(id);
        setData((current) => current.filter((item) => item.id !== id));
      } catch (deleteError) {
        setError(normalizeAdminPageError(deleteError, "Não foi possível excluir a despesa recorrente."));
      } finally {
        setPendingDeleteId(null);
      }
    }
  };

  const columns = useMemo(
    () => [
      columnHelper.accessor("nome", {
        header: "Nome",
        cell: (info) => (
          <span className="font-medium text-slate-800">{String(info.getValue()).substring(0, 40)}</span>
        ),
      }),
      columnHelper.accessor("valor", {
        header: "Valor",
        cell: (info) => (
          <span className="font-semibold">
            R${" "}
            {Number(info.getValue()).toLocaleString("pt-BR", {
              minimumFractionDigits: 2,
            })}
          </span>
        ),
      }),
      columnHelper.accessor("dia_mes", {
        header: "Dia",
        cell: (info) => (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-800 border">
            Dia {info.getValue()}
          </span>
        ),
      }),
      columnHelper.accessor("mes_inicio", {
        header: "Início",
        cell: (info) => <span className="text-slate-600">{formatMonthLabel(info.getValue() as string)}</span>,
      }),
      columnHelper.accessor("mes_fim", {
        header: "Fim",
        cell: (info) => {
          const val = info.getValue() as string | null;
          return (
            <span className="text-slate-600">
              {val ? formatMonthLabel(val) : "Sem fim"}
            </span>
          );
        },
      }),
      columnHelper.accessor("categoria", {
        header: "Categoria",
        cell: (info) => (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-800 border">
            {formatCategoryLabel(info.getValue() as string)}
          </span>
        ),
      }),
      columnHelper.display({
        id: "actions",
        cell: (props) => (
          <div className="flex justify-end gap-2 text-slate-500">
            <button
              title="Editar"
              aria-label="Editar"
              onClick={() => openEdit(props.row.original)}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-200 disabled:opacity-50"
            >
              <Edit className="h-4 w-4" />
            </button>
            <button
              title="Excluir"
              aria-label="Excluir"
              onClick={() => handleDelete(props.row.original.id)}
              disabled={pendingDeleteId === props.row.original.id}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-200 disabled:opacity-50"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ),
      }),
    ],
    [authenticated, loading, localBypass, pendingDeleteId]
  );

  const table = useReactTable({
    data,
    columns,
    state: { globalFilter },
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="rounded-t-lg border-b border-slate-200 bg-white px-4 py-4 sm:px-5">
          <div className="w-full space-y-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="font-semibold text-lg text-slate-800">
                Despesas recorrentes
              </h2>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <div className="flex h-10 w-full items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 shadow-sm sm:w-64">
                  <Search className="h-4 w-4 text-slate-400" />
                  <input
                    type="text"
                    value={globalFilter ?? ""}
                    onChange={(e) => setGlobalFilter(e.target.value)}
                    placeholder="Buscar..."
                    className="min-w-0 flex-1 bg-transparent text-sm outline-none"
                  />
                </div>
                <button
                  onClick={openCreate}
                  className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 text-sm font-medium text-white shadow-[0_12px_24px_-18px_rgba(15,23,42,0.9)] transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 sm:w-auto"
                >
                  <Plus className="h-4 w-4" />
                  Nova
                </button>
              </div>
            </div>
            {error && (
              <AdminRequestErrorBanner
                error={error}
                onReauthenticate={() => void signOut()}
              />
            )}
          </div>
        </div>

        <div className="overflow-x-auto">
          {fetching ? (
            <div className="flex min-h-52 items-center justify-center text-slate-500">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              Carregando...
            </div>
          ) : data.length === 0 ? (
            <div className="flex min-h-56 flex-col items-center justify-center gap-4 px-6 py-10 text-slate-500">
              <div className="text-center">
                <p className="text-base font-medium text-slate-700">
                  Nenhuma despesa recorrente cadastrada
                </p>
                <p className="text-sm text-slate-400 mt-1">
                  Cadastre despesas que se repetem todo mês
                </p>
              </div>
              <button
                onClick={openCreate}
                className="inline-flex h-11 items-center gap-2 rounded-lg bg-slate-950 px-4 text-sm font-medium text-white shadow-[0_12px_24px_-18px_rgba(15,23,42,0.9)] transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2"
              >
                <Plus className="h-4 w-4" />
                Nova despesa recorrente
              </button>
            </div>
          ) : (
            <table className="min-w-[820px] w-full text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <th key={header.id} className="px-6 py-4">
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody className="divide-y divide-slate-100">
                {table.getRowModel().rows.map((row) => (
                  <tr key={row.id} className="transition hover:bg-slate-50/80">
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-6 py-4 whitespace-nowrap text-slate-600">
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext()
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {data.length > 0 && (
          <div className="flex flex-col gap-3 rounded-b-lg border-t border-slate-200 bg-slate-50/60 p-4 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-sm text-slate-500">
              Mostrando {table.getRowModel().rows.length} registros
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => table.previousPage()}
                disabled={!table.getCanPreviousPage()}
                className="h-10 rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
              >
                Anterior
              </button>
              <button
                onClick={() => table.nextPage()}
                disabled={!table.getCanNextPage()}
                className="h-10 rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
              >
                Próxima
              </button>
            </div>
          </div>
        )}
      </div>

      {modalOpen && (
        <RecurringExpenseModal
          editingId={editingId}
          form={form}
          setForm={setForm}
          valueInput={valueInput}
          setValueInput={setValueInput}
          formError={formError}
          saving={saving}
          onClose={closeModal}
          onSave={handleSave}
        />
      )}
    </div>
  );
}

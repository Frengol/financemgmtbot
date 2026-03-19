import { useEffect, useState, useMemo } from "react";
import { supabase } from "@/lib/supabase";
import { deleteTransaction } from "@/lib/adminApi";
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable, getFilteredRowModel, getPaginationRowModel } from '@tanstack/react-table';
import { useAuth } from "@/hooks/useAuth";
import { Edit, Trash2, Search } from "lucide-react";

type Gasto = {
  id: string;
  data: string;
  natureza: string;
  categoria: string;
  descricao: string;
  valor: number;
  conta: string;
};

const columnHelper = createColumnHelper<Gasto>();

export default function Historico() {
  const { accessToken } = useAuth();
  const [data, setData] = useState<Gasto[]>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [error, setError] = useState("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  const fetchGastos = async () => {
    const { data: gastos } = await supabase.from('gastos').select('*').order('data', { ascending: false });
    if (gastos) setData(gastos);
  };

  useEffect(() => {
    fetchGastos();
  }, []);

  const handleDelete = async (id: string) => {
    if (confirm("Deseja mesmo excluir este registro? A ação não pode ser desfeita.")) {
      if (!accessToken) {
        setError("Sua sessão expirou. Faça login novamente.");
        return;
      }

      try {
        setPendingDeleteId(id);
        setError("");
        await deleteTransaction(accessToken, id);
        setData((current) => current.filter((item) => item.id !== id));
      } catch (deleteError) {
        setError(deleteError instanceof Error ? deleteError.message : "Nao foi possivel excluir o registro.");
      } finally {
        setPendingDeleteId(null);
      }
    }
  };

  const columns = useMemo(() => [
    columnHelper.accessor('data', {
      header: 'Data',
      cell: info => new Date(info.getValue()).toLocaleDateString('pt-BR', { timeZone: "UTC" }),
    }),
    columnHelper.accessor('descricao', {
      header: 'Descrição',
      cell: info => <span className="font-medium text-slate-800">{String(info.getValue() || '').substring(0, 35)}</span>,
    }),
    columnHelper.accessor('categoria', {
      header: 'Categoria',
      cell: info => (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-800 border">
          {info.getValue() || "N/A"}
        </span>
      ),
    }),
    columnHelper.accessor('valor', {
      header: 'Valor',
      cell: info => <span className="font-semibold">R$ {Number(info.getValue()).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</span>,
    }),
    columnHelper.display({
      id: 'actions',
      cell: (props) => (
        <div className="flex justify-end gap-3 text-slate-400">
           <button title="Editar" className="hover:text-blue-600 transition"><Edit className="h-4 w-4" /></button>
           <button
             onClick={() => handleDelete(props.row.original.id)}
             title="Excluir"
             disabled={pendingDeleteId === props.row.original.id}
             className="hover:text-rose-600 transition disabled:opacity-50"
           >
             <Trash2 className="h-4 w-4" />
           </button>
        </div>
      ),
    })
  ], [pendingDeleteId]);

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
    <div className="bg-white border rounded-xl shadow-sm">
      <div className="p-5 border-b flex justify-between items-center bg-slate-50/50 rounded-t-xl">
        <div className="space-y-3 w-full">
          <div className="flex justify-between items-center gap-4">
            <h2 className="font-semibold text-lg text-slate-800">Auditoria de Lançamentos</h2>
            <div className="flex items-center gap-2 bg-white border px-3 py-1.5 rounded-md shadow-sm">
              <Search className="h-4 w-4 text-slate-400" />
              <input
                type="text"
                value={globalFilter ?? ''}
                onChange={e => setGlobalFilter(e.target.value)}
                placeholder="Buscar (ex: Mercado)..."
                className="outline-none text-sm w-48 bg-transparent"
              />
            </div>
          </div>
          {error && (
            <div className="bg-rose-50 text-rose-700 border border-rose-100 rounded-lg px-4 py-3 text-sm">
              {error}
            </div>
          )}
        </div>
      </div>
      
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="bg-slate-50 text-slate-500 font-medium border-b">
            {table.getHeaderGroups().map(headerGroup => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map(header => (
                  <th key={header.id} className="px-6 py-4">
                    {flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-slate-100">
            {table.getRowModel().rows.map(row => (
              <tr key={row.id} className="hover:bg-slate-50/80 transition">
                {row.getVisibleCells().map(cell => (
                  <td key={cell.id} className="px-6 py-4 whitespace-nowrap text-slate-600">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      
      <div className="p-4 border-t flex justify-between items-center bg-slate-50/50 rounded-b-xl">
        <span className="text-sm text-slate-500">Mostrando {table.getRowModel().rows.length} registros</span>
        <div className="flex gap-2">
            <button
               onClick={() => table.previousPage()}
               disabled={!table.getCanPreviousPage()}
               className="px-4 py-2 border rounded-md disabled:opacity-50 text-slate-700 bg-white hover:bg-slate-50 shadow-sm text-sm font-medium"
            >Anterior</button>
            <button
               onClick={() => table.nextPage()}
               disabled={!table.getCanNextPage()}
               className="px-4 py-2 border rounded-md disabled:opacity-50 text-slate-700 bg-white hover:bg-slate-50 shadow-sm text-sm font-medium"
            >Próxima</button>
        </div>
      </div>
    </div>
  );
}

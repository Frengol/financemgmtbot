import { useEffect, useState } from "react";
import { approvePendingReceipt, getPendingReceipts, rejectPendingReceipt } from "@/lib/adminApi";
import { useAuth } from "@/hooks/useAuth";
import { Check, X, CreditCard, ListMinus } from "lucide-react";

type CacheItem = {
  id: string;
  payload: any;
  created_at: string;
};

export default function Aprovacoes() {
  const { accessToken, localBypass } = useAuth();
  const [items, setItems] = useState<CacheItem[]>([]);
  const [error, setError] = useState("");
  const [pendingId, setPendingId] = useState<string | null>(null);

  const fetchCache = async () => {
    try {
      const { items: data } = await getPendingReceipts(accessToken || '');
      if (data) {
        setItems(data as CacheItem[]);
      }
    } catch {
      setError("Nao foi possivel carregar as aprovacoes agora.");
    }
  };

  useEffect(() => {
    void fetchCache();
  }, [accessToken]);

  useEffect(() => {
    const refresh = () => {
      void fetchCache();
    };

    window.addEventListener('transactions:changed', refresh);
    return () => window.removeEventListener('transactions:changed', refresh);
  }, [accessToken]);

  const handleAprovar = async (item: CacheItem) => {
    if (!accessToken && !localBypass) {
      setError("Sua sessão expirou. Faça login novamente.");
      return;
    }

    try {
      setPendingId(item.id);
      setError("");
      await approvePendingReceipt(accessToken || '', item.id);
      setItems((current) => current.filter((currentItem) => currentItem.id !== item.id));
      window.dispatchEvent(new CustomEvent('transactions:changed'));
    } catch (approveError) {
      setError(approveError instanceof Error ? approveError.message : "Nao foi possivel aprovar o cupom pendente.");
    } finally {
      setPendingId(null);
    }
  };

  const handleRejeitar = async (id: string) => {
    if (!accessToken && !localBypass) {
      setError("Sua sessão expirou. Faça login novamente.");
      return;
    }

    try {
      setPendingId(id);
      setError("");
      await rejectPendingReceipt(accessToken || '', id);
      setItems((current) => current.filter((currentItem) => currentItem.id !== id));
      window.dispatchEvent(new CustomEvent('transactions:changed'));
    } catch (rejectError) {
      setError(rejectError instanceof Error ? rejectError.message : "Nao foi possivel rejeitar o cupom pendente.");
    } finally {
      setPendingId(null);
    }
  };

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-slate-500">
        <Check className="h-12 w-12 text-slate-300 mb-4" />
        <p>A caixa de aprovações está vazia. Tudo atualizado!</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="bg-rose-50 text-rose-700 border border-rose-100 rounded-lg px-4 py-3 text-sm">
          {error}
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {items.map((item) => {
          const dataLote = item.payload || {};
          const isLote = dataLote.itens && Array.isArray(dataLote.itens);
          const totalEstimado = isLote 
            ? dataLote.itens.reduce((acc: number, curr: any) => acc + (Number(curr.valor_bruto) || 0) - (Number(curr.desconto_item) || 0), 0) - (Number(dataLote.desconto_global)||0) 
            : 0;

          return (
            <div key={item.id} className="bg-white border text-sm rounded-xl p-5 shadow-sm hover:shadow-md transition">
              <div className="flex justify-between items-start mb-4">
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700">
                  <ListMinus className="w-3.5 h-3.5" />
                  Cupom Pendente
                </span>
                <span className="text-slate-400 text-xs">
                  {new Date(item.created_at).toLocaleDateString()}
                </span>
              </div>
              
              <div className="space-y-3 mb-6">
                <div className="flex items-center gap-2 text-slate-700">
                  <CreditCard className="w-4 h-4 text-slate-400" />
                  <span className="font-medium">{dataLote.metodo_pagamento || "Não informado"}</span>
                  <span className="text-slate-500 text-xs">({dataLote.conta || "Conta não informada"})</span>
                </div>
                
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 space-y-2">
                  <p className="font-semibold text-slate-800 text-xs flex justify-between">
                    <span>Qtd de Itens: {isLote ? dataLote.itens.length : 0}</span>
                    <span className="text-blue-600">Total: R$ {Math.max(0, totalEstimado).toFixed(2)}</span>
                  </p>
                  <ul className="text-xs text-slate-600 space-y-1">
                    {isLote && dataLote.itens.slice(0, 3).map((it:any, idx:number) => (
                      <li key={idx} className="truncate">• {it.nome}</li>
                    ))}
                    {isLote && dataLote.itens.length > 3 && (
                      <li className="text-slate-400 italic">...e mais {dataLote.itens.length - 3} itens</li>
                    )}
                  </ul>
                </div>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={() => handleAprovar(item)}
                  disabled={pendingId === item.id}
                  className="flex-1 flex items-center justify-center gap-2 bg-emerald-500 hover:bg-emerald-600 text-white font-medium py-2 px-4 rounded-lg transition"
                >
                  <Check className="w-4 h-4" />
                  Aprovar
                </button>
                <button
                  onClick={() => handleRejeitar(item.id)}
                  disabled={pendingId === item.id}
                  className="flex items-center justify-center gap-2 bg-rose-50 hover:bg-rose-100 text-rose-600 font-medium py-2 px-4 rounded-lg transition"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

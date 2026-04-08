import { useEffect, useState } from "react";
import { ApiError, approvePendingReceipt, getPendingReceipts, isReauthenticationError, rejectPendingReceipt, type PendingApprovalItem } from "@/lib/adminApi";
import { useAuth } from "@/hooks/useAuth";
import { Check, X, CreditCard, ListMinus } from "lucide-react";
import { clearBrowserAdminArtifacts } from "@/lib/auth";

export default function Aprovacoes() {
  const { authenticated, csrfToken, localBypass, signOut } = useAuth();
  const [items, setItems] = useState<PendingApprovalItem[]>([]);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const fetchCache = async () => {
    if (!authenticated && !localBypass) {
      setItems([]);
      setError(null);
      return;
    }

    try {
      const { items: data } = await getPendingReceipts();
      if (data) {
        setItems(data as PendingApprovalItem[]);
      }
      setError(null);
    } catch (fetchError) {
      if (isReauthenticationError(fetchError)) {
        clearBrowserAdminArtifacts();
      }
      setError(fetchError instanceof Error ? fetchError : new Error("Nao foi possivel carregar as aprovacoes agora."));
    }
  };

  useEffect(() => {
    void fetchCache();
  }, [authenticated, localBypass]);

  useEffect(() => {
    const refresh = () => {
      void fetchCache();
    };

    window.addEventListener('transactions:changed', refresh);
    return () => window.removeEventListener('transactions:changed', refresh);
  }, [authenticated, localBypass]);

  const handleAprovar = async (item: PendingApprovalItem) => {
    if ((!authenticated || !csrfToken) && !localBypass) {
      setError(new Error("Sua sessão expirou. Faça login novamente."));
      return;
    }

    try {
      setPendingId(item.id);
      setError(null);
      await approvePendingReceipt(item.id, csrfToken);
      setItems((current) => current.filter((currentItem) => currentItem.id !== item.id));
      window.dispatchEvent(new CustomEvent('transactions:changed'));
    } catch (approveError) {
      if (isReauthenticationError(approveError)) {
        clearBrowserAdminArtifacts();
      }
      setError(approveError instanceof Error ? approveError : new Error("Nao foi possivel aprovar o cupom pendente."));
    } finally {
      setPendingId(null);
    }
  };

  const handleRejeitar = async (id: string) => {
    if ((!authenticated || !csrfToken) && !localBypass) {
      setError(new Error("Sua sessão expirou. Faça login novamente."));
      return;
    }

    try {
      setPendingId(id);
      setError(null);
      await rejectPendingReceipt(id, csrfToken);
      setItems((current) => current.filter((currentItem) => currentItem.id !== id));
      window.dispatchEvent(new CustomEvent('transactions:changed'));
    } catch (rejectError) {
      if (isReauthenticationError(rejectError)) {
        clearBrowserAdminArtifacts();
      }
      setError(rejectError instanceof Error ? rejectError : new Error("Nao foi possivel rejeitar o cupom pendente."));
    } finally {
      setPendingId(null);
    }
  };

  if (items.length === 0 && !error) {
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
        <div className="flex flex-col gap-3 rounded-lg border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700 md:flex-row md:items-center md:justify-between">
          <span>{error.message}</span>
          {isReauthenticationError(error) ? (
            <button
              type="button"
              onClick={() => void signOut()}
              className="inline-flex items-center justify-center rounded-lg border border-rose-200 bg-white px-3 py-2 font-medium text-rose-700 transition hover:bg-rose-100"
            >
              Fazer login novamente
            </button>
          ) : null}
        </div>
      )}
      {items.length === 0 ? null : (
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {items.map((item) => {
          const preview = item.preview || {};
          const isReceiptBatch = item.kind !== 'delete_confirmation';
          const previewItems = Array.isArray(preview.itens) ? preview.itens : [];
          const totalEstimado = Number(preview.total_estimado) || 0;
          const recordCount = Number(preview.records_count) || 0;

          return (
            <div key={item.id} className="bg-white border text-sm rounded-xl p-5 shadow-sm hover:shadow-md transition">
              <div className="flex justify-between items-start mb-4">
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700">
                  <ListMinus className="w-3.5 h-3.5" />
                  {preview.summary || (isReceiptBatch ? 'Cupom Pendente' : 'Pendencia Administrativa')}
                </span>
                <span className="text-slate-400 text-xs">
                  {new Date(item.created_at).toLocaleDateString()}
                </span>
              </div>
              
              <div className="space-y-3 mb-6">
                {isReceiptBatch ? (
                  <div className="flex items-center gap-2 text-slate-700">
                    <CreditCard className="w-4 h-4 text-slate-400" />
                    <span className="font-medium">{preview.metodo_pagamento || "Não informado"}</span>
                    <span className="text-slate-500 text-xs">({preview.conta || "Conta não informada"})</span>
                  </div>
                ) : null}
                
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 space-y-2">
                  <p className="font-semibold text-slate-800 text-xs flex justify-between">
                    <span>{isReceiptBatch ? `Qtd de Itens: ${preview.itens_count || 0}` : `Registros: ${recordCount}`}</span>
                    {isReceiptBatch ? <span className="text-blue-600">Total: R$ {Math.max(0, totalEstimado).toFixed(2)}</span> : null}
                  </p>
                  <ul className="text-xs text-slate-600 space-y-1">
                    {previewItems.slice(0, 3).map((itemName, idx) => (
                      <li key={idx} className="truncate">• {itemName}</li>
                    ))}
                    {previewItems.length > 3 && (
                      <li className="text-slate-400 italic">...e mais {previewItems.length - 3} itens</li>
                    )}
                    {!previewItems.length && !isReceiptBatch && (
                      <li className="text-slate-400 italic">Aguardando confirmacao da exclusao segura.</li>
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
      )}
    </div>
  );
}

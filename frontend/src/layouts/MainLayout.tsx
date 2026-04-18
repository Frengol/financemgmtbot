import { Link, Outlet, useLocation } from "react-router-dom";
import { CopyPlus, LayoutDashboard, History, CheckSquare, Activity, LogOut, Menu, X } from "lucide-react";
import { useState, useEffect } from "react";
import { getAdminMe } from "@/features/admin/api";
import { useAuth } from "@/hooks/useAuth";
import { useTransactionComposer } from "@/hooks/useTransactionComposer";

export default function MainLayout() {
  const [isOnline, setIsOnline] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const location = useLocation();
  const { authenticated, loading, signOut } = useAuth();
  const { openCreate } = useTransactionComposer();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        openCreate();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [openCreate]);

  useEffect(() => {
    let cancelled = false;
    const authCallbackRoute = location.pathname.endsWith('/auth/callback');

    if (loading || !authenticated || authCallbackRoute) {
      setIsOnline(false);
      return () => {
        cancelled = true;
      };
    }

    const checkStatus = async () => {
      try {
        await getAdminMe();
        if (!cancelled) {
          setIsOnline(true);
        }
      } catch {
        if (!cancelled) {
          setIsOnline(false);
        }
      }
    };

    void checkStatus();

    return () => {
      cancelled = true;
    };
  }, [authenticated, loading, location.pathname]);

  useEffect(() => {
    setIsMobileMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!isMobileMenuOpen) {
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsMobileMenuOpen(false);
      }
    };

    window.addEventListener('keydown', handleEscape);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleEscape);
    };
  }, [isMobileMenuOpen]);

  const menu = [
    { name: "Dashboard", path: "/", icon: LayoutDashboard },
    { name: "Aprovações", path: "/aprovacoes", icon: CheckSquare },
    { name: "Histórico", path: "/historico", icon: History },
  ];

  const getPageTitle = () => {
    const route = menu.find(m => m.path === location.pathname);
    return route ? route.name : "Painel";
  };

  const renderMenuLinks = (onNavigate?: () => void) => (
    <>
      {menu.map((item) => (
        <Link
          key={item.path}
          to={item.path}
          onClick={onNavigate}
          className={`flex items-center gap-3 rounded-2xl border px-3 py-3 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 ${
            location.pathname === item.path
              ? "border-slate-200 bg-slate-100 text-slate-950 shadow-[0_16px_28px_-24px_rgba(15,23,42,0.42)]"
              : "border-transparent text-slate-500 hover:border-slate-200 hover:bg-slate-50 hover:text-slate-900"
          }`}
        >
          <item.icon className="h-4 w-4 shrink-0" />
          {item.name}
        </Link>
      ))}
    </>
  );

  return (
    <div className="flex h-screen w-full bg-slate-100">
      <aside className="hidden w-[236px] flex-col border-r border-slate-200/80 bg-white md:flex">
        <div className="border-b border-slate-200/80 px-6 py-6">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-slate-200 bg-slate-50 text-slate-700 shadow-[0_12px_26px_-24px_rgba(15,23,42,0.45)]">
              <Activity className="h-5 w-5" />
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.26em] text-slate-400">Finance</p>
              <p className="mt-1 text-base font-semibold tracking-[-0.02em] text-slate-950">Finance Copilot</p>
            </div>
          </div>
        </div>
        <nav className="flex-1 space-y-1 px-4 py-5">
          {renderMenuLinks()}
        </nav>

        <div className="border-t border-slate-200/80 p-4">
          <button
            onClick={signOut}
            className="flex w-full items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm font-medium text-slate-600 transition hover:border-rose-200 hover:bg-rose-50/60 hover:text-rose-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2"
          >
            <LogOut className="h-4 w-4" />
            Sair
          </button>
        </div>
      </aside>

      {isMobileMenuOpen && (
        <div className="fixed inset-0 z-40 md:hidden" aria-hidden="true">
          <button
            type="button"
            className="absolute inset-0 bg-slate-950/12 backdrop-blur-[1px]"
            onClick={() => setIsMobileMenuOpen(false)}
          />
        </div>
      )}

      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Menu de navegacao"
        className={`fixed inset-y-0 left-0 z-50 w-72 max-w-[82vw] border-r border-slate-200 bg-white shadow-[0_32px_56px_-32px_rgba(15,23,42,0.45)] transition-transform duration-200 md:hidden ${
          isMobileMenuOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-slate-200 bg-slate-50 text-slate-700">
              <Activity className="h-4 w-4" />
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-400">Finance</p>
              <p className="mt-1 text-sm font-semibold text-slate-950">Finance Copilot</p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Fechar menu de navegacao"
            className="rounded-2xl p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2"
            onClick={() => setIsMobileMenuOpen(false)}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-1 p-4">
          {renderMenuLinks(() => setIsMobileMenuOpen(false))}
        </nav>

        <div className="border-t border-slate-200 p-4">
          <button
            onClick={() => {
              setIsMobileMenuOpen(false);
              void signOut();
            }}
            className="flex w-full items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm font-medium text-slate-600 transition hover:border-rose-200 hover:bg-rose-50/60 hover:text-rose-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2"
          >
            <LogOut className="h-4 w-4" />
            Sair
          </button>
        </div>
      </aside>

      <div className="flex-1 flex flex-col h-screen overflow-hidden">
        <header className="flex min-h-[72px] items-center justify-between border-b border-slate-200/80 bg-white/95 px-4 py-3 backdrop-blur md:min-h-[76px] md:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              aria-label="Abrir menu de navegacao"
              className="inline-flex rounded-2xl border border-slate-200 bg-white p-2.5 text-slate-500 shadow-sm transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 md:hidden"
              onClick={() => setIsMobileMenuOpen(true)}
            >
              <Menu className="h-4 w-4" />
            </button>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Painel</p>
              <h1 className="mt-1 truncate text-xl font-semibold tracking-[-0.03em] text-slate-950 md:text-2xl">{getPageTitle()}</h1>
            </div>
          </div>
          <div className="flex items-center gap-2 md:gap-4">
             <div className="hidden items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-500 md:flex">
               <span className={`h-2 w-2 rounded-full ${isOnline ? 'bg-emerald-500' : 'bg-rose-500'}`} />
               {isOnline ? 'Online' : 'Offline'}
             </div>

             <button
               onClick={signOut}
               aria-label="Sair"
               className="inline-flex rounded-2xl border border-slate-200 bg-white p-2.5 text-slate-400 transition hover:border-rose-200 hover:bg-rose-50/60 hover:text-rose-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 md:hidden"
               title="Sair"
             >
                <LogOut className="h-5 w-5" />
             </button>

             <button
               onClick={openCreate}
               aria-label="Nova transação"
               className="inline-flex items-center gap-2 rounded-2xl bg-slate-950 px-3 py-2.5 text-sm font-medium text-white shadow-[0_16px_28px_-18px_rgba(15,23,42,0.7)] transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 focus-visible:ring-offset-2 md:px-4 md:py-3"
             >
               <CopyPlus className="h-4 w-4" />
               <span className="hidden min-[440px]:inline md:inline">Nova Transação</span>
               <kbd className="ml-1 hidden rounded-lg bg-slate-800 px-1.5 py-0.5 text-[11px] font-mono text-slate-300 lg:inline-flex">⌘K</kbd>
             </button>
          </div>
        </header>

        <main className="flex-1 overflow-auto bg-slate-100 px-4 py-5 sm:px-5 md:px-8 md:py-8">
          <div className="mx-auto max-w-[1340px] pb-10">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

import { Link, Outlet, useLocation } from "react-router-dom";
import { CopyPlus, LayoutDashboard, History, CheckSquare, Activity, LogOut, Menu, X } from "lucide-react";
import { useState, useEffect } from "react";
import { getTransactions } from "@/lib/adminApi";
import { useAuth } from "@/hooks/useAuth";
import { useTransactionComposer } from "@/hooks/useTransactionComposer";

export default function MainLayout() {
  const [isOnline, setIsOnline] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const location = useLocation();
  const { authenticated, loading, user, signOut } = useAuth();
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
        await getTransactions({ dateFrom: '2000-01-01', dateTo: '2000-01-01' });
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
          className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
            location.pathname === item.path
              ? "bg-blue-50 text-blue-700"
              : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
          }`}
        >
          <item.icon className="h-4 w-4" />
          {item.name}
        </Link>
      ))}
    </>
  );

  return (
    <div className="flex h-screen w-full bg-gray-50/50">
      <aside className="w-64 border-r bg-white flex flex-col hidden md:flex">
        <div className="h-16 flex items-center px-6 border-b font-semibold text-lg text-slate-800 gap-2">
          <Activity className="h-5 w-5 text-blue-600" />
          Finance Copilot
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {renderMenuLinks()}
        </nav>
        
        <div className="p-4 border-t space-y-3">
          {user && (
            <div className="flex items-center gap-2 px-2 text-xs text-slate-500 truncate">
              <div className="h-6 w-6 rounded-full bg-slate-100 flex items-center justify-center font-bold text-slate-700 uppercase">
                {user.email?.charAt(0)}
              </div>
              <span className="truncate">{user.email}</span>
            </div>
          )}
          <button
            onClick={signOut}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-rose-600 bg-rose-50 hover:bg-rose-100 rounded-md transition"
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
            className="absolute inset-0 bg-slate-950/20"
            onClick={() => setIsMobileMenuOpen(false)}
          />
        </div>
      )}

      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Menu de navegacao"
        className={`fixed inset-y-0 left-0 z-50 w-72 max-w-[80vw] border-r border-slate-200 bg-white/95 shadow-xl backdrop-blur-sm transition-transform duration-200 md:hidden ${
          isMobileMenuOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-16 items-center justify-between border-b px-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Activity className="h-4 w-4 text-blue-600" />
            Finance Copilot
          </div>
          <button
            type="button"
            aria-label="Fechar menu de navegacao"
            className="rounded-md p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
            onClick={() => setIsMobileMenuOpen(false)}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-1 p-4">
          {renderMenuLinks(() => setIsMobileMenuOpen(false))}
        </nav>

        <div className="border-t p-4 space-y-3">
          {user && (
            <div className="flex items-center gap-2 px-2 text-xs text-slate-500 truncate">
              <div className="h-6 w-6 rounded-full bg-slate-100 flex items-center justify-center font-bold text-slate-700 uppercase">
                {user.email?.charAt(0)}
              </div>
              <span className="truncate">{user.email}</span>
            </div>
          )}

          <button
            onClick={() => {
              setIsMobileMenuOpen(false);
              void signOut();
            }}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium text-rose-600 bg-rose-50 hover:bg-rose-100 rounded-md transition"
          >
            <LogOut className="h-4 w-4" />
            Sair
          </button>
        </div>
      </aside>

      <div className="flex-1 flex flex-col h-screen overflow-hidden">
        <header className="h-16 flex items-center justify-between px-6 border-b bg-white">
          <div className="flex items-center gap-3">
            <button
              type="button"
              aria-label="Abrir menu de navegacao"
              className="inline-flex rounded-md border border-slate-200 bg-white p-2 text-slate-500 shadow-sm transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 md:hidden"
              onClick={() => setIsMobileMenuOpen(true)}
            >
              <Menu className="h-4 w-4" />
            </button>
            <h1 className="text-xl font-semibold text-slate-800">{getPageTitle()}</h1>
          </div>
          <div className="flex items-center gap-4">
             <div className="flex items-center gap-2 text-sm text-slate-500">
               <span className={`h-2.5 w-2.5 rounded-full ${isOnline ? 'bg-emerald-500' : 'bg-rose-500'}`} />
               {isOnline ? 'Online' : 'Offline'}
             </div>
             
             <button onClick={signOut} className="md:hidden text-slate-400 hover:text-rose-600 transition" title="Sair">
                <LogOut className="h-5 w-5" />
             </button>

             <button
               onClick={openCreate}
               className="hidden md:flex items-center gap-2 bg-slate-900 text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-slate-800 transition shadow-sm"
             >
               <CopyPlus className="h-4 w-4" />
               <span className="hidden sm:inline">Nova Transação</span>
               <kbd className="hidden sm:inline-flex bg-slate-700 text-slate-300 rounded px-1.5 py-0.5 text-xs font-mono ml-2">⌘K</kbd>
             </button>
          </div>
        </header>

        <main className="flex-1 overflow-auto p-6">
          <div className="max-w-6xl mx-auto pb-10">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

import { Link, Outlet, useLocation } from "react-router-dom";
import { CopyPlus, LayoutDashboard, History, CheckSquare, Activity, LogOut } from "lucide-react";
import { useState, useEffect } from "react";
import { supabase } from "@/lib/supabase";
import { useAuth } from "@/hooks/useAuth";

export default function MainLayout() {
  const [isOnline, setIsOnline] = useState(false);
  const location = useLocation();
  const { user, signOut } = useAuth();

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const { error } = await supabase.from('gastos').select('id').limit(1);
        setIsOnline(!error);
      } catch {
        setIsOnline(false);
      }
    };
    checkStatus();
    
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        alert("Atalho detectado: Novo Rascunho de Transação");
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const menu = [
    { name: "Dashboard", path: "/", icon: LayoutDashboard },
    { name: "Aprovações", path: "/aprovacoes", icon: CheckSquare },
    { name: "Histórico", path: "/historico", icon: History },
  ];

  const getPageTitle = () => {
    const route = menu.find(m => m.path === location.pathname);
    return route ? route.name : "Painel";
  };

  return (
    <div className="flex h-screen w-full bg-gray-50/50">
      <aside className="w-64 border-r bg-white flex flex-col hidden md:flex">
        <div className="h-16 flex items-center px-6 border-b font-semibold text-lg text-slate-800 gap-2">
          <Activity className="h-5 w-5 text-blue-600" />
          Finance Copilot
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {menu.map((item) => (
            <Link
              key={item.path}
              to={item.path}
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

      <div className="flex-1 flex flex-col h-screen overflow-hidden">
        <header className="h-16 flex items-center justify-between px-6 border-b bg-white">
          <h1 className="text-xl font-semibold text-slate-800">{getPageTitle()}</h1>
          <div className="flex items-center gap-4">
             <div className="flex items-center gap-2 text-sm text-slate-500">
               <span className={`h-2.5 w-2.5 rounded-full ${isOnline ? 'bg-emerald-500' : 'bg-rose-500'}`} />
               {isOnline ? 'Online' : 'Offline'}
             </div>
             
             <button onClick={signOut} className="md:hidden text-slate-400 hover:text-rose-600 transition" title="Sair">
                <LogOut className="h-5 w-5" />
             </button>

             <button
               onClick={() => alert("Abrir modal: Nova Transação!")}
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

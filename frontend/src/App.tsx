import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./hooks/useAuth";
import { TransactionComposerProvider } from "./hooks/useTransactionComposer";
import TransactionModalGate from "./components/TransactionModalGate";
import { Loader2 } from "lucide-react";

const MainLayout = lazy(() => import("./layouts/MainLayout"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Aprovacoes = lazy(() => import("./pages/Aprovacoes"));
const Historico = lazy(() => import("./pages/Historico"));
const Login = lazy(() => import("./pages/Login"));
const ProtectedRoute = lazy(() => import("./components/ProtectedRoute"));

function RouteFallback() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
    </div>
  );
}

export default function App() {
  const basename = import.meta.env.BASE_URL === "/" ? "/" : import.meta.env.BASE_URL.replace(/\/$/, "");

  return (
    <AuthProvider>
      <TransactionComposerProvider>
        <BrowserRouter basename={basename}>
          <Suspense fallback={<RouteFallback />}>
            <Routes>
              <Route path="/login" element={<Login />} />
              
              <Route element={<ProtectedRoute />}>
                <Route path="/" element={<MainLayout />}>
                  <Route index element={<Dashboard />} />
                  <Route path="aprovacoes" element={<Aprovacoes />} />
                  <Route path="historico" element={<Historico />} />
                </Route>
              </Route>
            </Routes>
          </Suspense>
          <TransactionModalGate />
        </BrowserRouter>
      </TransactionComposerProvider>
    </AuthProvider>
  );
}

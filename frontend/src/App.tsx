import { BrowserRouter, Routes, Route } from "react-router-dom";
import MainLayout from "./layouts/MainLayout";
import Dashboard from "./pages/Dashboard";
import Aprovacoes from "./pages/Aprovacoes";
import Historico from "./pages/Historico";
import Login from "./pages/Login";
import ProtectedRoute from "./components/ProtectedRoute";

export default function App() {
  return (
    <BrowserRouter basename="/financemgmtbot">
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
    </BrowserRouter>
  );
}

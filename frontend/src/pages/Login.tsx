import { useState } from 'react';
import { Activity, Mail, Loader2, CheckCircle2 } from 'lucide-react';
import { localDevBypassEnabled, requestMagicLink } from '@/lib/adminApi';

export default function Login() {
  const redirectTarget = new URL(import.meta.env.BASE_URL, window.location.origin).toString();
  const searchParams = new URLSearchParams(window.location.search);
  const reason = searchParams.get('reason');
  const requestId = searchParams.get('requestId');
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState('');

  if (localDevBypassEnabled) {
    window.location.replace(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
    return null;
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      await requestMagicLink(email, redirectTarget);
      setSuccess(true);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Nao foi possivel solicitar o magic link agora.');
    }
    setLoading(false);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="max-w-md w-full bg-white rounded-2xl shadow-sm border p-8 space-y-6">
        <div className="flex flex-col items-center justify-center space-y-3">
          <div className="h-12 w-12 bg-blue-50 text-blue-600 rounded-full flex items-center justify-center">
            <Activity className="h-6 w-6" />
          </div>
          <h2 className="text-2xl font-semibold text-slate-800">Finance Copilot</h2>
          <p className="text-slate-500 text-sm text-center">
            Acesso restrito via Magic Link. <br /> Informe seu e-mail para receber o acesso.
          </p>
        </div>

        {success ? (
          <div className="bg-emerald-50 text-emerald-700 p-4 rounded-lg flex flex-col items-center gap-2 text-center border border-emerald-100">
            <CheckCircle2 className="h-6 w-6" />
            <p className="text-sm font-medium">Link mágico enviado!</p>
            <p className="text-xs opacity-90">Verifique a caixa de entrada (e o Spam) do e-mail <b>{email}</b> para fazer login.</p>
          </div>
        ) : (
          <form onSubmit={handleLogin} className="space-y-4">
            {reason === 'unauthorized' && (
              <div className="bg-amber-50 text-amber-700 p-3 rounded-lg text-sm border border-amber-100">
                Este usuario autenticou, mas nao esta autorizado a acessar o painel administrativo.
              </div>
            )}
            {reason === 'auth_unavailable' && (
              <div className="bg-amber-50 text-amber-700 p-3 rounded-lg text-sm border border-amber-100">
                <p>O login esta temporariamente indisponivel. Tente novamente em instantes.</p>
                {requestId && <p className="mt-1 text-xs">Codigo de suporte: {requestId}</p>}
              </div>
            )}
            {error && (
              <div className="bg-rose-50 text-rose-600 p-3 rounded-lg text-sm border border-rose-100">
                {error}
              </div>
            )}
            
            <div className="space-y-1.5">
              <label htmlFor="email" className="text-xs font-medium text-slate-700">
                E-mail de Acesso
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                  <Mail className="h-4 w-4" />
                </div>
                <input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  autoCapitalize="none"
                  autoCorrect="off"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full pl-10 pr-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-shadow bg-slate-50 text-slate-900"
                  placeholder="seu e-mail"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading || !email}
              className="w-full flex justify-center items-center py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                'Enviar Magic Link'
              )}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

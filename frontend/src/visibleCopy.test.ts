import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const sourceFiles = [
  'components/TransactionModal.tsx',
  'components/DashboardPeriodPicker.tsx',
  'features/admin/api/http.ts',
  'features/admin/lib/pageErrors.ts',
  'features/observability/clientTelemetry.ts',
  'hooks/useAuth.tsx',
  'layouts/MainLayout.tsx',
  'pages/Aprovacoes.tsx',
  'pages/AuthCallback.tsx',
  'pages/Dashboard.tsx',
  'pages/DespesasRecorrentes.tsx',
  'pages/Historico.tsx',
  'pages/Login.tsx',
];

const forbiddenVisibleCopy: Array<[RegExp, string]> = [
  [/\bNao foi possivel\b/, 'Nao foi possivel'],
  [/\bSua sessao\b/, 'Sua sessao'],
  [/\bFaca login\b/, 'Faca login'],
  [/\bautenticacao\b/, 'autenticacao'],
  [/\boperacao\b/, 'operacao'],
  [/\bCodigo de suporte\b/, 'Codigo de suporte'],
  [/\bCorrelacao\b/, 'Correlacao'],
  [/\bDiagnostico\b/, 'Diagnostico'],
  [/\bNova transacao\b/, 'Nova transacao'],
  [/\bCriar transacao\b/, 'Criar transacao'],
  [/\bDescricao\b/, 'Descricao'],
  [/\bMetodo de pagamento\b/, 'Metodo de pagamento'],
  [/\bDia do mes\b/, 'Dia do mes'],
  [/\bSelecionar mes\b/, 'Selecionar mes'],
  [/\bProxima\b/, 'Proxima'],
  [/\bPendencia Administrativa\b/, 'Pendencia Administrativa'],
  [/\bconfirmacao\b/, 'confirmacao'],
  [/\bexclusao\b/, 'exclusao'],
  [/\bnavegacao\b/, 'navegacao'],
  [/\bMes\b/, 'Mes'],
  [/\bInicio\b/, 'Inicio'],
];

describe('visible Portuguese copy', () => {
  it('keeps common user-facing Portuguese copy accented in production frontend sources', () => {
    const occurrences = sourceFiles.flatMap((file) => {
      const content = readFileSync(resolve(__dirname, file), 'utf8');
      return forbiddenVisibleCopy
        .filter(([pattern]) => pattern.test(content))
        .map(([, label]) => `${file}: ${label}`);
    });

    expect(occurrences).toEqual([]);
  });
});

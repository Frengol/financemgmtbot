import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockAuthProvider = vi.fn(({ children }: { children: React.ReactNode }) => <>{children}</>);
const mockTransactionComposerProvider = vi.fn(({ children }: { children: React.ReactNode }) => <>{children}</>);

vi.mock('./hooks/useAuth', () => ({
  AuthProvider: (props: { children: React.ReactNode }) => mockAuthProvider(props),
}));

vi.mock('./hooks/useTransactionComposer', () => ({
  TransactionComposerProvider: (props: { children: React.ReactNode }) => mockTransactionComposerProvider(props),
}));

vi.mock('./layouts/MainLayout', () => ({
  default: () => <div>Main layout</div>,
}));

vi.mock('./pages/Dashboard', () => ({
  default: () => <div>Dashboard page</div>,
}));

vi.mock('./pages/Aprovacoes', () => ({
  default: () => <div>Aprovacoes page</div>,
}));

vi.mock('./pages/Historico', () => ({
  default: () => <div>Historico page</div>,
}));

vi.mock('./pages/Login', () => ({
  default: () => <div>Login page</div>,
}));

vi.mock('./pages/AuthCallback', () => ({
  default: () => <div>Auth callback page</div>,
}));

vi.mock('./components/ProtectedRoute', () => ({
  default: () => <div>Protected route shell</div>,
}));

vi.mock('./components/TransactionModalGate', () => ({
  default: () => <div>Transaction modal gate</div>,
}));

describe('App', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('renders providers and transaction modal', async () => {
    window.history.pushState({}, '', '/login');
    const { default: App } = await import('./App');

    render(<App />);

    expect(mockAuthProvider).toHaveBeenCalled();
    expect(mockTransactionComposerProvider).toHaveBeenCalled();
    expect(await screen.findByText('Transaction modal gate')).toBeInTheDocument();
  });

  it('renders the login route', async () => {
    window.history.pushState({}, '', '/login');
    const { default: App } = await import('./App');

    render(<App />);

    expect(await screen.findByText('Login page')).toBeInTheDocument();
  });

  it('renders the protected shell for admin routes', async () => {
    window.history.pushState({}, '', '/historico');
    const { default: App } = await import('./App');

    render(<App />);

    expect(await screen.findByText('Protected route shell')).toBeInTheDocument();
  });

  it('renders the auth callback route', async () => {
    window.history.pushState({}, '', '/auth/callback#access_token=test&refresh_token=test');
    const { default: App } = await import('./App');

    render(<App />);

    expect(await screen.findByText('Auth callback page')).toBeInTheDocument();
  });
});

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Login from './Login';

const mockSignInWithOtp = vi.fn();
const mockRequestTestMagicLink = vi.fn();
const mockLoadBrowserAdminLoginNotice = vi.fn();
const mockClearBrowserAdminLoginNotice = vi.fn();
const mockUseAuth = vi.fn();

vi.mock('@/features/auth/lib/supabaseBrowserSession', () => ({
  supabase: {
    auth: {
      signInWithOtp: (...args: unknown[]) => mockSignInWithOtp(...args),
    },
  },
}));

vi.mock('@/features/admin/api', () => ({
  localDevBypassEnabled: false,
  requestTestMagicLink: (...args: unknown[]) => mockRequestTestMagicLink(...args),
}));

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock('@/features/auth/lib/browserState', async () => {
  const actual = await vi.importActual<typeof import('@/features/auth/lib/browserState')>('@/features/auth/lib/browserState');
  return {
    ...actual,
    browserAdminAuthTestModeEnabled: () => import.meta.env.VITE_AUTH_TEST_MODE === 'true',
    loadBrowserAdminLoginNotice: (...args: unknown[]) => mockLoadBrowserAdminLoginNotice(...args),
    clearBrowserAdminLoginNotice: (...args: unknown[]) => mockClearBrowserAdminLoginNotice(...args),
  };
});

describe('Login', () => {
  beforeEach(() => {
    mockSignInWithOtp.mockReset();
    mockRequestTestMagicLink.mockReset();
    mockLoadBrowserAdminLoginNotice.mockReset();
    mockClearBrowserAdminLoginNotice.mockReset();
    mockUseAuth.mockReset();
    mockLoadBrowserAdminLoginNotice.mockReturnValue(null);
    mockUseAuth.mockReturnValue({
      authenticated: false,
      loading: false,
      localBypass: false,
    });
    vi.stubEnv('VITE_AUTH_TEST_MODE', 'false');
    window.history.pushState({}, '', '/login');
  });

  it('requests a magic link directly from the Supabase browser client', async () => {
    mockSignInWithOtp.mockResolvedValue({ data: {}, error: null });

    render(<Login />);

    await userEvent.type(screen.getByLabelText('E-mail de Acesso'), 'admin@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'Enviar Magic Link' }));

    await waitFor(() => {
      expect(mockSignInWithOtp).toHaveBeenCalledWith({
        email: 'admin@example.com',
        options: {
          shouldCreateUser: false,
          emailRedirectTo: new URL('auth/callback', new URL(import.meta.env.BASE_URL, window.location.origin)).toString(),
        },
      });
    });
    expect(await screen.findByText('Link mágico enviado!')).toBeInTheDocument();
    expect(mockRequestTestMagicLink).not.toHaveBeenCalled();
  });

  it('uses the loopback auth test endpoint only in auth test mode', async () => {
    vi.stubEnv('VITE_AUTH_TEST_MODE', 'true');
    mockRequestTestMagicLink.mockResolvedValue({ magicLink: { link: 'http://127.0.0.1:8080/__test__/auth/verify?token_hash=1' } });

    render(<Login />);

    await userEvent.type(screen.getByLabelText('E-mail de Acesso'), 'admin@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'Enviar Magic Link' }));

    await waitFor(() => {
      expect(mockRequestTestMagicLink).toHaveBeenCalledWith(
        'admin@example.com',
        new URL('auth/callback', new URL(import.meta.env.BASE_URL, window.location.origin)).toString(),
      );
    });
    expect(mockSignInWithOtp).not.toHaveBeenCalled();
    expect(await screen.findByText('Link mágico enviado!')).toBeInTheDocument();
  });

  it('surfaces rate limiting and masks user enumeration failures', async () => {
    mockSignInWithOtp
      .mockResolvedValueOnce({ data: {}, error: { message: 'For security purposes, you can only request this after 8 seconds.' } })
      .mockResolvedValueOnce({ data: {}, error: { message: 'User not found' } });

    const { rerender } = render(<Login />);

    await userEvent.type(screen.getByLabelText('E-mail de Acesso'), 'admin@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'Enviar Magic Link' }));

    expect(await screen.findByText(/muitos pedidos de login/i)).toBeInTheDocument();

    rerender(<Login />);
    await userEvent.clear(screen.getByLabelText('E-mail de Acesso'));
    await userEvent.type(screen.getByLabelText('E-mail de Acesso'), 'blocked@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'Enviar Magic Link' }));

    expect(await screen.findByText('Link mágico enviado!')).toBeInTheDocument();
  });

  it('shows login notices persisted by the auth flow', () => {
    mockLoadBrowserAdminLoginNotice.mockReturnValue({
      message: 'Seu usuario nao esta autorizado a acessar o painel.',
    });

    render(<Login />);

    expect(screen.getByText(/nao esta autorizado/i)).toBeInTheDocument();
    expect(mockClearBrowserAdminLoginNotice).toHaveBeenCalledTimes(1);
  });

  it('renders the operational auth banners from the query string', () => {
    window.history.pushState({}, '', '/login?reason=auth_unavailable&requestId=req_test_1');

    render(<Login />);

    expect(screen.getByText(/login esta temporariamente indisponivel/i)).toBeInTheDocument();
    expect(screen.getByText(/codigo de suporte: req_test_1/i)).toBeInTheDocument();
  });

  it('surfaces a generic request failure when the Supabase browser client errors unexpectedly', async () => {
    mockSignInWithOtp.mockResolvedValue({ data: {}, error: { message: 'unexpected upstream failure' } });

    render(<Login />);

    await userEvent.type(screen.getByLabelText('E-mail de Acesso'), 'admin@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'Enviar Magic Link' }));

    expect(await screen.findByText(/nao foi possivel enviar o link de acesso agora/i)).toBeInTheDocument();
  });

  it('redirects to the app root when auth is already established', async () => {
    const originalLocation = window.location;
    const replaceSpy = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        ...originalLocation,
        replace: replaceSpy,
      },
    });
    mockUseAuth.mockReturnValue({
      authenticated: true,
      loading: false,
      localBypass: false,
    });

    render(<Login />);

    await waitFor(() => {
      expect(replaceSpy).toHaveBeenCalledWith(
        new URL(import.meta.env.BASE_URL, window.location.origin).toString(),
      );
    });

    Object.defineProperty(window, 'location', {
      configurable: true,
      value: originalLocation,
    });
  });

  it('redirects immediately when local bypass is already active', async () => {
    const originalLocation = window.location;
    const replaceSpy = vi.fn();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        ...originalLocation,
        replace: replaceSpy,
      },
    });
    mockUseAuth.mockReturnValue({
      authenticated: false,
      loading: false,
      localBypass: true,
    });

    render(<Login />);

    await waitFor(() => {
      expect(replaceSpy).toHaveBeenCalledWith(
        new URL(import.meta.env.BASE_URL, window.location.origin).toString(),
      );
    });

    Object.defineProperty(window, 'location', {
      configurable: true,
      value: originalLocation,
    });
  });

  it('keeps the login screen stable while auth hydration is still loading', () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      loading: true,
      localBypass: false,
    });

    render(<Login />);

    expect(screen.getByRole('button', { name: 'Enviar Magic Link' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Finance Copilot' })).toBeInTheDocument();
  });
});

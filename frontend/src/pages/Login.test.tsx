import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Login from './Login';

const mockRequestMagicLink = vi.fn();

vi.mock('@/lib/adminApi', () => ({
  localDevBypassEnabled: false,
  requestMagicLink: (...args: unknown[]) => mockRequestMagicLink(...args),
}));

describe('Login', () => {
  beforeEach(() => {
    mockRequestMagicLink.mockReset();
    window.history.pushState({}, '', '/login');
  });

  it('requests a magic link and renders the success state', async () => {
    mockRequestMagicLink.mockResolvedValue({ message: 'sent' });

    render(<Login />);

    const emailInput = screen.getByLabelText('E-mail de Acesso');
    expect(emailInput).toHaveAttribute('name', 'email');
    expect(emailInput).toHaveAttribute('autocomplete', 'email');
    expect(emailInput).toHaveAttribute('autocapitalize', 'none');
    expect(emailInput).toHaveAttribute('autocorrect', 'off');
    expect(emailInput).toHaveAttribute('placeholder', 'seu e-mail');

    await userEvent.type(emailInput, 'admin@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'Enviar Magic Link' }));

    await waitFor(() => {
      expect(mockRequestMagicLink).toHaveBeenCalledWith(
        'admin@example.com',
        new URL('auth/callback', new URL(import.meta.env.BASE_URL, window.location.origin)).toString(),
      );
    });
    expect(await screen.findByText('Link mágico enviado!')).toBeInTheDocument();
    expect(screen.getByText(/admin@example.com/i)).toBeInTheDocument();
  });

  it('shows the unauthorized reason and backend errors', async () => {
    mockRequestMagicLink.mockRejectedValue(new Error('Muitos pedidos de login em pouco tempo. Aguarde alguns minutos e tente novamente. Codigo de suporte: req_auth_123'));
    window.history.pushState({}, '', '/login?reason=unauthorized');

    render(<Login />);

    expect(screen.getByText(/nao esta autorizado/i)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('E-mail de Acesso'), 'blocked@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'Enviar Magic Link' }));

    expect(await screen.findByText(/Muitos pedidos de login em pouco tempo/i)).toBeInTheDocument();
    expect(screen.getByText(/Codigo de suporte: req_auth_123/i)).toBeInTheDocument();
  });

  it('shows auth unavailable reason with support code from callback fallback', () => {
    window.history.pushState({}, '', '/login?reason=auth_unavailable&requestId=req_auth_123');

    render(<Login />);

    expect(screen.getByText(/login esta temporariamente indisponivel/i)).toBeInTheDocument();
    expect(screen.getByText(/Codigo de suporte: req_auth_123/i)).toBeInTheDocument();
  });

  it('redirects immediately when local development bypass is enabled', async () => {
    const replaceSpy = vi.fn();
    vi.stubGlobal('location', { ...window.location, replace: replaceSpy });
    vi.resetModules();
    vi.doMock('@/lib/adminApi', () => ({
      localDevBypassEnabled: true,
      requestMagicLink: (...args: unknown[]) => mockRequestMagicLink(...args),
    }));

    const { default: LoginWithBypass } = await import('./Login');
    const { container } = render(<LoginWithBypass />);

    expect(container).toBeEmptyDOMElement();
    expect(replaceSpy).toHaveBeenCalledWith(new URL(import.meta.env.BASE_URL, window.location.origin).toString());
  });
});

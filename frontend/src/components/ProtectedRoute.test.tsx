import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ProtectedRoute from './ProtectedRoute';

const mockUseAuth = vi.fn();
const mockIsAllowedAdminEmail = vi.fn();

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock('@/lib/auth', () => ({
  isAllowedAdminEmail: (...args: unknown[]) => mockIsAllowedAdminEmail(...args),
}));

describe('ProtectedRoute', () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
    mockIsAllowedAdminEmail.mockReset();
  });

  function renderProtected() {
    return render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<div>Secure content</div>} />
          </Route>
          <Route path="/login" element={<div>Login screen</div>} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it('shows a loading spinner while auth is loading', () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      user: null,
      loading: true,
      localBypass: false,
      signOut: vi.fn(),
    });
    mockIsAllowedAdminEmail.mockReturnValue(false);

    renderProtected();

    expect(document.querySelector('.animate-spin')).toBeInTheDocument();
  });

  it('renders the protected outlet for authorized users', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: true,
      user: { email: 'admin@example.com' },
      loading: false,
      localBypass: false,
      signOut: vi.fn(),
    });
    mockIsAllowedAdminEmail.mockReturnValue(true);

    renderProtected();

    expect(await screen.findByText('Secure content')).toBeInTheDocument();
  });

  it('renders the protected outlet when local bypass is enabled', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      user: null,
      loading: false,
      localBypass: true,
      signOut: vi.fn(),
    });
    mockIsAllowedAdminEmail.mockReturnValue(false);

    renderProtected();

    expect(await screen.findByText('Secure content')).toBeInTheDocument();
  });

  it('redirects unauthenticated users to the login screen', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      user: null,
      loading: false,
      localBypass: false,
      signOut: vi.fn(),
    });
    mockIsAllowedAdminEmail.mockReturnValue(false);

    renderProtected();

    expect(await screen.findByText('Login screen')).toBeInTheDocument();
  });

  it('redirects unauthorized users and revokes the session', async () => {
    const signOut = vi.fn().mockResolvedValue(undefined);
    mockUseAuth.mockReturnValue({
      authenticated: true,
      user: { email: 'blocked@example.com' },
      loading: false,
      localBypass: false,
      signOut,
    });
    mockIsAllowedAdminEmail.mockReturnValue(false);

    renderProtected();

    await waitFor(() => {
      expect(signOut).toHaveBeenCalled();
    });
    expect(await screen.findByText('Login screen')).toBeInTheDocument();
  });
});

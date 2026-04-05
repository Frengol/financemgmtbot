import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ProtectedRoute from './ProtectedRoute';

const mockUseAuth = vi.fn();

vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => mockUseAuth(),
}));

describe('ProtectedRoute', () => {
  beforeEach(() => {
    mockUseAuth.mockReset();
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
    });

    renderProtected();

    expect(document.querySelector('.animate-spin')).toBeInTheDocument();
  });

  it('renders the protected outlet for authorized users', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: true,
      user: { email: 'admin@example.com' },
      loading: false,
      localBypass: false,
    });

    renderProtected();

    expect(await screen.findByText('Secure content')).toBeInTheDocument();
  });

  it('renders the protected outlet when local bypass is enabled', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      user: null,
      loading: false,
      localBypass: true,
    });

    renderProtected();

    expect(await screen.findByText('Secure content')).toBeInTheDocument();
  });

  it('redirects unauthenticated users to the login screen', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: false,
      user: null,
      loading: false,
      localBypass: false,
    });

    renderProtected();

    expect(await screen.findByText('Login screen')).toBeInTheDocument();
  });

  it('keeps authenticated users inside the app shell even when frontend metadata is incomplete', async () => {
    mockUseAuth.mockReturnValue({
      authenticated: true,
      user: null,
      loading: false,
      localBypass: false,
    });

    renderProtected();

    expect(await screen.findByText('Secure content')).toBeInTheDocument();
  });
});

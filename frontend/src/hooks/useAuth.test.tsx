import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from './useAuth';

const mockGetAuthSession = vi.fn();
const mockLogoutAuthSession = vi.fn();

vi.mock('@/lib/adminApi', () => ({
  getAuthSession: (...args: unknown[]) => mockGetAuthSession(...args),
  logoutAuthSession: (...args: unknown[]) => mockLogoutAuthSession(...args),
  localDevBypassEnabled: false,
}));

function AuthHarness() {
  const { authenticated, user, csrfToken, loading, refreshSession, signOut } = useAuth();

  return (
    <div>
      <div data-testid="loading">{loading ? 'loading' : 'ready'}</div>
      <div data-testid="authenticated">{authenticated ? 'yes' : 'no'}</div>
      <div data-testid="email">{user?.email || ''}</div>
      <div data-testid="csrf">{csrfToken}</div>
      <button type="button" onClick={() => void refreshSession()}>
        Refresh
      </button>
      <button type="button" onClick={() => void signOut()}>
        Sign out
      </button>
    </div>
  );
}

describe('useAuth', () => {
  beforeEach(() => {
    mockGetAuthSession.mockReset();
    mockLogoutAuthSession.mockReset();
    window.history.pushState({}, '', '/#access_token=abc&refresh_token=def');
  });

  it('loads the admin session, strips upstream tokens and refreshes on focus', async () => {
    mockGetAuthSession.mockResolvedValue({
      authenticated: true,
      user: { id: 'user-1', email: 'admin@example.com' },
      csrfToken: 'csrf-token',
    });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('ready');
    });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('yes');
    expect(screen.getByTestId('email')).toHaveTextContent('admin@example.com');
    expect(screen.getByTestId('csrf')).toHaveTextContent('csrf-token');
    expect(window.location.hash).toBe('');

    window.dispatchEvent(new Event('focus'));

    await waitFor(() => {
      expect(mockGetAuthSession).toHaveBeenCalledTimes(2);
    });
  });

  it('falls back to a logged-out state when session lookup fails', async () => {
    mockGetAuthSession.mockRejectedValue(new Error('network'));

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('ready');
    });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    expect(screen.getByTestId('email')).toHaveTextContent('');
    expect(screen.getByTestId('csrf')).toHaveTextContent('');
  });

  it('signs out through the backend and clears the local auth state', async () => {
    mockGetAuthSession.mockResolvedValue({
      authenticated: true,
      user: { id: 'user-1', email: 'admin@example.com' },
      csrfToken: 'csrf-token',
    });
    mockLogoutAuthSession.mockResolvedValue({ loggedOut: true });

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('yes');
    });

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));

    await waitFor(() => {
      expect(mockLogoutAuthSession).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByTestId('authenticated')).toHaveTextContent('no');
    expect(screen.getByTestId('csrf')).toHaveTextContent('');
  });
});

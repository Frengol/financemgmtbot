import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from './useAuth';
import { ApiError } from '@/features/admin/api';
import { registerUseAuthBrowserSessionCases } from './useAuth.browser-session.cases';
import { registerUseAuthEventCases } from './useAuth.events.cases';
import { registerUseAuthValidationCases } from './useAuth.validation.cases';

const mockGetAdminMe = vi.fn();
const mockGetSession = vi.fn();
const mockOnAuthStateChange = vi.fn();
const mockClearBrowserAuthState = vi.fn();
const mockPurgeLegacyBrowserAuthStorage = vi.fn();
const mockSetCachedBrowserAccessToken = vi.fn();
const mockBrowserAdminAuthTestModeEnabled = vi.fn();
const mockLoadBrowserAdminTestSession = vi.fn();
const mockSaveBrowserAdminProfile = vi.fn();
const mockSaveBrowserAdminLoginNotice = vi.fn();
const mockClearBrowserAdminLoginNotice = vi.fn();
const mockDecodeAccessTokenIdentity = vi.fn();

function buildJwtLikeToken(...segments: string[]) {
  return segments.join('.');
}

vi.mock('@/features/admin/api', () => ({
  ApiError: class ApiError extends Error {
    code: string;
    status: number;

    constructor(message: string, { code, status }: { code: string; status: number }) {
      super(message);
      this.name = 'ApiError';
      this.code = code;
      this.status = status;
    }
  },
  getAdminMe: (...args: unknown[]) => mockGetAdminMe(...args),
  localDevBypassEnabled: false,
}));

vi.mock('@/features/auth/lib/supabaseBrowserSession', () => ({
  clearBrowserAuthState: (...args: unknown[]) => mockClearBrowserAuthState(...args),
  purgeLegacyBrowserAuthStorage: (...args: unknown[]) => mockPurgeLegacyBrowserAuthStorage(...args),
  setCachedBrowserAccessToken: (...args: unknown[]) => mockSetCachedBrowserAccessToken(...args),
  supabase: {
    auth: {
      getSession: (...args: unknown[]) => mockGetSession(...args),
      onAuthStateChange: (...args: unknown[]) => mockOnAuthStateChange(...args),
    },
  },
}));

vi.mock('@/features/auth/lib/browserState', async () => {
  const actual = await vi.importActual<typeof import('@/features/auth/lib/browserState')>('@/features/auth/lib/browserState');
  return {
    ...actual,
    browserAdminAuthTestModeEnabled: (...args: unknown[]) => mockBrowserAdminAuthTestModeEnabled(...args),
    loadBrowserAdminTestSession: (...args: unknown[]) => mockLoadBrowserAdminTestSession(...args),
    saveBrowserAdminProfile: (...args: unknown[]) => mockSaveBrowserAdminProfile(...args),
    saveBrowserAdminLoginNotice: (...args: unknown[]) => mockSaveBrowserAdminLoginNotice(...args),
    clearBrowserAdminLoginNotice: (...args: unknown[]) => mockClearBrowserAdminLoginNotice(...args),
    decodeAccessTokenIdentity: (...args: unknown[]) => mockDecodeAccessTokenIdentity(...args),
  };
});

function AuthHarness() {
  const { authenticated, user, loading, refreshSession, signOut } = useAuth();

  return (
    <div>
      <div data-testid="loading">{loading ? 'loading' : 'ready'}</div>
      <div data-testid="authenticated">{authenticated ? 'yes' : 'no'}</div>
      <div data-testid="email">{user?.email || ''}</div>
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
    vi.unstubAllEnvs();
    mockGetAdminMe.mockReset();
    mockGetSession.mockReset();
    mockOnAuthStateChange.mockReset();
    mockClearBrowserAuthState.mockReset();
    mockPurgeLegacyBrowserAuthStorage.mockReset();
    mockSetCachedBrowserAccessToken.mockReset();
    mockBrowserAdminAuthTestModeEnabled.mockReset();
    mockLoadBrowserAdminTestSession.mockReset();
    mockSaveBrowserAdminProfile.mockReset();
    mockSaveBrowserAdminLoginNotice.mockReset();
    mockClearBrowserAdminLoginNotice.mockReset();
    mockDecodeAccessTokenIdentity.mockReset();

    mockBrowserAdminAuthTestModeEnabled.mockReturnValue(false);
    mockLoadBrowserAdminTestSession.mockReturnValue(null);
    mockGetSession.mockResolvedValue({ data: { session: null } });
    mockOnAuthStateChange.mockReturnValue({
      data: {
        subscription: {
          unsubscribe: vi.fn(),
        },
      },
    });
    mockGetAdminMe.mockResolvedValue({
      authenticated: true,
      authorized: true,
      user: {
        id: 'user-1',
        email: 'admin@example.com',
      },
    });
    mockClearBrowserAuthState.mockResolvedValue(undefined);
    mockDecodeAccessTokenIdentity.mockReturnValue(null);
    window.history.pushState({}, '', '/');
  });

  registerUseAuthBrowserSessionCases({
    AuthProvider,
    AuthHarness,
    buildJwtLikeToken,
    mockBrowserAdminAuthTestModeEnabled,
    mockLoadBrowserAdminTestSession,
    mockGetAdminMe,
    mockGetSession,
    mockOnAuthStateChange,
    mockClearBrowserAuthState,
    mockSaveBrowserAdminLoginNotice,
    mockSaveBrowserAdminProfile,
    mockSetCachedBrowserAccessToken,
  });

  registerUseAuthValidationCases({
    ApiError,
    AuthProvider,
    AuthHarness,
    buildJwtLikeToken,
    mockClearBrowserAuthState,
    mockDecodeAccessTokenIdentity,
    mockGetAdminMe,
    mockGetSession,
    mockSaveBrowserAdminLoginNotice,
    mockSaveBrowserAdminProfile,
  });

  registerUseAuthEventCases({
    AuthProvider,
    AuthHarness,
    buildJwtLikeToken,
    mockClearBrowserAuthState,
    mockGetAdminMe,
    mockGetSession,
    mockOnAuthStateChange,
  });

  it('supports local development bypass without touching Supabase or backend auth routes', async () => {
    vi.resetModules();

    const bypassGetSession = vi.fn();
    const bypassOnAuthStateChange = vi.fn().mockReturnValue({
      data: {
        subscription: {
          unsubscribe: vi.fn(),
        },
      },
    });
    const bypassClearBrowserAuthState = vi.fn();
    const bypassPurgeLegacyBrowserAuthStorage = vi.fn();

    vi.doMock('@/features/admin/api', () => ({
      ApiError: class ApiError extends Error {},
      getAdminMe: vi.fn(),
      localDevBypassEnabled: true,
    }));
    vi.doMock('@/features/auth/lib/supabaseBrowserSession', () => ({
      clearBrowserAuthState: (...args: unknown[]) => bypassClearBrowserAuthState(...args),
      purgeLegacyBrowserAuthStorage: (...args: unknown[]) => bypassPurgeLegacyBrowserAuthStorage(...args),
      setCachedBrowserAccessToken: vi.fn(),
      supabase: {
        auth: {
          getSession: (...args: unknown[]) => bypassGetSession(...args),
          onAuthStateChange: (...args: unknown[]) => bypassOnAuthStateChange(...args),
        },
      },
    }));

    const authModule = await import('./useAuth');

    function BypassHarness() {
      const { authenticated, user, loading, signOut } = authModule.useAuth();
      return (
        <div>
          <div data-testid="bypass-loading">{loading ? 'loading' : 'ready'}</div>
          <div data-testid="bypass-authenticated">{authenticated ? 'yes' : 'no'}</div>
          <div data-testid="bypass-email">{user?.email || ''}</div>
          <button type="button" onClick={() => void signOut()}>
            Bypass sign out
          </button>
        </div>
      );
    }

    render(
      <authModule.AuthProvider>
        <BypassHarness />
      </authModule.AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('bypass-loading')).toHaveTextContent('ready');
    });

    expect(screen.getByTestId('bypass-authenticated')).toHaveTextContent('yes');
    expect(screen.getByTestId('bypass-email')).toHaveTextContent('local-dev@localhost');

    await userEvent.click(screen.getByRole('button', { name: 'Bypass sign out' }));

    expect(bypassGetSession).not.toHaveBeenCalled();
    expect(bypassClearBrowserAuthState).not.toHaveBeenCalled();
    expect(bypassPurgeLegacyBrowserAuthStorage).toHaveBeenCalledTimes(1);
  });

  it('throws outside the provider', () => {
    function InvalidHarness() {
      useAuth();
      return null;
    }

    expect(() => render(<InvalidHarness />)).toThrow('useAuth must be used within AuthProvider.');
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('isAllowedAdminEmail', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('allows any e-mail when no allowlist is configured', async () => {
    vi.stubEnv('VITE_ALLOWED_ADMIN_EMAILS', '');
    const { isAllowedAdminEmail } = await import('./auth');

    expect(isAllowedAdminEmail('admin@example.com')).toBe(true);
    expect(isAllowedAdminEmail()).toBe(true);
  });

  it('enforces the configured allowlist in a case-insensitive way', async () => {
    vi.stubEnv('VITE_ALLOWED_ADMIN_EMAILS', 'admin@example.com,finance@example.com');
    const { isAllowedAdminEmail } = await import('./auth');

    expect(isAllowedAdminEmail('ADMIN@example.com')).toBe(true);
    expect(isAllowedAdminEmail('blocked@example.com')).toBe(false);
    expect(isAllowedAdminEmail()).toBe(false);
  });
});

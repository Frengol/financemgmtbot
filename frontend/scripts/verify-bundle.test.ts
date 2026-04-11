// @vitest-environment node

import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { verifyBundleDirectory } from './verify-bundle.mjs';

const createdDirs: string[] = [];
const PUBLIC_SUPABASE_URL = 'https://your-project-ref.supabase.co';

function buildJwtToken(parts: [string, string, string]) {
  return parts.join('.');
}

const PUBLIC_SUPABASE_ANON_KEY = buildJwtToken([
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9',
  'eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIiwicmVmIjoieW91ci1wcm9qZWN0LXJlZiJ9',
  'signatureexample1234567890',
]);

const UNEXPECTED_JWT = buildJwtToken([
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9',
  'eyJyb2xlIjoic2VydmljZV9yb2xlIiwiaXNzIjoiaW50cnVkZXIiLCJyZWYiOiJvdGhlci1wcm9qZWN0In0',
  'unexpectedsignature1234567890',
]);

function createBundleDir(bundleSource: string) {
  const dir = mkdtempSync(join(tmpdir(), 'fm-bundle-'));
  createdDirs.push(dir);
  writeFileSync(join(dir, 'index.html'), '<!doctype html><html><body><script src="/assets/index.js"></script></body></html>', 'utf-8');
  writeFileSync(
    join(dir, 'index.js'),
    `
      const releaseId = '20260411abcd';
      const telemetryUrl = '/api/client-telemetry';
      ${bundleSource}
    `,
    'utf-8',
  );
  return dir;
}

afterEach(() => {
  for (const dir of createdDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe('verifyBundleDirectory', () => {
  it('accepts a bundle that keeps the expected public Supabase config and bearer transport', () => {
    const dir = createBundleDir(`
      const supabaseUrl = '${PUBLIC_SUPABASE_URL}';
      const supabaseAnonKey = '${PUBLIC_SUPABASE_ANON_KEY}';
      const storageKey = 'financemgmtbot-admin-auth-v2';
      const authEmail = 'admin' + '@' + 'example.com';
      supabase.auth.signInWithOtp({ email: authEmail, options: { shouldCreateUser: false } });
      supabase.auth.onAuthStateChange(() => {});
      fetch('/api/admin/me', { headers: { Authorization: 'Bearer abc' } });
    `);

    expect(
      verifyBundleDirectory(dir, {
        supabaseUrl: PUBLIC_SUPABASE_URL,
        supabaseAnonKey: PUBLIC_SUPABASE_ANON_KEY,
      }),
    ).toBe(2);
  });

  it('rejects a bundle that loses bearer token transport', () => {
    const dir = createBundleDir(`
      const supabaseUrl = '${PUBLIC_SUPABASE_URL}';
      const supabaseAnonKey = '${PUBLIC_SUPABASE_ANON_KEY}';
      const storageKey = 'financemgmtbot-admin-auth-v2';
      const authEmail = 'admin' + '@' + 'example.com';
      supabase.auth.signInWithOtp({ email: authEmail, options: { shouldCreateUser: false } });
      supabase.auth.onAuthStateChange(() => {});
      fetch('/api/admin/me');
    `);

    expect(
      () =>
        verifyBundleDirectory(dir, {
          supabaseUrl: PUBLIC_SUPABASE_URL,
          supabaseAnonKey: PUBLIC_SUPABASE_ANON_KEY,
        }),
    ).toThrow(/bearer authorization transport/i);
  });

  it('rejects a bundle that loses the Supabase auth listener and handshake contract', () => {
    const dir = createBundleDir(`
      const supabaseUrl = '${PUBLIC_SUPABASE_URL}';
      const supabaseAnonKey = '${PUBLIC_SUPABASE_ANON_KEY}';
      const storageKey = 'financemgmtbot-admin-auth-v2';
      const authEmail = 'admin' + '@' + 'example.com';
      supabase.auth.signInWithOtp({ email: authEmail, options: { shouldCreateUser: false } });
      fetch('/api/admin/gastos', { headers: { Authorization: 'Bearer abc' } });
    `);

    expect(
      () =>
        verifyBundleDirectory(dir, {
          supabaseUrl: PUBLIC_SUPABASE_URL,
          supabaseAnonKey: PUBLIC_SUPABASE_ANON_KEY,
        }),
    ).toThrow(/Supabase auth state listener/i);
  });

  it('allows the official frontend callback route without tolerating backend relay requests', () => {
    const dir = createBundleDir(`
      const supabaseUrl = '${PUBLIC_SUPABASE_URL}';
      const supabaseAnonKey = '${PUBLIC_SUPABASE_ANON_KEY}';
      const storageKey = 'financemgmtbot-admin-auth-v2';
      const authEmail = 'admin' + '@' + 'example.com';
      supabase.auth.signInWithOtp({ email: authEmail, options: { shouldCreateUser: false } });
      supabase.auth.onAuthStateChange(() => {});
      fetch('/api/admin/me', { headers: { Authorization: 'Bearer abc' } });
      fetch('/api/admin/gastos', { headers: { Authorization: 'Bearer abc' } });
      const callbackRoute = '/auth/callback';
    `);

    expect(
      verifyBundleDirectory(dir, {
        supabaseUrl: PUBLIC_SUPABASE_URL,
        supabaseAnonKey: PUBLIC_SUPABASE_ANON_KEY,
      }),
    ).toBe(2);
  });

  it('rejects a bundle that still issues a backend auth request', () => {
    const dir = createBundleDir(`
      const supabaseUrl = '${PUBLIC_SUPABASE_URL}';
      const supabaseAnonKey = '${PUBLIC_SUPABASE_ANON_KEY}';
      const storageKey = 'financemgmtbot-admin-auth-v2';
      const authEmail = 'admin' + '@' + 'example.com';
      supabase.auth.signInWithOtp({ email: authEmail, options: { shouldCreateUser: false } });
      supabase.auth.onAuthStateChange(() => {});
      fetch('/auth/callback');
      fetch('/api/admin/me', { headers: { Authorization: 'Bearer abc' } });
    `);

    expect(
      () =>
        verifyBundleDirectory(dir, {
          supabaseUrl: PUBLIC_SUPABASE_URL,
          supabaseAnonKey: PUBLIC_SUPABASE_ANON_KEY,
        }),
    ).toThrow(/legacy backend auth request/i);
  });

  it('does not flag the loopback-only auth test endpoint as a published legacy auth path', () => {
    const dir = createBundleDir(`
      const supabaseUrl = '${PUBLIC_SUPABASE_URL}';
      const supabaseAnonKey = '${PUBLIC_SUPABASE_ANON_KEY}';
      const storageKey = 'financemgmtbot-admin-auth-v2';
      const authEmail = 'admin' + '@' + 'example.com';
      supabase.auth.signInWithOtp({ email: authEmail, options: { shouldCreateUser: false } });
      supabase.auth.onAuthStateChange(() => {});
      fetch('/__test__/auth/magic-link', { method: 'POST' });
      fetch('/api/admin/me', { headers: { Authorization: 'Bearer abc' } });
    `);

    expect(
      verifyBundleDirectory(dir, {
        supabaseUrl: PUBLIC_SUPABASE_URL,
        supabaseAnonKey: PUBLIC_SUPABASE_ANON_KEY,
      }),
    ).toBe(2);
  });

  it('rejects a bundle that contains an unexpected JWT', () => {
    const dir = createBundleDir(`
      const supabaseUrl = '${PUBLIC_SUPABASE_URL}';
      const supabaseAnonKey = '${PUBLIC_SUPABASE_ANON_KEY}';
      const storageKey = 'financemgmtbot-admin-auth-v2';
      const leakedToken = '${UNEXPECTED_JWT}';
      const authEmail = 'admin' + '@' + 'example.com';
      supabase.auth.signInWithOtp({ email: authEmail, options: { shouldCreateUser: false } });
      supabase.auth.onAuthStateChange(() => {});
      fetch('/api/admin/me', { headers: { Authorization: 'Bearer abc' } });
    `);

    expect(
      () =>
        verifyBundleDirectory(dir, {
          supabaseUrl: PUBLIC_SUPABASE_URL,
          supabaseAnonKey: PUBLIC_SUPABASE_ANON_KEY,
        }),
    ).toThrow(/unexpected JWT/i);
  });

  it('rejects a bundle that contains backend secret markers', () => {
    const dir = createBundleDir(`
      const supabaseUrl = '${PUBLIC_SUPABASE_URL}';
      const supabaseAnonKey = '${PUBLIC_SUPABASE_ANON_KEY}';
      const storageKey = 'financemgmtbot-admin-auth-v2';
      const leakedSecret = 'service_role';
      const authEmail = 'admin' + '@' + 'example.com';
      supabase.auth.signInWithOtp({ email: authEmail, options: { shouldCreateUser: false } });
      supabase.auth.onAuthStateChange(() => {});
      fetch('/api/admin/me', { headers: { Authorization: 'Bearer abc' } });
    `);

    expect(
      () =>
        verifyBundleDirectory(dir, {
          supabaseUrl: PUBLIC_SUPABASE_URL,
          supabaseAnonKey: PUBLIC_SUPABASE_ANON_KEY,
        }),
    ).toThrow(/backend Supabase service key literal/i);
  });

  it('rejects a bundle that contains an unexpected email address', () => {
    const dir = createBundleDir(`
      const supabaseUrl = '${PUBLIC_SUPABASE_URL}';
      const supabaseAnonKey = '${PUBLIC_SUPABASE_ANON_KEY}';
      const storageKey = 'financemgmtbot-admin-auth-v2';
      const leakedEmail = 'operator@example.com';
      const authEmail = 'admin' + '@' + 'example.com';
      supabase.auth.signInWithOtp({ email: authEmail, options: { shouldCreateUser: false } });
      supabase.auth.onAuthStateChange(() => {});
      fetch('/api/admin/me', { headers: { Authorization: 'Bearer abc' } });
    `);

    expect(
      () =>
        verifyBundleDirectory(dir, {
          supabaseUrl: PUBLIC_SUPABASE_URL,
          supabaseAnonKey: PUBLIC_SUPABASE_ANON_KEY,
        }),
    ).toThrow(/unexpected email/i);
  });

  it('rejects a bundle that still ships the legacy auth session path', () => {
    const dir = createBundleDir(`
      const supabaseUrl = '${PUBLIC_SUPABASE_URL}';
      const supabaseAnonKey = '${PUBLIC_SUPABASE_ANON_KEY}';
      const storageKey = 'financemgmtbot-admin-auth-v2';
      const authEmail = 'admin' + '@' + 'example.com';
      supabase.auth.signInWithOtp({ email: authEmail, options: { shouldCreateUser: false } });
      supabase.auth.onAuthStateChange(() => {});
      fetch('/auth/session');
      fetch('/api/admin/me', { headers: { Authorization: 'Bearer abc' } });
    `);

    expect(
      () =>
        verifyBundleDirectory(dir, {
          supabaseUrl: PUBLIC_SUPABASE_URL,
          supabaseAnonKey: PUBLIC_SUPABASE_ANON_KEY,
        }),
    ).toThrow(/legacy auth session path/i);
  });

  it('rejects a bundle that still ships the legacy auth logout path', () => {
    const dir = createBundleDir(`
      const supabaseUrl = '${PUBLIC_SUPABASE_URL}';
      const supabaseAnonKey = '${PUBLIC_SUPABASE_ANON_KEY}';
      const storageKey = 'financemgmtbot-admin-auth-v2';
      const authEmail = 'admin' + '@' + 'example.com';
      supabase.auth.signInWithOtp({ email: authEmail, options: { shouldCreateUser: false } });
      supabase.auth.onAuthStateChange(() => {});
      fetch('/auth/logout', { method: 'POST' });
      fetch('/api/admin/me', { headers: { Authorization: 'Bearer abc' } });
    `);

    expect(
      () =>
        verifyBundleDirectory(dir, {
          supabaseUrl: PUBLIC_SUPABASE_URL,
          supabaseAnonKey: PUBLIC_SUPABASE_ANON_KEY,
        }),
    ).toThrow(/legacy logout path/i);
  });
});

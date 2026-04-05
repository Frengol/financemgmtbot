// @vitest-environment node

import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { verifyBundleDirectory } from './verify-bundle.mjs';

const createdDirs: string[] = [];

function createBundleDir(bundleSource: string) {
  const dir = mkdtempSync(join(tmpdir(), 'fm-bundle-'));
  createdDirs.push(dir);
  writeFileSync(join(dir, 'index.html'), '<!doctype html><html><body><script src="/assets/index.js"></script></body></html>', 'utf-8');
  writeFileSync(join(dir, 'index.js'), bundleSource, 'utf-8');
  return dir;
}

afterEach(() => {
  for (const dir of createdDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe('verifyBundleDirectory', () => {
  it('accepts a bundle that keeps Supabase browser auth and bearer transport', () => {
    const dir = createBundleDir(`
      const storageKey = 'financemgmtbot-admin-auth';
      supabase.auth.setSession({ access_token: 'token', refresh_token: 'refresh' });
      fetch('/api/admin/gastos', { headers: { Authorization: 'Bearer abc' } });
    `);

    expect(verifyBundleDirectory(dir)).toBe(2);
  });

  it('rejects a bundle that loses bearer token transport', () => {
    const dir = createBundleDir(`
      const storageKey = 'financemgmtbot-admin-auth';
      supabase.auth.setSession({ access_token: 'token', refresh_token: 'refresh' });
      fetch('/api/admin/gastos');
    `);

    expect(() => verifyBundleDirectory(dir)).toThrow(/bearer authorization transport/i);
  });

  it('rejects a bundle that loses Supabase browser session bootstrap', () => {
    const dir = createBundleDir(`
      fetch('/api/admin/gastos', { headers: { Authorization: 'Bearer abc' } });
    `);

    expect(() => verifyBundleDirectory(dir)).toThrow(/Supabase browser session storage key/i);
  });

  it('does not fail only because legacy compatibility strings still exist in the bundle', () => {
    const dir = createBundleDir(`
      const storageKey = 'financemgmtbot-admin-auth';
      supabase.auth.setSession({ access_token: 'token', refresh_token: 'refresh' });
      fetch('/api/admin/gastos', { credentials: 'include', headers: { 'X-CSRF-Token': 'csrf' } });
      fetch('/api/admin/gastos', { headers: { Authorization: 'Bearer abc' } });
    `);

    expect(verifyBundleDirectory(dir)).toBe(2);
  });
});

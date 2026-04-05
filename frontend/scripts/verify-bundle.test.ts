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
  it('accepts a bundle that keeps cookie auth and CSRF without legacy browser auth', () => {
    const dir = createBundleDir(`
      fetch('/api/admin/gastos', { credentials: 'include', headers: { 'X-CSRF-Token': 'csrf' } });
    `);

    expect(verifyBundleDirectory(dir)).toBe(2);
  });

  it('rejects a bundle that reintroduces Authorization headers', () => {
    const dir = createBundleDir(`
      fetch('/api/admin/gastos', { credentials: 'include', headers: { Authorization: 'Bearer abc', 'X-CSRF-Token': 'csrf' } });
    `);

    expect(() => verifyBundleDirectory(dir)).toThrow(/legacy Authorization header usage/i);
  });

  it('rejects a bundle that loses cookie credentials', () => {
    const dir = createBundleDir(`
      fetch('/api/admin/gastos', { headers: { 'X-CSRF-Token': 'csrf' } });
    `);

    expect(() => verifyBundleDirectory(dir)).toThrow(/cookie-based credentials enabled/i);
  });

  it('rejects a bundle that bootstraps a Supabase browser client again', () => {
    const dir = createBundleDir(`
      createClient('https://your-project-ref.supabase.co', 'anon-key');
      fetch('/api/admin/gastos', { credentials: 'include', headers: { 'X-CSRF-Token': 'csrf' } });
    `);

    expect(() => verifyBundleDirectory(dir)).toThrow(/Supabase client bootstrap/i);
  });
});

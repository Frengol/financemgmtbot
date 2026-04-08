// @vitest-environment node

import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { copyPagesFallbackFile, verifyPagesFallbackFile } from './pages-fallback.mjs';

const createdDirs: string[] = [];

function createDistFixture(indexHtml: string) {
  const dir = mkdtempSync(join(tmpdir(), 'fm-pages-fallback-'));
  createdDirs.push(dir);
  mkdirSync(join(dir, 'assets'), { recursive: true });
  writeFileSync(join(dir, 'index.html'), indexHtml, 'utf-8');
  writeFileSync(join(dir, 'assets', 'index.js'), 'console.log("asset ok");', 'utf-8');
  return dir;
}

afterEach(() => {
  for (const dir of createdDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe('pages fallback build helpers', () => {
  it('copies index.html to 404.html after the production build', () => {
    const distDir = createDistFixture(`<!doctype html>
<html lang="pt-br">
  <body>
    <div id="root"></div>
    <script type="module" src="/financemgmtbot/assets/index.js"></script>
  </body>
</html>`);

    const fallbackPath = copyPagesFallbackFile(distDir);

    expect(readFileSync(fallbackPath, 'utf-8')).toBe(
      readFileSync(join(distDir, 'index.html'), 'utf-8'),
    );
  });

  it('verifies that 404.html is a functional SPA fallback for Pages', () => {
    const distDir = createDistFixture(`<!doctype html>
<html lang="pt-br">
  <body>
    <div id="root"></div>
    <script type="module" src="/financemgmtbot/assets/index.js"></script>
  </body>
</html>`);

    copyPagesFallbackFile(distDir);

    expect(verifyPagesFallbackFile(distDir)).toEqual({
      indexPath: join(distDir, 'index.html'),
      fallbackPath: join(distDir, '404.html'),
    });
  });

  it('rejects a fallback file that diverges from index.html', () => {
    const distDir = createDistFixture(`<!doctype html>
<html lang="pt-br">
  <body>
    <div id="root"></div>
    <script type="module" src="/financemgmtbot/assets/index.js"></script>
  </body>
</html>`);

    writeFileSync(join(distDir, '404.html'), '<html><body>broken fallback</body></html>', 'utf-8');

    expect(() => verifyPagesFallbackFile(distDir)).toThrow(/must match index\.html/i);
  });
});

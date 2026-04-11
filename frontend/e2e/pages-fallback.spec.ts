import { execFileSync } from 'node:child_process';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { existsSync, readFileSync } from 'node:fs';
import { extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';

const frontendDir = resolve(fileURLToPath(new URL('..', import.meta.url)));
const distDir = resolve(frontendDir, 'dist');
const publicSupabaseUrl = 'https://your-project-ref.supabase.co';
const publicSupabaseAnonKey = 'public-anon-key';

function ensureBuiltDist() {
  if (existsSync(join(distDir, 'index.html')) && existsSync(join(distDir, '404.html'))) {
    return;
  }

  execFileSync('npm', ['run', 'build'], {
    cwd: frontendDir,
    stdio: 'inherit',
    env: {
      ...process.env,
      VITE_API_BASE_URL: 'https://api.example.com',
      VITE_SUPABASE_URL: publicSupabaseUrl,
      VITE_SUPABASE_ANON_KEY: publicSupabaseAnonKey,
      VITE_APP_RELEASE: 'pages-fallback-test',
    },
  });
}

function contentTypeFor(filePath: string) {
  switch (extname(filePath)) {
    case '.html':
      return 'text/html; charset=utf-8';
    case '.js':
      return 'application/javascript; charset=utf-8';
    case '.css':
      return 'text/css; charset=utf-8';
    case '.json':
      return 'application/json; charset=utf-8';
    case '.svg':
      return 'image/svg+xml';
    case '.ico':
      return 'image/x-icon';
    default:
      return 'application/octet-stream';
  }
}

function resolvePagesFilePath(requestPath: string) {
  const normalizedPath = normalize(requestPath.replace(/^\/+/, ''));
  const basePath = 'financemgmtbot/';
  if (normalizedPath === 'financemgmtbot' || normalizedPath === 'financemgmtbot/') {
    return join(distDir, 'index.html');
  }

  if (!normalizedPath.startsWith(basePath)) {
    return null;
  }

  const relativePath = normalizedPath.slice(basePath.length);
  if (!relativePath || relativePath.endsWith('/')) {
    return join(distDir, 'index.html');
  }

  return join(distDir, relativePath);
}

async function startPagesLikeServer() {
  ensureBuiltDist();

  const fallbackHtml = readFileSync(join(distDir, '404.html'));

  const server = createServer((req: IncomingMessage, res: ServerResponse) => {
    const requestUrl = new URL(req.url || '/', 'http://127.0.0.1');
    const filePath = resolvePagesFilePath(requestUrl.pathname);

    if (filePath && existsSync(filePath)) {
      const body = readFileSync(filePath);
      res.statusCode = 200;
      res.setHeader('Content-Type', contentTypeFor(filePath));
      res.end(body);
      return;
    }

    res.statusCode = 404;
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.end(fallbackHtml);
  });

  await new Promise<void>((resolvePromise) => server.listen(0, '127.0.0.1', () => resolvePromise()));
  const address = server.address();
  if (!address || typeof address === 'string') {
    throw new Error('Could not determine the pages fallback test server port.');
  }

  return {
    server,
    baseUrl: `http://127.0.0.1:${address.port}`,
  };
}

test('loads the app shell for the Pages auth callback deep link instead of the host 404 page', async ({ page }) => {
  const { server, baseUrl } = await startPagesLikeServer();

  try {
    await page.route(`${publicSupabaseUrl}/**`, async (route) => {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({
          error: 'access_denied',
          error_description: 'Email link is invalid or has expired',
        }),
      });
    });

    const response = await page.goto(`${baseUrl}/financemgmtbot/auth/callback?code=fake-code`);
    expect(response?.status()).toBe(404);

    await expect(page.getByRole('heading', { name: 'Finance Copilot' })).toBeVisible();
    await expect(page.getByText(/nao foi possivel concluir o login com este link/i)).toBeVisible();
    await expect(page.getByText('File not found')).toHaveCount(0);
  } finally {
    await new Promise<void>((resolvePromise, rejectPromise) => {
      server.close((error) => {
        if (error) {
          rejectPromise(error);
          return;
        }
        resolvePromise();
      });
    });
  }
});

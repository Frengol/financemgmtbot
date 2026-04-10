import { expect, test, type APIRequestContext } from '@playwright/test';

const backendBaseUrl = process.env.E2E_API_BASE_URL || 'http://127.0.0.1:8080';
const frontendBaseUrl = process.env.E2E_FRONTEND_BASE_URL || `http://127.0.0.1:${process.env.E2E_FRONTEND_PORT || '4173'}`;
const frontendBaseUrlPattern = frontendBaseUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

test.describe.configure({ mode: 'serial' });

function appRootPattern() {
  return new RegExp(`${frontendBaseUrlPattern}/?$`);
}

async function seedTransactions(request: APIRequestContext) {
  const response = await request.post(`${backendBaseUrl}/__test__/auth/transactions`, {
    data: {
      transactions: [
        {
          id: 'tx-e2e-1',
          data: '2026-04-04',
          natureza: 'Essencial',
          categoria: 'Mercado',
          descricao: 'Mercado Playwright',
          valor: 88.75,
          conta: 'Nubank',
          metodo_pagamento: 'Pix',
        },
      ],
    },
  });

  expect(response.ok()).toBeTruthy();
}

async function waitForMagicLink(request: APIRequestContext, email: string) {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const response = await request.get(`${backendBaseUrl}/__test__/auth/magic-link?email=${encodeURIComponent(email)}`);
    if (response.ok()) {
      const payload = await response.json();
      const link = payload.magicLink?.link as string | undefined;
      if (link) {
        return link;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }

  throw new Error(`Timed out waiting for magic link for ${email}.`);
}
test('requests a magic link, completes the callback and loads seeded transactions', async ({ page, request, browserName }) => {
  const email = `admin+${browserName}@example.com`;
  await seedTransactions(request);
  const backendAuthCalls: string[] = [];

  await page.route(`${backendBaseUrl}/auth/**`, async (route) => {
    backendAuthCalls.push(new URL(route.request().url()).pathname);
    await route.continue();
  });

  await page.goto('/login');

  await page.getByLabel('E-mail de Acesso').fill(email);
  await page.getByRole('button', { name: 'Enviar Magic Link' }).click();

  await expect(page.getByText('Link mágico enviado!')).toBeVisible();

  const magicLink = await waitForMagicLink(request, email);

  await page.goto(magicLink);

  await expect.poll(async () => {
    try {
      return await page.evaluate(() => window.localStorage.getItem('financemgmtbot-admin-auth-test-session-v2'));
    } catch {
      return null;
    }
  }).not.toBeNull();
  await expect(page).toHaveURL(appRootPattern());
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  await page.goto('/historico');
  await expect(page.getByText('Mercado Playwright')).toBeVisible();
  expect(backendAuthCalls).not.toContain('/auth/session');
  expect(backendAuthCalls).not.toContain('/auth/callback');
});

test('shows an explicit error for an expired or invalid callback link', async ({ page }) => {
  await page.goto('/auth/callback#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired');

  await expect(page.getByText(/link de acesso invalido ou expirado/i)).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`${frontendBaseUrlPattern}/auth/callback`));
});

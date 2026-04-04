import { expect, test, type Page, type Route } from '@playwright/test';

type TransactionRecord = {
  id: string;
  data: string;
  natureza: 'Essencial' | 'Lazer' | 'Receita' | 'Outros';
  categoria: string;
  descricao: string;
  valor: number;
  conta: string;
  metodo_pagamento: string;
};

type PendingItem = {
  id: string;
  kind: string;
  created_at: string;
  expires_at: string;
  preview: {
    summary: string;
    metodo_pagamento?: string;
    conta?: string;
    itens?: string[];
    itens_count?: number;
    total_estimado?: number;
    records_count?: number;
  };
};

type MockState = {
  authenticated: boolean;
  magicLinkRequests: Array<{ email: string; redirectTo: string }>;
  signOutCalls: number;
  transactions: TransactionRecord[];
  pendingItems: PendingItem[];
};

function jsonResponse(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function installApiMocks(page: Page, stateOverrides: Partial<MockState> = {}) {
  const state: MockState = {
    authenticated: true,
    magicLinkRequests: [],
    signOutCalls: 0,
    transactions: [
      {
        id: 'tx-1',
        data: '2026-04-02',
        natureza: 'Essencial',
        categoria: 'Mercado',
        descricao: 'Compras do mercado',
        valor: 120,
        conta: 'Nubank',
        metodo_pagamento: 'Pix',
      },
      {
        id: 'tx-2',
        data: '2026-04-03',
        natureza: 'Lazer',
        categoria: 'Diversão',
        descricao: 'Cinema',
        valor: 45,
        conta: 'Nubank',
        metodo_pagamento: 'Pix',
      },
    ],
    pendingItems: [
      {
        id: 'P-1',
        kind: 'receipt_batch',
        created_at: '2026-04-03T10:00:00Z',
        expires_at: '2026-04-04T10:00:00Z',
        preview: {
          summary: 'Cupom pendente',
          metodo_pagamento: 'Pix',
          conta: 'Nubank',
          itens: ['Arroz', 'Feijao'],
          itens_count: 2,
          total_estimado: 20,
        },
      },
      {
        id: 'P-2',
        kind: 'delete_confirmation',
        created_at: '2026-04-03T11:00:00Z',
        expires_at: '2026-04-04T11:00:00Z',
        preview: {
          summary: 'Exclusão pendente',
          records_count: 2,
        },
      },
    ],
    ...stateOverrides,
  };

  await page.route('**/auth/session', async (route) => {
    if (!state.authenticated) {
      return jsonResponse(route, { status: 'ok', authenticated: false });
    }

    return jsonResponse(route, {
      status: 'ok',
      authenticated: true,
      csrfToken: 'csrf-token',
      user: {
        id: 'user-1',
        email: 'admin@example.com',
      },
      expiresAt: '2099-04-03T12:00:00Z',
    });
  });

  await page.route('**/auth/magic-link', async (route) => {
    const payload = route.request().postDataJSON() as { email: string; redirectTo: string };
    state.magicLinkRequests.push(payload);
    return jsonResponse(route, { status: 'ok', message: 'If the e-mail is authorized, a magic link will be sent shortly.' });
  });

  await page.route('**/auth/logout', async (route) => {
    state.authenticated = false;
    state.signOutCalls += 1;
    return jsonResponse(route, { status: 'ok', loggedOut: true });
  });

  await page.route('**/api/admin/gastos?*', async (route) => {
    return jsonResponse(route, { status: 'ok', transactions: state.transactions });
  });

  await page.route('**/api/admin/gastos', async (route) => {
    if (route.request().method() === 'GET') {
      return jsonResponse(route, { status: 'ok', transactions: state.transactions });
    }

    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON() as Omit<TransactionRecord, 'id'>;
      const transaction = { id: `tx-${state.transactions.length + 1}`, ...payload };
      state.transactions.unshift(transaction);
      return jsonResponse(route, { status: 'ok', transaction }, 201);
    }

    return route.fallback();
  });

  await page.route('**/api/admin/gastos/*', async (route) => {
    const url = new URL(route.request().url());
    const transactionId = url.pathname.split('/').pop() as string;

    if (route.request().method() === 'DELETE') {
      state.transactions = state.transactions.filter((item) => item.id !== transactionId);
      return jsonResponse(route, { status: 'ok', id: transactionId });
    }

    if (route.request().method() === 'PATCH') {
      const payload = route.request().postDataJSON() as Omit<TransactionRecord, 'id'>;
      state.transactions = state.transactions.map((item) => (
        item.id === transactionId ? { id: transactionId, ...payload } : item
      ));
      return jsonResponse(route, { status: 'ok', transaction: { id: transactionId, ...payload } });
    }

    return route.fallback();
  });

  await page.route('**/api/admin/cache-aprovacao', async (route) => {
    return jsonResponse(route, { status: 'ok', items: state.pendingItems });
  });

  await page.route('**/api/admin/cache-aprovacao/*/approve', async (route) => {
    const url = new URL(route.request().url());
    const id = url.pathname.split('/').slice(-2)[0];
    state.pendingItems = state.pendingItems.filter((item) => item.id !== id);
    return jsonResponse(route, { status: 'ok', id });
  });

  await page.route('**/api/admin/cache-aprovacao/*/reject', async (route) => {
    const url = new URL(route.request().url());
    const id = url.pathname.split('/').slice(-2)[0];
    state.pendingItems = state.pendingItems.filter((item) => item.id !== id);
    return jsonResponse(route, { status: 'ok', id });
  });

  return state;
}

test('redirects unauthenticated users to login and requests a magic link', async ({ page }) => {
  const state = await installApiMocks(page, { authenticated: false });

  await page.goto('/');

  await expect(page.getByRole('button', { name: 'Enviar Magic Link' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Finance Copilot' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Dashboard' })).not.toBeVisible();
  await page.getByLabel('E-mail de Acesso').fill('admin@example.com');
  await page.getByRole('button', { name: 'Enviar Magic Link' }).click();

  await expect(page.getByText('Link mágico enviado!')).toBeVisible();
  expect(state.magicLinkRequests).toHaveLength(1);
  expect(state.magicLinkRequests[0]?.email).toBe('admin@example.com');
});

test('loads the dashboard metrics and supports the mobile navigation drawer', async ({ page }) => {
  await installApiMocks(page);
  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto('/');
  const mobileDrawer = page.getByRole('dialog', { name: 'Menu de navegacao' });

  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  await expect(page.getByText('R$ 165,00')).toBeVisible();

  await page.getByRole('button', { name: 'Abrir menu de navegacao' }).click();
  await expect(mobileDrawer).toHaveClass(/translate-x-0/);
  await page.getByRole('button', { name: 'Fechar menu de navegacao' }).click();
  await expect(mobileDrawer).toHaveClass(/-translate-x-full/);
});

test('lists history records, opens edit mode and deletes a transaction', async ({ page }) => {
  await installApiMocks(page);

  page.on('dialog', (dialog) => dialog.accept());

  await page.goto('/historico');

  await expect(page.getByText('Compras do mercado')).toBeVisible();
  await page.getByTitle('Editar').first().click();
  await expect(page.getByRole('heading', { name: 'Editar transacao' })).toBeVisible();
  await page.getByRole('button', { name: 'Cancelar' }).click();

  await page.getByTitle('Excluir').first().click();
  await expect(page.getByText('Compras do mercado')).not.toBeVisible();
});

test('approves and rejects pending items through the approvals queue', async ({ page }) => {
  await installApiMocks(page);

  await page.goto('/aprovacoes');

  await expect(page.getByText('Cupom pendente')).toBeVisible();
  await expect(page.getByText('Exclusão pendente')).toBeVisible();

  await page.getByRole('button', { name: 'Aprovar' }).first().click();
  await expect(page.getByText('Arroz')).not.toBeVisible();

  const deleteCard = page.locator('div.bg-white.border', { hasText: 'Exclusão pendente' });
  await deleteCard.getByRole('button').last().click();
  await expect(page.getByText('Exclusão pendente')).not.toBeVisible();
  await expect(page.getByText('A caixa de aprovações está vazia. Tudo atualizado!')).toBeVisible();
});

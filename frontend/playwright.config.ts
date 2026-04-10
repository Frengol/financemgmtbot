import { defineConfig, devices } from '@playwright/test';

const e2eBackendPort = Number(process.env.E2E_BACKEND_PORT || '8080');
const e2eFrontendPort = Number(process.env.E2E_FRONTEND_PORT || '4173');
const e2eBackendBaseUrl = `http://127.0.0.1:${e2eBackendPort}`;
const e2eFrontendBaseUrl = `http://127.0.0.1:${e2eFrontendPort}`;
const reuseExistingServer = !process.env.CI && process.env.E2E_FORCE_FRESH_SERVERS !== 'true';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 2,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: e2eFrontendBaseUrl,
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'python main.py',
      cwd: '..',
      env: {
        ...process.env,
        PORT: String(e2eBackendPort),
        AUTH_TEST_MODE: 'true',
        TELEGRAM_BOT_TOKEN: 'test-telegram-token',
        TELEGRAM_SECRET_TOKEN: 'test-telegram-secret',
        SUPABASE_URL: 'https://example.supabase.co',
        SUPABASE_KEY: 'test-supabase-key',
        DEEPSEEK_API_KEY: 'test-deepseek-key',
        GROQ_API_KEY: 'test-groq-key',
        GEMINI_API_KEY: 'test-gemini-key',
        SUPABASE_ADMIN_EMAILS: 'admin@example.com,admin+chromium@example.com,admin+firefox@example.com',
        FRONTEND_ALLOWED_ORIGINS: `${e2eFrontendBaseUrl},http://localhost:${e2eFrontendPort}`,
        FRONTEND_PUBLIC_URL: `${e2eFrontendBaseUrl}/`,
        PYTHONUNBUFFERED: '1',
      },
      port: e2eBackendPort,
      reuseExistingServer,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${e2eFrontendPort}`,
      env: {
        ...process.env,
        VITE_API_BASE_URL: e2eBackendBaseUrl,
        VITE_SUPABASE_URL: 'https://your-project-ref.supabase.co',
        VITE_SUPABASE_ANON_KEY: 'public-anon-key',
        VITE_ALLOWED_ADMIN_EMAILS: 'admin@example.com,admin+chromium@example.com,admin+firefox@example.com',
        VITE_AUTH_TEST_MODE: 'true',
        VITE_LOCAL_DEV_BYPASS_AUTH: 'false',
      },
      port: e2eFrontendPort,
      reuseExistingServer,
      timeout: 120_000,
    },
  ],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
  ],
});

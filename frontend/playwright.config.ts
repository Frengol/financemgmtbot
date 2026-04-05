import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'python main.py',
      cwd: '..',
      env: {
        ...process.env,
        PORT: '8080',
        AUTH_TEST_MODE: 'true',
        TELEGRAM_BOT_TOKEN: 'test-telegram-token',
        TELEGRAM_SECRET_TOKEN: 'test-telegram-secret',
        SUPABASE_URL: 'https://example.supabase.co',
        SUPABASE_KEY: 'test-supabase-key',
        DEEPSEEK_API_KEY: 'test-deepseek-key',
        GROQ_API_KEY: 'test-groq-key',
        GEMINI_API_KEY: 'test-gemini-key',
        SUPABASE_ADMIN_EMAILS: 'admin@example.com,admin+chromium@example.com,admin+firefox@example.com',
        FRONTEND_ALLOWED_ORIGINS: 'http://127.0.0.1:4173,http://localhost:4173',
        FRONTEND_PUBLIC_URL: 'http://127.0.0.1:4173/',
        AUTH_CALLBACK_PUBLIC_URL: 'http://127.0.0.1:8080/auth/callback',
        PYTHONUNBUFFERED: '1',
      },
      port: 8080,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4173',
      env: {
        ...process.env,
        VITE_API_BASE_URL: 'http://127.0.0.1:8080',
        VITE_LOCAL_DEV_BYPASS_AUTH: 'false',
      },
      port: 4173,
      reuseExistingServer: !process.env.CI,
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

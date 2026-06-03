import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const devProxyTarget = process.env.VITE_DEV_PROXY_TARGET || process.env.E2E_API_BASE_URL || 'http://127.0.0.1:8080'

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: mode === 'production' ? '/financemgmtbot/' : '/',
  server: {
    proxy: {
      '/api': devProxyTarget,
      '/__test__': devProxyTarget,
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined;
          }

          if (id.includes('@tremor/react')) {
            return 'tremor';
          }

          if (id.includes('recharts')) {
            return 'recharts-vendor';
          }

          if (id.includes('@tanstack/react-table')) {
            return 'table';
          }

          if (id.includes('react-router-dom') || id.includes('/react/') || id.includes('react-dom') || id.includes('scheduler')) {
            return 'react-vendor';
          }

          return undefined;
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.test.{ts,tsx}', 'scripts/**/*.test.{ts,js,mjs}'],
    exclude: ['node_modules/**', 'e2e/**', 'playwright.config.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,tsx}'],
      thresholds: {
        statements: 90,
        branches: 90,
        functions: 90,
        lines: 90,
      },
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/test/**',
        'src/vite-env.d.ts',
        'src/main.tsx',
      ],
    },
  },
}))

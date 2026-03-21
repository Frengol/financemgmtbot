import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: mode === 'production' ? '/financemgmtbot/' : '/',
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8080',
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

          if (id.includes('@supabase') || id.includes('cross-fetch') || id.includes('ws')) {
            return 'supabase';
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
  },
}))

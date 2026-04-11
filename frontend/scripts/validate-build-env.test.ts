// @vitest-environment node

import { describe, expect, it } from 'vitest';

import { validateBuildEnv } from './validate-build-env.mjs';

describe('validateBuildEnv', () => {
  it('accepts the required public frontend variables', () => {
    expect(validateBuildEnv({
      VITE_API_BASE_URL: 'https://api.example.com/',
      VITE_SUPABASE_URL: 'https://your-project-ref.supabase.co/',
      VITE_SUPABASE_ANON_KEY: 'public-anon-key',
      VITE_APP_RELEASE: '20260411abcd',
    })).toEqual({
      apiBaseUrl: 'https://api.example.com',
      supabaseUrl: 'https://your-project-ref.supabase.co',
      supabaseAnonKey: 'public-anon-key',
      appRelease: '20260411abcd',
    });
  });

  it('rejects missing required frontend variables with deployment guidance', () => {
    expect(() => validateBuildEnv({
      VITE_API_BASE_URL: '',
      VITE_SUPABASE_URL: 'https://your-project-ref.supabase.co',
      VITE_SUPABASE_ANON_KEY: 'public-anon-key',
      VITE_APP_RELEASE: '20260411abcd',
    })).toThrow(/VITE_API_BASE_URL/i);
    expect(() => validateBuildEnv({
      VITE_API_BASE_URL: 'https://api.example.com',
      VITE_SUPABASE_URL: '',
      VITE_SUPABASE_ANON_KEY: 'public-anon-key',
      VITE_APP_RELEASE: '20260411abcd',
    })).toThrow(/VITE_SUPABASE_URL/i);
    expect(() => validateBuildEnv({
      VITE_API_BASE_URL: 'https://api.example.com',
      VITE_SUPABASE_URL: 'https://your-project-ref.supabase.co',
      VITE_SUPABASE_ANON_KEY: '',
      VITE_APP_RELEASE: '20260411abcd',
    })).toThrow(/VITE_SUPABASE_ANON_KEY/i);
    expect(() => validateBuildEnv({
      VITE_API_BASE_URL: 'https://api.example.com',
      VITE_SUPABASE_URL: 'https://your-project-ref.supabase.co',
      VITE_SUPABASE_ANON_KEY: 'public-anon-key',
      VITE_APP_RELEASE: '',
    })).toThrow(/VITE_APP_RELEASE/i);
  });

  it('rejects non-http URLs', () => {
    expect(() => validateBuildEnv({
      VITE_API_BASE_URL: 'ftp://api.example.com',
      VITE_SUPABASE_URL: 'https://your-project-ref.supabase.co',
      VITE_SUPABASE_ANON_KEY: 'public-anon-key',
      VITE_APP_RELEASE: '20260411abcd',
    })).toThrow(/VITE_API_BASE_URL must use http or https/i);
    expect(() => validateBuildEnv({
      VITE_API_BASE_URL: 'https://api.example.com',
      VITE_SUPABASE_URL: 'ftp://your-project-ref.supabase.co',
      VITE_SUPABASE_ANON_KEY: 'public-anon-key',
      VITE_APP_RELEASE: '20260411abcd',
    })).toThrow(/VITE_SUPABASE_URL must use http or https/i);
  });
});

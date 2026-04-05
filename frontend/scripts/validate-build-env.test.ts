// @vitest-environment node

import { describe, expect, it } from 'vitest';

import { validateBuildEnv } from './validate-build-env.mjs';

describe('validateBuildEnv', () => {
  it('accepts the required public frontend variables', () => {
    expect(validateBuildEnv({
      VITE_API_BASE_URL: 'https://api.example.com/',
      VITE_SUPABASE_URL: 'https://your-project-ref.supabase.co/',
      VITE_SUPABASE_ANON_KEY: 'public-anon-key',
    })).toEqual({
      apiBaseUrl: 'https://api.example.com',
      supabaseUrl: 'https://your-project-ref.supabase.co',
      supabaseAnonKey: 'public-anon-key',
    });
  });

  it('rejects missing required frontend variables with deployment guidance', () => {
    expect(() => validateBuildEnv({
      VITE_API_BASE_URL: '',
      VITE_SUPABASE_URL: 'https://your-project-ref.supabase.co',
      VITE_SUPABASE_ANON_KEY: 'public-anon-key',
    })).toThrow(/VITE_API_BASE_URL/i);
    expect(() => validateBuildEnv({
      VITE_API_BASE_URL: 'https://api.example.com',
      VITE_SUPABASE_URL: '',
      VITE_SUPABASE_ANON_KEY: 'public-anon-key',
    })).toThrow(/VITE_SUPABASE_URL/i);
    expect(() => validateBuildEnv({
      VITE_API_BASE_URL: 'https://api.example.com',
      VITE_SUPABASE_URL: 'https://your-project-ref.supabase.co',
      VITE_SUPABASE_ANON_KEY: '',
    })).toThrow(/VITE_SUPABASE_ANON_KEY/i);
  });

  it('rejects non-http URLs', () => {
    expect(() => validateBuildEnv({
      VITE_API_BASE_URL: 'ftp://api.example.com',
      VITE_SUPABASE_URL: 'https://your-project-ref.supabase.co',
      VITE_SUPABASE_ANON_KEY: 'public-anon-key',
    })).toThrow(/VITE_API_BASE_URL must use http or https/i);
    expect(() => validateBuildEnv({
      VITE_API_BASE_URL: 'https://api.example.com',
      VITE_SUPABASE_URL: 'ftp://your-project-ref.supabase.co',
      VITE_SUPABASE_ANON_KEY: 'public-anon-key',
    })).toThrow(/VITE_SUPABASE_URL must use http or https/i);
  });
});

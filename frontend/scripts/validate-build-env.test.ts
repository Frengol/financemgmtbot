// @vitest-environment node

import { describe, expect, it } from 'vitest';

import { validateApiBaseUrl } from './validate-build-env.mjs';

describe('validateApiBaseUrl', () => {
  it('accepts an absolute https API base URL', () => {
    expect(validateApiBaseUrl('https://api.example.com/')).toBe('https://api.example.com');
  });

  it('rejects a missing API base URL with deployment guidance', () => {
    expect(() => validateApiBaseUrl('')).toThrow(/Repository Variable or Secret named VITE_API_BASE_URL/i);
  });

  it('rejects non-http URLs', () => {
    expect(() => validateApiBaseUrl('ftp://api.example.com')).toThrow(/must use http or https/i);
  });
});

import { describe, expect, it } from 'vitest';
import { cn } from './utils';

describe('cn', () => {
  it('merges utility classes predictably', () => {
    expect(cn('px-2', 'text-sm', false && 'hidden', 'px-4', 'font-medium')).toBe('text-sm px-4 font-medium');
  });
});

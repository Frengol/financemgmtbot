import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

const distDir = resolve('dist');
const requiredPatterns = [
  {
    description: 'BFF browser requests must keep cookie-based credentials enabled',
    regex: /credentials\s*:\s*["']include["']/,
  },
  {
    description: 'Admin mutations must keep the CSRF header in the published bundle',
    regex: /X-CSRF-Token/,
  },
];
const forbiddenPatterns = [
  {
    description: 'legacy Authorization header usage',
    regex: /Authorization/,
  },
  {
    description: 'legacy bearer token transport',
    regex: /Bearer\s+/,
  },
  {
    description: 'legacy Supabase browser session lookup',
    regex: /\.auth\.getSession/,
  },
  {
    description: 'legacy Supabase OTP login path in the browser',
    regex: /signInWithOtp/,
  },
];

function collectFiles(dir) {
  const entries = readdirSync(dir, { withFileTypes: true });
  return entries.flatMap((entry) => {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      return collectFiles(fullPath);
    }
    return statSync(fullPath).isFile() ? [fullPath] : [];
  });
}

const files = collectFiles(distDir).filter((filePath) => filePath.endsWith('.js') || filePath.endsWith('.html'));
const bundle = files.map((filePath) => readFileSync(filePath, 'utf-8')).join('\n');

for (const pattern of requiredPatterns) {
  if (!pattern.regex.test(bundle)) {
    throw new Error(`Bundle verification failed: missing ${pattern.description}.`);
  }
}

for (const pattern of forbiddenPatterns) {
  if (pattern.regex.test(bundle)) {
    throw new Error(`Bundle verification failed: found ${pattern.description}.`);
  }
}

console.log(`Bundle verification passed for ${files.length} file(s).`);

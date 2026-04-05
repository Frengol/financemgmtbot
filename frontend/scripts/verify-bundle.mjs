import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

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
  {
    description: 'legacy Supabase client bootstrap in the browser bundle',
    regex: /createClient\(/,
  },
];

export function collectFiles(dir) {
  const entries = readdirSync(dir, { withFileTypes: true });
  return entries.flatMap((entry) => {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      return collectFiles(fullPath);
    }
    return statSync(fullPath).isFile() ? [fullPath] : [];
  });
}

export function verifyBundleDirectory(targetDir = resolve('dist')) {
  const files = collectFiles(targetDir).filter((filePath) => filePath.endsWith('.js') || filePath.endsWith('.html'));
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

  return files.length;
}

function runCli() {
  const targetDir = process.argv[2] ? resolve(process.argv[2]) : resolve('dist');
  const fileCount = verifyBundleDirectory(targetDir);
  console.log(`Bundle verification passed for ${fileCount} file(s).`);
}

const isCli =
  process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isCli) {
  runCli();
}

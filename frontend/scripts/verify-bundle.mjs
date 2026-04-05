import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const requiredPatterns = [
  {
    description: 'Supabase browser session storage key',
    regex: /financemgmtbot-admin-auth/,
  },
  {
    description: 'Supabase browser session bootstrap',
    regex: /\.auth\.setSession/,
  },
  {
    description: 'bearer authorization transport',
    regex: /Authorization/,
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

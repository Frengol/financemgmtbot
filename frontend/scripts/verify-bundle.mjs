import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const requiredPatterns = [
  {
    description: 'Supabase browser session storage key',
    regex: /financemgmtbot-admin-auth-v2/,
  },
  {
    description: 'Supabase magic link sign-in flow',
    regex: /\.auth\.signInWithOtp/,
  },
  {
    description: 'Supabase auth state listener',
    regex: /\.auth\.onAuthStateChange/,
  },
  {
    description: 'admin authorization handshake',
    regex: /\/api\/admin\/me/,
  },
  {
    description: 'bearer authorization transport',
    regex: /Authorization/,
  },
];

const forbiddenLiteralPatterns = [
  {
    description: 'backend Supabase service key literal',
    regex: /\bservice_role\b/,
  },
  {
    description: 'backend SUPABASE_KEY literal',
    regex: /\bSUPABASE_KEY\b/,
  },
  {
    description: 'backend APP_SESSION_SECRET literal',
    regex: /\bAPP_SESSION_SECRET\b/,
  },
  {
    description: 'backend DATA_ENCRYPTION_KEY literal',
    regex: /\bDATA_ENCRYPTION_KEY\b/,
  },
  {
    description: 'backend TELEGRAM_BOT_TOKEN literal',
    regex: /\bTELEGRAM_BOT_TOKEN\b/,
  },
  {
    description: 'backend TELEGRAM_SECRET_TOKEN literal',
    regex: /\bTELEGRAM_SECRET_TOKEN\b/,
  },
];

const jwtPattern = /\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b/g;
const emailPattern = /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g;
const forbiddenPublishedLegacyPathPatterns = [
  {
    description: 'legacy auth session path',
    regex: /(^|[^_A-Za-z0-9/.-])\/auth\/session\b/g,
  },
  {
    description: 'legacy magic link path',
    regex: /(^|[^_A-Za-z0-9/.-])\/auth\/magic-link\b/g,
  },
  {
    description: 'legacy logout path',
    regex: /(^|[^_A-Za-z0-9/.-])\/auth\/logout\b/g,
  },
];

function normalizePublicValue(value) {
  return typeof value === 'string' ? value.trim().replace(/\/$/, '') : '';
}

function uniqueMatches(bundle, regex) {
  return [...new Set(Array.from(bundle.matchAll(regex), (match) => match[0]))];
}

function findUnexpectedMatches(matches, allowedValues) {
  return matches.filter((value) => !allowedValues.has(value));
}

function resolvePublicConfig(options = {}) {
  return {
    supabaseUrl: normalizePublicValue(options.supabaseUrl ?? process.env.VITE_SUPABASE_URL),
    supabaseAnonKey: normalizePublicValue(
      options.supabaseAnonKey ?? process.env.VITE_SUPABASE_ANON_KEY,
    ),
  };
}

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

export function verifyBundleDirectory(targetDir = resolve('dist'), options = {}) {
  const files = collectFiles(targetDir).filter((filePath) => filePath.endsWith('.js') || filePath.endsWith('.html'));
  const bundle = files.map((filePath) => readFileSync(filePath, 'utf-8')).join('\n');
  const { supabaseUrl, supabaseAnonKey } = resolvePublicConfig(options);

  for (const pattern of requiredPatterns) {
    if (!pattern.regex.test(bundle)) {
      throw new Error(`Bundle verification failed: missing ${pattern.description}.`);
    }
  }

  if (supabaseUrl && !bundle.includes(supabaseUrl)) {
    throw new Error('Bundle verification failed: missing configured public Supabase URL.');
  }

  if (supabaseAnonKey && !bundle.includes(supabaseAnonKey)) {
    throw new Error('Bundle verification failed: missing configured public Supabase anon key.');
  }

  for (const legacyPath of forbiddenPublishedLegacyPathPatterns) {
    if (legacyPath.regex.test(bundle)) {
      throw new Error(`Bundle verification failed: found ${legacyPath.description}.`);
    }
  }

  for (const pattern of forbiddenLiteralPatterns) {
    if (pattern.regex.test(bundle)) {
      throw new Error(`Bundle verification failed: found ${pattern.description}.`);
    }
  }

  const allowedJwtTokens = new Set([supabaseAnonKey].filter(Boolean));
  const unexpectedJwtTokens = findUnexpectedMatches(uniqueMatches(bundle, jwtPattern), allowedJwtTokens);
  if (unexpectedJwtTokens.length > 0) {
    throw new Error('Bundle verification failed: found unexpected JWT token(s).');
  }

  const unexpectedEmails = uniqueMatches(bundle, emailPattern);
  if (unexpectedEmails.length > 0) {
    throw new Error('Bundle verification failed: found unexpected email address(es).');
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

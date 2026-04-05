import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

function validatePublicUrl(rawValue, variableName) {
  const value = typeof rawValue === 'string' ? rawValue.trim() : '';

  if (!value) {
    throw new Error(`Missing ${variableName}. Configure a GitHub Actions Repository Variable or Secret named ${variableName} before building the production frontend.`);
  }

  let parsedUrl;
  try {
    parsedUrl = new URL(value);
  } catch {
    throw new Error(`${variableName} must be an absolute http(s) URL.`);
  }

  if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
    throw new Error(`${variableName} must use http or https.`);
  }

  return parsedUrl.toString().replace(/\/$/, '');
}

export function validateBuildEnv(env) {
  const supabaseAnonKey = typeof env.VITE_SUPABASE_ANON_KEY === 'string' ? env.VITE_SUPABASE_ANON_KEY.trim() : '';
  if (!supabaseAnonKey) {
    throw new Error('Missing VITE_SUPABASE_ANON_KEY. Configure a GitHub Actions Repository Variable or Secret named VITE_SUPABASE_ANON_KEY before building the production frontend.');
  }

  return {
    apiBaseUrl: validatePublicUrl(env.VITE_API_BASE_URL, 'VITE_API_BASE_URL'),
    supabaseUrl: validatePublicUrl(env.VITE_SUPABASE_URL, 'VITE_SUPABASE_URL'),
    supabaseAnonKey,
  };
}

function runCli() {
  const result = validateBuildEnv(process.env);
  console.log(`Build environment verification passed for ${result.apiBaseUrl} with Supabase ${result.supabaseUrl}`);
}

const isCli =
  process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isCli) {
  runCli();
}

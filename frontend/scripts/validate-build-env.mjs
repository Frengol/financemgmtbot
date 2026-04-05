import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

export function validateApiBaseUrl(rawValue) {
  const value = typeof rawValue === 'string' ? rawValue.trim() : '';

  if (!value) {
    throw new Error(
      'Missing VITE_API_BASE_URL. Configure a GitHub Actions Repository Variable or Secret named VITE_API_BASE_URL before building the production frontend.',
    );
  }

  let parsedUrl;
  try {
    parsedUrl = new URL(value);
  } catch {
    throw new Error('VITE_API_BASE_URL must be an absolute http(s) URL.');
  }

  if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
    throw new Error('VITE_API_BASE_URL must use http or https.');
  }

  return parsedUrl.toString().replace(/\/$/, '');
}

function runCli() {
  const normalizedUrl = validateApiBaseUrl(process.env.VITE_API_BASE_URL);
  console.log(`Build environment verification passed for ${normalizedUrl}`);
}

const isCli =
  process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isCli) {
  runCli();
}

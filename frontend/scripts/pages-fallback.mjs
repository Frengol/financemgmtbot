import { copyFileSync, existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

function resolveTargetDir(targetDir = resolve('dist')) {
  return resolve(targetDir);
}

function resolvePagesPaths(targetDir = resolve('dist')) {
  const normalizedTargetDir = resolveTargetDir(targetDir);
  return {
    indexPath: join(normalizedTargetDir, 'index.html'),
    fallbackPath: join(normalizedTargetDir, '404.html'),
  };
}

export function copyPagesFallbackFile(targetDir = resolve('dist')) {
  const { indexPath, fallbackPath } = resolvePagesPaths(targetDir);
  if (!existsSync(indexPath)) {
    throw new Error(`Missing ${indexPath}. Build the frontend before generating the Pages fallback.`);
  }

  copyFileSync(indexPath, fallbackPath);
  return fallbackPath;
}

export function verifyPagesFallbackFile(targetDir = resolve('dist')) {
  const { indexPath, fallbackPath } = resolvePagesPaths(targetDir);
  if (!existsSync(indexPath)) {
    throw new Error(`Missing ${indexPath}. Build the frontend before verifying the Pages fallback.`);
  }

  if (!existsSync(fallbackPath)) {
    throw new Error(`Missing ${fallbackPath}. The GitHub Pages SPA fallback was not generated.`);
  }

  const indexHtml = readFileSync(indexPath, 'utf-8');
  const fallbackHtml = readFileSync(fallbackPath, 'utf-8');

  if (fallbackHtml !== indexHtml) {
    throw new Error('GitHub Pages fallback verification failed: 404.html must match index.html.');
  }

  if (!indexHtml.includes('<div id="root"></div>')) {
    throw new Error('GitHub Pages fallback verification failed: missing SPA root container.');
  }

  if (!/script\s+type="module"/i.test(indexHtml)) {
    throw new Error('GitHub Pages fallback verification failed: missing production module entrypoint.');
  }

  return {
    indexPath,
    fallbackPath,
  };
}

function runCli() {
  const action = (process.argv[2] || '').trim();
  const targetDir = process.argv[3] ? resolve(process.argv[3]) : resolve('dist');

  if (action === 'copy') {
    const fallbackPath = copyPagesFallbackFile(targetDir);
    console.log(`Pages fallback generated at ${fallbackPath}`);
    return;
  }

  if (action === 'verify') {
    const { fallbackPath } = verifyPagesFallbackFile(targetDir);
    console.log(`Pages fallback verification passed for ${fallbackPath}`);
    return;
  }

  throw new Error('Usage: node ./scripts/pages-fallback.mjs <copy|verify> [distDir]');
}

const isCli = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isCli) {
  runCli();
}

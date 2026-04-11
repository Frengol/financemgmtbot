# Public Release Checklist

Use this checklist before publishing the repository to a public remote.

## 1. Start from a trustworthy Git clone

- Prefer a fresh clone from the authoritative remote.
- Confirm the clone is healthy:
  - `git rev-parse --show-toplevel`
  - `git fsck --full`
  - `git status`
- If the workspace does not have a functional `.git`, do not publish from it.

## 2. Audit current content

- Keep `.env`, `.env.*`, local reports, coverage artifacts and security notes out of the public repository.
- Keep `.dockerignore` aligned with those exclusions so local secrets and reports are not copied into backend container builds.
- Verify examples and docs still use placeholders only.
- Run the local safety checks:
  - `make test-backend`
  - `make test-frontend`
  - `make test-frontend-e2e`
  - `make audit-frontend-deps`
  - `make audit-backend-deps`
  - `npm run verify:build-env --prefix frontend`
  - `npm run verify:bundle --prefix frontend`
- Confirm that docs/examples mention the public frontend release id (`VITE_APP_RELEASE`) and the first-party browser diagnostics endpoints (`/api/meta/runtime`, `/api/client-telemetry`) only as public operational metadata, never as secret-bearing flows.

## 3. Audit the Git history

- Fetch full history before scanning:
  - `git fetch --all --tags --prune`
- Review history for leaks:
  - `git log --all -p`
  - `git grep -n 'service_role\\|SUPABASE_KEY\\|DATA_ENCRYPTION_KEY' $(git rev-list --all)`
- Run a secret scanner over the repository and history:
  - `gitleaks detect --source . --redact`

## 4. If any real secret is found

- Rotate the affected credential before publication.
- Rewrite history with `git filter-repo` or an equivalent tool.
- Expire reflogs and garbage-collect after the rewrite.
- Repeat the history audit until it is clean.

## 5. Final publish gate

Only publish when all of the following are true:

- tests and build are green
- `npm audit --omit=dev` has no `high` or `critical`
- `pip-audit` has no blocking findings
- `gitleaks` is clean on content and history
- docs and examples contain placeholders only
- the release is being made from a healthy Git clone
- backend deploys from the checked-in `cloudbuild.yaml` and `Dockerfile`, not from an implicit Cloud Run source-build path
- Cloud Run production keeps `FRONTEND_PUBLIC_URL` and `FRONTEND_ALLOWED_ORIGINS` set to the published GitHub Pages values
- Cloud Run production keeps `AUTH_TEST_MODE=false` and `ALLOW_LOCAL_DEV_AUTH=false`
- Cloud Run production publishes runtime metadata (`APP_COMMIT_SHA`, `APP_RELEASE_SHA`) and can be checked with `GET /api/meta/runtime`
- the productive backend contract does not publish legacy `/auth/*` routes

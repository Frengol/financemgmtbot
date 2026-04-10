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
- Verify examples and docs still use placeholders only.
- Run the local safety checks:
  - `make test-backend`
  - `make test-frontend`
  - `make test-frontend-e2e`
  - `make audit-frontend-deps`
  - `make audit-backend-deps`
  - `npm run verify:build-env --prefix frontend`
  - `npm run verify:bundle --prefix frontend`

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

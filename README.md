# FinanceMgmtBot

## Environment setup

Backend local:
- create `.env` based on `.env.example`
- fill the required secrets before starting `main.py`

Frontend local:
- create `frontend/.env.development` based on `frontend/.env.development.example`
- keep `VITE_API_BASE_URL=` empty in local development to use the Vite proxy

GitHub Pages:
- create `frontend/.env.production` based on `frontend/.env.production.example`
- set `VITE_API_BASE_URL` only after you have a public backend URL; GitHub Pages cannot run the Python backend by itself
- prefer GitHub Actions `Variables` for `VITE_SUPABASE_URL` and `VITE_API_BASE_URL`, and a GitHub Actions `Secret` for `VITE_SUPABASE_ANON_KEY`, so these values are not stored in the workflow file

## Deployment model

- GitHub Pages publishes only the frontend SPA.
- Cloud Run continues to host the Python backend and admin API.
- Set the published frontend to talk only to your intended public backend origin, for example `https://api.example.com`.

## GitHub Actions

- [`.github/workflows/ci.yml`](.github/workflows/ci.yml) now runs backend coverage, frontend unit coverage, frontend build and deterministic Playwright smoke tests on pushes and pull requests.
- The CI workflow also runs `pip-audit`, `npm audit --omit=dev`, a built-asset string scan and a full-history `gitleaks` job when the repository is checked out in GitHub Actions.
- [`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml) builds the frontend with repository `Variables/Secrets` and deploys `frontend/dist` to GitHub Pages.
- In the repository settings, set the Pages source to `GitHub Actions`.
- Create these GitHub Actions settings before merging:
  - Repository Variable: `VITE_SUPABASE_URL`
  - Repository Variable: `VITE_API_BASE_URL`
  - Repository Secret: `VITE_SUPABASE_ANON_KEY`
- Important: this keeps the values out of the repository and workflow YAML, but anything required by the static frontend is still visible in the final browser bundle.

## Public release hygiene

- Keep `.env`, `.env.*`, local reports and internal assessment notes out of public commits.
- Do not publish internal pentest reports or operational security notebooks in the public repository.
- Use placeholders in examples and docs for project refs, public URLs and operator e-mails.
- Follow [`PUBLIC_RELEASE.md`](PUBLIC_RELEASE.md) before pushing to a public remote.

## Test commands

Backend:
- `make test-backend`
- `make test-backend-coverage`
- `make audit-backend-deps`

Frontend:
- `make test-frontend`
- `make test-frontend-coverage`
- `make audit-frontend-deps`
- `npm run test:e2e --prefix frontend`

Playwright:
- install Chromium locally with `npm run test:e2e:install --prefix frontend`
- the E2E suite runs against the local Vite app and mocks `/auth/*` and `/api/admin/*`, so it does not depend on Supabase, Telegram or Cloud Run

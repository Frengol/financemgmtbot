# FinanceMgmtBot

## Environment setup

Backend local:
- create `.env` based on `.env.example`
- fill the required secrets before starting `main.py`
- set `FRONTEND_PUBLIC_URL` to the published frontend URL in production
- set `AUTH_CALLBACK_PUBLIC_URL` to the public backend callback URL in production

Frontend local:
- create `frontend/.env.development` based on `frontend/.env.development.example`
- keep `VITE_API_BASE_URL=` empty in local development to use the Vite proxy

GitHub Pages:
- create `frontend/.env.production` based on `frontend/.env.production.example`
- set `VITE_API_BASE_URL` only after you have a public backend URL; GitHub Pages cannot run the Python backend by itself
- prefer GitHub Actions `Variables` for `VITE_API_BASE_URL`, and use a GitHub Actions `Secret` with the same name as fallback if your repository policy blocks Variables
- production builds now fail fast with `npm run verify:build-env` when `VITE_API_BASE_URL` is missing or not an absolute `http(s)` URL

Supabase Auth:
- in `Authentication -> URL Configuration`, set `Site URL` to your public backend callback, for example `https://api.example.com/auth/callback`
- add both the backend callback URL and the published frontend URL to `Redirect URLs`
- do not leave `localhost` as the production Site URL, or Supabase can generate expired/invalid links pointing at a local address

## Deployment model

- GitHub Pages publishes only the frontend SPA.
- Cloud Run continues to host the Python backend and admin API.
- Set the published frontend to talk only to your intended public backend origin, for example `https://api.example.com`.

## GitHub Actions

- [`.github/workflows/ci.yml`](.github/workflows/ci.yml) now runs backend coverage, frontend unit coverage, frontend build and deterministic Playwright smoke tests on pushes and pull requests.
- The CI workflow also runs `pip-audit`, `npm audit --omit=dev`, a built-asset string scan and a full-history `gitleaks` job when the repository is checked out in GitHub Actions.
- [`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml) validates the build environment, builds the frontend and deploys `frontend/dist` to GitHub Pages.
- In the repository settings, set the Pages source to `GitHub Actions`.
- Create these GitHub Actions settings before merging:
  - Repository Variable or Secret: `VITE_API_BASE_URL`
- Important: the frontend now depends only on the admin API base URL at build time; authentication itself stays behind the backend BFF.

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
- `npm run verify:build-env --prefix frontend`
- `npm run verify:bundle --prefix frontend`
- `npm run test:e2e --prefix frontend`

Playwright:
- install Chromium locally with `npm run test:e2e:install --prefix frontend`
- the E2E suite runs against the local Vite app and mocks `/auth/*` and `/api/admin/*`, so it does not depend on Supabase, Telegram or Cloud Run

# FinanceMgmtBot

## Environment setup

Backend local:
- create `.env` based on `.env.example`
- fill the required secrets before starting `main.py`
- set `FRONTEND_PUBLIC_URL` to the published frontend URL in production
- keep `AUTH_CALLBACK_PUBLIC_URL` only for legacy backend callback compatibility and internal tooling
- in production, `POST /auth/magic-link` now uses the canonical frontend callback derived from `FRONTEND_PUBLIC_URL`; browser-provided callback overrides are only accepted in local/test mode

Frontend local:
- create `frontend/.env.development` based on `frontend/.env.development.example`
- keep `VITE_API_BASE_URL=` empty in local development to use the Vite proxy for `/api`, `/auth` and local test-support routes
- set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` to the public values used by the GitHub Pages login flow

GitHub Pages:
- create `frontend/.env.production` based on `frontend/.env.production.example`
- set `VITE_API_BASE_URL`, `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` only after you have a public backend URL and public Supabase browser-auth values
- prefer GitHub Actions `Variables` for the three `VITE_*` values, and use a GitHub Actions `Secret` with the same name as fallback if your repository policy blocks Variables
- production builds now fail fast with `npm run verify:build-env` when any required `VITE_*` value is missing or invalid
- production builds also generate `frontend/dist/404.html` as a copy of `index.html`, so GitHub Pages can serve the SPA shell for deep links such as `/financemgmtbot/auth/callback`

Supabase Auth:
- in `Authentication -> URL Configuration`, set `Site URL` to your published frontend callback, for example `https://admin.example.com/auth/callback`
- add both the frontend callback URL and the published frontend root URL to `Redirect URLs`
- keep the backend callback URL in `Redirect URLs` only while you still need compatibility with older email links; the backend relay will forward those links to the frontend callback
- do not leave `localhost` as the production Site URL, or Supabase can generate expired/invalid links pointing at a local address

Local auth integration test mode:
- `AUTH_TEST_MODE=true` is reserved for local Playwright/backend integration and must never be enabled in Cloud Run production
- in this mode, the backend captures deterministic magic links and keeps test sessions/data in memory instead of calling upstream auth or the real `admin_web_sessions` table

## Deployment model

- GitHub Pages publishes only the frontend SPA.
- Cloud Run continues to host the Python backend and admin API.
- Set the published frontend to talk only to your intended public backend origin, for example `https://api.example.com`.

## GitHub Actions

- [`.github/workflows/ci.yml`](.github/workflows/ci.yml) now runs backend coverage, frontend unit coverage, frontend build and deterministic Playwright smoke tests on pushes and pull requests.
- Backend coverage now fails below `90%` for both `Lines` and `Branches`, and frontend unit coverage now fails below `90%` for `Statements`, `Branches`, `Functions` and `Lines`.
- The CI workflow also runs `pip-audit`, `npm audit --omit=dev`, a built-asset scan that allows only the expected public Supabase frontend values while blocking backend secrets/unexpected JWTs, and a full-history `gitleaks` job when the repository is checked out in GitHub Actions.
- [`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml) validates the build environment, builds the frontend and deploys `frontend/dist` to GitHub Pages.
- the frontend publication flow now validates `npm run verify:pages-fallback` after the build to guarantee that `404.html` exists and matches the SPA shell expected by GitHub Pages.
- In the repository settings, set the Pages source to `GitHub Actions`.
- Create these GitHub Actions settings before merging:
  - Repository Variable or Secret: `VITE_API_BASE_URL`
  - Repository Variable or Secret: `VITE_SUPABASE_URL`
  - Repository Variable or Secret: `VITE_SUPABASE_ANON_KEY`
- Important: the frontend now depends on the admin API base URL and the public Supabase browser-auth values at build time.
- For public repositories on GitHub.com, GitHub Secret Scanning runs automatically; keep it enabled and verify in `Security` that alerts are visible.
- In your GitHub user settings, enable `Push protection for yourself` so GitHub can block pushes that contain recognized secrets.

## Public release hygiene

- Keep `.env`, `.env.*`, local reports and internal assessment notes out of public commits.
- Do not publish internal pentest reports or operational security notebooks in the public repository.
- Use placeholders in examples and docs for project refs, public URLs and operator e-mails.
- Follow [`PUBLIC_RELEASE.md`](PUBLIC_RELEASE.md) before pushing to a public remote.

## Test commands

Backend:
- `make test-backend`
- `make test-backend-coverage`
- `make test-backend-live-db-smoke`
- `make audit-backend-deps`
- `make test-backend-coverage` now enforces `Lines >= 90%` and `Branches >= 90%`

Frontend:
- `make test-frontend`
- `make test-frontend-coverage`
- `make audit-frontend-deps`
- `npm run verify:build-env --prefix frontend`
- `npm run verify:pages-fallback --prefix frontend`
- `npm run verify:bundle --prefix frontend`
- `npm run test:e2e --prefix frontend`
- `npm run test:e2e:smoke --prefix frontend`
- `npm run test:e2e:integration --prefix frontend`
- `make test-frontend-coverage` now enforces `Statements >= 90%`, `Branches >= 90%`, `Functions >= 90%` and `Lines >= 90%`

Playwright:
- install Chromium and Firefox locally with `npm run test:e2e:install --prefix frontend`
- the smoke suite keeps mocking `/auth/*` and `/api/admin/*` for deterministic UI regression coverage
- the integration suite starts the local Quart backend in `AUTH_TEST_MODE`, requests a real magic link through the login form, follows the hosted-style verify link into the frontend callback and validates that authenticated data loading works end to end
- the live database smoke stays opt-in via `LIVE_DB_SMOKE=true` and only exercises read-only access to `/api/admin/gastos`

Before push:
- install `gitleaks` locally and confirm `make audit-repo-security` passes
- `make audit-repo-security` now scans the Git repository and the current tracked diff, so ignored local files such as `.env` and generated `dist` artifacts do not block the gate
- run `make pre-push` before every push
- run `make pre-push-full` for auth, frontend, CI, build, deploy, public-contract or security-sensitive changes
- `make pre-push` and `make pre-push-full` now inject safe public placeholders for `VITE_API_BASE_URL`, `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` during local build validation, so the gate works out of the box without exporting production values
- if you want to validate the local gate against specific public runtime values, override `FRONTEND_BUILD_API_BASE_URL`, `FRONTEND_BUILD_SUPABASE_URL` and `FRONTEND_BUILD_SUPABASE_ANON_KEY` when invoking `make pre-push`
- `make pre-push` now also checks the GitHub Pages SPA fallback by validating that `dist/404.html` matches `dist/index.html`
- if the change touches dependencies or publication, also run:
  - `make audit-backend-deps`
  - `make audit-frontend-deps`
- install the optional local Git hook with:
  - `make install-git-hooks`

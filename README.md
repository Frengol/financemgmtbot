# FinanceMgmtBot

## Environment setup

Backend local:
- create `.env` based on `.env.example`
- fill the required secrets before starting `main.py`
- set `FRONTEND_PUBLIC_URL` to the published frontend URL in production
- set `FRONTEND_ALLOWED_ORIGINS` to the published frontend origin in production, for example `https://frengol.github.io`
- in production, the published frontend talks directly to Supabase Auth for Magic Link issuance and callback completion; Cloud Run only validates Bearer tokens and serves `/api/admin/*`
- the backend does not expose `/auth/magic-link`, `/auth/callback`, `/auth/session` or `/auth/logout` as part of the productive panel flow
- Cloud Run production must keep `AUTH_TEST_MODE=false` and `ALLOW_LOCAL_DEV_AUTH=false`
- during `/auth/callback`, the shared auth provider stays silent and does not call `/api/admin/me`; the callback route alone concludes the Supabase browser session before the app authorizes the panel
- after `/api/admin/me` authorizes a valid browser session, local profile persistence is best-effort only; a storage write failure must not invalidate the in-memory login state for the current tab

Frontend local:
- create `frontend/.env.development` based on `frontend/.env.development.example`
- keep `VITE_API_BASE_URL=` empty in local development to use the Vite proxy for `/api` and local test-support routes
- set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` to the public values used by the GitHub Pages login flow
- set `VITE_APP_RELEASE` to a non-sensitive public release id when validating production-like frontend builds locally

GitHub Pages:
- create `frontend/.env.production` based on `frontend/.env.production.example`
- set `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` and `VITE_APP_RELEASE` only after you have a public backend URL and public Supabase browser-auth values
- prefer GitHub Actions `Variables` for the four public `VITE_*` values, and use a GitHub Actions `Secret` with the same name as fallback if your repository policy blocks Variables
- production builds now fail fast with `npm run verify:build-env` when any required `VITE_*` value is missing or invalid
- production builds also generate `frontend/dist/404.html` as a copy of `index.html`, so GitHub Pages can serve the SPA shell for deep links such as `/financemgmtbot/auth/callback`
- GitHub Pages does not expose logs de runtime da SPA; browser-side diagnostics now flow through `POST /api/client-telemetry` to Cloud Logging, correlated with `VITE_APP_RELEASE`

Supabase Auth:
- in `Authentication -> URL Configuration`, set `Site URL` to the published frontend root, for example `https://admin.example.com/`
- add the exact callback URL `https://admin.example.com/auth/callback` to `Redirect URLs`
- do not leave `localhost` as the production Site URL, or Supabase can generate expired/invalid links pointing at a local address

Local auth integration test mode:
- `AUTH_TEST_MODE=true` is reserved for local Playwright/backend integration and must never be enabled in Cloud Run production
- in this mode, the backend captures deterministic magic links and keeps auth test state/data in memory instead of calling upstream auth

## Deployment model

- GitHub Pages publishes only the frontend SPA.
- Cloud Run continues to host the Python backend and admin API.
- Set the published frontend to talk only to your intended public backend origin, for example `https://api.example.com`.
- In Cloud Run production, keep both `FRONTEND_PUBLIC_URL` and `FRONTEND_ALLOWED_ORIGINS` configured; the backend now fails fast when it cannot resolve a public browser origin safely.
- The backend deployment source of truth is now [`cloudbuild.yaml`](cloudbuild.yaml), which builds the checked-in `Dockerfile`, pushes the image to Artifact Registry and deploys Cloud Run by image digest.
- The productive backend deployment path no longer supports Cloud Run source deploy with buildpacks; disable the old source-build trigger after moving the service to the versioned Cloud Build trigger.
- Every Cloud Run rollout now stamps public runtime metadata (`APP_COMMIT_SHA`, `APP_RELEASE_SHA` and label `commit-sha`) so the published service can be checked with `GET /api/meta/runtime`.
- Run the backend Cloud Build trigger with a dedicated service account scoped to minimum roles only:
  - `Artifact Registry Writer`
  - `Cloud Run Admin`
  - `Service Account User` on the Cloud Run runtime identity
  - `Logs Writer`

## GitHub Actions

- [`.github/workflows/ci.yml`](.github/workflows/ci.yml) now runs backend coverage, frontend unit coverage, frontend build and deterministic Playwright smoke tests on pushes and pull requests.
- Backend coverage now fails below `90%` for both `Lines` and `Branches`, and frontend unit coverage now fails below `90%` for `Statements`, `Branches`, `Functions` and `Lines`.
- The CI workflow also runs `pip-audit`, `npm audit --omit=dev`, a built-asset scan that allows only the expected public Supabase frontend values while blocking backend secrets/unexpected JWTs, and a full-history `gitleaks` job when the repository is checked out in GitHub Actions.
- [`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml) validates the build environment, builds the frontend and deploys `frontend/dist` to GitHub Pages.
- the frontend publication flow now validates `npm run verify:pages-fallback` after the build to guarantee that `404.html` exists and matches the SPA shell expected by GitHub Pages.
- the Pages workflow now injects `VITE_APP_RELEASE=${GITHUB_SHA::12}` so browser telemetry can be correlated with the published bundle
- In the repository settings, set the Pages source to `GitHub Actions`.
- Create these GitHub Actions settings before merging:
  - Repository Variable or Secret: `VITE_API_BASE_URL`
  - Repository Variable or Secret: `VITE_SUPABASE_URL`
  - Repository Variable or Secret: `VITE_SUPABASE_ANON_KEY`
- Important: the frontend now depends on the admin API base URL and the public Supabase browser-auth values at build time.
- Backend deploys are intentionally kept outside GitHub Actions in this repository; Cloud Build now owns the container build and Cloud Run rollout via the checked-in [`cloudbuild.yaml`](cloudbuild.yaml).
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
- the smoke suite keeps mocking `/api/admin/*` and the local-only `__test__/auth/*` support routes for deterministic UI regression coverage
- the integration suite starts the local Quart backend in `AUTH_TEST_MODE`, requests a real magic link through the login form, follows the hosted-style verify link into the frontend callback and validates that authenticated data loading works end to end
- the live database smoke stays opt-in via `LIVE_DB_SMOKE=true` and only exercises read-only access to `/api/admin/gastos`
- browser-only auth and transport failures that do not surface in the admin API logs can now be observed through `browser_client_telemetry` entries in Cloud Logging, keyed by `clientEventId`, `requestId` and `VITE_APP_RELEASE`; the callback now stays focused on concluding the Supabase browser session and leaves `/api/admin/me` to the shared auth context

Before push:
- install `gitleaks` locally and confirm `make audit-repo-security` passes
- `make audit-repo-security` now scans the Git repository and the current tracked diff, so ignored local files such as `.env` and generated `dist` artifacts do not block the gate
- run `make pre-push` before every push
- run `make pre-push-full` for auth, frontend, CI, build, deploy, public-contract or security-sensitive changes
- `make pre-push` and `make pre-push-full` now inject safe public placeholders for `VITE_API_BASE_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` and `VITE_APP_RELEASE` during local build validation, so the gate works out of the box without exporting production values
- if you want to validate the local gate against specific public runtime values, override `FRONTEND_BUILD_API_BASE_URL`, `FRONTEND_BUILD_SUPABASE_URL`, `FRONTEND_BUILD_SUPABASE_ANON_KEY` and `FRONTEND_BUILD_APP_RELEASE` when invoking `make pre-push`
- `make pre-push` now also checks the GitHub Pages SPA fallback by validating that `dist/404.html` matches `dist/index.html`
- if the change touches dependencies or publication, also run:
  - `make audit-backend-deps`
  - `make audit-frontend-deps`
- install the optional local Git hook with:
  - `make install-git-hooks`

## Cloud Run backend deploy

- Create or update a Cloud Build trigger that points to [`cloudbuild.yaml`](cloudbuild.yaml) in this repository.
- Keep the trigger building the checked-in `Dockerfile`; do not use Cloud Run source deploy with buildpacks for the backend anymore.
- The default substitutions in [`cloudbuild.yaml`](cloudbuild.yaml) target:
  - Artifact Registry host `southamerica-east1-docker.pkg.dev`
  - repository `cloud-run-source-deploy`
  - image `financemgmtbot-git`
  - service `financemgmtbot-git`
  - region `southamerica-east1`
- If your service names differ, override the substitutions in the trigger instead of editing the deploy logic in the Google Cloud console.
- Preserve these runtime envs on the Cloud Run service during every deploy:
  - `FRONTEND_PUBLIC_URL=https://frengol.github.io/financemgmtbot/`
  - `FRONTEND_ALLOWED_ORIGINS=https://frengol.github.io`
  - `AUTH_TEST_MODE=false`
  - `ALLOW_LOCAL_DEV_AUTH=false`
- Use `GET /api/meta/runtime` after the rollout to confirm that the published Cloud Run revision is serving the commit you just deployed.
- Use `POST /api/client-telemetry` only as a first-party diagnostics sink for the GitHub Pages frontend; it must stay schema-limited, rate-limited and free of tokens, e-mails and callback query/hash data.
- In the callback flow, transport diagnostics now prefer `fetch(..., { keepalive: true })` while the page is active and only fall back to `navigator.sendBeacon()` when needed, so browser-side failures have a better chance of reaching Cloud Logging before any navigation happens.

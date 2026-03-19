# FinanceMgmtBot

## Environment setup

Backend local:
- create `.env` based on [`.env.example`](/home/fregolon/Área%20de%20trabalho/Projetos/financemgmtbot/financemgmtbot/.env.example)
- fill the required secrets before starting `main.py`

Frontend local:
- create `frontend/.env.development` based on [`frontend/.env.development.example`](/home/fregolon/Área%20de%20trabalho/Projetos/financemgmtbot/financemgmtbot/frontend/.env.development.example)
- keep `VITE_API_BASE_URL=` empty in local development to use the Vite proxy

GitHub Pages:
- create `frontend/.env.production` based on [`frontend/.env.production.example`](/home/fregolon/Área%20de%20trabalho/Projetos/financemgmtbot/financemgmtbot/frontend/.env.production.example)
- set `VITE_API_BASE_URL` only after you have a public backend URL; GitHub Pages cannot run the Python backend by itself
- prefer GitHub Actions `Variables` for `VITE_SUPABASE_URL` and `VITE_API_BASE_URL`, and a GitHub Actions `Secret` for `VITE_SUPABASE_ANON_KEY`, so these values are not stored in the workflow file

## Deployment model

- GitHub Pages publishes only the frontend SPA.
- Cloud Run continues to host the Python backend and admin API.
- The published frontend is configured to talk to `https://api.example.com`.

## GitHub Actions

- [`.github/workflows/ci.yml`](/home/fregolon/Área%20de%20trabalho/Projetos/financemgmtbot/financemgmtbot/.github/workflows/ci.yml) runs the Python tests and validates the frontend build on pushes and pull requests.
- [`.github/workflows/deploy-pages.yml`](/home/fregolon/Área%20de%20trabalho/Projetos/financemgmtbot/financemgmtbot/.github/workflows/deploy-pages.yml) builds the frontend and deploys `frontend/dist` to GitHub Pages.
- In the repository settings, set the Pages source to `GitHub Actions`.
- Create these GitHub Actions settings before merging:
  - Repository Variable: `VITE_SUPABASE_URL`
  - Repository Variable: `VITE_API_BASE_URL`
  - Repository Secret: `VITE_SUPABASE_ANON_KEY`
- Important: this keeps the values out of the repository and workflow YAML, but anything required by the static frontend is still visible in the final browser bundle.

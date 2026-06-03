.PHONY: test-backend test-backend-coverage test-backend-live-db-smoke test-frontend test-frontend-coverage test-frontend-e2e audit-backend-deps audit-frontend-deps audit-repo-security pre-push pre-push-full install-git-hooks run-backend-local run-frontend-local run-backend-qa-auth run-frontend-qa-auth

BACKEND_COVERAGE_ARGS = \
	--cov=admin_runtime \
	--cov=ai_service \
	--cov=config \
	--cov=core_logic \
	--cov=db_repository \
	--cov=domain \
	--cov=handlers \
	--cov=main \
	--cov=security \
	--cov=telegram_service \
	--cov=utils \
	--cov=web_app \
	--cov-branch \
	--cov-config=.coveragerc \
	--cov-report=term-missing \
	--cov-report=xml:coverage/backend/coverage.xml

FRONTEND_BUILD_ENV_UNSET = env -u VITE_API_BASE_URL -u VITE_SUPABASE_URL -u VITE_SUPABASE_ANON_KEY -u VITE_APP_RELEASE
FRONTEND_BUILD_API_BASE_URL ?= https://api.example.com
FRONTEND_BUILD_SUPABASE_URL ?= https://your-project-ref.supabase.co
FRONTEND_BUILD_SUPABASE_ANON_KEY ?= public-anon-key
FRONTEND_BUILD_APP_RELEASE ?= local-build-release
FRONTEND_BUILD_ENV = env VITE_API_BASE_URL=$(FRONTEND_BUILD_API_BASE_URL) VITE_SUPABASE_URL=$(FRONTEND_BUILD_SUPABASE_URL) VITE_SUPABASE_ANON_KEY=$(FRONTEND_BUILD_SUPABASE_ANON_KEY) VITE_APP_RELEASE=$(FRONTEND_BUILD_APP_RELEASE)

test-backend:
	pytest -q

test-backend-coverage:
	mkdir -p coverage/backend
	pytest -q $(BACKEND_COVERAGE_ARGS)
	python scripts/check_backend_coverage.py coverage/backend/coverage.xml --min-lines 90 --min-branches 90

test-backend-live-db-smoke:
	LIVE_DB_SMOKE=true pytest -q tests/backend/test_live_db_smoke.py

test-frontend:
	npm test --prefix frontend

test-frontend-coverage:
	npm run test:coverage --prefix frontend

test-frontend-e2e:
	npm run test:e2e --prefix frontend

audit-backend-deps:
	pip-audit -r requirements.txt
	pip-audit -r requirements-dev.txt

audit-frontend-deps:
	npm audit --omit=dev --prefix frontend

audit-repo-security:
	@command -v gitleaks >/dev/null 2>&1 || { \
		echo "gitleaks is not installed locally. Install it before committing security-sensitive changes."; \
		exit 1; \
	}
	gitleaks git --no-banner --redact .
	gitleaks git --no-banner --redact --pre-commit .

pre-push: audit-repo-security test-backend-coverage
	$(FRONTEND_BUILD_ENV_UNSET) npm run test:coverage --prefix frontend
	$(FRONTEND_BUILD_ENV) npm run verify:build-env --prefix frontend
	$(FRONTEND_BUILD_ENV) npm run build --prefix frontend
	$(FRONTEND_BUILD_ENV) npm run verify:pages-fallback --prefix frontend
	$(FRONTEND_BUILD_ENV) npm run verify:bundle --prefix frontend

pre-push-full: pre-push test-frontend-e2e

install-git-hooks:
	bash scripts/install-git-hooks.sh

run-backend-local:
	ALLOW_LOCAL_DEV_AUTH=true AUTH_TEST_MODE=false FRONTEND_PUBLIC_URL=http://127.0.0.1:5173/ FRONTEND_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173 python main.py

run-frontend-local:
	npm run dev --prefix frontend -- --host 127.0.0.1 --port 5173

run-backend-qa-auth:
	AUTH_TEST_MODE=true AUTH_TEST_DATA_SOURCE=database ALLOW_LOCAL_DEV_AUTH=false FRONTEND_PUBLIC_URL=http://127.0.0.1:5174/ FRONTEND_ALLOWED_ORIGINS=http://127.0.0.1:5174,http://localhost:5174 PORT=8080 python main.py

run-frontend-qa-auth:
	VITE_API_BASE_URL=http://127.0.0.1:8080 VITE_AUTH_TEST_MODE=true VITE_LOCAL_DEV_BYPASS_AUTH=false npm run dev --prefix frontend -- --host 127.0.0.1 --port 5174

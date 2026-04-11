.PHONY: test-backend test-backend-coverage test-backend-live-db-smoke test-frontend test-frontend-coverage test-frontend-e2e audit-backend-deps audit-frontend-deps audit-repo-security pre-push pre-push-full install-git-hooks

BACKEND_COVERAGE_ARGS = \
	--cov=admin_runtime \
	--cov=ai_service \
	--cov=config \
	--cov=core_logic \
	--cov=db_repository \
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
	LIVE_DB_SMOKE=true pytest -q test_live_db_smoke.py

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

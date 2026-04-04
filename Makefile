.PHONY: test-backend test-backend-coverage test-frontend test-frontend-coverage test-frontend-e2e audit-backend-deps audit-frontend-deps

BACKEND_COVERAGE_ARGS = \
	--cov=admin_api \
	--cov=ai_service \
	--cov=config \
	--cov=core_logic \
	--cov=db_repository \
	--cov=handlers \
	--cov=main \
	--cov=security \
	--cov=telegram_service \
	--cov=utils \
	--cov-branch \
	--cov-config=.coveragerc \
	--cov-report=term-missing \
	--cov-report=xml:coverage/backend/coverage.xml

test-backend:
	pytest -q

test-backend-coverage:
	mkdir -p coverage/backend
	pytest -q $(BACKEND_COVERAGE_ARGS)

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

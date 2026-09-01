from pathlib import Path
import json
import re
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_frontend_public_build_restores_supabase_runtime_dependency_for_pages_auth():
    package_json = json.loads((REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    dependencies = package_json.get("dependencies", {})

    assert "@supabase/supabase-js" in dependencies
    assert (REPO_ROOT / "frontend" / "src" / "features" / "auth" / "lib" / "supabaseBrowserSession.ts").exists()
    assert not (REPO_ROOT / "frontend" / "src" / "lib" / "supabase.ts").exists()


def test_public_frontend_contract_files_keep_runtime_setup_out_of_readme():
    build_files = [
        REPO_ROOT / "frontend" / ".env.example",
        REPO_ROOT / "frontend" / ".env.development.example",
        REPO_ROOT / "frontend" / ".env.production.example",
        REPO_ROOT / "frontend" / "src" / "vite-env.d.ts",
    ]

    for file_path in build_files:
        content = file_path.read_text(encoding="utf-8")
        assert "VITE_SUPABASE_URL" in content
        assert "VITE_SUPABASE_ANON_KEY" in content
        assert "VITE_APP_RELEASE" in content

    setup = (REPO_ROOT / "SETUP.md").read_text(encoding="utf-8")
    assert "VITE_API_BASE_URL" in setup
    assert "VITE_SUPABASE_URL" in setup
    assert "VITE_SUPABASE_ANON_KEY" in setup

    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "FRONTEND_ALLOWED_ORIGINS" in env_example
    assert "FRONTEND_PUBLIC_URL" in env_example

    public_runtime_names = re.findall(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", readme)
    assert public_runtime_names == []
    assert "architecture.md" not in readme
    assert "DeepSeek" not in readme
    assert "Gemini" not in readme
    assert "Groq" not in readme
    assert "React" not in readme
    assert "Vite" not in readme
    assert "Codex" not in readme
    assert "token" not in readme.lower()
    assert "chave" not in readme.lower()
    assert "segredo" not in readme.lower()
    assert "Pipeline de CI" in readme
    assert "Despesas fixas" in readme
    assert "Cupons Com Revisao" in readme
    assert "backend relay `/auth/callback`" not in readme

    tracked_setup = subprocess.run(
        ["git", "ls-files", "SETUP.md"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert tracked_setup.stdout.strip() == "SETUP.md"


def test_gitignore_allows_public_env_examples():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "!.env.example" in gitignore
    assert "!frontend/.env.example" in gitignore
    assert "!frontend/.env.development.example" in gitignore
    assert "!frontend/.env.production.example" in gitignore


def test_ci_and_pages_deploy_workflows_require_api_and_supabase_public_env():
    ci_workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    deploy_workflow = (REPO_ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8")

    assert "VITE_SUPABASE_URL" in ci_workflow
    assert "VITE_SUPABASE_ANON_KEY" in ci_workflow
    assert "VITE_SUPABASE_URL" in deploy_workflow
    assert "VITE_SUPABASE_ANON_KEY" in deploy_workflow
    assert "VITE_API_BASE_URL" in ci_workflow
    assert "VITE_API_BASE_URL" in deploy_workflow
    assert "vars.VITE_API_BASE_URL || secrets.VITE_API_BASE_URL" in ci_workflow
    assert "vars.VITE_API_BASE_URL || secrets.VITE_API_BASE_URL" in deploy_workflow
    assert "vars.VITE_SUPABASE_URL || secrets.VITE_SUPABASE_URL" in ci_workflow
    assert "vars.VITE_SUPABASE_URL || secrets.VITE_SUPABASE_URL" in deploy_workflow
    assert "vars.VITE_SUPABASE_ANON_KEY || secrets.VITE_SUPABASE_ANON_KEY" in ci_workflow
    assert "vars.VITE_SUPABASE_ANON_KEY || secrets.VITE_SUPABASE_ANON_KEY" in deploy_workflow
    assert "VITE_APP_RELEASE" in ci_workflow
    assert "VITE_APP_RELEASE" in deploy_workflow
    assert "GITHUB_SHA::12" in ci_workflow
    assert "GITHUB_SHA::12" in deploy_workflow
    assert "npm run verify:build-env" in ci_workflow
    assert "npm run verify:build-env" in deploy_workflow
    assert "npm run verify:bundle" in ci_workflow
    assert "npm run verify:bundle" in deploy_workflow
    assert "      - '.github/workflows/deploy-pages.yml'" in deploy_workflow


def test_e2e_backend_supplies_durable_queue_runtime_configuration():
    playwright = (REPO_ROOT / "frontend" / "playwright.config.ts").read_text(encoding="utf-8")

    for variable_name in (
        "TELEGRAM_TASKS_PROJECT",
        "TELEGRAM_TASKS_LOCATION",
        "TELEGRAM_TASKS_QUEUE",
        "TELEGRAM_WORKER_URL",
        "TELEGRAM_TASK_INVOKER_SERVICE_ACCOUNT",
    ):
        assert f"{variable_name}:" in playwright


def test_split_runtimes_require_one_shared_encryption_secret():
    cloudbuild = (REPO_ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")

    assert '"DATA_ENCRYPTION_KEY=${_SECRET_ID_DATA_ENCRYPTION_KEY}"' in cloudbuild
    assert '"--optional-secret-spec"' not in cloudbuild
    assert 'allowed={"SUPABASE_KEY","TELEGRAM_SECRET_TOKEN","RECURRING_EXPENSES_CRON_SECRET","DATA_ENCRYPTION_KEY"}' in cloudbuild
    assert 'allowed={"SUPABASE_KEY","TELEGRAM_BOT_TOKEN","DEEPSEEK_API_KEY","GROQ_API_KEY","GEMINI_API_KEY","DATA_ENCRYPTION_KEY"}' in cloudbuild


def test_manual_dependency_security_contract_avoids_automated_pr_flood():
    ci_workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    deploy_workflow = (REPO_ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8")
    package_json = json.loads((REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    dev_dependencies = package_json.get("devDependencies", {})
    overrides = package_json.get("overrides", {})

    assert not (REPO_ROOT / ".github" / "dependabot.yml").exists()
    assert "node-version: \"20.20.1\"" in ci_workflow
    assert "node-version: \"20.20.1\"" in deploy_workflow
    assert "npm audit --audit-level=low" in ci_workflow
    assert package_json["dependencies"]["react-router-dom"] == "^7.18.2"

    assert dev_dependencies["vite"] == "^8.1.0"
    assert dev_dependencies["@vitejs/plugin-react"] == "^6.0.3"
    assert dev_dependencies["vitest"] == "^4.1.9"
    assert dev_dependencies["@vitest/coverage-v8"] == "^4.1.9"
    assert dev_dependencies["postcss"] == "^8.5.26"
    assert dev_dependencies["jsdom"] == "^29.1.1"

    assert overrides["anymatch"]["picomatch"] == "^2.3.2"
    assert overrides["micromatch"]["picomatch"] == "^2.3.2"
    assert overrides["readdirp"]["picomatch"] == "^2.3.2"


def test_python_dependencies_are_reproducible_hashed_locks():
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    ci_workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime_input = (REPO_ROOT / "requirements.in").read_text(encoding="utf-8")
    dev_input = (REPO_ROOT / "requirements-dev.in").read_text(encoding="utf-8")
    runtime_lock = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    dev_lock = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

    for direct_dependency in (
        "quart",
        "hypercorn",
        "httpx",
        "supabase",
        "openai",
        "groq",
        "python-json-logger",
        "google-genai==2.18.1",
        "google-cloud-tasks",
        "cryptography",
    ):
        assert direct_dependency in runtime_input

    assert "-r requirements.in" in dev_input
    for direct_dependency in ("coverage[toml]", "pip>=26.2", "pip-audit", "pytest", "pytest-asyncio", "pytest-cov"):
        assert direct_dependency in dev_input

    for lock_content in (runtime_lock, dev_lock):
        assert "This file was autogenerated by uv" in lock_content
        assert "==+" not in lock_content
        assert ">=" not in lock_content
        assert re.search(r"^[a-z0-9][a-z0-9_.-]+==[0-9]", lock_content, re.MULTILINE)
        assert "--hash=sha256:" in lock_content

    assert "uv pip compile requirements.in --python-version 3.11 --generate-hashes --output-file requirements.txt" in makefile
    assert (
        "uv pip compile requirements-dev.in --python-version 3.11 --generate-hashes "
        "--output-file requirements-dev.txt"
    ) in makefile
    assert "pip install --no-cache-dir --require-hashes -r requirements.txt" in dockerfile
    assert "pip install --require-hashes -r requirements-dev.txt" in ci_workflow

    hashed_runtime_audit = "pip-audit --require-hashes --disable-pip -r requirements.txt"
    hashed_dev_audit = "pip-audit --require-hashes --disable-pip -r requirements-dev.txt"
    assert hashed_runtime_audit in makefile
    assert hashed_dev_audit in makefile
    assert hashed_runtime_audit in ci_workflow
    assert hashed_dev_audit in ci_workflow


def test_backend_cloud_build_contract_uses_dockerfile_image_deploy():
    cloudbuild = (REPO_ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")
    setup = (REPO_ROOT / "SETUP.md").read_text(encoding="utf-8")

    assert 'gcr.io/cloud-builders/docker' in cloudbuild
    assert 'gcr.io/cloud-builders/gcloud' in cloudbuild
    assert 'gcloud artifacts docker images scan' not in cloudbuild
    assert 'gcloud artifacts docker images list-vulnerabilities' not in cloudbuild
    assert 'id: "resolve-secret-versions"' in cloudbuild
    assert '--image' in cloudbuild
    assert 'gcr.io/k8s-skaffold/pack' not in cloudbuild
    assert '--source' not in cloudbuild
    assert 'logging: "CLOUD_LOGGING_ONLY"' in cloudbuild
    assert 'IMAGE_REF=$$(cat /workspace/image_ref.txt)' in cloudbuild
    assert '--image "$$IMAGE_REF"' in cloudbuild
    assert '${IMAGE_REF}' not in cloudbuild
    assert '--set-secrets "$$API_SECRET_ENV_VARS"' in cloudbuild
    assert '--set-secrets "$$WORKER_SECRET_ENV_VARS"' in cloudbuild
    assert "--update-secrets" not in cloudbuild
    assert ':latest' not in cloudbuild
    assert 'APP_COMMIT_SHA=${COMMIT_SHA}' in cloudbuild
    assert 'APP_RELEASE_SHA=${SHORT_SHA}' in cloudbuild
    assert '--update-labels "commit-sha=${SHORT_SHA}"' in cloudbuild
    assert '--min-instances "0"' in cloudbuild
    assert '--max-instances "1"' in cloudbuild
    assert '--concurrency "10"' in cloudbuild
    assert '--timeout "30s"' in cloudbuild
    assert 'id: "deploy-worker-cloud-run"' in cloudbuild
    assert 'id: "deploy-api-cloud-run"' in cloudbuild
    assert '--concurrency "1"' in cloudbuild
    assert '--timeout "240s"' in cloudbuild
    assert '--ingress internal' in cloudbuild
    assert '--no-allow-unauthenticated' in cloudbuild
    assert '--service-account "${_WORKER_RUNTIME_SERVICE_ACCOUNT}"' in cloudbuild
    assert '--service-account "${_API_RUNTIME_SERVICE_ACCOUNT}"' in cloudbuild
    assert 'APP_COMPONENT=telegram-worker' in cloudbuild
    assert 'APP_COMPONENT=api' in cloudbuild
    assert 'TELEGRAM_TASKS_LOCATION=${_REGION}' in cloudbuild
    assert "replace-me" not in cloudbuild
    assert cloudbuild.count('--project "${PROJECT_ID}"') >= 4
    assert '--memory "512Mi"' in cloudbuild
    assert 'id: "smoke-runtime-metadata"' in cloudbuild
    assert '/api/meta/runtime' in cloudbuild
    assert 'id: "prune-secret-versions"' in cloudbuild
    assert 'scripts/prune_secret_versions.py' in cloudbuild
    assert '--execute' in cloudbuild
    assert '--protected-version-file' in cloudbuild
    dedicated_build_account = "financemgmtbot-deploy@financemgmtbot.iam.gserviceaccount.com"
    assert f'--service-account="{dedicated_build_account}"' in setup
    assert "cloudbuild-yaml-09-04-26" in setup


def test_architecture_document_is_not_part_of_public_git_snapshot():
    result = subprocess.run(
        ["git", "ls-files", "architecture.md"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == ""


def test_backend_container_contract_is_runtime_only_and_protected_by_dockerignore():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "gcc" not in dockerfile
    assert "libpq-dev" not in dockerfile
    assert "USER financebotuser" in dockerfile
    assert ".env" in dockerignore
    assert ".env.*" in dockerignore
    assert "downloaded-logs-*" in dockerignore


def test_supabase_browser_auth_client_uses_pkce_and_callback_does_not_authorize_admin():
    supabase_browser_session = (
        REPO_ROOT / "frontend" / "src" / "features" / "auth" / "lib" / "supabaseBrowserSession.ts"
    ).read_text(encoding="utf-8")
    auth_callback = (REPO_ROOT / "frontend" / "src" / "pages" / "AuthCallback.tsx").read_text(encoding="utf-8")

    assert "flowType: 'pkce'" in supabase_browser_session
    assert "detectSessionInUrl: true" in supabase_browser_session
    assert "getAdminMe" not in auth_callback
    assert "/api/admin/me" not in auth_callback

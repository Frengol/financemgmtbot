from pathlib import Path
import json


REPO_ROOT = Path(__file__).resolve().parent


def test_frontend_public_build_restores_supabase_runtime_dependency_for_pages_auth():
    package_json = json.loads((REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    dependencies = package_json.get("dependencies", {})

    assert "@supabase/supabase-js" in dependencies
    assert (REPO_ROOT / "frontend" / "src" / "features" / "auth" / "lib" / "supabaseBrowserSession.ts").exists()
    assert not (REPO_ROOT / "frontend" / "src" / "lib" / "supabase.ts").exists()


def test_public_frontend_contract_files_require_supabase_env_again():
    files = [
        REPO_ROOT / "frontend" / ".env.example",
        REPO_ROOT / "frontend" / ".env.development.example",
        REPO_ROOT / "frontend" / ".env.production.example",
        REPO_ROOT / "frontend" / "src" / "vite-env.d.ts",
        REPO_ROOT / "README.md",
        REPO_ROOT / "architecture.md",
    ]

    for file_path in files:
        content = file_path.read_text(encoding="utf-8")
        assert "VITE_SUPABASE_URL" in content
        assert "VITE_SUPABASE_ANON_KEY" in content


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
    assert "npm run verify:build-env" in ci_workflow
    assert "npm run verify:build-env" in deploy_workflow
    assert "npm run verify:bundle" in ci_workflow
    assert "npm run verify:bundle" in deploy_workflow
    assert "      - '.github/workflows/deploy-pages.yml'" in deploy_workflow


def test_backend_cloud_build_contract_uses_dockerfile_image_deploy():
    cloudbuild = (REPO_ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")

    assert 'gcr.io/cloud-builders/docker' in cloudbuild
    assert 'gcr.io/cloud-builders/gcloud' in cloudbuild
    assert '--image' in cloudbuild
    assert 'gcr.io/k8s-skaffold/pack' not in cloudbuild
    assert '--source' not in cloudbuild
    assert 'logging: "CLOUD_LOGGING_ONLY"' in cloudbuild
    assert 'IMAGE_REF=$$(cat /workspace/image_ref.txt)' in cloudbuild
    assert '--image "$$IMAGE_REF"' in cloudbuild
    assert '${IMAGE_REF}' not in cloudbuild


def test_backend_container_contract_is_runtime_only_and_protected_by_dockerignore():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "gcc" not in dockerfile
    assert "libpq-dev" not in dockerfile
    assert "USER financebotuser" in dockerfile
    assert ".env" in dockerignore
    assert ".env.*" in dockerignore
    assert "downloaded-logs-*" in dockerignore

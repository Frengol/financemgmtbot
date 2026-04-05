from pathlib import Path
import json


REPO_ROOT = Path(__file__).resolve().parent


def test_frontend_public_build_has_no_supabase_runtime_dependency():
    package_json = json.loads((REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    dependencies = package_json.get("dependencies", {})

    assert "@supabase/supabase-js" not in dependencies
    assert not (REPO_ROOT / "frontend" / "src" / "lib" / "supabase.ts").exists()


def test_public_frontend_contract_files_no_longer_require_supabase_env():
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
        assert "VITE_SUPABASE_URL" not in content
        assert "VITE_SUPABASE_ANON_KEY" not in content


def test_ci_and_pages_deploy_workflows_only_require_backend_api_base_url():
    ci_workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    deploy_workflow = (REPO_ROOT / ".github" / "workflows" / "deploy-pages.yml").read_text(encoding="utf-8")

    assert "VITE_SUPABASE_URL" not in ci_workflow
    assert "VITE_SUPABASE_ANON_KEY" not in ci_workflow
    assert "VITE_SUPABASE_URL" not in deploy_workflow
    assert "VITE_SUPABASE_ANON_KEY" not in deploy_workflow
    assert "VITE_API_BASE_URL" in ci_workflow
    assert "VITE_API_BASE_URL" in deploy_workflow
    assert "vars.VITE_API_BASE_URL || secrets.VITE_API_BASE_URL" in ci_workflow
    assert "vars.VITE_API_BASE_URL || secrets.VITE_API_BASE_URL" in deploy_workflow
    assert "npm run verify:build-env" in ci_workflow
    assert "npm run verify:build-env" in deploy_workflow
    assert "npm run verify:bundle" in ci_workflow
    assert "npm run verify:bundle" in deploy_workflow
    assert "      - '.github/workflows/deploy-pages.yml'" in deploy_workflow

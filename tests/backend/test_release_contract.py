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


def test_ci_security_contract_scans_complete_frontend_dependency_tree():
    ci_workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "npm audit --omit=dev" not in ci_workflow
    assert "npm audit --omit=dev" not in makefile
    assert "run: npm audit" in ci_workflow
    assert "npm audit --prefix frontend" in makefile
    assert "pip-audit --require-hashes --disable-pip -r requirements.txt" in ci_workflow
    assert "pip-audit --require-hashes --disable-pip -r requirements-dev.txt" in ci_workflow
    assert "pip-audit --require-hashes --disable-pip -r requirements.txt" in makefile
    assert "pip-audit --require-hashes --disable-pip -r requirements-dev.txt" in makefile


def test_github_actions_are_pinned_to_full_commit_sha_with_version_comments():
    workflow_paths = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    action_ref = re.compile(r"uses:\s+[^@\s]+@(?P<ref>[^\s#]+)(?P<comment>\s+#\s*\S+)?")

    for workflow_path in workflow_paths:
        for match in action_ref.finditer(workflow_path.read_text(encoding="utf-8")):
            ref = match.group("ref")
            assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{workflow_path} uses mutable action ref {ref}"
            assert match.group("comment"), f"{workflow_path} action SHA must keep a human version comment"


def test_dependabot_monitors_supported_dependency_ecosystems():
    dependabot = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

    for ecosystem in ['"npm"', '"pip"', '"docker"', '"github-actions"']:
        assert f"package-ecosystem: {ecosystem}" in dependabot


def test_backend_cloud_build_contract_uses_dockerfile_image_deploy():
    cloudbuild = (REPO_ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")

    assert 'gcr.io/cloud-builders/docker' in cloudbuild
    assert 'gcr.io/cloud-builders/gcloud' in cloudbuild
    assert 'gcloud artifacts docker images scan' not in cloudbuild
    assert 'gcloud artifacts docker images list-vulnerabilities' not in cloudbuild
    assert 'id: "scan-image-vulnerabilities"' not in cloudbuild
    assert 'image_vulnerabilities' not in cloudbuild
    assert 'id: "push-image"' in cloudbuild
    assert 'id: "capture-image-digest"' in cloudbuild
    assert cloudbuild.index('id: "push-image"') < cloudbuild.index('id: "capture-image-digest"')
    assert cloudbuild.index('id: "capture-image-digest"') < cloudbuild.index('id: "deploy-cloud-run"')
    assert 'id: "resolve-secret-versions"' in cloudbuild
    assert '--image' in cloudbuild
    assert 'gcr.io/k8s-skaffold/pack' not in cloudbuild
    assert '--source' not in cloudbuild
    assert 'logging: "CLOUD_LOGGING_ONLY"' in cloudbuild
    assert 'IMAGE_REF=$$(cat /workspace/image_ref.txt)' in cloudbuild
    assert '--image "$$IMAGE_REF"' in cloudbuild
    assert '${IMAGE_REF}' not in cloudbuild
    assert '--update-secrets "$$SECRET_ENV_VARS"' in cloudbuild
    assert ':latest' not in cloudbuild
    assert 'APP_COMMIT_SHA=${COMMIT_SHA}' in cloudbuild
    assert 'APP_RELEASE_SHA=${SHORT_SHA}' in cloudbuild
    assert '--update-labels "commit-sha=${SHORT_SHA}"' in cloudbuild
    assert '--min-instances "0"' in cloudbuild
    assert '--max-instances "1"' in cloudbuild
    assert '--concurrency "10"' in cloudbuild
    assert '--timeout "30s"' in cloudbuild
    assert '--memory "512Mi"' in cloudbuild
    assert 'id: "smoke-runtime-metadata"' in cloudbuild
    assert '/api/meta/runtime' in cloudbuild
    assert 'id: "prune-secret-versions"' in cloudbuild
    assert 'scripts/prune_secret_versions.py' in cloudbuild
    assert '--execute' in cloudbuild
    assert '--protected-version-file' in cloudbuild


def test_python_requirements_are_locked_and_manifest_inputs_are_versioned():
    runtime_requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    dev_requirements = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    runtime_inputs = (REPO_ROOT / "requirements.in").read_text(encoding="utf-8")
    dev_inputs = (REPO_ROOT / "requirements-dev.in").read_text(encoding="utf-8")

    assert "quart>=" in runtime_inputs
    assert "pip-audit>=" in dev_inputs
    assert "-r requirements.in" in dev_inputs

    for content in (runtime_requirements, dev_requirements):
        requirement_lines = [
            line.strip()
            for line in content.splitlines()
            if line.strip()
            and not line.strip().startswith("#")
            and not line.strip().startswith("-r ")
            and not line.strip().startswith("--hash=")
        ]
        assert requirement_lines
        assert all("==" in line for line in requirement_lines)
        assert all(">=" not in line for line in requirement_lines)


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

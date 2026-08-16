from datetime import datetime, timedelta, timezone

from scripts import prune_secret_versions


def _version(secret_id, version_id, *, state="ENABLED", age_days=30):
    return prune_secret_versions.SecretVersion(
        secret_id=secret_id,
        version_id=str(version_id),
        state=state,
        create_time=datetime.now(timezone.utc) - timedelta(days=age_days),
    )


def test_plan_keeps_two_latest_enabled_versions_and_prunes_older_active_versions():
    versions = [
        _version("SUPABASE_KEY", 5),
        _version("SUPABASE_KEY", 4),
        _version("SUPABASE_KEY", 3),
        _version("SUPABASE_KEY", 2, state="DISABLED"),
        _version("SUPABASE_KEY", 1, state="DESTROYED"),
    ]

    plan = prune_secret_versions.plan_secret_version_prune(
        "SUPABASE_KEY",
        versions,
        retain_enabled=2,
        protected_versions=set(),
        now=datetime.now(timezone.utc),
    )

    assert [version.version_id for version in plan.kept] == ["5", "4"]
    assert [version.version_id for version in plan.destroyable] == ["3", "2"]
    assert [version.version_id for version in plan.ignored] == ["1"]


def test_plan_protects_versions_referenced_by_cloud_run_even_when_older():
    versions = [
        _version("TELEGRAM_BOT_TOKEN", 5),
        _version("TELEGRAM_BOT_TOKEN", 4),
        _version("TELEGRAM_BOT_TOKEN", 3),
    ]

    plan = prune_secret_versions.plan_secret_version_prune(
        "TELEGRAM_BOT_TOKEN",
        versions,
        retain_enabled=2,
        protected_versions={"3"},
        now=datetime.now(timezone.utc),
    )

    assert [version.version_id for version in plan.kept] == ["5", "4", "3"]
    assert plan.destroyable == []


def test_plan_keeps_recent_data_encryption_key_versions():
    now = datetime.now(timezone.utc)
    versions = [
        _version("DATA_ENCRYPTION_KEY", 4, age_days=30),
        _version("DATA_ENCRYPTION_KEY", 3, age_days=30),
        _version("DATA_ENCRYPTION_KEY", 2, age_days=3),
        _version("DATA_ENCRYPTION_KEY", 1, age_days=30),
    ]

    plan = prune_secret_versions.plan_secret_version_prune(
        "DATA_ENCRYPTION_KEY",
        versions,
        retain_enabled=2,
        protected_versions=set(),
        min_age_days=7,
        now=now,
    )

    assert [version.version_id for version in plan.kept] == ["4", "3", "2"]
    assert [version.version_id for version in plan.destroyable] == ["1"]


def test_parse_cloud_run_revisions_extracts_secret_versions_without_payloads():
    revisions = [
        {
            "spec": {
                "containers": [
                    {
                        "env": [
                            {
                                "name": "SUPABASE_KEY",
                                "valueFrom": {
                                    "secretKeyRef": {
                                        "name": "SUPABASE_KEY",
                                        "key": "7",
                                    }
                                },
                            }
                        ]
                    }
                ]
            }
        },
        {
            "template": {
                "containers": [
                    {
                        "env": [
                            {
                                "name": "GEMINI_API_KEY",
                                "valueSource": {
                                    "secretKeyRef": {
                                        "secret": "projects/project-1/secrets/GEMINI_API_KEY",
                                        "version": "3",
                                    }
                                },
                            }
                        ]
                    }
                ]
            }
        },
    ]

    protected = prune_secret_versions.extract_cloud_run_secret_refs(revisions)

    assert protected == {"SUPABASE_KEY": {"7"}, "GEMINI_API_KEY": {"3"}}


def test_cli_defaults_to_dry_run_and_requires_execute_to_destroy(monkeypatch, capsys):
    destroyed = []

    monkeypatch.setattr(
        prune_secret_versions,
        "list_secret_versions",
        lambda project_id, secret_id: [_version(secret_id, 3), _version(secret_id, 2), _version(secret_id, 1)],
    )
    monkeypatch.setattr(
        prune_secret_versions,
        "destroy_secret_version",
        lambda project_id, secret_id, version_id: destroyed.append((secret_id, version_id)),
    )
    monkeypatch.setattr(prune_secret_versions, "load_cloud_run_protected_versions", lambda *args, **kwargs: {})

    exit_code = prune_secret_versions.main(["prune", "--project", "project-1", "--secret", "SUPABASE_KEY"])

    assert exit_code == 0
    assert destroyed == []
    assert '"dry_run": true' in capsys.readouterr().out


def test_prune_collects_protected_versions_from_both_cloud_run_services(monkeypatch):
    inspected = []

    monkeypatch.setattr(
        prune_secret_versions,
        "list_secret_versions",
        lambda project_id, secret_id: [_version(secret_id, 3), _version(secret_id, 2), _version(secret_id, 1)],
    )
    monkeypatch.setattr(prune_secret_versions, "destroy_secret_version", lambda *args: None)

    def load_protected(project_id, service_name, region):
        inspected.append(service_name)
        return {"SUPABASE_KEY": {"1" if service_name == "api" else "2"}}

    monkeypatch.setattr(prune_secret_versions, "load_cloud_run_protected_versions", load_protected)

    exit_code = prune_secret_versions.main(
        [
            "prune",
            "--project",
            "project-1",
            "--secret",
            "SUPABASE_KEY",
            "--cloud-run-service",
            "api",
            "--cloud-run-service",
            "worker",
            "--cloud-run-region",
            "southamerica-east1",
        ]
    )

    assert exit_code == 0
    assert inspected == ["api", "worker"]


def test_cli_default_managed_secrets_use_real_secret_ids(monkeypatch):
    listed_secrets = []

    def fake_list(project_id, secret_id):
        listed_secrets.append(secret_id)
        return [_version(secret_id, 2), _version(secret_id, 1)]

    monkeypatch.setattr(prune_secret_versions, "list_secret_versions", fake_list)
    monkeypatch.setattr(prune_secret_versions, "load_cloud_run_protected_versions", lambda *args, **kwargs: {})

    exit_code = prune_secret_versions.main(["prune", "--project", "project-1"])

    assert exit_code == 0
    assert "recurring-expenses-cron-secret" in listed_secrets
    assert "RECURRING_EXPENSES_CRON_SECRET" not in listed_secrets


def test_resolve_latest_outputs_numeric_versions_without_secret_values(monkeypatch, tmp_path):
    monkeypatch.setattr(
        prune_secret_versions,
        "list_secret_versions",
        lambda project_id, secret_id: [
            _version(secret_id, 2),
            _version(secret_id, 10),
            _version(secret_id, 9, state="DISABLED"),
        ],
    )
    env_output = tmp_path / "secret_env.txt"
    protected_output = tmp_path / "protected.json"

    exit_code = prune_secret_versions.main(
        [
            "resolve-latest",
            "--project",
            "project-1",
            "--secret-spec",
            "SUPABASE_KEY=SUPABASE_KEY",
            "--env-output",
            str(env_output),
            "--protected-output",
            str(protected_output),
        ]
    )

    assert exit_code == 0
    assert env_output.read_text(encoding="utf-8") == "SUPABASE_KEY=SUPABASE_KEY:10"
    assert '"10"' in protected_output.read_text(encoding="utf-8")
    assert "FAKE" not in env_output.read_text(encoding="utf-8")


def test_resolve_latest_skips_missing_optional_secret(monkeypatch, tmp_path, capsys):
    def fake_list(project_id, secret_id):
        if secret_id == "DATA_ENCRYPTION_KEY":
            raise RuntimeError("not found")
        return [_version(secret_id, 1)]

    monkeypatch.setattr(prune_secret_versions, "list_secret_versions", fake_list)
    env_output = tmp_path / "secret_env.txt"
    protected_output = tmp_path / "protected.json"

    exit_code = prune_secret_versions.main(
        [
            "resolve-latest",
            "--project",
            "project-1",
            "--secret-spec",
            "SUPABASE_KEY=SUPABASE_KEY",
            "--optional-secret-spec",
            "DATA_ENCRYPTION_KEY=DATA_ENCRYPTION_KEY",
            "--env-output",
            str(env_output),
            "--protected-output",
            str(protected_output),
        ]
    )

    assert exit_code == 0
    assert env_output.read_text(encoding="utf-8") == "SUPABASE_KEY=SUPABASE_KEY:1"
    assert "DATA_ENCRYPTION_KEY" not in protected_output.read_text(encoding="utf-8")
    assert "optional_secret_version_missing" in capsys.readouterr().out

#!/usr/bin/env python3
"""Prune old Google Secret Manager versions without reading secret payloads."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


MANAGED_SECRET_IDS = (
    "SUPABASE_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_SECRET_TOKEN",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "recurring-expenses-cron-secret",
    "DATA_ENCRYPTION_KEY",
)
ACTIVE_STATES = {"ENABLED", "DISABLED"}
DEFAULT_MIN_AGE_DAYS_BY_SECRET = {"DATA_ENCRYPTION_KEY": 7}
SECRET_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class SecretVersion:
    secret_id: str
    version_id: str
    state: str
    create_time: datetime | None = None


@dataclass(frozen=True)
class SecretPrunePlan:
    secret_id: str
    kept: list[SecretVersion]
    destroyable: list[SecretVersion]
    ignored: list[SecretVersion]


def parse_timestamp(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None

    normalized = raw_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_version_id(raw_name_or_id: str) -> str:
    return str(raw_name_or_id).rstrip("/").split("/")[-1]


def parse_secret_id(raw_name_or_id: str) -> str:
    candidate = str(raw_name_or_id).rstrip("/")
    if "/secrets/" in candidate:
        return candidate.split("/secrets/", 1)[1].split("/", 1)[0]
    return candidate


def version_sort_key(version: SecretVersion):
    version_id = parse_version_id(version.version_id)
    if version_id.isdigit():
        return (1, int(version_id))
    return (0, version_id)


def sort_versions_desc(versions: list[SecretVersion]) -> list[SecretVersion]:
    return sorted(versions, key=version_sort_key, reverse=True)


def is_active_version(version: SecretVersion) -> bool:
    return version.state.upper() in ACTIVE_STATES


def is_enabled_version(version: SecretVersion) -> bool:
    return version.state.upper() == "ENABLED"


def is_recent(version: SecretVersion, *, min_age_days: int, now: datetime) -> bool:
    if min_age_days <= 0 or version.create_time is None:
        return False
    return version.create_time > now - timedelta(days=min_age_days)


def plan_secret_version_prune(
    secret_id: str,
    versions: list[SecretVersion],
    *,
    retain_enabled: int = 2,
    protected_versions: set[str] | None = None,
    min_age_days: int = 0,
    now: datetime | None = None,
) -> SecretPrunePlan:
    now = now or datetime.now(timezone.utc)
    protected_versions = {parse_version_id(version) for version in (protected_versions or set())}

    active_versions = sort_versions_desc([version for version in versions if is_active_version(version)])
    ignored_versions = sort_versions_desc([version for version in versions if not is_active_version(version)])
    enabled_versions = [version for version in active_versions if is_enabled_version(version)]

    keep_ids = {parse_version_id(version.version_id) for version in enabled_versions[:retain_enabled]}
    keep_ids.update(protected_versions)

    kept: list[SecretVersion] = []
    destroyable: list[SecretVersion] = []
    for version in active_versions:
        version_id = parse_version_id(version.version_id)
        if version_id in keep_ids or is_recent(version, min_age_days=min_age_days, now=now):
            kept.append(version)
        else:
            destroyable.append(version)

    return SecretPrunePlan(
        secret_id=secret_id,
        kept=kept,
        destroyable=destroyable,
        ignored=ignored_versions,
    )


def secret_version_from_gcloud(secret_id: str, item: dict[str, Any]) -> SecretVersion:
    return SecretVersion(
        secret_id=secret_id,
        version_id=parse_version_id(str(item.get("name") or "")),
        state=str(item.get("state") or "").upper(),
        create_time=parse_timestamp(item.get("createTime")),
    )


def run_json_command(command: list[str]) -> Any:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    output = result.stdout.strip()
    return json.loads(output) if output else []


def project_args(project_id: str | None) -> list[str]:
    return ["--project", project_id] if project_id else []


def list_secret_versions(project_id: str | None, secret_id: str) -> list[SecretVersion]:
    command = [
        "gcloud",
        "secrets",
        "versions",
        "list",
        secret_id,
        *project_args(project_id),
        "--format=json",
    ]
    return [secret_version_from_gcloud(secret_id, item) for item in run_json_command(command)]


def destroy_secret_version(project_id: str | None, secret_id: str, version_id: str) -> None:
    subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "destroy",
            version_id,
            "--secret",
            secret_id,
            *project_args(project_id),
            "--quiet",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def extract_cloud_run_secret_refs(value: Any) -> dict[str, set[str]]:
    protected: dict[str, set[str]] = {}

    def add_ref(secret_id: Any, version_id: Any) -> None:
        if not secret_id or not version_id:
            return
        secret = parse_secret_id(str(secret_id))
        version = parse_version_id(str(version_id))
        if version == "latest":
            return
        protected.setdefault(secret, set()).add(version)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            secret_ref = node.get("secretKeyRef")
            if isinstance(secret_ref, dict):
                add_ref(
                    secret_ref.get("name") or secret_ref.get("secret"),
                    secret_ref.get("key") or secret_ref.get("version"),
                )

            for child in node.values():
                visit(child)
            return

        if isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return protected


def load_cloud_run_protected_versions(
    project_id: str | None,
    service_name: str | None,
    region: str | None,
) -> dict[str, set[str]]:
    if not service_name or not region:
        return {}

    command = [
        "gcloud",
        "run",
        "revisions",
        "list",
        "--service",
        service_name,
        "--region",
        region,
        *project_args(project_id),
        "--format=json",
    ]
    return extract_cloud_run_secret_refs(run_json_command(command))


def merge_protected_versions(*sources: dict[str, set[str]]) -> dict[str, set[str]]:
    merged: dict[str, set[str]] = {}
    for source in sources:
        for secret_id, versions in source.items():
            merged.setdefault(secret_id, set()).update(parse_version_id(version) for version in versions)
    return merged


def load_protected_version_file(path: str | None) -> dict[str, set[str]]:
    if not path:
        return {}

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    protected: dict[str, set[str]] = {}
    for secret_id, versions in raw.items():
        protected[str(secret_id)] = {parse_version_id(str(version)) for version in versions}
    return protected


def parse_protected_version_args(raw_values: list[str] | None) -> dict[str, set[str]]:
    protected: dict[str, set[str]] = {}
    for raw_value in raw_values or []:
        secret_id, version_id = parse_key_value(raw_value, "--protected-version")
        protected.setdefault(secret_id, set()).add(parse_version_id(version_id))
    return protected


def parse_min_age_args(raw_values: list[str] | None) -> dict[str, int]:
    min_age_days = dict(DEFAULT_MIN_AGE_DAYS_BY_SECRET)
    for raw_value in raw_values or []:
        secret_id, days = parse_key_value(raw_value, "--min-age-secret")
        min_age_days[secret_id] = int(days)
    return min_age_days


def latest_enabled_version(versions: list[SecretVersion]) -> SecretVersion:
    enabled_versions = sort_versions_desc([version for version in versions if is_enabled_version(version)])
    if not enabled_versions:
        raise RuntimeError("No enabled secret version found.")
    return enabled_versions[0]


def validate_secret_id(secret_id: str) -> str:
    candidate = secret_id.strip()
    if not candidate or not SECRET_ID_RE.fullmatch(candidate):
        raise ValueError(f"Invalid secret id: {secret_id!r}")
    return candidate


def parse_key_value(raw_value: str, option_name: str) -> tuple[str, str]:
    if "=" not in raw_value:
        raise ValueError(f"{option_name} must use KEY=VALUE format.")

    key, value = raw_value.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key or not value:
        raise ValueError(f"{option_name} must use non-empty KEY=VALUE format.")
    return key, value


def parse_secret_spec(raw_value: str) -> tuple[str, str]:
    env_name, secret_id = parse_key_value(raw_value, "--secret-spec")
    return env_name, validate_secret_id(secret_id)


def emit_event(event: str, **payload: Any) -> None:
    print(json.dumps({"event": event, **payload}, sort_keys=True))


def command_resolve_latest(args: argparse.Namespace) -> int:
    specs = [(parse_secret_spec(raw_value), False) for raw_value in args.secret_spec]
    specs.extend((parse_secret_spec(raw_value), True) for raw_value in (args.optional_secret_spec or []))
    env_specs: list[str] = []
    protected_versions: dict[str, list[str]] = {}

    for (env_name, secret_id), optional in specs:
        try:
            version = latest_enabled_version(list_secret_versions(args.project, secret_id))
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            if not optional:
                raise
            emit_event("optional_secret_version_missing", secret_id=secret_id, reason=str(exc))
            continue

        version_id = parse_version_id(version.version_id)
        env_specs.append(f"{env_name}={secret_id}:{version_id}")
        protected_versions.setdefault(secret_id, []).append(version_id)

    Path(args.env_output).write_text(",".join(env_specs), encoding="utf-8")
    Path(args.protected_output).write_text(
        json.dumps(protected_versions, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    emit_event(
        "secret_versions_resolved",
        secrets=[secret_id for (_, secret_id), _ in specs],
        versions=protected_versions,
    )
    return 0


def command_prune(args: argparse.Namespace) -> int:
    secret_ids = [validate_secret_id(secret_id) for secret_id in (args.secret or MANAGED_SECRET_IDS)]
    min_age_days_by_secret = parse_min_age_args(args.min_age_secret)
    protected_versions = merge_protected_versions(
        load_protected_version_file(args.protected_version_file),
        parse_protected_version_args(args.protected_version),
        *(
            load_cloud_run_protected_versions(args.project, service_name, args.cloud_run_region)
            for service_name in (args.cloud_run_service or [])
        ),
    )
    now = datetime.now(timezone.utc)

    for secret_id in secret_ids:
        try:
            versions = list_secret_versions(args.project, secret_id)
        except subprocess.CalledProcessError as exc:
            if not args.ignore_missing_secrets:
                raise
            emit_event("secret_prune_skipped", secret_id=secret_id, reason=str(exc))
            continue

        plan = plan_secret_version_prune(
            secret_id,
            versions,
            retain_enabled=args.retention,
            protected_versions=protected_versions.get(secret_id, set()),
            min_age_days=min_age_days_by_secret.get(secret_id, 0),
            now=now,
        )
        emit_event(
            "secret_version_prune_plan",
            dry_run=not args.execute,
            secret_id=secret_id,
            keep=[version.version_id for version in plan.kept],
            destroy=[version.version_id for version in plan.destroyable],
            ignored=[version.version_id for version in plan.ignored],
        )

        for version in plan.destroyable:
            if args.execute:
                destroy_secret_version(args.project, secret_id, version.version_id)
                emit_event("secret_version_destroyed", secret_id=secret_id, version_id=version.version_id)
            else:
                emit_event("secret_version_destroy_dry_run", secret_id=secret_id, version_id=version.version_id)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely prune old Secret Manager versions.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser("resolve-latest", help="Resolve enabled latest versions for Cloud Run.")
    resolve_parser.add_argument("--project", required=True)
    resolve_parser.add_argument("--secret-spec", action="append", required=True, help="ENV_NAME=SECRET_ID")
    resolve_parser.add_argument("--optional-secret-spec", action="append", help="ENV_NAME=SECRET_ID")
    resolve_parser.add_argument("--env-output", required=True)
    resolve_parser.add_argument("--protected-output", required=True)
    resolve_parser.set_defaults(func=command_resolve_latest)

    prune_parser = subparsers.add_parser("prune", help="Destroy old active versions after planning.")
    prune_parser.add_argument("--project", required=True)
    prune_parser.add_argument("--secret", action="append", help="Explicit managed secret id. Defaults to app secrets.")
    prune_parser.add_argument("--retention", type=int, default=2)
    prune_parser.add_argument("--protected-version", action="append", help="SECRET_ID=VERSION_ID")
    prune_parser.add_argument("--protected-version-file", help="JSON map of SECRET_ID to protected version ids.")
    prune_parser.add_argument("--cloud-run-service", action="append")
    prune_parser.add_argument("--cloud-run-region")
    prune_parser.add_argument("--min-age-secret", action="append", help="SECRET_ID=DAYS")
    prune_parser.add_argument("--ignore-missing-secrets", action="store_true")
    prune_parser.add_argument("--execute", action="store_true", help="Actually destroy versions. Default is dry-run.")
    prune_parser.set_defaults(func=command_prune)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if getattr(args, "retention", 2) < 1:
            raise ValueError("--retention must be at least 1.")
        return args.func(args)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

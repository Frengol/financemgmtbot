#!/usr/bin/env bash
set -euo pipefail

postgres_image="${POSTGRES_IMAGE:-docker.io/library/postgres:15-bookworm}"
container_name="financemgmtbot-migration-test-$$"

cleanup() {
    podman rm --force "${container_name}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

podman run --detach --rm \
    --name "${container_name}" \
    --env POSTGRES_PASSWORD=test-only \
    --env POSTGRES_DB=financemgmtbot \
    "${postgres_image}" >/dev/null

for _ in $(seq 1 30); do
    if podman exec "${container_name}" pg_isready --username postgres --dbname financemgmtbot >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
podman exec "${container_name}" pg_isready --username postgres --dbname financemgmtbot >/dev/null

podman exec "${container_name}" mkdir -p /workspace/supabase/migrations /workspace/tests/sql
podman cp supabase/migrations/20260815_telegram_update_reliability.sql \
    "${container_name}:/workspace/supabase/migrations/20260815_telegram_update_reliability.sql"
podman cp supabase/migrations/20260908_telegram_ocr_fallback_recovery.sql \
    "${container_name}:/workspace/supabase/migrations/20260908_telegram_ocr_fallback_recovery.sql"
podman cp tests/sql/test_telegram_ocr_fallback_recovery.sql \
    "${container_name}:/workspace/tests/sql/test_telegram_ocr_fallback_recovery.sql"

podman exec --workdir /workspace/tests/sql "${container_name}" \
    psql --username postgres --dbname financemgmtbot --file test_telegram_ocr_fallback_recovery.sql

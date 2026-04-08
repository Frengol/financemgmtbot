#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! git -C "$repo_root" rev-parse --git-dir >/dev/null 2>&1; then
  echo "This script must be run from inside a Git working tree."
  exit 1
fi

git_dir="$(git -C "$repo_root" rev-parse --git-dir)"
hook_path="$repo_root/$git_dir/hooks/pre-push"

cat >"$hook_path" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

echo "[pre-push] Running local pre-push checks..."
make pre-push
HOOK

chmod +x "$hook_path"

echo "Installed pre-push hook at $hook_path"
echo "The hook runs: make pre-push"
echo "Use 'make pre-push-full' manually for auth, frontend, CI, build, deploy or security-sensitive changes."

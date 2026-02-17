#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

VERSION="${VERSION:-}"

if [ -z "$VERSION" ]; then
  echo "❌ VERSION is required. Usage: make release VERSION=x.y.z" >&2
  exit 1
fi

case "$VERSION" in
  [0-9]*.[0-9]*.[0-9]*) ;;
  *)
    echo "❌ VERSION must be semver-like (x.y.z). Got: $VERSION" >&2
    exit 1
    ;;
esac

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "❌ Working tree is not clean. Commit or stash changes before release." >&2
  exit 1
fi

if [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "❌ Untracked files found. Commit/stash/remove them before release." >&2
  exit 1
fi

echo "▶ Running tests before tagging..."
PYTHONPATH=. .venv/bin/pytest tests/ -q

TAG="v$VERSION"
if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "❌ Tag $TAG already exists." >&2
  exit 1
fi

git tag -a "$TAG" -m "Release $TAG"
echo "✅ Created tag $TAG"
echo "Next: git push origin $(git branch --show-current) --follow-tags"

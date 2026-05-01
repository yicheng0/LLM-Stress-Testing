#!/usr/bin/env sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$repo_root"

branch="$(git branch --show-current || true)"
if [ -n "$branch" ]; then
  git pull --ff-only origin "$branch"
else
  git pull --ff-only origin
fi

if docker compose version >/dev/null 2>&1; then
  docker compose up -d --build
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose up -d --build
else
  echo "docker compose command is not available" >&2
  exit 1
fi

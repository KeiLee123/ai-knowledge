#!/usr/bin/env bash
# Usage: bash scripts/hermes_gate3dc_isolated_chat_staging.sh --preflight
#        bash scripts/hermes_gate3dc_isolated_chat_staging.sh --run
# Does NOT register MCP or modify /opt/data. --run calls DeepSeek ONCE.
set -euo pipefail

test "$#" -eq 1
MODE="$1"
case "$MODE" in
  --preflight|--run) ;;
  *) echo "Usage: --preflight or --run" >&2; exit 2 ;;
esac

REPO="/opt/ai-knowledge-staging"
CID="hermes-rgu4flce2juuzyq6idzr49z2"
BASE="8493b8b7c45e4ba702cd22cf369c9d42cf6ad91e"

cd "$REPO"
export PYTHONDONTWRITEBYTECODE=1

test "$(git branch --show-current)" = staging
test -z "$(git status --porcelain)"
git merge-base --is-ancestor "$BASE" HEAD
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/staging)"
test "$(docker inspect -f '{{.State.Running}}' "$CID")" = true
test "$(docker inspect -f '{{.HostConfig.Privileged}}' "$CID")" = false

echo "=== HERMES GATE 3D-C: $MODE ==="
docker exec -i -e PYTHONDONTWRITEBYTECODE=1 \
  "$CID" /opt/hermes/.venv/bin/python - "$MODE" \
  < scripts/hermes_gate3dc_isolated_chat_staging.py

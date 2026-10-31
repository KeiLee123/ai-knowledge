#!/usr/bin/env bash
# No DeepSeek calls. Inspect Hermes MCP registration in a disposable profile.
set -euo pipefail

cd /opt/ai-knowledge-staging
BASE="3c734135c1d019a177f3e175544d170b4c6663e4"
CID="hermes-rgu4flce2juuzyq6idzr49z2"

test "$(git branch --show-current)" = staging
test -z "$(git status --porcelain)"
git merge-base --is-ancestor "$BASE" HEAD
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/staging)"
test "$(docker inspect -f '{{.State.Running}}' "$CID")" = true
test "$(docker inspect -f '{{.HostConfig.Privileged}}' "$CID")" = false

export PYTHONDONTWRITEBYTECODE=1
docker exec -i -e PYTHONDONTWRITEBYTECODE=1 "$CID" \
  /opt/hermes/.venv/bin/python - \
  < scripts/hermes_gate3dc_mcp_discovery_staging.py

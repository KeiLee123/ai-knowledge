#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${JASON_REPO_ROOT:-/opt/ai-knowledge-staging}"
PYTHON="${JASON_PYTHON:-$REPO_ROOT/.venv/bin/python}"
SOURCE_ID="${JASON_SOURCE_MONITOR_SOURCE_ID:-${1:-}}"
STATE_ROOT="${JASON_SOURCE_MONITOR_STATE_ROOT:-/var/lib/jason-os/source-monitor-staging}"
RUN_ROOT="${JASON_SOURCE_MONITOR_RUN_ROOT:-$STATE_ROOT/runs}"

if [ -z "$SOURCE_ID" ]; then
  echo "REFUSED: source id is required"
  exit 64
fi

case "$SOURCE_ID" in
  *[!A-Za-z0-9_.-]*)
    echo "REFUSED: unsafe source id"
    exit 64
    ;;
esac

case "$STATE_ROOT" in
  /var/lib/jason-os/source-monitor-staging|/var/lib/jason-os/source-monitor-staging/*)
    ;;
  *)
    echo "REFUSED: source monitor runner must use the Staging state root"
    exit 64
    ;;
esac

LOCK_FILE="${JASON_SOURCE_MONITOR_LOCK_FILE:-/run/lock/jason-os-source-monitor-staging-$SOURCE_ID.lock}"

command -v git >/dev/null 2>&1 || {
  echo "REFUSED: git is required"
  exit 64
}

command -v flock >/dev/null 2>&1 || {
  echo "REFUSED: flock is required"
  exit 64
}

REPO_BRANCH="$(git -C "$REPO_ROOT" branch --show-current)"
if [ "$REPO_BRANCH" != "staging" ]; then
  echo "REFUSED: scheduler checkout must be on staging branch"
  exit 64
fi

if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
  echo "REFUSED: scheduler checkout worktree must be clean"
  exit 64
fi

REPO_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"

test -x "$PYTHON" || {
  echo "REFUSED: Python runtime not executable: $PYTHON"
  exit 64
}

test -f "$REPO_ROOT/monitor_official_source_v1.py" || {
  echo "REFUSED: monitor entrypoint missing"
  exit 64
}

mkdir -p "$RUN_ROOT"
mkdir -p "$(dirname "$LOCK_FILE")"

exec 9>"$LOCK_FILE"

if ! flock -n 9; then
  echo "source_id=$SOURCE_ID"
  echo "STATUS: SOURCE_MONITOR_STAGING_V2 SKIPPED_ALREADY_RUNNING"
  exit 0
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$RUN_ROOT/$SOURCE_ID/$STAMP"
RESULT="$RUN_DIR/monitor-output.txt"

mkdir -p "$RUN_DIR"
umask 077

echo "============================================================"
echo "JASON OS SOURCE MONITOR — STAGING M9"
echo "============================================================"
echo "source_id=$SOURCE_ID"
echo "state_root=$STATE_ROOT"
echo "run_dir=$RUN_DIR"
echo "repo_branch=$REPO_BRANCH"
echo "repo_commit=$REPO_COMMIT"
echo "production_access=false"
echo "production_write=false"

"$PYTHON"   "$REPO_ROOT/monitor_official_source_v1.py"   --source "$SOURCE_ID"   --state-root "$STATE_ROOT"   --workdir "$RUN_DIR"   | tee "$RESULT"

echo
echo "STATUS: SOURCE_MONITOR_STAGING_V2 RUN_COMPLETE"

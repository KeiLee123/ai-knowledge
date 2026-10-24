#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${JASON_REPO_ROOT:-/opt/ai-knowledge-staging}"
PYTHON="${JASON_PYTHON:-$REPO_ROOT/.venv/bin/python}"
SOURCE_ID="${JASON_SOURCE_MONITOR_SOURCE_ID:-BD_PNAP_APP149}"
STATE_ROOT="${JASON_SOURCE_MONITOR_STATE_ROOT:-/var/lib/jason-os/source-monitor-staging}"
RUN_ROOT="${JASON_SOURCE_MONITOR_RUN_ROOT:-$STATE_ROOT/runs}"
LOCK_FILE="${JASON_SOURCE_MONITOR_LOCK_FILE:-/run/lock/jason-os-source-monitor-staging.lock}"

case "$STATE_ROOT" in
  /var/lib/jason-os/source-monitor-staging|/var/lib/jason-os/source-monitor-staging/*)
    ;;
  *)
    echo "REFUSED: source monitor scheduler must use the Staging state root"
    exit 64
    ;;
esac

if [ "$SOURCE_ID" != "BD_PNAP_APP149" ]; then
  echo "REFUSED: M8 MVP scheduler is locked to BD_PNAP_APP149"
  exit 64
fi

test -x "$PYTHON" || {
  echo "REFUSED: Python runtime not executable: $PYTHON"
  exit 64
}

test -f "$REPO_ROOT/monitor_official_source_v1.py" || {
  echo "REFUSED: monitor entrypoint missing"
  exit 64
}

command -v flock >/dev/null 2>&1 || {
  echo "REFUSED: flock is required"
  exit 64
}

mkdir -p "$RUN_ROOT"
mkdir -p "$(dirname "$LOCK_FILE")"

exec 9>"$LOCK_FILE"

if ! flock -n 9; then
  echo "STATUS: SOURCE_MONITOR_STAGING SKIPPED_ALREADY_RUNNING"
  exit 0
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$RUN_ROOT/$SOURCE_ID/$STAMP"
RESULT="$RUN_DIR/monitor-output.txt"

mkdir -p "$RUN_DIR"
umask 077

echo "============================================================"
echo "JASON OS SOURCE MONITOR — STAGING M8"
echo "============================================================"
echo "source_id=$SOURCE_ID"
echo "state_root=$STATE_ROOT"
echo "run_dir=$RUN_DIR"
echo "production_access=false"
echo "production_write=false"

"$PYTHON"   "$REPO_ROOT/monitor_official_source_v1.py"   --source "$SOURCE_ID"   --state-root "$STATE_ROOT"   --workdir "$RUN_DIR"   | tee "$RESULT"

echo
echo "STATUS: SOURCE_MONITOR_STAGING RUN_COMPLETE"

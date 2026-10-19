#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${JASON_REPO_ROOT:-/opt/ai-knowledge}"
WORK_DIR="${JASON_REPORT_WORKDIR:-/var/lib/jason-os/knowledge-reporting}"
PYTHON="${JASON_PYTHON:-$REPO_ROOT/.venv/bin/python}"

SNAPSHOT="$WORK_DIR/inbox/latest.json"

bash "$REPO_ROOT/ops/pull_anki_snapshot_from_drive_v1.sh"     "$SNAPSHOT"

"$PYTHON"     "$REPO_ROOT/run_knowledge_reporting_v1.py"     --snapshot "$SNAPSHOT"     --work-dir "$WORK_DIR"

bash "$REPO_ROOT/ops/publish_knowledge_reports_to_drive_v1.sh"     "$WORK_DIR/publish"

#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <publish-directory>" >&2
    exit 2
fi

SOURCE_DIR="$1"
REMOTE="${JASON_REPORT_REMOTE:-gdrive-out:Jason-OS/Knowledge-Reports}"

if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "Publish directory not found: $SOURCE_DIR" >&2
    exit 1
fi

if [[ ! -f "$SOURCE_DIR/latest.json" ]]; then
    echo "latest.json missing from publish directory" >&2
    exit 1
fi

if [[ ! -f "$SOURCE_DIR/latest.md" ]]; then
    echo "latest.md missing from publish directory" >&2
    exit 1
fi

rclone copy "$SOURCE_DIR" "$REMOTE"

echo "Published: $SOURCE_DIR"
echo "Remote:    $REMOTE"
